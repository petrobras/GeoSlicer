# fmt: off
import qt
import vtk
import os
import shutil
import subprocess
from typing import Tuple, Union
import csv

import re
import numpy as np
from scipy import ndimage
import slicer
import openpnm
from numba import njit, prange
import porespy
from porespy.networks import regions_to_network, snow2
import pandas as pd
import logging

from ltrace.slicer_utils import tableNodeToDict, slicer_is_in_developer_mode, dataFrameToTableNode
from ltrace.image import optimized_transforms
import ltrace.pore_networks.functions as pn
from .constants import *
from .vtk_utils import *

DEFAULT_SHAPE_FACTOR = 1.0
MAX_VISUALIZATION_POINTS = 15000
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


def geo2spy(geo_pore):
    """
    Takes a Table Node with pore_table type attribute and returns a dictionary
    describing the pore network using the PoreSpy format.
    """

    # Search for throats table in same folder as pores table
    if not (geo_throat := _get_paired_throats_table(geo_pore)):
        return False

    # Parse MRML tables into dict
    pore_dict = tableNodeToDict(geo_pore)
    throat_dict = tableNodeToDict(geo_throat)

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

    prop_array = [re.split(r"_\d$", key)[0] for key in geo.keys()]
    prop_dict = {i : prop_array.count(i) for i in prop_array}

    spy = {}
    for prop_name, columns in prop_dict.items():
        if columns == 1:
            spy[prop_name] = geo[prop_name]
        else:
            spy[prop_name] = np.stack([geo[f"{prop_name}_{i}"] for i in range(columns)], axis=1)

    spy["pore.phase1"] = spy["pore.phase"] == 1
    spy["pore.phase2"] = spy["pore.phase"] == 2
    return spy


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
    pore_area = pore_radius**2 / (4*pore_shape_factor)

    pore_shape = np.zeros(len(pore_network["pore.extended_diameter"]), dtype=np.uint8)
    pore_conductivity = np.zeros(len(pore_network["pore.extended_diameter"]), dtype=np.float32)
    for pore, shape_factor in enumerate(pore_network["pore.shape_factor"]):
        if shape_factor <= 0.048:
            pore_shape[pore] = 0
            pore_conductivity[pore] = (3/5) * pore_area[pore]**2 * shape_factor
        elif shape_factor <= 0.07:
            pore_shape[pore] = 1
            pore_conductivity[pore] = (0.5623) * pore_area[pore]**2 * shape_factor
        else:
            pore_shape[pore] = 2
            pore_conductivity[pore] = (1/8) * pore_area[pore] * pore_radius[pore]**2

    throat_shape = np.zeros(len(pore_network["throat.shape_factor"]), dtype=np.uint8)
    throat_conductivity = np.zeros(len(pore_network["throat.shape_factor"]), dtype=np.float32)
    throat_conductance = np.zeros(len(pore_network["throat.shape_factor"]), dtype=np.float32)
    for throat, shape_factor in enumerate(throat_shape_factor):
        conn_0 = pore_network["throat.conns"][throat][0]
        conn_1 = pore_network["throat.conns"][throat][1]
        if shape_factor <= 0.048:
            throat_shape[throat] = 0
            throat_conductivity[throat] = (3/5) * throat_area[throat]**2 * shape_factor
        elif shape_factor <= 0.07:
            throat_shape[throat] = 1
            throat_conductivity[throat] = (0.5623) * throat_area[throat]**2 * shape_factor
        else:
            throat_shape[throat] = 2
            throat_conductivity[throat] = (1/8) * throat_area[throat] * throat_radius[throat]**2
        throat_conductance[throat] = ((
            throat_conns_0_length[throat] / pore_conductivity[conn_0]
            + throat_mid_length[throat] / throat_conductivity[throat]
            + throat_conns_1_length[throat] / pore_conductivity[conn_1]
            )**(-1)
        )

    pore_network["throat.shape"] = throat_shape
    pore_network["throat.manual_valvatne_conductivity"] = throat_conductivity
    pore_network["throat.manual_valvatne_conductance"] = throat_conductance
    pore_network["pore.shape"] = pore_shape
    pore_network["pore.manual_valvatne_conductivity"] = pore_conductivity

    return

