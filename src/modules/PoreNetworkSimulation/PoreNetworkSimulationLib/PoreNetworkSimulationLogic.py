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

try:
    from Test.PoreNetworkSimulationTest import PoreNetworkSimulationTest
except ImportError:
    PoreNetworkSimulationTest = None  # tests not deployed to final version or closed source

NUM_THREADS = 48


class PoreNetworkSimulationLogic(LTracePluginLogic):
    def __init__(self, progressBar):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar

    def run_1phase_one_angle(self, inputTable, params, prefix):
        """
        Perform one-phase fluid simulation with one angle.

        Parameters
        ----------
        inputTable : vtkMRMLTableNode
            A table node with "table_type" attribute equal to "pore_table",
        a throat_table must be present in the same hierarchy folder.

        params : dict
        "model type"
            Currently only "Valvatne-Blunt" is accepted.
        "simulation type"
            Angle scheme, may be either ONE_ANGLE or MULTI_ANGLE

        prefix : string
            Simulation name, to be used on the hierarchy folder and nodes.

        Returns
        -------
        bool
            Returns True if successful
        """

        hide_nodes_of_type("vtkMRMLModelNode")

        pore_network = geo2spy(inputTable)

        in_faces = ("xmin", "ymin", "zmin")
        out_faces = ("xmax", "ymax", "zmax")

        pore_shape, throat_shape = [i.strip().lower() for i in params["model type"].split("-")]

        # Create tables nodes
        flow_rate_table_name = slicer.mrmlScene.GenerateUniqueName("flow_rate")
        flow_rate_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", flow_rate_table_name)
        flow_rate_table.SetAttribute("table_type", "flow_rate_tensor")

        permeability_table_name = slicer.mrmlScene.GenerateUniqueName("permeability")
        permeability_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", permeability_table_name)
        permeability_table.SetAttribute("table_type", "permeability_tensor")

        # Setup hierarchy base folder
        folderTree, rootDir = self.createFolder(f"{prefix}_Single_Phase_PN_Simulation", inputTable)

        flow_array = np.zeros((3, 3), dtype="float")
        permeability_array = np.zeros((3, 3), dtype="float")

        sizes = {
            "x": float(inputTable.GetAttribute("x_size")) / 10,
            "y": float(inputTable.GetAttribute("y_size")) / 10,
            "z": float(inputTable.GetAttribute("z_size")) / 10,
        }  # values in cm
        sizes_product = sizes["x"] * sizes["y"] * sizes["z"]

        visualization_dir = folderTree.CreateFolderItem(rootDir, "Visualization models")
        folderTree.SetItemExpanded(visualization_dir, False)
        folderTree.ItemModified(visualization_dir)

        for inlet, outlet in itertools.combinations_with_replacement((0, 1, 2), 2):
            in_face = in_faces[inlet]
            out_face = out_faces[outlet]
            perm, pn_pores, pn_throats = single_phase_permeability(
                pore_network,
                throat_shape,
                pore_shape,
                in_face,
                out_face,
                subresolution_function=params["subresolution function"],
            )
            if (perm == 0) or (perm.network.throats("all").size == 0):
                continue
            inlet_flow = perm.rate(perm.project[0].pores(in_face))
            outlet_flow = perm.rate(perm.project[0].pores(out_face))
            flow_rate = (inlet_flow - outlet_flow) / 2  # cm^3/s
            if in_face[0] == out_face[0]:
                length = sizes[in_faces[2 - inlet][0]]
                area = sizes_product / length
                permeability = flow_rate * (length / area)
            else:
                # Darcy permeability for pluridimensional flow is undefined
                permeability = 0
            flow_array[inlet, outlet] = flow_rate
            flow_array[outlet, inlet] = flow_rate
            permeability_array[inlet, outlet] = permeability * 1000  # Conversion factor from darcy to milidarcy
            permeability_array[outlet, inlet] = permeability * 1000  # Conversion factor from darcy to milidarcy

            if slicer_is_in_developer_mode():
                print("############## StokeFlow results #################")
                print(perm)
                print(perm.rate)
                print("##################################################")

            # Create VTK models
            throat_values = np.log10(perm.rate(throats=perm.network.throats("all"), mode="individual"))
            try:
                min_throat = np.min(throat_values[throat_values > (-np.inf)])
                max_throat = np.max(throat_values[throat_values > (-np.inf)])
            except:
                min_throat = -np.inf
                max_throat = np.inf
            pore_values = perm["pore.pressure"]
            pores_model_node, throats_model_node = create_flow_model(perm.project, pore_values, throat_values)
            pores_model_node.SetName("Pore Pressure")
            throats_model_node.SetName("Throat Flow Rate")
            subDir = folderTree.CreateFolderItem(
                visualization_dir, f"{['z', 'y', 'x'][inlet]}-{['z', 'y', 'x'][outlet]} folder"
            )
            folderTree.CreateItem(subDir, pores_model_node)
            folderTree.CreateItem(subDir, throats_model_node)

            throat_values = perm.network.throats("all")

            pore_values = perm.project.network[f"pore.{out_face}"].astype(int) - perm.project.network[
                f"pore.{in_face}"
            ].astype(int)
            border_pores_model_node, null_throats_model_node = create_flow_model(
                perm.project, pore_values, throat_values
            )
            border_pores_model_node.SetName("Pore Inlets and Outlets")
            slicer.mrmlScene.RemoveNode(null_throats_model_node)
            del null_throats_model_node
            folderTree.CreateItem(subDir, border_pores_model_node)
            border_pores_model_node.SetDisplayVisibility(False)

            folderTree.SetDisplayVisibilityForBranch(subDir, False)
            folderTree.SetItemExpanded(subDir, False)
            folderTree.ItemModified(subDir)

            pores_model_node.GetDisplayNode().SetAndObserveColorNodeID("vtkMRMLColorTableNodeFileViridis.txt")
            throats_model_node.GetDisplayNode().SetAndObserveColorNodeID("vtkMRMLColorTableNodeWarmTint1")
            border_pores_model_node.GetDisplayNode().SetAndObserveColorNodeID("vtkMRMLColorTableNodeFileViridis.txt")
            throats_model_node.GetDisplayNode().SetScalarRangeFlag(0)
            throats_model_node.GetDisplayNode().SetScalarRange(min_throat, max_throat)

            if (inlet + outlet) != 0:  # by default only display z-z results
                pores_model_node.SetDisplayVisibility(False)
                throats_model_node.SetDisplayVisibility(False)

            # Create Table nodes with PN properties
            df_pores = pd.DataFrame(pn_pores)
            df_throats = pd.DataFrame(pn_throats)
            poreOutputTableName = slicer.mrmlScene.GenerateUniqueName(f"{prefix}_pores_project")
            poreOutputTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", poreOutputTableName)
            poreOutputTable.SetAttribute("table_type", "project_pore_table")
            throatOutputTableName = slicer.mrmlScene.GenerateUniqueName(f"{prefix}_throat_project")
            throatOutputTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", throatOutputTableName)
            throatOutputTable.SetAttribute("table_type", "project_throat_table")
            _ = dataFrameToTableNode(df_pores, poreOutputTable)
            _ = dataFrameToTableNode(df_throats, throatOutputTable)
            _ = folderTree.CreateItem(subDir, poreOutputTable)
            _ = folderTree.CreateItem(subDir, throatOutputTable)

        flow_df = pd.DataFrame(
            flow_array, ("z [cm^3/s]", "y [cm^3/s]", "x [cm^3/s]"), ("z [cm^3/s]", "y [cm^3/s]", "x [cm^3/s]")
        )
        _ = dataFrameToTableNode(flow_df, flow_rate_table)
        folderTree.CreateItem(rootDir, flow_rate_table)

        permeability_df = pd.DataFrame(
            permeability_array, ("z [mD]", "y [mD]", "x [mD]"), ("z [mD]", "y [mD]", "x [mD]")
        )
        _ = dataFrameToTableNode(permeability_df, permeability_table)
        folderTree.CreateItem(rootDir, permeability_table)

        table_id = folderTree.GetItemByDataNode(pores_model_node)
        folder_id = folderTree.GetItemParent(table_id)
        root_folder_id = folderTree.GetItemParent(folder_id)
        folderTree.SetItemDisplayVisibility(root_folder_id, False)
        folderTree.SetItemDisplayVisibility(folder_id, False)
        folderTree.ItemModified(table_id)
        folderTree.ItemModified(folder_id)
        folderTree.ItemModified(root_folder_id)

        return permeability_table

    def run_1phase_multi_angle(self, inputTable, params, prefix):
        """
        Perform one-phase fluid simulation for multi angle.

        Parameters
        ----------
        inputTable : vtkMRMLTableNode
            A table node with "table_type" attribute equal to "pore_table",
        a throat_table must be present in the same hierarchy folder.

        params : dict
        "model type"
            Currently only "Valvatne-Blunt" is accepted.
        "simulation type"
            Angle scheme, may be either ONE_ANGLE or MULTI_ANGLE

        prefix : string
            Simulation name, to be used on the hierarchy folder and nodes.

        Returns
        -------
        bool
            Returns True if successful
        """

        hide_nodes_of_type("vtkMRMLModelNode")

        pore_network = geo2spy(inputTable)

        pore_shape, throat_shape = [i.strip().lower() for i in params["model type"].split("-")]

        folderTree, rootDir = self.createFolder(f"{prefix}_Single_Phase_PN_Simulation_multiangle", inputTable)
        visualization_dir = folderTree.CreateFolderItem(rootDir, "Visualization models")
        folderTree.SetItemExpanded(visualization_dir, False)
        folderTree.ItemModified(visualization_dir)

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

        # pore_network = get_sub_spy(pore_network, pore_in_sphere, throat_in_sphere)

        surface_points = generate_equidistant_points_on_sphere(
            N=params["rotation angles"] * 2, r=(bb_radius / np.sqrt(2))
        )
        number_surface_points = surface_points.shape[0] // 2
        surface_points = surface_points[0:number_surface_points, :]
        number_surface_points = surface_points.shape[0]
        permeabilities = []
        dx, dy, dz = bb_center
        for i in range(number_surface_points):
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

            perm, pn_pores, pn_throats = single_phase_permeability(
                pore_network,
                throat_shape,
                pore_shape,
                subresolution_function=params["subresolution function"],
            )
            if perm == 0:
                permeabilities.append((px, py, pz, 0))
                continue
            inlet_flow = perm.rate(perm.project[0].pores("xmin"))
            outlet_flow = perm.rate(perm.project[0].pores("xmax"))
            flow_rate = (inlet_flow - outlet_flow) / 2  # cm^3/s
            permeability = flow_rate / (2 * bb_radius)  # return is Darcy
            permeabilities.append((px, py, pz, permeability))
            permeabilities.append((-px, -py, -pz, permeability))

            # Create VTK models
            if i % 20 != 0:
                continue
            throat_values = np.log10(perm.rate(throats=perm.network.throats("all"), mode="individual"))
            try:
                min_throat = np.min(throat_values[throat_values > (-np.inf)])
                max_throat = np.max(throat_values[throat_values > (-np.inf)])
            except:
                min_throat = -np.inf
                max_throat = np.inf
            pore_values = perm["pore.pressure"]
            pores_model_node, throats_model_node = create_flow_model(perm.project, pore_values, throat_values)
            pores_model_node.SetName("Pore Pressure")
            throats_model_node.SetName("Throat Flow Rate")
            subDir = folderTree.CreateFolderItem(visualization_dir, f"{i} folder")
            _ = folderTree.CreateItem(subDir, pores_model_node)
            _ = folderTree.CreateItem(subDir, throats_model_node)

            throat_values = perm.network.throats("all")

            pore_values = perm.project.network["pore.xmin"].astype(int) - perm.project.network["pore.xmax"].astype(int)
            border_pores_model_node, null_throats_model_node = create_flow_model(
                perm.project, pore_values, throat_values
            )
            border_pores_model_node.SetName("Pore Inlets and Outlets")
            slicer.mrmlScene.RemoveNode(null_throats_model_node)
            del null_throats_model_node
            _ = folderTree.CreateItem(subDir, border_pores_model_node)
            border_pores_model_node.SetDisplayVisibility(False)

            folderTree.SetDisplayVisibilityForBranch(subDir, False)
            folderTree.SetItemExpanded(subDir, False)
            folderTree.ItemModified(subDir)

            pores_model_node.GetDisplayNode().SetAndObserveColorNodeID("vtkMRMLColorTableNodeFileViridis.txt")
            throats_model_node.GetDisplayNode().SetAndObserveColorNodeID("vtkMRMLColorTableNodeWarmTint1")
            border_pores_model_node.GetDisplayNode().SetAndObserveColorNodeID("vtkMRMLColorTableNodeFileViridis.txt")
            throats_model_node.GetDisplayNode().SetScalarRangeFlag(0)
            throats_model_node.GetDisplayNode().SetScalarRange(min_throat, max_throat)

            pores_model_node.SetDisplayVisibility(False)
            throats_model_node.SetDisplayVisibility(False)
            # End create VTK models

        sphere_dir = folderTree.CreateFolderItem(rootDir, "Visualization sphere")
        folderTree.SetItemExpanded(sphere_dir, False)
        create_permeability_sphere(
            permeabilities,
            target_dir=sphere_dir,
            radius=bb_radius,
            verbose=False,
        )

    def run_2phase(self, pore_node, params, prefix, callback):
        self.start_time = time.time()
        self.simulate_krel(pore_node, params, prefix, callback)

    def cancel_2phase(self):
        if self.cliNode is None:
            return
        self.cliNode.Cancel()

    def simulate_krel(self, pore_node, params, prefix, callback):
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
        krelResultsTableNode = self.createTableNode("Krel_results", "krel_simulation_results")
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
            tableNode = self.createTableNode(tableNodeName, "relative_permeability")
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
        statoil_dict = geo2pnf(pore_node, subresolution_function)
        with open(str(self.cwd / "statoil_dict.json"), "w") as file:
            json.dump(statoil_dict, file)

        with open(str(self.cwd / "params_dict.json"), "w") as file:
            json.dump(self.params, file)

        self.cliUpdateCounter = 0
        self.currentDataFrameLength = 0
        self.cliNode = slicer.cli.run(slicer.modules.porenetworksimulationcli, None, cliParams)
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.poreNetworkSimulationCLICallback)

    def poreNetworkSimulationCLICallback(self, caller, event):
        if caller is None:
            self.cliNode = None
            return
        if self.cliNode is None:
            return
        status = caller.GetStatusString()

        if "Completed" in status or status == "Cancelled":
            logging.info(status)
            del self.cliNode
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
    def createFolder(self, name, inputTable):
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemTreeId = folderTree.GetItemByDataNode(inputTable)
        parentItemId = folderTree.GetItemParent(folderTree.GetItemParent(itemTreeId))
        rootDir = folderTree.CreateFolderItem(parentItemId, name)
        folderTree.SetItemExpanded(rootDir, False)
        folderTree.ItemModified(rootDir)
        return folderTree, rootDir

    def createTableNode(self, name, tableTypeAttribute):
        table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
        table.SetName(name)
        table.SetAttribute("table_type", tableTypeAttribute)
        return table

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
        vtu_file_list = self.listFilesInDir(self.temp_dir)
        if len(vtu_file_list) > 0:
            animation_folder = folder_tree.CreateFolderItem(self.rootDir, "Animation")
            for i, file in enumerate(vtu_file_list):
                polydata = self.readPolydata(file)
                new_model_node = self.createModelNode(Path(file).stem, polydata, staturation_steps_list[i], i)
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

    @staticmethod
    def listFilesInDir(directory):
        files = []
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            if os.path.isfile(filepath):
                files.append(filepath)
        return files

    @staticmethod
    def readPolydata(filename):
        reader = vtk.vtkPolyDataReader()
        reader.SetFileName(filename)
        reader.Update()

        polydata = reader.GetOutput()
        return polydata

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
