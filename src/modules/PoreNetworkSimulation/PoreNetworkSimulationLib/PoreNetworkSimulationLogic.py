import vtk

import random
import string
import itertools
import json
import logging
import os
import re
import shutil
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit
import slicer
import pickle

from ltrace.algorithms.common import (
    generate_equidistant_points_on_sphere,
    points_are_below_plane,
)
from ltrace.pore_networks.functions import is_multiscale_geo, geo2pnf, geo2spy
from ltrace.pore_networks.vtk_utils import (
    create_flow_model,
    create_permeability_sphere,
)
from ltrace.slicer import helpers
from ltrace.slicer.binary_node import createBinaryNode, getBinary
from ltrace.slicer.node_attributes import TableType
from ltrace.slicer_utils import (
    LTracePluginLogic,
    dataFrameToTableNode,
    hide_nodes_of_type,
)

from .constants import *
from .utils import save_parameters_to_table

NUM_THREADS = 48


def createFolder(name, inputTable):  # TODO usar no lugar dos folderTree.CreateFolder
    folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    itemTreeId = folderTree.GetItemByDataNode(inputTable)
    parentItemId = folderTree.GetItemParent(folderTree.GetItemParent(itemTreeId))
    rootDir = folderTree.CreateFolderItem(parentItemId, name)
    folderTree.SetItemExpanded(rootDir, False)
    folderTree.ItemModified(rootDir)
    return folderTree, rootDir


def createTableNode(name, tableTypeAttribute):
    table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
    table.SetName(name)
    table.SetAttribute("table_type", tableTypeAttribute)
    return table


def listFilesInDir(directory):
    files = []
    for filename in os.listdir(directory):
        filepath = os.path.join(directory, filename)
        if os.path.isfile(filepath):
            files.append(filepath)
    return files


def listFilesRegex(directory, regex_pattern=None):
    matching_files = []
    regex = re.compile(regex_pattern)
    for root, dirs, files in os.walk(directory):
        for file in files:
            if regex.match(file):
                matching_files.append(os.path.join(root, file))
    return matching_files


def readPolydata(filename):
    reader = vtk.vtkPolyDataReader()
    reader.SetFileName(filename)
    reader.Update()

    polydata = reader.GetOutput()
    return polydata


def calculateTransformNodeFromVolume(tableNode):
    origin_attr = tableNode.GetAttribute("origin")
    origin = [float(val) for val in origin_attr.split(";")]

    transformMatrix = vtk.vtkMatrix4x4()
    transformMatrix.SetElement(0, 3, origin[0])
    transformMatrix.SetElement(1, 3, origin[1])
    transformMatrix.SetElement(2, 3, origin[2])

    transformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode")
    transformNode.SetMatrixTransformToParent(transformMatrix)

    return transformNode


