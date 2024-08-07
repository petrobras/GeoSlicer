import logging
import shutil
import subprocess
from pathlib import Path

import qt, slicer
import numpy as np
import pandas as pd
import DLISImportLib
from ltrace.image.optimized_transforms import DEFAULT_NULL_VALUE, handle_null_values
from ltrace.slicer import ui
from ltrace.slicer.helpers import highlight_error, remove_highlight
from ltrace.slicer.node_attributes import (
    ImageLogDataSelectable,
    TableType,
    TableDataOrientation,
    TableDataTypeAttribute,
)
from ltrace.slicer_utils import dataFrameToTableNode
from ltrace.utils.ProgressBarProc import ProgressBarProc
from .GeologConnectWidget import GeologConnectWidget, GEOLOG_SCRIPT_ERRORS, GeologScriptError


class GeologImportWidget(qt.QWidget):
    NO_WELL = "No Well Found"

    signalGeologDataFetched = qt.Signal(str, str, str, object)

    def __init__(self, parent=None):
        """
        Widget that allows the user to visualize the available data in a Geolog project and to import it into Geoslicer
        """
        super().__init__(parent)

        self.importedData = None
        self.setup()

    def setup(self):
        self.geologConnectWidget = GeologConnectWidget(prefix="import")
        self.geologConnectWidget.signalGeologData.connect(lambda geologData: self.onGeologDataFetched(geologData, True))

        self.wellComboBox = qt.QComboBox()
        self.wellComboBox.currentIndexChanged.connect(self._updateTable)
        self.wellComboBox.objectName = "Import Well Selector ComboBox"
        self.wellComboBox.setToolTip("Wells found in the Geolog Project")

        self.wellDiameter = ui.floatParam("")
        self.wellDiameter.setObjectName("Well Diameter Input")
        self.wellDiameter.objectName = "Import Well Diameter LineEdit"
        self.wellDiameter.setToolTip(
            "Diameter of the well in inches. This will be used to calculate the horizontal spacing of the imported data"
        )

        self.nullValuesListText = qt.QLineEdit()
        self.nullValuesListText.text = str(DEFAULT_NULL_VALUE)[1:-1]
        self.nullValuesListText.objectName = "Import Null Values LineEdit"
        self.nullValuesListText.setToolTip(
            "Values that represent null values. They will be changed to nan values during import."
        )

        self.tableView = DLISImportLib.DLISTableViewer()
        self.tableView.setMinimumHeight(500)
        self.tableView.loadClicked = self._onLoadClicked
        self.tableView.objectName = "dataTableView"

        self.status = qt.QLabel("Status: Idle")
        self.status.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        self.status.setWordWrap(True)

        layout = qt.QFormLayout()
        layout.addRow(self.geologConnectWidget)
        layout.addRow("", None)
        layout.addRow("Null values list:", self.nullValuesListText)
        layout.addRow("Well diameter (inches):", self.wellDiameter)
        layout.addRow("Well name:", self.wellComboBox)
        layout.addRow(self.tableView)
        layout.addRow(self.status)

        self.setLayout(layout)

        self.logic = GeologImportLogic()
        self._updateWellComboBox()

    def updateStatus(self, code=0, message="Finished!"):
        statusMessage = "Status: "
        if code:
            statusMessage = f"{statusMessage}Error code: {code} - "
            self.status.setStyleSheet("font-weight: bold; color: red")
        else:
            self.status.setStyleSheet("font-weight: bold; color: green")
        self.status.setText(f"{statusMessage}{message}")

    def checkRunState(self):
        if not self.wellDiameter.text:
            highlight_error(self.wellDiameter)
            return False
        else:
            remove_highlight(self.wellDiameter)

        if not self.nullValuesListText.text:
            highlight_error(self.nullValuesListText)
            return False
        else:
            remove_highlight(self.nullValuesListText)

        return True

    def _onLoadClicked(self, data):
        if not self.checkRunState():
            return

        geologPath, scriptPath = self.geologConnectWidget.getEnvs()
        well = self.wellComboBox.currentText
        setData = {}
        loadAsTable = {}
        loadAsLabelmap = {}
        for log in data:
            logicalFile = getattr(log, "logical_file")
            mnemonic = getattr(log, "mnemonic")
            asTable = getattr(log, "is_table")
            asLabelmap = getattr(log, "is_labelmap")

            if logicalFile not in setData:
                setData[logicalFile] = []
                loadAsTable[logicalFile] = {}
                loadAsLabelmap[logicalFile] = {}

            setData[logicalFile].append(mnemonic)
            loadAsTable[logicalFile][mnemonic] = asTable
            loadAsLabelmap[logicalFile][mnemonic] = asLabelmap

        with ProgressBarProc() as progressBar:
            try:
                for logical in setData:
                    self.logic.importGeologData(
                        logical,
                        setData[logical],
                        self.geologConnectWidget.projectComboBox.currentText,
                        well,
                        float(self.wellDiameter.text),
                        self.nullValuesListText.text,
                        loadAsTable[logical],
                        loadAsLabelmap[logical],
                        geologPath,
                        scriptPath,
                        self.importedData,
                    )
            except GeologScriptError as e:
                self.updateStatus(e.errorCode, e.errorMessage)
            else:
                self.updateStatus()

    def _updateTable(self):
        tableData = []
        if self.wellComboBox.currentText != "" and self.wellComboBox.currentText != self.NO_WELL:
            sets = self.importedData[self.wellComboBox.currentText]
        else:
            sets = None
        if sets:
            for setName, logs in sets.items():
                if logs:
                    for logName, attributes in logs.items():
                        tableData.append(
                            DLISImportLib.DLISImportLogic.ChannelMetadata(
                                logName,
                                attributes["comment"],
                                attributes["unit"],
                                attributes["sr"],
                                setName,
                                False,
                                False,
                                False,
                            )
                        )

            self.tableView.setDatabase(tableData)

    def onGeologDataFetched(self, geologData, emitToEnv=False):
        if geologData:
            self.importedData = geologData
        else:
            self.importedData = None

        self._updateWellComboBox()
        if emitToEnv:
            self.signalGeologDataFetched.emit(
                self.geologConnectWidget.geologInstalation.directory,
                self.geologConnectWidget.geologProjectsFolder.directory,
                self.geologConnectWidget.projectComboBox.currentText,
                geologData,
            )

    def _updateWellComboBox(self):
        self.wellComboBox.clear()
        if self.importedData:
            self.wellComboBox.enabled = True
            for well in self.importedData:
                self.wellComboBox.addItem(well)
        else:
            self.wellComboBox.addItem(self.NO_WELL)
            self.wellComboBox.enabled = False


