import logging
import os
import re
from typing import Optional

import numpy as np
import pandas as pd
import slicer
import vtk
from numba import njit, prange

from ltrace.slicer.data_utils import dataFrameToTableNode
from porespy.networks import regions_to_network_parallel, snow2
from porespy.tools import make_contiguous

DEFAULT_SHAPE_FACTOR = 1.0


"""
Three Pore network description formats:
spy: PoreSpy format (dict of 1D and 2D np arrays)
pne: PNExtractor format (four csv strings)
geo: GeoSlicer format (two MRML tables, one column for each property)
pnf: PNFlow format (four ascii tables), pore and throat indexes start 
    at 1 (pores with index -1 and 0 represent inlet and outlet, 
    repsectivelly). This is equivalent to the statoil format
vtu: VTK Unstructured Grid, in this context especifically .vtu files 
    created by PNFlow.
"""


def geo2spy(pore_dict, throat_dict):
    """
    Takes a Table Node with pore_table type attribute and returns a dictionary
    describing the pore network using the PoreSpy format.
    """
    # remove edge throats from PNExtract
    edge_throats = list(range(len(throat_dict["throat.all"])))
    for i in range(len(throat_dict["throat.all"])):
        if (throat_dict["throat.conns_0"][i] <= -1) or (throat_dict["throat.conns_1"][i] <= -1):
            edge_throats.remove(i)
    for column in throat_dict:
        throat_dict[column] = throat_dict[column][edge_throats]

    geo = {}
    geo.update(pore_dict)
    geo.update(throat_dict)

    spy = {}
    vector_keys = {}
    scalar_keys = []

    for key in geo.keys():
        match = re.search(r"(.+)_(\d+)$", key)
        if match:
            base = match.group(1)
            idx = int(match.group(2))
            if base not in vector_keys:
                vector_keys[base] = []
            vector_keys[base].append(idx)
        else:
            scalar_keys.append(key)

    for base, indices in vector_keys.items():
        indices.sort()
        if indices == list(range(len(indices))):
            spy[base] = np.stack([geo[f"{base}_{i}"] for i in indices], axis=1)
        else:
            for i in indices:
                spy[f"{base}_{i}"] = geo[f"{base}_{i}"]

    for key in scalar_keys:
        if key in vector_keys and vector_keys[key] == list(range(len(vector_keys[key]))):
            continue
        spy[key] = geo[key]

    spy["pore.phase1"] = spy["pore.phase"] == 1
    spy["pore.phase2"] = spy["pore.phase"] == 2
    return spy


