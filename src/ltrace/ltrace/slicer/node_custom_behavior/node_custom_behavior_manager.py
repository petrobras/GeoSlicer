import slicer
import vtk
import logging

from .node_custom_behavior_factory import NodeCustomBehaviorFactory
from .node_custom_behavior_base import NodeCustomBehaviorBase
from .defs import TriggerEvent


class NodeCustomBehaviorManager:
    """Class to handle custom behavior node initialization and runtime operation."""

    def __init__(self) -> None:
        self.__triggerEvent: TriggerEvent = TriggerEvent.NONE
        self.__customBehaviorNodeObservers = []
        self.__installNodeCustomBehaviorObservers()

    def __del__(self) -> None:
        self.__uninstallNodeCustomBehaviorObservers()

    @property
    def triggerEvent(self) -> TriggerEvent:
        return self.__triggerEvent

    @triggerEvent.setter
    def triggerEvent(self, triggerEvent: TriggerEvent):
        if self.__triggerEvent == triggerEvent:
            return

        self.__triggerEvent = triggerEvent

    def reset(self) -> None:
        self.__triggerEvent = TriggerEvent.NONE

    def __installNodeCustomBehaviorObservers(self) -> None:
        if len(self.__customBehaviorNodeObservers) > 0:
            self.__uninstallNodeCustomBehaviorObservers()

        self.__customBehaviorNodeObservers.extend(
            [
                slicer.mrmlScene.AddObserver(
                    slicer.mrmlScene.EndImportEvent, lambda x, y: self.behaviorCallback(method="afterLoad")
                ),
                slicer.mrmlScene.AddObserver(
                    slicer.mrmlScene.StartSaveEvent, lambda x, y: self.behaviorCallback(method="beforeSave")
                ),
                slicer.mrmlScene.AddObserver(
                    slicer.mrmlScene.EndSaveEvent, lambda x, y: self.behaviorCallback(method="afterSave")
                ),
                slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeAddedEvent, self.__onNodeAdded),
                slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeRemovedEvent, self.__onNodeRemoved),
            ]
        )

    def __uninstallNodeCustomBehaviorObservers(self) -> None:
        for observer in self.__customBehaviorNodeObservers:
            slicer.mrmlScene.RemoveObserver(observer)

        self.__customBehaviorNodeObservers.clear()

    def behaviorCallback(self, method: str, **kwargs) -> None:
        for customBehavior in self.__getAllNodeCustomBehaviors():
            if not hasattr(customBehavior, method):
                logging.error(
                    f"NodeCustomBehaviorManager: Invalid method '{method}' for custom behavior {customBehavior.__class__.__name__}"
                )
                continue

            callback = getattr(customBehavior, method)
            callback(**kwargs)

        self.reset()

    def __getAllNodeCustomBehaviors(self) -> list[NodeCustomBehaviorBase]:
        customBehaviorNodes = []
        for node in slicer.util.getNodes().values():
            for customBehavior in self.__getNodeCustomBehaviorsByNode(node):
                customBehaviorNodes.append(customBehavior)

        return customBehaviorNodes

    def __getNodeCustomBehaviorsByNode(self, node: slicer.vtkMRMLNode) -> list[NodeCustomBehaviorBase]:
        customBehaviors: list[NodeCustomBehaviorBase] = []
        try:
            customBehaviors = NodeCustomBehaviorFactory.factory(node, event=self.__triggerEvent)
        except ValueError as error:
            logging.error(error)

        return customBehaviors

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def __onNodeAdded(self, caller: object, eventId: object, callData: vtk.vtkObject) -> None:
        """Handle slicer' node added to scene event."""
        if not self.__isValidBehaviorNode(callData):
            return

        self.__triggerEvent = TriggerEvent.NODE_ADDED

        for customBehavior in self.__getNodeCustomBehaviorsByNode(callData):
            if not hasattr(customBehavior, "onNodeAdded"):
                logging.error(
                    f"NodeCustomBehaviorManager: Invalid method 'onNodeAdded' for custom behavior {customBehavior.__class__.__name__}"
                )
                continue

            customBehavior.onNodeAdded(node=callData)

        self.reset()

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def __onNodeRemoved(self, caller: object, eventId: object, callData: vtk.vtkObject):
        """Handles node's removal."""
        if callData is None:
            return

        if not self.__isValidBehaviorNode(callData):
            return

        self.__triggerEvent = TriggerEvent.NODE_REMOVED

        for customBehavior in self.__getNodeCustomBehaviorsByNode(callData):
            if not hasattr(customBehavior, "onNodeRemoved"):
                logging.error(
                    f"NodeCustomBehaviorManager: Invalid method 'onNodeRemoved' for custom behavior {customBehavior.__class__.__name__}"
                )
                continue

            customBehavior.onNodeRemoved(node=callData)

        self.reset()

    def __isValidBehaviorNode(self, node):
        return not issubclass(
            type(node),
            (
                slicer.vtkMRMLModelNode,
                slicer.vtkMRMLColorTableNode,
                slicer.vtkMRMLSubjectHierarchyNode,
                slicer.vtkMRMLTransformNode,
                slicer.vtkMRMLSliceDisplayNode,
                slicer.vtkMRMLTableViewNode,
                slicer.vtkMRMLSegmentEditorNode,
            ),
        ) and not (isinstance(node, slicer.vtkMRMLTableNode) and node.GetName() == "Default mineral colors")
