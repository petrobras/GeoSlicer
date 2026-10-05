#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

from pathlib import Path
import vtk
import sys
from time import sleep

from dask_jobqueue import SLURMCluster
from dask.distributed import Client
import json
import numpy as np
import os
import pickle

import slicer
import mrml
from ltrace.slicer.cli_utils import progressUpdate
from ltrace.pore_networks.functions_extract import general_pn_extract
from ltrace.remote.object_transfer import JsonObjectTransfer, VolumeNodeObjectTransfer
from ltrace.utils.mmap_shared_memory import MmapSharedMemory


def parse_divs(value):
    try:
        return json.loads(value)
    except Exception:
        return int(value)


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

    if args.slurm:
        geoslicer_base_path = os.getenv("GEOSLICER_BASE_PATH")
        log_dir = args.cwd if args.cwd else os.getcwd()  # Fallback to CWD if args.cwd isn't passed
        cluster = SLURMCluster(
            cores=args.slurm_cores,
            memory=args.slurm_memory,
            scheduler_options={"interface": "bond0"},
            python=f"{geoslicer_base_path}/scripts/run_apptainer.sh",
            account="tcr_ext",
            log_directory=log_dir,
            processes=1,
            death_timeout=3600,
            walltime=args.slurm_walltime,
        )
        cluster.scale(jobs=args.slurm_jobs)
        client = Client(cluster)

    if params["is_multiscale"]:
        volume_node_path = Path(args.scalar)
        with VolumeNodeObjectTransfer(volume_node_path.parent, volume_node_path.name) as transfer:
            scalar_array, volume_node_header = transfer.load()
        scale = volume_node_header["spacing"][::-1]

        label_array = None
        if args.label is not None:
            label_node_path = Path(args.label)
            with VolumeNodeObjectTransfer(label_node_path.parent, label_node_path.name) as transfer:
                if transfer.exists():
                    label_array, _ = transfer.load()
    else:
        label_node_path = Path(args.scalar)
        with VolumeNodeObjectTransfer(label_node_path.parent, label_node_path.name) as transfer:
            label_array, label_node_header = transfer.load()
        scale = label_node_header["spacing"][::-1]
        scalar_array = None

    extract_result = general_pn_extract(
        label_array=label_array,
        scalar_array=scalar_array,
        scale=scale,
        is_multiscale=params["is_multiscale"],
        watershed_blur=params["watershed_blur"],
        divs=args.divs,
    )

    if args.slurm:
        client.close()

    if extract_result is not None:
        pores_df, throats_df, network_df, output_watershed, _ = extract_result
    else:
        print("No connected network was identified. Possible cause: unsegmented pore space.")
        return

    pores_df.to_pickle(f"{args.cwd}/pore_network.pkl")
    throats_df.to_pickle(f"{args.cwd}/throat_network.pkl")
    network_df.to_pickle(f"{args.cwd}/network.pkl")
    if output_watershed is not None and not args.no_save_watershed:
        np.save(f"{args.cwd}/watershed.npy", output_watershed)


def cli_extract_shared_memory(args, params):
    semaphore_shm = MmapSharedMemory.from_file(args.semaphore)
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
        divs=args.divs,
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


def _load_shared_array(memory_path, shape, dtype):
    shared_memory = MmapSharedMemory.from_file(memory_path)
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
    parser.add_argument("--slurm", action="store_true")
    parser.add_argument("--no_save_watershed", action="store_true")
    parser.add_argument("--divs", type=parse_divs, default=2, required=False)
    parser.add_argument("--slurm_jobs", type=int, default=4, required=False)
    parser.add_argument("--slurm_cores", type=int, default=1, required=False)
    parser.add_argument("--slurm_memory", type=str, default="2GB", required=False)
    parser.add_argument("--slurm_walltime", type=str, default="10:00:00", required=False)
    args = parser.parse_args()

    with JsonObjectTransfer(args.cwd, "extractor_params_dict.json") as transfer:
        params = transfer.load()

    extractPNM(args, params)
