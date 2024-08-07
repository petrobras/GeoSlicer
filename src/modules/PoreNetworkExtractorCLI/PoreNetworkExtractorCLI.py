#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import vtk

import json
from pathlib import Path
import itertools

import slicer
import mrml
import numpy as np
import pandas as pd
import pickle
import porespy
import openpnm
from ltrace.slicer.cli_utils import progressUpdate
from PoreNetworkExtractorCLILib.utils import general_pn_extract


def readFrom(volumeFile, builder):
    sn = slicer.vtkMRMLNRRDStorageNode()
    sn.SetFileName(volumeFile)
    nodeIn = builder()
    sn.ReadData(nodeIn)
    return nodeIn


def writeDataFrame(df, path):
    df.to_pickle(str(path))


def writePolydata(polydata, filename):
    writer = vtk.vtkPolyDataWriter()
    writer.SetInputData(polydata)
    writer.SetFileName(filename)
    writer.Write()


def multiscale_extraction(
    inputPorosityNode: slicer.vtkMRMLScalarVolumeNode,
    inputWatershed: slicer.vtkMRMLLabelMapVolumeNode,
    prefix: str,
    method: str,
):
    porosity_array = slicer.util.arrayFromVolume(inputPorosityNode)
    if np.issubdtype(porosity_array.dtype, np.floating):
        if porosity_array.max() == 1:
            porosity_array = (100 * porosity_array).astype(np.uint8)
        else:
            porosity_array = porosity_array.astype(np.uint8)

    resolved_array = (porosity_array == 100).astype(np.uint8)
    unresolved_array = np.logical_and(porosity_array > 0, porosity_array < 100).astype(np.uint8)
    multiphase_array = resolved_array + (2 * unresolved_array)

    slicer.util.updateVolumeFromArray(inputPorosityNode, multiphase_array)

    extract_result = general_pn_extract(
        inputPorosityNode,
        inputWatershed,
        prefix=prefix + "_Multiscale",
        method=method,
        porosity_map=porosity_array,
    )

    return extract_result


def extractPNM(args):
    params = json.loads(args.xargs)

    progressUpdate(value=0.1)

    if params["is_multiscale"]:
        volumeNode = readFrom(args.volume, mrml.vtkMRMLScalarVolumeNode)
        labelNode = readFrom(args.label, mrml.vtkMRMLLabelMapVolumeNode) if args.label else None

        extract_result = multiscale_extraction(
            volumeNode,
            labelNode,
            params["prefix"],
            params["method"],
        )
    else:
        volumeNode = readFrom(args.volume, mrml.vtkMRMLLabelMapVolumeNode)

        extract_result = general_pn_extract(
            None,
            volumeNode,
            params["prefix"],
            params["method"],
        )

    if extract_result:
        pores_df, throats_df = extract_result
    else:
        print("No connected network was identified. Possible cause: unsegmented pore space.")
        return

    pores_df.to_pickle(f"{args.cwd}/pores.pd")
    throats_df.to_pickle(f"{args.cwd}/throats.pd")

    progressUpdate(value=1.0)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace pore network extraction CLI.")
    parser.add_argument("--volume", type=str, default=None, required=False)
    parser.add_argument("--label", type=str, default=None, required=False)
    parser.add_argument("--xargs", type=str, default="", required=False)
    parser.add_argument("--cwd", type=str, required=False)
    args = parser.parse_args()

    extractPNM(args)

    print("Done")