def geo2pnf(
    pore_dict,
    throat_dict,
    subresolution_function,
    extraction_algorithm,
    size,
    edge_throats="none",
    scale_factor=10**-3,
    axis="x",
    subres_shape_factor=0.071,
    subres_porosity_modifier=1.0,
    save_tables=False,
):
    """
    Returns a dictionary with four strings ("link1", "link2", "node1", "node2") representing the four files in the statoil format
    """
    # Local import here to prevent circular dependency
    from ltrace.pore_networks.functions_simulation import manual_valvatne_blunt, set_subresolution_conductance

    spy_network = geo2spy(pore_dict, throat_dict)
    manual_valvatne_blunt(spy_network)

    if (spy_network["pore.phase"] == 2).any():
        set_subresolution_conductance(
            spy_network,
            subresolution_function,
            subres_porositymodifier=subres_porosity_modifier,
            subres_shape_factor=subres_shape_factor,
            save_tables=save_tables,
        )
    spy2geo(spy_network)
    pore_dict = {i: spy_network[i] for i in spy_network.keys() if ("pore." in i)}
    throat_dict = {i: spy_network[i] for i in spy_network.keys() if ("throat." in i)}

    if extraction_algorithm == "porespy":
        # Correction necessary since porespy counts element volume twice (once for pore and once for throat)
        # While PNE/PNF counts each volume once, either for pore or throat
        volume_multiplier = 0.5
    else:
        volume_multiplier = 1

    connected_pores, connected_throats = get_connected_geo_network(pore_dict, throat_dict, f"{axis}min", f"{axis}max")
    if not any(connected_pores) or not any(connected_throats):
        logging.warning("The network is invalid. Does not percolate.")
        return None
    pore_dict, throat_dict = get_sub_geo(pore_dict, throat_dict, connected_pores, connected_throats)

    pores_with_edge_throats = set()
    n_pores = len(pore_dict["pore.all"])
    n_throats = len(throat_dict["throat.all"])
    pores_conns_pores = [[] for _ in range(n_pores)]
    pores_conns_throats = [[] for _ in range(n_pores)]
    # Connections are used to fill node1 item 6 parameters later
    for i in range(n_throats):
        left_pore = throat_dict["throat.conns_0"][i]
        right_pore = throat_dict["throat.conns_1"][i]
        for start_pore, end_pore in ((left_pore, right_pore), (right_pore, left_pore)):
            if start_pore >= 0:
                if end_pore >= 0:
                    pores_conns_pores[start_pore].append(end_pore)
                    pores_conns_throats[start_pore].append(i)
                elif axis == edge_throats:
                    pores_conns_pores[start_pore].append(end_pore)
                    pores_conns_throats[start_pore].append(i)
                    pores_with_edge_throats.add(start_pore)

    pnf = {"link1": [""], "link2": [], "link3": []}

    if "throat.perimeter" in throat_dict.keys():
        min_perimeter = throat_dict["throat.perimeter"][throat_dict["throat.perimeter"] > 0].min()

    for i in range(n_throats):
        # link1 items
        left_pore = throat_dict["throat.conns_0"][i]
        right_pore = throat_dict["throat.conns_1"][i]

        radius = "{:E}".format(scale_factor * throat_dict["throat.inscribed_diameter"][i] / 2)

        if "throat.shape_factor" in throat_dict.keys():
            shape_factor = "{:E}".format(throat_dict["throat.shape_factor"][i])
        else:
            cross_area = throat_dict["throat.cross_sectional_area"][i]
            perimeter = throat_dict["throat.perimeter"][i]
            if perimeter < min_perimeter:
                perimeter = min_perimeter
            eq_circle_area = perimeter**2 / (4 * np.pi)
            unformatted_shape_factor = cross_area / eq_circle_area
            if unformatted_shape_factor > 1:
                unformatted_shape_factor = 1
            shape_factor = "{:E}".format(unformatted_shape_factor)
        length = "{:E}".format(scale_factor * throat_dict["throat.direct_length"][i])

        # link2 items
        if "throat.conns_0_length" in throat_dict.keys():
            left_pore_length = "{:E}".format(scale_factor * throat_dict["throat.conns_0_length"][i])
            right_pore_length = "{:E}".format(scale_factor * throat_dict["throat.conns_1_length"][i])
        else:
            left_pore_length = "{:E}".format(scale_factor * pore_dict["pore.extended_diameter"][left_pore - 1])
            right_pore_length = "{:E}".format(scale_factor * pore_dict["pore.extended_diameter"][right_pore - 1])

        if "throat.mid_length" in throat_dict.keys():
            mid_length = "{:E}".format(scale_factor * throat_dict["throat.mid_length"][i])
        else:
            mid_length = "{:E}".format(float(length) - float(left_pore_length) - float(right_pore_length))

        if "throat.volume" in throat_dict.keys():
            volume = "{:E}".format(scale_factor**3 * throat_dict["throat.volume"][i] * volume_multiplier)
        else:
            volume = "{:E}".format(
                scale_factor**3
                * throat_dict["throat.direct_length"][i]
                * throat_dict["throat.cross_sectional_area"][i]
                * volume_multiplier
            )

        if not throat_dict.get("throat.clay", None):
            clay = "0"
        else:
            clay = "{:E}".format(throat_dict["throat.clay"][i])

        # modify values for darcy pores
        left_is_darcy = throat_dict["throat.phases_0"][i] == 2
        right_is_darcy = throat_dict["throat.phases_1"][i] == 2
        throat_is_darcy = left_is_darcy or right_is_darcy
        if throat_is_darcy:
            N = "{:E}".format(throat_dict["throat.number_of_capilaries"][i])
            radius = "{:E}".format(scale_factor * throat_dict["throat.cap_radius"][i])
            shape_factor = "{:E}".format(subres_shape_factor)

            mid_length = scale_factor * throat_dict["throat.mid_length"][i]

            if left_is_darcy:
                left_pore_length = scale_factor * throat_dict["throat.conns_0_length"][i]
            else:
                left_pore_length = scale_factor * throat_dict["throat.conns_0_length"][i]

            if right_is_darcy:
                right_pore_length = scale_factor * throat_dict["throat.conns_1_length"][i]
            else:
                right_pore_length = scale_factor * throat_dict["throat.conns_1_length"][i]

            length = left_pore_length + right_pore_length + mid_length
        else:  # pore is not Darcy
            N = "{:E}".format(1.0)

        # write results
        pnf["link1"].append(f"{i+1} {left_pore+1} {right_pore+1} {radius} {shape_factor} {length}")
        pnf["link2"].append(
            f"{i+1} {left_pore+1} {right_pore+1} {left_pore_length} {right_pore_length} {mid_length} {volume} {clay}"
        )
        pnf["link3"].append(f"{i+1} {left_pore+1} {right_pore+1} {N}")

    # adds mock throats to define inlets and outlets
    for i in range(n_pores):
        if i in pores_with_edge_throats:
            continue
        if pore_dict[f"pore.{axis}min"][i]:
            target_pore = -1
        elif pore_dict[f"pore.{axis}max"][i]:
            target_pore = -2
        else:
            continue
        pores_conns_pores[i].append(target_pore)
        pores_conns_throats[i].append(n_throats)
        shape_factor = "{:E}".format(subres_shape_factor)  # Similar to PNE behavior
        if "pore.extended_diameter" in pore_dict.keys():
            radius = "{:E}".format(scale_factor * pore_dict["pore.extended_diameter"][i] / 2)
            length = "{:E}".format(scale_factor * pore_dict["pore.extended_diameter"][i] / 2)
        else:
            radius = "{:E}".format(scale_factor * pore_dict["pore.radius"][i])
            length = "{:E}".format(scale_factor * pore_dict["pore.radius"][i])
        volume = "{:E}".format(scale_factor**3 * pore_dict["pore.volume"][i] * volume_multiplier)

        pnf["link1"].append(f"{n_throats+1} {i+1} {target_pore+1} {radius} {shape_factor} {length}")
        pnf["link2"].append(f"{n_throats+1} {i+1} {target_pore+1} {length} {0} {0} {volume} {0}")
        n_throats += 1

    pnf["link1"][0] = f"{n_throats}"

    x = size["x"] * scale_factor
    y = size["y"] * scale_factor
    z = size["z"] * scale_factor

    pnf["node1"] = [f"{n_pores} {x} {y} {z}"]
    pnf["node2"] = []
    pnf["node3"] = []
    for i in range(n_pores):
        input_x = pore_dict["pore.coords_0"][i] * scale_factor
        input_y = pore_dict["pore.coords_1"][i] * scale_factor
        input_z = pore_dict["pore.coords_2"][i] * scale_factor
        p_z, p_y, p_x = input_x, input_y, input_z
        coordinate_number = len(pores_conns_pores[i])
        is_inlet = int(pore_dict[f"pore.{axis}max"][i])
        is_outlet = int(pore_dict[f"pore.{axis}min"][i])
        connected_pores = " ".join((str(j + 1) for j in pores_conns_pores[i]))
        connected_throats = " ".join((str(j + 1) for j in pores_conns_throats[i]))
        if "pore.extended_diameter" in pore_dict.keys():
            radius = "{:E}".format(scale_factor * pore_dict["pore.extended_diameter"][i] / 2)
        else:
            radius = "{:E}".format(scale_factor * pore_dict["pore.radius"][i])
        volume = "{:E}".format(scale_factor**3 * pore_dict["pore.volume"][i] * volume_multiplier)
        area = scale_factor**2 * pore_dict["pore.surface_area"][i]

        if "pore.shape_factor" in pore_dict.keys():
            shape_factor = pore_dict["pore.shape_factor"][i]
        elif area > 0:
            eq_volume = (1 / (6 * np.sqrt(np.pi))) * (area) ** (3 / 2)
            shape_factor = "{:E}".format(float(volume) / eq_volume)
        else:
            shape_factor = DEFAULT_SHAPE_FACTOR

        if not throat_dict.get("pore.clay", None):
            clay = 0
        else:
            clay = "{:E}".format(throat_dict["pore.clay"][i])

        # adjustments for darcy pores
        if pore_dict["pore.phase"][i] == 2:
            radius = "{:E}".format(scale_factor * pore_dict["pore.cap_radius"][i])
            shape_factor = "{:E}".format(subres_shape_factor)
            N = "{:E}".format(pore_dict["pore.number_of_capilaries"][i])
        else:
            N = "{:E}".format(1.0)

        pnf["node1"].append(
            f"{i+1} {p_x} {p_y} {p_z} {coordinate_number} {connected_pores} {is_inlet} {is_outlet} {connected_throats}"
        )
        pnf["node2"].append(f"{i+1} {volume} {radius} {shape_factor} {clay}")

        pnf["node3"].append(f"{i+1} {N}")

    return pnf


