import logging
import typing

import ctk
import numpy as np
import qt
import slicer

from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer.microct import pcrMinMaxFromTableNode


class CheckableSegmentListBoard(qt.QWidget):

    itemChanged = qt.Signal(qt.QListWidgetItem)

    def __init__(self, defaultState=qt.Qt.Unchecked, parent=None):
        super().__init__(parent)

        self.defaultState = defaultState

        qt.QVBoxLayout(self)

        self.segmentList = qt.QListWidget()
        self.segmentList.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Fixed)
        self.segmentList.setFixedHeight(120)
        self.segmentList.setToolTip(
            "List of segments available in the segmentation. Check the segments to account them in the computation."
        )

        self.segmentListCollapsible = ctk.ctkCollapsibleButton()
        self.segmentListCollapsible.text = "Segments"
        self.segmentListCollapsible.collapsed = True
        self.segmentListCollapsible.flat = True

        bodyLayout = qt.QVBoxLayout(self.segmentListCollapsible)
        bodyLayout.addWidget(self.segmentList)

        self.layout().addWidget(self.segmentListCollapsible)

        self.segmentList.itemChanged.connect(self.itemChanged)

    def check(self, index):
        item = self.segmentList.item(index)
        item.setCheckState(qt.Qt.Checked)

    def showBoard(self):
        self.segmentListCollapsible.collapsed = False

    def setData(self, node):
        self.segmentList.clear()

        if node is None:
            return

        if node.IsA("vtkMRMLSegmentationNode"):
            self.setDataFromSegmentation(node)
        else:
            self.setDataFromLabelMap(node)

    def setDataFromSegmentation(self, node):
        segmentation = node.GetSegmentation()

        displayNode = node.GetDisplayNode()

        for index in range(segmentation.GetNumberOfSegments()):
            segment = segmentation.GetNthSegment(index)
            segmentID = segmentation.GetNthSegmentID(index)
            if segment and displayNode.GetSegmentVisibility(segmentID):
                self.segmentList.addItem(
                    self.createItem(
                        segment.GetName(),
                        np.array(segment.GetColor() + (1,)),
                        segmentID,
                        self.defaultState,
                    )
                )

    def setDataFromLabelMap(self, node):
        inputColors = node.GetDisplayNode().GetColorNode()

        for index in range(inputColors.GetNumberOfColors()):
            color = np.zeros(4)
            inputColors.GetColor(index, color)
            name = inputColors.GetColorName(index)

            self.segmentList.addItem(
                self.createItem(
                    name,
                    np.array(color),
                    index,
                    self.defaultState,
                )
            )

    def setStateByID(self, id, state):
        for index in range(self.segmentList.count):
            item = self.segmentList.item(index)
            if item.data(qt.Qt.UserRole) == id:
                item.setCheckState(state)

    def getCheckedItems(self) -> typing.List[str]:
        checkedItems = []
        for index in range(self.segmentList.count):
            item = self.segmentList.item(index)
            if item.checkState() == qt.Qt.Checked:
                if item.data(qt.Qt.UserRole):
                    checkedItems.append(item.data(qt.Qt.UserRole))
        return checkedItems

    def getCheckedIndexes(self) -> typing.List[int]:
        checkedIndexes = []
        for index in range(self.segmentList.count):
            item = self.segmentList.item(index)
            if item.checkState() == qt.Qt.Checked:
                checkedIndexes.append(index)
        return checkedIndexes

    @classmethod
    def createItem(cls, name, color, segmentID=None, state=qt.Qt.Unchecked):
        from ltrace.slicer.widgets import ColoredIcon

        item = qt.QListWidgetItem(name)
        item.setFlags(item.flags() | qt.Qt.ItemIsUserCheckable)
        item.setCheckState(state)
        icon = ColoredIcon(*[int(c * 255) for c in color[:3]])
        item.setIcon(icon)
        item.setData(qt.Qt.UserRole, segmentID)
        return item


