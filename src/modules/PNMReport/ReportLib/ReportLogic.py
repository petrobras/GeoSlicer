import os
import shutil
import time
from pathlib import Path
from collections import namedtuple
import json
import logging
import qt
import slicer
import vtk
import nrrd
import numpy as np
import pandas as pd

from ltrace.pore_networks.functions import geo2spy
from ltrace.slicer import data_utils as du
from ltrace.slicer.helpers import LazyLoad
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.utils.ProgressBarProc import ProgressBarProc
from ltrace.slicer_utils import LTracePluginLogic


from CustomResampleScalarVolume import CustomResampleScalarVolumeLogic
from PoreNetworkSimulation import (
    OnePhaseSimulationWidget,
    OnePhaseSimulationLogic,
    TwoPhaseSimulationLogic,
    TwoPhaseSimulationWidget,
    MercurySimulationWidget,
    MercurySimulationLogic,
    SubscaleLogicDict,
)
from PoreNetworkExtractor import PoreNetworkExtractorLogic
from PoreNetworkProduction import PoreNetworkProductionLogic


class PNMQueue(qt.QObject):
    simChanged = qt.Signal()


class ReportLogic(LTracePluginLogic):
    processFinished = qt.Signal()

    def __init__(self, parent, progressBar):
        LTracePluginLogic.__init__(self, parent)
        self.progressBar = None
        self.cliNode = None
        self._cliNodeObserver = None
        self.folder = None
        self.params = None

        self.extractState = False
        self.kabsOneAngleState = False
        self.kabsMultiAngleState = False
        self.sensibilityState = False
        self.MICPState = False
        self.finished = False
        self.batchExecution = False

        self.logic_models = SubscaleLogicDict

    def set_subres_model(self, table_node, params):
        pore_network = geo2spy(table_node)
        x_size = float(table_node.GetAttribute("x_size"))
        y_size = float(table_node.GetAttribute("y_size"))
        z_size = float(table_node.GetAttribute("z_size"))
        volume = x_size * y_size * z_size

        subres_model = params["subres_model_name"]
        subres_params = params["subres_params"]
        if (subres_model == "Throat Radius Curve" or subres_model == "Pressure Curve") and subres_params:
            subres_params = {
                i: np.asarray(subres_params[i]) if subres_params[i] is not None else None for i in subres_params.keys()
            }

        subresolution_logic = self.logic_models[subres_model]
        subresolution_function = subresolution_logic().get_capillary_radius_function(
            subres_params, pore_network, volume
        )

        return subresolution_function

    def deleteSubjectHierarchyFolder(self, folderName):
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        folderItemID = shNode.GetItemByName(folderName)
        if folderItemID:
            folderNode = shNode.GetItemDataNode(folderItemID)
            if folderNode:
                slicer.mrmlScene.RemoveNode(folderNode)
            shNode.RemoveItem(folderItemID)
        slicer.app.processEvents()

    def runInBatch(
        self,
        simulator,
        inputNode,
        batchDir,
        segTag,
        roiTag,
        valTag,
        labelTag,
        output_path=None,
        mode="Local",
        outputPrefix="",
        params=None,
    ):
        self.simulator = simulator
        self.params = params
        self.output_path = output_path
        self.outputPrefix = outputPrefix
        self.mode = mode
        self.rootDir = None
        self.progressBar = None
        self.finished = False
        self.cancelled = False

        slicer.app.processEvents()
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        allItemIDs = vtk.vtkIdList()
        shNode.GetItemChildren(shNode.GetSceneItemID(), allItemIDs, True)

        batch_images = [Path(batchDir) / file for file in os.listdir(batchDir) if file.endswith(valTag)]
        for filepath in batch_images:
            if filepath and os.path.isfile(filepath):
                data, header = nrrd.read(filepath)
                del data
                if header["type"] == "int":
                    volume_node = slicer.util.loadLabelVolume(filepath)
                else:
                    volume_node = slicer.util.loadVolume(filepath)
            else:
                logging.debug(f"Error at loading {filepath}, file not exists")
                break

            params["well_name"] = Path(filepath).stem

            folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            itemTreeId = folderTree.GetSceneItemID()
            rootDir = folderTree.CreateFolderItem(itemTreeId, f"{params['well_name']} Report")
            folderTree.CreateItem(rootDir, volume_node)
            slicer.app.processEvents()

            self.finished = False

            self.run(
                simulator,
                inputNode,
                volume_node,
                labels=None,
                roiNode=None,
                output_path=output_path,
                mode=mode,
                outputPrefix=params["well_name"],
                params=params,
                isBatch=True,
            )

            while self.finished is False:
                time.sleep(0.2)
                slicer.app.processEvents()

            if self.cancelled is True:
                break

            self.deleteSubjectHierarchyFolder(f"{params['well_name']} Report")

        self.processFinished.emit()
        slicer.app.processEvents()

    def run(
        self,
        simulator,
        segmentationNode,
        referenceNode,
        labels,
        roiNode=None,
        output_path=None,
        mode="Local",
        outputPrefix="",
        params=None,
        isBatch=False,
    ):
        if referenceNode is None:
            return

        self.referenceNode = referenceNode
        self.params = params
        self.outputPrefix = outputPrefix
        self.json_entry_node_ids = {}
        self.pnm_report = {
            "well": None,
            "porosity": None,
            "permeability": None,
            "residual_So": None,
            "realistic_production": None,
        }
        if self.progressBar is None:
            self.progressBar = ProgressBarProc()
        self.cancelled = False

        self.pnm_report["well"] = params["well_name"]

        self.json_entry_node_ids["volume"] = referenceNode.GetID()
        if referenceNode.GetClassName() == "vtkMRMLLabelMapVolumeNode":
            self.pnm_report["porosity"] = (slicer.util.arrayFromVolume(referenceNode) > 0).mean()
        else:
            self.pnm_report["porosity"] = slicer.util.arrayFromVolume(referenceNode).mean()

        local_progress_bar = LocalProgressBar()
        self.extractor_logic = PoreNetworkExtractorLogic(self.parent(), local_progress_bar)
        self.one_phase_logic = OnePhaseSimulationLogic(self.parent(), local_progress_bar)
        self.two_phase_logic = TwoPhaseSimulationLogic(self.parent(), local_progress_bar)
        self.micp_logic = MercurySimulationLogic(self.parent(), local_progress_bar)

        # Set subresolution model
        if "subscale_model_params" in params:
            self.subresolution_function = lambda node: self.set_subres_model(node, params["subscale_model_params"])
            self.subres_model_name = params["subscale_model_params"]["subres_model_name"]
            self.subres_params = params["subscale_model_params"]["subres_params"]
        else:
            kabs_params = OnePhaseSimulationWidget().getParams()
            self.subresolution_function = kabs_params["subresolution function call"]
            self.subres_model_name = kabs_params["subres_model_name"]
            self.subres_params = kabs_params["subres_params"]

        # Queue with simulations
        self.sim_index = 0
        self.sim_queue = {
            "extraction": self.run_extract,
            "one-phase sim w/ one angle": self.run_1phase_one_angle,
            "one-phase sim w/ multi angle": self.run_1phase_multi_angle,
            "MICP sim": self.run_micp,
        }
        if params.get("sensibility_parameters_node") is not None:
            self.sim_queue.update({"sensibility test simulations": self.run_sensibility})

        self.batchExecution = isBatch

        self.controlSims = PNMQueue()
        self.controlSims.simChanged.connect(self.run_next_simulation)
        self.controlSims.simChanged.emit()

    def cancel(self):
        if self.progressBar:
            self.progressBar.nextStep(99, f"Stopping simulation on {self.referenceNode.GetName()}")
        self.extractor_logic.cancel()
        self.one_phase_logic.cancel()
        self.two_phase_logic.cancel()
        self.micp_logic.cancel()

        self.cancelled = True
        self.finished = True
        if self.progressBar:
            self.progressBar.nextStep(100, "Cancelled")
            self.progressBar.__exit__(None, None, None)
            self.progressBar = None

    def run_next_simulation(self):
        if self.cancelled:
            return

        sim_keys = list(self.sim_queue.keys())
        sim_list = list(self.sim_queue.values())

        progressStep = self.sim_index * 100.0 / len(self.sim_queue)
        self.progressBar.nextStep(progressStep, f"Running {sim_keys[self.sim_index]} on {self.referenceNode.GetName()}")

        sim_list[self.sim_index]()
        self.sim_index += 1

    def run_extract(self):
        watershed_blur = {
            1: 0.4,
            2: 0.8,
        }
        self.extractor_logic.extract(
            self.referenceNode,
            None,
            self.outputPrefix,
            True,
            "PoreSpy",
            watershed_blur,
            self.extract_callback(self.extractor_logic),
        )

    def extract_callback(self, logic):
        def onFinishExtract(state):
            if state:
                if logic.results:
                    self.pore_table = logic.results["pore_table"]
                    self.throat_table = logic.results["throat_table"]
                else:
                    logging.debug("No connected network was identified. Possible cause: unsegmented pore space.")
                    return

                self.json_entry_node_ids["pore_table"] = self.pore_table.GetID()
                self.json_entry_node_ids["throat_table"] = self.throat_table.GetID()

                model_nodes = logic.results.get("model_nodes")
                for i, node in enumerate(model_nodes["pores_nodes"]):
                    self.json_entry_node_ids[f"pore_polydata_{i}"] = node.GetID()
                for i, node in enumerate(model_nodes["throats_nodes"]):
                    self.json_entry_node_ids[f"throat_polydata_{i}"] = node.GetID()

                folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
                itemTreeId = folderTree.GetItemByDataNode(self.pore_table)
                parentItemId = folderTree.GetItemParent(itemTreeId)
                folderTree.SetItemExpanded(parentItemId, False)

                self.extractState = True

                slicer.app.processEvents()
                self.checkFinish()

        return onFinishExtract

    # Kabs One-angle
    def run_1phase_one_angle(self):
        kabs_params = OnePhaseSimulationWidget().getParams()
        kabs_params["keep_temporary"] = True
        kabs_params["subresolution function call"] = self.subresolution_function
        kabs_params["subresolution function"] = kabs_params["subresolution function call"](self.pore_table)
        kabs_params["subres_model_name"] = self.subres_model_name
        kabs_params["subres_params"] = self.subres_params
        try:
            self.one_phase_logic.run_1phase(
                self.pore_table,
                kabs_params,
                prefix=self.outputPrefix,
                callback=self.kabs_oneangle_callback(self.one_phase_logic),
            )
        except Exception:
            logging.error("Error occured in one-phase one-angle simulation")
            import traceback

            traceback.print_exc()

    def kabs_oneangle_callback(self, logic):
        def onFinishKabs(state):
            if state:
                if "flow_rate" in logic.results:
                    flow_rate_node = slicer.util.getNode(logic.results["flow_rate"])
                    self.json_entry_node_ids["flow_rate"] = flow_rate_node.GetID()

                if "permeability" in logic.results:
                    perm_node = slicer.util.getNode(logic.results["permeability"])
                    self.json_entry_node_ids["perm_node"] = perm_node.GetID()

                    perm_df = slicer.util.dataframeFromTable(perm_node)
                    self.pnm_report["permeability"] = np.diag(perm_df).mean()

                self.kabsOneAngleState = True

                slicer.app.processEvents()
                self.checkFinish()

        return onFinishKabs

    # Kabs Multi-angle
    def run_1phase_multi_angle(self):
        kabs_params = OnePhaseSimulationWidget().getParams()
        kabs_params["simulation type"] = "Multiple orientations"
        kabs_params["rotation angles"] = 100
        kabs_params["keep_temporary"] = True
        kabs_params["subresolution function call"] = self.subresolution_function
        kabs_params["subresolution function"] = kabs_params["subresolution function call"](self.pore_table)
        kabs_params["subres_model_name"] = self.subres_model_name
        kabs_params["subres_params"] = self.subres_params
        try:
            self.one_phase_logic.run_1phase(
                self.pore_table,
                kabs_params,
                prefix=self.outputPrefix,
                callback=self.kabs_multiangle_callback(self.one_phase_logic),
            )
        except Exception:
            logging.error("Error occured in one-phase multi-angle simulation.")
            import traceback

            traceback.print_exc()

    def kabs_multiangle_callback(self, logic):
        def onFinishKabs(state):
            if state:
                if all(v in logic.results for v in ["model", "arrow", "plane", "sphere"]):
                    model_node = slicer.util.getNode(logic.results["model"])
                    arrow_node = slicer.util.getNode(logic.results["arrow"])
                    plane_node = slicer.util.getNode(logic.results["plane"])
                    sphere_node = slicer.util.getNode(logic.results["sphere"])
                else:
                    return

                self.json_entry_node_ids["multiangle_model"] = model_node.GetID()
                self.json_entry_node_ids["multiangle_arrow_model"] = arrow_node.GetID()
                self.json_entry_node_ids["multiangle_plane_model"] = plane_node.GetID()
                self.json_entry_node_ids["multiangle_sphere_model"] = sphere_node.GetID()

                # measure angles
                plane_node = slicer.util.getNode(logic.results["plane"])
                plane_points = plane_node.GetPolyData().GetPoints()
                plane_v1 = np.array(plane_points.GetPoint(1)) - np.array(plane_points.GetPoint(0))
                plane_v2 = np.array(plane_points.GetPoint(2)) - np.array(plane_points.GetPoint(0))
                plane_normal = np.cross(plane_v2, plane_v1)

                direction = logic.results["direction"]
                angle_with_plane = np.pi / 2.0 - np.arccos(
                    np.dot(direction, plane_normal) / (np.linalg.norm(direction) * np.linalg.norm(plane_normal))
                )

                projection = direction - np.dot(direction, plane_normal) / np.linalg.norm(plane_normal)
                projection_angle_with_z = np.arccos(
                    np.dot(projection, np.array([0, 0, 1])) / np.linalg.norm(projection)
                )

                # measure min, max, mean, desvio padrão dos valores
                permeabilities = logic.results["permeabilities"]
                perm_stats = pd.DataFrame(permeabilities[:, 3]).describe()

                df = pd.DataFrame(
                    {
                        "Angle with plane (º)": angle_with_plane * 180 / np.pi,
                        "Projection angle with z-axis (º)": projection_angle_with_z * 180 / np.pi,
                        "Average Permeability (mD)": 1000 * perm_stats.loc["mean"].tolist()[0],
                        "Standard Deviation Permeability (mD)": 1000 * perm_stats.loc["std"].tolist()[0],
                        "Min. Permeability (mD)": 1000 * perm_stats.loc["min"].tolist()[0],
                        "Max. Permeability (mD)": 1000 * perm_stats.loc["max"].tolist()[0],
                    },
                    index=[0],
                )
                table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
                table.SetName("multiangle_statistics")
                du.dataFrameToTableNode(df, table)
                folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
                itemTreeId = folderTree.GetItemByDataNode(self.referenceNode)
                parentItemId = folderTree.GetItemParent(itemTreeId)
                folderTree.CreateItem(parentItemId, table)
                self.json_entry_node_ids["multiangle_statistics"] = table.GetID()

                self.kabsMultiAngleState = True

                slicer.app.processEvents()
                self.checkFinish()

        return onFinishKabs

    # Sensibilidade
    def run_sensibility(self):
        twoPhaseWidget = TwoPhaseSimulationWidget()
        twoPhaseWidget.parameterInputWidget.setCurrentNode(self.params["sensibility_parameters_node"])
        twoPhaseWidget.onParameterInputLoad()
        krel_params = twoPhaseWidget.getParams()
        krel_params["subresolution function call"] = self.subresolution_function
        krel_params["subresolution function"] = krel_params["subresolution function call"](self.pore_table)
        krel_params["subres_model_name"] = self.subres_model_name
        krel_params["subres_params"] = self.subres_params
        try:
            self.two_phase_logic.run_2phase(
                self.pore_table,
                None,
                krel_params,
                prefix=self.outputPrefix,
                callback=self.sensibility_callback(self.two_phase_logic),
            )
        except Exception:
            logging.debug("Error occured in two-phase sensibility simulation.")
            import traceback

            traceback.print_exc()

    def sensibility_callback(self, logic):
        def onFinishKrel(state):
            if state:
                try:
                    self.json_entry_node_ids["sensibility_parameters"] = self.params[
                        "sensibility_parameters_node"
                    ].GetID()

                    krelResultsTableNode = slicer.util.getNode(logic.krelResultsTableNodeId)
                    krelResultsTableNode.SetName("Sensibility")
                    self.json_entry_node_ids["sensibility"] = krelResultsTableNode.GetID()

                    krel_df = slicer.util.dataframeFromTable(krelResultsTableNode)
                    swr = krel_df["result-swr"]
                    self.pnm_report["residual_So"] = np.median(1 - swr)

                    for i in range(3):
                        krelCycleTableNode = slicer.util.getNode(logic.krelCycleTableNodesId[i])
                        krelCycleTableNode.SetName(f"Sensibility cycle {i}")
                        self.json_entry_node_ids[f"sensibility_cycle{i}"] = krelCycleTableNode.GetID()

                    # Production
                    pnm_production_logic = PoreNetworkProductionLogic()
                    water_viscosity = 0.001
                    oil_viscosity = 0.01
                    krel_smoothing = 2.0
                    simulation = 0
                    sensibility = True
                    production_table = pnm_production_logic.run(
                        krelResultsTableNode,
                        water_viscosity,
                        oil_viscosity,
                        krel_smoothing,
                        sensibility,
                        simulation,
                    )
                    self.json_entry_node_ids["production"] = production_table.GetID()

                    npd_points_vtk_array = production_table.GetTable().GetColumnByName("realistic_NpD")
                    npd_points = vtk.util.numpy_support.vtk_to_numpy(npd_points_vtk_array)
                    self.pnm_report["realistic_production"] = np.median(npd_points)

                    self.sensibilityState = True
                except Exception:
                    self.json_entry_node_ids["sensibility"] = None
                    self.json_entry_node_ids["production"] = None
                    for i in range(3):
                        self.json_entry_node_ids[f"sensibility_cycle{i}"] = None

                    self.pnm_report["residual_So"] = None
                    self.pnm_report["realistic_production"] = None

                    logging.error("Error on sensibility callback.")
                    import traceback

                    traceback.print_exc()

                slicer.app.processEvents()
                self.checkFinish()

        return onFinishKrel

    # MICP
    def run_micp(self):
        micp_params = MercurySimulationWidget().getParams()
        micp_params["subresolution function call"] = self.subresolution_function
        micp_params["subresolution function"] = micp_params["subresolution function call"](self.pore_table)
        micp_params["subres_model_name"] = self.subres_model_name
        micp_params["subres_params"] = self.subres_params
        try:
            self.micp_logic.run_mercury(
                self.pore_table,
                micp_params,
                prefix=self.outputPrefix,
                callback=self.micp_callback(self.micp_logic),
            )
        except Exception:
            logging.error("Error occured in micp simulation.")
            import traceback

            traceback.print_exc()

    def micp_callback(self, logic):
        def onFinishMICP(state):
            if state:
                micp_results_node_id = logic.results_node_id
                if micp_results_node_id:
                    self.json_entry_node_ids["micp"] = micp_results_node_id

                flow_props_pore_id = logic.flow_props_pore_id
                flow_props_throat_id = logic.flow_props_throat_id
                if flow_props_pore_id and flow_props_throat_id:
                    self.json_entry_node_ids["flow_props_pore_network"] = flow_props_pore_id
                    self.json_entry_node_ids["flow_props_throat_network"] = flow_props_throat_id

                self.MICPState = True

                slicer.app.processEvents()
                self.checkFinish()

        return onFinishMICP

    # Check for finish or send another simulation in queue
    def checkFinish(self):
        if self.sim_index < len(self.sim_queue):
            self.controlSims.simChanged.emit()
        else:
            if not self.referenceNode:
                return

            self.progressBar.nextStep(99, "Saving report")

            self.prepare_directory_structure()
            self.save_folder_report_dict()
            self.process_json_entries()

            self.finished = True
            self.progressBar.nextStep(100, "Completed")
            self.progressBar.__exit__(None, None, None)
            self.progressBar = None

            if not self.batchExecution:
                self.processFinished.emit()

            slicer.app.processEvents()

    def prepare_directory_structure(self):
        current_path = self.params["report_folder"]

        # ensure scripts exists or copy into the folder
        if not (Path(current_path) / "PNM_Report.py").exists():
            origin_path = Path(__file__).parent.parent.resolve() / "streamlit"
            shutil.copytree(origin_path, current_path)

        # ensure static folder exist
        folder = Path(current_path) / "static"
        folder.mkdir(parents=True, exist_ok=True)

        # ensure projects.json exist or create an empty
        projects_path = folder / "projects.json"
        if not projects_path.exists():
            with open(projects_path, "w") as f:
                f.write("")

        # load projects.json
        with open(projects_path, "r") as f:
            self.projects_dict = json.load(f) if projects_path.stat().st_size != 0 else {}

        # if already exist this project, remove to replace it
        if (folder / self.outputPrefix).exists():
            shutil.rmtree(folder / self.outputPrefix)
        os.mkdir(folder / self.outputPrefix)

    def save_folder_report_dict(self):
        folder = Path(self.params["report_folder"]) / "static"
        pnm_report_path = folder / "folder_report.csv"
        pnm_report_df = pd.DataFrame(self.pnm_report, index=[0])
        if pnm_report_path.exists():
            existing_df = pd.read_csv(pnm_report_path, index_col=0)
            updated_df = pd.concat([existing_df, pnm_report_df], ignore_index=True)
        else:
            updated_df = pnm_report_df
        updated_df.index.name = "index"
        updated_df.to_csv(pnm_report_path, index=True, mode="w")

    def process_json_entries(self):
        folder = Path(self.params["report_folder"]) / "static"
        self.json_entry = {}

        for key, node_id in self.json_entry_node_ids.items():
            node = slicer.mrmlScene.GetNodeByID(node_id) if node_id else None

            if node:
                name = self.save_node_data(folder, key, node)
                self.json_entry[key] = os.path.basename(name)
            else:
                continue

        name = f"{folder}/{self.outputPrefix}/subres_model.json"
        with open(name, "w") as f:
            json.dump({self.subres_model_name: self.subres_params}, f)
        self.json_entry["subres_model"] = os.path.basename(name)

        self.projects_dict[self.outputPrefix] = self.json_entry

        projects_path = folder / "projects.json"
        with open(projects_path, "w") as f:
            json.dump(self.projects_dict, f)

    def save_node_data(self, folder, key, node):
        if isinstance(node, slicer.vtkMRMLScalarVolumeNode) or isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
            name = f"{folder}/{self.outputPrefix}/{key}.nrrd"
            slicer.util.saveNode(node, name)
            file_size = os.path.getsize(name)
            if file_size > 200000000:
                self.downscale_volume_node(node, name)
        elif isinstance(node, slicer.vtkMRMLTableNode):
            name = f"{folder}/{self.outputPrefix}/{key}.tsv"
            slicer.util.saveNode(node, name)
        elif isinstance(node, slicer.vtkMRMLModelNode):
            name = self.save_model_node(folder, key, node)

        return name

    def downscale_volume_node(self, node, name):
        original_spacing = np.array(node.GetSpacing())
        original_dimensions = np.array(node.GetImageData().GetDimensions())
        target_dimensions = np.array([200, 200, 200])
        new_spacing = original_spacing * (original_dimensions / target_dimensions)

        ResampleScalarVolumeData = namedtuple(
            "ResampleScalarVolumeData", ["input", "outputSuffix", "x", "y", "z", "interpolationType"]
        )
        parameters = ResampleScalarVolumeData(
            input=node,
            outputSuffix="Resampled",
            x=new_spacing[0],
            y=new_spacing[1],
            z=new_spacing[2],
            interpolationType="Nearest Neighbor" if node.IsA("vtkMRMLLabelMapVolumeNode") else "Linear",
        )

        local_progress_bar = LocalProgressBar()
        resample_logic = CustomResampleScalarVolumeLogic(local_progress_bar)
        resample_logic.run(parameters, cli_wait=True)

        node_downscaled = slicer.util.getNode(node.GetName() + "_" + parameters.outputSuffix)
        slicer.util.saveNode(node_downscaled, name)

    def save_model_node(self, folder, key, node):
        name = f"{folder}/{self.outputPrefix}/{key}.vtk"
        writer = vtk.vtkPolyDataWriter()
        writer.SetFileVersion(42)
        writer.SetFileName(name)
        writer.SetInputData(node.GetPolyData())
        writer.SetFileTypeToASCII()
        writer.Write()
        if key == "multiangle_model":
            name = f"{folder}/{self.outputPrefix}/{key}.vtp"
            writer = vtk.vtkXMLPolyDataWriter()
            writer.SetFileName(name)
            writer.SetInputData(node.GetPolyData())
            writer.Write()

        return name