def get_connected_geo_network(pore_dict, throat_dict, in_face, out_face):
    """
    in_face, out_face: str
        Each must be one of 'xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax'
    return:
        two bool arrays for pores and throats connected to both faces
    """
    from scipy.sparse import csgraph as csg
    import scipy.sparse as sprs

    valid_inputs = ["xmin", "xmax", "ymin", "ymax", "zmin", "zmax"]
    if in_face not in valid_inputs:
        raise ValueError(f"Face values is invalid: in_face = {in_face}")
    if out_face not in valid_inputs:
        raise ValueError(f"Face values is invalid: out_face = {out_face}")

    n_throats = throat_dict["throat.all"].size
    n_pores = pore_dict["pore.all"].size
    weights = np.ones((2 * n_throats,), dtype=int)

    conn_0 = [max(0, i) for i in throat_dict["throat.conns_0"]]
    conn_1 = [max(0, i) for i in throat_dict["throat.conns_1"]]
    row = conn_0
    col = conn_1
    row = np.append(row, conn_1)
    col = np.append(col, conn_0)

    adjacency_network = sprs.coo_matrix((weights, (row, col)), (n_pores, n_pores))
    _, cluster_labels = csg.connected_components(adjacency_network, directed=False)

    in_labels = np.unique(cluster_labels[pore_dict[f"pore.{in_face}"]])
    out_labels = np.unique(cluster_labels[pore_dict[f"pore.{out_face}"]])
    common_labels = np.intersect1d(in_labels, out_labels, assume_unique=True)

    connected_pores = np.isin(cluster_labels, common_labels)
    throat_connected_0 = connected_pores[throat_dict["throat.conns_0"]]
    throat_connected_1 = connected_pores[throat_dict["throat.conns_1"]]
    connected_throats = np.logical_or(throat_connected_0, throat_connected_1)
    return connected_pores, connected_throats


def get_sub_geo(pore_dict, throat_dict, sub_pores, sub_throats):
    def _counter():
        i = -1
        while True:
            i += 1
            yield i

    sub_pore_dict = {}
    sub_throat_dict = {}
    for prop in pore_dict.keys():
        sub_pore_dict[prop] = pore_dict[prop][sub_pores]
    for prop in throat_dict.keys():
        sub_throat_dict[prop] = throat_dict[prop][sub_throats]

    counter = _counter()
    f_counter = lambda x: next(counter) if x else 0
    new_pore_index = np.fromiter(map(f_counter, sub_pores), dtype="int")

    for i in np.nditer(sub_throat_dict["throat.conns_0"], op_flags=["readwrite"]):
        if i > 0:
            i[...] = new_pore_index[i]

    for i in np.nditer(sub_throat_dict["throat.conns_1"], op_flags=["readwrite"]):
        if i > 0:
            i[...] = new_pore_index[i]
    return sub_pore_dict, sub_throat_dict


def get_clusters(network):
    """
    clusters are numbered starting at 0
    """
    from scipy.sparse import csgraph as csg

    am = network.create_adjacency_matrix(fmt="coo", triu=True)
    N, Cs = csg.connected_components(am, directed=False)
    return N, Cs


def get_sub_spy(spy_network, sub_pores, sub_throats):
    def _counter():
        i = -1
        while True:
            i += 1
            yield i

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


def get_connected_spy_network(network, in_face, out_face, coord_limits=None):
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
    if coord_limits:
        pore_coords = network["pore.coords"][connected_pores]
        mask = np.ones(len(connected_pores), dtype=bool)
        for axis, (low, high) in coord_limits.items():
            axis_idx = "xyz".index(axis)
            mask &= (pore_coords[:, axis_idx] >= low) & (pore_coords[:, axis_idx] <= high)

        connected_pores = connected_pores[mask]

    return np.isin(cluster_labels, common_labels), np.isin(network["throat.conns"], connected_pores).all(axis=1)


def spy2geo(pn_properties):
    properties_keys_to_delete = []
    properties_pairs_to_add = {}
    for name, array in pn_properties.items():
        if array.ndim == 1:
            continue
        for i in range(array.shape[1]):
            properties_pairs_to_add[f"{name}_{i}"] = array[:, i]
        properties_keys_to_delete.append(name)
    for prop in properties_keys_to_delete:
        del pn_properties[prop]
    pn_properties.update(properties_pairs_to_add)


