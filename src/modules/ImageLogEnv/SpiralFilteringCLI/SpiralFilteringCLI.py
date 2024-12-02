#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml
import numpy as np

from ltrace.algorithms.spiral_filter import filter_spiral
from ltrace.slicer.cli_utils import progressUpdate, readFrom, writeDataInto
from ltrace.image.optimized_transforms import ANP_880_2022_DEFAULT_NULL_VALUE as DEFAULT_NULL_VALUE

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
    TDepth = amplitude.GetSpacing()[-1] / 1000.0
    amplitudeNodeNullValue = args.nullable

    amplitudeArray = slicer.util.arrayFromVolume(amplitude)
    if issubclass(amplitudeArray.dtype.type, np.integer):
        amplitudeArray = amplitudeArray.astype(np.double)
    originalAmpShape = amplitudeArray.shape
    amplitudeArray = amplitudeArray.squeeze()

    invalidIndexNullImage = amplitudeArray == amplitudeNodeNullValue  # amp outside range

    amplitudeArray[invalidIndexNullImage] = amplitudeArray.mean()
    amplitudeArray[(amplitudeArray < amplitudeArray.mean() - 3 * amplitudeArray.std())] = (
        amplitudeArray.mean() - 3 * amplitudeArray.std()
    )
    amplitudeArray[(amplitudeArray > amplitudeArray.mean() + 3 * amplitudeArray.std())] = (
        amplitudeArray.mean() + 3 * amplitudeArray.std()
    )

    progressUpdate(value=0.3)

    outputTau = args.wlength_min
    output, noise = filter_spiral(
        amplitudeArray, TDepth, args.wlength_min, args.wlength_max, args.multip_factor, args.smoothstep_factor
    )

    filteredDiff = (noise**2 / amplitudeArray**2).mean()
    output[invalidIndexNullImage] = args.nullable
    output = np.nan_to_num(output, nan=args.nullable, copy=False).reshape(originalAmpShape)

    # Get output node ID
    outputNodeID_std = args.outputVolume_std
    if outputNodeID_std is None:
        raise ValueError("Missing output node")

    writeDataInto(outputNodeID_std, output, mrml.vtkMRMLScalarVolumeNode, reference=amplitude)

    with open(args.returnparameterfile, "w") as f:
        f.write(f"filtered_diff={str(filteredDiff)}\n")

    progressUpdate(value=1.0)

    print("Done")
