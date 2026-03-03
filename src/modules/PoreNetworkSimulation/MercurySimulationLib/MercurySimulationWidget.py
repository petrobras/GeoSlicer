import PySide2 as pyside
import ctk
import numpy as np
import pyqtgraph as pg
import qt
import shiboken2
import slicer
from pyqtgraph.Qt import QtCore
from vtk.util.numpy_support import vtk_to_numpy

from PoreNetworkSimulationLib.constants import *
from ltrace.pore_networks.subres_models import get_pore_network_volume_data
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget
from .SubscaleModelWidget import SubscaleModelWidget


class MercurySimulationWidget(qt.QFrame):
    DEFAULT_VALUES = {
        "simulation type": MICP,
        "keep_temporary": False,
        "subres_model_name": "Fixed Radius",
        "subres_params": {"radius": 1.0},
        "subres_shape_factor": 0.04,
        "subres_porositymodifier": 1.0,
        "pressures": 100,
        "save_radii_distrib_plots": True,
        "experimental_radius": None,
    }

    def __init__(self):
        super().__init__()
        layout = qt.QFormLayout(self)

        self.subscaleModelWidget = SubscaleModelWidget()
        layout.addWidget(self.subscaleModelWidget)

        #
        # MICP Graph visualization
        #
        self.micpCollapsibleButton = ctk.ctkCollapsibleButton()
        self.micpCollapsibleButton.text = "MICP Visualization"
        self.micpCollapsibleButton.setChecked(False)
        layout.addRow(self.micpCollapsibleButton)
        micpFormLayout = qt.QFormLayout(self.micpCollapsibleButton)

        # input volume selector
        self.micpSelector = hierarchyVolumeInput(nodeTypes=["vtkMRMLTableNode"])
        self.micpSelector.showEmptyHierarchyItems = False
        self.micpSelector.addNodeAttributeIncludeFilter("table_type", "micp")
        self.micpSelector.currentItemChanged.connect(self.onChangeMicp)
        labelWidget = qt.QLabel("Simulation Results Node: ")

        micpSelectorLayout = qt.QHBoxLayout()
        micpSelectorLayout.addWidget(self.micpSelector)
        self.toggleMicpButton = qt.QPushButton("Hide")
        self.toggleMicpButton.setCheckable(True)
        self.toggleMicpButton.setChecked(True)
        self.toggleMicpButton.setToolTip("Toggle simulation plots visibility")
        self.toggleMicpButton.toggled.connect(self.onToggleMicpPlots)
        self.toggleMicpButton.setFixedWidth(50)
        micpSelectorLayout.addWidget(self.toggleMicpButton)
        micpFormLayout.addRow(labelWidget, micpSelectorLayout)

        self.sirrSelector = hierarchyVolumeInput(nodeTypes=["vtkMRMLTableNode"])
        self.sirrSelector.showEmptyHierarchyItems = False
        self.sirrSelector.addNodeAttributeIncludeFilter("table_type", "micp")
        self.sirrSelector.setToolTip("Select a SIRR imported MICP table node.")
        self.sirrSelector.objectName = "SIRR Input Selector"
        self.sirrSelector.currentItemChanged.connect(self.onChangeSirrMicp)
        sirrLabelWidget = qt.QLabel("Reference Table Node: ")

        sirrSelectorLayout = qt.QHBoxLayout()
        sirrSelectorLayout.addWidget(self.sirrSelector)
        self.toggleSirrButton = qt.QPushButton("Hide")
        self.toggleSirrButton.setCheckable(True)
        self.toggleSirrButton.setChecked(True)
        self.toggleSirrButton.setToolTip("Toggle SIRR plots visibility")
        self.toggleSirrButton.toggled.connect(self.onToggleSirrPlots)
        self.toggleSirrButton.setFixedWidth(50)
        sirrSelectorLayout.addWidget(self.toggleSirrButton)
        micpFormLayout.addRow(sirrLabelWidget, sirrSelectorLayout)

        # plots
        pysideReportForm = shiboken2.wrapInstance(hash(micpFormLayout), pyside.QtWidgets.QFormLayout)
        self.subvolumeGraphicsLayout = GraphicsLayoutWidget()
        self.subvolumeGraphicsLayout.setMinimumHeight(600)
        self.subvolumeGraphicsLayout.setMinimumWidth(100)

        # SIRR Plots (Background)
        self.micpPlotItem = self.subvolumeGraphicsLayout.addPlot(
            row=1, col=1, rowspan=1, colspan=1, left="Pc", bottom="Shg"
        )
        self.micpSirrSeries = self.micpPlotItem.plot(
            name="micp_sirr",
            pen=pg.mkPen((255, 100, 100), width=2, style=QtCore.Qt.DotLine),
            symbol="t",
            symbolPen=(255, 100, 100),
            symbolSize=8,
            symbolBrush=(255, 100, 100),
        )
        self.micpSirrSeries.getViewBox().invertX(True)

        self.pcPlotItem = self.subvolumeGraphicsLayout.addPlot(
            row=2, col=1, rowspan=1, colspan=1, left="dsn", bottom="Pc"
        )
        self.pcSirrSeries = self.pcPlotItem.plot(
            name="pc_sirr",
            pen=pg.mkPen((100, 200, 100), width=2, style=QtCore.Qt.DotLine),
            symbol="t",
            symbolPen=(100, 200, 100),
            symbolSize=8,
            symbolBrush=(100, 200, 100),
        )

        self.radiiPlotItem = self.subvolumeGraphicsLayout.addPlot(
            row=3, col=1, rowspan=1, colspan=1, left="dsn", bottom="Radius"
        )
        self.radiiSirrSeries = self.radiiPlotItem.plot(
            name="radii_sirr",
            pen=pg.mkPen((150, 150, 255), width=2, style=QtCore.Qt.DotLine),
            symbol="t",
            symbolPen=(150, 150, 255),
            symbolSize=8,
            symbolBrush=(150, 150, 255),
        )

        # Simulation Plots (Foreground)
        self.micpSeries = self.micpPlotItem.plot(
            name="micp",
            pen=pg.mkPen("r", width=2, style=QtCore.Qt.DashLine),
            symbol="o",
            symbolPen="r",
            symbolSize=8,
            symbolBrush="r",
        )
        self.pcSeries = self.pcPlotItem.plot(
            name="pc",
            pen=pg.mkPen("g", width=2, style=QtCore.Qt.DashLine),
            symbol="o",
            symbolPen="g",
            symbolSize=8,
            symbolBrush="g",
        )
        self.radiiSeries = self.radiiPlotItem.plot(
            name="radii",
            pen=pg.mkPen((50, 50, 255), width=2, style=QtCore.Qt.DashLine),
            symbol="o",
            symbolPen=(50, 50, 255),
            symbolSize=8,
            symbolBrush=(50, 50, 255),
        )

        self.micpPlotItem.addLegend()
        self.pcPlotItem.addLegend()
        self.radiiPlotItem.addLegend()
        pysideReportForm.addRow(self.subvolumeGraphicsLayout)

    def setVolumeNode(self, node):
        self.subscaleModelWidget.setVolumeNode(node)

    def getSirrSelector(self):
        return self.sirrSelector

    def onToggleMicpPlots(self, visible):
        self.toggleMicpButton.setText("Hide" if visible else "Show")
        if visible:
            self.micpSeries.show()
            self.pcSeries.show()
            self.radiiSeries.show()
        else:
            self.micpSeries.hide()
            self.pcSeries.hide()
            self.radiiSeries.hide()

    def onToggleSirrPlots(self, visible):
        self.toggleSirrButton.setText("Hide" if visible else "Show")
        if visible:
            self.micpSirrSeries.show()
            self.pcSirrSeries.show()
            self.radiiSirrSeries.show()
        else:
            self.micpSirrSeries.hide()
            self.pcSirrSeries.hide()
            self.radiiSirrSeries.hide()

    def onChangeSirrMicp(self):
        sirr_table_node = self.sirrSelector.currentNode()
        if not sirr_table_node:
            self.micpSirrSeries.clear()
            self.pcSirrSeries.clear()
            self.radiiSirrSeries.clear()
            return
        pc_table_id = sirr_table_node.GetAttribute("pc_table_id")
        radius_table_id = sirr_table_node.GetAttribute("radius_table_id")
        pc_table = slicer.mrmlScene.GetNodeByID(pc_table_id)
        radius_table = slicer.mrmlScene.GetNodeByID(radius_table_id)

        pc_points_vtk_array = sirr_table_node.GetTable().GetColumnByName("pc")
        self.second_pc_values = vtk_to_numpy(pc_points_vtk_array)
        snwp_points_vtk_array = sirr_table_node.GetTable().GetColumnByName("snwp")
        self.second_snwp_values = vtk_to_numpy(snwp_points_vtk_array)

        pc_y_vtk_array = pc_table.GetTable().GetColumnByName("dsn")
        self.second_pc_y_values = vtk_to_numpy(pc_y_vtk_array)
        pc_x_vtk_array = pc_table.GetTable().GetColumnByName("pc")
        self.second_pc_x_values = vtk_to_numpy(pc_x_vtk_array)

        radius_y_vtk_array = radius_table.GetTable().GetColumnByName("dsn")
        self.second_radius_y_values = vtk_to_numpy(radius_y_vtk_array)
        radius_x_vtk_array = radius_table.GetTable().GetColumnByName("radius")
        self.second_radius_x_values = vtk_to_numpy(radius_x_vtk_array)

        self.micpSirrSeries.setData(self.second_snwp_values, self.second_pc_values)
        self.pcSirrSeries.setData(self.second_pc_x_values[:-1], self.second_pc_y_values[:-1])
        self.radiiSirrSeries.setData(self.second_radius_x_values[:-1], self.second_radius_y_values[:-1])

    def onChangeMicp(self):
        micp_table_node = self.micpSelector.currentNode()
        if not micp_table_node:
            self.micpSeries.clear()
            self.pcSeries.clear()
            self.radiiSeries.clear()
            return
        pc_table_id = micp_table_node.GetAttribute("pc_table_id")
        radius_table_id = micp_table_node.GetAttribute("radius_table_id")
        pc_table = slicer.mrmlScene.GetNodeByID(pc_table_id)
        radius_table = slicer.mrmlScene.GetNodeByID(radius_table_id)

        pc_points_vtk_array = micp_table_node.GetTable().GetColumnByName("pc")
        self.pc_values = vtk_to_numpy(pc_points_vtk_array)
        snwp_points_vtk_array = micp_table_node.GetTable().GetColumnByName("snwp")
        self.snwp_values = vtk_to_numpy(snwp_points_vtk_array)

        pc_y_vtk_array = pc_table.GetTable().GetColumnByName("dsn")
        self.pc_y_values = vtk_to_numpy(pc_y_vtk_array)
        pc_x_vtk_array = pc_table.GetTable().GetColumnByName("pc")
        self.pc_x_values = vtk_to_numpy(pc_x_vtk_array)

        radius_y_vtk_array = radius_table.GetTable().GetColumnByName("dsn")
        self.radius_y_values = vtk_to_numpy(radius_y_vtk_array)
        radius_x_vtk_array = radius_table.GetTable().GetColumnByName("radius")
        self.radius_x_values = vtk_to_numpy(radius_x_vtk_array)

        self.micpSeries.setData(self.snwp_values, self.pc_values)
        self.pcSeries.setData(self.pc_x_values, self.pc_y_values)
        self.radiiSeries.setData(self.radius_x_values, self.radius_y_values)

    def getParams(self, node):
        subres_model_name = self.subscaleModelWidget.microscale_model_dropdown.currentText
        subres_params = self.subscaleModelWidget.parameter_widgets[subres_model_name].get_params()
        subres_shape_factor = self.subscaleModelWidget.getParams()["subres_shape_factor"]
        subres_porositymodifier = self.subscaleModelWidget.getParams()["subres_porositymodifier"]

        subres_params_copy = {}
        if (subres_model_name == "Throat Radius Curve" or subres_model_name == "Pressure Curve") and subres_params:
            for i in subres_params.keys():
                if subres_params[i] is not None:
                    if isinstance(subres_params[i], np.ndarray):
                        subres_params_copy.update({i: subres_params[i].tolist()})
                    else:
                        subres_params_copy.update({i: subres_params[i]})
                else:
                    subres_params_copy.update({i: None})
        else:
            subres_params_copy = subres_params

        params = {
            "simulation type": MICP,
            "keep_temporary": False,
            "subres_model_name": subres_model_name,
            "subres_shape_factor": subres_shape_factor,
            "subres_porositymodifier": subres_porositymodifier,
            "subres_params": subres_params_copy,
            "pressures": 100,
            "save_radii_distrib_plots": True,
            "experimental_radius": subres_params_copy.get("pore radii"),
        }

        if type(node) is slicer.vtkMRMLTableNode:
            params.update(get_pore_network_volume_data(node))
        return params

    def setParams(self, params):
        self.subscaleModelWidget.microscale_model_dropdown.setCurrentText(params["subres_model_name"])
        self.subscaleModelWidget.setParams(params)
