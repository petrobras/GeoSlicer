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
    Compute the proportion/fractions of each segment across depth of a 2D image log.

    Parameters
    ----------
    segmentation : np.ndarray
        2D segmented image array with shape (depth, height, width) containing integer segment IDs/labels.
        For permeability modeling, it must have at least 3 segments: Null segment, macropore, M1.
    id_segment_null : int
        Segment ID representing null/background/invalid values to exclude from calculations.
        Pixels with this ID are not counted in the total valid pixel count.

    Returns
    -------
    proportions : np.ndarray
        2D array of shape (n_depth_levels, n_segments) where each element represents the
        proportion/fraction of a segment at a given depth. Rows sum to 1.0 (unless all
        pixels at that depth are null). Each column corresponds to a segment in segment_list.
    segment_list : np.ndarray
        1D array of unique segment IDs found in the segmentation array.
        Segments are ordered as returned by np.unique().
    """
    segment_list = np.unique(segmentation)

    auxiliar_array2count = np.zeros(np.shape(segmentation))
    auxiliar_array2count[segmentation == id_segment_null] = 1

    n_null_values = np.sum(auxiliar_array2count, axis=1)
    n_null_values = np.sum(n_null_values, axis=1)

    n_lines = np.shape(segmentation)[0]
    proportions = np.zeros((n_lines, len(segment_list)))

    total_valid_pixels = (np.shape(segmentation)[2] * np.shape(segmentation)[1]) - n_null_values
    for segment_index, segment in enumerate(segment_list):
        auxiliar_array2count = np.zeros(np.shape(segmentation))
        auxiliar_array2count[segmentation == segment] = 1
        aux = np.sum(auxiliar_array2count, axis=1)
        segmentProportion = np.sum(aux, axis=1)
        result = np.divide(
            segmentProportion, total_valid_pixels, out=np.zeros_like(segmentProportion), where=total_valid_pixels != 0
        )
        proportions[:, segment_index] = result

    return proportions, segment_list


def smooth_proportions(proportions: np.ndarray, window_size: int) -> np.ndarray:
    """
    Apply centered moving-average smoothing to proportions and renormalize rows to sum to 1.

    Edge values are padded to handle boundaries symmetrically. Each row is renormalized after
    smoothing to maintain proportions as valid probability distributions.

    Parameters
    ----------
    proportions : np.ndarray
        2D array of shape (n_depth_levels, n_segments) where each column is a segment proportion.
    window_size : int
        Size of the moving-average window (>= 1). window_size=1 performs no smoothing.

    Returns
    -------
    np.ndarray
        Smoothed proportions with each row summing to 1.0.
    """
    proportions = np.asarray(proportions, dtype=float)

    if proportions.ndim != 2:
        raise ValueError("proportions must be a 2D array")

    if window_size < 1:
        raise ValueError("window_size must be >= 1")

    if window_size == 1:
        smoothed = proportions.copy()
    else:
        kernel = np.ones(window_size, dtype=float) / float(window_size)

        def _centered_moving_average_1d(x: np.ndarray) -> np.ndarray:
            left = np.repeat(x[0], window_size // 2)
            right = np.repeat(x[-1], window_size // 2)
            padded = np.concatenate((left, x, right))
            convolved = np.convolve(padded, kernel, mode="valid")
            return convolved[: x.size]

        smoothed = np.apply_along_axis(_centered_moving_average_1d, axis=0, arr=proportions)

    row_sums = smoothed.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    smoothed = smoothed / row_sums

    return smoothed


def compute_permeability(proportions, segment_list, porosity_array, perm_parameters, ids, excess_k_power_parameter=1.0):
    """
    Calculate permeability by combining segment proportions and porosity using empirical models.

    Macropore segments contribute via a single multiplier parameter, while rock matrix segments
    use power-law porosity-dependent contributions. Minimum permeability is set to 0.000001 to avoid
    zero/negative values.

        Based on the article "Permeability Estimation Using Ultrasonic Borehole Image Logs in Dual-Porosity
            Carbonate Reservoirs", by Candida Menezes de Jesus, André Luiz Martins Compan, and Rodrigo Surmas.

    Parameters
    ----------
    proportions : np.ndarray
        2D array of segment proportions by depth, shape (n_depth, n_segments).
    segment_list : np.ndarray
        Array of unique segment IDs (at least 3: macropore, matrix, null/ignored).
    porosity_array : np.ndarray
        Porosity values aligned with proportions array.
    perm_parameters : list
        Parameters of the permeability equation of the paper Jesus, Candida, 2016
    ids : list
        [macropore_segment_id, null_segment_id] to identify special segments, macro-pore and null/ignored.

    Returns
    -------
    np.ndarray
        Permeability values by depth. NaN where all proportions sum to 0.
    """

    permeability = np.zeros((porosity_array.shape))
    n_lines = np.shape(porosity_array)[0]
    segment_index = 0
    index_parameter = 0
    for segment in segment_list:
        # Macro pore
        if segment == ids[0]:
            permeability += perm_parameters[index_parameter] * np.power(
                proportions[:, segment_index].reshape(n_lines, 1), excess_k_power_parameter
            )
            index_parameter += 1
        # Rock Matrix (not null value)
        elif segment != ids[1]:
            aux = proportions[:, segment_index].reshape(n_lines, 1)
            permeability += perm_parameters[index_parameter] * np.multiply(
                aux, np.power(porosity_array, perm_parameters[index_parameter + 1])
            )
            index_parameter = index_parameter + 2

        segment_index = segment_index + 1

    # In cases where porosity is around 0, the permeability value is defined as 0.000001
    permeability[permeability <= 0] = 0.000001
    # Remove permeability values related to proportions rows where the sum of the proportions is 0
    zeros_proportions_indices = np.sum(proportions, axis=1) == 0
    permeability[zeros_proportions_indices] = np.nan

    return permeability


def compute_permeability_rock_matrix(proportions, segment_list, porosity_array, perm_parameters, ids):
    """
    Calculate rock matrix permeability by excluding macropore contribution.

    Sets macropore proportion to 0, renormalizes other segments, then computes permeability
    using only rock matrix contributions.


    Parameters
    ----------
    proportions : np.ndarray
        2D array of segment proportions by depth, shape (n_depth, n_segments).
    segment_list : np.ndarray
        Array of unique segment IDs (at least 3: macropore, matrix, null/ignored).
    porosity_array : np.ndarray
        Porosity values aligned with proportions array.
    perm_parameters : list
        Permeability model parameters.
    ids : list
        [macropore_segment_id, null_segment_id].

    Returns
    -------
    np.ndarray
        Rock matrix permeability by depth. NaN where proportions sum to 0.
    """
    # Define the proportion of the macropore segment as 0 to compute only the permeability related to the rock matrix
    index_macropore = np.where(segment_list == ids[0])[0][0]
    proportions[:, index_macropore] = 0
    row_sums = proportions.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    proportions = proportions / row_sums

    permeability = np.zeros((porosity_array.shape))
    n_lines = np.shape(porosity_array)[0]
    segment_index = 0
    index_parameter = 0
    for segment in segment_list:
        # Macro pore
        if segment == ids[0]:
            index_parameter += 1
        # Rock Matrix (not null value)
        elif segment != ids[1]:
            aux = proportions[:, segment_index].reshape(n_lines, 1)
            permeability += perm_parameters[index_parameter] * np.multiply(
                aux, np.power(porosity_array, perm_parameters[index_parameter + 1])
            )
            index_parameter = index_parameter + 2

        segment_index = segment_index + 1

    # In cases where porosity is around 0, the permeability value is defined as 0.000001
    permeability[permeability <= 0] = 0.000001
    # Remove permeability values related to proportions rows where the sum of the proportions is 0
    zeros_proportions_indices = np.sum(proportions, axis=1) == 0
    permeability[zeros_proportions_indices] = np.nan
    return permeability


def objective_funcion(
    perm_parameters,
    permeability_plugs,
    proportions_2opt,
    segment_list,
    porosity_2opt,
    ids,
    depth2work: np.ndarray,
    proportions_2work,
    porosity_image2work,
    kdsOptimizationDataFrame: pd.DataFrame = None,
    kdsOptimizationWeight=None,
    inOptimization=False,
    use_only_matrix_k_plug_error_term=False,
    excess_k_power_parameter: float = 1.0,
) -> float:
    """
    Calculate optimization error comparing measured plugs against modeled permeability.
    Computes rock matrix permeability and error against plug measurements. Optionally adds
    KDS optimization term if provided.

        Based on the article "Permeability Estimation Using Ultrasonic Borehole Image Logs in Dual-Porosity
            Carbonate Reservoirs", by Candida Menezes de Jesus, André Luiz Martins Compan, and Rodrigo Surmas.

    Parameters
    ----------
    perm_parameters : list
        Model parameters to optimize.
    permeability_plugs : np.ndarray
        Measured permeability at plug locations.
    proportions_2opt : np.ndarray
        Proportions at optimization depths.
    segment_list : np.ndarray
        Segment IDs/labels.
    porosity_2opt : np.ndarray
        Porosity at optimization depths.
    ids : list
        [macropore_id, null_id].
    depth2work : np.ndarray
        Depth array for full working data.
    proportions_2work : np.ndarray
        Proportions at all working depths.
    porosity_image2work : np.ndarray
        Porosity at all working depths.
    kdsOptimizationDataFrame : pd.DataFrame, optional
        KDST constraints by depth interval.
    kdsOptimizationWeight : float, optional
        Weight for KDST error term.
    inOptimization : bool
        If True, return single error value; if False, return (error, error_plug, kdsOptError).

    Returns
    -------
    float or tuple
        Total error (or tuple of errors if inOptimization=False).
    """
    # use compute_permeability_rock_matrix instead of compute_permeability if we want to compute only the permeability related to the rock matrix
    if use_only_matrix_k_plug_error_term:
        permeability_2opt = compute_permeability_rock_matrix(
            proportions_2opt, segment_list, porosity_2opt, perm_parameters, ids
        )
    else:  # use compute_permeability to compute the permeability including both macro-pore and rock matrix,
        permeability_2opt = compute_permeability(
            proportions_2opt, segment_list, porosity_2opt, perm_parameters, ids, excess_k_power_parameter
        )

    not_nan_indices = ~np.isnan(permeability_2opt)
    permeability_plugs = permeability_plugs[not_nan_indices]
    permeability_2opt = permeability_2opt[not_nan_indices]
    error_plug = np.sum(np.power(np.log10(permeability_plugs) - np.log10(permeability_2opt), 2))
    error_plug = np.sqrt(error_plug) / len(permeability_2opt)
    error = error_plug
    kdsOptError = 0.0

    hasKdsOptimization = len(kdsOptimizationDataFrame.index) > 0 if kdsOptimizationDataFrame is not None else False
    if hasKdsOptimization and kdsOptimizationDataFrame is not None and kdsOptimizationWeight is not None:

        kiH, kDstlkRro, h, kRro_interval_values = calculate_kiH_for_intervals(
            kdsOptimizationDataFrame,
            depth2work,
            proportions_2work,
            segment_list,
            porosity_image2work,
            perm_parameters,
            ids,
            excess_k_power_parameter,
        )

        kdsOptError = np.power(np.log10(kiH) - np.log10(kDstlkRro), 2)
        kdsOptError = kdsOptimizationWeight * np.sqrt(np.sum(kdsOptError)) / float(len(h))

        error = kdsOptError + error_plug

    if inOptimization:
        return error
    else:
        return error, error_plug, kdsOptError


def calculate_kiH_for_intervals(
    kdsOptimizationDataFrame: pd.DataFrame,
    depth2work: np.ndarray,
    proportions_2work: np.ndarray,
    segment_list: np.ndarray,
    porosity_image2work: np.ndarray,
    perm_parameters: List,
    ids: List,
    excess_k_power_paramater: float,
) -> List[float]:
    """
    Compute kiH (equivalent of mean permeability times depth interval) for each interval with measured KDS.

    Parameters
    ----------
    kdsOptimizationDataFrame : pd.DataFrame
        DataFrame with columns [startDepth, stopDepth, kDst, kRro].
    depth2work : np.ndarray
        Depth array for working data.
    proportions_2work : np.ndarray
        Segment proportions at all working depths.
    segment_list : np.ndarray
        Segment IDs.
    porosity_image2work : np.ndarray
        Porosity at all working depths.
    perm_parameters : List
        Permeability model parameters.
    ids : List
        [macropore_id, null_id].

    Returns
    -------
    tuple of Lists
        (kiH_values, kDst_kRro_values, interval_heights, kRro_values) for each interval.
    """
    kiH_values = []
    kDst_kRro_values = []
    h = []
    kRro_interval_values = []
    for _, row in kdsOptimizationDataFrame.iterrows():
        startDepth = float(row.iloc[0])
        stopDepth = float(row.iloc[1])
        kDst = float(row.iloc[2])
        kRro = float(row.iloc[3])

        if kRro == 0:
            continue

        indices_of_interval = np.where((depth2work >= startDepth) & (depth2work <= stopDepth))[0]
        permeability_of_interval = compute_permeability(
            proportions_2work[indices_of_interval],
            segment_list,
            porosity_image2work[indices_of_interval],
            perm_parameters,
            ids,
            excess_k_power_paramater,
        )

        kiH = permeability_of_interval.mean() * np.abs(stopDepth - startDepth)
        kiH_values.append(kiH)
        kDst_kRro_values.append(kDst / kRro)

        h.append(np.abs(stopDepth - startDepth))
        kRro_interval_values.append(kRro)

    return kiH_values, kDst_kRro_values, h, kRro_interval_values


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
