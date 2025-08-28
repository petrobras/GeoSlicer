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
import logging

from ltrace.slicer_utils import tableNodeToDict, slicer_is_in_developer_mode, dataFrameToTableNode
from ltrace.image import optimized_transforms
import ltrace.pore_networks.functions as pn
from ltrace.pore_networks.functions_extract import spy2geo
from ltrace.pore_networks.functions_simulation import (
    manual_valvatne_blunt, 
    set_subresolution_conductance,
    estimate_radius,
    estimate_pressure,
)
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


def geo2pnf(
        geo_pore, 
        subresolution_function, 
        scale_factor=10 ** -3, 
        axis="x",
        subres_shape_factor=0.071,
        subres_porositymodifier=1.0,
        ):
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
        set_subresolution_conductance(
            spy_network, 
            subresolution_function, 
            subres_porositymodifier=subres_porositymodifier,
            subres_shape_factor=subres_shape_factor,
            save_tables=slicer_is_in_developer_mode(),
            )
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
    pnf["link3"] = []

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
            N = "{:E}".format(throat_dict["throat.number_of_capilaries"][i])
            radius = "{:E}".format(scale_factor * throat_dict["throat.cap_radius"][i])
            shape_factor = "{:E}".format(subres_shape_factor)

            mid_length = (
                scale_factor * throat_dict["throat.mid_length"][i]
                #/ throat_dict["throat.number_of_capilaries"][i]
            )

            if left_is_darcy:
                left_pore_length = (
                    scale_factor * throat_dict["throat.conns_0_length"][i]
                    #/ pore_dict["pore.number_of_capilaries"][left_pore]
                )
            else:
                left_pore_length = scale_factor * throat_dict["throat.conns_0_length"][i]

            if right_is_darcy:
                right_pore_length = (
                    scale_factor * throat_dict["throat.conns_1_length"][i]
                    #/ pore_dict["pore.number_of_capilaries"][right_pore]
                )
            else:
                right_pore_length = scale_factor * throat_dict["throat.conns_1_length"][i]
            '''
                        volume = (
                np.pi
                * throat_dict["throat.cap_radius"][i]**2
                #* (9/np.sqrt(3))
                * mid_length
                #* throat_dict["throat.number_of_capilaries"][i]
            )
            '''
            length = left_pore_length + right_pore_length + mid_length
        else: # pore is not Darcy
            N = "{:E}".format(1.0)

        # write results
        pnf["link1"].append(f"{i+1} {left_pore+1} {right_pore+1} {radius} {shape_factor} {length}")
        pnf["link2"].append(
            f"{i+1} {left_pore+1} {right_pore+1} {left_pore_length} {right_pore_length} {mid_length} {volume} {clay}"
        )
        pnf["link3"].append(
            f"{i+1} {left_pore+1} {right_pore+1} {N}"
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
        shape_factor = "{:E}".format(subres_shape_factor)  # Similar to PNE behavior
        if "pore.extended_diameter" in pore_dict.keys():
            radius = "{:E}".format(scale_factor * pore_dict["pore.extended_diameter"][i] / 2)
            length = "{:E}".format(scale_factor * pore_dict["pore.extended_diameter"][i] / 2)
        else:
            radius = "{:E}".format(scale_factor * pore_dict["pore.radius"][i])
            length = "{:E}".format(scale_factor * pore_dict["pore.radius"][i])
        total_length = "{:E}".format(scale_factor * 3 * pore_dict["pore.extended_diameter"][i] / 2)
        volume = "{:E}".format(scale_factor ** 3 * pore_dict["pore.volume"][i] * volume_multiplier)
        N = "{:E}".format(1.0)
        
        pnf["link1"].append(f"{n_throats+1} {i+1} {target_pore+1} {radius} {shape_factor} {length}")
        pnf["link2"].append(f"{n_throats+1} {i+1} {target_pore+1} {length} {0} {0} {volume} {0}")
        # pnf["link3"].append(f"{n_throats+1} {i+1} {N}")
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
            #volume = pore_dict["pore.volume"][i] * pore_dict["pore.subresolution_porosity"][i]
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


'''
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
'''

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
            slicer.modules.AppContextInstance.mainWindow, "Table parsing failed", "No throats table found in pores table folder."
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


def is_multiscale_geo(geo_pore):
    spy_network = geo2spy(geo_pore)
    return (spy_network["pore.phase"] == 2).any()
