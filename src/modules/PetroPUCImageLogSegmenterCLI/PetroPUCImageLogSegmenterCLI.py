#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import vtk
import mrml
import slicer

import numpy as np

from ltrace.slicer.cli_utils import writeDataInto, progressUpdate, readFrom

from source import predict


def run(inputImage, segmentClass, depthInterval):
    well, labelArray = predict.run(inputImage, segmentClass, *depthInterval)
    labelArray = np.expand_dims(labelArray, axis=1)
    inputImageArray = slicer.util.arrayFromVolume(inputImage)
    finalArray = np.zeros(inputImageArray.shape)
    finalArray[depthInterval[0] : depthInterval[0] + len(labelArray)] = labelArray
    return finalArray


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--inputImagePath", type=str, dest="inputImage", required=True)
    parser.add_argument("--outputLabelPath", type=str, dest="outputLabel", required=True)
    parser.add_argument("--segmentClass", type=str, required=True)
    parser.add_argument("--depthInterval", type=str, required=True)
    args = parser.parse_args()

    inputImage = readFrom(args.inputImage, mrml.vtkMRMLScalarVolumeNode)

    segmentClass = args.segmentClass
    depthInterval = [int(i) for i in args.depthInterval.split(",")]

    labelArray = run(inputImage, segmentClass, depthInterval)

    writeDataInto(args.outputLabel, labelArray, mrml.vtkMRMLLabelMapVolumeNode, inputImage)

    print("Done")
