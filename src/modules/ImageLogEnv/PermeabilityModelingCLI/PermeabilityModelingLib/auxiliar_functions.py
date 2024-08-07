# -*- coding: utf-8 -*-
"""
Created on Fri Nov 13 13:32:43 2020

@author: leandro
"""
import numpy as np
import pandas as pd

from dataclasses import dataclass
from typing import List


def compute_segment_proportion_array(segmentation, id_segment_null):
    """
    Parameters
    ----------
    segmentation : TYPE - Segmentation-label
        Segmented image-log data with at least 3 segments, Marcopore, M1 and M2

    Returns
    -------
    proportions : TYPE
        Proportion of segments in function of depth, each column is related to a different segment
    segment_list : TYPE
        segment "ID" list, in case is is out of order

    """
    segment_list = np.unique(segmentation)

    auxiliar_array2count = np.zeros(np.shape(segmentation))
    auxiliar_array2count[segmentation == id_segment_null] = 1

    n_null_values = np.sum(auxiliar_array2count, axis=1)
    n_null_values = np.sum(n_null_values, axis=1)

    n_lines = np.shape(segmentation)[0]
    proportions = np.zeros((n_lines, len(segment_list)))

    for segment_index, segment in enumerate(segment_list):
        auxiliar_array2count = np.zeros(np.shape(segmentation))
        auxiliar_array2count[segmentation == segment] = 1
        aux = np.sum(auxiliar_array2count, axis=1)
        segmentProportion = np.sum(aux, axis=1)
        total_valid_pixels = (np.shape(segmentation)[2] * np.shape(segmentation)[1]) - n_null_values
        result = np.divide(
            segmentProportion, total_valid_pixels, out=np.zeros_like(segmentProportion), where=total_valid_pixels != 0
        )
        proportions[:, segment_index] = result

    return proportions, segment_list


def compute_permeability(proportions, segment_list, porosity_array, perm_parameters, ids):
    """
    Parameters
    ----------
    proportions : TYPE
        1D proportion of the segment list (Marcopore, M1 and M2) in function of depth
    segment_list : TYPE
        List of segment "ids", at least 3 segments, Marcopore, M1 and M2
    porosity_array : TYPE
        Porosity log. It must have the same dimension of the segmented image/proportion
    perm_parameters : TYPE
        Parameters of the permeability equation of the paper Jesus, Candida, 2016
    ids : TYPE
        List of segment "ids", at least 3 segments, Marcopore, M1 and M2

    Returns
    -------
    permeability : TYPE
        1D permeability in function of depth

    """

    permeability = np.zeros((porosity_array.shape))
    n_lines = np.shape(porosity_array)[0]

    segment_index = 0
    index_parameter = 1
    for segment in segment_list:
        # Macro pore
        if segment == ids[0]:
            permeability += perm_parameters[0] * proportions[:, segment_index].reshape(n_lines, 1)
        # Rock Matrix (not null value)
        elif segment != ids[1]:
            aux = proportions[:, segment_index].reshape(n_lines, 1)
            permeability += perm_parameters[index_parameter] * np.multiply(
                aux, np.power(porosity_array, perm_parameters[index_parameter + 1])
            )
            index_parameter = index_parameter + 2

        segment_index = segment_index + 1

    return permeability


def objective_funcion(
    perm_parameters,
    permebility_plugs,
    proportions_2opt,
    segment_list,
    porosity_2opt,
    ids,
    depthArray: np.ndarray,
    kdsOptimizationDataFrame: pd.DataFrame = None,
    kdsOptimizationWeight=None,
) -> float:
    permeability_2opt = compute_permeability(proportions_2opt, segment_list, porosity_2opt, perm_parameters, ids)
    error = np.sum(np.power(np.log10(permebility_plugs) - np.log10(permeability_2opt), 2))

    hasKdsOptimization = len(kdsOptimizationDataFrame.index) > 0 if kdsOptimizationDataFrame is not None else False
    if (
        hasKdsOptimization
        and kdsOptimizationDataFrame is not None
        and kdsOptimizationWeight is not None
        and len(permebility_plugs) > 0
    ):
        error = np.sqrt(error) / len(permeability_2opt)
        kdsOptError = kdsOptimizationTerm(
            depthArray=depthArray,
            kiArray=permeability_2opt,
            kdsOptimizationDataFrame=kdsOptimizationDataFrame,
            kdsOptimizationWeight=kdsOptimizationWeight,
        )
        error += kdsOptError

    return error


