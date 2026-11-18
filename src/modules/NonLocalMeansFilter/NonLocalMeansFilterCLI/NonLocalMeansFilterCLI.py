#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk  # noqa: F401
import slicer
import slicer.util
import mrml

import argparse

from commons.algorithms.non_local_means import (
    denoise,
    MODE_3D,
    MODE_2D,
    DEFAULT_STRENGTH,
    DEFAULT_PATCH_SIZE,
    DEFAULT_PATCH_DISTANCE,
)
from commons.slicer.cli_utils import progressUpdate, readFrom, writeDataInto


def main(args):
    progressUpdate(value=0)
    inputVolume = readFrom(args.inputVolume, mrml.vtkMRMLScalarVolumeNode)
    components = inputVolume.GetImageData().GetNumberOfScalarComponents()
    if components != 1:
        # The module converts RGB images to greyscale before calling this CLI
        raise ValueError(f"Expected a single-channel image, got {components} channels.")

    output, sigma, h = denoise(
        slicer.util.arrayFromVolume(inputVolume),
        strength=args.strength,
        sigma=args.sigma,
        mode=args.mode,
        patch_size=args.patchSize,
        patch_distance=args.patchDistance,
        fast_mode=args.fastMode,
        null_value=float(args.nullValue) if args.nullValue else None,
        progress_callback=lambda fraction: progressUpdate(value=fraction),
    )
    print(f"Filtered in {args.mode.upper()} with h = {h}, sigma = {sigma}")

    writeDataInto(args.outputVolume, output, mrml.vtkMRMLScalarVolumeNode, reference=inputVolume)

    if args.returnparameterfile:
        with open(args.returnparameterfile, "w") as returnFile:
            returnFile.write(f"usedSigma={sigma}\n")
            returnFile.write(f"usedH={h}\n")

    progressUpdate(value=1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Non-local means filter CLI for Slicer.")
    parser.add_argument("--inputVolume", type=str, required=True, help="Input volume file (.nrrd)")
    parser.add_argument("--outputVolume", type=str, required=True, help="Output volume file (.nrrd)")
    parser.add_argument("--mode", type=str, choices=[MODE_3D, MODE_2D], default=MODE_3D, help="3D or slice by slice 2D")
    parser.add_argument(
        "--strength", type=float, default=DEFAULT_STRENGTH[MODE_3D], help="Filter strength as a multiple of sigma"
    )
    parser.add_argument("--sigma", type=float, default=0, help="Noise standard deviation, 0 to estimate it")
    parser.add_argument("--patchSize", type=int, default=DEFAULT_PATCH_SIZE, help="Patch side in voxels")
    parser.add_argument("--patchDistance", type=int, default=DEFAULT_PATCH_DISTANCE, help="Search distance in voxels")
    parser.add_argument("--fastMode", action="store_true", help="Use the faster, box-weighted patch distance")
    parser.add_argument("--nullValue", type=str, default="", help="Value of voxels kept unchanged")
    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument("--returnparameterfile", type=str, default=None, help="File to store execution outputs")

    main(parser.parse_args())
