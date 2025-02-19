###########################################################
# WARNING: DO NOT IMPORT UI MODULES LIKE QT, CTK GLOBALLY #
###########################################################
import cv2
import enum
import importlib
import lasio
import logging
import numpy as np
import operator
import os
import pandas as pd
import psutil
import re
import slicer
import sys
import stat
import tempfile
import time
import vtk
import vtk.util.numpy_support as vn

from ltrace import transforms
from ltrace.slicer.module_utils import clone_or_update_repo
from ltrace.slicer.node_attributes import (
    NodeEnvironment,
    NodeTemporarity,
    LosslessAttribute,
)

from pathlib import Path
from skimage.segmentation import relabel_sequential
from typing import Dict, List, Tuple, Union

from ltrace.slicer import data_utils as dutils


""" 
Type references:
vtk: https://vtk.org/doc/release/5.0/html/a03469.html
names: https://en.wikipedia.org/wiki/C_data_types
"""
SCALAR_TYPE_LABELS = {
    vtk.VTK_VOID: "void",
    vtk.VTK_BIT: "bit",
    vtk.VTK_UNSIGNED_CHAR: "uint8",
    vtk.VTK_CHAR: "int8",
    vtk.VTK_SIGNED_CHAR: "int8",
    vtk.VTK_UNSIGNED_SHORT: "uint16",
    vtk.VTK_SHORT: "int16",
    vtk.VTK_UNSIGNED_INT: "uint16",
    vtk.VTK_INT: "int16",
    vtk.VTK_UNSIGNED_LONG: "uint32",
    vtk.VTK_UNSIGNED_LONG_LONG: "uint64",
    vtk.VTK_LONG_LONG: "int64",
    vtk.VTK_LONG: "int32",
    vtk.VTK_FLOAT: "float32",
    vtk.VTK_DOUBLE: "float64",
}


## This function receives a pyside2 widget and returns a pythonqt widget
def getPythonQtWidget(wid):
    from PySide2 import QtWidgets
    from PySide2.QtWidgets import QVBoxLayout
    import PythonQt
    import shiboken2

    pyqtlayout = PythonQt.Qt.QVBoxLayout()
    pysideLayout = shiboken2.wrapInstance(hash(pyqtlayout), QVBoxLayout)
    pysideLayout.addWidget(wid)
    pysideLayout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)
    return pyqtlayout.itemAt(0).widget()


def rescaleSegmentationGeometry(target, reference):
    sgw = slicer.qMRMLSegmentationGeometryWidget()
    sgw.setSegmentationNode(target)
    sgw.setSourceNode(reference)
    sgw.setEditEnabled(True)
    sgw.resampleLabelmapsInSegmentationNode()
    sgw.setReferenceImageGeometryForSegmentationNode()


def runConversionMethodLuminance(inputVolumeNode, outputVolumeNode):
    if not outputVolumeNode.GetDisplayNode():
        outputVolumeNode.CreateDefaultDisplayNodes()
    outputVolumeNode.CopyOrientation(inputVolumeNode)
    extract = vtk.vtkImageExtractComponents()
    extract.SetInputConnection(inputVolumeNode.GetImageDataConnection())
    extract.SetComponents(0, 1, 2)
    luminance = vtk.vtkImageLuminance()
    luminance.SetInputConnection(extract.GetOutputPort())
    luminance.Update()
    outputVolumeNode.SetImageDataConnection(luminance.GetOutputPort())


def runVectorToLabelVolume(inputVolumeNode, outputVolumeNode):
    ijkToRAS = vtk.vtkMatrix4x4()
    inputVolumeNode.GetIJKToRASMatrix(ijkToRAS)
    outputVolumeNode.SetIJKToRASMatrix(ijkToRAS)
    outputVolumeNode.SetOrigin(inputVolumeNode.GetOrigin())
    outputVolumeNode.SetSpacing(inputVolumeNode.GetSpacing())
    dataVoxelArray = slicer.util.arrayFromVolume(inputVolumeNode)[-1, ...]
    outputVolumeNode.SetAndObserveImageData(None)
    slicer.util.updateVolumeFromArray(outputVolumeNode, dataVoxelArray)
    outputVolumeNode.Modified()


def setDimensionFrom(inputVolumeNode, outputVolumeNode):
    outputVolumeNode.CreateDefaultDisplayNodes()

    imgD = vtk.vtkImageData()
    imgD.SetDimensions(*inputVolumeNode.GetImageData().GetDimensions())

    inputVoxelArray = slicer.util.arrayFromVolume(inputVolumeNode)
    outputVoxelArray = np.zeros(inputVoxelArray.shape, dtype=np.uint8)

    ijkToRAS = vtk.vtkMatrix4x4()
    inputVolumeNode.GetIJKToRASMatrix(ijkToRAS)

    outputVolumeNode.SetAndObserveImageData(imgD)
    slicer.util.updateVolumeFromArray(outputVolumeNode, outputVoxelArray)

    outputVolumeNode.SetIJKToRASMatrix(ijkToRAS)
    outputVolumeNode.SetOrigin(inputVolumeNode.GetOrigin())
    outputVolumeNode.SetSpacing(inputVolumeNode.GetSpacing())

    outputVolumeNode.GetDisplayNode().SetDefaultColorMap()
    outputVolumeNode.Modified()


def rgb2gray(vectorVolumeNode, randomName):
    volumesLogic = slicer.modules.volumes.logic()

    def tau_gamma_correct(pixel_channel):
        pixel_channel = pixel_channel ** (1 / 2.2)
        return pixel_channel

    clonedVolumeNode = volumesLogic.CloneVolume(slicer.mrmlScene, vectorVolumeNode, "Cloned Volume")
    rgbArray = slicer.util.arrayFromVolume(clonedVolumeNode)
    rgbArray = tau_gamma_correct(rgbArray)

    slicer.util.updateVolumeFromArray(clonedVolumeNode, rgbArray)
    clonedVolumeNode.Modified()

    scalarVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", randomName)
    runConversionMethodLuminance(clonedVolumeNode, scalarVolumeNode)

    slicer.mrmlScene.RemoveNode(clonedVolumeNode)

    return scalarVolumeNode


def make_labelmap_sequential(labelmap):
    array = slicer.util.arrayFromVolume(labelmap)
    array[...], get_new_label, get_old_label = relabel_sequential(array, offset=1)
    max_label = np.max(array)
    num_labels = max_label + 1

    display_node = labelmap.GetDisplayNode()
    if display_node is None or display_node.GetColorNode() is None:
        raise Exception("LabelMap node has no display node or its display " "node is not connected to a color node")

    color_node = display_node.GetColorNode()

    # make colors in the new colortable fit to the old one
    old_color = np.empty(4)
    for new_label in range(num_labels):
        old_label = get_old_label(new_label)
        if new_label != old_label:
            color_node.GetColor(old_label, old_color)
            color_node.SetColor(new_label, *old_color)
    color_node.SetNumberOfColors(num_labels)

    slicer.util.arrayFromVolumeModified(labelmap)


def get_subject_hierarchy_siblings(node, forbid_root_as_parent=False):  # TODO move to helpers
    tree_node = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    node_id_in_tree = tree_node.GetItemByDataNode(node)
    parent_id_in_tree = tree_node.GetItemParent(node_id_in_tree)
    scene_id_in_tree = tree_node.GetSceneItemID()
    if forbid_root_as_parent and parent_id_in_tree == scene_id_in_tree:
        return []

    sibling_ids_in_tree = vtk.vtkIdList()
    tree_node.GetItemChildren(parent_id_in_tree, sibling_ids_in_tree)
    sibling_ids_in_tree = [sibling_ids_in_tree.GetId(i) for i in range(sibling_ids_in_tree.GetNumberOfIds())]
    sibling_nodes = [tree_node.GetItemDataNode(i) for i in sibling_ids_in_tree]
    return [n for n in sibling_nodes if n is not None]


def clone_volume(volume, name=None, copy_names=True, as_temporary=True):
    new_volume = createTemporaryVolumeNode(volume.__class__, name=name, content=volume)
    if not as_temporary:
        makeTemporaryNodePermanent(new_volume, show=True)

    for identifier in range(new_volume.GetNumberOfDisplayNodes()):
        new_volume.RemoveNthDisplayNodeID(identifier)

    old_display_node = volume.GetDisplayNode()
    new_volume.CreateDefaultDisplayNodes()
    new_volume.CreateDefaultStorageNode()
    new_display_node = new_volume.GetDisplayNode()
    if hasattr(new_display_node, "AutoWindowLevelOff"):
        new_display_node.AutoWindowLevelOff()
        new_display_node.SetWindowLevel(old_display_node.GetWindow(), old_display_node.GetLevel())

    if isinstance(volume, slicer.vtkMRMLLabelMapVolumeNode):
        color_node = copyColorNode(
            new_volume,
            source_color_node=old_display_node.GetColorNode(),
            copy_names=copy_names,
        )
        if as_temporary:
            makeNodeTemporary(color_node)

    subject_hierarchy_node = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    item_parent = subject_hierarchy_node.GetItemParent(subject_hierarchy_node.GetItemByDataNode(volume))
    subject_hierarchy_node.SetItemParent(subject_hierarchy_node.GetItemByDataNode(new_volume), item_parent)

    return new_volume


def get_dataprobe_info(layers=None):
    """
    layers is a iterable of strings, valid strings are "L", "B" and "F", representing
    Geoslicers Label, Background and Foreground layers. The function will iterate over
    those layers and return the first with a valid value.
    If layers is none, function will iterate over all layers in the following sequence: ("L", "F", "B")
    """
    dataprobe_re = re.compile(r"\(( *\d+, *\d+, *\d+ *)\)[^\(]+\((\d+)\)")

    infoWidget = slicer.modules.DataProbeInstance.infoWidget
    if not layers:
        layers = ("L", "F", "B")
    for layer in layers:
        re_result = dataprobe_re.match(f"{infoWidget.layerIJKs[layer].text} {infoWidget.layerValues[layer].text}")
        if re_result:
            position = [int(i.strip()) for i in re_result.group(1).split(",")]
            value = int(re_result.group(2).strip())
            return position, value
    return None


def rgb2label(vectorVolumeNode, name):
    # scalarVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", name)
    scalarVolumeNode = createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, name)
    runVectorToLabelVolume(vectorVolumeNode, scalarVolumeNode)
    return scalarVolumeNode


