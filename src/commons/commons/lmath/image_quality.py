"""Image quality metrics for micro-CT volumes: SNR, CNR, cupping and edge-based MTF.

Pure numpy/scipy, no Slicer dependency. Volumes are indexed as (z, y, x) and `spacing` is given in the same
order, in millimeters.
"""

from typing import Optional, Tuple

import numpy as np
from scipy import ndimage
from scipy.signal.windows import tukey


def _stats(values: np.ndarray) -> Tuple[int, float, float]:
    if values.size == 0:
        return 0, float("nan"), float("nan")
    std = float(values.std(ddof=1, dtype=np.float64)) if values.size > 1 else float("nan")
    return int(values.size), float(values.mean(dtype=np.float64)), std


def region_stats(volume: np.ndarray, mask: np.ndarray) -> Tuple[int, float, float]:
    """Voxel count, mean and sample standard deviation of `volume` inside `mask`."""
    return _stats(np.asarray(volume)[mask])


def snr_from_stats(count: int, mean: float, std: float) -> float:
    if count < 2 or np.isnan(std):
        return float("nan")
    return float(mean / std) if std > 0 else float("inf")


def cnr_from_stats(stats1: Tuple[int, float, float], stats2: Tuple[int, float, float]) -> float:
    (n1, mean1, std1), (n2, mean2, std2) = stats1, stats2
    if n1 < 2 or n2 < 2:
        return float("nan")
    noise = float(np.sqrt(std1**2 + std2**2))
    return float(abs(mean1 - mean2) / noise) if noise > 0 else float("inf")


def snr(values: np.ndarray) -> float:
    """Signal-to-noise ratio of a homogeneous region: mean / standard deviation."""
    return snr_from_stats(*_stats(np.asarray(values).ravel()))


def cnr(values1: np.ndarray, values2: np.ndarray) -> float:
    """Contrast-to-noise ratio between two regions: |mu1 - mu2| / sqrt(sigma1^2 + sigma2^2)."""
    return cnr_from_stats(*(_stats(np.asarray(v).ravel()) for v in (values1, values2)))


def radial_profile(
    volume: np.ndarray,
    mask: np.ndarray,
    spacing: Tuple[float, float, float],
    bin_width: Optional[float] = None,
    max_slices: int = 256,
) -> Tuple[np.ndarray, np.ndarray, float]:
    """Mean gray level as a function of the distance to the axis of a cylindrical region.

    The axis is parallel to z and passes through the centroid of `mask` in the axial (y, x) plane. Only voxels
    inside `mask` contribute. At most `max_slices` evenly spaced slices are used and each one is processed on its
    own, so memory does not grow with the volume.

    Returns:
        (radii, profile, effective_radius), all in millimeters except `profile`. `radii` are bin centers and
        empty bins are dropped. `effective_radius` is the radius of the disc with the mean axial area of `mask`.
    """
    per_slice = np.count_nonzero(mask, axis=(1, 2))
    occupied = np.nonzero(per_slice)[0]
    if occupied.size == 0:
        raise ValueError("Empty mask")
    picks = np.linspace(0, occupied.size - 1, min(max_slices, occupied.size)).round().astype(np.int64)
    slices = np.unique(occupied[picks])

    dy, dx = spacing[1], spacing[2]
    ny, nx = mask.shape[1:]
    rows = np.zeros(ny)
    cols = np.zeros(nx)
    for z in slices:
        plane = mask[z]
        rows += plane.sum(axis=1)
        cols += plane.sum(axis=0)
    total = rows.sum()
    cy = float((rows * np.arange(ny)).sum() / total)
    cx = float((cols * np.arange(nx)).sum() / total)
    effective_radius = float(np.sqrt(total / slices.size * dy * dx / np.pi))

    bin_width = bin_width or min(dy, dx)
    n_bins = int(np.hypot(ny * dy, nx * dx) / bin_width) + 2
    counts = np.zeros(n_bins)
    sums = np.zeros(n_bins)
    for z in slices:
        ys, xs = np.nonzero(mask[z])
        index = (np.hypot((ys - cy) * dy, (xs - cx) * dx) / bin_width).astype(np.int64)
        counts += np.bincount(index, minlength=n_bins)
        sums += np.bincount(index, weights=np.asarray(volume[z])[ys, xs].astype(np.float64), minlength=n_bins)

    valid = counts > 0
    radii = (np.arange(n_bins) + 0.5)[valid] * bin_width
    return radii, sums[valid] / counts[valid], effective_radius