def set_subresolution_conductance(sub_network, subresolution_function):

    sub_network["pore.diameter"] = sub_network["pore.equivalent_diameter"]
    sub_network["throat.diameter"] = sub_network["throat.equivalent_diameter"]

    # Equations
    pressure2radius = lambda Pc: -2 * 480 * np.cos(np.pi * 140 / 180) / Pc
    area_function = lambda r: np.pi * r ** 2

    # Pore conductivity
    pore_conductivity_resolved = sub_network["pore.manual_valvatne_conductivity"]
    pore_phi = sub_network["pore.subresolution_porosity"]
    pore_pressure = np.array([subresolution_function(p) for p in pore_phi])
    pore_pressure[pore_phi == 1] = np.array([pressure2radius(r) for r in sub_network["pore.diameter"] / 2])[pore_phi == 1]
    
    pore_capilar_radius = np.array([pressure2radius(Pc) for Pc in pore_pressure])
    sub_network["pore.capilar_radius"] = pore_capilar_radius

    pore_number_of_capilaries = (
        (area_function(sub_network["pore.diameter"]/2) * pore_phi)
        / area_function(pore_capilar_radius)
    )
    sub_network["pore.number_of_capilaries"] = pore_number_of_capilaries
    pore_conductivity = (1/8) * np.pi * pore_capilar_radius**4
    pore_conductivity *= pore_number_of_capilaries

    throat_phi = sub_network["throat.subresolution_porosity"]
    throat_pressure = np.array([subresolution_function(p) for p in throat_phi])
    throat_pressure[throat_phi == 1] = np.array([pressure2radius(r) for r in sub_network["throat.diameter"] / 2])[throat_phi == 1]
    throat_capilar_radius = np.array([pressure2radius(Pc) for Pc in throat_pressure])

    # Throat diameter debug fix
    throat_diameter_temp = np.array(sub_network["throat.diameter"])
    non_zero_throat_diameters = throat_diameter_temp[throat_diameter_temp != 0]
    min_throat_diameter = np.min(non_zero_throat_diameters)
    throat_diameter_temp[throat_diameter_temp == 0.0] = min_throat_diameter
    sub_network["throat.diameter"] = throat_diameter_temp

    throat_number_of_capilaries = (
        (area_function(sub_network["throat.diameter"]/2) * throat_phi)
        / area_function(throat_capilar_radius)
    )
    throat_conductivity = (1/8) * np.pi * throat_capilar_radius**4
    throat_conductivity *= throat_number_of_capilaries
        
    # Throat conductance
    throat_conductance = np.copy(sub_network["throat.manual_valvatne_conductance"])
    for throat_index, (left_index, right_index) in enumerate(
        sub_network["throat.conns"],
    ):
        left_unresolved = sub_network["throat.phases"][throat_index][0] == 2
        right_unresolved = sub_network["throat.phases"][throat_index][1] == 2

        if left_unresolved and not right_unresolved:
            throat_conductance[throat_index] = (
                sub_network["throat.mid_length"][throat_index]
                / 
                (2 * throat_conductivity[throat_index])
            )
            throat_conductance[throat_index] += (
                sub_network["throat.conns_0_length"][throat_index]
                /
                pore_conductivity[left_index]
            )
            throat_conductance[throat_index] += (
                sub_network["throat.conns_1_length"][throat_index]
                /
                pore_conductivity_resolved[right_index]
            )
            throat_conductance[throat_index] **= -1

        elif right_unresolved and not left_unresolved:
            throat_conductance[throat_index] = (
                sub_network["throat.mid_length"][throat_index]
                / 
                (2 * throat_conductivity[throat_index])
            )
            throat_conductance[throat_index] += (
                sub_network["throat.conns_0_length"][throat_index]
                /
                pore_conductivity_resolved[left_index]
            )
            throat_conductance[throat_index] += (
                sub_network["throat.conns_1_length"][throat_index]
                /
                pore_conductivity[right_index]
            )
            throat_conductance[throat_index] **= -1

        elif right_unresolved and left_unresolved:
            throat_conductance[throat_index] = (
                sub_network["throat.mid_length"][throat_index]
                / 
                throat_conductivity[throat_index]
            )
            throat_conductance[throat_index] += (
                sub_network["throat.conns_0_length"][throat_index]
                /
                pore_conductivity[left_index]
            )
            throat_conductance[throat_index] += (
                sub_network["throat.conns_1_length"][throat_index]
                /
                pore_conductivity[right_index]
            )
            throat_conductance[throat_index] **= -1

    sub_network['pore.cap_pressure'] = pore_pressure.copy()
    sub_network['pore.cap_radius'] = pore_capilar_radius.copy()
    sub_network['throat.cap_pressure'] = throat_pressure.copy()
    sub_network['throat.cap_radius'] = throat_capilar_radius.copy()
    sub_network['throat.sub_conductivity'] = throat_conductivity.copy()
    sub_network['pore.sub_conductivity'] = pore_conductivity.copy()
    sub_network['throat.manual_valvatne_conductance_former'] = throat_conductance.copy()
    sub_network['throat.manual_valvatne_conductance'] = throat_conductance
    sub_network['throat.number_of_capilaries'] = throat_number_of_capilaries
    sub_network['pore.number_of_capilaries'] = pore_number_of_capilaries

    sub_network["throat.cross_sectional_area"] = np.pi * sub_network["throat.cap_radius"] ** 2
    sub_network["throat.volume"] = sub_network["throat.total_length"] * sub_network["throat.cross_sectional_area"]
    sub_network["pore.volume"] *= sub_network["pore.subresolution_porosity"]

    print(os.getcwd())
    for element in ("pore.", "throat."):
        pore_keys = [key for key in sub_network.keys() if key.startswith(element)]
        pore_dict = {key: sub_network[key] for key in pore_keys}
        csv_file_name = f'output_{element[:-1]}.csv'

        with open(csv_file_name, 'w', newline='') as csvfile:
            # Use filtered_keys as fieldnames to ensure only "pore" keys are included
            fieldnames = pore_keys
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()

            for i in range(len(pore_dict[pore_keys[0]])):
                row_data = {key: pore_dict[key][i] for key in pore_keys}
                writer.writerow(row_data)


