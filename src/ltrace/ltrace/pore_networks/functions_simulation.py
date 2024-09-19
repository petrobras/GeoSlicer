import os
import csv

import numpy as np
import openpnm
from pypardiso import spsolve
from scipy.sparse import csr_matrix
from numba import njit, prange


def manual_valvatne_blunt(pore_network):
    """
    Modifies a PoreSpy format pore network dictionary inplace, adding Valvatne
    Blunt flow properties:
        throat.manual_valvatne_conductivity
        throat.manual_valvatne_conductance
        pore.manual_valvatne_conductivity
        pore.shape

    Shape values:
        0 - Triangle
        1 - Square
        2 - Circle

        In this context, conductivity is linear (1D), therefore,
    to get conductance, it must be divided by length, but the
    cross sectional area is already computed in the value
        Conductance already takes in account the throat mid length
    and the connected pores half-lengths
    """
    throat_shape_factor = pore_network["throat.shape_factor"]
    throat_radius = pore_network["throat.inscribed_diameter"] / 2
    throat_area = pore_network["throat.cross_sectional_area"]
    throat_conns_0_length = pore_network["throat.conns_0_length"]
    throat_conns_1_length = pore_network["throat.conns_1_length"]
    throat_mid_length = pore_network["throat.mid_length"]
    pore_shape_factor = pore_network["pore.shape_factor"]
    pore_radius = pore_network["pore.extended_diameter"] / 2
    pore_area = pore_radius**2 / (4 * pore_shape_factor)

    pore_shape = np.zeros(len(pore_network["pore.extended_diameter"]), dtype=np.uint8)
    pore_conductivity = np.zeros(len(pore_network["pore.extended_diameter"]), dtype=np.float32)
    for pore, shape_factor in enumerate(pore_network["pore.shape_factor"]):
        if shape_factor <= 0.048:
            pore_shape[pore] = 0
            pore_conductivity[pore] = (3 / 5) * pore_area[pore] ** 2 * shape_factor
        elif shape_factor <= 0.07:
            pore_shape[pore] = 1
            pore_conductivity[pore] = (0.5623) * pore_area[pore] ** 2 * shape_factor
        else:
            pore_shape[pore] = 2
            pore_conductivity[pore] = (1 / 8) * pore_area[pore] * pore_radius[pore] ** 2

    throat_shape = np.zeros(len(pore_network["throat.shape_factor"]), dtype=np.uint8)
    throat_conductivity = np.zeros(len(pore_network["throat.shape_factor"]), dtype=np.float32)
    throat_conductance = np.zeros(len(pore_network["throat.shape_factor"]), dtype=np.float32)
    for throat, shape_factor in enumerate(throat_shape_factor):
        conn_0 = pore_network["throat.conns"][throat][0]
        conn_1 = pore_network["throat.conns"][throat][1]
        if shape_factor <= 0.048:
            throat_shape[throat] = 0
            throat_conductivity[throat] = (3 / 5) * throat_area[throat] ** 2 * shape_factor
        elif shape_factor <= 0.07:
            throat_shape[throat] = 1
            throat_conductivity[throat] = (0.5623) * throat_area[throat] ** 2 * shape_factor
        else:
            throat_shape[throat] = 2
            throat_conductivity[throat] = (1 / 8) * throat_area[throat] * throat_radius[throat] ** 2
        throat_conductance[throat] = (
            throat_conns_0_length[throat] / pore_conductivity[conn_0]
            + throat_mid_length[throat] / throat_conductivity[throat]
            + throat_conns_1_length[throat] / pore_conductivity[conn_1]
        ) ** (-1)

    pore_network["throat.shape"] = throat_shape
    pore_network["throat.manual_valvatne_conductivity"] = throat_conductivity
    pore_network["throat.manual_valvatne_conductance"] = throat_conductance
    pore_network["pore.shape"] = pore_shape
    pore_network["pore.manual_valvatne_conductivity"] = pore_conductivity

    return


