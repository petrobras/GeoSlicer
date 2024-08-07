import re

import pandas as pd
import slicer

from ltrace.pore_networks.krel_result import KrelParameterParser
from ltrace.slicer.node_attributes import TableType
from ltrace.slicer_utils import dataframeFromTable, dataFrameToTableNode


def parameter_node_to_dict(parameterNode):
    df = dataframeFromTable(parameterNode)
    parameter_name_list = zip(list(df["Parameter name"]), list(df["Start"]), list(df["Stop"]), list(df["Steps"]))
    parameters_dict = {}
    parameter_parser = KrelParameterParser()
    for parameter_name, start, stop, steps in parameter_name_list:
        parameter = parameter_parser.get_input_name(parameter_name)
        if parameter is None:
            continue

        if parameter not in parameters_dict:
            parameters_dict[parameter] = {}
        parameters_dict[parameter]["start"] = start
        parameters_dict[parameter]["stop"] = stop
        parameters_dict[parameter]["steps"] = steps

    return parameters_dict


def dict_to_parameter_node(parameter_dict, node_name, parent_node=None, update_current_node=False):
    return dataframe_to_parameter_node(
        parameters_dict_to_dataframe(parameter_dict), node_name, parent_node, update_current_node
    )


def parameters_dict_to_dataframe(parameter_dict: dict) -> pd.DataFrame:
    parameter_names = []
    parameter_start = []
    parameter_stop = []
    parameter_steps = []
    for parameter, values in parameter_dict.items():
        parameter_names.append(parameter)
        parameter_start.append(values["start"])
        parameter_stop.append(values["stop"])
        parameter_steps.append(values["steps"])

    df = pd.DataFrame(
        {
            "Parameter name": parameter_names,
            "Start": parameter_start,
            "Stop": parameter_stop,
            "Steps": parameter_steps,
        }
    )
    return df


def dataframe_to_parameter_node(input_values_df, node_name, parent_node=None, update_current_node=False):
    if update_current_node:
        slicer.mrmlScene.RemoveNode(parent_node)
        slicer.app.processEvents()

    parameterNode = dataFrameToTableNode(input_values_df)
    newParameterNodeName = slicer.mrmlScene.GenerateUniqueName(node_name) if not update_current_node else node_name
    parameterNode.SetName(newParameterNodeName)
    subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    if parent_node:
        itemTreeId = subjectHierarchyNode.GetItemByDataNode(parent_node)
        parentItemId = subjectHierarchyNode.GetItemParent(itemTreeId)
        newParentItemId = subjectHierarchyNode.GetItemParent(parentItemId)
        if newParentItemId > 0:
            parentItemId = newParentItemId
    else:
        parentItemId = subjectHierarchyNode.GetSceneItemID()
    subjectHierarchyNode.CreateItem(parentItemId, parameterNode)
    parameterNode.SetAttribute(TableType.name(), TableType.PNM_INPUT_PARAMETERS.value)
    return parameterNode