def geo2pnf(geo_pore, subresolution_function, scale_factor=10 ** -3, axis="x"):
    """
    Takes a Table Node with pore_table type attribute and returns a dictionary
    with four strings ("link1", "link2", "node1", "node2") representing the four
    files in the statoil format
    """

    # Search for throats table in same folder as pores table
    if not (geo_throat := _get_paired_throats_table(geo_pore)):
        return False

    spy_network = geo2spy(geo_pore)
    manual_valvatne_blunt(spy_network)

    if (spy_network["pore.phase"] == 2).any():
        set_subresolution_conductance(spy_network, subresolution_function)
    spy2geo(spy_network)
    pore_dict = {i: spy_network[i] for i in spy_network.keys() if ("pore." in i) }
    throat_dict = {i: spy_network[i] for i in spy_network.keys() if ("throat." in i) }

    # Parse MRML tables into dict
    #pore_dict = tableNodeToDict(geo_pore)
    #throat_dict = tableNodeToDict(geo_throat)

    if geo_pore.GetAttribute("extraction algorithm") == "porespy":
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
                elif axis == geo_pore.GetAttribute("edge_throats"):
                    pores_conns_pores[start_pore].append(end_pore)
                    pores_conns_throats[start_pore].append(i)
                    pores_with_edge_throats.add(start_pore)

    pnf = {}
    pnf["link1"] = ["",]
    pnf["link2"] = []

    if "throat.perimeter" in throat_dict.keys():
        min_perimeter = throat_dict["throat.perimeter"][throat_dict["throat.perimeter"] > 0].min()

    for i in range(n_throats):
        # link1 items
        left_pore = throat_dict["throat.conns_0"][i]
        right_pore = throat_dict["throat.conns_1"][i]

        radius = "{:E}".format(
            scale_factor * throat_dict["throat.inscribed_diameter"][i] / 2
            )
        
        if "throat.shape_factor" in throat_dict.keys():
            shape_factor = "{:E}".format(throat_dict["throat.shape_factor"][i])
        else:
            cross_area = throat_dict["throat.cross_sectional_area"][i]
            perimeter = throat_dict["throat.perimeter"][i]
            if perimeter < min_perimeter:
                perimeter = min_perimeter
            eq_circle_area = perimeter ** 2 / (4 * np.pi)
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
            volume = "{:E}".format(scale_factor ** 3 * throat_dict["throat.volume"][i] * volume_multiplier)
        else:
            volume = "{:E}".format(
                scale_factor ** 3
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
            radius = "{:E}".format(scale_factor * throat_dict["throat.cap_radius"][i])
            shape_factor = 0.048

            mid_length = (
                throat_dict["throat.mid_length"][i]
                / throat_dict["throat.number_of_capilaries"][i]
            )

            if left_is_darcy:
                left_pore_length = (
                    throat_dict["throat.conns_0_length"][i]
                    / pore_dict["pore.number_of_capilaries"][left_pore]
                )
            else:
                left_pore_length = mid_length / 100

            if right_is_darcy:
                right_pore_length = (
                    throat_dict["throat.conns_1_length"][i]
                    / pore_dict["pore.number_of_capilaries"][right_pore]
                )
            else:
                right_pore_length = mid_length / 100
            
            volume = (
                throat_dict["throat.cap_radius"][i]**2
                * (9/np.sqrt(3))
                * mid_length
                * throat_dict["throat.number_of_capilaries"][i]
            )
            length = left_pore_length + right_pore_length + mid_length

        # write results
        pnf["link1"].append(f"{i+1} {left_pore+1} {right_pore+1} {radius} {shape_factor} {length}")
        pnf["link2"].append(
            f"{i+1} {left_pore+1} {right_pore+1} {left_pore_length} {right_pore_length} {mid_length} {volume} {clay}"
        )

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
        shape_factor = "{:E}".format(0.07)  # Similar to PNE behavior
        if "pore.extended_diameter" in pore_dict.keys():
            radius = "{:E}".format(scale_factor * pore_dict["pore.extended_diameter"][i] / 2)
            length = "{:E}".format(scale_factor * pore_dict["pore.extended_diameter"][i] / 2)
        else:
            radius = "{:E}".format(scale_factor * pore_dict["pore.radius"][i])
            length = "{:E}".format(scale_factor * pore_dict["pore.radius"][i])
        total_length = "{:E}".format(scale_factor * 3 * pore_dict["pore.extended_diameter"][i] / 2)
        volume = "{:E}".format(scale_factor ** 3 * pore_dict["pore.volume"][i] * volume_multiplier)
        pnf["link1"].append(f"{n_throats+1} {i+1} {target_pore+1} {radius} {shape_factor} {length}")
        pnf["link2"].append(f"{n_throats+1} {i+1} {target_pore+1} {length} {0} {0} {volume} {0}")
        n_throats += 1

    pnf["link1"][0] = f"{n_throats}"

    x = float(geo_pore.GetAttribute("x_size")) * scale_factor
    y = float(geo_pore.GetAttribute("y_size")) * scale_factor
    z = float(geo_pore.GetAttribute("z_size")) * scale_factor

    pnf["link1"][0] = f"{n_throats}"

    x = float(geo_pore.GetAttribute("x_size")) * scale_factor
    y = float(geo_pore.GetAttribute("y_size")) * scale_factor
    z = float(geo_pore.GetAttribute("z_size")) * scale_factor

    pnf["node1"] = [f"{n_pores} {x} {y} {z}",]
    pnf["node2"] = []
    for i in range(n_pores):
        input_x = pore_dict["pore.coords_0"][i] * scale_factor
        input_y = pore_dict["pore.coords_1"][i] * scale_factor
        input_z = pore_dict["pore.coords_2"][i] * scale_factor
        if axis == "x":
            p_z, p_y, p_x = input_x, input_y, input_z
        elif axis == "y":
            p_y, p_z, p_x = input_x, input_y, input_z
        elif axis == "z":
            p_x, p_y, p_z = input_x, input_y, input_z
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
        area = scale_factor ** 2 * pore_dict["pore.surface_area"][i]

        if "pore.shape_factor" in pore_dict.keys():
            shape_factor = pore_dict["pore.shape_factor"][i]
        elif area > 0:
            eq_volume = (1 / (6*np.sqrt(np.pi))) * (area)**(3/2)
            shape_factor = "{:E}".format(float(volume) / eq_volume)
        else:
            shape_factor = DEFAULT_SHAPE_FACTOR

        if not throat_dict.get("pore.clay", None):
            clay = 0
        else:
            clay = "{:E}".format(throat_dict["pore.clay"][i])

        # adjustments for darcy pores
        if pore_dict["pore.phase"][i] == 2:
            volume = pore_dict["pore.volume"][i] * pore_dict["pore.subresolution_porosity"][i]
            radius = pore_dict["pore.cap_radius"][i]
            shape_factor = 0.048

        pnf["node1"].append(
            f"{i+1} {p_x} {p_y} {p_z} {coordinate_number} {connected_pores} {is_inlet} {is_outlet} {connected_throats}"
        )
        pnf["node2"].append(f"{i+1} {volume} {radius} {shape_factor} {clay}")

    return pnf


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
    weights = np.ones((2*n_throats,), dtype=int)

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


def get_connected_voxel(volume):
    output_array, _ = ndimage.label(volume)
    left_slice = slice(0,1)
    right_slice = slice(-1, None)
    full_slice = slice(None)
    edge_slices = [
        (left_slice, full_slice, full_slice),
        (right_slice, full_slice, full_slice),
        (full_slice, left_slice, full_slice),
        (full_slice, right_slice, full_slice),
        (full_slice, full_slice, left_slice),
        (full_slice, full_slice, right_slice)
        ]
    connected_labels = np.unique(
        np.concatenate(
            [np.unique(output_array[sl]) for sl in edge_slices]
            )
    )
    @njit(parallel=True)
    def inplace_where(test_array, values_array, valid_labels):
        x, y, z = test_array.shape
        for i in prange(x):
            for j in range(y):
                for k in range(z):
                    if test_array[i, j, k] in valid_labels:
                        test_array[i, j, k] = values_array[i, j, k]
                    else:
                        test_array[i, j, k] = 0
    inplace_where(output_array, volume, connected_labels)
    
    return output_array
    

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


def get_sub_geo(pore_dict, throat_dict, sub_pores, sub_throats):

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


def single_phase_permeability(
    pore_network, 
    throat_shape=None, 
    pore_shape=None, 
    in_face="xmin", 
    out_face="xmax",
    subresolution_function=None,
):

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
    print("multiscale: ", is_multiscale)
    if is_multiscale:
        pass
    set_subresolution_conductance(sub_network, subresolution_function)
    sub_proj = openpnm.io.network_from_porespy(sub_network)
    water = openpnm.phase.Water(network=sub_proj.network)
    water.add_model_collection(openpnm.models.collections.physics.standard)
    sub_proj['throat.hydraulic_conductance'] = sub_proj['throat.manual_valvatne_conductance']
    sub_proj["pore.phase"][...] = 1
    print("Hidr Cond: :", sub_proj['throat.hydraulic_conductance'])
    perm = openpnm.algorithms.StokesFlow(
        network=sub_proj,
        phase=water,
    )
    perm.settings["f_rtol"] = 1e-11
    perm.settings["x_rtol"] = 1e-11
    # print("\n\n############## OpenPNM flow ###########\n\n", perm, "\n\n##############################\n\n")

    perm.set_value_BC(
        pores=sub_proj.pores(in_face), 
        values=101325, 
        mode='overwrite'
    )  # pressure in pa: 101325 pa = 1 atm
    perm.set_value_BC(
        pores=sub_proj.pores(out_face), 
        values=0, 
        mode='overwrite'
    )
    
    perm.run(verbose=True)

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

    return (perm, pore_dict, throat_dict)


def single_phase_permeability_pnf(pore_table, axis="x"):
    """
    Uses PNFlow to calculate one phase permeability, deprecated. 
    """

    original_wd = os.getcwd()
    temporary_folder = slicer.util.tempDirectory()

    input_string = """TITLE  Output;
writeStatistics true;
NETWORK  F Image;

CALC_BOX:  0.1 0.9;

ClayResistivity            2.0 ;

WaterOilInterface          0.03 ;

DRAIN_SINGLETS: T;
"""
    try:
        out_dict = geo2pnf(pore_table, axis=axis)
        for name in ("link1", "link2", "node1", "node2"):
            filename = os.path.join(temporary_folder, f"Image_{name}.dat")
            with open(filename, mode="w") as file:
                for line in out_dict[name]:
                    file.write(line + "\n")
        dat_path = os.path.join(temporary_folder, "input_pnflow.dat")
        with open(dat_path, mode="w") as file:
            file.write(input_string)
        module_path = os.path.dirname(slicer.util.modulePath("PoreNetworkSimulation"))
        pnflow_path = os.path.join(module_path, "Resources", "pnflow.exe")
        os.chdir(temporary_folder)
        subprocess.run(f"{pnflow_path} {dat_path}", shell=True, timeout=PNF_TIMEOUT)
        output_path = os.path.join(temporary_folder, "Output_pnflow.prt")

        with open(output_path, mode="r") as file:
            for line in file:
                if "Absolute permeability:" in line:
                    perm = float(line.split(",")[1].split("(")[0].strip())
                    break

    finally:
        os.chdir(original_wd)
        shutil.rmtree(temporary_folder)

    return perm


def _counter():
    i = -1
    while True:
        i += 1
        yield i


def _get_paired_throats_table(geo_pore):
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
        qt.QMessageBox.information(
            slicer.util.mainWindow(), "Table parsing failed", "No throats table found in pores table folder."
        )
        return False
    return geo_throat


def connected_image(arr):

    labeled = ndimage.label(arr)[0]
    # fmt: off
    sets = [
        set(np.unique(labeled[1:-1, 1:-1,  0])),
        set(np.unique(labeled[1:-1, 1:-1, -1])),
        set(np.unique(labeled[1:-1,  0, 1:-1])),
        set(np.unique(labeled[1:-1, -1, 1:-1])),
        set(np.unique(labeled[ 0, 1:-1, 1:-1])),
        set(np.unique(labeled[-1, 1:-1, 1:-1]))
        ]
    # fmt: on
    all_labels = set().union(*sets)
    all_labels.discard(0)
    connected_labels = []
    for i in all_labels:
        faces_count = sum([(i in current_set) for current_set in sets])
        if faces_count >= 2:
            connected_labels.append(i)
    labeled = np.where(np.isin(labeled, connected_labels), arr, 0)

    if labeled.max() > 1:
        labeled = porespy.tools.make_contiguous(labeled)

    return labeled



def porespy_extract(multiphase, watershed, scale, porosity_map=None):

    # Extracts PNM with porespy and "flattens" the data into a dict of 1d arrays
    
    if watershed is None:
        input_array = multiphase
        snow_results = snow2(multiphase, porosity_map=porosity_map, voxel_size=scale, parallelization=None)
        pn_properties = snow_results.network
        watershed_image = snow_results.regions
    else:
        input_array = watershed
        if multiphase is None:
            pn_properties = regions_to_network(watershed, voxel_size=scale)
        else:
            watershed[multiphase==0]=0
            porosity_map[multiphase==0]=0
            pn_properties = regions_to_network(watershed, phases=multiphase, porosity_map=porosity_map, voxel_size=scale)
        watershed_image = watershed

    if not pn_properties:
        return False

    porosity = pn_properties["pore.subresolution_porosity"]
    pn_properties["pore.subresolution_porosity"][porosity == 0] = porosity[porosity > 0].min()
    
    # spy2geo
    spy2geo(pn_properties)

    # Include additional properties

    pn_properties["pore.radius"] = pn_properties["pore.extended_diameter"] / 2

    pn_properties["throat.shape_factor"] = np.clip(
        (pn_properties["throat.inscribed_diameter"] / 2) ** 2 
        / (4 * pn_properties["throat.cross_sectional_area"]),
        0.01, 
        0.09
    )
    pn_properties["throat.conns_0_length"] = pn_properties["pore.extended_diameter"][pn_properties["throat.conns_0"]]/2
    pn_properties["throat.conns_1_length"] = pn_properties["pore.extended_diameter"][pn_properties["throat.conns_1"]]/2
    pn_properties["throat.mid_length"] = (
        pn_properties["throat.total_length"]
        - pn_properties["throat.conns_0_length"]
        - pn_properties["throat.conns_1_length"]
    )

    pn_properties["throat.mid_length"] = np.where(
        pn_properties["throat.mid_length"] < pn_properties["throat.total_length"]*0.01, 
        pn_properties["throat.total_length"]*0.01, 
        pn_properties["throat.mid_length"]
    )
    pn_properties["throat.volume"] = (
        pn_properties["throat.total_length"] * pn_properties["throat.cross_sectional_area"]
    )

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
    for coord_name in ("pore.coords_", "pore.local_peak_", "pore.global_peak_", "pore.geometric_centroid_"):
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

    max_coords = [(i * scale[input_array.ndim-1-coord]) for coord,i in enumerate(input_array.shape[-1::-1])]
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
        pn_properties["throat.mid_length"] < pn_properties["throat.total_length"]*0.01, 
        pn_properties["throat.total_length"]*0.01, 
        pn_properties["throat.mid_length"]
    )
    pn_properties["pore.effective_volume"] = (
        pn_properties["pore.volume"] 
        * pn_properties["pore.subresolution_porosity"]
    )

    try:
        pore_subresolution_porosity = pn_properties["pore.subresolution_porosity"]
    except KeyError:
        print("The key pore.subresolution_porosity is not available from porespy, check the version of the porespy module.")

    # TODO (PL-2213): Create an option at interface to select random subresolution porosity instead of getting from network
    #rng = np.random.default_rng()
    #pore_subresolution_porosity = rng.random((pn_properties["pore.all"]).size)

    throat_phi = np.ones_like(pn_properties["throat.all"], dtype=np.float64)
    for throat_index in range(len(pn_properties["throat.all"])):
        left_index = pn_properties["throat.conns_0"][throat_index]
        right_index = pn_properties["throat.conns_1"][throat_index]

        left_unresolved = pn_properties["throat.phases_0"][throat_index] == 2
        right_unresolved = pn_properties["throat.phases_1"][throat_index] == 2

        if right_unresolved and left_unresolved:
            throat_phi[throat_index] = (
                pore_subresolution_porosity[left_index]
                * pn_properties["throat.conns_0_length"][throat_index]
                + pore_subresolution_porosity[right_index]
                * pn_properties["throat.conns_1_length"][throat_index]
            ) / (
                pn_properties["throat.conns_0_length"][throat_index]
                + pn_properties["throat.conns_1_length"][throat_index]
            )

        elif left_unresolved and not right_unresolved:
            throat_phi[throat_index] = pore_subresolution_porosity[left_index]

        elif right_unresolved and not left_unresolved:
            throat_phi[throat_index] = pore_subresolution_porosity[right_index]

    pn_properties["throat.subresolution_porosity"] = throat_phi

    return pn_properties

