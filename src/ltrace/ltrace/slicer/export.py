import csv
import os
from pathlib import Path
import re

import cv2
import numpy as np
import slicer.util
import vtk

from ltrace.slicer.helpers import (
    extent2size,
    getSourceVolume,
    export_las_from_histogram_in_depth_data,
    createTemporaryNode,
    removeTemporaryNodes,
    safe_convert_array,
)
from ltrace.slicer.node_attributes import TableDataOrientation
from ltrace.units import global_unit_registry as ureg, SLICER_LENGTH_UNIT

SCALAR_VOLUME_FORMAT_RAW = 0
SCALAR_VOLUME_FORMAT_TIF = 1

IMAGE_FORMAT_TIF = 0
IMAGE_FORMAT_PNG = 1

LABEL_MAP_FORMAT_RAW = 0
LABEL_MAP_FORMAT_TIF = 1
LABEL_MAP_FORMAT_PNG = 2

SEGMENTATION_FORMAT_RAW = 0
SEGMENTATION_FORMAT_TIF = 1
SEGMENTATION_FORMAT_PNG = 2

TABLE_FORMAT_CSV = 0
TABLE_FORMAT_LAS = 1


def _rawPath(node, name=None, imageType=None):
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


def _getItemsSubitemsIds(items):
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


def _createImageArrayForLabelMapAndSegmentation(labelMapNode):
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


def exportNodeAsImage(nodeName, dataArray, imageFormat, rootPath, nodePath, colorTable=None):
    path = rootPath / nodePath
    path.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path / Path(nodeName + imageFormat)), dataArray)
    if colorTable is not None:
        with open(str(path / Path(nodeName + ".csv")), mode="w", newline="") as csvFile:
            writer = csv.writer(csvFile, delimiter="\n")
            writer.writerow(colorTable)


def _exportTableAsCsv(node, rootPath, nodePath):
    csvRows = []

    # Column names
    csvRow = []
    for i in range(node.GetNumberOfColumns()):
        csvRow.append(node.GetColumnName(i))
    csvRows.append(",".join(str(s) for s in csvRow))

    # Values
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
    adequatedNodeName = re.sub(r"[\\/*.<>ç?:]", "_", node.GetName())  # avoiding characters not suitable for file name
    path.mkdir(parents=True, exist_ok=True)
    with open(str(path / Path(adequatedNodeName + ".csv")), mode="w", newline="") as csvFile:
        writer = csv.writer(csvFile, delimiter="\n")
        writer.writerow(csvRows)


def _exportTableAsLas(self, node, rootPath, nodePath):
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


def getDataNodes(itemsIds, exportableTypes):
    subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    itemsIds = _getItemsSubitemsIds(itemsIds)
    dataNodes = []
    for itemId in itemsIds:
        dataNode = subjectHierarchyNode.GetItemDataNode(itemId)
        if dataNode is not None and type(dataNode) in exportableTypes:
            dataNodes.append(dataNode)
    return dataNodes


def exportScalarVolume(node, rootPath, nodePath, format, name=None, imageType=None, imageDtype=None):
    name = name or node.GetName()
    array = slicer.util.arrayFromVolume(node)
    if format == SCALAR_VOLUME_FORMAT_RAW:
        path = rootPath / nodePath
        path.mkdir(parents=True, exist_ok=True)
        if imageDtype:
            array = safe_convert_array(array, imageDtype)
        array.tofile(str(path / _rawPath(node, name, imageType)))
    elif format == SCALAR_VOLUME_FORMAT_TIF:
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


def exportImage(node, rootPath, nodePath, format):
    array = slicer.util.arrayFromVolume(node)
    imageArray = cv2.cvtColor(array[0, :, :, :], cv2.COLOR_BGR2RGB)
    if format == IMAGE_FORMAT_TIF:
        exportNodeAsImage(node.GetName(), imageArray, ".tif", rootPath, nodePath)
    elif format == IMAGE_FORMAT_PNG:
        exportNodeAsImage(node.GetName(), imageArray, ".png", rootPath, nodePath)


def exportLabelMap(node, rootPath, nodePath, format, name=None, imageType=None, imageDtype=np.uint8):
    name = name or node.GetName()
    if format == LABEL_MAP_FORMAT_RAW:
        array = slicer.util.arrayFromVolume(node)
        path = rootPath / nodePath
        path.mkdir(parents=True, exist_ok=True)
        rawPath = path / _rawPath(node, name, imageType)
        array.astype(imageDtype).tofile(str(rawPath))
        colorCSV = getLabelMapLabelsCSV(node)
        csvPath = rawPath.with_suffix(".csv")
        with open(str(csvPath), mode="w", newline="") as csvFile:
            writer = csv.writer(csvFile, delimiter="\n")
            writer.writerow(colorCSV)
    else:
        imageArrayAndColorCSV = _createImageArrayForLabelMapAndSegmentation(node)
        if imageArrayAndColorCSV is not None:
            imageArray, colorCSV = imageArrayAndColorCSV
            imageArray = safe_convert_array(imageArray, imageDtype)
            if format == LABEL_MAP_FORMAT_TIF:
                exportNodeAsImage(name, imageArray, ".tif", rootPath, nodePath, colorTable=colorCSV)
            elif format == LABEL_MAP_FORMAT_PNG:
                exportNodeAsImage(name, imageArray, ".png", rootPath, nodePath, colorTable=colorCSV)


def exportSegmentation(node, rootPath, nodePath, format, name=None, imageType=None):
    name = name or node.GetName()
    labelMapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
    slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
        node, labelMapVolumeNode, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
    )
    if format == SEGMENTATION_FORMAT_RAW:
        array = slicer.util.arrayFromVolume(labelMapVolumeNode)
        path = rootPath / nodePath
        path.mkdir(parents=True, exist_ok=True)
        rawPath = path / _rawPath(node, name, imageType)
        array.astype(np.uint8).tofile(str(rawPath))
        colorCSV = getLabelMapLabelsCSV(labelMapVolumeNode)
        csvPath = rawPath.with_suffix(".csv")
        with open(str(csvPath), mode="w", newline="") as csvFile:
            writer = csv.writer(csvFile, delimiter="\n")
            writer.writerow(colorCSV)
    else:
        imageArrayAndColorCSV = _createImageArrayForLabelMapAndSegmentation(labelMapVolumeNode)
        if imageArrayAndColorCSV is not None:
            imageArray, colorCSV = imageArrayAndColorCSV
            if format == SEGMENTATION_FORMAT_TIF:
                exportNodeAsImage(name, imageArray, ".tif", rootPath, nodePath, colorTable=colorCSV)
            elif format == SEGMENTATION_FORMAT_PNG:
                exportNodeAsImage(name, imageArray, ".png", rootPath, nodePath, colorTable=colorCSV)
    slicer.mrmlScene.RemoveNode(labelMapVolumeNode)


def exportTable(node, rootPath, nodePath, format):
    if format == TABLE_FORMAT_CSV:
        _exportTableAsCsv(node, rootPath, nodePath)
    elif format == TABLE_FORMAT_LAS:
        _exportTableAsLas(node, rootPath, nodePath)
    else:
        raise RuntimeError(f"{format} export table format not implemented.")