class DoubleImageWithSegmentationInputWidget(qt.QWidget):

    imageSelected = qt.Signal(str)
    segmentationSelected = qt.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = qt.QFormLayout(self)

        self.saturatedImageNodeInput = hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLScalarVolumeNode"])
        self.saturatedPCRTableNodeInput = hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLTableNode"])
        self.dryImageNodeInput = hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLScalarVolumeNode"])
        self.dryPCRTableNodeInput = hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLTableNode"])

        segmentationSelectorLayout = qt.QHBoxLayout()
        self.segmentationNodeSelectorInput = qt.QComboBox()
        self.segmentationNodeSelectorInput.addItem("None")
        self.roiNodeSelectorInput = qt.QComboBox()
        self.roiNodeSelectorInput.addItem("Optional")

        self.allEnablerCheckBox = qt.QCheckBox("All")

        segmentationSelectorLayout.addWidget(self.segmentationNodeSelectorInput)
        segmentationSelectorLayout.addWidget(self.allEnablerCheckBox)

        self.segmentsBoard = CheckableSegmentListBoard(defaultState=qt.Qt.Checked)

        layout.addRow("Saturated Image: ", self.saturatedImageNodeInput)
        layout.addRow("Dry Image: ", self.dryImageNodeInput)
        layout.addRow("Segmentation: ", segmentationSelectorLayout)
        layout.addRow("Region: ", self.roiNodeSelectorInput)
        layout.addRow(self.segmentsBoard)

        self.saturatedImageNodeInput.currentItemChanged.connect(self.imageSelectedHandler)
        self.dryImageNodeInput.currentItemChanged.connect(self.imageSelectedHandler)

        self.segmentationNodeSelectorInput.currentIndexChanged.connect(self.segmentationSelectedHandler)

        self.segmentationSelected.connect(self.drawSegmentListBoard)

        self.allEnablerCheckBox.toggled.connect(lambda checked: self.updateSegmentation(useAll=checked))

    def imageSelectedHandler(self, itemHierarchyTreeId):
        treeNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        node = treeNode.GetItemDataNode(itemHierarchyTreeId)

        if not node:
            return

        self.updateSegmentation(useAll=self.allEnablerCheckBox.isChecked())

        self.imageSelected.emit(node.GetID())
        self.checkInput(node)

    def updateSegmentation(self, useAll=False):

        self.segmentationNodeSelectorInput.clear()
        self.segmentationNodeSelectorInput.addItem("None")

        self.roiNodeSelectorInput.clear()
        self.roiNodeSelectorInput.addItem("None")

        if useAll:
            for node in slicer.mrmlScene.GetNodesByClass("vtkMRMLSegmentationNode"):
                segName = node.GetName()
                self.segmentationNodeSelectorInput.addItem(segName, node)
                self.roiNodeSelectorInput.addItem(segName, node)
        else:
            saturatedSegmentations = getAssociatedSegmentationNodes(self.saturatedImageNodeInput.currentNode())
            drySegmentations = getAssociatedSegmentationNodes(self.dryImageNodeInput.currentNode())

            set_ = {s.GetID(): s for s in [*saturatedSegmentations, *drySegmentations]}

            for segmentation in set_.values():
                segName = segmentation.GetName()
                self.segmentationNodeSelectorInput.addItem(segName, segmentation)
                self.roiNodeSelectorInput.addItem(segName, segmentation)

    def segmentationSelectedHandler(self, index):
        segmentation = self.segmentationNodeSelectorInput.itemData(index)
        self.segmentationSelected.emit(segmentation.GetID() if segmentation else None)

    def drawSegmentListBoard(self):
        segmentation = self.segmentationNodeSelectorInput.currentData
        self.segmentsBoard.setData(segmentation)
        self.segmentsBoard.showBoard()

    def checkInput(self, node):
        # TODO PCR here is ok? maybe another place
        try:
            minPCR, maxPCR = pcrMinMaxFromTableNode(node)
            logging.info(f"PCR data linked to {node.GetName()} with min: {minPCR} and max: {maxPCR}")
        except:
            pass
            # try:
            #     pcrNode = pcrFromFile(node)
            #
            #     if pcrNode:
            #         node.SetAttribute("PCR", pcrNode.GetID())
            #
            #     minPCR, maxPCR = pcrMinMaxFromTableNode(node)
            #
            #     logging.info(f"PCR file loaded for {node.GetName()} with min: {minPCR} and max: {maxPCR}")
            # except FileNotFoundError:
            #     logging.debug("No PCR file found in the directory")
            # except:
            #     import traceback
            #
            #     traceback.print_exc()
            #     logging.warning(f"Failed to load PCR for Image: {node.GetName()}")


