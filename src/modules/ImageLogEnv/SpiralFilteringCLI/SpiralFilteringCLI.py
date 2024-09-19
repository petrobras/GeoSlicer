#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
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

from scipy.optimize import minimize
from scipy.stats import kurtosis
from scipy.stats import skew
from scipy.special import comb
from scipy.signal import convolve2d
from ltrace.image.optimized_transforms import DEFAULT_NULL_VALUE as DEFAULT_NULL_VALUES
from ltrace.algorithms.spiral_filter import filter_spiral
from ltrace.slicer.cli_utils import progressUpdate, readFrom, writeDataInto

DEFAULT_NULL_VALUE = list(DEFAULT_NULL_VALUES)[0]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--master1", type=str, dest="inputVolume1", required=True, help="Amplitude image log")
    parser.add_argument("--wlength_min", type=float, default=1, help="Multiplier value")
    parser.add_argument("--wlength_max", type=float, default=1, help="Multiplier value")
    parser.add_argument(
        "--outputvolume_std", type=str, dest="outputVolume_std", default=None, help="Output labelmap (3d) Values"
    )
    parser.add_argument("--nullable", type=float, default=DEFAULT_NULL_VALUE, help="Null value representation")
    parser.add_argument("--multip_factor", type=float, default=-1000000.0, help="Minimum amplitude value")
    parser.add_argument("--smoothstep_factor", type=float, default=-1000000.0, help="Minimum amplitude value")

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument("--returnparameterfile", type=str, help="File destination to store an execution outputs")

    args = parser.parse_args()

    progressUpdate(value=0.1)

    # Read as slicer node (copy)
    amplitude = readFrom(args.inputVolume1, mrml.vtkMRMLScalarVolumeNode)
    T_depth = amplitude.GetSpacing()[-1] / 1000.0
    amplitudeNodeNullValue = args.nullable

    amplitude_array = slicer.util.arrayFromVolume(amplitude)
    if issubclass(amplitude_array.dtype.type, np.integer):
        amplitude_array = amplitude_array.astype(np.double)
    original_amp_shape = amplitude_array.shape
    amplitude_array = amplitude_array.squeeze()

    invalid_index_Null_image = amplitude_array == amplitudeNodeNullValue  # amp outside range

    amplitude_array[invalid_index_Null_image] = amplitude_array.mean()
    amplitude_array[(amplitude_array < amplitude_array.mean() - 3 * amplitude_array.std())] = (
        amplitude_array.mean() - 3 * amplitude_array.std()
    )
    amplitude_array[(amplitude_array > amplitude_array.mean() + 3 * amplitude_array.std())] = (
        amplitude_array.mean() + 3 * amplitude_array.std()
    )

    progressUpdate(value=0.3)

    outputtau = args.wlength_min
    output, lixo = filter_spiral(
        amplitude_array, T_depth, args.wlength_min, args.wlength_max, args.multip_factor, args.smoothstep_factor
    )

    output[invalid_index_Null_image] = args.nullable
    output = np.nan_to_num(output, nan=args.nullable, copy=False).reshape(original_amp_shape)

    # Get output node ID
    outputNodeID_std = args.outputVolume_std
    if outputNodeID_std is None:
        raise ValueError("Missing output node")

    writeDataInto(outputNodeID_std, output, mrml.vtkMRMLScalarVolumeNode, reference=amplitude)

    progressUpdate(value=1.0)

    print("Done")
