import os
from pathlib import Path

import PySide2 as pyside
import ctk
import json
import numpy as np
import pyqtgraph as pg
import qt
import shiboken2
import slicer
import vtk
from pyqtgraph.Qt import QtCore

from ltrace.slicer import ui, widgets
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget
from ltrace.slicer_utils import (
    LTracePlugin,
    LTracePluginWidget,
    hide_nodes_of_type,
    getResourcePath,
)
from ltrace.slicer import widgets


try:
    from Test.PoreNetworkVisualizationTest import PoreNetworkVisualizationTest
except ImportError:
    PoreNetworkVisualizationTest = None  # tests not deployed to final version or closed source


#
# PoreNetworkVisualization
#
class PoreNetworkVisualization(LTracePlugin):
    SETTING_KEY = "PoreNetworkVisualization"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "PNM Cycles Visualization"
        self.parent.categories = ["MicroCT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = f"file:///{(getResourcePath('manual') / 'Modules/PNM/cycles.html').as_posix()}"
        self.parent.acknowledgementText = ""

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


#
# PoreNetworkVisualizationWidget
#
class PoreNetworkVisualizationWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)
        self.timer = qt.QTimer()
        self.active_table = None
        self.data_points = None
        self.sw_values = None
        self.krw_values = None
        self.kro_values = None
        self.pc_values = None

        self.visualization_sliders = []

        #
        # Input Area
        #
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.text = "Input"
        self.layout.addWidget(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)

        # input volume selector
        self.inputSelector = ui.hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLModelNode"])
        self.inputSelector.addNodeAttributeIncludeFilter("saturation_steps", None)
        self.inputSelector.setToolTip("Pick a Model node with multiple saturation tables.")
        self.inputSelector.objectName = "Input Selector"
        labelWidget = qt.QLabel("Input Model Node: ")
        inputFormLayout.addRow(labelWidget, self.inputSelector)

        #
        # Parameters Area
        #
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Parameters"
        self.layout.addWidget(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

        self.comboBoxVariable = qt.QComboBox()
        self.comboBoxVariable.addItems(["saturation", "condW", "condO"])
        parametersFormLayout.addRow("Variable", self.comboBoxVariable)

        # show zero in log krel
        self.showZeroLogCheck = qt.QCheckBox()  # .isChecked()
        parametersFormLayout.addRow("Show zero log Krel", self.showZeroLogCheck)
        self.showZeroLogCheck.setToolTip(
            "If checked, zero permeability will be shown in the log plot as two orders of magnitude lower than the lowest non-zero permeability"
        )

        # current step slicer
        self.stepSlider = ctk.ctkSliderWidget()
        self.stepSlider.singleStep = 1
        self.stepSlider.minimum = 0
        self.stepSlider.maximum = 100
        self.stepSlider.value = 0
        self.stepSlider.setToolTip("Show cycle step to show in the 3D view.")
        self.stepSlider.objectName = "Step Slider"
        parametersFormLayout.addRow("Animation step", self.stepSlider)

        # run animation checkbox
        self.runAnimationCheck = qt.QCheckBox()  # .isChecked()
        self.runAnimationCheck.objectName = "Run animation checkbox"
        parametersFormLayout.addRow("Run animation", self.runAnimationCheck)

        # loop anuimation checkbox
        self.loopAnimationCheck = qt.QCheckBox()  # .isChecked()
        parametersFormLayout.addRow("Loop animation", self.loopAnimationCheck)

        # animation speed slider
        self.speedSlider = ctk.ctkSliderWidget()
        self.speedSlider.singleStep = 1
        self.speedSlider.minimum = 1
        self.speedSlider.maximum = 100
        self.speedSlider.value = 3
        self.speedSlider.setToolTip("Set animation speed.")
        parametersFormLayout.addRow("Animation speed (fps)", self.speedSlider)

        # saturation threshold slider
        self.thresholdSlider = widgets.LTraceDoubleRangeSlider(step=0.01)
        self.thresholdSlider.setRange(0, 1)
        self.thresholdSlider.setInitState(0, 1)
        self.thresholdSlider.setStep(0.001)
        self.thresholdSlider.setToolTip("Set saturation display threshold.")
        self.thresholdSlider.objectName = "Threshold Slider"
        # parametersFormLayout.addRow("Saturation threshold", self.thresholdSlider) # PL-1111
        self.thresholdSlider.setParent(self.parent)
        self.thresholdSlider.hide()  # PL-1111
        self.visualization_sliders.append(self.thresholdSlider)

        # clip X, Y, Z sliders
        self.sliders = {}
        for axis in ("X", "Y", "Z"):
            self.sliders[f"clip{axis}Slider"] = widgets.LTraceDoubleRangeSlider(step=0.01)
            self.sliders[f"clip{axis}Slider"].setRange(0, 1)
            self.sliders[f"clip{axis}Slider"].setInitState(0, 1)
            self.sliders[f"clip{axis}Slider"].setStep(0.01)
            self.sliders[f"clip{axis}Slider"].setToolTip(f"Clip {axis} axis for visualization.")
            self.sliders[f"clip{axis}Slider"].objectName = f"{axis} Clip Slider"
            self.sliders[f"clip{axis}Slider"].setParent(self.parent)
            self.sliders[f"clip{axis}Slider"].hide()  # PL-1105
            # parametersFormLayout.addRow(f"Clip {axis} axis threshold", self.sliders[f"clip{axis}Slider"])  # PL-1105
            self.visualization_sliders.append(self.sliders[f"clip{axis}Slider"])

        #
        # Information Area
        #
        informationCollapsibleButton = ctk.ctkCollapsibleButton()
        informationCollapsibleButton.text = "Information"
        self.layout.addWidget(informationCollapsibleButton)
        informationFormLayout = qt.QFormLayout(informationCollapsibleButton)

        # Data Labels
        self.swLabel = qt.QLabel("")
        self.swLabel.objectName = "Sw label"
        informationFormLayout.addRow("Sw: ", self.swLabel)
        self.pcLabel = qt.QLabel("")
        self.pcLabel.objectName = "Pc label"
        informationFormLayout.addRow("Pc: ", self.pcLabel)
        self.krwLabel = qt.QLabel("")
        self.krwLabel.objectName = "Krw label"
        informationFormLayout.addRow("Krw: ", self.krwLabel)
        self.kroLabel = qt.QLabel("")
        self.kroLabel.objectName = "Kro label"
        informationFormLayout.addRow("Kro: ", self.kroLabel)
        pysideReportForm = shiboken2.wrapInstance(hash(informationFormLayout), pyside.QtWidgets.QFormLayout)
        self.subvolumeGraphicsLayout = GraphicsLayoutWidget()
        self.subvolumeGraphicsLayout.setMinimumHeight(400)
        self.subvolumeGraphicsLayout.setMinimumWidth(100)
        self.subvolumePlotItem = self.subvolumeGraphicsLayout.addPlot(
            row=1, col=1, rowspan=1, colspan=1, left="Krel", bottom="Sw"
        )
        self.subvolumeLogPlotItem = self.subvolumeGraphicsLayout.addPlot(
            row=2, col=1, rowspan=1, colspan=1, left="Krel", bottom="Sw"
        )
        self.subvolumePlotItem.addLegend()

        pysideReportForm.addRow(self.subvolumeGraphicsLayout)

        # colors
        KrwOilInvasion = (0, 0, 255)
        KrwWaterInvasion = (140, 0, 150)
        KroOilInvasion = (255, 0, 0)
        KroWaterInvasion = (200, 120, 0)

        self.subvolumeKrwOilInvasion = self.subvolumePlotItem.plot(
            name="Krw - oil invasion",
            pen=pg.mkPen(KrwOilInvasion, width=1, style=QtCore.Qt.DashLine),
            symbol="t3",
            symbolPen=KrwOilInvasion,
            symbolSize=8,
            symbolBrush=KrwOilInvasion,
        )
        self.subvolumeKrwWaterInvasion = self.subvolumePlotItem.plot(
            name="Krw - water invasion",
            pen=pg.mkPen(KrwWaterInvasion, width=1, style=QtCore.Qt.DashLine),
            symbol="t2",
            symbolPen=KrwWaterInvasion,
            symbolSize=8,
            symbolBrush=KrwWaterInvasion,
        )
        self.subvolumeKroOilInvasion = self.subvolumePlotItem.plot(
            name="Kro - oil invasion",
            pen=pg.mkPen(KroOilInvasion, width=1, style=QtCore.Qt.DashLine),
            symbol="t3",
            symbolPen=KroOilInvasion,
            symbolSize=8,
            symbolBrush=KroOilInvasion,
        )
        self.subvolumeKroWaterInvasion = self.subvolumePlotItem.plot(
            name="Kro - water invasion",
            pen=pg.mkPen(KroWaterInvasion, width=1, style=QtCore.Qt.DashLine),
            symbol="t2",
            symbolPen=KroWaterInvasion,
            symbolSize=8,
            symbolBrush=KroWaterInvasion,
        )
        self.subvolumePointOne = self.subvolumePlotItem.plot(
            pen=pg.mkPen("g", width=10), symbol="o", symbolPen="g", symbolSize=10, symbolBrush="g"
        )
        self.subvolumePointTwo = self.subvolumePlotItem.plot(
            pen=pg.mkPen("g", width=10), symbol="o", symbolPen="g", symbolSize=10, symbolBrush="g"
        )

        self.subvolumeLogKrwWaterInvasion = self.subvolumeLogPlotItem.plot(
            pen=pg.mkPen(KrwWaterInvasion, width=2, style=QtCore.Qt.DashLine),
            symbol="t2",
            symbolPen=KrwWaterInvasion,
            symbolSize=8,
            symbolBrush=KrwWaterInvasion,
        )
        self.subvolumeLogKrwOilInvasion = self.subvolumeLogPlotItem.plot(
            pen=pg.mkPen(KrwOilInvasion, width=2, style=QtCore.Qt.DashLine),
            symbol="t3",
            symbolPen=KrwOilInvasion,
            symbolSize=8,
            symbolBrush=KrwOilInvasion,
        )

        self.subvolumeLogKroWaterInvasion = self.subvolumeLogPlotItem.plot(
            pen=pg.mkPen(KroWaterInvasion, width=2, style=QtCore.Qt.DashLine),
            symbol="t2",
            symbolPen=KroWaterInvasion,
            symbolSize=8,
            symbolBrush=KroWaterInvasion,
        )
        self.subvolumeLogKroOilInvasion = self.subvolumeLogPlotItem.plot(
            pen=pg.mkPen(KroOilInvasion, width=2, style=QtCore.Qt.DashLine),
            symbol="t3",
            symbolPen=KroOilInvasion,
            symbolSize=8,
            symbolBrush=KroOilInvasion,
        )
        self.subvolumeLogPointOne = self.subvolumeLogPlotItem.plot(
            pen=pg.mkPen("g", width=10), symbol="o", symbolPen="g", symbolSize=10, symbolBrush="g"
        )
        self.subvolumeLogPointTwo = self.subvolumeLogPlotItem.plot(
            pen=pg.mkPen("g", width=10), symbol="o", symbolPen="g", symbolSize=10, symbolBrush="g"
        )
        self.subvolumeLogPlotItem.setLogMode(False, True)

        # connections
        self.inputSelector.currentItemChanged.connect(self.onChangeModel)
        self.comboBoxVariable.currentIndexChanged.connect(self.onChangeVariable)
        self.stepSlider.valueChanged.connect(self.onChangeStep)
        self.speedSlider.valueChanged.connect(self.onSpeedSliderChanged)
        self.timer.timeout.connect(self.nextStep)
        self.runAnimationCheck.stateChanged.connect(self.onRunAnimationCheckChanged)
        self.showZeroLogCheck.stateChanged.connect(self.onShowZeroLogCheck)
        self.thresholdSlider.slider.connect("valuesChanged(double, double)", self.onSaturationThresholdChanged)
        for axis in ("X", "Y", "Z"):
            self.sliders[f"clip{axis}Slider"].slider.connect(
                "valuesChanged(double, double)",
                lambda new_min, new_max, s=axis.lower(): self.onClipChanged(new_min, new_max, s),
            )

        # Add vertical spacer
        self.layout.addStretch(1)

    def cleanup(self):
        super().cleanup()
        if self.timer:
            self.timer.stop()
            del self.timer

        del self.active_table
        del self.data_points
        del self.sw_values
        del self.krw_values
        del self.kro_values
        del self.pc_values

        self.subvolumePlotItem.clear()
        self.subvolumeGraphicsLayout.clear()

        del self.subvolumePlotItem
        del self.subvolumeGraphicsLayout

    def onChangeModel(self):
        current_node = self.inputSelector.currentNode()

        hide_nodes_of_type("vtkMRMLModelNode")

        # Setup visualization and charts
        if current_node:
            # Disable visualization sliders when VTK pipeline is absent
            node_vtk_source = str(type(current_node.GetPolyDataConnection().GetProducer()))
            if "vtkExtractPolyDataGeometry" in node_vtk_source:
                for slider in self.visualization_sliders:
                    slider.setEnabled(True)
            elif "vtkTrivialProducer" in node_vtk_source:
                for slider in self.visualization_sliders:
                    slider.setEnabled(False)

            current_node.SetDisplayVisibility(True)
            current_node.GetDisplayNode().SetScalarRangeFlag(0)
            current_node.GetDisplayNode().SetScalarRange(0, 1)
            current_node.GetDisplayNode().SetThresholdRange(0, 1)
            layoutManager = slicer.app.layoutManager()
            threeDWidget = layoutManager.threeDWidget(0)
            threeDView = threeDWidget.threeDView()
            threeDView.resetFocalPoint()

            self.data_points = slicer.util.arrayFromModelPointData(current_node, "data_points")
            self.data_cycles = slicer.util.arrayFromModelPointData(current_node, "data_cycles")

            self.steps = len(self.data_points)
            self.stepSlider.value = 0
            self.stepSlider.maximum = self.steps - 1

            data_table_id_list = json.loads(current_node.GetAttribute("data_table_id"))
            self.active_table_nodes = []
            for table_id in data_table_id_list:
                self.active_table_nodes.append(slicer.mrmlScene.GetNodeByID(table_id))
            self.cycle_values = np.array([], dtype=int)
            self.sw_values = np.array([])
            self.pc_values = np.array([])
            self.krw_values = np.array([])
            self.kro_values = np.array([])
            for active_table in self.active_table_nodes:
                simulation_id = current_node.GetAttribute("simulation_id")
                cycle_points_vtk_array = active_table.GetTable().GetColumnByName("cycle")
                sw_points_vtk_array = active_table.GetTable().GetColumnByName("Sw")
                pc_points_vtk_array = active_table.GetTable().GetColumnByName(f"Pc_{simulation_id}")
                krw_points_vtk_array = active_table.GetTable().GetColumnByName(f"Krw_{simulation_id}")
                kro_points_vtk_array = active_table.GetTable().GetColumnByName(f"Kro_{simulation_id}")
                self.cycle_values = np.append(
                    self.cycle_values, vtk.util.numpy_support.vtk_to_numpy(cycle_points_vtk_array).astype(int)
                )
                self.sw_values = np.append(self.sw_values, vtk.util.numpy_support.vtk_to_numpy(sw_points_vtk_array))
                self.pc_values = np.append(self.pc_values, vtk.util.numpy_support.vtk_to_numpy(pc_points_vtk_array))
                self.krw_values = np.append(self.krw_values, vtk.util.numpy_support.vtk_to_numpy(krw_points_vtk_array))
                self.kro_values = np.append(self.kro_values, vtk.util.numpy_support.vtk_to_numpy(kro_points_vtk_array))

            self.sw_values_water_invasion = self.sw_values[(self.cycle_values % 2) == 0]
            self.sw_values_oil_invasion = self.sw_values[(self.cycle_values) == 1]

            self.krw_values_water_invasion = self.krw_values[(self.cycle_values % 2) == 0]
            self.krw_values_log_water_invasion = self.krw_values_water_invasion.copy()
            self.krw_values_oil_invasion = self.krw_values[(self.cycle_values) == 1]
            self.krw_values_log_oil_invasion = self.krw_values_oil_invasion.copy()

            self.kro_values_water_invasion = self.kro_values[(self.cycle_values % 2) == 0]
            self.kro_values_log_water_invasion = self.kro_values_water_invasion.copy()
            self.kro_values_oil_invasion = self.kro_values[(self.cycle_values) == 1]
            self.kro_values_log_oil_invasion = self.kro_values_oil_invasion.copy()
            bottom_axis_label_width = self.subvolumeLogPlotItem.getAxis("left").width()
            top_axis_label_width = self.subvolumePlotItem.getAxis("left").width()
            max_width = max(bottom_axis_label_width, top_axis_label_width)
            self.subvolumePlotItem.getAxis("left").setWidth(max_width)
            self.subvolumeLogPlotItem.getAxis("left").setWidth(max_width)
            self.onChangeStep(0)
            self.onChangeVariable()

    def nextStep(self):
        new_step = self.stepSlider.value + 1
        if new_step >= self.stepSlider.maximum:
            if self.loopAnimationCheck.isChecked():
                self.stepSlider.value = 0
            else:
                pass
        else:
            self.stepSlider.value = new_step

    def onSpeedSliderChanged(self, value) -> None:
        self.animationSetup()

    def onRunAnimationCheckChanged(self, status):
        self.animationSetup(status)

    def onShowZeroLogCheck(self, status):
        self.onChangeModel()

    def animationSetup(self, status):
        if self.runAnimationCheck.isChecked():
            self.timer.start(1000 / self.speedSlider.value)
        else:
            self.timer.stop()

    def onChangeStep(self, new_step):
        if self.inputSelector.currentNode():
            table_sw = self.data_points[int(new_step)]
            table_cycle = int(self.data_cycles[int(new_step)])
            self.inputSelector.currentNode().GetDisplayNode().SetActiveScalarName(
                f"{self.comboBoxVariable.currentText}_{int(new_step)+1}"
            )

            nearest_index = self.getNearestIndex(table_cycle, table_sw)

            current_sw_value = self.sw_values[nearest_index]
            current_kro_value = self.kro_values[nearest_index]
            current_krw_value = self.krw_values[nearest_index]
            current_pc_value = self.pc_values[nearest_index]

            self.swLabel.setText(current_sw_value)
            self.pcLabel.setText(current_pc_value)
            self.krwLabel.setText(current_krw_value)
            self.kroLabel.setText(current_kro_value)

            self.subvolumePlotItem.setXRange(0, 1)
            self.subvolumePlotItem.setYRange(0, 1)
            self.subvolumePlotItem.setLimits(
                xMin=-0.01,
                xMax=1.01,
                yMin=-0.01,
                yMax=1.01,
                minXRange=1.02,
                maxXRange=1.02,
                minYRange=1.02,
                maxYRange=1.02,
            )
            self.subvolumeKrwWaterInvasion.setData(self.sw_values_water_invasion, self.krw_values_water_invasion)
            self.subvolumeKrwOilInvasion.setData(self.sw_values_oil_invasion, self.krw_values_oil_invasion)
            self.subvolumeKroWaterInvasion.setData(self.sw_values_water_invasion, self.kro_values_water_invasion)
            self.subvolumeKroOilInvasion.setData(self.sw_values_oil_invasion, self.kro_values_oil_invasion)
            self.subvolumePointOne.setData([current_sw_value], [current_kro_value])
            self.subvolumePointTwo.setData([current_sw_value], [current_krw_value])

            krw_min = np.nanmin(self.krw_values)
            krw_max = np.nanmax(self.krw_values)
            self.subvolumeLogPlotItem.setXRange(0, 1)
            self.subvolumeLogPlotItem.setYRange(
                np.log10(max(krw_min, krw_max / 10 ** (20))),
                np.log10(krw_max),
            )

            if self.showZeroLogCheck.isChecked():
                self.subvolumeLogPlotItem.setYRange(
                    np.log10(max(krw_min, krw_max / 10 ** (20)) / 110),
                    np.log10(krw_max),
                )
                min_kr = krw_min / 100
                self.krw_values_log_water_invasion = np.where(
                    self.krw_values_log_water_invasion > 0, self.krw_values_log_water_invasion, min_kr
                )
                self.krw_values_log_oil_invasion = np.where(
                    self.krw_values_log_oil_invasion > 0, self.krw_values_log_oil_invasion, min_kr
                )
                self.kro_values_log_water_invasion = np.where(
                    self.kro_values_log_water_invasion > 0, self.kro_values_log_water_invasion, min_kr
                )
                self.kro_values_log_oil_invasion = np.where(
                    self.kro_values_log_oil_invasion > 0, self.kro_values_log_oil_invasion, min_kr
                )
            self.subvolumeLogKrwWaterInvasion.setData(self.sw_values_water_invasion, self.krw_values_log_water_invasion)
            self.subvolumeLogKrwOilInvasion.setData(self.sw_values_oil_invasion, self.krw_values_log_oil_invasion)
            self.subvolumeLogKroWaterInvasion.setData(self.sw_values_water_invasion, self.kro_values_log_water_invasion)
            self.subvolumeLogKroOilInvasion.setData(self.sw_values_oil_invasion, self.kro_values_log_oil_invasion)

            self.subvolumeLogPointOne.setData(
                [current_sw_value],
                [max(current_kro_value, krw_max / 10**20)],
            )
            self.subvolumeLogPointTwo.setData(
                [current_sw_value],
                [max(current_krw_value, krw_max / 10**20)],
            )

    def onChangeVariable(self):
        current_node = self.inputSelector.currentNode()

        if not current_node:
            return

        current_node.SetDisplayVisibility(True)
        if self.comboBoxVariable.currentText == "saturation":
            current_node.GetDisplayNode().SetScalarRangeFlag(0)
            current_node.GetDisplayNode().SetScalarRange(0, 1)
            current_node.GetDisplayNode().SetThresholdRange(0, 1)
            rgbColorNode = slicer.util.getNode("RedGreenBlue")
            current_node.GetDisplayNode().SetAndObserveColorNodeID(rgbColorNode.GetID())
        else:
            current_node.GetDisplayNode().SetScalarRangeFlag(1)
            viridisColorNode = slicer.util.getNode("Viridis")
            current_node.GetDisplayNode().SetAndObserveColorNodeID(viridisColorNode.GetID())

        self.onChangeStep(self.stepSlider.value)

    def onSaturationThresholdChanged(self, currentMin, currentMax):
        if self.inputSelector.currentNode():
            self.inputSelector.currentNode().GetDisplayNode().SetThresholdEnabled(True)
            self.inputSelector.currentNode().GetDisplayNode().SetThresholdRange(currentMin, currentMax)

    def onClipChanged(self, currentMin, currentMax, axis):
        # axis == x
        axis_min = 0
        axis_max = 1
        if axis == "y":
            axis_min = 2
            axis_max = 3
        elif axis == "z":
            axis_min = 4
            axis_max = 5

        if self.inputSelector.currentNode():
            node = self.inputSelector.currentNode()
            bounds = list(node.GetPolyDataConnection().GetProducer().GetOutputDataObject(0).GetBounds())
            full_bounds = list(node.GetPolyDataConnection().GetProducer().GetInput().GetBounds())
            bounds[axis_min] = full_bounds[axis_min] + (full_bounds[axis_max] - full_bounds[axis_min]) * currentMin
            bounds[axis_max] = full_bounds[axis_max] - (full_bounds[axis_max] - full_bounds[axis_min]) * (
                1 - currentMax
            )
            node.GetPolyDataConnection().GetProducer().GetImplicitFunction().SetBounds(*bounds)

            mod_event = node.GetDisplayNode().StartModify()
            node.GetDisplayNode().SetScalarVisibility(False)
            node.GetDisplayNode().SetScalarVisibility(True)
            node.GetDisplayNode().EndModify(mod_event)

    def getNearestIndex(self, cycle, sw_value):
        cycle_indexes = np.where(self.cycle_values == cycle)[0]
        array = self.sw_values[cycle_indexes]
        try:
            index = np.nanargmin(np.abs(array - sw_value))
        except ValueError:
            index = 0
        nearest_index = cycle_indexes[index]
        return nearest_index
