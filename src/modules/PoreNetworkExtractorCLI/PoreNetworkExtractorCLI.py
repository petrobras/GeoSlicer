#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import vtk
from multiprocessing.shared_memory import SharedMemory
import sys
from time import sleep

import json
import numpy as np

import slicer
import mrml
from ltrace.slicer.cli_utils import progressUpdate
from ltrace.pore_networks.functions_extract import general_pn_extract


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


def extractPNM(args, params):
    progressUpdate(value=0.1)
    if args.semaphore is None:
        cli_extract(args, params)
    else:
        cli_extract_shared_memory(args, params)
    progressUpdate(value=1.0)


def cli_extract(args, params):
    method = params["method"]
    if method != "PoreSpy":
        raise ValueError(f"Only 'PoreSpy' method is currently supported. Chosen method: '{method}'")

    if params["is_multiscale"]:
        volumeNode = readFrom(args.scalar, mrml.vtkMRMLScalarVolumeNode)
        scale = volumeNode.GetSpacing()[::-1]
        scalar_array = slicer.util.arrayFromVolume(volumeNode)
        labelNode = readFrom(args.label, mrml.vtkMRMLLabelMapVolumeNode) if args.label else None
        if labelNode is not None:
            label_array = slicer.util.arrayFromVolume(labelNode)
        else:
            label_array = None
    else:
        labelNode = readFrom(args.scalar, mrml.vtkMRMLLabelMapVolumeNode)
        label_array = slicer.util.arrayFromVolume(labelNode)
        scale = labelNode.GetSpacing()[::-1]
        scalar_array = None

    extract_result = general_pn_extract(
        label_array=label_array,
        scalar_array=scalar_array,
        scale=scale,
        is_multiscale=params["is_multiscale"],
        watershed_blur=params["watershed_blur"],
    )

    if extract_result is not None:
        pores_df, throats_df, network_df, output_watershed, _ = extract_result
    else:
        print("No connected network was identified. Possible cause: unsegmented pore space.")
        return

    pores_df.to_pickle(f"{args.cwd}/pore_network.pkl")
    throats_df.to_pickle(f"{args.cwd}/throat_network.pkl")
    network_df.to_pickle(f"{args.cwd}/network.pkl")
    if output_watershed is not None:
        np.save(f"{args.cwd}/watershed.npy", output_watershed)


def cli_extract_shared_memory(args, params):
    semaphore_shm = SharedMemory(args.semaphore)
    method = params["method"]
    if method != "PoreSpy":
        raise ValueError(f"Only 'PoreSpy' method is currently supported. Chosen method: '{method}'")

    scale = tuple(float(i) for i in params["scale"][1:-1].split(", "))
    if params["is_multiscale"] is True:
        scalar_memory, scalar_array = _load_shared_array(args.scalar, params["scalar_shape"], params["scalar_dtype"])
        if args.label is not None:
            label_memory, label_array = _load_shared_array(args.label, params["label_shape"], params["label_dtype"])
        else:
            label_array = None
            label_memory = None
    elif params["is_multiscale"] is False:
        label_memory, label_array = _load_shared_array(args.label, params["label_shape"], params["label_dtype"])
        scalar_array = None
        scalar_memory = None

    # shm = SharedMemory(name=args.shm_name)
    # output_watershed = np.ndarray(scalar_array.shape, dtype=np.int32, buffer=shm.buf)
    extract_result = general_pn_extract(
        label_array=label_array,
        scalar_array=scalar_array,
        scale=scale,
        is_multiscale=params["is_multiscale"],
        watershed_blur=params["watershed_blur"],
        use_shared_memory=True,
    )

    if extract_result is not None:
        pores_df, throats_df, network_df, watershed_memory, watershed_shape = extract_result
    else:
        print("No connected network was identified. Possible cause: unsegmented pore space.")
        return

    pores_df.to_pickle(f"{args.cwd}/pore_network.pkl")
    throats_df.to_pickle(f"{args.cwd}/throat_network.pkl")
    network_df.to_pickle(f"{args.cwd}/network.pkl")
    if watershed_memory is not None:
        with open(f"{args.cwd}/shm_info.txt", "w", encoding="utf-8") as file:
            file.write(f"{watershed_memory.name}\n")
            file.write(" ".join(map(str, watershed_shape)) + "\n")
        semaphore_shm.buf[0] = 1
        while semaphore_shm.buf[0] == 1:
            sleep(0.1)
        watershed_memory.close()
    semaphore_shm.close()
    if scalar_memory is not None:
        scalar_memory.close()
    if label_memory is not None:
        label_memory.close()
    # if output_watershed is not None:
    #    np.save(f"{args.cwd}/watershed.npy", output_watershed)
    # shm.close()


def _load_shared_array(memory_name, shape, dtype):
    shared_memory = SharedMemory(memory_name)
    shared_array = np.ndarray(
        tuple(int(i) for i in shape[1:-1].split(", ")),
        dtype=dtype,
        buffer=shared_memory.buf,
    )
    return shared_memory, shared_array


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace pore network extraction CLI.")
    parser.add_argument("--scalar", type=str, default=None, required=False)
    parser.add_argument("--label", type=str, default=None, required=False)
    parser.add_argument("--semaphore", type=str, required=False)
    parser.add_argument("--cwd", type=str, required=False)
    args = parser.parse_args()

    with open(f"{args.cwd}/extractor_params_dict.json", "r") as file:
        params = json.load(file)

    extractPNM(args, params)
