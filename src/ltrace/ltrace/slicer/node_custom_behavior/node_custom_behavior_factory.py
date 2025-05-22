from ltrace.slicer.node_custom_behavior.nodes.vector_volume_node_from_image import (
    VectorVolumeNodeFromImageCustomBehavior,
)
from ltrace.slicer.node_custom_behavior.nodes.volume_node import VolumeNodeCustomBehavior
from ltrace.slicer.node_custom_behavior.nodes.segmentation_display_node import SegmentationDisplayNodeCustomBehavior
from ltrace.slicer.node_custom_behavior.nodes.volume_rendering_display_node import (
    VolumeRenderingDisplayNodeCustomBehavior,
)
from ltrace.slicer.node_custom_behavior.nodes.table_node import TableNodeCustomBehavior
from .node_custom_behavior_base import NodeCustomBehaviorBase
from .defs import TriggerEvent

import slicer


class NodeCustomBehaviorFactory:
    """Factory for custom behavior node. New custom behavior node classes should be added to 'builders' list attribute.

    Raises:
        ValueError: if input's node don't match with any custom behavior specified in 'builders'.

    Returns:
        NodeCustomBehaviorBase: a custom behavior node class object.
    """

    builders = [
        VectorVolumeNodeFromImageCustomBehavior,
        VolumeNodeCustomBehavior,
        SegmentationDisplayNodeCustomBehavior,
        VolumeRenderingDisplayNodeCustomBehavior,
        TableNodeCustomBehavior,
    ]

    @staticmethod
    def factory(node: slicer.vtkMRMLNode, event: TriggerEvent) -> list[NodeCustomBehaviorBase]:
        if node is None:
            raise ValueError("Invalid node to create custom behavior.")

        customBehaviorList = []
        for cls in NodeCustomBehaviorFactory.builders:
            if cls.REQUIREMENTS.match(node):
                customBehaviorList.append(cls(node=node, event=event))

        return customBehaviorList
