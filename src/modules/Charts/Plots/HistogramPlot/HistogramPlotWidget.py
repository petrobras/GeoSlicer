from ..BasePlotWidget import BasePlotWidget
from ltrace.slicer.graph_data import NodeGraphData

from pyqtgraph.Qt import QtGui, QtCore
import pyqtgraph as pg
import numpy as np
from ltrace.slicer.widget.custom_color_button import CustomColorButton
import os
from .HistogramPlotWidgetModel import HistogramPlotWidgetModel
import math
from collections import namedtuple

RESOURCES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Resources")
ICONS_DIR_PATH = os.path.join(RESOURCES_PATH, "Icons")
REMOVE_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "CancelIcon.png")
VISIBLE_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "eye.svg")
NOT_VISIBLE_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "eye-off.svg")
PLOT_UPDATE_TIMER_INTERVAL_MS = 250
AXIS_NONE_PARAMETER = ""


HistogramData = namedtuple("HistogramData", ["x", "y", "originalMinValue", "originalMaxValue"])


class HistogramPlotWidget(BasePlotWidget):
    TYPE = "Histogram"

    def __init__(self, plotLabel="", *args, **kwargs):
        super().__init__(plotType=self.TYPE, plotLabel=plotLabel, *args, **kwargs)
        self.__model = HistogramPlotWidgetModel(self)
        self.__createPlotUpdateTimer()

    def setupUi(self):
        """Initialize widgets"""
        layout = QtGui.QVBoxLayout()

        # Data table widget
        self.__tableWidget = QtGui.QTableWidget()
        self.__tableWidget.setColumnCount(4)
        self.__tableWidget.setRowCount(0)
        self.__tableWidget.verticalHeader().setHidden(True)
        self.__tableWidget.horizontalHeader().setResizeMode(0, QtGui.QHeaderView.Stretch)
        self.__tableWidget.horizontalHeader().setResizeMode(3, QtGui.QHeaderView.ResizeToContents)
        self.__tableWidget.setHorizontalHeaderLabels(["Data", "Mean", "Std dev", "Options"])
        self.__tableWidget.setShowGrid(False)
        self.__tableWidget.setAlternatingRowColors(True)
        self.__tableWidget.setSelectionBehavior(self.__tableWidget.SelectRows)
        self.__tableWidget.setSelectionMode(self.__tableWidget.SingleSelection)
        layout.addWidget(self.__tableWidget, 4)

        # Plot widgets
        self.__graphicsLayoutWidget = pg.GraphicsLayoutWidget()
        self.__plotItem = self.__graphicsLayoutWidget.addPlot(row=0, rowspan=9, col=0)
        layout.addWidget(self.__graphicsLayoutWidget, 10)

        # Plot options
        optionLayout = QtGui.QFormLayout()
        self.__data_combo_box = QtGui.QComboBox()
        self.__weight_combo_box = QtGui.QComboBox()
        self.__bins_spin_box = QtGui.QSpinBox()
        self.__bins_spin_box.setRange(1, 999999)
        self.__bins_spin_box.setValue(10)

        # Minimum maximum clipping interval
        self.__xMinField = QtGui.QLineEdit()
        self.__xMinField.setPlaceholderText("X minimum")
        self.__xMaxField = QtGui.QLineEdit()
        self.__xMaxField.setPlaceholderText("X maximum")
        xIntervalLayout = QtGui.QHBoxLayout()
        xIntervalLayout.addWidget(self.__xMinField)
        xIntervalLayout.addWidget(self.__xMaxField)

        self.__showMeanStdCheck = QtGui.QCheckBox("Show mean and standard deviation in graph")
        self.__showMeanStdCheck.setChecked(True)

        # Log option
        self.__logCheckBox = QtGui.QCheckBox("Log mode")
        self.__logCheckBox.setChecked(False)

        optionLayout.addRow("Data", self.__data_combo_box)
        optionLayout.addRow("Bins", self.__bins_spin_box)
        optionLayout.addRow("Weight", self.__weight_combo_box)
        optionLayout.addRow("X Interval", xIntervalLayout)
        optionLayout.addRow(self.__showMeanStdCheck)
        optionLayout.addRow(self.__logCheckBox)

        layout.addLayout(optionLayout)

        self.setLayout(layout)

        # Create connections
        self.__data_combo_box.currentTextChanged.connect(lambda text: self.updatePlot())
        self.__weight_combo_box.currentTextChanged.connect(lambda text: self.updatePlot())
        self.__bins_spin_box.valueChanged.connect(lambda state: self.updatePlot())
        self.__xMinField.textChanged.connect(lambda text: self.updatePlot())
        self.__xMaxField.textChanged.connect(lambda text: self.updatePlot())
        self.__showMeanStdCheck.stateChanged.connect(lambda state: self.updatePlot())
        self.__logCheckBox.stateChanged.connect(lambda state: self.updatePlot())

    def appendData(self, dataNode):
        """Wrapper method for inserting data into the widget"""
        return self.__model.appendData(dataNode)

    def __clearPlot(self):
        """Handles plot clearing"""
        self.__plotItem.clear()

    def __createPlotUpdateTimer(self):
        """Initialize timer object that process data to plot"""
        if hasattr(self, "plotUpdateTimer") and self.plotUpdateTimer is not None:
            self.plotUpdateTimer.deleteLater()
            self.plotUpdateTimer = None

        self.plotUpdateTimer = QtCore.QTimer()
        self.plotUpdateTimer.setSingleShot(True)
        self.plotUpdateTimer.timeout.connect(lambda: self.__handleUpdatePlot())
        self.plotUpdateTimer.setInterval(PLOT_UPDATE_TIMER_INTERVAL_MS)

    def updatePlot(self):
        """Handler update plot timer start."""
        if self.plotUpdateTimer.isActive():
            self.plotUpdateTimer.stop()

        self.plotUpdateTimer.start()

    def updateGraphDataTable(self, graphDataList: list):
        """Handles table widget data update"""
        self.__tableWidget.clearContents()
        self.__tableWidget.setRowCount(0)
        for graphData in self.__model.graphDataList:
            self.__addDataToTable(graphData)

        self.__updateParameterComboBox()

    def __updateTableVisibleButton(self, button: QtGui.QPushButton, graphData: NodeGraphData):
        """Updates icon of the related visible button (from the table widget)."""
        if graphData.visible is True:
            button.setIcon(QtGui.QIcon(str(VISIBLE_ICON_FILE_PATH)))
        else:
            button.setIcon(QtGui.QIcon(str(NOT_VISIBLE_ICON_FILE_PATH)))

    def __toggleGraphVisible(self, button: QtGui.QPushButton, graphData: NodeGraphData):
        """Updates visible state from GraphData object."""
        graphData.visible = not graphData.visible
        self.__updateTableVisibleButton(button, graphData)

    def __addDataToTable(self, graphData):
        """Creates objects and widgets related to the GraphData inserted."""
        lastRowIndex = self.__tableWidget.rowCount()
        self.__tableWidget.setRowCount(lastRowIndex + 1)

        # Options widget
        optionsWidget = QtGui.QWidget()

        # Visible toggle button
        visibleButton = QtGui.QPushButton("")
        self.__updateTableVisibleButton(visibleButton, graphData)
        visibleButton.setFixedSize(26, 26)
        visibleButton.setIconSize(QtCore.QSize(20, 20))
        visibleButton.setAutoDefault(False)
        visibleButton.setDefault(False)

        # Customize style button
        editButton = CustomColorButton(color=graphData.style.color, symbol=None, line_style=None)
        editButton.setFixedSize(26, 26)
        editButton.setAutoDefault(False)
        editButton.setDefault(False)

        # Remove button
        removeButton = QtGui.QPushButton(QtGui.QIcon(str(REMOVE_ICON_FILE_PATH)), "")
        removeButton.setFixedSize(26, 26)
        removeButton.setIconSize(QtCore.QSize(20, 20))
        removeButton.setAutoDefault(False)
        removeButton.setDefault(False)

        # Options widget layout
        optionsLayout = QtGui.QHBoxLayout()
        optionsLayout.setSizeConstraint(QtGui.QLayout.SetMinimumSize)
        optionsLayout.setSpacing(5)
        optionsLayout.addWidget(visibleButton)
        optionsLayout.addWidget(editButton)
        optionsLayout.addWidget(removeButton)
        optionsWidget.setLayout(optionsLayout)

        # Buttons connections
        visibleButton.clicked.connect(lambda state: self.__toggleGraphVisible(visibleButton, graphData))
        removeButton.clicked.connect(lambda state: self.__model.removeGraphDataFromTable(graphData))
        editButton.sigStyleChanged.connect(
            lambda color, symbol, size: self.__onPlotStyleChanged(graphData, color, symbol, size)
        )

        nameItem = QtGui.QTableWidgetItem(graphData.name)
        nameItem.setFlags(nameItem.flags() & ~QtCore.Qt.ItemIsEditable)
        lastColumn = self.__tableWidget.columnCount() - 1
        self.__tableWidget.setItem(lastRowIndex, 0, nameItem)
        self.__tableWidget.setCellWidget(lastRowIndex, lastColumn, optionsWidget)

        # Fix horizontal header stretching over the limits
        self.__tableWidget.horizontalHeader().reset()

    def __onPlotStyleChanged(self, graphData, color, symbol_text, size):
        """Handles plot style update

        Args:
            graphData (GraphData): the related GraphData object
            color (tuple): the RGB tuple chosed
            symbol_text (str): the symbol description chosed
            size (int): the pen size chosed
        """
        graphData.style.color = (color.red(), color.green(), color.blue())
        self.updatePlot()

    def __xInterval(self):
        try:
            xMin = float(self.__xMinField.text())
        except ValueError:
            xMin = float("-inf")

        try:
            xMax = float(self.__xMaxField.text())
        except ValueError:
            xMax = float("+inf")

        if xMax <= xMin:
            xMin, xMax = float("-inf"), float("+inf")

        return xMin, xMax

    def __handleUpdatePlot(self):
        """Wrapper for updating the plots related to the user's input (2D or 3D plot)"""
        self.__clearPlot()

        # Update log mode
        self.__plotItem.setLogMode(x=self.__logCheckBox.isChecked(), y=False)
        self.__plotItem.setLabel("bottom", self.__data_combo_box.currentText())

        for i, graphData in enumerate(self.__model.graphDataList):
            if graphData.visible is False:
                continue

            self.__tableWidget.setItem(i, 1, QtGui.QTableWidgetItem(""))
            self.__tableWidget.setItem(i, 2, QtGui.QTableWidgetItem(""))

            data_parameter = self.__data_combo_box.currentText()
            weight_parameter = self.__weight_combo_box.currentText()
            bins = self.__bins_spin_box.value()

            data = graphData.data.get(data_parameter, None)
            weights = graphData.data.get(weight_parameter, None)

            if data is None or (weight_parameter != AXIS_NONE_PARAMETER and weights is None):
                continue

            xMin, xMax = self.__xInterval()
            valid_indexes = np.isfinite(data) & (xMin < data) & (data < xMax)
            if weights is not None:
                valid_indexes = valid_indexes & np.isfinite(weights)
                weights = weights[valid_indexes]
            self.__showMeanStdCheck.setEnabled(weights is None)
            data = data[valid_indexes]
            yHistogram, xHistogram = np.histogram(data, bins=bins, weights=weights)

            translucentColor = QtGui.QColor(*graphData.style.color[:3], 128)
            opaqueColor = QtGui.QColor(*graphData.style.color[:3], 255)

            brush = QtGui.QBrush(translucentColor)
            xHistogram = xHistogram if self.__logCheckBox.isChecked() is False else np.log10(xHistogram)
            curve = pg.PlotCurveItem(xHistogram, yHistogram, stepMode=True, fillLevel=0, brush=brush, pen=opaqueColor)
            self.__plotItem.addItem(item=curve)

            if data.size == 0:
                continue

            mean = np.mean(data)
            std = np.std(data)

            meanItem = QtGui.QTableWidgetItem("%6.6g" % mean)
            stdItem = QtGui.QTableWidgetItem("%6.6g" % std)
            self.__tableWidget.setItem(i, 1, meanItem)
            self.__tableWidget.setItem(i, 2, stdItem)

            def get_value_for_plot(value):
                if self.__logCheckBox.isChecked() is False:
                    return value

                if value <= 0:
                    return None

                return np.sign(value) * np.log10(np.abs(value))

            mean_pos = get_value_for_plot(mean)
            mean_minus_std_pos = get_value_for_plot(mean - std)
            mean_plus_std_pos = get_value_for_plot(mean + std)

            if self.__showMeanStdCheck.isEnabled() and self.__showMeanStdCheck.isChecked():
                pen = pg.mkPen(opaqueColor, style=QtCore.Qt.DashLine)
                labelOpts = {"color": "k"}
                self.__plotItem.addItem(pg.InfiniteLine(pos=mean_pos, pen=pen, label="x̄", labelOpts=labelOpts))
                if mean_minus_std_pos is not None:
                    self.__plotItem.addItem(
                        pg.InfiniteLine(pos=mean_minus_std_pos, pen=pen, label="x̄-σ", labelOpts=labelOpts)
                    )
                if mean_plus_std_pos is not None:
                    self.__plotItem.addItem(
                        pg.InfiniteLine(pos=mean_plus_std_pos, pen=pen, label="x̄+σ", labelOpts=labelOpts)
                    )

    def __updateParameterComboBox(self):
        """Update axis combo boxes with the existent data's parameters"""
        parameters_set = set()
        for graphData in self.__model.graphDataList:
            df = graphData.df().select_dtypes(include=[np.number])
            parameters_set.update(df.columns)

        # add empty parameter option
        parameters = [AXIS_NONE_PARAMETER] + list(parameters_set)
        parameters.sort()

        # store old axis selections
        current_data_parameter = self.__data_combo_box.currentText()
        current_weight_parameter = self.__weight_combo_box.currentText()

        # update available parameters
        self.__data_combo_box.clear()
        self.__data_combo_box.addItems(parameters)
        self.__weight_combo_box.clear()
        self.__weight_combo_box.addItems(parameters)

        # restore old axis selections
        self.__data_combo_box.setCurrentText(current_data_parameter)
        self.__weight_combo_box.setCurrentText(current_weight_parameter)
