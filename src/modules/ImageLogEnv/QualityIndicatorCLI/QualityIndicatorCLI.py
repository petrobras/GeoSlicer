#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import vtk, slicer, slicer.util, mrml

import logging
import os, sys
import traceback

from xarray import where

from ltrace.slicer.helpers import getVolumeNullValue

import json

from pathlib import Path
import numpy as np
import csv

from ltrace.image.optimized_transforms import DEFAULT_NULL_VALUE as DEFAULT_NULL_VALUES

from ltrace.slicer.cli_utils import readFrom, writeDataInto, progressUpdate
from ltrace.algorithms.spiral_filter import filter_spiral

DEFAULT_NULL_VALUE = list(DEFAULT_NULL_VALUES)[0]


def calculateSpiralIndicator(data, windowSizeIndex):
    data = np.abs(data).mean(1)
    media = data.mean()
    data = data - media

    indicator = np.convolve(data, np.ones(windowSizeIndex) / windowSizeIndex, mode="same")
    indicator = indicator + media
    indicator = indicator / 4.4105
    # obs. 4.4105 is a normalization factor according to the tests in reference wells
    return indicator


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--master1", type=str, dest="inputVolume1", required=True, help="Transit time image log")
    parser.add_argument(
        "--window_size", type=float, default=1, help="Size of the moving window in meters used to compute de indicator"
    )
    parser.add_argument(
        "--wlength_min", type=float, default=1, help="Minimum vertical wavelength of the spiraling effect in meters"
    )
    parser.add_argument(
        "--wlength_max", type=float, default=1, help="Maximum vertical wavelength of the spiraling effect in meters"
    )
    parser.add_argument("--outputvolume_std", type=str, dest="outputVolume_std", default=None, help="Output image name")
    parser.add_argument("--nullable", type=float, default=DEFAULT_NULL_VALUE, help="Null value representation")
    parser.add_argument("--multip_factor", type=float, default=-1000000.0, help="Multiplicative factor of the filter")
    parser.add_argument(
        "--smoothstep_factor", type=float, default=-1000000.0, help="Step length of the filter spectrum band"
    )

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument("--returnparameterfile", type=str, help="File destination to store an execution outputs")

    args = parser.parse_args()

    # Get output node ID
    outputNodeIdStd = args.outputVolume_std
    if outputNodeIdStd is None:
        raise ValueError("Missing output node")

    progressUpdate(value=0.1)

    # Read as slicer node (copy)
    amplitude = readFrom(args.inputVolume1, mrml.vtkMRMLScalarVolumeNode)
    tDepth = amplitude.GetSpacing()[-1] / 1000.0
    amplitudeNodeNullValue = getVolumeNullValue(amplitude) or args.nullable

    amplitudeArray = slicer.util.arrayFromVolume(amplitude)
    originalAmpShape = amplitudeArray.shape
    amplitudeArray = amplitudeArray.squeeze()

    invalidIndexNullImage = amplitudeArray == amplitudeNodeNullValue  # amp outside range

    # Treat outliers
    amplitudeArray[invalidIndexNullImage] = amplitudeArray.mean()
    amplitudeArray[(amplitudeArray < amplitudeArray.mean() - 3 * amplitudeArray.std())] = (
        amplitudeArray.mean() - 3 * amplitudeArray.std()
    )
    amplitudeArray[(amplitudeArray > amplitudeArray.mean() + 3 * amplitudeArray.std())] = (
        amplitudeArray.mean() + 3 * amplitudeArray.std()
    )

    progressUpdate(value=0.3)

    # Conditional to identify CBIL TT image and apply a 0.1 factor at the image
    if amplitudeArray.max() > 1000:
        print("Data detected as a CBIL transit time image ")
        amplitudeArray = 0.1 * amplitudeArray

    # apply spiral filter
    dataFiltered, dataNoise = filter_spiral(
        amplitudeArray, tDepth, args.wlength_min, args.wlength_max, args.multip_factor, args.smoothstep_factor
    )

    progressUpdate(value=0.9)

    # Compute indicator1
    indicator = calculateSpiralIndicator(dataNoise, int(args.window_size / tDepth))
    indicator2d = np.tile(indicator, (dataFiltered.shape[1], 1)).T

    indicator2d[invalidIndexNullImage] = args.nullable
    output = indicator2d.reshape(originalAmpShape)

    writeDataInto(outputNodeIdStd, output, mrml.vtkMRMLScalarVolumeNode, reference=amplitude)

    progressUpdate(value=1.0)

    print("Done")
