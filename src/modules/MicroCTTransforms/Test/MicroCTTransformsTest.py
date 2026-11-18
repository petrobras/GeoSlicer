import slicer
import numpy as np
import qt

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events, waitCondition


class MicroCTTransformsTest(LTracePluginTest):
    """
    Integration test for the MicroCTTransforms module.
    """

    def create_test_volume_node(self, name):
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", name)
        arr = np.ones((10, 20, 30))
        slicer.util.updateVolumeFromArray(node, arr)
        node.CreateDefaultDisplayNodes()
        return node

    def test_initial_state(self):
        """Verify the initial state of the widget's interface."""
        widget = self._module_widget
        self.assertIsNone(widget.movingNodeSelector.currentNode())
        self.assertFalse(widget.buttonsWidget.visible)
        self.assertFalse(widget.displayEditCollapsibleWidget.visible)

    def DISABLED_test_select_moving_volume(self):
        """Test selecting and deselecting a moving volume.
        Currently crashing the application.
        TODO (PL-3079): Review this test.
        """
        volumeNode = self.create_test_volume_node("TestVolume")
        widget = self._module_widget
        widget.movingNodeSelector.setCurrentNode(volumeNode)
        process_events()

        self.assertTrue(widget.buttonsWidget.visible)
        self.assertTrue(widget.displayEditCollapsibleWidget.visible)
        self.assertIsNotNone(widget.transformNodeSelector.currentNode())

        # Check if node is in the transformed tree view
        found = False
        model = widget.transformedTreeView.model()
        for i in range(model.rowCount()):
            index = model.index(i, 0)
            if index.data() == volumeNode.GetName():
                found = True
                break
        self.assertTrue(found, "Node not moved to transformed view")

        widget.movingNodeSelector.setCurrentNode(None)
        waitCondition(lambda: not widget.buttonsWidget.visible)

        self.assertFalse(widget.displayEditCollapsibleWidget.visible)

    def test_node_observer_lifetime(self):
        """Checks the node observer handlers lifetime handling."""
        widget = self._module_widget

        # enter() is called during test setup, which calls renewHiddenTransformNode
        self.assertIsNotNone(widget.transformNodeObserverHandler)
        transformNode = widget.transformNodeSelector.currentNode()
        self.assertIsNotNone(transformNode)

        # Delete the transform node externally
        slicer.mrmlScene.RemoveNode(transformNode)
        process_events()

        # Calling renewHiddenTransformNode again should work without errors
        try:
            widget.renewHiddenTransformNode()
            process_events()
            self.assertTrue(True, "renewHiddenTransformNode did not raise an error")
        except Exception as e:
            self.fail(f"renewHiddenTransformNode raised an exception: {e}")

        self.assertIsNotNone(widget.transformNodeObserverHandler)
        newTransformNode = widget.transformNodeSelector.currentNode()
        self.assertIsNotNone(newTransformNode)
        self.assertNotEqual(transformNode, newTransformNode)

    def DISABLED_test_undo_redo_translation(self):
        """Test undo and redo for a translation change.
        Currently crashing the application.
        TODO (PL-3079): Review this test.
        """
        volumeNode = self.create_test_volume_node("TestVolume")
        widget = self._module_widget
        widget.movingNodeSelector.setCurrentNode(volumeNode)
        process_events()

        transformNode = widget.transformNodeSelector.currentNode()
        initialMatrix = slicer.util.arrayFromTransformMatrix(transformNode).copy()

        self.assertFalse(widget.undoButton.enabled)
        self.assertFalse(widget.redoButton.enabled)

        # Translate
        translationSliders = widget.findChild(qt.QObject, "TranslationSliders")
        xSlider = translationSliders.findChild(slicer.qMRMLLinearTransformSlider, "LRSlider")
        xSlider.setValue(10.0)
        widget.onSliderReleased()  # this saves undo state
        process_events()

        self.assertTrue(widget.undoButton.enabled)
        matrixAfterTranslation = slicer.util.arrayFromTransformMatrix(transformNode)
        self.assertFalse(np.allclose(initialMatrix, matrixAfterTranslation))

        # Undo
        widget.onUndoButtonClicked()
        process_events()

        matrixAfterUndo = slicer.util.arrayFromTransformMatrix(transformNode)
        self.assertTrue(np.allclose(initialMatrix, matrixAfterUndo))
        self.assertTrue(widget.redoButton.enabled)

        # Redo
        widget.onRedoButtonClicked()
        process_events()

        matrixAfterRedo = slicer.util.arrayFromTransformMatrix(transformNode)
        self.assertTrue(np.allclose(matrixAfterTranslation, matrixAfterRedo))