def _porespy_postprocessing(pn_properties, watershed_image, scale, porosity_map=None):
    # Extracts PNM with porespy and "flattens" the data into a dict of 1d arrays
    porosity = pn_properties["pore.subresolution_porosity"]
    pn_properties["pore.subresolution_porosity"][porosity == 0] = porosity[porosity > 0].min()
    # spy2geo
    spy2geo(pn_properties)
    # Include additional properties
    pn_properties["pore.radius"] = pn_properties["pore.extended_diameter"] / 2

    pn_properties["throat.shape_factor"] = np.clip(
        (pn_properties["throat.inscribed_diameter"] / 2) ** 2 / (4 * pn_properties["throat.cross_sectional_area"]),
        0.01,
        0.09,
    )
    pn_properties["throat.conns_0_length"] = (
        pn_properties["pore.extended_diameter"][pn_properties["throat.conns_0"]] / 2
    )
    pn_properties["throat.conns_1_length"] = (
        pn_properties["pore.extended_diameter"][pn_properties["throat.conns_1"]] / 2
    )
    pn_properties["throat.mid_length"] = (
        pn_properties["throat.total_length"]
        - pn_properties["throat.conns_0_length"]
        - pn_properties["throat.conns_1_length"]
    )

    pn_properties["throat.mid_length"] = np.where(
        pn_properties["throat.mid_length"] < pn_properties["throat.total_length"] * 0.01,
        pn_properties["throat.total_length"] * 0.01,
        pn_properties["throat.mid_length"],
    )
    pn_properties["throat.volume"] = pn_properties["throat.total_length"] * pn_properties["throat.cross_sectional_area"]

    pn_properties["pore.shape_factor"] = np.zeros((len(pn_properties["pore.all"]),))
    conns_total_area = np.zeros((len(pn_properties["pore.all"]),))

    for throat in range(len(pn_properties["throat.all"])):
        conn_0 = pn_properties["throat.conns_0"][throat]
        conn_1 = pn_properties["throat.conns_1"][throat]
        pn_properties["pore.shape_factor"][conn_0] += (
            pn_properties["throat.shape_factor"][throat] * pn_properties["throat.cross_sectional_area"][throat]
        )
        pn_properties["pore.shape_factor"][conn_1] += (
            pn_properties["throat.shape_factor"][throat] * pn_properties["throat.cross_sectional_area"][throat]
        )
        conns_total_area[conn_0] += pn_properties["throat.cross_sectional_area"][throat]
        conns_total_area[conn_1] += pn_properties["throat.cross_sectional_area"][throat]
    conns_total_area = np.where(conns_total_area > 0, conns_total_area, 1)
    pn_properties["pore.shape_factor"] /= conns_total_area

    # Swap Z and X axis and displace by origin:
    for coord_name in (
        "pore.coords_",
        "pore.local_peak_",
        "pore.global_peak_",
        "pore.geometric_centroid_",
    ):
        temp_coord = pn_properties[f"{coord_name}0"]
        pn_properties[f"{coord_name}0"] = pn_properties[f"{coord_name}2"]
        pn_properties[f"{coord_name}2"] = temp_coord
    del temp_coord

    labels = pn_properties["pore.region_label"]
    edge_labels = {}
    edge_labels["all"] = []
    # fmt: off
    for face, face_slice in (
            ("pore.xmax", (slice(0, 1), slice(None), slice(None))),
            ("pore.xmin", (slice(-1, None), slice(None), slice(None))),
            ("pore.ymax", (slice(None), slice(0, 1), slice(None))),
            ("pore.ymin", (slice(None), slice(-1, None), slice(None))),
            ("pore.zmax", (slice(None), slice(None), slice(0, 1))),
            ("pore.zmin", (slice(None), slice(None), slice(-1, None))),
            ):
    # fmt: on
        edge_labels[face] = np.unique(watershed_image[face_slice])
        if edge_labels[face][0] == 0:
            edge_labels[face] = edge_labels[face][1:]
        if 0 in edge_labels[face]:
            raise Exception  # should be impossible, but expensive to guarantee
        edge_labels["all"] = np.unique(np.append(edge_labels["all"], edge_labels[face]))
        pn_properties[face] = np.isin(labels, edge_labels[face])

    max_coords = [(i * scale[watershed_image.ndim-1-coord]) for coord,i in enumerate(watershed_image.shape[-1::-1])]
    # fmt: off
    for labels_list, coord_axis, new_position in (
            (edge_labels["pore.xmax"], 2, 0),
            (edge_labels["pore.xmin"], 2, max_coords[2]),
            (edge_labels["pore.ymax"], 1, 0),
            (edge_labels["pore.ymin"], 1, max_coords[1]),
            (edge_labels["pore.zmax"], 0, 0),
            (edge_labels["pore.zmin"], 0, max_coords[0]),
            ):
        for label in labels_list:
            if label == 0:
                continue
            pn_properties[f"pore.coords_{coord_axis}"][label - 1] = new_position
    # fmt: on
    for throat in range(len(pn_properties["throat.all"])):
        pore0 = pn_properties["throat.conns_0"][throat]
        pore1 = pn_properties["throat.conns_1"][throat]
        total_distance = np.sqrt(
            (pn_properties["pore.coords_0"][pore0] - pn_properties["pore.coords_0"][pore1]) ** 2
            + (pn_properties["pore.coords_1"][pore0] - pn_properties["pore.coords_1"][pore1]) ** 2
            + (pn_properties["pore.coords_2"][pore0] - pn_properties["pore.coords_2"][pore1]) ** 2
        )
        distance_ratio = total_distance / pn_properties["throat.direct_length"][throat]
        pn_properties["throat.direct_length"][throat] = total_distance
        pn_properties["throat.total_length"][throat] *= distance_ratio
        pn_properties["throat.mid_length"][throat] = (
            total_distance
            - pn_properties["throat.conns_0_length"][throat]
            - pn_properties["throat.conns_1_length"][throat]
        )
    pn_properties["throat.mid_length"] = np.where(
        pn_properties["throat.mid_length"] < pn_properties["throat.total_length"] * 0.01,
        pn_properties["throat.total_length"] * 0.01,
        pn_properties["throat.mid_length"],
    )
    pn_properties["pore.effective_volume"] = pn_properties["pore.volume"] * pn_properties["pore.subresolution_porosity"]

    try:
        pore_subresolution_porosity = pn_properties["pore.subresolution_porosity"]
    except KeyError:
        print(
            "The key pore.subresolution_porosity is not available from porespy, check the version of the porespy module."
        )

    # TODO (PL-2213): Create an option at interface to select random subresolution porosity instead of getting from network
    # rng = np.random.default_rng()
    # pore_subresolution_porosity = rng.random((pn_properties["pore.all"]).size)

    throat_phi = np.ones_like(pn_properties["throat.all"], dtype=np.float64)
    for throat_index in range(len(pn_properties["throat.all"])):
        left_index = pn_properties["throat.conns_0"][throat_index]
        right_index = pn_properties["throat.conns_1"][throat_index]

        left_unresolved = pn_properties["throat.phases_0"][throat_index] == 2
        right_unresolved = pn_properties["throat.phases_1"][throat_index] == 2

        if right_unresolved and left_unresolved:
            throat_phi[throat_index] = (
                pore_subresolution_porosity[left_index] * pn_properties["throat.conns_0_length"][throat_index]
                + pore_subresolution_porosity[right_index] * pn_properties["throat.conns_1_length"][throat_index]
            ) / (
                pn_properties["throat.conns_0_length"][throat_index]
                + pn_properties["throat.conns_1_length"][throat_index]
            )

        elif left_unresolved and not right_unresolved:
            throat_phi[throat_index] = pore_subresolution_porosity[left_index]

        elif right_unresolved and not left_unresolved:
            throat_phi[throat_index] = pore_subresolution_porosity[right_index]

    pn_properties["throat.subresolution_porosity"] = throat_phi

    ### Volume properties
    if porosity_map is not None:
        input_volume_porosity = (porosity_map.sum() / porosity_map.size) / 100
        input_resolved_porosity = (porosity_map[porosity_map == 100].sum() / porosity_map.size) / 100
        input_subscale_porosity = (((0 < porosity_map) & (porosity_map < 100)) * porosity_map).sum() / (
            porosity_map.size * 100
        )
    else:
        input_volume_porosity = (watershed_image > 0).sum() / watershed_image.size
        input_resolved_porosity = input_volume_porosity
        input_subscale_porosity = 0.0

    voxel_volume = scale[0] * scale[1] * scale[2]
    input_total_volume = watershed_image.size * voxel_volume

    pore_resolved_volume = pn_properties["pore.volume"][pn_properties["pore.phase"] == 1].sum()
    pore_subscale_volume = (
        pn_properties["pore.volume"][pn_properties["pore.phase"] > 1]
        * pn_properties["pore.subresolution_porosity"][pn_properties["pore.phase"] > 1]
    ).sum()
    pore_total_volume = pore_resolved_volume + pore_subscale_volume

    throat_resolved_volume = pn_properties["throat.volume"][pn_properties["throat.phases_0"] == 1].sum()
    throat_resolved_volume += pn_properties["throat.volume"][pn_properties["throat.phases_1"] == 1].sum()
    throat_subscale_volume = (
        pn_properties["throat.volume"][pn_properties["throat.phases_0"] > 1]
        * pn_properties["throat.subresolution_porosity"][pn_properties["throat.phases_0"] > 1]
    ).sum()
    throat_subscale_volume += (
        pn_properties["throat.volume"][pn_properties["throat.phases_1"] > 1]
        * pn_properties["throat.subresolution_porosity"][pn_properties["throat.phases_1"] > 1]
    ).sum()
    throat_total_volume = throat_resolved_volume + throat_subscale_volume

    pn_properties["network.number_of_pores"] = len(pn_properties["pore.all"])
    pn_properties["network.number_of_throats"] = len(pn_properties["throat.all"])

    pn_properties["network.input_volume_porosity"] = 100 * input_volume_porosity
    pn_properties["network.input_resolved_porosity"] = 100 * input_resolved_porosity
    pn_properties["network.input_subscale_porosity"] = 100 * input_subscale_porosity
    pn_properties["network.input_total_volume"] = input_total_volume
    pn_properties["network.voxel_volume"] = voxel_volume

    pn_properties["network.pore_resolved_porosity"] = 100 * pore_resolved_volume / input_total_volume
    pn_properties["network.pore_subscale_porosity"] = 100 * pore_subscale_volume / input_total_volume
    pn_properties["network.pore_total_porosity"] = 100 * pore_total_volume / input_total_volume
    pn_properties["network.pore_resolved_volume"] = pore_resolved_volume
    pn_properties["network.pore_subscale_volume"] = pore_subscale_volume
    pn_properties["network.pore_total_volume"] = pore_total_volume

    pn_properties["network.throat_resolved_porosity"] = 100 * throat_resolved_volume / input_total_volume
    pn_properties["network.throat_subscale_porosity"] = 100 * throat_subscale_volume / input_total_volume
    pn_properties["network.throat_total_porosity"] = 100 * throat_total_volume / input_total_volume
    pn_properties["network.throat_resolved_volume"] = throat_resolved_volume
    pn_properties["network.throat_subscale_volume"] = throat_subscale_volume
    pn_properties["network.throat_total_volume"] = throat_total_volume

    return pn_properties


