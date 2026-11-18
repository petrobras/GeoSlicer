import slicer
import numpy as np

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events, waitCondition, wait


class UnwrapRegistrationTest(LTracePluginTest):
    """
    Integration test for the UnwrapRegistration module.
    """

    def pre_setup(self):
        self.imageNode = self.create_test_image_node()

    def create_test_image_node(self):
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TestUnwrapImage")
        node.SetAttribute("Volume type", "Well unwrap")
        # Create a simple array that is easy to check for rolls
        arr = np.zeros((4, 4, 360))
        arr[:, :, 90] = 1
        arr[:, :, 180] = 2
        arr[:, :, 270] = 3
        slicer.util.updateVolumeFromArray(node, arr)
        node.CreateDefaultDisplayNodes()
        return node

    def test_initial_state(self):
        """Verify the initial state of the widget's interface."""
        self.assertFalse(self._module_widget.depthSliderWidget.enabled)
        self.assertFalse(self._module_widget.orientationSliderWidget.enabled)
        self.assertFalse(self._module_widget.applyButton.enabled)
        self.assertFalse(self._module_widget.cancelButton.enabled)
        self.assertFalse(self._module_widget.undoButton.enabled)
        self.assertFalse(self._module_widget.redoButton.enabled)
        self.assertFalse(self._module_widget.saveButton.enabled)
        self.assertFalse(self._module_widget.resetButton.enabled)

    def DISABLED_test_input_image_selection_and_deselection(self):
        """Test the behavior of selecting and deselecting an input image.
        Disabled due to 'imageComboBox' current node changed callback only being executed after the test finishing.
        TODO (PL-3078): Unwrap Registration improvements.
        """
        widget = self._module_widget

        # Select image
        widget.imageComboBox.setCurrentNode(self.imageNode)
        process_events()

        self.assertTrue(widget.depthSliderWidget.enabled)
        self.assertTrue(widget.orientationSliderWidget.enabled)
        self.assertTrue(widget.registering)
        self.assertIsNotNone(widget.transformNode)

        # Deselect image
        widget.imageComboBox.setCurrentNode(None)
        process_events()
        wait(0.5)

        self.assertFalse(widget.depthSliderWidget.enabled)
        self.assertFalse(widget.orientationSliderWidget.enabled)
        self.assertFalse(widget.registering)
        self.assertIsNone(widget.transformNode)

    def test_observers_lifetime(self):
        """Test the node observer handlers' lifetime management."""
        widget = self._module_widget
        self.assertEqual(len(widget.observers), 0)

        widget.imageComboBox.setCurrentNode(self.imageNode)
        process_events()

        self.assertTrue(widget.registering)
        self.assertEqual(len(widget.observers), 2)

        widget.stopRegistration()
        process_events()

        waitCondition(lambda: widget.registering is False)
        self.assertEqual(len(widget.observers), 0)
        self.assertIsNone(widget.transformNode)

    def test_depth_change_updates_transform(self):
        """Test if changing the depth slider updates the transform node."""
        widget = self._module_widget
        widget.imageComboBox.setCurrentNode(self.imageNode)
        process_events()

        initialTransformArray = slicer.util.arrayFromTransformMatrix(widget.transformNode).copy()

        widget.depthSliderWidget.value = 1.23
        process_events()

        newTransformArray = slicer.util.arrayFromTransformMatrix(widget.transformNode)

        self.assertNotEqual(initialTransformArray[2, 3], newTransformArray[2, 3])
        self.assertAlmostEqual(newTransformArray[2, 3], initialTransformArray[2, 3] + 1.23 * 1000)

    def test_orientation_change_updates_image(self):
        """Test if changing the orientation slider updates the image data by rolling it."""
        widget = self._module_widget
        widget.imageComboBox.setCurrentNode(self.imageNode)
        process_events()

        initialImageArray = slicer.util.arrayFromVolume(self.imageNode).copy()

        orientationDegrees = 90
        widget.orientationSliderWidget.value = orientationDegrees
        process_events()

        rolledArray = slicer.util.arrayFromVolume(self.imageNode)

        imageWidth = initialImageArray.shape[2]
        rollValue = int(np.round((orientationDegrees / 360) * imageWidth))
        expectedRolledArray = np.roll(initialImageArray, rollValue, axis=2)

        self.assertTrue(np.array_equal(rolledArray, expectedRolledArray))

    def test_apply_and_undo_redo_actions(self):
        """Test Apply, Undo and Redo button functionality.
        TODO (PL-3078): Unwrap Registration improvements.
        Review this test due to undo button not being disabled after first undo action.
        """
        widget = self._module_widget
        widget.imageComboBox.setCurrentNode(self.imageNode)
        process_events()

        # Initial state
        initialImageArray = slicer.util.arrayFromVolume(self.imageNode).copy()

        # Modify depth and orientation
        widget.depthSliderWidget.value = 0.5
        widget.orientationSliderWidget.value = 45
        process_events()

        # Apply changes
        widget.applyButton.click()
        process_events()

        # Check state after apply
        self.assertFalse(widget.applyButton.enabled)
        self.assertTrue(widget.undoButton.enabled)
        self.assertFalse(widget.redoButton.enabled)

        # Undo
        widget.undoButton.click()
        process_events()

        # Check state after undo
        imageAfterUndo = slicer.util.arrayFromVolume(self.imageNode)
        # self.assertTrue(np.allclose(transformAfterUndo, initialTransformArray))
        self.assertTrue(np.array_equal(imageAfterUndo, initialImageArray))
        # self.assertFalse(widget.undoButton.enabled)
        self.assertTrue(widget.redoButton.enabled)

        # Redo
        widget.redoButton.click()
        process_events()

        # Check state after redo
        # self.assertFalse(np.allclose(initialTransformArray, slicer.util.arrayFromTransformMatrix(widget.transformNode)))
        self.assertFalse(np.array_equal(initialImageArray, slicer.util.arrayFromVolume(self.imageNode)))
        self.assertTrue(widget.undoButton.enabled)
        self.assertFalse(widget.redoButton.enabled)

    def test_cancel_button_reverts_changes(self):
        """Test if the Cancel button reverts transient slider changes."""
        widget = self._module_widget
        widget.imageComboBox.setCurrentNode(self.imageNode)
        process_events()

        initialTransformArray = slicer.util.arrayFromTransformMatrix(widget.transformNode).copy()
        initialImageArray = slicer.util.arrayFromVolume(self.imageNode).copy()

        # Modify sliders
        widget.depthSliderWidget.value = -0.7
        widget.orientationSliderWidget.value = 180
        process_events()

        self.assertTrue(widget.applyButton.enabled)
        self.assertTrue(widget.cancelButton.enabled)

        # Cancel changes
        widget.cancelButton.click()
        process_events()

        transformAfterCancel = slicer.util.arrayFromTransformMatrix(widget.transformNode)
        imageAfterCancel = slicer.util.arrayFromVolume(self.imageNode)

        self.assertTrue(np.allclose(transformAfterCancel, initialTransformArray))
        self.assertTrue(np.array_equal(imageAfterCancel, initialImageArray))
        self.assertFalse(widget.applyButton.enabled)
        self.assertFalse(widget.cancelButton.enabled)
