import numpy as np
import openpnm
import pandas as pd
import slicer
import pickle

import itertools
import json
import logging
import os
import shutil
from pathlib import Path

from ltrace.pore_networks.functions import geo2spy
from ltrace.slicer_utils import LTracePluginLogic, dataFrameToTableNode, slicer_is_in_developer_mode

HG_SURFACE_TENSION = 480  # 480N/km 0.48N/m 48e-5N/mm 48dyn/mm 480dyn/cm
HG_CONTACT_ANGLE = 140  # º


def estimate_radius(capilary_pressure):
    theta = (np.pi * HG_CONTACT_ANGLE) / 180.0
    return abs(2.0 * HG_SURFACE_TENSION * np.cos(theta)) / capilary_pressure


def estimate_pressure(radius):
    theta = (np.pi * HG_CONTACT_ANGLE) / 180.0
    return abs(2.0 * HG_SURFACE_TENSION * np.cos(theta)) / radius


class MercurySimulationLogic(LTracePluginLogic):
    def __init__(self, progressBar):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar
        self.prefix = None
        self.rootDir = None
        self.results_node_id = None

    def run_mercury(self, inputTable, params, prefix, callback, wait=False):
        self.params = params
        self.params["save_tables"] = slicer_is_in_developer_mode()
        self.cwd = Path(slicer.util.tempDirectory())
        self.callback = callback
        self.prefix = prefix

        self.temp_dir = f"{slicer.app.temporaryPath}/porenetworksimulationcli"
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        os.mkdir(self.temp_dir)

        cliParams = {
            "model": "MICP",
            "cwd": str(self.cwd),
            "tempDir": self.temp_dir,
        }

        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
        itemTreeId = folderTree.GetItemByDataNode(inputTable)
        parentItemId = folderTree.GetItemParent(folderTree.GetItemParent(itemTreeId))
        self.rootDir = folderTree.CreateFolderItem(parentItemId, f"{prefix} Mercury Injection Simulation")
        folderTree.SetItemExpanded(self.rootDir, False)

        pore_network = geo2spy(inputTable)

        dict_file = open(str(self.cwd / "pore_network.dict"), "wb")
        pickle.dump(pore_network, dict_file)
        dict_file.close()

        subresolution_function = self.params["subresolution function"]
        del self.params["subresolution function"]
        del self.params["subresolution function call"]

        self.params["sizes"] = {
            "x": float(inputTable.GetAttribute("x_size")) / 10,  ## TODO divide por 10?
            "y": float(inputTable.GetAttribute("y_size")) / 10,
            "z": float(inputTable.GetAttribute("z_size")) / 10,
        }  # values in cm

        with open(str(self.cwd / "params_dict.json"), "w") as file:
            json.dump(self.params, file)

        self.cliNode = slicer.cli.run(
            slicer.modules.porenetworksimulationcli, None, cliParams, wait_for_completion=wait
        )
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.micpCLICallback)

    def cancel(self):
        if self.cliNode is None:
            return
        self.cliNode.Cancel()

    def micpCLICallback(self, caller, event):
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
                self.onFinish()

            if not self.params["keep_temporary"]:
                shutil.rmtree(self.cwd)

            self.callback(True)

    def onFinish(self):
        pc = pd.read_pickle(str(self.cwd / "micpResults.pd"))

        with open(str(self.cwd / "return_net.dict"), "rb") as file:
            net = pickle.load(file)

        delta_saturation = np.diff(pc.snwp, n=1, prepend=0)
        throat_radii = estimate_radius(pc.pc)
        micp_results = pd.DataFrame({"pc": pc.pc, "snwp": pc.snwp, "dsn": delta_saturation, "radii": throat_radii})

        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
        micpTableName = slicer.mrmlScene.GenerateUniqueName("MICP")
        micpTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", micpTableName)
        micpTable.SetAttribute("table_type", "micp")
        self.results_node_id = micpTable.GetID()
        _ = dataFrameToTableNode(micp_results, micpTable)
        _ = folderTree.CreateItem(self.rootDir, micpTable)

        self.setChartNodes(micpTable, self.rootDir)

        if self.params["save_radii_distrib_plots"]:
            self.setDistributionFolderAndChartNodes(self.rootDir, net, micp_results, self.params["experimental_radius"])

    def setChartNodes(self, micpTable, currentDir):
        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()

        seriesSnwpNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", "Simulated MICP Curve")
        micpTable.SetAttribute("micp data", seriesSnwpNode.GetID())
        seriesSnwpNode.SetAndObserveTableNodeID(micpTable.GetID())
        seriesSnwpNode.SetYColumnName("pc")
        seriesSnwpNode.SetXColumnName("snwp")
        seriesSnwpNode.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter)
        seriesSnwpNode.SetLineStyle(slicer.vtkMRMLPlotSeriesNode.LineStyleSolid)
        seriesSnwpNode.SetMarkerStyle(slicer.vtkMRMLPlotSeriesNode.MarkerStyleCircle)
        seriesSnwpNode.SetColor(0.1, 0.1, 0.9)
        seriesSnwpNode.SetLineWidth(3)
        seriesSnwpNode.SetMarkerSize(7)
        folderTree.CreateItem(currentDir, seriesSnwpNode)

        seriesDeltaNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", "Effective Pressure Distribution")
        micpTable.SetAttribute("pc data", seriesDeltaNode.GetID())
        seriesDeltaNode.SetAndObserveTableNodeID(micpTable.GetID())
        seriesDeltaNode.SetXColumnName("pc")
        seriesDeltaNode.SetYColumnName("dsn")
        seriesDeltaNode.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter)
        seriesDeltaNode.SetLineStyle(slicer.vtkMRMLPlotSeriesNode.LineStyleSolid)
        seriesDeltaNode.SetMarkerStyle(slicer.vtkMRMLPlotSeriesNode.MarkerStyleCircle)
        seriesDeltaNode.SetColor(0.1, 0.9, 0.1)
        seriesDeltaNode.SetLineWidth(3)
        seriesDeltaNode.SetMarkerSize(7)
        folderTree.CreateItem(currentDir, seriesDeltaNode)

        seriesRadiiNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", "Effective Radii Distribution")
        micpTable.SetAttribute("radii data", seriesRadiiNode.GetID())
        seriesRadiiNode.SetAndObserveTableNodeID(micpTable.GetID())
        seriesRadiiNode.SetXColumnName("radii")
        seriesRadiiNode.SetYColumnName("dsn")
        seriesRadiiNode.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter)
        seriesRadiiNode.SetLineStyle(slicer.vtkMRMLPlotSeriesNode.LineStyleSolid)
        seriesRadiiNode.SetMarkerStyle(slicer.vtkMRMLPlotSeriesNode.MarkerStyleCircle)
        seriesRadiiNode.SetColor(0.1, 0.1, 0.75)
        seriesRadiiNode.SetLineWidth(3)
        seriesRadiiNode.SetMarkerSize(7)
        folderTree.CreateItem(currentDir, seriesRadiiNode)

    def setDistributionFolderAndChartNodes(self, currentDir, net, micp_results, experimental_radius=None):
        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()

        def create_histogram_data(data, bins):
            bins = np.sort(bins)
            lbin = bins[0] - (bins[1] - bins[0]) / 2
            rbin = bins[-1] + (bins[-1] - bins[-2]) / 2
            bins = np.concatenate(([lbin], (bins[:-1] + bins[1:]) / 2, [rbin]))
            hist, bin_edges = np.histogram(data, bins=bins)
            return hist, bin_edges

        def create_table_node_and_series(
            folderTree, current_dir, table_name, hist_data, bin_edges, table_type, plot_type, color=(0.1, 0.1, 0.75)
        ):
            table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", table_name)
            table.SetAttribute("table_type", table_type)
            df_data = pd.DataFrame.from_dict({"radii": bin_edges[:-1] + np.diff(bin_edges) / 2, "prob": hist_data})
            _ = dataFrameToTableNode(df_data, table)
            _ = folderTree.CreateItem(current_dir, table)

            series_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", table_name)
            table.SetAttribute("radii_prob_data", series_node.GetID())
            series_node.SetAndObserveTableNodeID(table.GetID())
            series_node.SetXColumnName("radii")
            series_node.SetYColumnName("prob")
            series_node.SetPlotType(plot_type)
            series_node.SetLineStyle(slicer.vtkMRMLPlotSeriesNode.LineStyleSolid)
            series_node.SetMarkerStyle(slicer.vtkMRMLPlotSeriesNode.MarkerStyleCircle)
            series_node.SetColor(*color)
            series_node.SetLineWidth(3)
            series_node.SetMarkerSize(7)
            _ = folderTree.CreateItem(current_dir, series_node)

        df = openpnm.io.network_to_pandas(net)

        ##################################################

        poreVolumeDir = folderTree.CreateFolderItem(currentDir, f"Pore volume distributions")
        folderTree.SetItemExpanded(poreVolumeDir, False)

        table_type = "pore"
        bins = experimental_radius if experimental_radius is not None else micp_results["radii"]
        hist_range = (0, df[table_type]["pore.effective_volume"].max())
        pore_phases_num = df[table_type]["pore.phase"].to_numpy().max()

        pore_volume_hist, bin_edges = create_histogram_data(df[table_type]["pore.effective_volume"], bins)
        poreTableName = slicer.mrmlScene.GenerateUniqueName("Pore Volume Distribution")
        create_table_node_and_series(
            folderTree,
            poreVolumeDir,
            poreTableName,
            pore_volume_hist / len(df[table_type]),
            bin_edges,
            table_type,
            slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter,
        )

        pore_phases_num = df[table_type]["pore.phase"].to_numpy().max()
        if pore_phases_num == 2:
            for phase in range(1, pore_phases_num + 1):
                phase_filter = df[table_type]["pore.phase"] == phase
                pore_volume_hist, bin_edges = create_histogram_data(
                    df[table_type]["pore.effective_volume"][phase_filter], bins
                )
                if phase == 1:
                    poreTableName = slicer.mrmlScene.GenerateUniqueName("Resolved Pore Volume Distribution")
                    color = (0.1, 0.75, 0.1)
                else:
                    poreTableName = slicer.mrmlScene.GenerateUniqueName("Unresolved Pore Volume Distribution")
                    color = (0.75, 0.1, 0.1)
                create_table_node_and_series(
                    folderTree,
                    poreVolumeDir,
                    poreTableName,
                    pore_volume_hist / len(df[table_type]),
                    bin_edges,
                    table_type,
                    slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter,
                    color=color,
                )

        ##################################################

        throatVolumeDir = folderTree.CreateFolderItem(currentDir, f"Throat volume distributions")
        folderTree.SetItemExpanded(throatVolumeDir, False)

        table_type = "throat"
        bins = experimental_radius if experimental_radius is not None else micp_results["radii"]
        hist_range = (0, df[table_type]["throat.volume"].max())

        throat_volume_hist, bin_edges = create_histogram_data(df[table_type]["throat.volume"], bins)
        throatTableName = slicer.mrmlScene.GenerateUniqueName("Throat Volume Distribution")
        create_table_node_and_series(
            folderTree,
            throatVolumeDir,
            throatTableName,
            throat_volume_hist / len(df[table_type]),
            bin_edges,
            table_type,
            slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter,
        )

        ##################################################

        poreRadiiDir = folderTree.CreateFolderItem(currentDir, f"Pore radii distributions")
        folderTree.SetItemExpanded(poreRadiiDir, False)

        table_type = "pore"
        bins = experimental_radius if experimental_radius is not None else micp_results["radii"]
        hist_range = (0, df[table_type]["pore.cap_radius"].max())

        pore_radii_hist, bin_edges = create_histogram_data(df[table_type]["pore.cap_radius"], bins)
        poreTableName = slicer.mrmlScene.GenerateUniqueName("Pore Radii Distribution")
        create_table_node_and_series(
            folderTree,
            poreRadiiDir,
            poreTableName,
            pore_radii_hist / len(df[table_type]),
            bin_edges,
            table_type,
            slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter,
        )

        if pore_phases_num == 2:
            for phase in range(1, pore_phases_num + 1):
                phase_filter = df[table_type]["pore.phase"] == phase
                pore_radii_hist, bin_edges = create_histogram_data(
                    df[table_type]["pore.cap_radius"][phase_filter], bins
                )
                if phase == 1:
                    poreTableName = slicer.mrmlScene.GenerateUniqueName("Resolved Pore Radii Distribution")
                    color = (0.1, 0.75, 0.1)
                else:
                    poreTableName = slicer.mrmlScene.GenerateUniqueName("Unresolved Pore Radii Distribution")
                    color = (0.75, 0.1, 0.1)
                create_table_node_and_series(
                    folderTree,
                    poreRadiiDir,
                    poreTableName,
                    pore_radii_hist / len(df[table_type]),
                    bin_edges,
                    table_type,
                    slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter,
                    color=color,
                )

        ##################################################

        throatRadiiDir = folderTree.CreateFolderItem(currentDir, f"Throat radii distributions")
        folderTree.SetItemExpanded(throatRadiiDir, False)

        table_type = "throat"
        bins = experimental_radius if experimental_radius is not None else micp_results["radii"]
        hist_range = (0, df[table_type]["throat.cap_radius"].max())

        throat_radii_hist, bin_edges = create_histogram_data(df[table_type]["throat.cap_radius"], bins)
        throatTableName = slicer.mrmlScene.GenerateUniqueName("Throat Radii Distribution")
        create_table_node_and_series(
            folderTree,
            throatRadiiDir,
            throatTableName,
            throat_radii_hist / len(df[table_type]),
            bin_edges,
            table_type,
            slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter,
        )

        if pore_phases_num == 2:
            throat_radii = df[table_type]["throat.cap_radius"]
            phase1_filter = df[table_type]["throat.phase1_phase1"] == True
            phase2_filter = df[table_type]["throat.phase2_phase2"] == True
            phase1_phase2_filter = df[table_type]["throat.phase1_phase2"] == True
            phase2_phase1_filter = df[table_type]["throat.phase2_phase1"] == True

            throat_radii_hist, bin_edges = create_histogram_data(throat_radii[phase1_filter], bins)
            throatTableName = slicer.mrmlScene.GenerateUniqueName("Resolved Throat Radii Distribution")
            create_table_node_and_series(
                folderTree,
                throatRadiiDir,
                throatTableName,
                throat_radii_hist / len(df[table_type]),
                bin_edges,
                table_type,
                slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter,
                color=(0.75, 0.1, 0.1),
            )

            throat_radii_hist, bin_edges = create_histogram_data(
                throat_radii[phase1_phase2_filter | phase2_phase1_filter | phase2_filter], bins
            )
            throatTableName = slicer.mrmlScene.GenerateUniqueName("Unresolved Throat Radii Distribution")
            create_table_node_and_series(
                folderTree,
                throatRadiiDir,
                throatTableName,
                throat_radii_hist / len(df[table_type]),
                bin_edges,
                table_type,
                slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter,
                color=(0.1, 0.75, 0.1),
            )