def general_pn_extract(
    scalar_array: Optional[np.ndarray],
    label_array: Optional[np.ndarray],
    scale: np.ndarray,
    watershed_blur=[0.4, 0.8],
    is_multiscale=False,
    force_cpu=False,
    divs=2,
):
    """
    Creates two table nodes describing the pore-network represented by multiphaseNode or by the watershedNode.

    :param multiphaseNode:
        The node containing the phases of each pixel (Solid, Pore and Subresolution).
    :param watershedNode:
        The node containing the watershed of the image used to separate pores.
    :param method:
        Either "PoreSpy" or "PNExtract".
        PoreSpy mas receive a labeled volume (each pore must have an unique number),
        while PNExtract receives a binary volume (0 for solid, >0 for por space), a labeled
        volume can be obtained by performing a watershed segmentation on a binary image.
        PNExtract is prone to crash with large volumes, and should be available only on
        developer mode.
    :param porosity_map:
        Numpy array with the porosity map (range 0~100).
    :param divs: list or int
        Number of domains each axis will be divided. Options are:
          - scalar: it will be assigned to all axis.
          - list: each respective axis will be divided by its
            corresponding number in the list. For example [2, 3, 4] will
            divide z, y and x axis to 2, 3, and 4 respectively.

    :return:
        Two table nodes describing the pore-network represented by multiphaseNode/watershedNode or False if method if not found or the pore-network
        properties could not be extracted.
    """
    if label_array is not None and np.max(label_array) <= 0:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), label_array.astype(np.int32)

    if (label_array is None) and (is_multiscale is True):
        if type(watershed_blur) is dict:
            keys = list(watershed_blur.keys())
            for key in keys:
                watershed_blur[int(key)] = watershed_blur[key]

        multiphase_array = _phases_from_porosity_map(scalar_array)

        _parallelization = {"divs": divs} if divs > 1 else None
        snow_results = snow2(
            phases=multiphase_array,
            porosity_map=scalar_array,
            voxel_size=scale,
            parallel_extraction=True,
            sigma=watershed_blur,
            force_cpu=force_cpu,
            boundary_width=0,
            parallelization=_parallelization,
        )
        pn_properties = snow_results.network
        watershed_output = snow_results.regions
    elif is_multiscale is True:  # and label_array is not None
        if not is_contiguous(label_array):
            watershed_output = make_contiguous(label_array)
            label_array = watershed_output
        else:
            watershed_output = None
        multiphase_array = _phases_from_porosity_map(scalar_array)

        pn_properties = regions_to_network_parallel(
            regions=label_array,
            phases=multiphase_array,
            porosity_map=scalar_array,
            voxel_size=scale,
            force_cpu=force_cpu,
        )
    else:  # is_multiscale is False and label_array is not None
        if not is_contiguous(label_array):
            watershed_output = make_contiguous(label_array)
            label_array = watershed_output
        else:
            watershed_output = None

        pn_properties = regions_to_network_parallel(
            regions=label_array,
            voxel_size=scale,
            force_cpu=force_cpu,
        )

    if watershed_output is not None:
        watershed_output = watershed_output.astype(np.int32)

    if not pn_properties:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), watershed_output
    if is_multiscale is True and pn_properties["pore.subresolution_porosity"].max() <= 0.01:
        pn_properties["pore.subresolution_porosity"] *= 100
    pn_properties = _porespy_postprocessing(
        pn_properties,
        watershed_image=(watershed_output if (watershed_output is not None) else label_array),
        scale=scale,
        porosity_map=(scalar_array if is_multiscale else None),
    )

    pn_throats = {}
    pn_pores = {}
    pn_network = {}
    for i in pn_properties.keys():
        if "pore." in i:
            pn_pores[i] = pn_properties[i]
        elif "throat." in i:
            pn_throats[i] = pn_properties[i]
        elif "network." in i:
            pn_network[i] = pn_properties[i]

    df_pores = pd.DataFrame(pn_pores)
    df_throats = pd.DataFrame(pn_throats)
    df_network = pd.DataFrame([pn_network])

    return df_pores, df_throats, df_network, watershed_output


