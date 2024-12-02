import ctk
import numpy as np
import os
import qt
import shiboken2
import slicer
import vtk

from collections import namedtuple
from ltrace.slicer.widget.style_editor_widget import NO_CHANGE
from ltrace.slicer.graph_data import NodeGraphData, SCATTER_PLOT_TYPE, TEXT_SYMBOLS, LINE_STYLES
from ltrace.slicer import helpers, ui
from ltrace.slicer.equations.equation_base import EquationBase
from ltrace.slicer.equations.fit_data import FitData
from ltrace.slicer.widget.data_plot_widget import DataPlotWidget
from ltrace.slicer.widget.help_button import HelpButton
from matplotlib import cm as matplotlibcm
from pint import Unit, UndefinedUnitError, DefinitionSyntaxError
from pint_pandas import PintArray
from ..BasePlotWidget import BasePlotWidget
from .data_table_widget import DataTableWidget
from .equations.line import Line
from .equations.timur_coates import TimurCoates
from pyqtgraph.Qt import QtGui, QtCore

RESOURCES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Resources")
COLOR_MAPS_DIR_PATH = os.path.join(RESOURCES_PATH, "ColorMaps")
ICONS_DIR_PATH = os.path.join(RESOURCES_PATH, "Icons")
REMOVE_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "CancelIcon.png")
VISIBLE_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "eye.svg")
NOT_VISIBLE_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "eye-off.svg")
AXIS_NONE_PARAMETER = ""
PLOT_UPDATE_TIMER_INTERVAL_MS = 200

"""
Available color maps:
  'flag', 'prism', 'ocean', 'gist_earth', 'terrain', 'gist_stern',
  'gnuplot', 'gnuplot2', 'CMRmap', 'cubehelix', 'brg',
  'gist_rainbow', 'rainbow', 'jet', 'turbo', 'nipy_spectral',
  'gist_ncar'
"""
CrossplotColorMapInfo = namedtuple("CrossplotColorMapInfo", ["label", "object", "reference_image"])
CrossplotColorMaps = [
    CrossplotColorMapInfo(
        label="Gist Rainbow",
        object=matplotlibcm.gist_rainbow,
        reference_image=os.path.join(COLOR_MAPS_DIR_PATH, "gist_rainbow.png"),
    ),
    CrossplotColorMapInfo(
        label="Jet",
        object=matplotlibcm.jet,
        reference_image=os.path.join(COLOR_MAPS_DIR_PATH, "jet.png"),
    ),
    CrossplotColorMapInfo(
        label="Rainbow",
        object=matplotlibcm.rainbow,
        reference_image=os.path.join(COLOR_MAPS_DIR_PATH, "rainbow.png"),
    ),
    CrossplotColorMapInfo(
        label="Hot",
        object=matplotlibcm.hot,
        reference_image=os.path.join(COLOR_MAPS_DIR_PATH, "hot.png"),
    ),
    CrossplotColorMapInfo(
        label="YlOrBr",
        object=matplotlibcm.YlOrBr,
        reference_image=os.path.join(COLOR_MAPS_DIR_PATH, "YlOrBr.png"),
    ),
    CrossplotColorMapInfo(
        label="Seismic",
        object=matplotlibcm.seismic,
        reference_image=os.path.join(COLOR_MAPS_DIR_PATH, "seismic.png"),
    ),
]


class UnitConversionWidget(qt.QWidget):
    unitsChanged = qt.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.__lastUnits = None
        self.__currentUnits = None

        layout = qt.QHBoxLayout()
        # layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.__fromUnitEdit = self.__createUnitLineEdit()
        self.__toLabel = qt.QLabel("→")
        self.__toUnitEdit = self.__createUnitLineEdit()

        help_button = HelpButton(
            "### Unit conversion"
            + "\n\nConvert values from the unit expressed on the left to the unit expressed on the"
            + " right. A comprehensive list of physical units, prefixes and constants can be"
            + " found [here](https://github.com/hgrecco/pint/blob/master/pint/default_en.txt)."
        )

        layout.addWidget(qt.QLabel("Convert from"))
        layout.addWidget(self.__fromUnitEdit)
        layout.addWidget(self.__toLabel)
        layout.addWidget(self.__toUnitEdit)
        layout.addWidget(help_button)
        layout.addStretch()

    def __createUnitLineEdit(self):
        lineEdit = qt.QLineEdit()
        lineEdit.setFixedWidth(60)
        lineEdit.editingFinished.connect(self.__updateUnits)
        lineEdit.textChanged.connect(lambda: self.__updateLineEditStyle(lineEdit))
        lineEdit.textChanged.connect(self.__updateUnitsStyle)
        return lineEdit

    def __unitFromLineEdit(self, lineEdit):
        unit = ""
        text = lineEdit.text
        if text:
            try:
                unit = Unit(text)
            except (UndefinedUnitError, DefinitionSyntaxError):
                unit = None
        return unit

    def __updateLineEditStyle(self, lineEdit):
        unit = self.__unitFromLineEdit(lineEdit)
        if unit == "":
            style = ""
        else:
            color = "red" if unit is None else "green"
            style = f"border: 1px solid {color}"
        lineEdit.setStyleSheet(style)

    def __updateUnitsStyle(self):
        units = self.currentUnits()

        if not all(units):
            units = None
            self.__toLabel.setStyleSheet("")
        else:
            unitFrom, unitTo = units
            if unitFrom.is_compatible_with(unitTo):
                self.__toLabel.setStyleSheet("color: green")
                self.__toLabel.setToolTip(f"Converting {unitFrom} to {unitTo}")
            else:
                self.__toLabel.setStyleSheet("color: red")
                self.__toLabel.setToolTip(f"Cannot convert {unitFrom} to {unitTo}")
                units = None

        self.__currentUnits = units

    def __updateUnits(self):
        if self.__currentUnits != self.__lastUnits:
            self.__lastUnits = self.__currentUnits
            self.unitsChanged.emit()

    def convert(self, array):
        if self.__lastUnits is None:
            return array
        unitFrom, unitTo = self.__lastUnits
        parsed_array = array.astype(f"pint[{unitFrom}]").pint
        return parsed_array.to(unitTo).pint.magnitude

    def currentUnits(self):
        return self.__unitFromLineEdit(self.__fromUnitEdit), self.__unitFromLineEdit(self.__toUnitEdit)

    def isActive(self):
        units = self.currentUnits()

        unitFrom, unitTo = units

        return all(units) and unitFrom.is_compatible_with(unitTo)