def extent2size(extent):
    """Converts extent 6-tuple to size 3-tuple.

    :param extent: tuple of format (xmin, xmax, ymin, ymax, zmin, zmax)
    :return: tuple of format (xsize, ysize, zsize)
    """
    return tuple(extent[i * 2 + 1] - extent[i * 2] + 1 for i in range(len(extent) // 2))


def bounds2size(extent):
    """Converts bounds 6-tuple to size 3-tuple.

    :param extent: tuple of format (xmin, xmax, ymin, ymax, zmin, zmax)
    :return: tuple of format (xsize, ysize, zsize)
    """
    return tuple(abs(extent[i * 2 + 1] - extent[i * 2]) for i in range(len(extent) // 2))


def getCurrentEnvironment():
    try:
        envName = slicer.modules.AppContextInstance.modules.currentWorkingDataType[1]
    except Exception as error:
        return None

    for env in NodeEnvironment:
        if env.value == envName:
            return env

    return None


def in_image_log_environment():
    return getCurrentEnvironment() == NodeEnvironment.IMAGE_LOG


def in_micro_ct_environment():
    return getCurrentEnvironment() == NodeEnvironment.MICRO_CT


def in_core_environment():
    return getCurrentEnvironment() == NodeEnvironment.CORE


def in_thin_section_environment():
    return getCurrentEnvironment() == NodeEnvironment.THIN_SECTION


def moveNodeTo(dirId, node, dirTree=None):
    """Wrapper function of CreateItem.

    This wrapper only exists to indicate that the function is not duplicating an existing item but moving it.
    When using 'CreateItem' in another folder it removes 'node' from the previous location.

    Args:
        dirId (vtkItem): Destination
        node (vtkMRMLNode): Moveable target
        dirTree (SubjectHierarchyNode, optional): Defaults to None.
    """
    if not dirTree:
        dirTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

    dirTree.CreateItem(dirId, node)


def createNode(cls, name, environment=None, hidden=True, content=None, display=None):
    node = slicer.mrmlScene.CreateNodeByClass(cls.__name__)
    node.UnRegister(None)  # to prevent memory leaks
    node.SetName(slicer.mrmlScene.GenerateUniqueName(name))

    if not environment:
        environment = getCurrentEnvironment()
    if environment is not None:
        node.SetAttribute(NodeEnvironment.name(), environment.value)

    if display is None and hasattr(node, "CreateDefaultDisplayNodes"):
        node.CreateDefaultDisplayNodes()
    elif display:
        node.SetAndObserveDisplayNodeID(display)

    if hidden:
        node.SetHideFromEditors(True)

    if content:
        node.CopyContent(content)

    return node


def createTemporaryVolumeNode(
    cls,
    name,
    environment=None,
    content=None,
    hidden=True,
    saveWithScene=False,
    uniqueName=True,
):
    """
    Creates temporary volume node with class given by `cls` and name given by
    `name`.  The environment in which the temporary node is being used is to
    be set in `environment` as a `ltrace.slicer.node_attributes.NodeEnvironment` enum
    option.
    """
    valid_name = slicer.mrmlScene.GenerateUniqueName(name) if uniqueName else name
    tempNode = slicer.mrmlScene.AddNewNodeByClass(cls.__name__, valid_name)
    if hasattr(tempNode, "CreateDefaultDisplayNodes"):
        tempNode.CreateDefaultDisplayNodes()

    if hidden:
        tempNode.SetHideFromEditors(True)

    if not saveWithScene:
        tempNode.SaveWithSceneOff()

    if content:
        tempNode.CopyContent(content)

    if not environment:
        environment = getCurrentEnvironment()

    tempNode.SetAttribute(NodeTemporarity.name(), NodeTemporarity.TRUE.value)

    if environment is not None:
        value = environment if not hasattr(environment, "value") else environment.value
        tempNode.SetAttribute(NodeEnvironment.name(), value)

    triggerNodeModified(tempNode)

    return tempNode


def makeTemporaryNodePermanent(node, show=None, save=True):
    node.SetAttribute(NodeTemporarity.name(), NodeTemporarity.FALSE.value)
    if save is not None and save:
        node.SaveWithSceneOn()
    if show is not None:
        node.SetHideFromEditors(not show)
    # node.SetSelectable(True)
    triggerNodeModified(node)


def makeNodeTemporary(node, hide=None, save=False):
    node.SetAttribute(NodeTemporarity.name(), NodeTemporarity.TRUE.value)
    if save is not None and not save:
        node.SaveWithSceneOff()
    if hide is not None:
        node.SetHideFromEditors(hide)
    # node.SetSelectable(False)
    triggerNodeModified(node)


def triggerNodeModified(node):
    """WARNING: This is a trick to trigger a node attribute update for the entire application.
    This is required because some attribute changes, like HideFromEditors, do not notify the UI and the info displayed by
    some widgets (like comboboxes) become outdated.
    """
    name = str(node.GetName())
    node.SetName(f"{name}_updated")  # hack it
    node.SetName(name)  # hack it
    node.Modified()


def getNodesWithAttribute(attribute, cls=None, nodes=None):
    """
    Get a dict mapping node names to their associated nodes if they have the
    correct `attribute` enum and node class (`cls`). Tip: use this function
    recursively in `nodes` to perform multiple filters.

    Example:
    # get all the nodes inside the image log environment
    from ltrace.slicer.node_attributes import NodeEnvironment
    envNodes = getNodesWithAttribute(NodeEnvironment.IMAGE_LOG)

    # get all the temporary nodes inside the image log environment
    tempEnvNodes = getNodesWithAttribute(NodeTemporarity.TRUE, nodes=envNodes)

    :param attribute (str): node attribute searched
    :param cls (str): only look for nodes with attribute `attr` from class `cls`
    :param nodes (dict): nodes to be searched
    :return: found nodes
    """
    nodes = nodes or slicer.util.getNodes()

    if isinstance(attribute, enum.EnumMeta):
        attributeName = attribute.__name__
        attributeValue = None
    elif isinstance(attribute, enum.Enum):
        attributeName = attribute.__class__.__name__
        attributeValue = attribute.value
    elif hasattr(attribute, "value"):
        attributeName = NodeEnvironment.name()
        attributeValue = attribute.value
    else:
        try:
            attributeName = NodeEnvironment.name()
            attributeValue = attribute
        except Exception:
            raise NotImplementedError("Argument 'attribute' must be defined in " "'ltrace.slicer.node_attributes'")

    if attributeValue is None:
        hasAttribute = lambda node: node.GetAttribute(attributeName) is not None
    else:
        hasAttribute = lambda node: node.GetAttribute(attributeName) == attributeValue

    if cls is None:
        isCorrectClass = lambda node: True
    else:
        isCorrectClass = lambda node: node.__class__ == cls

    return {name: node for (name, node) in nodes.items() if hasAttribute(node) and isCorrectClass(node)}


def isTemporaryNode(node):
    return node.GetAttribute(NodeTemporarity.name()) == NodeTemporarity.TRUE.value


def getTemporaryNodes(environment=None, nodes=None):
    tempNodes = nodes or getNodesWithAttribute(NodeTemporarity.TRUE)
    if len(tempNodes) > 0 and environment is not None:
        tempNodes = getNodesWithAttribute(environment, nodes=tempNodes)
    return tempNodes


def removeTemporaryNodes(environment=None, nodes=None):
    """'
    Removes temporary nodes in environment `environment`. If `environment` not
    set, removes all temporary nodes.

    :param environment (enum): environment enum as defined in
        `ltrace.slicer.node_attributes.NodeEnvironment` to filter removals
        (i.e. `ltrace.slicer.node_attributes.NodeEnvironment.IMAGE_LOG`)
    :param nodes (dict): subset of nodes to search
    """
    tempNodes = getTemporaryNodes(environment=environment, nodes=nodes)
    for name, node in tempNodes.items():
        logging.debug(f"Removing temporary node named {name} with id {node.GetID()}")
        slicer.mrmlScene.RemoveNode(node)


def createTemporaryNode(cls, name, environment=None, hidden=True, uniqueName=True, saveWithScene=False):
    valid_name = slicer.mrmlScene.GenerateUniqueName(name) if uniqueName else name
    tempNode = slicer.mrmlScene.AddNewNodeByClass(cls.__name__, valid_name)
    tempNode.SetAttribute(NodeTemporarity.name(), NodeTemporarity.TRUE.value)

    if not environment:
        environment = getCurrentEnvironment()
    if environment is not None:
        value = environment if not hasattr(environment, "value") else environment.value
        tempNode.SetAttribute(NodeEnvironment.name(), value)

    if not saveWithScene:
        tempNode.SaveWithSceneOff()

    if hidden:
        tempNode.SetHideFromEditors(True)

    triggerNodeModified(tempNode)

    return tempNode


def boundsAsRows(node):
    """Return a matrix of dimensions x ends"""
    bounds = [0] * 6
    node.GetRASBounds(bounds)
    return np.vstack([bounds[1::2], bounds[0::2]]).T


def cropBounds(shape, bounds, offset=0):
    x_min, y_min, z_min = [int(np.ceil(max(np.min(bounds[:, i]) - offset, 0))) for i in [0, 1, 2]]
    x_max, y_max, z_max = [int(np.ceil(min(np.max(bounds[:, i]) - offset, shape[i]))) for i in [0, 1, 2]]
    return slice(x_min, x_max), slice(y_min, y_max), slice(z_min, z_max)


def getOverlappingSlices(dimension_one, dimension_two, displacement):
    """
    Return slices for first and second image that allow equivalence
    dimension_one, dimension_two: tuples in format (x, y)
    displacement: tuple in format (delta_x, delta_y), representing top
        left position of second array relative to first array

    Use example:
        To copy arr2 into arr1 displaced by 10 elements in both axes, trimming elements of arr2 outside arr1:
    slice_one, slice_two = get_overlaping_slices(arr1.shape, arr2.shape, (10, 10))
    arr1[slice_one] = arr2[slice_two]

    Similar to cropBounds, except it returns the croped slices for the bounding array
    """
    slice_one = []
    slice_two = []

    for i, delta in enumerate(displacement):
        left_trim = max(0, -delta)
        right_trim = max(0, (delta + dimension_two[i]) - dimension_one[i])
        slice_one.append(slice(max(0, delta), min(dimension_one[i], delta + dimension_two[i]), None))
        slice_two.append(slice(left_trim, dimension_two[i] - right_trim, None))
    return tuple(slice_one), tuple(slice_two)


def separateLabelmapVolumeIntoSlices(node, axis=0, verifyContent=True, dtype=np.int32):
    slices = []

    if axis == 0:
        slicefunc = lambda vec, i: vec[i, ...]
    elif axis == 1:
        slicefunc = lambda vec, i: vec[:, i, :]
    elif axis == 2:
        slicefunc = lambda vec, i: vec[:, :, i]
    else:
        raise ValueError("Axis must be 0, 1 or 2")

    volumeIJKToRASMatrix = vtk.vtkMatrix4x4()
    node.GetIJKToRASMatrix(volumeIJKToRASMatrix)
    referenceSpacing = node.GetSpacing()
    volumeOrigin = np.array(node.GetOrigin())
    volumeOrigin[axis] = 0.0

    arr = slicer.util.arrayFromVolume(node)
    for i in range(arr.shape[axis]):
        sliceArray = slicefunc(arr, i).astype(dtype)
        if np.any(sliceArray) or not verifyContent:
            sliceNode = createNode(slicer.vtkMRMLLabelMapVolumeNode, f"{node.GetName()}_ind{i}")
            sliceNode.SetHideFromEditors(False)
            slicer.mrmlScene.AddNode(sliceNode)

            slicer.util.updateVolumeFromArray(sliceNode, sliceArray)

            sliceNode.SetIJKToRASMatrix(volumeIJKToRASMatrix)
            sliceNode.SetSpacing(referenceSpacing)
            sliceNode.SetOrigin(volumeOrigin)

            castVolumeNode(sliceNode, dtype)

            slices.append((i, sliceNode))

    return slices


def get_voxel_volume(volume_node):
    ijk_to_ras_vtk = vtk.vtkMatrix4x4()
    volume_node.GetRASToIJKMatrix(ijk_to_ras_vtk)
    ijk_to_ras_vtk.Invert()
    ijk_to_ras = slicer.util.arrayFromVTKMatrix(ijk_to_ras_vtk)
    r, a, s = ijk_to_ras[:3, :3].T
    return np.abs(np.cross(r, a).dot(s))


def createMaskWithROI(inputNode, roiNode):
    tempROINode = createTemporaryVolumeNode(slicer.vtkMRMLSegmentationNode, name="TMP-ROI", content=roiNode)

    try:
        rescaleSegmentationGeometry(tempROINode, reference=inputNode)

        rasToIJK = vtk.vtkMatrix4x4()
        inputNode.GetRASToIJKMatrix(rasToIJK)

        inputVoxelArray = slicer.util.arrayFromVolume(inputNode)

        bounds = np.zeros(6)
        tempROINode.GetRASBounds(bounds)
        slices = cropBounds(
            inputVoxelArray.shape,
            transforms.transformPoints(rasToIJK, bounds.reshape((3, 2)).T),
        )

        segment_id = tempROINode.GetSegmentation().GetNthSegmentID(0)
        mask = np.array(
            arrayFromSegmentBinaryLabelmap(tempROINode, segment_id, inputNode),
            dtype=bool,
        )

        if inputVoxelArray.ndim == 4:
            mask = np.repeat(mask[:, :, :, np.newaxis], inputVoxelArray.shape[-1], axis=3)

        return slices, mask
    except:
        raise
    finally:
        slicer.mrmlScene.RemoveNode(tempROINode)


def getColorTableForLabels(labelMapNode):
    colors = labelMapNode.GetDisplayNode().GetColorNode()
    id = labelMapNode.GetImageData()
    srange = id.GetScalarRange()

    def _get_color(lb):
        color = np.zeros(4)
        colors.GetColor(lb, color)
        name = colors.GetColorName(lb)
        return dict(name=name, color=color)

    return {v: _get_color(v) for v in range(1, colors.GetNumberOfColors()) if srange[0] <= v <= srange[1]}


def getCountForLabels(labelMapNode, roiNode=None):
    labelVoxelArray = slicer.util.arrayFromVolume(labelMapNode)
    if labelVoxelArray.dtype == np.float64:
        logging.warning(f"LabelMap <{labelMapNode.GetName()}> has wrong type, casting to uin32")
        labelVoxelArray = labelVoxelArray.astype(np.uint32)

    if not roiNode:
        total = labelVoxelArray.size
    else:
        _, mask = createMaskWithROI(labelMapNode, roiNode)
        total = np.count_nonzero(mask)
        labelVoxelArray = labelVoxelArray * mask

    bins = np.bincount(labelVoxelArray.ravel())
    counts = {v: dict(count=count) for v, count in enumerate(bins) if int(v) != 0 and int(count) != 0}
    counts["total"] = total

    return counts


def getSourceVolume(node: slicer.vtkMRMLSegmentationNode):
    return node.GetNodeReference(slicer.vtkMRMLSegmentationNode.GetReferenceImageGeometryReferenceRole())


def setSourceVolume(node: slicer.vtkMRMLSegmentationNode, source: slicer.vtkMRMLVolumeNode):
    if source:
        node.SetNodeReferenceID(
            slicer.vtkMRMLSegmentationNode.GetReferenceImageGeometryReferenceRole(),
            source.GetID(),
        )
    else:
        node.RemoveNodeReferenceIDs(slicer.vtkMRMLSegmentationNode.GetReferenceImageGeometryReferenceRole())


# TODO change that name
def segmentProportionFromLabelMap(labelMapNode, roiNode=None, return_proportions=False):
    if return_proportions:
        colors = getColorTableForLabels(labelMapNode)
        segmentmap = getCountForLabels(labelMapNode, roiNode)
        for key in segmentmap:
            if key in colors:
                segmentmap[key].update(colors[key])
    else:
        segmentmap = getColorTableForLabels(labelMapNode)

    return segmentmap


def segmentListFromSegmentation(segmentationNode):
    segments = {}
    segmentation = segmentationNode.GetSegmentation()
    for index in range(segmentation.GetNumberOfSegments()):
        segment = segmentation.GetNthSegment(index)
        if segment:
            name = segment.GetName()
            color = np.array(segment.GetColor() + (1,))
            segments[index + 1] = {"name": name, "color": color}
    return segments


class MissingReferenceNodeError(Exception):
    pass


def segmentListAndProportionsFromSegmentation(
    segmentationNode, roiNode=None, referenceNode=None, return_proportions=False
):
    if not return_proportions:
        return segmentListFromSegmentation(segmentationNode)

    if not referenceNode:
        raise MissingReferenceNodeError("Reference node is required to compute segment proportions")

    segment_map = segmentListFromSegmentation(segmentationNode)
    props = segmentProportionFromSegmentation(segmentationNode, roiNode, referenceNode)
    for key in segment_map:
        if key in props:
            segment_map[key] |= props[key]
    segment_map["total"] = props["total"]

    return segment_map


def zeroCopyComputeStatisticsOnSegmentatioNode(targetSegmentationNode):
    import SegmentStatistics

    segStatLogic = SegmentStatistics.SegmentStatisticsLogic()
    segStatLogic.getParameterNode().SetParameter("Segmentation", targetSegmentationNode.GetID())
    segStatLogic.getParameterNode().SetParameter("visibleSegmentsOnly", str(False))
    segStatLogic.computeStatistics()
    return segStatLogic.getStatistics()


def segmentProportionFromSegmentation(node, roiNode, refNode):
    counts = {}
    numberOfSegments = node.GetSegmentation().GetNumberOfSegments()

    if roiNode:
        tempIntersectionNode = createTemporaryVolumeNode(
            slicer.vtkMRMLSegmentationNode, name="TMP-INTERSECT", content=node
        )
        try:
            segmentation = tempIntersectionNode.GetSegmentation()

            segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
            segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
            segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
            segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)
            segmentEditorWidget.setSegmentationNode(tempIntersectionNode)
            segmentEditorWidget.setSourceVolumeNode(refNode)
            segmentEditorWidget.setActiveEffectByName("Logical operators")
            effect = segmentEditorWidget.activeEffect()

            roiNodeSegment = roiNode.GetSegmentation().GetNthSegment(0)
            segmentation.AddSegment(roiNodeSegment)
            roiSegmentID = segmentation.GetNthSegmentID(numberOfSegments)

            effect.setParameter("Operation", "INTERSECT")
            modifierSegmentID = segmentation.GetNthSegmentID(numberOfSegments)
            effect.setParameter("ModifierSegmentID", modifierSegmentID)
            for n in range(numberOfSegments):
                nodeSegmentID = segmentation.GetNthSegmentID(n)
                segmentEditorWidget.setCurrentSegmentID(nodeSegmentID)
                effect.self().onApply()

            stats = zeroCopyComputeStatisticsOnSegmentatioNode(tempIntersectionNode)

            counts["total"] = stats[roiSegmentID, "LabelmapSegmentStatisticsPlugin.voxel_count"]
            for segNumber in range(numberOfSegments):
                segmentID = segmentation.GetNthSegmentID(segNumber)
                count = stats[segmentID, "LabelmapSegmentStatisticsPlugin.voxel_count"]
                counts[segNumber + 1] = {"count": count}
        except:
            raise
        finally:
            slicer.mrmlScene.RemoveNode(tempIntersectionNode)
    else:
        segmentation = node.GetSegmentation()
        stats = zeroCopyComputeStatisticsOnSegmentatioNode(node)
        counts["total"] = np.prod(refNode.GetImageData().GetDimensions())

        for segNumber in range(numberOfSegments):
            segmentID = segmentation.GetNthSegmentID(segNumber)
            count = stats[segmentID, "LabelmapSegmentStatisticsPlugin.voxel_count"]
            counts[segNumber + 1] = {"count": count}

    return counts


def getSegmentList(node, roiNode=None, refNode=None, return_proportions=False):
    if node is None:
        return {}

    if node.IsA(slicer.vtkMRMLSegmentationNode.__name__):
        return segmentListAndProportionsFromSegmentation(
            node,
            roiNode=roiNode,
            referenceNode=refNode,
            return_proportions=return_proportions,
        )
    return segmentProportionFromLabelMap(node, roiNode=roiNode, return_proportions=return_proportions)


def setup_segment_editor(segmentationNode=None, sourceVolumeNode=None):
    """Runs standard setup of segment editor widget and segment editor node"""
    segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
    segmentEditorNode = slicer.vtkMRMLSegmentEditorNode()
    slicer.mrmlScene.AddNode(segmentEditorNode)
    segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)
    segmentEditorWidget.setSegmentationNode(segmentationNode)
    segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
    if sourceVolumeNode:
        segmentEditorWidget.setSourceVolumeNode(sourceVolumeNode)
    return segmentEditorWidget, segmentEditorNode


def convertToIJK(bounds, rasBounds, ijkBounds):
    def conversor(x, oldScale, newScale):
        omin, omax = oldScale
        nmin, nmax = newScale
        return nmin + ((x - omin) * (nmax - nmin)) / (omax - omin)

    rows = []
    for i, row in enumerate(bounds):
        rows.append([conversor(v, rasBounds[i, :], ijkBounds[i, :]) for v in row])

    return np.array(rows)


def exportSegmentLabelsForCollapsedSegmentationNode(segmentationNode, selection=None):
    segmentation = segmentationNode.GetSegmentation()
    if selection is None:
        selection = [i for i in range(segmentation.GetNumberOfSegments())]

    sids = [segmentation.GetNthSegmentID(index) for index in selection]

    try:
        labels = [segmentation.GetSegment(sid).GetLabelValue() for sid in sids]
        names = [segmentation.GetSegment(sid).GetName() for sid in sids]
    except Exception as exc:
        logging.critical("Failed to fetch labels - do nothing. Exception: ", repr(exc))
        labels = []
        names = []

    return labels, names


def maskInputWithROI(inputNode, soiNode, mask=True):
    if mask:
        maskedArray = slicer.util.arrayFromVolume(inputNode)
        _, mask = createMaskWithROI(inputNode, soiNode)
        maskedArray *= mask
        slicer.util.arrayFromVolumeModified(inputNode)

    bounds = np.zeros(6)
    soiNode.GetRASBounds(bounds)
    roiNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLMarkupsROINode.__name__)
    roiNode.SetDisplayVisibility(0)
    radiusXYZ = np.diff(bounds)[::2] * 0.5
    roiNode.SetXYZ(bounds[::2] + radiusXYZ)
    roiNode.SetRadiusXYZ(radiusXYZ)

    cropParamNode = slicer.vtkMRMLCropVolumeParametersNode()
    cropParamNode.SetInputVolumeNodeID(inputNode.GetID())
    cropParamNode.SetROINodeID(roiNode.GetID())
    cropParamNode.VoxelBasedOn()

    cropParamNode.SetOutputVolumeNodeID(inputNode.GetID())
    slicer.modules.cropvolume.logic().Apply(cropParamNode)

    try:
        slicer.mrmlScene.RemoveNode(roiNode)
        slicer.mrmlScene.RemoveNode(cropParamNode)
    except Exception as e:
        logging.critical(repr(e))

    return inputNode


def updateSegmentationFromLabelMap(
    segmentationNode,
    labelmapVolumeNode=None,
    roiVolumeNode=None,
    includeEmptySegments=False,
):
    if roiVolumeNode:
        maskedArray = slicer.util.arrayFromVolume(labelmapVolumeNode)
        _, mask = createMaskWithROI(labelmapVolumeNode, roiVolumeNode)
        maskedArray *= mask
        slicer.util.arrayFromVolumeModified(labelmapVolumeNode)

    if includeEmptySegments:
        segmentStrArray = vtk.vtkStringArray()
        colorNode = labelmapVolumeNode.GetDisplayNode().GetColorNode()
        for segmentIndex in range(1, colorNode.GetNumberOfColors()):
            segmentID = colorNode.GetColorName(segmentIndex)
            segmentStrArray.InsertNextValue(segmentID)

            color = [0, 0, 0, 0]
            colorNode.GetColor(segmentIndex, color)
            color = color[:3]
            segmentationNode.GetSegmentation().AddEmptySegment(segmentID, segmentID, color)
        success = slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
            labelmapVolumeNode, segmentationNode, segmentStrArray
        )
    else:
        success = slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
            labelmapVolumeNode, segmentationNode
        )
    if not success:
        raise RuntimeError("Importing of segment failed.")


