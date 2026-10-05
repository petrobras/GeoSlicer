"""Project save/load behaviour for virtual nodes.

The sample a virtual node holds is small, so it is saved with the scene and the node stays viewable even
when the original data is unreachable (an unmounted share, a dataset moved to another machine). On load the
source is checked: if it changed, the sample is re-read; if it is gone, the node is flagged stale rather
than deleted.

Registered in :class:`ltrace.slicer.node_custom_behavior.node_custom_behavior_factory.NodeCustomBehaviorFactory`.
"""

import logging

import slicer

from ltrace.slicer.node_custom_behavior.defs import TriggerEvent
from ltrace.slicer.node_custom_behavior.node_custom_behavior_base import (
    CustomBehaviorRequirements,
    NodeCustomBehaviorBase,
)

from . import attributes as attrs
from .uri import SCHEME_FILE, VirtualURI


class VirtualNodeCustomBehavior(NodeCustomBehaviorBase):
    REQUIREMENTS = CustomBehaviorRequirements(
        nodeTypes=[
            slicer.vtkMRMLScalarVolumeNode,  # covers vtkMRMLLabelMapVolumeNode
            slicer.vtkMRMLVectorVolumeNode,
            slicer.vtkMRMLTableNode,
        ],
        attributes={attrs.VIRTUAL_NODE: attrs.TRUE},
    )

    def __init__(self, node: slicer.vtkMRMLNode, event: TriggerEvent, eventArgs: dict = None) -> None:
        super().__init__(node=node, event=event, eventArgs=eventArgs)

    def _afterLoad(self) -> None:
        from . import virtual_node

        node = self._node
        node_spec = virtual_node.spec(node)
        if node_spec is None:
            return

        # 4D proxy nodes are virtual too, but their source is a folder plus a pattern: restoring them means
        # rebuilding a player and a preview cache, which the 4D manager does on demand.
        if attrs.is_true(node, attrs.FOURD_PROXY) or VirtualURI.parse(node_spec.uri).scheme != SCHEME_FILE:
            return

        try:
            if virtual_node.refresh(node):
                logging.info(f"Virtual node {node.GetName()} was refreshed from {node_spec.uri}")
        except Exception as error:
            virtual_node.mark_stale(node, True, reason=repr(error))

    def _afterSave(self) -> None:
        pass

    def _beforeSave(self) -> None:
        pass

    def _onNodeAdded(self, node: slicer.vtkMRMLNode) -> None:
        pass

    def _onNodeRemoved(self, node: slicer.vtkMRMLNode) -> None:
        pass

    def _onNodeAboutToBeRemoved(self, node: slicer.vtkMRMLNode) -> None:
        pass