class CrossplotWidget(BasePlotWidget):
    TYPE = "Crossplot"

    def __init__(self, plotLabel="", *args, **kwargs):
        super().__init__(plotType=self.TYPE, plotLabel=plotLabel, *args, **kwargs)
        self.dataPlotWidget = None
        self.__graphDataList = list()
        self.__tableWidget = None
        self.__zMinValueRange = 0
        self.__zMaxValueRange = 0
        self.__createPlotUpdateTimer()
        self.__fitDataList = []
        self.__validFittedCurveSelected = False

        self.__fitEquations = [Line(), TimurCoates()]

    def setupUi(self):
        """Initialize widgets"""
        self.setObjectName("Crossplot Widget")
        self.setMinimumSize(780, 600)
        layout = QtGui.QHBoxLayout()

        parametersWidget = QtGui.QFrame()
        parametersLayout = QtGui.QVBoxLayout()
        parametersWidget.setLayout(parametersLayout)
        plot_layout = QtGui.QVBoxLayout()
        # Data table widget
        self.__tableWidget = DataTableWidget()
        self.__tableWidget.signal_style_changed.connect(self.__updatePlot)
        self.__tableWidget.signal_data_removed.connect(self.__removeDataFromTableByName)
        self.__tableWidget.signal_all_style_changed.connect(self.__updateAllDataStyles)
        self.__tableWidget.signal_all_visible_changed.connect(self.__updateAllDataVisibility)
        parametersLayout.addWidget(self.__tableWidget)
        # Plot widget
        self.dataPlotWidget = DataPlotWidget()
        self.dataPlotWidget.toggleLegendSignal.connect(self.__toggleLegend)
        plot_layout.addWidget(self.dataPlotWidget.widget)

        plot_layout.addStretch()
        # X axis
        # Histogram options
        self.__xAxisHistogramEnableCheckBox = QtGui.QCheckBox()
        self.__xAxisHistogramEnableCheckBox.setChecked(True)
        self.__xAxisHistogramEnableCheckBox.stateChanged.connect(self.__onHistogramCheckBoxChange)
        xHistogramCheckBoxLabel = QtGui.QLabel("Enable histogram")
        xHistogramCheckBoxLabel.setBuddy(self.__xAxisHistogramEnableCheckBox)

        self.__xHistogramBinSpinBox = QtGui.QSpinBox()
        self.__xHistogramBinSpinBox.setRange(3, 99999)
        self.__xHistogramBinSpinBox.setValue(10)
        xHistogramSpinBoxLabel = QtGui.QLabel("Bins")
        xHistogramSpinBoxLabel.setBuddy(self.__xHistogramBinSpinBox)

        self.__xUnitConversion = UnitConversionWidget()

        self.__xLogCheckBox = QtGui.QCheckBox()
        self.__xLogCheckBox.setVisible(False)
        self.__xLogCheckBox.setEnabled(False)
        self.__xLogCheckBox.setChecked(False)
        self.__xLogCheckBox.stateChanged.connect(self.__onLogCheckBoxChange)
        xLogCheckBoxLabel = QtGui.QLabel("Log")
        xLogCheckBoxLabel.setBuddy(self.__xLogCheckBox)
        xLogCheckBoxLabel.setVisible(False)

        # Parameter combobox
        self.__xAxisComboBox = QtGui.QComboBox()
        self.__xAxisComboBox.objectName = "X Axis Combo Box"
        xAxisParameterLayout = QtGui.QFormLayout()
        xAxisParameterLayout.addRow("Parameter", self.__xAxisComboBox)
        xAxisParameterLayout.setHorizontalSpacing(8)
        # Layout
        self.__xAxisGridLayout = QtGui.QGridLayout()
        self.__xAxisGroupBox = QtGui.QGroupBox("X axis")
        self.__xAxisGroupBox.setLayout(self.__xAxisGridLayout)
        parametersLayout.addWidget(self.__xAxisGroupBox)

        self.__xAxisGridLayout.setHorizontalSpacing(5)
        self.__xAxisGridLayout.addLayout(xAxisParameterLayout, 0, 0, 1, -1)
        self.__xAxisGridLayout.addWidget(xHistogramCheckBoxLabel, 1, 0, 1, 1)
        self.__xAxisGridLayout.addWidget(self.__xAxisHistogramEnableCheckBox, 1, 1, 1, 1)
        x_bins_layout = QtGui.QHBoxLayout()
        x_bins_layout.addWidget(xHistogramSpinBoxLabel)
        x_bins_layout.addWidget(self.__xHistogramBinSpinBox)
        x_bins_layout.setSpacing(5)
        self.__xAxisGridLayout.addLayout(x_bins_layout, 1, 2, 1, 1)
        self.__xAxisGridLayout.addWidget(
            shiboken2.wrapInstance(hash(self.__xUnitConversion), QtGui.QWidget), 2, 0, 1, 4
        )
        # Groupbox

        # Y axis
        # Histogram options
        self.__yAxisHistogramEnableCheckBox = QtGui.QCheckBox()
        self.__yAxisHistogramEnableCheckBox.setChecked(True)
        self.__yAxisHistogramEnableCheckBox.stateChanged.connect(self.__onHistogramCheckBoxChange)
        yHistogramCheckBoxLabel = QtGui.QLabel("Enable histogram")
        yHistogramCheckBoxLabel.setBuddy(self.__yAxisHistogramEnableCheckBox)

        self.__yHistogramBinSpinBox = QtGui.QSpinBox()
        self.__yHistogramBinSpinBox.setRange(3, 99999)
        self.__yHistogramBinSpinBox.setValue(10)
        yHistogramSpinBoxLabel = QtGui.QLabel("Bins")
        yHistogramSpinBoxLabel.setBuddy(self.__yHistogramBinSpinBox)

        self.__yUnitConversion = UnitConversionWidget()

        self.__yLogCheckBox = QtGui.QCheckBox()
        self.__yLogCheckBox.setVisible(False)
        self.__yLogCheckBox.setEnabled(False)
        self.__yLogCheckBox.setChecked(False)
        self.__yLogCheckBox.stateChanged.connect(self.__onLogCheckBoxChange)
        yLogCheckBoxLabel = QtGui.QLabel("Log")
        yLogCheckBoxLabel.setBuddy(self.__yLogCheckBox)
        yLogCheckBoxLabel.setVisible(False)

        # Parameter combobox
        self.__yAxisComboBox = QtGui.QComboBox()
        self.__yAxisComboBox.objectName = "Y Axis Combo Box"
        yAxisParameterLayout = QtGui.QFormLayout()
        yAxisParameterLayout.addRow("Parameter", self.__yAxisComboBox)
        yAxisParameterLayout.setHorizontalSpacing(8)

        # Layout
        self.__yAxisGridLayout = QtGui.QGridLayout()
        self.__yAxisGroupBox = QtGui.QGroupBox("Y axis")
        self.__yAxisGroupBox.setLayout(self.__yAxisGridLayout)
        parametersLayout.addWidget(self.__yAxisGroupBox)

        self.__yAxisGridLayout.setHorizontalSpacing(5)
        self.__yAxisGridLayout.addLayout(yAxisParameterLayout, 0, 0, 1, -1)
        self.__yAxisGridLayout.addWidget(yHistogramCheckBoxLabel, 1, 0, 1, 1)
        self.__yAxisGridLayout.addWidget(self.__yAxisHistogramEnableCheckBox, 1, 1, 1, 1)
        y_bins_layout = QtGui.QHBoxLayout()
        y_bins_layout.addWidget(yHistogramSpinBoxLabel)
        y_bins_layout.addWidget(self.__yHistogramBinSpinBox)
        y_bins_layout.setSpacing(5)
        self.__yAxisGridLayout.addLayout(y_bins_layout, 1, 2, 1, 1)
        self.__yAxisGridLayout.addWidget(
            shiboken2.wrapInstance(hash(self.__yUnitConversion), QtGui.QWidget), 2, 0, 1, 4
        )
        # Groupbox

        # Z axis
        self.__zAxisComboBox = QtGui.QComboBox()
        self.__autoRangeCheckBox = QtGui.QCheckBox()
        self.__ZMinValueRangeDoubleSpinBox = QtGui.QDoubleSpinBox()
        self.__ZMinValueRangeDoubleSpinBox.setRange(0, 99999999)

        self.__ZMaxValueRangeDoubleSpinBox = QtGui.QDoubleSpinBox()
        self.__ZMaxValueRangeDoubleSpinBox.setRange(0, 99999999)

        self.__colorMapComboBox = QtGui.QComboBox()
        self.__colorMapComboBox.setIconSize(QtCore.QSize(80, 20))
        self.__populateColorMapComboBox()

        # Manual/Auto range widgets layout
        rangeLayout = QtGui.QHBoxLayout()
        rangeLayout.setSpacing(5)
        autoRangeLayout = QtGui.QHBoxLayout()
        autoRangeLayout.setSpacing(5)
        autoRangeLayout.addWidget(QtGui.QLabel("Auto Range"))
        autoRangeLayout.addWidget(self.__autoRangeCheckBox)
        rangeLayout.addLayout(autoRangeLayout)
        minimumLayout = QtGui.QHBoxLayout()
        minimumLayout.setSpacing(5)
        minimumLayout.addWidget(QtGui.QLabel("Min"))
        minimumLayout.addWidget(self.__ZMinValueRangeDoubleSpinBox)
        rangeLayout.addLayout(minimumLayout)
        maximumLayout = QtGui.QHBoxLayout()
        maximumLayout.setSpacing(5)
        maximumLayout.addWidget(QtGui.QLabel("Max"))
        maximumLayout.addWidget(self.__ZMaxValueRangeDoubleSpinBox)
        rangeLayout.addLayout(maximumLayout)

        self.__zUnitConversion = UnitConversionWidget()
        formLayout = QtGui.QFormLayout()
        zStyleGroupBox = QtGui.QGroupBox("Z axis")
        zStyleGroupBox.setLayout(formLayout)
        parametersLayout.addWidget(zStyleGroupBox)
        formLayout.addRow("Parameter", self.__zAxisComboBox)
        formLayout.addRow(rangeLayout)
        formLayout.addRow("Color map", self.__colorMapComboBox)
        formLayout.addRow(shiboken2.wrapInstance(hash(self.__zUnitConversion), QtGui.QWidget))

        # Settings
        self.__settingsGroupBox = QtGui.QGroupBox("Settings")
        self.__themeComboBox = QtGui.QComboBox()
        for themeName in self.dataPlotWidget.themes:
            self.__themeComboBox.addItem(themeName)
        self.__embeddedLegendVisibilityCheckBox = QtGui.QCheckBox()
        self.__embeddedLegendVisibilityCheckBox.setChecked(self.dataPlotWidget.embeddedLegendVisibility)
        self.__embeddedLegendVisibilityCheckBox.stateChanged.connect(self.__onEmbeddedLegendVisibilityChange)
        settingsFormLayout = QtGui.QFormLayout()
        settingsFormLayout.setHorizontalSpacing(8)
        settingsFormLayout.addRow("Theme", self.__themeComboBox)
        settingsFormLayout.addRow("Show legend", self.__embeddedLegendVisibilityCheckBox)
        self.__settingsGroupBox.setLayout(settingsFormLayout)

        parametersLayout.addWidget(self.__settingsGroupBox)

        self.__themeComboBox.setCurrentText(self.dataPlotWidget.themes[0])

        # Stretch
        parametersLayout.addStretch()

        # Tabs
        tabWidget = QtGui.QTabWidget()
        tabWidget.addTab(parametersWidget, "Data")
        fitFrameQt = self.__createFitTab()
        fitFrameQtGui = shiboken2.wrapInstance(hash(fitFrameQt), QtGui.QFrame)
        tabWidget.addTab(fitFrameQtGui, "Curve fitting")
        self.equationsTab = EquationsTabWidget(self.__fitDataList)
        self.equationsTab.signalNewFunctionCurveData.connect(self.__onFitDataCreated)
        self.equationsTab.signalImportFunctionCurve.connect(self.__onImportClicked)
        self.equationsTab.signalExportFunctionCurve.connect(self.__onExportClicked)
        self.equationsTab.signalFunctionCurveEdited.connect(self.__onFunctionCurveEdited)
        self.equationsTab.signalSaveData.connect(self.__on_function_curve_save_button_clicked)
        equationsTabQtGui = shiboken2.wrapInstance(hash(self.equationsTab), QtGui.QFrame)
        tabWidget.addTab(equationsTabQtGui, "Curves")

        shortest_width = min(parametersWidget.sizeHint().width(), fitFrameQtGui.sizeHint().width())
        parametersWidget.setMaximumWidth(shortest_width)
        fitFrameQtGui.setMaximumWidth(shortest_width)
        tabWidget.setMaximumWidth(shortest_width)

        # Layout
        layout.addWidget(tabWidget)
        layout.addLayout(plot_layout)
        layout.setSpacing(10)
        self.setLayout(layout)

        # Start connections
        self.__autoRangeCheckBox.stateChanged.connect(self.__onAutoRangeCheckBoxChanged)
        self.__xAxisComboBox.currentTextChanged.connect(lambda text: self.__updatePlot())
        self.__yAxisComboBox.currentTextChanged.connect(lambda text: self.__updatePlot())
        self.__zAxisComboBox.currentTextChanged.connect(lambda text: self.__updatePlot())
        self.__colorMapComboBox.currentTextChanged.connect(self.__onColorMapComboBoxChanged)
        self.__ZMinValueRangeDoubleSpinBox.valueChanged.connect(self.__onZMinValueRangeChanged)
        self.__ZMaxValueRangeDoubleSpinBox.valueChanged.connect(self.__onZMaxValueRangeChanged)

        self.__xHistogramBinSpinBox.valueChanged.connect(self.__onHistogramBinChange)
        self.__yHistogramBinSpinBox.valueChanged.connect(self.__onHistogramBinChange)
        self.__themeComboBox.currentTextChanged.connect(lambda text: self.__updatePlot())

        self.__xUnitConversion.unitsChanged.connect(self.__updatePlot)
        self.__yUnitConversion.unitsChanged.connect(self.__updatePlot)
        self.__zUnitConversion.unitsChanged.connect(self.__updatePlot)

        # Apply default values
        self.__autoRangeCheckBox.setChecked(True)
        self.dataPlotWidget.set_theme(self.__themeComboBox.currentText())
        self.__updatePlotsLayout()
        self.__onFittedCurveSelected("")

    @property
    def graphDataList(self):
        return list(self.__graphDataList)

    def __createFitTab(self) -> qt.QFrame:
        """Creates a tab for the curve fitting functionality.

        Returns:
            qt.QFrame: a QFrame containing the layout of the tab.
        """
        self.__fitDataInputComboBox = qt.QComboBox()

        self.__fitEquationComboBox = qt.QComboBox()
        for fitEquation in self.__fitEquations:
            self.__fitEquationComboBox.addItem(fitEquation.widget.DISPLAY_NAME)
        self.__fitEquationComboBox.currentTextChanged.connect(self.__selectFitEquation)

        fitButton = qt.QPushButton("New fit")
        fitButton.setFocusPolicy(qt.Qt.NoFocus)
        fitButton.clicked.connect(self.__onFitClicked)

        fitButtonsLayout = qt.QHBoxLayout()
        fitButtonsLayout.addWidget(fitButton)

        fitInputLayout = qt.QFormLayout()
        fitInputLayout.addRow("Data: ", self.__fitDataInputComboBox)
        fitInputLayout.addRow("Equation: ", self.__fitEquationComboBox)
        fitInputLayout.addRow("", fitButtonsLayout)

        fitInputFrame = qt.QFrame()
        fitInputFrame.setLayout(fitInputLayout)

        ## Input layout
        inputLayout = qt.QVBoxLayout()
        inputLayout.addWidget(fitInputFrame)

        self.inputCollapsible = ctk.ctkCollapsibleButton()
        self.inputCollapsible.text = "Input"
        self.inputCollapsible.setLayout(inputLayout)

        # Parameters

        ## Parameters stack
        self.fittedCurvesComboBox = qt.QComboBox()
        self.fittedCurvesComboBox.addItem("")
        self.fittedCurvesComboBox.currentTextChanged.connect(self.__onFittedCurveSelected)

        self.parametersStack = qt.QStackedWidget()
        for fitEquation in self.__fitEquations:
            equationWidget = fitEquation.widget.get_widget()
            self.parametersStack.addWidget(equationWidget)
            equationWidget.signal_parameter_changed.connect(self.__onEquationChanged)
            equationWidget.refit_button_pressed.connect(self.__on_refit_button_clicked)

        parametersLayout = qt.QFormLayout()
        parametersLayout.addRow("Fitted curve: ", self.fittedCurvesComboBox)
        parametersLayout.addRow(self.parametersStack)

        self.parametersCollapsible = ctk.ctkCollapsibleButton()
        self.parametersCollapsible.text = "Parameters"
        self.parametersCollapsible.setLayout(parametersLayout)

        self.__selectFitEquation(self.__fitEquations[0].widget.DISPLAY_NAME)

        # Output
        self.__saveButton = qt.QPushButton("Save to project")
        self.__saveButton.setFocusPolicy(qt.Qt.NoFocus)
        self.__saveButton.clicked.connect(self.__onFitSaveButtonClicked)

        outputLayout = qt.QFormLayout()
        outputLayout.addRow("", self.__saveButton)

        outputCollapsible = ctk.ctkCollapsibleButton()
        outputCollapsible.text = "Output: "
        outputCollapsible.setLayout(outputLayout)

        # Layout
        fitTabLayout = qt.QVBoxLayout()
        fitTabLayout.addWidget(self.inputCollapsible)
        fitTabLayout.addWidget(self.parametersCollapsible)
        fitTabLayout.addWidget(outputCollapsible)
        fitTabLayout.addStretch()

        self.__fitTabWidget = qt.QFrame()
        self.__fitTabWidget.setLayout(fitTabLayout)
        return self.__fitTabWidget

    def __selectFitEquation(self, selected_equation):
        self.fittedCurvesComboBox.setCurrentText("")

        for index, fitEquation in enumerate(self.__fitEquations):
            if fitEquation.widget.DISPLAY_NAME == selected_equation:
                self.__setCurrentParametersStack(index)
                break

    def __setCurrentParametersStack(self, index):
        self.parametersStack.setCurrentIndex(index)
        self.parametersCollapsible.setMaximumHeight(125 + 50 * len(self.__fitEquations[index].widget.PARAMETERS))

    def __onFittedCurveSelected(self, fittedCurve):
        self.__validFittedCurveSelected = False
        if not fittedCurve:
            self.__setCurrentFittedCurve(None)
        for fitData in self.__fitDataList:
            if fitData.name == fittedCurve:
                self.__setCurrentFittedCurve(fitData)
                self.__validFittedCurveSelected = True
                break
        self.__updateRefitButtonState()
        self.__updateOutputButtonState()

    def __onFitClicked(self):
        inputData = self.__getCurrentInputData()
        if inputData is None:
            return

        for fitEquation in self.__fitEquations:
            if self.__fitEquationComboBox.currentText == fitEquation.widget.DISPLAY_NAME:
                fitData = fitEquation.equation.fit(
                    self.__fitDataInputComboBox.currentText, inputData["x"], inputData["y"]
                )
                break
        fitData.style.color = inputData["color"]
        self.__addFitData(fitData)

    def __onImportClicked(self):
        fileDialog = qt.QFileDialog(self.__fitTabWidget, "Select function")
        fileDialog.setNameFilters(["Table file (*.tsv)"])
        if fileDialog.exec():
            paths = fileDialog.selectedFiles()
            importedVolume = slicer.util.loadTable(paths[0])
            if importedVolume.GetColumnName(0) != "Fitting equation":
                slicer.mrmlScene.RemoveNode(importedVolume)
                slicer.util.errorDisplay("Couldn't import the file as a fitted function", parent=self.__fitTabWidget)
            else:
                importedVolume.SetAttribute("table_type", "equation")
                self.appendData(importedVolume)

        fileDialog.delete()

    def __onExportClicked(self, functionCurveName):
        fitData = self.__getFitData(functionCurveName)
        path = qt.QFileDialog.getSaveFileName(
            None, "Save file", f"{functionCurveName}.tsv", "Tab-separated values (*.tsv)"
        )
        if path:
            for fitEquation in self.__fitEquations:
                if fitData.type == fitEquation.equation.NAME:
                    df = fitEquation.equation.to_df(fitData)
                    df.to_csv(path, sep="\t", index=False)
                    break

    def __onEquationChanged(self, parameterName: str, newValue: float, isFixed: bool):
        fitData = self.__getCurrentFitData()
        if not fitData:
            return

        if isFixed:
            fixed_parameters = fitData.fixed_parameters
            if parameterName not in fixed_parameters:
                fixed_parameters.append(parameterName)
                fitData.fixed_parameters = fixed_parameters
        self.__updateFunctionCurve(fitData, parameterName, newValue)
        self.__setCurrentFunctionCurveData(fitData)

    def __onFunctionCurveEdited(self, function_curve: str, parameterName: str, newValue: float):
        fitData = self.__getFitData(function_curve)
        if not fitData:
            return
        self.__updateFunctionCurve(fitData, parameterName, newValue)
        self.__setCurrentFunctionCurveData(fitData)

    def __updateFunctionCurve(self, fitData: FitData, parameterName: str, newValue: float):
        fitData.set_parameter(parameterName, newValue)
        for fitEquation in self.__fitEquations:
            if fitData.type == fitEquation.equation.NAME:
                fitData.y = fitEquation.equation.equation(fitData.x, fitData.parameters)
                break
        self.__updatePlot()

    def __setCurrentFittedCurve(self, fitData):
        if fitData is None:
            for fitEquation in self.__fitEquations:
                fitEquation.widget.clear()
            return

        for index, fitEquation in enumerate(self.__fitEquations):
            if fitEquation.equation.NAME == fitData.type:
                fitEquation.widget.update(fitData)
                self.__setCurrentParametersStack(index)
                return

    def __setCurrentFunctionCurveData(self, fitData: FitData):
        self.__setCurrentFittedCurve(fitData)
        self.equationsTab.setCurrentFunctionCurveData(fitData)

    def __on_refit_button_clicked(self):
        fitData = self.__getCurrentFitData()
        inputData = self.__getCurrentInputData()
        for fitEquation in self.__fitEquations:
            if fitEquation.equation.NAME == fitData.type:
                fixedValues = fitEquation.widget.get_fixed_values()
                customBounds = fitEquation.widget.get_custom_bounds()
                if None not in fixedValues:
                    slicer.util.errorDisplay(
                        "All values are fixed. There's no refit to be made.", parent=self.__fitTabWidget
                    )
                    return
                newFitData = fitEquation.equation.fit(
                    fitData.name, inputData["x"], inputData["y"], fixedValues, customBounds
                )
        newFitData.style.color = inputData["color"]
        newFitData.style.size = 1
        self.__addFitData(newFitData)

    def __update_fitted_curves_plot(self):
        for fitData in self.__fitDataList:
            if fitData.visible:
                self.dataPlotWidget.add_curve_plot(fitData)

    def appendData(self, dataNode: slicer.vtkMRMLNode):
        if dataNode.GetAttribute("table_type") == "equation":
            self.__addEquationDataFromTable(dataNode)
        else:
            self.appendDataNode(dataNode)

    def appendDataNode(self, dataNode: slicer.vtkMRMLNode):
        """Store and parse node's data. Each data will be available at the table's widget as well.

        Args:
            dataNode (slicer.vtkMRMLNode): the slicer's node object.
        """
        graphData = NodeGraphData(self, dataNode, plot_type=SCATTER_PLOT_TYPE)
        if graphData in self.__graphDataList:
            return

        if len(graphData.data) <= 0:
            raise RuntimeError(
                "The data from '{}' is not valid for plotting. Please select another input data.".format(
                    graphData.node.GetName()
                )
            )

        graphData.signalVisibleChanged.connect(lambda is_visible: self.__updatePlot())
        graphData.signalModified.connect(self.__updatePlot)
        graphData.signalRemoved.connect(lambda: self.__removeGraphDataFromTable(graphData))

        # store GraphData object
        self.__graphDataList.append(graphData)

        # append parameters and data to combo boxes
        self.__updateAxisComboBoxes()
        self.__updateCurveFittingComboBoxes()

        # Updata graph data table
        self.__updateGraphDataTable()

    def __updateAxisComboBoxes(self):
        """Update axis combo boxes with the existent data's parameters"""
        parametersSet = set()
        for graphData in self.__graphDataList:
            df = graphData.df().select_dtypes(include=[np.number])
            parametersSet.update(df.columns)

        # add empty parameter option
        parameters = [AXIS_NONE_PARAMETER] + list(parametersSet)
        parameters.sort()

        # store old axis selections
        currentXAxis = self.__xAxisComboBox.currentText()
        currentYAxis = self.__yAxisComboBox.currentText()
        currentZAxis = self.__zAxisComboBox.currentText()

        # update available parameters
        self.__xAxisComboBox.clear()
        self.__yAxisComboBox.clear()
        self.__zAxisComboBox.clear()
        self.__xAxisComboBox.addItems(parameters)
        self.__yAxisComboBox.addItems(parameters)
        self.__zAxisComboBox.addItems(parameters)

        # restore old axis selections
        self.__xAxisComboBox.setCurrentText(currentXAxis)
        self.__yAxisComboBox.setCurrentText(currentYAxis)
        self.__zAxisComboBox.setCurrentText(currentZAxis)

    def __updateCurveFittingComboBoxes(self):
        current_data_input = self.__fitDataInputComboBox.currentText
        self.__fitDataInputComboBox.clear()
        self.fittedCurvesComboBox.clear()

        self.fittedCurvesComboBox.addItem("")

        for graph_data in self.__graphDataList:
            self.__fitDataInputComboBox.addItem(graph_data.name)

        functionCurveNames = []
        for fitData in self.__fitDataList:
            functionCurveNames.append(fitData.name)
        self.fittedCurvesComboBox.addItems(functionCurveNames)
        self.equationsTab.setFunctionsCurves(functionCurveNames)

        if current_data_input:
            self.__fitDataInputComboBox.setCurrentText(current_data_input)

    def __createPlotUpdateTimer(self):
        """Initialize timer object that process data to plot"""
        if hasattr(self, "plotUpdateTimer") and self.plotUpdateTimer is not None:
            self.plotUpdateTimer.deleteLater()
            self.plotUpdateTimer = None

        self.plotUpdateTimer = QtCore.QTimer()
        self.plotUpdateTimer.setSingleShot(True)
        self.plotUpdateTimer.timeout.connect(lambda: self.__handleUpdatePlot())
        self.plotUpdateTimer.setInterval(PLOT_UPDATE_TIMER_INTERVAL_MS)

    def __updatePlot(self):
        """Handler update plot timer start."""
        if self.plotUpdateTimer.isActive():
            self.plotUpdateTimer.stop()

        self.plotUpdateTimer.start()

    def __handleUpdatePlot(self):
        """Wrapper for updating the plots related to the user's input (2D or 3D plot)"""
        self.dataPlotWidget.clear_plot()

        if (
            self.__xAxisComboBox.currentText() != AXIS_NONE_PARAMETER
            and self.__yAxisComboBox.currentText() != AXIS_NONE_PARAMETER
        ):
            if self.__zAxisComboBox.currentText() == AXIS_NONE_PARAMETER:
                self.__update2dPlot(
                    self.__xAxisComboBox.currentText(),
                    self.__yAxisComboBox.currentText(),
                    self.__graphDataList,
                )
            else:
                self.__update3dPlot(
                    self.__xAxisComboBox.currentText(),
                    self.__yAxisComboBox.currentText(),
                    self.__zAxisComboBox.currentText(),
                    self.__graphDataList,
                )

            self.__plotHistograms()

        self.__updatePlotsLayout()
        self.__update_fitted_curves_plot()
        self.dataPlotWidget.auto_range()

    def __update2dPlot(self, xAxisParameter, yAxisParameter, graph_data_list):
        """Handles 2D plot updates"""
        self.__updateLogMode()

        for graphData in graph_data_list:
            if graphData.visible is False:
                continue

            xData = graphData.data.get(xAxisParameter, None)
            yData = graphData.data.get(yAxisParameter, None)

            if xData is None or yData is None:
                continue

            xAxisName = xAxisParameter
            yAxisName = yAxisParameter

            if self.__xUnitConversion.isActive():
                xData = self.__xUnitConversion.convert(xData)
                xAxisName = xAxisName.split()[0] + f" ({self.__xUnitConversion.currentUnits()[1]})"

            if self.__yUnitConversion.isActive():
                yData = self.__yUnitConversion.convert(yData)
                yAxisName = yAxisName.split()[0] + f" ({self.__yUnitConversion.currentUnits()[1]})"

            self.dataPlotWidget.add2dPlot(graphData, xData, yData, xAxisName, yAxisName)

    def __update3dPlot(self, xAxisParameter, yAxisParameter, zAxisParameter, graph_data_list):
        """Handles 3D plot updates"""
        self.__updateLogMode()

        enabled_graph_data_list = []

        # Define max/min value for Z Axis
        zMin = None
        zMax = None
        for graphData in graph_data_list:
            if graphData.visible is False:
                continue

            xData = graphData.data.get(xAxisParameter, None)
            yData = graphData.data.get(yAxisParameter, None)
            zData = graphData.data.get(zAxisParameter, None)

            if xData is None or yData is None or zData is None:
                continue

            zData = self.__zUnitConversion.convert(zData)

            # Define Z range value
            min_ = np.nanmin(zData)
            if zMin is None or zMin > min_:
                zMin = min_
            max_ = np.nanmax(zData)
            if zMax is None or zMax < max_:
                zMax = max_

            enabled_graph_data_list.append(graphData)

        ## Calculate global zMin and zMax before start plotting things

        if (
            zMin is not None
            and zMax is not None
            and self.__autoRangeCheckBox.isChecked() is False
            and self.__hasValidZAxisRange() is True
        ):
            zMin = max(zMin, self.__zMinValueRange)
            zMax = min(zMax, self.__zMaxValueRange)
        elif self.__autoRangeCheckBox.isChecked() is True:
            self.__ZMinValueRangeDoubleSpinBox.setValue(zMin or 0)
            self.__ZMaxValueRangeDoubleSpinBox.setValue(zMax or 0)

        # Plot
        zAxisName = ""
        for graphData in enabled_graph_data_list:
            xData = graphData.data.get(xAxisParameter, None)
            yData = graphData.data.get(yAxisParameter, None)
            zData = graphData.data.get(zAxisParameter, None)

            xAxisName = xAxisParameter
            yAxisName = yAxisParameter
            zAxisName = zAxisParameter

            if self.__xUnitConversion.isActive():
                xData = self.__xUnitConversion.convert(xData)
                xAxisName = xAxisName.split()[0] + f" ({self.__xUnitConversion.currentUnits()[1]})"
            if self.__yUnitConversion.isActive():
                yData = self.__yUnitConversion.convert(yData)
                yAxisName = yAxisName.split()[0] + f" ({self.__yUnitConversion.currentUnits()[1]})"
            if self.__zUnitConversion.isActive():
                zData = self.__zUnitConversion.convert(zData)
                zAxisName = zAxisName.split()[0] + f" ({self.__zUnitConversion.currentUnits()[1]})"

            self.dataPlotWidget.add3dPlot(graphData, xData, yData, zData, xAxisName, yAxisName, zAxisName, zMin, zMax)

        self.dataPlotWidget.update_legend_item(zAxisName)

    def __updateGraphDataTable(self):
        """Handles table widget data update"""
        self.__tableWidget.clear()

        for graphData in self.__graphDataList:
            self.__tableWidget.add_data(graphData, DataTableWidget.INPUT_DATA_TYPE)

        for fitData in self.__fitDataList:
            self.__tableWidget.add_data(fitData, DataTableWidget.FIT_DATA_TYPE)

    def __removeGraphDataFromTable(self, graphData: NodeGraphData):
        """Remove data and objects related to the GraphData object."""
        if not graphData in self.__graphDataList:
            return

        self.__graphDataList.remove(graphData)
        self.__updateGraphDataTable()
        self.__updateAxisComboBoxes()
        self.__updateCurveFittingComboBoxes()
        self.__updatePlot()

    def __removeFitDataFromTable(self, fitData: FitData):
        """Remove data and objects related to the FitData object."""
        if not fitData in self.__fitDataList:
            return

        self.__fitDataList.remove(fitData)
        self.__updateGraphDataTable()
        self.__updatePlot()

    def __removeDataFromTableByName(self, name):
        for graph_data in self.__graphDataList:
            if graph_data.name == name:
                self.__removeGraphDataFromTable(graph_data)
                return

        for fitData in self.__fitDataList:
            if fitData.name == name:
                self.__removeFitDataFromTable(fitData)
                return

    def __populateColorMapComboBox(self):
        """Initialize color map combo box options."""
        for colorMapInfo in CrossplotColorMaps:
            self.__colorMapComboBox.addItem(QtGui.QIcon(colorMapInfo.reference_image), colorMapInfo.label)

        self.__colorMapComboBox.setCurrentText("Gist Rainbow")
        self.dataPlotWidget.set_colormap(matplotlibcm.gist_rainbow.name)

    def __onColorMapComboBoxChanged(self, text):
        """Handles color map combo box options change event."""
        for colorMapInfo in CrossplotColorMaps:
            if text != colorMapInfo.label:
                continue

            self.dataPlotWidget.set_colormap(colorMapInfo.object.name)
            self.__updatePlot()
            break

    def __onAutoRangeCheckBoxChanged(self, state):
        """Handle auto range check box change event."""
        is_auto_range = bool(state)
        self.__ZMaxValueRangeDoubleSpinBox.setEnabled(not is_auto_range)
        self.__ZMinValueRangeDoubleSpinBox.setEnabled(not is_auto_range)
        self.__updatePlot()

    def __onZMinValueRangeChanged(self, value):
        """Handles minimum range value options change event."""
        if value == self.__zMinValueRange:
            return

        self.__zMinValueRange = value

        if not self.__autoRangeCheckBox.isChecked() is True and self.__hasValidZAxisRange():
            self.__updatePlot()

    def __onZMaxValueRangeChanged(self, value):
        """Handles maximum range value options change event."""
        if value == self.__zMaxValueRange:
            return

        self.__zMaxValueRange = value

        if not self.__autoRangeCheckBox.isChecked() is True and self.__hasValidZAxisRange():
            self.__updatePlot()

    def __hasValidZAxisRange(self):
        """Check if axis range values are considered valid

        Returns:
            bool: True if ranges are valid. Otherwise, returns False.
        """
        return (
            self.__zMinValueRange is not None
            and self.__zMaxValueRange is not None
            and self.__zMinValueRange < self.__zMaxValueRange
        )

    def __plotHistograms(self):
        self.dataPlotWidget.clear_histogram_x()
        self.dataPlotWidget.clear_histogram_y()

        if (
            self.__xAxisHistogramEnableCheckBox.isChecked() is False
            and self.__yAxisHistogramEnableCheckBox.isChecked() is False
        ):
            return

        xAxisParameter = self.__xAxisComboBox.currentText()
        yAxisParameter = self.__yAxisComboBox.currentText()

        def createHistogramPlots(graphData, axisParameter, bins):
            if graphData.visible is False:
                return None, None

            data = graphData.data.get(axisParameter, None)
            if data is None:
                return None, None

            data = data[~np.isnan(data)]
            data = (
                self.__xUnitConversion.convert(data)
                if axisParameter == xAxisParameter
                else self.__yUnitConversion.convert(data)
            )
            yHistogram, xHistogram = np.histogram(data, bins=bins)

            # Create brush
            return xHistogram, yHistogram

        if self.__xAxisHistogramEnableCheckBox.isChecked() is True:
            for graphData in self.__graphDataList:
                xHistogram, yHistogram = createHistogramPlots(
                    graphData, xAxisParameter, self.__xHistogramBinSpinBox.value()
                )
                if xHistogram is not None and yHistogram is not None:
                    self.dataPlotWidget.add_histogram_plot_x(graphData, xHistogram, yHistogram)

        if self.__yAxisHistogramEnableCheckBox.isChecked() is True:
            for graphData in self.__graphDataList:
                xHistogram, yHistogram = createHistogramPlots(
                    graphData, yAxisParameter, self.__yHistogramBinSpinBox.value()
                )
                if xHistogram is not None and yHistogram is not None:
                    self.dataPlotWidget.add_histogram_plot_y(graphData, xHistogram, yHistogram)

    def __onHistogramCheckBoxChange(self, state):
        if self.__xAxisHistogramEnableCheckBox.isChecked() is False:
            self.dataPlotWidget.clear_histogram_x()

        if self.__yAxisHistogramEnableCheckBox.isChecked() is False:
            self.dataPlotWidget.clear_histogram_y()

        self.__updatePlot()

    def __onLogCheckBoxChange(self, state):
        self.__updatePlot()

    def __onHistogramBinChange(self, value):
        self.__updatePlot()

    def __updateLogMode(self):
        self.dataPlotWidget.set_log_mode(x=self.__xLogCheckBox.isChecked(), y=self.__yLogCheckBox.isChecked())

    def __updatePlotsLayout(self):
        self.dataPlotWidget.set_theme(self.__themeComboBox.currentText())
        self.dataPlotWidget._updatePlotsLayout(
            self.__xAxisHistogramEnableCheckBox.isChecked(),
            self.__yAxisHistogramEnableCheckBox.isChecked(),
            self.__zAxisComboBox.currentText(),
        )

    def __updateRefitButtonState(self):
        for fitEquation in self.__fitEquations:
            fitEquation.widget.update_refit_button_state(self.__validFittedCurveSelected)

    def __updateOutputButtonState(self):
        self.__saveButton.enabled = self.__validFittedCurveSelected

    def __onFitSaveButtonClicked(self):
        fitData = self.__getCurrentFitData()
        if fitData is None:
            return

        self.__saveDataToNode(fitData, fitData.name)

    def __on_function_curve_save_button_clicked(self, functionCurveName):
        fitData = self.__getFitData(functionCurveName)
        self.__saveDataToNode(fitData, functionCurveName)

    def __saveDataToNode(self, fitData, new_name):
        tableNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__)
        tableNode.SetName(slicer.mrmlScene.GenerateUniqueName(new_name))

        table_modification = tableNode.StartModify()

        columnFittingEquation = vtk.vtkStringArray()
        columnFittingEquation.SetName("Fitting equation")
        columnFittingEquation.InsertNextValue(fitData.type)
        tableNode.AddColumn(columnFittingEquation)

        for fitEquation in self.__fitEquations:
            if fitEquation.equation.NAME == fitData.type:
                fitEquation.equation.append_to_node(fitData, tableNode)
                break

        tableNode.SetAttribute("table_type", "equation")
        tableNode.Modified()
        tableNode.EndModify(table_modification)

        outputDirName = "Math functions"
        subjectHierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        appFolderId = subjectHierarchy.GetSceneItemID()
        outputDir = subjectHierarchy.GetItemChildWithName(appFolderId, outputDirName)
        if outputDir == 0:
            outputDir = subjectHierarchy.CreateFolderItem(
                appFolderId, helpers.generateName(subjectHierarchy, outputDirName)
            )
        subjectHierarchy.CreateItem(outputDir, tableNode)

        fitData.name = new_name
        self.__updateCurveFittingComboBoxes()
        self.__updateGraphDataTable()

    def __addEquationDataFromTable(self, tableNode):
        vtkTable = tableNode.GetTable()
        equation_type = vtkTable.GetValueByName(0, "Fitting equation")
        for fitEquation in self.__fitEquations:
            if fitEquation.equation.NAME == equation_type:
                fitData = fitEquation.equation.from_table(tableNode.GetName(), vtkTable)
                break
        self.__addFitData(fitData)

    def __onFitDataCreated(self, fitData):
        self.__addFitData(fitData)
        self.__setCurrentFunctionCurveData(fitData)

    def __addFitData(self, newFitData: FitData):
        for fitData in self.__fitDataList:
            if fitData.name == newFitData.name:
                self.__fitDataList.remove(fitData)
                break

        newFitData.style.size = 1
        self.__fitDataList.append(newFitData)
        newFitData.signalVisibleChanged.connect(self.__updatePlot)

        self.__updatePlot()
        self.__updateGraphDataTable()
        self.__updateCurveFittingComboBoxes()
        self.fittedCurvesComboBox.setCurrentText(newFitData.name)

    def __getCurrentFitData(self):
        return self.__getFitData(self.fittedCurvesComboBox.currentText)

    def __getFitData(self, name):
        for fitData in self.__fitDataList:
            if fitData.name == name:
                return fitData
        return None

    def __getCurrentInputData(self):
        try:
            inputData = self.dataPlotWidget.get_plotted_data(self.__fitDataInputComboBox.currentText)
        except KeyError:
            slicer.util.errorDisplay(
                "Nothing related to this data is plotted. "
                "Please assign parameters from this input data in the Data tab or select another one.",
                parent=self.__fitTabWidget,
            )
            return None

        if inputData["x"] is None or inputData["y"] is None:
            slicer.util.errorDisplay(
                "Missing 2D data. You must select data for X and Y axes before fitting to the equation.",
                parent=self.__fitTabWidget,
            )
            return None

        return inputData

    def __updateAllDataStyles(self, symbol, symbol_size, line_style, line_size):
        for graphData in self.__graphDataList:
            if symbol != NO_CHANGE:
                graphData.style.symbol = TEXT_SYMBOLS[symbol]
            if symbol_size > 0:
                graphData.style.size = symbol_size
            if line_style != NO_CHANGE:
                graphData.style.line_style = LINE_STYLES[line_style]
            if line_size > 0:
                graphData.style.line_size = line_size

        self.__updatePlot()
        self.__updateGraphDataTable()

    def __updateAllDataVisibility(self, visibility_state):
        for graphData in self.__graphDataList:
            graphData.visible = visibility_state

        self.__updateGraphDataTable()

    def __onEmbeddedLegendVisibilityChange(self, state):
        if not self.dataPlotWidget:
            return

        self.dataPlotWidget.embeddedLegendVisibility = state == qt.Qt.Checked

    def __toggleLegend(self):
        self.__embeddedLegendVisibilityCheckBox.setChecked(self.dataPlotWidget.embeddedLegendVisibility)