def set_subresolution_conductance(sub_network, subresolution_function, save_tables=False):
    sub_network["pore.diameter"] = sub_network["pore.equivalent_diameter"]
    sub_network["throat.diameter"] = sub_network["throat.equivalent_diameter"]

    # Equations
    pressure2radius = lambda Pc: -2 * 480 * np.cos(np.pi * 140 / 180) / Pc
    area_function = lambda r: np.pi * r**2

    # Pore conductivity
    pore_conductivity_resolved = sub_network["pore.manual_valvatne_conductivity"]
    pore_phi = sub_network["pore.subresolution_porosity"]
    pore_pressure = np.array([subresolution_function(p) for p in pore_phi])
    pore_pressure[pore_phi == 1] = np.array([pressure2radius(r) for r in sub_network["pore.diameter"] / 2])[
        pore_phi == 1
    ]

    pore_capilar_radius = np.array([pressure2radius(Pc) for Pc in pore_pressure])
    sub_network["pore.capilar_radius"] = pore_capilar_radius

    pore_number_of_capilaries = (area_function(sub_network["pore.diameter"] / 2) * pore_phi) / area_function(
        pore_capilar_radius
    )
    sub_network["pore.number_of_capilaries"] = pore_number_of_capilaries
    pore_conductivity = (1 / 8) * np.pi * pore_capilar_radius**4
    pore_conductivity *= pore_number_of_capilaries

    throat_phi = sub_network["throat.subresolution_porosity"]
    throat_pressure = np.array([subresolution_function(p) for p in throat_phi])
    throat_pressure[throat_phi == 1] = np.array([pressure2radius(r) for r in sub_network["throat.diameter"] / 2])[
        throat_phi == 1
    ]
    throat_capilar_radius = np.array([pressure2radius(Pc) for Pc in throat_pressure])
    throat_number_of_capilaries = (area_function(sub_network["throat.diameter"] / 2) * throat_phi) / area_function(
        throat_capilar_radius
    )
    throat_conductivity = (1 / 8) * np.pi * throat_capilar_radius**4
    throat_conductivity *= throat_number_of_capilaries

    # Throat conductance
    throat_conductance = np.copy(sub_network["throat.manual_valvatne_conductance"])
    for throat_index, (left_index, right_index) in enumerate(
        sub_network["throat.conns"],
    ):
        left_unresolved = sub_network["throat.phases"][throat_index][0] == 2
        right_unresolved = sub_network["throat.phases"][throat_index][1] == 2

        if left_unresolved and not right_unresolved:
            throat_conductance[throat_index] = sub_network["throat.mid_length"][throat_index] / (
                2 * throat_conductivity[throat_index]
            )
            throat_conductance[throat_index] += (
                sub_network["throat.conns_0_length"][throat_index] / pore_conductivity[left_index]
            )
            throat_conductance[throat_index] += (
                sub_network["throat.conns_1_length"][throat_index] / pore_conductivity_resolved[right_index]
            )
            throat_conductance[throat_index] **= -1

        elif right_unresolved and not left_unresolved:
            throat_conductance[throat_index] = sub_network["throat.mid_length"][throat_index] / (
                2 * throat_conductivity[throat_index]
            )
            throat_conductance[throat_index] += (
                sub_network["throat.conns_0_length"][throat_index] / pore_conductivity_resolved[left_index]
            )
            throat_conductance[throat_index] += (
                sub_network["throat.conns_1_length"][throat_index] / pore_conductivity[right_index]
            )
            throat_conductance[throat_index] **= -1

        elif right_unresolved and left_unresolved:
            throat_conductance[throat_index] = (
                sub_network["throat.mid_length"][throat_index] / throat_conductivity[throat_index]
            )
            throat_conductance[throat_index] += (
                sub_network["throat.conns_0_length"][throat_index] / pore_conductivity[left_index]
            )
            throat_conductance[throat_index] += (
                sub_network["throat.conns_1_length"][throat_index] / pore_conductivity[right_index]
            )
            throat_conductance[throat_index] **= -1

    sub_network["pore.cap_pressure"] = pore_pressure.copy()
    sub_network["pore.cap_radius"] = pore_capilar_radius.copy()
    sub_network["throat.cap_pressure"] = throat_pressure.copy()
    sub_network["throat.cap_radius"] = throat_capilar_radius.copy()
    sub_network["throat.sub_conductivity"] = throat_conductivity.copy()
    sub_network["pore.sub_conductivity"] = pore_conductivity.copy()
    sub_network["throat.manual_valvatne_conductance_former"] = throat_conductance.copy()
    sub_network["throat.manual_valvatne_conductance"] = throat_conductance
    sub_network["throat.number_of_capilaries"] = throat_number_of_capilaries
    sub_network["pore.number_of_capilaries"] = pore_number_of_capilaries

    sub_network["throat.cross_sectional_area"] = np.pi * sub_network["throat.cap_radius"] ** 2
    sub_network["throat.volume"] = sub_network["throat.total_length"] * sub_network["throat.cross_sectional_area"]
    sub_network["pore.volume"] *= sub_network["pore.subresolution_porosity"]

    if save_tables:
        print(os.getcwd())
        for element in ("pore.", "throat."):
            pore_keys = [key for key in sub_network.keys() if key.startswith(element)]
            pore_dict = {key: sub_network[key] for key in pore_keys}
            csv_file_name = f"output_{element[:-1]}.csv"

            with open(csv_file_name, "w", newline="") as csvfile:
                # Use filtered_keys as fieldnames to ensure only "pore" keys are included
                fieldnames = pore_keys
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()

                for i in range(len(pore_dict[pore_keys[0]])):
                    row_data = {key: pore_dict[key][i] for key in pore_keys}
                    writer.writerow(row_data)


