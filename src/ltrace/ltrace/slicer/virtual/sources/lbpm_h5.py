"""LBPM visualization frames: a ``vis<timestep>/`` folder of per-rank HDF5 sub-domains.

LBPM writes one HDF5 file per MPI rank, each holding its own sub-domain of every saved field::

    vis10000/00000.h5:/domain_00000/{phase,Pressure,Velocity_x,Velocity_y,Velocity_z}  shape (z, y, x)
                      /domain_00000/rankinfo   [rank, npx, npy, npz]
                      /domain_00000/range      [x0, x1, y0, y1, z0, z1]   (voxel coordinates)

The global volume is the union of those sub-domains, so a read has to be scattered across the rank files.
Only the ranks that intersect the requested window are opened, and the stride is pushed down into h5py's
slicing, which keeps a preview read proportional to the preview size rather than to the frame size.
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

from .base import (
    CLASS_SCALAR_VOLUME,
    KIND_VOLUME,
    SourceError,
    SourceInfo,
    VirtualSource,
    path_stamp,
    window_slices,
)
from .metadata import isotropic

DOMAIN_GROUP = re.compile(r"^domain_(\d+)$")
GEOMETRY_DATASETS = {"x", "y", "z", "N", "range", "rankinfo"}
DEFAULT_VARIABLE_ORDER = ("phase", "Pressure", "Velocity_x", "Velocity_y", "Velocity_z")


class _Rank:
    """One rank file and where its sub-domain sits inside the global volume."""

    __slots__ = ("path", "group", "offset_zyx", "shape_zyx")

    def __init__(self, path: Path, group: str, offset_zyx: Tuple[int, int, int], shape_zyx: Tuple[int, int, int]):
        self.path = path
        self.group = group
        self.offset_zyx = offset_zyx
        self.shape_zyx = shape_zyx

    @property
    def z_start(self) -> int:
        return self.offset_zyx[0]

    @property
    def z_stop(self) -> int:
        return self.offset_zyx[0] + self.shape_zyx[0]


class LbpmH5Source(VirtualSource):
    KIND = KIND_VOLUME
    EXTENSIONS = (".h5",)

    def __init__(self, path, variable: str = None, spacing: float = None, shape_zyx=None, **options):
        super().__init__(path, variable=variable, **options)
        self._spacing = spacing
        self._reference_shape = tuple(int(size) for size in shape_zyx) if shape_zyx else None
        self._ranks: List[_Rank] = []

    def set_reference_shape(self, shape_zyx) -> None:
        """Read this frame as if it had ``shape_zyx``.

        A frame written by fewer ranks than the domain needs — a frame still being produced — would
        otherwise report its own, smaller extent, and its sub-domains would be placed at the wrong depth.
        With the reference geometry known, each rank lands where it belongs and the rest reads as empty.
        """
        shape = tuple(int(size) for size in shape_zyx) if shape_zyx else None
        if shape != self._reference_shape:
            self._reference_shape = shape
            self._info = None

    # -- discovery ------------------------------------------------------------------------------------
    @classmethod
    def can_open(cls, path: Path) -> bool:
        candidates = sorted(path.glob("*.h5")) if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.suffix.lower() != ".h5":
                continue
            try:
                import h5py

                with h5py.File(candidate.as_posix(), "r") as handle:
                    if any(DOMAIN_GROUP.match(key) for key in handle.keys()):
                        return True
            except Exception:
                continue
        return False

    def _files(self) -> List[Path]:
        return sorted(self.path.glob("*.h5")) if self.path.is_dir() else [self.path]

    # -- description ----------------------------------------------------------------------------------
    def _describe(self) -> SourceInfo:
        import h5py

        files = self._files()
        if not files:
            raise SourceError(f"No HDF5 rank file inside {self.path}")

        ranks: List[_Rank] = []
        variables: List[str] = []
        dtype = None

        for file in files:
            try:
                with h5py.File(file.as_posix(), "r") as handle:
                    for key in handle.keys():
                        if not DOMAIN_GROUP.match(key):
                            continue
                        group = handle[key]
                        names = [
                            name
                            for name in group.keys()
                            if name not in GEOMETRY_DATASETS and getattr(group[name], "ndim", 0) == 3
                        ]
                        if not names:
                            continue

                        extent = group["range"][:] if "range" in group else None
                        sample = group[names[0]]
                        shape_zyx = tuple(int(size) for size in sample.shape)
                        if extent is not None and len(extent) == 6:
                            offset = (int(extent[4]), int(extent[2]), int(extent[0]))
                        else:
                            offset = (0, 0, 0)

                        ranks.append(_Rank(file, key, offset, shape_zyx))
                        dtype = dtype or str(sample.dtype)
                        for name in names:
                            if name not in variables:
                                variables.append(name)
            except OSError as error:
                logging.warning(f"Skipping unreadable LBPM rank file {file.name}: {error}")

        if not ranks:
            raise SourceError(f"{self.path} holds no LBPM sub-domain")

        ranks.sort(key=lambda rank: rank.offset_zyx)
        self._ranks = ranks

        shape_zyx = self._reference_shape or (
            max(rank.z_stop for rank in ranks),
            max(rank.offset_zyx[1] + rank.shape_zyx[1] for rank in ranks),
            max(rank.offset_zyx[2] + rank.shape_zyx[2] for rank in ranks),
        )

        ordered = [name for name in DEFAULT_VARIABLE_ORDER if name in variables]
        ordered += [name for name in variables if name not in ordered]
        variable = self.variable if self.variable in ordered else ordered[0]

        # A frame is the simulated state of the case's input image, so it belongs exactly where that image
        # is. The case records that placement when GeoSlicer wrote it; otherwise all that is known is the
        # voxel size, and the frame is centred like any image whose file says nothing about its origin.
        placement = self._placement_from_case(shape_zyx)
        spacing = isotropic(self._spacing) if self._spacing else None

        return SourceInfo(
            kind=KIND_VOLUME,
            node_class=CLASS_SCALAR_VOLUME,
            shape_zyx=shape_zyx,
            dtype=dtype or "float64",
            spacing_zyx=spacing or (placement.spacing_zyx if placement else isotropic(self._spacing_from_case())),
            origin_zyx=placement.origin_zyx if placement else None,
            variables=tuple(ordered),
            variable=variable,
            extra={"ranks": len(ranks), "placement": placement.source if placement else ""},
        )

    def _placement_from_case(self, shape_zyx):
        """The case's recorded placement, when it describes a volume of this shape."""
        try:
            from ltrace.lbpm.geometry import CaseGeometry
        except ImportError:  # pragma: no cover - the LBPM package ships with this one
            return None

        geometry = CaseGeometry.find(self.path)
        if geometry is None:
            return None
        if not geometry.matches(shape_zyx):
            logging.debug(
                f"Ignoring the recorded placement of {self.path}: it describes {geometry.shape_zyx}, "
                f"not {tuple(shape_zyx)}."
            )
            return None
        return geometry

    def _spacing_from_case(self):
        """Voxel size from the LBPM case configuration, searched upwards from the frame folder."""
        try:
            from ltrace.lbpm.config import WaterflowConfig
        except ImportError:  # pragma: no cover
            return None

        folder = self.path if self.path.is_dir() else self.path.parent
        for parent in (folder, *folder.parents[:2]):
            for candidate in sorted(parent.glob("*.db")):
                try:
                    spacing = WaterflowConfig.from_file(candidate).voxel_length_mm()
                    if spacing:
                        return spacing
                except Exception as error:
                    logging.debug(f"Ignoring {candidate} while reading LBPM voxel size: {error}")
        return None

    # -- reading --------------------------------------------------------------------------------------
    def read_window(self, origin_zyx: Sequence[int] = (0, 0, 0), size_zyx: Sequence[int] = None, factor: int = 1):
        import h5py

        info = self.describe()
        variable = self.variable or info.variable
        z_slice, y_slice, x_slice = window_slices(info.shape_zyx, origin_zyx, size_zyx, factor)
        wanted = np.arange(z_slice.start, z_slice.stop, z_slice.step)
        if wanted.size == 0:
            raise SourceError(f"Empty window requested from {self.path}")

        planes: Dict[int, np.ndarray] = {}
        by_file: Dict[Path, List[_Rank]] = {}
        for rank in self._ranks:
            by_file.setdefault(rank.path, []).append(rank)

        for file, ranks in by_file.items():
            selected = [
                (rank, wanted[(wanted >= rank.z_start) & (wanted < rank.z_stop)])
                for rank in ranks
                if wanted[(wanted >= rank.z_start) & (wanted < rank.z_stop)].size
            ]
            if not selected:
                continue

            with h5py.File(file.as_posix(), "r") as handle:
                for rank, indices in selected:
                    dataset = handle[rank.group].get(variable)
                    if dataset is None:
                        raise SourceError(f"{file.name}/{rank.group} has no variable {variable!r}")

                    local = indices - rank.z_start
                    local_slice = slice(int(local[0]), int(local[-1]) + 1, int(z_slice.step))
                    block = np.asarray(dataset[local_slice, y_slice, x_slice])
                    for position, index in enumerate(indices):
                        planes[int(index)] = block[position]

        missing = [int(index) for index in wanted if int(index) not in planes]
        if missing:
            # Ragged rank output (a frame still being written). Empty planes, not repeated ones: while a
            # simulation runs the user must be able to tell an incomplete frame from a finished one.
            if len(missing) == len(wanted):
                raise SourceError(f"No rank of {self.path} covers the requested window")
            reference = planes[next(iter(planes))]
            empty = np.zeros_like(reference)
            for index in missing:
                planes[index] = empty

        return np.stack([planes[int(index)] for index in wanted], axis=0)

    def paths(self) -> Sequence[Path]:
        return self._files()

    def stamp(self) -> str:
        return path_stamp(self.paths())
