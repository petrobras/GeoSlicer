from pathlib import Path
from AnalysisTypes.analysis_base import AnalysisReport, AnalysisBase, FILE_NOT_FOUND
from AnalysisTypes.basic_petrophysics_analysis import BasicPetrophysicsAnalysis
from AnalysisTypes.histogram_in_depth_analysis import HistogramInDepthAnalysis
from AnalysisTypes.mean_in_depth_analysis import MeanInDepthAnalysis
from ltrace.slicer.data_utils import dataFrameToTableNode
from ltrace.slicer import helpers
from ltrace.slicer.node_attributes import TableDataOrientation
from ltrace.slicer_utils import (
    LTracePlugin,
    LTracePluginWidget,
    LTracePluginLogic,
)
from typing import List, Union, Dict

import os
import vtk, qt, ctk, slicer
import logging
import numpy as np
import pandas as pd
import traceback

# Checks if closed source code is available
try:
    from Test.MultipleImageAnalysisTest import MultipleImageAnalysisTest
except ImportError:
    MultipleImageAnalysisTest = None  # tests not deployed to final version or closed source


class MultipleImageAnalysis(LTracePlugin):
    SETTING_KEY = "MultipleImageAnalysis"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Multi-Image Analysis"
        self.parent.categories = ["Tools", "Thin Section"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]  # replace with "Firstname Lastname (Organization)"
        self.parent.helpText = f"file:///{Path(helpers.get_scripted_modules_path() + '/Resources/manual/Thin%20Section/Modulos/MultipleImageAnalysis.html').as_posix()}"

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MultipleImageAnalysisWidget(LTracePluginWidget):
    """Plugin responsible to generate custom reports based on the analysis' type selected.
    To add a new type of analysis, create a custom class that inherits AnalysisBase class, and then append its instance to
    'analysisTypes' list object.
    """

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.logic: MultipleImageAnalysisLogic = None

    def setup(self) -> None:
        LTracePluginWidget.setup(self)
        self.logic = MultipleImageAnalysisLogic(self.parent)
        self.logic.processFinished.connect(self._updateWidgetsStates)

        self.analysisTypes = [
            HistogramInDepthAnalysis(self.parent),
            MeanInDepthAnalysis(self.parent),
            BasicPetrophysicsAnalysis(self.parent),
        ]

        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Multiple Image Analysis"
        self.layout.addWidget(parametersCollapsibleButton)

        formLayout = qt.QFormLayout(parametersCollapsibleButton)

        # Analysis type combo box
        self.analysisTypeComboBox = qt.QComboBox()
        self.analysisTypeComboBox.objectName = "Analysis Type Combo Box"
        analysysTypeNameList = [analysisCls.name for analysisCls in self.analysisTypes]
        defaultAnalysisType = HistogramInDepthAnalysis.name
        self.analysisTypeComboBox.addItems(analysysTypeNameList)
        self.analysisTypeComboBox.setCurrentText(defaultAnalysisType)
        formLayout.addRow("Analysis: ", self.analysisTypeComboBox)

        # Directory selection widget
        self.directoryInputPathLineEdit = ctk.ctkPathLineEdit()
        self.directoryInputPathLineEdit.filters = ctk.ctkPathLineEdit.Dirs
        self.directoryInputPathLineEdit.settingKey = "ioDirInputSegInspector"
        self.directoryInputPathLineEdit.setToolTip(
            "Directory with several GeoSlicer projects/folders, one for each Thin section image at a given depth. The name of the projects must finish with the depth info, such as “Well_5000,00”."
        )
        self.directoryInputPathLineEdit.setCurrentPath("")
        self.directoryInputPathLineEdit.objectName = "Directory Input Path Line Edit"
        formLayout.addRow("Projects folder: ", self.directoryInputPathLineEdit)

        # Table widget that shows directory important information
        self.loadedFilesTable = self._createLoadedFilesTableWidget()
        formLayout.addRow(self.loadedFilesTable)

        # Label to warn user to modify parameters while seeing the preview
        self.previewLabel = qt.QLabel("You may change the parameters while seeing the preview.")
        self.previewLabel.setStyleSheet("QLabel { color : green; }")
        self.previewLabel.visible = False
        formLayout.addRow(self.previewLabel)
        formLayout.setAlignment(self.previewLabel, qt.Qt.AlignCenter)

        # Label to warn user the selected path doesn't have valid data to the current analysis
        self.invalidLabel = qt.QLabel("The selected path doesn't have valid data to the current analysis.")
        self.invalidLabel.setStyleSheet("QLabel { color : red; }")
        self.invalidLabel.visible = False
        formLayout.addRow(self.invalidLabel)
        formLayout.setAlignment(self.invalidLabel, qt.Qt.AlignCenter)

        # Populate configuration widget for analysis types
        self.analysisTypeConfigWidgets = qt.QStackedWidget()
        formLayout.addRow(self.analysisTypeConfigWidgets)
        self.nullTypeWidget = qt.QWidget()
        self.analysisTypeConfigWidgets.addWidget(self.nullTypeWidget)
        for type in self.analysisTypes:
            widget = type.configWidget
            self.analysisTypeConfigWidgets.addWidget(widget)
            widget.outputNameChangedSignal.connect(lambda model=type: self._onOutputNameChangedSignal(model))

        self.outputName = qt.QLineEdit()
        formLayout.addRow("Output name: ", self.outputName)

        self.saveButton = qt.QPushButton("Save")
        self.saveButton.toolTip = "Save the current report into a node."
        self.saveButton.enabled = False
        self.saveButton.setFixedHeight(40)
        self.saveButton.visible = False
        self.saveButton.objectName = "Save Button"
        formLayout.addRow(self.saveButton)

        # connections
        self.directoryInputPathLineEdit.currentPathChanged.connect(self._onDirectoryInputChanged)
        self.analysisTypeComboBox.currentTextChanged.connect(self._onAnalysisTypeChanged)
        self.saveButton.clicked.connect(self._onSaveButtonClicked)

        self._onAnalysisTypeChanged(self.analysisTypeComboBox.currentText)
        self._updateWidgetsStates()
        # Add vertical spacer
        self.layout.addStretch(1)

    def _onOutputNameChangedSignal(self, model: AnalysisBase) -> None:
        """Handle output name changed signal.

        Args:
            model (AnalysisBase): The analysis model object.
        """
        path = self.directoryInputPathLineEdit.currentPath
        self.outputName.text = model.getSuggestedOutputName(path)

    def _onAnalysisTypeChanged(self, type: str) -> None:
        """Handle analysis type' combobox change event.

        Args:
            type (str): the name of the analysis type.
        """
        if self.logic.generating:
            self._cancelAnalysis()

        analysisModel = self.getAnalysisModel(type)
        if analysisModel is None:
            self.analysisTypeConfigWidgets.setCurrentWidget(self.nullTypeWidget)
            return

        self.analysisTypeConfigWidgets.setCurrentWidget(analysisModel.configWidget)

        if self.directoryInputPathLineEdit.currentPath:
            self._onDirectoryInputChanged(self.directoryInputPathLineEdit.currentPath)

    def getAnalysisModel(self, desired_analysis_name: str) -> AnalysisBase:
        """Get Analysis model object based on the name

        Args:
            desired_analysis_name (str): The analysis' name

        Returns:
            AnalysisBase: The Analysis model object.
        """
        model = None
        for analysisModel in self.analysisTypes:
            if analysisModel.name == desired_analysis_name:
                model = analysisModel
                break

        return model

    def __generate(self) -> None:
        """Generates the report."""
        if self.logic.generating:
            self.logic.cancel()

        selectedAnalysisType = self.analysisTypeComboBox.currentText
        analysisModel = self.getAnalysisModel(selectedAnalysisType)
        if analysisModel is None:
            return

        path = self.directoryInputPathLineEdit.currentPath
        if not path:
            return

        name = self.getOutputNodeName()
        data = {"path": path, "name": name, "analysisModel": analysisModel}

        helpers.save_path(self.directoryInputPathLineEdit)
        self.logic.generate(data=data)

    def getOutputNodeName(self) -> str:
        """Get the name of the report to be generated.

        Returns:
            str: the name of the report to be generated.
        """
        selectedAnalysisType = self.analysisTypeComboBox.currentText
        path = self.directoryInputPathLineEdit.currentPath
        analysisModel = self.getAnalysisModel(selectedAnalysisType)
        name = self.outputName.text or analysisModel.getSuggestedOutputName(path)

        return name

    def _createLoadedFilesTableWidget(self) -> qt.QTableWidget:
        """Initialize information's table widget.

        Returns:
            qt.QTableWidget: the Table Widget object.
        """
        table_widget = qt.QTableWidget()
        table_widget.verticalHeader().setVisible(False)
        table_widget.horizontalHeader().setStretchLastSection(True)
        table_widget.setShowGrid(True)
        table_widget.setAlternatingRowColors(True)
        table_widget.setSelectionMode(table_widget.NoSelection)

        return table_widget

    def _onDirectoryInputChanged(self, folder: str) -> None:
        """Handles directory change event

        Args:
            folder (str): the directory string.
        """
        if self.logic.generating:
            self._cancelAnalysis()

        # Garantee the path remains after cancel analysis clear the widgets values
        previousState = self.directoryInputPathLineEdit.blockSignals(True)
        self.directoryInputPathLineEdit.currentPath = folder
        self.directoryInputPathLineEdit.blockSignals(previousState)

        self._clearTable()

        if folder == "" or not os.path.isdir(folder):
            message = "The selected path is invalid. Please select a directory."
            logging.warning(message)
            qt.QMessageBox.information(slicer.modules.AppContextInstance.mainWindow, "Error", message)
            return

        self._refreshInputReportFiles(folder)
        self.__generate()

    def _refreshInputReportFiles(self, folder: str) -> None:
        """Update the information displayed in the table based on the current analysis.

        Args:
            folder (str): the selected directory string.
        """
        selectedAnalysisType = self.analysisTypeComboBox.currentText
        analysisModel = self.getAnalysisModel(selectedAnalysisType)
        if analysisModel is None:
            message = "The selected analysis' type is invalid. Please, contact the technical support."
            logging.warning(message)
            qt.QMessageBox.information(slicer.modules.AppContextInstance.mainWindow, "Error", message)
            return

        try:
            tableData = analysisModel.refreshInputReportfiles(folder)
            self._onOutputNameChangedSignal(analysisModel)
        except RuntimeError as error:
            logging.warning(error)
            qt.QMessageBox.information(slicer.modules.AppContextInstance.mainWindow, "Error", error)
        else:
            self._updateTable(tableData)

    def _clearTable(self) -> None:
        """Clear table's information."""
        self.loadedFilesTable.clearContents()
        self.loadedFilesTable.setRowCount(0)
        self.loadedFilesTable.setColumnCount(0)
        self.loadedFilesTable.setHorizontalHeaderLabels([])

    def _updateTable(self, tableData: pd.DataFrame) -> None:
        """Handles table's information update.

        Args:
            tableData (pd.DataFrame): The data to be populated at the table widget.
        """
        totalRows = tableData.shape[0]
        columns = list(tableData.columns)

        self._clearTable()
        self.loadedFilesTable.rowCount = totalRows
        self.loadedFilesTable.setColumnCount(len(columns))
        self.loadedFilesTable.setHorizontalHeaderLabels(columns)

        success = True
        for idx, column in enumerate(columns):
            array = tableData[column]
            result = self._addColumnToTable(idx, array)
            success = success and result

    def _addColumnToTable(self, columnIndex: int, data: Union[List, np.ndarray]) -> bool:
        """Wrapper for populating table's column.

        Args:
            columnIndex (integer): the column's index
            data (list, array): the column's data

        Returns:
            bool: If the operation succeed.
        """

        def createTextTableItem(text):
            item = qt.QTableWidgetItem(text)
            flags = ~qt.Qt.ItemIsEditable
            original_flags = item.flags()
            item.setFlags(qt.Qt.ItemFlag(original_flags and flags))
            return item

        success = True
        for row, element in enumerate(data):
            item = createTextTableItem(str(element))
            if element == FILE_NOT_FOUND:
                item.setForeground(qt.QBrush(qt.QColor(255, 0, 0)))
                success = False
            self.loadedFilesTable.setItem(row, columnIndex, item)
        return success

    def _onSaveButtonClicked(self) -> None:
        """Handle a click on the save button."""
        if self.logic is None:
            return

        self.__saveGeneratedReport()

    def _updateWidgetsStates(self) -> None:
        """Update widgets states according to the current process' state."""
        if self.logic is None:
            return

        self.saveButton.enabled = self.logic.generating
        self.saveButton.visible = self.logic.generating

        self._updateWarningLabels()

    def _updateWarningLabels(self) -> None:
        """Update warning labels according to the current process' state."""
        configWidgetHasParameters = len(self.analysisTypeConfigWidgets.currentWidget().children()) > 2
        self.previewLabel.visible = self.logic.generating and configWidgetHasParameters
        self.invalidLabel.visible = self.logic.errorDetected

    def __saveGeneratedReport(self) -> None:
        """Wrapper for the logic's saveGeneratedReport method."""
        try:
            self.logic.saveGeneratedReport(outputName=self.getOutputNodeName())
        except RuntimeError as error:
            logging.warning(error)
            slicer.util.errorDisplay(f"An error ocurred while saving the report to a node: {error}")

        self._resetWidgets()

    def enter(self) -> None:
        """Overwrite LTracePluginWidget enter method."""
        LTracePluginWidget.enter(self)

    def exit(self) -> None:
        """Overwrite LTracePluginWidget exit method."""
        self._cancelAnalysis()

    def _cancelAnalysis(self) -> None:
        """Cancel the current analysis."""
        if self.logic is None or not self.logic.generating:
            return

        self.logic.cancel()
        self._resetWidgets()

    def _resetWidgets(self) -> None:
        """Restore the widgets to their default state."""
        self.directoryInputPathLineEdit.setCurrentPath("")
        self._clearTable()
        self.outputName.setText("")

        selectedAnalysisType = self.analysisTypeComboBox.currentText
        analysisModel = self.getAnalysisModel(selectedAnalysisType)

        if analysisModel is None:
            return

        analysisModel.resetConfiguration()