class ObservableWidget(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._observers = []

    def addObserver(self, observer):
        self._observers.append(observer)

    def notifyObservers(self, *args, **kwargs):
        for observer in self._observers:
            observer(*args, **kwargs)


class SegmentedImageInputWidget(ObservableWidget):

    imageSelected = qt.Signal(str)
    segmentationSelected = qt.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.imageNodeInput = None
        self.segmentationNodeSelectorInput = None

        self.setup()

    def setup(self):
        qt.QFormLayout(self)
        self.setupInputs()
        self.setupConnections()

    def setupInputs(self):
        self.imageNodeInput = hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLScalarVolumeNode"])

        self.segmentationNodeSelectorInput = qt.QComboBox()
        self.segmentationNodeSelectorInput.addItem("None")
        self.addObserver(self.updateSegmentation)

        self.layout().addRow("Image: ", self.imageNodeInput)
        self.layout().addRow("Segmentation: ", self.segmentationNodeSelectorInput)

    def setupConnections(self):
        self.imageNodeInput.currentItemChanged.connect(self.imageSelectedHandler)
        self.segmentationNodeSelectorInput.currentIndexChanged.connect(self.segmentationSelectedHandler)

    def imageSelectedHandler(self, itemHierarchyTreeId):
        treeNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        node = treeNode.GetItemDataNode(itemHierarchyTreeId)

        if not node:
            return

        segmentations = getAssociatedSegmentationNodes(node)

        self.notifyObservers(segmentations)

        self.imageSelected.emit(node.GetID())

    def segmentationSelectedHandler(self, index):
        segmentation = self.segmentationNodeSelectorInput.itemData(index)
        if segmentation:
            self.segmentationSelected.emit(segmentation.GetID())

    def updateSegmentation(self, segmentations):
        self.segmentationNodeSelectorInput.clear()
        self.segmentationNodeSelectorInput.addItem("None")
        for segmentation in segmentations:
            self.segmentationNodeSelectorInput.addItem(segmentation.GetName(), segmentation)


class SegmentedImageWithROIInputWidget(SegmentedImageInputWidget):

    roiSelected = qt.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def setupInputs(self):
        super().setupInputs()

        self.roiNodeSelectorInput = qt.QComboBox()
        self.roiNodeSelectorInput.addItem("None")

        self.addObserver(self.updateROI)

        self.layout().addRow("Mask: ", self.roiNodeSelectorInput)

    def setupConnections(self):
        super().setupConnections()

        self.roiNodeSelectorInput.currentIndexChanged.connect(self.roiSelectedHandler)

    def roiSelectedHandler(self, index):
        roi = self.roiNodeSelectorInput.itemData(index)
        if roi:
            self.roiSelected.emit(roi.GetID())

    def updateROI(self, segmentations):
        self.roiNodeSelectorInput.clear()
        self.roiNodeSelectorInput.addItem("None")
        for segmentation in segmentations:
            self.roiNodeSelectorInput.addItem(segmentation.GetName(), segmentation)


def getAssociatedSegmentationNodes(scalarVolumeNode):
    """
    This function receives a scalar volume node and returns all segmentation nodes associated with it.
    """
    if not scalarVolumeNode:
        return []

    associatedSegmentationNodes = []
    scalarVolumeNodeID = scalarVolumeNode.GetID()
    for node in slicer.mrmlScene.GetNodesByClass("vtkMRMLSegmentationNode"):
        if (
            node.GetNodeReferenceID("referenceVolume") == scalarVolumeNodeID
            or node.GetNodeReferenceID("referenceImageGeometryRef") == scalarVolumeNodeID
        ):
            associatedSegmentationNodes.append(node)
    return associatedSegmentationNodes
