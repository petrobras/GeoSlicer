#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import vtk

import json
from pathlib import Path
import itertools

import mrml
import numpy as np
import pandas as pd
import pickle
import porespy
import openpnm

from ltrace.algorithms.common import (
    generate_equidistant_points_on_sphere,
    points_are_below_plane,
)
from ltrace.pore_networks.krel_result import KrelResult, KrelTables
from ltrace.pore_networks.visualization_model import generate_model_variable_scalar
from PoreNetworkSimulationCLILib.two_phase.two_phase_simulation import PNFLOW, PORE_FLOW, TwoPhaseSimulation

from ltrace.pore_networks.functions_simulation import (
    get_connected_spy_network,
    get_flow_rate,
    get_sub_spy,
    manual_valvatne_blunt,
    set_subresolution_conductance,
    single_phase_permeability,
)
from ltrace.pore_networks.subres_models import set_subres_model

from PoreNetworkSimulationCLILib.vtk_utils import create_flow_model, create_permeability_sphere

from ltrace.slicer.cli_utils import progressUpdate
import shutil


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


def onePhase(args, params):
    cwd = Path(args.cwd)

    with open(str(cwd / "pore_network.dict"), "rb") as file:
        pore_network = pickle.load(file)

    in_faces = ("xmin", "ymin", "zmin")
    out_faces = ("xmax", "ymax", "zmax")

    flow_array = np.zeros((1, 3), dtype="float")
    permeability_array = np.zeros((1, 3), dtype="float")

    sizes = params["sizes"]
    ijktoras = params["ijktoras"]
    sizes_product = sizes["x"] * sizes["y"] * sizes["z"]

    subres_func = set_subres_model(pore_network, params)

    minmax = []
    counter = 1
    # for inlet, outlet in itertools.combinations_with_replacement((0, 1, 2), 2):
    for inlet, outlet in ((0, 0), (1, 1), (2, 2)):
        in_face = in_faces[inlet]
        out_face = out_faces[outlet]
        perm, pn_pores, pn_throats = single_phase_permeability(
            pore_network,
            in_face,
            out_face,
            subresolution_function=subres_func,
            subres_porositymodifier=params["subres_porositymodifier"],
            subres_shape_factor=params["subres_shape_factor"],
            solver=params["solver"],
            target_error=params["solver_error"],
            preconditioner=params["preconditioner"],
            clip_check=params["clip_check"],
            clip_value=params["clip_value"],
        )
        if (perm == 0) or (perm.network.throats("all").size == 0):
            continue
        net = perm.project.network

        flow_rate = get_flow_rate(pn_pores, pn_throats)

        if in_face[0] == out_face[0]:
            length = sizes[in_faces[2 - inlet][0]]
            area = sizes_product / length
            permeability = flow_rate * (length / area)
        else:
            # Darcy permeability for pluridimensional flow is undefined
            permeability = 0
        flow_array[0, inlet] = flow_rate
        # flow_array[outlet, 0] = flow_rate
        permeability_array[0, inlet] = permeability * 1000  # Conversion factor from darcy to milidarcy
        # permeability_array[outlet, 0] = permeability * 1000  # Conversion factor from darcy to milidarcy

        # Create VTK models
        # throat_values = np.log10(perm.rate(throats=perm.network.throats("all"), mode="individual"))
        throat_values = np.zeros(pn_throats["throat.all"].size)
        try:
            min_throat = np.min(throat_values[throat_values > (-np.inf)])
            max_throat = np.max(throat_values[throat_values > (-np.inf)])
        except:
            min_throat = -np.inf
            max_throat = np.inf
        minmax.append({"inlet": inlet, "outlet": outlet, "min": min_throat, "max": max_throat})

        # pore_values = perm["pore.pressure"]
        pore_values = pn_pores["pore.pressure"]
        pores_model, throats_model = create_flow_model(perm.project, pore_values, throat_values, sizes, ijktoras)
        writePolydata(pores_model, f"{args.tempDir}/pore_pressure_{inlet}_{outlet}.vtk")
        writePolydata(throats_model, f"{args.tempDir}/throat_flow_rate_{inlet}_{outlet}.vtk")

        throat_values = perm.network.throats("all")

        pore_values = perm.project.network[f"pore.{out_face}"].astype(int) - perm.project.network[
            f"pore.{in_face}"
        ].astype(int)
        border_pores_model_node, null_throats_model_node = create_flow_model(
            perm.project, pore_values, throat_values, sizes, ijktoras
        )
        del null_throats_model_node
        writePolydata(border_pores_model_node, f"{args.tempDir}/border_pores_{inlet}_{outlet}.vtk")

        df_pores = pd.DataFrame(pn_pores)
        df_throats = pd.DataFrame(pn_throats)
        writeDataFrame(df_pores, f"{args.tempDir}/pores_{inlet}_{outlet}.pd")
        writeDataFrame(df_throats, f"{args.tempDir}/throats_{inlet}_{outlet}.pd")

        progressUpdate(value=0.1 + 0.9 * counter / 6)
        counter += 1

    with open(f"{args.tempDir}/return_params.json", "w") as file:
        json.dump(minmax, file)

    flow_df = pd.DataFrame(
        flow_array,
        index=None,
        columns=("z [cm^3/s]", "y [cm^3/s]", "x [cm^3/s]"),
    )
    writeDataFrame(flow_df, cwd / "flow.pd")

    permeability_df = pd.DataFrame(
        permeability_array,
        index=None,
        columns=("z [mD]", "y [mD]", "x [mD]"),
    )
    writeDataFrame(permeability_df, cwd / "permeability.pd")
    # writeDataFrame(pd.DataFrame(x, "Pressure"), cwd / "pressure.pd")


