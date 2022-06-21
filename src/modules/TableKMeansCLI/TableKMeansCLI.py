#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import vtk, slicer, slicer.util, mrml

import logging
import os, sys
import traceback

from ltrace.algorithms.common import ArrayProcessor, parseWindowFormat

import json

from pathlib import Path
import numpy as np
import sklearn, sklearn.cluster


def progressUpdate(value):
    """
    Progress Bar updates over stdout (Slicer handles the parsing)
    """
    print(f"<filter-progress>{value}</filter-progress>")
    sys.stdout.flush()


def readFrom(volumeFile, builder, storageNode=slicer.vtkMRMLNRRDStorageNode):
    sn = storageNode()
    sn.SetFileName(volumeFile)
    nodeIn = builder()
    sn.ReadData(nodeIn)  # read data from volumeFile into nodeIn
    return nodeIn


def writeDataInto(volumeFile, dataVoxelArray, builder, reference=None):
    sn_out = slicer.vtkMRMLNRRDStorageNode()
    sn_out.SetFileName(volumeFile)
    nodeOut = builder()

    if reference:
        # copy image information
        nodeOut.Copy(reference)
        # reset the attribute dictionary, otherwise it will be transferred over
        attrs = vtk.vtkStringArray()
        nodeOut.GetAttributeNames(attrs)
        for i in range(0, attrs.GetNumberOfValues()):
            nodeOut.SetAttribute(attrs.GetValue(i), None)

    # reset the data array to force resizing, otherwise we will just keep the old data too
    nodeOut.SetAndObserveImageData(None)
    slicer.util.updateVolumeFromArray(nodeOut, dataVoxelArray)
    nodeOut.Modified()

    sn_out.WriteData(nodeOut)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--table", type=str, dest="table", required=True, help="Input table from segment inspector")
    parser.add_argument(
        "--labelmap", type=str, dest="labelmap", required=True, help="Labelmap used at segment inspector"
    )
    parser.add_argument("--k", type=int, dest="k", required=True, help="Number of clusters to partition the data")
    parser.add_argument(
        "--outputvolume", type=str, dest="outputVolume", default=None, help="Output labelmap for repartition"
    )

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )

    args = parser.parse_args()

    # Read as slicer node (copy)
    tablenode = readFrom(args.table, mrml.vtkMRMLTableNode, slicer.vtkMRMLTableStorageNode)
    print(tablenode)
    dataframe = slicer.util.dataframeFromTable(tablenode)
    labelmap = readFrom(args.labelmap, mrml.vtkMRMLLabelMapVolumeNode)

    tableArray = dataframe.values

    print(tableArray)
    # Removing element label, class id and class label
    tableArrayForKmeans = tableArray[:, 1:-2]

    km = sklearn.cluster.KMeans(n_clusters=args.k)
    km.fit(tableArrayForKmeans)
    labels = km.labels_

    # Access numpy view (reference)
    labelmapArray = slicer.util.arrayFromVolume(labelmap)

    lookup = dict(zip(tableArray[:, 0], labels))

    totalPixels = len(labelmapArray.flat)

    k = np.array(tableArray[:, 0], dtype=int)

    mapping_ar = np.zeros(k.max() + 1, dtype=k.dtype)
    mapping_ar[k] = labels + 1  # +1 because 0 is the labelmap background
    outputArray = mapping_ar[labelmapArray]

    # Get output node ID
    outputNodeID = args.outputVolume
    if outputNodeID is None:
        raise ValueError("Missing output node")

    # Write output data
    writeDataInto(outputNodeID, outputArray, mrml.vtkMRMLLabelMapVolumeNode, reference=labelmap)

    print("Done")
