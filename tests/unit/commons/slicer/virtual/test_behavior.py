"""Virtual nodes' save/load behaviour, as the node custom behavior factory builds it."""

import inspect
from unittest.mock import MagicMock

from commons.slicer.node_custom_behavior.defs import TriggerEvent
from commons.slicer.node_custom_behavior.node_custom_behavior_factory import NodeCustomBehaviorFactory
from commons.slicer.virtual.behavior import VirtualNodeCustomBehavior


def test_the_virtual_node_behavior_is_built_the_way_the_factory_builds_it():
    """Built otherwise, every event of a virtual node raised, deleting a 4D node included."""
    node = MagicMock()
    node.GetID.return_value = "vtkMRMLScalarVolumeNode1"

    behavior = VirtualNodeCustomBehavior(node=node, event=TriggerEvent.LOAD, eventArgs={"source": "test"})

    assert behavior._eventArgs == {"source": "test"}


def test_every_registered_behavior_takes_what_the_factory_passes():
    for builder in NodeCustomBehaviorFactory.builders:
        parameters = inspect.signature(builder.__init__).parameters
        assert {"node", "event", "eventArgs"} <= set(parameters), builder.__name__