@dataclass
class KdsOptimization:
    startDepth: float
    stopDepth: float
    kDst: float
    kRro: float
    depthInterval: float = None

    def __post_init__(self):
        self.depthInterval = self.stopDepth - self.startDepth

    def calculateKiH(self, kiArray: np.ndarray, depthArray: np.ndarray):
        if len(kiArray) != len(depthArray):
            raise ValueError("kiArray and depthArray must have the same length")

        # Trim depthArray in interval valid for startDepth and stopDepth
        validDepthArrayIndexes = np.argwhere((depthArray >= self.startDepth) & (depthArray <= self.stopDepth))

        if len(validDepthArrayIndexes) == 0 or len(depthArray) <= 1 or len(kiArray) <= 1:
            return 0.0

        trimmedDepthArray = depthArray[validDepthArrayIndexes]
        minDepth = depthArray[0]
        startDepth = trimmedDepthArray[0].item()

        # Adjusting startDepth to be the first valid depth in interval
        if minDepth <= self.startDepth:
            startDepth = min(self.startDepth, startDepth)

        stopDepth = trimmedDepthArray[-1].item()
        # Adjusting start/stop depth in case there is only one valid depth value in interval
        if len(trimmedDepthArray) == 1:
            startDepth = min(trimmedDepthArray[0].item(), self.startDepth)
            stopDepth = min(stopDepth, self.stopDepth)
            trimmedDepthArray = np.array([startDepth, stopDepth])
            ki = kiArray[validDepthArrayIndexes[0]].item()
            trimmedKiArray = np.array([ki, ki])

        trimmedKiArray = kiArray[validDepthArrayIndexes]
        trimmedDepthArray[0] = startDepth
        kiAvg = np.mean(trimmedKiArray)
        kiH = kiAvg * abs(stopDepth - startDepth)

        return kiH.item()

    def conflicts(self, other: "KdsOptimization") -> bool:
        return self.startDepth <= other.stopDepth and self.stopDepth >= other.startDepth


def kdsOptimizationTerm(
    depthArray: np.ndarray, kiArray: np.ndarray, kdsOptimizationDataFrame: pd.DataFrame, kdsOptimizationWeight: float
) -> float:
    kdsOptimizationIntervals: List[KdsOptimization] = []
    for _, row in kdsOptimizationDataFrame.iterrows():
        startDepth = float(row.iloc[0])
        stopDepth = float(row.iloc[1])
        kDst = float(row.iloc[2])
        kRro = float(row.iloc[3])

        kdsOptimizationIntervals.append(KdsOptimization(startDepth, stopDepth, kDst, kRro))

    errorValues = []
    hTotal = 0
    for interval in kdsOptimizationIntervals:
        if interval.kRro == 0:
            continue

        kiH = interval.calculateKiH(kiArray, depthArray)
        kDst_kRro = interval.kDst / interval.kRro
        if np.isclose(kiH, 0) or np.isclose(kDst_kRro, 0):
            continue

        error = np.power(np.log10(kiH) - np.log10(kDst_kRro), 2)
        errorValues.append(error)
        hTotal += interval.depthInterval

    if hTotal == 0:
        return 0.0

    errorSum = (kdsOptimizationWeight / hTotal) * np.sqrt(np.sum(errorValues))

    return errorSum
