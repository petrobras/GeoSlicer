"""Volume backends: scalar, label map and vector volumes filled from a strided source read."""

import logging
from typing import Dict, Sequence

import numpy as np
import slicer

from ..sources.base import (
    CLASS_LABELMAP_VOLUME,
    CLASS_SCALAR_VOLUME,
    CLASS_VECTOR_VOLUME,
    SourceInfo,
    sample_factor,
)
from .base import VirtualNodeBackend, apply_geometry


class VolumeBackend(VirtualNodeBackend):
    """Shared behaviour for the three volume node classes."""

    @classmethod
    def fill(
        cls,
        node,
        source,
        info: SourceInfo,
        factor: int = None,
        inplane_target: int = None,
        origin_zyx: Sequence[int] = (0, 0, 0),
        size_zyx: Sequence[int] = None,
        **options,
    ) -> Dict:
        if factor is None:
            factor = sample_factor(info.shape_zyx, **({"target": inplane_target} if inplane_target else {}))

        array = source.read_window(origin_zyx=origin_zyx, size_zyx=size_zyx, factor=factor)
        cls.write_array(node, array, info, factor=factor, origin_zyx=origin_zyx, size_zyx=size_zyx)
        return {"factor": int(factor), "shape": tuple(int(size) for size in array.shape[:3])}

    @classmethod
    def write_array(
        cls,
        node,
        array: np.ndarray,
        info: SourceInfo,
        factor: int = 1,
        origin_zyx=(0, 0, 0),
        size_zyx: Sequence[int] = None,
    ) -> None:
        slicer.util.updateVolumeFromArray(node, np.ascontiguousarray(array))
        # The array itself says how many voxels the window was sampled into, which is what places it: a
        # ragged or clamped read must not be positioned as if it had the shape the factor implies.
        apply_geometry(
            node,
            info,
            factor=factor,
            origin_offset_zyx=origin_zyx,
            sampled_shape_zyx=array.shape[:3],
            window_zyx=size_zyx,
        )
        cls.configure_display(node, array, info)

    @classmethod
    def configure_display(cls, node, array: np.ndarray, info: SourceInfo) -> None:
        display = node.GetDisplayNode()
        if display is None or not hasattr(display, "SetAutoWindowLevel"):
            return
        try:
            finite = array[np.isfinite(array)] if np.issubdtype(array.dtype, np.floating) else array
            if finite.size:
                display.SetAutoWindowLevel(False)
                display.SetWindowLevelMinMax(float(finite.min()), float(finite.max()))
        except Exception as error:
            logging.debug(f"Unable to set the window/level of {node.GetName()}: {error}")


class ScalarVolumeBackend(VolumeBackend):
    NODE_CLASS = CLASS_SCALAR_VOLUME


class VectorVolumeBackend(VolumeBackend):
    NODE_CLASS = CLASS_VECTOR_VOLUME

    @classmethod
    def configure_display(cls, node, array, info) -> None:
        return


class LabelMapVolumeBackend(VolumeBackend):
    NODE_CLASS = CLASS_LABELMAP_VOLUME

    @classmethod
    def create(cls, name: str, info: SourceInfo):
        node = super().create(name, info)
        color_node = cls._color_node(name, info)
        if color_node is not None:
            node.GetDisplayNode().SetAndObserveColorNodeID(color_node.GetID())
        return node

    @classmethod
    def configure_display(cls, node, array, info) -> None:
        return

    @classmethod
    def _color_node(cls, name: str, info: SourceInfo):
        if not info.labels:
            return None
        try:
            from ltrace.slicer.netcdf import nc_labels_to_color_node

            return nc_labels_to_color_node(list(info.labels), name)
        except Exception as error:
            logging.debug(f"Unable to build a color table for {name}: {error}")
            return None
