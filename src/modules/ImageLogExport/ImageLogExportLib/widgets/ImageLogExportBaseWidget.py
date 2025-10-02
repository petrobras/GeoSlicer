import logging
import os
import re
import ctk
import qt
import slicer
import vtk
import traceback

from ImageLogExportLib import ImageLogCSV

import ltrace.image.las as imglas
from ltrace.slicer import export
from ltrace.image.dlis import extract_dlis_info_from_node, export_dlis
from ltrace.slicer.helpers import (
    createTemporaryNode,
    getNodeDataPath,
    getSourceVolume,
    removeTemporaryNodes,
    checkUniqueNames,
    tryGetNode,
)
from ltrace.slicer.node_attributes import NodeEnvironment, TableType
from ltrace.utils.ProgressBarProc import ProgressBarProc
from ltrace.utils.recursive_progress import RecursiveProgress
from pathlib import Path
from .output_name_dialog import OutputNameDialog


class ImageLogExportBaseWidget(qt.QWidget):
    EXPORT_DIR = "ImageLogExport/exportDir"
    IGNORE_DIR_STRUCTURE = "ImageLogExport/ignoreDirStructure"
    FORMAT_MATRIX_CSV = "CSV (matrix format)"
    FORMAT_TECHLOG_CSV = "CSV (Techlog format)"
    FORMAT_CSV = "CSV"
    FORMAT_LAS = "LAS"
    FORMAT_DLIS = "DLIS"
    FORMAT_LAS_GEOLOG = "LAS (for Geolog)"

    EXPORTABLE_TYPES = (
        slicer.vtkMRMLSegmentationNode,
        slicer.vtkMRMLScalarVolumeNode,
        slicer.vtkMRMLTableNode,
        slicer.vtkMRMLLabelMapVolumeNode,
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.cancel = False
        self.cliCompleted = False
        self.auxNode = None
        self.moduleName = "ImageLogExport"
        self.nodes = []

        self.setup()

    def setup(self):
        self.subjectHierarchyTreeView = slicer.qMRMLSubjectHierarchyTreeView()
        self.subjectHierarchyTreeView.objectName = "Tree View"
        self.subjectHierarchyTreeView.setMRMLScene(slicer.app.mrmlScene())
        self.subjectHierarchyTreeView.header().setVisible(False)
        for i in range(2, 6):
            self.subjectHierarchyTreeView.hideColumn(i)
        self.subjectHierarchyTreeView.setEditMenuActionVisible(False)
        self.subjectHierarchyTreeView.setFocusPolicy(qt.Qt.NoFocus)

        self.logFormatBox = qt.QComboBox()
        self.logFormatBox.objectName = "Log Format ComboBox"
        self.logFormatBox.addItem(ImageLogExportBaseWidget.FORMAT_DLIS)
        self.logFormatBox.addItem(ImageLogExportBaseWidget.FORMAT_MATRIX_CSV)
        self.logFormatBox.addItem(ImageLogExportBaseWidget.FORMAT_TECHLOG_CSV)
        self.logFormatBox.addItem(ImageLogExportBaseWidget.FORMAT_LAS)
        self.logFormatBox.addItem(ImageLogExportBaseWidget.FORMAT_LAS_GEOLOG)

        self.tableFormatBox = qt.QComboBox()
        self.tableFormatBox.objectName = "Table Format ComboBox"
        self.tableFormatBox.addItem(ImageLogExportBaseWidget.FORMAT_CSV)

        self.ignoreDirStructureCheckbox = qt.QCheckBox()
        self.ignoreDirStructureCheckbox.objectName = "Ignore Structure CheckBox"
        self.ignoreDirStructureCheckbox.checked = (
            slicer.app.settings().value(self.IGNORE_DIR_STRUCTURE, "False") == "True"
        )
        self.ignoreDirStructureCheckbox.setToolTip(
            "Export all data ignoring the directory structure. Only one node with the same name and type will be exported."
        )

        self.directorySelector = ctk.ctkDirectoryButton()
        self.directorySelector.objectName = "Directory Selector"
        self.directorySelector.caption = "Export directory"
        self.directorySelector.directory = slicer.app.settings().value(
            self.EXPORT_DIR, Path(slicer.mrmlScene.GetRootDirectory()).parent
        )
        self.directorySelector.setMaximumWidth(374)

        self.associatedDataLabel = qt.QLabel("Associated Data:")
        self.associatedDataLabel.hide()
        self.associatedDataGroup = qt.QGroupBox()
        self.associatedDataGroup.hide()
        associatedDataLayout = qt.QFormLayout(self.associatedDataGroup)

        self.exportProportionsCheckBox = qt.QCheckBox("Proportions")
        self.exportProportionsCheckBox.objectName = "Proportions CheckBox"
        associatedDataLayout.addWidget(self.exportProportionsCheckBox)

        self.progressBar = qt.QProgressBar()
        self.progressBar.setValue(0)
        self.progressBar.hide()

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.hide()

        progressLayout = qt.QHBoxLayout()
        progressLayout.addWidget(self.progressBar)
        progressLayout.addWidget(self.cancelButton)

        self.exportButton = qt.QPushButton("Export")
        self.exportButton.objectName = "Export Button"
        self.exportButton.setFixedHeight(40)
        self.exportButton.enabled = False

        self.exportButton.clicked.connect(self.onExportClicked)
        self.cancelButton.clicked.connect(self.onCancelClicked)
        self.subjectHierarchyTreeView.currentItemChanged.connect(self.onSelectionChanged)

        formatGroup = qt.QGroupBox()
        formatLayout = qt.QFormLayout(formatGroup)
        formatLayout.addRow("Well log:", self.logFormatBox)
        formatLayout.addRow("Table:", self.tableFormatBox)
        formatLayout.addRow(self.associatedDataLabel, self.associatedDataGroup)

        formLayout = qt.QFormLayout()
        formLayout.addRow(self.subjectHierarchyTreeView)
        formLayout.addRow("Ignore directory structure:", self.ignoreDirStructureCheckbox)
        formLayout.addRow("Export directory:", self.directorySelector)
        formLayout.addRow("Export format:", formatGroup)
        formLayout.addRow(self.exportButton)
        formLayout.addRow(progressLayout)

        statusLabel = qt.QLabel("Status: ")
        self.currentStatusLabel = qt.QLabel("Idle")
        statusHBoxLayout = qt.QHBoxLayout()
        statusHBoxLayout.addStretch(1)
        statusHBoxLayout.addWidget(statusLabel)
        statusHBoxLayout.addWidget(self.currentStatusLabel)
        formLayout.addRow(statusHBoxLayout)

        layout = qt.QVBoxLayout()
        layout.addLayout(formLayout)
        layout.addStretch(1)

        self.setLayout(layout)

    def _startExport(self):
        self.progressBar.setValue(0)
        self.progressBar.show()
        self.cancelButton.show()
        self.cancel = False
        self.cancelButton.enabled = True
        self.exportButton.enabled = False

    def _stopExport(self):
        self.cancelButton.enabled = False
        self.onSelectionChanged(None)
        self._cleanUp()

    def _checkSelectedNodes(self):
        items = vtk.vtkIdList()
        self.subjectHierarchyTreeView.currentItems(items)
        return export.getDataNodes(items, self.EXPORTABLE_TYPES)

    def _updateAssociatedDataWidget(self, nodes):
        if nodes:
            for node in nodes:
                if type(node) is slicer.vtkMRMLSegmentationNode:
                    if tryGetNode(f"{node.GetName()}_Proportions") is not None:
                        self.associatedDataGroup.show()
                        self.associatedDataLabel.show()
                        return

        self.associatedDataGroup.hide()
        self.associatedDataLabel.hide()
        self.exportProportionsCheckBox.setChecked(qt.Qt.Unchecked)

    def _addProportionsToExport(self):
        if self.nodes:
            for node in self.nodes:
                if type(node) is slicer.vtkMRMLSegmentationNode:
                    proportionNode = tryGetNode(f"{node.GetName()}_Proportions")
                    if proportionNode is not None:
                        self.nodes.append(proportionNode)

    def onExportClicked(self):
        self.currentStatusLabel.text = "Exporting..."
        slicer.app.processEvents()

        self.nodes = self._checkSelectedNodes()

        checkUniqueNames(self.nodes)
        outputDir = self.directorySelector.directory
        ignoreDirStructure = self.ignoreDirStructureCheckbox.checked
        slicer.app.settings().setValue(self.EXPORT_DIR, outputDir)
        slicer.app.settings().setValue(self.IGNORE_DIR_STRUCTURE, str(ignoreDirStructure))

        if self.exportProportionsCheckBox.isChecked():
            self._addProportionsToExport()

        self._startExport()

        # Separate nodes
        nodeToExportList = []
        nodeToDlisList = []
        nodeToLASList = []
        for node in self.nodes:
            if (
                type(node) is slicer.vtkMRMLTableNode
                or self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_MATRIX_CSV
                or self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_TECHLOG_CSV
            ):
                nodeToExportList.append(node)
            if (
                self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_LAS
                or self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_LAS_GEOLOG
            ):
                nodeToLASList.append(node)
            elif self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_DLIS:
                nodeToDlisList.append(node)

        # Create progress management
        def progressCallback(progressValue):
            self.progressBar.setValue(progressValue * 100)

        baseProgress = RecursiveProgress(callback=progressCallback)
        progressList = []
        dlisProgress = None
        lasProgress = None
        for node in nodeToExportList:
            progressList.append(baseProgress.create_sub_progress())
        if len(nodeToDlisList) > 0:
            dlisProgress = baseProgress.create_sub_progress(weight=len(nodeToDlisList))
        if len(nodeToLASList) > 0:
            lasProgress = baseProgress.create_sub_progress(weight=len(nodeToLASList))

        # Export
        for node in nodeToExportList:
            nodeDir = Path(outputDir) if ignoreDirStructure else Path(outputDir) / getNodeDataPath(node).parent
            progress = progressList.pop()

            if type(node) is slicer.vtkMRMLTableNode:
                if node.GetAttribute(TableType.name()) == TableType.HISTOGRAM_IN_DEPTH.value:
                    if self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_MATRIX_CSV:
                        self.startLogToCsvExport(node, nodeDir, progress, isTechlog=False)
                    else:
                        if node in nodeToLASList:
                            logging.warning(
                                f"If you want {node.GetName()} to be exported in a separated CSV file, select {ImageLogExportBaseWidget.FORMAT_MATRIX_CSV} option in the Well log and export again."
                            )
                        else:
                            logging.warning(
                                f"{node.GetName()} not exported as CSV. Please select {ImageLogExportBaseWidget.FORMAT_MATRIX_CSV} option and try to export it again."
                            )
                else:
                    if self.tableFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_CSV:
                        export.exportTable(node, outputDir, nodeDir, export.TABLE_FORMAT_CSV)
                        progress.set_progress(1)
            else:
                if self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_TECHLOG_CSV:
                    self.startLogToCsvExport(node, nodeDir, progress, isTechlog=True)
                elif self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_MATRIX_CSV:
                    self.startLogToCsvExport(node, nodeDir, progress, isTechlog=False)
                elif self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_DLIS:
                    raise RuntimeError("Node selection went wrong")
                elif (
                    self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_LAS
                    or self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_LAS_GEOLOG
                ):
                    raise RuntimeError("Node selection went wrong")

        if self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_DLIS and len(nodeToDlisList):
            with ProgressBarProc() as progressBarProc:
                progressBarProc.nextStep(5, "Starting to export DLIS...")
                try:
                    self.startDlisExport(nodeToDlisList, outputDir, dlisProgress)
                except RuntimeError as e:
                    logging.error(e)
                    self._stopExport()
                    self.progressBar.setValue(0)
                    self.currentStatusLabel.text = "Export failed!"
                    progressBarProc.nextStep(0, "Error exporting DLIS data.")
                    return
                progressBarProc.nextStep(100, "DLIS export completed")
        elif (
            self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_LAS
            or self.logFormatBox.currentText == ImageLogExportBaseWidget.FORMAT_LAS_GEOLOG
        ) and len(nodeToLASList):

            with ProgressBarProc() as progressBarProc:
                progressBarProc.nextStep(5, "Starting to export LAS...")
                try:
                    self.startLasExport(nodeToLASList, outputDir, lasProgress)
                except RuntimeError as e:
                    logging.error(f"{e}.\n{traceback.format_exc()}")
                    self._stopExport()
                    self.progressBar.setValue(0)
                    self.currentStatusLabel.text = "Export failed!"
                    progressBarProc.nextStep(0, "Error exporting LAS data.")
                    return
                progressBarProc.nextStep(100, "LAS export completed.")

        self._stopExport()
        self.progressBar.setValue(100)
        self.currentStatusLabel.text = "Export complete"

    def preExport(self, node_list):
        # Get file ID
        nodePath = Path()
        fileId = ""
        if len(node_list) == 1:
            fileId = node_list[0].GetName()
            nodePath = self.__getNodeDirectoryPath(node_list[0])
        elif len(node_list) > 0:
            directoryName = self.__getNodeDirectoryName(node_list[0])
            askForOutputName = False
            for node in node_list:
                newDirectoryName = self.__getNodeDirectoryName(node)
                directoryPath = self.__getNodeDirectoryPath(node_list[0])
                if directoryName != newDirectoryName:
                    askForOutputName = True
                    break
            if askForOutputName:
                outputNameDialog = OutputNameDialog(self)
                result = outputNameDialog.exec()
                if bool(result):
                    fileId = outputNameDialog.getOutputName()
                else:
                    return None, None
            else:
                nodePath = directoryPath
                fileId = directoryName

        fileId = re.sub(r"[\\/*.<>ç?:]", "_", fileId)  # avoiding characters not suitable for file name

        return nodePath, fileId

    def startLasExport(self, node_list, output_dir, progressOutput):
        nodePath, fileId = self.preExport(node_list)
        if not nodePath:
            return False
        outputDir = Path(output_dir)
        tempDir = slicer.app.temporaryPath + "/imagelogexport/"
        if not os.path.exists(tempDir):
            os.makedirs(tempDir)

        if not self.ignoreDirStructureCheckbox.checked:
            outpuPath = outputDir / nodePath
        else:
            outpuPath = outputDir
        outpuPath.mkdir(parents=True, exist_ok=True)

        outputFilePath: Path = outpuPath / f"{fileId}.las"
        outputFilePathStr: str = outputFilePath.as_posix()

        # "FORMAT_LAS_GEOLOG" is in fact an initial support to LAS 3.0
        version = 2 if self.logFormatBox.currentText != ImageLogExportBaseWidget.FORMAT_LAS_GEOLOG else 3

        try:
            imglas.export_las(node_list, outputFilePathStr, version=version)
        except RuntimeError as e:
            raise RuntimeError(e)
        finally:
            removeTemporaryNodes(NodeEnvironment.IMAGE_LOG)

        return True

    def startDlisExport(self, nodeList, outputDir, progressOutput):
        nodePath, fileId = ImageLogExportBaseWidget.preExport(self, nodeList)
        if not nodePath:
            return False
        outputDir = Path(outputDir)
        tempDir = Path(slicer.app.temporaryPath) / "imagelogexport/"
        if not os.path.exists(tempDir):
            os.makedirs(tempDir)

        if not self.ignoreDirStructureCheckbox.checked:
            outputPath = outputDir / nodePath
        else:
            outputPath = outputDir
        outputPath.mkdir(parents=True, exist_ok=True)

        file_name_no_extension = fileId

        try:
            export_dlis(
                nodeList,
                outputPath,
                file_name_no_extension,
                tempDir,
            )
        except RuntimeError as e:
            raise RuntimeError(e)
        finally:
            removeTemporaryNodes(NodeEnvironment.IMAGE_LOG)

        return True

    def onCancelClicked(self):
        self.cancel = True

    def onSelectionChanged(self, _):
        nodes = self._checkSelectedNodes()
        self._updateAssociatedDataWidget(nodes)
        self.exportButton.setEnabled(True if nodes else False)

    def startLogToCsvExport(self, node, nodeDir, progressOutput, isTechlog):
        task = ImageLogCSV.exportCSV(node, nodeDir, isTechlog)
        try:
            for progress in task:
                progressOutput.set_progress(progress)
                if self.cancel:
                    self._stopExport()
                    return
        except Exception as exc:
            self._stopExport()
            self.currentStatusLabel.text = "Export failed."
            raise exc

    def _cleanUp(self):
        del self.nodes
        self.nodes = []

    @staticmethod
    def __getNodeDirectoryName(node):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(node))
        directoryName = subjectHierarchyNode.GetItemName(itemParent)
        return directoryName

    @staticmethod
    def __getNodeDirectoryPath(node):
        directoryPath = Path()
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        sceneItemId = subjectHierarchyNode.GetSceneItemID()
        itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(node))
        while itemParent != 0 and itemParent != sceneItemId:
            directoryPath = Path(subjectHierarchyNode.GetItemName(itemParent)) / directoryPath
            itemParent = subjectHierarchyNode.GetItemParent(itemParent)
        return directoryPath
