"""Radial fan artifact correction for already reconstructed CT/micro-CT images.

A dense inclusion (heavy mineral, metal) makes the reconstruction filter (FBP)
spread energy outwards, producing a fan of fine streaks radiating from that
grain. Unlike a ring artifact (a bias constant at a given RADIUS, varying with
the angle), a radial streak is a bias narrow in ANGLE that persists along the
radius, the exact dual of a ring.

Method: same principle as `ring_artifact_removal`, with the roles of radius
and angle swapped. In polar coordinates around the focus, a high-pass/median
filter along the angular direction isolates the streaks, and a coherence
average along the radius keeps only what a real streak does and rock texture
does not. The correction is then subtracted from each pixel according to its
own polar coordinates, without ever resampling the image, which avoids
blurring the real texture.

Caveat, measured on real data: this separation only works when the angular
width of the streaks is clearly narrower than the texture scale of the sample.
Where the two scales overlap, no window size separates them, and the
correction removes texture rather than artifact. Always verify on a slice
before applying to a whole volume.
"""

import numpy as np
from scipy import ndimage
from scipy.ndimage import median_filter, uniform_filter1d

from commons.lmath.utils import low_memory_percentile, safe_cast


def find_fan_center(volume, background=None, axis=0):
    """Locate the focus of a radial fan: the high-attenuation grain the
    streaks emanate from.

    Unlike a ring center (which is an abstract geometric point, and therefore
    must be found by optimizing a metric), the fan focus is a PHYSICAL OBJECT
    the most attenuating voxel of the scene. So it can simply be searched for
    directly, without optimization and without local-minimum risk.

    In a 3D volume, the search is done on the MEDIAN along z, not slice by
    slice: the grain is persistent along z, so it survives the median while an
    isolated hot voxel (noise) does not. This also returns a single center for
    the whole volume, which is exactly what the fan correction uses.

    Parameters
    ----------
    volume : np.ndarray (2D or 3D)
    background : float, optional
        Level below which a pixel is considered background. Default:
        1st percentile of the data.
    axis : int
        Slice axis, when `volume` is 3D.

    Returns
    -------
    tuple (y, x)
        Focus position, in slice coordinates.
    """
    volume = np.asarray(volume)
    if volume.ndim not in (2, 3):
        raise ValueError("find_fan_center expects a 2D or 3D array.")
    if background is None:
        background = low_memory_percentile(volume, 1, axis=axis)

    if volume.ndim == 3:
        # The median is taken a block of rows at a time, so the float32 copy and the
        # sorting buffers np.median makes stay a few tens of MB whatever the volume size.
        moved = np.moveaxis(volume, axis, 0)
        reference = np.empty(moved.shape[1:], dtype=np.float32)
        rows = max(1, (1 << 22) // max(1, moved.shape[0] * moved.shape[2]))
        for start in range(0, moved.shape[1], rows):
            block = moved[:, start : start + rows, :].astype(np.float32)
            reference[start : start + rows] = np.median(block, axis=0)
    else:
        reference = volume.astype(np.float64)

    candidates = np.where(reference > background, reference, -np.inf)
    y, x = np.unravel_index(np.argmax(candidates), candidates.shape)
    return float(y), float(x)


def remove_radial_streak_artifacts(
    image,
    center,
    mask=None,
    arc_width=5.0,
    radial_coherence=21,
    n_angles=1440,
    min_radius=3.0,
    max_radius=None,
):
    """Remove a FAN of radial streaks emanating from a fixed point.

    Unlike `remove_streak_artifacts` (which models an infinite line and
    produces parallel bands across the whole image, practically ignoring the
    marked point), here the marked point is the center of a polar system: a
    radial streak is a narrow bias in THETA that persists along r, the exact
    dual of a ring. This captures a continuous, dense fan of thin rays at
    once, without having to enumerate/count rays.

    Two steps:

    1. High-pass along THETA at each radius, with a constant ARC window
       (`arc_width`, in pixels) rather than a constant angle, so the detected
       streak width is the same near and far from the center.
    2. Average the result along r (`radial_coherence`): only what is
       radially COHERENT survives. A real streak keeps the same signal at the
       same theta for tens of radii; rock texture does not. Without this
       step the correction eats the real texture and leaves a blur in arcs.

    Parameters
    ----------
    image : np.ndarray (2D)
    center : tuple (y, x)
        Focus the streaks emanate from (e.g. the dense inclusion).
    mask : np.ndarray bool, optional
        True = sample. Pixels outside are ignored in the profile and kept
        unchanged in the output.
    arc_width : float
        Typical streak width, in arc pixels.
    radial_coherence : int
        Length (in radius pixels) of the radial coherence window.
        Values that are too high make the fan reappear, because the rays
        curve slightly in theta as r grows.
    n_angles : int
        Angular resolution of the polar grid.
    min_radius : float
        Radius below which nothing is corrected (avoids the dense grain itself).
    max_radius : float, optional
        Maximum corrected radius. Default: farthest corner of the image.

    Returns
    -------
    np.ndarray
        Corrected image.
    """
    image = np.asarray(image, dtype=np.float64)
    if image.ndim != 2:
        raise ValueError("remove_radial_streak_artifacts expects a 2D image (a single slice).")

    cy, cx = center
    h, w = image.shape
    if max_radius is None:
        max_radius = float(np.hypot(max(cy, h - cy), max(cx, w - cx)))
    n_radii = max(int(np.ceil(max_radius)), 2)

    radii = np.linspace(0, max_radius, n_radii)
    angles = np.linspace(0, 2 * np.pi, n_angles, endpoint=False)
    r_grid, a_grid = np.meshgrid(radii, angles, indexing="ij")
    ys = cy + r_grid * np.sin(a_grid)
    xs = cx + r_grid * np.cos(a_grid)

    polar = ndimage.map_coordinates(image, [ys, xs], order=1, mode="constant", cval=np.nan)
    if mask is not None:
        mask_grid = ndimage.map_coordinates(mask.astype(np.float64), [ys, xs], order=0, mode="constant", cval=0.0)
        polar = np.where(mask_grid > 0.5, polar, np.nan)

    dtheta = 2 * np.pi / n_angles
    highpass = np.zeros_like(polar)
    for i, r in enumerate(radii):
        row = polar[i]
        valid = ~np.isnan(row)
        if r < min_radius or valid.sum() < 8:
            continue
        filled = row.copy()
        if not valid.all():
            idxs = np.arange(n_angles)
            filled[~valid] = np.interp(idxs[~valid], idxs[valid], row[valid], period=n_angles)
        # window in samples covering `arc_width` arc pixels at this radius
        k = int(round(arc_width / max(r * dtheta, 1e-6)))
        k = max(3, min(k, n_angles // 4))
        if k % 2 == 0:
            k += 1
        pad = k // 2
        extended = np.concatenate([filled[-pad:], filled, filled[:pad]])
        hp = filled - median_filter(extended, size=k, mode="nearest")[pad:-pad]
        hp[~valid] = 0.0
        highpass[i] = hp

    coherent = uniform_filter1d(highpass, size=max(int(radial_coherence), 1), axis=0, mode="nearest")

    yy, xx = np.indices((h, w))
    dy, dx = yy - cy, xx - cx
    r_idx = np.hypot(dy, dx) / max_radius * (n_radii - 1)
    th_idx = (np.arctan2(dy, dx) % (2 * np.pi)) / (2 * np.pi) * n_angles
    pad_theta = 4
    extended2d = np.concatenate([coherent[:, -pad_theta:], coherent, coherent[:, :pad_theta]], axis=1)
    pixel_correction = ndimage.map_coordinates(extended2d, [r_idx, th_idx + pad_theta], order=1, mode="nearest")

    corrected = image - pixel_correction
    if mask is not None:
        corrected = np.where(mask, corrected, image)
    return corrected


def remove_radial_streak_artifacts_volume(
    volume,
    center,
    axis=0,
    mask=None,
    arc_width=5.0,
    radial_coherence=21,
    n_angles=1440,
    min_radius=3.0,
    max_radius=None,
    out_dtype=None,
    background_level=None,
    progress_callback=None,
):
    """Apply `remove_radial_streak_artifacts` to each slice of a 3D volume.

    The center is the same (x, y) in all slices; the angular distribution of
    the streaks is re-estimated automatically on each slice, so the fan can
    rotate freely with z without any additional parameter.

    Each corrected slice is stored in `out_dtype` as soon as it is computed, so
    no full-size float64 intermediate is needed. `remove_ring_artifacts_volume`
    explains the memory reasoning.

    Parameters
    ----------
    out_dtype : np.dtype, optional
        dtype of the returned volume, float64 by default. Integer dtypes are
        rounded and clamped, never truncated or wrapped.
    background_level : float, optional
        Threshold used to derive each slice's sample mask on the fly when
        `mask` is not given, instead of building a boolean volume.
    progress_callback : callable(done, total), optional
        Called after each slice is stored. Raising from inside it aborts the
        run (see `remove_ring_artifacts_volume`).
    remaining parameters: see `remove_radial_streak_artifacts`.
    """
    volume = np.asarray(volume)
    if volume.ndim != 3:
        raise ValueError("remove_radial_streak_artifacts_volume expects a 3D volume.")
    volume = np.moveaxis(volume, axis, 0)

    mask_moved = None if mask is None else np.moveaxis(mask, axis, 0)
    out_dtype = np.float64 if out_dtype is None else np.dtype(out_dtype)
    out = np.empty(volume.shape, dtype=out_dtype)

    for i in range(volume.shape[0]):
        if mask_moved is not None:
            slice_mask = mask_moved[i]
        elif background_level is not None:
            slice_mask = volume[i] > background_level
        else:
            slice_mask = None
        corrected = remove_radial_streak_artifacts(
            volume[i],
            center,
            mask=slice_mask,
            arc_width=arc_width,
            radial_coherence=radial_coherence,
            n_angles=n_angles,
            min_radius=min_radius,
            max_radius=max_radius,
        )
        out[i] = safe_cast(corrected, out_dtype)
        if progress_callback is not None:
            progress_callback(i + 1, volume.shape[0])

    return np.moveaxis(out, 0, axis)
