import logging
import os
import re

import numpy as np
import ctk
import qt

from .analysis_base import AnalysisBase, AnalysisReport, AnalysisWidgetBase, FILE_NOT_FOUND
import pandas as pd
import slicer

from ltrace.slicer.segment_inspector.inspector_files.inspector_file_reader import InspectorFileReader
from ltrace.slicer.segment_inspector.inspector_files.inspector_report_file import InspectorReportFile
from ltrace.slicer.segment_inspector.inspector_files.inspector_variables_file import InspectorVariablesFile
from ltrace.slicer.node_attributes import TableDataOrientation, TableType
from ltrace.slicer.ui import numberParamInt


class HistogramInDepthAnalysisWidget(AnalysisWidgetBase):
    NORMALIZATION_BY_SUM_LABEL = "Number of elements"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setup(self):
        REPORT_PARAMETERS = InspectorReportFile.header(accept_types=[float, int])
        VARIABLES_PARAMETERS = InspectorVariablesFile.header()
        REPORT_PARAMETERS.sort()
        VARIABLES_PARAMETERS.sort()
        formLayout = qt.QFormLayout()
        self.parameter_label_combo_box = qt.QComboBox()
        self.parameter_label_combo_box.addItems(REPORT_PARAMETERS)
        self.parameter_label_combo_box.currentText = "max_feret"
        self.parameter_label_combo_box.setToolTip("Select one of the table parameters to compute the histogram.")
        self.parameter_label_combo_box.currentTextChanged.connect(self.__on_parameter_label_combo_box_changed)

        self.weight_label_combo_box = qt.QComboBox()
        self.weight_label_combo_box.addItem("None")
        self.weight_label_combo_box.addItems(REPORT_PARAMETERS)
        self.weight_label_combo_box.setToolTip("Select one of the table parameters to be used as the weight.")
        self.weight_label_combo_box.currentTextChanged.connect(lambda *args: self.output_name_changed())

        self.histogram_bin_spin_box = numberParamInt(vrange=(0, 1000), value=20)
        self.histogram_bin_spin_box.setToolTip("Type the number of bins to compute the histograms.")

        optional_collapsible_button = ctk.ctkCollapsibleButton()
        optional_collapsible_button.text = "Optional"
        optional_collapsible_button.collapsed = True
        optional_form_layout = qt.QFormLayout(optional_collapsible_button)

        self.histogram_height_spin_box = qt.QDoubleSpinBox()
        self.histogram_height_spin_box.setRange(0, 10)
        self.histogram_height_spin_box.setValue(1)
        self.histogram_height_spin_box.setToolTip(
            "Maximum height of the histograms related to the well depth scale (in meter)."
        )

        self.normalization_label_combo_box = qt.QComboBox()
        self.normalization_label_combo_box.addItems([self.NORMALIZATION_BY_SUM_LABEL])
        self.normalization_label_combo_box.addItems(VARIABLES_PARAMETERS)
        self.normalization_label_combo_box.setToolTip(
            "Parameter to be used as the amplitude normalization. If nothing is specified, then there will be no normalization."
        )

        self.normalize_check_box = qt.QCheckBox()
        self.normalize_check_box.setChecked(True)
        self.normalize_check_box.setToolTip("Normalize histogram's amplitude.")
        self.normalize_check_box.stateChanged.connect(self.__on_normalized_checkbox_changed)

        normalization_frame = qt.QFrame()
        normalization_layout = qt.QHBoxLayout(normalization_frame)
        normalization_layout.setContentsMargins(0, 0, 0, 0)
        normalization_layout.addWidget(self.normalize_check_box)
        normalization_layout.addWidget(qt.QLabel(" by "))
        normalization_layout.addWidget(self.normalization_label_combo_box)
        normalization_layout.addStretch()

        optional_form_layout.addRow("Histogram Height: ", self.histogram_height_spin_box)
        optional_form_layout.addRow("Normalize: ", normalization_frame)

        formLayout.addRow("Histogram Input Parameter: ", self.parameter_label_combo_box)
        formLayout.addRow("Histogram Weight Parameter: ", self.weight_label_combo_box)
        formLayout.addRow("Histogram Bins: ", self.histogram_bin_spin_box)
        formLayout.addRow(optional_collapsible_button)

        self.setLayout(formLayout)
        self.__on_normalized_checkbox_changed(qt.Qt.Checked)

    def __on_parameter_label_combo_box_changed(self, text):
        enable_bins_option = text != "pore_size_class"
        self.histogram_bin_spin_box.setEnabled(enable_bins_option)
        self.output_name_changed.emit()

    def update_report_parameters(self, parameters):
        parameters.sort()
        current_selected_input_parameter = self.parameter_label_combo_box.currentText
        self.parameter_label_combo_box.clear()
        self.parameter_label_combo_box.addItems(parameters)
        self.parameter_label_combo_box.setCurrentText(current_selected_input_parameter)

        current_selected_weight_parameter = self.weight_label_combo_box.currentText
        self.weight_label_combo_box.clear()
        self.weight_label_combo_box.addItem("None")
        self.weight_label_combo_box.addItems(parameters)
        self.weight_label_combo_box.setCurrentText(current_selected_weight_parameter)

    def update_variables_parameters(self, parameters):
        current_selected_normalization_parameter = self.normalization_label_combo_box.currentText
        self.normalization_label_combo_box.clear()
        self.normalization_label_combo_box.addItems([self.NORMALIZATION_BY_SUM_LABEL])
        if parameters:
            parameters.sort()
            self.normalization_label_combo_box.addItems(parameters)
            self.normalization_label_combo_box.setCurrentText(current_selected_normalization_parameter)

    def __on_normalized_checkbox_changed(self, state: qt.Qt.CheckState) -> None:
        self.normalization_label_combo_box.enabled = state != qt.Qt.Unchecked
        self.histogram_height_spin_box.enabled = state == qt.Qt.Unchecked


