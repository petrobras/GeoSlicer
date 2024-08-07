#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above
#
# Doubts: 1) Does porosity have the same depth scale than the imagelog? If not, interpolated is required for next version.
# Or the proportion should be computed for a depth range

from __future__ import print_function

import logging
import os, sys
import traceback

from pathlib import Path

import vtk, slicer, slicer.util, mrml
import vtkSegmentationCorePython as vtkSegmentationCore

import csv
import numpy as np
import pandas as pd

from ltrace.ocr import parse_pdf


def is_float(value):
    return value.dtype in [np.dtype("float64"), np.dtype("float32")]


def is_int(value):
    return value.dtype in [np.dtype("int64"), np.dtype("int32")]


def writeDataInto(tableFile, df):
    sn_out = slicer.vtkMRMLNRRDStorageNode()
    sn_out.SetFileName(tableFile)
    nodeOut = mrml.vtkMRMLTableNode()

    # reset the data array to force resizing, otherwise we will just keep the old data too

    table = nodeOut.GetTable()

    tableWasModified = nodeOut.StartModify()
    for ind, column in enumerate(df.columns):
        serie = df[column]
        if is_float(serie):
            arrX = vtk.vtkFloatArray()
        elif is_int(serie):
            arrX = vtk.vtkIntArray()
        else:
            arrX = vtk.vtkStringArray()

        for value in serie:
            arrX.InsertNextValue(value)

        arrX.SetName(column)

        table.AddColumn(arrX)

    nodeOut.Modified()
    nodeOut.EndModify(tableWasModified)
    sn_out.WriteData(nodeOut)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--file", type=str, required=True, help="PDF File")
    parser.add_argument("--pages", type=str, default="1-end", help="Pages to extract table")
    parser.add_argument(
        "--columns",
        type=str,
        default=None,
        help="Columns to match",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default="no",
        help="Filter result by columns",
    )

    parser.add_argument(
        "--table",
        type=str,
        default=None,
        help="Output table",
    )

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile",
        type=str,
        default=None,
        help="File destination to store an execution outputs",
    )

    args = parser.parse_args()

    filepath = Path(args.file)

    if not filepath.exists():
        raise ValueError(
            f"File must exist to continue! Please select a valid path file. Error: {args.file} does not exist."
        )

    column_names = args.columns.split(",")
    column_filter = True if args.filter == "yes" else False

    df = parse_pdf(args.file, pages=args.pages, columns=column_names, remove_extra=column_filter)

    print(args.pages)
    print(column_names)
    print(column_filter)

    df.to_csv(args.table, quoting=csv.QUOTE_NONNUMERIC, index=False)

    print("Done")
