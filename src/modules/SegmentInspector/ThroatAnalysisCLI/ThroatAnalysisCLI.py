#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function

import vtk
import mrml

from ltrace.slicer.cli_utils import readFrom, writeDataInto
from ltrace.slicer.throat_analysis.throat_analysis import ThroatAnalysis

import numpy as np


def write_to_table(df, table_path):
    df.to_pickle(table_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--labels", type=str, dest="labelVolume", default=None)
    parser.add_argument("--outputReport", type=str, dest="outputReport", default=None)
    parser.add_argument("--outputLabelVolume", type=str, dest="outputLabelVolume", default=None)
    parser.add_argument("--params", type=str)

    args = parser.parse_args()

    label_volume_node = readFrom(args.labelVolume, mrml.vtkMRMLLabelMapVolumeNode)
    ijk_to_ras_matrix = vtk.vtkMatrix4x4()
    label_volume_node.GetIJKToRASMatrix(ijk_to_ras_matrix)

    throat_analysis = ThroatAnalysis(labelVolume=label_volume_node, params=args.params)

    write_to_table(throat_analysis.throat_report_df, args.outputReport)
    writeDataInto(
        args.outputLabelVolume,
        throat_analysis.boundary_labeled_array,
        mrml.vtkMRMLLabelMapVolumeNode,
        reference=label_volume_node,
    )
