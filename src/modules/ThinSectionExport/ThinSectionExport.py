import os
import qt
import slicer
import ctk
import vtk
from ltrace.slicer.helpers import getNodeDataPath
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from pathlib import Path
from Export import ExportLogic, checkUniqueNames


class ThinSectionExport(LTracePlugin):
    SETTING_KEY = "ThinSectionExport"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    FORMAT_PNG = "PNG"
    FORMAT_TIF = "TIF"

    FORMAT_CSV = "CSV"
    FORMAT_LAS = "LAS"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Thin Section Export"
        self.parent.categories = ["Thin Section"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = ThinSectionExport.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ThinSectionExportWidget(LTracePluginWidget):
    EXPORT_DIR = "exportDir"
    IGNORE_DIR_STRUCTURE = "ignoreDirStructure"

    EXPORTABLE_TYPES = (
        slicer.vtkMRMLSegmentationNode,
        slicer.vtkMRMLVectorVolumeNode,
        slicer.vtkMRMLLabelMapVolumeNode,
        slicer.vtkMRMLTableNode,
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = ThinSectionExportLogic()

    def setup(self):
        LTracePluginWidget.setup(self)

        self.subjectHierarchyTreeView = slicer.qMRMLSubjectHierarchyTreeView()
        self.subjectHierarchyTreeView.setMRMLScene(slicer.app.mrmlScene())
        self.subjectHierarchyTreeView.header().setVisible(False)
        for i in range(2, 6):
            self.subjectHierarchyTreeView.hideColumn(i)
        self.subjectHierarchyTreeView.setEditMenuActionVisible(False)
        self.subjectHierarchyTreeView.setFocusPolicy(qt.Qt.NoFocus)

        self.imageFormatBox = qt.QComboBox()
        self.imageFormatBox.addItem(ThinSectionExport.FORMAT_PNG)
        self.imageFormatBox.addItem(ThinSectionExport.FORMAT_TIF)

        self.tableFormatBox = qt.QComboBox()
        self.tableFormatBox.addItem(ThinSectionExport.FORMAT_CSV)
        self.tableFormatBox.addItem(ThinSectionExport.FORMAT_LAS)

        self.ignoreDirStructureCheckbox = qt.QCheckBox()
        self.ignoreDirStructureCheckbox.checked = (
            ThinSectionExport.get_setting(self.IGNORE_DIR_STRUCTURE, "True") == "True"
        )
        self.ignoreDirStructureCheckbox.setToolTip(
            "Export all data ignoring the directory structure. Only one node with the same name and type will be exported."
        )

        self.directorySelector = ctk.ctkDirectoryButton()
        self.directorySelector.caption = "Export directory"
        self.directorySelector.directory = ThinSectionExport.get_setting(
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

        self.statusLabel = qt.QLabel()

        self.exportButton = qt.QPushButton("Export")
        self.exportButton.setFixedHeight(40)
        self.exportButton.enabled = False

        self.exportButton.clicked.connect(self.onExportClicked)
        self.cancelButton.clicked.connect(self.onCancelClicked)
        self.subjectHierarchyTreeView.currentItemChanged.connect(self.onSelectionChanged)

        formatGroup = qt.QGroupBox()
        formatLayout = qt.QFormLayout(formatGroup)
        formatLayout.addRow("Image:", self.imageFormatBox)
        formatLayout.addRow("Table:", self.tableFormatBox)

        formLayout = qt.QFormLayout()
        formLayout.addRow(self.subjectHierarchyTreeView)
        formLayout.addRow("Ignore directory structure:", self.ignoreDirStructureCheckbox)
        formLayout.addRow("Export directory:", self.directorySelector)
        formLayout.addRow("Export format:", formatGroup)
        formLayout.addRow(progressLayout)
        formLayout.addRow(self.statusLabel)
        formLayout.addRow(self.exportButton)

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

    def onExportClicked(self):
        checkUniqueNames(self.nodes)
        outputDir = self.directorySelector.directory
        ignoreDirStructure = self.ignoreDirStructureCheckbox.checked
        imageFormat = self.imageFormatBox.currentText
        tableFormat = self.tableFormatBox.currentText

        ThinSectionExport.set_setting(self.EXPORT_DIR, outputDir)
        ThinSectionExport.set_setting(self.IGNORE_DIR_STRUCTURE, str(ignoreDirStructure))

        self._startExport()

        self.progressBar.setValue(0)
        slicer.app.processEvents()
        try:
            for i, node in enumerate(self.nodes):
                self.progressBar.setValue(round(100 * (i / len(self.nodes))))
                self.statusLabel.text = f'Exporting "{node.GetName()}"'
                slicer.app.processEvents()
                self.logic.export(node, outputDir, ignoreDirStructure, imageFormat, tableFormat)
                if self.cancel:
                    self.statusLabel.text = "Export canceled"
                    self._stopExport()
                    return
        except Exception as exc:
            slicer.util.errorDisplay(f"Export failed.\n{exc}")
            self.statusLabel.text = "Export failed"
            self._stopExport()
            raise exc

        if len(self.nodes) == 1:
            self.statusLabel.text = f'"{self.nodes[0].GetName()}"'
        else:
            self.statusLabel.text = f"{len(self.nodes)} files"
        self.statusLabel.text += " exported successfully"
        self.progressBar.setValue(100)
        self._stopExport()

    def onCancelClicked(self):
        self.cancel = True

    def onSelectionChanged(self, _):
        self._updateNodesAndExportButton()


class ThinSectionExportLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def export(self, node, outputDir, ignoreDirStructure, imageFormat, tableFormat):
        logic = ExportLogic()
        nodeDir = Path(outputDir) if ignoreDirStructure else Path(outputDir) / getNodeDataPath(node).parent
        if isinstance(node, slicer.vtkMRMLSegmentationNode):
            format_ = {
                ThinSectionExport.FORMAT_PNG: ExportLogic.SEGMENTATION_FORMAT_PNG,
                ThinSectionExport.FORMAT_TIF: ExportLogic.SEGMENTATION_FORMAT_TIF,
            }[imageFormat]
            logic.exportSegmentation(node, outputDir, nodeDir, format_)
        elif isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
            format_ = {
                ThinSectionExport.FORMAT_PNG: ExportLogic.LABEL_MAP_FORMAT_PNG,
                ThinSectionExport.FORMAT_TIF: ExportLogic.LABEL_MAP_FORMAT_TIF,
            }[imageFormat]
            logic.exportLabelMap(node, outputDir, nodeDir, format_)
        elif isinstance(node, slicer.vtkMRMLScalarVolumeNode):
            format_ = {
                ThinSectionExport.FORMAT_PNG: ExportLogic.IMAGE_FORMAT_PNG,
                ThinSectionExport.FORMAT_TIF: ExportLogic.IMAGE_FORMAT_TIF,
            }[imageFormat]
            logic.exportImage(node, outputDir, nodeDir, format_)
        elif isinstance(node, slicer.vtkMRMLTableNode):
            format_ = {
                ThinSectionExport.FORMAT_CSV: ExportLogic.TABLE_FORMAT_CSV,
                ThinSectionExport.FORMAT_LAS: ExportLogic.TABLE_FORMAT_LAS,
            }[tableFormat]
            logic.exportTable(node, outputDir, nodeDir, format_)