def tryGetNode(*tokens):
    for token in tokens:
        if token:
            try:
                node = slicer.util.getNode(handleNodeNameToRegex(token))
                return node
            except slicer.util.MRMLNodeNotFoundException:
                continue  # searching

    return None


def mergeSegments(labelmapNode, labels="all"):
    """
    Sets all elements on _labelmapNode_ attached volume to 1 if the element value is in the _labels_ iterator
    Modifies the node data inplace and updates the node
    """
    voxelArray = slicer.util.arrayFromVolume(labelmapNode)

    if labels:
        if labels != "all":
            unique_values = np.unique(voxelArray)
            for value in unique_values:
                if value not in labels:
                    voxelArray[voxelArray == value] = 0

        voxelArray[voxelArray != 0] = 1
    else:
        voxelArray *= 0

    slicer.util.arrayFromVolumeModified(labelmapNode)


def autoDetectColumnType(tableNode):
    def tryCast(v, type_):
        try:
            type_(v)
            return True
        except (ValueError, TypeError):
            return False

    tableWasModified = tableNode.StartModify()
    table = tableNode.GetTable()

    for col in range(table.GetNumberOfColumns()):
        colname = table.GetColumnName(col)
        value = table.GetValue(0, col)
        if value.IsString():
            if tryCast(value.ToString(), int):
                tableNode.SetColumnType(colname, vtk.VTK_INT)
            elif tryCast(value.ToString(), float):
                tableNode.SetColumnType(colname, vtk.VTK_DOUBLE)

    tableNode.Modified()
    tableNode.EndModify(tableWasModified)


