import numpy as np
from scipy.fft import fft, ifft, ifftshift

__all__ = [
    "naninterp",
    "timewindow_crosscorrelation",
    "remove_step",
    "low_memory_percentile",
    "safe_cast",
]


def naninterp(array):
    nans = np.isnan(array)
    not_nans = ~nans

    def flat_argwhere(x):
        return np.argwhere(x).flatten()

    only_nans = flat_argwhere(nans)
    if only_nans.size == 0:
        return array
    interpolation = np.interp(only_nans, flat_argwhere(not_nans), array[not_nans])
    array[only_nans] = interpolation
    return array


def timewindow_crosscorrelation(a, b, sample_frequency, time_window, time_step, max_lag_time, normalize_output=False):
    if sample_frequency <= 0:
        raise RuntimeError("Sampling frequency must be greater than zero")

    if time_window <= 0:
        raise RuntimeError("Time window must be greater than zero")

    if np.round(time_step * sample_frequency) <= 0:
        raise RuntimeError("Time step needs to be at least one sample")

    if time_window * sample_frequency > a.size:
        raise RuntimeError("The specified time window is larger than the duration of the input signal")

    if len(a.shape) != 1 or len(b.shape) != 1:
        raise RuntimeError("Both inputs should be unidimensional arrays")

    if a.size != b.size:
        raise RuntimeError("Both arrays should have the same length")

    total_samples = a.size
    time_window_samples = int(np.round(time_window * sample_frequency))
    time_step_samples = int(np.round(time_step * sample_frequency))
    number_time_windows = int((total_samples + 1 - time_window_samples) / time_step_samples)

    window_start = 0
    time_index = np.array([], dtype=np.int32)
    for i in range(number_time_windows):
        time_index = np.concatenate([time_index, np.arange(window_start, window_start + time_window_samples)])
        window_start += time_step_samples

    time_index = time_index.reshape(number_time_windows, time_window_samples)

    time_window = np.arange(number_time_windows) * time_step
    lag_maximum_samples = int(np.ceil(max_lag_time * sample_frequency))
    lags = np.arange(-lag_maximum_samples, lag_maximum_samples + 1)
    lag_time = lags / sample_frequency

    if time_window_samples > lag_maximum_samples:
        zero_padding_samples = time_window_samples
    else:
        zero_padding_samples = time_window_samples + 2 * lag_maximum_samples

    zero_padding = np.zeros((number_time_windows, zero_padding_samples))
    a_extended = np.concatenate([a[time_index], zero_padding], axis=1)
    b_extended = np.concatenate([b[time_index], zero_padding], axis=1)

    a_fft = fft(a_extended)
    b_fft = fft(b_extended)
    inverse_combined_fft = ifft(a_fft * np.conj(b_fft))
    shifted_inverse_combined_fft = ifftshift(np.real(inverse_combined_fft), axes=1)

    mid_point = (time_window_samples + zero_padding_samples) // 2
    cross_correlation = shifted_inverse_combined_fft[
        :, mid_point - lag_maximum_samples : mid_point + lag_maximum_samples + 1
    ]

    return lag_time, time_window, cross_correlation


def remove_step(input, maximum_step_width):
    step_minimum_height = np.std(input)
    output = input.copy()
    i = 1
    while i < len(output) - maximum_step_width:
        previous = output[i - 1]
        current = output[i]
        if abs(current - previous) < step_minimum_height:
            i += 1
            continue

        j = i
        while j < i + maximum_step_width:
            lookahead = output[j]
            if abs(previous - lookahead) < step_minimum_height:
                output[i:j] = previous
                break
            else:
                j += 1

        i = j + 1

    return output