def _counter():
    i = -1
    while True:
        i += 1
        yield i


def get_clusters(network):
    """
    clusters are numbered starting at 0
    """
    from scipy.sparse import csgraph as csg

    am = network.create_adjacency_matrix(fmt="coo", triu=True)
    N, Cs = csg.connected_components(am, directed=False)
    return N, Cs


def get_sub_spy(spy_network, sub_pores, sub_throats):
    sub_pn = {}
    for prop in spy_network.keys():
        if prop.split(".")[0] == "pore":
            sub_pn[prop] = spy_network[prop][sub_pores]
        else:
            sub_pn[prop] = spy_network[prop][sub_throats]

    counter = _counter()
    f_counter = lambda x: next(counter) if x else 0
    new_pore_index = np.fromiter(map(f_counter, sub_pores), dtype="int")

    if len(sub_pn["throat.conns"]) == 0:
        return False
    for i in np.nditer(sub_pn["throat.conns"], op_flags=["readwrite"]):
        i[...] = new_pore_index[i]
    return sub_pn


def get_connected_spy_network(network, in_face, out_face):
    """
    in_face, out_face: str
        Each must be one of 'xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax'
    """
    valid_inputs = ["xmin", "xmax", "ymin", "ymax", "zmin", "zmax"]
    if in_face not in valid_inputs:
        raise ValueError(f"Face values is invalid: in_face = {in_face}")
    if out_face not in valid_inputs:
        raise ValueError(f"Face values is invalid: out_face = {out_face}")

    _, cluster_labels = get_clusters(network)
    in_labels = np.unique(cluster_labels[network[f"pore.{in_face}"]])
    out_labels = np.unique(cluster_labels[network[f"pore.{out_face}"]])
    common_labels = np.intersect1d(in_labels, out_labels, assume_unique=True)

    connected_pores = network.pores()[np.isin(cluster_labels, common_labels)]
    connected_throats = network.throats()[np.isin(network["throat.conns"], connected_pores).all(axis=1)]

    return np.isin(cluster_labels, common_labels), np.isin(network["throat.conns"], connected_pores).all(axis=1)