def clearPattern(pattern):
    while True:
        nodes = slicer.util.getNodes(pattern)
        if len(nodes) == 0:
            break

        for key, node in nodes.items():
            logging.debug(f"Removed {key} {node.GetID()} {node.GetName()}")
            slicer.mrmlScene.RemoveNode(node)


def generateName(dirTree, name):
    item = dirTree.GetItemByName(name)
    if not item:
        return name

    for i in range(1, 100):
        tname = f"{name} {i}"
        if not dirTree.GetItemByName(tname):
            return tname

    return f"{name} N"


def setVolumeNullValue(volumeNode, value):
    if volumeNode is None:
        return False

    volumeNode.SetAttribute("NullValue", str(value))
    return True


def getVolumeNullValue(volumeNode):
    if volumeNode is None:
        return None

    value = volumeNode.GetAttribute("NullValue")

    if value == "None" or value is None:
        return None

    return float(value)


def extractSegmentInfo(itemID: int, refNode: slicer.vtkMRMLVolumeNode = None):
    subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()

    tryNode = subjectHierarchyNode.GetItemDataNode(itemID)
    if tryNode is not None:
        if tryNode.IsA("vtkMRMLSegmentationNode"):
            segmentation = tryNode.GetSegmentation()
            vtkSegmentIds = vtkStringArrayBuilder(
                "Labels",
                [segmentation.GetNthSegmentID(i) for i in range(segmentation.GetNumberOfSegments())],
            )
            labelmapNode = createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, name="TMP-LABELMAP")
            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                tryNode, vtkSegmentIds, labelmapNode, refNode
            )
            return labelmapNode  # converted labelmap
        return tryNode  # already a labelmap

    segmentName = subjectHierarchyNode.GetItemName(itemID)
    segmentationNodeItemID = subjectHierarchyNode.GetItemParent(itemID)
    segmentationNode = subjectHierarchyNode.GetItemDataNode(segmentationNodeItemID)
    if not segmentationNode:
        raise Exception("Invalid segmentation node.")

    segmentId = segmentationNode.GetSegmentation().GetSegmentIdBySegmentName(segmentName)

    vtkSegmentIds = vtkStringArrayBuilder("Labels", [segmentId])

    labelmapNode = createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, name="TMP-LABELMAP")

    slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
        segmentationNode, vtkSegmentIds, labelmapNode, refNode
    )

    return labelmapNode


def vtkStringArrayBuilder(name, values):
    vtkSegmentIds = vtk.vtkStringArray()
    vtkSegmentIds.SetName(name)
    for value in values:
        vtkSegmentIds.InsertNextValue(value)
    return vtkSegmentIds


def rand_cmap(n_colors: int):
    """Generate color map for bright colors based on hsv"""

    import colorsys

    rand_vals = np.random.random_sample((n_colors, 3))
    # rand_vals[:, 0]  # full range
    rand_vals[:, 1] = (1 - 0.2) * rand_vals[:, 1] + 0.2
    rand_vals[:, 2] = (1 - 0.9) * rand_vals[:, 2] + 0.9
    rand_hsv_colors = list(map(tuple, rand_vals))

    rand_rgb_colors = [colorsys.hsv_to_rgb(*hsv_color) for hsv_color in rand_hsv_colors]
    return rand_rgb_colors


def create_color_table(
    node_name: str,
    colors: List[Tuple[float, float, float]],
    color_names: List[str] = None,
    add_background: bool = False,
) -> slicer.vtkMRMLColorTableNode:
    color_lookup_table = vtk.vtkLookupTable()

    if add_background:
        # colors.insert(0, (0, 0, 0, 0))
        if color_names:
            color_names.insert(0, "Background")

        color_lookup_table.SetNumberOfTableValues(len(colors) + 1)
        color_lookup_table.SetTableValue(0, 0, 0, 0, 0)
    else:
        color_lookup_table.SetNumberOfTableValues(len(colors))

    start = 1 if add_background else 0
    for label, color in enumerate(colors, start=start):
        color_lookup_table.SetTableValue(label, *color)

    color_table_node = slicer.vtkMRMLColorTableNode()
    color_table_node.SetTypeToUser()
    color_table_node.SetName(node_name)
    color_table_node.SetHideFromEditors(0)
    # color_table_node.SetNumberOfColors(len(colors))
    color_table_node.NamesInitialisedOff()
    color_table_node.SetLookupTable(color_lookup_table)

    if color_names:
        color_table_node.ClearNames()
        color_table_node.SetColorNames(color_names)

    color_table_node.NamesInitialisedOn()

    slicer.mrmlScene.AddNode(color_table_node)
    return color_table_node


def createLabelmapInput(
    segmentationNode,
    name: str,
    segments="all",
    tag=None,
    referenceNode=None,
    soiNode=None,
    uniqueName=True,
    topSegments=None,
):
    invmap = []

    if not tag:
        tag = getCurrentEnvironment()

    if segmentationNode.IsA(slicer.vtkMRMLSegmentationNode.__name__):
        # if segmentationNode.GetSegmentation().GetNumberOfLayers() > 1:
        #     logging.warning('Warning: Multiple layers found, collapsing binary labelmaps!')
        #     segmentationNode.GetSegmentation().CollapseBinaryLabelmaps(True)

        labelmapNode = createTemporaryVolumeNode(
            slicer.vtkMRMLLabelMapVolumeNode,
            name,
            environment=tag,
            uniqueName=uniqueName,
        )

        vtkSegmentIds = vtk.vtkStringArray()
        vtkSegmentIds.SetName("Labels")
        segmentation = segmentationNode.GetSegmentation()

        if segments == "all":
            segments = range(segmentation.GetNumberOfSegments())
        else:
            segments = [segment - 1 for segment in segments]

        for index in segments:
            vtkSegmentIds.InsertNextValue(segmentation.GetNthSegmentID(index))

        slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
            segmentationNode, vtkSegmentIds, labelmapNode, referenceNode
        )

        if segmentationNode.GetSegmentation().GetNumberOfLayers() > 1 and topSegments:
            vtkSegmentIds = vtk.vtkStringArray()
            topLabelmapNode = createTemporaryVolumeNode(
                slicer.vtkMRMLLabelMapVolumeNode,
                name,
                environment=tag,
                uniqueName=uniqueName,
            )
            for index in topSegments:
                vtkSegmentIds.InsertNextValue(segmentation.GetNthSegmentID(index - 1))
            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                segmentationNode, vtkSegmentIds, topLabelmapNode, referenceNode
            )

            array = slicer.util.arrayFromVolume(labelmapNode)
            topArray = slicer.util.arrayFromVolume(topLabelmapNode)

            # Relabel topArray to keep the same labels as array
            for i, segment in enumerate(topSegments, start=1):
                topArray[topArray == i] = segment

            mask = topArray > 0
            array[mask] = topArray[mask]

            slicer.util.updateVolumeFromArray(labelmapNode, array)

        for index in segments:
            segment = segmentation.GetNthSegment(index)
            invmap.append((segment.GetLabelValue(), segment.GetName(), segment.GetColor()))
    else:
        inputColors = segmentationNode.GetDisplayNode().GetColorNode()
        labelmapNode = createTemporaryVolumeNode(
            slicer.vtkMRMLLabelMapVolumeNode,
            name,
            environment=tag,
            content=segmentationNode,
        )
        if segments != "all":
            array = slicer.util.arrayFromVolume(labelmapNode)
            mask = np.logical_not(np.isin(array, segments))
            array[mask] = 0
            slicer.util.updateVolumeFromArray(labelmapNode, array)

        copyColorNode(labelmapNode, inputColors)

        for index in range(inputColors.GetNumberOfColors()):
            color = np.zeros(4)
            inputColors.GetColor(index, color)
            name = inputColors.GetColorName(index)
            invmap.append((index, name, color))

    colorNode = labelmapNode.GetDisplayNode().GetColorNode()
    makeNodeTemporary(colorNode, hide=True)
    tag_value = tag if not hasattr(tag, "value") else tag.value
    colorNode.SetAttribute(NodeEnvironment.name(), tag_value)

    invmap = list(filter(lambda x: x[0] != 0, invmap))

    if soiNode:
        labelmapNode = maskInputWithROI(labelmapNode, soiNode)

    return labelmapNode, invmap