@njit(parallel=True)
def _phases_from_porosity_map(porosity_map):
    W, H, D = porosity_map.shape
    phases = np.zeros((W, H, D), dtype=np.uint8)
    if porosity_map.max() > 1:
        porosity_threshold = 100
    else:
        porosity_threshold = 1
    for x in prange(W):
        for y in range(H):
            for z in range(D):
                if porosity_map[x, y, z] >= porosity_threshold:
                    phases[x, y, z] = 1
                elif porosity_map[x, y, z] > 0:
                    phases[x, y, z] = 2

    return phases


@njit
def get_throat_areas_from_labelmap(labelmap, voxel_size):
    areas = {}
    W, H, D = labelmap.shape
    area = voxel_size[1] * voxel_size[2]
    for x in range(1, W):
        for y in range(H):
            for z in range(D):
                left_label = labelmap[x - 1, y, z] - 1
                right_label = labelmap[x, y, z] - 1
                if (left_label == -1) or (right_label == -1) or (left_label == right_label):
                    continue
                if right_label < left_label:
                    right_label = left_label
                    left_label = labelmap[x, y, z] - 1
                key = (left_label, right_label)
                if key not in areas:
                    areas[key] = area
                else:
                    areas[key] += area
    area = voxel_size[0] * voxel_size[2]
    for x in range(W):
        for y in range(1, H):
            for z in range(D):
                left_label = labelmap[x, y - 1, z] - 1
                right_label = labelmap[x, y, z] - 1
                if (left_label == -1) or (right_label == -1) or (left_label == right_label):
                    continue
                if right_label < left_label:
                    right_label = left_label
                    left_label = labelmap[x, y, z] - 1
                key = (left_label, right_label)
                if key not in areas:
                    areas[key] = area
                else:
                    areas[key] += area
    area = voxel_size[0] * voxel_size[1]
    for x in range(W):
        for y in range(H):
            for z in range(1, D):
                left_label = labelmap[x, y, z - 1] - 1
                right_label = labelmap[x, y, z] - 1
                if (left_label == -1) or (right_label == -1) or (left_label == right_label):
                    continue
                if right_label < left_label:
                    right_label = left_label
                    left_label = labelmap[x, y, z] - 1
                key = (left_label, right_label)
                if key not in areas:
                    areas[key] = area
                else:
                    areas[key] += area
    return areas


def is_contiguous(labelmap):
    unique_vals = np.unique(labelmap)
    while len(unique_vals) > 0 and unique_vals[0] <= 0:
        unique_vals = unique_vals[1:]
    if not len(unique_vals):
        return True
    if len(unique_vals) == unique_vals[-1]:
        return True
    elif len(unique_vals) < unique_vals[-1]:
        return False
    else:
        raise Exception