class OnePhaseSimulationLogic(LTracePluginLogic):
    def __init__(self, parent, progressBar):
        LTracePluginLogic.__init__(self, parent)
        self.cliNode = None
        self.progressBar = progressBar
        self.prefix = None
        self.rootDir = None
        self.results = {}
        self.caDistributionTableDir = None
        self.visualization = False

    def run_1phase(self, inputTable, params, prefix, callback, wait=False):
        self.inputTable = inputTable
        self.params = params
        self.cwd = Path(slicer.util.tempDirectory())
        self.callback = callback
        self.prefix = prefix
        self.visualization = params["visualization"]
        params["advanced visualization"] = False

        refNode = inputTable.GetNodeReference("PoresLabelMap")
        ijktorasDirections = np.zeros([3, 3])
        refNode.GetIJKToRASDirections(ijktorasDirections)
        self.params["ijktoras"] = [ijktorasDirections[i, i] for i in range(3)]

        hash = "".join(
            random.choices(
                string.ascii_letters,
                k=22,
            )
        )
        directory_name = f"pnm_cli_{hash}"
        self.temp_dir = f"{slicer.app.temporaryPath}/{directory_name}"
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        os.mkdir(self.temp_dir)

        cliParams = {
            "model": "onePhase",
            "cwd": str(self.cwd),
            "tempDir": self.temp_dir,
        }

        hide_nodes_of_type("vtkMRMLModelNode")

        pore_network = geo2spy(inputTable)

        dict_file = open(str(self.cwd / "pore_network.dict"), "wb")
        pickle.dump(pore_network, dict_file)
        dict_file.close()

        del self.params["subresolution function"]
        del self.params["subresolution function call"]

        self.params["sizes"] = {
            "x": float(inputTable.GetAttribute("x_size")) / 10,
            "y": float(inputTable.GetAttribute("y_size")) / 10,
            "z": float(inputTable.GetAttribute("z_size")) / 10,
        }  # values in cm

        with open(str(self.cwd / "params_dict.json"), "w") as file:
            json.dump(self.params, file)

        self.cliNode = slicer.cli.run(
            slicer.modules.porenetworksimulationcli, None, cliParams, wait_for_completion=wait
        )
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.onePhaseCLICallback)

    def cancel(self):
        if self.cliNode is None:
            return
        self.cliNode.Cancel()

    def onePhaseCLICallback(self, caller, event):
        if caller is None:
            self.cliNode = None
            return
        if self.cliNode is None:
            return

        status = caller.GetStatusString()
        if status in ["Completed", "Cancelled"]:
            logging.info(status)
            del self.cliNode
            self.cliNode = None
            if status == "Completed":
                time.sleep(1)  # TODO como resolve sem precisar?
                self.onFinish()
            if not self.params["keep_temporary"]:
                shutil.rmtree(self.cwd)

            self.callback(True)

    def onFinish(self):
        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
        itemTreeId = folderTree.GetItemByDataNode(self.inputTable)
        parentItemId = folderTree.GetItemParent(folderTree.GetItemParent(itemTreeId))
        if self.params["simulation type"] == "Single orientation":
            self.rootDir = folderTree.CreateFolderItem(parentItemId, f"{self.prefix}_Single_Phase_PN_Simulation")
        elif self.params["simulation type"] == "Multiple orientations":
            self.rootDir = folderTree.CreateFolderItem(
                parentItemId, f"{self.prefix}_Single_Phase_PN_Simulation_multiangle"
            )
        folderTree.SetItemExpanded(self.rootDir, False)

        parametersNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTextNode", "simulation_parameters")
        parametersNode.SetText(json.dumps(self.params, indent=4))
        parametersNode.SetAttribute(TableType.name(), TableType.PNM_INPUT_PARAMETERS.value)
        folderTree.CreateItem(self.rootDir, parametersNode)

        if self.params["simulation type"] == ONE_ANGLE:
            self.createTableNodes()
            if self.visualization:
                self.createVisualizationModels()
        elif self.params["simulation type"] == MULTI_ANGLE:
            self.createVisualizationMultiAngleModels()
            self.createVisualizationMultiAngleSphereModels()

    def createTableNodes(self):
        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()

        flow_rate_table_name = slicer.mrmlScene.GenerateUniqueName("flow_rate")
        flow_rate_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", flow_rate_table_name)
        flow_rate_table.SetAttribute("table_type", "flow_rate_tensor")
        flow_rate_df = pd.read_pickle(str(self.cwd / "flow.pd"))
        _ = dataFrameToTableNode(flow_rate_df, flow_rate_table)
        _ = folderTree.CreateItem(self.rootDir, flow_rate_table)

        permeability_table_name = slicer.mrmlScene.GenerateUniqueName("permeability")
        permeability_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", permeability_table_name)
        permeability_table.SetAttribute("table_type", "permeability_tensor")
        permeability_df = pd.read_pickle(str(self.cwd / "permeability.pd"))
        _ = dataFrameToTableNode(permeability_df, permeability_table)
        _ = folderTree.CreateItem(self.rootDir, permeability_table)

        self.results = {
            "permeability": permeability_table.GetID(),
            "flow_rate": flow_rate_table.GetID(),
        }

    def createVisualizationModels(self):
        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
        visualization_dir = folderTree.CreateFolderItem(self.rootDir, "Visualization models")
        folderTree.SetItemExpanded(visualization_dir, False)
        folderTree.ItemModified(visualization_dir)

        transformNode = calculateTransformNodeFromVolume(self.inputTable)

        with open(f"{self.temp_dir}/return_params.json", "r") as file:
            minmax = json.load(file)

        minmax_dict = {}
        for line in minmax:
            key = (line["inlet"], line["outlet"])
            val = {"min": line["min"], "max": line["max"]}
            minmax_dict[key] = val

        for inlet, outlet in ((0, 0), (1, 1), (2, 2)):
            key = (inlet, outlet)
            if key not in minmax_dict.keys():
                continue
            subDir = folderTree.CreateFolderItem(
                visualization_dir, f"{['z', 'y', 'x'][inlet]}-{['z', 'y', 'x'][outlet]} folder"
            )

            visualization_models = [
                ("pore_pressure", "Pore Pressure"),
                ("throat_flow_rate", "Throat Flow Rate"),
                ("border_pores", "Pore Inlets and Outlets"),
            ]
            if self.params["advanced visualization"] == True:
                visualization_models.append(("resolved_pore_pressure", "Resolved Pore Pressure"))
                visualization_models.append(("unresolved_pore_pressure", "Unresolved Pore Pressure"))
            model_node = {}
            for prefix, name in visualization_models:
                file = f"{self.temp_dir}/{prefix}_{inlet}_{outlet}.vtk"
                polydata = readPolydata(file)
                model_node[prefix] = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", name)
                model_node[prefix].SetAndObservePolyData(polydata)
                model_node[prefix].CreateDefaultDisplayNodes()
                model_node[prefix].SetAndObserveTransformNodeID(transformNode.GetID())
                slicer.vtkSlicerTransformLogic().hardenTransform(model_node[prefix])
                model_display = model_node[prefix].GetDisplayNode()
                model_node[prefix].SetDisplayVisibility(True)
                model_display.SetScalarVisibility(True)
                model_display.SetActiveScalarName("value")
                folderTree.CreateItem(subDir, model_node[prefix])

            model_node["border_pores"].SetDisplayVisibility(False)

            model_node["pore_pressure"].GetDisplayNode().SetAndObserveColorNodeID(
                "vtkMRMLColorTableNodeFileViridis.txt"
            )
            model_node["throat_flow_rate"].GetDisplayNode().SetAndObserveColorNodeID("vtkMRMLColorTableNodeWarmTint1")
            model_node["border_pores"].GetDisplayNode().SetAndObserveColorNodeID("vtkMRMLColorTableNodeFileViridis.txt")
            # model_node["throat_flow_rate"].GetDisplayNode().SetScalarRangeFlag(0)
            # min_throat = minmax_dict[key]["min"]
            # max_throat = minmax_dict[key]["max"]
            # model_node["throat_flow_rate"].GetDisplayNode().SetScalarRange(min_throat, max_throat)
            model_node["throat_flow_rate"].GetDisplayNode().SetScalarRangeFlag(1)
            model_node["throat_flow_rate"].GetDisplayNode().SetActiveScalarName("log value array")

            # if (inlet + outlet) != 0:  # by default only display z-z results
            #    model_node["pore_pressure"].SetDisplayVisibility(False)
            #    model_node["throat_flow_rate"].SetDisplayVisibility(False)

            folderTree.SetDisplayVisibilityForBranch(subDir, False)
            folderTree.SetItemExpanded(subDir, False)
            folderTree.ItemModified(subDir)

            # Create Table nodes with PN properties
            df_pores = pd.read_pickle(f"{self.temp_dir}/pores_{inlet}_{outlet}.pd")
            df_throats = pd.read_pickle(f"{self.temp_dir}/throats_{inlet}_{outlet}.pd")
            poreOutputTableName = slicer.mrmlScene.GenerateUniqueName(f"{self.prefix}_pores_project")
            poreOutputTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", poreOutputTableName)
            poreOutputTable.SetAttribute("table_type", "project_pore_table")
            throatOutputTableName = slicer.mrmlScene.GenerateUniqueName(f"{self.prefix}_throat_project")
            throatOutputTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", throatOutputTableName)
            throatOutputTable.SetAttribute("table_type", "project_throat_table")
            _ = dataFrameToTableNode(df_pores, poreOutputTable)
            _ = dataFrameToTableNode(df_throats, throatOutputTable)
            _ = folderTree.CreateItem(subDir, poreOutputTable)
            _ = folderTree.CreateItem(subDir, throatOutputTable)

            boundingbox = {
                "xmin": df_pores["pore.coords_0"].min(),
                "xmax": df_pores["pore.coords_1"].max(),
                "ymin": df_pores["pore.coords_2"].min(),
                "ymax": df_pores["pore.coords_0"].max(),
                "zmin": df_pores["pore.coords_1"].min(),
                "zmax": df_pores["pore.coords_2"].max(),
            }  # mm
            bb_sizes = {i: 0.1 * (boundingbox[f"{i}max"] - boundingbox[f"{i}min"]) for i in "xyz"}

            vector_polydata = self._create_vector_map(df_pores, df_throats, sizes=bb_sizes)
            vector_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "Vector glyph")
            vector_node.SetAndObservePolyData(vector_polydata)
            vector_node.CreateDefaultDisplayNodes()
            vector_node.SetAndObserveTransformNodeID(transformNode.GetID())
            slicer.vtkSlicerTransformLogic().hardenTransform(vector_node)
            model_display = vector_node.GetDisplayNode()
            vector_node.SetDisplayVisibility(True)
            model_display.SetScalarVisibility(True)
            # model_display.SetActiveScalarName("value")
            folderTree.CreateItem(subDir, vector_node)

            watershed_id = self.inputTable.GetAttribute("watershed_node_id")
            if watershed_id is not None and (self.params["advanced visualization"] == True):
                watershed_node = slicer.mrmlScene.GetNodeByID(watershed_id)
                watershed_array = slicer.util.arrayFromVolume(watershed_node)
                resolved_array, unresolved_array = self._create_volumetric_pressure(
                    df_pores, df_throats, watershed_array
                )

                v = vtk.vtkMatrix4x4()
                watershed_node.GetIJKToRASDirectionMatrix(v)

                resolved_pressure_node = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLScalarVolumeNode", "Resolved pressure"
                )
                resolved_pressure_node.CreateDefaultDisplayNodes()
                slicer.util.updateVolumeFromArray(resolved_pressure_node, resolved_array)
                resolved_pressure_node.SetSpacing(watershed_node.GetSpacing())
                resolved_pressure_node.SetOrigin(watershed_node.GetOrigin())
                resolved_pressure_node.SetIJKToRASDirectionMatrix(v)
                folderTree.CreateItem(subDir, resolved_pressure_node)

                unresolved_pressure_node = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLScalarVolumeNode", "Unresolved pressure"
                )
                unresolved_pressure_node.CreateDefaultDisplayNodes()
                slicer.util.updateVolumeFromArray(unresolved_pressure_node, unresolved_array)
                unresolved_pressure_node.SetSpacing(watershed_node.GetSpacing())
                unresolved_pressure_node.SetOrigin(watershed_node.GetOrigin())
                unresolved_pressure_node.SetIJKToRASDirectionMatrix(v)
                folderTree.CreateItem(subDir, unresolved_pressure_node)

        slicer.mrmlScene.RemoveNode(transformNode)
        slicer.app.processEvents()

    def createVisualizationMultiAngleModels(self):
        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
        visualization_dir = folderTree.CreateFolderItem(self.rootDir, "Visualization models")
        folderTree.SetItemExpanded(visualization_dir, False)
        folderTree.ItemModified(visualization_dir)

        with open(f"{self.temp_dir}/return_params.json", "r") as file:
            return_params = json.load(file)

        minmax = return_params["minmax"]
        number_surface_points = len(minmax)
        for i in range(number_surface_points):
            index = minmax[i]["index"]
            subDir = folderTree.CreateFolderItem(visualization_dir, f"{index} folder")

            model_node = {}
            for prefix, name in [
                ("pore_pressure", "Pore Pressure"),
                ("throat_flow_rate", "Throat Flow Rate"),
                ("border_pores", "Pore Inlets and Outlets"),
            ]:
                file = f"{self.temp_dir}/{prefix}_{index}.vtk"
                polydata = readPolydata(file)
                model_node[prefix] = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", name)
                model_node[prefix].SetAndObservePolyData(polydata)
                model_node[prefix].CreateDefaultDisplayNodes()
                model_display = model_node[prefix].GetDisplayNode()
                model_node[prefix].SetDisplayVisibility(True)
                model_display.SetScalarVisibility(True)
                folderTree.CreateItem(subDir, model_node[prefix])

            folderTree.SetDisplayVisibilityForBranch(subDir, False)
            folderTree.SetItemExpanded(subDir, False)
            folderTree.ItemModified(subDir)

            model_node["border_pores"].SetDisplayVisibility(False)

            model_node["pore_pressure"].GetDisplayNode().SetAndObserveColorNodeID(
                "vtkMRMLColorTableNodeFileViridis.txt"
            )
            model_node["throat_flow_rate"].GetDisplayNode().SetAndObserveColorNodeID("vtkMRMLColorTableNodeWarmTint1")
            model_node["border_pores"].GetDisplayNode().SetAndObserveColorNodeID("vtkMRMLColorTableNodeFileViridis.txt")
            model_node["throat_flow_rate"].GetDisplayNode().SetScalarRangeFlag(0)
            min_throat = minmax[i]["min"]
            max_throat = minmax[i]["max"]
            model_node["throat_flow_rate"].GetDisplayNode().SetScalarRange(min_throat, max_throat)

            model_node["pore_pressure"].SetDisplayVisibility(False)
            model_node["throat_flow_rate"].SetDisplayVisibility(False)

    def createVisualizationMultiAngleSphereModels(self):
        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()

        sphere_dir = folderTree.CreateFolderItem(self.rootDir, "Visualization sphere")
        folderTree.SetItemExpanded(sphere_dir, False)

        with open(f"{self.temp_dir}/return_params.json", "r") as file:
            return_params = json.load(file)

        multiangle_model_range = return_params["multiangle_model_range"]
        file = f"{self.temp_dir}/model.vtk"
        model_polydata = readPolydata(file)
        model_node_name = slicer.mrmlScene.GenerateUniqueName("multiangle_model")
        model_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", model_node_name)
        model_node.CreateDefaultDisplayNodes()
        model_display = model_node.GetDisplayNode()
        model_node.SetDisplayVisibility(True)
        model_display.SetScalarVisibility(1)
        model_display.SetScalarRange(0, multiangle_model_range)
        model_display.SetAndObserveColorNodeID(slicer.util.getNode("Viridis").GetID())
        model_display.SetScalarRangeFlag(0)
        model_display.SetScalarRange(0, multiangle_model_range)
        # model_display.SetColor(0.1, 0.1, 0.9)
        # model_display.SetAmbient(0.15)
        # model_display.SetDiffuse(0.85)
        model_node.SetAndObservePolyData(model_polydata)

        file = f"{self.temp_dir}/sphere.vtk"
        sphere_polydata = readPolydata(file)
        sphere_node_name = slicer.mrmlScene.GenerateUniqueName("multiangle_sphere_model")
        sphere_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", sphere_node_name)
        sphere_node.CreateDefaultDisplayNodes()
        sphere_node.SetAndObservePolyData(sphere_polydata)
        sphere_node.SetDisplayVisibility(True)
        sphere_display = sphere_node.GetDisplayNode()
        sphere_display.SetColor(0.63, 0.63, 0.63)

        file = f"{self.temp_dir}/plane.vtk"
        plane_polydata = readPolydata(file)
        plane_node_name = slicer.mrmlScene.GenerateUniqueName("multiangle_plane_model")
        plane_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", plane_node_name)
        plane_node.CreateDefaultDisplayNodes()
        plane_node.SetAndObservePolyData(plane_polydata)
        plane_node.SetDisplayVisibility(True)
        plane_display = plane_node.GetDisplayNode()
        plane_display.SetOpacity(0.3)

        file = f"{self.temp_dir}/arrow.vtk"
        arrow_polydata = readPolydata(file)
        arrow_node_name = slicer.mrmlScene.GenerateUniqueName("multiangle_arrow_model")
        arrow_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", arrow_node_name)
        arrow_node.CreateDefaultDisplayNodes()
        arrow_node.SetAndObservePolyData(arrow_polydata)
        arrow_node.SetDisplayVisibility(True)
        arrow_display = arrow_node.GetDisplayNode()
        arrow_display.SetColor(0, 0, 1)
        arrow_display.SetAmbient(0.15)
        arrow_display.SetDiffuse(0.85)

        self.results = {
            "model": model_node.GetID(),
            "sphere": sphere_node.GetID(),
            "plane": plane_node.GetID(),
            "arrow": arrow_node.GetID(),
            "direction": np.array(return_params["direction"]),
            "permeabilities": np.array(return_params["permeabilities"]),
        }

        _ = folderTree.CreateItem(sphere_dir, model_node)
        _ = folderTree.CreateItem(sphere_dir, sphere_node)
        _ = folderTree.CreateItem(sphere_dir, plane_node)
        _ = folderTree.CreateItem(sphere_dir, arrow_node)

    def _create_vector_map(
        self,
        df_pores,
        df_throats,
        sizes,
        IJKTORAS=(-1, -1, 1),
    ):

        if sizes:
            offset = [10 * sizes[axis] if IJKTORAS[i] < 0 else 0 for i, axis in enumerate(["x", "y", "z"])]
        else:
            offset = [0 for i, axis in enumerate(["x", "y", "z"])]
        # pn_throats["throat.conns_0"]
        # pn_throats["throat.conns_1"]
        # pn_throats["throat.flow"]
        # throat.global_peak_0, throat.conns_0, pore.geometric_centroid_0

        points = vtk.vtkPoints()
        # for i in range(len(df_throats["throat.global_peak_0"])):
        #     points.InsertNextPoint((
        #         df_throats["throat.global_peak_0"][i],
        #         df_throats["throat.global_peak_1"][i],
        #         df_throats["throat.global_peak_2"][i],
        #     ))

        flow_array = vtk.vtkFloatArray()
        flow_array.SetName("flow")

        min_flow = min(df_throats["throat.flow"])
        max_flow = max(abs(df_throats["throat.flow"]))
        max_radius = min(sizes.values()) * 2
        direction_array = vtk.vtkFloatArray()
        direction_array.SetNumberOfComponents(3)
        direction_array.SetName("Direction vector array")
        for i in range(len(df_throats["throat.conns_0"])):
            i0 = df_throats["throat.conns_0"][i]
            i1 = df_throats["throat.conns_1"][i]
            flow = df_throats["throat.flow"][i]
            x0 = df_pores["pore.coords_0"][i0] * IJKTORAS[0] + offset[0]
            y0 = df_pores["pore.coords_1"][i0] * IJKTORAS[1] + offset[1]
            z0 = df_pores["pore.coords_2"][i0] * IJKTORAS[2] + offset[2]
            x1 = df_pores["pore.coords_0"][i1] * IJKTORAS[0] + offset[0]
            y1 = df_pores["pore.coords_1"][i1] * IJKTORAS[1] + offset[1]
            z1 = df_pores["pore.coords_2"][i1] * IJKTORAS[2] + offset[2]
            xd = x1 - x0
            yd = y1 - y0
            zd = z1 - z0
            length = np.sqrt(xd**2 + yd**2 + zd**2)
            xn = xd / length
            yn = yd / length
            zn = zd / length
            scaled_flow = flow / max_flow

            direction_array.InsertNextTuple(
                (
                    (xn * length) / 2,
                    (yn * length) / 2,
                    (zn * length) / 2,
                )
            )
            points.InsertNextPoint(
                (
                    ((x0 + x1) - (xn * length / 2)) / 2,
                    ((y0 + y1) - (yn * length / 2)) / 2,
                    ((z0 + z1) - (zn * length / 2)) / 2,
                )
            )
            flow_array.InsertNextValue(abs(scaled_flow))

        # Create a PolyData to hold the points and vectors
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(points)
        polydata.GetPointData().SetVectors(direction_array)
        polydata.GetPointData().AddArray(flow_array)

        # Create an arrow source
        arrow_source = vtk.vtkArrowSource()

        # Glyph to draw an arrow at each point, scaled & oriented by vector
        glyph = vtk.vtkGlyph3D()
        glyph.SetSourceConnection(arrow_source.GetOutputPort())
        glyph.SetInputData(polydata)
        glyph.SetVectorModeToUseVector()
        glyph.SetScaleModeToScaleByVector()
        glyph.OrientOn()
        glyph.SetScaleFactor(1)  # Adjust arrow size
        glyph.Update()

        # mapper = vtk.vtkPolyDataMapper()
        # mapper.SetInputConnection(glyph.GetOutputPort())

        arrow_glyph3D_with_normals = vtk.vtkPolyDataNormals()
        arrow_glyph3D_with_normals.SetSplitting(False)
        arrow_glyph3D_with_normals.SetInputConnection(glyph.GetOutputPort())
        arrow_glyph3D_with_normals.Update()

        normals = arrow_glyph3D_with_normals.GetOutput().GetPointData().GetNormals()
        normals.SetName("Normals")

        #### New approach

        # Append all arrows here
        append = vtk.vtkAppendPolyData()

        # We will also collect scalars manually
        flow_values = vtk.vtkFloatArray()
        flow_values.SetName("flow")

        for i in range(len(df_throats["throat.conns_0"])):
            i0 = df_throats["throat.conns_0"][i]
            i1 = df_throats["throat.conns_1"][i]
            flow = df_throats["throat.flow"][i]
            x0 = df_pores["pore.coords_0"][i0] * IJKTORAS[0] + offset[0]
            y0 = df_pores["pore.coords_1"][i0] * IJKTORAS[1] + offset[1]
            z0 = df_pores["pore.coords_2"][i0] * IJKTORAS[2] + offset[2]
            x1 = df_pores["pore.coords_0"][i1] * IJKTORAS[0] + offset[0]
            y1 = df_pores["pore.coords_1"][i1] * IJKTORAS[1] + offset[1]
            z1 = df_pores["pore.coords_2"][i1] * IJKTORAS[2] + offset[2]
            xd = x1 - x0
            yd = y1 - y0
            zd = z1 - z0
            length = np.sqrt(xd**2 + yd**2 + zd**2)
            xn = xd / length
            yn = yd / length
            zn = zd / length
            scaled_flow = abs(flow / max_flow) ** (1 / 2) * max_radius
            position = np.array(
                (
                    (x0 + 0.05 * (x1 - x0)),
                    (y0 + 0.05 * (y1 - y0)),
                    (z0 + 0.05 * (z1 - z0)),
                )
            )

            # Create arrow source (unit arrow along +X)
            arrow = vtk.vtkArrowSource()
            arrow.SetTipResolution(10)
            arrow.SetShaftResolution(10)
            if flow < 0:
                arrow.InvertOn()
            arrow.Update()

            # Transform
            transform = vtk.vtkTransform()
            transform.PostMultiply()

            if scaled_flow > (length / 2):
                scaled_flow = length / 2
            # Scale: X axis = length, Y/Z axes = radius
            transform.Scale(length * 0.9, scaled_flow, scaled_flow)

            # Rotate arrow (default is along +X axis in vtkArrowSource)
            ref_dir = np.array([1, 0, 0])
            axis = np.cross(ref_dir, np.array((xn, yn, zn)))
            angle = np.degrees(np.arccos(np.dot(ref_dir, np.array((xn, yn, zn)))))
            if np.linalg.norm(axis) > 1e-6:
                transform.RotateWXYZ(angle, axis)

            # Translate to position
            transform.Translate(position)

            # Apply transform
            tf = vtk.vtkTransformPolyDataFilter()
            tf.SetInputConnection(arrow.GetOutputPort())
            tf.SetTransform(transform)
            tf.Update()

            # Append
            append.AddInputData(tf.GetOutput())

            # Add flow value for each point in this arrow
            npts = tf.GetOutput().GetNumberOfPoints()
            for _ in range(npts):
                flow_values.InsertNextValue(abs(flow))

        append.Update()

        # Final polydata with scalars
        arrows = append.GetOutput()
        arrows.GetPointData().SetScalars(flow_values)

        # return arrow_glyph3D_with_normals.GetOutput()
        return arrows

    def _create_volumetric_pressure(self, df_pores, df_throats, watershed_array):
        if _is_sorted(df_pores["pore.region_label"].to_numpy()) is not True:
            raise ValueError
        resolved_array = np.zeros_like(watershed_array, dtype=np.float32)
        unresolved_array = np.zeros_like(watershed_array, dtype=np.float32)
        W, H, D = watershed_array.shape
        for x in range(W):
            for y in range(H):
                for z in range(D):
                    array_label = watershed_array[x, y, z]
                    if array_label > 0:
                        table_index = np.searchsorted(df_pores["pore.region_label"], array_label)
                        if (table_index > len(df_pores["pore.region_label"])) or (
                            array_label != df_pores["pore.region_label"][table_index]
                        ):
                            continue
                        pressure = df_pores["pore.pressure"][table_index]
                        phase = (df_pores["pore.subresolution_porosity"][table_index] < 1) + 1
                        if phase == 1:
                            resolved_array[x, y, z] = pressure
                        elif phase == 2:
                            unresolved_array[x, y, z] = pressure
        return resolved_array, unresolved_array