def get_associated_color_node(node):
    if isinstance(node, slicer.vtkMRMLDisplayableNode):
        return source_color_node.GetDisplayNode().GetColorNode()
    elif isinstance(node, slicer.vtkMRMLColorNode):
        return node
    else:
        raise RuntimeError("Source type conversion not implemented")


def get_labelmap_colors(labelmap):
    color_node = get_associated_color_node(labelmap)
    num_colors = color_node.GetNumberOfColors()
    colors = np.empty((num_colors, 4))
    for c, color in enumerate(colors):
        color_node.GetColor(c, color)
    return colors


def get_labelmap_names(labelmap):
    color_node = get_associated_color_node(labelmap)
    num_colors = color_node.GetNumberOfColors()
    return [color_node.GetColorName(n) for n in range(num_colors)]


def copyColorNode(node, source_color_node, copy_names=True):
    """Handler color node information copy from source to the desire node.

    Args:
        node (slicer.vtkMRMLDisplayableNode): the desired node object
        source_color_node (slicer.vtkMRMLDisplayableNode or slicer.vtkMRMLColorNode): [description]

    Raises:
        RuntimeError: If node type conversion is not implemented.
    """
    source_color_node = get_associated_color_node(source_color_node)

    colors = get_labelmap_colors(source_color_node)
    if copy_names:
        names = get_labelmap_names(source_color_node)
    else:
        names = False
    new_color_node_name = node.GetName() + "_ColorMap"
    color_node = create_color_table(
        node_name=new_color_node_name,
        colors=colors,
        color_names=names,
        add_background=False,
    )

    node.GetDisplayNode().SetAndObserveColorNodeID(color_node.GetID())
    color_node.NamesInitialisedOn()

    return color_node


def extractLabels(node, segments=None):
    """Wrapper for extracting segment labels from node.

    Args:
        node (vtk.vtkMRMLSegmentationNode or vtk.vtkMRMLLabelMapVolumeNode): [description]
        segments ([type], optional): [description]. Defaults to None.

    Returns:
        dict: a dictionary with segment's indices as key and segment's label as value.
    """
    if node.IsA(slicer.vtkMRMLSegmentationNode.__name__):
        return extractLabelsFromSegmentationNode(node, segments)
    elif node.IsA(slicer.vtkMRMLLabelMapVolumeNode.__name__):
        return extractLabelsFromLabelMap(node, segments)
    else:
        logging.warning("Type {} not implemented for extracting the segment's labels.")
        return {}


def extractLabelsFromSegmentationNode(segmentationNode, segments=None):
    """Get segments labels from segmentation node.

    Args:
        segmentationNode (vtk.vtkMRMLSegmentationNode): the segmentation node object.
        segments (list, optional): A list of the selected segments index. Defaults to None.

    Returns:
        dict: a dictionary with segment's indices as key and segment's label as value.
    """
    labels = dict()
    if segmentationNode is None or not segmentationNode.IsA(slicer.vtkMRMLSegmentationNode.__name__):
        return labels

    segmentation = segmentationNode.GetSegmentation()
    targets = range(0, segmentation.GetNumberOfSegments()) if segments is None else segments

    for i in targets:
        segment = segmentation.GetNthSegment(i)
        labels[i + 1] = segment.GetName()  # background offset

    return labels


def extractLabelsFromLabelMap(labelMapVolumeNode, segments=None):
    """Get segments labels from label map volume node.

    Args:
        labelMapVolumeNode (vtk.vtkMRMLLabelMapVolume): the label map volume target.
        segments (list, optional): The list of segments indexes that must be exported as a result. Defaults to None, will export
        all segments.

    Returns:
        dict: a dictionary with segment's indices as key and segment's label as value.
    """
    if not labelMapVolumeNode.IsA(slicer.vtkMRMLLabelMapVolumeNode.__name__):
        raise RuntimeError("The node is not a label map volume node.")

    if labelMapVolumeNode is None:
        return labels

    segments_dict = segmentProportionFromLabelMap(labelMapVolumeNode)
    segments = range(0, len(segments_dict)) if segments is None else segments
    labels = [
        (idx, segment["name"]) for idx, segment in segments_dict.items() if idx - 1 in segments
    ]  # -1 due to selecte segments indexes starts with 0 but Background (0) is not listed.
    labels_dict = dict(labels)

    return labels_dict


def createOutput(prefix="", ntype="", where=None, builder=None):
    if builder is None:
        raise ValueError("Missing builder function")
    sh = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    nodename = prefix.replace("{type}", ntype)
    outNode = builder(nodename)
    # add to results subfolder
    if where:
        nodeTreeId = sh.CreateItem(where, outNode)
        sh.SetItemDisplayVisibility(nodeTreeId, 0)

    return outNode


def getDepthArrayFromVolume(volumeNode):
    """Gets the depth node reference on the DEPTH_NODE attribute of the volumeNode,
    if there is no such node, the spacing is calculated from the volumeNode origin
    and spacing.
    Note: CLIs does not have access to the referenced node, so do not use the DEPTH_NODE
    option when running a CLI.

    Args:
        volumeNode (Node): Slicer node with spacing or with a DEPTH_NODE attribute
        indicating the depth data

    Returns:
        ndarray: calculated or retrieved depth in meters.
    """
    if volumeNode is None:
        return None

    depthID = volumeNode.GetAttribute("DEPTH_NODE")

    if depthID is not None and depthID != "None":
        tdepNode = slicer.util.getNode(depthID)
        tdepArray = slicer.util.arrayFromVolume(tdepNode)
        depthArray = np.squeeze(tdepArray) / 1000
        return depthArray
    else:
        bounds = np.zeros((6))
        volumeNode.GetBounds(bounds)
        depth = bounds[4:6]
        number_of_lines = slicer.util.arrayFromVolume(volumeNode).shape[0]
        depthArray = np.linspace(depth[0], depth[-1], number_of_lines)
        depthArray = depthArray / -1000
        return depthArray


def listLtraceModules(sort=False):
    """Retrieve a list containing all the modules objects that has 'LTrace' as contributors

    Args:
        sort (bool, optional): Sort list alphabetically if True. Defaults to False.

    Returns:
        list: a list with LTrace modules objects.
    """
    allModulesNameList = dir(slicer.modules)
    ltraceModules = []
    for moduleName in allModulesNameList:
        module = getattr(slicer.modules, moduleName)
        if module is None or not isinstance(module, slicer.ScriptedLoadableModule.ScriptedLoadableModule):
            continue

        if not hasattr(module, "parent"):
            continue

        moduleParent = module.parent
        if not hasattr(moduleParent, "contributors"):
            continue

        value = getattr(moduleParent, "contributors")
        if "LTrace" in str(value):
            ltraceModules.append(module)

    if sort:
        ltraceModules = sorted(ltraceModules, key=operator.attrgetter("parent.title"))

    return ltraceModules


def openModuleHelp(module):
    """Display plugin's with its 'Help & Ackownledgement' window opened

    Args:
        module (ScriptedLoadableModule.ScriptedLoadableModule or str): the slicer's module
    """
    import ctk

    moduleName = ""
    if type(module) == str:
        moduleName = module
        module = getattr(slicer.modules, moduleName)
        if module is None:
            return

    elif isinstance(module, slicer.ScriptedLoadableModule.ScriptedLoadableModule):
        moduleName = module.parent.name
    else:
        return

    mainWindow = slicer.modules.AppContextInstance.mainWindow
    mainWindow.moduleSelector().selectModule(module.parent.name)
    modulePanel = mainWindow.findChild(slicer.qSlicerModulePanel, "ModulePanel")
    helpCollapsibleButton = modulePanel.findChild(ctk.ctkCollapsibleButton, "HelpCollapsibleButton")
    helpCollapsibleButton.collapsed = False


def arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId, referenceVolumeNode=None):
    """TODO WARNING: This function is copied from master branch of GeoSlicer. Move when base application version is upgraded."""

    """Return voxel array of a segment's binary labelmap representation as numpy array.
    :param segmentationNode: source segmentation node.
    :param segmentId: ID of the source segment.
      Can be determined from segment name by calling ``segmentationNode.GetSegmentation().GetSegmentIdBySegmentName(segmentName)``.
    :param referenceVolumeNode: a volume node that determines geometry (origin, spacing, axis directions, extents) of the array.
      If not specified then the volume that was used for setting the segmentation's geometry is used as reference volume.
    :raises RuntimeError: in case of failure
    Voxels values are copied, therefore changing the returned numpy array has no effect on the source segmentation.
    The modified array can be written back to the segmentation by calling :py:meth:`updateSegmentBinaryLabelmapFromArray`.
    To get voxels of a segment as a modifiable numpy array, you can use :py:meth:`arrayFromSegmentInternalBinaryLabelmap`.
    """

    import slicer
    import vtk

    # Get reference volume
    if not referenceVolumeNode:
        referenceVolumeNode = getSourceVolume(segmentationNode)
        if not referenceVolumeNode:
            raise RuntimeError(
                "No reference volume is found in the input segmentationNode, therefore a valid referenceVolumeNode input is required."
            )

    # Export segment as vtkImageData (via temporary labelmap volume node)
    segmentIds = vtk.vtkStringArray()
    segmentIds.InsertNextValue(segmentId)
    labelmapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "__temp__")
    try:
        if not slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
            segmentationNode, segmentIds, labelmapVolumeNode, referenceVolumeNode
        ):
            raise RuntimeError("Export of segment failed.")
        narray = slicer.util.arrayFromVolume(labelmapVolumeNode)
    finally:
        slicer.mrmlScene.RemoveNode(labelmapVolumeNode)

    return narray


