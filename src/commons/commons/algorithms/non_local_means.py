"""Non-local means denoising of volumes, in full 3D or as a stack of independent 2D slices along the first axis.

2D slices are filtered by skimage.restoration.denoise_nl_means in a thread pool.

3D volumes are filtered by a numba kernel that reproduces skimage's fast mode, split into small tiles processed by a
thread pool. skimage's 3D kernel streams the whole volume through memory once per patch shift, so it is limited by
memory bandwidth and barely scales with cores: a 1000^3 volume with the default parameters takes hours. Each tile here
carries its own margin and is filtered shift by shift while it stays in cache, so the result matches a single
full-volume call. This scales with the number of cores and filters a 1000^3 volume in about 15 minutes on a 16-core
desktop. Results differ from skimage by a small fraction of the noise, because skimage approximates the exponential of
the weights with errors of a few percent.
"""

import itertools
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

import numba as nb
import numpy as np
from skimage.restoration import denoise_nl_means

from commons.interactive.resources import available_cores

MODE_3D = "3d"
MODE_2D = "2d"

# Filter strength h as a multiple of the noise standard deviation. Recommended ranges are about 0.45-0.6 for 3D and
# 0.6-0.8 for 2D, since a 3D patch averages over more voxels and needs less strength for the same smoothing.
DEFAULT_STRENGTH = {MODE_3D: 1.5, MODE_2D: 1.7}
DEFAULT_PATCH_SIZE = 5
DEFAULT_PATCH_DISTANCE = 6

# Core shape of the 3D tiles. Small enough that a tile and its buffers stay in cache, large enough that the margin
# read around each tile is cheap. The last axis is the longest because the kernel vectorizes along it.
TILE_SHAPE_3D = (32, 64, 128)

# Patches with a normalized distance above this get no weight, as exp(-5) is negligible. Same cutoff as skimage.
_DISTANCE_CUTOFF = 5.0

# Ratio between the median absolute deviation and the standard deviation of a normal distribution
_MAD_TO_SIGMA = 0.6744897501960817

# ITU-R BT.601 luma weights, the same used by OpenCV's RGB to grey conversion
_LUMA_WEIGHTS = np.array([0.299, 0.587, 0.114], dtype=np.float32)


def rgb_to_greyscale(rgb: np.ndarray, dtype=np.float32) -> np.ndarray:
    """Converts an RGB or RGBA volume indexed as (slice, row, column, channel) to a greyscale volume of type dtype.

    Alpha is ignored. Integer types are rounded and clipped to their range. Slices are converted one at a time, so
    memory beyond the output is a single float slice.
    """
    if rgb.ndim != 4 or rgb.shape[-1] not in (3, 4):
        raise ValueError(f"Expected an RGB or RGBA volume, got shape {rgb.shape}.")
    grey = np.empty(rgb.shape[:-1], dtype=dtype)
    is_integer = np.issubdtype(grey.dtype, np.integer)
    if is_integer:
        limits = np.iinfo(grey.dtype)
    for i in range(rgb.shape[0]):
        grey_slice = rgb[i, ..., :3].astype(np.float32) @ _LUMA_WEIGHTS
        if is_integer:
            grey_slice = np.clip(np.rint(grey_slice), limits.min, limits.max)
        grey[i] = grey_slice
    return grey


def estimate_noise_sigma(array: np.ndarray, mode: str = MODE_3D) -> float:
    """Estimates the standard deviation of Gaussian noise in an image.

    Uses the median absolute deviation of the finest diagonal Haar wavelet detail coefficients (Donoho's estimator),
    the same approach as skimage.restoration.estimate_sigma but without depending on PyWavelets. In 2D mode the
    coefficients are taken in-plane only, so the estimate matches the noise seen by a slice-by-slice filter.
    Coefficients that are exactly zero, typically from constant padding around the sample, are ignored.
    """
    axes = range(array.ndim) if mode == MODE_3D else range(1, array.ndim)
    detail = np.asarray(array, dtype=np.float32)
    for axis in axes:
        length = detail.shape[axis] // 2 * 2
        if length == 0:
            continue
        even = [slice(None)] * detail.ndim
        odd = [slice(None)] * detail.ndim
        even[axis] = slice(0, length, 2)
        odd[axis] = slice(1, length, 2)
        detail = (detail[tuple(even)] - detail[tuple(odd)]) / np.float32(math.sqrt(2))

    detail = np.abs(detail[detail != 0])
    if detail.size == 0:
        return 0.0
    return float(np.median(detail) / _MAD_TO_SIGMA)


@nb.njit(nogil=True, fastmath=True, cache=True, inline="always")
def _exp_neg(x):  # pragma: no cover - compiled by numba
    """exp(-x) for 0 <= x <= _DISTANCE_CUTOFF, with relative error below 1e-4.

    Degree 6 Taylor polynomial of exp(-x / 8), raised to the 8th power. Unlike np.exp, it vectorizes without SVML, which
    makes the 3D kernel about 40% faster. skimage itself uses a coarser approximation, with errors of a few percent.
    """
    y = -x * np.float32(0.125)
    p = np.float32(1 / 720)
    p = p * y + np.float32(1 / 120)
    p = p * y + np.float32(1 / 24)
    p = p * y + np.float32(1 / 6)
    p = p * y + np.float32(0.5)
    p = p * y + np.float32(1.0)
    p = p * y + np.float32(1.0)
    p = p * p
    p = p * p
    return p * p


