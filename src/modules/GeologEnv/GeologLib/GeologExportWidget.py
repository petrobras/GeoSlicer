import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import qt, ctk, slicer
import vtk
from ltrace.slicer import ui
from ltrace.slicer.helpers import highlight_error, remove_highlight
from ltrace.slicer.node_attributes import TableType
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.utils.ProgressBarProc import ProgressBarProc
from .GeologConnectWidget import GeologConnectWidget, GEOLOG_SCRIPT_ERRORS, GeologScriptError

NEW_WELL = "New Well"
NEW_SET = "New Set"
EXPORTABLE_TYPES = (
    slicer.vtkMRMLScalarVolumeNode,
    slicer.vtkMRMLTableNode,
    slicer.vtkMRMLLabelMapVolumeNode,
)


class GeologExportWidget(qt.QWidget):
    signalGeologDataFetched = qt.Signal(str, str, str, object)

    def __init__(self, parent=None):
        """
        Widget to let the user select data nodes and export them to Geolog
        """
        super().__init__(parent)

        self.geologData = None
        self.setup()

    def setup(self):

        self.geologConnectWidget = GeologConnectWidget(prefix="export")
        self.geologConnectWidget.signalGeologData.connect(lambda geologData: self.onGeologDataFetched(geologData, True))

        section = ctk.ctkCollapsibleButton()
        section.text = "Export to Geolog"
        section.collapsed = False

        layoutWell = qt.QHBoxLayout()
        layoutWell.setContentsMargins(0, 0, 0, 0)

        self.exportWellComboBox = qt.QComboBox()
        self.exportWellComboBox.setMinimumWidth(200)
        self.exportWellComboBox.currentIndexChanged.connect(self.onExportwellChanged)
        self.exportWellComboBox.objectName = "Export Well Selector ComboBox"

        self.wellName = qt.QLineEdit()
        self.wellName.placeholderText = "Type a well Name"
        self.wellName.objectName = "Export Well Name LineEdit"

        layoutWell.addWidget(self.exportWellComboBox)
        layoutWell.addWidget(self.wellName)

        self.exportWellWidget = qt.QWidget()
        self.exportWellWidget.setLayout(layoutWell)

        layoutSet = qt.QHBoxLayout()
        layoutSet.setContentsMargins(0, 0, 0, 0)

        self.newSetName = qt.QLineEdit()
        self.newSetName.placeholderText = "Type a set Name"
        self.newSetName.objectName = "Export Set Name LineEdit"

        self.overwriteCheckBox = qt.QCheckBox("Overwrite SET")
        self.overwriteCheckBox.objectName = "Export Allow Set Overwrite CheckBox"

        overwriteHelp = HelpButton(
            "If there is a set with the same name as the export set, checking this option will overwrite the set and its data in Geolog. If unchecked the export will terminate if a set with the same name is present."
        )

        layoutSet.addWidget(self.newSetName)
        layoutSet.addWidget(self.overwriteCheckBox)
        layoutSet.addWidget(overwriteHelp)

        self.exportSetWidget = qt.QWidget()
        self.exportSetWidget.setLayout(layoutSet)

        self.subjectHierarchyTreeView = slicer.qMRMLSubjectHierarchyTreeView()
        self.subjectHierarchyTreeView.setMRMLScene(slicer.app.mrmlScene())
        self.subjectHierarchyTreeView.header().setVisible(False)
        self.subjectHierarchyTreeView.nodeTypes = [exportable.__name__ for exportable in EXPORTABLE_TYPES]
        for i in range(2, 6):
            self.subjectHierarchyTreeView.hideColumn(i)
        self.subjectHierarchyTreeView.setEditMenuActionVisible(False)
        self.subjectHierarchyTreeView.contextMenuEnabled = False
        self.subjectHierarchyTreeView.setFocusPolicy(qt.Qt.NoFocus)
        self.subjectHierarchyTreeView.objectName = "Export Node Selector TreeView"
        self.subjectHierarchyTreeView.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)

        self.exportButton = ui.ApplyButton(
            onClick=self.onExportButtonClick, tooltip="Export the selected nodes to Geolog", enabled=True
        )
        self.exportButton.objectName = "Export Button"
        self.status = qt.QLabel("Status: Idle")
        self.status.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        self.status.setWordWrap(True)

        sectionLayout = qt.QFormLayout(section)
        sectionLayout.addRow(self.geologConnectWidget)
        sectionLayout.addRow("Choose a well:", self.exportWellWidget)
        sectionLayout.addRow("Choose a set:", self.exportSetWidget)
        sectionLayout.addRow(self.subjectHierarchyTreeView)
        sectionLayout.addRow(self.exportButton)
        sectionLayout.addRow(self.status)

        self.setLayout(sectionLayout)

        self.updateWellComboBox()

        self.logic = GeologExportLogic()

    def checkRunState(self):
        isValid = True
        if not self.newSetName.text:
            highlight_error(self.newSetName)
            isValid = False
        else:
            remove_highlight(self.newSetName)

        if not self.wellName.text:
            highlight_error(self.wellName)
            isValid = False
        else:
            remove_highlight(self.wellName)

        if not self._getNodesToExport():
            highlight_error(self.subjectHierarchyTreeView)
            isValid = False
        else:
            remove_highlight(self.subjectHierarchyTreeView)

        if not self.geologConnectWidget.checkEnvViability():
            isValid = False
            self.updateStatus(-1, GEOLOG_SCRIPT_ERRORS[-1])

        return isValid

    def updateStatus(self, code=0, message="Finished!"):
        statusMessage = "Status: "
        if code:
            statusMessage = f"{statusMessage}Error code: {code} - "
            self.status.setStyleSheet("font-weight: bold; color: red")
        else:
            self.status.setStyleSheet("font-weight: bold; color: green")
        self.status.setText(f"{statusMessage}{message}")

    def onGeologDataFetched(self, geologData, emitToEnv=False):
        self.geologData = geologData
        self.updateWellComboBox()
        if emitToEnv:
            self.signalGeologDataFetched.emit(
                self.geologConnectWidget.geologInstalation.directory,
                self.geologConnectWidget.geologProjectsFolder.directory,
                self.geologConnectWidget.projectComboBox.currentText,
                geologData,
            )

    def onExportwellChanged(self):
        if self.exportWellComboBox.currentText == NEW_WELL:
            self.wellName.enabled = True
            self.wellName.text = ""
        else:
            self.wellName.enabled = False
            self.wellName.text = self.exportWellComboBox.currentText

    def updateWellComboBox(self):
        self.exportWellComboBox.clear()
        self.exportWellComboBox.addItem(NEW_WELL)
        if self.geologData:
            for well in self.geologData:
                self.exportWellComboBox.addItem(well)

    def _checkNodesViability(self, nodes):
        spacing = set([])
        nodeType = set([])
        has3D = []
        for node in nodes:
            nodeType.add(node.__class__.__name__)
            if isinstance(node, slicer.vtkMRMLScalarVolumeNode):
                spacing.add(node.GetSpacing()[2])
                dimensions = node.GetImageData().GetDimensions()
                if all(axis > 1 for axis in dimensions):
                    has3D.append(node.GetName())

        if len(spacing) > 1 or (len(nodeType) > 1 and slicer.vtkMRMLLabelMapVolumeNode in nodeType):
            self.updateStatus(21, GEOLOG_SCRIPT_ERRORS[21])
            return False
        elif has3D:
            self.updateStatus(22, f"{GEOLOG_SCRIPT_ERRORS[22]} 3D nodes: {', '.join(has3D)}")
            return False

        return True

    def _getNodesToExport(self):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        items = vtk.vtkIdList()
        self.subjectHierarchyTreeView.currentItems(items)
        nodes = []
        for id in range(items.GetNumberOfIds()):
            itemId = items.GetId(id)
            dataNode = subjectHierarchyNode.GetItemDataNode(itemId)
            if dataNode is not None and type(dataNode) in EXPORTABLE_TYPES:
                nodes.append(dataNode)

        nodesAreValid = self._checkNodesViability(nodes)

        return nodes if nodesAreValid else []

    def onExportButtonClick(self):
        if not self.checkRunState():
            return

        exportNodes = self._getNodesToExport()
        if not exportNodes:
            return

        geologPath, scriptPath = self.geologConnectWidget.getEnvs()
        well = self.wellName.text
        logicalFile = self.newSetName.text

        overwrite = self.overwriteCheckBox.isChecked()

        with ProgressBarProc() as progressBar:
            try:
                self.logic.exportGeologData(
                    self.geologConnectWidget.projectComboBox.currentText,
                    well,
                    logicalFile,
                    exportNodes,
                    overwrite,
                    geologPath,
                    scriptPath,
                )
            except GeologScriptError as e:
                self.updateStatus(e.errorCode, e.errorMessage)
            else:
                self.updateStatus()