# Copied from ImageLogCSV.py - TODO MUSA-89
def arrayPartsFromNode(node: slicer.vtkMRMLNode) -> tuple[np.ndarray, np.ndarray]:

    mmToM = 0.001
    if isinstance(node, slicer.vtkMRMLScalarVolumeNode):
        values = slicer.util.arrayFromVolume(node).copy().squeeze()
        if values.ndim != 2:
            raise ValueError(f"Node has dimension {values.ndim}, expected 2.")

        bounds = [0] * 6
        node.GetBounds(bounds)
        ymax = -bounds[4] * mmToM
        ymin = -bounds[5] * mmToM
        spacing = node.GetSpacing()[2] * mmToM
        depthColumn = np.arange(ymin, ymax - spacing / 2, spacing)

        ijkToRas = np.zeros([3, 3])
        node.GetIJKToRASDirections(ijkToRas)
        if ijkToRas[0][0] > 0:
            values = np.flip(values, axis=0)
        if ijkToRas[1][1] > 0:
            values = np.flip(values, axis=1)
        if ijkToRas[2][2] > 0:
            values = np.flip(values, axis=2)
    elif isinstance(node, slicer.vtkMRMLTableNode):
        if node.GetAttribute("table_type") == "histogram_in_depth":
            df = dutils.tableNodeToDataFrame(node)  # using ltrace's version, not slicer.utils
            df_columns = df.columns
            depthColumn = df[df_columns[0]].to_numpy() * mmToM
            values = df[df_columns[1:]].to_numpy()
        else:
            values = slicer.util.arrayFromTableColumn(node, node.GetColumnName(1))
            depthColumn = slicer.util.arrayFromTableColumn(node, node.GetColumnName(0)) * mmToM
            if depthColumn[0] > depthColumn[-1]:
                depthColumn = np.flipud(depthColumn)
                values = np.flipud(values)

    return depthColumn, values


def themeIsDark():
    import qt

    palette = slicer.app.palette()
    bg_color = palette.color(qt.QPalette.Background)
    fg_color = palette.color(qt.QPalette.WindowText)
    return fg_color.value() > bg_color.value()


def svgToQIcon(iconPath):
    import qt

    with open(iconPath, "r", encoding="utf-8") as src:
        svg_content = src.read()

    hex = "#e1e1e1" if themeIsDark() else "#333333"
    updated_svg_content = re.sub(r'stroke="[^"]+"', f'stroke="{hex}"', svg_content)

    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w", encoding="utf-8") as src:
        src.write(updated_svg_content)
        tmpIconPath = Path(src.name)

    icon = qt.QIcon(tmpIconPath.as_posix())
    tmpIconPath.unlink()

    return icon


def numberArrayToLabelArray(array: np.ndarray) -> np.ndarray:
    """Convert float, int, or negative values to label values."""
    if np.issubdtype(array.dtype, np.floating):
        array = np.rint(array).astype(np.uint16)

    if np.min(array) < 0:
        array = np.clip(array + 1, 0, None)
    return array


def castVolumeNode(node, dtype):
    lock = node.StartModify()
    arr = slicer.util.arrayFromVolume(node)
    if arr.dtype != dtype:
        retyped_arr = arr.astype(dtype)
        slicer.util.updateVolumeFromArray(node, retyped_arr)
        node.Modified()
    node.EndModify(lock)


def getTerminologyIndices(dataType: str) -> list:
    """Returns the indices for terminology types based on
    the provided data type (BIN, BIW and BASINS supported)
    """
    if "BIN" in dataType:
        return [6, 0]  # [Solid, Pore]
    if "BIW" in dataType:
        return [0, 6]  # [Pore, Solid]
    if "BASINS" in dataType:
        # [Outer, Pore, Quartz, Microporosity, Calcite, High attenuation coefficient]
        return [5, 0, 1, 2, 3, 4]
    return None


def getColorMapFromTerminology(name: str, environment: int, type_indices: list) -> slicer.vtkMRMLColorTableNode:
    """Create color table for segments of given data type;
    enviroment: 0 -> Image Log; 1 -> Core; 2 -> Micro CT; 3 -> Thin Section
    """
    terminologyLogic = slicer.app.moduleLogic("Terminologies")
    terminologyCategory = slicer.vtkSlicerTerminologyCategory()
    terminologyLogic.GetNthCategoryInTerminology(
        "Segmentation category and type - DICOM master list",
        environment,
        terminologyCategory,
    )

    segmentNames = []
    colors = []
    for n, i in enumerate(type_indices):
        terminologyType = slicer.vtkSlicerTerminologyType()
        terminologyLogic.GetNthTypeInTerminologyCategory(
            "Segmentation category and type - DICOM master list",
            terminologyCategory,
            i,
            terminologyType,
        )
        segmentNames.append(terminologyType.GetCodeMeaning())
        rgb255 = terminologyType.GetRecommendedDisplayRGBValue()
        rgb1 = [x / 255 for x in rgb255] + [n and 1.0]  # 0 should be transparent
        colors.append(rgb1)
    colorMapNode = create_color_table(node_name=name, colors=colors, color_names=segmentNames, add_background=False)
    return colorMapNode


def labelArrayToColorNode(array: np.ndarray, name: str) -> slicer.vtkMRMLColorTableNode:
    """Create color table with generic names and random colors
    based on label map array.
    """
    n_nonzero_labels = int(np.max(array))
    return labels_to_color_node(n_nonzero_labels, name)


def labels_to_color_node(n_nonzero_labels: int, name: str) -> slicer.vtkMRMLColorTableNode:
    """Create color table with generic names and random colors based on the number of non-zero labels."""
    colors = rand_cmap(n_nonzero_labels)
    color_names = [f"Segment_{label + 1}" for label in range(n_nonzero_labels)]
    color_map_node = create_color_table(node_name=name, colors=colors, color_names=color_names, add_background=True)
    return color_map_node


def number_of_channels(node: slicer.vtkMRMLScalarVolumeNode) -> int:
    shape = slicer.util.arrayFromVolume(node).shape
    if len(shape) < 4:
        return 1
    else:
        return shape[3]


def getIJKVector(rasLineNode, referenceVolumeNode):
    volumeRASToIJKMatrix = vtk.vtkMatrix4x4()
    referenceVolumeNode.GetRASToIJKMatrix(volumeRASToIJKMatrix)
    points = slicer.util.arrayFromMarkupsControlPoints(rasLineNode)
    return transforms.transformPoints(volumeRASToIJKMatrix, points, returnInt=True)[:, :-1]


def export_las_from_histogram_in_depth_data(df: pd.DataFrame, file_path: str):
    """Handle LAS file export from histogram in depth data frame.

    Args:
        df (pd.DataFrame): the data
        file_path (str): the absolute file path for the exported file.

    Returns:
        bool: True if file was exported successfully, otherwise False.
    """
    lf = lasio.LASFile()

    # transform to numpy array
    df_array = df.values

    # sort by depth
    df_array = df_array[df_array[:, 0].argsort()]

    # add depth as double to first curve
    lf.append_curve("DEPT", df_array[:-1, 0].astype(np.double), unit="m")

    # add remaining data as pore size distribution i
    for i in range(df_array.shape[1] - 1):
        lf.append_curve("DTP" + str(i), df_array[:-1, i + 1])

    lf.well.append(lasio.HeaderItem(mnemonic="BIN0", value=df_array[-1, 1], descr="VALOR INICIAL DOS BINS"))
    lf.well.append(lasio.HeaderItem(mnemonic="BINN", value=df_array[-1, -1], descr="VALOR FINAL DOS BINS"))
    lf.well.append(
        lasio.HeaderItem(
            mnemonic="BIN_STEP",
            value="LOG10",
            descr="TIPO DE ESPACAMENTO DOS BINS LINEAR OU LOG10",
        )
    )

    lf.write(file_path, version=2.0, STEP=0)

    return os.path.isfile(file_path)


def concatenateImageArrayVertically(image_array_list: list):
    max_width = 0
    total_height = 0
    for image in image_array_list:
        image_height = image.shape[0]
        image_width = image.shape[1]
        total_height += image_height
        max_width = max(max_width, image_width)

    concatenated_array = np.zeros((total_height, max_width, 3), dtype=np.uint8)

    current_y = 0
    for image in image_array_list:
        image = np.hstack((image, np.zeros((image.shape[0], max_width - image.shape[1], 3))))
        concatenated_array[current_y : current_y + image.shape[0], :, :] = image
        current_y += image.shape[0]

    return concatenated_array


def resizeRgbArray(image: np.ndarray, new_height, new_width, interpolation=cv2.INTER_CUBIC):
    resized_rgb_image = np.zeros((new_height, new_width, 3))

    for idx in range(3):
        img_1_color_array = image[:, :, idx]
        resized_2d_img = cv2.resize(img_1_color_array, (new_width, new_height), interpolation=interpolation)
        resized_rgb_image[:, :, idx] = resized_2d_img

    return resized_rgb_image


def resizeNdimArray(image: np.ndarray, new_height, new_width, interpolation=cv2.INTER_CUBIC):
    dim = image.shape[2]
    resized_rgb_image = np.zeros((new_height, new_width, dim))

    for idx in range(dim):
        img_1_color_array = image[:, :, idx]
        resized_2d_img = cv2.resize(img_1_color_array, (new_width, new_height), interpolation=interpolation)
        resized_rgb_image[:, :, idx] = resized_2d_img

    return resized_rgb_image


def getTesseractCmd() -> str:
    if os.getenv("GEOSLICER_MODE") == "Remote":
        return "tesseract"
    tesseract_cmd = (
        str(Path(slicer.app.applicationDirPath()) / "Tesseract-OCR/tesseract.exe")
        if sys.platform.startswith("win32")
        else str(Path(slicer.app.applicationDirPath()) / "Tesseract-OCR/tesseract-4.1.1-x86_64.AppImage")
    )
    return tesseract_cmd


def getNodeDataPath(node):
    path = Path("")
    subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    item = subjectHierarchyNode.GetItemByDataNode(node)
    while subjectHierarchyNode.GetItemName(item) != "Scene":
        path = subjectHierarchyNode.GetItemName(item) / path
        item = subjectHierarchyNode.GetItemParent(item)
    return path


def setVolumeVisibilityIn3D(volumeNode, visible):
    viewNode = slicer.app.layoutManager().threeDWidget(0).mrmlViewNode()
    volumeRenderingLogic = slicer.modules.volumerendering.logic()
    renderingNode = volumeRenderingLogic.GetVolumeRenderingDisplayNodeForViewNode(volumeNode, viewNode)
    if renderingNode is None:
        renderingNode = volumeRenderingLogic.CreateDefaultVolumeRenderingNodes(volumeNode)
    if visible:
        renderingNode.SetVisibility(True)
    else:
        slicer.mrmlScene.RemoveNode(renderingNode.GetROINode())
        slicer.mrmlScene.RemoveNode(renderingNode)