def general_pn_extract(
        multiphaseNode: slicer.vtkMRMLLabelMapVolumeNode,
        watershedNode: slicer.vtkMRMLLabelMapVolumeNode,
        prefix: str, 
        method: str,
        porosity_map=None,
    ) -> Union[Tuple[slicer.vtkMRMLTableNode, slicer.vtkMRMLTableNode], bool]:
        """
        Creates two table nodes describing the pore-network represented by multiphaseNode or by the watershedNode.

        :param multiphaseNode: 
            The node containing the phases of each pixel (Solid, Pore and Subresolution).
        :param watershedNode:
            The node containing the watershed of the image used to separate pores.
        :param prefix: 
            Created node names will be preceded by this string.
        :param method:
            Either "PoreSpy" or "PNExtract".
            PoreSpy mas receive a labeled volume (each pore must have an unique number),
            while PNExtract receives a binary volume (0 for solid, >0 for por space), a labeled
            volume can be obtained by performing a watershed segmentation on a binary image.
            PNExtract is prone to crash with large volumes, and should be available only on
            developer mode.
        :param porosity_map:
            Numpy array with the porosity map (range 0~100).

        :return:
            Two table nodes describing the pore-network represented by multiphaseNode/watershedNode or False if method if not found or the pore-network
            properties could not be extracted.
        """

        ### Create MRML nodes ###

        def _create_table(table_type):
            table = slicer.mrmlScene.CreateNodeByClass("vtkMRMLTableNode")
            table.AddNodeReferenceID("PoresLabelMap", inputNode.GetID())
            table.SetName(slicer.mrmlScene.GenerateUniqueName(f"{prefix}_{table_type}_table"))
            table.SetAttribute("table_type", f"{table_type}_table")
            table.SetAttribute("is_multiscale", "false")
            slicer.mrmlScene.AddNode(table)
            return table

        def _create_tables(algorithm_name):
            poreOutputTable = _create_table("pore")
            throatOutputTable = _create_table("throat")
            poreOutputTable.SetAttribute("extraction_algorithm", algorithm_name)
            edge_throats = "none" if (algorithm_name == "porespy") else "x"
            poreOutputTable.SetAttribute("edge_throats", edge_throats)
            return throatOutputTable, poreOutputTable

        if method == "PoreSpy":
            input_multiphase = None
            input_watershed = None
            if multiphaseNode is not None:
                inputNode = multiphaseNode
                input_multiphase = slicer.util.arrayFromVolume(multiphaseNode)
            if watershedNode is not None:
                inputNode = watershedNode
                input_watershed = get_connected_array_from_node(watershedNode)
            # Convert from adimensional voxel size to node scale
            # TODO: Deal with anisotropic data PL-1370
            scale = inputNode.GetSpacing()[::-1]
            pn_properties = pn.porespy_extract(
                input_multiphase, input_watershed, scale, 
                porosity_map=porosity_map,
            )
            if pn_properties is False:
                return False
            throatOutputTable, poreOutputTable = _create_tables("porespy")
        elif method == "PNExtract":
            print("Method is no longer supported")
            return False
            #pn_properties = self._pnextract_extract(watershedNode)
            #throatOutputTable, poreOutputTable = _create_tables("pnextract")
        else:
            print(f"method not found: {method}")
            return False

        pn_throats = {}
        pn_pores = {}
        for i in pn_properties.keys():
            if "pore" in i:
                pn_pores[i] = pn_properties[i]
            else:
                pn_throats[i] = pn_properties[i]

        df_pores = pd.DataFrame(pn_pores)
        df_throats = pd.DataFrame(pn_throats)
        dataFrameToTableNode(df_pores, poreOutputTable)
        dataFrameToTableNode(df_throats, throatOutputTable)

        ### Include size infomation ###
        bounds = [0, 0, 0, 0, 0, 0]
        inputNode.GetBounds(bounds)  # In millimeters
        poreOutputTable.SetAttribute("x_size", str(bounds[1] - bounds[0]))
        poreOutputTable.SetAttribute("y_size", str(bounds[3] - bounds[2]))
        poreOutputTable.SetAttribute("z_size", str(bounds[5] - bounds[4]))
        poreOutputTable.SetAttribute("origin", f"{bounds[0]};{bounds[2]};{bounds[4]}")

        ### Move table nodes to hierarchy nodes ###
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemTreeId = folderTree.GetItemByDataNode(inputNode)
        parentItemId = folderTree.GetItemParent(itemTreeId)
        currentDir = folderTree.CreateFolderItem(parentItemId, f"{prefix}_Pore_Network")

        folderTree.CreateItem(currentDir, poreOutputTable)
        folderTree.CreateItem(currentDir, throatOutputTable)

        return poreOutputTable, throatOutputTable


