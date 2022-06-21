#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import vtk

import mrml
from ltrace.slicer.cli_utils import writeDataInto, progressUpdate, readFrom

from InstanceSegmenterCLILib.model.imagelog import ImageLogSidewallSampleModel, ImageLogSidewallSampleModelParameters


def segmentImageLogSidewallSample(args):
    redChannelImageNode = readFrom(args.redChannelImage, mrml.vtkMRMLScalarVolumeNode)
    greenChannelImageNode = readFrom(args.greenChannelImage, mrml.vtkMRMLScalarVolumeNode)

    parameters = ImageLogSidewallSampleModelParameters(
        model=args.model,
        ampImageNode=redChannelImageNode,
        ttImageNode=greenChannelImageNode,
        minimumScore=args.minimumScore,
        maximumDetections=args.maximumDetections,
        gpuEnabled=args.gpuEnabled,
    )

    model = ImageLogSidewallSampleModel()
    labelMapArray, parametersDataFrame = model.segment(parameters)

    writeDataInto(args.outputLabelMapNode, labelMapArray, mrml.vtkMRMLLabelMapVolumeNode, greenChannelImageNode)
    parametersDataFrame.to_pickle(args.outputParametersFile)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace instance segmenter for Slicer.")
    parser.add_argument("--model", type=str, required=True)
    parser.add_argument("--redChannelImagePath", type=str, dest="redChannelImage", default=None)
    parser.add_argument("--greenChannelImagePath", type=str, dest="greenChannelImage", default=None)
    parser.add_argument("--blueChannelImagePath", type=str, dest="blueChannelImage", default=None)
    parser.add_argument("--minimumScore", type=float, default=0)
    parser.add_argument("--maximumDetections", type=int, default=999)
    parser.add_argument("--outputLabelMapNodePath", type=str, dest="outputLabelMapNode", required=True)
    parser.add_argument("--outputParametersFilePath", type=str, dest="outputParametersFile", required=True)
    parser.add_argument("--gpuEnabled", action="store_true")

    args = parser.parse_args()

    progressUpdate(value=0.1)

    segmentImageLogSidewallSample(args)

    progressUpdate(value=1)

    print("Done")
