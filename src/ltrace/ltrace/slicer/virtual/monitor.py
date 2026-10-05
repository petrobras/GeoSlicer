"""One change-detection service for every deferred-data feature.

Virtual folders and 4D proxies both need to know "did this folder change?", and they differ only in what
they do about it — the task's own closing observation. So detection lives here, once:

* :class:`qt.QFileSystemWatcher` reports local changes immediately;
* a timer poll (default 5 s) covers what the watcher cannot see. That is not belt-and-braces: LBPM writes
  its output to NFS/CIFS shares, where watcher notifications are unreliable or absent, and a running
  simulation is precisely the case this service exists for;
* both paths are debounced, because a simulation writing one frame produces a burst of file events.

A folder is watched while at least one subscriber (a virtual folder, a 4D player) holds a token on it.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Set

import hashlib
import qt
import slicer

DEFAULT_POLL_INTERVAL_MS = 5000
DEBOUNCE_INTERVAL_MS = 400


def folder_signature(root: Path, include_hidden: bool = False) -> str:
    """Digest of a folder's direct listing: names, sizes and modification times.

    Only the top level is stat-ed. A file written inside a sub-folder bumps that sub-folder's own
    modification time, so new simulation frames are still detected without walking thousands of files on
    every poll.
    """
    digest = hashlib.blake2b(digest_size=12)
    try:
        with os.scandir(root) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                if not include_hidden and entry.name.startswith("."):
                    continue
                try:
                    stat = entry.stat(follow_symlinks=False)
                    size = 0 if entry.is_dir(follow_symlinks=False) else stat.st_size
                    digest.update(f"{entry.name}|{size}|{stat.st_mtime_ns}".encode("utf-8"))
                except OSError:
                    digest.update(f"{entry.name}|unreadable".encode("utf-8"))
    except OSError as error:
        logging.debug(f"Unable to scan {root}: {error}")
        return "missing"

    return digest.hexdigest()


@dataclass
class MonitorEntry:
    root: Path
    signature: str = ""
    subscribers: Set[str] = field(default_factory=set)
    missing: bool = False


class FolderMonitorService(qt.QObject):
    """Singleton. Use :meth:`instance`."""

    folderChanged = qt.Signal(str)
    """Emitted with the folder's posix path whenever its listing changed."""

    folderMissing = qt.Signal(str)
    """Emitted when a watched folder disappears (unmounted share, deleted directory)."""

    folderPolled = qt.Signal(str)
    """Emitted on every poll of a watched folder, changed or not.

    The listing signature only sees entries appearing, disappearing or changing size — it cannot see a file
    being *overwritten* inside a sub-folder, because that does not change the sub-folder's modification
    time. Consumers that care (the 4D player, checking whether the frame it shows was rewritten) use this
    to run their own, narrower check."""

    __instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: Dict[str, MonitorEntry] = {}
        self._watcher = qt.QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._onDirectoryChanged)

        self._pollTimer = qt.QTimer(self)
        self._pollTimer.setInterval(DEFAULT_POLL_INTERVAL_MS)
        self._pollTimer.timeout.connect(self.checkAll)

        # Bursts of file events (a simulation writing a frame) collapse into one check per folder.
        self._pending: Set[str] = set()
        self._debounceTimer = qt.QTimer(self)
        self._debounceTimer.setSingleShot(True)
        self._debounceTimer.setInterval(DEBOUNCE_INTERVAL_MS)
        self._debounceTimer.timeout.connect(self._flushPending)

        self._sceneCloseObserver = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndCloseEvent, lambda *args: self.clear()
        )

    @classmethod
    def instance(cls) -> "FolderMonitorService":
        if cls.__instance is None:
            cls.__instance = cls()
        return cls.__instance

    # -- subscriptions --------------------------------------------------------------------------------
    def watch(self, root, token: str) -> None:
        """Start watching ``root`` on behalf of ``token`` (a node id, a folder key, ...)."""
        root = Path(root)
        key = root.as_posix()

        entry = self._entries.get(key)
        if entry is None:
            entry = MonitorEntry(root=root, signature=folder_signature(root))
            self._entries[key] = entry
            if root.is_dir():
                self._watcher.addPath(key)
            else:
                entry.missing = True

        entry.subscribers.add(token)

        if not self._pollTimer.isActive():
            self._pollTimer.start()

    def unwatch(self, root, token: str = None) -> None:
        """Drop ``token``'s interest in ``root``; stop watching when nobody is left."""
        key = Path(root).as_posix()
        entry = self._entries.get(key)
        if entry is None:
            return

        if token is None:
            entry.subscribers.clear()
        else:
            entry.subscribers.discard(token)

        if not entry.subscribers:
            self._watcher.removePath(key)
            self._entries.pop(key, None)

        if not self._entries and self._pollTimer.isActive():
            self._pollTimer.stop()

    def clear(self) -> None:
        for key in list(self._entries):
            self._watcher.removePath(key)
        self._entries.clear()
        self._pending.clear()
        self._pollTimer.stop()

    def roots(self) -> List[Path]:
        return [entry.root for entry in self._entries.values()]

    def isWatched(self, root) -> bool:
        return Path(root).as_posix() in self._entries

    def subscribers(self, root) -> Set[str]:
        entry = self._entries.get(Path(root).as_posix())
        return set(entry.subscribers) if entry else set()

    def setPollInterval(self, intervalMs: int) -> None:
        self._pollTimer.setInterval(max(500, int(intervalMs)))

    # -- checking -------------------------------------------------------------------------------------
    def checkAll(self) -> None:
        for key in list(self._entries):
            self.check(key)
            self.folderPolled.emit(key)

    def check(self, root, force: bool = False) -> bool:
        """Re-read the folder signature; emit and return whether it changed."""
        key = Path(root).as_posix()
        entry = self._entries.get(key)
        if entry is None:
            return False

        signature = folder_signature(entry.root)

        if signature == "missing":
            if not entry.missing:
                entry.missing = True
                entry.signature = signature
                self.folderMissing.emit(key)
            return False

        if entry.missing:
            # A share came back: re-register the path, the watcher lost it while it was gone.
            entry.missing = False
            self._watcher.addPath(key)

        if not force and signature == entry.signature:
            return False

        entry.signature = signature
        self.folderChanged.emit(key)
        return True

    # -- internals ------------------------------------------------------------------------------------
    def _onDirectoryChanged(self, path: str) -> None:
        self._pending.add(Path(path).as_posix())
        self._debounceTimer.start()

    def _flushPending(self) -> None:
        pending, self._pending = self._pending, set()
        for key in pending:
            self.check(key)


def instance() -> FolderMonitorService:
    return FolderMonitorService.instance()
