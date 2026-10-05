"""Caches that make 4D playback smooth: a downsampled preview on disk, a tiny full-resolution LRU in RAM.

This is the central performance decision of the feature. Streaming a full-resolution frame on every scrub
step was tried in an earlier iteration and rejected: reads outran the user's input and playback came out
slow and out of order. Instead:

* every frame is downsampled once into a **memory-mapped ``.npy`` file on disk** (~192 voxels in-plane),
  built in the background, frame by frame, starting from where the user is looking. Scrubbing then costs
  one small read regardless of how big the dataset is, and RAM stays flat;
* the **full resolution** of a frame is read only when the user settles on it and asks for it, and at most
  a couple of those are kept in memory (default 2 — enough to compare a frame with its neighbour).

The preview store is keyed by the dataset's identity and validated against its shape/dtype on reopen, so
reopening a project — or restarting the application — reuses the work instead of rebuilding it.

Nothing in this module logs from the builder thread: Slicer routes Python logging into its own Qt log
handler, and writing to it off the main thread crashes the application. Messages produced while building
are queued and drained by the main thread instead (:meth:`PreviewCache.drain_messages`).

One file per frame, rather than one array holding all of them: the builder thread and the Qt thread then
never touch the same file, growing the store while a simulation runs is just another file, and writes are
made atomic with a temporary file plus a rename. (Zarr was tried first and abandoned: its synchronous
facade drives an internal event loop, and exercising it from a worker thread and the Qt thread at once
crashed the application.)
"""

import json
import logging
import os
import shutil
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, List, Optional, Sequence

import numpy as np

DEFAULT_PREVIEW_TARGET = 192
"""Target in-plane size of a preview frame."""

DEFAULT_FULL_RES_CAP = 2
"""Full-resolution frames kept in memory at once."""

CACHE_EXPIRATION_DAYS = 14

STATE_MISSING = 0
STATE_FILLED = 1
STATE_FAILED = 2


def cache_root() -> Path:
    """Directory holding the preview stores.

    A dedicated root rather than :class:`ltrace.slicer.cache.cache_files.CacheFiles`: that helper expires
    entries with ``Path.unlink``, which fails on the *directories* a store is made of.
    """
    try:
        import slicer

        base = Path(slicer.app.cachePath)
    except Exception:  # pragma: no cover - outside the application
        import tempfile

        base = Path(tempfile.gettempdir())

    root = base / "geoslicer-4d-preview"
    root.mkdir(parents=True, exist_ok=True)
    return root


def purge_expired(days: int = CACHE_EXPIRATION_DAYS, root: Path = None) -> int:
    """Delete preview stores untouched for ``days``. Returns how many were removed."""
    root = root or cache_root()
    cutoff = time.time() - days * 86400
    removed = 0

    for store in root.glob("*.preview"):
        try:
            if store.stat().st_mtime < cutoff:
                shutil.rmtree(store, ignore_errors=True)
                removed += 1
        except OSError as error:
            logging.debug(f"Unable to expire the preview cache {store}: {error}")

    return removed


BUILDER_THREAD_NAME = "FourDPreviewBuilder"


class _WorkerLogGuard:
    """Drops log records emitted from the preview-builder thread.

    Slicer installs its own logging handler that forwards records to the GUI. A record emitted from a worker
    thread is delivered to that handler and takes the application down shortly afterwards — reproduced with
    a bare worker thread that only calls ``logging.warning``.

    The builder itself never logs (it queues through :meth:`PreviewCache.drain_messages`), but the libraries
    it calls into — tifffile, h5py, xarray, this package's own source backends — do. Filtering by thread name
    at the handler level is what makes calling them from a thread safe at all.
    """

    _guarded_handlers = set()

    @staticmethod
    def _allow(record) -> bool:
        return not str(getattr(record, "threadName", "")).startswith(BUILDER_THREAD_NAME)

    @classmethod
    def install(cls) -> None:
        for handler in list(logging.getLogger().handlers):
            if id(handler) in cls._guarded_handlers:
                continue
            handler.addFilter(cls._allow)
            cls._guarded_handlers.add(id(handler))


