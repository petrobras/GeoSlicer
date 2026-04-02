import slicer
import qt
import logging

from ltrace.slicer import ui
from ltrace.slicer.widget.rename_dialog import RenameDialog
from ltrace.slicer.metadata import copy_metadata
from ltrace.slicer.helpers import (
    moveNodeTo,
    clone_volume,
    copy_hierarchy_attributes,
    tryGetNode,
)


class CloneAndRenameWidget(qt.QWidget):
    signalCloneNode = qt.Signal(str)
    signalRenameNode = qt.Signal(str)

    def __init__(self, nodeType: str = "Volume", suffix: str = "", parent=None) -> None:
        super().__init__(parent)

        self.nodeID = None
        self.sourceNodeID = None
        self.setupWidget(nodeType, parent=parent)
        self.suffix = suffix

    def setupWidget(self, nodeType, parent=None) -> None:
        self.cloneButton = ui.ButtonWidget(
            text=f"Clone {nodeType}",
            tooltip=f"Clone the input {nodeType}",
            object_name="cloneVolumeButton",
            enabled=False,
            onClick=self.onCloneClicked,
        )

        self.renameButton = ui.ButtonWidget(
            text=f"Rename {nodeType}",
            tooltip=f"Rename the input {nodeType}",
            object_name="renameVolumeButton",
            enabled=False,
            onClick=self.onRenameClicked,
        )

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.setContentsMargins(6, 0, 6, 0)
        buttonsLayout.addStretch(1)
        buttonsLayout.addWidget(self.cloneButton)
        buttonsLayout.addWidget(self.renameButton)

        self.setLayout(buttonsLayout)

    def onCloneClicked(self) -> None:
        node = tryGetNode(self.nodeID)
        if not node:
            return

        try:
            sourceNode = tryGetNode(self.sourceNodeID)
            clonedNode = cloneNode(node, sourceNode, name=node.GetName() + self.suffix)
            self.signalCloneNode.emit(clonedNode.GetID())
        except Exception as e:
            logging.error(f"Error cloning node: {e}")
            slicer.util.errorDisplay("An error occurred while cloning the node")

    def onRenameClicked(self) -> None:
        sourceNode = tryGetNode(self.nodeID)
        if not sourceNode:
            return

        try:
            accepted, name = requestName(sourceNode.GetName())
            if accepted and name != sourceNode.GetName():
                sourceNode.SetName(name)
                self.signalRenameNode.emit(sourceNode.GetID())
        except Exception as e:
            logging.error(f"Error renaming node: {e}")
            slicer.util.errorDisplay("An error occurred while renaming the node")

    def setNodeID(self, nodeID: str = None) -> None:
        node = tryGetNode(nodeID)

        if node is not None:
            self.nodeID = nodeID
            self.cloneButton.enabled = True
            self.renameButton.enabled = True
        else:
            self.nodeID = None
            self.cloneButton.enabled = False
            self.renameButton.enabled = False

    def setSourceNodeID(self, sourceNodeID: str = None) -> None:
        node = tryGetNode(sourceNodeID)

        if node is not None:
            self.sourceNodeID = sourceNodeID
        else:
            self.sourceNodeID = None


def cloneNode(node, sourceNode=None, name=None):
    if isinstance(node, slicer.vtkMRMLSegmentationNode):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemIDToClone = subjectHierarchyNode.GetItemByDataNode(node)
        clonedItemID = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(
            subjectHierarchyNode, itemIDToClone
        )
        clonedNode = subjectHierarchyNode.GetItemDataNode(clonedItemID)
        clonedNode.SetAttribute("ImageLogSegmentation", "True")
        clonedNode.SetName(name)
        if sourceNode:
            clonedNode.SetReferenceImageGeometryParameterFromVolumeNode(sourceNode)

        previousDisplayNode = node.GetDisplayNode()
        previousDisplayNode.SetVisibility(False)
        copy_metadata(node, clonedNode)
        copy_hierarchy_attributes(node, clonedNode)

    else:
        clonedNode = clone_volume(node, name, as_temporary=False)
        clonedNode.CopyReferences(node)

    placeNodeWith(node, clonedNode)

    return clonedNode


def requestName(sourceNodeName=None):
    renameDialog = RenameDialog(slicer.modules.AppContextInstance.mainWindow)
    renameDialog.objectName = "renameDialog"

    renameDialog.setOutputName(sourceNodeName)
    if not renameDialog.exec_():
        return False, sourceNodeName

    newName = renameDialog.getOutputName()

    if newName != sourceNodeName:
        newName = slicer.mrmlScene.GenerateUniqueName(renameDialog.getOutputName())
    return True, newName


def placeNodeWith(destinationNode, node):
    nodeId = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemByDataNode(destinationNode)
    folder = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemParent(nodeId)
    moveNodeTo(folder, node)
