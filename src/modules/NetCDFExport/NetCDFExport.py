import os

import qt
import slicer
import vtk
import ctk

from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget
from ltrace.slicer import ui, export
from pathlib import Path
from ltrace.slicer.helpers import save_path

from ltrace.slicer import netcdf
from ltrace.utils.callback import Callback


def findChildDataNodes(parentItemIds, exportableTypes):
    sh = slicer.mrmlScene.GetSubjectHierarchyNode()
    foundNodes = []
    processedItemIds = set()
    exportableTypesSet = set(exportableTypes)

    def _findNodesRecursively(itemId):
        """A nested helper function to perform the recursion."""
        if itemId in processedItemIds:
            return
        processedItemIds.add(itemId)

        dataNode = sh.GetItemDataNode(itemId)
        if dataNode and type(dataNode) in exportableTypesSet:
            foundNodes.append(dataNode)

        children = vtk.vtkIdList()
        sh.GetItemChildren(itemId, children, False)

        for i in range(children.GetNumberOfIds()):
            childId = children.GetId(i)
            _findNodesRecursively(childId)

    sceneItemId = sh.GetSceneItemID()
    for i in range(parentItemIds.GetNumberOfIds()):
        itemId = parentItemIds.GetId(i)
        if itemId == sceneItemId:
            continue
        _findNodesRecursively(itemId)

    uniqueNodes = []
    seenNodeIds = set()
    for node in foundNodes:
        if node.GetID() not in seenNodeIds:
            uniqueNodes.append(node)
            seenNodeIds.add(node.GetID())
    return uniqueNodes