def get_connected_array_from_node(inputVolume: slicer.vtkMRMLLabelMapVolumeNode) -> np.ndarray:
        """
        Receives a volume node, removes its array unconnected elements and returns that array.

        :param inputVolume: The volume node representing the pore-network.

        :return: The volume node array with connected elements only.

        :raises PoreNetworkExtractorError:
            Pore network extraction failed: there was no percolating pore network through any oposite faces of the volume.
        """

        input_array = slicer.util.arrayFromVolume(inputVolume)
        if input_array.max() <= 2**16 - 1:
            input_array = input_array.astype(np.uint16)
        else:
            print(f"{inputVolume} has many indexes: {input_array.max()}")
            input_array = input_array.astype(np.uint32)

        input_array = optimized_transforms.connected_image(input_array, direction="all_combinations")

        if input_array.max() == 0:
            raise PoreNetworkExtractorError(
                "Pore network extraction failed: there was no percolating pore network through any oposite faces of the volume."
            )

        return input_array

def visualize(
    poreOutputTable: slicer.vtkMRMLTableNode,
    throatOutputTable: slicer.vtkMRMLTableNode,
    inputVolume: slicer.vtkMRMLLabelMapVolumeNode,
) -> None:
    """
    Receives pore and throat table nodes and adds modelNode visualizations for them in the scene.

    :param poreOutputTable: Table node describing the pore-network pores.
    :param throatOutputTable: Table node describing the pore-network throats.
    :param inputVolume: Input volume as the reference node.
    """

    ########################
    ##### Create pores #####
    ########################
    pore_columns = {}
    for column_index in range(poreOutputTable.GetNumberOfColumns()):
        pore_columns[poreOutputTable.GetColumnName(column_index)] = column_index

    ### Set up point coordinates and scalars ###
    n_of_phases = np.array(poreOutputTable.GetTable().GetColumn(pore_columns["pore.phase"])).max()
    coordinates = []
    diameters = []
    for i in range(n_of_phases):
        coordinates.append(vtk.vtkPoints())
        diameters.append(vtk.vtkFloatArray())

    IJKToRASMatrix = vtk.vtkMatrix4x4()
    inputVolume.GetIJKToRASDirectionMatrix(IJKToRASMatrix)
    IJK_TO_RAS = np.diag(slicer.util.arrayFromVTKMatrix(IJKToRASMatrix))

    for pore_index in range(poreOutputTable.GetTable().GetNumberOfRows()):
        row = poreOutputTable.GetTable().GetRow(pore_index)
        phase = row.GetVariantValue(pore_columns["pore.phase"]).ToInt() - 1
        coordinates[phase].InsertNextPoint(
            row.GetVariantValue(pore_columns["pore.coords_0"]).ToFloat(),
            row.GetVariantValue(pore_columns["pore.coords_1"]).ToFloat(),
            row.GetVariantValue(pore_columns["pore.coords_2"]).ToFloat(),
        )
        diameters[phase].InsertNextTuple1(row.GetVariantValue(pore_columns["pore.equivalent_diameter"]).ToFloat())

    sphere_colors = (
        (0.1, 0.1, 0.9),
        (0.9, 0.1, 0.9),
    )
    pores_model_nodes = []
    for phase in range(n_of_phases):
        ### Setup VTK filters ###
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

        ### Create and configure MRML nodes ###
        pores_model_nodes.append(slicer.mrmlScene.CreateNodeByClass("vtkMRMLModelNode"))
        pores_model_nodes[phase].SetName(f"pore_model_phase_{phase+1}")
        slicer.mrmlScene.AddNode(pores_model_nodes[phase])

        pores_model_nodes[phase].SetPolyDataConnection(glyph3D.GetOutputPort())
        pores_model_nodes[phase].CreateDefaultDisplayNodes()
        pores_model_nodes[phase].SetDisplayVisibility(True)
        pores_model_display = pores_model_nodes[phase].GetDisplayNode()
        pores_model_display.SetScalarVisibility(0)
        pores_model_display.SetColor(*sphere_colors[phase])

    ##########################
    ##### Create throats #####
    ##########################
    throat_columns = {}
    for column_index in range(throatOutputTable.GetNumberOfColumns()):
        throat_columns[throatOutputTable.GetColumnName(column_index)] = column_index

    ### Read and extract throat properties from table node ###
    nodes_list_by_phase = []
    links_list_by_phase = []
    diameters_list_by_phase = []
    i_by_phase = []
    max_diameter_by_phase = []
    min_diameter_by_phase = []
    for i in range(n_of_phases*2 - 1):
        nodes_list_by_phase.append([])
        links_list_by_phase.append([])
        diameters_list_by_phase.append([])
        i_by_phase.append(0)
        max_diameter_by_phase.append(0)
        min_diameter_by_phase.append(np.inf)

    for throat_index in range(throatOutputTable.GetTable().GetNumberOfRows()):
        throat_row = throatOutputTable.GetTable().GetRow(throat_index)
        left_pore_index = throat_row.GetVariantValue(throat_columns["throat.conns_0"]).ToInt()
        right_pore_index = throat_row.GetVariantValue(throat_columns["throat.conns_1"]).ToInt()

        left_pore_phase = throat_row.GetVariantValue(throat_columns["throat.phases_0"]).ToInt()
        right_pore_phase = throat_row.GetVariantValue(throat_columns["throat.phases_1"]).ToInt()
        throat_phase = left_pore_phase + right_pore_phase - 2
        
        i = i_by_phase[throat_phase]

        if (left_pore_index < 0) or (right_pore_index < 0):
            continue

        left_pore_row = poreOutputTable.GetTable().GetRow(left_pore_index)
        nodes_list_by_phase[throat_phase].append(
            (
                i * 2,
                left_pore_row.GetVariantValue(pore_columns["pore.coords_0"]).ToFloat(),
                left_pore_row.GetVariantValue(pore_columns["pore.coords_1"]).ToFloat(),
                left_pore_row.GetVariantValue(pore_columns["pore.coords_2"]).ToFloat(),
            )
        )

        right_pore_row = poreOutputTable.GetTable().GetRow(right_pore_index)
        nodes_list_by_phase[throat_phase].append(
            (
                i * 2 + 1,
                right_pore_row.GetVariantValue(pore_columns["pore.coords_0"]).ToFloat(),
                right_pore_row.GetVariantValue(pore_columns["pore.coords_1"]).ToFloat(),
                right_pore_row.GetVariantValue(pore_columns["pore.coords_2"]).ToFloat(),
            )
        )

        throat_diameter = throat_row.GetVariantValue(throat_columns["throat.inscribed_diameter"]).ToFloat()

        if (throat_diameter < min_diameter_by_phase[throat_phase]) and (throat_diameter > 0):
            min_diameter_by_phase[throat_phase] = throat_diameter

        if throat_diameter > max_diameter_by_phase[throat_phase]:
            max_diameter_by_phase[throat_phase] = throat_diameter

        diameters_list_by_phase[throat_phase].append((i * 2, throat_diameter))
        diameters_list_by_phase[throat_phase].append((i * 2 + 1, throat_diameter))
        
        
        links_list_by_phase[throat_phase].append((i * 2, i * 2 + 1))
        i_by_phase[throat_phase] += 1

    throats_model_nodes = []
    throats_colors = (
        (0.1, 0.9, 0.1),
        (0.9, 0.8, 0.1),
        (0.9, 0.1, 0.1),
    )

    for phase in range(n_of_phases*2 - 1):
        ### Create VTK data types from lists ###
        coordinates = vtk.vtkPoints()
        for i, j, k, l in nodes_list_by_phase[phase]:
            coordinates.InsertPoint(i, j, k, l)

        elements = vtk.vtkCellArray()
        for i, j in links_list_by_phase[phase]:
            elementIdList = vtk.vtkIdList()
            _ = elementIdList.InsertNextId(i)
            _ = elementIdList.InsertNextId(j)
            _ = elements.InsertNextCell(elementIdList)

        radius = vtk.vtkDoubleArray()
        radius.SetNumberOfTuples(len(diameters_list_by_phase[phase]))
        radius.SetName("TubeRadius")
        for i, dia in diameters_list_by_phase[phase]:
            radius.SetTuple1(i, dia)

        ### Setup VTK filters ###
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(coordinates)
        polydata.SetLines(elements)
        polydata.GetPointData().AddArray(radius)
        polydata.GetPointData().SetActiveScalars("TubeRadius")

        min_radius = min_diameter_by_phase[phase] / (2 * (phase+1))
        # VTK tubes filter uses max_radius as a multiple of minimum radius
        max_radius = (max_diameter_by_phase[phase] / min_diameter_by_phase[phase]) ** (0.5)

        tubes = vtk.vtkTubeFilter()
        tubes.SetInputData(polydata)
        tubes.SetNumberOfSides(6)
        tubes.SetVaryRadiusToVaryRadiusByScalar()
        tubes.SetRadius(min_radius)  # This actually sets the minimum radius
        tubes.SetRadiusFactor(max_radius)
        tubes.Update()

        ### Create and configure MRML nodes ###
        throats_model_nodes.append(slicer.mrmlScene.CreateNodeByClass("vtkMRMLModelNode"))
        throats_model_nodes[phase].SetName(f"throat_model_phase_{phase+1}")
        slicer.mrmlScene.AddNode(throats_model_nodes[phase])

        throats_model_nodes[phase].SetPolyDataConnection(tubes.GetOutputPort())
        throats_model_nodes[phase].CreateDefaultDisplayNodes()
        throats_display_node = throats_model_nodes[phase].GetDisplayNode()
        throats_display_node.SetScalarVisibility(0)
        throats_display_node.SetColor(*throats_colors[phase])

    ##### Move model nodes into hierarchy folders #####
    folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    itemTreeId = folderTree.GetItemByDataNode(poreOutputTable)
    parentItemId = folderTree.GetItemParent(itemTreeId)

    for model_node in (pores_model_nodes + throats_model_nodes):
        folderTree.CreateItem(parentItemId, model_node)

    # Set the correct orientation and origin
    vtkTransformationMatrix = vtk.vtkMatrix4x4()
    inputVolume.GetIJKToRASDirectionMatrix(vtkTransformationMatrix)
    poresLabelMapOrigin = inputVolume.GetOrigin()
    vtkTransformationMatrix.SetElement(0, 3, poresLabelMapOrigin[0])
    vtkTransformationMatrix.SetElement(1, 3, poresLabelMapOrigin[1])
    vtkTransformationMatrix.SetElement(2, 3, poresLabelMapOrigin[2])
    transformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode")
    transformNode.SetMatrixTransformToParent(vtkTransformationMatrix)
    for model_node in (pores_model_nodes + throats_model_nodes):
        model_node.SetAndObserveTransformNodeID(transformNode.GetID())
        model_node.HardenTransform()
    slicer.mrmlScene.RemoveNode(transformNode)

    return {"pores_nodes": pores_model_nodes, "throats_nodes": throats_model_nodes}

class PoreNetworkExtractorError(RuntimeError):
    pass
