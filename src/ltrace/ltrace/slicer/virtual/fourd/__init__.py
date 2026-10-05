"""4D datasets: time sequences played from a downsampled preview cache.

* :mod:`ltrace.slicer.virtual.fourd.dataset` — the frames of a sequence and how to read them;
* :mod:`ltrace.slicer.virtual.fourd.cache` — the on-disk preview cache and the full-resolution LRU;
* :mod:`ltrace.slicer.virtual.fourd.proxy` — the single node the sequence is seen through;
* :mod:`ltrace.slicer.virtual.fourd.player` — navigation, playback and the preview/full-resolution split;
* :mod:`ltrace.slicer.virtual.fourd.manager` — proxy node <-> player registry, and folder monitoring.
"""

from .cache import (
    DEFAULT_FULL_RES_CAP,
    DEFAULT_PREVIEW_TARGET,
    CacheStats,
    FullResolutionCache,
    PreviewBuilder,
    PreviewCache,
    cache_root,
    purge_expired,
)
from .dataset import Frame, FourDDataset, conform_shape
from .manager import FourDManager, get_manager
from .player import DEFAULT_FPS, SETTLE_INTERVAL_MS, FourDPlayer
from .proxy import RESOLUTION_FULL, RESOLUTION_PREVIEW, is_proxy
