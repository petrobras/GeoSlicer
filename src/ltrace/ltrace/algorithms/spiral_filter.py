import numpy as np

from scipy.special import comb


def filter_spiral(data, T_depth, wlength_min=3.0, wlength_max=100.0, factor=1.0, transit_bandw=0.02):

    I = np.shape(data)[0]

    media = data.mean()
    data = data - media

    Fnorm_transit_bandw = 2 * T_depth * transit_bandw / 2
    Fnorm_transit_bandw_index = int(round(Fnorm_transit_bandw * I))
    Fnorm_max = 2 * T_depth / wlength_min
    Fnorm_max_index = int(round(Fnorm_max * I))
    Fnorm_min = 2 * T_depth / wlength_max
    Fnorm_min_index = int(round(Fnorm_min * I))

    if Fnorm_transit_bandw_index == 0:
        Fnorm_transit_bandw_index = 1

    FFT_abs = np.abs(np.fft.fft2(data))
    FFT_angle = np.angle(np.fft.fft2(data))

    ## Filtering step ##
    espiral_abs = np.zeros(np.shape(FFT_abs))

    # filtering in the positive side of the spectrum
    filtro1 = smooth_step(
        np.arange(I), Fnorm_min_index - Fnorm_transit_bandw_index, Fnorm_min_index + Fnorm_transit_bandw_index, 1
    )
    filtro2 = 1 - smooth_step(
        np.arange(I), Fnorm_max_index - Fnorm_transit_bandw_index, Fnorm_max_index + Fnorm_transit_bandw_index, 1
    )
    filtro = filtro1 * filtro2

    espiral_abs[:, 1] = FFT_abs[:, 1] * filtro * factor

    # filtering in the negative side of the spectrum
    filtro1 = np.flip(filtro1)
    filtro1 = np.concatenate((np.array([filtro1[0]]), filtro1[0:-1]))
    filtro2 = np.flip(filtro2)
    filtro2 = np.concatenate((np.array([filtro2[0]]), filtro2[0:-1]))
    filtro = filtro1 * filtro2

    espiral_abs[:, -1] = FFT_abs[:, -1] * filtro * factor

    # IFFT and return ##
    espiral_fft = espiral_abs * np.cos(FFT_angle) + espiral_abs * np.sin(FFT_angle) * 1j
    espiral = np.real(np.fft.ifft2(espiral_fft))

    data_filtered = data - espiral + media

    data_noise = espiral

    return data_filtered, data_noise


def smooth_step(x, x_min=0, x_max=1, N=1):
    # from https://stackoverflow.com/questions/45165452/how-to-implement-a-smooth-clamp-function-in-python
    x = np.clip((x - x_min) / (x_max - x_min), 0, 1)

    result = 0
    for n in range(0, N + 1):
        result += comb(N + n, n) * comb(2 * N + 1, N - n) * (-x) ** n

    result *= x ** (N + 1)

    return result