def onePhaseMultiAngle(args, params):
    cwd = Path(args.cwd)

    with open(str(cwd / "pore_network.dict"), "rb") as file:
        pore_network = pickle.load(file)

    boundingbox = {
        "xmin": pore_network["pore.coords"][:, 0].min(),
        "xmax": pore_network["pore.coords"][:, 0].max(),
        "ymin": pore_network["pore.coords"][:, 1].min(),
        "ymax": pore_network["pore.coords"][:, 1].max(),
        "zmin": pore_network["pore.coords"][:, 2].min(),
        "zmax": pore_network["pore.coords"][:, 2].max(),
    }
    bb_sizes = np.array(tuple(boundingbox[f"{i}max"] - boundingbox[f"{i}min"] for i in "xyz"))
    bb_center = bb_sizes / 2 + tuple(boundingbox[f"{i}min"] for i in "xyz")
    bb_radius = bb_sizes.min() / 2
    bb_radius_sq = bb_radius**2

    pore_in_sphere = (pore_network["pore.coords"][:, 0] - bb_center[0]) ** 2
    pore_in_sphere += (pore_network["pore.coords"][:, 1] - bb_center[1]) ** 2
    pore_in_sphere += (pore_network["pore.coords"][:, 2] - bb_center[2]) ** 2
    pore_in_sphere = (pore_in_sphere <= bb_radius_sq).astype(bool)

    throat_in_sphere = np.zeros(pore_network["throat.all"].shape, dtype=bool)
    for i in range(throat_in_sphere.size):
        conn_1, conn_2 = pore_network["throat.conns"][i, :]
        if (pore_in_sphere[conn_1]) and (pore_in_sphere[conn_2]):
            throat_in_sphere[i] = True

    subres_func = set_subres_model(pore_network, params)

    minmax = []
    surface_points = generate_equidistant_points_on_sphere(N=params["rotation angles"] * 2, r=(bb_radius / np.sqrt(2)))
    number_surface_points = surface_points.shape[0] // 2
    surface_points = surface_points[0:number_surface_points, :]
    number_surface_points = surface_points.shape[0]
    permeabilities = []
    dx, dy, dz = bb_center
    for counter, i in enumerate(range(number_surface_points)):
        px, py, pz = surface_points[i]

        pore_network["pore.xmax"] = points_are_below_plane(
            pore_network["pore.coords"],
            (px + dx, py + dy, pz + dz),
            (-px, -py, -pz),
        )
        pore_network["pore.xmin"] = points_are_below_plane(
            pore_network["pore.coords"],
            (-px + dx, -py + dy, -pz + dz),
            (px, py, pz),
        )

        """
        perm, pn_pores, pn_throats = single_phase_permeability(
            pore_network,
            subresolution_function=subres_func,
            solver=params["solver"],
            target_error=params["solver_error"],
        )
        """
        perm, pn_pores, pn_throats = single_phase_permeability(
            pore_network,
            subresolution_function=subres_func,
            subres_shape_factor=params["subres_shape_factor"],
            solver=params["solver"],
            target_error=params["solver_error"],
            preconditioner=params["preconditioner"],
            clip_check=params["clip_check"],
            clip_value=params["clip_value"],
        )
        if perm == 0:
            permeabilities.append((px, py, pz, 0))
            continue

        flow_rate = get_flow_rate(pn_pores, pn_throats)  # cm^3/s

        permeability = flow_rate / (2 * bb_radius)  # return is Darcy
        permeabilities.append((px, py, pz, permeability))
        permeabilities.append((-px, -py, -pz, permeability))

        # Create VTK models
        if i % 20 != 0:
            continue

        throat_values = np.log10(pn_throats["throat.flow"])
        try:
            min_throat = np.min(throat_values[throat_values > (-np.inf)])
            max_throat = np.max(throat_values[throat_values > (-np.inf)])
        except:
            min_throat = -np.inf
            max_throat = np.inf
        minmax.append({"index": i, "min": min_throat, "max": max_throat})
        pore_values = pn_pores["pore.pressure"]
        pores_model, throats_model = create_flow_model(perm.project, pore_values, throat_values, None)

        writePolydata(pores_model, f"{args.tempDir}/pore_pressure_{i}.vtk")
        writePolydata(throats_model, f"{args.tempDir}/throat_flow_rate_{i}.vtk")

        throat_values = perm.network.throats("all")

        pore_values = perm.project.network["pore.xmin"].astype(int) - perm.project.network["pore.xmax"].astype(int)
        border_pores_model_node, null_throats_model_node = create_flow_model(
            perm.project, pore_values, throat_values, None
        )
        del null_throats_model_node
        writePolydata(border_pores_model_node, f"{args.tempDir}/border_pores_{i}.vtk")

        progressUpdate(value=0.1 + 0.9 * counter / number_surface_points)

    model, model_range, sphere, plane, arrow, direction = create_permeability_sphere(
        permeabilities,
        radius=bb_radius,
        verbose=False,
    )

    writePolydata(model, f"{args.tempDir}/model.vtk")
    writePolydata(sphere, f"{args.tempDir}/sphere.vtk")
    writePolydata(plane, f"{args.tempDir}/plane.vtk")
    writePolydata(arrow, f"{args.tempDir}/arrow.vtk")
    return_params = {
        "minmax": minmax,
        "multiangle_model_range": model_range,
        "direction": direction,
        "permeabilities": permeabilities,
    }
    with open(f"{args.tempDir}/return_params.json", "w") as file:
        json.dump(return_params, file)


