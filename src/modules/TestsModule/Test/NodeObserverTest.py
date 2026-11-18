import numpy as np
import qt
import slicer

from commons.slicer.node_observer import NodeObserver
from commons.slicer_utils import LTracePluginTest
from commons.slicer.tests.utils import process_events, wait
from unittest.mock import MagicMock


class NodeObserverTest(LTracePluginTest):
    def test_node_observer_on_node_removed(self):
        """
        Tests if node_observer removedSignal is being emitted and only once
        """
        n = 5

        nodeList = [slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", f"test_node_{i}") for i in range(n)]
        observerList = [NodeObserver(node=node, parent=self) for node in nodeList]
        emittedObservers = list()

        def check_observers(observer, observerList):
            assert observer in observerList
            emittedObservers.append(observer)

        for observer in observerList:
            observer.removedSignal.connect(lambda emittedObserver, _: check_observers(emittedObserver, observerList))

        for node in nodeList:
            slicer.mrmlScene.RemoveNode(node)
            del node

        process_events()
        assert len(observerList) == len(emittedObservers), (
            f"Expected {len(observerList)} observers, but got {len(emittedObservers)}"
        )

    def test_node_observer_calling_clear_on_remove(self):
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TestNode")
        nodeObserver = NodeObserver(node=node, parent=self)

        clearMock = MagicMock()
        nodeObserver.clear = clearMock
        assert clearMock.call_count == 0
        assert nodeObserver.node is node

        slicer.mrmlScene.RemoveNode(node)
        process_events()

        assert clearMock.call_count == 1, f"Expected 1 call to clear(), got {clearMock.call_count}"

    def test_node_observer_clear(self):
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TestNode")
        nodeObserver = NodeObserver(node=node, parent=self)

        slicer.mrmlScene.RemoveNode(node)
        process_events()

        currentHandlers = nodeObserver._NodeObserver__observerHandlers
        assert len(currentHandlers) == 0, f"Expected 0 handlers, got {len(currentHandlers)}"
        assert nodeObserver.node is None

    def test_node_observer_modified(self):
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TestNode")
        nodeObserver = NodeObserver(node=node, parent=self)

        modifiedMock = MagicMock()
        nodeObserver.modifiedSignal.connect(modifiedMock)

        node.Modified()

        wait(1)

        assert modifiedMock.call_count == 1, f"Expected 1 call to modifiedSignal, got {modifiedMock.call_count}"

        args, _ = modifiedMock.call_args
        assert len(args) == 2, f"!Expected 2 args, got {len(args)}"
        assert isinstance(args[0], NodeObserver), f"Expected NodeObserver, got {type(args[0])}"
        assert isinstance(args[1], slicer.vtkMRMLScalarVolumeNode), (
            f"Expected vtkMRMLScalarVolumeNode, got {type(args[1])}"
        )

    def test_node_observer_modified_debounce_effect(self):
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TestNode")
        nodeObserver = NodeObserver(node=node, parent=self)

        modifiedMock = MagicMock()
        nodeObserver.modifiedSignal.connect(modifiedMock)

        for i in range(5):
            node.Modified()

        wait(1)

        assert modifiedMock.call_count == 1, f"Expected 1 call to modifiedSignal, got {modifiedMock.call_count}"

    def test_node_observer_modified_after_being_deleted(self):
        """A node removed from the scene keeps its observer attached, so a modified
        event still reaches a NodeObserver whose Qt object is already gone."""
        parent = qt.QObject()
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TestNode")
        nodeObserver = NodeObserver(node=node, parent=parent)

        slicer.mrmlScene.RemoveNode(node)
        process_events()
        parent.delete()

        nodeObserver._NodeObserver__onNodeModified(node, None)

    def test_display_node_modified(self):
        # Create label map volume node
        labelMapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(
            labelMapVolumeNode, np.random.randint(low=0, high=20, size=(10, 10, 10), dtype=np.int16)
        )
        labelMapVolumeNode.CreateDefaultDisplayNodes()
        labelMapVolumeNode.GetDisplayNode().SetAndObserveColorNodeID(
            slicer.mrmlScene.GetFirstNodeByName("Warm1").GetID()
        )
        labelMapVolumeNode.SetSpacing((1000.237000001, 0.001240000000005, 1.0))

        # Create vector volume node
        vectorVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode")
        slicer.util.updateVolumeFromArray(
            vectorVolumeNode, np.random.randint(low=0, high=20, size=(10, 10, 10, 3), dtype=np.int16)
        )
        vectorVolumeNode.CreateDefaultDisplayNodes()

        labelMapObserver = NodeObserver(node=labelMapVolumeNode, parent=self)
        labelMapObserverDisplayNodeModifiedMock = MagicMock()
        labelMapObserver.displayNodeModifiedSignal.connect(labelMapObserverDisplayNodeModifiedMock)

        vectorVolumeObserver = NodeObserver(node=vectorVolumeNode, parent=self)
        vectorVolumeObserverDisplayNodeModifiedMock = MagicMock()
        vectorVolumeObserver.displayNodeModifiedSignal.connect(vectorVolumeObserverDisplayNodeModifiedMock)

        # Assert label map
        labelMapVolumeNode.GetDisplayNode().SetVisibility(True)  # Won't trigger modified event as it is already visible
        labelMapVolumeNode.GetDisplayNode().SetVisibility(False)
        wait(1)
        labelMapObserverDisplayNodeModifiedMock.assert_called_once()

        # Assert vector volume
        vectorVolumeNode.GetDisplayNode().SetVisibility(True)  # Won't trigger modified event as it is already visible
        vectorVolumeNode.GetDisplayNode().SetVisibility(False)
        wait(1)
        vectorVolumeObserverDisplayNodeModifiedMock.assert_called_once()

    def test_display_node_removed(self) -> None:
        """Remove display node from node being observed. Check if the observer related to the display node is removed."""
        labelMapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(
            labelMapVolumeNode, np.random.randint(low=0, high=20, size=(10, 10, 10), dtype=np.int16)
        )
        labelMapVolumeNode.CreateDefaultDisplayNodes()
        labelMapVolumeNode.GetDisplayNode().SetAndObserveColorNodeID(
            slicer.mrmlScene.GetFirstNodeByName("Warm1").GetID()
        )
        labelMapVolumeNode.SetSpacing((1000.237000001, 0.001240000000005, 1.0))

        labelMapObserver = NodeObserver(node=labelMapVolumeNode, parent=self)

        observers = labelMapObserver._NodeObserver__observerHandlers
        assert len(observers) == 3, f"Expected a total of '3' observers. Actual {len(observers)}."
        displayNode = labelMapVolumeNode.GetDisplayNode()
        slicer.mrmlScene.RemoveNode(displayNode)
        wait(0.4)
        assert len(observers) == 2, f"Expected a total of '2' observers. Actual {len(observers)}."

        displayNode = labelMapVolumeNode.GetDisplayNode()
        assert displayNode is None

        labelMapVolumeNode.CreateDefaultDisplayNodes()
        displayNode = labelMapVolumeNode.GetDisplayNode()
        assert displayNode is not None
        wait(0.4)

        assert len(observers) == 3, f"Expected a total of '3' observers. Actual {len(observers)}."
