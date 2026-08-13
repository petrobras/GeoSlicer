#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml
import json
import numpy as np
import time
import porespy
import microtom

from ltrace.slicer.cli_utils import writeDataInto, readFrom, progressUpdate
from ltrace.constants import PSDLib


def run(args):
    psdLib = PSDLib.getFromName(args.psdLib)

    if not psdLib:
        raise ValueError("PSD lib not found")

    start_time = time.time()
    inputVolume = readFrom(args.inputVolume, mrml.vtkMRMLScalarVolumeNode)
    inputVolumeArray = slicer.util.arrayFromVolume(inputVolume).astype(np.uint8)
    width = inputVolumeArray.shape[-1]

    progressUpdate(value=0.25)

    inputVolumeArray = np.dstack([inputVolumeArray, inputVolumeArray, inputVolumeArray])
    params = json.loads(args.params) if args.params is not None else {}

    progressUpdate(value=0.5)

    lib_start = time.time()

    if psdLib == PSDLib.MICROTOM:
        result = microtom.psd(inputVolumeArray, **params)
        result = result["psd"]
        result = np.array(result, dtype=np.float64)
    elif psdLib == PSDLib.PORESPY:
        result = porespy.filters.local_thickness(inputVolumeArray, **params)
        result = result.reshape(inputVolumeArray.shape)

    lib_end = time.time()

    result = result[:, :, width : 2 * width]
    result = result.astype(np.float32)

    progressUpdate(value=0.75)

    writeDataInto(args.outputVolume, result, mrml.vtkMRMLScalarVolumeNode, reference=inputVolume)

    progressUpdate(value=0.90)

    end_time = time.time()

    processInfo = {
        "psdLib": psdLib.value,
        "workspace": args.workspace,
        "lib_time": (lib_end - lib_start),
        "total_time": (end_time - start_time),
    }

    with open(args.returnparameterfile, "w") as returnFile:
        returnFile.write("imageLogPSDGeneration=" + json.dumps(processInfo) + "\n")

    progressUpdate(value=1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--psdLib", type=str, dest="psdLib", required=True, help="PSD lib")
    parser.add_argument("--inputVolume", type=str, dest="inputVolume", required=True, help="Input LabelMap volume")
    parser.add_argument("--outputVolume", type=str, dest="outputVolume", required=True, help="Output scalar volume")
    parser.add_argument("--workspace", type=str, dest="workspace", required=True, help="Workspace to run")
    parser.add_argument("--params", type=str, dest="params", default=None, help="PSD lib parameters")
    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )

    args = parser.parse_args()

    run(args)

    print("Done")
