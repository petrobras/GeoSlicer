import slicer
import os
from pathlib import Path
import qt
from math import isclose
from scipy.signal import find_peaks

from commons.slicer.helpers import arrayPartsFromNode, tryGetNode
from commons.slicer.data_utils import tableNodeToDataFrame
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, wait

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
TEST_PROJECT_FILE = TEST_RESOURCES_DIR / "psd_volume/psd_volume.mrml"
TEST_SYNTH_PROJECT_FILE = TEST_RESOURCES_DIR / "synth_spheres/synth_spheres.mrml"
TEST_PRESETS_FULLPATH_TEMP = Path(slicer.app.temporaryPath).absolute() / "presets" / "test_PSDPerDepthPresets.json"
TEST_PRESETS_DIR_TEMP = Path(slicer.app.temporaryPath).absolute() / "presets"


class PSDPerDepthTest(LTracePluginTest):
    MODULE_NAME = "PSDPerDepth"

    def pre_setup(self):
        """
        Runs before the setup, so the module can be initialized before any widget is created
        """
        pass

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = {
            "input_selector": self.find_widget("Input PSD Volume Selector"),
            "depth_interval_spin_box": self.find_widget("Depth Interval Spin Box"),
            "nbins_spin_box": self.find_widget("Number of Histograms Bins Spin Box"),
            "log_x_axis_check_box": self.find_widget("Log X Axis Check Box"),
            "output_prefix_line_edit": self.find_widget("Output Prefix Line Edit"),
            "apply_button": self.find_widget("Apply Button"),
            "progress_bar": self.find_widget("Progress Bar"),
            "internal_binning_log_check_box": self.find_widget("Internal Binning Log Check Box"),
        }

    def tear_down(self):
        pass

    def test_default_interface_configuration(self):
        inputSelector = self._widgets["input_selector"]
        depthIntervalSpinBox = self._widgets["depth_interval_spin_box"]
        nbinsSpinBox = self._widgets["nbins_spin_box"]
        logXAxisCheckBox = self._widgets["log_x_axis_check_box"]
        outputPrefixLineEdit = self._widgets["output_prefix_line_edit"]
        applyButton = self._widgets["apply_button"]

        # logic = self._module_widget.logic

        # self.presets = logic.getPresets(TEST_PRESETS_FULLPATH_TEMP)

        self.assertIsNone(inputSelector.currentNode())
        self.assertEqual(depthIntervalSpinBox.value, 1.0)
        self.assertEqual(nbinsSpinBox.value, 20)
        self.assertFalse(logXAxisCheckBox.isChecked())
        self.assertEqual(outputPrefixLineEdit.text, "")
        self.assertFalse(applyButton.enabled)

        assert [depthIntervalSpinBox.minimum, depthIntervalSpinBox.maximum] == [0.01, 1000]

    def test_generate_psds(self):
        inputSelector = self._widgets["input_selector"]
        depthIntervalSpinBox = self._widgets["depth_interval_spin_box"]
        applyButton = self._widgets["apply_button"]

        load_project(TEST_PROJECT_FILE)

        logic = self._module_widget.logic

        PSDVolume = tryGetNode("Segmentation-label_cropped_PSD")
        assert PSDVolume is not None, (
            "Expected PSD volume node 'Segmentation-label_cropped_PSD' to exist in the loaded scene"
        )

        openViews = len(slicer.modules.AppContextInstance.imageLogDataLogic.imageLogViewList)

        # Selecting our volume should open it in a new view
        inputSelector.setCurrentNode(None)
        inputSelector.setCurrentNode(PSDVolume)
        wait(5.0)
        assert len(slicer.modules.AppContextInstance.imageLogDataLogic.imageLogViewList) == openViews + 1, (
            "A new view should have been created with PSD volume"
        )
        openViews += 1

        depthStepLimits = self._module_widget.getDepthIntervalLimits()
        assert depthStepLimits == [depthIntervalSpinBox.minimum, depthIntervalSpinBox.maximum]
        self._module_widget.defaultDepthIntervalM()
        assert depthIntervalSpinBox.value == 1.0, (
            "The PSD volume of the scene was changed, or something changed in PSDPerDepth's onInputNodeChanged()"
        )

        self.assertTrue(applyButton.enabled)
        depthIntervalSpinBox.setValue(0.5)
        qt.QApplication.processEvents()

        # We should now have a reference to the view
        assert logic.associatedView == slicer.modules.AppContextInstance.imageLogDataLogic.imageLogViewList[-1], (
            "logic.associatedView not set. Maybe the view took too long to load?"
        )

        PSDHistograms = tryGetNode("Segmentation-label_cropped_PSD_PSDPerDepth")
        assert PSDHistograms is not None, (
            "Expected resulting node 'Segmentation-label_cropped_PSD_PSDPerDepth' not found"
        )

        wait(3.0)
        assert len(slicer.modules.AppContextInstance.imageLogDataLogic.imageLogViewList) == openViews + 1, (
            "A new view should have been created)"
        )
        openViews += 1

        groupedDepths, _ = arrayPartsFromNode(PSDHistograms)
        PSDVolumeBounds = [0, 0, 0, 0, 0, 0]
        PSDVolume.GetBounds(PSDVolumeBounds)
        assert len(groupedDepths) == 11
        # First and last depths should match the depth bounds of the volume
        assert isclose(groupedDepths[0], -PSDVolumeBounds[5] / 1000.0, abs_tol=0.04, rel_tol=0)
        assert isclose(groupedDepths[-1], -PSDVolumeBounds[4] / 1000.0, abs_tol=0.04, rel_tol=0)

    def test_presets_handling(self):
        os.makedirs(TEST_PRESETS_DIR_TEMP)
        os.makedirs(TEST_PRESETS_DIR_TEMP / "test_scene")

        self._module_widget.presetsFilePath = TEST_PRESETS_FULLPATH_TEMP
        # logic = self._module_widget.logic
        # self._module_widget.presets = logic.getPresets(TEST_PRESETS_FULLPATH_TEMP)

        depthIntervalSpinBox = self._widgets["depth_interval_spin_box"]
        nbinsSpinBox = self._widgets["nbins_spin_box"]
        logXAxisCheckBox = self._widgets["log_x_axis_check_box"]

        # Creating two presets (t1 and t2) with different parameter values.

        preset1_depthInterval = 0.5
        depthIntervalSpinBox.setValue(preset1_depthInterval)
        preset1_nbins = 10
        nbinsSpinBox.setValue(preset1_nbins)
        preset1_logXAxisCheckBox = 0
        logXAxisCheckBox.setChecked(preset1_logXAxisCheckBox)
        self._module_widget.createPreset("t1")

        preset2_depthInterval = 1.0
        depthIntervalSpinBox.setValue(preset2_depthInterval)
        preset2_nbins = 20
        nbinsSpinBox.setValue(preset2_nbins)
        preset2_logXAxisCheckBox = 1
        logXAxisCheckBox.setChecked(preset2_logXAxisCheckBox)
        self._module_widget.createPreset("t2")

        preset_names = [p.name for p in self._module_widget.presets.values()]
        self.assertIn("t1", preset_names)
        self.assertIn("t2", preset_names)

        # Asserting that their selection updates the corresponding widgets

        for i in range(len(self._module_widget.presets)):
            self._module_widget.presetWidget.presetComboBox.setCurrentIndex(i + 1)
            if self._module_widget.presetWidget.getCurrentData() is None:
                continue

        preset1_index = next((i for i, p in enumerate(self._module_widget.presets.values()) if p.name == "t1"), -1)
        self._module_widget.presetWidget.presetComboBox.setCurrentIndex(
            preset1_index + 1
        )  # +1 because 1st element is the None
        assert isclose(depthIntervalSpinBox.value, float(preset1_depthInterval))
        assert isclose(nbinsSpinBox.value, int(preset1_nbins))
        assert logXAxisCheckBox.isChecked() == bool(preset1_logXAxisCheckBox)

        preset2_index = next((i for i, p in enumerate(self._module_widget.presets.values()) if p.name == "t2"), -1)
        self._module_widget.presetWidget.presetComboBox.setCurrentIndex(preset2_index + 1)

        assert isclose(depthIntervalSpinBox.value, float(preset2_depthInterval))
        assert isclose(nbinsSpinBox.value, int(preset2_nbins))
        assert logXAxisCheckBox.isChecked() == bool(preset2_logXAxisCheckBox)

        # Deleting t1, saving the scene and closing it

        self._module_widget.presetWidget.presetComboBox.setCurrentIndex(preset1_index + 1)
        presetId = self._module_widget.presetWidget.getCurrentData()
        self._module_widget.deletePreset(presetId, TEST_PRESETS_FULLPATH_TEMP)

        if TEST_PRESETS_DIR_TEMP.exists():
            slicer.util.saveScene(str(TEST_PRESETS_DIR_TEMP / "test_scene" / "test_scene.mrml"))
        else:
            slicer.util.saveScene(str(TEST_PRESETS_DIR_TEMP / "test_scene"))

        slicer.mrmlScene.Clear(0)
        wait(0.3)

        # Loading the scene again

        slicer.util.loadScene(TEST_PRESETS_DIR_TEMP / "test_scene" / "test_scene.mrml")
        wait(0.3)
        self._module_widget.presetParameters.presetToFields()

        # - Assert that t1 got removed
        preset_names = [p.name for p in self._module_widget.presets.values()]
        self.assertNotIn("t1", preset_names)
        self.assertIn("t2", preset_names)

        # - And that t2 is sane
        preset2_index = next((i for i, p in enumerate(self._module_widget.presets.values()) if p.name == "t2"), -1)
        self._module_widget.presetWidget.presetComboBox.setCurrentIndex(preset2_index + 1)
        assert isclose(depthIntervalSpinBox.value, float(preset2_depthInterval))
        assert isclose(nbinsSpinBox.value, int(preset2_nbins))
        assert logXAxisCheckBox.isChecked() == bool(preset2_logXAxisCheckBox)

        if os.path.isfile(TEST_PRESETS_FULLPATH_TEMP):
            os.remove(TEST_PRESETS_FULLPATH_TEMP)

        if os.path.isfile(TEST_PRESETS_DIR_TEMP / "test_scene" / "test_scene.mrml"):
            os.remove(TEST_PRESETS_DIR_TEMP / "test_scene" / "test_scene.mrml")

        if os.path.isdir(TEST_PRESETS_DIR_TEMP / "test_scene"):
            os.removedirs(TEST_PRESETS_DIR_TEMP / "test_scene")

        if os.path.isdir(TEST_PRESETS_DIR_TEMP):
            os.removedirs(TEST_PRESETS_DIR_TEMP)

    def test_synth_circles(self):
        import numpy as np

        load_project(TEST_SYNTH_PROJECT_FILE)

        inputSelector = self._widgets["input_selector"]
        depthIntervalSpinBox = self._widgets["depth_interval_spin_box"]
        nbinsSpinBox = self._widgets["nbins_spin_box"]
        logXAxisCheckBox = self._widgets["log_x_axis_check_box"]
        internalBinningLogCheckBox = self._widgets["internal_binning_log_check_box"]
        applyButton = self._widgets["apply_button"]

        # Load the volume
        volume_node = tryGetNode("Segmentation_1_PSD")
        assert volume_node is not None, "Segmentation_1_PSD node not found"
        inputSelector.setCurrentNode(volume_node)

        # Verify the volume has data
        assert volume_node.GetImageData() is not None, "Volume has no image data"
        dimensions = volume_node.GetImageData().GetDimensions()
        assert dimensions == (600, 1, 600), f"Invalid volume dimensions: {dimensions}. Expected (600, 1, 600)."

        depthIntervalSpinBox.setDecimals(3)
        depthIntervalSpinBox.setValue(0.591)
        nbinsSpinBox.setValue(20)
        logXAxisCheckBox.setChecked(True)
        internalBinningLogCheckBox.setChecked(True)  # if not in log, the 6mm peak is lost

        applyButton.clicked()

        table_node = tryGetNode("Segmentation_1_PSD_PSDPerDepth")

        assert table_node is not None, "Segmentation_1_PSD_PSDPerDepth node not found"

        df = tableNodeToDataFrame(table_node)
        np.array(df.columns.tolist()[1:]).astype(float)

        depths, values = arrayPartsFromNode(table_node)

        peaks, _ = find_peaks(values[0], height=0.01)  # , distance=10)

        """
        The proportions of the areas occupied by the circles (== pdf) are:
        Radius 200mm (1 circle)  -> Pi*200^2   = Pi*40000
        Radius 100mm (2 circles) -> 2*Pi*100^2 = Pi*20000 
        Radius 50mm (5 circles)  -> 5*Pi*50^2  = Pi*12500
        Radius 25mm (22 circles) -> 22*Pi*25^2 = Pi*13750
        Radius 6mm (32 circles)  -> 32*Pi*6^2  = Pi*1152
        Proportions relative to 200mm pore area are then:
        200mm -> 1
        100mm -> 0.5
        50mm  -> 0.3125
        25mm  -> 0.34375
        6mm   -> 0.0288
        """
        peaks_proportions = [values[0][peaks[p]] / values[0][peaks[4]] for p in range(len(peaks))]

        assert len(peaks) == 5, f"We should have 5 peaks, but found {len(peaks)}"
        assert isclose(peaks_proportions[0], 0.0288, rel_tol=0.05), (
            f"Peak 1 proportion should be close to 0.0288, but got {peaks_proportions[0]}"
        )
        assert isclose(peaks_proportions[1], 0.34375, rel_tol=0.05), (
            f"Peak 2 proportion should be close to 0.34375, but got {peaks_proportions[1]}"
        )
        assert isclose(peaks_proportions[2], 0.3125, rel_tol=0.05), (
            f"Peak 3 proportion should be close to 0.3125, but got {peaks_proportions[2]}"
        )
        assert isclose(peaks_proportions[3], 0.5, rel_tol=0.05), (
            f"Peak 4 proportion should be close to 0.5, but got {peaks_proportions[3]}"
        )