def cupping_percent(
    radii: np.ndarray,
    profile: np.ndarray,
    effective_radius: float,
    center_frac: float = 0.2,
    edge_frac: Tuple[float, float] = (0.8, 0.95),
) -> float:
    """Cupping = (mu_edge - mu_center) / mu_edge * 100.

    `mu_center` is the mean of the profile up to `center_frac * effective_radius`. `mu_edge` is the mean between
    `edge_frac[0]` and `edge_frac[1]` of the effective radius, which leaves out the interface voxels.
    """
    radii = np.asarray(radii)
    profile = np.asarray(profile, dtype=np.float64)
    center = profile[radii <= center_frac * effective_radius]
    edge = profile[(radii >= edge_frac[0] * effective_radius) & (radii <= edge_frac[1] * effective_radius)]
    if center.size == 0 or edge.size == 0:
        return float("nan")
    mu_center, mu_edge = center.mean(), edge.mean()
    return float((mu_edge - mu_center) / mu_edge * 100.0) if mu_edge != 0 else float("nan")


def _densify(points: np.ndarray, step: float) -> np.ndarray:
    """Insert points along a polyline so that consecutive points are at most `step` apart."""
    if len(points) < 2:
        return points
    segments = np.diff(points, axis=0)
    pieces = np.maximum(np.ceil(np.hypot(segments[:, 0], segments[:, 1]) / step).astype(np.int64), 1)
    owner = np.repeat(np.arange(len(segments)), pieces)
    within = np.arange(pieces.sum()) - np.repeat(np.cumsum(pieces) - pieces, pieces)
    fraction = (within / pieces[owner])[:, None]
    return np.vstack([points[owner] + segments[owner] * fraction, points[-1:]])


