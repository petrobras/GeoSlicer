import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyqtgraph as pg
import PySide2 as pyside
import qt

from ltrace.slicer.widget.heatmap import HeatMap
from PoreNetworkKrelEdaLib.visualization_widgets.plot_base import PlotBase


class ParameterResultCorrelation(PlotBase):
    DISPLAY_NAME = "Parameters and Result correlation"
    METHOD = "plot3"

    def __init__(self, *args, **kwargs):
        super().__init__()

        self.data_manager = kwargs["data_manager"]

        self.mainLayout = qt.QFormLayout(self)
        self.heatmap = HeatMap()

        self.mainLayout.addRow(self.heatmap)

    def update(self):
        corr = self.data_manager.get_error_correlation_dataframe()
        parameters = self.data_manager.get_variable_parameters_list()
        results = self.data_manager.get_sqerror_result_list()

        sub_corr = corr[parameters].loc[results]

        self.heatmap.set_dataframe(sub_corr)

    def clear_saved_plots(self):
        df = pd.DataFrame()
        self.heatmap.set_dataframe(df)


class ParameterErrorCorrelation(PlotBase):
    DISPLAY_NAME = "Parameters and Error correlation"
    METHOD = "plot4"

    def __init__(self, *args, **kwargs):
        super().__init__()

        self.data_manager = kwargs["data_manager"]

        self.mainLayout = qt.QFormLayout(self)
        self.heatmap = HeatMap()

        self.mainLayout.addRow(self.heatmap)

    def update(self):
        corr = self.data_manager.get_error_correlation_dataframe()
        errors = self.data_manager.get_errors_list()
        parameters = self.data_manager.get_variable_parameters_list()

        sub_corr = corr[parameters].loc[errors]

        self.heatmap.set_dataframe(sub_corr)

    def clear_saved_plots(self):
        df = pd.DataFrame()
        self.heatmap.set_dataframe(df)


class ResultSelfCorrelation(PlotBase):
    DISPLAY_NAME = "Results selfcorrelation"
    METHOD = "plot5"

    def __init__(self, *args, **kwargs):
        super().__init__()

        self.data_manager = kwargs["data_manager"]

        self.mainLayout = qt.QFormLayout(self)
        self.heatmap = HeatMap()

        self.mainLayout.addRow(self.heatmap)

    def update(self):
        corr = self.data_manager.get_error_correlation_dataframe()
        results = self.data_manager.get_sqerror_result_list()

        sub_corr = corr[results].loc[results]

        self.heatmap.set_dataframe(sub_corr)

    def clear_saved_plots(self):
        df = pd.DataFrame()
        self.heatmap.set_dataframe(df)


class SecondOrderInteraction(PlotBase):
    DISPLAY_NAME = "Second order interactions"
    METHOD = "plot6"

    def __init__(self, *args, **kwargs):
        super().__init__()

        self.data_manager = kwargs["data_manager"]

        self.mainLayout = qt.QFormLayout(self)
        self.heatmap = HeatMap()
        self.heatmap.color_scale = color_scale

        self.mainLayout.addRow(self.heatmap)

    def update(self):
        anova = self.data_manager.anova(2)

        anova_parameters = {}
        for column in anova.index:
            if ":" not in column and column != "Intercept" and column != "Residual":
                anova_parameters[column] = len(anova_parameters)

        anova_df = pd.DataFrame(columns=anova_parameters, index=anova_parameters)

        for i in anova.index:
            if ":" not in i and i != "Intercept" and i != "Residual":
                anova_df.loc[i][i] = anova.loc[i]["PR(>F)"]
            elif i != "Intercept" and i != "Residual":
                j, k = i.split(":")
                anova_df.loc[j][k] = anova.loc[i]["PR(>F)"]
                anova_df.loc[k][j] = anova.loc[i]["PR(>F)"]

        for i in anova_df:
            anova_df[i] = anova_df[i].astype(float)

        self.heatmap.set_dataframe(anova_df)

    def clear_saved_plots(self):
        df = pd.DataFrame()
        self.heatmap.set_dataframe(df)


def color_scale(value):
    if value <= 0.05:
        value = value / 0.05
        back_color = (int(255 * value), int(150 + 105 * value), int(180 * value))
    else:
        value = (value - 0.05) / 0.45
        value = min(1, value)
        back_color = (255, int(255 - 205 * value), int(180 - 130 * value))

    font_color = (0, 0, 0)
    return back_color, font_color
