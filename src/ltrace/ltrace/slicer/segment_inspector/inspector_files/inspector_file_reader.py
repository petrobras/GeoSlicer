import glob
import logging
import os
import re

from ltrace.slicer.segment_inspector.inspector_files.inspector_basic_petrophysics_file import (
    InspectorBasicPetrophysicsFile,
)
from ltrace.slicer.segment_inspector.inspector_files.inspector_report_file import InspectorReportFile
from ltrace.slicer.segment_inspector.inspector_files.inspector_variables_file import InspectorVariablesFile


class InspectorFileReader:
    PORE_DELIMETER_REGEX_PATTERN = r"[\.\-\,\;\_]"
    PORE_FOLDER_REGEX_PATTERN = r"[0-9]{2,}(" + PORE_DELIMETER_REGEX_PATTERN + r"[0-9]{2}($|(?=m$)))?"

    def __init__(self):
        pass

    def parse_directory(self, selected_dir):
        if not os.path.isdir(selected_dir):
            return None

        folder_list = self.__get_project_folders(selected_dir)
        pattern = re.compile(rf"{self.PORE_FOLDER_REGEX_PATTERN}(?!.*{self.PORE_FOLDER_REGEX_PATTERN})")

        # Create pore's dictionary with relevant data
        pores_dict = dict()
        for folder in folder_list:

            # Retrieve Variables and Report Files
            variables_files = list()
            report_files = list()
            basic_petrophysics_files = list()

            for root, _, _ in os.walk(folder):
                var_files = glob.glob(os.path.join(root, "*Variables*.tsv"))
                var_files.extend(glob.glob(os.path.join(root, "*Globals*.tsv")))
                var_files = [file for file in var_files if "schema" not in file]

                rpt_files = glob.glob(os.path.join(root, "*Report*.tsv"))
                rpt_files = [file for file in rpt_files if "schema" not in file]

                bp_files = glob.glob(os.path.join(root, "*Basic_Petrophysics*.tsv"))
                bp_files = [file for file in bp_files if "schema" not in file]

                variables_files.extend(var_files)
                report_files.extend(rpt_files)
                basic_petrophysics_files.extend(bp_files)

            variables_file = self.__select_valid_inspector_file_from_list(
                cls=InspectorVariablesFile, files=variables_files
            )
            report_file = self.__select_valid_inspector_file_from_list(cls=InspectorReportFile, files=report_files)
            basic_petrophysics_file = self.__select_valid_inspector_file_from_list(
                cls=InspectorBasicPetrophysicsFile, files=basic_petrophysics_files
            )

            match = re.search(pattern, folder)
            if not match:
                logging.warning(
                    f"Discarding files from {folder} because it's name doesn't match the 'Depth' pattern (ex: TAG_5050,00)"
                )
                continue

            pore = match.group()
            pore = float(re.sub(self.PORE_DELIMETER_REGEX_PATTERN, ".", pore))
            pores_dict[pore] = {
                "Variables": variables_file,
                "Report": report_file,
                "BasicPetrophysics": basic_petrophysics_file,
                "base_folder": folder,
            }

        return pores_dict

    def __get_project_folders(self, selected_dir):
        project_dirs = []
        for root, _, _ in os.walk(selected_dir):
            project_file = glob.glob(os.path.join(root, "*.mrml"))

            if len(project_file) <= 0:
                continue

            project_dirs.append(root)

        return project_dirs

    def __select_valid_inspector_file_from_list(self, cls, files):
        """Select a valid variable file based on the following criterias:
           1) Recently modified
           2) Readable by pandas
           3) Consistent based on InspectorVariablesFile load's logic.

        Args:
            cls (InspectorVariablesFile/InspectorReportFile): the class related to the inspector output's file.
            files (list): a list with the absolute file path to a variable file candidate.

        Returns:
            InspectorVariablesFile/InspectorReportFile: the selected file type's object.
        """
        sorted_files = sorted(files, key=lambda t: -os.stat(t).st_mtime)
        for file in sorted_files:
            try:
                variable_file = cls(file)
            except Exception as error:
                logging.warning("{} is not a valid {} file: {}".format(file, cls.__name__, error))
                continue

            return variable_file