class HistogramInDepthAnalysis(AnalysisBase):
    def __init__(self):
        super().__init__(name="Histogram in Depth Analysis", config_widget=HistogramInDepthAnalysisWidget())

    def run(self, files_dir, output_name):
        """Runs analysis.

        Args:
            files_dir (str): the selected data's directory.
        """
        inspector_file_reader = InspectorFileReader()
        pores_data_dict = inspector_file_reader.parse_directory(files_dir)
        sample_column_label = self.config_widget.parameter_label_combo_box.currentText
        weight_column_label = self.config_widget.weight_label_combo_box.currentText
        normalization_label = self.config_widget.normalization_label_combo_box.currentText
        normalization_enabled = self.config_widget.normalization_label_combo_box.enabled
        normalize_check_box = self.config_widget.normalize_check_box.isChecked()
        n_bins = self.config_widget.histogram_bin_spin_box.value
        histogram_height = self.config_widget.histogram_height_spin_box.value
        project_name = os.path.basename(files_dir)

        # Filter valid depths
        for pore in list(pores_data_dict.keys()):
            if pores_data_dict[pore]["Report"] is None:
                pores_data_dict.pop(pore)

        # check min / max value from sample data
        min_sample_value = np.inf
        max_sample_value = -np.inf
        for pore in pores_data_dict.keys():
            report_data = pores_data_dict[pore]["Report"].data
            sample_data = report_data.loc[:, sample_column_label]
            current_min = np.amin(sample_data)
            current_max = np.amax(sample_data)

            min_sample_value = min(min_sample_value, current_min)
            max_sample_value = max(max_sample_value, current_max)

        limit_bins = n_bins
        if sample_column_label == "pore_size_class":
            first_pore_size_class = 0
            last_pore_size_class = 7
            limit_bins = np.linspace(
                start=first_pore_size_class,
                stop=last_pore_size_class + 1,
                num=last_pore_size_class + 1 - first_pore_size_class + 1,
            )
        elif min_sample_value != 0:
            limit_bins = np.zeros(n_bins + 1)
            for i in range(0, len(limit_bins)):
                limit_bins[i] = min_sample_value * np.power(
                    np.power(max_sample_value / min_sample_value, 1 / (n_bins)), i
                )

        data = dict()
        for pore in pores_data_dict.keys():
            report_data = pores_data_dict[pore]["Report"].data
            variables_file = pores_data_dict[pore]["Variables"]
            variables_data = variables_file.data if variables_file else None
            weights = None
            if weight_column_label != "None" and weight_column_label in list(report_data.columns):
                weights = report_data.loc[:, weight_column_label]

            y_values, x = np.histogram(report_data.loc[:, sample_column_label], bins=limit_bins, weights=weights)
            if data.get("X") is None:
                if sample_column_label == "pore_size_class":
                    data["X"] = x[:-1]
                else:
                    x_values = [np.sqrt(x[i + 1] * x[i]) for i in range(0, n_bins)]
                    data["X"] = x_values

            if (
                normalization_enabled
                and normalization_label != ""
                and normalization_label != self.config_widget.NORMALIZATION_BY_SUM_LABEL
                and variables_data is not None
                and normalization_label in list(variables_data["Properties"])
            ):
                normalizationFactor = float(
                    variables_data.loc[variables_data["Properties"] == normalization_label, "Values"].iloc[0]
                )
                if normalizationFactor > 0:
                    y_values = y_values / normalizationFactor
            elif normalize_check_box:
                y_values = y_values / y_values.sum()
            else:
                mx = np.nanmax(y_values) / histogram_height
                if np.isscalar(mx):
                    y_values = np.true_divide(y_values, mx)

            data[str(pore)] = y_values

        # Create AnalysisReport from data
        config = {
            TableDataOrientation.name(): TableDataOrientation.ROW.value,
            TableType.name(): TableType.HISTOGRAM_IN_DEPTH.value,
        }
        report = AnalysisReport(name=output_name, data=data, config=config)
        return report

    def get_suggested_output_name(self, files_dir):
        project_name = os.path.basename(files_dir)
        sample_column_label = self.config_widget.parameter_label_combo_box.currentText
        weight_column_label = self.config_widget.weight_label_combo_box.currentText
        name = f"{project_name} {sample_column_label} Histogram in Depth"
        if weight_column_label != "None":
            name += f" Weighted by {weight_column_label}"
        return name

    def refresh_input_report_files(self, folder):
        """Retrieve valid information, related to the this analysis, from the selected directory.

        Args:
            folder (str): the selected directory string.

        Raises:
            RuntimeError: Folder doesn't have any valid file for the current analysis type.

        Returns:
            dict: the summary information about the analysis files found at the input folder.
        """
        inspector_file_reader = InspectorFileReader()
        pores_dict = inspector_file_reader.parse_directory(folder)

        report_files = list()
        variables_files = list()

        if not pores_dict:
            raise RuntimeError("The selected directory doesn't contain any data related to this analysis type")

        pores = list(pores_dict.keys())

        for pore in pores:
            try:
                report_file = pores_dict[pore]["Report"]
                variables_file = pores_dict[pore]["Variables"]
                if not report_file:
                    logging.error(f"Depth {str(pore)} does not contain a valid report file.")
                    report_files.append(FILE_NOT_FOUND)
                    variables_files.append(FILE_NOT_FOUND)
                    continue

                report_files.append(report_file.filename)
                variables_files.append(variables_file.filename if variables_file else None)
            except KeyError:
                logging.warning("Problem during dictionary parsing. Please check this behavior.")
                continue

        if not report_files:
            raise RuntimeError("The selected directory doesn't contain any data related to this analysis type")

        # Update widgets information with the available parameters
        self._update_widget_informations(pores_dict)
        df = pd.DataFrame(
            data=zip(pores, report_files, variables_files), columns=["Depth", "Report File", "Variables File"]
        )
        return df

    def _update_widget_informations(self, pores_dict):
        """Update config widgets informations based on loaded files.

        Args:
            pores_dict (dict): dictionary with valid loaded files.
        """
        # Check report files version being used
        report_versions_used = list()
        variables_versions_used = list()
        for pore in pores_dict.keys():
            report_file = pores_dict[pore]["Report"]
            variables_file = pores_dict[pore]["Variables"]
            if report_file in (None, FILE_NOT_FOUND):
                continue
            report_versions_used.append(report_file.version)
            variables_versions_used.append(variables_file.version if variables_file else None)

        if len(report_versions_used) <= 0:
            return

        # Select the newer 'protocol' version
        current_report_version = (
            report_versions_used[0] if len(set(report_versions_used)) == 1 else max(report_versions_used)
        )
        current_variables_version = (
            variables_versions_used[0]
            if len(set(variables_versions_used)) == 1
            else np.nanmax(np.array(variables_versions_used, dtype=np.float64))
        )

        # Update related widgets
        self.config_widget.update_report_parameters(
            InspectorReportFile.header(version=current_report_version, accept_types=[float, int])
        )
        if None in variables_versions_used:
            self.config_widget.update_variables_parameters([])
        else:
            self.config_widget.update_variables_parameters(
                InspectorVariablesFile.header(version=current_variables_version)
            )