class MultipleImageAnalysisLogic(LTracePluginLogic):
    processFinished = qt.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.__generating = False
        self.__generatedReportNodeId = None
        self.data = None
        self.__errorDetected = False
        self.__imageLogDataLogic = slicer.util.getModuleLogic("ImageLogData")

    @property
    def generating(self) -> bool:
        return self.__generating

    @property
    def errorDetected(self) -> bool:
        return self.__errorDetected

    def generate(self, data: Dict) -> None:
        """Generates the analysis

        Args:
            data (dict): The dictionary with the necessary information to generate the analysis
        """
        self.__errorDetected = False
        self.data = data

        try:
            self._run()
        except Exception as error:
            logging.info(f"Unable to generate analysis: {error}")
            self.__errorDetected = True
            self.processFinished.emit()
            return

        analysisModel = data.get("analysisModel")
        analysisModel.configModified.connect(self.__onModelConfigModified)
        self.__generating = True
        self.processFinished.emit()

    def _run(self, tableNode: slicer.vtkMRMLTableNode = None, displayImageLogView: bool = True) -> None:
        """Run the analysis.

        Args:
            tableNode (slicer.vtkMRMLTableNode, optional): The node that will be used as the output table. Defaults to None.
            displayImageLogView (bool, optional): If True, the analysis will be displayed in the image log view. Defaults to True.
        """

        path = self.data.get("path")
        name = self.data.get("name")
        analysisModel = self.data.get("analysisModel")

        report = analysisModel.run(path, name)
        if not report.data:
            raise ValueError("No analysis available for the selected path.")

        node = self._exportReportTableNode(report, tableNode)
        self.__generatedReportNodeId = node.GetID()

        # Show node in image log view
        if displayImageLogView:
            self.__imageLogDataLogic.changeToLayout()
            try:
                self.__imageLogDataLogic.addView(node)
            except Exception as error:
                slicer.util.warningDisplay(
                    f"The maximum number of views has been reached, preventing the current preview from being displayed.\nTo view the current analysis, please select the analysis node in an already open view."
                )
                logging.debug(error)

    def _exportReportTableNode(
        self, report: AnalysisReport, tableNode: slicer.vtkMRMLTableNode = None
    ) -> slicer.vtkMRMLTableNode:
        """Handle report export to a table node.

        Args:
            report (AnalysisReport): the AnalysisReport object.

        Returns:
            slicer.vtkMRMLTableNode: the output table report.
        """
        defaultOrientation = TableDataOrientation.ROW.value
        if isinstance(report.config, dict):
            orientation = report.config.get(TableDataOrientation.name(), defaultOrientation)
        else:
            orientation = defaultOrientation

        if tableNode is None:
            tableNode = helpers.createTemporaryNode(
                cls=slicer.vtkMRMLTableNode, name="Multiple Image Analysis Preview", hidden=True, uniqueName=False
            )
        else:
            tableNode.RemoveAllColumns()
            tableNode.GetTable().Initialize()
            tableNode.Modified()

        if orientation == TableDataOrientation.ROW.value:
            tableNode.SetUseColumnNameAsColumnHeader(True)
            tableNode.SetUseFirstColumnAsRowHeader(True)

            df = pd.DataFrame.from_dict(report.data, orient="index")
            df = df.sort_index(ascending=True)
            df = df.round(decimals=5)

            # Workaround to create a row header
            tableWasModified = tableNode.StartModify()
            headerArray = vtk.vtkStringArray()
            for header in list(df.index):
                headerArray.InsertNextValue(header)
            tableNode.AddColumn(headerArray)
            tableNode.Modified()

            tableNode.EndModify(tableWasModified)
            dataFrameToTableNode(dataFrame=df, tableNode=tableNode)
            # Rename first table's cell random name
        else:
            df = pd.DataFrame.from_dict(report.data)
            df = df.sort_values(by=df.columns[0], ascending=True)
            df = df.round(decimals=5)
            dataFrameToTableNode(dataFrame=df, tableNode=tableNode)

        for key, values in report.config.items():
            tableNode.SetAttribute(str(key), str(values))
        return tableNode

    def __onModelConfigModified(self) -> None:
        """Handle a modification from the analysis model configuration's parameter."""
        if not self.__generating or self.__generatedReportNodeId is None:
            return

        node = helpers.tryGetNode(self.__generatedReportNodeId)
        self._run(tableNode=node, displayImageLogView=False)

    def saveGeneratedReport(self, outputName: str = None) -> None:
        """Store the generated report to a permanent node.

        Args:
            outputName (str, optional): the permanent node name. Defaults to None, which will mantain the current name.

        Raises:
            RuntimeError: When the temporary node cannot be retrieved.
        """
        if not self.__generating or self.__generatedReportNodeId is None:
            return

        node = helpers.tryGetNode(self.__generatedReportNodeId)

        if not node:
            raise RuntimeError("Failed to retrieve generated report node.")

        helpers.makeTemporaryNodePermanent(node, show=True)
        if outputName:
            node.SetName(outputName)

        self._clear()
        self.processFinished.emit()

    def _clear(self) -> None:
        """Reinitialize attributes related to the process."""
        if self.data is not None:
            self.data["analysisModel"].configModified.disconnect(self.__onModelConfigModified)
            self.data = None

        self.__generating = False
        if self.__generatedReportNodeId is not None:
            try:
                self.__imageLogDataLogic.removeViewFromPrimaryNode(self.__generatedReportNodeId)
            except Exception as error:
                logging.error(f"{error}.\n{traceback.format_exc()}")

            self.__generatedReportNodeId = None

    def cancel(self) -> None:
        """Cancel the current process."""
        if not self.generating:
            return

        node = None
        if self.__generatedReportNodeId is not None:
            node = helpers.tryGetNode(self.__generatedReportNodeId)

        self._clear()

        # Remove node after clear to avoid synch problem with the ImageLog views
        if node:
            slicer.mrmlScene.RemoveNode(node)

        self.processFinished()