def getVolumeVisibilityIn3D(volumeNode):
    viewNode = slicer.app.layoutManager().threeDWidget(0).mrmlViewNode()
    volumeRenderingLogic = slicer.modules.volumerendering.logic()
    renderingNode = volumeRenderingLogic.GetVolumeRenderingDisplayNodeForViewNode(volumeNode, viewNode)
    return renderingNode.GetVisibility() if renderingNode else False


def get_memory_usage(mode="bytes"):
    """Get the Geoslicer memory usage as percent value

    Returns:
        float: the memory usage as percent value
    """
    process = psutil.Process(os.getpid())
    if mode == "bytes":
        mem = process.memory_full_info().uss
    elif mode == "percent":
        mem = process.memory_percent()
    else:
        raise NotImplementedError("The chosen mode is not implemented.")

    return mem


def hide_masking_widget(effect):
    import qt

    widget = effect.scriptedEffect.optionsFrame()
    while widget.objectName != "qMRMLSegmentEditorWidget":
        widget = widget.parent()
    widget = widget.findChild(qt.QGroupBox, "MaskingGroupBox")

    # This widget is shown right after the call to activate,
    # so we hide it on the next event.
    qt.QTimer.singleShot(0, widget.hide)


def fit_segmentation_node_in_view(node: slicer.vtkMRMLNode, segment_id=None, view_filter=["Red", "Green", "Yellow"]):
    """Handle a segment from vtkMRMLSegmentationNode to be centralized and zoomed in the selected views

    Args:
        node (vtkMRMLNode): the segmentation node object
        segment_id (_type_, optional): the segment id from the segmentation node
        view_filter (list, optional): views name to be update.

    Raises:
        ValueError: If node is invalid.
        AttributeError: If segment from node is invalid.
    """
    if node is None or not node.IsA(slicer.vtkMRMLSegmentationNode.__name__):
        raise ValueError(f"Unable to fit. Expecting a Segmentation node but received a {type(node)}.")

    if segment_id is None:
        segment_array = vtk.vtkStringArray()
        node.GetSegmentation().GetSegmentIDs(segment_array)
        if segment_array.GetNumberOfValues() <= 0:
            raise AttributeError(f"Unable to fit Segmentation node because there isn't a segment.")
        segment_id = segment_array.GetValue(0)

    # Center view position to the segment center
    center_ras = np.zeros(3)
    node.GetSegmentCenterRAS(segment_id, center_ras)
    slicer.vtkMRMLSliceNode.JumpAllSlices(slicer.mrmlScene, *center_ras, slicer.vtkMRMLSliceNode.CenteredJumpSlice)

    # Change field of view based on the segment bound values
    bounds_ras = np.zeros(6)
    node.GetRASBounds(bounds_ras)
    _, xmax, _, ymax, _, _ = bounds_ras
    xmax = 1.75 * xmax
    ymax = 1.75 * ymax
    slice_nodes = get_slice_node_views(view_filter=view_filter)
    for slice_node in slice_nodes:
        dim = get_default_view_fov(slice_node.GetName())
        max_proportion = max(dim)
        slice_node.SetFieldOfView(xmax * (dim[0] / max_proportion), ymax * (dim[1] / max_proportion), dim[2])


def get_slice_node_views(view_filter=["Red", "Green", "Yellow"]):
    """Get available vtkMRMLSliceNode at the current mrmlScene

    Args:
        view_filter (list, optional): Filter node of interest by name. Defaults to ["Red", "Green", "Yellow"].

    Returns:
        list: a list of the available vtkMRMLSliceNode objects.
    """
    all_slice_nodes = slicer.util.getNodesByClass("vtkMRMLSliceNode")
    slice_nodes = []
    for slice_node in all_slice_nodes:
        if view_filter is not None and slice_node.GetName() not in view_filter:
            continue

        slice_nodes.append(slice_node)

    return slice_nodes


def get_default_view_fov(view_name: str):
    """Get default Field of View values for default slicer view selected by name.

    Args:
        view_name (str): the slicer view name.

    Returns:
        tuple: The FOV value as tuple (x, y, z)
        None: if the view name FOV was not defined.
    """
    views_fov = {
        "Red": (250.0, 139.57176843774783, 1.0),
        "Green": (250.0, 75.0, 1.0),
        "Yellow": (250.0, 75.0, 1.0),
    }

    return views_fov.get(view_name, None)


def clear_layout(layout):
    while not layout.isEmpty():
        child = layout.takeAt(0)
        if child.layout():
            clear_layout(child.layout())
        elif child.widget():
            widgetToRemove = child.widget()
            layout.removeWidget(widgetToRemove)
            widgetToRemove.deleteLater()


def highlight_error(widget, widget_name="QWidget"):
    if themeIsDark():
        widget.setStyleSheet(widget_name + " {background-color: #600000}")
    else:
        widget.setStyleSheet(widget_name + " {background-color: #FFC0C0}")


def remove_highlight(widget):
    widget.setStyleSheet("")


def reset_style_on_valid_text(line_edit):
    import ctk

    def on_text_changed(text):
        if text:
            line_edit.setStyleSheet("")

    if issubclass(type(line_edit), ctk.ctkPathLineEdit):
        line_edit.currentPathChanged.connect(on_text_changed)
    else:
        line_edit.textChanged.connect(on_text_changed)


def reset_style_on_valid_node(combobox):
    from ltrace.slicer.widget.hierarchy_volume_input import HierarchyVolumeInput

    if isinstance(combobox, HierarchyVolumeInput):
        combobox.resetStyleOnValidNode()
    else:

        def on_node_changed(node):
            if node:
                combobox.setStyleSheet("")

        # This import must be inside the function to avoid erros when importing this file on CLIs
        from qt import QComboBox

        if isinstance(combobox, QComboBox):
            combobox.currentIndexChanged.connect(on_node_changed)
        else:
            combobox.currentNodeChanged.connect(on_node_changed)


class ElapsedTime:
    def __init__(self, print: bool = False, tag: str = "") -> None:
        self.print = print
        self.tag = tag

    def __enter__(self):
        self.time = time.perf_counter()
        return self

    def __exit__(self, type, value, traceback):
        self.time = time.perf_counter() - self.time
        if self.print:
            self.readout = f"Time: {self.time:.3f} seconds"
            if self.tag:
                self.readout = f"[{self.tag}] {self.readout}"
            print(self.readout)


class GitImportError(Exception):
    pass


def install_git_module(remote, collection=False):
    from ltrace.slicer.app import getApplicationInfo

    modules_parent_dir = get_scripted_modules_path().parent
    third_party_dir = modules_parent_dir / "qt-scripted-external-modules"

    repo = clone_or_update_repo(remote, third_party_dir, branch="master", collection=collection)

    return repo

    # modules_folders = (
    #     *(os.path.dirname(slicer.app.launcherExecutableFilePath).split("/")),
    #     *(("lib\\" + geoslicer_version + "\\qt-scripted-modules").split("\\")),
    # )
    # modules_path = os.path.join(modules_folders[0], os.sep, *modules_folders[1:])
    #
    # json_folders = (
    #     *(os.path.dirname(slicer.app.launcherExecutableFilePath).split("/")),
    #     *(("lib\\" + geoslicer_version + "\\qt-scripted-modules\\Resources\\json\\WelcomeGeoSlicer.json").split("\\")),
    # )
    # json_path = os.path.join(json_folders[0], os.sep, *json_folders[1:])
    #
    # new_module_name = remote.split("/")[-1].split(".")[0]
    # new_module_path = os.path.join(modules_path, new_module_name)
    # _ = import_git().Repo.clone_from(remote, new_module_path, env={"GIT_SSL_NO_VERIFY": "1"})
    # config_module_paths(new_module_name, new_module_path, json_path)


def config_module_paths(new_module_name, new_module_path, json_path):
    import json

    if f"{new_module_name}.py" in os.listdir(new_module_path):
        with open(json_path, "r") as json_file:
            data = json.load(json_file)
        data["CUSTOM_REL_PATHS"].append(new_module_path)
        data["VISIBLE_LTRACE_PLUGINS"].append(new_module_name)
        with open(json_path, "w") as json_file:
            json.dump(data, json_file, indent=4)
    else:
        new_modules_subfolders = {}
        for subfolder in [i for i in os.listdir(new_module_path) if os.path.isdir(os.path.join(new_module_path, i))]:
            new_module_subfolder = os.path.join(new_module_path, subfolder)
            if f"{subfolder}.py" in os.listdir(new_module_subfolder):
                new_modules_subfolders[subfolder] = new_module_subfolder
        with open(json_path, "r") as json_file:
            data = json.load(json_file)
        for new_submodule_name, new_submodule_path in new_modules_subfolders.items():
            data["CUSTOM_REL_PATHS"].append(new_submodule_path)
            data["VISIBLE_LTRACE_PLUGINS"].append(new_submodule_name)
        with open(json_path, "w") as json_file:
            json.dump(data, json_file, indent=4)


def handleNodeNameToRegex(nodeName: str) -> str:
    """Get the regex pattern string related to the input's node's name.
       This method avoid the problem when using the slicer.utils.getNode method while the node's name has special characters.

    Args:
        nodeName (str): the node name.

    Returns:
        str: the regex pattern string related to the node's name.
    """
    special_characters = ["[", "]", "(", ")"]
    regex_pattern = "\\" + "|\\".join(special_characters)

    matchs = list(re.finditer(regex_pattern, nodeName))
    for match in reversed(matchs):
        start = match.start()
        end = match.end()
        character = match.group()
        nodeName = nodeName[:start] + "[" + character + "]" + nodeName[end:]

    return nodeName


def make_directory_writable(func=None, path=None, exc_info=None):
    """
    Error handler for ``shutil.rmtree``.

    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.

    If the error is for another reason it re-raises the error.

    Usage : ``shutil.rmtree(path, onerror=make_directory_writable)``
    """
    if path is None:
        raise RuntimeError("Invalid path.")

    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        if func is not None:
            func(path)


def copy_display(from_: slicer.vtkMRMLScalarVolumeNode, to: slicer.vtkMRMLScalarVolumeNode):
    from_display = from_.GetDisplayNode()
    if not from_display:
        return

    to.CreateDefaultDisplayNodes()
    to_display = to.GetDisplayNode()
    to_display.Copy(from_.GetDisplayNode())
    if hasattr(to_display, "AutoWindowLevelOff") and hasattr(to_display, "AutoThresholdOff"):
        to_display.AutoWindowLevelOff()
        to_display.AutoThresholdOff()


