import numpy as np
import pytest

from commons.algorithms import streaming_quantile
from commons.algorithms.streaming_quantile import kthSmallest, proportionLimit, targetRank, validStatistics


def _valid(values, exclude=None):
    flat = values.reshape(-1)
    keep = np.ones(flat.size, dtype=bool)
    if exclude is not None:
        keep &= flat != exclude
    if np.issubdtype(flat.dtype, np.floating):
        keep &= np.isfinite(flat)
    return flat[keep]


def _datasets():
    rng = np.random.default_rng(0)
    skewed = np.concatenate([rng.normal(1000, 0.01, 50_000), rng.uniform(0, 5e6, 50)]).astype(np.float64)
    return {
        "uint16": rng.integers(0, 65535, (30, 40, 50), dtype=np.uint16),
        "int16_negative": rng.integers(-30000, 30000, 60_000, dtype=np.int16),
        "int32_wide_span": rng.integers(-(2**30), 2**30, 60_000, dtype=np.int32),
        "float32": rng.normal(0, 100, (20, 30, 40)).astype(np.float32),
        "float64_skewed": skewed,
        "few_distinct_values": rng.choice([3, 7, 7, 7, 9], 50_000).astype(np.uint8),
        "constant": np.full(5_000, 4.5),
    }


@pytest.mark.parametrize("name", list(_datasets()))
@pytest.mark.parametrize("quantile", [0.0, 0.001, 0.15, 0.5, 0.97, 1.0])
def test_kth_smallest_matches_sort(name, quantile):
    values = _datasets()[name]
    valid = _valid(values)
    kth = int(quantile * (valid.size - 1))
    count, vmin, vmax, _, _ = validStatistics(values, 0, chunkSize=997)

    # Tiny chunks and bins force several chunks, several refinement rounds and the gather step.
    result = kthSmallest(values, kth, vmin, vmax, chunkSize=997, bins=64, gatherLimit=100)

    assert count == valid.size
    assert result == np.sort(valid)[kth]


def test_null_and_nan_voxels_are_ignored():
    values = np.array([-1.0] * 40 + [np.nan] * 10 + list(np.arange(100.0)))
    count, vmin, vmax, below, belowOrEqual = validStatistics(values, 20.0, exclude=-1.0, chunkSize=16)

    assert (count, vmin, vmax, below, belowOrEqual) == (100, 0.0, 99.0, 20, 21)
    assert kthSmallest(values, 14, vmin, vmax, exclude=-1.0, chunkSize=16, bins=8, gatherLimit=4) == 14.0


def test_infinite_voxels_are_ignored():
    values = np.array([np.inf, -np.inf] + list(np.arange(100.0)), dtype=np.float32)

    assert proportionLimit(values, 0.5, 0.0, True, chunkSize=16, workers=1) == 49.0


def test_all_voxels_null_yields_no_statistics():
    assert validStatistics(np.full(10, -1), 0, exclude=-1) == (0, None, None, 0, 0)


@pytest.mark.parametrize("name", ["uint16", "float64_skewed", "int32_wide_span"])
def test_parallel_result_equals_serial_result(name):
    values = _datasets()[name]
    kwargs = dict(chunkSize=997, bins=64, gatherLimit=100)
    kth = values.size // 3

    serialStats = validStatistics(values, 0, chunkSize=997, workers=1)
    parallelStats = validStatistics(values, 0, chunkSize=997, workers=4)

    assert serialStats == parallelStats
    count, vmin, vmax, _, _ = parallelStats
    assert kthSmallest(values, kth, vmin, vmax, workers=1, **kwargs) == kthSmallest(
        values, kth, vmin, vmax, workers=4, **kwargs
    )


def _expectedLimit(values, proportion, fixedLimit, isMaxLimit, exclude=None):
    valid = np.sort(_valid(values, exclude))
    below = np.count_nonzero(valid < fixedLimit)
    belowOrEqual = np.count_nonzero(valid <= fixedLimit)
    return valid[targetRank(valid.size, below, belowOrEqual, proportion, isMaxLimit)]


@pytest.mark.parametrize("name", ["uint16", "float32", "float64_skewed", "few_distinct_values"])
@pytest.mark.parametrize("isMaxLimit, proportion", [(True, 0.15), (True, 0.5), (False, 0.15), (True, 0.97)])
@pytest.mark.parametrize("workers", [1, 4])
def test_proportion_limit_with_sample_is_exact(name, isMaxLimit, proportion, workers):
    values = _datasets()[name]
    sample = np.random.default_rng(1).choice(values.reshape(-1), 5_000, replace=False)
    fixedLimit = np.quantile(values, 0.2 if isMaxLimit else 0.8)

    result = proportionLimit(values, proportion, fixedLimit, isMaxLimit, sample=sample, chunkSize=997, workers=workers)

    assert result == _expectedLimit(values, proportion, fixedLimit, isMaxLimit)


def test_proportion_limit_with_good_sample_needs_a_single_pass(monkeypatch):
    values = np.random.default_rng(0).normal(0, 1, 200_000).astype(np.float32)
    sample = np.random.default_rng(1).choice(values, 30_000, replace=False)
    calls = []
    original = streaming_quantile._accumulate
    monkeypatch.setattr(
        streaming_quantile, "_accumulate", lambda *args, **kwargs: calls.append(1) or original(*args, **kwargs)
    )

    result = proportionLimit(values, 0.15, -0.5, True, sample=sample, chunkSize=997)

    assert len(calls) == 1
    assert result == _expectedLimit(values, 0.15, -0.5, True)


def test_proportion_limit_falls_back_when_the_sample_misleads():
    values = np.random.default_rng(0).normal(0, 1, 100_000).astype(np.float32)
    misleading = np.random.default_rng(1).normal(5, 0.1, 5_000)

    result = proportionLimit(values, 0.3, -0.5, True, sample=misleading, chunkSize=997)

    assert result == _expectedLimit(values, 0.3, -0.5, True)


def test_proportion_limit_falls_back_when_the_window_is_too_large():
    values = np.random.default_rng(0).normal(0, 1, 100_000).astype(np.float32)
    sample = np.random.default_rng(1).choice(values, 5_000, replace=False)

    result = proportionLimit(values, 0.3, -0.5, True, sample=sample, chunkSize=997, windowLimit=10)

    assert result == _expectedLimit(values, 0.3, -0.5, True)


def test_proportion_limit_ignores_null_voxels_and_reports_when_none_are_valid():
    values = np.array([-1.0] * 400 + list(np.arange(1000.0)))
    sample = np.random.default_rng(1).choice(values, 1_200, replace=False)

    assert proportionLimit(values, 0.15, 0.0, True, exclude=-1.0, sample=sample) == _expectedLimit(
        values, 0.15, 0.0, True, exclude=-1.0
    )
    assert proportionLimit(np.full(10, -1.0), 0.15, 0.0, True, exclude=-1.0) is None
