import logging
import vtk, qt, ctk, slicer

from pathlib import Path
from Export import ExportLogic, checkUniqueNames
from ImageLogExportLib import ImageLogCSV
from ltrace.slicer.helpers import getNodeDataPath
from ltrace.slicer_utils import LTracePluginWidget
from ltrace.utils.recursive_progress import RecursiveProgress


class ImageLogExportOpenSourceWidget(LTracePluginWidget):
    EXPORT_DIR = "ImageLogExport/exportDir"
    IGNORE_DIR_STRUCTURE = "ImageLogExport/ignoreDirStructure"
    FORMAT_MATRIX_CSV = "CSV (matrix format)"
    FORMAT_TECHLOG_CSV = "CSV (Techlog format)"
    FORMAT_CSV = "CSV"

    EXPORTABLE_TYPES = (
        slicer.vtkMRMLSegmentationNode,
        slicer.vtkMRMLScalarVolumeNode,
        slicer.vtkMRMLTableNode,
        slicer.vtkMRMLLabelMapVolumeNode,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cancel = False
        self.cliCompleted = False
        self.auxNode = None
        self.moduleName = "ImageLogExport"

    def setup(self):
        LTracePluginWidget.setup(self)

        self.subjectHierarchyTreeView = slicer.qMRMLSubjectHierarchyTreeView()
        self.subjectHierarchyTreeView.setMRMLScene(slicer.app.mrmlScene())
        self.subjectHierarchyTreeView.header().setVisible(False)
        for i in range(2, 6):
            self.subjectHierarchyTreeView.hideColumn(i)
        self.subjectHierarchyTreeView.setEditMenuActionVisible(False)
        self.subjectHierarchyTreeView.setFocusPolicy(qt.Qt.NoFocus)

        self.logFormatBox = qt.QComboBox()
        self.logFormatBox.addItem(ImageLogExportOpenSourceWidget.FORMAT_MATRIX_CSV)
        self.logFormatBox.addItem(ImageLogExportOpenSourceWidget.FORMAT_TECHLOG_CSV)

        self.tableFormatBox = qt.QComboBox()
        self.tableFormatBox.addItem(ImageLogExportOpenSourceWidget.FORMAT_CSV)

        self.ignoreDirStructureCheckbox = qt.QCheckBox()
        self.ignoreDirStructureCheckbox.checked = (
            slicer.app.settings().value(self.IGNORE_DIR_STRUCTURE, "False") == "True"
        )
        self.ignoreDirStructureCheckbox.setToolTip(
            "Export all data ignoring the directory structure. Only one node with the same name and type will be exported."
        )

        self.directorySelector = ctk.ctkDirectoryButton()
        self.directorySelector.caption = "Export directory"
        self.directorySelector.directory = slicer.app.settings().value(
            self.EXPORT_DIR, Path(slicer.mrmlScene.GetRootDirectory()).parent
        )

        self.progressBar = qt.QProgressBar()
        self.progressBar.setValue(0)
        self.progressBar.hide()

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.hide()

        progressLayout = qt.QHBoxLayout()
        progressLayout.addWidget(self.progressBar)
        progressLayout.addWidget(self.cancelButton)

        self.exportButton = qt.QPushButton("Export")
        self.exportButton.setFixedHeight(40)
        self.exportButton.enabled = False

        self.exportButton.clicked.connect(self.onExportClicked)
        self.cancelButton.clicked.connect(self.onCancelClicked)
        self.subjectHierarchyTreeView.currentItemChanged.connect(self.onSelectionChanged)

        formatGroup = qt.QGroupBox()
        formatLayout = qt.QFormLayout(formatGroup)
        formatLayout.addRow("Well log:", self.logFormatBox)
        formatLayout.addRow("Table:", self.tableFormatBox)

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

        self.layout.addLayout(formLayout)

        self.layout.addStretch(1)

    def _startExport(self):
        self.progressBar.setValue(0)
        self.progressBar.show()
        self.cancelButton.show()
        self.cancel = False
        self.cancelButton.enabled = True
        self.exportButton.enabled = False

    def _stopExport(self):
        self.cancelButton.enabled = False
        self._updateNodesAndExportButton()

    def _updateNodesAndExportButton(self):
        items = vtk.vtkIdList()
        self.subjectHierarchyTreeView.currentItems(items)
        self.nodes = ExportLogic().getDataNodes(items, self.EXPORTABLE_TYPES)
        self.exportButton.enabled = self.nodes

    def onCliModified(self, caller, event, progressOutput):
        if caller.GetStatusString() == "Running":
            progressValue = caller.GetProgress()
            progressOutput.set_progress(progressValue / 100)
        else:
            if caller.GetStatusString() == "Completed":
                self.cliCompleted = True
            else:
                self.currentStatusLabel.text = "Export failed."
                logging.error(caller.GetErrorText())

            if self.auxNode is not None:
                slicer.mrmlScene.RemoveNode(self.auxNode)
                self.auxNode = None

    def onExportClicked(self):
        self.currentStatusLabel.text = "Exporting..."
        slicer.app.processEvents()

        checkUniqueNames(self.nodes)
        outputDir = self.directorySelector.directory
        ignoreDirStructure = self.ignoreDirStructureCheckbox.checked
        slicer.app.settings().setValue(self.EXPORT_DIR, outputDir)
        slicer.app.settings().setValue(self.IGNORE_DIR_STRUCTURE, str(ignoreDirStructure))

        self._startExport()

        # Separate nodes
        nodeToExportList = []
        for node in self.nodes:
            nodeToExportList.append(node)

        # Create progress management
        def progressCallback(progressValue):
            self.progressBar.setValue(progressValue * 100)

        baseProgress = RecursiveProgress(callback=progressCallback)
        progressList = []
        for node in nodeToExportList:
            progressList.append(baseProgress.create_sub_progress())

        # Export
        for node in nodeToExportList:
            nodeDir = Path(outputDir) if ignoreDirStructure else Path(outputDir) / getNodeDataPath(node).parent
            progress = progressList.pop()

            if type(node) is slicer.vtkMRMLTableNode:
                if self.tableFormatBox.currentText == ImageLogExportOpenSourceWidget.FORMAT_CSV:
                    ExportLogic().exportTable(node, outputDir, nodeDir, ExportLogic.TABLE_FORMAT_CSV)
                    progress.set_progress(1)
            else:
                if self.logFormatBox.currentText == ImageLogExportOpenSourceWidget.FORMAT_TECHLOG_CSV:
                    self.startLogToCsvExport(node, nodeDir, progress, isTechlog=True)
                elif self.logFormatBox.currentText == ImageLogExportOpenSourceWidget.FORMAT_MATRIX_CSV:
                    self.startLogToCsvExport(node, nodeDir, progress, isTechlog=False)

        self._stopExport()
        self.progressBar.setValue(100)
        self.currentStatusLabel.text = "Export complete"

    def onCancelClicked(self):
        self.cancel = True

    def onSelectionChanged(self, _):
        self._updateNodesAndExportButton()

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
