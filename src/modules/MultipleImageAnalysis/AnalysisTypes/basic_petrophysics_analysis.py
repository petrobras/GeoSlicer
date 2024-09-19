import os

import logging
import pandas as pd
import slicer

from collections import defaultdict
from .analysis_base import AnalysisBase, AnalysisReport, AnalysisWidgetBase, FILE_NOT_FOUND
from ltrace.slicer.segment_inspector.inspector_files.inspector_file_reader import InspectorFileReader
from ltrace.slicer.node_attributes import TableDataOrientation, TableType


class BasicPetrophysicsAnalysisWidget(AnalysisWidgetBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setup(self):
        pass


class BasicPetrophysicsAnalysis(AnalysisBase):
    def __init__(self, parent) -> None:
        super().__init__(
            parent=parent, name="Basic Petrophysics Analysis", configWidget=BasicPetrophysicsAnalysisWidget()
        )

    def run(self, filesDir, outputName: str) -> AnalysisReport:
        """Runs analysis.

        Args:
            filesDir (str): the selected data's directory.
            outputName (str): the report's name.

        Returns:
            AnalysisReport: the analysis report object.
        """
        inspectorFileReader = InspectorFileReader()
        poresDataDict = inspectorFileReader.parse_directory(filesDir)

        # Filter valid depths
        for pore in list(poresDataDict.keys()):
            if poresDataDict[pore]["BasicPetrophysics"] is None:
                poresDataDict.pop(pore)

        data = defaultdict(list)

        for pore in poresDataDict.keys():
            basicPetrophysicsData = poresDataDict[pore]["BasicPetrophysics"].data
            columnNames = list(basicPetrophysicsData["Properties"])
            columnValues = list(basicPetrophysicsData["Values"])
            data["DEPTH"].append(pore)
            for i in range(len(columnValues)):
                if columnNames[i] not in data:
                    data[columnNames[i]] = []
                data[columnNames[i]].append(columnValues[i])

        config = {
            TableDataOrientation.name(): TableDataOrientation.COLUMN.value,
            TableType.name(): TableType.BASIC_PETROPHYSICS.value,
        }
        projectName = os.path.basename(filesDir)
        report = AnalysisReport(name=outputName, data=data, config=config)
        return report

    def getSuggestedOutputName(self, filesDir: str) -> None:
        projectName = os.path.basename(filesDir)
        return f"{projectName} Basic Petrophysics"

    def refreshInputReportfiles(self, folder: str) -> pd.DataFrame:
        inspectorFileReader = InspectorFileReader()
        poresDict = inspectorFileReader.parse_directory(folder)

        basicPetrophysicsFiles = list()
        if not poresDict:
            raise RuntimeError("The selected directory doesn't contain any data related to this analysis type")

        pores = list(poresDict.keys())
        for pore in pores:
            basicPetrophysicsFile = poresDict[pore].get("BasicPetrophysics")
            if not basicPetrophysicsFile:
                logging.error(f"Depth {str(pore)} does not contain a valid report file.")
                basicPetrophysicsFiles.append(FILE_NOT_FOUND)
                continue

            basicPetrophysicsFiles.append(basicPetrophysicsFile.filename)

        if len(basicPetrophysicsFiles) == 0:
            raise RuntimeError("The selected directory doesn't contain any data related to this analysis type")

        return pd.DataFrame(data=zip(pores, basicPetrophysicsFiles), columns=["Depth", "Basic Petrophysics File"])
