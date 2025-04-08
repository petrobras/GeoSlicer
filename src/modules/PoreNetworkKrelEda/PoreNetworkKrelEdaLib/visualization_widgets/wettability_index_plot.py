import numpy as np
import PySide2 as pyside
import qt
import shiboken2

from ltrace.slicer.graph_data import DataFrameGraphData
from ltrace.slicer.widget.data_plot_widget import DataPlotWidget
from PoreNetworkKrelEdaLib.visualization_widgets.plot_base import PlotBase


class WettabilityIndexPlot(PlotBase):
    DISPLAY_NAME = "Wettability index plot"
    METHOD = "plot11"

    def __init__(self, *args, **kwargs):
        super().__init__()

        self.data_manager = kwargs["data_manager"]

        self.mainLayout = qt.QFormLayout(self)

        self.zAxisComboBox = qt.QComboBox()
        self.zAxisComboBox.currentTextChanged.connect(self.update)
        self.mainLayout.addRow("Z-axis", self.zAxisComboBox)

        self.dataPlotWidget = DataPlotWidget()
        self.dataPlotWidget.set_theme("Light")

        self.spacerWidget = pyside.QtWidgets.QSpacerItem(
            0, 0, pyside.QtWidgets.QSizePolicy.Expanding, pyside.QtWidgets.QSizePolicy.Expanding
        )

        pySideMainLayout = shiboken2.wrapInstance(hash(self.mainLayout), pyside.QtWidgets.QFormLayout)
        pySideMainLayout.addRow(self.dataPlotWidget.widget)
        pySideMainLayout.addItem(self.spacerWidget)

    def update(self):
        self.zAxisComboBox.blockSignals(True)

        current_z = self.zAxisComboBox.currentText
        self.zAxisComboBox.clear()

        # Define the interactive widgets
        error_columns = self.data_manager.get_errors_list()
        parameters = self.data_manager.get_variable_parameters_list()
        self.zAxisComboBox.addItems(parameters)
        self.zAxisComboBox.setCurrentText(current_z)

        self.zAxisComboBox.blockSignals(False)

        parameters_df = self.data_manager.get_parameters_dataframe()
        z_col = self.zAxisComboBox.currentText

        graphData = DataFrameGraphData(None, parameters_df)
        xData = parameters_df["result-amott"]
        yData = parameters_df["result-usbm"]
        zData = parameters_df[z_col]
        self.dataPlotWidget.clear_plot()
        self.dataPlotWidget.add3dPlot(
            graphData, xData, yData, zData, "result-amott", "result-usbm", z_col, np.min(zData), np.max(zData)
        )
        self.dataPlotWidget.update_legend_item(z_col)
        self.dataPlotWidget._updatePlotsLayout(True, True, z_col)
        self.dataPlotWidget.embeddedLegendVisibility = False

    def clear_saved_plots(self):
        self.dataPlotWidget.clear_plot()
