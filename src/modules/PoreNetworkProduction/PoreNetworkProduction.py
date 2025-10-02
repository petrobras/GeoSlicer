import os
from pathlib import Path

import PySide2 as pyside
import ctk
import numpy as np
import pandas as pd
import pyqtgraph as pg
import qt
import shiboken2
import slicer
import sympy as sym
import vtk
from numba import njit
from pyqtgraph import QtCore
from scipy import optimize, ndimage, interpolate
import re

from ltrace.slicer import ui
from ltrace.slicer.helpers import highlight_error
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, dataframeFromTable, getResourcePath
from ltrace.slicer_utils import tableNodeToDict, dataFrameToTableNode
from ltrace.utils.ProgressBarProc import ProgressBarProc

try:
    from Test.PoreNetworkProductionTest import PoreNetworkProductionTest
except ImportError:
    PoreNetworkProductionTest = None  # tests not deployed to final version or closed source


#
# PoreNetworkProduction
#
class PoreNetworkProduction(LTracePlugin):
    SETTING_KEY = "PoreNetworkProduction"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "PNM Production Prediction"
        self.parent.categories = ["Tutorials/Examples", "MicroCT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.acknowledgementText = ""
        self.setHelpUrl("Volumes/PNM/production.html")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


#
# PoreNetworkProductionWidget
#
class PoreNetworkProductionWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = PoreNetworkProductionLogic()

        #
        # Input Area: inputFormLayout
        #
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.text = "Input"
        self.layout.addWidget(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)

        # data type selector
        optionsLayout = qt.QHBoxLayout()

        self.singleRadio = qt.QRadioButton("Single Krel")
        self.multipleRadio = qt.QRadioButton("Sensitivity test")
        optionsLayout.addWidget(self.singleRadio)
        optionsLayout.addWidget(self.multipleRadio)
        self.singleRadio.setChecked(True)
        self.singleRadio.toggled.connect(self.inputTypeChanged)

        inputFormLayout.addRow(optionsLayout)

        # input table selector
        self.inputSelector = hierarchyVolumeInput(nodeTypes=["vtkMRMLTableNode"], onChange=self.onInputSelectorChanged)
        self.inputSelector.showEmptyHierarchyItems = False
        self.inputSelector.addNodeAttributeIncludeFilter("table_type", "krel_simulation_results")
        self.inputSelector.objectName = "Input Selector"
        self.inputSelector.resetStyleOnValidNode()
        inputFormLayout.addRow("Input Krel Table: ", self.inputSelector)

        self.simulationWidget = qt.QWidget()
        simulationFormLayout = qt.QFormLayout(self.simulationWidget)
        simulationFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        simulationFormLayout.setContentsMargins(0, 0, 0, 0)
        self.simulationSlider = slicer.qMRMLSliderWidget()
        self.simulationSlider.setDecimals(0)
        self.simulationSlider.valueChanged.connect(self.onSimulationSliderValueChanged)
        self.dataFrameWidget = DataFrameWidget()
        self.dataFrameWidget.setMinimumHeight(180)
        self.dataFrameWidget.rowSelected.connect(self.handleRowSelection)
        simulationFormLayout.addRow("Simulation:", self.simulationSlider)
        simulationFormLayout.addRow(self.dataFrameWidget)
        self.simulationWidget.setVisible(False)
        inputFormLayout.addRow(self.simulationWidget)

        #
        # Parameters Area: parametersFormLayout
        #
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Parameters"
        self.layout.addWidget(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

        # fluid viscosities
        self.waterViscosityEdit = ui.floatParam(0.001)
        self.oilViscosityEdit = ui.floatParam(0.01)
        parametersFormLayout.addRow("Water viscosity", self.waterViscosityEdit)
        parametersFormLayout.addRow("Oil viscosity", self.oilViscosityEdit)

        # krel smoothing
        self.smoothingDeviationEdit = ui.floatParam(2.0)
        parametersFormLayout.addRow("Krel data smoothing", self.smoothingDeviationEdit)

        #
        # Apply Button
        #
        self.simulateButton = ui.ApplyButton(tooltip="Perform simulation.")
        self.simulateButton.objectName = "Apply Button"
        self.layout.addWidget(self.simulateButton)

        #
        # Visualization Area: visualizationFormLayout
        #
        visualizationCollapsibleButton = ctk.ctkCollapsibleButton()
        visualizationCollapsibleButton.text = "Visualization"
        self.layout.addWidget(visualizationCollapsibleButton)
        visualizationFormLayout = qt.QFormLayout(visualizationCollapsibleButton)

        # Visualization selection
        self.visualizationSelector = hierarchyVolumeInput(nodeTypes=["vtkMRMLTableNode"])
        self.visualizationSelector.showEmptyHierarchyItems = False
        self.visualizationSelector.addNodeAttributeIncludeFilter("production_table", "true")
        self.visualizationSelector.objectName = "Visualization Input"
        self.visualizationSelector.setToolTip('Pick a Table node of type "production".')
        visualizationFormLayout.addRow("Input Production Table: ", self.visualizationSelector)

        # Single visualization plot
        visualizationPlotForm = shiboken2.wrapInstance(hash(visualizationFormLayout), pyside.QtWidgets.QFormLayout)
        self.visualizationGraphicsLayout = GraphicsLayoutWidget()
        self.visualizationGraphicsLayout.setMinimumHeight(800)
        self.visualizationGraphicsLayout.setMinimumWidth(100)
        self.productionPlotItem = self.visualizationGraphicsLayout.addPlot(
            row=1, col=1, rowspan=1, colspan=1, left="NpD [Oil volumes produced]", bottom="tD [Water volumes injected]"
        )
        self.productionPlotItem.addLegend()
        self.fractionPlotItem = self.visualizationGraphicsLayout.addPlot(
            row=2,
            col=1,
            rowspan=1,
            colspan=1,
            left="Krel [Relative permeability]",
            bottom="Sw [Water fraction]",
            right="fw [Fractional flow]",
        )
        self.fractionPlotItem.addLegend()
        visualizationPlotForm.addRow(self.visualizationGraphicsLayout)

        self.seriesNpD = self.productionPlotItem.plot(
            name="NpD", pen=pg.mkPen("b", width=4), symbol=None, symbolPen=None, symbolSize=None, symbolBrush=None
        )
        self.seriesKro = self.fractionPlotItem.plot(
            name="Kro", pen=None, symbol="o", symbolPen=(185, 0, 0, 180), symbolSize=6, symbolBrush=(185, 0, 0, 180)
        )
        self.seriesKrw = self.fractionPlotItem.plot(
            name="Krw", pen=None, symbol="o", symbolPen=(0, 0, 200, 150), symbolSize=6, symbolBrush=(0, 0, 200, 150)
        )
        self.seriesKrw_attenuated = self.fractionPlotItem.plot(
            name="Krw moving average",
            pen=pg.mkPen((0, 0, 230, 230), width=2, style=QtCore.Qt.SolidLine),
            symbol=None,
            symbolPen=None,
            symbolSize=None,
            symbolBrush=None,
        )
        self.seriesKro_attenuated = self.fractionPlotItem.plot(
            name="Kro moving average",
            pen=pg.mkPen((200, 0, 0, 230), width=2, style=QtCore.Qt.SolidLine),
            symbol=None,
            symbolPen=None,
            symbolSize=None,
            symbolBrush=None,
        )
        self.seriesFw = self.fractionPlotItem.plot(
            name="fw fit",
            pen=pg.mkPen((0, 160, 0, 255), width=3),
            symbol=None,
            symbolPen=None,
            symbolSize=None,
            symbolBrush=None,
        )
        self.seriesFw_points = self.fractionPlotItem.plot(
            name="fw data",
            pen=None,
            symbol="o",
            symbolPen=(0, 160, 0, 200),
            symbolSize=4,
            symbolBrush=(0, 160, 160, 200),
        )
        self.seriesTangent = self.fractionPlotItem.plot(
            name="Shock Tangent",
            pen=pg.mkPen((230, 100, 0, 255), width=3, style=QtCore.Qt.DashDotLine),
            symbol=None,
            symbolPen=None,
            symbolSize=None,
            symbolBrush=None,
        )
        self.seriesShock = self.fractionPlotItem.plot(
            name="Shock",
            pen=None,
            symbol="o",
            symbolPen=pg.mkPen((230, 100, 0, 255), width=3),
            symbolSize=12,
            symbolBrush=None,
        )

        # Sensitivity visualization plot
        self.SensitivityVisualizationGraphicsLayout = GraphicsLayoutWidget()
        self.SensitivityVisualizationGraphicsLayout.setMinimumHeight(400)
        self.SensitivityVisualizationGraphicsLayout.setMinimumWidth(100)
        self.sensitivityPlotItem = self.SensitivityVisualizationGraphicsLayout.addPlot(
            row=1, col=1, rowspan=1, colspan=1, left="NpD", bottom="tD"
        )
        self.sensitivityPlotItem.addLegend()
        visualizationPlotForm.addRow(self.SensitivityVisualizationGraphicsLayout)

        self.pessimisticNpD = self.sensitivityPlotItem.plot(
            name="Pessimistic NpD",
            pen=pg.mkPen((200, 0, 0, 255), width=4),
            symbol=None,
            symbolPen=None,
            symbolSize=None,
            symbolBrush=None,
        )

        self.realisticNpD = self.sensitivityPlotItem.plot(
            name="Realistic NpD",
            pen=pg.mkPen((230, 100, 0, 255), width=4),
            symbol=None,
            symbolPen=None,
            symbolSize=None,
            symbolBrush=None,
        )

        self.optimisticNpD = self.sensitivityPlotItem.plot(
            name="Optimistic NpD",
            pen=pg.mkPen((0, 200, 0, 255), width=4),
            symbol=None,
            symbolPen=None,
            symbolSize=None,
            symbolBrush=None,
        )

        self.SensitivityVisualizationGraphicsLayout.hide()

        #
        # Connections
        #
        self.simulateButton.connect("clicked(bool)", self.onSimulateButton)
        self.visualizationSelector.currentItemChanged.connect(self.onChangeVisualization)
        # Add vertical spacer
        self.layout.addStretch(1)

    def onInputSelectorChanged(self, nodeId):
        inputNode = self.inputSelector.currentNode()
        if inputNode and self.singleRadio.isChecked():
            numberOfSimulations = inputNode.GetNumberOfRows()
            self.simulationSlider.maximum = numberOfSimulations - 1
            self.simulationSlider.value = 0

            inputDataFrame = dataframeFromTable(inputNode)
            self.dataFrameWidget.setDataFrame(inputDataFrame)
            self.dataFrameWidget.setRowNumber(0)

            self.simulationWidget.setVisible(True)
        else:
            self.simulationWidget.setVisible(False)

    def onSimulationSliderValueChanged(self, simulation):
        self.dataFrameWidget.setRowNumber(simulation)

    def inputTypeChanged(self):
        self.onInputSelectorChanged(None)

    def handleRowSelection(self, row):
        self.simulationSlider.value = row

    def onSimulateButton(self):
        if self.inputSelector.currentNode() is None:
            highlight_error(self.inputSelector)
            return

        self.simulateButton.enabled = False
        water_viscosity = float(self.waterViscosityEdit.text)
        oil_viscosity = float(self.oilViscosityEdit.text)
        krel_smoothing = float(self.smoothingDeviationEdit.text)
        sensitivity_test = self.multipleRadio.isChecked()
        current_node = self.inputSelector.currentNode()
        simulation = int(self.simulationSlider.value)

        production_table = None
        if current_node:
            with ProgressBarProc() as pb:
                pb.setMessage("Setting up")
                pb.setProgress(0)
                pb.setMessage("Generating visualization")
                pb.setProgress(10)
                production_table = self.logic.run(
                    current_node, water_viscosity, oil_viscosity, krel_smoothing, sensitivity_test, simulation
                )
                pb.setMessage("Done")
                pb.setProgress(100)
        self.visualizationSelector.setCurrentNode(production_table)
        self.simulateButton.enabled = True

    def onChangeVisualization(self, i):
        # current_item = self.visualizationSelector.currentItem()
        production_node = self.visualizationSelector.currentNode()
        if not production_node:
            return

        if production_node.GetAttribute("table_type") == "production":
            self.SensitivityVisualizationGraphicsLayout.hide()
            self.visualizationGraphicsLayout.show()

            fraction_node, details_node = self.logic.get_other_nodes(production_node)

            fraction_node_table = fraction_node.GetTable()
            cols = fraction_node_table.GetNumberOfColumns()
            name = fraction_node_table.GetColumnName(cols - 1)
            sim = "_" + re.search(r"\d+", name).group()

            sw_points_vtk_array = fraction_node.GetTable().GetColumnByName("Sw")
            self.sw_values = vtk.util.numpy_support.vtk_to_numpy(sw_points_vtk_array)
            krw_points_vtk_array = fraction_node.GetTable().GetColumnByName("Krw" + sim)
            self.krw_values = vtk.util.numpy_support.vtk_to_numpy(krw_points_vtk_array)
            kro_points_vtk_array = fraction_node.GetTable().GetColumnByName("Kro" + sim)
            self.kro_values = vtk.util.numpy_support.vtk_to_numpy(kro_points_vtk_array)
            krw_att_points_vtk_array = fraction_node.GetTable().GetColumnByName("Krw_blur" + sim)
            self.krw_att_values = vtk.util.numpy_support.vtk_to_numpy(krw_att_points_vtk_array)
            kro_att_points_vtk_array = fraction_node.GetTable().GetColumnByName("Kro_blur" + sim)
            self.kro_att_values = vtk.util.numpy_support.vtk_to_numpy(kro_att_points_vtk_array)
            fw_points_vtk_array = fraction_node.GetTable().GetColumnByName("fw_fit" + sim)
            self.fw_values = vtk.util.numpy_support.vtk_to_numpy(fw_points_vtk_array)
            fw_points_vtk_array = fraction_node.GetTable().GetColumnByName("fw" + sim)
            self.fw_points_values = vtk.util.numpy_support.vtk_to_numpy(fw_points_vtk_array)

            td_points_vtk_array = production_node.GetTable().GetColumnByName("tD")
            self.td_values = vtk.util.numpy_support.vtk_to_numpy(td_points_vtk_array)
            npd_points_vtk_array = production_node.GetTable().GetColumnByName("NpD")
            self.npd_values = vtk.util.numpy_support.vtk_to_numpy(npd_points_vtk_array)

            self.fractionPlotItem.setXRange(0, 1)
            self.fractionPlotItem.setYRange(0, 1.1)
            self.productionPlotItem.setXRange(0, 2)
            self.productionPlotItem.setYRange(0, 1)
            self.seriesNpD.setData(self.td_values, self.npd_values)
            self.seriesKro.setData(self.sw_values, self.kro_values)
            self.seriesKrw.setData(self.sw_values, self.krw_values)
            self.seriesKro_attenuated.setData(self.sw_values, self.kro_att_values)
            self.seriesKrw_attenuated.setData(self.sw_values, self.krw_att_values)
            self.seriesFw.setData(self.sw_values, self.fw_values)
            self.seriesFw_points.setData(self.sw_values, self.fw_points_values)
            self.seriesTangent.setData(
                [
                    details_node.GetTable().GetColumnByName("shock_line_sw_0").GetValue(0),
                    details_node.GetTable().GetColumnByName("breakthrough_sw").GetValue(0),
                    details_node.GetTable().GetColumnByName("shock_line_sw_1").GetValue(0),
                ],
                [
                    details_node.GetTable().GetColumnByName("shock_line_fw_0").GetValue(0),
                    details_node.GetTable().GetColumnByName("breakthrough_fw").GetValue(0),
                    details_node.GetTable().GetColumnByName("shock_line_fw_1").GetValue(0),
                ],
            )
            self.seriesShock.setData(
                [
                    details_node.GetTable().GetColumnByName("breakthrough_sw").GetValue(0),
                ],
                [
                    details_node.GetTable().GetColumnByName("breakthrough_fw").GetValue(0),
                ],
            )

        elif production_node.GetAttribute("table_type") == "production_sensitivity":
            self.SensitivityVisualizationGraphicsLayout.show()
            self.visualizationGraphicsLayout.hide()
            self.sensitivityPlotItem.setXRange(0, 2)
            self.sensitivityPlotItem.setYRange(0, 1)

            series_list = []
            NpD_arrays_list = []
            n_curves = int(production_node.GetAttribute("production_curves"))

            td_points_vtk_array = production_node.GetTable().GetColumnByName("tD")
            self.td_values = vtk.util.numpy_support.vtk_to_numpy(td_points_vtk_array)

            for i in range(n_curves):
                series_list.append(
                    self.sensitivityPlotItem.plot(
                        pen=pg.mkPen((127, 127, 127, 127), width=3),
                        symbol=None,
                        symbolPen=None,
                        symbolSize=None,
                        symbolBrush=None,
                    )
                )
                npd_points_vtk_array = production_node.GetTable().GetColumnByName(f"NpD_{i}")
                NpD_arrays_list.append(vtk.util.numpy_support.vtk_to_numpy(npd_points_vtk_array))
                series_list[-1].setData(self.td_values, NpD_arrays_list[-1])

            npd_points_vtk_array = production_node.GetTable().GetColumnByName("pessimistic_NpD")
            pessimistic_NpD_numpy = vtk.util.numpy_support.vtk_to_numpy(npd_points_vtk_array)
            self.pessimisticNpD.setData(self.td_values, pessimistic_NpD_numpy)
            self.pessimisticNpD.setZValue(1)

            npd_points_vtk_array = production_node.GetTable().GetColumnByName("realistic_NpD")
            realistic_NpD_numpy = vtk.util.numpy_support.vtk_to_numpy(npd_points_vtk_array)
            self.realisticNpD.setData(self.td_values, realistic_NpD_numpy)
            self.realisticNpD.setZValue(1)

            npd_points_vtk_array = production_node.GetTable().GetColumnByName("optimistic_NpD")
            optimistic_NpD_numpy = vtk.util.numpy_support.vtk_to_numpy(npd_points_vtk_array)
            self.optimisticNpD.setData(self.td_values, optimistic_NpD_numpy)
            self.optimisticNpD.setZValue(1)


#
# PoreNetworkProductionLogic
#
class PoreNetworkProductionLogic(LTracePluginLogic):
    def get_other_nodes(self, production_node):
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        table_id = folderTree.GetItemByDataNode(production_node)
        table_folder_id = folderTree.GetItemParent(table_id)

        tables_list = vtk.vtkIdList()
        folderTree.GetItemChildren(table_folder_id, tables_list)

        for table_id in (tables_list.GetId(i) for i in range(tables_list.GetNumberOfIds())):
            current_node = folderTree.GetItemDataNode(table_id)
            if current_node.GetAttribute("table_type") == "fractional_flow":
                fraction_node = current_node
            elif current_node.GetAttribute("table_type") == "details":
                details_node = current_node

        return fraction_node, details_node

    def run(
        self,
        krel_results_table: slicer.vtkMRMLTableNode,
        water_viscosity: float,
        oil_viscosity: float,
        krel_smoothing: float,
        sensitivity_test: bool,
        simulation: int,
    ) -> slicer.vtkMRMLTableNode:
        """
        Creates an oil production prediction table based on Bukley-Leverett model from Krel results.

        :param krel_results_table: The table node containing the relative permeability data.
        :param water_viscosity: Water viscosity value.
        :param oil_viscosity: Oil viscosity value.
        :param krel_smoothing: Sets standard deviation for the Gaussian moving average over
            fractional flow values.
        :param sensitivity_test: Defines if the prediction should be run over an group of sensitivity
            test Krel results.

        :return: The production table.
        """
        numberOfSimulations = krel_results_table.GetNumberOfRows()
        cycle2TableNode = slicer.util.getNode(krel_results_table.GetAttribute("cycle_table_2_id"))
        krel_dict = tableNodeToDict(cycle2TableNode)

        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        sample_dir = folderTree.GetItemParent(folderTree.GetItemByDataNode(krel_results_table))
        table_name = cycle2TableNode.GetName()

        output_dir = folderTree.CreateFolderItem(sample_dir, "Production preview")

        if not sensitivity_test:
            for i in range(numberOfSimulations):
                if i != simulation:
                    for prefix in ["cycle_", "Pc_", "Krw_", "Kro_"]:
                        del krel_dict[f"{prefix}{i}"]

            try:
                krel_dict, production, details = self.calculate_production_preview(
                    krel_dict, water_viscosity, oil_viscosity, krel_smoothing, sim=simulation
                )
            except Exception as e:
                print(f" Error while predicting production of {cycle2TableNode.GetName()} :")
                print("\t", e)
                return

            # Results tables
            flow_table_name = slicer.mrmlScene.GenerateUniqueName("fractional_flow_table")
            flow_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", flow_table_name)
            flow_table.SetAttribute("table_type", "fractional_flow")
            df_results = pd.DataFrame(krel_dict)
            flow_node = dataFrameToTableNode(df_results, flow_table)
            folderTree.CreateItem(output_dir, flow_node)

            production_table_name = slicer.mrmlScene.GenerateUniqueName(f"{table_name}_visualization")
            production_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", production_table_name)
            production_table.SetAttribute("table_type", "production")
            production_table.SetAttribute("production_table", "true")
            production_df_results = pd.DataFrame(production)
            production_node = dataFrameToTableNode(production_df_results, production_table)
            folderTree.CreateItem(output_dir, production_node)

            details_table_name = slicer.mrmlScene.GenerateUniqueName("details_table")
            details_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", details_table_name)

            details_table.SetAttribute("table_type", "details")
            details_df = pd.DataFrame(details, index=[0])
            details_node = dataFrameToTableNode(details_df, details_table)
            folderTree.CreateItem(output_dir, details_node)
        else:
            min_tD = np.inf
            NpD_at_1_tD = []
            interpolated_functions = []
            productions_list = {}

            for i in range(numberOfSimulations):
                try:
                    _, production, details = self.calculate_production_preview(
                        krel_dict, water_viscosity, oil_viscosity, krel_smoothing, sim=i
                    )
                except Exception as e:
                    print(f" Error while predicting production of {cycle2TableNode.GetName()} :")
                    print("\t", e)
                else:
                    NpD_at_1_tD.append(details["NpD_at_1_tD"])
                    x_points, y_points = remove_overlapping_points(production["tD"], production["NpD"])
                    interpolated_functions.append(
                        interpolate.interp1d(
                            x_points,
                            y_points,
                            kind="linear",
                            bounds_error=False,
                            fill_value=(y_points[0], y_points[-1]),
                        )
                    )
                    min_tD = min(min_tD, production["tD"].max())

            min_tD = max(min_tD, 2)
            sorted_indexes = np.argsort(NpD_at_1_tD)  # ascending order
            n = len(sorted_indexes)
            pessimistic_id = sorted_indexes[n // 10]
            realistic_id = sorted_indexes[n // 2]
            optimistic_id = sorted_indexes[n - n // 10 - 1]

            productions_list["tD"] = np.linspace(0, min_tD, 200)
            for i, func in enumerate(interpolated_functions):
                productions_list[f"NpD_{i}"] = func(productions_list["tD"])
            productions_list["pessimistic_NpD"] = productions_list[f"NpD_{pessimistic_id}"].copy()
            productions_list["realistic_NpD"] = productions_list[f"NpD_{realistic_id}"].copy()
            productions_list["optimistic_NpD"] = productions_list[f"NpD_{optimistic_id}"].copy()

            production_table_name = slicer.mrmlScene.GenerateUniqueName("production_table")
            production_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", production_table_name)
            production_table.SetAttribute("table_type", "production_sensitivity")
            production_table.SetAttribute("production_table", "true")
            production_table.SetAttribute("production_curves", str(n))
            production_df_results = pd.DataFrame(productions_list)
            production_node = dataFrameToTableNode(production_df_results, production_table)
            folderTree.CreateItem(output_dir, production_node)

        return production_table

    def gaussian_filter1d_w_nans(self, U, smoothing):
        """
        Using this function instead of ndimage.gaussian_filter1d, to avoid nan values in the gaussian mean.

        :param U: np.array with values.
        :param smoothing: Smoothing range.

        :return: np.array with smoothed values inside range.
        """

        V = U.copy()
        V[np.isnan(U)] = 0
        VV = ndimage.gaussian_filter1d(V, smoothing)
        VV[np.isnan(U)] = np.nan

        W = 0 * U.copy() + 1
        W[np.isnan(U)] = 0
        WW = ndimage.gaussian_filter1d(W, smoothing)
        WW[np.isnan(U)] = np.nan

        return VV / WW

    def calculate_production_preview(self, krel_dict, water_viscosity, oil_viscosity, krel_smoothing, sim):
        sim = "_" + str(sim)
        krel_dict["Kro_blur" + sim] = self.gaussian_filter1d_w_nans(krel_dict["Kro" + sim], krel_smoothing)
        krel_dict["Krw_blur" + sim] = self.gaussian_filter1d_w_nans(krel_dict["Krw" + sim], krel_smoothing)
        krel_dict["fw" + sim] = 1 / (
            1 + (water_viscosity * krel_dict["Kro_blur" + sim]) / (oil_viscosity * krel_dict["Krw_blur" + sim])
        )

        krel_dict["fw" + sim] = replace_nans(krel_dict["fw" + sim])

        coef, _ = optimize.curve_fit(_general_logistic, krel_dict["Sw"], krel_dict["fw" + sim], maxfev=1000000)
        fitted_logistic = lambda x: _general_logistic(x, *coef)
        fitted_logistic_diff = lambda x: _general_logistic_diff(x, *coef)
        swi = krel_dict["Sw"][0]
        sw_max = krel_dict["Sw"][-1]
        fw_delta = lambda x: fitted_logistic(x) / (x - swi)

        symbols = {}
        for key in "xABCDEFG":
            symbols[key] = sym.symbols(key)
        eqs = []
        for i, key in enumerate("ABCDEFG"):
            eqs.append(sym.Eq(symbols[key], coef[i]))
        vals = {}
        for i, key in enumerate("ABCDEFG"):
            vals[key] = coef[i]

        second_derivative = (
            symbols["B"]
            * symbols["C"] ** 2
            * symbols["D"]
            * (symbols["E"] - symbols["F"])
            * (
                -symbols["B"]
                * symbols["D"]
                * sym.exp(symbols["C"] * (symbols["G"] + symbols["x"]))
                / (symbols["A"] + symbols["B"] * sym.exp(symbols["C"] * (symbols["G"] + symbols["x"])))
                - symbols["B"]
                * sym.exp(symbols["C"] * (symbols["G"] + symbols["x"]))
                / (symbols["A"] + symbols["B"] * sym.exp(symbols["C"] * (symbols["G"] + symbols["x"])))
                + 1
            )
            * sym.exp(symbols["C"] * (symbols["G"] + symbols["x"]))
            / (
                (symbols["A"] + symbols["B"] * sym.exp(symbols["C"] * (symbols["G"] + symbols["x"])))
                * (symbols["A"] + symbols["B"] * sym.exp(symbols["C"] * (symbols["G"] + symbols["x"]))) ** symbols["D"]
            )
        )

        eqs.append(sym.Eq(second_derivative, 0))
        try:
            middle_logistic_curve = float(sym.solve(sym.Eq(second_derivative, 0), symbols["x"])[0].subs(vals))
        except TypeError as e:
            print(f"Error found while searching for middle of logistic curve: ", e)
            middle_logistic_curve = krel_dict["Sw"].min()

        no_shock = False
        try:
            sws_solution = optimize.brentq(
                lambda x: fitted_logistic_diff(x) - fw_delta(x), a=middle_logistic_curve * 0.99, b=sw_max
            )
        except ValueError as e:
            print(f"Found error while searching for shock: ", e)
            gradient_at_swi = fitted_logistic_diff(swi)
            if gradient_at_swi >= 0.5:
                sws_solution = swi
            else:
                sws_solution = sw_max
                no_shock = True

        sws = sws_solution
        krel_dict["fw_fit" + sim] = fitted_logistic(krel_dict["Sw"])
        krel_dict["fw_fit_diff" + sim] = fitted_logistic_diff(krel_dict["Sw"])
        krel_dict["fw_delta" + sim] = np.empty(krel_dict["fw_fit" + sim].shape, dtype=np.float32)
        krel_dict["fw_delta" + sim][0] = 0
        krel_dict["fw_delta" + sim][1:] = (krel_dict["fw_fit" + sim][1:] - krel_dict["fw_fit" + sim][0]) / (
            krel_dict["Sw"][1:] - krel_dict["Sw"][0]
        )
        shock_line_sw = [swi, sw_max]
        shock_line_fw = [
            fitted_logistic(sws) - (sws - swi) * fitted_logistic_diff(sws),
            fitted_logistic(sws) + (sw_max - sws) * fitted_logistic_diff(sws),
        ]

        if no_shock or fitted_logistic_diff(sws) == 0:
            t_breakthrough = sw_max - swi
            production = {
                "tD": np.array((0, t_breakthrough, 2)),
                "Sw": np.array((0, 0, 0)),
                "NpD": np.array((0, t_breakthrough, t_breakthrough)),
                "Sw_mean": np.array((0, 0, 0)),
                "vD": np.array((0, 0, 0)),
            }
            NtD_function = lambda x: sw_max - swi

        else:
            t_breakthrough = (fitted_logistic_diff(sws)) ** (-1)
            before_breakthrough = {}
            before_breakthrough["tD"] = np.linspace(0, t_breakthrough, 50)
            before_breakthrough["Sw"] = np.ones(50) * swi
            before_breakthrough["NpD"] = before_breakthrough["tD"].copy()
            before_breakthrough["Sw_mean"] = np.zeros(50)  # actually just uncomputated since it's not used
            before_breakthrough["vD"] = np.zeros(50)  # actually just uncomputated since it's not used

            after_breakthrough = {}
            after_breakthrough["Sw"] = np.linspace(sws, sw_max, 50)  # sw_max = (1 - Sor)
            after_breakthrough["vD"] = fitted_logistic_diff(after_breakthrough["Sw"])
            after_breakthrough["tD"] = 1 / after_breakthrough["vD"]
            after_breakthrough["Sw_mean"] = after_breakthrough["Sw"] + after_breakthrough["tD"] * (
                1 - fitted_logistic(after_breakthrough["Sw"])
            )
            after_breakthrough["NpD"] = after_breakthrough["Sw_mean"] - swi
            valid_indexes = np.logical_and(
                fitted_logistic(after_breakthrough["Sw"]) <= 1, after_breakthrough["Sw_mean"] <= 1
            )
            production = {}
            for key in before_breakthrough.keys():
                production[key] = np.concatenate((before_breakthrough[key], after_breakthrough[key][valid_indexes]))

            try:
                NtD_function = interpolate.interp1d(
                    after_breakthrough["tD"][valid_indexes],
                    after_breakthrough["NpD"][valid_indexes],
                    kind="linear",
                    fill_value="extrapolate",
                )
            except ValueError as e:
                print(f"found error while interpolating NtD: ", e)
                NtD_function = lambda x: sw_max - swi

        details = {
            "coef_A": coef[0],
            "coef_B": coef[1],
            "coef_C": coef[2],
            "coef_D": coef[3],
            "coef_E": coef[4],
            "coef_F": coef[5],
            "coef_G": coef[6],
            "breakthrough_t": t_breakthrough,
            "breakthrough_sw": sws,
            "breakthrough_fw": fitted_logistic(sws),
            "NpD_at_1_tD": float(NtD_function(1)),
            "shock_line_sw_0": shock_line_sw[0],
            "shock_line_sw_1": shock_line_sw[1],
            "shock_line_fw_0": shock_line_fw[0],
            "shock_line_fw_1": shock_line_fw[1],
        }

        return (krel_dict, production, details)


def replace_nans(array):
    if np.isnan(array).all():
        raise ValueError("Input array consists entirely of NaN values.")

    non_nan_indices = np.where(~np.isnan(array))[0]

    if len(non_nan_indices) <= 1:
        raise ValueError("Input array must have at least two non-NaN values.")

    left_index = non_nan_indices[0]
    right_index = non_nan_indices[-1]

    array[:left_index] = np.nan_to_num(array[:left_index], nan=0)
    array[right_index + 1 :] = np.nan_to_num(array[right_index + 1 :], nan=1)

    return array


@njit
def _general_logistic(x, A, B, C, D, E, F, G):
    return E + (F - E) / (A + B * np.exp(C * (x + G))) ** D


@njit
def _general_logistic_diff(x, A, B, C, D, E, F, G):
    return (
        -B
        * C
        * D
        * (-E + F)
        * np.exp(C * (G + x))
        / ((A + B * np.exp(C * (G + x))) * (A + B * np.exp(C * (G + x))) ** D)
    )


@njit
def _general_logistic_diff_2(x, A, B, C, D, E, F, G):
    return (
        B
        * C**2
        * D
        * (E - F)
        * (
            -B * D * np.exp(C * (G + x)) / (A + B * np.exp(C * (G + x)))
            - B * np.exp(C * (G + x)) / (A + B * np.exp(C * (G + x)))
            + 1
        )
        * np.exp(C * (G + x))
        / ((A + B * np.exp(C * (G + x))) * (A + B * np.exp(C * (G + x))) ** D)
    )


def remove_overlapping_points(x_points, y_points):
    points = set()
    unique_x = []
    unique_y = []
    for x, y in zip(x_points, y_points):
        if x in points:
            continue
        points.add(x)
        unique_x.append(x)
        unique_y.append(y)
    return unique_x, unique_y


class DataFrameWidget(qt.QWidget):
    rowSelected = qt.Signal(int)

    def __init__(self):
        super().__init__()
        self.dataframe = None
        self.row_number = None
        self.initUI()

    def initUI(self):
        self.setWindowTitle("DataFrame Widget")

        # Create a QStandardItemModel
        self.model = qt.QStandardItemModel(self)

        # Create a QTableView and set the model
        self.table_view = qt.QTableView(self)
        self.table_view.setModel(self.model)
        self.table_view.selectionModel().currentRowChanged.connect(self.handleRowSelection)

        # Set table properties
        self.table_view.setEditTriggers(qt.QTableView.NoEditTriggers)
        self.table_view.setSelectionMode(qt.QTableView.SingleSelection)
        self.table_view.setSelectionBehavior(qt.QTableView.SelectRows)
        self.table_view.horizontalHeader().setStretchLastSection(True)

        # Create a vertical layout and add the table view
        layout = qt.QVBoxLayout(self)
        layout.addWidget(self.table_view)
        self.setLayout(layout)

    def setDataFrame(self, dataframe):
        self.dataframe = dataframe
        self.row_number = None
        self.updateModel()
        self.setRowNumber(0)

    def updateModel(self):
        # Clear existing model data
        self.model.clear()

        # Set the number of rows and columns
        if self.dataframe is not None:
            self.model.setColumnCount(self.dataframe.shape[1])
            self.model.setRowCount(self.dataframe.shape[0])
            self.model.setHorizontalHeaderLabels(self.dataframe.columns)
            self.table_view.resizeColumnsToContents()

            # Set the data from the DataFrame
            for row in range(self.dataframe.shape[0]):
                for col in range(self.dataframe.shape[1]):
                    item = str(self.dataframe.iloc[row, col])
                    self.model.setItem(row, col, qt.QStandardItem(item))

    def setRowNumber(self, row_number):
        self.table_view.selectRow(row_number)

    def handleRowSelection(self, current: qt.QModelIndex, previous: qt.QModelIndex):
        row = current.row()
        self.rowSelected.emit(row)