def single_phase_permeability(
    pore_network,
    in_face="xmin",
    out_face="xmax",
    subresolution_function=None,
    save_tables=False,
    solver="pyflowsolver",
    target_error=1e-7,
    preconditioner="inverse_diagonal",
    clip_check=False,
    clip_value=1e10,
):
    if solver not in ("pyflowsolver", "openpnm", "pypardiso"):
        raise Exception('Parameter solver must be  "pyflowsolver", "pypardiso" or "openpnm"')

    if (pore_network[f"pore.{in_face}"].sum() == 0) or (pore_network[f"pore.{out_face}"].sum() == 0):
        return (0, None, None)

    is_multiscale = pore_network["pore.phase2"].any()
    if is_multiscale and (subresolution_function is None):
        print("Multiscale network with no subresolution function")
        return (0, None, None)

    proj = openpnm.io.network_from_porespy(pore_network)
    connected_pores, connected_throats = get_connected_spy_network(proj.network, in_face, out_face)
    sub_network = get_sub_spy(pore_network, connected_pores, connected_throats)
    if sub_network is False:
        return 0, None, None
    for prop in sub_network.keys():
        np.nan_to_num(sub_network[prop], copy=False)
    manual_valvatne_blunt(sub_network)
    if is_multiscale:
        pass
    set_subresolution_conductance(sub_network, subresolution_function, save_tables=save_tables)
    sub_proj = openpnm.io.network_from_porespy(sub_network)

    ### Network clipping
    if clip_check:
        cond = sub_network["throat.sub_conductivity"].astype(np.float64)
        min_cond = cond.min()
        max_cond = cond.max()
        cond_range = max_cond / min_cond
        if cond_range > clip_value:
            max_clip = min_cond * clip_value
            cond = np.clip(cond, a_min=None, a_max=max_clip)
            sub_network["throat.sub_conductivity"] = cond
            sub_proj = openpnm.io.network_from_porespy(sub_network)
    elif False:
        cond = sub_network["throat.sub_conductivity"].astype(np.float64)
        min_cond = cond.min()
        max_cond = cond.max()
        cond_range = max_cond / min_cond
        if cond_range > clip_value:
            min_clip = max_cond / clip_value
            relevant_throats = cond >= min_clip
            preclipped_network = get_sub_spy(sub_network, sub_network["pore.all"], relevant_throats)
            preclipped_proj = openpnm.io.network_from_porespy(preclipped_network)
            connected_pores, connected_throats = get_connected_spy_network(preclipped_proj.network, in_face, out_face)
            clipped_network = get_sub_spy(preclipped_network, connected_pores, connected_throats)
            if clipped_network is False:
                return 0, None, None
            sub_proj = openpnm.io.network_from_porespy(clipped_network)

    water = openpnm.phase.Water(network=sub_proj.network)
    water.add_model_collection(openpnm.models.collections.physics.standard)
    sub_proj["throat.hydraulic_conductance"] = sub_proj["throat.manual_valvatne_conductance"]
    sub_proj["pore.phase"][...] = 1
    perm = openpnm.algorithms.StokesFlow(
        network=sub_proj,
        phase=water,
    )
    perm.settings["f_rtol"] = 1e-11
    perm.settings["x_rtol"] = 1e-11
    # print("\n\n############## OpenPNM flow ###########\n\n", perm, "\n\n##############################\n\n")
    perm.set_value_BC(
        pores=sub_proj.pores(in_face), values=101325, mode="overwrite"
    )  # pressure in pa: 101325 pa = 1 atm
    perm.set_value_BC(pores=sub_proj.pores(out_face), values=0, mode="overwrite")
    inlets = perm.network[f"pore.{in_face}"].astype(np.int32)
    outlets = perm.network[f"pore.{out_face}"].astype(np.int32)
    inlets = inlets * (1 - outlets)

    if (
        (perm.network["pore.all"].size <= 1)
        or (perm.network["throat.all"].size <= 1)
        or (inlets.sum() == 0)
        or (outlets.sum() == 0)
    ):
        return (0, None, None)

    if solver == "openpnm":
        perm.run(verbose=True)
        perm.network["throat.flow"] = perm.rate(throats=perm.network.throats("all"), mode="individual")
    elif solver == "pyflowsolver":
        conn = perm.network["throat.conns"].astype(np.int32)
        cond = perm.network["throat.sub_conductivity"].astype(np.float64)
        r = _get_sparse_system(conn, cond, inlets, outlets)
        sparse_val, sparse_col_idx, sparse_row_ptr, b, mid_to_total_indexes = r
        if preconditioner == "inverse_diagonal":
            P_val, P_col_idx, P_row_ptr = _get_diagonal_preconditioner(
                A_val=sparse_val,
                A_col_idx=sparse_col_idx,
                A_row_ptr=sparse_row_ptr,
                threads=1,
            )
        else:
            raise Exception
        x, error, iterations = _solve_pcg(
            sparse_val,
            sparse_col_idx,
            sparse_row_ptr,
            P_val,
            P_col_idx,
            P_row_ptr,
            b,
            max_iterations=sparse_val.size**2,  # sqrt(n) for n x n system
            target_error=target_error,  # 1.0e-6
            X0=np.zeros(b.size, dtype=np.float64),
            threads=1,
        )

        pressure = np.zeros(inlets.size, dtype=np.float64)
        pressure[mid_to_total_indexes] = x * np.float64(101325)
        for i in range(inlets.size):
            if inlets[i] == 1:
                pressure[i] = np.float64(101325)
            elif outlets[i] == 1:
                pressure[i] = np.float64(0)
    elif solver == "pypardiso":
        conn = perm.network["throat.conns"].astype(np.int32)
        cond = perm.network["throat.sub_conductivity"].astype(np.float64)
        r = _get_sparse_system(conn, cond, inlets, outlets)
        sparse_val, sparse_col_idx, sparse_row_ptr, b, mid_to_total_indexes = r
        A = csr_matrix(
            (
                sparse_val,
                sparse_col_idx,
                np.append(sparse_row_ptr, sparse_val.size),
            )
        )
        x = spsolve(A, b)
        pressure = np.zeros(inlets.size, dtype=np.float64)
        pressure[mid_to_total_indexes] = x * np.float64(101325)
        for i in range(inlets.size):
            if inlets[i] == 1:
                pressure[i] = np.float64(101325)
            elif outlets[i] == 1:
                pressure[i] = np.float64(0)

    project = perm.project
    pore_dict = {}
    throat_dict = {}
    for l in range(len(project)):
        for p in project[l].props():
            # if slicer_is_in_developer_mode():
            #    print(p, type(project[l][p]), project[l][p])
            prop_array = project[l][p]
            if prop_array.ndim == 1:
                if p[:4] == "pore":
                    pore_dict[p] = project[l][p]
                else:
                    throat_dict[p] = project[l][p]
            else:
                for i in range(prop_array.shape[1]):
                    if p[:4] == "pore":
                        pore_dict[f"{p}_{i}"] = project[l][p][:, i]
                    else:
                        throat_dict[f"{p}_{i}"] = project[l][p][:, i]

    pore_dict["pore.inlets"] = inlets
    pore_dict["pore.outlets"] = outlets

    if solver in ("pyflowsolver", "pypardiso"):
        output = np.zeros(inlets.shape, dtype=np.float64)
        output[: x.size] = x
        pore_dict["pore.pressure"] = pressure

        throat_dict["throat.cond"] = cond

    return (perm, pore_dict, throat_dict)