class NetCDFExport(LTracePlugin):
    SETTING_KEY = "NetCDFExport"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "NetCDF Export"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = NetCDFExport.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class NetCDFExportWidget(LTracePluginWidget):
    EXPORTABLE_TYPES = (
        slicer.vtkMRMLLabelMapVolumeNode,
        slicer.vtkMRMLSegmentationNode,
        slicer.vtkMRMLVectorVolumeNode,
        slicer.vtkMRMLScalarVolumeNode,
        slicer.vtkMRMLTableNode,
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        self.formLayout = qt.QFormLayout()
        self.formLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.subjectHierarchyTreeView = slicer.qMRMLSubjectHierarchyTreeView()
        self.subjectHierarchyTreeView.setMRMLScene(slicer.app.mrmlScene())
        self.subjectHierarchyTreeView.hideColumn(2)
        self.subjectHierarchyTreeView.hideColumn(3)
        self.subjectHierarchyTreeView.hideColumn(4)
        self.subjectHierarchyTreeView.hideColumn(5)
        self.subjectHierarchyTreeView.setFocusPolicy(qt.Qt.NoFocus)
        self.subjectHierarchyTreeView.setMinimumHeight(300)
        self.subjectHierarchyTreeView.currentItemChanged.connect(lambda _: self.onSelectionChanged())
        self.formLayout.addRow(self.subjectHierarchyTreeView)
        self.formLayout.addRow("", None)

        coordsGroup = qt.QGroupBox()
        coordsLayout = qt.QFormLayout(coordsGroup)

        self.singleCoordsCheckBox = qt.QCheckBox("Use the same coordinate system for all images")
        self.singleCoordsCheckBox.setToolTip(
            "Export images in the same coordinate system, making the arrays spatially aligned. Uncheck to avoid padding images and thus reduce file size."
        )
        self.singleCoordsCheckBox.stateChanged.connect(
            lambda state: self.netcdfReferenceNodeBox.setEnabled(state == qt.Qt.Checked)
        )
        coordsLayout.addRow(self.singleCoordsCheckBox)

        ref_types = set(self.EXPORTABLE_TYPES) - {slicer.vtkMRMLTableNode}
        self.netcdfReferenceNodeBox = ui.volumeInput(
            hasNone=True,
            nodeTypes=[cls.__name__ for cls in ref_types],
        )
        self.netcdfReferenceNodeBox.setToolTip(
            "When exporting images using a single coordinate system, all images within the directory will be "
            "resampled and aligned to the reference node."
        )
        self.netcdfReferenceNodeBox.setEnabled(False)
        coordsLayout.addRow("Reference node:", self.netcdfReferenceNodeBox)

        self.formLayout.addRow(coordsGroup)

        self.compressionCheckBox = qt.QCheckBox("Use compression")
        self.compressionCheckBox.setToolTip(
            "Use compression when exporting to NetCDF. Reduces file size but makes file slower to load."
        )
        self.formLayout.addRow(self.compressionCheckBox)

        self.exportPathEdit = ctk.ctkPathLineEdit()
        self.exportPathEdit.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Writable
        self.exportPathEdit.nameFilters = ["*.nc"]
        self.exportPathEdit.settingKey = "NetCDFExport/ExportPath"

        self.formLayout.addRow("Export path:", self.exportPathEdit)
        self.formLayout.addRow("", None)

        self.exportNetCDFButton = qt.QPushButton("Export")
        self.exportNetCDFButton.setFixedHeight(40)
        self.exportNetCDFButton.clicked.connect(self.onExportNetcdfButtonClicked)
        self.formLayout.addRow(self.exportNetCDFButton)

        self.layout.addLayout(self.formLayout)

        statusLabel = qt.QLabel("Status: ")
        self.currentStatusLabel = qt.QLabel("Idle")
        statusHBoxLayout = qt.QHBoxLayout()
        statusHBoxLayout.addStretch(1)
        statusHBoxLayout.addWidget(statusLabel)
        statusHBoxLayout.addWidget(self.currentStatusLabel)
        self.layout.addLayout(statusHBoxLayout)

        self.progressBar = qt.QProgressBar()
        self.layout.addWidget(self.progressBar)
        self.progressBar.hide()

        self.layout.addStretch(1)

    def getItemsToExport(self):
        selected_items = vtk.vtkIdList()
        self.subjectHierarchyTreeView.currentItems(selected_items)
        return findChildDataNodes(selected_items, self.EXPORTABLE_TYPES)

    def onSelectionChanged(self):
        selected_items = self.getItemsToExport()
        if not selected_items:
            return
        current = self.netcdfReferenceNodeBox.currentNode()
        if current not in selected_items:
            current = None

        is_good_ref = lambda node: type(node) in (slicer.vtkMRMLScalarVolumeNode, slicer.vtkMRMLVectorVolumeNode)
        if current and is_good_ref(current):
            return

        # Find a reference node if not specified. Prefer scalar/vector volumes over label maps.
        ref_node = current or selected_items[0]
        for node in selected_items:
            if is_good_ref(node):
                ref_node = node
                break

        self.netcdfReferenceNodeBox.setCurrentNode(ref_node)

    def onExportNetcdfButtonClicked(self):
        callback = Callback(on_update=lambda message, percent: self.updateStatus(message, progress=percent))
        try:
            exportPath = self.exportPathEdit.currentPath
            if not exportPath.endswith(".nc"):
                exportPath += ".nc"
                self.exportPathEdit.setCurrentPath(exportPath)
            save_path(self.exportPathEdit)

            dataNodes = self.getItemsToExport()

            referenceItem = self.netcdfReferenceNodeBox.currentNode()
            useCompression = self.compressionCheckBox.checked
            singleCoords = self.singleCoordsCheckBox.checked

            warnings = netcdf.exportNetcdf(exportPath, dataNodes, referenceItem, singleCoords, useCompression, callback)
            callback.on_update("", 100)

            if warnings:
                slicer.util.warningDisplay("\n".join(warnings), windowTitle="NetCDF export warnings")
            else:
                slicer.util.infoDisplay("Export completed.")
        except Exception as e:
            slicer.util.errorDisplay(str(e))
            raise
        finally:
            callback.on_update("", 100)
            self.exportPathEdit.setCurrentPath("")

    def updateStatus(self, message, progress=None):
        self.progressBar.show()
        self.currentStatusLabel.text = message
        if not progress:
            return
        self.progressBar.setValue(progress)
        if self.progressBar.value == 100:
            self.progressBar.hide()
            self.currentStatusLabel.text = "Idle"
        slicer.app.processEvents()
