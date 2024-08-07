import vtk

import itertools
import json
import logging
import os
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import slicer
import pickle

from ltrace.algorithms.common import (
    generate_equidistant_points_on_sphere,
    points_are_below_plane,
)
from ltrace.pore_networks.functions import (
    single_phase_permeability,
    geo2pnf,
    geo2spy,
)
from ltrace.pore_networks.vtk_utils import (
    create_flow_model,
    create_permeability_sphere,
)
from ltrace.slicer import helpers
from ltrace.slicer_utils import (
    LTracePluginLogic,
    dataFrameToTableNode,
    slicer_is_in_developer_mode,
    hide_nodes_of_type,
)

from PoreNetworkSimulationLib.constants import *

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


def readPolydata(filename):
    reader = vtk.vtkPolyDataReader()
    reader.SetFileName(filename)
    reader.Update()

    polydata = reader.GetOutput()
    return polydata


class OnePhaseSimulationLogic(LTracePluginLogic):
    def __init__(self, progressBar):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar
        self.prefix = None
        self.rootDir = None
        self.results = {}

    def run_1phase(self, inputTable, params, prefix, callback, wait=False):
        self.params = params
        self.cwd = Path(slicer.util.tempDirectory())
        self.callback = callback
        self.prefix = prefix

        self.temp_dir = f"{slicer.app.temporaryPath}/porenetworksimulationcli"
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        os.mkdir(self.temp_dir)

        cliParams = {
            "model": "onePhase",
            "cwd": str(self.cwd),
            "tempDir": self.temp_dir,
        }

        hide_nodes_of_type("vtkMRMLModelNode")

        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
        itemTreeId = folderTree.GetItemByDataNode(inputTable)
        parentItemId = folderTree.GetItemParent(folderTree.GetItemParent(itemTreeId))
        if params["simulation type"] == "Single orientation":
            self.rootDir = folderTree.CreateFolderItem(parentItemId, f"{prefix}_Single_Phase_PN_Simulation")
        elif params["simulation type"] == "Multiple orientations":
            self.rootDir = folderTree.CreateFolderItem(parentItemId, f"{prefix}_Single_Phase_PN_Simulation_multiangle")
        folderTree.SetItemExpanded(self.rootDir, False)

        pore_network = geo2spy(inputTable)

        dict_file = open(str(self.cwd / "pore_network.dict"), "wb")
        pickle.dump(pore_network, dict_file)
        dict_file.close()

        subresolution_function = self.params["subresolution function"]
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
                # try:
                time.sleep(1)  # TODO como resolve sem precisar?
                self.onFinish()
                # except:
                #    slicer.util.errorDisplay("A problem has occurred during the simulation.")

            if not self.params["keep_temporary"]:
                shutil.rmtree(self.cwd)

            self.callback(True)

    def onFinish(self):
        if self.params["simulation type"] == ONE_ANGLE:
            self.createVisualizationModels()
            self.createTableNodes()
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

        with open(f"{self.temp_dir}/return_params.json", "r") as file:
            minmax = json.load(file)

        counter = 0
        for inlet, outlet in itertools.combinations_with_replacement((0, 1, 2), 2):
            if counter >= len(minmax):
                break

            subDir = folderTree.CreateFolderItem(
                visualization_dir, f"{['z', 'y', 'x'][inlet]}-{['z', 'y', 'x'][outlet]} folder"
            )

            model_node = {}
            for prefix, name in [
                ("pore_pressure", "Pore Pressure"),
                ("throat_flow_rate", "Throat Flow Rate"),
                ("border_pores", "Pore Inlets and Outlets"),
            ]:
                file = f"{self.temp_dir}/{prefix}_{inlet}_{outlet}.vtk"
                polydata = readPolydata(file)
                model_node[prefix] = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", name)
                model_node[prefix].SetAndObservePolyData(polydata)
                model_node[prefix].CreateDefaultDisplayNodes()
                model_display = model_node[prefix].GetDisplayNode()
                model_node[prefix].SetDisplayVisibility(True)
                model_display.SetScalarVisibility(True)
                folderTree.CreateItem(subDir, model_node[prefix])

            model_node["border_pores"].SetDisplayVisibility(False)

            model_node["pore_pressure"].GetDisplayNode().SetAndObserveColorNodeID(
                "vtkMRMLColorTableNodeFileViridis.txt"
            )
            model_node["throat_flow_rate"].GetDisplayNode().SetAndObserveColorNodeID("vtkMRMLColorTableNodeWarmTint1")
            model_node["border_pores"].GetDisplayNode().SetAndObserveColorNodeID("vtkMRMLColorTableNodeFileViridis.txt")
            model_node["throat_flow_rate"].GetDisplayNode().SetScalarRangeFlag(0)
            min_throat = minmax[counter]["min"]
            max_throat = minmax[counter]["max"]
            counter += 1
            model_node["throat_flow_rate"].GetDisplayNode().SetScalarRange(min_throat, max_throat)

            if (inlet + outlet) != 0:  # by default only display z-z results
                model_node["pore_pressure"].SetDisplayVisibility(False)
                model_node["throat_flow_rate"].SetDisplayVisibility(False)

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


