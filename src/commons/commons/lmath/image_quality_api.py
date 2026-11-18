"""Image quality report of a micro-CT scan (SNR, CNR, cupping and edge MTF) from plain arrays.

This is the entry point for scripts, notebooks and other modules: it needs no Slicer, only numpy, scipy and
scikit-image. The regions are whatever `mask_provider` returns, so they can come from a segmentation node, a file or
a geometric recipe.

    result = measure_quality(
        volume, spacing=(0.09, 0.09, 0.09), mask_provider=masks.__getitem__, name_provider=str,
        options=QualityOptions(snr=["rock", "air"], cnr=CnrOptions("rock", "air")),
    )
    result.metrics["CNR"]
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from commons.lmath.image_quality import (
    cnr_from_stats,
    cupping_percent,
    edge_mtf,
    radial_profile,
    region_stats,
    snr_from_stats,
)


class QualityError(ValueError):
    """The requested metrics could not be computed."""


@dataclass
class CnrOptions:
    segment_a: str
    segment_b: str


@dataclass
class CuppingOptions:
    """The cupping of the union of `segments` (the whole sample, or just one segment). `name` is the label stored in
    the "Cupping segment" column; by default the segment names joined by " + "."""

    segments: Sequence[str]
    name: str | None = None
    center_fraction: float = 0.2
    edge_fraction: tuple[float, float] = (0.8, 0.95)


@dataclass
class MtfOptions:
    side_a: str
    side_b: str
    band_voxels: float = 10


@dataclass
class QualityOptions:
    """The metrics to compute. A metric left as `None` (or an empty SNR list) is skipped."""

    snr: Sequence[str] | None = None
    cnr: CnrOptions | None = None
    cupping: CuppingOptions | None = None
    mtf: MtfOptions | None = None


@dataclass
class QualityResult:
    """`metrics` is an ordered dict (column name -> value), `curves` holds the arrays of the plots and `warnings`
    the metrics that failed while others succeeded."""

    metrics: dict = field(default_factory=dict)
    curves: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class _SegmentData:
    """Masks and statistics of the segments of one scan, each computed at most once."""

    def __init__(self, volume, mask_provider, name_provider):
        self.volume = volume
        self._mask_provider = mask_provider
        self.name = name_provider
        self._masks = {}
        self._stats = {}

    def mask(self, segment_id):
        if segment_id not in self._masks:
            mask = self._mask_provider(segment_id)
            if mask is None or not mask.any():
                raise QualityError(f"Segment '{self.name(segment_id)}' is empty.")
            self._masks[segment_id] = np.asarray(mask, dtype=bool)  # no copy when it already is a bool array
        return self._masks[segment_id]

    def union(self, segment_ids):
        """Mask of all the given segments together. Empty segments are skipped; it fails only if all are empty."""
        union = None
        for segment_id in segment_ids:
            try:
                mask = self.mask(segment_id)
            except QualityError:
                continue
            union = mask if union is None else union | mask
        if union is None:
            raise QualityError("The selected segments are empty.")
        return union

    def stats(self, segment_id):
        if segment_id not in self._stats:
            self._stats[segment_id] = region_stats(self.volume, self.mask(segment_id))
        return self._stats[segment_id]


def measure_quality(
    volume: np.ndarray,
    spacing: Sequence[float],
    mask_provider: Callable[[str], np.ndarray],
    name_provider: Callable[[str], str],
    options: QualityOptions,
    label: str = "",
    metadata: Mapping[str, str] | None = None,
) -> QualityResult:
    """Compute the selected metrics.

    Args:
        volume: gray levels, indexed (z, y, x). A memory-mapped array works.
        spacing: voxel size in mm in the same (z, y, x) order as `volume`.
        mask_provider: `segment id -> boolean array` with the shape of `volume`, called at most once per id.
        name_provider: `segment id -> display name`, used in the column names.
        options: which metrics to compute and on which segments.
        label: name of the scan, stored in the "Volume" column.
        metadata: extra values copied into the row, keyed by column name (for instance acquisition parameters).

    A metric that fails (for instance an MTF between segments that do not touch) does not stop the others: it is
    reported in `warnings`. A QualityError is raised only when no metric could be computed.
    """
    spacing = tuple(float(s) for s in spacing)
    data = _SegmentData(volume, mask_provider, name_provider)

    row = {"Volume": label}
    row.update(metadata or {})
    row["Voxel size (um)"] = float(np.mean(spacing)) * 1000.0
    base = set(row)
    curves, warnings = {}, []

    def snr():
        for segment_id in options.snr:
            row[f"SNR [{data.name(segment_id)}]"] = snr_from_stats(*data.stats(segment_id))

    def cnr():
        a, b = options.cnr.segment_a, options.cnr.segment_b
        row["CNR"] = cnr_from_stats(data.stats(a), data.stats(b))
        row["CNR phases"] = f"{data.name(a)} vs {data.name(b)}"

    def cupping():
        settings = options.cupping
        radii, profile, radius = radial_profile(data.volume, data.union(settings.segments), spacing)
        row["Cupping segment"] = settings.name or " + ".join(data.name(segment_id) for segment_id in settings.segments)
        row["Cupping (%)"] = cupping_percent(radii, profile, radius, settings.center_fraction, settings.edge_fraction)
        curves["radial"] = {"radius": radii, "profile": profile}

    def mtf():
        settings = options.mtf
        band = settings.band_voxels * float(np.mean(spacing))
        result = edge_mtf(data.volume, data.mask(settings.side_a), data.mask(settings.side_b), spacing, band)
        row["MTF edge"] = f"{data.name(settings.side_a)} | {data.name(settings.side_b)}"
        row["Resolvable at 50% (um)"] = result["resolvable_um50"]
        row["Resolvable at 10% (um)"] = result["resolvable_um10"]
        row["LSF FWHM (um)"] = result["fwhm"] * 1000.0
        nyquist = 0.5 / float(np.mean(spacing))
        curves["mtf"] = {
            "frequencies": result["frequencies"],
            "mtf": result["mtf"],
            "xmax": 2.0 * nyquist,
            "f50": result["f50"],
            "f10": result["f10"],
        }

    for requested, label_, function in (
        (options.snr, "SNR", snr),
        (options.cnr, "CNR", cnr),
        (options.cupping, "Cupping", cupping),
        (options.mtf, "MTF", mtf),
    ):
        if not requested:
            continue
        try:
            function()
        except ValueError as error:
            warnings.append(f"{label_}: {error}")

    if set(row) == base:
        raise QualityError("No metric could be computed.\n" + "\n".join(warnings))
    return QualityResult(metrics=row, curves=curves, warnings=warnings)