class TwoPhaseSimulationLogic(LTracePluginLogic):
    def __init__(self, parent, progressBar):
        LTracePluginLogic.__init__(self, parent)
        self.cliNode = None
        self.progressBar = progressBar
        self.prefix = None

    def run_2phase(self, pore_node, snapshot_node, params, prefix, callback, wait=False):
        self.start_time = time.time()
        self.simulate_krel(pore_node, snapshot_node, params, prefix, callback, wait)

    def cancel(self):
        if self.cliNode is None:
            return
        self.cliNode.Cancel()

    def simulate_krel(self, pore_node, snapshot_node, params, prefix, callback, wait=False):
        """
        Perform two-phase fluid simulation
        Runs all parallel batches of simulation, then concatenates the results
        Returns:
            outputTable -> MRML Table Node
            df_results -> Pandas DataFrame
        """

        self.cwd = Path(slicer.util.tempDirectory())
        self.callback = callback

        self.pore_node = pore_node
        self.params = params
        self.prefix = prefix

        hash = "".join(
            random.choices(
                string.ascii_letters,
                k=22,
            )
        )
        directory_name = f"pnm_cli_{hash}"
        self.temp_dir = f"{slicer.app.temporaryPath}/{directory_name}"
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        os.mkdir(self.temp_dir)

        cliParams = {"model": "TwoPhaseSensibilityTest", "cwd": str(self.cwd), "tempDir": self.temp_dir}

        subresolution_function = params["subresolution function"]
        del params["subresolution function"]
        del params["subresolution function call"]

        statoil_dict = geo2pnf(
            pore_node,
            subresolution_function,
            axis=params["direction"],
            subres_shape_factor=params["subres_shape_factor"],
            subres_porositymodifier=params["subres_porositymodifier"],
        )

        with open(str(self.cwd / "statoil_dict.json"), "w") as file:
            json.dump(statoil_dict, file)

        with open(str(self.cwd / "params_dict.json"), "w") as file:
            json.dump(self.params, file)

        if snapshot_node is not None:
            with open(str(self.cwd / "snapshot.bin"), "wb") as file:
                snapshot_data = getBinary(snapshot_node)
                file.write(snapshot_data)

        self.cliNode = slicer.cli.run(
            slicer.modules.porenetworksimulationcli, None, cliParams, wait_for_completion=wait
        )
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.twoPhaseCLICallback)

    def twoPhaseCLICallback(self, caller, event):
        if caller is None:
            self.cliNode = None
            return
        if self.cliNode is None:
            return
        status = caller.GetStatusString()

        if "Completed" in status or status == "Cancelled":
            logging.info(status)
            self.cliNode = None
            if status == "Completed":
                try:
                    folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
                    itemTreeId = folderTree.GetItemByDataNode(self.pore_node)
                    parentItemId = folderTree.GetItemParent(folderTree.GetItemParent(itemTreeId))
                    self.rootDir = folderTree.CreateFolderItem(parentItemId, f"{self.prefix}_Two_Phase_PN_Simulation")
                    folderTree.SetItemExpanded(self.rootDir, False)

                    # Reload updated params
                    with open(str(self.cwd / "params_dict.json"), "r") as f:
                        self.params = json.load(f)

                    parametersNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTextNode", "simulation_parameters")
                    parametersNode.SetText(json.dumps(self.params, indent=4))
                    parametersNode.SetAttribute(TableType.name(), TableType.PNM_INPUT_PARAMETERS.value)
                    folderTree.CreateItem(self.rootDir, parametersNode)

                    krelResultsTableNode = createTableNode("Krel_results", "krel_simulation_results")
                    self.krelResultsTableNodeId = krelResultsTableNode.GetID()
                    self.krelCycleTableNodesId = []

                    if self.params["create_ca_distributions"] == "T":
                        self.caDistributionTableDir = folderTree.CreateFolderItem(self.rootDir, "CA Distribution")
                        folderTree.SetItemExpanded(self.caDistributionTableDir, False)

                    for cycle in range(1, 4):
                        tableNodeName = slicer.mrmlScene.GenerateUniqueName(f"krel_table_cycle{cycle}")
                        tableNode = createTableNode(tableNodeName, "relative_permeability")
                        krelResultsTableNode.SetAttribute(f"cycle_table_{cycle}_id", tableNode.GetID())
                        self.krelCycleTableNodesId.append(tableNode.GetID())
                        # cliParams[f"krelCycle{cycle}"] = tableNode.GetID()

                    tableDir = folderTree.CreateFolderItem(self.rootDir, "Tables")
                    folderTree.SetItemExpanded(tableDir, False)

                    for krelCycleTableNodeId in self.krelCycleTableNodesId:
                        if krelCycleTableNode := helpers.tryGetNode(krelCycleTableNodeId):
                            folderTree.CreateItem(tableDir, krelCycleTableNode)

                    folderTree.CreateItem(self.rootDir, krelResultsTableNode)

                    self.updateOutputTables()
                    self.createCaDistributionTables()
                    self.__createSnapshotBinNode()
                    if "saturation_steps" in self.params:
                        self.loadAnimationNodes(self.params["saturation_steps"])
                except:
                    self.removeNodes()
                    logging.error(traceback.format_exc())
                    slicer.util.errorDisplay("A problem has occurred during the simulation.")
            self.cleanup()
            self.callback(True)

    #  utils
    def updateTableFromDataFrame(self, tableNode, dataFrameFileName):
        dataFrame = pd.read_pickle(str(self.cwd / dataFrameFileName))
        dataFrameToTableNode(dataFrame, tableNode)
        return True

    def updateOutputTables(self):
        dataFrameCycleFileNames = ["krelCycle1", "krelCycle2", "krelCycle3"]
        krelResultsTableNode = helpers.tryGetNode(self.krelResultsTableNodeId)
        if krelResultsTableNode and self.updateTableFromDataFrame(krelResultsTableNode, "krelResults"):
            for tableNodeId, dataFrameFilename in zip(self.krelCycleTableNodesId, dataFrameCycleFileNames):
                tableNode = helpers.tryGetNode(tableNodeId)
                self.updateTableFromDataFrame(tableNode, dataFrameFilename)

    def createCaDistributionTables(self):
        krelResultsTableNode = helpers.tryGetNode(self.krelResultsTableNodeId)
        if krelResultsTableNode and self.params["create_ca_distributions"] == "T":
            for file in listFilesRegex(str(self.cwd), "ca_distribution_\\d+"):
                nodeName = Path(file).stem
                caDistributionNode = self.__createCaDistributionNode(nodeName)
                krelResultsTableNode.SetAttribute(f"{nodeName}_id", caDistributionNode.GetID())

    def __createSnapshotBinNode(self):
        if self.params["create_drainage_snapshot"] == "T":
            with open(str(Path(str(self.cwd)) / "snapshot.bin"), "rb") as fp:
                snapshotData = fp.read()
                binaryNode = createBinaryNode(snapshotData)
                binaryNode.SetName("drainage_snapshot")
                slicer.mrmlScene.AddNode(binaryNode)

                folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
                folderTree.CreateItem(self.rootDir, binaryNode)

    def __createCaDistributionNode(self, ca_distribution_file):
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        caDistributionTableNode = createTableNode(ca_distribution_file, "ca_distribution")
        folderTree.CreateItem(self.caDistributionTableDir, caDistributionTableNode)
        self.updateTableFromDataFrame(caDistributionTableNode, ca_distribution_file)
        return caDistributionTableNode

    def loadAnimationNodes(self, staturation_steps_list):
        folder_tree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        vtu_file_list = listFilesInDir(self.temp_dir)
        if len(vtu_file_list) > 0:
            self.animation_nodes_ids = []
            animation_folder = folder_tree.CreateFolderItem(self.rootDir, "Animation")
            for i, file in enumerate(vtu_file_list):
                polydata = readPolydata(file)
                new_model_node = self.createModelNode(Path(file).stem, polydata, staturation_steps_list[i], i)
                self.animation_nodes_ids.append(new_model_node.GetID())
                folder_tree.CreateItem(animation_folder, new_model_node)
        shutil.rmtree(self.temp_dir)

    def removeNodes(self):
        krelResultsTableNode = helpers.tryGetNode(self.krelResultsTableNodeId)
        slicer.mrmlScene.RemoveNode(krelResultsTableNode)
        del krelResultsTableNode
        self.krelResultsTableNodeId = None

        for krelCycleTableNodeId in self.krelCycleTableNodesId:
            if node := helpers.tryGetNode(krelCycleTableNodeId):
                slicer.mrmlScene.RemoveNode(node)
                del node
        self.krelCycleTableNodesId.clear()
        slicer.mrmlScene.GetSubjectHierarchyNode().RemoveItem(self.rootDir)

    def cleanup(self):
        # Remove created files if told to do so
        if not self.params["keep_temporary"] == "T":
            shutil.rmtree(self.cwd)

    def createModelNode(self, node_name, polydata, saturation_steps, simulation_id):
        data_table_id_list = []
        for tableNodeId in self.krelCycleTableNodesId:
            data_table_id_list.append(tableNodeId)
        pores_model_node_name = slicer.mrmlScene.GenerateUniqueName(node_name)
        pores_model_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", pores_model_node_name)
        pores_model_node.CreateDefaultDisplayNodes()
        pores_model_display = pores_model_node.GetDisplayNode()
        pores_model_node.SetDisplayVisibility(False)
        pores_model_display.SetScalarVisibility(1)
        pores_model_display.SetColor(0.1, 0.1, 0.9)
        pores_model_display.SetAmbient(0.15)
        pores_model_display.SetDiffuse(0.85)

        pores_model_node.SetAndObservePolyData(polydata)
        pores_model_node.SetAttribute("saturation_steps", str(saturation_steps))
        pores_model_node.SetAttribute("data_table_id", json.dumps(data_table_id_list))
        pores_model_node.SetAttribute("simulation_id", str(simulation_id))
        pores_model_node.GetDisplayNode().SetActiveScalarName("saturation_0")

        # Set the correct orientation and origin
        poresLabelMap = self.pore_node.GetNodeReference("PoresLabelMap")
        vtkTransformationMatrix = vtk.vtkMatrix4x4()
        poresLabelMap.GetIJKToRASDirectionMatrix(vtkTransformationMatrix)
        poresLabelMapOrigin = poresLabelMap.GetOrigin()
        vtkTransformationMatrix.SetElement(0, 3, poresLabelMapOrigin[0])
        vtkTransformationMatrix.SetElement(1, 3, poresLabelMapOrigin[1])
        vtkTransformationMatrix.SetElement(2, 3, poresLabelMapOrigin[2])
        transformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode")
        transformNode.SetMatrixTransformToParent(vtkTransformationMatrix)
        pores_model_node.SetAndObserveTransformNodeID(transformNode.GetID())
        pores_model_node.HardenTransform()
        slicer.mrmlScene.RemoveNode(transformNode)
        del transformNode

        return pores_model_node


@njit
def _is_sorted(arr):
    for i in range(1, len(arr)):
        if arr[i] < arr[i - 1]:
            return False
    return True
