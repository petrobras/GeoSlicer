import numpy as np
import PySide2 as pyside
import qt
import shiboken2

from ltrace.slicer.graph_data import DataFrameGraphData
from Plots.Crossplot.data_plot_widget import DataPlotWidget
from PoreNetworkKrelEdaLib.visualization_widgets.plot_base import PlotBase


class CrossedError(PlotBase):
    DISPLAY_NAME = "Crossed error"
    METHOD = "plot1"

    def __init__(self, *args, **kwargs):
        super().__init__()

        self.data_manager = kwargs["data_manager"]

        self.mainLayout = qt.QFormLayout(self)

        self.xAxisComboBox = qt.QComboBox()
        self.yAxisComboBox = qt.QComboBox()
        self.zAxisComboBox = qt.QComboBox()
        self.xAxisComboBox.currentTextChanged.connect(self.update)
        self.yAxisComboBox.currentTextChanged.connect(self.update)
        self.zAxisComboBox.currentTextChanged.connect(self.update)
        self.mainLayout.addRow("X-axis", self.xAxisComboBox)
        self.mainLayout.addRow("Y-axis", self.yAxisComboBox)
        self.mainLayout.addRow("Z-axis", self.zAxisComboBox)

        self.dataPlotWidget = DataPlotWidget()
        self.dataPlotWidget.set_theme("Light")
        pySideMainLayout = shiboken2.wrapInstance(hash(self.mainLayout), pyside.QtWidgets.QFormLayout)
        pySideMainLayout.addRow(self.dataPlotWidget.widget)

    def update(self):
        self.xAxisComboBox.blockSignals(True)
        self.yAxisComboBox.blockSignals(True)
        self.zAxisComboBox.blockSignals(True)

        current_x = self.xAxisComboBox.currentText
        self.xAxisComboBox.clear()
        current_y = self.yAxisComboBox.currentText
        self.yAxisComboBox.clear()
        current_z = self.zAxisComboBox.currentText
        self.zAxisComboBox.clear()

        # Define the interactive widgets
        error_columns = self.data_manager.get_errors_list()
        parameters = self.data_manager.get_variable_parameters_list()
        self.xAxisComboBox.addItems(error_columns)
        self.xAxisComboBox.setCurrentText(current_x)
        self.yAxisComboBox.addItems(error_columns)
        self.yAxisComboBox.setCurrentText(current_y)
        self.zAxisComboBox.addItems(parameters)
        self.zAxisComboBox.setCurrentText(current_z)

        self.xAxisComboBox.blockSignals(False)
        self.yAxisComboBox.blockSignals(False)
        self.zAxisComboBox.blockSignals(False)

        parameters_df = self.data_manager.get_parameters_dataframe()
        x_col = self.xAxisComboBox.currentText
        y_col = self.yAxisComboBox.currentText
        z_col = self.zAxisComboBox.currentText

        graphData = DataFrameGraphData(None, parameters_df)
        xData = parameters_df[x_col]
        yData = parameters_df[y_col]
        zData = parameters_df[z_col]
        self.dataPlotWidget.clear_plot()
        self.dataPlotWidget.add3dPlot(graphData, xData, yData, zData, x_col, y_col, z_col, np.min(zData), np.max(zData))
        self.dataPlotWidget.update_legend_item(z_col)
        self.dataPlotWidget._updatePlotsLayout(True, True, z_col)

    def clear_saved_plots(self):
        self.dataPlotWidget.clear_plot()


class CrossedParameters(PlotBase):
    DISPLAY_NAME = "Crossed parameters"
    METHOD = "plot2"

    def __init__(self, *args, **kwargs):
        super().__init__()

        self.data_manager = kwargs["data_manager"]

        self.mainLayout = qt.QFormLayout(self)

        self.xAxisComboBox = qt.QComboBox()
        self.yAxisComboBox = qt.QComboBox()
        self.zAxisComboBox = qt.QComboBox()
        self.xAxisComboBox.currentTextChanged.connect(self.update)
        self.yAxisComboBox.currentTextChanged.connect(self.update)
        self.zAxisComboBox.currentTextChanged.connect(self.update)
        self.mainLayout.addRow("X-axis", self.xAxisComboBox)
        self.mainLayout.addRow("Y-axis", self.yAxisComboBox)
        self.mainLayout.addRow("Z-axis", self.zAxisComboBox)

        self.dataPlotWidget = DataPlotWidget()
        self.dataPlotWidget.set_theme("Light")
        pySideMainLayout = shiboken2.wrapInstance(hash(self.mainLayout), pyside.QtWidgets.QFormLayout)
        pySideMainLayout.addRow(self.dataPlotWidget.widget)

    def update(self):
        self.xAxisComboBox.blockSignals(True)
        self.yAxisComboBox.blockSignals(True)
        self.zAxisComboBox.blockSignals(True)

        current_x = self.xAxisComboBox.currentText
        self.xAxisComboBox.clear()
        current_y = self.yAxisComboBox.currentText
        self.yAxisComboBox.clear()
        current_z = self.zAxisComboBox.currentText
        self.zAxisComboBox.clear()

        # Define the interactive widgets
        error_columns = self.data_manager.get_errors_list()
        parameters = self.data_manager.get_variable_parameters_list()
        self.xAxisComboBox.addItems(parameters)
        self.xAxisComboBox.setCurrentText(current_x)
        self.yAxisComboBox.addItems(parameters)
        self.yAxisComboBox.setCurrentText(current_y)
        self.zAxisComboBox.addItems(error_columns)
        self.zAxisComboBox.setCurrentText(current_z)

        self.xAxisComboBox.blockSignals(False)
        self.yAxisComboBox.blockSignals(False)
        self.zAxisComboBox.blockSignals(False)

        parameters_df = self.data_manager.get_parameters_dataframe()
        x_col = self.xAxisComboBox.currentText
        y_col = self.yAxisComboBox.currentText
        z_col = self.zAxisComboBox.currentText

        graphData = DataFrameGraphData(None, parameters_df)
        grouped_df = parameters_df[[x_col, y_col, z_col]]
        if x_col != y_col:
            grouped_df = parameters_df[[x_col, y_col, z_col]]
            grouped_df = grouped_df.groupby([x_col, y_col], as_index=False).mean()
        else:
            grouped_df = parameters_df[[x_col, z_col]]
            grouped_df = grouped_df.groupby([x_col], as_index=False).mean()
        xData = grouped_df[x_col]
        yData = grouped_df[y_col]
        zData = grouped_df[z_col]
        self.dataPlotWidget.clear_plot()
        self.dataPlotWidget.add3dPlot(graphData, xData, yData, zData, x_col, y_col, z_col, np.min(zData), np.max(zData))
        self.dataPlotWidget.update_legend_item(z_col)
        self.dataPlotWidget._updatePlotsLayout(True, True, z_col)

    def clear_saved_plots(self):
        self.dataPlotWidget.clear_plot()
