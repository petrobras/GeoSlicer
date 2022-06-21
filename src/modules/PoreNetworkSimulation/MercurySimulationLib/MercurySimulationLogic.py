import numpy as np
import openpnm
import pandas as pd
import slicer

from ltrace.pore_networks.functions import (
    single_phase_permeability,
    geo2pnf,
    geo2spy,
    get_connected_spy_network,
    get_sub_spy,
)
from ltrace.pore_networks.vtk_utils import (
    create_flow_model,
    create_permeability_sphere,
)
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

HG_SURFACE_TENSION = 480  # 480N/km 0.48N/m 48e-5N/mm 48dyn/mm 480dyn/cm
HG_CONTACT_ANGLE = 140  # º


def estimate_radius(capilary_pressure):
    theta = (np.pi * HG_CONTACT_ANGLE) / 180.0
    return abs(2.0 * HG_SURFACE_TENSION * np.cos(theta)) / capilary_pressure


def estimate_pressure(radius):
    theta = (np.pi * HG_CONTACT_ANGLE) / 180.0
    return abs(2.0 * HG_SURFACE_TENSION * np.cos(theta)) / radius


class MercurySimulationLogic:
    def __init__(self):
        pass

    def run_mercury(self, pore_node, subresolution_function, prefix):
        pc = None
        progress = 0

        for res in self.simulate_mercury(pore_node, subresolution_function):  # remover complexidade
            progress, pc = res
            yield progress

        delta_saturation = np.diff(pc.snwp, n=1, prepend=0)
        throat_radii = estimate_radius(pc.pc)
        micp_results = pd.DataFrame({"pc": pc.pc, "snwp": pc.snwp, "dsn": delta_saturation, "radii": throat_radii})

        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemTreeId = folderTree.GetItemByDataNode(pore_node)
        parentItemId = folderTree.GetItemParent(folderTree.GetItemParent(itemTreeId))
        currentDir = folderTree.CreateFolderItem(parentItemId, f"{prefix} Mercury Injection Simulation")
        folderTree.SetItemExpanded(currentDir, False)

        micpTableName = slicer.mrmlScene.GenerateUniqueName("MICP")
        micpTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", micpTableName)
        micpTable.SetAttribute("table_type", "micp")
        _ = dataFrameToTableNode(micp_results, micpTable)
        _ = folderTree.CreateItem(currentDir, micpTable)

        self.setChartNodes(micpTable, folderTree, currentDir)

        yield 100

    def set_subresolution_adaptation(self, net, subresolution_function):
        phase = net["throat.phases"][:, 0] + net["throat.phases"][:, 1]
        net["throat.phases"][:, :] = 1

        radius = net["throat.inscribed_diameter"] / 2
        phi = net["throat.subresolution_porosity"]
        net["throat.entry_pressure"] = np.zeros(phase.shape)
        net["throat.entry_pressure"][phase == 2] = estimate_pressure(radius[phase == 2])
        net["throat.entry_pressure"][phase != 2] = subresolution_function(phi[phase != 2])
        net["throat.inscribed_diameter"] = 2 * estimate_radius(net["throat.entry_pressure"])

        net["throat.diameter"] = net["throat.inscribed_diameter"]
        net["throat.cross_sectional_area"] = np.pi * (net["throat.diameter"] / 2) ** 2
        net["throat.volume"] = np.where(
            phase == 1,
            net["throat.total_length"] * net["throat.cross_sectional_area"],
            net["throat.total_length"] * net["throat.cross_sectional_area"] / 2,
        )

        # net["pore.phase"][:] = 1
        net["pore.volume"] *= net["pore.subresolution_porosity"]

    def simulate_mercury(
        self,
        pore_node,
        subresolution_function,
        pressures=200,
    ):
        pore_network = geo2spy(pore_node)

        proj = openpnm.io.network_from_porespy(pore_network)
        connected_pores, connected_throats = get_connected_spy_network(proj.network, "xmin", "xmax")
        sub_network = get_sub_spy(pore_network, connected_pores, connected_throats)
        if sub_network is False:
            print("No subnetwork found")
            return (0, None)
        for prop in sub_network.keys():
            np.nan_to_num(sub_network[prop], copy=False)

        net = openpnm.io.network_from_porespy(sub_network)

        self.set_subresolution_adaptation(net, subresolution_function)

        hg = openpnm.phase.Mercury(network=net, name="mercury")

        phys = openpnm.models.collections.physics.basic
        hg.add_model_collection(phys)
        hg.regenerate_models()

        mip = openpnm.algorithms.Drainage(network=net, phase=hg)
        mip.set_inlet_BC(pores=net.pores("xmin"), mode="overwrite")
        mip.set_outlet_BC(pores=net.pores("xmax"), mode="overwrite")

        # mip.run()
        # code block originally taken from openpnm source
        phase = mip.project[mip.settings.phase]
        phase[mip.settings.throat_entry_pressure] = net["throat.entry_pressure"]
        hi = 1.25 * phase[mip.settings.throat_entry_pressure].max()
        low = 0.80 * phase[mip.settings.throat_entry_pressure].min()
        pressures = np.logspace(np.log10(low), np.log10(hi), pressures)
        pressures = np.array(pressures, ndmin=1)
        for i, p in enumerate(pressures):
            mip._run_special(p)
            pmask = mip["pore.invaded"] * (mip["pore.invasion_pressure"] == np.inf)
            mip["pore.invasion_pressure"][pmask] = p
            mip["pore.invasion_sequence"][pmask] = i
            tmask = mip["throat.invaded"] * (mip["throat.invasion_pressure"] == np.inf)
            mip["throat.invasion_pressure"][tmask] = p
            mip["throat.invasion_sequence"][tmask] = i
            yield (int(100 * i / pressures.size), None)
        # if np.any(mip["pore.bc.outlet"]):
        #    mip.apply_trapping()

        pc = mip.pc_curve()

        yield (100, pc)

    def setChartNodes(self, micpTable, folderTree, currentDir):
        micpChartNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode", "Mercury Injection Chart")
        folderTree.CreateItem(currentDir, micpChartNode)
        seriesSnwpNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", "MICP")
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
        micpChartNode.AddAndObservePlotSeriesNodeID(seriesSnwpNode.GetID())
        folderTree.CreateItem(currentDir, seriesSnwpNode)

        deltaChartNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode", "Mercury Injection Delta Chart")
        folderTree.CreateItem(currentDir, deltaChartNode)
        seriesDeltaNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", "Delta MICP")
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
        deltaChartNode.AddAndObservePlotSeriesNodeID(seriesDeltaNode.GetID())
        folderTree.CreateItem(currentDir, seriesDeltaNode)

        radiiChartNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode", "Mercury Injection Delta Chart")
        folderTree.CreateItem(currentDir, radiiChartNode)
        seriesRadiiNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", "Radii")
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
        radiiChartNode.AddAndObservePlotSeriesNodeID(seriesRadiiNode.GetID())
        folderTree.CreateItem(currentDir, seriesRadiiNode)


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

        unresolved_throats = np.logical_or(
            pore_network["throat.phases"][:, 0] == 2,
            pore_network["throat.phases"][:, 1] == 2,
        )
        unresolved_radii = pnm_radii[unresolved_throats]
        if unresolved_radii.size == 0:
            return lambda _: None

        biggest_unresolved_raddi = unresolved_radii.max()

        if params["throat radii"] is not None:
            subresolution_radii_bool_index = np.logical_and(
                params["throat radii"] > 1e-8, params["throat radii"] <= biggest_unresolved_raddi
            )
            if subresolution_radii_bool_index.sum() == 0:
                return lambda _: biggest_unresolved_raddi / 2
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
