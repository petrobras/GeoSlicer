"""Metadata sniffing shared by the source backends: voxel size and RAW geometry.

All spacings are returned in millimeters, the Slicer length unit.

The filename conventions understood here are the ones already in use across GeoSlicer, so a deferred read
recovers the same geometry the eager loaders would have produced:

* ``..._<X>_<Y>_<Z>_<SSSSS>nm.raw`` — the nine-part RAW convention of ``MicroCTLoader/Libs/RawLoader.py``;
* ``..._<SSSSS>nm.<ext>`` — the spacing-only convention of ``ltrace.slicer.microct.SPACING_REGEX``.
"""

import logging
import re
from pathlib import Path
from typing import Optional, Tuple

NM_IN_MM = 1e6
UM_IN_MM = 1e3
CM_IN_MM = 10.0
INCH_IN_MM = 25.4

SPACING_NM_REGEX = re.compile(r"_(\d{5})nm")

RAW_DTYPE_BY_TAG = {
    "BIN": ("uint8", True),
    "BIW": ("uint8", True),
    "LABEL": ("uint8", True),
    "BASINS": ("uint8", True),
    "MANGO": ("uint8", False),
    "CT": ("uint16", False),
    "PSD": ("uint16", False),
    "MICP": ("uint16", False),
    "POR": ("float32", False),
    "FLOAT": ("float32", False),
}
"""Data-type tag embedded in the RAW filename -> (numpy dtype, is a label map)."""


def spacing_from_name(name: str) -> Optional[float]:
    """Voxel size in mm from the ``_01000nm`` filename convention, or ``None``."""
    match = SPACING_NM_REGEX.search(Path(name).name)
    if not match:
        return None
    return int(match.group(1)) / NM_IN_MM


def raw_geometry_from_name(name: str):
    """``(shape_zyx, dtype, is_labelmap, spacing_mm)`` from the nine-part RAW convention, or ``None``."""
    stem = Path(name).stem
    parts = stem.split("_")
    if len(parts) != 9:
        return None

    tag = parts[4].upper()
    dtype_entry = next((value for key, value in RAW_DTYPE_BY_TAG.items() if key in tag), None)
    if dtype_entry is None:
        return None

    dtype, is_labelmap = dtype_entry
    try:
        x, y, z = (int(parts[index]) for index in (5, 6, 7))
    except ValueError:
        return None

    spacing = spacing_from_name(stem)
    return (z, y, x), dtype, is_labelmap, spacing


def tiff_spacing(page) -> Optional[float]:
    """Voxel size in mm from TIFF tags (``XResolution`` + ``ResolutionUnit``) or ImageJ metadata."""
    try:
        tags = page.tags
    except AttributeError:
        return None

    resolution = tags.get("XResolution")
    unit = tags.get("ResolutionUnit")
    if resolution is not None and resolution.value:
        try:
            numerator, denominator = resolution.value
            pixels_per_unit = float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            pixels_per_unit = 0.0

        if pixels_per_unit > 0:
            # ResolutionUnit: 1 = none, 2 = inch, 3 = centimeter
            unit_value = getattr(unit, "value", 3)
            unit_value = int(getattr(unit_value, "value", unit_value))
            if unit_value == 2:
                return INCH_IN_MM / pixels_per_unit
            if unit_value == 3:
                return CM_IN_MM / pixels_per_unit

    description = tags.get("ImageDescription")
    if description is not None and isinstance(description.value, str) and "unit=" in description.value:
        try:
            fields = dict(line.split("=", 1) for line in description.value.splitlines() if "=" in line)
            spacing = float(fields.get("spacing", ""))
            return spacing * _unit_to_mm(fields.get("unit", "mm").strip())
        except (TypeError, ValueError) as error:
            logging.debug(f"Unable to parse ImageJ TIFF description for spacing: {error}")

    return None


def _unit_to_mm(unit: str) -> float:
    unit = unit.lower()
    if unit in ("nm", "nanometer"):
        return 1 / NM_IN_MM
    if unit in ("um", "micron", "micrometer", "µm"):
        return 1 / UM_IN_MM
    if unit in ("cm", "centimeter"):
        return CM_IN_MM
    if unit in ("inch", "in"):
        return INCH_IN_MM
    return 1.0


def isotropic(spacing: Optional[float], fallback: float = 1.0) -> Tuple[float, float, float]:
    value = fallback if spacing is None or spacing <= 0 else float(spacing)
    return (value, value, value)
