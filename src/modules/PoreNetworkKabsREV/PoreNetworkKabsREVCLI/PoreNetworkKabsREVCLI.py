#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import slicer

import json
import logging
import re
from pathlib import Path

import mrml
import numpy as np
import pandas as pd

from ltrace.pore_networks.functions_extract import general_pn_extract
from ltrace.pore_networks.functions_simulation import get_flow_rate, single_phase_permeability
from ltrace.pore_networks.subres_models import get_subres_function
from ltrace.slicer.cli_utils import progressUpdate

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


def crop_volume(array, size, translation=(0, 0, 0), is_labelmap=False):
    shape = array.shape

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

    cropped_array = array[zmin:zmax, ymin:ymax, xmin:xmax]

    return cropped_array


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
    full_array = slicer.util.arrayFromVolume(volume)
    scale = volume.GetSpacing()[::-1]

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
            cropped_volume = crop_volume(
                full_array, size, translation=translation, is_labelmap=not params["is_multiscale"]
            )

            # try:
            if params["is_multiscale"]:
                watershed_blur = {1: 0.1, 2: 0.1}
                extract_result = general_pn_extract(
                    scalar_array=cropped_volume,
                    label_array=None,
                    watershed_blur=watershed_blur,
                    force_cpu=True,
                    is_multiscale=True,
                    scale=scale,
                )
            else:
                extract_result = general_pn_extract(
                    scalar_array=None,
                    label_array=cropped_volume,
                    force_cpu=True,
                    is_multiscale=False,
                    scale=scale,
                )
            # except Exception as err:
            #    print(Exception, err)

            pores_df, throats_df, network_df, _ = extract_result

            if pores_df.empty:
                continue

            pore_network = dfs2spy(pores_df, throats_df)

            x_size = scale[0] * cropped_volume.shape[0]
            y_size = scale[1] * cropped_volume.shape[1]
            z_size = scale[2] * cropped_volume.shape[2]

            params["scalar_volume_data"] = {}
            params["scalar_volume_data"]["sizes"] = {
                "x": x_size,
                "y": y_size,
                "z": z_size,
            }  # In mm
            params["scalar_volume_data"]["spacing"] = {
                "x": scale[0],
                "y": scale[1],
                "z": scale[2],
            }
            sizes_product = x_size * y_size * z_size
            subres_func = get_subres_function(pore_network, params)

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

                length = 0.1 * params["scalar_volume_data"]["sizes"][in_faces[2 - inlet][0]]  # cm
                mu = params["fluid_viscosity"]  # Pa*s
                deltaP = params["pressure_drop"]  # Pa
                flow_rate = get_flow_rate(pn_pores, pn_throats, viscosity=mu, pressure_drop=deltaP) / 1000  # cm^3/s
                area = 0.1**3 * sizes_product / length  # cm^2
                permeability = (flow_rate / area) * (mu * length / deltaP)  # cm^2
                permeabilities[directions[inlet]].append(
                    (
                        100 * length_fraction,  # %
                        10 * length,  # mm
                        100 * area,  # mm^2
                        flow_rate,  # cm^3/s
                        permeability * 1.01325e11,  # mD
                        volume_porosity,  # %
                        network_porosity,  # %
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
