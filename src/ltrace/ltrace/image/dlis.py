from dliswriter import DLISFile, enums
from ltrace.constants import DLISImportConst
from ImageLogExportLib.ImageLogCSV import _arrayPartsFromNode

# from dliswriter.logical_record.core.eflr import origin
import numpy as np
import os
import slicer
from ltrace.slicer.helpers import getVolumeNullValue, arrayFromVisibleSegmentsBinaryLabelmap, getWellAttributeFromNode
from ltrace.image.optimized_transforms import ANP_880_2022_DEFAULT_NULL_VALUE
from pathlib import Path
import re
import logging
from collections import defaultdict
import math

WELL_NAME_TAG = DLISImportConst.WELL_NAME_TAG
UNITS_TAG = DLISImportConst.UNITS_TAG
DLIS_LOGICAL_FILE_TAG = DLISImportConst.LOGICAL_FILE_TAG
DLIS_ORIGIN_TAG = DLISImportConst.ORIGIN_TAG
DLIS_FRAME_TAG = DLISImportConst.FRAME_TAG


def extract_dlis_data_from_node(node):
    dlis_data = {}

    if isinstance(node, slicer.vtkMRMLSegmentationNode):
        dlis_data["data"], spacing, origin = arrayFromVisibleSegmentsBinaryLabelmap(node)
        dlis_data["spacing"] = spacing[2]
        dlis_data["origin"] = origin[2]
    else:
        dlis_data["data"] = slicer.util.arrayFromVolume(node)
        dlis_data["spacing"] = node.GetSpacing()[2]
        dlis_data["origin"] = node.GetOrigin()[2]

    return dlis_data


def _extract_dlis_data_from_node(node):
    dlis_data = {}
    depths = []
    if isinstance(node, slicer.vtkMRMLSegmentationNode):
        dlis_data["data"], spacing, origin = arrayFromVisibleSegmentsBinaryLabelmap(node)
        dlis_data["spacing"] = spacing[2]
        dlis_data["origin"] = origin[2]
    elif isinstance(node, slicer.vtkMRMLTableNode):
        depths, dlis_data["data"] = _arrayPartsFromNode(node)
        dlis_data["spacing"] = depths[1] - depths[0]
        dlis_data["origin"] = depths[0]
    else:
        dlis_data["data"] = slicer.util.arrayFromVolume(node)
        dlis_data["spacing"] = node.GetSpacing()[2]
        dlis_data["origin"] = node.GetOrigin()[2]

    data = dlis_data["data"] = dlis_data["data"].squeeze()

    if not isinstance(node, slicer.vtkMRMLTableNode):
        # Slicer world is in mm. Converting to meters:
        step = dlis_data["spacing"] / 1000.0
        origin = dlis_data["origin"] / 1000.0
        min_depth = -1 * origin
        max_depth = min_depth + step * (data.shape[0] - 1)  # -1?
        depths = np.linspace(min_depth, max_depth, data.shape[0])

    return dlis_data, depths


