#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import slicer
import vtk

import json
from pathlib import Path
import itertools

import re
import mrml
import numpy as np
import pandas as pd
import pickle
import porespy
import openpnm

from ltrace.algorithms.common import (
    points_are_below_plane,
)
from ltrace.pore_networks.functions_simulation import (
    get_connected_spy_network,
    get_flow_rate,
    get_sub_spy,
    manual_valvatne_blunt,
    set_subresolution_conductance,
    single_phase_permeability,
)

from ltrace.pore_networks.functions_extract import general_pn_extract, multiscale_extraction
from ltrace.pore_networks.subres_models import set_subres_model

from ltrace.slicer.cli_utils import progressUpdate
import shutil

from ltrace.pore_networks.watershed_normalization import normalize_watershed

import logging

logger = logging.getLogger("numba")
logger.setLevel(logging.ERROR)


def dfs2spy(pores_df, throats_df):
    pores_dict = {col: pores_df[col].to_numpy() for col in pores_df.columns}
    throats_dict = {col: throats_df[col].to_numpy() for col in throats_df.columns}

    geo = {}
    geo.update(pores_dict)
    geo.update(throats_dict)

    prop_array = [re.split(r"_\d$", key)[0] for key in geo.keys()]
    prop_dict = {i: prop_array.count(i) for i in prop_array}

    spy = {}
    for prop_name, columns in prop_dict.items():
        if columns == 1:
            spy[prop_name] = geo[prop_name]
        else:
            spy[prop_name] = np.stack([geo[f"{prop_name}_{i}"] for i in range(columns)], axis=1)

    spy["pore.phase1"] = spy["pore.phase"] == 1
    spy["pore.phase2"] = spy["pore.phase"] == 2

    return spy


