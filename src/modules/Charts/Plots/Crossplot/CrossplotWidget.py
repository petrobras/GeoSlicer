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
from ltrace.slicer.widget.help_button import HelpButton
from matplotlib import cm as matplotlibcm
from pint import Unit, UndefinedUnitError, DefinitionSyntaxError
from pint_pandas import PintArray
from Plots.BasePlotWidget import BasePlotWidget
from Plots.Crossplot.data_table_widget import DataTableWidget
from Plots.Crossplot.data_plot_widget import DataPlotWidget
from Plots.Crossplot.equations.line import Line
from Plots.Crossplot.equations.timur_coates import TimurCoates
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

    def __init__(self):
        super().__init__()
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
        self.__graphDataList = list()
        self.__zMinValueRange = 0
        self.__zMaxValueRange = 0
        self.__createPlotUpdateTimer()
        self.__fit_data_list = []
        self.__valid_fitted_curve_selected = False

        self.__fit_equations = [Line(), TimurCoates()]

    def setupUi(self):
        """Initialize widgets"""
        self.setMinimumSize(780, 600)
        layout = QtGui.QHBoxLayout()

        parameters_widget = QtGui.QFrame()
        parameters_layout = QtGui.QVBoxLayout()
        parameters_widget.setLayout(parameters_layout)
        plot_layout = QtGui.QVBoxLayout()

        # Data table widget
        self.__tableWidget = DataTableWidget()
        self.__tableWidget.signal_style_changed.connect(self.__updatePlot)
        self.__tableWidget.signal_data_removed.connect(self.__removeDataFromTableByName)
        self.__tableWidget.signal_all_style_changed.connect(self.__updateAllDataStyles)
        self.__tableWidget.signal_all_visible_changed.connect(self.__updateAllDataVisibility)
        parameters_layout.addWidget(self.__tableWidget)

        # Plot widget
        self.data_plot_widget = DataPlotWidget()
        plot_layout.addWidget(self.data_plot_widget.widget)

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
        xAxisParameterLayout = QtGui.QFormLayout()
        xAxisParameterLayout.addRow("Parameter", self.__xAxisComboBox)
        xAxisParameterLayout.setHorizontalSpacing(8)

        # Layout
        self.__xAxisGridLayout = QtGui.QGridLayout()
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
        self.__xAxisGroupBox = QtGui.QGroupBox("X axis")
        self.__xAxisGroupBox.setLayout(self.__xAxisGridLayout)

        parameters_layout.addWidget(self.__xAxisGroupBox)

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
        yAxisParameterLayout = QtGui.QFormLayout()
        yAxisParameterLayout.addRow("Parameter", self.__yAxisComboBox)
        yAxisParameterLayout.setHorizontalSpacing(8)

        # Layout
        self.__yAxisGridLayout = QtGui.QGridLayout()
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
        self.__yAxisGroupBox = QtGui.QGroupBox("Y axis")
        self.__yAxisGroupBox.setLayout(self.__yAxisGridLayout)

        parameters_layout.addWidget(self.__yAxisGroupBox)

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

        self.__zUnitConversion = UnitConversionWidget()

        # Manual/Auto range widgets layout
        range_layout = QtGui.QHBoxLayout()
        range_layout.setSpacing(5)
        auto_range_layout = QtGui.QHBoxLayout()
        auto_range_layout.setSpacing(5)
        auto_range_layout.addWidget(QtGui.QLabel("Auto Range"))
        auto_range_layout.addWidget(self.__autoRangeCheckBox)
        range_layout.addLayout(auto_range_layout)
        minimum_layout = QtGui.QHBoxLayout()
        minimum_layout.setSpacing(5)
        minimum_layout.addWidget(QtGui.QLabel("Min"))
        minimum_layout.addWidget(self.__ZMinValueRangeDoubleSpinBox)
        range_layout.addLayout(minimum_layout)
        maximum_layout = QtGui.QHBoxLayout()
        maximum_layout.setSpacing(5)
        maximum_layout.addWidget(QtGui.QLabel("Max"))
        maximum_layout.addWidget(self.__ZMaxValueRangeDoubleSpinBox)
        range_layout.addLayout(maximum_layout)

        formLayout = QtGui.QFormLayout()
        formLayout.addRow("Parameter", self.__zAxisComboBox)
        formLayout.addRow(range_layout)
        formLayout.addRow("Color map", self.__colorMapComboBox)
        formLayout.addRow(shiboken2.wrapInstance(hash(self.__zUnitConversion), QtGui.QWidget))

        zStyleGroupBox = QtGui.QGroupBox("Z axis")
        zStyleGroupBox.setLayout(formLayout)

        parameters_layout.addWidget(zStyleGroupBox)

        # Theme
        self.__themeGroupBox = QtGui.QGroupBox("Theme settings")
        self.__themeComboBox = QtGui.QComboBox()
        themeParameterLayout = QtGui.QFormLayout()
        themeParameterLayout.setHorizontalSpacing(8)
        themeParameterLayout.addRow("Theme", self.__themeComboBox)
        for themeName in self.data_plot_widget.themes:
            self.__themeComboBox.addItem(themeName)
        self.__themeGroupBox.setLayout(themeParameterLayout)
        parameters_layout.addWidget(self.__themeGroupBox)

        self.__themeComboBox.setCurrentText(self.data_plot_widget.themes[0])

        # Stretch
        parameters_layout.addStretch()

        # Tabs
        tab_widget = QtGui.QTabWidget()
        tab_widget.addTab(parameters_widget, "Data")
        fit_frame_qt = self.__create_fit_tab()
        fit_frame_qtgui = shiboken2.wrapInstance(hash(fit_frame_qt), QtGui.QFrame)
        tab_widget.addTab(fit_frame_qtgui, "Curve fitting")
        self.equations_tab = EquationsTabWidget(self.__fit_data_list)
        self.equations_tab.signal_new_function_curve_data.connect(self.__on_fit_data_created)
        self.equations_tab.signal_import_function_curve.connect(self.__on_import_clicked)
        self.equations_tab.signal_export_function_curve.connect(self.__on_export_clicked)
        self.equations_tab.signal_function_curve_edited.connect(self.__on_function_curve_edited)
        self.equations_tab.signal_save_data.connect(self.__on_function_curve_save_button_clicked)
        equations_tab_qtgui = shiboken2.wrapInstance(hash(self.equations_tab), QtGui.QFrame)
        tab_widget.addTab(equations_tab_qtgui, "Curves")

        shortest_width = min(parameters_widget.sizeHint().width(), fit_frame_qtgui.sizeHint().width())
        parameters_widget.setMaximumWidth(shortest_width)
        fit_frame_qtgui.setMaximumWidth(shortest_width)
        tab_widget.setMaximumWidth(shortest_width)

        # Layout
        layout.addWidget(tab_widget)
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
        self.data_plot_widget.set_theme(self.__themeComboBox.currentText())
        self.__updatePlotsLayout()
        self.__on_fitted_curve_selected("")

    def __create_fit_tab(self):
        ## New fit widget
        self.__fit_data_input_combo_box = qt.QComboBox()

        self.__fit_equation_combo_box = qt.QComboBox()
        for fit_equation in self.__fit_equations:
            self.__fit_equation_combo_box.addItem(fit_equation.widget.DISPLAY_NAME)
        self.__fit_equation_combo_box.currentTextChanged.connect(self.__select_fit_equation)

        fit_button = qt.QPushButton("New fit")
        fit_button.setFocusPolicy(qt.Qt.NoFocus)
        fit_button.clicked.connect(self.__on_fit_clicked)

        fit_buttons_layout = qt.QHBoxLayout()
        fit_buttons_layout.addWidget(fit_button)

        fit_input_layout = qt.QFormLayout()
        fit_input_layout.addRow("Data: ", self.__fit_data_input_combo_box)
        fit_input_layout.addRow("Equation: ", self.__fit_equation_combo_box)
        fit_input_layout.addRow("", fit_buttons_layout)

        fit_input_frame = qt.QFrame()
        fit_input_frame.setLayout(fit_input_layout)

        ## Input layout
        input_layout = qt.QVBoxLayout()
        input_layout.addWidget(fit_input_frame)

        self.input_collapsible = ctk.ctkCollapsibleButton()
        self.input_collapsible.text = "Input"
        self.input_collapsible.setLayout(input_layout)

        # Parameters

        ## Parameters stack
        self.fitted_curves_combobox = qt.QComboBox()
        self.fitted_curves_combobox.addItem("")
        self.fitted_curves_combobox.currentTextChanged.connect(self.__on_fitted_curve_selected)

        self.parameters_stack = qt.QStackedWidget()
        for fit_equation in self.__fit_equations:
            equation_widget = fit_equation.widget.get_widget()
            self.parameters_stack.addWidget(equation_widget)
            equation_widget.signal_parameter_changed.connect(self.__on_equation_changed)
            equation_widget.refit_button_pressed.connect(self.__on_refit_button_clicked)

        parameters_layout = qt.QFormLayout()
        parameters_layout.addRow("Fitted curve: ", self.fitted_curves_combobox)
        parameters_layout.addRow(self.parameters_stack)

        self.parameters_collapsible = ctk.ctkCollapsibleButton()
        self.parameters_collapsible.text = "Parameters"
        self.parameters_collapsible.setLayout(parameters_layout)

        self.__select_fit_equation(self.__fit_equations[0].widget.DISPLAY_NAME)

        # Output
        self.__save_button = qt.QPushButton("Save to project")
        self.__save_button.setFocusPolicy(qt.Qt.NoFocus)
        self.__save_button.clicked.connect(self.__on_fit_save_button_clicked)

        output_layout = qt.QFormLayout()
        output_layout.addRow("", self.__save_button)

        output_collapsible = ctk.ctkCollapsibleButton()
        output_collapsible.text = "Output: "
        output_collapsible.setLayout(output_layout)

        # Layout
        fit_tab_layout = qt.QVBoxLayout()
        fit_tab_layout.addWidget(self.input_collapsible)
        fit_tab_layout.addWidget(self.parameters_collapsible)
        fit_tab_layout.addWidget(output_collapsible)
        fit_tab_layout.addStretch()

        self.__fit_tab_widget = qt.QFrame()
        self.__fit_tab_widget.setLayout(fit_tab_layout)
        return self.__fit_tab_widget

    def __select_fit_equation(self, selected_equation):
        self.fitted_curves_combobox.setCurrentText("")

        for index, fit_equation in enumerate(self.__fit_equations):
            if fit_equation.widget.DISPLAY_NAME == selected_equation:
                self.__set_current_parameters_stack(index)
                break

    def __set_current_parameters_stack(self, index):
        self.parameters_stack.setCurrentIndex(index)
        self.parameters_collapsible.setMaximumHeight(125 + 50 * len(self.__fit_equations[index].widget.PARAMETERS))

    def __on_fitted_curve_selected(self, fitted_curve):
        self.__valid_fitted_curve_selected = False
        if not fitted_curve:
            self.__set_current_fitted_curve(None)
        for fit_data in self.__fit_data_list:
            if fit_data.name == fitted_curve:
                self.__set_current_fitted_curve(fit_data)
                self.__valid_fitted_curve_selected = True
                break
        self.__update_refit_button_state()
        self.__update_output_button_state()

    def __on_fit_clicked(self):
        input_data = self.__get_current_input_data()
        if input_data is None:
            return

        for fit_equation in self.__fit_equations:
            if self.__fit_equation_combo_box.currentText == fit_equation.widget.DISPLAY_NAME:
                fit_data = fit_equation.equation.fit("temp_curve", input_data["x"], input_data["y"])
                break
        fit_data.style.color = input_data["color"]
        self.__add_fit_data(fit_data)

    def __on_import_clicked(self):
        file_dialog = qt.QFileDialog(self.__fit_tab_widget, "Select function")
        file_dialog.setNameFilters(["Table file (*.tsv)"])
        if file_dialog.exec():
            paths = file_dialog.selectedFiles()
            imported_volume = slicer.util.loadTable(paths[0])
            if imported_volume.GetColumnName(0) != "Fitting equation":
                slicer.mrmlScene.RemoveNode(imported_volume)
                slicer.util.errorDisplay("Couldn't import the file as a fitted function", parent=self.__fit_tab_widget)
            else:
                imported_volume.SetAttribute("table_type", "equation")
                self.appendData(imported_volume)

    def __on_export_clicked(self, function_curve_name):
        fit_data = self.__get_fit_data(function_curve_name)
        path = qt.QFileDialog.getSaveFileName(
            None, "Save file", f"{function_curve_name}.tsv", "Tab-separated values (*.tsv)"
        )
        if path:
            for fit_equation in self.__fit_equations:
                if fit_data.type == fit_equation.equation.NAME:
                    df = fit_equation.equation.to_df(fit_data)
                    df.to_csv(path, sep="\t", index=False)
                    break

    def __on_equation_changed(self, parameter_name: str, new_value: float, is_fixed: bool):
        fit_data = self.__get_current_fit_data()
        if not fit_data:
            return

        if is_fixed:
            fixed_parameters = fit_data.fixed_parameters
            if parameter_name not in fixed_parameters:
                fixed_parameters.append(parameter_name)
                fit_data.fixed_parameters = fixed_parameters
        self.__update_function_curve(fit_data, parameter_name, new_value)
        self.__set_current_function_curve_data(fit_data)

    def __on_function_curve_edited(self, function_curve: str, parameter_name: str, new_value: float):
        fit_data = self.__get_fit_data(function_curve)
        if not fit_data:
            return
        self.__update_function_curve(fit_data, parameter_name, new_value)
        self.__set_current_function_curve_data(fit_data)

    def __update_function_curve(self, fit_data: FitData, parameter_name: str, new_value: float):
        fit_data.set_parameter(parameter_name, new_value)
        for fit_equation in self.__fit_equations:
            if fit_data.type == fit_equation.equation.NAME:
                fit_data.y = fit_equation.equation.equation(fit_data.x, fit_data.parameters)
                break
        self.__updatePlot()

    def __set_current_fitted_curve(self, fit_data):
        if fit_data is None:
            for fit_equation in self.__fit_equations:
                fit_equation.widget.clear()
            return

        for index, fit_equation in enumerate(self.__fit_equations):
            if fit_equation.equation.NAME == fit_data.type:
                fit_equation.widget.update(fit_data)
                self.__set_current_parameters_stack(index)
                return

    def __set_current_function_curve_data(self, fit_data: FitData):
        self.__set_current_fitted_curve(fit_data)
        self.equations_tab.set_current_function_curve_data(fit_data)

    def __on_refit_button_clicked(self):
        fit_data = self.__get_current_fit_data()
        input_data = self.__get_current_input_data()
        for fit_equation in self.__fit_equations:
            if fit_equation.equation.NAME == fit_data.type:
                fixed_values = fit_equation.widget.get_fixed_values()
                custom_bounds = fit_equation.widget.get_custom_bounds()
                if None not in fixed_values:
                    slicer.util.errorDisplay(
                        "All values are fixed. There's no refit to be made.", parent=self.__fit_tab_widget
                    )
                    return
                new_fit_data = fit_equation.equation.fit(
                    fit_data.name, input_data["x"], input_data["y"], fixed_values, custom_bounds
                )
        new_fit_data.style.color = input_data["color"]
        new_fit_data.style.size = 1
        self.__add_fit_data(new_fit_data)

    def __update_fitted_curves_plot(self):
        for fit_data in self.__fit_data_list:
            if fit_data.visible:
                self.data_plot_widget.add_curve_plot(fit_data)

    def appendData(self, dataNode: slicer.vtkMRMLNode):
        if dataNode.GetAttribute("table_type") == "equation":
            self.__add_equation_data_from_table(dataNode)
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
        current_data_input = self.__fit_data_input_combo_box.currentText
        self.__fit_data_input_combo_box.clear()
        self.fitted_curves_combobox.clear()

        self.fitted_curves_combobox.addItem("")

        for graph_data in self.__graphDataList:
            self.__fit_data_input_combo_box.addItem(graph_data.name)

        function_curve_names = []
        for fit_data in self.__fit_data_list:
            function_curve_names.append(fit_data.name)
        self.fitted_curves_combobox.addItems(function_curve_names)
        self.equations_tab.set_functions_curves(function_curve_names)

        if current_data_input:
            self.__fit_data_input_combo_box.setCurrentText(current_data_input)

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
        self.data_plot_widget.clear_plot()

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
        self.data_plot_widget.auto_range()

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

            self.data_plot_widget.add2dPlot(graphData, xData, yData, xAxisName, yAxisName)

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

            self.data_plot_widget.add3dPlot(graphData, xData, yData, zData, xAxisName, yAxisName, zAxisName, zMin, zMax)

        self.data_plot_widget.update_legend_item(zAxisName)

    def __updateGraphDataTable(self):
        """Handles table widget data update"""
        self.__tableWidget.clear()

        for graphData in self.__graphDataList:
            self.__tableWidget.add_data(graphData, DataTableWidget.INPUT_DATA_TYPE)

        for fit_data in self.__fit_data_list:
            self.__tableWidget.add_data(fit_data, DataTableWidget.FIT_DATA_TYPE)

    def __removeGraphDataFromTable(self, graphData: NodeGraphData):
        """Remove data and objects related to the GraphData object."""
        if not graphData in self.__graphDataList:
            return

        self.__graphDataList.remove(graphData)
        self.__updateGraphDataTable()
        self.__updateAxisComboBoxes()
        self.__updateCurveFittingComboBoxes()
        self.__updatePlot()

    def __removeFitDataFromTable(self, fit_data: FitData):
        """Remove data and objects related to the FitData object."""
        if not fit_data in self.__fit_data_list:
            return

        self.__fit_data_list.remove(fit_data)
        self.__updateGraphDataTable()
        self.__updatePlot()

    def __removeDataFromTableByName(self, name):
        for graph_data in self.__graphDataList:
            if graph_data.name == name:
                self.__removeGraphDataFromTable(graph_data)
                return

        for fit_data in self.__fit_data_list:
            if fit_data.name == name:
                self.__removeFitDataFromTable(fit_data)
                return

    def __populateColorMapComboBox(self):
        """Initialize color map combo box options."""
        for colorMapInfo in CrossplotColorMaps:
            self.__colorMapComboBox.addItem(QtGui.QIcon(colorMapInfo.reference_image), colorMapInfo.label)

        self.__colorMapComboBox.setCurrentText("Gist Rainbow")
        self.data_plot_widget.set_colormap(matplotlibcm.gist_rainbow.name)

    def __onColorMapComboBoxChanged(self, text):
        """Handles color map combo box options change event."""
        for colorMapInfo in CrossplotColorMaps:
            if text != colorMapInfo.label:
                continue

            self.data_plot_widget.set_colormap(colorMapInfo.object.name)
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
        self.data_plot_widget.clear_histogram_x()
        self.data_plot_widget.clear_histogram_y()

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
                    self.data_plot_widget.add_histogram_plot_x(graphData, xHistogram, yHistogram)

        if self.__yAxisHistogramEnableCheckBox.isChecked() is True:
            for graphData in self.__graphDataList:
                xHistogram, yHistogram = createHistogramPlots(
                    graphData, yAxisParameter, self.__yHistogramBinSpinBox.value()
                )
                if xHistogram is not None and yHistogram is not None:
                    self.data_plot_widget.add_histogram_plot_y(graphData, xHistogram, yHistogram)

    def __onHistogramCheckBoxChange(self, state):
        if self.__xAxisHistogramEnableCheckBox.isChecked() is False:
            self.data_plot_widget.clear_histogram_x()

        if self.__yAxisHistogramEnableCheckBox.isChecked() is False:
            self.data_plot_widget.clear_histogram_y()

        self.__updatePlot()

    def __onLogCheckBoxChange(self, state):
        self.__updatePlot()

    def __onHistogramBinChange(self, value):
        self.__updatePlot()

    def __updateLogMode(self):
        self.data_plot_widget.set_log_mode(x=self.__xLogCheckBox.isChecked(), y=self.__yLogCheckBox.isChecked())

    def __updatePlotsLayout(self):
        self.data_plot_widget.set_theme(self.__themeComboBox.currentText())
        self.data_plot_widget._updatePlotsLayout(
            self.__xAxisHistogramEnableCheckBox.isChecked(),
            self.__yAxisHistogramEnableCheckBox.isChecked(),
            self.__zAxisComboBox.currentText(),
        )

    def __update_refit_button_state(self):
        for fit_equation in self.__fit_equations:
            fit_equation.widget.update_refit_button_state(self.__valid_fitted_curve_selected)

    def __update_output_button_state(self):
        self.__save_button.enabled = self.__valid_fitted_curve_selected

    def __on_fit_save_button_clicked(self):
        fit_data = self.__get_current_fit_data()
        if fit_data is None:
            return

        self.__save_data_to_node(fit_data, fit_data.name)

    def __on_function_curve_save_button_clicked(self, function_curve_name):
        fit_data = self.__get_fit_data(function_curve_name)
        self.__save_data_to_node(fit_data, function_curve_name)

    def __save_data_to_node(self, fit_data, new_name):
        table_node = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__)
        table_node.SetName(slicer.mrmlScene.GenerateUniqueName(new_name))

        table_modification = table_node.StartModify()

        column_fitting_equation = vtk.vtkStringArray()
        column_fitting_equation.SetName("Fitting equation")
        column_fitting_equation.InsertNextValue(fit_data.type)
        table_node.AddColumn(column_fitting_equation)

        for fit_equation in self.__fit_equations:
            if fit_equation.equation.NAME == fit_data.type:
                fit_equation.equation.append_to_node(fit_data, table_node)
                break

        table_node.SetAttribute("table_type", "equation")
        table_node.Modified()
        table_node.EndModify(table_modification)

        OUTPUT_DIR_NAME = "Math functions"
        subject_hierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        app_folder_id = subject_hierarchy.GetSceneItemID()
        output_dir = subject_hierarchy.GetItemChildWithName(app_folder_id, OUTPUT_DIR_NAME)
        if output_dir == 0:
            output_dir = subject_hierarchy.CreateFolderItem(
                app_folder_id, helpers.generateName(subject_hierarchy, OUTPUT_DIR_NAME)
            )
        subject_hierarchy.CreateItem(output_dir, table_node)

        fit_data.name = new_name
        self.__updateCurveFittingComboBoxes()
        self.__updateGraphDataTable()

    def __add_equation_data_from_table(self, table_node):
        vtk_table = table_node.GetTable()
        equation_type = vtk_table.GetValueByName(0, "Fitting equation")
        for fit_equation in self.__fit_equations:
            if fit_equation.equation.NAME == equation_type:
                fit_data = fit_equation.equation.from_table(table_node.GetName(), vtk_table)
                break
        self.__add_fit_data(fit_data)

    def __on_fit_data_created(self, fit_data):
        self.__add_fit_data(fit_data)
        self.__set_current_function_curve_data(fit_data)

    def __add_fit_data(self, new_fit_data: FitData):
        for fit_data in self.__fit_data_list:
            if fit_data.name == new_fit_data.name:
                self.__fit_data_list.remove(fit_data)
                break

        new_fit_data.style.size = 1
        self.__fit_data_list.append(new_fit_data)
        new_fit_data.signalVisibleChanged.connect(self.__updatePlot)

        self.__updatePlot()
        self.__updateGraphDataTable()
        self.__updateCurveFittingComboBoxes()
        self.fitted_curves_combobox.setCurrentText(new_fit_data.name)

    def __get_current_fit_data(self):
        return self.__get_fit_data(self.fitted_curves_combobox.currentText)

    def __get_fit_data(self, name):
        for fit_data in self.__fit_data_list:
            if fit_data.name == name:
                return fit_data
        return None

    def __get_current_input_data(self):
        try:
            input_data = self.data_plot_widget.get_plotted_data(self.__fit_data_input_combo_box.currentText)
        except KeyError:
            slicer.util.errorDisplay(
                "Nothing related to this data is plotted. "
                "Please assign parameters from this input data in the Data tab or select another one.",
                parent=self.__fit_tab_widget,
            )
            return None

        if input_data["x"] is None or input_data["y"] is None:
            slicer.util.errorDisplay(
                "Missing 2D data. You must select data for X and Y axes before fitting to the equation.",
                parent=self.__fit_tab_widget,
            )
            return None

        return input_data

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


