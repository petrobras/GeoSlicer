import numbers

import PySide2
import ctk
import numpy as np
import pandas as pd
import pyqtgraph as pg
import qt
import shiboken2
import slicer
import warnings
from PoreNetworkKrelEdaLib.input_estimation import (
    closest_estimate,
    CurveFilter,
    ErrorToReferences,
    filter_simulations,
    regression_estimate,
)
from PoreNetworkKrelEdaLib.visualization_widgets.plot_base import PlotBase
from PoreNetworkKrelEdaLib.visualization_widgets.plot_data import KrelResultCurves

from ltrace.pore_networks.krel_result import KrelParameterParser, RESULT_PREFIX
from ltrace.pore_networks.simulation_parameters_node import (
    dataframe_to_parameter_node,
    parameters_dict_to_dataframe,
)
from ltrace.slicer import ui, widgets
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget
from ltrace.slicer_utils import dataframeFromTable, getResourcePath


class CurvesPlot(PlotBase):
    DISPLAY_NAME = "Krel curves dispersion"
    METHOD = "plot0"

    def __init__(self, *args, **kwargs):
        super().__init__()

        self.estimation_method = None
        self.data_manager = kwargs["data_manager"]
        self.mainLayout = qt.QFormLayout(self)

        self.zAxisComboBox = qt.QComboBox()
        self.zAxisComboBox.currentTextChanged.connect(self.update_curves_color_scale)

        self.filterListWidget = FilterListWidget(self.data_manager)
        self.filterListWidget.objectName = "Filter list"
        self.filterListWidget.applyFiltersClicked.connect(self.update)
        self.filterListWidget.curveEyeChanged.connect(self.__update_hidden_ref_curves)
        self.filterListWidget.setMinimumHeight(230)
        simulationFilterCollapsible = ctk.ctkCollapsibleGroupBox()
        simulationFilterCollapsible.setTitle("Simulation filters")
        simulationFilterCollapsible.flat = True
        simulationFilterCollapsible.collapsed = True
        simulationFilterCollapsible.setLayout(qt.QVBoxLayout())
        simulationFilterCollapsible.layout().addWidget(self.filterListWidget)
        self.mainLayout.addRow(simulationFilterCollapsible)

        self.mainLayout.addRow("Curves color scale", self.zAxisComboBox)

        self.mainLayout.addRow(" ", None)

        self.boxes_layout = qt.QGridLayout()
        self.boxes_layout.setColumnStretch(1, 1)
        self.boxes_layout.setColumnStretch(3, 1)
        self.boxes_layout.setColumnStretch(5, 1)
        self.checkboxes = {}
        cycle_labels = ["Drainage", "Imbibition", "Second Drainage"]
        for i, label in enumerate(cycle_labels):
            for j, phase in enumerate(["Ko", "Kw"]):
                name = f"{label} {phase}"
                self.__add_visibility_checkbox(name, i, j)
        self.__add_visibility_checkbox("Mean", i + 1, 0)

        self.mainLayout.addRow(self.boxes_layout)
        self.checkboxes["Imbibition Ko"].setChecked(True)
        self.checkboxes["Imbibition Kw"].setChecked(True)
        self.checkboxes["Mean"].setChecked(True)

        self.mainLayout.addRow(" ", None)

        graphics_layout_widget, plot_item = self.__createKrelPlotWidget()

        logarithmic_graphics_layout_widget, log_plot_item = self.__createKrelPlotWidget()
        log_plot_item.setLogMode(x=False, y=True)

        self.__plot_item = DualPlotItem(plot_item, log_plot_item)

        self.__krel_curves_plot = None
        self.__ref_curves_plots = {}

        pySideMainLayout = shiboken2.wrapInstance(hash(self.mainLayout), PySide2.QtWidgets.QFormLayout)
        pySideMainLayout.addRow(graphics_layout_widget)
        pySideMainLayout.addRow(logarithmic_graphics_layout_widget)

        self.color_bar = ColorBar()
        self.mainLayout.addRow(self.color_bar)

        estimateButton = qt.QPushButton("Estimate")
        estimateButton.objectName = "Estimate button"
        estimateButton.clicked.connect(self.__estimate)
        self.mainLayout.addRow(estimateButton)

        self.estimatedInputsTableWidget = qt.QTableWidget()
        self.estimatedInputsTableWidget.objectName = "Estimated parameters table"
        self.estimatedInputsTableWidget.setVisible(False)
        self.estimatedInputsTableWidget.setMinimumHeight(230)
        self.mainLayout.addRow(self.estimatedInputsTableWidget)

        self.createParameterNodeButton = qt.QPushButton("Create parameter node")
        self.createParameterNodeButton.objectName = "Create parameter node button"
        self.createParameterNodeButton.clicked.connect(self.__createParameterNode)
        self.createParameterNodeButton.setVisible(False)
        self.mainLayout.addRow(self.createParameterNodeButton)

        self.parameterNodeStatus = ui.TemporaryStatusLabel()
        self.mainLayout.addRow(self.parameterNodeStatus)

        self.spacerItem = qt.QSpacerItem(0, 0, qt.QSizePolicy.Minimum, qt.QSizePolicy.Expanding)
        self.mainLayout.addItem(self.spacerItem)

    def clear_saved_plots(self):
        self.__plot_item.clear()
        self.__krel_curves_plot = None
        self.__ref_curves_plots = {}
        self.estimatedInputsTableWidget.setVisible(False)
        self.createParameterNodeButton.setVisible(False)

    def update_curves_color_scale(self):
        self.clear_saved_plots()
        self.update()

    def update(self):
        self.estimation_method = self.filterListWidget.getEstimationMethod()
        self.zAxisComboBox.blockSignals(True)
        current_text = self.zAxisComboBox.currentText
        self.zAxisComboBox.clear()
        self.zAxisComboBox.addItem("None")
        variable_parameters = self.data_manager.get_variable_parameters_list()
        self.zAxisComboBox.addItems(variable_parameters)
        self.zAxisComboBox.setCurrentText("None")
        self.zAxisComboBox.setCurrentText(current_text)
        self.zAxisComboBox.blockSignals(False)

        parameters_df = self.data_manager.get_parameters_dataframe()
        if parameters_df is None:
            return

        self.__plot_item.disableAutoRange()

        color_parameter = self.zAxisComboBox.currentText
        colors_callback = None

        # Set colors
        if color_parameter != "None":
            color_max_val = parameters_df[color_parameter].max()
            color_min_val = parameters_df[color_parameter].min()
            color_transparency = 127

            def generate_color(simulation_id, simulation_type):
                if not isinstance(simulation_id, int):
                    return None
                val = parameters_df[color_parameter][simulation_id]
                normal_val = (val - color_min_val) / (color_max_val - color_min_val)

                rw, gw, bw = water_color_gradient(normal_val)
                ro, go, bo = oil_color_gradient(normal_val)

                if simulation_type == KrelCurvesPlot.KRW:
                    return (rw, gw, bw, color_transparency)
                elif simulation_type == KrelCurvesPlot.KRO:
                    return (ro, go, bo, color_transparency)
                else:
                    return None

            colors_callback = generate_color

            self.color_bar.set_scale_range(color_min_val, color_max_val)
            self.color_bar.show()
        else:
            self.color_bar.hide()

        def generate_refcurve_color(simulation_id, simulation_type):
            if simulation_type == KrelCurvesPlot.KRO:
                return (178, 53, 53, 180)
            elif simulation_type == KrelCurvesPlot.KRW:
                return (69, 54, 178, 180)
            else:
                None

        # Create plots
        if not self.__krel_curves_plot:
            krel_result_curves = self.data_manager.get_krel_result_curves()
            self.__krel_curves_plot = KrelCurvesPlot(self.__plot_item, krel_result_curves)

        ref_curve_node_list = self.filterListWidget.getReferenceCurvesNodes()
        for curve_node in ref_curve_node_list:
            if curve_node not in self.__ref_curves_plots:
                ref_curve_result = KrelResultCurves(curve_node)
                new_krel_curves_plot = KrelCurvesPlot(self.__plot_item, ref_curve_result)
                self.__ref_curves_plots[curve_node] = new_krel_curves_plot

        # Set visibilities
        cycle_name_list = ((1, "Drainage"), (2, "Imbibition"), (3, "Second Drainage"))
        for cycle_info in cycle_name_list:
            cycle_id, cycle_name = cycle_info
            plot_krw = self.checkboxes[f"{cycle_name} Kw"].isChecked()
            plot_kro = self.checkboxes[f"{cycle_name} Ko"].isChecked()
            self.__krel_curves_plot.set_visible(cycle_id, KrelCurvesPlot.KRW, plot_krw)
            self.__krel_curves_plot.set_visible(cycle_id, KrelCurvesPlot.KRO, plot_kro)

            for ref_plot in self.__ref_curves_plots.values():
                ref_plot.set_visible(cycle_id, KrelCurvesPlot.KRW, plot_krw)
                ref_plot.set_visible(cycle_id, KrelCurvesPlot.KRO, plot_kro)

        filtered_simulation_id_list = self.__getSelectedSimulations(parameters_df)
        if self.checkboxes["Mean"].isChecked():
            filtered_simulation_id_list += ["middle"]
        self.__krel_curves_plot.set_all_visible_simulations(filtered_simulation_id_list)
        self.filtered_simulation_list = [x for x in filtered_simulation_id_list if isinstance(x, numbers.Number)]

        # Recalculate means
        self.__krel_curves_plot.recalculate_middle(self.filtered_simulation_list)

        # Plot curves
        self.__krel_curves_plot.plot(colors_callback)

        for ref_plot in self.__ref_curves_plots.values():
            ref_plot.plot(generate_refcurve_color)

        # Clean removed curves
        for removed_node in self.__ref_curves_plots.keys() - ref_curve_node_list:
            removed_curve = self.__ref_curves_plots.pop(removed_node)
            removed_curve.remove_plots()

        slicer.app.processEvents()

        self.__plot_item.autoRange()

    def __add_visibility_checkbox(self, name, i, j):
        self.boxes_layout.addWidget(qt.QLabel(name), j, i * 2)
        self.checkboxes[name] = qt.QCheckBox()
        self.boxes_layout.addWidget(self.checkboxes[name], j, i * 2 + 1)
        self.checkboxes[name].setChecked(False)
        self.checkboxes[name].objectName = name
        self.checkboxes[name].stateChanged.connect(self.update)

    def __update_hidden_ref_curves(self):
        hidden_curve_nodes = self.filterListWidget.getHiddenCurveNodes()
        for node, krel_curves_plot in self.__ref_curves_plots.items():
            krel_curves_plot.hide_simulations(node in hidden_curve_nodes)

    def __getSelectedSimulations(self, parameters_df):
        parameters_df = self.data_manager.get_parameters_dataframe()
        filtered_simulations_ids = self.__getFilteredSimulations(parameters_df)
        filtered_simulations_df = parameters_df.iloc[filtered_simulations_ids]

        ref_simulation_result_df_list = self.__getReferenceCurvesDataFrames()

        column_name_list = []
        for filter in self.filterListWidget.getFilters():
            column_name_list.append(filter.column_name)

        if (
            len(ref_simulation_result_df_list) == 0
            or len(column_name_list) == 0
            or self.estimation_method == "Regression"
        ):
            return filtered_simulations_ids
        else:
            error_to_references = ErrorToReferences(ref_simulation_result_df_list, filtered_simulations_df)
            minimal_error_id = error_to_references.getMinimalErrorId(column_name_list)
            return [filtered_simulations_ids[minimal_error_id]]

    def __getReferenceCurvesDataFrames(self):
        ref_simulation_result_node_list = self.filterListWidget.getReferenceCurvesNodes()
        ref_simulation_result_df_list = []
        for ref_simulation_node in ref_simulation_result_node_list:
            ref_simulation_result_df_list.append(dataframeFromTable(ref_simulation_node))
        return ref_simulation_result_df_list

    def __getFilteredSimulations(self, parameters_df):
        return filter_simulations(parameters_df, self.filterListWidget.getFilters())

    def __estimate(self):
        output_ranges = {}
        for filter in self.filterListWidget.getFilters():
            output_ranges[filter.column_name] = [filter.min_value, filter.max_value]
        parameters_df = pd.DataFrame(self.data_manager.get_parameters_dataframe().iloc[self.filtered_simulation_list])

        ref_simulation_result_df_list = self.__getReferenceCurvesDataFrames()
        if len(ref_simulation_result_df_list) > 0 and self.estimation_method == "Regression":
            estimated_inputs = regression_estimate(parameters_df, ref_simulation_result_df_list)
        else:
            estimated_inputs = closest_estimate(parameters_df, output_ranges)

        self.estimatedInputsDf = parameters_dict_to_dataframe(estimated_inputs)
        self.df_to_widget(self.estimatedInputsDf, self.estimatedInputsTableWidget)

        self.estimatedInputsTableWidget.setVisible(True)
        self.createParameterNodeButton.setVisible(True)

    def __createParameterNode(self):
        parameterNode = dataframe_to_parameter_node(
            self.estimatedInputsDf, "simulation_input_parameters", self.data_manager.input_node
        )
        newParameterNodeName = parameterNode.GetName()
        self.parameterNodeStatus.setStatus(f"Sucessfully generated {newParameterNodeName} node")

    @staticmethod
    def df_to_widget(dataframe, table_widget: qt.QTableWidget):
        num_rows, num_cols = dataframe.shape
        table_widget.setRowCount(num_rows)
        table_widget.setColumnCount(num_cols)

        for row_idx, row_item in enumerate(dataframe.iterrows()):
            row_name, row_data = row_item
            table_widget.setVerticalHeaderItem(row_idx, qt.QTableWidgetItem(row_name))
            for col_idx, value in enumerate(row_data):
                item = qt.QTableWidgetItem(str(value))
                table_widget.setItem(row_idx, col_idx, item)

        table_widget.resizeColumnsToContents()
        table_widget.resizeRowsToContents()

    @staticmethod
    def __createKrelPlotWidget():
        graphics_layout_widget = GraphicsLayoutWidget()
        graphics_layout_widget.setBackground("w")
        graphics_layout_widget.setFixedHeight(360)

        x_legend_label_item = pg.LabelItem(angle=0)
        y_legend_label_item = pg.LabelItem(angle=270)
        x_legend_label_item.setText("Sw", color="k")
        y_legend_label_item.setText("Krel", color="k")
        graphics_layout_widget.addItem(x_legend_label_item, row=2, col=2, colspan=2)
        graphics_layout_widget.addItem(y_legend_label_item, row=0, col=1, rowspan=2)

        black_pen = pg.mkPen("k")
        axis_item_x = pg.AxisItem("bottom", pen=black_pen, textPen=black_pen, tickPen=black_pen)
        axis_item_y = pg.AxisItem("left", pen=black_pen, textPen=black_pen, tickPen=black_pen)
        plot_item = graphics_layout_widget.addPlot(axisItems={"bottom": axis_item_x, "left": axis_item_y})

        return graphics_layout_widget, plot_item


