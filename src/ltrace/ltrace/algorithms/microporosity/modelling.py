import configparser
import typing

from dataclasses import dataclass
from numba import uint16, uint32, uint64, float32
from numba import njit, prange
from numba.types import ListType, Array

import numpy as np

import slicer


"""
Normalization (just for reference)
def norm(x, minimum, maximum):
    return minimum + (maximum - minimum) * x / 65535.0


def denorm(x, current_min, current_max, into_min=0, into_max=65535):
    return into_min + (into_max - into_min) * (x - current_min) / (current_max - current_min)
"""


@njit(parallel=True)
def fastMapping(
    porosityImageArray: Array(float32, 3, "C"),
    labelsArray: Array(uint16, 3, "C"),
    maskArray: Array(uint16, 3, "C"),
    targets: ListType(uint16),
):
    """
    Same as:
    # porosityImageFinalArray = np.clip(porosityImageFloat, 0, 1, dtype=np.float32)
    # porosityImageFinalArray[self.__lastLabelsArray >= targets[1]] = np.float32(0)
    # porosityImageFinalArray[self.__lastLabelsArray == 0] = np.float32(0)
    # porosityImageFinalArray[self.__lastLabelsArray == targets[0]] = np.float32(1)
    # porosityImageFinalArray *= self.__lastMaskArray
    """

    z, y, x = porosityImageArray.shape
    for i in prange(z):
        for j in range(y):
            for k in range(x):

                if maskArray[i, j, k] == 0:
                    porosityImageArray[i, j, k] = np.float32(0)
                    continue

                if labelsArray[i, j, k] == targets[0]:
                    porosityImageArray[i, j, k] = np.float32(1)
                elif labelsArray[i, j, k] >= targets[1]:
                    porosityImageArray[i, j, k] = np.float32(0)
                elif labelsArray[i, j, k] == 0:
                    porosityImageArray[i, j, k] = np.float32(0)
                else:
                    porosityImageArray[i, j, k] = max(0, min(1, porosityImageArray[i, j, k]))

    return porosityImageArray


@njit
def fast1DBinCountUInt64(array: Array(uint32, 1, "C")) -> Array(uint64, 1, "C"):
    max_ = np.max(array)
    out = np.zeros(max_ + 1, dtype=np.uint64)

    for i in range(len(array)):
        out[array[i]] += 1

    return out


def mapValue(values, x: typing.Union[float, typing.List[float]]):
    # Compute the attenuation factor for the modelled region
    accsum = np.cumsum(values)
    return np.interp(x, accsum / accsum[-1], np.arange(1, len(values) + 1))


@dataclass
class DataVar:
    values: np.ndarray
    start: uint32
    label: uint32
    name: str
    threshold: np.ndarray = None
    color: tuple = (0, 0, 0)


class SampleModel:
    def __init__(self, pcrRange=(0.0, 1.0)):
        self.variables: typing.Dict[str, DataVar] = {}
        self.pcrMin = np.float32(pcrRange[0])
        self.pcrMax = np.float32(pcrRange[1])
        self.image = None
        self.limits = None

    def addData(self, image: np.ndarray, mask: np.ndarray, label: int = 0, color: tuple = (0, 0, 0)):
        self.image = image
        self.addSubGroup("Data", mask, label, color, markers=[0.0001, 0.99])
        self.limits = [int(np.round(v)) for v in self.variables["Data"].threshold]

    def addSubGroup(self, name: str, mask: np.ndarray, label: int, color: tuple, markers: typing.List[float] = None):
        if self.image is None:
            raise ValueError("Image is missing")

        if np.any(mask.shape != self.image.shape):
            raise ValueError("Mask and image must have the same shape")

        counts = fast1DBinCountUInt64(self.image[mask])
        counts[0] = 0  # exclude background 0
        threshold = mapValue(counts, x=markers)

        if self.limits is not None:
            min_, max_ = self.limits
            posmax = min(len(counts), max_)
            posmin = max(min_, 0)
        else:
            posmax = len(counts)
            posmin = 0

        for i in range(posmin, posmax, 1):
            if counts[i] > 0:
                posmin = i
                break

        counts = counts if posmin == 0 else counts[posmin:]
        self.variables[name] = DataVar(counts, posmin, label, name, threshold, color)

    def threshold(self, key, normalized=False):
        value = self.variables[key].threshold
        if normalized:
            return self.pcrMin + (self.pcrMax - self.pcrMin) * value / 65535
        return value

    def setThreshold(self, key, value: np.ndarray, normalized=False):
        if normalized:
            value = 65535 * (value - self.pcrMin) / (self.pcrMax - self.pcrMin)
        self.variables[key].threshold = value

    def getImage(self, normalized=False):
        if normalized:
            return self.pcrMin + (self.pcrMax - self.pcrMin) * self.image / 65535
        return self.image
