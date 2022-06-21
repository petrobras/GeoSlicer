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
from ltrace.pore_networks.functions import geo2spy
from ltrace.file_utils import read_csv
from ltrace.slicer import ui
from ltrace.slicer.ui import (
    hierarchyVolumeInput,
    DirOrFileWidget,
    floatParam,
)
from ltrace.slicer_utils import dataframeFromTable
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget
from MercurySimulationLib.MercurySimulationLogic import MercurySimulationLogic
from MercurySimulationLib.SubscaleModelWidget import SubscaleModelWidget


class MercurySimulationWidget(qt.QFrame):
    def __init__(self):
        super().__init__()
        layout = qt.QFormLayout(self)

        self.mercury_logic = MercurySimulationLogic()

        self.subscaleModelWidget = SubscaleModelWidget()
        layout.addWidget(self.subscaleModelWidget)

        #
        # MICP Graph visualization
        #
        micpCollapsibleButton = ctk.ctkCollapsibleButton()
        micpCollapsibleButton.text = "MICP Visualization"
        micpCollapsibleButton.setChecked(False)
        layout.addRow(micpCollapsibleButton)
        micpFormLayout = qt.QFormLayout(micpCollapsibleButton)

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

    def runMICPSimulation(self, pb, pore_node, output_prefix):
        pb.setMessage("Beginning simulation")
        pb.setProgress(0)
        pb.setMessage("Running mercury injection simulation")
        pb.setProgress(0)

        pore_network = geo2spy(pore_node)
        x_size = float(pore_node.GetAttribute("x_size"))
        y_size = float(pore_node.GetAttribute("y_size"))
        z_size = float(pore_node.GetAttribute("z_size"))
        volume = x_size * y_size * z_size

        subres_model_name = self.subscaleModelWidget.microscale_model_dropdown.currentText
        subres_model = self.subscaleModelWidget.parameter_widgets[subres_model_name]
        subresolution_function = subres_model.get_subradius_function(pore_network, volume)

        for progress in self.mercury_logic.run_mercury(
            pore_node,
            subresolution_function=subresolution_function,
            prefix=output_prefix,
        ):
            pb.setProgress(progress)
        pb.setMessage("Done")
        pb.setProgress(100)

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
        return capillary_function
