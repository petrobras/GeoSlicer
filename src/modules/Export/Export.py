import csv
import os
from collections import namedtuple
from pathlib import Path
from threading import Lock
import re

import ctk
import cv2
import numpy as np
import qt
import slicer.util
import vtk

from ltrace.slicer.helpers import (
    extent2size,
    getSourceVolume,
    export_las_from_histogram_in_depth_data,
    getNodeDataPath,
    createTemporaryNode,
    removeTemporaryNodes,
    safe_convert_array,
    getCurrentEnvironment,
)
from ltrace.slicer.node_attributes import TableDataOrientation, NodeEnvironment
from ltrace.slicer_utils import *
from ltrace.transforms import getRoundedInteger
from ltrace.units import global_unit_registry as ureg, SLICER_LENGTH_UNIT


def checkUniqueNames(nodes):
    nodeNames = set()
    for node in nodes:
        if node.GetName() in nodeNames:
            node.SetName(slicer.mrmlScene.GenerateUniqueName(node.GetName()))
        nodeNames.add(node.GetName())


class Export(LTracePlugin):
    SETTING_KEY = "Export"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Export (Legacy)"
        self.parent.categories = ["LTrace Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = Export.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ExportWidget(LTracePluginWidget):
    EXPORT_DIRECTORY = "exportDirectory"
    IGNORE_DIRECTORY_STRUCTURE = "ignoreDirectoryStructure"

    # Scalar volume
    SCALAR_VOLUME_DATA_TYPE = "scalarVolumeDataType"
    SCALAR_VOLUME_FORMAT = "scalarVolumeFormat"

    # Image (Vector volumes with length 1 in the first dimension)
    IMAGE_DATA_TYPE = "imageDataType"
    IMAGE_FORMAT = "imageFormat"

    # Label map
    LABEL_MAP_DATA_TYPE = "labelMapDataType"
    LABEL_MAP_FORMAT = "labelMapFormat"

    # Segmentation
    SEGMENTATION_DATA_TYPE = "segmentationDataType"
    SEGMENTATION_FORMAT = "segmentationFormat"

    # Table
    TABLE_DATA_TYPE = "tableDataType"
    TABLE_FORMAT = "tableFormat"

    ExportParameters = namedtuple(
        "ExportParameters",
        [
            "callback",
            EXPORT_DIRECTORY,
            "selectedItems",
            SCALAR_VOLUME_DATA_TYPE,
            IMAGE_DATA_TYPE,
            LABEL_MAP_DATA_TYPE,
            SEGMENTATION_DATA_TYPE,
            TABLE_DATA_TYPE,
            IMAGE_FORMAT,
            LABEL_MAP_FORMAT,
            SEGMENTATION_FORMAT,
            SCALAR_VOLUME_FORMAT,
            IGNORE_DIRECTORY_STRUCTURE,
            TABLE_FORMAT,
        ],
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def getExportDirectory(self):
        return Export.get_setting(self.EXPORT_DIRECTORY, default=str(Path.home()))

    def getImageFormat(self):
        return Export.get_setting(self.IMAGE_FORMAT, default=self.logic.IMAGE_FORMAT_TIF)

    def getScalarVolumeFormat(self):
        return Export.get_setting(self.SCALAR_VOLUME_FORMAT, default=self.logic.SCALAR_VOLUME_FORMAT_RAW)

    def getLabelMapFormat(self):
        return Export.get_setting(self.LABEL_MAP_FORMAT, default=self.logic.LABEL_MAP_FORMAT_TIF)

    def getSegmentationFormat(self):
        return Export.get_setting(self.SEGMENTATION_FORMAT, default=self.logic.SEGMENTATION_FORMAT_TIF)

    def getTableFormat(self):
        return Export.get_setting(self.TABLE_FORMAT, default=self.logic.TABLE_FORMAT_CSV)

    def getImageDataType(self):
        return Export.get_setting(self.IMAGE_DATA_TYPE, default=str(True))

    def getScalarVolumeDataType(self):
        return Export.get_setting(self.SCALAR_VOLUME_DATA_TYPE, default=str(True))

    def getLabelMapDataType(self):
        return Export.get_setting(self.LABEL_MAP_DATA_TYPE, default=str(True))

    def getSegmentationDataType(self):
        return Export.get_setting(self.SEGMENTATION_DATA_TYPE, default=str(True))

    def getTableDataType(self):
        return Export.get_setting(self.TABLE_DATA_TYPE, default=str(True))

    def getIgnoreDirectoryStructure(self):
        return Export.get_setting(self.IGNORE_DIRECTORY_STRUCTURE, default=str(False))

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = ExportLogic()

        self.mainTab = qt.QTabWidget()
        self.netcdfPage = slicer.modules.netcdfexport.createNewWidgetRepresentation()
        self.standardPage = qt.QWidget()

        self.mainTab.addTab(self.standardPage, "Standard")
        self.mainTab.addTab(self.netcdfPage, "NetCDF")

        self.layout.addWidget(self.mainTab)

        self.formLayout_standard = qt.QFormLayout()
        self.formLayout_standard.setLabelAlignment(qt.Qt.AlignRight)

        self.setup_standard_tab()

        self.standardPage.setLayout(self.formLayout_standard)

        statusLabel = qt.QLabel("Status: ")
        self.currentStatusLabel = qt.QLabel("Idle")
        statusHBoxLayout = qt.QHBoxLayout()
        statusHBoxLayout.addStretch(1)
        statusHBoxLayout.addWidget(statusLabel)
        statusHBoxLayout.addWidget(self.currentStatusLabel)
        self.layout.addLayout(statusHBoxLayout)

        self.progressBar = qt.QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        self.layout.addWidget(self.progressBar)
        self.progressBar.hide()

        self.progressMux = Lock()

    def setup_standard_tab(self):
        self.subjectHierarchyTreeView = slicer.qMRMLSubjectHierarchyTreeView()
        self.subjectHierarchyTreeView.setMRMLScene(slicer.app.mrmlScene())
        self.subjectHierarchyTreeView.hideColumn(2)
        self.subjectHierarchyTreeView.hideColumn(3)
        self.subjectHierarchyTreeView.hideColumn(4)
        self.subjectHierarchyTreeView.hideColumn(5)
        self.subjectHierarchyTreeView.setEditMenuActionVisible(False)
        self.subjectHierarchyTreeView.setContextMenuEnabled(False)
        self.subjectHierarchyTreeView.setDragEnabled(False)
        self.subjectHierarchyTreeView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.subjectHierarchyTreeView.setFocusPolicy(qt.Qt.NoFocus)
        self.subjectHierarchyTreeView.setMinimumHeight(300)
        self.formLayout_standard.addRow(self.subjectHierarchyTreeView)
        self.formLayout_standard.addRow(" ", None)

        self.exportDirectoryButton = ctk.ctkDirectoryButton()
        self.exportDirectoryButton.caption = "Export directory"
        self.exportDirectoryButton.directory = self.getExportDirectory()
        self.formLayout_standard.addRow("Export directory:", self.exportDirectoryButton)
        self.formLayout_standard.addRow(" ", None)

        # Environments
        environmentsCollapsibleButton = ctk.ctkCollapsibleButton()
        environmentsCollapsibleButton.setText("Environments")
        environmentsCollapsibleButton.collapsed = True
        self.formLayout_standard.addRow(environmentsCollapsibleButton)
        environmentsLayout = qt.QGridLayout(environmentsCollapsibleButton)
        environmentsCollapsibleButton.enabled = False

        # Data types
        dataTypesCollapsibleButton = ctk.ctkCollapsibleButton()
        dataTypesCollapsibleButton.setText("Data types")
        dataTypesCollapsibleButton.collapsed = True
        self.formLayout_standard.addRow(dataTypesCollapsibleButton)
        dataTypesLayout = qt.QGridLayout(dataTypesCollapsibleButton)
        dataTypesLayout.setContentsMargins(15, 15, 15, 15)

        self.scalarVolumeDataTypeCheckbox = qt.QCheckBox("3D images")
        self.scalarVolumeDataTypeCheckbox.setChecked(self.getScalarVolumeDataType() == "True")
        dataTypesLayout.addWidget(self.scalarVolumeDataTypeCheckbox, 0, 0)

        self.imageDataTypeCheckbox = qt.QCheckBox("2D images")
        self.imageDataTypeCheckbox.setChecked(self.getImageDataType() == "True")
        dataTypesLayout.addWidget(self.imageDataTypeCheckbox, 1, 0)

        self.labelMapDataTypeCheckbox = qt.QCheckBox("Label maps")
        self.labelMapDataTypeCheckbox.setChecked(self.getLabelMapDataType() == "True")
        dataTypesLayout.addWidget(self.labelMapDataTypeCheckbox, 0, 1)

        self.segmentationDataTypeCheckbox = qt.QCheckBox("Segmentations")
        self.segmentationDataTypeCheckbox.setChecked(self.getSegmentationDataType() == "True")
        dataTypesLayout.addWidget(self.segmentationDataTypeCheckbox, 1, 1)

        self.tableDataTypeCheckbox = qt.QCheckBox("Tables")
        self.tableDataTypeCheckbox.setChecked(self.getTableDataType() == "True")
        dataTypesLayout.addWidget(self.tableDataTypeCheckbox, 0, 2)

        # Options
        optionsCollapsibleButton = ctk.ctkCollapsibleButton()
        optionsCollapsibleButton.setText("Options")
        optionsCollapsibleButton.collapsed = True
        self.formLayout_standard.addRow(optionsCollapsibleButton)

        optionsFormLayout = qt.QFormLayout(optionsCollapsibleButton)
        optionsFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        optionsFormLayout.setContentsMargins(15, 15, 15, 15)

        self.ignoreDirectoryStructureCheckbox = qt.QCheckBox("Ignore directory structure")
        self.ignoreDirectoryStructureCheckbox.setChecked(self.getIgnoreDirectoryStructure() == "True")
        self.ignoreDirectoryStructureCheckbox.setToolTip(
            "Export all data ignoring the directory structure. Only one node with the same name and type will be exported."
        )
        optionsFormLayout.addRow(self.ignoreDirectoryStructureCheckbox)

        # Scalar volume
        scalarVolumeOptionsGroupBox = qt.QGroupBox("3D image options:")
        scalarVolumeOptionsGroupBoxLayout = qt.QFormLayout(scalarVolumeOptionsGroupBox)
        scalarVolumeOptionsGroupBoxLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.scalarVolumeFormatComboBox = qt.QComboBox()
        self.scalarVolumeFormatComboBox.addItem("RAW", self.logic.SCALAR_VOLUME_FORMAT_RAW)
        self.scalarVolumeFormatComboBox.addItem("TIF", self.logic.SCALAR_VOLUME_FORMAT_TIF)
        self.scalarVolumeFormatComboBox.setCurrentIndex(
            self.scalarVolumeFormatComboBox.findData(self.getScalarVolumeFormat())
        )
        self.scalarVolumeFormatComboBox.setToolTip("Select a 3D image format.")
        scalarVolumeOptionsGroupBoxLayout.addRow("Format:", self.scalarVolumeFormatComboBox)
        optionsFormLayout.addRow(scalarVolumeOptionsGroupBox)
        optionsFormLayout.addRow(" ", None)

        # Image
        imageOptionsGroupBox = qt.QGroupBox("2D image options:")
        imageOptionsGroupBoxLayout = qt.QFormLayout(imageOptionsGroupBox)
        imageOptionsGroupBoxLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.imageFormatComboBox = qt.QComboBox()
        self.imageFormatComboBox.addItem("TIF", self.logic.IMAGE_FORMAT_TIF)
        self.imageFormatComboBox.addItem("PNG", self.logic.IMAGE_FORMAT_PNG)
        self.imageFormatComboBox.setCurrentIndex(self.imageFormatComboBox.findData(self.getImageFormat()))
        self.imageFormatComboBox.setToolTip("Select a 2D image format.")
        imageOptionsGroupBoxLayout.addRow("Format:", self.imageFormatComboBox)
        optionsFormLayout.addRow(imageOptionsGroupBox)
        optionsFormLayout.addRow(" ", None)

        # Label map
        labelMapOptionsGroupBox = qt.QGroupBox("Label map options:")
        labelMapOptionsGroupBoxLayout = qt.QFormLayout(labelMapOptionsGroupBox)
        labelMapOptionsGroupBoxLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.labelMapFormatComboBox = qt.QComboBox()
        self.labelMapFormatComboBox.addItem("RAW", self.logic.LABEL_MAP_FORMAT_RAW)
        self.labelMapFormatComboBox.addItem("TIF", self.logic.LABEL_MAP_FORMAT_TIF)
        self.labelMapFormatComboBox.addItem("PNG", self.logic.LABEL_MAP_FORMAT_PNG)
        self.labelMapFormatComboBox.setCurrentIndex(self.labelMapFormatComboBox.findData(self.getLabelMapFormat()))
        self.labelMapFormatComboBox.setToolTip("Select an label map format.")
        labelMapOptionsGroupBoxLayout.addRow("Format:", self.labelMapFormatComboBox)
        optionsFormLayout.addRow(labelMapOptionsGroupBox)
        optionsFormLayout.addRow(" ", None)

        # Segmentation
        segmentationOptionsGroupBox = qt.QGroupBox("Segmentation options:")
        segmentationOptionsGroupBoxLayout = qt.QFormLayout(segmentationOptionsGroupBox)
        segmentationOptionsGroupBoxLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.segmentationFormatComboBox = qt.QComboBox()
        self.segmentationFormatComboBox.addItem("RAW", self.logic.SEGMENTATION_FORMAT_RAW)
        self.segmentationFormatComboBox.addItem("TIF", self.logic.SEGMENTATION_FORMAT_TIF)
        self.segmentationFormatComboBox.addItem("PNG", self.logic.SEGMENTATION_FORMAT_PNG)
        self.segmentationFormatComboBox.setCurrentIndex(
            self.segmentationFormatComboBox.findData(self.getSegmentationFormat())
        )
        self.segmentationFormatComboBox.setToolTip("Select a segmentation format.")
        segmentationOptionsGroupBoxLayout.addRow("Format:", self.segmentationFormatComboBox)
        optionsFormLayout.addRow(segmentationOptionsGroupBox)
        optionsFormLayout.addRow(" ", None)

        # Table
        tableOptionsGroupBox = qt.QGroupBox("Table options:")
        tableOptionsGroupBoxLayout = qt.QFormLayout(tableOptionsGroupBox)
        tableOptionsGroupBoxLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.tableFormatComboBox = qt.QComboBox()
        self.tableFormatComboBox.addItem("CSV", self.logic.TABLE_FORMAT_CSV)
        self.tableFormatComboBox.addItem("LAS", self.logic.TABLE_FORMAT_LAS)
        self.tableFormatComboBox.setCurrentIndex(self.tableFormatComboBox.findData(self.getTableFormat()))
        self.tableFormatComboBox.setToolTip("Select a table format.")
        tableOptionsGroupBoxLayout.addRow("Format:", self.tableFormatComboBox)
        optionsFormLayout.addRow(tableOptionsGroupBox)

        self.exportButton = qt.QPushButton("Export")
        self.exportButton.setFixedHeight(40)
        self.exportButton.clicked.connect(self.onExportStandardButtonClicked)
        self.formLayout_standard.addRow(self.exportButton)

    def onExportStandardButtonClicked(self):
        callback = Callback(on_update=lambda message, percent: self.updateStatus(message, progress=percent))
        try:
            Export.set_setting(self.EXPORT_DIRECTORY, self.exportDirectoryButton.directory)
            Export.set_setting(self.IMAGE_FORMAT, self.imageFormatComboBox.currentData)
            Export.set_setting(self.LABEL_MAP_FORMAT, self.labelMapFormatComboBox.currentData)
            Export.set_setting(self.SEGMENTATION_FORMAT, self.segmentationFormatComboBox.currentData)
            Export.set_setting(self.TABLE_FORMAT, self.tableFormatComboBox.currentData)
            Export.set_setting(self.SCALAR_VOLUME_FORMAT, self.scalarVolumeFormatComboBox.currentData)
            Export.set_setting(self.SCALAR_VOLUME_DATA_TYPE, str(self.scalarVolumeDataTypeCheckbox.isChecked()))
            Export.set_setting(self.IMAGE_DATA_TYPE, str(self.imageDataTypeCheckbox.isChecked()))
            Export.set_setting(self.LABEL_MAP_DATA_TYPE, str(self.labelMapDataTypeCheckbox.isChecked()))
            Export.set_setting(self.SEGMENTATION_DATA_TYPE, str(self.segmentationDataTypeCheckbox.isChecked()))
            Export.set_setting(self.TABLE_DATA_TYPE, str(self.tableDataTypeCheckbox.isChecked()))
            Export.set_setting(self.IGNORE_DIRECTORY_STRUCTURE, str(self.ignoreDirectoryStructureCheckbox.isChecked()))
            selectedItems = vtk.vtkIdList()
            self.subjectHierarchyTreeView.currentItems(selectedItems)
            exportParameters = self.ExportParameters(
                callback,
                self.exportDirectoryButton.directory,
                selectedItems,
                self.scalarVolumeDataTypeCheckbox.isChecked(),
                self.imageDataTypeCheckbox.isChecked(),
                self.labelMapDataTypeCheckbox.isChecked(),
                self.segmentationDataTypeCheckbox.isChecked(),
                self.tableDataTypeCheckbox.isChecked(),
                self.imageFormatComboBox.currentData,
                self.labelMapFormatComboBox.currentData,
                self.segmentationFormatComboBox.currentData,
                self.scalarVolumeFormatComboBox.currentData,
                self.ignoreDirectoryStructureCheckbox.isChecked(),
                self.tableFormatComboBox.currentData,
            )
            self.logic.export(exportParameters)
        except ExportInfo as e:
            slicer.util.infoDisplay(str(e))
            return
        finally:
            callback.on_update("", 100)
        slicer.util.infoDisplay("Export completed.")

    def updateStatus(self, message, progress=None, processEvents=True):
        self.progressBar.show()
        self.currentStatusLabel.text = message
        if progress == -1:
            self.progressBar.setRange(0, 0)
        else:
            self.progressBar.setRange(0, 100)
            self.progressBar.setValue(progress)
            if self.progressBar.value == 100:
                self.progressBar.hide()
                self.currentStatusLabel.text = "Idle"
        if not processEvents:
            return
        if self.progressMux.locked():
            return
        with self.progressMux:
            slicer.app.processEvents()


class Callback(object):
    def __init__(self, on_update=None):
        self.on_update = on_update or (lambda *args, **kwargs: None)


class ExportLogic(LTracePluginLogic):
    DataType = namedtuple("ExportParameters", ["name", "dimension"])

    # Data types and formats
    SCALAR_VOLUME_DATA_TYPE = DataType("scalarVolume", 3)
    SCALAR_VOLUME_FORMAT_RAW = 0
    SCALAR_VOLUME_FORMAT_TIF = 1
    IMAGE_DATA_TYPE = DataType("image", 3)  # (Vector volumes with length 1 in the first dimension)
    IMAGE_FORMAT_TIF = 0
    IMAGE_FORMAT_PNG = 1
    LABEL_MAP_DATA_TYPE = DataType("labelMap", 3)
    LABEL_MAP_FORMAT_RAW = 0
    LABEL_MAP_FORMAT_TIF = 1
    LABEL_MAP_FORMAT_PNG = 2
    SEGMENTATION_DATA_TYPE = DataType("segmentation", 3)
    SEGMENTATION_FORMAT_RAW = 0
    SEGMENTATION_FORMAT_TIF = 1
    SEGMENTATION_FORMAT_PNG = 2
    TABLE_DATA_TYPE = DataType("table", 1)
    TABLE_FORMAT_CSV = 0
    TABLE_FORMAT_LAS = 1

    EXPORTABLE_NODE_TYPES = (
        slicer.vtkMRMLLabelMapVolumeNode,
        slicer.vtkMRMLSegmentationNode,
        slicer.vtkMRMLVectorVolumeNode,
        slicer.vtkMRMLTableNode,
        slicer.vtkMRMLScalarVolumeNode,
    )

    def __init__(self):
        LTracePluginLogic.__init__(self)

    def export(self, p):
        rootPath = Path(p.exportDirectory).absolute()
        nodes = self.getDataNodes(p.selectedItems, self.EXPORTABLE_NODE_TYPES)
        checkUniqueNames(nodes)
        if not nodes:
            raise ExportInfo("There are no items selected to export.")

        for i in range(len(nodes)):
            node = nodes[i]
            p.callback.on_update("Exporting " + node.GetName() + "...", getRoundedInteger(i * 100 / len(nodes)))
            nodePath = Path("")
            if not p.ignoreDirectoryStructure:
                nodePath = nodePath / getNodeDataPath(node).parent
                print("NODE", nodePath)
            if (
                type(node) is slicer.vtkMRMLVectorVolumeNode
                and node.GetImageData().GetDimensions()[2] == 1  # if it's a vector volume representing a 2D image
                and p.imageDataType
            ):
                self.exportImage(node, rootPath, nodePath, p.imageFormat)
            elif type(node) is slicer.vtkMRMLLabelMapVolumeNode and p.labelMapDataType:
                self.exportLabelMap(node, rootPath, nodePath, p.labelMapFormat)
            elif type(node) is slicer.vtkMRMLSegmentationNode and p.segmentationDataType:
                self.exportSegmentation(node, rootPath, nodePath, p.segmentationFormat)
            elif type(node) is slicer.vtkMRMLTableNode and p.tableDataType:
                self.exportTable(node, rootPath, nodePath, p.tableFormat)
            elif type(node) is slicer.vtkMRMLScalarVolumeNode and p.scalarVolumeDataType:
                self.exportScalarVolume(node, rootPath, nodePath, p.scalarVolumeFormat)

    @staticmethod
    def rawPath(node, name=None, imageType=None):
        """Creates path for node according to standard nomenclature.
        See https://ltrace.atlassian.net/browse/PL-532
        """
        inferredName = node.GetName()
        if isinstance(node, slicer.vtkMRMLSegmentationNode):
            # Use the master volume to find out the extent
            master = getSourceVolume(node)
            if master:
                inferredName = master.GetName()
                imageData = master.GetImageData()
                spacing = master.GetMinSpacing()
            else:
                # Segmentation has no master volume, so we merge the segments
                imageData = slicer.vtkOrientedImageData()
                node.GenerateMergedLabelmapForAllSegments(imageData, slicer.vtkSegmentation.EXTENT_UNION_OF_SEGMENTS)
                spacing = min(imageData.GetSpacing())
            inferredImageType = "LABELS"
        elif isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
            imageData = node.GetImageData()
            inferredImageType = "LABELS"
            spacing = node.GetMinSpacing()
        elif isinstance(node, slicer.vtkMRMLScalarVolumeNode):
            imageData = node.GetImageData()
            size = imageData.GetScalarSize()
            if size == 1:
                inferredImageType = "LABELS"
            elif size == 2:
                inferredImageType = "CT"
            elif size >= 4:
                inferredImageType = "FLOAT"
            spacing = node.GetMinSpacing()

        name = name or inferredName
        imageType = imageType or inferredImageType
        parts = [name, imageType]

        dimensions = extent2size(imageData.GetExtent())
        parts += [str(dim).rjust(4, "0") for dim in dimensions]

        mmToNm = 10**6
        spacingNm = int(spacing * mmToNm)
        parts.append(str(spacingNm).rjust(5, "0") + "nm.raw")

        return Path("_".join(parts))

    def getDataNodes(self, itemsIds, exportableTypes):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemsIds = self.getItemsSubitemsIds(itemsIds)
        dataNodes = []
        for itemId in itemsIds:
            dataNode = subjectHierarchyNode.GetItemDataNode(itemId)
            if dataNode is not None and type(dataNode) in exportableTypes:
                dataNodes.append(dataNode)
        return dataNodes

    def getItemsSubitemsIds(self, items):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        nodesIds = []
        numberOfIds = items.GetNumberOfIds()
        if numberOfIds == 0:
            return []
        for i in range(numberOfIds):
            itemId = items.GetId(i)
            if itemId == 3:  # when not selecting any item, it supposes entire scene, which we don't want
                return []
            nodesIds.append(itemId)
            itemChildren = vtk.vtkIdList()
            subjectHierarchyNode.GetItemChildren(itemId, itemChildren, True)  # recursive
            for j in range(itemChildren.GetNumberOfIds()):
                childrenItemId = itemChildren.GetId(j)
                nodesIds.append(childrenItemId)
        return list(set(nodesIds))  # removing duplicate items

    def exportScalarVolume(self, node, rootPath, nodePath, format, name=None, imageType=None, imageDtype=None):
        name = name or node.GetName()
        array = slicer.util.arrayFromVolume(node)
        if format == self.SCALAR_VOLUME_FORMAT_RAW:
            path = rootPath / nodePath
            path.mkdir(parents=True, exist_ok=True)
            if imageDtype:
                array = safe_convert_array(array, imageDtype)
            array.tofile(str(path / ExportLogic.rawPath(node, name, imageType)))
        elif format == self.SCALAR_VOLUME_FORMAT_TIF:
            path = rootPath / nodePath / Path(f"{name}_{imageType}.tif")

            dtype = imageDtype or array.dtype
            if dtype not in [np.uint8, np.uint16, np.int8, np.int16]:
                # Slicer supports float 32 TIFF, but not integer 32 types, or 64 bit types
                dtype = np.float32

            array = safe_convert_array(array, dtype)
            node = createTemporaryNode(slicer.vtkMRMLScalarVolumeNode, "converted")
            slicer.util.updateVolumeFromArray(node, array)

            success = slicer.util.saveNode(node, str(path))
            removeTemporaryNodes()

            if not success:
                slicer.util.errorDisplay(f"Failed to save node {name} to {path}")
                return

    def exportImage(self, node, rootPath, nodePath, format):
        array = slicer.util.arrayFromVolume(node)
        imageArray = cv2.cvtColor(array[0, :, :, :], cv2.COLOR_BGR2RGB)
        if format == self.IMAGE_FORMAT_TIF:
            self.exportNodeAsImage(node.GetName(), imageArray, ".tif", rootPath, nodePath)
        elif format == self.IMAGE_FORMAT_PNG:
            self.exportNodeAsImage(node.GetName(), imageArray, ".png", rootPath, nodePath)

    def exportLabelMap(self, node, rootPath, nodePath, format, name=None, imageType=None, imageDtype=np.uint8):
        name = name or node.GetName()
        if format == self.LABEL_MAP_FORMAT_RAW:
            array = slicer.util.arrayFromVolume(node)
            path = rootPath / nodePath
            path.mkdir(parents=True, exist_ok=True)
            rawPath = path / ExportLogic.rawPath(node, name, imageType)
            array.astype(imageDtype).tofile(str(rawPath))
            colorCSV = self.getLabelMapLabelsCSV(node)
            csvPath = rawPath.with_suffix(".csv")
            with open(str(csvPath), mode="w", newline="") as csvFile:
                writer = csv.writer(csvFile, delimiter="\n")
                writer.writerow(colorCSV)
        else:
            imageArrayAndColorCSV = self.createImageArrayForLabelMapAndSegmentation(node)
            if imageArrayAndColorCSV is not None:
                imageArray, colorCSV = imageArrayAndColorCSV
                imageArray = safe_convert_array(imageArray, imageDtype)
                if format == self.LABEL_MAP_FORMAT_TIF:
                    self.exportNodeAsImage(name, imageArray, ".tif", rootPath, nodePath, colorTable=colorCSV)
                elif format == self.LABEL_MAP_FORMAT_PNG:
                    self.exportNodeAsImage(name, imageArray, ".png", rootPath, nodePath, colorTable=colorCSV)

    def exportSegmentation(self, node, rootPath, nodePath, format, name=None, imageType=None):
        name = name or node.GetName()
        labelMapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
            node, labelMapVolumeNode, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
        )
        if format == self.SEGMENTATION_FORMAT_RAW:
            array = slicer.util.arrayFromVolume(labelMapVolumeNode)
            path = rootPath / nodePath
            path.mkdir(parents=True, exist_ok=True)
            rawPath = path / ExportLogic.rawPath(node, name, imageType)
            array.astype(np.uint8).tofile(str(rawPath))
            colorCSV = self.getLabelMapLabelsCSV(labelMapVolumeNode)
            csvPath = rawPath.with_suffix(".csv")
            with open(str(csvPath), mode="w", newline="") as csvFile:
                writer = csv.writer(csvFile, delimiter="\n")
                writer.writerow(colorCSV)
        else:
            imageArrayAndColorCSV = self.createImageArrayForLabelMapAndSegmentation(labelMapVolumeNode)
            if imageArrayAndColorCSV is not None:
                imageArray, colorCSV = imageArrayAndColorCSV
                if format == self.SEGMENTATION_FORMAT_TIF:
                    self.exportNodeAsImage(name, imageArray, ".tif", rootPath, nodePath, colorTable=colorCSV)
                elif format == self.SEGMENTATION_FORMAT_PNG:
                    self.exportNodeAsImage(name, imageArray, ".png", rootPath, nodePath, colorTable=colorCSV)
        slicer.mrmlScene.RemoveNode(labelMapVolumeNode)

    def exportTable(self, node, rootPath, nodePath, format):
        if format == self.TABLE_FORMAT_CSV:
            self.__exportTableAsCsv(node, rootPath, nodePath)
        elif format == self.TABLE_FORMAT_LAS:
            self.__exportTableAsLas(node, rootPath, nodePath)
        else:
            raise RuntimeError(f"{format} export table format not implemented.")

    def __exportTableAsCsv(self, node, rootPath, nodePath):
        csvRows = []

        # Column names
        csvRow = []
        for i in range(node.GetNumberOfColumns()):
            csvRow.append(node.GetColumnName(i))
        csvRows.append(",".join(str(s) for s in csvRow))

        # Values
        environment = getCurrentEnvironment()
        for i in range(node.GetNumberOfRows()):
            csvRow = []
            for j in range(node.GetNumberOfColumns()):
                value = node.GetCellText(i, j)
                if j == 0 and "DEPTH" in node.GetColumnName(j):
                    value = (float(value) * SLICER_LENGTH_UNIT).m_as(ureg.meter)
                if isinstance(value, float):
                    value = np.format_float_positional(value, trim="0", precision=6)
                csvRow.append(value)
            csvRows.append(",".join(str(s) for s in csvRow))

        path = rootPath / nodePath
        adequatedNodeName = re.sub(
            r"[\\/*.<>ç?:]", "_", node.GetName()
        )  # avoiding characters not suitable for file name
        path.mkdir(parents=True, exist_ok=True)
        with open(str(path / Path(adequatedNodeName + ".csv")), mode="w", newline="") as csvFile:
            writer = csv.writer(csvFile, delimiter="\n")
            writer.writerow(csvRows)

    def __exportTableAsLas(self, node, rootPath, nodePath):
        table_data_orientation_attribute = node.GetAttribute(TableDataOrientation.name())
        if table_data_orientation_attribute is None or table_data_orientation_attribute != str(
            TableDataOrientation.ROW.value
        ):
            raise RuntimeError("The selected table doesn't match the pattern necessary for this export type.")

        path = rootPath / nodePath
        path.mkdir(parents=True, exist_ok=True)
        file_path = os.path.join(path, node.GetName() + ".las")

        df = slicer.util.dataframeFromTable(node)
        status = export_las_from_histogram_in_depth_data(df=df, file_path=file_path)
        if not status:
            raise RuntimeError("Unable to export the LAS file. Please check the logs for more information.")

    def createImageArrayForLabelMapAndSegmentation(self, labelMapNode):
        array = slicer.util.arrayFromVolume(labelMapNode).copy()

        if 1 not in array.shape:  # if the label map is not 2D
            print("Export 3D images to TIFF or PNG format is not supported yet.")
            return None

        arrayShape = np.array(array.shape)
        imageDimensions = arrayShape[arrayShape > 1]
        array = array.reshape(imageDimensions).astype(np.uint8)

        # Converting to RGB
        imageArray = cv2.cvtColor(array, cv2.COLOR_GRAY2RGB)

        colorNode = labelMapNode.GetDisplayNode().GetColorNode()
        colorCSV = []
        for i in range(1, colorNode.GetNumberOfColors()):
            color = np.zeros(4)
            colorNode.GetColor(i, color)
            rgbColor = (color * 255).round().astype(int)[:-1]
            colorLocations = np.where(
                np.logical_and(imageArray[:, :, 0] == i, imageArray[:, :, 1] == i, imageArray[:, :, 2] == i)
            )
            imageArray[colorLocations] = rgbColor[::-1]
            if len(colorLocations[0]) > 0:
                colorCSV.append(colorNode.GetColorName(i) + "," + ",".join(str(e) for e in rgbColor))

        return imageArray, colorCSV

    @staticmethod
    def getLabelMapLabelsCSV(labelMapNode, withColor=False):
        colorNode = labelMapNode.GetDisplayNode().GetColorNode()
        labelsCSV = []
        for i in range(1, colorNode.GetNumberOfColors()):
            label = f"{colorNode.GetColorName(i)},{i}"
            if withColor:
                color = [0] * 4
                colorNode.GetColor(i, color)
                label += ",#%02x%02x%02x" % tuple(int(ch * 255) for ch in color[:3])
            labelsCSV.append(label)
        return labelsCSV

    def exportNodeAsImage(self, nodeName, dataArray, imageFormat, rootPath, nodePath, colorTable=None):
        path = rootPath / nodePath
        path.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path / Path(nodeName + imageFormat)), dataArray)
        if colorTable is not None:
            with open(str(path / Path(nodeName + ".csv")), mode="w", newline="") as csvFile:
                writer = csv.writer(csvFile, delimiter="\n")
                writer.writerow(colorTable)


class ExportInfo(RuntimeError):
    pass
