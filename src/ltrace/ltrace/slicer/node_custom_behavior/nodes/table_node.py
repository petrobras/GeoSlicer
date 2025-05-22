import slicer
import qt

from ltrace.slicer.node_custom_behavior.node_custom_behavior_base import (
    NodeCustomBehaviorBase,
    CustomBehaviorRequirements,
)
from ltrace.slicer.node_custom_behavior.defs import TriggerEvent


class TableNodeCustomBehavior(NodeCustomBehaviorBase):
    """Custom behavior for vtkMRMLTableNode.
    This change forces the related storable node to signalize that it was modified when the node itself is modified."""

    REQUIREMENTS = CustomBehaviorRequirements(nodeTypes=[slicer.vtkMRMLTableNode], attributes={})

    def __init__(self, node: slicer.vtkMRMLNode, event: TriggerEvent) -> None:
        super().__init__(node=node, event=event)

    def _onNodeAdded(self, node: slicer.vtkMRMLNode) -> None:
        node.AddObserver("ModifiedEvent", self.__onNodeModified)

    def _onNodeRemoved(self, node: slicer.vtkMRMLNode) -> None:
        node.RemoveAllObservers()

    def __onNodeModified(self, node: slicer.vtkMRMLNode, event) -> None:
        node.StorableModified()
