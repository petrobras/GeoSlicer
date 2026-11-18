import itertools

import numpy as np
import pytest
from skimage.restoration import denoise_nl_means

import commons.algorithms.non_local_means as nlm_module
from commons.algorithms.non_local_means import (
    MODE_2D,
    MODE_3D,
    denoise,
    estimate_noise_sigma,
    non_local_means,
    rgb_to_greyscale,
)

SIGMA = 10.0
NLM_KWARGS = dict(patch_size=3, patch_distance=2, fast_mode=True)


def reference_nlm_3d(image, h, sigma, patch_size, patch_distance):
    """Plain float64 implementation of skimage's fast-mode 3D non-local means, with an exact exponential.

    skimage replaces even patch sizes by the next odd one, and its integral image sums each patch over a box of
    2 * (patch_size // 2) voxels per axis, at offsets 1 - patch_size // 2 to patch_size // 2.
    """
    if patch_size % 2 == 0:
        patch_size += 1
    half = patch_size // 2
    margin = patch_distance + half
    padded = np.pad(np.asarray(image, dtype=np.float64), margin, mode="reflect")
    shape = image.shape

    def view(offset):
        return padded[tuple(slice(margin + o, margin + o + n) for o, n in zip(offset, shape))]

    result = np.zeros(shape)
    weights = np.zeros(shape)
    shifts = range(-patch_distance, patch_distance + 1)
    for shift in itertools.product(shifts, repeat=3):
        distance = np.zeros(shape)
        for offset in itertools.product(range(1 - half, half + 1), repeat=3):
            shifted_offset = tuple(o + s for o, s in zip(offset, shift))
            distance += (view(offset) - view(shifted_offset)) ** 2 - 2 * sigma**2
        distance = np.maximum(distance, 0) / (patch_size**3 * h * h)
        weight = np.where(distance > 5, 0, np.exp(-distance))
        result += weight * view(shift)
        weights += weight
    return result / weights


@pytest.fixture
def clean_volume():
    """Piecewise constant volume with a few flat regions."""
    volume = np.full((24, 32, 32), 100.0, dtype=np.float32)
    volume[:, 8:24, 8:24] = 160.0
    volume[6:18, 12:20, 12:20] = 220.0
    return volume


@pytest.fixture
def noisy_volume(clean_volume):
    rng = np.random.default_rng(42)
    return clean_volume + rng.normal(0, SIGMA, clean_volume.shape).astype(np.float32)


@pytest.mark.parametrize("mode", [MODE_3D, MODE_2D])
def test_estimate_noise_sigma_recovers_gaussian_noise(mode):
    rng = np.random.default_rng(0)
    volume = 1000 + rng.normal(0, SIGMA, (32, 64, 64))

    assert estimate_noise_sigma(volume, mode) == pytest.approx(SIGMA, rel=0.05)


def test_estimate_noise_sigma_ignores_zero_padding():
    rng = np.random.default_rng(0)
    volume = np.zeros((32, 64, 64), dtype=np.float32)
    volume[:, 16:48, 16:48] = 1000 + rng.normal(0, SIGMA, (32, 32, 32))

    assert estimate_noise_sigma(volume) == pytest.approx(SIGMA, rel=0.05)


def test_estimate_noise_sigma_of_constant_volume_is_zero():
    assert estimate_noise_sigma(np.full((8, 8, 8), 5.0)) == 0.0


def test_2d_mode_matches_skimage_slice_by_slice(noisy_volume):
    expected = np.stack(
        [denoise_nl_means(s, h=0.7 * SIGMA, sigma=SIGMA, preserve_range=True, **NLM_KWARGS) for s in noisy_volume]
    )

    result = non_local_means(noisy_volume, h=0.7 * SIGMA, sigma=SIGMA, mode=MODE_2D, workers=4, **NLM_KWARGS)

    np.testing.assert_allclose(result, expected, rtol=1e-5, atol=1e-3)