def extract_dlis_info_from_node(node):
    dlis_info = {}

    dlis_info["data_name"] = node.GetName()

    if isinstance(node, slicer.vtkMRMLLabelMapVolumeNode) or isinstance(node, slicer.vtkMRMLSegmentationNode):
        dlis_info["null_value"] = 0
    else:
        dlis_info["null_value"] = getVolumeNullValue(node)

    subject_hierarchy_node = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    item_parent = subject_hierarchy_node.GetItemParent(subject_hierarchy_node.GetItemByDataNode(node))
    directory_name = subject_hierarchy_node.GetItemName(item_parent)

    dlis_info["frame_name"] = directory_name

    #  well name (same code as in las.py's extract_dlis_info_from_node)
    well_from_node_name = node.GetName().split("_")[0] if len(node.GetName().split("_")) > 1 else ""
    if node.GetAttribute(WELL_NAME_TAG) is not None:
        dlis_info["well_name"] = node.GetAttribute(WELL_NAME_TAG)
        if well_from_node_name == "":
            logging.info(
                f"Node name ({node.GetName()}) doesn't have the well name ({node.GetAttribute(WELL_NAME_TAG)}) prepended to it."
            )
        elif node.GetAttribute(WELL_NAME_TAG) != well_from_node_name:
            logging.warning(
                f"Well name informed in {node.GetName()} ({node.GetAttribute(WELL_NAME_TAG)}) metadata is different from the well name implied by the node name ({well_from_node_name}). {node.GetAttribute(WELL_NAME_TAG)} will be considered as the well name."
            )
    else:
        dlis_info["well_name"] = well_from_node_name
        # TO-DO - MUSA-128 - We can retrieve the well name from a Segmentation node, but not from a LabelMap
        # The correct would be to, when creating a Segmentation or LabelMap, copy its attribute from their
        # originating volume node
        if isinstance(node, slicer.vtkMRMLSegmentationNode) and well_from_node_name == "":
            dlis_info["well_name"] = slicer.util.getNode(
                node.GetNodeReferenceID("referenceImageGeometryRef")
            ).GetAttribute(WELL_NAME_TAG)
        if dlis_info["well_name"] != "":
            logging.warning(f"No well name found for {node.GetName()}.")

    #  units (same code as in las.py's  extract_dlis_info_from_node)
    units_search = re.search(r"\[(.*?)\]", node.GetName())
    units_from_name = units_search.group(1) if units_search else "NONE"
    units = units_from_name

    if node.GetAttribute(UNITS_TAG) is not None:
        units = node.GetAttribute(UNITS_TAG)
        if units_from_name == "NONE":
            logging.info(
                f"Node name ({node.GetName()}) doesn't include its units ({node.GetAttribute(UNITS_TAG)}) in it."
            )
        elif node.GetAttribute(UNITS_TAG) != units_from_name:
            logging.warning(
                f"Units informed in {node.GetName()} ({node.GetAttribute(UNITS_TAG)}) metadata are different from the units implied by the node name ({units_from_name}). {node.GetAttribute(UNITS_TAG)} will be considered as the units."
            )
    else:
        units = units_from_name
        if units_from_name == "NONE":
            logging.warning(f"No units found for {node.GetName()}. They'll be set to value 'NONE'")

    dlis_info["units"] = units

    return dlis_info


logger = logging.getLogger(__name__)


class DlisWriter:
    def __init__(self):
        self.dlisFile = None

    def _createLogger(self, output_progress_file_path, output_path):
        # Remove any previous handler
        for handler in logger.handlers:
            logger.removeHandler(handler)

        logger.propagate = False

        # Create and add the file handler
        formatter = logging.Formatter(
            "[%(levelname)s] %(asctime)s - %(name)s: %(message)s",
            datefmt="%d/%m/%Y %I:%M:%S%p",
        )

        logFilePath = Path(output_progress_file_path) / f"dliswriter_progress_{output_path}.log"
        fileHandler = logging.FileHandler(logFilePath, mode="w")
        fileHandler.setLevel(logging.INFO)
        fileHandler.setFormatter(formatter)
        logger.addHandler(fileHandler)

    def create(
        self,
        output_path,
        file_name_no_extension,
        output_progress_file_path,
        file_set_name="noname",
        file_type="notype",
        field_name="noname",
        producer_name="noname",
    ):
        self._createLogger(output_progress_file_path, file_name_no_extension)

        self.dlisFile = DLISFile()

        self.current_frame = None

        logger.info(f"DLISFile created. Trying to write to {output_path}")

        self.full_output_path = f"{output_path / file_name_no_extension}.dlis"

    def write_single_node(self, origin, node=None):
        dlis_data, depths = _extract_dlis_data_from_node(node)
        dlis_info = extract_dlis_info_from_node(node)

        depth_channel = self.dlisFile.logical_files[0].add_channel(
            name="MD",
            long_name="Measured depth",
            data=depths,
            units=enums.Unit.METER,
            origin_reference=origin.origin_reference,
        )

        data = dlis_data["data"].squeeze()
        #######value = data.ravel().astype("float64").copy()
        # Replace nan with the default value
        nan_indexes = np.where(data == dlis_info["null_value"])  # value
        data[nan_indexes] = ANP_880_2022_DEFAULT_NULL_VALUE  # value

        data_channel = self.dlisFile.logical_files[0].add_channel(
            node.GetName(),
            data=data,
            units=dlis_info["units"],
            origin_reference=origin.origin_reference,
        )

        # define frame, referencing the above defined channels
        frame = self.dlisFile.logical_files[0].add_frame(
            dlis_info["frame_name"],  # dlis_info["data_name"],
            channels=(depth_channel, data_channel),
            index_type=enums.FrameIndexType.BOREHOLE_DEPTH,
            origin_reference=origin.origin_reference,
        )

    def close(self):
        self.dlisFile.write(self.full_output_path)


