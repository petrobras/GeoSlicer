import ctk
import qt
import slicer

import logging
import numpy as np
import os
import pandas as pd

from .analysis_base import AnalysisBase, AnalysisReport, AnalysisWidgetBase, FILE_NOT_FOUND
from ltrace.slicer.segment_inspector.inspector_files.inspector_file_reader import InspectorFileReader
from ltrace.slicer.segment_inspector.inspector_files.inspector_report_file import InspectorReportFile
from ltrace.slicer.segment_inspector.inspector_files.inspector_variables_file import InspectorVariablesFile
from ltrace.slicer.node_attributes import TableDataOrientation, TableType
from ltrace.slicer.ui import numberParamInt
from ltrace.utils.ProgressBarProc import ProgressBarProc
from typing import Dict, List


class HistogramInDepthAnalysisWidget(AnalysisWidgetBase):
    NORMALIZATION_BY_SUM_LABEL: str = "Number of elements"
    DEFAULT_BINS_VALUE: int = 100
    DEFAULT_NORMALIZE_OPTION: qt.Qt.CheckState = qt.Qt.Checked
    DEFAULT_HEIGHT: int = 1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setup(self) -> None:
        REPORT_PARAMETERS = InspectorReportFile.header(accept_types=[float, int])
        VARIABLES_PARAMETERS = InspectorVariablesFile.header()
        REPORT_PARAMETERS.sort()
        VARIABLES_PARAMETERS.sort()
        formLayout = qt.QFormLayout()
        self.parameterLabelComboBox = qt.QComboBox()
        self.parameterLabelComboBox.addItems(REPORT_PARAMETERS)
        self.parameterLabelComboBox.setToolTip("Select one of the table parameters to compute the histogram.")
        self.parameterLabelComboBox.currentTextChanged.connect(self.__onParameterLabelComboBoxChanged)
        self.parameterLabelComboBox.objectName = "Histogram in Depth Parameter Combo Box"

        self.weightLabelComboBox = qt.QComboBox()
        self.weightLabelComboBox.addItem("None")
        self.weightLabelComboBox.addItems(REPORT_PARAMETERS)
        self.weightLabelComboBox.setToolTip("Select one of the table parameters to be used as the weight.")
        self.weightLabelComboBox.currentTextChanged.connect(lambda *args: self.outputNameChangedSignal.emit())
        self.weightLabelComboBox.objectName = "Histogram in Depth Weight Combo Box"

        self.histogramBinSpinBox = numberParamInt(vrange=(10, 1000), value=self.DEFAULT_BINS_VALUE)
        self.histogramBinSpinBox.setToolTip("Type the number of bins to compute the histograms.")
        self.histogramBinSpinBox.objectName = "Histogram in Depth Bins Spin Box"

        visualizationCollapsibleButton = ctk.ctkCollapsibleButton()
        visualizationCollapsibleButton.text = "Visualization"
        visualizationCollapsibleButton.collapsed = False
        visualizationFormLayout = qt.QFormLayout(visualizationCollapsibleButton)

        self.histogramHeightSpinBox = qt.QDoubleSpinBox()
        self.histogramHeightSpinBox.setRange(0, 10)
        self.histogramHeightSpinBox.setValue(self.DEFAULT_HEIGHT)
        self.histogramHeightSpinBox.setToolTip(
            "Maximum height of the histograms related to the well depth scale (in meter)."
        )
        self.histogramHeightSpinBox.objectName = "Histogram in Depth Height Spin Box"

        self.normalizationLabelComboBox = qt.QComboBox()
        self.normalizationLabelComboBox.addItems([self.NORMALIZATION_BY_SUM_LABEL])
        self.normalizationLabelComboBox.addItems(VARIABLES_PARAMETERS)
        self.normalizationLabelComboBox.setToolTip(
            "Parameter to be used as the amplitude normalization. If nothing is specified, then there will be no normalization."
        )
        self.normalizationLabelComboBox.objectName = "Histogram in Depth Normalization Combo Box"

        self.normalizeCheckBox = qt.QCheckBox()
        self.normalizeCheckBox.setChecked(self.DEFAULT_NORMALIZE_OPTION == qt.Qt.Checked)
        self.normalizeCheckBox.setToolTip("Normalize histogram's amplitude.")
        self.normalizeCheckBox.stateChanged.connect(self.__onNormalizedCheckboxChanged)
        self.normalizeCheckBox.objectName = "Histogram in Depth Normalize Check Box"

        normalizationFrame = qt.QFrame()
        normalizationLayout = qt.QHBoxLayout(normalizationFrame)
        normalizationLayout.setContentsMargins(0, 0, 0, 0)
        normalizationLayout.addWidget(self.normalizeCheckBox)
        normalizationLayout.addWidget(qt.QLabel(" by "))
        normalizationLayout.addWidget(self.normalizationLabelComboBox)
        normalizationLayout.addStretch()

        visualizationFormLayout.addRow("Histogram Height: ", self.histogramHeightSpinBox)
        visualizationFormLayout.addRow("Normalize: ", normalizationFrame)

        formLayout.addRow("Histogram Input Parameter: ", self.parameterLabelComboBox)
        formLayout.addRow("Histogram Weight Parameter: ", self.weightLabelComboBox)
        formLayout.addRow("Histogram Bins: ", self.histogramBinSpinBox)
        formLayout.addRow(visualizationCollapsibleButton)

        self.__applyDefaultValues()

        # Connections
        self.histogramHeightSpinBox.valueChanged.connect(lambda value: self.modified())
        self.normalizationLabelComboBox.currentTextChanged.connect(lambda text: self.modified())
        self.normalizeCheckBox.stateChanged.connect(lambda state: self.modified())
        self.parameterLabelComboBox.currentTextChanged.connect(lambda text: self.modified())
        self.weightLabelComboBox.currentTextChanged.connect(lambda text: self.modified())
        self.histogramBinSpinBox.valueChanged.connect(lambda value: self.modified())

        self.setLayout(formLayout)
        self.__onNormalizedCheckboxChanged(qt.Qt.Checked)

    def __onParameterLabelComboBoxChanged(self, text: str) -> None:
        enableBinsOption = text != "pore_size_class"
        self.histogramBinSpinBox.setEnabled(enableBinsOption)
        self.outputNameChangedSignal.emit()

    def updateReportParameters(self, parameters: List) -> None:
        parameters.sort()
        currentSelectedInputParameter = self.parameterLabelComboBox.currentText
        self.parameterLabelComboBox.clear()
        self.parameterLabelComboBox.addItems(parameters)
        self.parameterLabelComboBox.setCurrentText(currentSelectedInputParameter)

        currentSelectedWeightParameter = self.weightLabelComboBox.currentText
        self.weightLabelComboBox.clear()
        self.weightLabelComboBox.addItem("None")
        self.weightLabelComboBox.addItems(parameters)
        self.weightLabelComboBox.setCurrentText(currentSelectedWeightParameter)

    def updateVariablesParameters(self, parameters: List) -> None:
        currentSelectedNormalizationParameter = self.normalizationLabelComboBox.currentText
        self.normalizationLabelComboBox.clear()
        self.normalizationLabelComboBox.addItems([self.NORMALIZATION_BY_SUM_LABEL])
        if parameters:
            parameters.sort()
            self.normalizationLabelComboBox.addItems(parameters)
            self.normalizationLabelComboBox.setCurrentText(currentSelectedNormalizationParameter)

    def __onNormalizedCheckboxChanged(self, state: qt.Qt.CheckState) -> None:
        self.normalizationLabelComboBox.enabled = state != qt.Qt.Unchecked
        self.histogramHeightSpinBox.enabled = state == qt.Qt.Unchecked

    def __applyDefaultValues(self) -> None:
        defaultInputParameters = ["max_feret", "max feret"]
        defaultWeightParameters = ["area"]

        # Input parameter
        for index in range(self.parameterLabelComboBox.count):
            itemText = self.parameterLabelComboBox.itemText(index)
            if itemText not in defaultInputParameters:
                continue

            self.parameterLabelComboBox.setCurrentIndex(index)
            break

        # Weight parameter
        for index in range(self.weightLabelComboBox.count):
            itemText = self.weightLabelComboBox.itemText(index)
            if itemText not in defaultWeightParameters:
                continue

            self.weightLabelComboBox.setCurrentIndex(index)
            break

        self.histogramBinSpinBox.setValue(self.DEFAULT_BINS_VALUE)
        self.normalizeCheckBox.setChecked(self.DEFAULT_NORMALIZE_OPTION == qt.Qt.Checked)
        self.histogramHeightSpinBox.setValue(self.DEFAULT_HEIGHT)
        self.normalizationLabelComboBox.setCurrentText(self.NORMALIZATION_BY_SUM_LABEL)

    def resetConfiguration(self) -> None:
        self.__applyDefaultValues()


