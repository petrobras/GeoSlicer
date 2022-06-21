#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above
#

from __future__ import print_function

import vtk

import pathlib
import sys

import lasio
import mrml
import pandas as pd
import slicer
import slicer.util

from ltrace.ocr import parse_pdf
from scipy.interpolate import interp1d
from scipy.optimize import minimize

from ltrace.slicer.helpers import getDepthArrayFromVolume
from ltrace.slicer.cli_utils import writeToTable
from PermeabilityModelingLib import *


def progressUpdate(value):
    """
    Progress Bar updates over stdout (Slicer handles the parsing)
    """
    print(f"<filter-progress>{value}</filter-progress>")
    sys.stdout.flush()


def readFrom(volumeFile, builder):
    sn = slicer.vtkMRMLNRRDStorageNode()
    sn.SetFileName(volumeFile)
    nodeIn = builder()
    sn.ReadData(nodeIn)  # read data from volumeFile into nodeIn
    return nodeIn


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--log_por", type=str, dest="log_por", required=True, help="Porosity log id")
    parser.add_argument("--depth_por", type=str, dest="depth_por", required=True, help="Porosity depth log")
    parser.add_argument("--master1", type=str, dest="inputVolume1", required=True, help="Amplitude image log")
    parser.add_argument("--depth_plugs", type=str, dest="depth_plugs", required=True, help="Amplitude image log")
    parser.add_argument("--perm_plugs", type=str, dest="perm_plugs", required=True, help="Amplitude image log")
    parser.add_argument(
        "--outputvolume", type=str, dest="outputVolume", default=None, help="Output labelmap (3d) Values"
    )
    parser.add_argument("--class1", type=float, default=1, help="Multiplier value")
    parser.add_argument("--nullable", type=float, default=-9999, help="Null value representation")

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )
    args = parser.parse_args()

    if args.nullable == args.class1:
        raise RuntimeError("Null/missing value cannot be defined as MacroPore")

    ## LOAD DATA
    progressUpdate(value=0.0)
    # Read as slicer node (copy)
    porosity_las_vol = readFrom(args.log_por, mrml.vtkMRMLScalarVolumeNode)
    porosity_depth_las_vol = readFrom(args.depth_por, mrml.vtkMRMLScalarVolumeNode)
    segmentation = readFrom(args.inputVolume1, mrml.vtkMRMLScalarVolumeNode)
    depth_plugs_vol = readFrom(args.depth_plugs, mrml.vtkMRMLScalarVolumeNode)
    permebility_plugs_vol = readFrom(args.perm_plugs, mrml.vtkMRMLScalarVolumeNode)

    # Access numpy view (reference)
    porosity_las = slicer.util.arrayFromVolume(porosity_las_vol).squeeze()
    depth_las = slicer.util.arrayFromVolume(porosity_depth_las_vol).squeeze() / 1000
    segmentation_array = slicer.util.arrayFromVolume(segmentation)
    depth_image_array = getDepthArrayFromVolume(segmentation).squeeze()
    depth_plugs = (slicer.util.arrayFromVolume(depth_plugs_vol) / 1000).squeeze()
    permebility_plugs = slicer.util.arrayFromVolume(permebility_plugs_vol)
    permebility_plugs[permebility_plugs < 0.001] = 0.001

    # Mantain segmentation image in ascending order
    if depth_image_array[0] > depth_image_array[-1]:
        depth_image_array[:] = np.flipud(depth_image_array)
        segmentation_array[:] = np.flipud(segmentation_array)

    ## FILTER DATA
    progressUpdate(value=0.15)
    # filter data in a valid depth range (not nan in LAS)
    depth_las_notnan = depth_las[~np.isnan(porosity_las)]
    porosity_las_notnan = porosity_las[~np.isnan(porosity_las)]

    depth_initial = np.array([[depth_las_notnan[0], depth_image_array[0]]], dtype="float").max()
    depth_final = np.array([[depth_las_notnan[-1], depth_image_array[-1]]], dtype="float").min()

    index2work_image = np.nonzero((depth_image_array > depth_initial) & (depth_image_array < depth_final))
    depth2work_image = depth_image_array[index2work_image]

    f_interp = interp1d(depth_las_notnan, porosity_las_notnan, kind="linear")
    porosity_image2work = f_interp(depth2work_image)
    porosity_image2work = porosity_image2work.reshape(porosity_image2work.shape[0], 1)

    indexline_2work_image = np.asarray(index2work_image)[0, :]
    segmentation_image2work = segmentation_array[indexline_2work_image, :, :]

    permebility_plugs = permebility_plugs[(depth_plugs > depth_initial) & (depth_plugs < depth_final)]
    depth_plugs = depth_plugs[(depth_plugs > depth_initial) & (depth_plugs < depth_final)]
    permebility_plugs = permebility_plugs.reshape((permebility_plugs.shape[0], 1))

    # OPTIMIZATION
    ids_ = [args.class1, args.nullable]  # [id_macro_pore, id_null]

    depth_2opt = depth_plugs
    f_interp = interp1d(depth_las_notnan, porosity_las_notnan, kind="linear")
    porosity_2opt = f_interp(depth_2opt).reshape((depth_2opt.shape[0], 1))

    proportions, segment_list = compute_segment_proportion_array(segmentation_array, ids_[-1])
    proportions_2opt = np.zeros((depth_2opt.shape[0], proportions.shape[1]))
    for j in range(proportions.shape[1]):
        f_interp = interp1d(depth_image_array, proportions[:, j], kind="linear")
        proportions_2opt[:, j] = f_interp(depth_2opt)

    # adapting number of parameter if nullable is in the imagelog
    if args.nullable in segment_list:
        perm_parameters = [1.0] * ((np.shape(segment_list)[0] - 1) * 2 - 1)
    else:
        perm_parameters = [1.0] * ((np.shape(segment_list)[0]) * 2 - 1)

    progressUpdate(value=0.3)

    bnds = ((0.0, None),) * len(perm_parameters)
    res = minimize(
        objective_funcion,
        (perm_parameters),
        args=(
            np.array(permebility_plugs, np.double),
            np.array(proportions_2opt, np.double),
            segment_list,
            np.array(porosity_2opt, np.double),
            ids_,
        ),
        method="SLSQP",
        bounds=bnds,
    )
    print("Optimized parameters:")
    print(res.x)

    error_initial = objective_funcion(
        perm_parameters, permebility_plugs, proportions_2opt, segment_list, porosity_2opt, ids_
    )
    print("Initial error: ", error_initial)
    error_final = objective_funcion(res.x, permebility_plugs, proportions_2opt, segment_list, porosity_2opt, ids_)
    print("Optimized error: ", error_final)

    progressUpdate(value=0.9)

    # Permeability values optimized at the plugs location:
    # permeability_optmized = compute_permeability(proportions_2opt, segment_list, porosity_2opt, res.x, ids_)

    # COMPUTE THE FINAL PERMEABILITY IN THE IMAGE SCALE BUT IN THE VALID DEPTH RANGE (index2work_image)
    proportions_2work = proportions[indexline_2work_image, :]
    permeability_2work = compute_permeability(proportions_2work, segment_list, porosity_image2work, res.x, ids_)

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
    writeToTable(output_df, outputNodeID, na_rep="nan")

    progressUpdate(value=1)

    print("Done")
