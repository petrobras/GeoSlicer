import logging
import os
import qt

import numpy as np
import pandas as pd
import slicer

from collections import defaultdict

from AnalysisTypes.analysis_base import AnalysisBase, AnalysisReport, AnalysisWidgetBase, FILE_NOT_FOUND
from ltrace.slicer.segment_inspector.inspector_files.inspector_file_reader import InspectorFileReader
from ltrace.slicer.segment_inspector.inspector_files.inspector_report_file import InspectorReportFile
from ltrace.slicer.node_attributes import TableDataOrientation, TableType


class MeanInDepthAnalysisWidget(AnalysisWidgetBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setup(self):
        REPORT_PARAMETERS = InspectorReportFile.header(accept_types=[float, int])

        form_layout = qt.QFormLayout()

        self.parameter_label_combo_box = qt.QComboBox()
        self.parameter_label_combo_box.addItem("All")
        self.parameter_label_combo_box.addItems(REPORT_PARAMETERS)
        self.parameter_label_combo_box.currentText = "max_feret"
        self.parameter_label_combo_box.setToolTip("Select one of the table parameters to compute the mean.")
        form_layout.addRow("Mean Input Parameter: ", self.parameter_label_combo_box)

        self.weight_label_combo_box = qt.QComboBox()
        self.weight_label_combo_box.addItem("None")
        self.weight_label_combo_box.addItems(REPORT_PARAMETERS)
        self.weight_label_combo_box.currentText = "None"
        self.weight_label_combo_box.setToolTip("Select one of the table parameters to be used as the weight.")
        form_layout.addRow("Mean Weight Parameter: ", self.weight_label_combo_box)

        self.setLayout(form_layout)

    def update_report_parameters(self, parameters):
        parameters.sort()
        current_selected_input_parameter = self.parameter_label_combo_box.currentText
        self.parameter_label_combo_box.clear()
        self.parameter_label_combo_box.addItem("All")
        self.parameter_label_combo_box.addItems(parameters)
        self.parameter_label_combo_box.setCurrentText(current_selected_input_parameter)
        self.parameter_label_combo_box.currentIndexChanged.connect(lambda *args: self.output_name_changed())

        current_selected_weight_parameter = self.weight_label_combo_box.currentText
        self.weight_label_combo_box.clear()
        self.weight_label_combo_box.addItem("None")
        self.weight_label_combo_box.addItems(parameters)
        self.weight_label_combo_box.setCurrentText(current_selected_weight_parameter)
        self.weight_label_combo_box.currentIndexChanged.connect(lambda *args: self.output_name_changed())


class MeanInDepthAnalysis(AnalysisBase):
    def __init__(self):
        super().__init__(name="Mean in Depth Analysis", config_widget=MeanInDepthAnalysisWidget())

    def run(self, files_dir, output_name):
        """Runs analysis.

        Args:
            files_dir (str): the selected data's directory.
        """
        inspector_file_reader = InspectorFileReader()
        pores_data_dict = inspector_file_reader.parse_directory(files_dir)
        sample_column_label = self.config_widget.parameter_label_combo_box.currentText
        weight_column_label = self.config_widget.weight_label_combo_box.currentText

        # Filter valid depths
        for pore in list(pores_data_dict.keys()):
            if pores_data_dict[pore]["Report"] is None:
                pores_data_dict.pop(pore)

        data = defaultdict(list)
        for key, value in pores_data_dict.items():
            report_data = value["Report"].data
            weight_data = None
            if weight_column_label != "None":
                weight_data = report_data.loc[:, weight_column_label]

            if sample_column_label == "All":
                columns = list(report_data.select_dtypes(include=[np.number]))
                if columns[0] == "label":
                    columns = columns[1:]
            else:
                columns = [sample_column_label]

            sample_data = report_data.loc[:, columns]
            data["DEPTH"].append(key * 1000)  # m to mm
            for column in columns:
                data[f"MEAN_{column}"].append(np.average(sample_data[column], weights=weight_data))

        # Create AnalysisReport from data
        config = {
            TableDataOrientation.name(): TableDataOrientation.COLUMN.value,
            TableType.name(): TableType.MEAN_IN_DEPTH.value,
        }
        report = AnalysisReport(name=output_name, data=data, config=config)
        return report

    def get_suggested_output_name(self, files_dir):
        project_name = os.path.basename(files_dir)
        sample_column_label = self.config_widget.parameter_label_combo_box.currentText
        weight_column_label = self.config_widget.weight_label_combo_box.currentText
        name = f"{project_name} {sample_column_label} Mean in Depth"
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

        if not pores_dict:
            raise RuntimeError("The selected directory doesn't contain any data related to this analysis type")

        pores = list(pores_dict.keys())

        for pore in pores:
            try:
                report_file = pores_dict[pore]["Report"]
                if not report_file:
                    logging.error(f"Depth {str(pore)} does not contain a valid report file.")
                    report_files.append(FILE_NOT_FOUND)
                    continue

                report_files.append(report_file.filename)
            except KeyError:
                logging.warning("Problem during dictionary parsing. Please check this behavior.")
                continue

        if not report_files:
            raise RuntimeError("The selected directory doesn't contain any data related to this analysis type")

        # Update widgets information with the available parameters
        self._update_widget_informations(pores_dict)
        df = pd.DataFrame(data=zip(list(pores), report_files), columns=["Depth", "Report File"])
        return df

    def _update_widget_informations(self, pores_dict):
        """Update config widgets informations based on loaded files.

        Args:
            pores_dict (dict): dictionary with valid loaded files.
        """
        # Check report files version being used
        report_versions_used = list()
        for key, value in pores_dict.items():
            report_file = value["Report"]
            if report_file in (None, FILE_NOT_FOUND):
                continue
            report_versions_used.append(report_file.version)

        if len(report_versions_used) <= 0:
            return

        # Select the newer 'protocol' version
        current_report_version = (
            report_versions_used[0] if len(set(report_versions_used)) == 1 else max(report_versions_used)
        )

        # Update related widgets
        self.config_widget.update_report_parameters(
            InspectorReportFile.header(version=current_report_version, accept_types=[float, int])
        )