class GeologExportLogic(object):
    def exportGeologData(self, project, well, logicalFile, exportNodes, overwrite, geologPath, scriptPath):
        scriptPath = f"{scriptPath}/scriptExport.py"
        temporaryPath = Path(slicer.util.tempDirectory())

        if isinstance(exportNodes[0], slicer.vtkMRMLScalarVolumeNode):
            wrongTypeNodes = self._createVolumeExportFiles(exportNodes, temporaryPath)
        else:
            wrongTypeNodes = self._createTableExportFiles(exportNodes, temporaryPath)

        args = [
            geologPath,
            "mod_python",
            scriptPath,
            "--project",
            project,
            "--well",
            well,
            "--set",
            logicalFile,
            "--overwrite",
            str(1 if overwrite else 0),
            "--tempPath",
            temporaryPath,
        ]

        try:
            self._runProcess(args)
        except subprocess.CalledProcessError as e:
            if GEOLOG_SCRIPT_ERRORS.get(e.returncode, -1) == -1:
                raise GeologScriptError(-1, GEOLOG_SCRIPT_ERRORS[-1])
            raise GeologScriptError(e.returncode, GEOLOG_SCRIPT_ERRORS[e.returncode]) from e
        else:
            if wrongTypeNodes:
                GeologScriptError(23, f"{GEOLOG_SCRIPT_ERRORS[23]} Nodes: {', '.join(wrongTypeNodes)}")
        finally:
            self._cleanUp(temporaryPath)

    def _cleanUp(self, temporaryPath):
        if temporaryPath.is_dir():
            shutil.rmtree(temporaryPath, ignore_errors=True)

    def _runProcess(self, args):
        proc = slicer.util.launchConsoleProcess(args)
        slicer.util.logProcessOutput(proc)
        logging.info(f"Export process still running: {proc.poll()}")

    def _createBinaryFile(self, node, logName, temporaryPath):
        if isinstance(node, slicer.vtkMRMLTableNode):
            df = slicer.util.dataframeFromTable(node)
            arr = np.array(df)[:, 1:]
            if node.GetAttribute(TableType.name()) == TableType.POROSITY_PER_REALIZATION.value:
                arr = np.reshape(np.mean(arr, axis=1), (-1, 1))
        else:
            arr = slicer.util.arrayFromVolume(node)[:, 0, :]
            nullValue = node.GetAttribute("NullValue")
            if nullValue:
                arr[arr == float(nullValue)] = -9999
            arr[np.isnan(arr)] = -9999

        file = f"{temporaryPath}/{logName}.npy"
        if not Path(file).is_file():
            np.save(file, arr)

    def _getNameAndUnit(self, name):
        pattern = r"\[(.*?)\]"
        outputString = re.split(pattern, name)
        logName = outputString[0].strip()

        unit = None
        if len(outputString) > 1:
            unit = outputString[1]

        return logName, unit

    def _createTableExportFiles(self, exportNodes, temporaryPath):
        logsAttributes = {}
        wrongTypeNodes = []
        for node in exportNodes:
            if not isinstance(node, slicer.vtkMRMLTableNode):
                wrongTypeNodes.append(node.GetName())
                continue

            logName, unit = self._getNameAndUnit(node.GetName())

            self._createBinaryFile(node, logName, temporaryPath)
            logsAttributes[logName] = self.getNodeAttributes(node, unit)

        self._saveAttributesJson(logsAttributes, "table", temporaryPath)

        return wrongTypeNodes

    def _createVolumeExportFiles(self, exportNodes, temporaryPath):
        logsAttributes = {}
        wrongTypeNodes = []
        for node in exportNodes:
            if not isinstance(node, slicer.vtkMRMLScalarVolumeNode):
                wrongTypeNodes.append(node.GetName())
                continue

            browserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(node)
            if browserNode:
                sequenceNode = browserNode.GetSequenceNode(node)

            logName, unit = self._getNameAndUnit(node.GetName())

            if browserNode:
                for image in range(sequenceNode.GetNumberOfDataNodes()):
                    nthNode = sequenceNode.GetNthDataNode(image)
                    nthName = f"{logName}_r{image}"
                    self._createBinaryFile(nthNode, nthName, temporaryPath)
                    logsAttributes[nthName] = self.getNodeAttributes(nthNode, unit)
            else:
                self._createBinaryFile(node, logName, temporaryPath)
                logsAttributes[logName] = self.getNodeAttributes(node, unit)

        self._saveAttributesJson(logsAttributes, "volume", temporaryPath)

        return wrongTypeNodes

    def _saveAttributesJson(self, logsAttributes, nodeType, temporaryPath):
        depthTop = np.inf
        depthBottom = 0
        depthIncrement = 0
        for key in logsAttributes.keys():
            if logsAttributes[key]["top"] < depthTop:
                depthTop = logsAttributes[key]["top"]
            if logsAttributes[key]["bottom"] > depthBottom:
                depthBottom = logsAttributes[key]["bottom"]
            depthIncrement = logsAttributes[key]["spacing"]

        depthLog = {
            "name": "DEPTH",
            "top": depthTop,
            "bottom": depthBottom,
            "spacing": depthIncrement,
            "type": "DOUBLE",
            "unit": "METRES",
        }

        exportJson = {"nodeType": nodeType, "reference": depthLog, "logs": logsAttributes}

        with open(f"{temporaryPath}/attributes.json", "w", encoding="utf-8") as f:
            json.dump(exportJson, f, ensure_ascii=False, indent=4)

    def getNodeAttributes(self, node, unit=None):
        if isinstance(node, slicer.vtkMRMLTableNode):
            df = slicer.util.dataframeFromTable(node)
            arr = np.array(df)

            unitConversion = 1000
            if node.GetAttribute(TableType.name()) == TableType.POROSITY_PER_REALIZATION.value:
                unitConversion = 1

            top = arr[0, 0] / unitConversion
            bottom = arr[-1, 0] / unitConversion
            height = arr.shape[0]
            verticalSpacing = (bottom - top) / (height - 1)

        else:
            origins = -np.round(node.GetOrigin(), 5) / 1000
            spacings = np.round(node.GetSpacing(), 5) / 1000
            dimensions = np.array(node.GetImageData().GetDimensions())
            top = origins[2]
            bottom = origins[2] + dimensions[2] * spacings[2]
            height = dimensions[2]
            verticalSpacing = spacings[2]

        nodeAttributes = {
            "top": top,
            "bottom": bottom,
            "height": int(height),
            "spacing": float(verticalSpacing),
            "type": "REAL" if isinstance(node, slicer.vtkMRMLLabelMapVolumeNode) else "DOUBLE",
        }

        nodeAttributes["unit"] = unit

        return nodeAttributes
