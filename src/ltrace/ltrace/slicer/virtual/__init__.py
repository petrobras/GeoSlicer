"""Deferred data for GeoSlicer: virtual nodes, monitored folders and 4D datasets.

* :mod:`ltrace.slicer.virtual.virtual_node` — nodes holding a sample of data that stays on disk;
* :mod:`ltrace.slicer.virtual.folder` — folders listed (and kept in sync) without being loaded;
* :mod:`ltrace.slicer.virtual.monitor` — the single change-detection service both features share;
* :mod:`ltrace.slicer.virtual.fourd` — time sequences played from a downsampled preview cache.
"""

from . import attributes
from .sources.base import (
    DEFAULT_INPLANE_TARGET,
    DEFAULT_SAMPLE_ROWS,
    KIND_TABLE,
    KIND_VOLUME,
    SourceError,
    SourceInfo,
    UnsupportedSourceError,
    sample_factor,
)
from .sources.factory import open_source
from .uri import VirtualURI, file_uri, fourd_uri
from .virtual_node import (
    VirtualNodeSpec,
    create,
    describe,
    is_stale,
    is_virtual_node,
    load_full,
    mark_stale,
    open_node_source,
    promote,
    refresh,
    resolve,
    spec,
)
