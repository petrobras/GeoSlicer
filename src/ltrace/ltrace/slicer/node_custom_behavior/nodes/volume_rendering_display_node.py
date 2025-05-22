import slicer
import qt

from ltrace.slicer.node_custom_behavior.node_custom_behavior_base import (
    NodeCustomBehaviorBase,
    CustomBehaviorRequirements,
)
from ltrace.slicer.node_custom_behavior.defs import TriggerEvent
from ltrace.slicer.hierarchy_visibility_manager import HierarchyVisibilityManager


class VolumeRenderingDisplayNodeCustomBehavior(NodeCustomBehaviorBase):
    """Custom behavior for vtkMRMLVolumeRenderingDisplayNode"""

    REQUIREMENTS = CustomBehaviorRequirements(nodeTypes=[slicer.vtkMRMLVolumeRenderingDisplayNode], attributes={})

    def __init__(self, node: slicer.vtkMRMLNode, event: TriggerEvent) -> None:
        super().__init__(node=node, event=event)

    def _onNodeAdded(self, node: slicer.vtkMRMLNode) -> None:
        node.SetFollowVolumeDisplayNode(True)
        HierarchyVisibilityManager(node, lambda _node: _node.GetVolumeNode())

    def _onNodeRemoved(self, node: slicer.vtkMRMLNode) -> None:
        node.RemoveAllObservers()
