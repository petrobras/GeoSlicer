import os
from pathlib import Path

from ltrace.slicer.segment_inspector.inspector_files.inspector_basic_petrophysics_file import (
    InspectorBasicPetrophysicsFile,
)


class InspectorBasicPetrophysicsFileReader:
    def parse_directory(self, directory_path):
        if not os.path.isdir(directory_path):
            return None

        tsv_files = self.__get_tsv_files(directory_path)

        for file in tsv_files:
            InspectorBasicPetrophysicsFile(file)

    def __get_tsv_files(self, directory_path):
        files = []
        for path in Path(directory_path).rglob("*.tsv"):
            files.append(path)
        return files
