from collections import namedtuple

import ctk
import lasio
import numpy as np
import qt
import slicer
from ltrace.slicer.cli_utils import writeToTable
from ltrace.slicer.slicer_matplotlib import MatplotlibCanvasWidget

from ltrace.slicer_utils import LTracePlugin, LTracePluginLogic, LTracePluginWidget
from ltrace.units import global_unit_registry as ureg
from ltrace import lmath
from pathlib import Path
from scipy.stats import norm
import pandas as pd
import vtk


class UpscaleTomoToLAS(LTracePlugin):

    SETTING_KEY = "UpscaleTomoToLAS"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "UpscaleTomoToLAS"
        self.parent.categories = ["Upscaling"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = """"""
        self.parent.acknowledgementText = """This module upscales data from the tomography domain to the LAS domain."""

    def setup(self):
        pass


class UpscaleTomoToLASLogic(LTracePluginLogic):

    UpscaleResult = namedtuple(
        "UpscaleResult",
        [
            "las_depth",
            "result_porosity_upscaled",
            "las_porosity",
            "result_porosity_filtered",
            "las_porosity_filtered",
            "depth_correction_filtered",
            "depth_correction_raw",
            "timewindow_depth",
            "lag_time",
            "cross_correlation",
            "cross_correlation_depth",
            "result_curves_corrected",
        ],
    )

    def __init__(self):
        self.current_result = None

    @classmethod
    def upscale_tomo_to_las(cls, porosity_table_node, las_file, las_depth_shift):
        loaded_table = cls.load_arrays_from_table_node(porosity_table_node)
        las_depth, las_porosity = cls.load_depth_and_porosity_from_las(las_file)
        result_depth = loaded_table["DEPTH"]

        las_depth, las_porosity, result_depth = cls.preprocess_data(
            las_depth, las_porosity, las_depth_shift, result_depth
        )

        las_sampling_interval = las_depth[1] - las_depth[0]  # 0.1524 ?

        upscaled_curves = {}
        for name, curve in loaded_table.items():
            if name == "DEPTH":
                continue

            curve_upscaled = cls.upscale_data(result_depth, curve, las_depth, interval_length=las_sampling_interval)
            upscaled_curves[name] = curve_upscaled

        result_porosity_upscaled = upscaled_curves["POROSITY"]

        depth_window = 12 * ureg.meter
        max_lag_depth = depth_window

        (
            las_porosity_filtered,
            result_porosity_filtered,
            lag_time,
            timewindow_depth,
            cross_correlation,
        ) = cls.cross_correlate_signals(
            las_porosity.magnitude,
            result_porosity_upscaled.magnitude,
            lowpass_frequency_cut=0.65,
            highpass_frequency_cut=0.15,
            time_step=las_sampling_interval,
            depth_window=depth_window,
            max_lag_depth=max_lag_depth,
        )

        result_porosity_filtered = result_porosity_filtered * ureg.dimensionless
        las_porosity_filtered = las_porosity_filtered * ureg.dimensionless
        cross_correlation = cross_correlation * ureg.dimensionless

        depth_correction_raw, depth_correction_filtered = cls.calculate_depth_adjustment(
            cross_correlation, las_sampling_interval
        )

        cross_correlation_depth = las_depth[0] + depth_window / 2 + timewindow_depth

        border_size = (las_depth.size - depth_correction_filtered.size) // 2
        depth_correction_filtered_data = depth_correction_filtered.magnitude
        depth_correction_filtered_padded_data = np.concatenate(
            [
                np.full(border_size, depth_correction_filtered_data[0]),
                depth_correction_filtered_data,
                np.full(border_size, depth_correction_filtered_data[-1]),
            ]
        )

        depth_correction = depth_correction_filtered_padded_data * depth_correction_filtered.units
        depth_corrected = las_depth + depth_correction

        result_curves_corrected = {}
        for name, curve in upscaled_curves.items():
            result_curves_corrected[name] = curve.units * np.interp(
                las_depth.magnitude, depth_corrected.magnitude, curve.magnitude
            )

        return cls.UpscaleResult(
            las_depth,
            result_porosity_upscaled,
            las_porosity,
            result_porosity_filtered,
            las_porosity_filtered,
            depth_correction_filtered,
            depth_correction_raw,
            timewindow_depth,
            lag_time,
            cross_correlation,
            cross_correlation_depth,
            result_curves_corrected,
        )

    @staticmethod
    def load_arrays_from_table_node(porosity_table_node):
        porosity_table = porosity_table_node.GetTable()
        loaded_table = {}
        for column_index in range(porosity_table_node.GetNumberOfColumns()):
            loaded_array = np.zeros(porosity_table_node.GetNumberOfRows())
            for i in range(loaded_array.size):
                loaded_array[i] = porosity_table.GetValue(i, column_index).ToFloat()
            column_name = porosity_table_node.GetColumnName(column_index)
            unit = porosity_table_node.GetColumnUnitLabel(column_name)
            loaded_table[column_name] = ureg.Quantity(loaded_array, unit)
        return loaded_table

    @staticmethod
    def load_depth_and_porosity_from_las(las_file):
        las = lasio.read(las_file, index_unit="m")
        depth = las.curves["DEPT"].data * ureg.meter
        porosity = las.curves["MRP"].data * ureg.dimensionless
        return depth, porosity

    @staticmethod
    def preprocess_data(las_depth, las_porosity, las_depth_shift, result_depth):
        las_depth_shifted = las_depth - las_depth_shift
        las_cut_indices = (las_depth_shifted >= np.min(result_depth)) & (las_depth_shifted <= np.max(result_depth))
        las_depth_shifted_cut = las_depth_shifted[las_cut_indices]
        las_porosity_cut = las_porosity[las_cut_indices]

        return las_depth_shifted_cut, las_porosity_cut, result_depth

    @staticmethod
    def upscale_data(original_domain, original_image, target_domain, interval_length):
        target_data = []

        for target_point in target_domain:
            interval_begin = target_point - interval_length / 2
            interval_end = target_point + interval_length / 2
            interval_indices = np.where((original_domain > interval_begin) & (original_domain < interval_end))

            # run np.take on the raw array because numpy isn't behaving well with pint's types
            t = np.take(original_image.magnitude, interval_indices)
            if t.size > 0:
                target_data.append(np.mean(t))
            else:
                target_data.append(np.nan)

        upscaled_image = np.asarray(target_data)
        upscaled_image = lmath.naninterp(upscaled_image)
        return original_image.units * upscaled_image

    @staticmethod
    def cross_correlate_signals(
        input_a,
        input_b,
        lowpass_frequency_cut,
        highpass_frequency_cut,
        time_step,
        depth_window,
        max_lag_depth,
    ):
        input_a_filtered = input_a - lmath.filtering.lowPassFilter2(input_a, 0.15 * 1e3, 500, highpass_frequency_cut)
        input_b_filtered = lmath.filtering.lowPassFilter2(input_b, 0.15 * 1e3, 10, lowpass_frequency_cut)
        input_b_filtered -= lmath.filtering.lowPassFilter2(input_b_filtered, 0.15 * 1e3, 500, highpass_frequency_cut)

        sampling_frequency = 1 / time_step

        lag_time, timewindow_depth, cross_correlation = lmath.timewindow_crosscorrelation(
            input_a_filtered, input_b_filtered, sampling_frequency, depth_window, time_step, max_lag_depth
        )

        cross_correlation /= np.max(cross_correlation, axis=1)[:, np.newaxis]

        return input_a_filtered, input_b_filtered, lag_time, timewindow_depth, cross_correlation

    @staticmethod
    def calculate_depth_adjustment(cross_correlation, time_step):
        cross_correlation_t = np.transpose(cross_correlation)
        rows = cross_correlation_t.shape[0]
        filter_gauss = norm(loc=rows / 2, scale=rows / 10).pdf(np.arange(1, rows + 1))
        cross_correlation_t *= filter_gauss[:, np.newaxis]

        depth_correction_raw = np.argmax(cross_correlation_t, axis=0)
        depth_correction_raw = lmath.remove_step(depth_correction_raw, maximum_step_width=10)
        depth_correction_filtered = lmath.filtering.lowPassFilter2(depth_correction_raw, 0.15 * 1000, 500, 0.1)
        depth_correction_raw = (depth_correction_raw - rows / 2) * time_step
        depth_correction_filtered = (depth_correction_filtered - rows / 2) * time_step

        return depth_correction_raw, depth_correction_filtered

    def export_result_to_las(self, filename, export_range):
        from datetime import datetime

        las = lasio.LASFile()
        las.well.DATE = datetime.today().strftime("%Y-%m-%d %H:%M:%S")
        las.other = "Generated by GeoSlicer"

        result = self.current_result
        depths = result.las_depth
        result_curves = result.result_curves_corrected.copy()

        if export_range is not None:
            minimum, maximum = export_range
            indices = (depths >= minimum) & (depths <= maximum)
            depths = depths[indices]
            for name, curve in result_curves.items():
                result_curves[name] = curve[indices]

        las.add_curve("DEPT", depths.m_as(ureg.meter), unit="m")

        def get_unit_str(quantity):
            unit = quantity.units
            if unit == ureg.dimensionless:
                return "-"
            return "{:~P}".format(quantity.units)

        for name, curve in result_curves.items():
            las.add_curve(name, curve.magnitude, unit=get_unit_str(curve))

        las.write(filename, version=2)

    def export_result_to_table(self, table):
        result = self.current_result
        result_curves = result.result_curves_corrected.copy()

        depths = result.las_depth
        result_curves["DEPT"] = depths.to("m")

        df = pd.DataFrame(result_curves)
        writeToTable(df, table.GetID())

        for name, curve in result_curves.items():
            table.SetColumnUnitLabel(name, str(curve.units))

        return table


class UpscaleTomoToLASWidget(LTracePluginWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.logic = UpscaleTomoToLASLogic()

    def setup(self):
        LTracePluginWidget.setup(self)
        inputs_group = ctk.ctkCollapsibleButton()
        inputs_group.text = "Configuration"
        inputs_group.setLayout(qt.QVBoxLayout())
        self.inputs_frame = qt.QWidget()
        self.inputs_frame.setLayout(qt.QFormLayout())
        inputs_group.layout().addWidget(self.inputs_frame)

        self.tomo_table_cb = self._create_table_selection_widget()
        self.inputs_frame.layout().addRow("Tomo Result Table: ", self.tomo_table_cb)
        self.select_las_input_line_edit = SelectFileLineEdit(
            "UpscaleTomoToLAS/LAS-last-load-path",
            "Load LAS File",
            "LAS Files (*.las)",
            "Select file to load",
        )
        self.inputs_frame.layout().addRow("LAS Input: ", self.select_las_input_line_edit)

        vertical_shift_frame = qt.QWidget()
        vertical_shift_frame.setLayout(qt.QHBoxLayout())
        new_margin = vertical_shift_frame.layout().contentsMargins()
        new_margin.setLeft(0)
        new_margin.setRight(0)
        vertical_shift_frame.layout().setContentsMargins(new_margin)
        self.las_depth_offset_m_sb = qt.QDoubleSpinBox()
        self.las_depth_offset_m_sb.setDecimals(2)
        self.las_depth_offset_m_sb.setRange(0, 12)
        self.las_depth_offset_m_sb.setSingleStep(0.01)
        self.inputs_frame.layout().addRow("LAS Depth Offset (m): ", self.las_depth_offset_m_sb)

        self.run_button = qt.QPushButton("Run")
        self.run_button.clicked.connect(self._on_run_clicked)

        export_group = ctk.ctkCollapsibleButton()
        export_group.text = "Export"
        export_group.setLayout(qt.QVBoxLayout())
        self.export_frame = qt.QWidget()
        self.export_frame.setLayout(qt.QFormLayout())
        export_group.layout().addWidget(self.export_frame)

        self.select_las_export_line_edit = SelectFileLineEdit(
            "UpscaleTomoToLAS/LAS-last-export-path",
            "Export LAS File",
            "LAS Files (*.las)",
            "Select file to export",
            mode="save",
        )

        range_selection_layout = qt.QHBoxLayout()
        self.export_full_range_check_box = qt.QCheckBox("Export full range")
        self.export_full_range_check_box.setChecked(True)
        self.export_range_begin = qt.QSpinBox()
        self.export_range_begin.setRange(0, 99999)
        self.export_range_begin.value = self.export_range_begin.minimum
        self.export_range_begin.valueChanged.connect(self._update_range_limits)
        self.export_range_end = qt.QSpinBox()
        self.export_range_end.setRange(1, 100000)
        self.export_range_end.value = self.export_range_end.maximum
        self.export_range_end.valueChanged.connect(self._update_range_limits)
        self.export_button = qt.QPushButton("Export LAS")
        self.export_full_range_check_box.stateChanged.connect(self._update_manual_range_specification)
        range_selection_layout.addWidget(self.export_full_range_check_box)
        range_selection_layout.addStretch()
        self.export_range_begin_label = qt.QLabel("Begin (m): ")
        range_selection_layout.addWidget(self.export_range_begin_label)
        range_selection_layout.addWidget(self.export_range_begin)
        self.export_range_end_label = qt.QLabel("End (m): ")
        range_selection_layout.addWidget(self.export_range_end_label)
        range_selection_layout.addWidget(self.export_range_end)

        self.export_frame.layout().addRow("LAS Export Path: ", self.select_las_export_line_edit)
        self.export_frame.layout().addRow(range_selection_layout)
        export_button_layout = qt.QHBoxLayout()
        export_button_layout.addWidget(self.export_button)
        self.export_frame.layout().addRow(export_button_layout)
        self.export_button.clicked.connect(self._on_export_clicked)

        self.layout.addWidget(inputs_group)
        self.layout.addWidget(self.run_button)
        self.layout.addWidget(export_group)
        self.layout.addStretch()

        self.tomo_table_cb.currentNodeChanged.connect(self._update_run_button)
        self.select_las_input_line_edit.line_edit.textChanged.connect(self._update_run_button)
        self.select_las_export_line_edit.line_edit.textChanged.connect(self._update_export_button)
        self._update_ui()

    def _create_table_selection_widget(self):
        node_selection_cb = slicer.qMRMLNodeComboBox()
        node_selection_cb.nodeTypes = ["vtkMRMLTableNode"]
        node_selection_cb.selectNodeUponCreation = False
        node_selection_cb.addEnabled = False
        node_selection_cb.removeEnabled = False
        node_selection_cb.noneEnabled = False
        node_selection_cb.showHidden = False
        node_selection_cb.showChildNodeTypes = False
        node_selection_cb.setMRMLScene(slicer.mrmlScene)
        return node_selection_cb

    def _on_select_file_button_clicked(self):

        last_path = UpscaleTomoToLAS.get_setting("last-load-path")
        if last_path is None:
            last_path = ""

        selected_file = qt.QFileDialog.getOpenFileName(None, "Load DLIS file", last_path, "DLIS Files (*.dlis)")
        if not selected_file:
            return

        UpscaleTomoToLAS.set_setting("last-load-path", str(Path(selected_file).parent))

        self.selected_file_line_edit.setText(selected_file)

    def _on_run_clicked(self):
        current_node = self.tomo_table_cb.currentNode()
        las_file = Path(self.select_las_input_line_edit.line_edit.text)
        las_depth_shift = self.las_depth_offset_m_sb.value * ureg.meter

        result = self.logic.upscale_tomo_to_las(current_node, las_file, las_depth_shift)
        self.logic.current_result = result
        table_name = current_node.GetName() + "_LAS"
        table = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__, table_name)
        self.logic.export_result_to_table(table)
        self._update_ui()
        slicer.util.infoDisplay(f'Table "{table_name}" created')

    def _on_export_clicked(self):
        filename = self.select_las_export_line_edit.line_edit.text
        range_ = None
        if not self.export_full_range_check_box.isChecked():
            minimum = self.export_range_begin.value * ureg.meter
            maximum = self.export_range_end.value * ureg.meter
            range_ = minimum, maximum

        self.logic.export_result_to_las(filename, range_)
        slicer.util.infoDisplay(f'Exported LAS file "{filename}"')

    def _update_ui(self):
        result = self.logic.current_result
        self._update_run_button()
        self._update_export_section(result)

    def _update_export_section(self, result):
        self.export_frame.setEnabled(result is not None)
        self._update_export_button()
        self._update_manual_range_specification()

    def _update_plots(self, result):
        result_porosity_upscaled = result.result_porosity_upscaled.m_as(ureg.dimensionless)
        las_depth = result.las_depth.m_as(ureg.meter)
        las_porosity = result.las_porosity.m_as(ureg.dimensionless)
        result_porosity_filtered = result.result_porosity_filtered.m_as(ureg.dimensionless)
        las_porosity_filtered = result.las_porosity_filtered.m_as(ureg.dimensionless)
        result_porosity_corrected = result.result_curves_corrected["Porosity"].m_as(ureg.dimensionless)
        lag_time = result.lag_time.m_as(ureg.meter)
        cross_correlation_depth = result.cross_correlation_depth.m_as(ureg.meter)
        depth_correction_filtered = result.depth_correction_filtered.m_as(ureg.meter)
        depth_correction_raw = result.depth_correction_raw.m_as(ureg.meter)
        cross_correlation = result.cross_correlation.m_as(ureg.dimensionless)
        range_begin, range_end = self._get_result_range()

        def common_plot_configuration(widget, show_legend=True):
            widget.axes.set_ylim(range_begin, range_end)
            widget.axes.invert_yaxis()
            if show_legend:
                widget.axes.legend(loc="upper center", bbox_to_anchor=(0.5, -0.05))
            widget.axes.grid()
            widget.figure.set_tight_layout(True)

        canvas_widget1 = MatplotlibCanvasWidget()
        canvas_widget1.add_subplot(1, 1, 1)
        canvas_widget1.axes.set_title("Raw Data")
        canvas_widget1.axes.plot(result_porosity_upscaled, las_depth, label="Tomo")
        canvas_widget1.axes.plot(las_porosity, las_depth, label="LAS")
        canvas_widget1.axes.set_xlabel("Porosity")
        canvas_widget1.axes.set_ylabel("Depth (meters)")
        common_plot_configuration(canvas_widget1)

        canvas_widget2 = MatplotlibCanvasWidget()
        canvas_widget2.add_subplot(1, 1, 1)
        canvas_widget2.axes.set_title("Band Limited Data")
        canvas_widget2.axes.plot(result_porosity_filtered, las_depth, label="Tomo")
        canvas_widget2.axes.plot(las_porosity_filtered, las_depth, label="LAS")
        canvas_widget2.axes.set_xlabel("Porosity")
        canvas_widget2.axes.set_ylabel("Depth (meters)")
        common_plot_configuration(canvas_widget2)

        canvas_widget3 = MatplotlibCanvasWidget(parent=self.layout.parent())
        canvas_widget3.add_subplot(1, 1, 1)
        canvas_widget3.axes.set_title("Windowed Cross Correlation")
        canvas_widget3.axes.set_title("Small correction")
        canvas_widget3.axes.set_xlabel("Depth Correction (meters)")
        canvas_widget3.axes.set_ylabel("Depth (meters)")
        canvas_widget3.axes.pcolormesh(lag_time, cross_correlation_depth, cross_correlation, aa=False)
        canvas_widget3.axes.plot(depth_correction_filtered, cross_correlation_depth)
        canvas_widget3.axes.plot(depth_correction_raw, cross_correlation_depth)
        common_plot_configuration(canvas_widget3, show_legend=False)

        canvas_widget4 = MatplotlibCanvasWidget(parent=self.layout.parent())
        canvas_widget4.add_subplot(1, 1, 1)
        canvas_widget4.axes.set_title("Processed")
        canvas_widget4.axes.plot(result_porosity_corrected, las_depth, label="Tomo Corrected")
        canvas_widget4.axes.plot(las_porosity, las_depth, label="LAS")
        canvas_widget4.axes.set_xlabel("Porosity")
        canvas_widget4.axes.set_ylabel("Depth (meters)")
        common_plot_configuration(canvas_widget4)

    def _add_tomo_result_table(self, name, curves):
        table_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", name)
        table = table_node.GetTable()

        curves_size = next(iter(curves.values())).size
        for curve in curves.values():
            assert curve.size == curves_size, f"All curves should have the same size: {curves_size}"

        for column_index, (column_name, curve) in enumerate(curves.items()):
            column_array = vtk.vtkFloatArray()
            column_array.SetName(column_name)
            table.AddColumn(column_array)
            table_node.SetColumnProperty(column_index, "unit", str(curve.units))

        table.SetNumberOfRows(curves_size)
        for column_index, curve in enumerate(curves.values()):
            array_value = curve.magnitude
            for value_index in range(curves_size):
                table.SetValue(value_index, column_index, array_value[value_index])

    def _update_run_button(self):
        has_node_selected = self.tomo_table_cb.currentNode() is not None
        has_las_selected = Path(self.select_las_input_line_edit.line_edit.text).is_file()
        self.run_button.setEnabled(has_node_selected and has_las_selected)

    def _update_export_button(self):
        current_text = self.select_las_export_line_edit.line_edit.text
        if current_text and not current_text.endswith(".las"):
            self.select_las_export_line_edit.line_edit.text = current_text + ".las"

        result = self.logic.current_result
        has_result = result is not None
        has_output_file_selected = len(current_text) > 0
        self.export_button.setEnabled(has_result and has_output_file_selected)

    def _update_manual_range_specification(self):
        enabled = not self.export_full_range_check_box.isChecked()
        self.export_range_begin.setEnabled(enabled)
        self.export_range_begin_label.setEnabled(enabled)
        self.export_range_end.setEnabled(enabled)
        self.export_range_end_label.setEnabled(enabled)

        minimum, maximum = self._get_result_range()
        self.export_range_begin.setRange(minimum, maximum - 1)
        self.export_range_end.setRange(minimum + 1, maximum)

        if self.export_range_begin.value < minimum:
            self.export_range_begin.value = minimum
        if self.export_range_end.value > maximum:
            self.export_range_end.value = maximum

        self._update_range_limits()

    def _update_range_limits(self):
        self.export_range_begin.setMaximum(self.export_range_end.value - 1)
        self.export_range_end.setMinimum(self.export_range_begin.value + 1)

    def _get_result_range(self):
        result = self.logic.current_result
        if result is None:
            return 0, 100000

        import math

        minimum = math.floor(result.las_depth[0].m_as(ureg.meter))
        maximum = math.ceil(result.las_depth[-1].m_as(ureg.meter))

        return minimum, maximum


class SelectFileLineEdit(qt.QWidget):
    def __init__(self, setting_key, dialog_title, dialog_filter, placeholder_text, mode="open"):
        super().__init__()
        selected_file_layout = qt.QHBoxLayout()
        new_margin = selected_file_layout.contentsMargins()
        new_margin.setLeft(0)
        new_margin.setRight(0)
        selected_file_layout.setContentsMargins(new_margin)

        self.setLayout(selected_file_layout)
        self.line_edit = qt.QLineEdit()
        self.line_edit.setReadOnly(True)
        self.line_edit.placeholderText = placeholder_text
        self.select_file_button = qt.QPushButton("...")
        self.select_file_button.clicked.connect(self._on_button_clicked)
        self.setting_key = setting_key
        self.dialog_title = dialog_title
        self.dialog_filter = dialog_filter

        assert mode in ["open", "save"]
        dialog_open_functions = {
            "open": qt.QFileDialog.getOpenFileName,
            "save": qt.QFileDialog.getSaveFileName,
        }
        self._open_dialog_function = dialog_open_functions[mode]

        selected_file_layout.addWidget(self.line_edit)
        selected_file_layout.addWidget(self.select_file_button)

    def _on_button_clicked(self):
        last_path = UpscaleTomoToLAS.get_setting(self.setting_key, str(Path.home()))
        selected_file = self._open_dialog_function(None, self.dialog_title, last_path, self.dialog_filter)

        if selected_file:
            UpscaleTomoToLAS.set_setting(self.setting_key, str(Path(selected_file)))
            self.line_edit.setText(selected_file)
