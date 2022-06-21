#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml
import json
import logging
import numpy as np
import os
import sys
import time

from pathlib import Path
from ltrace.slicer.cli_utils import writeDataInto, readFrom, progressUpdate


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument(
        "-i", "--inputVolume", type=str, dest="inputVolume", required=True, help="Input LabelMap volume"
    )
    parser.add_argument(
        "-o", "--outputVolume", type=str, dest="outputVolume", default=None, help="Output LabelMap volume"
    )
    parser.add_argument("-m", "--multiplier", type=float, default=1, help="Multiplier value")

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )

    args = parser.parse_args()

    if args.inputVolume is None:
        raise ValueError("Missing input volume node")

    # Read as slicer node (copy)
    masterVolumeNode = readFrom(args.inputVolume, mrml.vtkMRMLLabelMapVolumeNode)
    # Access numpy view (reference)
    masterVolumeVoxelArray = slicer.util.arrayFromVolume(masterVolumeNode)

    # Progress Bar example
    for i in range(0, 100, 10):
        progressUpdate(value=i / 100.0)
        time.sleep(0.1)

    # Do something with your input
    output = masterVolumeVoxelArray * args.multiplier

    # Get output node ID
    outputNodeId = args.outputVolume
    if outputNodeId is None:
        raise ValueError("Missing output volume node")

    # Write output data
    writeDataInto(outputNodeId, output, mrml.vtkMRMLLabelMapVolumeNode, reference=masterVolumeNode)

    print("Done")
