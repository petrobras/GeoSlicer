# -*- coding: utf-8 -*-
"""
Created on Fri Nov 13 13:32:43 2020

@author: leandro
"""


import numpy as np
import csv


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

    segment_index = 0
    for segment in segment_list:
        auxiliar_array2count = np.zeros(np.shape(segmentation))
        auxiliar_array2count[segmentation == segment] = 1
        aux = np.sum(auxiliar_array2count, axis=1)
        proportions[:, segment_index] = np.sum(aux, axis=1)
        total_valid_pixels = (np.shape(segmentation)[2] * np.shape(segmentation)[1]) - n_null_values
        proportions[:, segment_index] = proportions[:, segment_index] / total_valid_pixels
        segment_index = segment_index + 1

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


def objective_funcion(perm_parameters, permebility_plugs, proportions_2opt, segment_list, porosity_2opt, ids):

    permeability_2opt = compute_permeability(proportions_2opt, segment_list, porosity_2opt, perm_parameters, ids)

    error = np.sum(np.power(np.log10(permebility_plugs) - np.log10(permeability_2opt), 2))

    return error
