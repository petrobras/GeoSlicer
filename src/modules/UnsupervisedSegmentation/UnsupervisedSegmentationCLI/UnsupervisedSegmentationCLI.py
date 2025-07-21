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
import cv2

from pathlib import Path
from ltrace.slicer.cli_utils import writeDataInto, readFrom, progressUpdate

from ltrace.algorithms.unsupervised_segmentation import segment_image

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("-i", "--inputVolume", type=str, dest="inputVolume", required=True)
    parser.add_argument("-e", "--extraInputVolume", type=str, dest="extraInputVolume", required=False)
    parser.add_argument("-o", "--outputVolume", type=str, dest="outputVolume", default=None)
    parser.add_argument("-r", "--resolution", type=int, default=1000)
    parser.add_argument("-c", "--colorTablePath", type=str)
    parser.add_argument("-m", "--minLabelNum", type=int, default=3, help="Minimum number of segments to produce")

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )

    args = parser.parse_args()
    if args.inputVolume is None:
        raise ValueError("Missing input volume node")

    imageNode = readFrom(args.inputVolume, mrml.vtkMRMLVectorVolumeNode)
    imageArray = slicer.util.arrayFromVolume(imageNode)

    extraImageArray = None
    if args.extraInputVolume:
        extraImageNode = readFrom(args.extraInputVolume, mrml.vtkMRMLVectorVolumeNode)
        extraImageArray = slicer.util.arrayFromVolume(extraImageNode)

        if imageArray.shape != extraImageArray.shape:
            raise ValueError("Input and extra input volumes must have the same shape")

        assert extraImageArray.shape[0] == 1, "Only 2D images are supported"
        extraImageArray = extraImageArray[0]

    assert imageArray.shape[0] == 1, "Only 2D images are supported"
    imageArray = imageArray[0]

    task = segment_image(
        imageArray,
        extraImageArray,
        processing_resolution=args.resolution,
        min_label_num=args.minLabelNum,
    )
    try:
        progress = 10
        while True:
            status = next(task)
            progress += 1
            progressUpdate(value=progress / 100)
    except StopIteration as e:
        result = e.value

    # Progress Bar example
    for i in range(0, 100, 10):
        progressUpdate(value=i / 100.0)
        time.sleep(0.1)

    # Do something with your input
    labelArray, colorMap = result
    labelArray = labelArray[np.newaxis] + 1

    colorMap = np.insert(colorMap, 0, [0, 0, 0], axis=0)  # Add background color
    np.save(args.colorTablePath, colorMap)

    # Get output node ID
    outputNodeId = args.outputVolume
    if outputNodeId is None:
        raise ValueError("Missing output volume node")

    # Write output data
    writeDataInto(outputNodeId, labelArray, mrml.vtkMRMLLabelMapVolumeNode, reference=imageNode)

    print("Done", colorMap)
