"""Node backends: how each MRML node class is created from, and filled with, a source sample.

One backend per node class, as required by the task: table, scalar volume, label map and vector volume.
Backends are stateless; they are chosen from a :class:`~ltrace.slicer.virtual.sources.base.SourceInfo`.
"""

from abc import ABC, abstractmethod
from math import ceil
from typing import Dict, Sequence, Tuple

import slicer

from ..sources.base import SourceInfo

IJK_TO_RAS_DIRECTIONS = (-1, 0, 0, 0, -1, 0, 0, 0, 1)
"""GeoSlicer's convention for imported images (X and Y flipped), as used by ``ltrace.slicer.netcdf``."""


def _triple(values, fill, length: int = 3) -> Tuple:
    values = tuple(values or ())[:length]
    return values + (fill,) * (length - len(values))


def centered_origin_zyx(shape_zyx: Sequence[int], spacing_zyx: Sequence[float]) -> Tuple[float, float, float]:
    """Placement of a source that does not record where it sits: centred on the world origin.

    Every eager import path in GeoSlicer centres the image it loads — ``Center volume`` defaults to on in
    both ``MicroCTLoader/Libs/RawLoader.py`` and ``ltrace.slicer.microct`` — so an image whose file carries
    no origin (RAW, TIFF, LBPM's per-rank HDF5) ends up centred in the scene. A deferred node built from
    the same file has to land in the same place, or it will not overlap the eagerly loaded copy of the very
    data it samples.
    """
    return tuple(-(max(1, int(shape_zyx[axis])) - 1) * float(spacing_zyx[axis]) / 2.0 for axis in range(3))


def apply_geometry(
    node,
    info: SourceInfo,
    factor: int = 1,
    origin_offset_zyx: Sequence[int] = (0, 0, 0),
    sampled_shape_zyx: Sequence[int] = None,
    window_zyx: Sequence[int] = None,
) -> None:
    """Give ``node`` the physical placement of the source window it holds.

    The window a sample covers is fixed, however coarsely it was read, so the spacing is derived from the
    window rather than from the sampling factor: ``spacing × covered voxels ÷ sampled voxels``. A sample
    and the full-resolution data then occupy *exactly* the same RAS bounds — slice views neither jump nor
    rescale when a frame is promoted — and an axis that could not be decimated (LBPM's quasi-2D domains
    are one voxel thick) keeps its real thickness instead of being inflated by the factor.
    """
    spacing_zyx = _triple(info.spacing_zyx, 1.0)
    shape_zyx = _triple(info.shape_zyx, 1)
    offset_zyx = _triple(origin_offset_zyx, 0)
    window_zyx = _triple(window_zyx, None)
    sampled_shape_zyx = _triple(sampled_shape_zyx, None)

    base_zyx = info.origin_zyx if info.origin_zyx is not None else centered_origin_zyx(shape_zyx, spacing_zyx)
    base_zyx = _triple(base_zyx, 0.0)

    spacing, origin = [], []
    for axis in range(3):
        source_spacing = float(spacing_zyx[axis])
        available = max(1, int(shape_zyx[axis]) - int(offset_zyx[axis]))
        covered = available if window_zyx[axis] is None else max(1, min(int(window_zyx[axis]), available))
        count = int(sampled_shape_zyx[axis] or ceil(covered / max(1, int(factor))))

        step = source_spacing * covered / max(1, count)
        start = base_zyx[axis] + offset_zyx[axis] * source_spacing - source_spacing / 2.0 + step / 2.0

        spacing.append(step)
        origin.append(start)

    node.SetSpacing(spacing[2], spacing[1], spacing[0])
    node.SetOrigin(-origin[2], -origin[1], origin[0])
    node.SetIJKToRASDirections(*IJK_TO_RAS_DIRECTIONS)


class VirtualNodeBackend(ABC):
    NODE_CLASS = ""

    @classmethod
    def handles(cls, info: SourceInfo) -> bool:
        return info.node_class == cls.NODE_CLASS

    @classmethod
    def create(cls, name: str, info: SourceInfo):
        node = slicer.mrmlScene.AddNewNodeByClass(cls.NODE_CLASS, name)
        if hasattr(node, "CreateDefaultDisplayNodes"):
            node.CreateDefaultDisplayNodes()
        return node

    @classmethod
    @abstractmethod
    def fill(cls, node, source, info: SourceInfo, **options) -> Dict:
        """Write a sample (or a requested window) into ``node``; return what was written.

        The returned dictionary feeds the node's virtual attributes, so it uses the keys of
        :class:`~ltrace.slicer.virtual.virtual_node.VirtualNodeSpec`: ``factor``, ``rows``, ``shape``.
        """
