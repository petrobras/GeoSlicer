import numpy as np
import pyqtgraph as pg
import PySide2
import qt
import re
import shiboken2
import slicer

from ltrace.slicer import helpers
from ltrace.slicer_utils import dataframeFromTable
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget
from PoreNetworkKrelEdaLib.visualization_widgets.plot_base import PlotBase


class CaDistributionPlot(PlotBase):
    DISPLAY_NAME = "CA distribution plot"
    METHOD = "plot9"

    def __init__(self, *args, **kwargs):
        super().__init__()

        self.data_manager = kwargs["data_manager"]

        self.graphics_layout_widget = GraphicsLayoutWidget()
        self.graphics_layout_widget.setBackground("w")
        self.graphics_layout_widget.setFixedHeight(360)

        x_legend_label_item = pg.LabelItem(angle=0)
        y_legend_label_item = pg.LabelItem(angle=270)
        x_legend_label_item.setText("Contact angle (degree)", color="k")
        y_legend_label_item.setText("Bins", color="k")
        self.graphics_layout_widget.addItem(x_legend_label_item, row=2, col=2, colspan=2)
        self.graphics_layout_widget.addItem(y_legend_label_item, row=0, col=1, rowspan=2)

        self.plot_item = self.graphics_layout_widget.addPlot()
        self.plot_item.addLegend()

        self.simulationCombobox = qt.QComboBox()
        self.simulationCombobox.addItem(0)
        self.simulationCombobox.currentTextChanged.connect(self.__update_histograms)

        self.phaseCombobox = qt.QComboBox()
        self.phaseCombobox.addItem("Drainage")
        self.phaseCombobox.addItem("Imbibition")
        self.phaseCombobox.currentTextChanged.connect(self.__update_histograms)

        formLayout = qt.QFormLayout()
        formLayout.addRow("Simulation:", self.simulationCombobox)
        formLayout.addRow("Phase:", self.phaseCombobox)

        pySideMainLayout = shiboken2.wrapInstance(hash(formLayout), PySide2.QtWidgets.QFormLayout)
        pySideMainLayout.addRow(self.graphics_layout_widget)

        frameLayout = qt.QVBoxLayout()
        frameLayout.addLayout(formLayout)
        frameLayout.addStretch()

        mainFrame = qt.QFrame()
        mainFrame.setLayout(frameLayout)

        mainLayout = qt.QVBoxLayout()
        mainLayout.addWidget(mainFrame)
        mainLayout.addStretch()
        self.setLayout(mainLayout)

    def clear_saved_plots(self):
        self.plot_item.clear()

    def update(self):
        inputNode = self.data_manager.input_node
        if inputNode is None:
            return

        self.simulationCombobox.clear()

        regex = re.compile("ca_distribution_(\\d+)_id")
        for name in inputNode.GetAttributeNames():
            matches = regex.match(name)
            if matches:
                self.simulationCombobox.addItem(matches[1])

        self.__update_histograms()

    def __update_histograms(self):
        self.clear_saved_plots()
        self.__update_plots()

    def __update_plots(self):
        inputNode = self.data_manager.input_node
        if inputNode is None:
            return

        tableNode = None
        regex = re.compile("ca_distribution_(\\d+)_id")
        for name in inputNode.GetAttributeNames():
            matches = regex.match(name)
            if matches and matches[1] == self.simulationCombobox.currentText:
                tableNode = helpers.tryGetNode(inputNode.GetAttribute(name))
                break

        if tableNode is None:
            return

        df = dataframeFromTable(tableNode)

        if self.phaseCombobox.currentText == "Drainage":
            preffix = "drainage"
        else:
            preffix = "imbibition"

        hist, edges = np.histogram(df[f"{preffix}-advancing"], bins=20)
        self.plot_item.plot(
            edges, hist, name="advancing", stepMode=True, fillLevel=0, brush=(0, 0, 255, 80), pen=(0, 0, 0)
        )

        hist, edges = np.histogram(df[f"{preffix}-receding"], bins=20)
        self.plot_item.plot(
            edges, hist, name="receding", stepMode=True, fillLevel=0, brush=(255, 0, 0, 80), pen=(0, 0, 0)
        )
