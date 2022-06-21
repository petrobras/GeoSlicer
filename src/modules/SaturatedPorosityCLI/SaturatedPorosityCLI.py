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


def main(args):
    if args.dryVolumeID is None:
        print("Missing dry volume! Nothing to do...")
        progressUpdate(1)

    if args.saturatedVolumeID is None:
        print("Missing saturated volume! Nothing to do...")
        progressUpdate(1)

    if args.outputVolumeID is None:
        print("Missing output! Nothing to do...")
        progressUpdate(1)

    progressUpdate(0)

    params = json.loads(args.params) if args.params else {}
    air_value = params.get("airValueDry", None)
    water_value = params.get("calciteValueDry", None)
    dry_norm_values = (air_value, water_value)

    dryVolumeNode = readFrom(args.dryVolumeID, mrml.vtkMRMLScalarVolumeNode)
    saturatedVolumeNode = readFrom(args.saturatedVolumeID, mrml.vtkMRMLScalarVolumeNode)

    dryVoxelArray = slicer.util.arrayFromVolume(dryVolumeNode)
    saturatedVoxelArray = slicer.util.arrayFromVolume(saturatedVolumeNode)

    outputVoxelArray, totalPorosity, porosityLayer = measure.saturatedPorosity(
        dryVoxelArray,
        saturatedVoxelArray,
        norm_values=dry_norm_values,
        step_callback=lambda i: progressUpdate(i / 100),
    )

    voxel_size = np.prod(np.array([i for i in dryVolumeNode.GetSpacing()]))

    N = outputVoxelArray.size
    rows = [
        (name.replace("Voxels", "Segment (%)"), 100 * (value / N))
        for name, value in porosityLayer.items()
        if "Voxels" in name
    ]

    rows.extend(
        [
            ("Total Pore Voxels", totalPorosity),
            ("Total Pore Volume (mm^3)", totalPorosity * voxel_size),
            ("Total Porosity (Micro+Macro) (%)", totalPorosity * 100 / outputVoxelArray.size),
        ]
    )

    df = pd.DataFrame(rows, columns=("Property", "Value"))
    df = df.round(decimals=4)
    progressUpdate(0.15)

    writeDataInto(args.outputVolumeID, outputVoxelArray, mrml.vtkMRMLScalarVolumeNode, reference=dryVolumeNode)

    writeToTable(df, args.outputReportID)
    progressUpdate(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--dry", type=str, dest="dryVolumeID", default=None)
    parser.add_argument("--saturated", type=str, dest="saturatedVolumeID", default=None)
    parser.add_argument("--params", type=str, default=None)
    parser.add_argument("--output", type=str, dest="outputVolumeID", default=None)
    parser.add_argument("--report", type=str, dest="outputReportID", default=None)

    args = parser.parse_args()

    main(args)

    print("Done")
