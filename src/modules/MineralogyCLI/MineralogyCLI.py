#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function

import vtk

import json
import sys

import slicer, mrml, slicer.util

from ltrace.utils.NeighbourPixelCount import NeighbourPixelCount


def progressUpdate(value):
    print(f"<filter-progress>{value}</filter-progress>")
    sys.stdout.flush()


def readFrom(volumeFile, builder):
    sn = slicer.vtkMRMLNRRDStorageNode()
    sn.SetFileName(volumeFile)
    nodeIn = builder()
    sn.ReadData(nodeIn)  # read data from volumeFile into nodeIn
    return nodeIn


def writeToTable(df, tableID):
    df.insert(0, "Mineralogy", list(df.columns))
    df.to_csv(tableID, sep="\t", header=True, index=False)


def main(args):
    progressUpdate(0)
    params = json.loads(args.params)
    asPercent = params.get("asPercent", False)
    allowNaN = params.get("allowNaN", False)
    allowSelfCount = params.get("allowSelfCount", False)
    labelBlackList = params.get("labelBlackList", None)
    progressUpdate(0.25)

    labelVolumeNode = readFrom(args.labelVolume, mrml.vtkMRMLLabelMapVolumeNode)

    arrayFromVolume = slicer.util.arrayFromVolume(labelVolumeNode)

    labels = {int(k): v for k, v in json.loads(args.pixelLabels).items()}

    progressUpdate(0.5)
    df = NeighbourPixelCount.NeighbourPixelCount(matrix=arrayFromVolume[0], allowSelfCount=allowSelfCount).toDataFrame(
        asPercent=asPercent, pixelLabels=labels, allowNaN=allowNaN, labelBlackList=labelBlackList
    )

    progressUpdate(0.75)

    if args.outputReport:
        writeToTable(df, args.outputReport)

    progressUpdate(1.0)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--input", type=str, dest="labelVolume", default=None)
    parser.add_argument("--output", type=str, dest="outputReport", default=None)
    parser.add_argument("--params", type=str)
    parser.add_argument("--labels", type=str, dest="pixelLabels")

    main(parser.parse_args())

    print("Done")
