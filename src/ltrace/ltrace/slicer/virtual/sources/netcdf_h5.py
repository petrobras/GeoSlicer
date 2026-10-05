"""NetCDF / HDF5 volumes read through xarray, one window at a time.

``xarray`` + ``h5netcdf`` is already the transport used by ``ltrace.slicer.netcdf`` and by the existing
LazyNode protocols, so deferred reads of the project's own NetCDF exports go through the same stack. The
spacing/origin conventions are recomputed here from the coordinate arrays instead of importing
``ltrace.slicer.netcdf``, which pulls in ``slicer``.
"""

import logging
from pathlib import Path
from typing import Sequence

import numpy as np

from .base import (
    CLASS_LABELMAP_VOLUME,
    CLASS_SCALAR_VOLUME,
    CLASS_VECTOR_VOLUME,
    KIND_VOLUME,
    SourceError,
    SourceInfo,
    VirtualSource,
    window_slices,
)

NETCDF_EXTENSIONS = (".nc", ".h5", ".hdf5", ".nc4")
ENGINE = "h5netcdf"


def _spacing_from_coords(array) -> tuple:
    spacing = []
    for dim in array.dims[:3]:
        coord = array.coords.get(dim)
        if coord is None or coord.size < 2:
            spacing.append(1.0)
            continue
        spacing.append(float(abs(coord.values[1] - coord.values[0])))
    while len(spacing) < 3:
        spacing.append(1.0)
    return tuple(spacing)


def _origin_from_coords(array) -> tuple:
    origin = []
    for dim in array.dims[:3]:
        coord = array.coords.get(dim)
        origin.append(float(coord.values[0]) if coord is not None and coord.size else 0.0)
    while len(origin) < 3:
        origin.append(0.0)
    return tuple(origin)


class NetCdfSource(VirtualSource):
    """A NetCDF-4/HDF5 file (or a directory of them) holding one or more image variables."""

    KIND = KIND_VOLUME
    EXTENSIONS = NETCDF_EXTENSIONS

    def __init__(self, path, variable: str = None, **options):
        super().__init__(path, variable=variable, **options)
        self._dataset = None

    @classmethod
    def can_open(cls, path: Path) -> bool:
        if path.is_dir():
            return bool(next(iter(path.glob("*.nc")), None))
        return path.is_file() and path.suffix.lower() in cls.EXTENSIONS

    def _open(self):
        import xarray as xr

        if self._dataset is None:
            backend = {"lock": False}
            if self.path.is_dir():
                files = sorted(self.path.glob("*.nc"))
                if not files:
                    raise SourceError(f"No NetCDF file inside {self.path}")
                self._dataset = xr.open_mfdataset(
                    [file.as_posix() for file in files],
                    combine="by_coords",
                    chunks=256,
                    engine=ENGINE,
                    backend_kwargs=backend,
                )
            else:
                self._dataset = xr.open_dataset(self.path.as_posix(), engine=ENGINE, chunks=256, backend_kwargs=backend)
        return self._dataset

    def _array(self):
        dataset = self._open()
        variable = self.variable or self.describe().variable
        if variable not in dataset:
            raise SourceError(f"{self.path.name} has no variable named {variable!r}")
        return dataset[variable]

    def _describe(self) -> SourceInfo:
        dataset = self._open()
        candidates = [name for name, array in dataset.data_vars.items() if array.ndim >= 2]
        if not candidates:
            raise SourceError(f"{self.path.name} holds no image variable")

        variable = (
            self.variable
            if self.variable in candidates
            else max(candidates, key=lambda name: int(np.prod(dataset[name].shape)))
        )
        array = dataset[variable]
        shape = tuple(int(size) for size in array.shape[:3])
        components = int(array.shape[3]) if array.ndim > 3 else 1
        labels = array.attrs.get("labels")
        if isinstance(labels, str):
            labels = (labels,)

        node_class = CLASS_SCALAR_VOLUME
        if labels:
            node_class = CLASS_LABELMAP_VOLUME
        elif components > 1:
            node_class = CLASS_VECTOR_VOLUME

        return SourceInfo(
            kind=KIND_VOLUME,
            node_class=node_class,
            shape_zyx=shape,
            dtype=str(array.dtype),
            spacing_zyx=_spacing_from_coords(array),
            origin_zyx=_origin_from_coords(array),
            components=components,
            variables=tuple(candidates),
            variable=variable,
            labels=tuple(labels or ()),
            extra={"dims": tuple(str(dim) for dim in array.dims)},
        )

    def read_window(self, origin_zyx: Sequence[int] = (0, 0, 0), size_zyx: Sequence[int] = None, factor: int = 1):
        info = self.describe()
        slices = window_slices(info.shape_zyx, origin_zyx, size_zyx, factor)
        array = self._array()
        if array.ndim > 3:
            slices = slices + (slice(None),) * (array.ndim - 3)
        return np.asarray(array[slices].values)

    def paths(self) -> Sequence[Path]:
        return sorted(self.path.glob("*.nc")) if self.path.is_dir() else [self.path]

    def close(self) -> None:
        if self._dataset is not None:
            try:
                self._dataset.close()
            except Exception as error:
                logging.debug(f"Failed to close {self.path}: {error}")
            self._dataset = None
        super().close()
