from abc import ABC
from ltrace.slicer import helpers

import vtk, slicer
import numpy as np


class CorrelatedLabelMapVolume(ABC):
    """Class to create a correlated label map related to another node.
    Every time the node is modified, the process callback method passed as argument is called.
    When the reference node is deleted, the related label map volume node create by this class is deleted as well.
    """

    def __init__(self, referenceNode, processCallback, name=""):
        if referenceNode is None or processCallback is None:
            raise ValueError("Invalid input. Please pass a valid node object.")

        self._referenceNodeId = referenceNode.GetID() if referenceNode is not None else None
        self._callback = processCallback
        self._observerHandlers = list()
        self._labelMapVolumeNodeId = None
        self._name = name

        self._callback()

        self.__installObservers(referenceNode=referenceNode)

    def __installObservers(self, referenceNode):
        if referenceNode is None:
            return

        self._observerHandlers.append(
            (
                referenceNode,
                referenceNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.__onNodeModified),
            )
        )
        self._observerHandlers.append(
            (
                slicer.mrmlScene,
                slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeRemovedEvent, self.__onNodeRemoved),
            )
        )

        if not isinstance(referenceNode, slicer.vtkMRMLSegmentationNode):
            return

        self._observerHandlers.append(
            (
                referenceNode,
                referenceNode.AddObserver(
                    referenceNode.GetSegmentation().RepresentationModified, self.__onNodeModified
                ),
            )
        )
        self._observerHandlers.append(
            (
                referenceNode,
                referenceNode.AddObserver(referenceNode.GetSegmentation().SegmentAdded, self.__onNodeModified),
            )
        )
        self._observerHandlers.append(
            (
                referenceNode,
                referenceNode.AddObserver(referenceNode.GetSegmentation().SegmentRemoved, self.__onNodeModified),
            )
        )
        self._observerHandlers.append(
            (
                referenceNode,
                referenceNode.AddObserver(referenceNode.GetSegmentation().SegmentModified, self.__onNodeModified),
            )
        )

    def __del__(self):
        self._cleanUp()

    @property
    def referenceNode(self):
        return helpers.tryGetNode(self._referenceNodeId)

    @property
    def labelMapVolumeNode(self):
        return helpers.tryGetNode(self._labelMapVolumeNodeId)

    def __onNodeModified(self, caller, event):
        if not self._isNodeValid():
            return

        self._callback()

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def __onNodeRemoved(self, caller, event, node):
        """Handles node's removal."""
        if node is None or node.GetID() != self._referenceNodeId:
            return

        self._cleanUp()

    def _cleanUp(self):
        """Clears current object's data."""
        for obj, tag in self._observerHandlers:
            obj.RemoveObserver(tag)

        self.__removeLabelMapNode()
        self._referenceNodeId = None

    def _isNodeValid(self):
        return self._referenceNodeId is not None and self._callback is not None

    def __removeLabelMapNode(self):
        if self._labelMapVolumeNodeId is None:
            return

        node = helpers.tryGetNode(self._labelMapVolumeNodeId)
        slicer.mrmlScene.RemoveNode(node)
        self._labelMapVolumeNodeId = None


class ProportionLabelMapVolume(CorrelatedLabelMapVolume):
    """Creates a proportion label map volume"""

    def __init__(self, referenceNode, name=""):
        super().__init__(referenceNode=referenceNode, processCallback=self.__process, name=name)

    def __process(self):
        if self._referenceNodeId is None:
            return

        referenceNode = helpers.tryGetNode(self._referenceNodeId)
        if referenceNode is None:
            return

        labelMapVolumeNode = None
        if isinstance(referenceNode, slicer.vtkMRMLSegmentationNode):
            if self._labelMapVolumeNodeId is None:
                labelMapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
                self._labelMapVolumeNodeId = labelMapVolumeNode.GetID()

            seg = referenceNode.GetSegmentation()
            empty = seg.GetNumberOfSegments() == 0

            if not empty:
                try:
                    seg_id = seg.GetNthSegmentID(0)
                    array = slicer.util.arrayFromSegmentInternalBinaryLabelmap(referenceNode, seg_id)
                    empty = array.max() <= 0
                except (ValueError, AttributeError):
                    empty = True

            if not empty:
                slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
                    referenceNode, self.labelMapVolumeNode, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
                )
        elif isinstance(referenceNode, slicer.vtkMRMLLabelMapVolumeNode):
            labelMapVolumeNode = slicer.mrmlScene.CopyNode(referenceNode)
            self._labelMapVolumeNodeId = labelMapVolumeNode.GetID()

        labelMapVolumeNode = self.labelMapVolumeNode

        if labelMapVolumeNode is None:
            return

        if self._name.replace(" ", ""):
            labelMapVolumeNode.SetName(self._name)

        labelMapVolumeNode.Modified()

        try:
            array = slicer.util.arrayFromVolume(labelMapVolumeNode)
            dataArray = np.array(array, copy=True, dtype=np.uint8)
            proportionDataArray = np.sort(dataArray, axis=2)
            slicer.util.updateVolumeFromArray(labelMapVolumeNode, proportionDataArray)
        except Exception:  # In case where the reference node data is empty:
            pass
