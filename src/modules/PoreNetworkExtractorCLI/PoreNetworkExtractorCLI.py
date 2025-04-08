#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import vtk

import json
from pathlib import Path
import itertools

import slicer
import mrml
import numpy as np
import pandas as pd
import pickle
import porespy
import openpnm
from ltrace.slicer.cli_utils import progressUpdate
from ltrace.pore_networks.functions_extract import general_pn_extract, multiscale_extraction


def readFrom(volumeFile, builder):
    sn = slicer.vtkMRMLNRRDStorageNode()
    sn.SetFileName(volumeFile)
    nodeIn = builder()
    sn.ReadData(nodeIn)
    return nodeIn


def writeDataFrame(df, path):
    df.to_pickle(str(path))


def writePolydata(polydata, filename):
    writer = vtk.vtkPolyDataWriter()
    writer.SetInputData(polydata)
    writer.SetFileName(filename)
    writer.Write()


def extractPNM(args):
    params = json.loads(args.xargs)

    progressUpdate(value=0.1)

    if params["is_multiscale"]:
        volumeNode = readFrom(args.volume, mrml.vtkMRMLScalarVolumeNode)
        labelNode = readFrom(args.label, mrml.vtkMRMLLabelMapVolumeNode) if args.label else None

        extract_result = multiscale_extraction(
            volumeNode,
            labelNode,
            params["method"],
            params["watershed_blur"],
        )
    else:
        volumeNode = readFrom(args.volume, mrml.vtkMRMLLabelMapVolumeNode)

        extract_result = general_pn_extract(
            multiphaseNode=None,
            watershedNode=volumeNode,
            method=params["method"],
        )

    if extract_result:
        pores_df, throats_df, network_df = extract_result
    else:
        print("No connected network was identified. Possible cause: unsegmented pore space.")
        return

    pores_df.to_pickle(f"{args.cwd}/pores.pd")
    throats_df.to_pickle(f"{args.cwd}/throats.pd")
    network_df.to_pickle(f"{args.cwd}/network.pd")

    progressUpdate(value=1.0)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace pore network extraction CLI.")
    parser.add_argument("--volume", type=str, default=None, required=False)
    parser.add_argument("--label", type=str, default=None, required=False)
    parser.add_argument("--xargs", type=str, default="", required=False)
    parser.add_argument("--cwd", type=str, required=False)
    args = parser.parse_args()

    extractPNM(args)

    print("Done")
