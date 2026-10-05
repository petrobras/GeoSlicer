"""RAW binary volumes, read through ``numpy.memmap`` so a strided read stays partial.

A RAW file carries no geometry, so it is recovered, in order, from:

1. explicit ``shape_zyx``/``dtype`` options given by the caller;
2. the nine-part filename convention shared with ``MicroCTLoader``;
3. a sibling LBPM configuration file (``*.db``), which is how LBPM's ``id_t<step>.raw`` snapshots are
   interpreted — their names carry no geometry at all.
"""

import logging
from pathlib import Path
from typing import Sequence

import numpy as np

from .base import (
    CLASS_LABELMAP_VOLUME,
    CLASS_SCALAR_VOLUME,
    KIND_VOLUME,
    SourceError,
    SourceInfo,
    VirtualSource,
    window_slices,
)
from .metadata import isotropic, raw_geometry_from_name, spacing_from_name

RAW_EXTENSIONS = (".raw", ".bin")


def _geometry_from_sibling_config(path: Path, depth: int = 2):
    """``(shape_zyx, dtype, is_labelmap, spacing_mm)`` from a nearby LBPM ``.db``.

    Searched upwards as well as beside the file: a simulation writes its snapshots into per-frame folders,
    while the configuration that describes their geometry stays in the case folder above them.
    """
    try:
        from ltrace.lbpm.config import WaterflowConfig
    except ImportError:  # pragma: no cover - the LBPM package is always shipped alongside
        return None

    folders = [path.parent, *list(path.parents)[1 : depth + 1]]
    for folder in folders:
        for candidate in sorted(folder.glob("*.db")):
            try:
                geometry = WaterflowConfig.from_file(candidate).domain_geometry()
                if geometry is not None:
                    return geometry
            except Exception as error:
                logging.debug(f"Ignoring {candidate.name} while inferring RAW geometry: {error}")

    return None


def _placement_from_case(path: Path, shape_zyx):
    """The placement GeoSlicer recorded for the case this file belongs to, when it fits ``shape_zyx``."""
    try:
        from ltrace.lbpm.geometry import CaseGeometry
    except ImportError:  # pragma: no cover - the LBPM package ships with this one
        return None

    geometry = CaseGeometry.find(path)
    return geometry if geometry is not None and geometry.matches(shape_zyx) else None


class RawSource(VirtualSource):
    KIND = KIND_VOLUME
    EXTENSIONS = RAW_EXTENSIONS

    def __init__(self, path, variable: str = None, shape_zyx=None, dtype=None, labelmap=None, spacing=None, **options):
        super().__init__(path, variable=variable, **options)
        self._shape_zyx = tuple(shape_zyx) if shape_zyx else None
        self._dtype = dtype
        self._labelmap = labelmap
        self._spacing = spacing
        self._memmap = None

    def _describe(self) -> SourceInfo:
        shape, dtype, labelmap, spacing = self._shape_zyx, self._dtype, self._labelmap, self._spacing

        if shape is None or dtype is None:
            inferred = raw_geometry_from_name(self.path.name) or _geometry_from_sibling_config(self.path)
            if inferred is None:
                raise SourceError(
                    f"Cannot infer the geometry of {self.path.name}. Provide shape_zyx and dtype, or place "
                    "the simulation configuration file (*.db) next to it."
                )
            inferred_shape, inferred_dtype, inferred_labelmap, inferred_spacing = inferred
            shape = shape or inferred_shape
            dtype = dtype or inferred_dtype
            labelmap = inferred_labelmap if labelmap is None else labelmap
            spacing = spacing or inferred_spacing

        expected = int(np.prod(shape)) * np.dtype(dtype).itemsize
        actual = self.path.stat().st_size
        if actual != expected:
            raise SourceError(
                f"{self.path.name} is {actual} bytes but the inferred geometry {shape} of {dtype} needs {expected}."
            )

        self._shape_zyx, self._dtype = tuple(int(size) for size in shape), str(dtype)
        spacing = spacing or spacing_from_name(self.path.name)

        # LBPM's `id_t<step>.raw` snapshots are the case's input image at a later time, so they inherit
        # its placement when the case recorded one.
        placement = _placement_from_case(self.path, self._shape_zyx)

        return SourceInfo(
            kind=KIND_VOLUME,
            node_class=CLASS_LABELMAP_VOLUME if labelmap else CLASS_SCALAR_VOLUME,
            shape_zyx=self._shape_zyx,
            dtype=self._dtype,
            spacing_zyx=isotropic(spacing) if spacing else (placement.spacing_zyx if placement else isotropic(None)),
            origin_zyx=placement.origin_zyx if placement else None,
            variables=(self.path.stem,),
            variable=self.variable or self.path.stem,
            extra={"labelmap": bool(labelmap)},
        )

    def _mapped(self) -> np.memmap:
        info = self.describe()
        if self._memmap is None:
            self._memmap = np.memmap(self.path, dtype=info.dtype, mode="r", shape=info.shape_zyx)
        return self._memmap

    def read_window(self, origin_zyx: Sequence[int] = (0, 0, 0), size_zyx: Sequence[int] = None, factor: int = 1):
        info = self.describe()
        slices = window_slices(info.shape_zyx, origin_zyx, size_zyx, factor)
        return np.array(self._mapped()[slices])

    def close(self) -> None:
        self._memmap = None
        super().close()
