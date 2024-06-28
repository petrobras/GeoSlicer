#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import json

import vtk, slicer, slicer.util, mrml

import microtom
import numpy as np
import pandas as pd
import re

from ltrace.algorithms.common import FlowSetter
from ltrace.slicer.cli_utils import progressUpdate, readFrom, writeDataInto
from ltrace.wrappers import sanitize_file_path, filter_module_name
from pathvalidate.argparse import sanitize_filepath_arg


""" CLI Core functionality
"""


def writeToTable(df, tableID):
    df.to_csv(tableID, sep="\t", header=True, index=False)


def main(args):
    # Read as slicer node (copy)
    referenceVolumeNode = readFrom(args.inputVolume, mrml.vtkMRMLScalarVolumeNode)

    # Access numpy view (reference)
    volumeArray = slicer.util.arrayFromVolume(referenceVolumeNode).astype(np.uint8)

    progressUpdate(value=25 / 100.0)

    params = json.loads(args.params) if args.params is not None else {}

    vfrac = params.pop("vfrac", None)

    # Not used in local execution
    params.pop("n_threads", None)
    params.pop("n_threads_per_node", None)

    simulator = getattr(microtom, args.simulator)
    results = simulator(volumeArray, **params)

    progressUpdate(value=0.85)

    simulator = args.simulator

    if referenceVolumeNode:
        resultArray = results[simulator].astype(np.float32)
        writeDataInto(
            args.outputVolume,
            resultArray,
            mrml.vtkMRMLScalarVolumeNode,
            reference=referenceVolumeNode,
        )

    radii = np.array(results[f"radii_{simulator}"])
    snw = np.array(results[f"snw_{simulator}"])

    progressUpdate(value=0.9)

    sw = 1.0 - snw
    table = {
        "radii (voxel)": radii,
        "1/radii": 1.0 / radii,
        "log(1/radii)": np.log(1.0 / radii),
        "Snw (frac)": snw,
        "Sw (frac)": sw,
    }

    if vfrac != None:
        table["Sws (frac)"] = sw
        sw_corrected = vfrac + sw * (1.0 - vfrac)
        table["Sw (frac)"] = sw_corrected
        table["Snw (frac)"] = 1 - sw_corrected

    if args.psdAxis:
        df = pd.DataFrame(table)
        ddf = df.round(decimals=5)
        writeToTable(ddf, args.psdAxis)

    progressUpdate(value=0.98)

    processInfo = {"simulator": args.simulator, "workspace": args.workspace}

    returnParameterFile = sanitize_file_path(args.returnparameterfile)
    with open(returnParameterFile.as_posix(), "w") as returnFile:
        returnFile.write("porosimetry=" + json.dumps(processInfo) + "\n")

    progressUpdate(value=100 / 100.0)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument(
        "--master", type=sanitize_filepath_arg, dest="inputVolume", required=True, help="Intensity Input (3d) Values"
    )
    parser.add_argument(
        "--output",
        type=sanitize_filepath_arg,
        dest="outputVolume",
        default=None,
        help="PSD Output labelmap (3d) Values",
    )
    parser.add_argument("--psdaxis", type=str, dest="psdAxis", default=None, help="PSD Output Axis")
    parser.add_argument("--outputdir", type=sanitize_filepath_arg, required=True, help="Output location to save")
    parser.add_argument("--params", type=str, default=None, help="Simulator configuration")
    parser.add_argument("--simulator", type=str, required=True, help="Simulator to be executed")
    parser.add_argument("--workspace", type=str, required=True, help="Workspace to run")
    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile",
        type=sanitize_filepath_arg,
        default=None,
        help="File destination to store an execution outputs",
    )

    args = parser.parse_args()
    args.inputVolume = sanitize_file_path(args.inputVolume)
    if args.outputVolume:
        args.outputVolume = sanitize_file_path(args.outputVolume)
    args.outputdir = sanitize_file_path(args.outputdir)
    args.simulator = filter_module_name(args.simulator)

    if not hasattr(microtom, args.simulator):
        raise ValueError(f"Unknown simulator: {args.simulator}")

    main(args)

    print("Done")
