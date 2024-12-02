import csv
from collections import namedtuple
from pathlib import Path

import ctk
import cv2
import numpy as np
import qt
import slicer.util
import vtk
from SegmentEditorEffects import *
from ltrace.slicer_utils import *
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from ltrace.slicer.helpers import getNodeDataPath
from netCDF4 import Dataset

DataType = namedtuple("ExportParameters", ["name", "dimension"])

# Data types and formats
SCALAR_VOLUME_DATA_TYPE = DataType("scalarVolume", 3)
SCALAR_VOLUME_FORMAT_RAW = 0
SCALAR_VOLUME_FORMAT_NETCDF = 1
IMAGE_DATA_TYPE = DataType("image", 3)  # (Vector volumes with length 1 in the first dimension)
IMAGE_FORMAT_TIF = 0
IMAGE_FORMAT_PNG = 1
IMAGE_FORMAT_NETCDF = 2
LABEL_MAP_DATA_TYPE = DataType("labelMap", 3)
LABEL_MAP_FORMAT_TIF = 0
LABEL_MAP_FORMAT_PNG = 1
LABEL_MAP_FORMAT_NETCDF = 2
SEGMENTATION_DATA_TYPE = DataType("segmentation", 3)
SEGMENTATION_FORMAT_TIF = 0
SEGMENTATION_FORMAT_PNG = 1
SEGMENTATION_FORMAT_NETCDF = 2
TABLE_DATA_TYPE = DataType("table", 1)
TABLE_FORMAT_CSV = 0
TABLE_FORMAT_NETCDF = 1

EXPORTABLE_NODE_TYPES = (
    slicer.vtkMRMLLabelMapVolumeNode,
    slicer.vtkMRMLSegmentationNode,
    slicer.vtkMRMLVectorVolumeNode,
    slicer.vtkMRMLTableNode,
    slicer.vtkMRMLScalarVolumeNode,
)