def twoPhaseSensibilityTest(args, params, is_multiscale):
    cwd = Path(args.cwd)

    with open(str(cwd / "statoil_dict.json"), "r") as file:
        statoil_dict = json.load(file)

    snapshot_file_path = cwd / "snapshot.bin"
    if snapshot_file_path.is_file():
        snapshot_file = str(snapshot_file_path)
    else:
        snapshot_file = None

    num_tests = get_number_of_tests(params)
    keep_temporary = params["keep_temporary"]
    timeout_enabled = params["timeout_enabled"]

    if statoil_dict is None:
        raise RuntimeError("The network is invalid.")
        return

    parallel = TwoPhaseSimulation(
        cwd=cwd,
        statoil_dict=statoil_dict,
        snapshot_file=snapshot_file,
        params=params,
        num_tests=num_tests,
        timeout_enabled=timeout_enabled,
        write_debug_files=keep_temporary,
    )

    parallel.set_simulator(PNFLOW if params["simulator"] == "pnflow" else PORE_FLOW)

    saturation_steps_list = []
    krel_result = KrelResult()
    for i, result in enumerate(parallel.run(args.maxSubprocesses)):
        krel_result.add_single_result(result["input_params"], result["table"])

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
                polydata, saturation_steps = generate_model_variable_scalar(
                    Path(result["cwd"]) / "Output_res", is_multiscale=is_multiscale
                )
                writePolydata(polydata, f"{args.tempDir}/cycle_node_{i}.vtk")
                saturation_steps_list.append(saturation_steps)

            if params["create_ca_distributions"] == "T":
                try:
                    with open(str(Path(result["cwd"]) / "ca_distribution.json"), "r") as fp:
                        ca_distribution_dict = json.load(fp)
                    ca_distribution_df = pd.DataFrame()
                    ca_distribution_df["drainage-advancing"] = ca_distribution_dict["drainage"]["advancing_ca"]
                    ca_distribution_df["drainage-receding"] = ca_distribution_dict["drainage"]["receding_ca"]
                    ca_distribution_df["imbibition-advancing"] = ca_distribution_dict["imbibition"]["advancing_ca"]
                    ca_distribution_df["imbibition-receding"] = ca_distribution_dict["imbibition"]["receding_ca"]
                    writeDataFrame(ca_distribution_df, cwd / f"ca_distribution_{i}")
                except FileNotFoundError:
                    pass

            if params["create_drainage_snapshot"] == "T":
                shutil.copyfile(Path(result["cwd"]) / "snapshot.bin", cwd / "snapshot.bin")

            if not keep_temporary:
                shutil.rmtree(result["cwd"])

    with open(args.returnparameterfile, "w") as returnFile:
        returnFile.write("saturation_steps=" + json.dumps(saturation_steps_list) + "\n")