@nb.njit(nogil=True, fastmath=True, cache=True)
def _nlm_3d_tile(tile, half_patch, distance, inv_s3_h2, noise_offset):  # pragma: no cover - compiled by numba
    """Filters the core of a tile padded by distance + half_patch voxels on every side.

    Weights follow skimage's fast mode: the patch distance is the sum of squared differences over a box of
    2 * half_patch voxels per axis (offsets 1 - half_patch to half_patch), minus the expected noise contribution
    noise_offset, clipped at zero and scaled by inv_s3_h2. Each shift is processed plane by plane: the squared
    differences of a plane are box-summed along columns and rows, and the last 2 * half_patch planes are kept in a
    ring to sum along planes. Box sums are computed directly rather than as running sums, to avoid the float32
    cancellation errors of the latter on large intensities.
    """
    box = 2 * half_patch
    margin = distance + half_patch
    n_pln = tile.shape[0] - 2 * margin
    n_row = tile.shape[1] - 2 * margin
    n_col = tile.shape[2] - 2 * margin
    result = np.zeros((n_pln, n_row, n_col), np.float32)
    weights = np.zeros((n_pln, n_row, n_col), np.float32)
    zero = np.float32(0.0)
    cutoff = np.float32(_DISTANCE_CUTOFF)

    if box == 0:
        # A patch of a single voxel has an empty box in skimage, so every shift gets the same weight
        for t_pln in range(-distance, distance + 1):
            for t_row in range(-distance, distance + 1):
                for t_col in range(-distance, distance + 1):
                    for pln in range(n_pln):
                        for row in range(n_row):
                            for col in range(n_col):
                                result[pln, row, col] += tile[
                                    pln + margin + t_pln, row + margin + t_row, col + margin + t_col
                                ]
        return result / np.float32((2 * distance + 1) ** 3)

    # Squared differences cover the core extended by the patch box
    n_diff_row = n_row + box - 1
    n_diff_col = n_col + box - 1
    first = distance + 1  # tile index of the first voxel of the extended core
    diff = np.empty((n_diff_row, n_diff_col), np.float32)
    col_sums = np.empty((n_diff_row, n_col), np.float32)
    plane_sums = np.empty((box, n_row, n_col), np.float32)

    for t_pln in range(-distance, distance + 1):
        for t_row in range(-distance, distance + 1):
            for t_col in range(-distance, distance + 1):
                for k in range(n_pln + box - 1):
                    pln = first + k
                    for i in range(n_diff_row):
                        row = first + i
                        for j in range(n_diff_col):
                            v = tile[pln, row, first + j] - tile[pln + t_pln, row + t_row, first + j + t_col]
                            diff[i, j] = v * v
                    for i in range(n_diff_row):
                        for j in range(n_col):
                            total = diff[i, j]
                            for b in range(1, box):
                                total += diff[i, j + b]
                            col_sums[i, j] = total
                    slot = k % box
                    for i in range(n_row):
                        for j in range(n_col):
                            total = col_sums[i, j]
                            for b in range(1, box):
                                total += col_sums[i + b, j]
                            plane_sums[slot, i, j] = total
                    if k < box - 1:
                        continue
                    out_pln = k - (box - 1)
                    src_pln = out_pln + margin + t_pln
                    for i in range(n_row):
                        src_row = i + margin + t_row
                        for j in range(n_col):
                            total = plane_sums[0, i, j]
                            for b in range(1, box):
                                total += plane_sums[b, i, j]
                            patch_distance = max(total - noise_offset, zero) * inv_s3_h2
                            weight = _exp_neg(patch_distance) if patch_distance <= cutoff else zero
                            weights[out_pln, i, j] += weight
                            result[out_pln, i, j] += weight * tile[src_pln, src_row, j + margin + t_col]
    return result / weights


def _reflect_indices(start: int, stop: int, size: int) -> np.ndarray:
    """Indices of positions start to stop - 1 along an axis of the given size, reflected like np.pad(mode='reflect')."""
    positions = np.arange(start, stop)
    if size == 1:
        return np.zeros_like(positions)
    period = 2 * (size - 1)
    positions = np.abs(positions) % period
    return np.where(positions >= size, period - positions, positions)