def crop_volume(volume, size, translation=(0, 0, 0), is_labelmap=False):
    numpy_array = slicer.util.arrayFromVolume(volume)
    shape = numpy_array.shape

    center = [s // 2 for s in shape]

    zmin, zmax = (
        int(max(0, center[0] - size[0] // 2)) + translation[0],
        int(min(shape[0], center[0] + size[0] // 2)) + translation[0],
    )
    ymin, ymax = (
        int(max(0, center[1] - size[1] // 2)) + translation[1],
        int(min(shape[1], center[1] + size[1] // 2)) + translation[1],
    )
    xmin, xmax = (
        int(max(0, center[2] - size[2] // 2)) + translation[2],
        int(min(shape[2], center[2] + size[2] // 2)) + translation[2],
    )

    cropped_array = numpy_array[zmin:zmax, ymin:ymax, xmin:xmax]

    if is_labelmap:
        normalized_array = normalize_watershed(cropped_array)
    else:
        normalized_array = cropped_array

    cropped_image = vtk.vtkImageData()
    cropped_image.SetDimensions(normalized_array.shape[::-1])
    cropped_image.AllocateScalars(volume.GetImageData().GetScalarType(), 1)

    cropped_vtk_array = vtk.util.numpy_support.numpy_to_vtk(normalized_array.T.ravel(), deep=True)
    cropped_image.GetPointData().SetScalars(cropped_vtk_array)

    if is_labelmap:
        cropped_volume = mrml.vtkMRMLLabelMapVolumeNode()
    else:
        cropped_volume = mrml.vtkMRMLScalarVolumeNode()
    cropped_volume.SetAndObserveImageData(cropped_image)
    cropped_volume.SetSpacing(volume.GetSpacing())
    cropped_volume.SetOrigin(volume.GetOrigin())

    return cropped_volume


def readFrom(volumeFile, builder):
    sn = slicer.vtkMRMLNRRDStorageNode()
    sn.SetFileName(volumeFile)
    nodeIn = builder()
    sn.ReadData(nodeIn)  # read data from volumeFile into nodeIn
    return nodeIn


def writeDataFrame(df, path):
    df.to_pickle(str(path))


def KabsREV(args, params):
    cwd = Path(args.cwd)

    if params["is_multiscale"]:
        volume = readFrom(args.volume, mrml.vtkMRMLScalarVolumeNode)
    else:
        volume = readFrom(args.volume, mrml.vtkMRMLLabelMapVolumeNode)

    directions = "xyz"
    in_faces = ("xmin", "ymin", "zmin")
    out_faces = ("xmax", "ymax", "zmax")

    permeabilities = {ax: [] for ax in directions}

    image_data = volume.GetImageData()
    dims = image_data.GetDimensions()

    length_fractions = np.linspace(params["min_fraction"], 1.00, params["number_of_fractions"])
    for idx, length_fraction in enumerate(length_fractions):
        size = [int(length_fraction * d) for d in dims]

        if length_fraction < 0.5:
            translations = [
                (-size[0] // 4, -size[1] // 4, -size[2] // 4),
                (-size[0] // 4, -size[1] // 4, +size[2] // 4),
                (-size[0] // 4, +size[1] // 4, -size[2] // 4),
                (-size[0] // 4, +size[1] // 4, +size[2] // 4),
                (+size[0] // 4, -size[1] // 4, -size[2] // 4),
                (+size[0] // 4, -size[1] // 4, +size[2] // 4),
                (+size[0] // 4, +size[1] // 4, -size[2] // 4),
                (+size[0] // 4, +size[1] // 4, +size[2] // 4),
            ]
        else:
            translations = [(0, 0, 0)]

        for translation in translations:
            cropped_volume = crop_volume(volume, size, translation=translation, is_labelmap=not params["is_multiscale"])

            try:
                if params["is_multiscale"]:
                    watershed_blur = {1: 0.1, 2: 0.1}
                    extract_result = multiscale_extraction(
                        cropped_volume,
                        None,
                        "PoreSpy",
                        watershed_blur,
                        force_cpu=True,
                    )
                else:
                    extract_result = general_pn_extract(
                        None,
                        cropped_volume,
                        "PoreSpy",
                        force_cpu=True,
                    )
            except:
                continue

            pores_df, throats_df, network_df = extract_result

            pore_network = dfs2spy(pores_df, throats_df)

            bounds = [0, 0, 0, 0, 0, 0]
            cropped_volume.GetBounds(bounds)  # In millimeters
            params["sizes"] = {
                "x": (bounds[1] - bounds[0]) / 10.0,
                "y": (bounds[3] - bounds[2]) / 10.0,
                "z": (bounds[5] - bounds[4]) / 10.0,
            }  # In cm
            sizes_product = params["sizes"]["x"] * params["sizes"]["y"] * params["sizes"]["z"]
            subres_func = set_subres_model(pore_network, params)

            volume_porosity = 100 * network_df["network.input_volume_porosity"][0]
            network_porosity = 100 * network_df["network.pore_total_porosity"][0]

            progressUpdate(value=(0.1 + 0.8 * idx / len(length_fractions)))

            for inlet, outlet in ((0, 0), (1, 1), (2, 2)):
                in_face = in_faces[inlet]
                out_face = out_faces[outlet]
                try:
                    perm, pn_pores, pn_throats = single_phase_permeability(
                        pore_network,
                        in_face,
                        out_face,
                        subresolution_function=subres_func,
                        subres_shape_factor=params["subres_shape_factor"],
                        solver=params["solver"],
                        target_error=params["solver_error"],
                        preconditioner=params["preconditioner"],
                        clip_check=params["clip_check"],
                        clip_value=params["clip_value"],
                        coord_limits=None,
                    )
                except:
                    continue

                if perm == 0:
                    continue

                length = params["sizes"][in_faces[2 - inlet][0]]
                flow_rate = get_flow_rate(pn_pores, pn_throats)  # cm^3/s
                area = sizes_product / length
                permeability = flow_rate * (length / area)  # length in mm, return is Darcy
                permeabilities[directions[inlet]].append(
                    (
                        100 * length_fraction,
                        length,
                        area,
                        flow_rate,
                        1000 * permeability,
                        volume_porosity,
                        network_porosity,
                    )
                )

    for i in directions:
        df = pd.DataFrame(
            permeabilities[i],
            columns=[
                "length fraction (%)",
                "length (mm)",
                "area (mm^2)",
                "flow rate (cm^3/s)",
                "permeability (mD)",
                "volume porosity (%)",
                "network porosity (%)",
            ],
        )
        df["normalized permeability"] = df["permeability (mD)"] / df["permeability (mD)"].iloc[-1]
        writeDataFrame(df, cwd / f"kabs_rev_{i}.pd")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace pore network simulation CLI.")
    parser.add_argument("--volume", type=str, default=None)
    parser.add_argument("--cwd", type=str, required=False)
    parser.add_argument(
        "--returnparameterfile",
        type=str,
        default=None,
        help="File destination to store an execution outputs",
    )
    args = parser.parse_args()

    with open(f"{args.cwd}/params_dict.json", "r") as file:
        params = json.load(file)

    progressUpdate(value=0.1)

    KabsREV(args, params)

    progressUpdate(value=1)

    print("Done")
