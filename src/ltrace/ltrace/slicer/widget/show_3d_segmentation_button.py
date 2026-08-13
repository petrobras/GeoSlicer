from ltrace.slicer.node_observer import NodeObserver
from ltrace.slicer import helpers
from typing import Optional

import logging
import slicer
import qt
import vtk


class Show3DSegmentationModel(qt.QObject):
    visibilityChanged = qt.Signal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        self._nodeId: Optional[str] = None
        self._nodeObserver: Optional[NodeObserver] = None
        self._clonedLabelMapVolumeNodeId: Optional[str] = None
        self.__show: bool = False

    @property
    def labelMapVolume(self) -> slicer.vtkMRMLLabelMapVolumeNode:
        return helpers.tryGetNode(self._clonedLabelMapVolumeNodeId)

    @property
    def segmentationNode(self) -> slicer.vtkMRMLSegmentationNode:
        return helpers.tryGetNode(self._nodeId)

    @segmentationNode.setter
    def segmentationNode(self, node: slicer.vtkMRMLSegmentationNode) -> None:
        if node is None and self._nodeId is None:
            return

        if node is not None and node.GetID() == self._nodeId:
            return

        self._setCurrentNode(node)

    @property
    def show(self) -> bool:
        return self.__show

    @show.setter
    def show(self, mode: bool) -> None:
        if self.__show == mode:
            return

        if mode and self._clonedLabelMapVolumeNodeId is None:
            created = self._createLabelMapVolumeNode()
            if not created:
                return

        self.__show = mode
        self._setVolumeVisibility(volumeNode=self.labelMapVolume, mode=self.__show)
        self.visibilityChanged.emit(self.show)

    def _createLabelMapVolumeNode(self) -> bool:
        """Handle Label Map Volume Node creation.

        Returns:
            bool: True if node was created, otherwise False.
        """
        if self._clonedLabelMapVolumeNodeId is not None:
            return True

        currentNode = self.segmentationNode
        if currentNode is None:
            logging.warning("Unable to render a Segmentation using invalid data.")
            return False

        referenceVolumeNodeId = helpers.getReferenceNode(currentNode)
        referenceVolumeNode = helpers.tryGetNode(referenceVolumeNodeId) if referenceVolumeNodeId else None
        if referenceVolumeNode is None:
            logging.warning("Unable to render a Segmentation without a defined Reference Node.")
            return False

        # Create a cloned LabelMapVolumeNode from Segmentation
        currentLabelMapVolumeNode = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLLabelMapVolumeNode, f"{currentNode.GetName()}_LabelMap", environment="custom_visualization"
        )
        self._clonedLabelMapVolumeNodeId = currentLabelMapVolumeNode.GetID()
        self._exportAllSegments(currentNode, currentLabelMapVolumeNode, referenceVolumeNode)

        return True

    def _exportAllSegments(
        self,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
        referenceVolumeNode: slicer.vtkMRMLVolumeNode,
    ) -> None:
        segmentIds = vtk.vtkStringArray()
        segmentationNode.GetSegmentation().GetSegmentIDs(segmentIds)
        slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
            segmentationNode, segmentIds, labelMapVolumeNode, referenceVolumeNode
        )
        self._syncSegmentOpacities(segmentationNode, labelMapVolumeNode)

    def _syncSegmentOpacities(
        self,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ) -> None:
        displayNode = segmentationNode.GetDisplayNode()
        labelMapDisplayNode = labelMapVolumeNode.GetDisplayNode()
        colorNode = labelMapDisplayNode.GetColorNode() if labelMapDisplayNode is not None else None
        if displayNode is None or colorNode is None:
            return

        segmentation = segmentationNode.GetSegmentation()
        state = colorNode.StartModify()
        for index in range(segmentation.GetNumberOfSegments()):
            segmentId = segmentation.GetNthSegmentID(index)
            label = colorNode.GetColorIndexByName(segmentation.GetSegment(segmentId).GetName())
            if label > 0:
                colorNode.SetOpacity(label, 1.0 if displayNode.GetSegmentVisibility(segmentId) else 0.0)
        colorNode.EndModify(state)

    def _setCurrentNode(self, node: slicer.vtkMRMLSegmentationNode) -> None:
        if node is not None and node.GetID() == self._nodeId:
            return

        if self._nodeObserver is not None:
            self._nodeObserver.deleteLater()
            self._nodeObserver = None

        if self.show:
            self.show = False

        # Remove cloned Label Map Volume Node
        clonedLabelMapVolumeNode = helpers.tryGetNode(self._clonedLabelMapVolumeNodeId)
        if clonedLabelMapVolumeNode is not None:
            slicer.mrmlScene.RemoveNode(clonedLabelMapVolumeNode)
        self._clonedLabelMapVolumeNodeId = None

        # Store current node
        currentNode = helpers.tryGetNode(node.GetID()) if node is not None else None
        self._nodeId = currentNode.GetID() if currentNode is not None else None

        if currentNode is None:
            return

        # Create observer
        self._nodeObserver = NodeObserver(node=currentNode, parent=self)
        self._nodeObserver.modifiedSignal.connect(self._onNodeModified)
        self._nodeObserver.removedSignal.connect(self._onNodeRemoved)
        self._nodeObserver.displayNodeModifiedSignal.connect(self._onDisplayNodeModified)

    def _onNodeModified(self, observer: NodeObserver, node: Optional[slicer.vtkMRMLSegmentationNode]) -> None:
        if node is None:
            logging.info("Node modified event with invalid node reference.")
            return

        if self._nodeId is None or self._clonedLabelMapVolumeNodeId is None:
            logging.debug("Node modified event with invalid node id.")
            return

        referenceVolumeNode = helpers.tryGetNode(helpers.getReferenceNode(node))
        if referenceVolumeNode is None:
            logging.warning("Unable to render a segmentation without a Reference Node.")
            return

        currentLabelMapVolumeNode = helpers.tryGetNode(self._clonedLabelMapVolumeNodeId)
        self._exportAllSegments(node, currentLabelMapVolumeNode, referenceVolumeNode)

    def _onNodeRemoved(self, observer: NodeObserver, node: Optional[slicer.vtkMRMLSegmentationNode]) -> None:
        self._cleanUp()

    def _onDisplayNodeModified(self, observer: NodeObserver, displayNode: Optional[slicer.vtkMRMLDisplayNode]) -> None:
        if displayNode is None:
            logging.info("Display node modified event with invalid display node reference.")
            return

        if self._nodeId is None:
            logging.info("Display node modified event with invalid node id")
            self._cleanUp()
            return

        currentNode = helpers.tryGetNode(self._nodeId)
        if currentNode is None:
            logging.info("Display node modified event with invalid node reference ")
            self._cleanUp()
            return

        currentLabelMapVolumeNode = helpers.tryGetNode(self._clonedLabelMapVolumeNodeId)
        if currentLabelMapVolumeNode is None:
            logging.info("Display node modified event with invalid label map volume node reference ")
            self._cleanUp()
            return

        self._syncSegmentOpacities(currentNode, currentLabelMapVolumeNode)

        if not displayNode.GetVisibility():
            self.show = False
            return

        self._setVolumeVisibility(volumeNode=currentLabelMapVolumeNode, mode=self.show)

    def toggleVisibility(self, _state: bool = None) -> None:
        currentLabelMapVolumeNode = helpers.tryGetNode(self._clonedLabelMapVolumeNodeId)
        if currentLabelMapVolumeNode is None and self._nodeId is None:
            logging.info("Invalid label map volume node reference during attempt to toggle visibility")
            self._cleanUp()
            return

        visibility = (
            helpers.getVolumeVisibilityIn3D(currentLabelMapVolumeNode)
            if currentLabelMapVolumeNode is not None
            else False
        )

        self.show = not visibility

        if self.show:
            # Update Segmentation visibility to visible as well
            if not self.segmentationNode:
                return

            displayNode = self.segmentationNode.GetDisplayNode()
            if not displayNode:
                return

            if not bool(displayNode.GetVisibility()):
                state = self._nodeObserver.blockSignals(True)
                displayNode.SetVisibility(True)
                self._nodeObserver.blockSignals(state)

    def _setVolumeVisibility(self, volumeNode: slicer.vtkMRMLVolumeNode, mode: bool) -> None:
        if volumeNode is None:
            logging.warning("Attempt to set volume node visibility to a NoneType node reference.")
            return

        if helpers.getVolumeVisibilityIn3D(volumeNode=volumeNode) == mode:
            logging.debug("Attempt to set volume node 3D visibility to the same state")
            return

        helpers.setVolumeVisibilityIn3D(volumeNode=volumeNode, visible=mode)

    def _cleanUp(self):
        self._nodeId = None

        if self._clonedLabelMapVolumeNodeId is not None:
            slicer.mrmlScene.RemoveNode(helpers.tryGetNode(self._clonedLabelMapVolumeNodeId))

        self._clonedLabelMapVolumeNodeId = None
        self.show = False
        self._removeObserver()

    def _removeObserver(self):
        if self._nodeObserver is None:
            return

        self._nodeObserver.deleteLater()
        self._nodeObserver = None


class Show3DSegmentationButton(qt.QPushButton):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._model = Show3DSegmentationModel(parent=self)
        self.setUp()

    def setUp(self) -> None:
        self._updateButtonLabel()
        self.clicked.connect(self._onClicked)
        self._model.visibilityChanged.connect(self._onModelVisibilityChanged)

    def _updateButtonLabel(self):
        self.text = "Show 3D" if not self._model.show else "Hide 3D"

    def segmentationNode(self) -> slicer.vtkMRMLSegmentationNode:
        return self._model.segmentationNode

    def setSegmentationNode(self, node: slicer.vtkMRMLSegmentationNode) -> None:
        self._model.segmentationNode = node

    def _onClicked(self):
        self._model.toggleVisibility()

    def _onModelVisibilityChanged(self, _mode: bool):
        self._updateButtonLabel()
