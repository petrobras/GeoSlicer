import numpy as np
import pytest
from scipy.special import erf

from commons.lmath.image_quality import (
    cnr,
    cupping_percent,
    edge_mtf,
    frequency_at_mtf,
    radial_profile,
    region_stats,
    snr,
)

RNG = np.random.default_rng(0)


def test_snr_matches_mean_over_std():
    values = RNG.normal(loc=100.0, scale=5.0, size=200_000)
    assert snr(values) == pytest.approx(20.0, rel=0.02)


def test_snr_degenerate_inputs():
    assert np.isnan(snr(np.array([1.0])))
    assert snr(np.full(10, 3.0)) == float("inf")


def test_cnr_matches_formula():
    a = RNG.normal(100.0, 4.0, size=200_000)
    b = RNG.normal(60.0, 3.0, size=200_000)
    assert cnr(a, b) == pytest.approx(40.0 / 5.0, rel=0.02)
    assert cnr(a, b) == pytest.approx(cnr(b, a))


def _disc_volume(radius=20, size=64, depth=5, profile=lambda rr: np.full_like(rr, 100.0)):
    y, x = np.mgrid[:size, :size]
    rr = np.hypot(y - (size - 1) / 2, x - (size - 1) / 2) / radius
    inside = rr <= 1.0
    image = np.where(inside, profile(rr), 0.0)
    return np.repeat(image[None], depth, axis=0), np.repeat(inside[None], depth, axis=0)


def test_flat_disc_has_no_cupping():
    volume, mask = _disc_volume()
    radii, profile, radius = radial_profile(volume, mask, (1.0, 1.0, 1.0))
    assert radius == pytest.approx(20.0, rel=0.03)
    assert cupping_percent(radii, profile, radius) == pytest.approx(0.0, abs=1e-9)


def test_parabolic_disc_cupping():
    # 20% drop at the center, edge (r in 0.8..0.95) is close to the nominal 100
    volume, mask = _disc_volume(profile=lambda rr: 100.0 - 20.0 * (1.0 - rr**2))
    radii, profile, radius = radial_profile(volume, mask, (1.0, 1.0, 1.0))
    value = cupping_percent(radii, profile, radius)
    assert 15.0 < value < 20.0


def test_radial_profile_uses_physical_spacing():
    volume, mask = _disc_volume()
    _, _, radius = radial_profile(volume, mask, (0.5, 0.01, 0.01))
    assert radius == pytest.approx(0.2, rel=0.03)


def test_frequency_at_mtf_interpolates_and_handles_missing_crossing():
    f = np.linspace(0, 10, 101)
    assert frequency_at_mtf(f, 1 - f / 10, 0.5) == pytest.approx(5.0)
    assert np.isnan(frequency_at_mtf(f, np.ones_like(f), 0.5))