class EquationParametersWidget(qt.QFrame):
    signal_function_curve_selected = qt.Signal(str)
    signal_function_curve_edited = qt.Signal(str, str, float, bool)

    def __init__(self):
        super().__init__()

        self.__fit_equations = [Line(False), TimurCoates(False)]

        self.function_curves_combobox = qt.QComboBox()
        self.function_curves_combobox.addItem("")
        self.function_curves_combobox.currentTextChanged.connect(self.__on_function_curve_selected)

        self.parameters_stack = ShrinkableStackedWidget()
        for fit_equation in self.__fit_equations:
            equation_widget = fit_equation.widget.get_widget()
            self.parameters_stack.addWidget(equation_widget)
            equation_widget.signal_parameter_changed.connect(self.__on_equation_changed)
        self.parameters_stack.setCurrentIndex(0)

        edit_layout = qt.QFormLayout()
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.addRow("Function:", self.function_curves_combobox)
        edit_layout.addRow(self.parameters_stack)

        self.parameters_collapsible = ctk.ctkCollapsibleButton(self)
        self.parameters_collapsible.text = "Parameters"
        self.parameters_collapsible.setLayout(edit_layout)

        layout = qt.QVBoxLayout()
        layout.addWidget(self.parameters_collapsible)
        self.setLayout(layout)

    def set_functions_curves(self, function_curve_list: list):
        self.function_curves_combobox.clear()
        self.function_curves_combobox.addItem("")
        self.function_curves_combobox.addItems(function_curve_list)

    def set_current_function_curve_data(self, curve_data):
        if curve_data is None:
            for fit_equation in self.__fit_equations:
                fit_equation.widget.clear()
            return

        for index, fit_equation in enumerate(self.__fit_equations):
            if fit_equation.equation.NAME == curve_data.type:
                fit_equation.widget.update(curve_data)
                self.__set_current_parameters_stack(index)
                self.function_curves_combobox.setCurrentText(curve_data.name)
                break

    def get_current_function_curve_name(self):
        return self.function_curves_combobox.currentText

    def __on_function_curve_selected(self, function_curve):
        self.signal_function_curve_selected.emit(function_curve)

    def __set_current_parameters_stack(self, index):
        self.parameters_stack.setCurrentIndex(index)

    def __on_equation_changed(self, parameter_name, new_value, is_fixed):
        function_curve = self.function_curves_combobox.currentText
        self.signal_function_curve_edited.emit(function_curve, parameter_name, new_value, is_fixed)