class TwoPhaseSimulationLogic(LTracePluginLogic):
    def __init__(self, progressBar):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar
        self.prefix = None

    def run_2phase(self, pore_node, params, prefix, callback, wait=False):
        self.start_time = time.time()
        self.simulate_krel(pore_node, params, prefix, callback, wait)

    def cancel(self):
        if self.cliNode is None:
            return
        self.cliNode.Cancel()

    def simulate_krel(self, pore_node, params, prefix, callback, wait=False):
        """
        Perform two-phase fluid simulation
        Runs all parallel batches of simulation, then concatenates the results
        Returns:
            outputTable -> MRML Table Node
            df_results -> Pandas DataFrame
        """

        self.pore_node = pore_node
        self.params = params
        self.prefix = prefix
        krelResultsTableNode = createTableNode("Krel_results", "krel_simulation_results")
        self.krelResultsTableNodeId = krelResultsTableNode.GetID()
        self.krelCycleTableNodesId = []
        self.cwd = Path(slicer.util.tempDirectory())
        self.callback = callback

        self.temp_dir = f"{slicer.app.temporaryPath}/porenetworksimulationcli"
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        os.mkdir(self.temp_dir)

        cliParams = {
            "model": "TwoPhaseSensibilityTest",
            "cwd": str(self.cwd),
            "maxSubprocesses": self.params["max_subprocesses"],
            "krelResults": self.krelResultsTableNodeId,
            "tempDir": self.temp_dir,
        }

        for cycle in range(1, 4):
            tableNodeName = slicer.mrmlScene.GenerateUniqueName(f"krel_table_cycle{cycle}")
            tableNode = createTableNode(tableNodeName, "relative_permeability")
            krelResultsTableNode.SetAttribute(f"cycle_table_{cycle}_id", tableNode.GetID())
            self.krelCycleTableNodesId.append(tableNode.GetID())
            cliParams[f"krelCycle{cycle}"] = tableNode.GetID()

        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
        itemTreeId = folderTree.GetItemByDataNode(self.pore_node)
        parentItemId = folderTree.GetItemParent(folderTree.GetItemParent(itemTreeId))
        self.rootDir = folderTree.CreateFolderItem(parentItemId, f"{self.prefix}_Two_Phase_PN_Simulation")
        folderTree.SetItemExpanded(self.rootDir, False)
        tableDir = folderTree.CreateFolderItem(self.rootDir, "Tables")
        folderTree.SetItemExpanded(tableDir, False)

        for krelCycleTableNodeId in self.krelCycleTableNodesId:
            if krelCycleTableNode := helpers.tryGetNode(krelCycleTableNodeId):
                folderTree.CreateItem(tableDir, krelCycleTableNode)

        folderTree.CreateItem(self.rootDir, krelResultsTableNode)

        subresolution_function = params["subresolution function"]
        del params["subresolution function"]
        del params["subresolution function call"]
        print(subresolution_function)
        statoil_dict = geo2pnf(pore_node, subresolution_function)
        with open(str(self.cwd / "statoil_dict.json"), "w") as file:
            json.dump(statoil_dict, file)

        with open(str(self.cwd / "params_dict.json"), "w") as file:
            json.dump(self.params, file)

        self.cliUpdateCounter = 0
        self.currentDataFrameLength = 0
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
                    self.updateOutputTables()
                    self.loadAnimationNodes(caller.GetParameterAsString("saturation_steps"))
                except:
                    self.removeNodes()
                    slicer.util.errorDisplay("A problem has occurred during the simulation.")
                elapsed_time = time.time() - self.start_time
                print("Elapsed time:", elapsed_time, "seconds")
            elif status == "Cancelled":
                self.removeNodes()
            else:
                self.removeNodes()
            self.cleanup()
            self.callback(True)
        else:
            if self.cliUpdateCounter % 20 == 0:
                self.updateOutputTables()

        self.cliUpdateCounter += 1

    #  utils
    def updateTableFromDataFrame(self, tableNode, dataFrameFileName):
        try:
            dataFrame = pd.read_pickle(str(self.cwd / dataFrameFileName))
            if dataFrameFileName == "krelResults":
                dataFrameLength = len(dataFrame)
                if dataFrameLength > self.currentDataFrameLength:
                    dataFrameToTableNode(dataFrame, tableNode)
                    self.currentDataFrameLength = dataFrameLength
                    return True
            else:
                dataFrameToTableNode(dataFrame, tableNode)
        except:
            pass

    def updateOutputTables(self):
        dataFrameCycleFileNames = ["krelCycle1", "krelCycle2", "krelCycle3"]
        krelResultsTableNode = helpers.tryGetNode(self.krelResultsTableNodeId)
        if krelResultsTableNode and self.updateTableFromDataFrame(krelResultsTableNode, "krelResults"):
            for tableNodeId, dataFrameFilename in zip(self.krelCycleTableNodesId, dataFrameCycleFileNames):
                tableNode = helpers.tryGetNode(tableNodeId)
                self.updateTableFromDataFrame(tableNode, dataFrameFilename)

    def loadAnimationNodes(self, staturation_steps_json):
        staturation_steps_list = json.loads(staturation_steps_json)
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
        if not self.params["keep_temporary"]:
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
