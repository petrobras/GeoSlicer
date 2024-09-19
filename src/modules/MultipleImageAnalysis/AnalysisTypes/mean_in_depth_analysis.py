import qt
import slicer
import logging
import numpy as np
import pandas as pd
import os

from .analysis_base import AnalysisBase, AnalysisReport, AnalysisWidgetBase, FILE_NOT_FOUND
from collections import defaultdict
from ltrace.slicer.segment_inspector.inspector_files.inspector_file_reader import InspectorFileReader
from ltrace.slicer.segment_inspector.inspector_files.inspector_report_file import InspectorReportFile
from ltrace.slicer.node_attributes import TableDataOrientation, TableType
from ltrace.utils.ProgressBarProc import ProgressBarProc
from typing import Dict


class MeanInDepthAnalysisWidget(AnalysisWidgetBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setup(self):
        REPORT_PARAMETERS = InspectorReportFile.header(accept_types=[float, int])

        formLayout = qt.QFormLayout()

        self.parameterLabelComboBox = qt.QComboBox()
        self.parameterLabelComboBox.addItem("All")
        self.parameterLabelComboBox.addItems(REPORT_PARAMETERS)
        self.parameterLabelComboBox.currentText = "max_feret"
        self.parameterLabelComboBox.setToolTip("Select one of the table parameters to compute the mean.")
        self.parameterLabelComboBox.objectName = "Mean in Depth Parameter Combo Box"
        formLayout.addRow("Mean Input Parameter: ", self.parameterLabelComboBox)

        self.weightLabelComboBox = qt.QComboBox()
        self.weightLabelComboBox.addItem("None")
        self.weightLabelComboBox.addItems(REPORT_PARAMETERS)
        self.weightLabelComboBox.currentText = "None"
        self.weightLabelComboBox.setToolTip("Select one of the table parameters to be used as the weight.")
        self.weightLabelComboBox.objectName = "Mean in Depth Weight Combo Box"
        formLayout.addRow("Mean Weight Parameter: ", self.weightLabelComboBox)

        self.setLayout(formLayout)

        # Connections
        self.parameterLabelComboBox.currentTextChanged.connect(lambda text: self.modified())
        self.weightLabelComboBox.currentTextChanged.connect(lambda text: self.modified())

    def updateReportParameters(self, parameters: Dict) -> None:
        parameters.sort()
        currentSelectedInputParameter = self.parameterLabelComboBox.currentText
        self.parameterLabelComboBox.clear()
        self.parameterLabelComboBox.addItem("All")
        self.parameterLabelComboBox.addItems(parameters)
        self.parameterLabelComboBox.setCurrentText(currentSelectedInputParameter)
        self.parameterLabelComboBox.currentIndexChanged.connect(lambda *args: self.outputNameChangedSignal.emit())

        currentSelectedWeightParameter = self.weightLabelComboBox.currentText
        self.weightLabelComboBox.clear()
        self.weightLabelComboBox.addItem("None")
        self.weightLabelComboBox.addItems(parameters)
        self.weightLabelComboBox.setCurrentText(currentSelectedWeightParameter)
        self.weightLabelComboBox.currentIndexChanged.connect(lambda *args: self.outputNameChangedSignal.emit())


class MeanInDepthAnalysis(AnalysisBase):
    def __init__(self, parent) -> None:
        super().__init__(parent=parent, name="Mean in Depth Analysis", configWidget=MeanInDepthAnalysisWidget())

    def run(self, filesDir: str, outputName: str) -> AnalysisReport:
        """Runs analysis.

        Args:
            filesDir (str): the selected data's directory.
            outputName (str): the report's name.

        Returns:
            AnalysisReport: the analysis report object.
        """
        inspectorFileReader = InspectorFileReader()
        poresDataDict = inspectorFileReader.parse_directory(filesDir)
        sampleColumnLabel = self.configWidget.parameterLabelComboBox.currentText
        weightColumnLabel = self.configWidget.weightLabelComboBox.currentText

        # Filter valid depths
        for pore in list(poresDataDict.keys()):
            if poresDataDict[pore]["Report"] is None:
                poresDataDict.pop(pore)

        data = defaultdict(list)
        for key, value in poresDataDict.items():
            reportData = value["Report"].data
            weightData = None
            if weightColumnLabel != "None":
                weightData = reportData.loc[:, weightColumnLabel]

            if sampleColumnLabel == "All":
                columns = list(reportData.select_dtypes(include=[np.number]))
                if columns[0] == "label":
                    columns = columns[1:]
            else:
                columns = [sampleColumnLabel]

            sampleData = reportData.loc[:, columns]
            data["DEPTH"].append(key * 1000)  # m to mm
            for column in columns:
                data[f"MEAN_{column}"].append(np.average(sampleData[column], weights=weightData))

        # Create AnalysisReport from data
        config = {
            TableDataOrientation.name(): TableDataOrientation.COLUMN.value,
            TableType.name(): TableType.MEAN_IN_DEPTH.value,
        }
        report = AnalysisReport(name=outputName, data=data, config=config)
        return report

    def getSuggestedOutputName(self, filesDir: str) -> None:
        projectName = os.path.basename(filesDir)
        sampleColumnLabel = self.configWidget.parameterLabelComboBox.currentText
        weightColumnLabel = self.configWidget.weightLabelComboBox.currentText
        name = f"{projectName} {sampleColumnLabel} Mean in Depth"
        if weightColumnLabel != "None":
            name += f" Weighted by {weightColumnLabel}"
        return name

    def refreshInputReportfiles(self, folder: str) -> pd.DataFrame:
        """Retrieve valid information, related to the this analysis, from the selected directory.

        Args:
            folder (str): the selected directory string.

        Raises:
            RuntimeError: Folder doesn't have any valid file for the current analysis type.

        Returns:
            dict: the summary information about the analysis files found at the input folder.
        """
        inspectorFileReader = InspectorFileReader()
        poresDict = inspectorFileReader.parse_directory(folder)

        reportFiles = list()

        if not poresDict:
            raise RuntimeError("The selected directory doesn't contain any data related to this analysis type")

        pores = list(poresDict.keys())

        for pore in pores:
            try:
                reportFile = poresDict[pore]["Report"]
                if not reportFile:
                    logging.error(f"Depth {str(pore)} does not contain a valid report file.")
                    reportFiles.append(FILE_NOT_FOUND)
                    continue

                reportFiles.append(reportFile.filename)
            except KeyError:
                logging.warning("Problem during dictionary parsing. Please check this behavior.")
                continue

        if not reportFiles:
            raise RuntimeError("The selected directory doesn't contain any data related to this analysis type")

        # Update widgets information with the available parameters
        self._updateWidgetInformation(poresDict)
        df = pd.DataFrame(data=zip(list(pores), reportFiles), columns=["Depth", "Report File"])
        return df

    def _updateWidgetInformation(self, poresDict: Dict) -> None:
        """Update config widgets informations based on loaded files.

        Args:
            poresDict (dict): dictionary with valid loaded files.
        """
        # Check report files version being used
        reportVersionsUsed = list()
        for key, value in poresDict.items():
            reportFile = value["Report"]
            if reportFile in (None, FILE_NOT_FOUND):
                continue
            reportVersionsUsed.append(reportFile.version)

        if len(reportVersionsUsed) <= 0:
            return

        # Select the newer 'protocol' version
        currentReportVersion = reportVersionsUsed[0] if len(set(reportVersionsUsed)) == 1 else max(reportVersionsUsed)

        # Update related widgets
        self.configWidget.updateReportParameters(
            InspectorReportFile.header(version=currentReportVersion, accept_types=[float, int])
        )
