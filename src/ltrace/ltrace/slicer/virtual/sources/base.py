"""Source backends: everything that knows how to read a *part* of a dataset without loading all of it.

These classes are deliberately free of ``slicer``, ``vtk`` and ``qt`` imports: they are plain readers over
files on disk, which keeps them unit-testable headlessly and reusable by the 4D dataset, the folder
scanner and the virtual node builders alike.

Two families exist, distinguished by :attr:`SourceInfo.kind`:

* volume sources implement :meth:`VirtualSource.read_window` (a strided/cropped read);
* table sources implement :meth:`VirtualSource.read_rows`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from math import ceil, prod
from pathlib import Path
from typing import Dict, Sequence, Tuple

import hashlib
import logging

KIND_VOLUME = "volume"
KIND_TABLE = "table"

CLASS_SCALAR_VOLUME = "vtkMRMLScalarVolumeNode"
CLASS_LABELMAP_VOLUME = "vtkMRMLLabelMapVolumeNode"
CLASS_VECTOR_VOLUME = "vtkMRMLVectorVolumeNode"
CLASS_TABLE = "vtkMRMLTableNode"

DEFAULT_INPLANE_TARGET = 192
"""Target in-plane size (voxels) of a sample/preview. Small enough to paint instantly, large enough to
recognize the structure of a micro-CT image."""

DEFAULT_SAMPLE_ROWS = 10
"""Rows kept by a virtual table node: enough to show the columns, units and magnitudes."""

DEFAULT_MAX_SAMPLE_VOXELS = 8_000_000
"""Upper bound for a sample, in voxels. Only bites for near-cubic volumes, where the in-plane target alone
would still leave a large Z extent."""


class SourceError(RuntimeError):
    pass


class UnsupportedSourceError(SourceError):
    pass


@dataclass(frozen=True)
class SourceInfo:
    """Everything needed to build a node for a source without reading its data."""

    kind: str
    node_class: str
    variables: Tuple[str, ...] = ()
    variable: str = None
    shape_zyx: Tuple[int, ...] = None
    dtype: str = None
    spacing_zyx: Tuple[float, ...] = None
    origin_zyx: Tuple[float, ...] = None
    """Where the first voxel sits, or ``None`` when the source does not record it.

    ``None`` is not the same as ``(0, 0, 0)``: a source that says nothing about its placement is placed
    the way GeoSlicer's importers place an image (centred), so that a deferred node and the eagerly
    loaded version of the same data overlap. See ``ltrace.slicer.virtual.nodes.base.apply_geometry``.
    """
    components: int = 1
    rows: int = None
    columns: Tuple[str, ...] = ()
    labels: Tuple[str, ...] = ()
    extra: Dict = field(default_factory=dict)

    def with_variable(self, variable: str) -> "SourceInfo":
        return replace(self, variable=variable)

    @property
    def voxel_count(self) -> int:
        return prod(self.shape_zyx) if self.shape_zyx else 0


class VirtualSource(ABC):
    """Base class for every deferred reader.

    Subclasses declare which paths they can open through :meth:`can_open` and are registered in
    ``ltrace.slicer.virtual.sources.factory``.
    """

    KIND = KIND_VOLUME
    EXTENSIONS: Tuple[str, ...] = ()

    def __init__(self, path, variable: str = None, **options):
        self.path = Path(path)
        self.variable = variable
        self.options = options
        self._info = None

    # -- discovery ------------------------------------------------------------------------------------
    @classmethod
    def can_open(cls, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in cls.EXTENSIONS

    # -- description ----------------------------------------------------------------------------------
    def describe(self) -> SourceInfo:
        if self._info is None:
            self._info = self._describe()
        return self._info

    @abstractmethod
    def _describe(self) -> SourceInfo:
        """Read only the metadata needed to fill a :class:`SourceInfo`."""

    # -- reading --------------------------------------------------------------------------------------
    def read_window(self, origin_zyx: Sequence[int] = (0, 0, 0), size_zyx: Sequence[int] = None, factor: int = 1):
        """Read a (cropped, strided) window of a volume source as a numpy array."""
        raise UnsupportedSourceError(f"{type(self).__name__} is not a volume source.")

    def read_rows(self, limit: int = None, offset: int = 0):
        """Read up to ``limit`` rows of a table source as a pandas DataFrame."""
        raise UnsupportedSourceError(f"{type(self).__name__} is not a table source.")

    def set_reference_shape(self, shape_zyx) -> None:
        """Offer the geometry the caller expects. Ignored by sources that carry their own."""
        return

    # -- change detection -----------------------------------------------------------------------------
    def paths(self) -> Sequence[Path]:
        """Files whose modification means this source changed."""
        return [self.path]

    def stamp(self) -> str:
        return path_stamp(self.paths())

    # -- lifetime -------------------------------------------------------------------------------------
    def close(self) -> None:
        self._info = None

    def __enter__(self) -> "VirtualSource":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.path.as_posix()!r}, variable={self.variable!r})"


def sample_factor(
    shape_zyx: Sequence[int],
    target: int = DEFAULT_INPLANE_TARGET,
    max_voxels: int = DEFAULT_MAX_SAMPLE_VOXELS,
) -> int:
    """Isotropic sampling factor bringing a volume down to a previewable size.

    Driven by the largest in-plane axis (Y/X) so slice views stay legible, then raised further only if the
    result would still exceed ``max_voxels`` (the near-cubic case).
    """
    if not shape_zyx:
        return 1

    shape = [max(1, int(size)) for size in shape_zyx]
    inplane = max(shape[1:]) if len(shape) > 1 else shape[0]
    factor = max(1, ceil(inplane / max(1, target)))

    if max_voxels:
        while factor < max(shape) and prod(ceil(size / factor) for size in shape) > max_voxels:
            factor += 1

    return factor


def sampled_shape(shape_zyx: Sequence[int], factor: int) -> Tuple[int, ...]:
    return tuple(max(1, ceil(size / factor)) for size in shape_zyx)


def window_slices(shape_zyx, origin_zyx=(0, 0, 0), size_zyx=None, factor: int = 1) -> Tuple[slice, ...]:
    """Clamped ``slice`` tuple for a crop + stride read, in ZYX order."""
    factor = max(1, int(factor))
    slices = []
    for axis, extent in enumerate(shape_zyx):
        start = max(0, int(origin_zyx[axis]) if axis < len(origin_zyx) else 0)
        length = extent - start if size_zyx is None or size_zyx[axis] is None else int(size_zyx[axis])
        stop = min(extent, start + max(1, length))
        slices.append(slice(start, stop, factor))
    return tuple(slices)


def path_stamp(paths: Sequence[Path]) -> str:
    """Cheap digest of a file set, used to decide whether a sample must be re-read.

    Uses size and modification time only: hashing content would defeat the purpose of deferred loading.
    """
    digest = hashlib.blake2b(digest_size=12)
    for path in sorted(Path(item) for item in paths):
        try:
            stat = path.stat()
            digest.update(f"{path.as_posix()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8"))
        except OSError as error:
            logging.debug(f"Unable to stat {path} while stamping a virtual source: {error}")
            digest.update(f"{path.as_posix()}|missing".encode("utf-8"))
    return digest.hexdigest()