@dataclass
class CacheStats:
    filled: int
    failed: int
    total: int

    @property
    def pending(self) -> int:
        return max(0, self.total - self.filled - self.failed)

    @property
    def complete(self) -> bool:
        return self.pending == 0

    def __str__(self) -> str:
        return f"{self.filled}/{self.total} frames cached" + (f", {self.failed} unreadable" if self.failed else "")


class PreviewCache:
    """Downsampled frames of a :class:`~ltrace.slicer.virtual.fourd.dataset.FourDDataset`, on disk.

    Layout of a store::

        <key>.preview/meta.json          descriptor + per-frame state and modification stamp
        <key>.preview/frame_000000.npy   one memory-mappable file per cached frame
    """

    META_NAME = "meta.json"

    def __init__(self, dataset, factor: int = None, target: int = DEFAULT_PREVIEW_TARGET, root: Path = None):
        self.dataset = dataset
        self.target = target
        self.factor = int(factor or dataset.preview_factor(target))
        self.frame_shape = tuple(int(size) for size in dataset.sampled_shape(self.factor))
        self.dtype = np.dtype(dataset.describe().dtype)

        name = f"{dataset.stable_key()}-{dataset.variable or 'default'}-f{self.factor}.preview"
        self.path = (root or cache_root()) / name
        self.path.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._messages: Deque[str] = deque(maxlen=64)
        self._meta = self._load_meta()
        self._validate_or_reset()

    # -- diagnostics ----------------------------------------------------------------------------------
    def _report(self, message: str) -> None:
        """Queue a message instead of logging it: this may run on the builder thread."""
        self._messages.append(message)

    def drain_messages(self) -> List[str]:
        """Take the queued messages. Call from the main thread, which is the only safe place to log."""
        messages = []
        while True:
            try:
                messages.append(self._messages.popleft())
            except IndexError:
                break
        return messages

    # -- store ----------------------------------------------------------------------------------------
    @property
    def descriptor(self) -> dict:
        return {
            "uri": self.dataset.uri,
            "factor": self.factor,
            "frame_shape": list(self.frame_shape),
            "dtype": str(self.dtype),
        }

    def frame_path(self, index: int) -> Path:
        return self.path / f"frame_{int(index):06d}.npy"

    def _meta_path(self) -> Path:
        return self.path / self.META_NAME

    def _load_meta(self) -> dict:
        try:
            return json.loads(self._meta_path().read_text())
        except (OSError, ValueError):
            return {"descriptor": None, "frames": {}}

    def _save_meta(self) -> None:
        """Rewrite ``meta.json`` atomically: a torn file would invalidate a whole cache."""
        temporary = self._meta_path().with_suffix(".json.tmp")
        try:
            temporary.write_text(json.dumps(self._meta))
            temporary.replace(self._meta_path())
        except OSError as error:
            self._report(f"Unable to update the preview cache metadata: {error}")

    def _validate_or_reset(self) -> None:
        """Reuse an existing store only when it describes the same frames; otherwise start over."""
        if self._meta.get("descriptor") == self.descriptor:
            return

        if self._meta.get("descriptor") is not None:
            logging.info(f"Preview cache {self.path.name} describes different frames; rebuilding it.")

        for stale in self.path.glob("frame_*.npy"):
            stale.unlink(missing_ok=True)

        self._meta = {"descriptor": self.descriptor, "frames": {}}
        self._save_meta()

    def ensure_frames(self, frame_count: int) -> None:
        """Kept for symmetry with growing datasets: nothing is preallocated, so there is nothing to do."""
        return

    @property
    def frame_count(self) -> int:
        return self.dataset.frame_count

    # -- frames ---------------------------------------------------------------------------------------
    def _entry(self, index: int) -> dict:
        return self._meta.get("frames", {}).get(str(int(index)), {})

    def state(self, index: int) -> int:
        return int(self._entry(index).get("state", STATE_MISSING))

    def is_filled(self, index: int) -> bool:
        return self.state(index) == STATE_FILLED and self.frame_path(index).exists()

    def read(self, index: int) -> Optional[np.ndarray]:
        """The cached preview of ``index``, or ``None`` when it is not there (yet)."""
        if not self.is_filled(index):
            return None

        try:
            return np.array(np.load(self.frame_path(index).as_posix(), mmap_mode="r"))
        except (OSError, ValueError) as error:
            self._report(f"Discarding an unreadable cached frame {index}: {error}")
            self.reset(index)
            return None

    def write(self, index: int, array: np.ndarray) -> None:
        target = self.frame_path(index)
        temporary = target.with_name(target.name + ".tmp")

        # Written through a file object on purpose: numpy appends ".npy" to a *path* that lacks it, which
        # would leave the temporary file under a different name than the one being renamed.
        with open(temporary, "wb") as handle:
            np.save(handle, array.astype(self.dtype, copy=False))
        temporary.replace(target)

        self._record(index, STATE_FILLED)

    def mark_failed(self, index: int) -> None:
        """Remember that a frame could not be read, so the builder does not retry it in a loop.

        The frame's modification stamp is recorded alongside, which is what lets :meth:`refresh_states`
        retry it later: the usual reason a frame fails is that the simulation was still writing it.
        """
        self._record(index, STATE_FAILED)

    def reset(self, index: int) -> None:
        with self._lock:
            self._meta.setdefault("frames", {}).pop(str(int(index)), None)
            self._save_meta()

    def _record(self, index: int, state: int) -> None:
        with self._lock:
            self._meta.setdefault("frames", {})[str(int(index))] = {
                "state": int(state),
                "stamp": self._frame_stamp(index),
            }
            self._save_meta()

    def _frame_stamp(self, index: int) -> int:
        """Change stamp of a frame's source.

        A frame is often a *directory* (an LBPM ``vis`` folder, a stack of planes), and rewriting the files
        inside one does not change the directory's own modification time. So the newest modification time
        among the directory and its direct entries is used — otherwise a frame rewritten in place would
        never be re-read.
        """
        try:
            frame_path = self.dataset.frame(index).path
            stamp = frame_path.stat().st_mtime_ns

            if frame_path.is_dir():
                with os.scandir(frame_path) as entries:
                    for entry in entries:
                        try:
                            stamp = max(stamp, entry.stat(follow_symlinks=False).st_mtime_ns)
                        except OSError:
                            continue

            return int(stamp)
        except Exception:
            return 0

    def refresh_states(self, indices: Sequence[int] = None) -> List[int]:
        """Forget the frames whose source changed since it was read. Returns the indices reset.

        Frames of a running simulation are written incrementally: one that failed, or that was cached while
        incomplete, has to be read again once it changes on disk. With ``indices`` only those frames are
        checked, which is what the per-poll tail check uses to stay cheap on large sequences.
        """
        reset = []
        with self._lock:
            frames = self._meta.setdefault("frames", {})
            candidates = list(frames) if indices is None else [str(int(index)) for index in indices]

            for key in candidates:
                entry = frames.get(key)
                if entry is None:
                    continue

                index = int(key)
                if index >= self.dataset.frame_count:
                    continue

                if int(entry.get("stamp", 0)) != self._frame_stamp(index):
                    frames.pop(key, None)
                    reset.append(index)

            if reset:
                self._save_meta()

        return reset

    def build(self, index: int) -> Optional[np.ndarray]:
        """Read a frame from the dataset, store it and return it.

        Never raises: a frame that cannot be read (still being written, truncated, deleted underneath) is
        marked failed so playback continues, and the reason is queued for the main thread to log.
        """
        try:
            array = self.dataset.read_frame(index, factor=self.factor)
        except Exception as error:
            self._report(f"Frame {index} of {self.dataset.root.name} could not be read: {error}")
            self.mark_failed(index)
            return None

        try:
            self.write(index, array)
        except OSError as error:
            self._report(f"Frame {index} of {self.dataset.root.name} could not be cached: {error}")

        return array

    def get_or_build(self, index: int) -> Optional[np.ndarray]:
        cached = self.read(index)
        return cached if cached is not None else self.build(index)

    def stats(self) -> CacheStats:
        total = self.dataset.frame_count
        filled = failed = 0
        for key, entry in self._meta.get("frames", {}).items():
            if int(key) >= total:
                continue
            state = int(entry.get("state", STATE_MISSING))
            filled += state == STATE_FILLED
            failed += state == STATE_FAILED
        return CacheStats(filled=filled, failed=failed, total=total)

    def missing(self) -> List[int]:
        frames = self._meta.get("frames", {})
        return [index for index in range(self.dataset.frame_count) if str(index) not in frames]

    def close(self) -> None:
        return

    def delete(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


class PreviewBuilder:
    """Fills a :class:`PreviewCache` in a background thread, nearest frames first.

    Runs off the Qt thread so the application stays responsive while a long dataset is prepared; only Zarr
    is written from the thread, and the player reads the store back on the main thread.
    """

    def __init__(self, cache: PreviewCache, on_progress: Callable[[CacheStats], None] = None):
        self.cache = cache
        self.on_progress = on_progress
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._priority = 0
        self._queue_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def prioritize(self, index: int) -> None:
        """Fill frames near ``index`` first: the user's attention is the best prefetch hint available."""
        with self._queue_lock:
            self._priority = int(index)

    def start(self, priority: int = 0) -> None:
        if self.running:
            self.prioritize(priority)
            return

        _WorkerLogGuard.install()

        self._stop.clear()
        self.prioritize(priority)
        self._thread = threading.Thread(target=self._run, name=BUILDER_THREAD_NAME, daemon=True)
        self._thread.start()

    def stop(self, join: bool = False, timeout: float = 5.0) -> None:
        self._stop.set()
        if join and self._thread is not None:
            self._thread.join(timeout)

    def wait(self, timeout: float = 60.0) -> bool:
        """Block until the build finishes (or ``timeout`` elapses). Returns whether it finished.

        Used where the whole preview is needed before continuing — an export, a test — as opposed to
        interactive use, where frames simply appear as they are built.
        """
        if self._thread is None:
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _next_index(self) -> Optional[int]:
        missing = self.cache.missing()
        if not missing:
            return None
        with self._queue_lock:
            priority = self._priority
        return min(missing, key=lambda index: (abs(index - priority), index))

    def _run(self) -> None:
        while not self._stop.is_set():
            index = self._next_index()
            if index is None:
                break

            self.cache.build(index)

            if self.on_progress is not None:
                try:
                    self.on_progress(self.cache.stats())
                except Exception:
                    # Deliberately silent: this runs on the builder thread, where logging is unsafe.
                    pass

        if self.on_progress is not None and not self._stop.is_set():
            try:
                self.on_progress(self.cache.stats())
            except Exception:
                pass


class FullResolutionCache:
    """Bounded LRU of full-resolution frames. Evicted frames fall back to their preview."""

    def __init__(self, capacity: int = DEFAULT_FULL_RES_CAP):
        self._entries: "OrderedDict[int, np.ndarray]" = OrderedDict()
        self._capacity = max(1, int(capacity))

    @property
    def capacity(self) -> int:
        return self._capacity

    @capacity.setter
    def capacity(self, value: int) -> None:
        self._capacity = max(1, int(value))
        self._evict()

    def __contains__(self, index: int) -> bool:
        return index in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def indices(self) -> Sequence[int]:
        return list(self._entries)

    def get(self, index: int) -> Optional[np.ndarray]:
        array = self._entries.get(index)
        if array is not None:
            self._entries.move_to_end(index)
        return array

    def put(self, index: int, array: np.ndarray) -> None:
        self._entries[index] = array
        self._entries.move_to_end(index)
        self._evict()

    def clear(self) -> None:
        self._entries.clear()

    def _evict(self) -> None:
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