class ExtractionNodesCreator:
    def __init__(self, metadata, cwd, prefix, visualization):
        """
        :param metadata: dict containing 'spacing', 'origin', 'ijktorasmatrix', 'bounds', and 'itemTreeId'
        :param cwd: current working directory (Path object)
        :param prefix: string prefix for node naming
        :param visualization: boolean to trigger 3D model creation
        """
        self.metadata = metadata
        self.cwd = cwd
        self.prefix = prefix
        self.visualization = visualization
        self.results = {}

        self.network_property_map = {
            "network.number_of_pores": "Number of Pores",
            "network.number_of_throats": "Number of Throats",
            "network.input_volume_porosity": "Input Volume Porosity (%)",
            "network.input_resolved_porosity": "Input Resolved Porosity (%)",
            "network.input_subscale_porosity": "Input Subscale Porosity (%)",
            "network.input_total_volume": "Input Total Volume (mm³)",
            "network.voxel_volume": "Voxel Volume (mm³)",
            "network.pore_resolved_porosity": "Pore Resolved Porosity (%)",
            "network.pore_subscale_porosity": "Pore Subscale Porosity (%)",
            "network.pore_total_porosity": "Pore Total Porosity (%)",
            "network.pore_resolved_volume": "Pore Resolved Volume (mm³)",
            "network.pore_subscale_volume": "Pore Subscale Volume (mm³)",
            "network.pore_total_volume": "Pore Total Volume (mm³)",
            "network.throat_resolved_porosity": "Throat Resolved Porosity (%)",
            "network.throat_subscale_porosity": "Throat Subscale Porosity (%)",
            "network.throat_total_porosity": "Throat Total Porosity (%)",
            "network.throat_resolved_volume": "Throat Resolved Volume (mm³)",
            "network.throat_subscale_volume": "Throat Subscale Volume (mm³)",
            "network.throat_total_volume": "Throat Total Volume (mm³)",
        }

    def create(self, parent_folder=None):
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        if parent_folder is None:
            parent_folder = folderTree.GetSceneItemID()
        required_files = ["pore_network.pkl", "throat_network.pkl", "network.pkl"]
        missing_files = []

        for filename in required_files:
            file_path = self.cwd / filename
            if not file_path.exists():
                missing_files.append(str(file_path))

        if missing_files:
            raise FileNotFoundError(
                f"The following required pore network files were not found: {', '.join(missing_files)}"
            )

        dict_pores, dict_throats, dict_network_raw = [pd.read_pickle(str(self.cwd / f)) for f in required_files]

        dict_network = {}
        if not dict_network_raw.empty:
            record = dict_network_raw.iloc[0]
            for key, value in record.items():
                new_key = self.network_property_map.get(key)
                if new_key:
                    dict_network[new_key] = value

        df_pores = pd.DataFrame(dict_pores)
        df_throats = pd.DataFrame(dict_throats)
        df_network = pd.DataFrame(list(dict_network.items()), columns=["Property", "Value"])

        # Handle Watershed Volume
        if os.path.isfile(str(self.cwd / "watershed.npy")):
            array_watershed = np.load(str(self.cwd / "watershed.npy"))
            output_watershed_volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
            output_watershed_volume.CreateDefaultDisplayNodes()
            slicer.util.updateVolumeFromArray(output_watershed_volume, array_watershed)

            # Apply metadata
            output_watershed_volume.SetSpacing(self.metadata["spacing"])
            output_watershed_volume.SetOrigin(self.metadata["origin"])
            vtk_matrix = slicer.util.vtkMatrixFromArray(np.array(self.metadata["ijktorasmatrix"]))
            output_watershed_volume.SetIJKToRASDirectionMatrix(vtk_matrix)
        else:
            array_watershed = None

        throatOutputTable, poreOutputTable, networkOutputTable = self.__create_tables("porespy")

        self.results["pore_table"] = poreOutputTable
        self.results["throat_table"] = throatOutputTable
        self.results["network_table"] = networkOutputTable

        dataFrameToTableNode(df_pores, poreOutputTable)
        dataFrameToTableNode(df_throats, throatOutputTable)
        dataFrameToTableNode(df_network, networkOutputTable)

        ### Include size and spatial information in attributes ###
        bounds = self.metadata["bounds"]
        spacing = self.metadata["spacing"]
        origin = self.metadata["origin"]

        ijktoras = self.metadata.get("ijktorasmatrix")
        poreOutputTable.AddNodeReferenceID("throat_table", throatOutputTable.GetID())
        poreOutputTable.SetAttribute("x_size", str(bounds[1] - bounds[0]))
        poreOutputTable.SetAttribute("y_size", str(bounds[3] - bounds[2]))
        poreOutputTable.SetAttribute("z_size", str(bounds[5] - bounds[4]))
        poreOutputTable.SetAttribute("origin", f"{origin[0]};{origin[1]};{origin[2]}")
        poreOutputTable.SetAttribute("x_spacing", str(spacing[0]))
        poreOutputTable.SetAttribute("y_spacing", str(spacing[1]))
        poreOutputTable.SetAttribute("z_spacing", str(spacing[2]))
        if ijktoras is not None:
            poreOutputTable.SetAttribute("ijktoras", ";".join(str(v) for row in ijktoras for v in row))

        if array_watershed is not None:
            poreOutputTable.SetAttribute("watershed_node_id", output_watershed_volume.GetID())
            poreOutputTable.AddNodeReferenceID("watershed", output_watershed_volume.GetID())

        # Create the specific folder for this extraction
        currentDir = folderTree.CreateFolderItem(parent_folder, f"{self.prefix}_Pore_Network")

        # Helper to move and organize nodes
        for node in [poreOutputTable, throatOutputTable, networkOutputTable]:
            itemId = folderTree.GetItemByDataNode(node)
            folderTree.SetItemParent(itemId, currentDir)

        if array_watershed is not None:
            itemId = folderTree.GetItemByDataNode(output_watershed_volume)
            folderTree.SetItemParent(itemId, currentDir)

        if self.visualization:
            self.results["model_nodes"] = visualize_network(poreOutputTable, throatOutputTable, self.metadata)

        return self.results

    def __create_tables(self, algorithm_name):
        poreOutputTable = self.__create_table("pore")
        throatOutputTable = self.__create_table("throat")
        networkOutputTable = self.__create_table("summary")

        poreOutputTable.SetAttribute("extraction_algorithm", algorithm_name)
        edge_throats = "none" if (algorithm_name == "porespy") else "x"
        poreOutputTable.SetAttribute("edge_throats", edge_throats)
        return throatOutputTable, poreOutputTable, networkOutputTable

    def __create_table(self, table_type):
        table = slicer.mrmlScene.CreateNodeByClass("vtkMRMLTableNode")
        table.SetName(slicer.mrmlScene.GenerateUniqueName(f"{self.prefix}_{table_type}_table"))
        table.SetAttribute("table_type", f"{table_type}_table")
        table.SetAttribute("is_multiscale", "false")
        slicer.mrmlScene.AddNode(table)
        return table