class EquationParametersWidget(qt.QFrame):
    signalFunctionCurveSelected = qt.Signal(str)
    signalFunctionCurveEdited = qt.Signal(str, str, float, bool)

    def __init__(self):
        super().__init__()

        self.__fitEquations = [Line(False), TimurCoates(False)]

        self.functionCurvesComboBox = qt.QComboBox()
        self.functionCurvesComboBox.addItem("")
        self.functionCurvesComboBox.currentTextChanged.connect(self.__onFunctionCurveSelected)

        self.parametersStack = ShrinkableStackedWidget()
        for fitEquation in self.__fitEquations:
            equationWidget = fitEquation.widget.get_widget()
            self.parametersStack.addWidget(equationWidget)
            equationWidget.signal_parameter_changed.connect(self.__onEquationChanged)
        self.parametersStack.setCurrentIndex(0)

        editLayout = qt.QFormLayout()
        editLayout.setContentsMargins(0, 0, 0, 0)
        editLayout.addRow("Function:", self.functionCurvesComboBox)
        editLayout.addRow(self.parametersStack)

        self.parametersCollapsible = ctk.ctkCollapsibleButton(self)
        self.parametersCollapsible.text = "Parameters"
        self.parametersCollapsible.setLayout(editLayout)

        layout = qt.QVBoxLayout()
        layout.addWidget(self.parametersCollapsible)
        self.setLayout(layout)

    def setFunctionsCurves(self, function_curve_list: list):
        self.functionCurvesComboBox.clear()
        self.functionCurvesComboBox.addItem("")
        self.functionCurvesComboBox.addItems(function_curve_list)

    def setCurrentFunctionCurveData(self, curve_data):
        if curve_data is None:
            for fitEquation in self.__fitEquations:
                fitEquation.widget.clear()
            return

        for index, fitEquation in enumerate(self.__fitEquations):
            if fitEquation.equation.NAME == curve_data.type:
                fitEquation.widget.update(curve_data)
                self.__setCurrentParametersStack(index)
                self.functionCurvesComboBox.setCurrentText(curve_data.name)
                break

    def getCurrentFunctionCurveName(self):
        return self.functionCurvesComboBox.currentText

    def __onFunctionCurveSelected(self, function_curve):
        self.signalFunctionCurveSelected.emit(function_curve)

    def __setCurrentParametersStack(self, index):
        self.parametersStack.setCurrentIndex(index)

    def __onEquationChanged(self, parameterName, newValue, isFixed):
        function_curve = self.functionCurvesComboBox.currentText
        self.signalFunctionCurveEdited.emit(function_curve, parameterName, newValue, isFixed)


