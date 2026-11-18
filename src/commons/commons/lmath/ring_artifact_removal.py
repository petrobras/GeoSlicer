"""Ring artifact correction for already reconstructed CT/micro-CT images.

Method: the image is transformed to polar coordinates around a center (rings,
concentric to that center, become straight streaks along the radial
direction) only to estimate a correction profile, one value per radius, by
applying a high-pass/median filter along the angular direction. The image
itself is never transformed: the correction is subtracted from each pixel
according to its own distance to the center. Only the 1D profile makes the
round trip, so the image is never resampled and the real texture is preserved.

Not every ring artifact is centered on the sample: rotation axis misalignment
or cone-beam geometry (detector rows outside the central plane) produce
shifted foci, which inside an image window appear as nearly straight
("hyperbolic") arcs. The center is therefore an input, and a shifted focus has
to be identified by whoever calls this.

Reference: Sijbers & Postnov, "Reduction of ring artefacts in high
resolution micro-CT reconstructions", Phys. Med. Biol. 49 (2004) N247.
"""

import re
import warnings

import numpy as np
from scipy import ndimage
from scipy.ndimage import median_filter

from commons.lmath.utils import safe_cast


def center_from_reconstruction_parameters(rec, shape):
    """Rotation center of a slice, read from the scan's reconstruction parameters.

    The parameters give the rotation axis as a detector column (`RotationCenter`) and the
    detector column the reconstruction grid is centered on (`HorizontalCenter`). The slice
    center is the grid center displaced by the difference between the two:
    `cx = (columns - 1) / 2 + (RotationCenter - HorizontalCenter)`. The axis is vertical, so
    it crosses every slice at the same row, the grid center: `cy = (rows - 1) / 2`.

    The difference is added as it is, without unit conversion. That assumes the voxel size is
    the detector pixel projected onto the object (pixel size divided by the magnification), so
    that one detector pixel spans one voxel, which holds when the projections were not rebinned.
    The sign also assumes the detector is neither flipped nor the rotation reversed.

    Parameters
    ----------
    rec : str or bytes
        Text of the reconstruction parameters stored with the image.
    shape : tuple
        (rows, columns) of the slice.

    Returns
    -------
    tuple (cy, cx), or None if the parameters are absent or unreadable.
    """
    if not rec:
        return None
    if isinstance(rec, bytes):
        rec = rec.decode("utf-8", errors="ignore")

    def read(name):
        match = re.search(rf"<Name>\s*{name}\s*</Name>\s*<Value[^>]*>\s*([^<\s]+)\s*</Value>", rec)
        try:
            return float(match.group(1)) if match else None
        except ValueError:
            return None

    rotation_center, horizontal_center = read("RotationCenter"), read("HorizontalCenter")
    if rotation_center is None or horizontal_center is None:
        return None
    return (shape[0] - 1) / 2.0, (shape[1] - 1) / 2.0 + (rotation_center - horizontal_center)


def _find_center(image, mask=None):
    """Estimate the rotation center as the centroid of the sample region (mask) or of the image."""
    if mask is None:
        mask = image > 0
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        cy, cx = (image.shape[0] - 1) / 2.0, (image.shape[1] - 1) / 2.0
    else:
        cy, cx = ys.mean(), xs.mean()
    return cy, cx


def _to_polar(image, center, n_angles=None, n_radii=None):
    cy, cx = center
    h, w = image.shape
    max_radius = int(np.ceil(np.hypot(max(cy, h - cy), max(cx, w - cx))))
    if n_radii is None:
        n_radii = max_radius
    if n_angles is None:
        n_angles = max(h, w) * 2

    radii = np.linspace(0, max_radius, n_radii)
    angles = np.linspace(0, 2 * np.pi, n_angles, endpoint=False)
    r_grid, a_grid = np.meshgrid(radii, angles, indexing="ij")

    ys = cy + r_grid * np.sin(a_grid)
    xs = cx + r_grid * np.cos(a_grid)

    polar = ndimage.map_coordinates(image, [ys, xs], order=1, mode="constant", cval=np.nan)
    return polar, radii, angles


def _radius_weight(radii, radius_range, taper):
    """Weight in [0, 1] per radius: 1 inside `radius_range`, fading to 0 at its ends."""
    weight = np.ones_like(radii, dtype=np.float64)
    if radius_range is None:
        return weight
    r_min, r_max = radius_range
    taper = max(float(taper), 1e-6)
    if r_min:
        weight *= np.clip((radii - r_min) / taper, 0.0, 1.0)
    if r_max:
        weight *= np.clip((r_max - radii) / taper, 0.0, 1.0)
    return weight


