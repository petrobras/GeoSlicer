import qt
import slicer
import vtk
import logging
import traceback

from typing import Optional
from ltrace.slicer import helpers
from ltrace.slicer.debounce_caller import DebounceCaller


class NodeObserver(qt.QObject):
    """Class responsible to emit signals (Qt.Signal) from events related to the related node."""

    modifiedSignal = qt.Signal(object, object)
    removedSignal = qt.Signal(object, object)
    displayNodeModifiedSignal = qt.Signal(object, object)

    def __init__(self, node: slicer.vtkMRMLNode, parent: qt.QObject = None, *args, **kwargs) -> None:
        super().__init__(parent, *args, **kwargs)
        if node is None:
            raise ValueError("Invalid node reference to observe.")

        self.__nodeId = node.GetID()
        self.__observerHandlers = list()
        self.__observerHandlers.append(
            (
                node.GetID(),
                node.AddObserver("ModifiedEvent", self.__onNodeModified),
            )
        )
        self.__observerHandlers.append(
            (
                slicer.mrmlScene,
                slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeRemovedEvent, self.__onNodeRemoved),
            )
        )
        if node.IsA("vtkMRMLSegmentationNode"):
            for eventType in (
                slicer.vtkSegmentation.RepresentationModified,
                slicer.vtkSegmentation.SegmentModified,
            ):
                self.__observerHandlers.append(
                    (
                        node.GetID(),
                        node.AddObserver(eventType, self.__onNodeModified),
                    )
                )

        self._addDisplayNodeObserver(node)
        self.__signalModifiedDebouncer = DebounceCaller(parent=self, intervalMs=100)
        self.__signalModifiedDebouncer.triggered.connect(self.onModifiedSignalToBeTriggered)
        self.__signalDisplayNodeModifiedDebouncer = DebounceCaller(parent=self, intervalMs=100)
        self.__signalDisplayNodeModifiedDebouncer.triggered.connect(self.onDisplayNodeModifiedSignalToBeTriggered)
        self.destroyed.connect(self.__del__)

    def __del__(self) -> None:
        self.clear()

    @property
    def node(self) -> Optional[slicer.vtkMRMLNode]:
        return helpers.tryGetNode(self.__nodeId)

    def __onNodeModified(self, caller: Optional[slicer.vtkMRMLNode], event: object) -> None:
        """Handles node's modification."""
        self.__signalModifiedDebouncer(self, caller)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def __onNodeRemoved(self, caller, event: object, node):
        """Handles node's removal."""
        if node is None:
            return

        # Check if display node was deleted
        removedNodeId = node.GetID()
        totalHandlers = len(self.__observerHandlers)
        for idx, objHandlerTuple in enumerate(reversed(self.__observerHandlers[:])):
            obj, handler = objHandlerTuple
            if isinstance(obj, str) and removedNodeId == obj:
                self.__observerHandlers.pop(totalHandlers - 1 - idx)
                logging.debug(f"Observer '{handler}' removed from NodeObserver({self.__nodeId}) ")

        if removedNodeId != self.__nodeId:
            return

        try:
            self.removedSignal.emit(self, node)
            self.clear()
        except Exception as error:
            logging.debug(
                f"Bypassing error from node observer related to node {node.GetName()} ({node.GetID()}): {error}. Traceback:\n{traceback.format_exc()}"
            )

    def clear(self):
        """Clears current object's data."""
        try:
            self.modifiedSignal.disconnect()
            self.removedSignal.disconnect()
        except (ValueError, SystemError):
            # Object has been deleted
            pass

        for obj, tag in reversed(self.__observerHandlers):
            if obj is None:
                continue

            if isinstance(obj, str):  # is a node ID
                obj = helpers.tryGetNode(obj)
                if obj is None:
                    continue

            obj.RemoveObserver(tag)

        self.__observerHandlers.clear()
        self.__nodeId = None

    def onModifiedSignalToBeTriggered(self, *args, **kwargs) -> None:
        node = self.node
        if hasattr(node, "GetDisplayNode"):
            displayNode = node.GetDisplayNode()
            if displayNode is not None and not self.isNodeBeingObserved(displayNode):
                self._addDisplayNodeObserver(node)

        self.modifiedSignal.emit(*args, **kwargs)

    def onDisplayNodeModifiedSignalToBeTriggered(self, *args, **kwargs) -> None:
        self.displayNodeModifiedSignal.emit(*args, **kwargs)

    def __onDisplayNodeModified(self, caller: Optional[slicer.vtkMRMLNode], event: object) -> None:
        self.__signalDisplayNodeModifiedDebouncer(self, caller)

    def isNodeBeingObserved(self, targetNode: slicer.vtkMRMLNode):
        if targetNode is None:
            return False

        for obj, tag in self.__observerHandlers:
            if not isinstance(obj, str):  # Not a node ID
                continue

            if obj == targetNode.GetID():
                return True

        return False

    def _addDisplayNodeObserver(self, node: slicer.vtkMRMLNode) -> None:
        if not hasattr(node, "GetDisplayNode") or node.GetDisplayNode() is None:
            return

        displayNode = node.GetDisplayNode()
        self.__observerHandlers.append(
            (
                displayNode.GetID(),
                displayNode.AddObserver("ModifiedEvent", self.__onDisplayNodeModified),
            )
        )