def arrayFromVisibleSegmentsBinaryLabelmap(segmentationNode, referenceVolumeNode=None):
    """
    Return voxel array of all visible segment's binary labelmap representation as numpy array.

    Args:
        segmentationNode: source segmentation node.
        referenceVolumeNode: a volume node that determines geometry (origin, spacing, axis directions, extents) of the array.
            If not specified then the volume that was used for setting the segmentation's geometry is used as reference volume.

    Returns:
        nparray: All visible segment data
    """
    import slicer
    import vtk

    # Get reference volume
    if not referenceVolumeNode:
        referenceVolumeNode = getSourceVolume(segmentationNode)
        if not referenceVolumeNode:
            raise RuntimeError(
                "No reference volume is found in the input segmentationNode, therefore a valid referenceVolumeNode input is required."
            )

    # Export segment as vtkImageData (via temporary labelmap volume node)
    labelmapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "__temp__")
    try:
        if not slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
            segmentationNode, labelmapVolumeNode, referenceVolumeNode
        ):
            raise RuntimeError("Export of segment failed.")
        narray = slicer.util.arrayFromVolume(labelmapVolumeNode)
        spacing = labelmapVolumeNode.GetSpacing()
        origin = labelmapVolumeNode.GetOrigin()
    finally:
        slicer.mrmlScene.RemoveNode(labelmapVolumeNode)

    return narray, spacing, origin


class BlockSignals:
    """Usage:
    >>> with BlockSignals(widget):
    >>>     widget.setText("Hello")
    """

    def __init__(self, widget):
        self.widget = widget

    def __enter__(self):
        self.was_blocked = self.widget.blockSignals(True)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.widget.blockSignals(self.was_blocked)


def save_path(pathLineEdit):
    """
    ctkPathLineEdit.addCurrentPathToHistory() sends a lot of undesired currentPathChanged signals.
    """
    with BlockSignals(pathLineEdit):
        pathLineEdit.addCurrentPathToHistory()


def getScalarTypesAsString(scalarType: int):
    return SCALAR_TYPE_LABELS.get(scalarType, "undefined type")


def safe_convert_array(array, dtype):
    dtype = np.dtype(dtype)

    if array.dtype == dtype:
        return array

    if array.dtype.kind not in "fui" or dtype.kind not in "fui":
        raise ValueError("Only numeric types are supported")

    from_float = array.dtype.kind in "f"
    to_int = dtype.kind in "iu"

    if to_int:
        if from_float:
            array = np.round(array)
        type_info = np.iinfo(dtype)
        min_ = type_info.min
        max_ = type_info.max
        array = np.clip(array, min_, max_)

    array = array.astype(dtype)
    return array


def isImageFile(filePath: Union[Path, str]) -> bool:
    """Retrieve if the file at the given path is related to an image file"""
    imageTypes = {"bmp", "gif", "jpeg", "jpg", "png", "webp"}
    if isinstance(filePath, str):
        filePath = Path(filePath)

    return filePath.suffix.replace(".", "").lower() in imageTypes


def singleton(class_):
    """Singleton decorator. Allow a class to behave like a singleton. QObject compatible."""
    instances = {}

    def getinstance(*args, **kwargs):
        if class_ not in instances:
            instances[class_] = class_(*args, **kwargs)
        return instances[class_]

    return getinstance


class WatchSignal:
    """Context manager class to wait until a specific mrmlScene signal is triggered before leaving the context.
    Raises an exception if signal isn't triggered until timeout.
    Example:
    >>> with WatchSignal(signal=slicer.mrmlScene.EndImportEvent, timeout_ms=10000):
    >>>     doSomething()
    >>>     ProjectManager().close() # Close project
    """

    def __init__(self, signal: slicer.vtkMRMLScene.SceneEventType, timeout_ms: int = 2000) -> None:
        self.signal = signal
        self.triggered = False
        self.observer_handler = None
        self.timer = None
        self.timeout_ms = timeout_ms

        assert self.signal is not None and isinstance(
            self.signal, slicer.mrmlScene.SceneEventType
        ), "Invalid mrmlScene signal."

    def _check_triggered_timeout(self) -> None:
        logging.debug(f"WatchSignal [{self.signal}] timeout!")
        if self.timer is None or self.triggered:
            return

        self._remove_timer()
        self._remove_observer()

    def _triggered(self) -> None:
        logging.debug(f"WatchSignal [{self.signal}] triggered!")
        self.triggered = True
        self._remove_timer()
        self._remove_observer()

    def _remove_observer(self) -> None:
        if self.observer_handler is None:
            return

        slicer.mrmlScene.RemoveObserver(self.observer_handler)
        self.observer_handler = None

    def _remove_timer(self) -> None:
        if self.timer is None:
            return

        self.timer.stop()
        self.timer = None

    def __enter__(self) -> None:
        self.observer_handler = slicer.mrmlScene.AddObserver(self.signal, lambda x, y: self._triggered())
        self.timer = self._create_timer(timeout_ms=self.timeout_ms, callback=self._check_triggered_timeout)
        self.timer.start()
        return self

    def __exit__(self, type, value, traceback) -> None:
        if self.triggered:
            return

        while not self.triggered:
            if self.timer is None:
                raise RuntimeError(f"Expected signal {self.signal} to trigger in {self.timeout_ms}ms, but it didn't.")

            time.sleep(0.1)
            slicer.app.processEvents()
            continue

        self._remove_timer()
        self._remove_observer()

    def _create_timer(self, timeout_ms: int, callback: object) -> object:
        import qt

        timer = qt.QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.setInterval(timeout_ms)
        return timer


def isNodeImage2D(nodeId):
    if nodeId is None:
        return False

    node = tryGetNode(nodeId)
    if node is None:
        return False

    is_2d_image = False
    imageData = node.GetImageData()
    if imageData is not None:
        shape = np.array(imageData.GetDimensions())
        shape[shape != 1] = 0
        is_2d_image = any(shape)

    return is_2d_image


def get_scripted_modules_path() -> str:
    lib_path = Path(slicer.app.slicerHome) / "lib"
    lib_geoslicer_path = next(lib_path.glob("GeoSlicer-*"))
    return (lib_geoslicer_path / "qt-scripted-modules").resolve().as_posix()


def hex2Rgb(hex: str, normalize=True) -> Tuple:
    """Convert color hex string to RGB tuple

    Args:
        hex (str): the color hex string.
        normalize (bool, optional): Normalize color value between 0~1 when True, otherwise maintain 0~255 range. Defaults to True.

    Returns:
        Tuple: The RGB color tuple.
    """
    normalizeValue = 255.0 if normalize else 1
    hex = hex.lstrip("#")
    lv = len(hex)
    rgb = tuple(int(hex[i : i + lv // 3], 16) / normalizeValue for i in range(0, lv, lv // 3))
    return rgb


class LazyLoad:
    def __init__(self, moduleName):
        self.moduleName = moduleName
        self.module = None

    def __getattr__(self, name):
        if not self.module:
            moduleInfo = slicer.modules.AppContextInstance.modules.availableModules[self.moduleName]
            sys.path.append(moduleInfo.searchPath)
            self.module = importlib.import_module(self.moduleName)
        return getattr(self.module, name)


class LazyLoad2:
    def __init__(self, importPath: str):
        self.importPath = importPath
        path_ = importPath.split(".")
        self.moduleName = path_[0]
        self.targetModuleName = path_[-1]
        self.module = None

    def __getattr__(self, name):
        if not self.module:
            moduleInfo = slicer.modules.AppContextInstance.modules.availableModules[self.moduleName]
            libraryPath = Path(moduleInfo.searchPath)
            for el in libraryPath.iterdir():
                if el.is_dir() and (el / "__init__.py").exists():
                    sys.path.append(el.as_posix())
            sys.path.append(libraryPath.as_posix())

            self.module = importlib.import_module(self.targetModuleName)

        return getattr(self.module, name)


def checkUniqueNames(nodes):
    nodeNames = set()
    for node in nodes:
        if node.GetName() in nodeNames:
            node.SetName(slicer.mrmlScene.GenerateUniqueName(node.GetName()))
        nodeNames.add(node.GetName())


def arrayPartsFromNode(node: slicer.vtkMRMLNode) -> tuple[np.ndarray, np.ndarray]:
    mmToM = 0.001
    if isinstance(node, slicer.vtkMRMLScalarVolumeNode):
        values = slicer.util.arrayFromVolume(node).copy().squeeze()
        if values.ndim != 2:
            raise ValueError(f"Node has dimension {values.ndim}, expected 2.")

        bounds = [0] * 6
        node.GetBounds(bounds)
        ymax = -bounds[4] * mmToM
        ymin = -bounds[5] * mmToM
        spacing = node.GetSpacing()[2] * mmToM
        depthColumn = np.arange(ymin, ymax - spacing / 2, spacing)

        ijkToRas = np.zeros([3, 3])
        node.GetIJKToRASDirections(ijkToRas)
        if ijkToRas[0][0] > 0:
            values = np.flip(values, axis=0)
        if ijkToRas[1][1] > 0:
            values = np.flip(values, axis=1)
        if ijkToRas[2][2] > 0:
            values = np.flip(values, axis=2)
    elif isinstance(node, slicer.vtkMRMLTableNode):
        if node.GetAttribute("table_type") == "histogram_in_depth":
            df = slicer.util.dataframeFromTable(node)
            df_columns = df.columns
            depthColumn = df[df_columns[0]].to_numpy() * mmToM
            values = df[df_columns[1:]].to_numpy()
        else:
            values = slicer.util.arrayFromTableColumn(node, node.GetColumnName(1))
            depthColumn = slicer.util.arrayFromTableColumn(node, node.GetColumnName(0)) * mmToM
            if depthColumn[0] > depthColumn[-1]:
                depthColumn = np.flipud(depthColumn)
                values = np.flipud(values)

    return depthColumn, values


def maskImageFromMaskArray(maskArray, referenceNode):
    maskImage = vtk.vtkImageData()
    maskImage.SetDimensions(*referenceNode.GetImageData().GetDimensions())
    maskImage.SetSpacing(referenceNode.GetSpacing())
    maskImage.SetOrigin(referenceNode.GetOrigin())

    maskData = vn.numpy_to_vtk(num_array=maskArray.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
    maskData.SetNumberOfComponents(1)
    maskImage.GetPointData().SetScalars(maskData)

    return maskImage


def modifySelectedSegmentByMaskImage(scriptedEffect, maskImage):
    modifierLabelmap = scriptedEffect.defaultModifierLabelmap()
    originalImageToWorldMatrix = vtk.vtkMatrix4x4()
    modifierLabelmap.GetImageToWorldMatrix(originalImageToWorldMatrix)
    modifierLabelmap.DeepCopy(maskImage)

    # Apply changes
    scriptedEffect.modifySelectedSegmentByLabelmap(
        modifierLabelmap,
        slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet,
    )


def modifySelectedSegmentByMaskArray(scriptedEffect, maskArray, referenceNode):
    modifySelectedSegmentByMaskImage(scriptedEffect, maskImageFromMaskArray(maskArray, referenceNode))