def _non_local_means_3d(
    image: np.ndarray,
    h: float,
    sigma: float,
    patch_size: int,
    patch_distance: int,
    workers: int,
    report: Callable[[float], None],
) -> np.ndarray:
    # Same patch geometry and weights as skimage.restoration.denoise_nl_means with fast_mode=True
    if patch_size % 2 == 0:
        patch_size += 1
    half_patch = patch_size // 2
    margin = patch_distance + half_patch
    inv_s3_h2 = np.float32(1.0 / (patch_size**3 * h * h))
    noise_offset = np.float32((2 * half_patch) ** 3 * 2 * sigma * sigma)

    output = np.empty_like(image)
    tile_shape = [min(t, n) for t, n in zip(TILE_SHAPE_3D, image.shape)]
    origins = itertools.product(*[range(0, n, t) for n, t in zip(image.shape, tile_shape)])

    def filter_tile(origin):
        core = tuple(slice(o, min(o + t, n)) for o, t, n in zip(origin, tile_shape, image.shape))
        indices = [_reflect_indices(c.start - margin, c.stop + margin, n) for c, n in zip(core, image.shape)]
        output[core] = _nlm_3d_tile(image[np.ix_(*indices)], half_patch, patch_distance, inv_s3_h2, noise_offset)
        return (core[0].stop - core[0].start) * (core[1].stop - core[1].start) * (core[2].stop - core[2].start)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(filter_tile, origin) for origin in origins]
        for future in as_completed(futures):
            report(future.result() / image.size)
    return output


def non_local_means(
    array: np.ndarray,
    h: float,
    sigma: float,
    mode: str = MODE_3D,
    patch_size: int = DEFAULT_PATCH_SIZE,
    patch_distance: int = DEFAULT_PATCH_DISTANCE,
    fast_mode: bool = True,
    workers: Optional[int] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> np.ndarray:
    """Applies the non-local means filter to a 3D array, returning a float32 array in the input intensity range.

    Args:
        array: volume indexed as (slice, row, column).
        h: filter strength, in intensity units. Usually a multiple of sigma (see DEFAULT_STRENGTH).
        sigma: noise standard deviation, in intensity units. Used to make the patch weights more robust.
        mode: MODE_3D to filter the full volume, MODE_2D to filter each slice along the first axis independently.
        patch_size: side, in voxels, of the patches compared to compute weights.
        patch_distance: maximal distance, in voxels, to search for similar patches.
        fast_mode: in 2D, use skimage's faster, box-weighted patch distance instead of the Gaussian-weighted one.
            3D always uses the box-weighted distance, since the Gaussian-weighted one is too slow for volumes.
        workers: number of parallel threads. Defaults to the number of physical cores available.
        progress_callback: called with the completed fraction, from 0 to 1.
    """
    if mode not in (MODE_3D, MODE_2D):
        raise ValueError(f"Invalid mode '{mode}'. Expected '{MODE_3D}' or '{MODE_2D}'.")
    if array.ndim != 3:
        raise ValueError(f"Expected a 3D array, got {array.ndim} dimensions.")

    image = np.asarray(array, dtype=np.float32)
    if h <= 0:
        return image.copy()

    # A single slice has no 3D neighborhood
    if image.shape[0] == 1:
        mode = MODE_2D

    if workers is None:
        workers = available_cores()
    done = 0.0

    def report(fraction):
        nonlocal done
        done = min(done + fraction, 1.0)
        if progress_callback is not None:
            progress_callback(done)

    if mode == MODE_3D:
        return _non_local_means_3d(image, h, sigma, patch_size, patch_distance, workers, report)

    nlm_kwargs = dict(
        patch_size=patch_size,
        patch_distance=patch_distance,
        h=h,
        sigma=sigma,
        fast_mode=fast_mode,
        preserve_range=True,
    )
    output = np.empty_like(image)
    n_slices = image.shape[0]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(denoise_nl_means, image[i], **nlm_kwargs): i for i in range(n_slices)}
        for future in as_completed(futures):
            output[futures[future]] = future.result()
            report(1 / n_slices)
    return output


def denoise(
    array: np.ndarray,
    strength: float,
    sigma: float = 0,
    mode: str = MODE_3D,
    patch_size: int = DEFAULT_PATCH_SIZE,
    patch_distance: int = DEFAULT_PATCH_DISTANCE,
    fast_mode: bool = True,
    null_value: Optional[float] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> tuple[np.ndarray, float, float]:
    """Filters a 3D array with h = strength * sigma, and returns the result in the array dtype, sigma and h.

    Args:
        sigma: noise standard deviation, estimated from the array if not positive.
        null_value: voxels with this value are kept unchanged.
        progress_callback: called with the completed fraction, from 0 to 1.
        Other arguments as in non_local_means.
    """
    image = np.asarray(array, dtype=np.float32)
    if sigma <= 0:
        sigma = estimate_noise_sigma(image, mode)
    h = strength * sigma
    output = non_local_means(
        image,
        h=h,
        sigma=sigma,
        mode=mode,
        patch_size=patch_size,
        patch_distance=patch_distance,
        fast_mode=fast_mode,
        progress_callback=progress_callback,
    )

    if null_value is not None:
        output[image == null_value] = null_value

    if np.issubdtype(array.dtype, np.integer):
        limits = np.iinfo(array.dtype)
        output = np.clip(np.rint(output), limits.min, limits.max)
    return output.astype(array.dtype, copy=False), sigma, h
