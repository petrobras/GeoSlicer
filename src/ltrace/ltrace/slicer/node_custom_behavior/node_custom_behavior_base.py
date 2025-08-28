from abc import abstractmethod
from dataclasses import dataclass
import slicer
import logging
from .defs import TriggerEvent


@dataclass
class CustomBehaviorRequirements:
    nodeTypes: list
    attributes: dict

    def match(self, node: slicer.vtkMRMLNode) -> bool:
        if node is None:
            return False

        # Check node types
        if issubclass(type(node), tuple(self.nodeTypes)) is False:
            return False

        # Check attributes
        for attribute, value in self.attributes.items():
            attr_val = node.GetAttribute(attribute)
            if attr_val != value:
                return False

        return True


class NodeCustomBehaviorBase:
    """Base class used to create custom behavior for slicer.vtkMRMLNode.
    The derived class can implement the folowing methods: '_afterLoad', '_afterSave' and '_beforeSave'.
    """

    def __init__(self, node: slicer.vtkMRMLNode, event: TriggerEvent) -> None:
        self._node = node
        self._event = event

    @abstractmethod
    def _afterLoad(self) -> None:
        """Abstract method for handling node behavior after the node's load process is done inside the project."""
        pass

    def afterLoad(self, **kwargs) -> None:
        """Wrapper for custom behavior after the load process is done."""
        if not self.isValid():
            logging.info("Skipping custom node behavior after the project's loading due the conditions were not met.")
            return
        self._afterLoad()
        self.updateNodeReference()

    @abstractmethod
    def _afterSave(self) -> None:
        """Abstract method for handling node behavior after the node's save process is done inside the project."""
        pass

    def afterSave(self, **kwargs) -> None:
        """Wrapper for custom behavior after the save process is done."""
        if not self.isValid():
            logging.info("Skipping custom node behavior after the project's loading due the conditions were not met.")
            return
        self.updateNodeReference()
        self._afterSave()

    @abstractmethod
    def _beforeSave(self) -> None:
        """Abstract method for handling node behavior before the node's save process is done inside the project."""
        pass

    def beforeSave(self, **kwargs) -> None:
        """Wrapper for custom behavior before the save process is done."""
        self._beforeSave()

    def _onNodeAdded(self, node: slicer.vtkMRMLNode) -> None:
        """Abstract method for handling node behavior when a new node of matchin type is added"""
        pass

    def onNodeAdded(self, **kwargs) -> None:
        node = kwargs.get("node")
        if not node:
            return

        self._onNodeAdded(node=node)

    def _onNodeRemoved(self, node: slicer.vtkMRMLNode) -> None:
        """Abstract method for handling node behavior when a new node of matchin type is removed"""
        pass

    def onNodeRemoved(self, **kwargs) -> None:
        node = kwargs.get("node")
        if not node:
            return

        self._onNodeRemoved(node=node)

    def updateNodeReference(self) -> None:
        """Update the node's object reference. It changes during node' saving/loading process."""
        assert self._node is not None, "Node object is invalid."

        # Update node reference
        node = slicer.mrmlScene.GetNodeByID(self._node.GetID())

        assert node is not None, f"Couldn't retrieve a new node reference for {self._node.GetName()}."
        self._node = node

    def isValid(self) -> bool:
        """Check certains conditions for custom behavior.

        Returns:
            bool: True if the conditions are valid, otherwise returns False.
        """
        return self._node is not None