@njit
def _get_sparse_system(conn, cond, inlets, outlets):
    # network must have only connected pores
    # conn array(n, 2)

    inlets *= np.int32(1) - outlets
    border = inlets + outlets

    n_p_total = inlets.size
    n_p_in = inlets.sum()
    n_p_out = outlets.sum()
    n_p_mid = n_p_total - n_p_in - n_p_out
    n_t = cond.size

    mid_to_total_indexes = np.zeros((n_p_mid), dtype=np.int32)
    total_to_mid_indexes = np.zeros((n_p_total), dtype=np.int32)

    pore_index_filled = 0
    for p in range(n_p_total):
        if border[p] == 0:
            mid_to_total_indexes[pore_index_filled] = p
            total_to_mid_indexes[p] = pore_index_filled
            pore_index_filled += 1
    if pore_index_filled != mid_to_total_indexes.size:
        raise Exception

    sparse_row_counter = np.zeros((n_p_mid), dtype=np.int32)
    n_mid_t = 0
    for t in range(n_t):
        i = conn[t, 0]
        j = conn[t, 1]
        if (border[i] == 0) and (border[j] == 0):
            n_mid_t += 1
            sparse_row_counter[total_to_mid_indexes[i]] += 1
            sparse_row_counter[total_to_mid_indexes[j]] += 1

    sparse_val = np.zeros((n_p_mid + 2 * n_mid_t), dtype=np.float64)
    sparse_col_idx = np.ones((sparse_val.size), dtype=np.int32) * -1
    sparse_row_ptr = np.zeros((n_p_mid), dtype=np.int32)
    sparse_col_idx[0] = 0
    for i in range(1, n_p_mid):
        sparse_row_ptr[i] = sparse_row_ptr[i - 1] + sparse_row_counter[i - 1] + 1
        sparse_col_idx[sparse_row_ptr[i]] = i

    b = np.zeros(n_p_mid, dtype=np.float64)

    for t in range(n_t):
        conn_0 = conn[t, 0]
        conn_1 = conn[t, 1]
        conductance = cond[t]

        for i, j in ((conn_0, conn_1), (conn_1, conn_0)):
            if border[i] == 1:
                continue
            i_mid = total_to_mid_indexes[i]
            row_ptr_start = sparse_row_ptr[i_mid]
            sparse_val[row_ptr_start] -= conductance
            # print(i, j)

            if inlets[j] == 1:
                b[i_mid] -= conductance
            elif border[j] == 0:
                j_mid = total_to_mid_indexes[j]
                # print("mid: ", i_mid, j_mid)
                # target column is j_mid
                # first check if column is already occupied
                if (i_mid + 1) < sparse_row_ptr.size:
                    row_ptr_end = sparse_row_ptr[i_mid + 1]
                else:
                    row_ptr_end = sparse_val.size

                found = False
                for linear_index in range(row_ptr_start, row_ptr_end):
                    if sparse_col_idx[linear_index] == j_mid:
                        sparse_val[linear_index] += conductance
                        found = True
                        break
                if not found:
                    local_index = sparse_row_counter[i_mid]
                    linear_index = row_ptr_start + local_index
                    if (local_index <= 0) or (sparse_val[linear_index] != 0):
                        raise Exception
                    sparse_col_idx[linear_index] = j_mid
                    sparse_val[linear_index] = conductance
                    sparse_row_counter[i_mid] -= 1
                    found = True
                # print(found, linear_index, sparse_val[linear_index])
                if not found:
                    raise Exception

    # print(sparse_val.sum())
    # sparse cleanup

    sparse_val_dirty = sparse_val.copy()
    sparse_col_idx_dirty = sparse_col_idx.copy()
    sparse_row_ptr_dirty = sparse_row_ptr.copy()

    nulls_counter = 0
    for i in range(sparse_row_ptr.size):
        row_ptr_start = sparse_row_ptr[i]
        if (i + 1) < sparse_row_ptr.size:
            row_ptr_stop = sparse_row_ptr[i + 1]
        else:
            row_ptr_stop = sparse_val.size
        nulls = (sparse_col_idx[row_ptr_start:row_ptr_stop] == -1).sum()
        filled = row_ptr_stop - row_ptr_start - nulls
        sort_index = np.argsort(sparse_col_idx[row_ptr_start:row_ptr_stop])
        sorted_vals = sparse_val[row_ptr_start:row_ptr_stop][sort_index]
        sorted_col_idx = sparse_col_idx[row_ptr_start:row_ptr_stop][sort_index]
        compacted_start = row_ptr_start - nulls_counter
        compacted_end = compacted_start + filled
        sparse_val[compacted_start:compacted_end] = sorted_vals[nulls:]
        sparse_col_idx[compacted_start:compacted_end] = sorted_col_idx[nulls:]
        nulls_counter += nulls
        sparse_row_ptr[i] -= nulls_counter
        # print()
        # print(sorted_vals)
        # print(sparse_col_idx)
        # print(sparse_row_ptr)
    if nulls > 0:
        sparse_val = sparse_val[:-nulls_counter]
        sparse_col_idx = sparse_col_idx[:-nulls_counter]

    # return sparse_val, sparse_col_idx, sparse_row_ptr, b, mid_to_total_indexes, sparse_val_dirty, sparse_col_idx_dirty, sparse_row_ptr_dirty
    return sparse_val, sparse_col_idx, sparse_row_ptr, b, mid_to_total_indexes