class GeologImportLogic(object):
    def importGeologData(
        self,
        logicalFile,
        logList,
        project,
        wellName,
        wellDiameter,
        nullValueString,
        loadAsTable,
        loadAsLabelmap,
        geologPath,
        scriptPath,
        importedData,
    ):
        scriptPath = f"{scriptPath}/scriptImport.py"

        temporaryPath = Path(slicer.util.tempDirectory())

        args = [
            geologPath,
            "mod_python",
            scriptPath,
            "--project",
            project,
            "--well",
            wellName,
            "--set",
            logicalFile,
            "--log",
            *logList,
            "--tempPath",
            temporaryPath,
        ]

        try:
            self._runProcess(args)
        except subprocess.CalledProcessError as e:
            if GEOLOG_SCRIPT_ERRORS.get(e.returncode, -1) == -1:
                GeologScriptError(-1, GEOLOG_SCRIPT_ERRORS[-1])
            raise GeologScriptError(e.returncode, GEOLOG_SCRIPT_ERRORS[e.returncode]) from e
        else:
            self._readImportedData(
                wellName,
                wellDiameter,
                nullValueString,
                logicalFile,
                logList,
                loadAsTable,
                loadAsLabelmap,
                temporaryPath,
                importedData,
            )
        finally:
            self._cleanUp(temporaryPath)

    def _runProcess(self, args):
        proc = slicer.util.launchConsoleProcess(args)
        slicer.util.logProcessOutput(proc)
        logging.info(f"Import process still running: {proc.poll()}")

    def _readImportedData(
        self,
        well: str,
        wellDiameter: float,
        nullValueString: str,
        logicalFile: str,
        logList: list,
        loadAsTable: object,
        loadAsLabelmap: object,
        temporaryPath: str,
        importedData: object,
    ):
        for log in logList:
            data = np.load(f"{temporaryPath}/{log}.npy")
            if importedData[well][logicalFile][log]["repeat"] > 1 and not loadAsTable[log]:
                self._loadAsVolume(
                    well,
                    wellDiameter,
                    nullValueString,
                    data,
                    importedData[well][logicalFile][log],
                    log,
                    loadAsLabelmap[log],
                )
            else:
                self._loadAsTable(well, nullValueString, data, importedData[well][logicalFile][log], log)

    def _loadAsVolume(
        self, wellName, wellDiameterInches, nullValueString, logData, logAttributes, logName, loadAsLabelmap
    ):
        wellDiameter = wellDiameterInches * 25.4
        horizontalSpacing = (wellDiameter * np.pi) / logData.shape[1]

        top = float(logAttributes["top"])
        bottom = float(logAttributes["bottom"])
        imageOrigin = [wellDiameter * np.pi / 2, 0, -top * 1000]
        spacing = [horizontalSpacing, 0.48, (((bottom - top) * 1000) / (logData.shape[0] - 1))]

        nodeType = "vtkMRMLLabelMapVolumeNode" if loadAsLabelmap else "vtkMRMLScalarVolumeNode"

        unitString = f" [{logAttributes['unit']}]" if logAttributes["unit"] else ""
        nodeName = f"{wellName}_{logName}{unitString}"

        volume = slicer.mrmlScene.AddNewNodeByClass(nodeType, nodeName)

        nullValues = np.array(nullValueString.split(",")).astype(np.float32)
        if not loadAsLabelmap:
            nullValue = handle_null_values(logData, nullValues)
        else:
            for value in nullValues:
                logData[np.where(logData == value)] = 0
            nullValue = 0

        values3D = np.zeros((logData.shape[0], 1, logData.shape[1]))
        values3D[:, 0, :] = logData
        slicer.util.updateVolumeFromArray(volume, values3D)

        volume.SetAttribute("NullValue", str(nullValue))
        volume.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
        volume.SetIJKToRASDirections(-1, 0, 0, 0, -1, 0, 0, 0, -1)
        volume.SetOrigin(imageOrigin)
        volume.SetSpacing(spacing)

    def _loadAsTable(self, wellName, nullValueString, logData, logAttributes, logName):
        top = float(logAttributes["top"]) * 1000
        bottom = float(logAttributes["bottom"]) * 1000
        nullValues = np.array(nullValueString.split(",")).astype(np.float32)
        logValues = np.where(np.isin(logData, nullValues), np.nan, logData)

        df = pd.DataFrame(logValues.astype(float))

        depthCurve = np.linspace(top, bottom, num=logValues.shape[0])
        df.insert(0, "DEPTH", depthCurve.astype(float))

        tableNode = dataFrameToTableNode(dataFrame=df)

        unitString = f" [{logAttributes['unit']}]" if logAttributes["unit"] else ""
        nodeName = f"{wellName}_{logName}{unitString}"
        tableNode.SetName(nodeName)

        tableNode.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)

        if logValues.shape[1] > 1:
            tableNode.SetAttribute(TableType.name(), TableType.HISTOGRAM_IN_DEPTH.value)
            tableNode.SetAttribute(TableDataTypeAttribute.name(), TableDataTypeAttribute.IMAGE_2D.value)
            tableNode.SetAttribute(TableDataOrientation.name(), TableDataOrientation.ROW.value)
            tableNode.SetUseFirstColumnAsRowHeader(True)
            tableNode.SetUseColumnNameAsColumnHeader(True)

    def _cleanUp(self, temporaryPath):
        if temporaryPath.is_dir():
            shutil.rmtree(temporaryPath, ignore_errors=True)
