import csv
import logging
from ltrace.slicer.helpers import createTemporaryVolumeNode, hex2Rgb, maskInputWithROI, rgb2label
import numpy as np

import vtk
import slicer


def getVolumeMinSpacing(volumeNode):
    return min(volumeNode.GetSpacing())


def compareVolumeSpacings(volumeNode, referenceNode):
    volumeSpacing = getVolumeMinSpacing(volumeNode)
    referenceSpacing = getVolumeMinSpacing(referenceNode)
    sameMinSpacing = volumeSpacing == referenceSpacing
    delta = volumeSpacing - referenceSpacing
    relativeError = abs(delta / referenceSpacing)
    return sameMinSpacing, relativeError


def adjustSpacingAndCrop(volumeNode, outputPrefix, soiNode=None, referenceNode=None):
    if volumeNode is None:
        return None

    adjustSpacing = False
    if referenceNode is not None:
        sameMinSpacing, relativeError = compareVolumeSpacings(volumeNode, referenceNode)
        if not sameMinSpacing:
            adjustSpacing = True

    # copy original array
    if soiNode or adjustSpacing:
        volumeNode = createTemporaryVolumeNode(
            volumeNode.__class__,
            outputPrefix.replace("{type}", "TMP_REFNODE"),
            hidden=True,
            content=volumeNode,
        )

        if referenceNode:
            referenceSpacing = referenceNode.GetSpacing()
            volumeNode.SetSpacing(referenceSpacing)
            volumeOrigin = np.array(volumeNode.GetOrigin())
            volumeNode.SetOrigin((volumeOrigin // referenceSpacing) * referenceSpacing)

    # crop with SOI
    if soiNode:
        volumeNode = maskInputWithROI(volumeNode, soiNode, mask=True)

    return volumeNode


def makeColorsSlices(volumeNode, outputPrefix, deleteOriginal=False):
    """
    the strategy of making color channels slices is hacky,
    works only for 2D data and thus should be avoided
    """
    originalNode = volumeNode
    volumeNode = rgb2label(originalNode, outputPrefix.replace("{type}", "TMP_REFNODECM"))
    if deleteOriginal:
        slicer.mrmlScene.RemoveNode(originalNode)
    return volumeNode


def prepareTemporaryInputs(inputNodes, outputPrefix, soiNode=None, referenceNode=None, colorsToSlices=False):
    ctypes = []
    tmpInputNodes = []
    tmpReferenceNode = None
    tmpReferenceNodeDims = None

    for n, node in enumerate(inputNodes):
        if node is None:
            continue

        tmpNode = adjustSpacingAndCrop(
            node, outputPrefix, soiNode=soiNode
        )  # without spacing to avoid problems with null image

        if n == 0:
            tmpReferenceNode = tmpNode
            tmpReferenceNodeDims = tmpReferenceNode.GetImageData().GetDimensions()
        else:
            tmpNodeDims = tmpNode.GetImageData().GetDimensions()
            sameDimensions = all(d1 == d2 for d1, d2 in zip(tmpNodeDims, tmpReferenceNodeDims))
            if not sameDimensions:
                msg = (
                    "Volume arrays inside SOI have different shapes "
                    f"({tmpNodeDims} found while {tmpReferenceNodeDims} was expected)"
                )
                # remove already created tmpInputNodes before cancellation
                for node, tmpNode in zip(inputNodes, tmpInputNodes):
                    if tmpNode != node and node is not None and tmpNode is not None:
                        slicer.mrmlScene.RemoveNode(tmpNode)
                raise Exception(msg)

        ctype = "rgb" if node.IsA("vtkMRMLVectorVolumeNode") else "value"
        ctypes.append(ctype)

        # the strategy of making color channels slices is hacky,
        # works only for 2D data and thus should be avoided
        if colorsToSlices and ctype == "rgb":
            tmpNodeIsCopy = tmpNode != node
            tmpNode = makeColorsSlices(tmpNode, outputPrefix=outputPrefix, deleteOriginal=tmpNodeIsCopy)

        tmpInputNodes.append(tmpNode)
    return tmpInputNodes, ctypes


def revertColorTable(invMap, destinationNode):
    segmentation = destinationNode.GetSegmentation()
    for j in range(segmentation.GetNumberOfSegments()):
        segment = segmentation.GetNthSegment(j)
        try:
            index, name, color = invMap[segment.GetLabelValue() - 1]
            segment.SetName(name)
            segment.SetColor(color[:3])
            # segment.SetLabelValue(index)
        except Exception as e:
            logging.warning(
                f"Failed during segment {j} [id: {segmentation.GetNthSegmentID(j)}, name: {segment.GetName()}, label: {segment.GetLabelValue()}]"
            )


def setupResultInScene(segmentationNode, referenceNode, imageLogMode, soiNode=None, croppedReferenceNode=None):
    folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    itemTreeId = folderTree.GetItemByDataNode(referenceNode)
    parentItemId = folderTree.GetItemParent(itemTreeId)
    nodeTreeId = folderTree.CreateItem(parentItemId, segmentationNode)

    if imageLogMode:
        segmentationNode.SetAttribute("ImageLogSegmentation", "True")
    else:
        segmentationNode.GetDisplayNode().SetVisibility(True)
        folderTree.SetItemDisplayVisibility(nodeTreeId, True)

        if soiNode:
            slicer.util.setSliceViewerLayers(background=croppedReferenceNode, fit=True)
            slicer.util.setSliceViewerLayers(background=referenceNode, fit=False)
        else:
            slicer.util.setSliceViewerLayers(background=referenceNode, fit=True)


def paddingImageUntilReference(node, reference):
    ref_origin = np.array(reference.GetOrigin())
    ref_spacing = np.array(reference.GetSpacing())
    label_origin = np.array(node.GetOrigin())
    disl = (ref_origin - label_origin) / ref_spacing

    dims = reference.GetImageData().GetDimensions()
    image_data = node.GetImageData()
    extend = reference.GetImageData().GetExtent()

    constant_pad = vtk.vtkImageConstantPad()
    constant_pad.SetOutputWholeExtent(
        np.round(extend[0] - disl[0]).astype(int),
        np.round(extend[1] - disl[0]).astype(int),
        np.round(extend[2] - disl[1]).astype(int),
        np.round(extend[3] - disl[1]).astype(int),
        0,
        0,
    )
    constant_pad.SetConstant(0.0)
    constant_pad.SetInputData(image_data)
    constant_pad.Update()

    new_image_data = constant_pad.GetOutput()
    new_image_data.SetExtent(extend)
    node.SetAndObserveImageData(new_image_data)
    node.SetOrigin(reference.GetOrigin())
    node.Modified()


def import_colors_from_csv(path):
    with open(path, mode="r") as f:
        reader = csv.reader(f)
        color_dict = {}
        for rows in reader:
            k = rows[1]
            v = rows[0]
            color_dict[k] = hex2Rgb(v)
    return color_dict


def setTableUnits(tableNode):
    tableUnits = {
        "label": "null",
        "width": "mm",
        "height": "mm",
        "confidence": "%",
        "area": "mm^2",
        "max_feret": "mm",
        "min_feret": "mm",
        "aspect_ratio": "null",
        "elongation": "null",
        "eccentricity": "null",
        "perimeter": "mm",
    }

    for col in range(tableNode.GetNumberOfColumns()):
        name = tableNode.GetColumnName(col)
        tableNode.SetColumnUnitLabel(name, tableUnits[name])
        if tableUnits[name] != "null":
            tableNode.RenameColumn(col, f"{name} ({tableUnits[name]})")