class EquationsTabWidget(qt.QFrame):
    signalNewFunctionCurveData = qt.Signal(FitData)
    signalImportFunctionCurve = qt.Signal()
    signalExportFunctionCurve = qt.Signal(str)
    signalFunctionCurveEdited = qt.Signal(str, str, float)
    signalSaveData = qt.Signal(str)

    def __init__(self, fit_data_list):
        super().__init__()

        self.__fitDataList = fit_data_list

        # Input layout
        self.__functionCurveNameLineEdit = qt.QLineEdit()

        self.__fitEquationComboBox = qt.QComboBox()
        self.__fitEquations = [Line(False), TimurCoates(False)]
        for fitEquation in self.__fitEquations:
            self.__fitEquationComboBox.addItem(fitEquation.widget.DISPLAY_NAME)

        createButton = qt.QPushButton("Create")
        createButton.setFocusPolicy(qt.Qt.NoFocus)
        createButton.clicked.connect(self.__onCreateClicked)
        importButton = qt.QPushButton("Import")
        importButton.setFocusPolicy(qt.Qt.NoFocus)
        importButton.clicked.connect(self.__onImportClicked)

        inputButtonLayout = qt.QHBoxLayout()
        inputButtonLayout.addWidget(createButton)
        inputButtonLayout.addWidget(importButton)

        inputLayout = qt.QFormLayout()
        inputLayout.addRow("Name:", self.__functionCurveNameLineEdit)
        inputLayout.addRow("Equation:", self.__fitEquationComboBox)
        inputLayout.addRow("", inputButtonLayout)

        inputCollapsible = ctk.ctkCollapsibleButton()
        inputCollapsible.text = "Input"
        inputCollapsible.setLayout(inputLayout)

        # Edit layout
        self.editCollapsible = EquationParametersWidget()
        self.editCollapsible.signalFunctionCurveSelected.connect(self.__onFunctionCurveSelected)
        self.editCollapsible.signalFunctionCurveEdited.connect(self.__onFunctionCurveEdited)

        # Output layout

        self.__saveButton = qt.QPushButton("Save to project")
        self.__saveButton.setFocusPolicy(qt.Qt.NoFocus)
        self.__saveButton.clicked.connect(self.__on_save_button_clicked)
        self.__exportButton = qt.QPushButton("Export to file")
        self.__exportButton.setFocusPolicy(qt.Qt.NoFocus)
        self.__exportButton.clicked.connect(self.__onExportClicked)

        outputLayout = qt.QHBoxLayout()
        outputLayout.addWidget(self.__saveButton)
        outputLayout.addWidget(self.__exportButton)

        outputCollapsible = ctk.ctkCollapsibleButton()
        outputCollapsible.text = "Output"
        outputCollapsible.setLayout(outputLayout)

        # Equations tab
        equations_tab_layout = qt.QVBoxLayout()
        equations_tab_layout.addWidget(inputCollapsible)
        equations_tab_layout.addWidget(self.editCollapsible)
        equations_tab_layout.addWidget(outputCollapsible)
        equations_tab_layout.addStretch()

        self.setLayout(equations_tab_layout)

        self.__onFunctionCurveSelected("")

    def setFunctionsCurves(self, function_curve_list: list):
        self.editCollapsible.setFunctionsCurves(function_curve_list)

    def setCurrentFunctionCurveData(self, curve_data):
        self.editCollapsible.setCurrentFunctionCurveData(curve_data)

    def __onFunctionCurveSelected(self, function_curve):
        self.editCollapsible.setCurrentFunctionCurveData(None)
        for fitData in self.__fitDataList:
            if fitData.name == function_curve:
                self.editCollapsible.setCurrentFunctionCurveData(fitData)
                break
        self.__updateOutputButtonState()

    def __onCreateClicked(self):
        functionCurveName = self.__functionCurveNameLineEdit.text
        if functionCurveName == "":
            return
        for fitEquation in self.__fitEquations:
            if fitEquation.widget.DISPLAY_NAME == self.__fitEquationComboBox.currentText:
                fitData = fitEquation.equation.create_default(functionCurveName)
                self.signalNewFunctionCurveData.emit(fitData)
                break

    def __onImportClicked(self):
        self.signalImportFunctionCurve.emit()

    def __onExportClicked(self):
        functionCurveName = self.editCollapsible.getCurrentFunctionCurveName()
        self.signalExportFunctionCurve.emit(functionCurveName)

    def __onFunctionCurveEdited(self, function_curve, parameterName, newValue, isFixed):
        self.signalFunctionCurveEdited.emit(function_curve, parameterName, newValue)

    def __on_save_button_clicked(self):
        functionCurveName = self.editCollapsible.getCurrentFunctionCurveName()
        self.signalSaveData.emit(functionCurveName)

    def __updateOutputButtonState(self):
        validFunctionCurve = False
        functionCurveName = self.editCollapsible.getCurrentFunctionCurveName()
        if functionCurveName:
            for fitData in self.__fitDataList:
                if fitData.name == functionCurveName:
                    validFunctionCurve = True
                    break
        self.__saveButton.enabled = validFunctionCurve
        self.__exportButton.enabled = validFunctionCurve


class ShrinkableStackedWidget(qt.QFrame):
    """A StackedWidget that reduces it's weight according to the current selected widget."""

    def __init__(self):
        super().__init__()
        self.widgetList = []
        self.mainLayout = qt.QVBoxLayout()
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.mainLayout)

    def setCurrentIndex(self, index):
        for i, widget in enumerate(self.widgetList):
            if i == index:
                widget.setVisible(True)
            else:
                widget.setVisible(False)

    def addWidget(self, widget):
        self.widgetList.append(widget)
        self.mainLayout.addWidget(widget)