class HistogramInDepthAnalysis(AnalysisBase):
    def __init__(self, parent) -> None:
        super().__init__(
            parent=parent, name="Histogram in Depth Analysis", configWidget=HistogramInDepthAnalysisWidget()
        )

    def run(self, filesDir: str, outputName: str) -> AnalysisReport:
        """Runs analysis.

        Args:
            filesDir (str): the selected data's directory.
            outputName (str): the report's name.

        Returns:
            AnalysisReport: the analysis report object.
        """
        inspectorfileReader = InspectorFileReader()
        poresDataDict = inspectorfileReader.parse_directory(filesDir)
        sampleColumnLabel = self.configWidget.parameterLabelComboBox.currentText
        weightColumnLabel = self.configWidget.weightLabelComboBox.currentText
        normalizationLabel = self.configWidget.normalizationLabelComboBox.currentText
        normalizationEnabled = self.configWidget.normalizationLabelComboBox.enabled
        normalizeCheckBox = self.configWidget.normalizeCheckBox.isChecked()
        nBins = self.configWidget.histogramBinSpinBox.value
        histogramHeight = self.configWidget.histogramHeightSpinBox.value
        projectName = os.path.basename(filesDir)

        poresNumber = len(poresDataDict.keys())
        if poresNumber <= 0:
            raise Exception("No data found in the selected directory")

        with ProgressBarProc() as progressBar:
            progressBar.setTitle("Histogram in Depth Analysis")
            progressStep = 99 // (poresNumber * 3)  # 3 for loops
            currentProgress = 0
            progressBar.nextStep(0, "Starting...")

            # Filter valid depths
            for pore in list(poresDataDict.keys()):
                if poresDataDict[pore]["Report"] is None:
                    poresDataDict.pop(pore)

                currentProgress += progressStep
                progressBar.nextStep(currentProgress, f"Filtering valid data for {pore}...")

            # check min / max value from sample data
            minSampleValue = np.inf
            maxSampleValue = -np.inf
            for pore in poresDataDict.keys():
                currentProgress += progressStep
                progressBar.nextStep(currentProgress, f"Checking minimum/maximum values for {pore}...")

                reportData = poresDataDict[pore]["Report"].data
                sampleData = reportData.loc[:, sampleColumnLabel]
                currentMin = np.amin(sampleData)
                currentMax = np.amax(sampleData)

                minSampleValue = min(minSampleValue, currentMin)
                maxSampleValue = max(maxSampleValue, currentMax)

            limitBins = nBins
            if sampleColumnLabel == "pore_size_class":
                firestPoreSizeClass = 0
                lasPoreSizeClass = 7
                limitBins = np.linspace(
                    start=firestPoreSizeClass,
                    stop=lasPoreSizeClass + 1,
                    num=lasPoreSizeClass + 1 - firestPoreSizeClass + 1,
                )
            elif minSampleValue != 0:
                limitBins = np.zeros(nBins + 1)
                for i in range(0, len(limitBins)):
                    limitBins[i] = minSampleValue * np.power(np.power(maxSampleValue / minSampleValue, 1 / (nBins)), i)

            data = dict()
            for pore in poresDataDict.keys():
                currentProgress += progressStep
                progressBar.nextStep(currentProgress, f"Generating histogram for {pore}...")

                reportData = poresDataDict[pore]["Report"].data
                variablesFile = poresDataDict[pore]["Variables"]
                variablesData = variablesFile.data if variablesFile else None
                weights = None
                if weightColumnLabel != "None" and weightColumnLabel in list(reportData.columns):
                    weights = reportData.loc[:, weightColumnLabel]

                yValues, x = np.histogram(reportData.loc[:, sampleColumnLabel], bins=limitBins, weights=weights)
                if data.get("X") is None:
                    if sampleColumnLabel == "pore_size_class":
                        data["X"] = x[:-1]
                    else:
                        xValues = [np.sqrt(x[i + 1] * x[i]) for i in range(0, nBins)]
                        data["X"] = xValues

                if (
                    normalizationEnabled
                    and normalizationLabel != ""
                    and normalizationLabel != self.configWidget.NORMALIZATION_BY_SUM_LABEL
                    and variablesData is not None
                    and normalizationLabel in list(variablesData["Properties"])
                ):
                    normalizationFactor = float(
                        variablesData.loc[variablesData["Properties"] == normalizationLabel, "Values"].iloc[0]
                    )
                    if normalizationFactor > 0:
                        yValues = yValues / normalizationFactor
                elif normalizeCheckBox:
                    yValues = yValues / yValues.sum()
                else:
                    mx = np.nanmax(yValues) / histogramHeight
                    if np.isscalar(mx):
                        yValues = np.true_divide(yValues, mx)

                data[str(pore)] = yValues

            # Create AnalysisReport from data
            config = {
                TableDataOrientation.name(): TableDataOrientation.ROW.value,
                TableType.name(): TableType.HISTOGRAM_IN_DEPTH.value,
            }
            report = AnalysisReport(name=outputName, data=data, config=config)
            progressBar.nextStep(100, "Done!")

            return report

    def getSuggestedOutputName(self, filesDir: str) -> str:
        projectName = os.path.basename(filesDir)
        sampleColumnLabel = self.configWidget.parameterLabelComboBox.currentText
        weightColumnLabel = self.configWidget.weightLabelComboBox.currentText
        name = f"{projectName} {sampleColumnLabel} Histogram in Depth"
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
        inspectorfileReader = InspectorFileReader()
        poresDict = inspectorfileReader.parse_directory(folder)

        reportFiles = list()
        variablesFiles = list()

        if not poresDict:
            raise RuntimeError("The selected directory doesn't contain any data related to this analysis type")

        pores = list(poresDict.keys())

        for pore in pores:
            try:
                reportFile = poresDict[pore]["Report"]
                variablesFile = poresDict[pore]["Variables"]
                if not reportFile:
                    logging.error(f"Depth {str(pore)} does not contain a valid report file.")
                    reportFiles.append(FILE_NOT_FOUND)
                    variablesFiles.append(FILE_NOT_FOUND)
                    continue

                reportFiles.append(reportFile.filename)
                variablesFiles.append(variablesFile.filename if variablesFile else None)
            except KeyError:
                logging.warning("Problem during dictionary parsing. Please check this behavior.")
                continue

        if not reportFiles:
            raise RuntimeError("The selected directory doesn't contain any data related to this analysis type")

        # Update widgets information with the available parameters
        self._updateWidgetInformation(poresDict)
        df = pd.DataFrame(
            data=zip(pores, reportFiles, variablesFiles), columns=["Depth", "Report File", "Variables File"]
        )
        return df

    def _updateWidgetInformation(self, poresDict: Dict) -> None:
        """Update config widgets information based on loaded files.

        Args:
            poresDict (dict): dictionary with valid loaded files.
        """
        # Check report files version being used
        reportVersionsUsed = list()
        variablesVersionsUsed = list()
        for pore in poresDict.keys():
            reportFile = poresDict[pore]["Report"]
            variablesFile = poresDict[pore]["Variables"]
            if reportFile in (None, FILE_NOT_FOUND):
                continue
            reportVersionsUsed.append(reportFile.version)
            variablesVersionsUsed.append(variablesFile.version if variablesFile else None)

        if len(reportVersionsUsed) <= 0:
            return

        # Select the newer 'protocol' version
        currentReportVersion = reportVersionsUsed[0] if len(set(reportVersionsUsed)) == 1 else max(reportVersionsUsed)
        currentVariablesVersion = (
            variablesVersionsUsed[0]
            if len(set(variablesVersionsUsed)) == 1
            else np.nanmax(np.array(variablesVersionsUsed, dtype=np.float64))
        )

        # Update related widgets
        self.configWidget.updateReportParameters(
            InspectorReportFile.header(version=currentReportVersion, accept_types=[float, int])
        )
        if None in variablesVersionsUsed:
            self.configWidget.updateVariablesParameters([])
        else:
            self.configWidget.updateVariablesParameters(InspectorVariablesFile.header(version=currentVariablesVersion))
