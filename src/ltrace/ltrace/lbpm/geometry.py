"""Where a case's images sit in space.

LBPM's configuration says how big a domain is — ``Domain.N`` counts the voxels and ``Domain.voxel_length``
measures one — but never where the image came from, and its output carries no more than its input did.
GeoSlicer knows: the user picked the node the case was written from. That placement is recorded beside the
configuration and read back when the results are loaded, so the simulated frames land exactly on the image
they were computed from.

Without it the frames can only be placed by convention, and the two conventions in play disagree: an image
imported into GeoSlicer is centred on the world origin (``Center volume`` is on by default), while a file
that records no origin would otherwise be anchored with its first voxel there — half a domain away.

The placement is stored in the ZYX order and the sign convention of :class:`SourceInfo`, matching
``ltrace.slicer.netcdf.get_origin``, so a reader can hand it straight to a node without converting.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

GEOMETRY_NAME = "geoslicer_geometry.json"
"""Sidecar written next to the case configuration. Named for what it is: GeoSlicer's, not LBPM's."""


@dataclass(frozen=True)
class CaseGeometry:
    """Placement of the image a case was built from."""

    origin_zyx: Tuple[float, float, float]
    spacing_zyx: Tuple[float, float, float]
    shape_zyx: Optional[Tuple[int, int, int]] = None
    source: str = ""

    @classmethod
    def from_volume_node(cls, node, source: str = None) -> "CaseGeometry":
        """Read the placement of a Slicer volume node.

        Only ``GetOrigin``/``GetSpacing``/``GetImageData`` are used, so this stays free of a ``slicer``
        import and can be exercised with a stub. The origin is the RAS position of voxel (0, 0, 0)
        expressed in the ZYX convention, which round-trips through
        ``ltrace.slicer.virtual.nodes.base.apply_geometry`` unchanged.
        """
        origin = node.GetOrigin()
        spacing = node.GetSpacing()
        dimensions = node.GetImageData().GetDimensions() if node.GetImageData() is not None else None

        return cls(
            origin_zyx=(float(origin[2]), -float(origin[1]), -float(origin[0])),
            spacing_zyx=(float(spacing[2]), float(spacing[1]), float(spacing[0])),
            shape_zyx=tuple(int(size) for size in reversed(dimensions)) if dimensions else None,
            source=source or node.GetName(),
        )

    # -- storage --------------------------------------------------------------------------------------
    def write(self, folder) -> Path:
        path = Path(folder) / GEOMETRY_NAME
        path.write_text(json.dumps(self.as_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    def as_dict(self) -> dict:
        return {
            "origin_zyx": [float(value) for value in self.origin_zyx],
            "spacing_zyx": [float(value) for value in self.spacing_zyx],
            "shape_zyx": [int(value) for value in self.shape_zyx] if self.shape_zyx else None,
            "source": self.source,
        }

    @classmethod
    def read(cls, folder) -> Optional["CaseGeometry"]:
        path = Path(folder) / GEOMETRY_NAME
        if not path.is_file():
            return None
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                origin_zyx=tuple(float(value) for value in content["origin_zyx"]),
                spacing_zyx=tuple(float(value) for value in content["spacing_zyx"]),
                shape_zyx=tuple(int(value) for value in content["shape_zyx"]) if content.get("shape_zyx") else None,
                source=content.get("source", ""),
            )
        except (KeyError, TypeError, ValueError, OSError) as error:
            logging.debug(f"Ignoring an unreadable {path}: {error}")
            return None

    @classmethod
    def find(cls, path, depth: int = 2) -> Optional["CaseGeometry"]:
        """Search for the sidecar beside ``path`` and in the folders above it.

        A simulation writes its frames into per-frame folders inside the run folder, so the case that
        describes them is one or two levels up — the same search ``RawSource`` makes for the ``.db``.
        """
        path = Path(path)
        start = path if path.is_dir() else path.parent
        for folder in (start, *list(start.parents)[:depth]):
            geometry = cls.read(folder)
            if geometry is not None:
                return geometry
        return None

    # -- use ------------------------------------------------------------------------------------------
    def matches(self, shape_zyx: Sequence[int]) -> bool:
        """Whether this placement describes a volume of ``shape_zyx``.

        A mismatch means the frames are not the image the sidecar was written for — a case re-run on a
        different image, or an LBPM domain padded past its input — and the placement must not be applied,
        because it would put the frames somewhere no data ever was.
        """
        if self.shape_zyx is None or shape_zyx is None:
            return True
        return tuple(int(size) for size in shape_zyx[:3]) == tuple(int(size) for size in self.shape_zyx)
