"""
Quick estimate of the characteristic texture length of an image, in pixels.

The idea: 2x2 mean downsampling is a low-pass filter, so each pyramid step
removes the variance (detail) living at that octave. Fine-texture images lose
their variance after one or two steps; coarse images (structures spanning many
pixels) keep it for several steps. `lambda` is the (geometric) variance-weighted
average scale across octaves.

Larger lambda  -> coarser image (structures span more pixels)
              -> larger feature-size multiplier needed for similar semantics.

Two design choices make the estimate UNBIASED across images of different size,
framing and resolution (validated on microCT cylinders and thin sections):

* Fixed measurement window. The tile size is capped (not scaled to the image),
  so every image is measured against the same octave ceiling and the resulting
  lambdas are directly comparable. Rock textures are often near scale-free, so
  the absolute value is window-dependent -- treat lambda as a RELATIVE descriptor
  and always compare images at the same `tile`, via the ratio.

* Central sampling that never starves the window. Borders (the null rim of a
  microCT cylinder, torn/uneven thin-section margins) inject a huge
  sample-vs-background step edge whose large-scale variance swamps the real
  texture, and they are too irregular to detect reliably -- so we sample the
  centre geometrically. The central box is clamped to at least 2*tile so a small
  image still fits the fixed window (otherwise the ceiling would differ and break
  comparability).

For 3D volumes a few slices are sampled and the median lambda is returned, since
a single slice varies ~15% from the volume median.

Console use (dev instance imports straight from the worktree):

    from ltrace.interactive.scale_estimate import compute_lambda
    compute_lambda(array("thin_section_15k"))
    compute_lambda(array("mct_cylinder"))
"""

import numpy as np
import logging

DEFAULT_TILE = 512
DEFAULT_CENTER_FRACTION = 0.5
DEFAULT_N_SLICES = 7


def _to_gray2d(plane):
    """Coerce a single image plane (2D or H x W x C) to a 2D float32 array."""
    a = np.squeeze(np.asarray(plane))
    if a.ndim == 3 and a.shape[-1] in (3, 4):  # color image -> luminance-ish mean
        a = a[..., :3].mean(axis=-1)
    if a.ndim != 2:
        raise ValueError(f"Expected a 2D plane, got shape {np.asarray(plane).shape}")
    return np.ascontiguousarray(a, dtype=np.float32)


def _level_variances(tile, min_size=4):
    """Global variance of `tile` at each level of a 2x2-mean pyramid."""
    a = tile
    variances = [float(a.var())]
    while min(a.shape) >= 2 * min_size:
        h, w = (a.shape[0] // 2) * 2, (a.shape[1] // 2) * 2
        a = a[:h, :w].reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))
        variances.append(float(a.var()))
    return variances


def _spectrum(gray, tile, max_tiles, center_fraction):
    """
    Per-octave band energy summed over tiles sampled from the central region.

    Tiles stay strictly inside the central `center_fraction` box and are never
    spread out to its edges, so they cannot reach the image borders (the null rim
    of a microCT cylinder, messy thin-section margins). The window is the
    requested `tile`, capped to the central box -- so an image smaller than the
    box (e.g. a ~500px crop vs a 512 window) is measured at a smaller window and
    its lambda is only loosely comparable. That is unavoidable: a small bordered
    image cannot offer a large border-free window. Production microCT (>=1000px)
    and thin sections are large enough that the full 512 window fits centrally.
    """
    height, width = gray.shape
    crop_h = max(1, min(height, int(round(height * center_fraction))))
    crop_w = max(1, min(width, int(round(width * center_fraction))))
    y0, x0 = (height - crop_h) // 2, (width - crop_w) // 2
    used = int(min(tile, crop_h, crop_w))

    grid = max(1, int(np.floor(np.sqrt(max_tiles))))
    ys = np.unique(np.linspace(y0, y0 + crop_h - used, grid).astype(int))
    xs = np.unique(np.linspace(x0, x0 + crop_w - used, grid).astype(int))

    band_sum = None
    for y in ys:
        for x in xs:
            variances = _level_variances(gray[y : y + used, x : x + used])
            bands = np.maximum(0.0, np.array(variances[:-1]) - np.array(variances[1:]))
            if band_sum is None:
                band_sum = np.zeros(bands.size)
            band_sum[: bands.size] += bands[: band_sum.size]
    return band_sum, used, len(ys) * len(xs)


def _lambda_from_spectrum(band_sum, skip_finest=False):
    """Geometric (log-space) variance-weighted mean scale, in pixels."""
    octaves = np.arange(band_sum.size)
    weights = band_sum.copy()
    if skip_finest and weights.size:
        weights[0] = 0.0  # drop the 1->2px band (mostly sensor noise)
    total = weights.sum()
    if total <= 0:
        return float("nan")
    log2_lambda = ((octaves + 1) * weights).sum() / total
    return float(2.0**log2_lambda)


