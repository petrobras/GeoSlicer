import numpy as np
from scipy.fft import fft, ifft, ifftshift

__all__ = ["naninterp", "timewindow_crosscorrelation", "remove_step"]


def naninterp(array):
    nans = np.isnan(array)
    not_nans = ~nans
    flat_argwhere = lambda x: np.argwhere(x).flatten()
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