def visualize_network(
    poreOutputTable: slicer.vtkMRMLTableNode,
    throatOutputTable: slicer.vtkMRMLTableNode,
    metadata: dict,
):
    """
    Receives pore and throat table nodes and metadata to create 3D visualizations.
    """
    ########################
    ##### Create pores #####
    ########################
    pore_columns = {poreOutputTable.GetColumnName(i): i for i in range(poreOutputTable.GetNumberOfColumns())}

    n_of_phases = int(np.array(poreOutputTable.GetTable().GetColumn(pore_columns["pore.phase"])).max())
    coordinates = [vtk.vtkPoints() for _ in range(n_of_phases)]
    diameters = [vtk.vtkFloatArray() for _ in range(n_of_phases)]

    for pore_index in range(poreOutputTable.GetTable().GetNumberOfRows()):
        row = poreOutputTable.GetTable().GetRow(pore_index)
        phase = row.GetVariantValue(pore_columns["pore.phase"]).ToInt() - 1
        coordinates[phase].InsertNextPoint(
            row.GetVariantValue(pore_columns["pore.coords_0"]).ToFloat(),
            row.GetVariantValue(pore_columns["pore.coords_1"]).ToFloat(),
            row.GetVariantValue(pore_columns["pore.coords_2"]).ToFloat(),
        )
        diameters[phase].InsertNextTuple1(row.GetVariantValue(pore_columns["pore.equivalent_diameter"]).ToFloat())

    sphere_colors = ((0.1, 0.1, 0.9), (0.9, 0.1, 0.9))
    pores_model_nodes = []

    for phase in range(n_of_phases):
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(coordinates[phase])
        polydata.GetPointData().SetScalars(diameters[phase])

        sphereSource = vtk.vtkSphereSource()
        glyph3D = vtk.vtkGlyph3D()
        glyph3D.SetScaleModeToScaleByScalar()
        glyph3D.SetScaleFactor(0.5)
        glyph3D.SetSourceConnection(sphereSource.GetOutputPort())
        glyph3D.SetInputData(polydata)
        glyph3D.Update()

        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", f"pore_model_phase_{phase+1}")
        node.SetPolyDataConnection(glyph3D.GetOutputPort())
        node.CreateDefaultDisplayNodes()
        display = node.GetDisplayNode()
        display.SetScalarVisibility(0)
        display.SetColor(*sphere_colors[phase])
        pores_model_nodes.append(node)

    ##########################
    ##### Create throats #####
    ##########################
    throat_columns = {throatOutputTable.GetColumnName(i): i for i in range(throatOutputTable.GetNumberOfColumns())}

    n_throat_phases = n_of_phases * 2 - 1
    nodes_list_by_phase = [[] for _ in range(n_throat_phases)]
    links_list_by_phase = [[] for _ in range(n_throat_phases)]
    diameters_list_by_phase = [[] for _ in range(n_throat_phases)]
    i_by_phase = [0] * n_throat_phases
    max_diameter_by_phase = [0.0] * n_throat_phases
    min_diameter_by_phase = [np.inf] * n_throat_phases

    for throat_index in range(throatOutputTable.GetTable().GetNumberOfRows()):
        throat_row = throatOutputTable.GetTable().GetRow(throat_index)
        lp_idx = throat_row.GetVariantValue(throat_columns["throat.conns_0"]).ToInt()
        rp_idx = throat_row.GetVariantValue(throat_columns["throat.conns_1"]).ToInt()

        if (lp_idx < 0) or (rp_idx < 0):
            continue

        l_phase = throat_row.GetVariantValue(throat_columns["throat.phases_0"]).ToInt()
        r_phase = throat_row.GetVariantValue(throat_columns["throat.phases_1"]).ToInt()
        t_phase = l_phase + r_phase - 2

        curr_i = i_by_phase[t_phase]

        lp_row = poreOutputTable.GetTable().GetRow(lp_idx)
        nodes_list_by_phase[t_phase].append(
            (
                curr_i * 2,
                lp_row.GetVariantValue(pore_columns["pore.coords_0"]).ToFloat(),
                lp_row.GetVariantValue(pore_columns["pore.coords_1"]).ToFloat(),
                lp_row.GetVariantValue(pore_columns["pore.coords_2"]).ToFloat(),
            )
        )

        rp_row = poreOutputTable.GetTable().GetRow(rp_idx)
        nodes_list_by_phase[t_phase].append(
            (
                curr_i * 2 + 1,
                rp_row.GetVariantValue(pore_columns["pore.coords_0"]).ToFloat(),
                rp_row.GetVariantValue(pore_columns["pore.coords_1"]).ToFloat(),
                rp_row.GetVariantValue(pore_columns["pore.coords_2"]).ToFloat(),
            )
        )

        t_dia = throat_row.GetVariantValue(throat_columns["throat.inscribed_diameter"]).ToFloat()
        if (t_dia < min_diameter_by_phase[t_phase]) and (t_dia > 0):
            min_diameter_by_phase[t_phase] = t_dia
        if t_dia > max_diameter_by_phase[t_phase]:
            max_diameter_by_phase[t_phase] = t_dia

        diameters_list_by_phase[t_phase].append((curr_i * 2, t_dia))
        diameters_list_by_phase[t_phase].append((curr_i * 2 + 1, t_dia))

        links_list_by_phase[t_phase].append((curr_i * 2, curr_i * 2 + 1))
        i_by_phase[t_phase] += 1

    throats_model_nodes = []
    throats_colors = ((0.1, 0.9, 0.1), (0.9, 0.8, 0.1), (0.9, 0.1, 0.1))

    for phase in range(n_throat_phases):
        if not nodes_list_by_phase[phase]:
            continue

        coords = vtk.vtkPoints()
        for pt in nodes_list_by_phase[phase]:
            coords.InsertPoint(pt[0], pt[1:])

        elements = vtk.vtkCellArray()
        for link in links_list_by_phase[phase]:
            idList = vtk.vtkIdList()
            idList.InsertNextId(link[0])
            idList.InsertNextId(link[1])
            elements.InsertNextCell(idList)

        rad_array = vtk.vtkDoubleArray()
        rad_array.SetName("TubeRadius")
        rad_array.SetNumberOfTuples(len(diameters_list_by_phase[phase]))
        for entry in diameters_list_by_phase[phase]:
            rad_array.SetTuple1(entry[0], entry[1])

        poly = vtk.vtkPolyData()
        poly.SetPoints(coords)
        poly.SetLines(elements)
        poly.GetPointData().AddArray(rad_array)
        poly.GetPointData().SetActiveScalars("TubeRadius")

        min_r = min_diameter_by_phase[phase] / (2 * (phase + 1))
        max_r_factor = (max_diameter_by_phase[phase] / min_diameter_by_phase[phase]) ** 0.5

        tubes = vtk.vtkTubeFilter()
        tubes.SetInputData(poly)
        tubes.SetNumberOfSides(6)
        tubes.SetVaryRadiusToVaryRadiusByScalar()
        tubes.SetRadius(min_r)
        tubes.SetRadiusFactor(max_r_factor)
        tubes.Update()

        t_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", f"throat_model_phase_{phase+1}")
        t_node.SetPolyDataConnection(tubes.GetOutputPort())
        t_node.CreateDefaultDisplayNodes()
        t_node.GetDisplayNode().SetScalarVisibility(0)
        t_node.GetDisplayNode().SetColor(*throats_colors[phase])
        throats_model_nodes.append(t_node)

    ### Final Spatial Placement and Hierarchy ###
    folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    parentItemId = folderTree.GetItemParent(folderTree.GetItemByDataNode(poreOutputTable))

    # Construct the full transform matrix from metadata
    fullMatrix = slicer.util.vtkMatrixFromArray(np.array(metadata["ijktorasmatrix"]))
    fullMatrix.SetElement(0, 3, metadata["origin"][0])
    fullMatrix.SetElement(1, 3, metadata["origin"][1])
    fullMatrix.SetElement(2, 3, metadata["origin"][2])

    transformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode")
    transformNode.SetMatrixTransformToParent(fullMatrix)

    for model_node in pores_model_nodes + throats_model_nodes:
        folderTree.SetItemParent(folderTree.GetItemByDataNode(model_node), parentItemId)
        model_node.SetAndObserveTransformNodeID(transformNode.GetID())
        model_node.HardenTransform()

    slicer.mrmlScene.RemoveNode(transformNode)

    return {"pores_nodes": pores_model_nodes, "throats_nodes": throats_model_nodes}


def _get_paired_throats_table(geo_pore):
    """ "
    =================================================================================================
    DEPRECATED To get the paired throat table use geo_pore.GetNodeReference("throat_table")
    =================================================================================================
    """

    folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    pore_table_id = folderTree.GetItemByDataNode(geo_pore)
    parent_id = folderTree.GetItemParent(pore_table_id)
    vtk_list = vtk.vtkIdList()
    folderTree.GetItemChildren(parent_id, vtk_list)
    geo_throat = None
    for i in range(vtk_list.GetNumberOfIds()):
        sibling_id = vtk_list.GetId(i)
        node = folderTree.GetItemDataNode(sibling_id)
        if not node:
            continue
        table_type = node.GetAttribute("table_type")
        if table_type:
            if table_type == "throat_table":
                geo_throat = node
                break

    if not geo_throat:
        logging.warning("No throats table found in pores table folder.")
        return False
    return geo_throat