# lambda of a typical microCT at the default 512 window -- the multiplier=1
# anchor. Calibrate against your own representative microCT if it drifts.
REFERENCE_LAMBDA = 20.0
# Supported feature-scale multipliers (powers of two the kernel scaler accepts).
SUPPORTED_MULTIPLIERS = (1, 2, 4)


def suggest_multiplier(image, ref_lambda=REFERENCE_LAMBDA, **kwargs):
    """
    Suggest a feature-scale multiplier from the image's characteristic length.

    lambda grows ~1.5x per true octave of texture scale (not 2x), so the bands
    are geometric with that ratio anchored at `ref_lambda`: an image one octave
    coarser than the microCT reference (-> 1.5x lambda) maps to x2, two octaves
    (-> ~2.25x lambda) to x4. Boundaries are the geometric midpoints. Returns one
    of SUPPORTED_MULTIPLIERS. Extra kwargs pass through to compute_lambda.
    """
    lam = compute_lambda(image, verbose=False, **kwargs)
    if not np.isfinite(lam):
        return 1
    ratio = lam / ref_lambda
    # Midpoints between successive 1.5x steps: sqrt(1*1.5)=1.22, sqrt(1.5*2.25)=1.84.
    if ratio < 1.22:
        return 1
    if ratio < 1.84:
        return 2
    return 4


def _iter_planes(image, n_slices):
    """
    Yield the 2D planes to analyze. A stack along axis 0 (K > 1, not a color
    channel) is treated as a volume and sampled at `n_slices` evenly-spaced
    slices; anything else is a single (optionally color) 2D image.
    """
    vol = np.asarray(image)
    is_volume = vol.ndim >= 3 and vol.shape[0] > 1 and not (vol.ndim == 3 and vol.shape[-1] in (3, 4))
    if is_volume:
        ks = np.unique(np.linspace(0, vol.shape[0] - 1, min(n_slices, vol.shape[0])).astype(int))
        return [vol[int(k)] for k in ks]
    return [vol]


def compute_lambda(
    image,
    tile=DEFAULT_TILE,
    max_tiles=16,
    center_fraction=DEFAULT_CENTER_FRACTION,
    n_slices=DEFAULT_N_SLICES,
    skip_finest=False,
    verbose=True,
):
    """
    Estimate the characteristic texture length (pixels) of `image`.

    Returns lambda in pixels. For a 3D volume, returns the median lambda over a
    few sampled slices. lambda is a RELATIVE descriptor: compare images only at
    the same `tile`, and use the ratio (round to a power of 2 for a feature-size
    multiplier).

    tile            fixed measurement window (capped, NOT scaled to the image)
    max_tiles       approximate cap on tiles sampled per plane
    center_fraction central fraction kept to dodge borders (clamped so the window fits)
    n_slices        slices sampled and median-combined for 3D volumes
    skip_finest     drop octave 0 (the 1->2px band, mostly sensor noise)
    """
    planes = _iter_planes(image, n_slices)

    pooled = None
    lambdas = []
    for plane in planes:
        band_sum, used_tile, n_tiles = _spectrum(_to_gray2d(plane), tile, max_tiles, center_fraction)
        lambdas.append(_lambda_from_spectrum(band_sum, skip_finest))
        if pooled is None:
            pooled = np.zeros(band_sum.size)
        pooled[: band_sum.size] += band_sum[: pooled.size]

    lambdas = np.array(lambdas, dtype=float)
    lam = float(np.nanmedian(lambdas))

    if verbose:
        scales = (2.0 ** (np.arange(pooled.size) + 1)).astype(int)
        total = pooled.sum()
        truncated = total > 0 and int(np.argmax(pooled)) == pooled.size - 1
        logging.debug(
            f"window: tile={used_tile}px, {n_tiles} tile(s)/plane, central {center_fraction:.0%}, "
            f"{len(planes)} plane(s)"
        )
        logging.debug(f"{'scale(px)':>10} {'band energy':>14} {'fraction':>9}")
        for scale, energy in zip(scales, pooled):
            frac = energy / total if total > 0 else 0.0
            logging.debug(f"{scale:>10} {energy:>14.4g} {frac:>8.1%}")
        if len(lambdas) > 1:
            spread = 100 * np.nanstd(lambdas) / lam if lam else 0
            logging.debug(
                f"per-slice lambda: min={np.nanmin(lambdas):.1f} "
                f"median={lam:.1f} max={np.nanmax(lambdas):.1f} (spread {spread:.0f}%)"
            )
        logging.debug(
            f"lambda (centroid): {lam:.1f}px"
            + (
                "    [WARNING: spectrum still climbing at top octave -- texture coarser "
                "than the window; lambda saturated, use only as a floor]"
                if truncated
                else ""
            )
        )

    return lam