def get_flow_rate(pn_pores, pn_throats):
    inlet_flow_total = np.float64(0.0)
    outlet_flow_total = np.float64(0.0)
    inlets = pn_pores["pore.inlets"]
    outlets = pn_pores["pore.outlets"]
    border_pore = np.logical_or(inlets, outlets)

    flow = np.zeros(pn_throats["throat.all"].size, dtype=np.float64)
    delta_p = np.zeros(pn_throats["throat.all"].size, dtype=np.float64)
    inlet_flow = np.zeros(pn_throats["throat.all"].size, dtype=np.float64)
    outlet_flow = np.zeros(pn_throats["throat.all"].size, dtype=np.float64)
    for throat in range(pn_throats["throat.all"].size):
        p0 = pn_throats["throat.conns_0"][throat]
        p1 = pn_throats["throat.conns_1"][throat]
        c = pn_throats["throat.sub_conductivity"][throat]
        delta_p[throat] = np.abs(p0 - p1)
        flow[throat] = delta_p[throat] * c
    pn_throats["throat.flow"] = flow
    pn_throats["throat.delta_p"] = delta_p

    border_pore = np.logical_or(inlets, outlets)
    for throat in range(pn_throats["throat.all"].size):
        p0 = pn_throats["throat.conns_0"][throat]
        p1 = pn_throats["throat.conns_1"][throat]
        c = pn_throats["throat.sub_conductivity"][throat]
        if inlets[p0] and (not border_pore[p1]):
            inlet_flow_total += c * (np.float64(101325.0) - pn_pores["pore.pressure"][p1])
            inlet_flow[throat] = c * (np.float64(101325.0) - pn_pores["pore.pressure"][p1])
        if inlets[p1] and (not border_pore[p0]):
            inlet_flow_total += c * (np.float64(101325.0) - pn_pores["pore.pressure"][p0])
            inlet_flow[throat] = c * (np.float64(101325.0) - pn_pores["pore.pressure"][p0])
        if outlets[p0] and (not border_pore[p1]):
            outlet_flow_total += c * (pn_pores["pore.pressure"][p1])
            outlet_flow[throat] = c * (pn_pores["pore.pressure"][p1])
        if outlets[p1] and (not border_pore[p0]):
            outlet_flow_total += c * (pn_pores["pore.pressure"][p0])
            outlet_flow[throat] = c * (pn_pores["pore.pressure"][p0])

    pn_throats["throat.outlet_flow"] = outlet_flow
    pn_throats["throat.inlet_flow"] = inlet_flow
    pn_throats["throat.flow"] = flow

    flow_rate = (outlet_flow_total + inlet_flow_total) / 2
    return flow_rate