class ColorBar(qt.QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background-color:white;")
        self.setFixedHeight(90)
        self.scale_min = 0
        self.scale_max = 1
        self.hide()

    def paintEvent(self, event):
        # paint color scale

        horizontal_pad = 40
        painter = qt.QPainter(self)
        painter.setRenderHint(qt.QPainter.Antialiasing)

        # Draw the first rectangle with a linear gradient
        rect1 = qt.QRect(horizontal_pad, 5, self.width - (2 * horizontal_pad), 23)
        # gradient1 = qt.QLinearGradient(rect1.topLeft(), rect1.topRight())
        gradient1 = qt.QLinearGradient(0, 0, rect1.width(), 0)
        gradient1.setColorAt(0, qt.QColor(*water_color_gradient(0)))
        gradient1.setColorAt(1, qt.QColor(*water_color_gradient(1)))
        brush1 = qt.QBrush(gradient1)

        painter.setBrush(brush1)
        painter.drawRect(rect1)

        # Draw the second rectangle with another linear gradient
        rect2 = qt.QRect(horizontal_pad, 35, self.width - (2 * horizontal_pad), 23)
        # gradient2 = qt.QLinearGradient(rect2.topLeft(), rect2.topRight())
        gradient2 = qt.QLinearGradient(0, 0, rect1.width(), 0)
        gradient2.setColorAt(0, qt.QColor(*oil_color_gradient(0)))
        gradient2.setColorAt(1, qt.QColor(*oil_color_gradient(1)))
        brush2 = qt.QBrush(gradient2)

        painter.setBrush(brush2)
        painter.drawRect(rect2)

        # Draw the black line
        color = qt.QColor()
        pen = qt.QPen()
        pen.setColor(color)
        pen.setWidth(2)
        pen.setStyle(qt.Qt.SolidLine)
        painter.setPen(pen)
        painter.drawLine(horizontal_pad + 1, 65, self.width - (horizontal_pad + 1), 65)

        # Draw the tick marks and numeric values
        num_ticks = 5
        tick_spacing = (self.width - (2 * horizontal_pad + 2)) / (num_ticks - 1)
        font = qt.QFont()
        font.setPointSize(10)
        painter.setFont(font)

        scientific_notation = True if self.scale_min < 0.2 and self.scale_max < 0.2 else False
        precision = self.scale_max - self.scale_min

        for i in range(num_ticks):
            x = int((horizontal_pad + 1) + i * tick_spacing)
            y = 65

            # Draw the tick mark
            painter.drawLine(x, y, x, y + 5)

            # Draw the numeric value
            normal_value = i / (num_ticks - 1)
            value = normal_value * (self.scale_max - self.scale_min) + self.scale_min
            if scientific_notation:
                text = f"{value:.1e}".split("e")
                base_mult = text[0]
                exp = str(int(text[1]))
                text = f"{base_mult}·10<sup>{exp}</sup>"
                text_width = 45
            elif precision < 0.5:
                text = f"{value:.2f}"
                text_width = 35
            else:
                text = f"{value:.1f}"
                text_width = 30

            # text_width = painter.fontMetrics().boundingRect(text).width()
            painter.drawStaticText(x - text_width // 2, y + 10, qt.QStaticText(text))

    def set_scale_range(self, new_min, new_max):
        self.scale_min = new_min
        self.scale_max = new_max


def water_color_gradient(normalized_value):
    r = 0  # 0
    g = int(100 + 140 * normalized_value)  # 100 --> 240
    b = int(200 * (1 - normalized_value))  # 200 --> 0
    return (r, g, b)


def oil_color_gradient(normalized_value):
    r = int(200 + 55 * normalized_value)  # 200 --> 255
    g = int(0 + 110 * normalized_value)  # 0 --> 110
    b = int(10 + 190 * (1 - normalized_value))  # 200 --> 10
    return (r, g, b)


class FilterListWidget(qt.QFrame):
    applyFiltersClicked = qt.Signal()
    curveEyeChanged = qt.Signal()

    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.filterWidgetList = []

        self.filterList = qt.QListWidget()
        self.filterList.setStyleSheet("QListView::item { border-bottom: 1px solid #333333;}")

        self.estimationMethodCombobox = qt.QComboBox()
        self.estimationMethodCombobox.addItem("Closest")
        self.estimationMethodCombobox.addItem("Regression")
        self.estimationMethodCombobox.setCurrentIndex(1)

        addRefCurveButton = qt.QPushButton("Add reference curve")
        addRefCurveButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Add.png"))
        addRefCurveButton.setIconSize(qt.QSize(16, 16))
        addRefCurveButton.clicked.connect(self.__onAddRefCurveClicked)

        addFilterButton = qt.QPushButton("Add filter")
        addFilterButton.objectName = "Add filter button"
        addFilterButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Add.png"))
        addFilterButton.setIconSize(qt.QSize(16, 16))
        addFilterButton.clicked.connect(self.__onAddFilterClicked)

        applyFiltersButton = qt.QPushButton("Apply filters")
        applyFiltersButton.objectName = "Apply filters button"
        applyFiltersButton.clicked.connect(self.__onApplyFiltersClicked)

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(addRefCurveButton)
        buttonsLayout.addStretch()
        buttonsLayout.addWidget(addFilterButton)
        buttonsLayout.addWidget(applyFiltersButton)

        estimationMethodLayout = qt.QHBoxLayout()
        estimationMethodLayout.addWidget(qt.QLabel("Estimation method:"))
        estimationMethodLayout.addWidget(self.estimationMethodCombobox)
        estimationMethodLayout.addStretch()

        self.mainLayout = qt.QVBoxLayout(self)
        self.mainLayout.addWidget(self.filterList)
        self.mainLayout.addLayout(buttonsLayout)
        self.mainLayout.addLayout(estimationMethodLayout)

    def getFilters(self):
        filters = []
        for list_item_widget in self.filterWidgetList:
            if not isinstance(list_item_widget.widget, FilterWidget):
                continue
            filter_name = list_item_widget.widget.getSelectedFilter()
            if filter_name == "-":
                continue
            new_curve_filter = CurveFilter()
            new_curve_filter.column_name = filter_name
            new_curve_filter.min_value = list_item_widget.widget.getMinValue()
            new_curve_filter.max_value = list_item_widget.widget.getMaxValue()
            filters.append(new_curve_filter)
        return filters

    def getReferenceCurvesNodes(self):
        reference_curves = []
        for list_item_widget in self.filterWidgetList:
            if not isinstance(list_item_widget.widget, RefCurveWidget):
                continue
            new_reference_curve = list_item_widget.widget.getSelectedNode()
            if new_reference_curve is None:
                continue
            reference_curves.append(new_reference_curve)
        return reference_curves

    def getHiddenCurveNodes(self):
        hidden_reference_curves = []
        for list_item_widget in self.filterWidgetList:
            if not isinstance(list_item_widget.widget, RefCurveWidget):
                continue
            if list_item_widget.widget.isCurveVisible():
                continue
            ref_curve_node = list_item_widget.widget.getSelectedNode()
            if ref_curve_node is None:
                continue
            hidden_reference_curves.append(ref_curve_node)
        return hidden_reference_curves

    def getEstimationMethod(self):
        return self.estimationMethodCombobox.currentText

    def __getFilterList(self):
        filter_list = ["-"]
        column_names = list(self.data_manager.parameters_df.columns)
        parameter_parser = KrelParameterParser()
        for column_name in column_names:
            parameter_name = parameter_parser.get_result_name(column_name) or parameter_parser.get_input_name(
                column_name
            )
            if parameter_name is not None:
                filter_list.append(column_name)
        return filter_list

    def __onAddFilterClicked(self):
        newFilterWidget = FilterWidget(self.__getFilterList())
        newFilterWidget.objectName = "Filter widget"
        newListItem = qt.QListWidgetItem()
        self.filterList.addItem(newListItem)
        newListItem.setSizeHint(newFilterWidget.sizeHint)
        self.filterList.setItemWidget(newListItem, newFilterWidget)
        filterItemWidget = FilterItemWidget(newListItem, newFilterWidget)
        self.filterWidgetList.append(filterItemWidget)
        newFilterWidget.removeButtonClicked.connect(lambda: self.__removeFilter(filterItemWidget))

    def __onAddRefCurveClicked(self):
        newRefCurveWidget = RefCurveWidget()
        newListItem = qt.QListWidgetItem()
        self.filterList.addItem(newListItem)
        newListItem.setSizeHint(newRefCurveWidget.sizeHint)
        self.filterList.setItemWidget(newListItem, newRefCurveWidget)
        filterItemWidget = FilterItemWidget(newListItem, newRefCurveWidget)
        self.filterWidgetList.append(filterItemWidget)
        newRefCurveWidget.removeButtonClicked.connect(lambda: self.__removeFilter(filterItemWidget))
        newRefCurveWidget.visibilityButtonToggled.connect(self.__onVisibilityButtonToggled)

    def __removeFilter(self, filterItemWidget):
        self.filterWidgetList.remove(filterItemWidget)
        self.filterList.takeItem(self.filterList.row(filterItemWidget.item))
        filterItemWidget.widget.deleteLater()

    def __onApplyFiltersClicked(self):
        self.applyFiltersClicked.emit()

    def __onVisibilityButtonToggled(self):
        self.curveEyeChanged.emit()


class FilterBaseWidget(qt.QFrame):
    removeButtonClicked = qt.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.removeFilterButton = qt.QPushButton()
        self.removeFilterButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Cancel.png"))
        self.removeFilterButton.setIconSize(qt.QSize(16, 16))
        self.removeFilterButton.setFlat(True)
        self.removeFilterButton.clicked.connect(self.__onRemoveButtonClicked)

        self.configLayout = qt.QHBoxLayout()

        layout = qt.QHBoxLayout(self)
        layout.addLayout(self.configLayout)
        layout.addStretch()
        layout.addWidget(self.removeFilterButton)

    def __onRemoveButtonClicked(self):
        self.removeButtonClicked.emit()


class FilterWidget(FilterBaseWidget):
    def __init__(self, filterList=[], parent=None):
        super().__init__(parent)

        self.combobox = qt.QComboBox()
        if filterList:
            self.combobox.addItems(filterList)

        self.minLineEdit = ui.floatParam()
        self.maxLineEdit = ui.floatParam()

        self.configLayout.addWidget(self.combobox)
        self.configLayout.addWidget(qt.QLabel("Min:"))
        self.configLayout.addWidget(self.minLineEdit)
        self.configLayout.addWidget(qt.QLabel("Max:"))
        self.configLayout.addWidget(self.maxLineEdit)

    def getSelectedFilter(self):
        return self.combobox.currentText

    def getMinValue(self):
        return float(self.minLineEdit.text)

    def getMaxValue(self):
        return float(self.maxLineEdit.text)


class FilterItemWidget:
    def __init__(self, item=None, widget=None):
        self.item = item
        self.widget = widget


class RefCurveWidget(FilterBaseWidget):
    visibilityButtonToggled = qt.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.refCurveInput = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLTableNode"],
            defaultText="Select reference curve",
        )
        self.refCurveInput.addNodeAttributeIncludeFilter("table_type", "krel_simulation_results")

        self.showHideButton = widgets.ShowHideButton()
        self.showHideButton.toggled.connect(self.__onVisibilityButtonToggled)

        self.configLayout.addWidget(self.refCurveInput)
        self.configLayout.addWidget(self.showHideButton)

    def getSelectedNode(self):
        return self.refCurveInput.currentNode()

    def isCurveVisible(self):
        return self.showHideButton.isOpen()

    def __onVisibilityButtonToggled(self):
        self.visibilityButtonToggled.emit()


class KrelCurvesPlot:
    KRW = 0
    KRO = 1
    DRAINAGE = 1
    IMBIBITION = 2
    SECOND_DRINAGE = 3

    DEFAULT_COLOR_DICT = {
        "middle": {
            KRW: "blue",
            KRO: "red",
        }
    }

    def __init__(self, plot_item, krel_result_curves):
        self.__plot_item = plot_item
        self.__krel_result_curves = krel_result_curves
        self.__plot_manager = PlotManager()

    def recalculate_middle(self, filtered_list):
        for cycle_id in range(1, 4):
            cycle = self.__krel_result_curves.get_cycle(cycle_id)

            if not filtered_list:
                continue

            krw_filtered = [cycle.krw_data[id] for id in filtered_list if id in cycle.krw_data]
            kro_filtered = [cycle.kro_data[id] for id in filtered_list if id in cycle.kro_data]

            if krw_filtered:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    krw_mean = np.nanmean(np.array(krw_filtered), axis=0)
                cycle.krw_data["middle"] = list(krw_mean)

            if kro_filtered:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    kro_mean = np.nanmean(np.array(kro_filtered), axis=0)
                cycle.kro_data["middle"] = list(kro_mean)

    def plot(self, color_callback=None):
        for cycle_id in range(1, 4):
            krel_cycle_curves = self.__krel_result_curves.get_cycle(cycle_id)

            self.__plot_with_color(
                cycle_id, krel_cycle_curves, "middle", color_callback, evidence=True, replace_plot=True
            )

            number_of_simulations = krel_cycle_curves.get_number_of_simulations()
            if number_of_simulations > 0:
                self.transparency = 128 + 64 // number_of_simulations
            else:
                self.transparency = 128
            for simulation_id in range(number_of_simulations):
                self.__plot_with_color(cycle_id, krel_cycle_curves, simulation_id, color_callback)

    def set_visible(self, cycle, type, visible):
        self.__plot_manager.set_type_visible(cycle, type, visible)

    def set_all_visible_simulations(self, simulation_id_list):
        self.__plot_manager.set_all_visible_simulations(simulation_id_list)

    def hide_simulations(self, hide):
        self.__plot_manager.hide_curves(hide)

    def remove_plots(self):
        plot_list = self.__plot_manager.get_all_plots()
        for plot in plot_list:
            self.__plot_item.removeItem(plot)

    def __plot_with_color(
        self, cycle_id, krel_cycle_curves, simulation_id, color_callback, evidence=False, replace_plot=False
    ):
        color_callback = color_callback if color_callback else self.__generate_color
        krw_color = color_callback(simulation_id, self.KRW) or self.__generate_color(simulation_id, self.KRW)
        kro_color = color_callback(simulation_id, self.KRO) or self.__generate_color(simulation_id, self.KRO)

        if replace_plot and self.__plot_manager.exists(cycle_id, simulation_id, self.KRW):
            self.__plot_manager.remove_plot(cycle_id, simulation_id)

        if not self.__plot_manager.exists(cycle_id, simulation_id, self.KRW) and self.__plot_manager.is_visible(
            cycle_id, simulation_id, self.KRW
        ):
            krw_plot = self.__plot_krw(krel_cycle_curves, simulation_id, krw_color, evidence)
            if krw_plot:
                self.__plot_manager.add_plot(cycle_id, simulation_id, self.KRW, krw_plot)
        if not self.__plot_manager.exists(cycle_id, simulation_id, self.KRO) and self.__plot_manager.is_visible(
            cycle_id, simulation_id, self.KRO
        ):
            kro_plot = self.__plot_kro(krel_cycle_curves, simulation_id, kro_color, evidence)
            if kro_plot:
                self.__plot_manager.add_plot(cycle_id, simulation_id, self.KRO, kro_plot)

    def __plot_krw(self, krel_cycle_curves, simulation_id, color, evidence=False):
        sw = krel_cycle_curves.get_sw_data()

        krw_plot = None

        krw = krel_cycle_curves.get_krw_data(simulation_id)
        if not krw:
            return
        krw_plot = self.__plot_item.plot(pen=pg.mkPen(color, width=2))
        krw_plot.setData(sw, krw)
        if evidence:
            krw_plot.setZValue(1)

        return krw_plot

    def __plot_kro(self, krel_cycle_curves, simulation_id, color, evidence=False):
        sw = krel_cycle_curves.get_sw_data()

        kro_plot = None

        kro = krel_cycle_curves.get_kro_data(simulation_id)
        if not kro:
            return
        kro_plot = self.__plot_item.plot(pen=pg.mkPen(color, width=2))
        kro_plot.setData(sw, kro)
        if evidence:
            kro_plot.setZValue(1)

        return kro_plot

    def __generate_color(self, simulation_id, simulation_type):
        if simulation_id in KrelCurvesPlot.DEFAULT_COLOR_DICT:
            color = KrelCurvesPlot.DEFAULT_COLOR_DICT[simulation_id][simulation_type]
        else:
            if simulation_type == self.KRW:
                color = (128, 128, 170, self.transparency)
            else:
                color = (160, 128, 128, self.transparency)
        return color


class PlotManager:
    def __init__(self):
        self.__plot_dict = {}
        self.__type_visibility = {}
        self.__simulation_id_list = None
        self.__hidden = False

    def add_plot(self, cycle_id: int, simulation_id, type: int, plot):
        if cycle_id not in self.__plot_dict:
            self.__plot_dict[cycle_id] = {}
        if simulation_id not in self.__plot_dict[cycle_id]:
            self.__plot_dict[cycle_id][simulation_id] = {}
        if type not in self.__plot_dict[cycle_id][simulation_id]:
            new_plot = OptionalPlot()
            new_plot.plot = plot
            self.__plot_dict[cycle_id][simulation_id][type] = new_plot
        else:
            existing_plot = self.__plot_dict[cycle_id][simulation_id][type]
            existing_plot.plot = plot
        self.__update_visibility()

    def remove_plot(self, cycle_id: int, simulation_id):
        try:
            plot_removed = self.__plot_dict[cycle_id][simulation_id]
            for type_id, opt_plot in plot_removed.items():
                if opt_plot.plot is not None:
                    opt_plot.plot.clear()
            self.__plot_dict[cycle_id].pop(simulation_id)
            self.__update_visibility()
        except KeyError:
            print("Plot key not found. Make sure the plot exists before removing it.")

    def set_visible(self, cycle_id: int, simulation_id, type: int, visible: bool):
        if cycle_id not in self.__plot_dict:
            self.__plot_dict[cycle_id] = {}
        if simulation_id not in self.__plot_dict[cycle_id]:
            self.__plot_dict[cycle_id][simulation_id] = {}
        if type not in self.__plot_dict[cycle_id][simulation_id]:
            new_plot = OptionalPlot()
            new_plot.visible = visible
            self.__plot_dict[cycle_id][simulation_id][type] = new_plot
        else:
            existing_plot = self.__plot_dict[cycle_id][simulation_id][type]
            existing_plot.visible = visible
        self.__update_visibility()

    def set_type_visible(self, cycle_id: int, type: int, visible):
        if cycle_id not in self.__type_visibility:
            self.__type_visibility[cycle_id] = {}
        self.__type_visibility[cycle_id][type] = visible
        self.__update_visibility()

    def set_all_visible_simulations(self, simulation_id_list):
        self.__simulation_id_list = list(simulation_id_list)
        self.__update_visibility()

    def exists(self, cycle_id: int, simulation_id, type: int) -> bool:
        opt_plot = self.__get(cycle_id, simulation_id, type)
        if opt_plot and opt_plot.plot is not None:
            return True
        else:
            return False

    def is_visible(self, cycle_id: int, simulation_id, type: int) -> bool:
        if self.__hidden:
            return False
        elif self.__simulation_id_list is not None and simulation_id not in self.__simulation_id_list:
            return False
        elif not self.__is_type_visible(cycle_id, type):
            return False
        else:
            opt_plot = self.__get(cycle_id, simulation_id, type)
            if opt_plot:
                return opt_plot.visible
            else:
                return True

    def get_plot(self, cycle_id: int, simulation_id, type: int) -> bool:
        opt_plot = self.__get(cycle_id, simulation_id, type)
        if opt_plot:
            return opt_plot.plot
        else:
            return None

    def get_all_plots(self) -> list:
        plot_list = []
        for cycle_id, simulation_list in self.__plot_dict.items():
            for simulation_id, type_list in simulation_list.items():
                for type_id, opt_plot in type_list.items():
                    if opt_plot.plot is not None:
                        plot_list.append(opt_plot.plot)
        return plot_list

    def hide_curves(self, hide):
        self.__hidden = hide
        self.__update_visibility()

    def __get(self, cycle_id: int, simulation_id, type: int):
        try:
            return self.__plot_dict[cycle_id][simulation_id][type]
        except KeyError:
            return None

    def __is_type_visible(self, cycle_id: int, type: int):
        try:
            return self.__type_visibility[cycle_id][type]
        except KeyError:
            return True

    def __update_visibility(self):
        for cycle_id, simulation_list in self.__plot_dict.items():
            for simulation_id, type_list in simulation_list.items():
                for type_id, opt_plot in type_list.items():
                    if opt_plot.plot is not None:
                        visible = self.is_visible(cycle_id, simulation_id, type_id)
                        opt_plot.plot.setVisible(visible)


class OptionalPlot:
    def __init__(self):
        self.plot = None
        self.visible = True


class DualPlotItem:
    def __init__(self, plot, log_plot):
        self.__plot = plot
        self.__log_plot = log_plot

    def clear(self):
        self.__plot.clear()
        self.__log_plot.clear()

    def disableAutoRange(self):
        self.__plot.disableAutoRange()
        self.__log_plot.disableAutoRange()

    def autoRange(self):
        self.__plot.autoRange()
        self.__log_plot.autoRange()

    def removeItem(self, dual_plot):
        self.__plot.removeItem(dual_plot.plot_a)
        self.__log_plot.removeItem(dual_plot.plot_b)

    def plot(self, *args, **kwargs):
        plot_a = self.__plot.plot(*args, **kwargs)
        plot_b = self.__log_plot.plot(*args, **kwargs)
        return DualPlot(plot_a, plot_b)


class DualPlot:
    def __init__(self, plot_a, plot_b):
        self.plot_a = plot_a
        self.plot_b = plot_b

    def clear(self):
        self.plot_a.clear()
        self.plot_b.clear()

    def setData(self, x, y):
        self.plot_a.setData(x, y)
        self.plot_b.setData(x, y)

    def setZValue(self, value):
        self.plot_a.setZValue(value)
        self.plot_b.setZValue(value)

    def setVisible(self, visible):
        self.plot_a.setVisible(visible)
        self.plot_b.setVisible(visible)
