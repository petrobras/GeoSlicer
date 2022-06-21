#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function

import json
import sys
import numpy as np
import pandas as pd

import vtk, slicer, mrml, slicer.util

from ltrace.slicer.cli_utils import readFrom, writeDataInto, writeToTable, progressUpdate
from ltrace.algorithms import measurements as measure
from ltrace.transforms import clip_to


def main(args):
    if args.inputVolumeID is None:
        print("Missing input! Nothing to do...")
        progressUpdate(1)

    if args.labelmapVolumeID is None:
        print("Missing labelmap! Nothing to do...")
        progressUpdate(1)

    if args.outputVolumeID is None:
        print("Missing output! Nothing to do...")
        progressUpdate(1)

    params = json.loads(args.params) if args.params else {}
    bgPorosity = params.get("intrinsic_porosity", 1)
    labels_ = params.get("labels", None)
    microporosityLowerLimit = params.get("microporosityLowerLimit", None)
    microporosityUpperLimit = params.get("microporosityUpperLimit", None)

    inputVolumeNode = readFrom(args.inputVolumeID, mrml.vtkMRMLScalarVolumeNode)
    labelmapVolumeNode = readFrom(args.labelmapVolumeID, mrml.vtkMRMLLabelMapVolumeNode)

    inputVoxelArray = slicer.util.arrayFromVolume(inputVolumeNode)
    labelmapVoxelArray = slicer.util.arrayFromVolume(labelmapVolumeNode)

    validLabels = sum([len(labels_[key]) for key in labels_ if key != "Ignore"])

    outputVoxelArray, totalPorosity, porosityLayer = measure.microporosity(
        inputVoxelArray,
        labelmapVoxelArray,
        labels_,
        bgPorosity,
        stepCallback=lambda i: progressUpdate(i / validLabels),
        microporosityLowerLimit=microporosityLowerLimit,
        microporosityUpperLimit=microporosityUpperLimit,
    )

    voxel_size = np.prod(np.array([i for i in inputVolumeNode.GetSpacing()]))

    N = outputVoxelArray.size
    rows = [
        (name.replace("Voxels", "Segment (%)"), 100 * (value / N))
        for name, value in porosityLayer.items()
        if "Voxels" in name
    ]

    rows.extend(
        [
            ("Total Microporosity (%)", 100 * (porosityLayer["Microporosity Weighted"] / N)),
            ("Total Pore Voxels", totalPorosity),
            ("Total Pore Volume (mm^3)", totalPorosity * voxel_size),
            ("Total Porosity (Micro+Macro) (%)", totalPorosity * 100 / outputVoxelArray.size),
        ]
    )

    df = pd.DataFrame(rows, columns=("Property", "Value"))
    df = df.round(decimals=4)

    writeDataInto(args.outputVolumeID, outputVoxelArray, mrml.vtkMRMLScalarVolumeNode, reference=inputVolumeNode)

    writeToTable(df, args.outputReportID)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--input", type=str, dest="inputVolumeID", default=None)
    parser.add_argument("--labelmap", type=str, dest="labelmapVolumeID", default=None)
    parser.add_argument("--labels", type=str, dest="labels", default=None)
    parser.add_argument("--params", type=str, default=None)
    parser.add_argument("--output", type=str, dest="outputVolumeID", default=None)
    parser.add_argument("--report", type=str, dest="outputReportID", default=None)

    args = parser.parse_args()

    main(args)

    print("Done")