@pytest.mark.parametrize("patch_size, patch_distance", [(3, 2), (5, 3), (4, 2), (1, 2)])
def test_3d_mode_matches_reference(noisy_volume, patch_size, patch_distance):
    volume = noisy_volume[:10, :14, :16]
    expected = reference_nlm_3d(volume, 0.5 * SIGMA, SIGMA, patch_size, patch_distance)

    result = non_local_means(
        volume, h=0.5 * SIGMA, sigma=SIGMA, mode=MODE_3D, patch_size=patch_size, patch_distance=patch_distance
    )

    np.testing.assert_allclose(result, expected, rtol=0, atol=1e-3)


def test_3d_mode_is_close_to_skimage(noisy_volume):
    # skimage approximates exp(-x) with errors of a few percent, so it only agrees to a small fraction of the noise
    expected = denoise_nl_means(noisy_volume, h=0.5 * SIGMA, sigma=SIGMA, preserve_range=True, **NLM_KWARGS)

    result = non_local_means(noisy_volume, h=0.5 * SIGMA, sigma=SIGMA, mode=MODE_3D, **NLM_KWARGS)

    difference = np.abs(result - expected)
    assert difference.mean() < 0.01 * SIGMA
    assert difference.max() < 0.1 * SIGMA


@pytest.mark.parametrize("workers", [1, 3])
def test_3d_tiles_match_single_tile(noisy_volume, monkeypatch, workers):
    single_tile = non_local_means(noisy_volume, h=0.5 * SIGMA, sigma=SIGMA, mode=MODE_3D, workers=1, **NLM_KWARGS)
    # Tiles that do not divide the volume evenly, with a margin wider than the last tile along each axis
    monkeypatch.setattr(nlm_module, "TILE_SHAPE_3D", (5, 6, 7))

    tiled = non_local_means(noisy_volume, h=0.5 * SIGMA, sigma=SIGMA, mode=MODE_3D, workers=workers, **NLM_KWARGS)

    np.testing.assert_allclose(tiled, single_tile, rtol=1e-6, atol=1e-4)


def test_3d_mode_on_volume_smaller_than_the_search_margin(noisy_volume):
    volume = noisy_volume[:3, :4, :5]
    expected = reference_nlm_3d(volume, 0.5 * SIGMA, SIGMA, patch_size=5, patch_distance=6)

    result = non_local_means(volume, h=0.5 * SIGMA, sigma=SIGMA, mode=MODE_3D, patch_size=5, patch_distance=6)

    np.testing.assert_allclose(result, expected, rtol=0, atol=1e-3)


def test_3d_mode_on_large_intensities(noisy_volume):
    # Intensities in the upper uint16 range must not lose the precision of small patch distances
    volume = noisy_volume[:8, :12, :12] * 100 + 40000
    expected = reference_nlm_3d(volume, 0.5 * SIGMA * 100, SIGMA * 100, patch_size=3, patch_distance=2)

    result = non_local_means(volume, h=0.5 * SIGMA * 100, sigma=SIGMA * 100, mode=MODE_3D, **NLM_KWARGS)

    np.testing.assert_allclose(result, expected, rtol=1e-5, atol=0)


@pytest.mark.parametrize("mode, strength", [(MODE_3D, 0.5), (MODE_2D, 0.7)])
def test_filter_reduces_noise(clean_volume, noisy_volume, mode, strength):
    result = non_local_means(noisy_volume, h=strength * SIGMA, sigma=SIGMA, mode=mode, workers=2, **NLM_KWARGS)

    error_before = np.abs(noisy_volume - clean_volume).mean()
    error_after = np.abs(result - clean_volume).mean()
    assert result.dtype == np.float32
    assert error_after < 0.5 * error_before


def test_non_positive_strength_returns_input_unchanged(noisy_volume):
    result = non_local_means(noisy_volume, h=0, sigma=SIGMA)

    np.testing.assert_array_equal(result, noisy_volume)
    assert result is not noisy_volume