def lists_are_close(list1, list2, tol=1e-9):
    if len(list1) != len(list2):
        return False
    else:
        return all(math.isclose(a, b, abs_tol=tol) for a, b in zip(list1, list2))


def get_logical_file(dlis_file, header_id):
    for logical_file in dlis_file.logical_files:
        if logical_file.file_header.header_id == header_id:
            return logical_file
    return None


def assert_single_well(nodes_list):
    well_name = ""
    count_well = 0
    for node in nodes_list:
        if getWellAttributeFromNode(node, WELL_NAME_TAG) != well_name:
            well_name = getWellAttributeFromNode(node, WELL_NAME_TAG)
            count_well += 1
        if count_well == 2:
            raise RuntimeError("Error exporting to DLIS. You can't export nodes from different Wells to the same file.")


def add_origin(writer, lf_header_id, well_name, origin_ref=None):
    return get_logical_file(writer.dlisFile, lf_header_id).add_origin(
        name=f"LF-{lf_header_id}_O-{well_name}",
        well_name=well_name,
        origin_reference=origin_ref,
        set_name=f"O_LF-{lf_header_id}",
    )


def write_nodes(dlis_file, nodes_dict, remaining_nodes, depths_remaining, depth_disparity_tolerance):

    # Write the nodes curves to their logical files and frames, informing the correct origins

    for lf_header_id in nodes_dict:

        if len(nodes_dict[lf_header_id]) == 0:
            continue

        logical_file = get_logical_file(dlis_file, lf_header_id)
        first_frame_key = next(iter(nodes_dict[lf_header_id]))
        null_value = extract_dlis_info_from_node((nodes_dict[lf_header_id][first_frame_key])[0])["null_value"]
        if null_value:
            logical_file.add_parameter(
                name="ABSENT_VALUE",
                values=null_value,
                long_name="Value used to represent absent data - equivalent to LAS' NULL_VALUE",
            )

        for frame in nodes_dict[lf_header_id]:
            _, depths = _extract_dlis_data_from_node(nodes_dict[lf_header_id][frame][0])
            channels = []
            depth_channel = logical_file.add_channel(
                name="MD",
                long_name="Measured depth",
                data=depths,
                units=enums.Unit.METER,
                origin_reference=int(nodes_dict[lf_header_id][frame][0].GetAttribute(DLIS_ORIGIN_TAG)),
                set_name=f"C_LF-{lf_header_id}",
            )
            channels.append(depth_channel)
            for i, node in enumerate(nodes_dict[lf_header_id][frame]):
                dlis_info = extract_dlis_info_from_node(node)
                dlis_data, depths = _extract_dlis_data_from_node(node)
                data = dlis_data["data"].squeeze()
                nan_indexes = np.where(data == dlis_info["null_value"])
                data[nan_indexes] = ANP_880_2022_DEFAULT_NULL_VALUE

                channels.append(
                    logical_file.add_channel(
                        node.GetName(),
                        data=data,
                        units=dlis_info["units"],
                        origin_reference=int(node.GetAttribute(DLIS_ORIGIN_TAG)),
                        set_name=f"C_LF-{lf_header_id}",
                    )
                )
            logical_file.add_frame(
                name=frame,
                channels=channels,
                index_type=enums.FrameIndexType.BOREHOLE_DEPTH,
                origin_reference=int(nodes_dict[lf_header_id][frame][0].GetAttribute(DLIS_ORIGIN_TAG)),
                set_name=f"F_LF-{lf_header_id}",
            )

    # Then the nodes that had no frame (in principle, LAS and CSV-originated ones).
    # Their depths will define if they belong to the same frame or not

    for lf_header_id, nodes_lf in remaining_nodes.items():
        logical_file = get_logical_file(dlis_file, lf_header_id)
        first_node = nodes_lf[0]
        null_value = extract_dlis_info_from_node(first_node)["null_value"]
        if null_value:
            logical_file.add_parameter(
                name="ABSENT_VALUE",
                values=null_value,
                long_name="Value used to represent absent data - equivalent to LAS' NULL_VALUE",
            )

        for i, node in enumerate(nodes_lf):
            dlis_data, depths = _extract_dlis_data_from_node(node)
            dlis_info = extract_dlis_info_from_node(node)
            channels = []

            newDepths = True
            for idx, lst in enumerate(depths_remaining):
                if idx < i:
                    if lists_are_close(depths, lst):
                        newDepths = False
                        break

            if i == 0 or newDepths:
                dlis_data, depths = _extract_dlis_data_from_node(node)
                data = dlis_data["data"].squeeze()
                nan_indexes = np.where(data == dlis_info["null_value"])
                data[nan_indexes] = ANP_880_2022_DEFAULT_NULL_VALUE

                depth_channel = logical_file.add_channel(
                    name="MD",
                    long_name="Measured depth",
                    data=depths,
                    units=enums.Unit.METER,
                    origin_reference=int(node.GetAttribute(DLIS_ORIGIN_TAG)),
                    set_name=f"C_LF-{lf_header_id}",
                )

                data_channel = logical_file.add_channel(
                    node.GetName(),
                    data=data,
                    units=dlis_info["units"],
                    origin_reference=int(node.GetAttribute(DLIS_ORIGIN_TAG)),
                    set_name=f"C_LF-{lf_header_id}",
                )

                channels = [depth_channel, data_channel]
            else:
                if any(lists_are_close(depths, lst) for lst in depths_remaining):
                    continue

            for j, depths in enumerate(depths_remaining[lf_header_id]):
                if j <= i:
                    continue
                if len(depths_remaining[lf_header_id][i]) != len(depths):
                    continue
                subtr = np.subtract(depths_remaining[lf_header_id][i], depths)
                if len(depths_remaining[lf_header_id][i][abs(subtr) > depth_disparity_tolerance]) == 0:
                    dlis_data, depths = _extract_dlis_data_from_node(node)
                    dlis_info = extract_dlis_info_from_node(node)

                    data = dlis_data["data"].squeeze()
                    nan_indexes = np.where(data == dlis_info["null_value"])  # value
                    data[nan_indexes] = ANP_880_2022_DEFAULT_NULL_VALUE  # value

                    channels.append(
                        logical_file.add_channel(
                            node[j].GetName(),
                            data=data,
                            units=dlis_info["units"],
                            origin_reference=int(node.GetAttribute(DLIS_ORIGIN_TAG)),
                            set_name=f"C_LF-{lf_header_id}",
                        )
                    )

            logical_file.add_frame(
                dlis_info["frame_name"],
                channels=channels,
                index_type=enums.FrameIndexType.BOREHOLE_DEPTH,
                origin_reference=int(node.GetAttribute(DLIS_ORIGIN_TAG)),
                set_name=f"F_LF-{lf_header_id}",
            )