class FixedRadiusLogic:
    required_params = ("radius",)

    def __init__(self):
        pass

    @classmethod
    def get_capillary_pressure_function(cls, params, pore_network, volume):
        for required_param in cls.required_params:
            params[required_param]

        return lambda _: estimate_pressure(params["radius"])


class LeverettOldLogic:
    required_params = ("J", "Sw", "corey_a", "corey_b", "model")
    models = {
        "k = a * phi ** b": lambda a, b, phi: a * phi**b,
    }

    def __init__(self):
        pass

    @classmethod
    def get_capillary_pressure_function(cls, params, pore_network, volume):
        for required_param in cls.required_params:
            params[required_param]

        total_pore_volume = pore_network["pore.region_volume"].sum()
        porosity = total_pore_volume / volume
        corey = cls.models[params["model"]](params["corey_a"], params["corey_b"], porosity)
        Pc = (params["J"] / 2) * estimate_pressure(np.sqrt(corey / porosity))

        radii = pore_network["throat.equivalent_diameter"] / 2
        resolved_throats = np.logical_and(
            pore_network["throat.phases"][:, 0],
            pore_network["throat.phases"][:, 1],
        )
        resolved_radii = radii[resolved_throats]
        smallest_raddi = resolved_radii.min()
        highest_pc = estimate_pressure(smallest_raddi)
        highest_pc_index = Pc >= highest_pc
        if highest_pc_index.sum() == 0:
            return lambda _: highest_pc

        porosity_cdf = cls._get_cumulative_dist_points(pore_network["throat.subresolution_porosity"])
        pressure_cdf = cls._get_cumulative_dist_function(
            Pc[highest_pc_index],
            params["Sw"][highest_pc_index],
        )

        def pressure_function(phi):
            phi_position = np.interp(phi, porosity_cdf["x"], porosity_cdf["y"])
            estimated_pressure = np.interp(phi_position, pressure_cdf["y"], pressure_cdf["x"])
            return estimated_pressure

        return pressure_function

    @classmethod
    def _get_cumulative_dist_function(cls, x, y):
        cumulative_y = np.zeros(x.size)
        for i in range(1, x.size):
            area = ((y[i] + y[i - 1]) / 2) * (x[i] - x[i - 1])
            cumulative_y[i] = cumulative_y[i - 1] + area
        cumulative_y /= cumulative_y[-1]
        return {"x": x, "y": cumulative_y}

    @classmethod
    def _get_cumulative_dist_points(cls, points):
        cumulative_y = np.zeros(99)
        cumulative_x = np.zeros(99)
        hist, hist_edges = np.histogram(points, 99)
        cumulative_x[0] = hist_edges[0]
        for i in range(99):
            area = (hist[i]) * (hist_edges[i + 1] - hist_edges[i])
            cumulative_x[i] = hist_edges[i]
            cumulative_y[i] = cumulative_y[i - 1] + area
        cumulative_y /= cumulative_y[-1]
        return {"x": cumulative_x, "y": cumulative_y}


