#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above
#

from __future__ import print_function

import vtk

import pathlib
import sys
import numpy as np

import lasio
import mrml
import pandas as pd
import slicer
import slicer.util

from ltrace.ocr import parse_pdf
from scipy.interpolate import interp1d
from scipy.optimize import minimize

from ltrace.slicer.helpers import getDepthArrayFromVolume
from ltrace.slicer.cli_utils import writeToTable, readFrom
from PermeabilityModelingLib import *


def progressUpdate(value):
    """
    Progress Bar updates over stdout (Slicer handles the parsing)
    """
    print(f"<filter-progress>{value}</filter-progress>")
    sys.stdout.flush()


def dataframeFromTable(tableNode):
    """Optimized version from slicer.util.dataframeFromTable

    Convert table node content to pandas dataframe.

    Table content is copied. Therefore, changes in table node do not affect the dataframe,
    and dataframe changes do not affect the original table node.
    """
    try:
        # Suppress "lzma compression not available" UserWarning when loading pandas
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter(action="ignore", category=UserWarning)
            import pandas as pd
    except ImportError:
        raise ImportError(
            "Failed to convert to pandas dataframe. Please install pandas by running `slicer.util.pip_install('pandas')`"
        )

    vtable = tableNode.GetTable()
    data = []
    columns = []
    for columnIndex in range(vtable.GetNumberOfColumns()):
        vcolumn = vtable.GetColumn(columnIndex)
        numberOfComponents = vcolumn.GetNumberOfComponents()
        column_name = vcolumn.GetName()
        columns.append(column_name)

        if numberOfComponents == 1:
            column_data = [vcolumn.GetValue(rowIndex) for rowIndex in range(vcolumn.GetNumberOfValues())]
        else:
            column_data = []
            for rowIndex in range(vcolumn.GetNumberOfTuples()):
                item = [vcolumn.GetValue(rowIndex, componentIndex) for componentIndex in range(numberOfComponents)]
                column_data.append(tuple(item))
        data.append(column_data)

    dataframe = pd.DataFrame(zip(*data), columns=columns)

    return dataframe


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--log_por", type=str, dest="log_por", required=True, help="Porosity log id")
    parser.add_argument("--depth_por", type=str, dest="depth_por", required=True, help="Porosity depth log")
    parser.add_argument("--master1", type=str, dest="inputVolume1", required=True, help="Amplitude image log")
    parser.add_argument("--depth_plugs", type=str, dest="depth_plugs", required=True, help="Amplitude image log")
    parser.add_argument("--perm_plugs", type=str, dest="perm_plugs", required=True, help="Amplitude image log")
    parser.add_argument(
        "--kdsOptimizationTable", dest="kdsOptimizationTable", required=False, help="Kds Optimization Table"
    )
    parser.add_argument(
        "--kdsOptimizationWeight",
        type=float,
        dest="kdsOptimizationWeight",
        required=False,
        help="Kds Optimization Weight",
    )

    parser.add_argument(
        "--outputvolume", type=str, dest="outputVolume", default=None, help="Output labelmap (3d) Values"
    )
    parser.add_argument("--class1", type=float, default=1, help="Multiplier value")
    parser.add_argument("--nullable", type=float, default=-9999, help="Null value representation")

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )
    parser.add_argument("--fractionSmoothingWindowSize", type=int, default=10, help="Fraction Smoothing Window Size")
    parser.add_argument("--excessKFractionThreshold", type=float, default=1.0, help="Excess-K Fraction Threshold")
    parser.add_argument(
        "--useMatrixKPlugErrorTerm", action="store_true", default=False, help="Use Matrix K Plug Error Term"
    )
    parser.add_argument("--excessKPowerParamater", type=float, default=1.0, help="Excess-K Power Paramater")

    args = parser.parse_args()

    if args.nullable == args.class1:
        raise RuntimeError("Null/missing value cannot be defined as MacroPore")

    ## LOAD DATA
    progressUpdate(value=0.0)

    # Read as slicer node (copy)
    porosity_las_vol = readFrom(args.log_por, slicer.vtkMRMLScalarVolumeNode)
    porosity_depth_las_vol = readFrom(args.depth_por, slicer.vtkMRMLScalarVolumeNode)
    segmentation = readFrom(args.inputVolume1, slicer.vtkMRMLScalarVolumeNode)
    depth_plugs_vol = readFrom(args.depth_plugs, slicer.vtkMRMLScalarVolumeNode)
    permebility_plugs_vol = readFrom(args.perm_plugs, slicer.vtkMRMLScalarVolumeNode)

    # Access numpy view (reference)
    porosity_las = slicer.util.arrayFromVolume(porosity_las_vol).squeeze()
    depth_las = slicer.util.arrayFromVolume(porosity_depth_las_vol).squeeze() / 1000
    segmentation_array = slicer.util.arrayFromVolume(segmentation)
    depth_image_array = getDepthArrayFromVolume(segmentation).squeeze()
    depth_plugs = (slicer.util.arrayFromVolume(depth_plugs_vol) / 1000).squeeze()
    permeability_plugs = slicer.util.arrayFromVolume(permebility_plugs_vol)
    permeability_plugs[permeability_plugs < 0.001] = 0.001

    fraction_smoothing_window_size = args.fractionSmoothingWindowSize
    excess_k_fraction_threshold = args.excessKFractionThreshold
    use_only_matrix_k_plug_error_term = args.useMatrixKPlugErrorTerm
    excess_k_power_paramater = args.excessKPowerParamater

    kdsOptimizationDataFrame = None
    if args.kdsOptimizationTable is not None:
        kdsOptimizationTable = readFrom(
            args.kdsOptimizationTable, slicer.vtkMRMLTableNode, slicer.vtkMRMLTableStorageNode
        )
        kdsOptimizationDataFrame = dataframeFromTable(kdsOptimizationTable)

    # Mantain segmentation image in ascending order
    if depth_image_array[0] > depth_image_array[-1]:
        depth_image_array[:] = np.flipud(depth_image_array)
        # The segmentation is already in the correct order
        # segmentation_array[:] = np.flipud(segmentation_array)

    progressUpdate(value=0.15)

    ## FILTER DATA
    # filter data in a valid depth range (not nan in LAS)
    depth_las_notnan = depth_las[~np.isnan(porosity_las)]
    porosity_las_notnan = porosity_las[~np.isnan(porosity_las)]

    # If porosity is in percentage, convert to fraction
    if porosity_las_notnan.max() > 1.01:
        porosity_las_notnan = porosity_las_notnan / 100
        print("Porosity values converted from percentage to fraction.")

    # Define the depth range to work where both LAS and image data are available.
    depth_initial = np.array([[depth_las_notnan[0], depth_image_array[0]]], dtype="float").max()
    depth_final = np.array([[depth_las_notnan[-1], depth_image_array[-1]]], dtype="float").min()

    index2work_image = np.nonzero((depth_image_array > depth_initial) & (depth_image_array < depth_final))
    depth2work_image = depth_image_array[index2work_image]

    # Crop data within the valid depth range
    f_interp = interp1d(depth_las_notnan, porosity_las_notnan, kind="linear")
    porosity_image2work = f_interp(depth2work_image)
    porosity_image2work = porosity_image2work.reshape(porosity_image2work.shape[0], 1)

    indexline_2work_image = np.asarray(index2work_image)[0, :]
    segmentation_image2work = segmentation_array[indexline_2work_image, :, :]

    permeability_plugs = permeability_plugs[(depth_plugs > depth_initial) & (depth_plugs < depth_final)]
    depth_plugs = depth_plugs[(depth_plugs > depth_initial) & (depth_plugs < depth_final)]
    permeability_plugs = permeability_plugs.reshape((permeability_plugs.shape[0], 1))

    # Transform the class1 and nullable from the segment index to the segment ID/label in the segmentation.
    segment_list = np.unique(segmentation_array)
    ids_ = [segment_list[int(args.class1)], segment_list[int(args.nullable)]]

    # if there is any background in the segmentation, it will be treated as the ignored/null segment.
    if np.any(segmentation_array == 0):
        ids_ = [segment_list[int(args.class1) + 1], segment_list[int(args.nullable) + 1]]
        segmentation_array = segmentation_array.copy()
        segmentation_array[segmentation_array == 0] = ids_[-1]

    # Define the depth range to optimize where both plugs and image data are available
    depth_2opt = depth_plugs

    # For stability, define the segment proportion/fraction as smoothed values of the original proportion computed in the segmentation.
    proportions, segment_list = compute_segment_proportion_array(segmentation_array, ids_[-1])
    proportions = smooth_proportions(proportions, window_size=fraction_smoothing_window_size)
    proportions_2work = proportions[indexline_2work_image, :]

    # Get proportions at the optimization depths by interpolation. We use nearest for stability.
    proportions_2opt = np.zeros((depth_2opt.shape[0], proportions.shape[1]))
    for j in range(proportions.shape[1]):
        f_interp = interp1d(depth_image_array, proportions[:, j], kind="nearest")
        proportions_2opt[:, j] = f_interp(depth_2opt)

    # In investigation: Additional parameter of macro pore fraction threshold to filter plugs with high karstification that can lead to instability in the optimization.
    indexes_high_karstification = proportions_2opt[:, int(args.class1)] > excess_k_fraction_threshold
    print(
        "Number of plugs in high karstification regions (fraction of macro pore >",
        excess_k_fraction_threshold * 100,
        "%): ",
        np.sum(indexes_high_karstification),
    )
    depth_2opt = depth_2opt[~indexes_high_karstification]
    proportions_2opt = proportions_2opt[~indexes_high_karstification]
    permeability_plugs = permeability_plugs[~indexes_high_karstification]
    print("Final number of plugs used for optimization: ", permeability_plugs.shape[0])

    # Get porosity values at the optimization depths by interpolation.
    f_interp = interp1d(depth_las_notnan, porosity_las_notnan, kind="linear")
    porosity_2opt = f_interp(depth_2opt).reshape((depth_2opt.shape[0], 1))

    print("KDST Weight for optimization: ", args.kdsOptimizationWeight)

    # START OPTIMIZATION SETTING
    # If in future version we decide to allow user to consider null segment optional, we should addapt the number of parameters
    # Define initial parameters and bounds for the optimization. We can define different bounds for macro pore and rock matrix parameters based on physical considerations and prior knowledge of the reservoir, to improve the stability and convergence of the optimization.
    number_parameters = (np.shape(segment_list)[0] - 2) * 2 + 1
    perm_parameters = np.ones(number_parameters)
    bnds = np.zeros((number_parameters, 2))
    index_parameter = 0
    for segment in segment_list:
        # Macro pore
        if segment == ids_[0]:
            perm_parameters[index_parameter] = 100
            bnds[index_parameter, 0] = 100
            bnds[index_parameter, 1] = 500000
            index_parameter += 1
        # Rock Matrix (not null value)
        elif segment != ids_[1]:
            perm_parameters[index_parameter] = 10
            bnds[index_parameter, 0] = 10
            bnds[index_parameter, 1] = 1000000
            perm_parameters[index_parameter + 1] = 4
            bnds[index_parameter + 1, 0] = 2
            bnds[index_parameter + 1, 1] = 6
            index_parameter = index_parameter + 2

    progressUpdate(value=0.3)

    # Optimization:
    res = minimize(
        objective_funcion,
        (perm_parameters),
        args=(
            np.array(permeability_plugs, np.double),
            np.array(proportions_2opt, np.double),
            segment_list,
            np.array(porosity_2opt, np.double),
            ids_,
            depth2work_image,
            proportions_2work,
            porosity_image2work,
            kdsOptimizationDataFrame,
            args.kdsOptimizationWeight,
            True,
            use_only_matrix_k_plug_error_term,
            excess_k_power_paramater,
        ),
        method="SLSQP",
        bounds=bnds,
        tol=1e-9,
    )

    # PRINTS
    # Print optimized parameters with their respective segment and parameter type (macro or matrix)
    optimized_parameters = res.x
    index_parameter = 0
    rock_matrix_count = 1
    print("---")
    for segment in segment_list:
        # Macro pore
        if segment == ids_[0]:
            print("Macro pore parameter:", optimized_parameters[index_parameter])
            index_parameter += 1
        # Rock Matrix (not null value)
        elif segment != ids_[1]:
            print("Rock matrix ", rock_matrix_count, "parameter 1:", optimized_parameters[index_parameter])
            print("Rock matrix ", rock_matrix_count, "parameter 2:", optimized_parameters[index_parameter + 1])
            rock_matrix_count += 1
            index_parameter = index_parameter + 2

    print("---")

    # Print errors before and after optimization, including the plug error and KDS error separately
    error_initial, error_plug_initial, kdsOptError_initial = objective_funcion(
        perm_parameters,
        np.array(permeability_plugs, np.double),
        np.array(proportions_2opt, np.double),
        segment_list,
        np.array(porosity_2opt, np.double),
        ids_,
        depth2work_image,
        proportions_2work,
        porosity_image2work,
        kdsOptimizationDataFrame,
        args.kdsOptimizationWeight,
        False,
        use_only_matrix_k_plug_error_term,
        excess_k_power_paramater,
    )
    print("Initial error: ", error_initial)
    print("Initial plug error: ", error_plug_initial)
    print("Initial KDST error: ", kdsOptError_initial)
    print("---")

    error_final, error_plug_final, kdsOptError_final = objective_funcion(
        res.x,
        np.array(permeability_plugs, np.double),
        np.array(proportions_2opt, np.double),
        segment_list,
        np.array(porosity_2opt, np.double),
        ids_,
        depth2work_image,
        proportions_2work,
        porosity_image2work,
        kdsOptimizationDataFrame,
        args.kdsOptimizationWeight,
        False,
        use_only_matrix_k_plug_error_term,
        excess_k_power_paramater,
    )
    print("Optimized error: ", error_final)
    print("Optimized plug error: ", error_plug_final)
    print("Optimized KDST error: ", kdsOptError_final)
    print("---")

    if kdsOptimizationDataFrame is not None:
        kiH_ksd_values = calculate_kiH_for_intervals(
            kdsOptimizationDataFrame,
            depth2work_image,
            proportions_2work,
            segment_list,
            porosity_image2work,
            res.x,
            ids_,
            excess_k_power_paramater,
        )

        for i in range(len(kiH_ksd_values[0])):
            kro_interval = kiH_ksd_values[3][i]
            print("Measured KDST for interval", i + 1, ":  ", kiH_ksd_values[1][i] * kro_interval)
            print("Optimized KH for interval", i + 1, ": ", kiH_ksd_values[0][i] * kro_interval)

    progressUpdate(value=0.9)

    # COMPUTE THE FINAL PERMEABILITY IN THE IMAGE SCALE BUT IN THE VALID DEPTH RANGE (index2work_image)
    permeability_2work = compute_permeability(
        proportions_2work, segment_list, porosity_image2work, res.x, ids_, excess_k_power_paramater
    )

    depth_permeability_matrix = np.column_stack((depth2work_image, permeability_2work))

    permeability = -np.ones((depth_image_array.shape[0], 1))
    permeability[indexline_2work_image, :] = permeability_2work

    output = permeability
    output[output == -1] = np.nan

    # Get output node ID
    outputNodeID = args.outputVolume
    if outputNodeID is None:
        raise ValueError("Missing output node")

    # Write output data
    data = np.column_stack((depth_image_array * 1000, output))
    output_df = pd.DataFrame(data, columns=["DEPTH", "PERMEABILITY"])
    writeToTable(output_df.round(decimals=5), outputNodeID, na_rep="nan")

    progressUpdate(value=1)

    print("---")
    print("Done")