def simulate_mercury(args, params):
    cwd = Path(args.cwd)

    with open(str(cwd / "pore_network.dict"), "rb") as file:
        pore_network = pickle.load(file)

    subres_func = set_subres_model(pore_network, params)

    proj = openpnm.io.network_from_porespy(pore_network)
    connected_pores, connected_throats = get_connected_spy_network(proj.network, "xmin", "xmax")
    sub_network = get_sub_spy(pore_network, connected_pores, connected_throats)
    if sub_network is False:
        print("No subnetwork found")
        return (0, None)
    for prop in sub_network.keys():
        np.nan_to_num(sub_network[prop], copy=False)

    manual_valvatne_blunt(sub_network)
    set_subresolution_conductance(
        sub_network,
        subresolution_function=subres_func,
        subres_porositymodifier=params["subres_porositymodifier"],
        subres_shape_factor=params["subres_shape_factor"],
        save_tables=params["save_tables"],
    )

    with open(str(cwd / "net_flow_props.dict"), "wb") as file:
        pickle.dump(sub_network, file)

    net = openpnm.io.network_from_porespy(sub_network)

    hg = openpnm.phase.Mercury(network=net, name="mercury")

    phys = openpnm.models.collections.physics.basic
    hg.add_model_collection(phys)
    hg.regenerate_models()

    mip = openpnm.algorithms.Drainage(network=net, phase=hg)
    mip.set_inlet_BC(pores=net.pores("xmin"), mode="overwrite")
    mip.set_outlet_BC(pores=net.pores("xmax"), mode="overwrite")

    # mip.run()
    # code block originally taken from openpnm source
    phase = mip.project[mip.settings.phase]
    phase[mip.settings.throat_entry_pressure] = net["throat.cap_pressure"]
    hi = 1.25 * phase[mip.settings.throat_entry_pressure].max()
    low = 0.80 * phase[mip.settings.throat_entry_pressure].min()
    pressures = np.logspace(np.log10(low), np.log10(hi), params["pressures"])
    pressures = np.array(pressures, ndmin=1)
    for i, p in enumerate(pressures):
        mip._run_special(p)
        pmask = mip["pore.invaded"] * (mip["pore.invasion_pressure"] == np.inf)
        mip["pore.invasion_pressure"][pmask] = p
        mip["pore.invasion_sequence"][pmask] = i
        tmask = mip["throat.invaded"] * (mip["throat.invasion_pressure"] == np.inf)
        mip["throat.invasion_pressure"][tmask] = p
        mip["throat.invasion_sequence"][tmask] = i
        progressUpdate(value=int(100 * i / pressures.size))
    # if np.any(mip["pore.bc.outlet"]):
    #    mip.apply_trapping()

    pc = mip.pc_curve()

    df = pd.DataFrame({"pc": pc.pc, "snwp": pc.snwp})
    writeDataFrame(df, cwd / "micpResults.pd")

    dict_file = open(str(cwd / "return_net.dict"), "wb")
    pickle.dump(net, dict_file)
    dict_file.close()

    progressUpdate(value=100)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace pore network simulation CLI.")
    parser.add_argument("--model", type=str, required=True)
    parser.add_argument("--cwd", type=str, required=False)
    parser.add_argument("--maxSubprocesses", type=int, default=8, required=False)
    parser.add_argument("--tempDir", type=str, dest="tempDir", default=None, help="Temporary directory")
    parser.add_argument(
        "--returnparameterfile",
        type=str,
        default=None,
        help="File destination to store an execution outputs",
    )
    parser.add_argument("--isMultiScale", type=int, default=0, required=False)
    args = parser.parse_args()

    with open(f"{args.cwd}/params_dict.json", "r") as file:
        params = json.load(file)

    progressUpdate(value=0.1)

    if args.model == "onePhase" and params.get("simulation type") == "Single orientation":
        onePhase(args, params)
    elif args.model == "onePhase" and params.get("simulation type") == "Multiple orientations":
        onePhaseMultiAngle(args, params)
    elif args.model == "TwoPhaseSensibilityTest":
        twoPhaseSensibilityTest(args, params, bool(args.isMultiScale))
    elif args.model == "MICP":
        simulate_mercury(args, params)

    progressUpdate(value=1)

    print("Done")