def remove_ring_artifacts(image, center=None, mask=None, median_size=17, clip=True, radius_range=None, taper=10.0):
    """Remove ring artifacts from a reconstructed 2D image (CT slice).

    The polar transform is used only to ESTIMATE the correction profile
    (one value per radius); the correction is then applied to each original
    pixel according to its own distance to the center (`image - correction(r)`),
    never resampling/interpolating the image itself. This avoids the blurring
    that a Cartesian→polar→Cartesian roundtrip of the whole image would cause.

    Parameters
    ----------
    image : np.ndarray (2D)
        Image to correct (e.g. a slice of the volume).
    center : tuple (cy, cx), optional
        Rotation center. If None, it is estimated as the centroid of `mask`
        (or of the image itself, assuming background = 0).
    mask : np.ndarray bool, optional
        Sample region mask (True = material), used to estimate the center
        when `center` is not given.
    median_size : int
        Window size of the median filter applied along the angular direction,
        in the polar domain. Controls the detected ring "thickness"; larger
        values remove wider rings but may blur detail.
    clip : bool
        If True, clips the final result to the min/max of the original image
        (avoids artificial overshoot at the edges of the correction).
    radius_range : tuple (r_min, r_max), optional
        Only radii inside this range, in pixels from the center, are corrected;
        the rest of the image is left as it is. Either end may be None for no
        limit.
    taper : float
        Width in pixels over which the correction fades in at `r_min` and out at
        `r_max`. A hard cut would leave a visible step at the edge of the range.
        It fades inside the range, so the correction is whole from `r_min + taper`
        to `r_max - taper` and zero at the ends.

    Returns
    -------
    np.ndarray
        Corrected image, same shape and dtype (float) as the input.
    """
    image = np.asarray(image, dtype=np.float64)
    if image.ndim != 2:
        raise ValueError("remove_ring_artifacts expects a 2D image (a single slice).")

    if center is None:
        center = _find_center(image, mask)

    polar, radii, angles = _to_polar(image, center)

    # The ring artifact is constant at a given radius (same column in the polar
    # domain) — we isolate the systematic radial profile with the median along
    # the angular axis and subtract its high-frequency radial variation.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        radial_profile = np.nanmedian(polar, axis=1)

    # Radii close to the bounding box limit may fall outside the image at
    # some angles (NaN from map_coordinates); fill by interpolation so NaN
    # does not propagate into the correction.
    valid = ~np.isnan(radial_profile)
    if valid.any() and not valid.all():
        radial_profile[~valid] = np.interp(np.flatnonzero(~valid), np.flatnonzero(valid), radial_profile[valid])
    elif not valid.any():
        radial_profile[:] = 0.0

    smoothed_profile = median_filter(radial_profile, size=median_size, mode="nearest")
    correction_by_radius = radial_profile - smoothed_profile
    correction_by_radius *= _radius_weight(radii, radius_range, taper)

    cy, cx = center
    h, w = image.shape
    yy, xx = np.indices((h, w))
    r = np.hypot(yy - cy, xx - cx)
    pixel_correction = np.interp(r, radii, correction_by_radius)

    corrected = image - pixel_correction

    if clip:
        corrected = np.clip(corrected, image.min(), image.max())

    return corrected.astype(image.dtype, copy=False)


def remove_ring_artifacts_volume(
    volume,
    axis=0,
    center=None,
    mask=None,
    median_size=17,
    clip=True,
    out_dtype=None,
    background_level=None,
    progress_callback=None,
    radius_range=None,
):
    """Apply `remove_ring_artifacts` to each slice of a 3D volume.

    Slices are processed one at a time and each corrected slice is stored in
    `out_dtype` straight away, so the output is the only full-size array alive.
    Passing `out_dtype=volume.dtype` holds the peak at one extra copy of the
    input rather than the 8 bytes per voxel a float64 output needs. For a
    2000**3 uint16 volume that is 16 GB instead of 64 GB.

    Parameters
    ----------
    volume : np.ndarray (3D)
    axis : int
        Axis along which the 2D slices (reconstruction plane, where the rings
        appear) are taken. Defaults to 0 (slices along z).
    out_dtype : np.dtype, optional
        dtype of the returned volume, float64 by default. Integer dtypes are
        rounded and clamped (see `safe_cast`), never truncated or wrapped.
    background_level : float, optional
        Threshold used to derive each slice's sample mask on the fly when
        `mask` is not given, so no boolean volume (1 byte per voxel) has to be
        built just to locate the center.
    progress_callback : callable(done, total), optional
        Called after each slice is stored. Raising from inside it aborts the
        run: the exception propagates untouched, which is how a caller
        implements cancellation without this module knowing about it.
    remaining parameters: see `remove_ring_artifacts`.
    """
    volume = np.asarray(volume)
    if volume.ndim != 3:
        raise ValueError("remove_ring_artifacts_volume expects a 3D volume.")
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
        corrected = remove_ring_artifacts(
            volume[i],
            center=center,
            mask=slice_mask,
            median_size=median_size,
            clip=clip,
            radius_range=radius_range,
        )
        out[i] = safe_cast(corrected, out_dtype)
        if progress_callback is not None:
            progress_callback(i + 1, volume.shape[0])

    return np.moveaxis(out, 0, axis)