#  Using the well-id's open source dliswriter
def export_dlis(
    nodes_list,
    output_path,
    file_name_no_extension,
    output_progress_file_path,
    well_name="",
    field_name="",
    producer_name="",
    allow_multiple_wells=False,
):
    def try_copy_origin_attribute(node, nodes_dict, remaining_nodes, lf_header_id):
        for frame_tag, nodes in nodes_dict[lf_header_id].items():
            for node2 in nodes:
                if node is not node2:
                    if (
                        node2.GetAttribute(WELL_NAME_TAG) == node.GetAttribute(WELL_NAME_TAG)
                        and node2.GetAttribute(DLIS_LOGICAL_FILE_TAG) in origins_per_logical_file
                        and node2.GetAttribute(DLIS_ORIGIN_TAG)
                    ):
                        node.SetAttribute(DLIS_ORIGIN_TAG, node2.GetAttribute(DLIS_ORIGIN_TAG))
        for node2 in remaining_nodes[lf_header_id]:
            if node is not node2:
                if (
                    node2.GetAttribute(WELL_NAME_TAG) == node.GetAttribute(WELL_NAME_TAG)
                    and node2.GetAttribute(DLIS_LOGICAL_FILE_TAG) in origins_per_logical_file
                    and node2.GetAttribute(DLIS_ORIGIN_TAG)
                ):
                    node.SetAttribute(DLIS_ORIGIN_TAG, node2.GetAttribute(DLIS_ORIGIN_TAG))

    # Even though our code exports multiple wells correctly, GeoSlicer currently actively prevents it
    # because of usability
    if not allow_multiple_wells:
        assert_single_well(nodes_list)

    writer = DlisWriter()

    writer.create(
        output_path=output_path,
        file_name_no_extension=file_name_no_extension,
        output_progress_file_path=output_progress_file_path,
        field_name=field_name,
        producer_name=producer_name,
    )

    # * Adding (and/or creating) the necessary logical files to the dlis_file
    # * And preparing some dicts to help organizing nodes and other data

    nodes_dict = defaultdict(dict)  # {key: header_id, value: {key: frame, value: list of nodes}}
    remaining_nodes = {}  # nodes without FRAME tag. key: header_id, value: list of nodes
    depths_remaining = {}  # key: header_id, value: list of arrays of depths
    origins_per_logical_file = {}  # key: header_id, value: list of origins
    subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()

    for node in nodes_list:
        itemID = subjectHierarchyNode.GetItemByDataNode(node)  # the hierarchy item ID corresponding to our node
        logical_file_tag = subjectHierarchyNode.GetItemAttribute(itemID, DLIS_LOGICAL_FILE_TAG)
        header_id = logical_file_tag
        node.SetAttribute(DLIS_LOGICAL_FILE_TAG, logical_file_tag)
        frame_tag = subjectHierarchyNode.GetItemAttribute(itemID, DLIS_FRAME_TAG)

        node.SetAttribute(DLIS_FRAME_TAG, frame_tag)
        if frame_tag:
            if header_id not in nodes_dict:
                nodes_dict[header_id] = {}
                writer.dlisFile.add_logical_file(fh_id=header_id)
            if frame_tag not in nodes_dict[header_id]:
                nodes_dict[header_id][frame_tag] = []
            nodes_dict[header_id][frame_tag].append(node)
        else:  # Node originated from CSV or LAS
            if header_id not in remaining_nodes:
                remaining_nodes[header_id] = []
                writer.dlisFile.add_logical_file(fh_id=header_id)
            remaining_nodes[header_id].append(node)
            _, depths = _extract_dlis_data_from_node(node)
            # In write_nodes(..) we'll use the depths as a criteria to determine if remaining nodes
            # from a same logical file belong to the same frame or not
            depths_remaining[header_id] = []
            depths_remaining[header_id].append(depths)

    #
    # Adding (and/or creating) origins to their logical files, using their origin_references

    origins_per_logical_file = {}  # per logical file
    for lf_header_id, frame_and_nodes in nodes_dict.items():
        origins_per_logical_file[lf_header_id] = []
        for frame_tag, nodes in frame_and_nodes.items():
            for node in nodes:
                node_origin = node.GetAttribute(DLIS_ORIGIN_TAG)
                added_orig = None
                if node_origin:
                    if int(node_origin) not in origins_per_logical_file[lf_header_id]:
                        added_orig = add_origin(
                            writer, lf_header_id, getWellAttributeFromNode(node, WELL_NAME_TAG), int(node_origin)
                        )
                else:  # Shouldn't enter here, as nodes with frame info come from DLIS - so, should have origin info also
                    logger.info(
                        f"Node {node.GetName()} doesn't have origin attribute but has frame attribute. "
                        "Make sure it has correct data and attributes..."
                    )

                    # if node didn't have origin attribute, we assume one origin per well
                    # If another node has the same logical file and well, copy its origin
                    try_copy_origin_attribute(node, nodes_dict, remaining_nodes, lf_header_id)

                    # If still not found an origin, create one
                if not node.GetAttribute(DLIS_ORIGIN_TAG):
                    added_orig = add_origin(writer, lf_header_id, getWellAttributeFromNode(node, WELL_NAME_TAG), None)
                    node.SetAttribute(DLIS_ORIGIN_TAG, str(added_orig.origin_reference))

                if added_orig:
                    origins_per_logical_file[lf_header_id].append(added_orig.origin_reference)

    for lf_header_id in remaining_nodes:
        if lf_header_id not in origins_per_logical_file:
            origins_per_logical_file[lf_header_id] = []
        for node in remaining_nodes[lf_header_id]:
            node_origin = node.GetAttribute(DLIS_ORIGIN_TAG)
            added_orig = None
            if node_origin:  # shouldn't enter here - LAS or CSV -originated nodes
                logger.info(
                    f"Node {node.GetName()} doesn't have frame attribute but has origin attribute. "
                    "Make sure it has correct data and attributes..."
                )
                if int(node_origin) not in origins_per_logical_file:
                    added_orig = add_origin(
                        writer, lf_header_id, getWellAttributeFromNode(node, WELL_NAME_TAG), int(node_origin)
                    )
            else:
                # if node didn't have origin attribute, we assume one origin per well
                # If another node has the same logical file and well, copy its origin
                try_copy_origin_attribute(node, nodes_dict, remaining_nodes, lf_header_id)

                # If still not found an origin, create one
                if not node.GetAttribute(DLIS_ORIGIN_TAG):
                    added_orig = add_origin(writer, lf_header_id, getWellAttributeFromNode(node, WELL_NAME_TAG), None)
                    node.SetAttribute(DLIS_ORIGIN_TAG, str(added_orig.origin_reference))

            if added_orig:
                origins_per_logical_file[lf_header_id].append(added_orig.origin_reference)

    write_nodes(writer.dlisFile, nodes_dict, remaining_nodes, depths_remaining, 5e-02)

    writer.close()
    logger.info(f"All nodes wrote to {output_path}. File closed.")


def single_node_to_dlis(
    node,
    output_path,
    file_name_no_extension,
    output_progress_file_path,
    well_name="",
    file_set_name=None,
    file_type=None,
    well_id=None,
    field_name=None,
    producer_name=None,
    file_id=None,
):
    writer = DlisWriter()

    dlis_info = extract_dlis_info_from_node(node)

    writer.create(
        output_path=output_path,
        file_name_no_extension=file_name_no_extension,
        output_progress_file_path=output_progress_file_path,
        field_name=field_name,
        producer_name=producer_name,
    )

    writer.dlisFile.add_logical_file()

    # Add the absent value as a parameter in the metadata
    writer.dlisFile.logical_files[0].add_parameter(
        name="ABSENT_VALUE",
        values=dlis_info["null_value"],
        long_name="Value used to represent absent data - equivalent to LAS' NULL_VALUE",
    )

    origin = writer.dlisFile.logical_files[0].add_origin(
        name="ORIGIN", well_name=getWellAttributeFromNode(node, WELL_NAME_TAG)
    )

    writer.write_single_node(
        origin,
        node,
    )

    writer.close()
    logger.info(f"Node wrote to {output_path}. File closed.")
