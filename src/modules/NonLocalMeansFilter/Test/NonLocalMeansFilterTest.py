import numpy as np
import slicer

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import check_for_message_box, process_events, wait_cli_to_finish

NOISE_STD = 10.0


def createNoisyVolume(name, rgb=False):
    """Creates a noisy uint16 volume, or a uint8 greyscale image stored as RGB, and its noiseless version."""
    clean = np.full((20, 40, 40), 100, dtype=np.uint16)
    clean[:, 10:30, 10:30] = 140
    clean[5:15, 15:25, 15:25] = 180
    noise = np.random.default_rng(0).normal(0, NOISE_STD, clean.shape)
    noisy = np.clip(np.rint(clean + noise), 0, 255)
    if rgb:
        clean = clean.astype(np.uint8)
        noisy = np.repeat(noisy[..., np.newaxis], 3, axis=-1).astype(np.uint8)
    else:
        noisy = noisy.astype(np.uint16)
    nodeClass = "vtkMRMLVectorVolumeNode" if rgb else "vtkMRMLScalarVolumeNode"
    volume = slicer.mrmlScene.AddNewNodeByClass(nodeClass, name)
    slicer.util.updateVolumeFromArray(volume, noisy)
    volume.CreateDefaultDisplayNodes()
    return volume, clean


class NonLocalMeansFilterTest(LTracePluginTest):
    def test_default_interface_configuration(self):
        widget = self._module_widget

        self.assertEqual(widget.modeComboBox.currentText, "3D")
        self.assertAlmostEqual(widget.strengthSpinBox.value, 0.5)
        self.assertTrue(widget.estimateSigmaCheckBox.isChecked())
        self.assertFalse(widget.sigmaSpinBox.enabled)
        self.assertEqual(widget.patchSizeSpinBox.value, 5)
        self.assertEqual(widget.patchDistanceSpinBox.value, 6)
        self.assertTrue(widget.fastModeCheckBox.isChecked())

    def test_mode_change_updates_default_strength_only(self):
        widget = self._module_widget

        widget.modeComboBox.setCurrentIndex(1)
        process_events()
        self.assertAlmostEqual(widget.strengthSpinBox.value, 0.7)

        widget.modeComboBox.setCurrentIndex(0)
        process_events()
        self.assertAlmostEqual(widget.strengthSpinBox.value, 0.5)

        widget.strengthSpinBox.setValue(0.55)
        widget.modeComboBox.setCurrentIndex(1)
        process_events()
        self.assertAlmostEqual(widget.strengthSpinBox.value, 0.55)

    def test_fast_mode_is_only_editable_in_2d(self):
        widget = self._module_widget
        self.assertFalse(widget.fastModeCheckBox.enabled)

        widget.modeComboBox.setCurrentIndex(1)
        process_events()
        self.assertTrue(widget.fastModeCheckBox.enabled)

        widget.modeComboBox.setCurrentIndex(0)
        process_events()
        self.assertFalse(widget.fastModeCheckBox.enabled)

    def test_manual_sigma_is_enabled_when_estimation_is_unchecked(self):
        widget = self._module_widget

        widget.estimateSigmaCheckBox.setChecked(False)
        process_events()

        self.assertTrue(widget.sigmaSpinBox.enabled)

    def test_apply_without_input_prompts_message(self):
        with check_for_message_box("Please select an input image."):
            self._module_widget.buttons.applyBtn.click()

    def test_apply_3d(self):
        self._run_and_check(modeIndex=0, outputName="NoisyVolume3D_NLM")

    def test_apply_2d(self):
        self._run_and_check(modeIndex=1, outputName="NoisyVolume2D_NLM")

    def test_rgb_warning_is_shown_only_for_rgb_input(self):
        widget = self._module_widget
        greyVolume, _ = createNoisyVolume("GreyVolume")
        rgbVolume, _ = createNoisyVolume("RgbVolume", rgb=True)

        widget.inputImageComboBox.setCurrentNode(rgbVolume)
        process_events()
        self.assertTrue(widget.rgbWarningLabel.visible)

        widget.inputImageComboBox.setCurrentNode(greyVolume)
        process_events()
        self.assertFalse(widget.rgbWarningLabel.visible)

    def test_apply_rgb_outputs_greyscale(self):
        output = self._run_and_check(modeIndex=1, outputName="NoisyVolumeRgb_NLM", rgb=True)

        self.assertFalse(output.IsA("vtkMRMLVectorVolumeNode"))
        self.assertEqual(output.GetImageData().GetNumberOfScalarComponents(), 1)
        # The temporary greyscale copy sent to the CLI is removed
        self.assertEqual(len(slicer.util.getNodes("*_greyscale*")), 0)

    def _run_and_check(self, modeIndex, outputName, rgb=False):
        widget = self._module_widget
        volume, clean = createNoisyVolume(outputName.replace("_NLM", ""), rgb=rgb)

        widget.inputImageComboBox.setCurrentNode(volume)
        widget.modeComboBox.setCurrentIndex(modeIndex)
        process_events()
        self.assertEqual(widget.outputVolumeNameLineEdit.text, outputName)

        widget.buttons.applyBtn.click()
        process_events()
        wait_cli_to_finish(widget.logic.cliNode)

        output = slicer.util.getNode(outputName)
        inputArray = slicer.util.arrayFromVolume(volume)
        if rgb:
            inputArray = inputArray[..., 0]
        outputArray = slicer.util.arrayFromVolume(output)
        self.assertEqual(outputArray.dtype, inputArray.dtype)
        self.assertEqual(outputArray.shape, inputArray.shape)

        errorBefore = np.abs(inputArray.astype(float) - clean).mean()
        errorAfter = np.abs(outputArray.astype(float) - clean).mean()
        self.assertLess(errorAfter, 0.6 * errorBefore)

        self.assertTrue(widget.buttons.applyBtn.enabled)
        self.assertTrue(widget.usedParametersLabel.visible)
        return output
