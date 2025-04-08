from pathlib import Path

import PySide2 as pyside
import ctk
import pyqtgraph as pg
import qt
import shiboken2
from pyqtgraph.Qt import QtCore
from vtk.util.numpy_support import vtk_to_numpy
import slicer

import numpy as np
from ltrace.pore_networks.functions import (
    geo2spy,
    estimate_pressure,
)
from ltrace.file_utils import read_csv
from ltrace.slicer import ui
from ltrace.slicer.ui import (
    hierarchyVolumeInput,
    DirOrFileWidget,
    floatParam,
)
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget
from .SubscaleModelWidget import SubscaleModelWidget
from PoreNetworkSimulationLib.constants import *


class MercurySimulationWidget(qt.QFrame):
    DEFAULT_VALUES = {
        "simulation type": MICP,
        "keep_temporary": False,
        "subres_model_name": "Fixed Radius",
        "subres_params": {"radius": 0.1},
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
        labelWidget = qt.QLabel("Input Model Node: ")
        micpFormLayout.addRow(labelWidget, self.micpSelector)

        # plots
        pysideReportForm = shiboken2.wrapInstance(hash(micpFormLayout), pyside.QtWidgets.QFormLayout)
        self.subvolumeGraphicsLayout = GraphicsLayoutWidget()
        self.subvolumeGraphicsLayout.setMinimumHeight(600)
        self.subvolumeGraphicsLayout.setMinimumWidth(100)
        self.micpPlotItem = self.subvolumeGraphicsLayout.addPlot(
            row=1, col=1, rowspan=1, colspan=1, left="Pc", bottom="Shg"
        )
        self.micpSeries = self.micpPlotItem.plot(
            name="micp",
            pen=pg.mkPen("r", width=2, style=QtCore.Qt.DashLine),
            symbol="o",
            symbolPen="r",
            symbolSize=8,
            symbolBrush="r",
        )
        self.micpSeries.getViewBox().invertX(True)
        self.pcPlotItem = self.subvolumeGraphicsLayout.addPlot(
            row=2, col=1, rowspan=1, colspan=1, left="dsn", bottom="Pc"
        )
        self.pcSeries = self.pcPlotItem.plot(
            name="pc",
            pen=pg.mkPen("g", width=2, style=QtCore.Qt.DashLine),
            symbol="o",
            symbolPen="g",
            symbolSize=8,
            symbolBrush="g",
        )
        self.radiiPlotItem = self.subvolumeGraphicsLayout.addPlot(
            row=3, col=1, rowspan=1, colspan=1, left="dsn", bottom="Radius"
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

    def onChangeMicp(self):
        micp_table_node = self.micpSelector.currentNode()
        if not micp_table_node:
            return
        micp_data = micp_table_node.GetAttribute("micp_data")
        pc_data = micp_table_node.GetAttribute("pc_data")
        radii_data = micp_table_node.GetAttribute("radii_data")

        pc_points_vtk_array = micp_table_node.GetTable().GetColumnByName("pc")
        self.pc_values = vtk_to_numpy(pc_points_vtk_array)
        snwp_points_vtk_array = micp_table_node.GetTable().GetColumnByName("snwp")
        self.snwp_values = vtk_to_numpy(snwp_points_vtk_array)
        dsn_points_vtk_array = micp_table_node.GetTable().GetColumnByName("dsn")
        self.dsn_values = vtk_to_numpy(dsn_points_vtk_array)
        throat_radii_points_vtk_array = micp_table_node.GetTable().GetColumnByName("radii")
        self.throat_radii_values = vtk_to_numpy(throat_radii_points_vtk_array)

        self.micpSeries.setData(self.snwp_values, self.pc_values)
        self.pcSeries.setData(self.pc_values[:-1], self.dsn_values[:-1])
        self.radiiSeries.setData(self.throat_radii_values[:-1], self.dsn_values[:-1])

    def getFunction(self, pore_node):
        pore_network = geo2spy(pore_node)
        x_size = float(pore_node.GetAttribute("x_size"))
        y_size = float(pore_node.GetAttribute("y_size"))
        z_size = float(pore_node.GetAttribute("z_size"))
        volume = x_size * y_size * z_size

        model = self.subscaleModelWidget.microscale_model_dropdown.currentText
        capillary_function = self.subscaleModelWidget.parameter_widgets[model].get_subradius_function(
            pore_network, volume
        )
        return lambda x: capillary_function(x)

    def getParams(self):
        subres_model_name = self.subscaleModelWidget.microscale_model_dropdown.currentText
        subres_params = self.subscaleModelWidget.parameter_widgets[subres_model_name].get_params()
        subres_shape_factor = self.subscaleModelWidget.getParams()["subres_shape_factor"]
        subres_porositymodifier = self.subscaleModelWidget.getParams()["subres_porositymodifier"]

        if (subres_model_name == "Throat Radius Curve" or subres_model_name == "Pressure Curve") and subres_params:
            subres_params = {
                i: subres_params[i].tolist() if subres_params[i] is not None else None for i in subres_params.keys()
            }

        return {
            "simulation type": MICP,
            "keep_temporary": False,
            "subresolution function call": self.getFunction,
            "subres_model_name": subres_model_name,
            "subres_shape_factor": subres_shape_factor,
            "subres_porositymodifier": subres_porositymodifier,
            "subres_params": subres_params,
            "pressures": 100,
            "save_radii_distrib_plots": True,
            "experimental_radius": subres_params.get("pore radii"),
        }

    def setParams(self, params):
        self.subscaleModelWidget.microscale_model_dropdown.setCurrentText(params["subres_model_name"])
