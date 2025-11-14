#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function
import argparse
import mrml
import numpy as np
import slicer

from pyedt import edt

from ltrace.slicer.cli_utils import progressUpdate, readFrom, writeDataInto


def main(args):
    try:
        progressUpdate(value=0.1)

        # Read input volume
        print("Loading input volume...")
        inputVolume = readFrom(args.inputVolume, mrml.vtkMRMLScalarVolumeNode)
        if not inputVolume:
            raise RuntimeError(f"Failed to load input volume: {args.inputVolume}")

        input_array = slicer.util.arrayFromVolume(inputVolume).astype(np.float32)

        progressUpdate(value=0.3)

        # Compute EDT
        output_array = edt(input_array).astype(np.float32)

        progressUpdate(value=0.8)

        # Save output volume
        slicer.util.updateVolumeFromArray(inputVolume, output_array)

        # Save to the specified output file path
        writeDataInto(args.outputVolume, output_array, mrml.vtkMRMLScalarVolumeNode, reference=inputVolume)

        progressUpdate(value=1.0)

    except Exception as e:
        print(f"Error in EuclideanDistanceTransformCLI: {e}")
        # Optionally, re-raise or handle the error appropriately for the CLI environment
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Euclidean Distance Transform CLI for Slicer.")
    parser.add_argument("--inputVolume", type=str, required=True, help="Input volume file (.nrrd)")
    parser.add_argument("--outputVolume", type=str, required=True, help="Output distance map volume file (.nrrd)")

    args = parser.parse_args()

    main(args)
