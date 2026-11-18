import numpy as np
import pytest
from scipy import ndimage

from commons.lmath.image_quality_api import (
    CnrOptions,
    CuppingOptions,
    MtfOptions,
    QualityError,
    QualityOptions,
    measure_quality,
)

SPACING = 0.01
SIGMA = 1.5
NAMES = {"tube": "Tube", "outside": "Outside", "core": "Core", "empty": "Empty"}


@pytest.fixture
def scan():
    """A bright tube (radius 40 voxels, blurred edge, noise) in a dark background, plus a core and an empty segment."""
    size, depth, radius = 128, 6, 40
    y, x = np.mgrid[:size, :size]
    r = np.hypot(y - (size - 1) / 2, x - (size - 1) / 2)
    tube = r <= radius
    image = ndimage.gaussian_filter(tube.astype(float) * 1000.0, SIGMA) + np.random.default_rng(0).normal(
        0, 10, (size, size)
    )
    volume = np.repeat(image[None], depth, axis=0).astype(np.float32)
    planes = {"tube": tube, "outside": ~tube, "core": r <= 10, "empty": np.zeros_like(tube)}
    masks = {name: np.repeat(plane[None], depth, axis=0) for name, plane in planes.items()}

    def measure(options, metadata=None):
        return measure_quality(
            volume, (SPACING,) * 3, masks.__getitem__, NAMES.__getitem__, options, label="scan", metadata=metadata
        )

    return measure


def test_every_metric_in_a_single_run(scan):
    options = QualityOptions(
        snr=["tube", "outside"],
        cnr=CnrOptions("tube", "outside"),
        cupping=CuppingOptions(["tube"]),
        mtf=MtfOptions("tube", "outside", band_voxels=10),
    )
    result = scan(options, {"kV": "60"})
    row = result.metrics

    assert result.warnings == []
    assert row["kV"] == "60" and row["Volume"] == "scan"
    assert row["Voxel size (um)"] == pytest.approx(10.0)
    assert {"SNR [Tube]", "SNR [Outside]", "CNR", "Cupping (%)", "Resolvable at 50% (um)"} <= set(row)
    assert row["CNR phases"] == "Tube vs Outside"
    assert row["Cupping segment"] == "Tube" and row["MTF edge"] == "Tube | Outside"
    assert row["CNR"] > 5  # the tube std includes its blurred edge ring
    assert abs(row["Cupping (%)"]) < 3.0
    expected_f50 = np.sqrt(2 * np.log(2)) / (2 * np.pi * SIGMA * SPACING)
    assert row["Resolvable at 50% (um)"] == pytest.approx(500.0 / expected_f50, rel=0.05)
    assert row["LSF FWHM (um)"] == pytest.approx(2.355 * SIGMA * 10.0, rel=0.08)
    assert set(result.curves) == {"radial", "mtf"}
    assert 500.0 / result.curves["mtf"]["f50"] == row["Resolvable at 50% (um)"]


def test_cupping_of_several_segments_uses_their_union_and_skips_empty_ones(scan):
    single = scan(QualityOptions(cupping=CuppingOptions(["tube"]))).metrics
    union = scan(QualityOptions(cupping=CuppingOptions(["tube", "core", "empty"]))).metrics  # core is inside the tube

    assert union["Cupping segment"] == "Tube + Core + Empty"
    assert union["Cupping (%)"] == pytest.approx(single["Cupping (%)"])
    assert scan(QualityOptions(cupping=CuppingOptions(["tube"], name="Sample"))).metrics["Cupping segment"] == "Sample"


def test_cupping_fails_when_every_segment_is_empty(scan):
    with pytest.raises(QualityError, match="selected segments are empty"):
        scan(QualityOptions(cupping=CuppingOptions(["empty"])))


def test_metrics_that_were_not_requested_are_left_out(scan):
    result = scan(QualityOptions(snr=["core"]))
    assert "SNR [Core]" in result.metrics
    assert not {"CNR", "Cupping (%)", "Resolvable at 50% (um)"} & set(result.metrics)
    assert result.curves == {}


def test_a_failing_metric_does_not_stop_the_others(scan):
    result = scan(QualityOptions(snr=["core"], mtf=MtfOptions("core", "outside", band_voxels=10)))

    assert "SNR [Core]" in result.metrics and "Resolvable at 50% (um)" not in result.metrics
    assert len(result.warnings) == 1 and result.warnings[0].startswith("MTF:")
    assert "mtf" not in result.curves


def test_an_empty_segment_is_reported_by_name(scan):
    result = scan(QualityOptions(snr=["tube", "empty"]))
    assert "SNR [Tube]" in result.metrics and "SNR [Empty]" not in result.metrics
    assert result.warnings == ["SNR: Segment 'Empty' is empty."]


def test_error_when_nothing_could_be_computed(scan):
    with pytest.raises(QualityError, match="No metric could be computed"):
        scan(QualityOptions(mtf=MtfOptions("core", "outside", band_voxels=10)))


def test_masks_are_requested_once_per_segment():
    volume = np.random.default_rng(0).normal(100, 5, (4, 16, 16)).astype(np.float32)
    mask = np.zeros(volume.shape, bool)
    mask[:, 4:12, 4:12] = True
    calls = []

    def provider(segment_id):
        calls.append(segment_id)
        return mask if segment_id == "a" else ~mask

    options = QualityOptions(snr=["a", "b"], cnr=CnrOptions("a", "b"))
    measure_quality(volume, (1, 1, 1), provider, str, options)
    assert sorted(calls) == ["a", "b"]