##### Temporary, delete later and import module


@njit
def _solve_cg(
    A_val,
    A_col_idx,
    A_row_ptr,
    b,
    max_iterations,  # sqrt(n) for n x n system
    target_error,  # 1.0e-6
    X0,
    threads,
):
    # Reference: https://repository.lsu.edu/cgi/viewcontent.cgi?article=1254&context=honors_etd

    x = X0.copy()
    r = b.copy()
    m = np.empty(1, dtype=np.float64)
    m[0] = _square_sum_vector(r, threads)  # f(x:vector) = x'*x
    m_last = np.empty(1, dtype=np.float64)
    p = r.copy()
    alpha = np.empty(1, dtype=np.float64)
    beta = np.empty(1, dtype=np.float64)
    iteration = 0
    for _ in range(max_iterations):
        iteration += 1
        alpha[0] = m[0] / _scalar_product(
            p,
            A_val,
            A_col_idx,
            A_row_ptr,
            threads,
        )  # scalar_product = p'*A*p
        _add_product(x, alpha[0], p, threads)  # f(x: vector, y: scalar, z:vector): x += y * z
        # _subtract_product_of_product(
        #    r,
        #    alpha[0],
        #    A_val,
        #    A_col_idx,
        #    A_row_ptr,
        #    p,
        #    threads,
        # ) # f(x:vector, y:scalar, z:array, k:vector): x -= y * z * k
        r[:] = _recalc_residuals_jit(A_val, A_col_idx, A_row_ptr, b, x)
        m_last[0] = m[0]
        m[0] = _square_sum_vector(r, threads)
        beta[0] = m[0] / m_last[0]
        _multiply_and_add(
            p,
            r,
            beta[0],
            threads,
        )  # f(x:vector, y:vector, z:scalar): x = y + z * x
        error = np.sqrt(_square_sum_vector(r, threads) / _square_sum_vector(b, threads))
        if error <= target_error:
            return x, error, iteration

    return x, error, iteration


@njit(parallel=True)
def _square_sum_vector(v, threads):
    # f(v:vector) = v'*v
    partial_sum = np.zeros(threads, dtype=np.float64)
    n = v.size

    for w in prange(threads):
        thread_start = w * n // threads
        thread_end = (w + 1) * n // threads
        for i in range(thread_start, thread_end):
            partial_sum[w] += v[i] ** 2
    return partial_sum.sum()


@njit(parallel=True)
def _scalar_product(
    v,
    A_val,
    A_col_idx,
    A_row_ptr,
    threads,
):
    # f(v: vector[n], A:array[n, n]) = x'*A*x
    partial_sum = np.zeros(threads, dtype=np.float64)
    n = v.size

    for w in prange(threads):
        thread_start = w * n // threads
        thread_end = (w + 1) * n // threads
        for i in range(thread_start, thread_end):
            A_start = A_row_ptr[i]
            if (i + 1) < n:
                A_stop = A_row_ptr[i + 1]
            else:
                A_stop = A_val.size
            for A_linear_index in range(A_start, A_stop):
                j = A_col_idx[A_linear_index]
                partial_sum[w] += v[i] * A_val[A_linear_index] * v[j]
    return partial_sum.sum()


@njit(parallel=True)
def _add_product(v, x, u, threads):
    # f(v: vector, x: scalar, u:vector): v += x * u
    n = v.size

    for w in prange(threads):
        thread_start = w * n // threads
        thread_end = (w + 1) * n // threads
        for i in range(thread_start, thread_end):
            v[i] += x * u[i]


@njit(parallel=True)
def _recalc_residuals_jit(r, val, col_idx, row_ptr, condensed_b, X):
    # residuals = np.zeros(condensed_b.size, dtype=np.float64)
    r[:] = condensed_b

    for row in range(row_ptr.size):
        start = row_ptr[row]
        if row < (row_ptr.size - 1):
            stop = row_ptr[row + 1]
        else:
            stop = val.size

        for index in range(start, stop):
            v = val[index]
            column = col_idx[index]
            r[row] -= v * X[column]


@njit(parallel=True)
def _subtract_product_of_product(
    v,
    x,
    A_val,
    A_col_idx,
    A_row_ptr,
    u,
    threads,
):
    # f(v:vector, x:scalar, A:array, u:vector): v -= x * A * u
    n = v.size

    for w in prange(threads):
        thread_start = w * n // threads
        thread_end = (w + 1) * n // threads
        for i in range(thread_start, thread_end):
            A_start = A_row_ptr[i]
            if (i + 1) < n:
                A_stop = A_row_ptr[i + 1]
            else:
                A_stop = A_val.size
            for A_linear_index in range(A_start, A_stop):
                j = A_col_idx[A_linear_index]
                v[i] -= x * A_val[A_linear_index] * u[j]