def _slice_edge_samples(
    image: np.ndarray,
    plane1: np.ndarray,
    plane2: np.ndarray,
    spacing: Tuple[float, float],
    band: float,
    smoothing: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """(signed distance, gray level) of the voxels around the region 1 / region 2 interface in one axial slice.

    The interface is the 0.5 level of the Gaussian-smoothed mask of region 1, which gives a sub-voxel contour that
    does not follow the staircase of the mask, and only the part of it that touches region 2 is used. Distances are
    exact distances to that contour (negative inside region 1), not distances between voxel centers.
    """
    from scipy.spatial import cKDTree
    from skimage import measure

    dy, dx = spacing
    pad_y = int(np.ceil((band + 3 * smoothing * dy) / dy)) + 2
    pad_x = int(np.ceil((band + 3 * smoothing * dx) / dx)) + 2
    rows = np.nonzero((plane1 | plane2).any(axis=1))[0]
    cols = np.nonzero((plane1 | plane2).any(axis=0))[0]
    box = (
        slice(max(rows[0] - pad_y, 0), rows[-1] + pad_y + 1),
        slice(max(cols[0] - pad_x, 0), cols[-1] + pad_x + 1),
    )
    image, plane1, plane2 = image[box], plane1[box], plane2[box]

    phi1 = ndimage.gaussian_filter(plane1.astype(np.float32), smoothing)
    phi2 = ndimage.gaussian_filter(plane2.astype(np.float32), smoothing)
    points = [_densify(c, 0.1) for c in measure.find_contours(phi1, 0.5)]
    points = np.vstack(points) if points else np.empty((0, 2))
    if len(points):
        near_region2 = ndimage.map_coordinates(phi2, points.T, order=1, mode="nearest") >= 0.2
        points = points[near_region2]
    empty = np.empty(0), np.empty(0)
    if len(points) < 2:
        return empty

    edge = plane1 & ~ndimage.binary_erosion(plane1)
    if not edge.any():
        return empty
    reach = ndimage.distance_transform_edt(~edge, sampling=spacing) <= band + 3 * min(spacing)
    candidates = np.nonzero(reach & (plane1 | plane2))
    scale = np.array(spacing)
    distance, _ = cKDTree(points * scale).query(np.column_stack(candidates) * scale)
    inside = phi1[candidates] > 0.5
    return np.where(inside, -distance, distance), image[candidates].astype(np.float64)


def esf_from_masks(
    volume: np.ndarray,
    mask1: np.ndarray,
    mask2: np.ndarray,
    spacing: Tuple[float, float, float],
    band: float,
    bin_width: Optional[float] = None,
    max_slices: int = 8,
    smoothing: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Oversampled edge spread function across the interface between two regions.

    The interface is located on up to `max_slices` evenly spaced axial slices where both regions are present, so
    it should be roughly perpendicular to the slice plane (the wall of a tube along z, a flat face parallel to z).
    On each slice every voxel of region 1 or 2 within `band` mm of the interface is placed at its signed distance
    to a sub-voxel contour (see `_slice_edge_samples`; `smoothing` is the Gaussian sigma, in voxels, applied to the
    mask before taking the contour). The ESF is the mean gray level per distance bin. Memory use is bounded by a
    slice, whatever the size of the volume.

    Returns:
        (distances, esf), `distances` in millimeters, negative inside region 1.
    """
    per_slice = np.minimum(np.count_nonzero(mask1, axis=(1, 2)), np.count_nonzero(mask2, axis=(1, 2)))
    present = np.nonzero(per_slice)[0]
    if present.size == 0:
        raise ValueError("The two regions do not share a slice")
    picks = np.linspace(0, present.size - 1, min(max_slices, present.size)).round().astype(np.int64)

    spacing = tuple(float(s) for s in spacing)
    bin_width = bin_width or min(spacing[1:]) / 4.0
    n_bins = int(np.ceil(2 * band / bin_width))
    counts = np.zeros(n_bins)
    sums = np.zeros(n_bins)
    for z in np.unique(present[picks]):
        signed, values = _slice_edge_samples(
            np.asarray(volume[z]),
            mask1[z],
            mask2[z],
            spacing[1:],
            band,
            smoothing,
        )
        keep = np.abs(signed) < band
        index = np.floor((signed[keep] + band) / bin_width).astype(np.int64)
        counts += np.bincount(index, minlength=n_bins)[:n_bins]
        sums += np.bincount(index, weights=values[keep], minlength=n_bins)[:n_bins]

    valid = counts > 0
    if valid.sum() < 4:
        raise ValueError("The regions do not share an interface within the band")
    distances = ((np.arange(n_bins) + 0.5) * bin_width - band)[valid]
    return distances, sums[valid] / counts[valid]


def lsf_from_esf(distances: np.ndarray, esf: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
    """Line spread function (absolute derivative of the ESF) on a uniform grid, normalized to unit area.

    The ESF may have gaps (empty bins); it is resampled on a uniform grid first.

    Returns:
        (grid, lsf, step) with `grid` and `step` in millimeters.
    """
    distances = np.asarray(distances, dtype=np.float64)
    esf = np.asarray(esf, dtype=np.float64)
    step = float(np.median(np.diff(distances)))
    grid = np.arange(distances[0], distances[-1] + step / 2, step)
    esf = np.interp(grid, distances, esf)
    lsf = np.abs(np.gradient(esf, step))
    area = lsf.sum() * step
    if area <= 0:
        raise ValueError("Flat edge profile: there is no edge in the selected band")
    return grid, lsf / area, step


def mtf_from_lsf(lsf: np.ndarray, step: float, oversampling: int = 8) -> Tuple[np.ndarray, np.ndarray]:
    """MTF = |FFT(LSF)| normalized so MTF(0) = 1. The LSF is Tukey-windowed (alpha 0.5) and zero-padded.

    A Hann window would narrow the LSF and overestimate the MTF by several percent for a band of a few sigmas.

    Returns:
        (frequencies, mtf) with frequencies in line pairs per millimeter (cycles/mm).
    """
    lsf = np.asarray(lsf, dtype=np.float64)
    windowed = lsf * tukey(lsf.size, 0.5)
    n = lsf.size * oversampling
    spectrum = np.abs(np.fft.rfft(windowed, n=n))
    return np.fft.rfftfreq(n, d=step), spectrum / spectrum[0]


def frequency_at_mtf(frequencies: np.ndarray, mtf: np.ndarray, level: float) -> float:
    """First spatial frequency where the MTF falls below `level` (linear interpolation), NaN if it never does."""
    below = np.nonzero(mtf < level)[0]
    if below.size == 0 or below[0] == 0:
        return float("nan")
    i = below[0]
    f0, f1, m0, m1 = frequencies[i - 1], frequencies[i], mtf[i - 1], mtf[i]
    return float(f0 + (m0 - level) / (m0 - m1) * (f1 - f0))


def lsf_fwhm(grid: np.ndarray, lsf: np.ndarray, smooth_sigma: float = 0.0) -> float:
    """Full width at half maximum of the LSF (linear interpolation at the half-height crossings).

    The LSF is the derivative of a binned profile, so it is noisy from bin to bin and its half-height crossings
    are fragile. With `smooth_sigma` (same unit as `grid`) the LSF is Gaussian-smoothed first and the smoothing is
    removed in quadrature from the width, which is exact for a Gaussian blur.
    """
    step = float(grid[1] - grid[0])
    if smooth_sigma > 0:
        lsf = ndimage.gaussian_filter1d(lsf, smooth_sigma / step, mode="nearest")
    peak = int(np.argmax(lsf))
    half = lsf[peak] / 2.0

    left = peak
    while left > 0 and lsf[left] > half:
        left -= 1
    right = peak
    while right < lsf.size - 1 and lsf[right] > half:
        right += 1
    if lsf[left] > half or lsf[right] > half:
        return float("nan")

    x_left = grid[left] + (half - lsf[left]) / (lsf[left + 1] - lsf[left]) * (grid[left + 1] - grid[left])
    x_right = grid[right - 1] + (lsf[right - 1] - half) / (lsf[right - 1] - lsf[right]) * (
        grid[right] - grid[right - 1]
    )
    width = float(x_right - x_left)
    if smooth_sigma > 0:
        excess = width**2 - (2.3548 * smooth_sigma) ** 2
        return float(np.sqrt(excess)) if excess > 0 else float("nan")
    return width


def edge_mtf(
    volume: np.ndarray,
    mask1: np.ndarray,
    mask2: np.ndarray,
    spacing: Tuple[float, float, float],
    band: float,
    bin_width: Optional[float] = None,
) -> dict:
    """MTF figures of merit from the interface between two regions.

    Returns a dict with the curves (`esf_*`, `lsf_*`, `frequencies`, `mtf`) and the scalars `f50`, `f10`
    (lp/mm), `resolvable_um50`/`resolvable_um10` (1 / (2 f), in micrometers) and `fwhm` (mm).
    """
    distances, esf = esf_from_masks(volume, mask1, mask2, spacing, band, bin_width)
    grid, lsf, step = lsf_from_esf(distances, esf)
    frequencies, mtf = mtf_from_lsf(lsf, step)
    f50 = frequency_at_mtf(frequencies, mtf, 0.5)
    f10 = frequency_at_mtf(frequencies, mtf, 0.1)
    um50, um10 = 500.0 / f50, 500.0 / f10  # 1 / (2 f) mm -> um
    return {
        "esf_distance": distances,
        "esf": esf,
        "lsf_distance": grid,
        "lsf": lsf,
        "frequencies": frequencies,
        "mtf": mtf,
        "f50": f50,
        "f10": f10,
        "resolvable_um50": um50,
        "resolvable_um10": um10,
        "fwhm": lsf_fwhm(grid, lsf, smooth_sigma=0.5 * float(np.mean(spacing[1:]))),
    }
