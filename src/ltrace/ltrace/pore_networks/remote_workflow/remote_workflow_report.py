import re
import warnings

import numpy as np
import pandas as pd
import slicer
import vtk

from ltrace.slicer.data_utils import dataFrameToTableNode

WELL_SAMPLE_REGEX = re.compile(
    r"(?P<well>\w+)_(?P<sample_name>\w+)_(?P<condition>\w+)_(?P<sample_type>\w+)_(?P<resolution>\d+)nm"
)

PREFIX_SUFFIXES = (
    "_Two_Phase_PN_Simulation",
    "_Single_Phase_PN_Simulation_multiangle",
    "_Single_Phase_PN_Simulation",
    "_Pore_Network",
)


def _find_descendant_tables_by_type(sh_node, start_item_id, table_type):
    """Recursively searches for MRML table nodes with a specific table_type under start_item_id."""
    matching_nodes = []
    stack = [start_item_id]
    while stack:
        current_id = stack.pop()
        data_node = sh_node.GetItemDataNode(current_id)
        if data_node is not None and data_node.IsA("vtkMRMLTableNode"):
            if data_node.GetAttribute("table_type") == table_type:
                matching_nodes.append((current_id, data_node))

        children_ids = vtk.vtkIdList()
        sh_node.GetItemChildren(current_id, children_ids)
        for i in range(children_ids.GetNumberOfIds()):
            stack.append(children_ids.GetId(i))
    return matching_nodes


def _find_descendant_table_by_type(sh_node, start_item_id, table_type):
    """Finds the first descendant table node matching table_type under start_item_id."""
    stack = [start_item_id]
    while stack:
        current_id = stack.pop()
        data_node = sh_node.GetItemDataNode(current_id)
        if data_node is not None and data_node.IsA("vtkMRMLTableNode"):
            if data_node.GetAttribute("table_type") == table_type:
                return data_node

        children_ids = vtk.vtkIdList()
        sh_node.GetItemChildren(current_id, children_ids)
        for i in range(children_ids.GetNumberOfIds()):
            stack.append(children_ids.GetId(i))
    return None


def _parse_well_and_sample(name):
    match = WELL_SAMPLE_REGEX.search(name)
    if match:
        return match.group("well"), match.group("sample_name")
    return None, name


def _prefix_from_root_dir_name(root_dir_name):
    for suffix in PREFIX_SUFFIXES:
        if root_dir_name.endswith(suffix):
            return root_dir_name[: -len(suffix)]
    return root_dir_name


def _get_resolution(pore_table_node):
    if pore_table_node is None:
        return None
    spacing = [pore_table_node.GetAttribute(a) for a in ("x_spacing", "y_spacing", "z_spacing")]
    if any(value is None for value in spacing):
        return None
    return min(float(value) for value in spacing)


def _get_porosity(summary_table_node):
    if summary_table_node is None:
        return None
    try:
        summary_df = slicer.util.dataframeFromTable(summary_table_node)
        for property_name in ("Pore Total Porosity (%)", "Input Volume Porosity (%)"):
            row = summary_df.loc[summary_df["Property"] == property_name]
            if not row.empty:
                return float(row["Value"].iloc[0])
    except Exception:
        pass
    return None


def _get_permeability(permeability_table_node):
    if permeability_table_node is None:
        return None
    try:
        permeability_df = slicer.util.dataframeFromTable(permeability_table_node)
        return float(permeability_df.iloc[0, 0])
    except Exception:
        pass
    return None


def _get_contact_angle(krel_row):
    """
    Retrieves equilibrium contact angle used in Krel simulation.
    It is stored in the Krel_results table with the prefix 'input-'.
    """
    if "input-equil_contact_angle" in krel_row.index:
        return krel_row.get("input-equil_contact_angle")
    angle_min = krel_row.get("input-equil_contact_angle_min")
    angle_max = krel_row.get("input-equil_contact_angle_max")
    if angle_min is not None and angle_max is not None:
        return (float(angle_min) + float(angle_max)) / 2
    return None


def generate_remote_workflow_report(workflow_folder_item, output_table_name="Remote_Workflow_Report"):
    """
    Scans table nodes strictly inside workflow_folder_item and creates/updates a consolidated report.
    """
    if not workflow_folder_item:
        return None

    # Scope warning suppression strictly to this function call
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=pd.errors.PerformanceWarning)

        sh_node = slicer.mrmlScene.GetSubjectHierarchyNode()

        # Search only inside the current workflow folder item branch
        krel_entries = _find_descendant_tables_by_type(sh_node, workflow_folder_item, "krel_simulation_results")

        rows = []
        for krel_item_id, krel_results_node in krel_entries:
            parent_id = sh_node.GetItemParent(krel_item_id)
            grandparent_id = sh_node.GetItemParent(parent_id) if parent_id else None

            # Scope search hierarchy for associated summary/pore/permeability tables
            search_scopes = [parent_id, grandparent_id, workflow_folder_item]
            pore_table_node = None
            summary_table_node = None
            permeability_table_node = None

            for scope_id in search_scopes:
                if scope_id and scope_id != 0:
                    if pore_table_node is None:
                        pore_table_node = _find_descendant_table_by_type(sh_node, scope_id, "pore_table")
                    if summary_table_node is None:
                        summary_table_node = _find_descendant_table_by_type(sh_node, scope_id, "summary_table")
                    if permeability_table_node is None:
                        permeability_table_node = _find_descendant_table_by_type(
                            sh_node, scope_id, "permeability_tensor"
                        )

            root_dir_name = sh_node.GetItemName(parent_id) if parent_id else ""
            prefix = _prefix_from_root_dir_name(root_dir_name)
            well, sample = _parse_well_and_sample(prefix)

            resolution = _get_resolution(pore_table_node)
            porosity = _get_porosity(summary_table_node)
            permeability = _get_permeability(permeability_table_node)

            krel_df = slicer.util.dataframeFromTable(krel_results_node)
            for _, krel_row in krel_df.iterrows():
                swr = krel_row.get("result-swr")
                rows.append(
                    {
                        "Well": well,
                        "Sample": sample,
                        "Resolution": resolution,
                        "Porosity": porosity,
                        "Permeability": permeability,
                        "Contact Angle": _get_contact_angle(krel_row),
                        "Swi": krel_row.get("result-swi"),
                        "Sor": (1 - swr) if swr is not None and pd.notna(swr) else None,
                        "Kro@Swi": krel_row.get("result-kro_swi"),
                        "Krw@Sor": krel_row.get("result-krw_swr"),
                        "Amott": krel_row.get("result-amott"),
                        "USBM": krel_row.get("result-usbm"),
                    }
                )

        report_df = pd.DataFrame(rows)

        # Re-use existing table node if present, otherwise create a new one inside the workflow folder
        report_item_id = sh_node.GetItemChildWithName(workflow_folder_item, output_table_name)
        if report_item_id != 0:
            report_table_node = sh_node.GetItemDataNode(report_item_id)
            if report_table_node:
                dataFrameToTableNode(report_df, report_table_node, replace=True)
            else:
                report_table_node = dataFrameToTableNode(report_df)
                report_table_node.SetName(output_table_name)
                report_item_id = sh_node.CreateItem(workflow_folder_item, report_table_node)
        else:
            report_table_node = dataFrameToTableNode(report_df)
            report_table_node.SetName(output_table_name)
            report_item_id = sh_node.CreateItem(workflow_folder_item, report_table_node)

        report_table_node.SetAttribute("table_type", "pnm_workflow_report")
        return report_table_node