def _blurred_edge(sigma_voxels, voxel=0.01, nx=96):
    x = np.arange(nx)
    edge = (nx - 1) / 2.0
    profile = 0.5 * (1 + erf((x - edge) / (np.sqrt(2) * sigma_voxels)))
    volume = np.broadcast_to(profile, (6, 6, nx)).copy() * 1000.0
    left = np.zeros_like(volume, dtype=bool)
    left[..., : nx // 2] = True
    return volume, left, ~left, (voxel, voxel, voxel)


@pytest.mark.parametrize("sigma_voxels", [2.0, 3.0])
def test_edge_mtf_recovers_gaussian_blur(sigma_voxels):
    volume, mask1, mask2, spacing = _blurred_edge(sigma_voxels)
    sigma = sigma_voxels * spacing[0]
    result = edge_mtf(volume, mask1, mask2, spacing, band=6 * sigma)

    expected_f50 = np.sqrt(2 * np.log(2)) / (2 * np.pi * sigma)
    expected_f10 = np.sqrt(2 * np.log(10)) / (2 * np.pi * sigma)
    assert result["f50"] == pytest.approx(expected_f50, rel=0.1)
    assert result["f10"] == pytest.approx(expected_f10, rel=0.1)
    assert result["fwhm"] == pytest.approx(2.355 * sigma, rel=0.1)
    assert result["mtf"][0] == pytest.approx(1.0)
    assert result["resolvable_um10"] == pytest.approx(500.0 / result["f10"])


def test_sharper_edge_gives_higher_mtf():
    volume, mask1, mask2, spacing = _blurred_edge(1.5)
    sharp = edge_mtf(volume, mask1, mask2, spacing, band=0.1)
    volume, mask1, mask2, spacing = _blurred_edge(4.0)
    blurry = edge_mtf(volume, mask1, mask2, spacing, band=0.1)
    assert sharp["f50"] > blurry["f50"]


def test_edge_mtf_requires_shared_interface():
    volume, mask1, _, spacing = _blurred_edge(2.0)
    far = np.zeros_like(mask1)
    far[..., 0] = True
    with pytest.raises(ValueError):
        edge_mtf(volume, mask1 & ~far, far, spacing, band=0.05)


def test_edge_mtf_ignores_voxels_facing_a_third_phase():
    volume, mask1, mask2, spacing = _blurred_edge(2.0)
    clean = edge_mtf(volume, mask1, mask2, spacing, band=0.12)

    # a much brighter third phase touching region 1 on the far side must not enter the ESF
    polluted = volume.copy()
    polluted[..., :8] = 5000.0
    mask1 = mask1.copy()
    mask1[..., :8] = False
    got = edge_mtf(polluted, mask1, mask2, spacing, band=0.12)
    assert got["f50"] == pytest.approx(clean["f50"], rel=0.05)


def test_region_stats_matches_numpy():
    volume = RNG.normal(300.0, 25.0, size=(23, 9, 11)).astype(np.float32)
    mask = RNG.random(volume.shape) > 0.4
    values = volume[mask].astype(np.float64)
    count, mean, std = region_stats(volume, mask)
    assert count == values.size
    assert mean == pytest.approx(values.mean())
    assert std == pytest.approx(values.std(ddof=1))


def test_radial_profile_slice_limit_does_not_change_a_uniform_cylinder():
    volume, mask = _disc_volume(depth=40, profile=lambda rr: 100.0 - 20.0 * (1.0 - rr**2))
    full = radial_profile(volume, mask, (1.0, 1.0, 1.0))
    few = radial_profile(volume, mask, (1.0, 1.0, 1.0), max_slices=3)
    np.testing.assert_allclose(few[1], full[1])
    assert few[2] == pytest.approx(full[2])


def test_edge_mtf_slice_limit_does_not_change_a_uniform_tube():
    volume, mask1, mask2, spacing = _blurred_edge(2.5)
    volume = np.repeat(volume[:1], 30, axis=0)
    mask1 = np.repeat(mask1[:1], 30, axis=0)
    mask2 = np.repeat(mask2[:1], 30, axis=0)

    from commons.lmath.image_quality import esf_from_masks, lsf_from_esf, mtf_from_lsf

    f50 = []
    for max_slices in (1, 8, 30):
        distances, esf = esf_from_masks(volume, mask1, mask2, spacing, 0.1, max_slices=max_slices)
        _, lsf, step = lsf_from_esf(distances, esf)
        frequencies, mtf = mtf_from_lsf(lsf, step)
        f50.append(frequency_at_mtf(frequencies, mtf, 0.5))
    assert f50[0] == pytest.approx(f50[2], rel=0.01)
    assert f50[1] == pytest.approx(f50[2], rel=0.01)


@pytest.mark.parametrize("noise", [0.0, 300.0])
def test_edge_mtf_of_a_curved_edge_is_not_biased_by_the_voxel_staircase(noise):
    """The wall of a tube: the mask is thresholded from the (noisy) image and its boundary is a staircase."""
    from scipy import ndimage

    n, sigma = 260, 2.0
    y, x = np.mgrid[:n, :n]
    disc = np.hypot(y - (n - 1) / 2, x - (n - 1) / 2) <= 90
    image = ndimage.gaussian_filter(disc.astype(float) * 20000, sigma) + 100
    volume = np.repeat(image[None], 4, axis=0) + np.random.default_rng(3).normal(0, noise, (4, n, n))
    mask1 = volume > 10100

    result = edge_mtf(volume, mask1, ~mask1, (1.0, 1.0, 1.0), band=12.0)
    assert result["f50"] == pytest.approx(np.sqrt(2 * np.log(2)) / (2 * np.pi * sigma), rel=0.05)
    assert result["f10"] == pytest.approx(np.sqrt(2 * np.log(10)) / (2 * np.pi * sigma), rel=0.05)
    assert result["fwhm"] == pytest.approx(2.355 * sigma, rel=0.08)
