from .custom_behavior_image_node import CustomBehaviorImageNode
from .custom_behavior_node_base import CustomBehaviorNodeBase
from .defs import TriggerEvent

import slicer


class CustomBehaviorNodeFactory:
    """Factory for custom behavior node. New custom behavior node classes should be added to 'builders' list attribute.

    Raises:
        ValueError: if input's node don't match with any custom behavior specified in 'builders'.

    Returns:
        CustomBehaviorNodeBase: a custom behavior node class object.
    """

    builders = [CustomBehaviorImageNode]

    @staticmethod
    def factory(node: slicer.vtkMRMLNode, event: TriggerEvent) -> CustomBehaviorNodeBase:
        for cls in CustomBehaviorNodeFactory.builders:
            if cls.REQUIREMENTS.match(node):
                return cls(node=node, event=event)

        raise ValueError(f"Node {node.GetName()} doesn't apply for a custom behavior")
