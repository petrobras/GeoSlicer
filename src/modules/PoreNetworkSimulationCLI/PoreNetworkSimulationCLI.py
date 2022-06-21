#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import vtk

import json
from pathlib import Path

import mrml
import numpy as np
import pandas as pd

from ltrace.pore_networks.krel_result import KrelResult, KrelTables
from ltrace.pore_networks.visualization_model import generate_model_variable_scalar
from PoreNetworkSimulationCLILib.pnflow.pnflow_parallel import PnFlow
from ltrace.slicer.cli_utils import progressUpdate
from ltrace.wrappers import sanitize_file_path
import shutil


def twoPhaseSensibilityTest(args):
    cwd = sanitize_file_path(args.cwd)
    statoil_dict_file = cwd / "statoil_dict.json"
    params_dict_file = cwd / "params_dict.json"

    with open(statoil_dict_file.as_posix(), "r") as file:
        statoil_dict = json.load(file)

    with open(params_dict_file.as_posix(), "r") as file:
        params = json.load(file)

    num_tests = get_number_of_tests(params)
    keep_temporary = params["keep_temporary"]

    pnflow_parallel = PnFlow(cwd=cwd, statoil_dict=statoil_dict, params=params, num_tests=num_tests)

    saturation_steps_list = []
    krel_result = KrelResult()
    for i, pnflow_result in enumerate(pnflow_parallel.run_pnflow(args.maxSubprocesses)):
        krel_result.add_single_result(pnflow_result["input_params"], pnflow_result["pnflow_table"])

        # Write results only every 10 new results
        krel_tables_len = len(krel_result.krel_tables)
        frequency = 10
        if (krel_tables_len > 0 and krel_tables_len % frequency == 0) or krel_tables_len > num_tests - frequency:
            df_cycle_results = pd.DataFrame(KrelTables.get_complete_dict(krel_result.krel_tables))

            for cycle in range(1, 4):
                cycle_data_frame = df_cycle_results[df_cycle_results["cycle"] == cycle]
                writeDataFrame(cycle_data_frame, cwd / f"krelCycle{cycle}")

            curve_analysis_df = krel_result.to_dataframe()
            writeDataFrame(curve_analysis_df, cwd / "krelResults")

            if params["create_sequence"] == "T":
                polydata, saturation_steps = generate_model_variable_scalar(Path(pnflow_result["cwd"]) / "Output_res")
                writePolydata(polydata, f"{args.tempDir}/cycle_node_{i}.vtk")
                saturation_steps_list.append(saturation_steps)

            if not keep_temporary:
                shutil.rmtree(pnflow_result["cwd"])

    return_parameter_file_path = sanitize_file_path(args.returnparameterfile)
    with open(return_parameter_file_path.as_posix(), "w") as returnFile:
        returnFile.write("saturation_steps=" + json.dumps(saturation_steps_list) + "\n")


def get_number_of_tests(params: dict):
    num_tests = 1
    for _, value in params.items():
        if type(value) == list:
            num_tests *= len(value)
    return num_tests


def writeDataFrame(df, path):
    df.to_pickle(str(path))


def writePolydata(polydata, filename):
    writer = vtk.vtkPolyDataWriter()
    writer.SetInputData(polydata)
    writer.SetFileName(filename)
    writer.Write()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace pore network simulation CLI.")
    parser.add_argument("--model", type=str, required=True)
    parser.add_argument("--cwd", type=str, required=False)
    parser.add_argument("--maxSubprocesses", type=int, default=8, required=False)
    parser.add_argument("--tempDir", type=str, dest="tempDir", default=None, help="Temporary directory")
    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )
    args = parser.parse_args()

    progressUpdate(value=0.1)

    if args.model == "TwoPhaseSensibilityTest":
        twoPhaseSensibilityTest(args)

    progressUpdate(value=1)

    print("Done")