def low_memory_percentile(volume, q, axis=0, bins=1 << 16):
    """Percentile of a large array without copying it.

    `np.percentile` partitions a full copy of the input, which for a 2000**3
    uint16 volume means 16 GB resident alongside the volume itself. This walks
    the array one slice at a time and keeps only a histogram, so the extra
    memory is a few hundred kB whatever the volume size. No voxel is skipped.

    Integer inputs get one bin per possible value, which makes the result
    exact. Float inputs fall back to a binned histogram, as do integer inputs
    whose range is too wide for one bin per value; the error is then bounded by
    the bin width, (max - min) / `bins`. That bound is absolute, not relative:
    for CT data it sits well below the noise, but one extreme outlier widens
    every bin and spoils it.

    The result is a value taken from the data, or a bin edge, rather than the
    interpolation between order statistics that `np.percentile` returns, so the
    two can differ by about a bin even where both are exact.

    NaN and infinities are ignored, the way `np.nanpercentile` ignores NaN. An
    array with no finite value at all raises.

    Parameters
    ----------
    volume : np.ndarray
        Array of any dimensionality (traversed along `axis` when 3D).
    q : float
        Percentile to compute, in [0, 100].
    axis : int
        Axis to stream along, to bound the size of each temporary.
    bins : int
        Number of histogram bins used for floating point inputs.

    Returns
    -------
    float
    """
    volume = np.asarray(volume)
    if not 0.0 <= q <= 100.0:
        raise ValueError("q must be in [0, 100].")
    if volume.size == 0:
        raise ValueError("low_memory_percentile needs a non-empty array.")
    if volume.ndim < 3:
        return float(np.percentile(volume, q))

    moved = np.moveaxis(volume, axis, 0)

    if np.issubdtype(moved.dtype, np.integer):
        value_min = min(int(moved[i].min()) for i in range(moved.shape[0]))
        value_max = max(int(moved[i].max()) for i in range(moved.shape[0]))
        n_values = value_max - value_min + 1
    else:
        n_values = None

    # One bin per integer value is only worth it while the histogram stays
    # small. A wide int32 range falls back to the binned path below.
    if n_values is not None and n_values <= max(bins, 1 << 24):
        histogram = np.zeros(n_values, dtype=np.int64)
        for i in range(moved.shape[0]):
            # Shifting by value_min keeps the histogram small for data that
            # does not start at zero (and makes signed dtypes work).
            histogram += np.bincount((moved[i].ravel().astype(np.int64) - value_min), minlength=n_values)
        target = q / 100.0 * histogram.sum()
        index = int(np.searchsorted(np.cumsum(histogram), target))
        return float(min(index, n_values - 1) + value_min)

    # Only finite values define the range. np.nanmin would be the obvious
    # choice, but on an all-NaN slice it warns and returns NaN, and Python's
    # min() then swallows that NaN or propagates it depending on argument
    # order, giving a bogus range instead of an error.
    value_min, value_max = np.inf, -np.inf
    for i in range(moved.shape[0]):
        finite = moved[i][np.isfinite(moved[i])]
        if finite.size == 0:
            continue
        value_min = min(value_min, float(finite.min()))
        value_max = max(value_max, float(finite.max()))
    if not np.isfinite(value_min) or not np.isfinite(value_max):
        raise ValueError("low_memory_percentile needs at least one finite value.")
    if value_max == value_min:
        return value_min

    histogram = np.zeros(bins, dtype=np.int64)
    edges = np.linspace(value_min, value_max, bins + 1)
    for i in range(moved.shape[0]):
        histogram += np.histogram(moved[i], bins=edges)[0]
    target = q / 100.0 * histogram.sum()
    index = int(np.searchsorted(np.cumsum(histogram), target))
    return float(edges[min(index, bins - 1)])


def safe_cast(array, dtype):
    """Cast to `dtype`, rounding and clamping instead of truncating and wrapping.

    Towards an integer type, `np.ndarray.astype` truncates towards zero, a
    systematic bias of half a least significant bit, and wraps silently on
    overflow: one negative value cast to uint16 comes out near 65535. Both
    matter when a float correction is stored back into the integer dtype the
    CT volume came in.

    An array that already has `dtype` is returned as is, without a copy.
    """
    dtype = np.dtype(dtype)
    if array.dtype == dtype:
        return array
    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        rounded = np.rint(array)
        np.clip(rounded, info.min, info.max, out=rounded)
        return rounded.astype(dtype, copy=False)
    return array.astype(dtype, copy=False)
