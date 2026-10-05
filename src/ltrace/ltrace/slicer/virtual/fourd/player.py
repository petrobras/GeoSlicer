"""The 4D player: frame navigation, playback and the preview/full-resolution split.

The controller owns no UI. It exposes the operations a scrubber needs (step, play/pause, loop, follow,
load full resolution) plus signals for a widget to follow, so the same player can be driven from the
Explorer panel, from a module, or from a test.

Scrubbing only ever paints cached preview frames — never full-resolution reads. Full resolution happens
when the user has settled on a frame and asks for it explicitly (or opts into auto-loading on settle).
"""

import logging
from typing import Optional

import numpy as np
import qt

from . import proxy
from .cache import DEFAULT_FULL_RES_CAP, CacheStats, FullResolutionCache, PreviewBuilder, PreviewCache
from .dataset import FourDDataset

DEFAULT_FPS = 8
SETTLE_INTERVAL_MS = 350
"""How long the user must stay on a frame before it counts as "settled"."""


class FourDPlayer(qt.QObject):
    frameChanged = qt.Signal(int)
    stateChanged = qt.Signal()
    cacheChanged = qt.Signal(str)
    framesAppended = qt.Signal(int)
    frameUnavailable = qt.Signal(int)
    """A frame could not be read — typically one the simulation is still writing."""

    def __init__(self, dataset: FourDDataset, node, cache: PreviewCache = None, parent=None):
        super().__init__(parent)
        self.dataset = dataset
        self.node = node
        self.cache = cache or PreviewCache(dataset)
        self.fullResolution = FullResolutionCache(DEFAULT_FULL_RES_CAP)

        self._index = proxy.frame_index(node)
        self._step = 1
        self._loop = False
        self._follow = proxy.follow(node)
        self._settled = False
        self._painting = False
        self._autoLoadFull = False
        self._frameAvailable = True

        self._playTimer = qt.QTimer(self)
        self._playTimer.setInterval(int(1000 / DEFAULT_FPS))
        self._playTimer.timeout.connect(self._onPlayTick)

        self._settleTimer = qt.QTimer(self)
        self._settleTimer.setSingleShot(True)
        self._settleTimer.setInterval(SETTLE_INTERVAL_MS)
        self._settleTimer.timeout.connect(self._onSettled)

        # Progress arrives from the builder thread; a queued timer hop moves it to the Qt thread.
        self._pendingStats: Optional[CacheStats] = None
        self._progressTimer = qt.QTimer(self)
        self._progressTimer.setInterval(300)
        self._progressTimer.timeout.connect(self._emitCacheProgress)

        self.builder = PreviewBuilder(self.cache, on_progress=self._onBuilderProgress)

    # -- state ----------------------------------------------------------------------------------------
    @property
    def frameCount(self) -> int:
        return self.dataset.frame_count

    @property
    def index(self) -> int:
        return self._index

    @property
    def step(self) -> int:
        return self._step

    @property
    def loop(self) -> bool:
        return self._loop

    @property
    def follow(self) -> bool:
        return self._follow

    @property
    def playing(self) -> bool:
        return self._playTimer.isActive()

    @property
    def settled(self) -> bool:
        return self._settled

    @property
    def resolution(self) -> str:
        return proxy.resolution(self.node)

    @property
    def frameAvailable(self) -> bool:
        """Whether the frame currently selected could actually be painted."""
        return self._frameAvailable

    @property
    def autoLoadFull(self) -> bool:
        return self._autoLoadFull

    def frameLabel(self, index: int = None) -> str:
        try:
            return self.dataset.frame(self._index if index is None else index).label
        except Exception:
            return ""

    def cacheStats(self) -> CacheStats:
        return self.cache.stats()

    # -- setters --------------------------------------------------------------------------------------
    def setStep(self, step: int) -> None:
        self._step = max(1, int(step))
        self.stateChanged.emit()

    def setLoop(self, loop: bool) -> None:
        self._loop = bool(loop)
        self.stateChanged.emit()

    def setFollow(self, follow: bool) -> None:
        self._follow = bool(follow)
        proxy.set_follow(self.node, self._follow)
        if self._follow and self.frameCount:
            self.seek(self.frameCount - 1)
        self.stateChanged.emit()

    def setAutoLoadFull(self, enabled: bool) -> None:
        self._autoLoadFull = bool(enabled)
        self.stateChanged.emit()

    def setFramesPerSecond(self, fps: float) -> None:
        self._playTimer.setInterval(int(1000 / max(0.5, float(fps))))

    def setFullResolutionCapacity(self, capacity: int) -> None:
        self.fullResolution.capacity = capacity

    # -- navigation -----------------------------------------------------------------------------------
    def start(self) -> None:
        """Show the first frame and begin filling the preview cache around it."""
        self.cache.ensure_frames(self.frameCount)
        self.seek(self._index)
        self.builder.start(priority=self._index)
        self._progressTimer.start()

    def seek(self, index: int, force: bool = False) -> bool:
        """Paint ``index`` from the preview cache. Returns whether a frame was painted."""
        if not self.frameCount:
            return False

        index = max(0, min(int(index), self.frameCount - 1))
        changed = index != self._index or force
        self._index = index

        self._settled = False
        self._settleTimer.start()
        self.builder.prioritize(index)

        painted = self._paintPreview(index)
        self._frameAvailable = painted

        if changed:
            self.frameChanged.emit(index)
        if not painted:
            self.frameUnavailable.emit(index)

        return painted

    def nextFrame(self) -> bool:
        return self.seek(self._index + self._step)

    def previousFrame(self) -> bool:
        return self.seek(self._index - self._step)

    def firstFrame(self) -> bool:
        return self.seek(0)

    def lastFrame(self) -> bool:
        return self.seek(self.frameCount - 1)

    def play(self) -> None:
        if not self.playing and self.frameCount > 1:
            self._playTimer.start()
            self.stateChanged.emit()

    def pause(self) -> None:
        if self.playing:
            self._playTimer.stop()
            self.stateChanged.emit()

    def togglePlay(self) -> None:
        self.pause() if self.playing else self.play()

    # -- resolution -----------------------------------------------------------------------------------
    def loadFullResolution(self, index: int = None) -> bool:
        """Read the settled frame at full resolution and paint it into the proxy node."""
        if not self.frameCount:
            return False

        index = self._index if index is None else index
        array = self.fullResolution.get(index)

        if array is None:
            try:
                array = self.dataset.read_frame(index, factor=1)
            except Exception as error:
                logging.warning(f"Unable to read frame {index} at full resolution: {error}")
                return False
            self.fullResolution.put(index, array)

        proxy.paint(self.node, self.dataset, array, factor=1, index=index, resolution=proxy.RESOLUTION_FULL)
        self.stateChanged.emit()
        return True

    def showPreview(self) -> bool:
        """Go back to the preview of the current frame (what eviction falls back to)."""
        return self.seek(self._index, force=True)

    # -- growth ---------------------------------------------------------------------------------------
    def refreshFrames(self) -> int:
        """Re-list the folder; with *follow* on, jump to the newest frame.

        Called when the monitor service reports that the folder changed, which is how an ongoing
        simulation shows up frame by frame.
        """
        retried = self.cache.refresh_states()
        appended = self.dataset.rescan()

        if not appended and not retried:
            return 0

        self.cache.ensure_frames(self.frameCount)
        proxy.update_frames(self.node, self.dataset)
        self.builder.start(priority=self.frameCount - 1 if self._follow else self._index)
        self._progressTimer.start()

        if appended:
            self.framesAppended.emit(appended)

        if self._follow:
            self.seek(self.frameCount - 1, force=True)
        elif retried and self._index in retried:
            self.seek(self._index, force=True)
        else:
            self.stateChanged.emit()

        return appended

    def refreshTail(self, tail: int = 2) -> int:
        """Re-check only the frames that a running simulation could still be writing.

        Called on every monitor poll: the newest frames plus the one on screen. Checking every frame of a
        159-frame sequence on a timer would stat thousands of files for nothing, since a finished frame does
        not change.
        """
        if not self.frameCount:
            return 0

        indices = {self._index}
        for offset in range(max(1, tail)):
            indices.add(max(0, self.frameCount - 1 - offset))

        retried = self.cache.refresh_states(indices=sorted(indices))
        if not retried:
            return 0

        self.builder.start(priority=self._index)
        self._progressTimer.start()

        if self._index in retried:
            self.seek(self._index, force=True)
        else:
            self.stateChanged.emit()

        return len(retried)

    def reload(self) -> int:
        """Re-check every frame and re-list the folder: the explicit "something changed on disk" action."""
        retried = self.cache.refresh_states()
        self.dataset.rescan()
        self.cache.ensure_frames(self.frameCount)
        proxy.update_frames(self.node, self.dataset)

        self.builder.start(priority=self._index)
        self._progressTimer.start()
        self.seek(self._index, force=True)
        return len(retried)

    # -- lifetime -------------------------------------------------------------------------------------
    def close(self) -> None:
        self._playTimer.stop()
        self._settleTimer.stop()
        self._progressTimer.stop()
        # Wait for the builder: it reads the dataset's files, which may be about to disappear (a closed
        # scene, a deleted folder), and a thread still reading them then has nothing to read.
        self.builder.stop(join=True)
        self.fullResolution.clear()
        self.cache.close()

    # -- internals ------------------------------------------------------------------------------------
    def _paintPreview(self, index: int) -> bool:
        if self._painting:
            return False

        self._painting = True
        try:
            array = self.cache.read(index)
            if array is None:
                # Not cached yet: read it now, at preview resolution, and keep it for next time. This is
                # bounded work (a few MB), unlike a full-resolution read.
                array = self.cache.build(index)

            if array is None:
                return False

            proxy.paint(
                self.node,
                self.dataset,
                array,
                factor=self.cache.factor,
                index=index,
                resolution=proxy.RESOLUTION_PREVIEW,
            )
            return True
        finally:
            self._painting = False

    def _onPlayTick(self) -> None:
        if self._painting:
            # Skip the tick instead of queueing work: queued frames are what made an earlier
            # implementation play out of order.
            return

        nextIndex = self._index + self._step
        if nextIndex >= self.frameCount:
            if self._loop:
                nextIndex = 0
            else:
                self.pause()
                return

        self.seek(nextIndex)

    def _onSettled(self) -> None:
        self._settled = True
        self.stateChanged.emit()

        if self._autoLoadFull and not self.playing:
            self.loadFullResolution()

    def _onBuilderProgress(self, stats: CacheStats) -> None:
        # Runs on the builder thread: only store the value, let the timer emit it.
        self._pendingStats = stats

    def _emitCacheProgress(self) -> None:
        # The builder thread cannot log (Slicer's log handler is not thread-safe); it queues instead.
        for message in self.cache.drain_messages():
            logging.info(message)

        stats = self._pendingStats
        if stats is None:
            if not self.builder.running:
                self._progressTimer.stop()
            return

        self._pendingStats = None
        self.cacheChanged.emit(str(stats))

        if stats.complete and not self.builder.running:
            self._progressTimer.stop()
