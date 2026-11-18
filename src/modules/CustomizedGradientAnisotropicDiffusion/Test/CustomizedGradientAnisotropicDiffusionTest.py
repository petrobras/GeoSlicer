import slicer
import numpy as np
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import wait_cli_to_finish, process_events


class CustomizedGradientAnisotropicDiffusionTest(LTracePluginTest):
    def test_display_threshold(self):
        array = np.random.rand(200, 200, 200) * 1000
        max_ = 21234.56789123456
        array[40:70, 40:70] = max_
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TestVolume")
        slicer.util.updateVolumeFromArray(volume, array)

        volume.CreateDefaultDisplayNodes()
        volume.GetDisplayNode().SetVisibility(True)
        volume.GetDisplayNode().ApplyThresholdOn()
        volume.GetDisplayNode().SetUpperThreshold(max_)

        widget = self._module_widget

        widget.inputVolumeComboBox.setCurrentNode(volume)
        widget.conductanceSliderWidget.setValue(0.01)
        widget.iterationsSliderWidget.setValue(1)
        widget.timeStepSliderWidget.setValue(0.0625)
        widget.applyButton.click()

        process_events()

        cli_node = widget.logic.cliNode
        wait_cli_to_finish(cli_node)

        output = slicer.util.getNode("TestVolume_GradDiffusion")
        display = output.GetDisplayNode()
        self.assertTrue(display.GetApplyThreshold())
        upper = display.GetUpperThreshold()
        array = slicer.util.arrayFromVolume(output)
        self.assertTrue(array.max() <= upper)
        self.assertTrue(upper > max_)

    def test_cancel_preview_picking(self):
        widget = self._module_widget

        # Create a dummy volume
        array = np.random.rand(10, 10, 10)
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TestVolumeForPreview")
        slicer.util.updateVolumeFromArray(volume, array)

        widget.inputVolumeComboBox.setCurrentNode(volume)
        process_events()

        # Store current layout
        layout_manager = slicer.app.layoutManager()
        initial_layout = layout_manager.layout

        # Click preview button to start picking
        self.assertTrue(widget.togglePreviewButton.enabled)
        self.assertFalse(widget.logic.previewEnabled)
        widget.togglePreviewButton.click()
        process_events()

        # Check that picking has started
        self.assertFalse(widget.togglePreviewButton.enabled)
        self.assertIn("Picking a spot", widget.togglePreviewButton.text)

        # Simulate Esc key press to cancel picking
        widget.markup.cancel_picking()
        widget.markup.finish_callback(widget.markup, -1)
        process_events()

        # Check that the layout hasn't changed
        self.assertEqual(initial_layout, layout_manager.layout)

        # Check that layout has not changed and button is back to normal
        current_layout = layout_manager.layout
        self.assertEqual(initial_layout, current_layout)
        self.assertTrue(widget.togglePreviewButton.enabled)
        self.assertIn("Pick spot", widget.togglePreviewButton.text)
        self.assertFalse(widget.logic.previewEnabled)

    def test_cancel_apply(self):
        widget = self._module_widget

        # Create a dummy volume
        array = np.random.rand(50, 50, 50)
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TestVolumeToCancel")
        slicer.util.updateVolumeFromArray(volume, array)

        widget.inputVolumeComboBox.setCurrentNode(volume)
        widget.conductanceSliderWidget.setValue(1.0)
        widget.iterationsSliderWidget.setValue(100)  # High iterations to ensure it runs long enough to cancel
        widget.timeStepSliderWidget.setValue(0.0625)

        # Verify initial state
        self.assertTrue(widget.applyButton.enabled)
        self.assertFalse(widget.cancelButton.enabled)

        # Start process
        widget.applyButton.click()
        process_events()

        # Check running state
        self.assertFalse(widget.applyButton.enabled)
        self.assertTrue(widget.cancelButton.enabled)
        self.assertTrue(widget.logic.computingFilter)

        # Cancel process
        widget.cancelButton.click()
        process_events()

        # Wait for CLI to finish (cancelled)
        wait_cli_to_finish(widget.logic.cliNode, timeout_sec=10)
        process_events()

        # Check final state
        self.assertTrue(widget.applyButton.enabled)
        self.assertFalse(widget.cancelButton.enabled)
        self.assertFalse(widget.logic.computingFilter)

        # Verify output node is gone
        output_name = widget.outputVolumeNameLineEdit.text
        with self.assertRaises(slicer.util.MRMLNodeNotFoundException):
            slicer.util.getNode(output_name)

        # Cleanup
        slicer.mrmlScene.RemoveNode(volume)