class EquationsTabWidget(qt.QFrame):
    signal_new_function_curve_data = qt.Signal(FitData)
    signal_import_function_curve = qt.Signal()
    signal_export_function_curve = qt.Signal(str)
    signal_function_curve_edited = qt.Signal(str, str, float)
    signal_save_data = qt.Signal(str)

    def __init__(self, fit_data_list):
        super().__init__()

        self.__fit_data_list = fit_data_list

        # Input layout
        self.__functionCurveNameLineEdit = qt.QLineEdit()

        self.__fit_equation_combo_box = qt.QComboBox()
        self.__fit_equations = [Line(False), TimurCoates(False)]
        for fit_equation in self.__fit_equations:
            self.__fit_equation_combo_box.addItem(fit_equation.widget.DISPLAY_NAME)

        createButton = qt.QPushButton("Create")
        createButton.setFocusPolicy(qt.Qt.NoFocus)
        createButton.clicked.connect(self.__on_create_clicked)
        importButton = qt.QPushButton("Import")
        importButton.setFocusPolicy(qt.Qt.NoFocus)
        importButton.clicked.connect(self.__on_import_clicked)

        inputButtonLayout = qt.QHBoxLayout()
        inputButtonLayout.addWidget(createButton)
        inputButtonLayout.addWidget(importButton)

        inputLayout = qt.QFormLayout()
        inputLayout.addRow("Name:", self.__functionCurveNameLineEdit)
        inputLayout.addRow("Equation:", self.__fit_equation_combo_box)
        inputLayout.addRow("", inputButtonLayout)

        inputCollapsible = ctk.ctkCollapsibleButton()
        inputCollapsible.text = "Input"
        inputCollapsible.setLayout(inputLayout)

        # Edit layout
        self.edit_collapsible = EquationParametersWidget()
        self.edit_collapsible.signal_function_curve_selected.connect(self.__on_function_curve_selected)
        self.edit_collapsible.signal_function_curve_edited.connect(self.__on_function_curve_edited)

        # Output layout

        self.__save_button = qt.QPushButton("Save to project")
        self.__save_button.setFocusPolicy(qt.Qt.NoFocus)
        self.__save_button.clicked.connect(self.__on_save_button_clicked)
        self.__exportButton = qt.QPushButton("Export to file")
        self.__exportButton.setFocusPolicy(qt.Qt.NoFocus)
        self.__exportButton.clicked.connect(self.__on_export_clicked)

        output_layout = qt.QHBoxLayout()
        output_layout.addWidget(self.__save_button)
        output_layout.addWidget(self.__exportButton)

        output_collapsible = ctk.ctkCollapsibleButton()
        output_collapsible.text = "Output"
        output_collapsible.setLayout(output_layout)

        # Equations tab
        equations_tab_layout = qt.QVBoxLayout()
        equations_tab_layout.addWidget(inputCollapsible)
        equations_tab_layout.addWidget(self.edit_collapsible)
        equations_tab_layout.addWidget(output_collapsible)
        equations_tab_layout.addStretch()

        self.setLayout(equations_tab_layout)

        self.__on_function_curve_selected("")

    def set_functions_curves(self, function_curve_list: list):
        self.edit_collapsible.set_functions_curves(function_curve_list)

    def set_current_function_curve_data(self, curve_data):
        self.edit_collapsible.set_current_function_curve_data(curve_data)

    def __on_function_curve_selected(self, function_curve):
        self.edit_collapsible.set_current_function_curve_data(None)
        for fit_data in self.__fit_data_list:
            if fit_data.name == function_curve:
                self.edit_collapsible.set_current_function_curve_data(fit_data)
                break
        self.__update_output_button_state()

    def __on_create_clicked(self):
        function_curve_name = self.__functionCurveNameLineEdit.text
        if function_curve_name == "":
            return
        for fit_equation in self.__fit_equations:
            if fit_equation.widget.DISPLAY_NAME == self.__fit_equation_combo_box.currentText:
                fit_data = fit_equation.equation.create_default(function_curve_name)
                self.signal_new_function_curve_data.emit(fit_data)
                break

    def __on_import_clicked(self):
        self.signal_import_function_curve.emit()

    def __on_export_clicked(self):
        function_curve_name = self.edit_collapsible.get_current_function_curve_name()
        self.signal_export_function_curve.emit(function_curve_name)

    def __on_function_curve_edited(self, function_curve, parameter_name, new_value, is_fixed):
        self.signal_function_curve_edited.emit(function_curve, parameter_name, new_value)

    def __on_save_button_clicked(self):
        function_curve_name = self.edit_collapsible.get_current_function_curve_name()
        self.signal_save_data.emit(function_curve_name)

    def __update_output_button_state(self):
        valid_function_curve = False
        function_curve_name = self.edit_collapsible.get_current_function_curve_name()
        if function_curve_name:
            for fit_data in self.__fit_data_list:
                if fit_data.name == function_curve_name:
                    valid_function_curve = True
                    break
        self.__save_button.enabled = valid_function_curve
        self.__exportButton.enabled = valid_function_curve


class ShrinkableStackedWidget(qt.QFrame):
    """A StackedWidget that reduces it's weight according to the current selected widget."""

    def __init__(self):
        super().__init__()
        self.widgetList = []
        self.main_layout = qt.QVBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.main_layout)

    def setCurrentIndex(self, index):
        for i, widget in enumerate(self.widgetList):
            if i == index:
                widget.setVisible(True)
            else:
                widget.setVisible(False)

    def addWidget(self, widget):
        self.widgetList.append(widget)
        self.main_layout.addWidget(widget)