class LeverettNewLogic:
    required_params = ("J", "Sw", "permeability")

    def __init__(self):
        pass

    @classmethod
    def get_capillary_pressure_function(cls, params, pore_network, volume):
        for required_param in cls.required_params:
            params[required_param]

        total_pore_volume = pore_network["pore.region_volume"].sum()
        porosity = total_pore_volume / volume
        Pc = (params["J"] / 2) * estimate_pressure(params["permeability"] / porosity)

        radii = pore_network["throat.equivalent_diameter"] / 2
        resolved_throats = np.logical_and(
            pore_network["throat.phases"][:, 0],
            pore_network["throat.phases"][:, 1],
        )
        resolved_radii = radii[resolved_throats]
        smallest_raddi = resolved_radii.min()
        highest_pc = estimate_pressure(smallest_raddi)
        highest_pc_index = Pc >= highest_pc
        if highest_pc_index.sum() == 0:
            return lambda _: highest_pc

        porosity_cdf = cls._get_cumulative_dist_points(pore_network["throat.subresolution_porosity"])
        pressure_cdf = cls._get_cumulative_dist_function(
            Pc[highest_pc_index],
            params["Sw"][highest_pc_index],
        )

        def pressure_function(phi):
            phi_position = np.interp(phi, porosity_cdf["x"], porosity_cdf["y"])
            estimated_pressure = np.interp(phi_position, pressure_cdf["y"], pressure_cdf["x"])
            return estimated_pressure

        return pressure_function

    @classmethod
    def _get_cumulative_dist_function(cls, x, y):
        cumulative_y = np.zeros(x.size)
        for i in range(1, x.size):
            area = ((y[i] + y[i - 1]) / 2) * (x[i] - x[i - 1])
            cumulative_y[i] = cumulative_y[i - 1] + area
        cumulative_y /= cumulative_y[-1]
        return {"x": x, "y": cumulative_y}

    @classmethod
    def _get_cumulative_dist_points(cls, points):
        cumulative_y = np.zeros(99)
        cumulative_x = np.zeros(99)
        hist, hist_edges = np.histogram(points, 99)
        cumulative_x[0] = hist_edges[0]
        for i in range(99):
            area = (hist[i]) * (hist_edges[i + 1] - hist_edges[i])
            cumulative_x[i] = hist_edges[i]
            cumulative_y[i] = cumulative_y[i - 1] + area
        cumulative_y /= cumulative_y[-1]
        return {"x": cumulative_x, "y": cumulative_y}


