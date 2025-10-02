from ltrace.algorithms.CorrelationDistance.CorrelationDistance import CorrelationDistance, interpolate_spline
from scipy.ndimage import uniform_filter
import cv2
import numpy as np


def win_var(img, wlen):
    # Variance filter
    img = img.astype(np.float32)
    wlen = round(wlen)
    wmean, wsqrmean = (cv2.boxFilter(x, -1, (wlen, wlen), borderType=cv2.BORDER_REFLECT) for x in (img, img * img))
    return wsqrmean - wmean * wmean


def win_var_3d(img, wlen):
    # Variance filter
    img = img.astype(np.float32)
    wlen = round(wlen)
    wmean, wsqrmean = (uniform_filter(x, size=wlen, mode="reflect") for x in (img, img * img))
    return wsqrmean - wmean * wmean


def variogram(image, spacing, kernel_size, initial_progress_value=0, mid_progress_value=1):
    unit_size = kernel_size // 2
    output_data, _ = CorrelationDistance.calculate_correlation(
        image,
        spacing,
        [kernel_size] * len(image.shape),
        [unit_size] * len(image.shape),
        initial_progress_value,
        mid_progress_value,
    )

    output_data = np.nan_to_num(output_data)
    output_data, _ = interpolate_spline(image.shape, spacing, output_data)

    padding = np.array(image.shape) - np.array(output_data.shape)
    pad_width = ()
    for axis, margin in enumerate(padding):
        if margin >= 0:
            pad_width += ((0, margin),)
        else:
            output_data = np.delete(output_data, slice(0, abs(margin)), axis)
            pad_width += ((0, 0),)
    return np.pad(output_data, pad_width, mode="edge")


def rescale(filters, out_type=np.uint16):
    """
    Rescale filters by setting the quantile of 2% as
    minimum and quantile of 98% as maximum.
    """
    fmin = np.quantile(filters[::8, ::8], 0.02)
    fmax = np.quantile(filters[::8, ::8], 0.98)
    max_value = np.iinfo(out_type).max
    filters_quant = np.array((filters - fmin) * max_value / (fmax - fmin))
    filters_quant = np.clip(filters_quant, 0, max_value)
    return filters_quant.astype(out_type)