class Export(Workstep):
    NAME = "Data: Export"

    INPUT_TYPES = (
        slicer.vtkMRMLSegmentationNode,
        slicer.vtkMRMLScalarVolumeNode,
        slicer.vtkMRMLVectorVolumeNode,
        slicer.vtkMRMLLabelMapVolumeNode,
        slicer.vtkMRMLTableNode,
    )
    OUTPUT_TYPE = type(None)

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.exportDirectory = ""

        self.scalarVolumeDataType = True
        self.imageDataType = True
        self.labelMapDataType = True
        self.segmentationDataType = True
        self.tableDataType = True

        self.ignoreFolderStructure = False
        self.singleNetCDFFileExport = False
        self.delete_inputs = False

        self.scalarVolumeFormat = SCALAR_VOLUME_FORMAT_RAW
        self.imageFormat = IMAGE_FORMAT_TIF
        self.labelMapFormat = LABEL_MAP_FORMAT_TIF
        self.segmentationFormat = SEGMENTATION_FORMAT_TIF
        self.tableFormat = TABLE_FORMAT_CSV

    def run(self, nodes):
        rootPath = Path(self.exportDirectory).absolute()

        singleNetCDF = None
        if self.singleNetCDFFileExport:
            rootPath.mkdir(parents=True, exist_ok=True)
            singleNetCDF = Dataset(str(rootPath / Path("data.nc")), "w", format="NETCDF4")

        for node in nodes:
            # p.callback.on_update("Exporting " + node.GetName() + "...", getRoundedInteger(i * 100 / len(nodes)))
            nodePath = Path("")
            if not self.ignoreFolderStructure:
                nodePath = nodePath / getNodeDataPath(node).parent
            if (
                type(node) is slicer.vtkMRMLVectorVolumeNode
                and node.GetImageData().GetDimensions()[2] == 1  # if it's a vector volume representing a 2D image
                and self.imageDataType
            ):
                self.exportImage(node, rootPath, nodePath, self.imageFormat, singleNetCDF=singleNetCDF)
            elif type(node) is slicer.vtkMRMLLabelMapVolumeNode and self.labelMapDataType:
                self.exportLabelMap(node, rootPath, nodePath, self.labelMapFormat, singleNetCDF=singleNetCDF)
            elif type(node) is slicer.vtkMRMLSegmentationNode and self.segmentationDataType:
                self.exportSegmentation(node, rootPath, nodePath, self.segmentationFormat, singleNetCDF=singleNetCDF)
            elif type(node) is slicer.vtkMRMLTableNode and self.tableDataType:
                self.exportTable(node, rootPath, nodePath, self.tableFormat, singleNetCDF=singleNetCDF)
            elif type(node) is slicer.vtkMRMLScalarVolumeNode and self.scalarVolumeDataType:
                self.exportScalarVolume(node, rootPath, nodePath, self.scalarVolumeFormat, singleNetCDF=singleNetCDF)

            self.discard_input(node)

            yield node

        if singleNetCDF is not None:
            singleNetCDF.close()

    def exportScalarVolume(self, node, rootPath, nodePath, format, singleNetCDF=None):
        array = slicer.util.arrayFromVolume(node)
        if format == SCALAR_VOLUME_FORMAT_RAW:
            path = rootPath / nodePath
            path.mkdir(parents=True, exist_ok=True)
            array.tofile(str(path / Path(node.GetName() + ".raw")))
        elif format == SCALAR_VOLUME_FORMAT_NETCDF:
            self.exportNodeAsNetCDF(
                node.GetName(),
                array,
                SCALAR_VOLUME_DATA_TYPE,
                rootPath,
                nodePath,
                singleNetCDF=singleNetCDF,
                spacing=node.GetSpacing(),
            )

    def exportImage(self, node, rootPath, nodePath, format, singleNetCDF=None):
        array = slicer.util.arrayFromVolume(node)
        imageArray = cv2.cvtColor(array[0, :, :, :], cv2.COLOR_BGR2RGB)
        if format == IMAGE_FORMAT_TIF:
            self.exportNodeAsImage(node.GetName(), imageArray, ".tif", rootPath, nodePath)
        elif format == IMAGE_FORMAT_PNG:
            self.exportNodeAsImage(node.GetName(), imageArray, ".png", rootPath, nodePath)
        elif format == IMAGE_FORMAT_NETCDF:
            self.exportNodeAsNetCDF(
                node.GetName(),
                imageArray,
                IMAGE_DATA_TYPE,
                rootPath,
                nodePath,
                singleNetCDF=singleNetCDF,
                spacing=node.GetSpacing(),
            )

    def exportLabelMap(self, node, rootPath, nodePath, format, singleNetCDF=None):
        imageArray, colorCSV = self.createImageArrayForLabelMapAndSegmentation(node)
        if format == LABEL_MAP_FORMAT_TIF:
            self.exportNodeAsImage(node.GetName(), imageArray, ".tif", rootPath, nodePath, colorTable=colorCSV)
        elif format == LABEL_MAP_FORMAT_PNG:
            self.exportNodeAsImage(node.GetName(), imageArray, ".png", rootPath, nodePath, colorTable=colorCSV)
        elif format == LABEL_MAP_FORMAT_NETCDF:
            self.exportNodeAsNetCDF(
                node.GetName(),
                imageArray,
                LABEL_MAP_DATA_TYPE,
                rootPath,
                nodePath,
                singleNetCDF=singleNetCDF,
                spacing=node.GetSpacing(),
                colorTable=colorCSV,
            )

    def exportSegmentation(self, node, rootPath, nodePath, format, singleNetCDF=None):
        labelMapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(node, labelMapVolumeNode)
        imageArray, colorCSV = self.createImageArrayForLabelMapAndSegmentation(labelMapVolumeNode)
        if format == SEGMENTATION_FORMAT_TIF:
            self.exportNodeAsImage(node.GetName(), imageArray, ".tif", rootPath, nodePath, colorTable=colorCSV)
        elif format == SEGMENTATION_FORMAT_PNG:
            self.exportNodeAsImage(node.GetName(), imageArray, ".png", rootPath, nodePath, colorTable=colorCSV)
        elif format == SEGMENTATION_FORMAT_NETCDF:
            self.exportNodeAsNetCDF(
                node.GetName(),
                imageArray,
                SEGMENTATION_DATA_TYPE,
                rootPath,
                nodePath,
                singleNetCDF=singleNetCDF,
                spacing=labelMapVolumeNode.GetSpacing(),
                colorTable=colorCSV,
            )
        slicer.mrmlScene.RemoveNode(labelMapVolumeNode)

    def exportTable(self, node, rootPath, nodePath, format, singleNetCDF=None):
        csvRows = []
        for i in range(node.GetNumberOfRows()):
            csvRow = []
            for j in range(node.GetNumberOfColumns()):
                csvRow.append(node.GetCellText(i, j))
            csvRows.append(",".join(str(s) for s in csvRow))

        if format == TABLE_FORMAT_CSV:
            path = rootPath / nodePath
            path.mkdir(parents=True, exist_ok=True)
            with open(str(path / Path(node.GetName() + ".csv")), mode="w", newline="") as csvFile:
                writer = csv.writer(csvFile, delimiter="\n")
                writer.writerow(csvRows)
        elif format == TABLE_FORMAT_NETCDF:
            self.exportNodeAsNetCDF(
                node.GetName(), np.array(csvRows), TABLE_DATA_TYPE, rootPath, nodePath, singleNetCDF=singleNetCDF
            )

    def createImageArrayForLabelMapAndSegmentation(self, labelMapNode):
        array = slicer.util.arrayFromVolume(labelMapNode).copy()
        array = array.astype(np.uint8)

        # Converting to RGB
        imageArray = cv2.cvtColor(array[0], cv2.COLOR_GRAY2RGB)

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

    def exportNodeAsNetCDF(
        self, nodeName, dataArray, dataType, rootPath, nodePath, singleNetCDF=None, spacing=None, colorTable=None
    ):
        """
        If it is not single netCDF file (i.e. each data node is exported in a separate nc file), directory structure
        will only affect the disk directory structure, not the groups within the nc file (there is no reason to
        replicate again this structure with groups). If it as single netCDF file, directory structure will be in the
        form of groups inside the nc file.
        """
        if singleNetCDF is None:
            path = rootPath / nodePath
            path.mkdir(parents=True, exist_ok=True)
            group = Dataset(str(path / Path(nodeName + ".nc")), "w", format="NETCDF4")
            # If is a single netCDF, don't use dynamic dimensions (poor space usage)
            self.createDataTypeNetCDFDimensions(group, dataType, dataArray.shape)
        else:
            group = singleNetCDF
            self.createDataTypeNetCDFDimensions(group, dataType)
            if nodePath != Path(""):
                group = singleNetCDF.createGroup(nodePath.as_posix())

        arrayVariable = group.createVariable(
            nodeName, dataArray.dtype.str, [dataType.name + str(i) for i in range(dataType.dimension)]
        )
        arrayVariable[:] = dataArray

        if spacing is not None:
            arrayVariable.spacing = spacing

        if colorTable is not None:
            arrayVariable.colorTable = colorTable

        if singleNetCDF is None:
            group.close()

    def createDataTypeNetCDFDimensions(self, singleNetCDF, dataType, dataDimensions=None):
        """
        Creates the data type necessary number of labeled dimensions
        """
        for i in range(dataType.dimension):
            try:
                if dataDimensions is None:
                    singleNetCDF.createDimension(dataType.name + str(i), None)
                else:
                    singleNetCDF.createDimension(dataType.name + str(i), dataDimensions[i])
            except:
                pass  # if dimension is already created for that datatype

    def exportNodeAsImage(self, nodeName, dataArray, imageFormat, rootPath, nodePath, colorTable=None):
        path = rootPath / nodePath
        path.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path / Path(nodeName + imageFormat)), dataArray)
        if colorTable is not None:
            with open(str(path / Path(nodeName + ".csv")), mode="w", newline="") as csvFile:
                writer = csv.writer(csvFile, delimiter="\n")
                writer.writerow(colorTable)

    def widget(self):
        return ExportWidget(self)


class ExportWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)

        self.formLayout = qt.QFormLayout()
        self.formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout().addLayout(self.formLayout)

        self.exportDirectoryButton = ctk.ctkDirectoryButton()
        self.exportDirectoryButton.setMaximumWidth(374)
        self.exportDirectoryButton.caption = "Export directory"
        self.formLayout.addRow("Export directory:", self.exportDirectoryButton)
        self.formLayout.addRow(" ", None)

        # Data types

        dataTypesCollapsibleButton = ctk.ctkCollapsibleButton()
        dataTypesCollapsibleButton.setText("Data types")
        dataTypesCollapsibleButton.collapsed = True
        self.formLayout.addRow(dataTypesCollapsibleButton)
        dataTypesLayout = qt.QGridLayout(dataTypesCollapsibleButton)
        dataTypesLayout.setContentsMargins(15, 15, 15, 15)

        self.scalarVolumeDataTypeCheckbox = qt.QCheckBox("Scalar volumes")
        dataTypesLayout.addWidget(self.scalarVolumeDataTypeCheckbox, 0, 0)

        self.imageDataTypeCheckbox = qt.QCheckBox("Images")
        dataTypesLayout.addWidget(self.imageDataTypeCheckbox, 1, 0)

        self.labelMapDataTypeCheckbox = qt.QCheckBox("Label maps")
        dataTypesLayout.addWidget(self.labelMapDataTypeCheckbox, 0, 1)

        self.segmentationDataTypeCheckbox = qt.QCheckBox("Segmentations")
        dataTypesLayout.addWidget(self.segmentationDataTypeCheckbox, 1, 1)

        self.tableDataTypeCheckbox = qt.QCheckBox("Tables")
        dataTypesLayout.addWidget(self.tableDataTypeCheckbox, 0, 2)

        # Options

        optionsCollapsibleButton = ctk.ctkCollapsibleButton()
        optionsCollapsibleButton.setText("Options")
        optionsCollapsibleButton.collapsed = True
        self.formLayout.addRow(optionsCollapsibleButton)

        optionsFormLayout = qt.QFormLayout(optionsCollapsibleButton)
        optionsFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        optionsFormLayout.setContentsMargins(15, 15, 15, 15)

        self.ignoreFolderStructureCheckbox = qt.QCheckBox("Ignore folder structure")
        self.ignoreFolderStructureCheckbox.setToolTip(
            "Export all data ignoring the folder structure. Only one node with the same name and type will be exported."
        )
        optionsFormLayout.addRow(self.ignoreFolderStructureCheckbox)

        netCDFOptionsHBoxLayout = qt.QHBoxLayout()
        self.singleNetCDFFileExportCheckbox = qt.QCheckBox("Single netCDF file export")
        self.singleNetCDFFileExportCheckbox.setToolTip("Export all data in a single netCDF file.")
        netCDFOptionsHBoxLayout.addWidget(self.singleNetCDFFileExportCheckbox)
        self.deleteInputsCheckbox = qt.QCheckBox("Remove nodes in project after export")
        self.deleteInputsCheckbox.setToolTip(
            "Remove input nodes from project as soon as they are exported to disk in order to reduce memory usage."
        )
        self.allDataTypesToNetCDFButton = qt.QPushButton("Set all data types format to netCDF")
        self.allDataTypesToNetCDFButton.clicked.connect(self.onAllDataTypesToNetCDFButton)
        netCDFOptionsHBoxLayout.addWidget(self.allDataTypesToNetCDFButton)
        optionsFormLayout.addRow(netCDFOptionsHBoxLayout)
        optionsFormLayout.addRow(self.deleteInputsCheckbox)
        optionsFormLayout.addRow(" ", None)

        # Scalar volume
        scalarVolumeOptionsGroupBox = qt.QGroupBox("Scalar volume options:")
        scalarVolumeOptionsGroupBoxLayout = qt.QFormLayout(scalarVolumeOptionsGroupBox)
        scalarVolumeOptionsGroupBoxLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.scalarVolumeFormatComboBox = qt.QComboBox()
        self.scalarVolumeFormatComboBox.addItem("RAW", SCALAR_VOLUME_FORMAT_RAW)
        self.scalarVolumeFormatComboBox.addItem("netCDF", SCALAR_VOLUME_FORMAT_NETCDF)
        self.scalarVolumeFormatComboBox.setToolTip("Select a scalar volume format.")
        scalarVolumeOptionsGroupBoxLayout.addRow("Format:", self.scalarVolumeFormatComboBox)
        optionsFormLayout.addRow(scalarVolumeOptionsGroupBox)
        optionsFormLayout.addRow(" ", None)

        # Image
        imageOptionsGroupBox = qt.QGroupBox("Image options:")
        imageOptionsGroupBoxLayout = qt.QFormLayout(imageOptionsGroupBox)
        imageOptionsGroupBoxLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.imageFormatComboBox = qt.QComboBox()
        self.imageFormatComboBox.addItem("TIF", IMAGE_FORMAT_TIF)
        self.imageFormatComboBox.addItem("PNG", IMAGE_FORMAT_PNG)
        self.imageFormatComboBox.addItem("netCDF", IMAGE_FORMAT_NETCDF)
        self.imageFormatComboBox.setToolTip("Select an image format.")
        imageOptionsGroupBoxLayout.addRow("Format:", self.imageFormatComboBox)
        optionsFormLayout.addRow(imageOptionsGroupBox)
        optionsFormLayout.addRow(" ", None)

        # Label map
        labelMapOptionsGroupBox = qt.QGroupBox("Label map options:")
        labelMapOptionsGroupBoxLayout = qt.QFormLayout(labelMapOptionsGroupBox)
        labelMapOptionsGroupBoxLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.labelMapFormatComboBox = qt.QComboBox()
        self.labelMapFormatComboBox.addItem("TIF", LABEL_MAP_FORMAT_TIF)
        self.labelMapFormatComboBox.addItem("PNG", LABEL_MAP_FORMAT_PNG)
        self.labelMapFormatComboBox.addItem("netCDF", LABEL_MAP_FORMAT_NETCDF)
        self.labelMapFormatComboBox.setToolTip("Select an label map format.")
        labelMapOptionsGroupBoxLayout.addRow("Format:", self.labelMapFormatComboBox)
        optionsFormLayout.addRow(labelMapOptionsGroupBox)
        optionsFormLayout.addRow(" ", None)

        # Segmentation
        segmentationOptionsGroupBox = qt.QGroupBox("Segmentation options:")
        segmentationOptionsGroupBoxLayout = qt.QFormLayout(segmentationOptionsGroupBox)
        segmentationOptionsGroupBoxLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.segmentationFormatComboBox = qt.QComboBox()
        self.segmentationFormatComboBox.addItem("TIF", SEGMENTATION_FORMAT_TIF)
        self.segmentationFormatComboBox.addItem("PNG", SEGMENTATION_FORMAT_PNG)
        self.segmentationFormatComboBox.addItem("netCDF", SEGMENTATION_FORMAT_NETCDF)
        self.segmentationFormatComboBox.setToolTip("Select a segmentation format.")
        segmentationOptionsGroupBoxLayout.addRow("Format:", self.segmentationFormatComboBox)
        optionsFormLayout.addRow(segmentationOptionsGroupBox)
        optionsFormLayout.addRow(" ", None)

        # Table
        tableOptionsGroupBox = qt.QGroupBox("Table options:")
        tableOptionsGroupBoxLayout = qt.QFormLayout(tableOptionsGroupBox)
        tableOptionsGroupBoxLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.tableFormatComboBox = qt.QComboBox()
        self.tableFormatComboBox.addItem("CSV", TABLE_FORMAT_CSV)
        self.tableFormatComboBox.addItem("netCDF", TABLE_FORMAT_NETCDF)
        self.tableFormatComboBox.setToolTip("Select a table format.")
        tableOptionsGroupBoxLayout.addRow("Format:", self.tableFormatComboBox)
        optionsFormLayout.addRow(tableOptionsGroupBox)

        self.layout().addStretch(1)

    def onAllDataTypesToNetCDFButton(self):
        self.scalarVolumeFormatComboBox.setCurrentIndex(SCALAR_VOLUME_FORMAT_NETCDF)
        self.imageFormatComboBox.setCurrentIndex(IMAGE_FORMAT_NETCDF)
        self.labelMapFormatComboBox.setCurrentIndex(LABEL_MAP_FORMAT_NETCDF)
        self.segmentationFormatComboBox.setCurrentIndex(SEGMENTATION_FORMAT_NETCDF)
        self.tableFormatComboBox.setCurrentIndex(TABLE_FORMAT_NETCDF)

    def save(self):
        self.workstep.exportDirectory = self.exportDirectoryButton.directory
        self.workstep.scalarVolumeDataType = self.scalarVolumeDataTypeCheckbox.isChecked()
        self.workstep.imageDataType = self.imageDataTypeCheckbox.isChecked()
        self.workstep.labelMapDataType = self.labelMapDataTypeCheckbox.isChecked()
        self.workstep.segmentationDataType = self.segmentationDataTypeCheckbox.isChecked()
        self.workstep.tableDataType = self.tableDataTypeCheckbox.isChecked()
        self.workstep.ignoreFolderStructure = self.ignoreFolderStructureCheckbox.isChecked()
        self.workstep.singleNetCDFFileExport = self.singleNetCDFFileExportCheckbox.isChecked()
        self.workstep.deleteInputs = self.deleteInputsCheckbox.isChecked()
        self.workstep.scalarVolumeFormat = self.scalarVolumeFormatComboBox.currentData
        self.workstep.imageFormat = self.imageFormatComboBox.currentData
        self.workstep.labelMapFormat = self.labelMapFormatComboBox.currentData
        self.workstep.segmentationFormat = self.segmentationFormatComboBox.currentData
        self.workstep.tableFormat = self.tableFormatComboBox.currentData

    def load(self):
        self.exportDirectoryButton.directory = self.workstep.exportDirectory
        self.scalarVolumeDataTypeCheckbox.setChecked(self.workstep.scalarVolumeDataType)
        self.imageDataTypeCheckbox.setChecked(self.workstep.imageDataType)
        self.labelMapDataTypeCheckbox.setChecked(self.workstep.labelMapDataType)
        self.segmentationDataTypeCheckbox.setChecked(self.workstep.segmentationDataType)
        self.tableDataTypeCheckbox.setChecked(self.workstep.tableDataType)
        self.ignoreFolderStructureCheckbox.setChecked(self.workstep.ignoreFolderStructure)
        self.singleNetCDFFileExportCheckbox.setChecked(self.workstep.singleNetCDFFileExport)
        self.deleteInputsCheckbox.setChecked(self.workstep.deleteInputs)
        self.setComboBoxIndexByData(self.scalarVolumeFormatComboBox, self.workstep.scalarVolumeFormat)
        self.setComboBoxIndexByData(self.imageFormatComboBox, self.workstep.imageFormat)
        self.setComboBoxIndexByData(self.labelMapFormatComboBox, self.workstep.labelMapFormat)
        self.setComboBoxIndexByData(self.segmentationFormatComboBox, self.workstep.segmentationFormat)
        self.setComboBoxIndexByData(self.tableFormatComboBox, self.workstep.tableFormat)