@njit(parallel=True)
def _multiply_and_add(
    v,
    u,
    x,
    threads,
):
    # f(v:vector, u:vector, x:scalar): v = u + x * v
    n = v.size

    for w in prange(threads):
        thread_start = w * n // threads
        thread_end = (w + 1) * n // threads
        for i in range(thread_start, thread_end):
            v[i] = u[i] + x * v[i]


@njit
def _get_diagonal_preconditioner(
    A_val,
    A_col_idx,
    A_row_ptr,
    threads,
):  # f(v, A): v = A*v
    diagonal_n = A_row_ptr.size
    P_val = np.empty(diagonal_n, dtype=np.float64)
    P_col_idx = np.arange(diagonal_n, dtype=np.int32)
    P_row_ptr = np.arange(diagonal_n, dtype=np.int32)
    for row in range(diagonal_n):
        start = A_row_ptr[row]
        if row < (A_row_ptr.size - 1):
            stop = A_row_ptr[row + 1]
        else:
            stop = A_val.size

        for linear_index in range(start, stop):
            column = A_col_idx[linear_index]
            if column == row:
                v = A_val[linear_index]
                P_val[row] = 1 / v
    return P_val, P_col_idx, P_row_ptr


@njit
def _solve_pcg(
    A_val,
    A_col_idx,
    A_row_ptr,
    P_val,
    P_col_idx,
    P_row_ptr,
    b,
    max_iterations,  # sqrt(n) for n x n system
    target_error,  # 1.0e-6
    X0,
    threads,
):
    # Reference: https://repository.lsu.edu/cgi/viewcontent.cgi?article=1254&context=honors_etd

    x = X0.copy()
    r = b.copy()
    m = np.empty(1, dtype=np.float64)
    m[0] = _scalar_product(
        r,
        P_val,
        P_col_idx,
        P_row_ptr,
        threads,
    )  # scalar_product = p'*A*p
    m_last = np.empty(1, dtype=np.float64)
    p = r.copy()
    p[:] = _vector_array_multiply(
        p,
        P_val,
        P_col_idx,
        P_row_ptr,
        threads,
    )  # f(v, A): v = A*v
    alpha = np.empty(1, dtype=np.float64)
    beta = np.empty(1, dtype=np.float64)
    iteration = 0
    for _ in range(max_iterations):
        iteration += 1
        alpha[0] = m[0] / _scalar_product(
            p,
            A_val,
            A_col_idx,
            A_row_ptr,
            threads,
        )  # scalar_product = p'*A*p
        _add_product(x, alpha[0], p, threads)  # f(x: vector, y: scalar, z:vector): x += y * z
        _recalc_residuals_jit(r, A_val, A_col_idx, A_row_ptr, b, x)
        m_last[0] = m[0]
        m[0] = _scalar_product(
            r,
            P_val,
            P_col_idx,
            P_row_ptr,
            threads,
        )  # scalar_product = p'*A*p
        beta[0] = m[0] / m_last[0]
        p[:] = _multiply_array_and_add(
            p,
            r,
            beta[0],
            P_val,
            P_col_idx,
            P_row_ptr,
            threads,
        )  # f(x:vector, y:vector, z:scalar, A:array): x = A * y + z * x
        error = np.sqrt(_square_sum_vector(r, threads) / _square_sum_vector(b, threads))
        if error <= target_error:
            return x, error, iteration

    return x, error, iteration


@njit  #
def _vector_array_multiply(
    p,
    val,
    col_idx,
    row_ptr,
    threads,
):  # f(v, A): v = A*v
    new_p = np.zeros_like(p)
    for row in range(row_ptr.size):
        start = row_ptr[row]
        if row < (row_ptr.size - 1):
            stop = row_ptr[row + 1]
        else:
            stop = val.size

        for index in range(start, stop):
            v = val[index]
            column = col_idx[index]
            new_p[row] += v * p[column]
    return new_p


@njit(parallel=True)
def _multiply_array_and_add(
    u,
    v,
    x,
    val,
    col_idx,
    row_ptr,
    threads,
):  # f(u:vector, v:vector, x:scalar, A:array): x = A * v + x * u
    new_p = _vector_array_multiply(
        v,
        val,
        col_idx,
        row_ptr,
        threads,
    )
    new_p += x * u
    return new_p