def test_single_slice_volume_in_3d_mode_is_filtered_as_2d(noisy_volume):
    single_slice = noisy_volume[:1]
    expected = denoise_nl_means(single_slice[0], h=SIGMA, sigma=SIGMA, preserve_range=True, **NLM_KWARGS)

    result = non_local_means(single_slice, h=SIGMA, sigma=SIGMA, mode=MODE_3D, **NLM_KWARGS)

    np.testing.assert_allclose(result[0], expected, rtol=1e-5, atol=1e-3)


@pytest.mark.parametrize("mode, workers", [(MODE_2D, 2), (MODE_3D, 1), (MODE_3D, 2)])
def test_progress_reaches_completion(noisy_volume, mode, workers):
    progress = []

    non_local_means(
        noisy_volume, h=SIGMA, sigma=SIGMA, mode=mode, workers=workers, progress_callback=progress.append, **NLM_KWARGS
    )

    assert progress == sorted(progress)
    assert progress[-1] == pytest.approx(1.0)


def test_invalid_mode_raises(noisy_volume):
    with pytest.raises(ValueError):
        non_local_means(noisy_volume, h=SIGMA, sigma=SIGMA, mode="4d")


@pytest.mark.parametrize("channels", [3, 4])
def test_rgb_to_greyscale_keeps_grey_values_stored_as_rgb(channels):
    grey = np.random.default_rng(0).integers(0, 256, (4, 8, 8)).astype(np.uint8)
    rgb = np.repeat(grey[..., np.newaxis], channels, axis=-1)
    if channels == 4:
        rgb[..., 3] = 255  # alpha is ignored

    result = rgb_to_greyscale(rgb)

    assert result.dtype == np.float32
    np.testing.assert_allclose(result, grey, atol=1e-3)


def test_rgb_to_greyscale_uses_luma_weights():
    rgb = np.zeros((1, 1, 3, 3), dtype=np.uint8)
    rgb[0, 0, 0] = (100, 0, 0)
    rgb[0, 0, 1] = (0, 100, 0)
    rgb[0, 0, 2] = (0, 0, 100)

    np.testing.assert_allclose(rgb_to_greyscale(rgb)[0, 0], [29.9, 58.7, 11.4], rtol=1e-5)


def test_rgb_to_greyscale_rounds_to_integer_types():
    rgb = np.zeros((1, 1, 3, 3), dtype=np.uint8)
    rgb[0, 0, 0] = (100, 0, 0)
    rgb[0, 0, 1] = (0, 100, 0)
    rgb[0, 0, 2] = (255, 255, 255)

    result = rgb_to_greyscale(rgb, dtype=rgb.dtype)

    assert result.dtype == np.uint8
    np.testing.assert_array_equal(result[0, 0], [30, 59, 255])


@pytest.mark.parametrize("shape", [(4, 8, 8), (4, 8, 8, 2)])
def test_rgb_to_greyscale_rejects_non_rgb(shape):
    with pytest.raises(ValueError):
        rgb_to_greyscale(np.zeros(shape))


def test_denoise_estimates_sigma_and_keeps_integer_dtype(noisy_volume):
    volume = np.clip(np.rint(noisy_volume), 0, 255).astype(np.uint8)
    sigma = estimate_noise_sigma(volume.astype(np.float32))
    expected = non_local_means(volume, h=0.5 * sigma, sigma=sigma, **NLM_KWARGS)

    result, used_sigma, used_h = denoise(volume, strength=0.5, **NLM_KWARGS)

    assert used_sigma == pytest.approx(sigma)
    assert used_h == pytest.approx(0.5 * sigma)
    assert result.dtype == np.uint8
    np.testing.assert_array_equal(result, np.rint(expected).astype(np.uint8))


def test_denoise_keeps_null_values(noisy_volume):
    volume = noisy_volume.copy()
    volume[:, :4] = -1

    result, _, _ = denoise(volume, strength=0.5, sigma=SIGMA, null_value=-1, **NLM_KWARGS)

    assert np.all(result[:, :4] == -1)
    assert np.all(result[:, 4:] > 0)