class PressureCurveLogic:
    required_params = ("throat radii", "capillary pressure", "dsn")

    def __init__(self):
        pass

    @classmethod
    def get_capillary_pressure_function(cls, params, pore_network, volume):
        for required_param in cls.required_params:
            params[required_param]
        pnm_radii = pore_network["throat.equivalent_diameter"] / 2

        resolved_throats = np.logical_and(
            pore_network["throat.phases"][:, 0] != 2,
            pore_network["throat.phases"][:, 1] != 2,
        )
        resolved_radii = pnm_radii[resolved_throats]
        if resolved_radii.size == 0:
            return lambda _: None

        smallest_resolved_raddi = resolved_radii.min()

        if params["throat radii"] is not None:
            subresolution_radii_bool_index = np.logical_and(
                params["throat radii"] > 1e-8, params["throat radii"] <= smallest_resolved_raddi
            )
            if subresolution_radii_bool_index.sum() == 0:
                return lambda _: smallest_resolved_raddi / 2
            elif subresolution_radii_bool_index.sum() == 1:
                return lambda _: params["throat radii"][subresolution_radii_bool_index][0]

            radius = params["throat radii"][subresolution_radii_bool_index]
            Pc = estimate_pressure(radius)
            Fvol = params["dsn"][subresolution_radii_bool_index]
        elif params["capillary pressure"] is not None:
            Pc = params["capillary pressure"]
            Fvol = params["dsn"]

        porosity_cdf = cls._get_cumulative_dist_points(pore_network["throat.subresolution_porosity"])
        pressure_cdf = cls._get_cumulative_dist_function(
            Pc,
            Fvol,
        )

        def pressure_function(phi):
            phi_position = np.interp(phi, porosity_cdf["x"], porosity_cdf["y"])
            estimated_pressure = np.interp(phi_position, pressure_cdf["y"], pressure_cdf["x"])
            return estimated_pressure

        return pressure_function

    @classmethod
    def _get_cumulative_dist_function(cls, x, y):
        cumulative_y = np.zeros(x.size)
        for i in range(1, x.size):
            area = ((y[i] + y[i - 1]) / 2) * (x[i] - x[i - 1])
            cumulative_y[i] = cumulative_y[i - 1] + area
        cumulative_y /= cumulative_y[-1]
        return {"x": x, "y": cumulative_y}

    @classmethod
    def _get_cumulative_dist_points(cls, points):
        cumulative_y = np.zeros(99)
        cumulative_x = np.zeros(99)
        hist, hist_edges = np.histogram(points, 99)
        cumulative_x[0] = hist_edges[0]
        for i in range(99):
            area = (hist[i]) * (hist_edges[i + 1] - hist_edges[i])
            cumulative_x[i] = hist_edges[i]
            cumulative_y[i] = cumulative_y[i - 1] + area
        cumulative_y /= cumulative_y[-1]
        return {"x": cumulative_x, "y": cumulative_y}
