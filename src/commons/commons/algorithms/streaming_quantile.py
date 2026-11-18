"""Exact order statistics of very large arrays with bounded memory.

The array is visited in fixed-size chunks, so no copy of the whole volume is ever made (unlike ``np.partition``, which
needs one or two full copies). Null and non-finite (NaN, +-inf) voxels are dropped chunk by chunk.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional, Tuple

import numpy as np

CHUNK_SIZE = 1 << 22


def availableWorkers() -> int:
    """Number of CPUs this process may run on.

    On Linux the scheduler affinity is the exact count (it respects cgroups/cpusets of cluster jobs, unlike
    `os.cpu_count`, which reports the whole node); elsewhere (Windows, macOS) it falls back to `os.cpu_count`.
    """
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError:
        return max(1, os.cpu_count() or 1)


# NumPy releases the GIL in the heavy per-chunk operations, so threads scale without copying the volume.
DEFAULT_WORKERS = availableWorkers()
HISTOGRAM_BINS = 1 << 16
# Largest integer value span that is counted exactly, one bin per value.
EXACT_INTEGER_SPAN = 1 << 20
# Largest set of values that is gathered and partitioned in memory.
GATHER_LIMIT = 1 << 22


def _validChunk(flat: np.ndarray, start: int, exclude: Optional[float], chunkSize: int) -> np.ndarray:
    chunk = flat[start : start + chunkSize]
    keep = None
    if exclude is not None:
        keep = chunk != exclude
    if np.issubdtype(flat.dtype, np.floating):
        finite = np.isfinite(chunk)
        keep = finite if keep is None else keep & finite
    return chunk if keep is None else chunk[keep]


def _accumulate(
    values: np.ndarray,
    exclude: Optional[float],
    chunkSize: int,
    process: Callable,
    merge: Callable,
    initial,
    workers: int = 1,
):
    """Runs `process(chunk)` on every valid chunk and folds the results with `merge`.

    With `workers` > 1 the chunks are processed by a thread pool, so at most `workers` chunks are alive at once.
    `merge` always runs on the calling thread, in chunk order.
    """
    flat = values.reshape(-1)

    def run(start):
        chunk = _validChunk(flat, start, exclude, chunkSize)
        return process(chunk) if chunk.size else None

    starts = range(0, flat.size, chunkSize)
    result = initial
    if workers <= 1:
        results = map(run, starts)
        for partial in results:
            if partial is not None:
                result = merge(result, partial)
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for partial in pool.map(run, starts):
            if partial is not None:
                result = merge(result, partial)
    return result


def validStatistics(
    values: np.ndarray,
    referenceValue: float,
    exclude: Optional[float] = None,
    chunkSize: int = CHUNK_SIZE,
    workers: int = DEFAULT_WORKERS,
) -> Tuple[int, Optional[float], Optional[float], int, int]:
    """Single pass over the valid voxels.

    Returns:
        (count, min, max, count of voxels < referenceValue, count of voxels <= referenceValue)
    """

    def process(chunk):
        return (
            chunk.size,
            chunk.min(),
            chunk.max(),
            int(np.count_nonzero(chunk < referenceValue)),
            int(np.count_nonzero(chunk <= referenceValue)),
        )

    def merge(acc, new):
        if acc is None:
            return new
        return (acc[0] + new[0], min(acc[1], new[1]), max(acc[2], new[2]), acc[3] + new[3], acc[4] + new[4])

    result = _accumulate(values, exclude, chunkSize, process, merge, None, workers)
    if result is None:
        return 0, None, None, 0, 0
    count, vmin, vmax, below, belowOrEqual = result
    return count, vmin.item(), vmax.item(), below, belowOrEqual


def _binIndex(chunk: np.ndarray, low: float, scale: float, bins: int) -> np.ndarray:
    index = ((chunk.astype(np.float64) - low) * scale).astype(np.int64)
    return np.minimum(index, bins - 1)


def kthSmallest(
    values: np.ndarray,
    kth: int,
    vmin: float,
    vmax: float,
    exclude: Optional[float] = None,
    chunkSize: int = CHUNK_SIZE,
    bins: int = HISTOGRAM_BINS,
    gatherLimit: int = GATHER_LIMIT,
    workers: int = DEFAULT_WORKERS,
):
    """Value at 0-based rank `kth` among the valid voxels, i.e. ``np.sort(valid)[kth]``, computed exactly.

    `vmin` and `vmax` are the extremes of the valid voxels (see `validStatistics`). Each round histograms the voxels
    inside [low, high] and keeps only the bin that holds the rank, shrinking the range until the few remaining voxels
    fit in memory.
    """
    low, high = vmin, vmax
    isInteger = np.issubdtype(values.dtype, np.integer)

    while low != high:
        if isInteger and high - low < EXACT_INTEGER_SPAN:
            # One bin per integer value: the answer is read directly from the cumulative counts.
            def countExact(chunk):
                inside = chunk[(chunk >= low) & (chunk <= high)]
                return np.bincount(inside.astype(np.int64) - int(low), minlength=int(high - low) + 1)

            counts = _accumulate(values, exclude, chunkSize, countExact, np.add, 0, workers)
            return low + int(np.searchsorted(np.cumsum(counts), kth, side="right"))

        scale = bins / (high - low)

        def histogram(chunk):
            inside = chunk[(chunk >= low) & (chunk <= high)]
            return np.bincount(_binIndex(inside, low, scale, bins), minlength=bins)

        counts = _accumulate(values, exclude, chunkSize, histogram, np.add, 0, workers)
        cumulative = np.cumsum(counts)
        target = int(np.searchsorted(cumulative, kth, side="right"))
        kth -= int(cumulative[target - 1]) if target > 0 else 0

        def inTargetBin(chunk):
            inside = chunk[(chunk >= low) & (chunk <= high)]
            return inside[_binIndex(inside, low, scale, bins) == target]

        if counts[target] <= gatherLimit:
            parts = _accumulate(values, exclude, chunkSize, lambda c: [inTargetBin(c)], lambda a, b: a + b, [], workers)
            gathered = np.concatenate(parts)
            return np.partition(gathered, kth)[kth].item()

        # The bin is still too populated: narrow the range to the values it actually holds.
        def extremes(chunk):
            selected = inTargetBin(chunk)
            return (selected.min(), selected.max()) if selected.size else None

        def merge(acc, new):
            if new is None:
                return acc
            return new if acc is None else (min(acc[0], new[0]), max(acc[1], new[1]))

        low, high = _accumulate(values, exclude, chunkSize, extremes, merge, None, workers)
        low, high = low.item(), high.item()

    return low


# Largest number of voxels the one-pass window may gather (about 4 GB of float32, times the 3 live copies of gathering,
# concatenating and partitioning). With the usual sample the window holds a few percent of the volume, so only volumes
# of hundreds of GB come close; larger windows fall back to the multi-pass algorithm.
WINDOW_LIMIT = 1 << 30
# A sample of the volume gives a rank estimate good to ~sqrt(p(1-p)/n); the window spans this many standard errors.
WINDOW_SIGMAS = 4.0
MIN_SAMPLE_SIZE = 1000

_MISS = object()


def targetRank(count: int, below: int, belowOrEqual: int, proportion: float, isMaxLimit: bool) -> int:
    """0-based rank, among `count` valid voxels, of the limit that makes a segment hold `proportion` of them.

    If `isMaxLimit`, `below` voxels (< the segment's min) stay out and the segment extends until it holds
    `proportion`; otherwise `belowOrEqual` voxels (<= the segment's max) are fixed and the min goes back.
    """
    targetVoxels = proportion * count
    if isMaxLimit:
        rank = int(np.ceil(below + targetVoxels)) - 1
    else:
        rank = int(np.round(belowOrEqual - targetVoxels))
    return min(max(rank, 0), count - 1)


def _windowedLimit(values, proportion, fixedLimit, isMaxLimit, exclude, sample, chunkSize, workers, windowLimit):
    """One pass over the volume: counts the voxels and gathers only a window around the expected rank.

    The window comes from a sample of the volume. Whatever the sample says, the result is verified against the exact
    counts, so it is either exact or `_MISS` (and the caller falls back to the multi-pass algorithm).
    """
    ordered = np.sort(_validChunk(sample.reshape(-1), 0, exclude, sample.size))
    n = ordered.size
    if n < MIN_SAMPLE_SIZE:
        return _MISS

    fixedFraction = np.searchsorted(ordered, fixedLimit, side="left" if isMaxLimit else "right") / n
    expected = fixedFraction + proportion if isMaxLimit else fixedFraction - proportion
    expected = min(max(expected, 0.0), 1.0)
    variance = (fixedFraction * (1 - fixedFraction) + expected * (1 - expected)) / n
    margin = WINDOW_SIGMAS * np.sqrt(variance) + 1.0 / n
    lowFraction, highFraction = expected - margin, expected + margin

    if values.size * (min(highFraction, 1.0) - max(lowFraction, 0.0)) > windowLimit:
        return _MISS
    windowLow = None if lowFraction <= 0 else ordered[int(np.floor(lowFraction * (n - 1)))]
    windowHigh = None if highFraction >= 1 else ordered[int(np.ceil(highFraction * (n - 1)))]

    def process(chunk):
        inside = np.ones(chunk.size, dtype=bool)
        belowWindow = 0
        if windowLow is not None:
            inside &= chunk >= windowLow
            belowWindow = int(np.count_nonzero(chunk < windowLow))
        if windowHigh is not None:
            inside &= chunk <= windowHigh
        return (
            chunk.size,
            int(np.count_nonzero(chunk < fixedLimit)),
            int(np.count_nonzero(chunk <= fixedLimit)),
            belowWindow,
            [chunk[inside]],
        )

    def merge(acc, new):
        return tuple(a + b for a, b in zip(acc, new))

    count, below, belowOrEqual, belowWindow, parts = _accumulate(
        values, exclude, chunkSize, process, merge, (0, 0, 0, 0, []), workers
    )
    if count == 0:
        return None

    rank = targetRank(count, below, belowOrEqual, proportion, isMaxLimit) - belowWindow
    gathered = np.concatenate(parts)
    if not 0 <= rank < gathered.size:
        return _MISS
    return np.partition(gathered, rank)[rank].item()


def proportionLimit(
    values: np.ndarray,
    proportion: float,
    fixedLimit: float,
    isMaxLimit: bool,
    exclude: Optional[float] = None,
    sample: Optional[np.ndarray] = None,
    chunkSize: int = CHUNK_SIZE,
    workers: int = DEFAULT_WORKERS,
    windowLimit: int = WINDOW_LIMIT,
):
    """Limit of a segment such that it holds `proportion` of the valid voxels, or None if there are none.

    If `isMaxLimit`, `fixedLimit` is the segment's min and the returned value is its max; otherwise `fixedLimit` is
    the segment's max and the returned value is its min. The result is always exact. When a `sample` of the volume is
    given, it is usually found in a single pass; otherwise (or if the sample misleads) a multi-pass histogram is used.
    """
    if sample is not None:
        result = _windowedLimit(
            values, proportion, fixedLimit, isMaxLimit, exclude, sample, chunkSize, workers, windowLimit
        )
        if result is not _MISS:
            return result

    count, vmin, vmax, below, belowOrEqual = validStatistics(values, fixedLimit, exclude, chunkSize, workers)
    if count == 0:
        return None
    rank = targetRank(count, below, belowOrEqual, proportion, isMaxLimit)
    return kthSmallest(values, rank, vmin, vmax, exclude, chunkSize, workers=workers)
