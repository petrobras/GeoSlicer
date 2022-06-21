import os

import logging
import pandas as pd
import slicer

from AnalysisTypes.analysis_base import AnalysisBase, AnalysisReport, AnalysisWidgetBase, FILE_NOT_FOUND
from ltrace.slicer.segment_inspector.inspector_files.inspector_file_reader import InspectorFileReader
from ltrace.slicer.node_attributes import TableDataOrientation, TableType


class BasicPetrophysicsAnalysisWidget(AnalysisWidgetBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setup(self):
        pass


class BasicPetrophysicsAnalysis(AnalysisBase):
    def __init__(self):
        super().__init__(name="Basic Petrophysics Analysis", config_widget=BasicPetrophysicsAnalysisWidget())

    def run(self, files_dir, output_name):
        inspector_file_reader = InspectorFileReader()
        pores_data_dict = inspector_file_reader.parse_directory(files_dir)

        # Filter valid depths
        for pore in list(pores_data_dict.keys()):
            if pores_data_dict[pore]["BasicPetrophysics"] is None:
                pores_data_dict.pop(pore)

        data = dict(DEPTH=[])

        for pore in pores_data_dict.keys():
            basic_petrophysics_data = pores_data_dict[pore]["BasicPetrophysics"].data
            column_names = list(basic_petrophysics_data["Properties"])
            column_values = list(basic_petrophysics_data["Values"])
            data["DEPTH"].append(pore)
            for i in range(len(column_values)):
                if column_names[i] not in data:
                    data[column_names[i]] = []
                data[column_names[i]].append(column_values[i])

        config = {
            TableDataOrientation.name(): TableDataOrientation.COLUMN.value,
            TableType.name(): TableType.BASIC_PETROPHYSICS.value,
        }
        project_name = os.path.basename(files_dir)
        report = AnalysisReport(name=output_name, data=data, config=config)
        return report

    def get_suggested_output_name(self, files_dir):
        project_name = os.path.basename(files_dir)
        return f"{project_name} Basic Petrophysics"

    def refresh_input_report_files(self, folder):
        inspector_file_reader = InspectorFileReader()
        pores_dict = inspector_file_reader.parse_directory(folder)

        basic_petrophysics_files = list()
        if not pores_dict:
            raise RuntimeError("The selected directory doesn't contain any data related to this analysis type")

        pores = list(pores_dict.keys())
        for pore in pores:
            basic_petrophysics_file = pores_dict[pore].get("BasicPetrophysics")
            if not basic_petrophysics_file:
                logging.error(f"Depth {str(pore)} does not contain a valid report file.")
                basic_petrophysics_files.append(FILE_NOT_FOUND)
                continue

            basic_petrophysics_files.append(basic_petrophysics_file.filename)

        if len(basic_petrophysics_files) == 0:
            raise RuntimeError("The selected directory doesn't contain any data related to this analysis type")

        return pd.DataFrame(data=zip(pores, basic_petrophysics_files), columns=["Depth", "Basic Petrophysics File"])
