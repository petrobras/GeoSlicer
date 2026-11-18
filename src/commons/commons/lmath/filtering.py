import numpy as np
from scipy import signal


def lowPassFilter2(signalp, Ts, Ncoef, cutFreq):
    single_dimensional = len(signalp.shape) == 1
    if single_dimensional:
        signalp = signalp.reshape((-1, 1))

    Ts = Ts * 1e-3
    impFiltered = np.zeros([signalp.shape[0], signalp.shape[1]])
    for j in range(0, signalp.shape[1]):
        impFiltered[:, j], h = lowPassFilter1(signalp[:, j], Ts, Ncoef, cutFreq)

    if single_dimensional:
        return impFiltered[:, 0]
    else:
        return impFiltered


def lowPassFilter1(signalp, Ts, Ncoef, cutFreq):
    Fnorm = cutFreq * 2 * Ts
    h = signal.firwin(Ncoef + 1, Fnorm)

    signalMod = np.zeros(2 * Ncoef + signalp.size + 1)

    signalMod[0:Ncoef] = signalp[0]
    signalMod[Ncoef : Ncoef + signalp.size] = signalp
    signalMod[Ncoef + signalp.size : 2 * Ncoef + signalp.size + 1] = signalp[-1]

    impFiltered = signal.lfilter(h, 1, signalMod)
    impFiltered = impFiltered[(int)(3 * Ncoef / 2) : (int)(signalp.size + (3 * Ncoef / 2))]
    return impFiltered, h


class DistributionFilter:
    def __init__(self, data_array):
        self.arraymean = np.nanmean(data_array)
        self.arraystd = np.nanstd(data_array)

    @property
    def mean(self):
        return self.arraymean

    @property
    def std(self):
        return self.arraystd

    def get_filter_min_max(self, number_of_stds):
        min_ = self.arraymean - number_of_stds * self.arraystd
        max_ = self.arraymean + number_of_stds * self.arraystd
        return min_, max_
