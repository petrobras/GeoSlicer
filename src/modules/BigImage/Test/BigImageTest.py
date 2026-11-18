import slicer
import numpy as np
from pathlib import Path
from commons.slicer.tests.utils import load_project, process_events
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest


RESOURCES = Path(__file__).parent / "Resources"
PROJECT_FILE_PATH = RESOURCES / "SEG" / "SEG.mrml"


class BigImageTest(LTracePluginTest):
    def _boundary_removal_initialize(self):
        customizedSegmentEditorWidget = slicer.util.getNewModuleWidget("CustomizedSegmentEditor")
        customizedSegmentEditorWidget.segmentationNodeComboBox.setCurrentNode(slicer.util.getNode("Segmentation"))
        customizedSegmentEditorWidget.sourceVolumeNodeComboBox.setCurrentNode(slicer.util.getNode("IMAGE_reduced"))

        boundaryRemovalEffect = customizedSegmentEditorWidget.editor.effectByName("Boundary removal")
        effectInstance = boundaryRemovalEffect.self()
        effectInstance.initializeButton.clicked()

    def _big_image_start_preview(self, widget, volume_name):
        node = slicer.mrmlScene.GetFirstNodeByName(volume_name)

        self.assertNotEqual(node, None)

        # We call startPreview() directly instead of using the interface
        # because only the original Big Image widget instance is connected
        # to the lazy node visibility change event, while integration tests
        # use a fresh instance of the widget for each test.
        widget.startPreview(node)

        process_events()

    def _big_image_stop_preview(self, widget):
        widget.stopPreviewButton.click()

    def _big_image_load_and_start_preview(self, volume_name):
        widget = self._module_widget
        widget.inputDirSelector.directory = str(RESOURCES / volume_name)

        process_events()
        widget.loadDatasetButton.click()

        process_events()
        self._big_image_start_preview(widget, volume_name)

        return widget

    def _generate_test_volume(self, volume_name):
        widget = self._big_image_load_and_start_preview(volume_name)
        widget.onLoadClicked()
        self._big_image_stop_preview(widget)
        return widget

    def _test_preview_volumes_and_opacity(self, widget, compositeNode, volume_name):
        self._big_image_start_preview(widget, volume_name)

        previewNode = widget.logic.previewNodes[0]

        backgroundIDAfterPreview = compositeNode.GetBackgroundVolumeID()
        foregroundIDAfterPreview = compositeNode.GetForegroundVolumeID()
        foregroundOpacityAfterPreview = compositeNode.GetForegroundOpacity()

        assert backgroundIDAfterPreview is None
        assert foregroundIDAfterPreview == previewNode.GetID()
        assert foregroundOpacityAfterPreview == 1

        self._big_image_stop_preview(widget)

    def test_preview_before_and_after_BR_init(self):
        load_project(PROJECT_FILE_PATH)
        volume_name = "IMAGE"

        widget = self._generate_test_volume(volume_name)

        compositeNode = slicer.app.layoutManager().sliceWidget("Red").sliceLogic().GetSliceCompositeNode()

        self._test_preview_volumes_and_opacity(widget, compositeNode, volume_name)

        self._boundary_removal_initialize()

        self._test_preview_volumes_and_opacity(widget, compositeNode, volume_name)

    def assert_almost_equal(self, array1, array2):
        array1 = np.asarray(array1)
        array2 = np.asarray(array2)
        self.assertEqual(array1.shape, array2.shape)
        diff = np.abs(array1 - array2)
        self.assertLess(diff.max(), 1e-5)

    def test_output_size(self):
        widget = self._big_image_load_and_start_preview("tomo_small")

        self.assertEqual(widget.outputSizeLabel.text, "50.0 kB")

        widget.cropSizeSpinBoxes[0].value = 25
        widget.cropSizeSpinBoxes[1].value = 24
        widget.cropSizeSpinBoxes[2].value = 7

        process_events()
        self.assertEqual(widget.outputSizeLabel.text, "8.4 kB")

        widget.cropOriginSpinBoxes[0].value = 30
        widget.cropOriginSpinBoxes[1].value = 20
        widget.cropOriginSpinBoxes[2].value = 7

        process_events()
        self.assertEqual(widget.outputSizeLabel.text, "2.9 kB")

        widget.convertedTypeComboBox.setCurrentText("float32")

        process_events()
        self.assertEqual(widget.outputSizeLabel.text, "5.8 kB")

        widget.downsampleBox.value = 2

        process_events()
        self.assertEqual(widget.outputSizeLabel.text, "720 Bytes")

    def test_spacing(self):
        widget = self._big_image_load_and_start_preview("tomo_small")

        preview_node = slicer.mrmlScene.GetFirstNodeByName("tomo_small Z Slice Preview")
        self.assert_almost_equal(preview_node.GetSpacing(), (0.3, 0.4, 0.5))
        self.assert_almost_equal(preview_node.GetOrigin(), (0, 50, -7.5))

        roi_node = slicer.mrmlScene.GetFirstNodeByName("Big Image Extent ROI")
        crop_roi_node = slicer.mrmlScene.GetFirstNodeByName("Big Image Crop ROI")

        self.assertTrue(roi_node.GetDisplayVisibility())
        self.assertTrue(crop_roi_node.GetDisplayVisibility())

        center = [0] * 3
        roi_node.GetXYZ(center)
        radius = [0] * 3
        roi_node.GetRadiusXYZ(radius)

        self.assert_almost_equal(center, (-7.5 + 0.15, 40 + 0.2, -7.5 - 0.25))
        self.assert_almost_equal(radius, (7.5, 10, 2.5))

        crop_roi_node.GetXYZ(center)
        crop_roi_node.GetRadiusXYZ(radius)

        self.assert_almost_equal(center, (-7.5 + 0.15, 40 + 0.2, -7.5 - 0.25))
        self.assert_almost_equal(radius, (7.5, 10, 2.5))

        widget.cropSizeSpinBoxes[0].value = 20
        widget.cropSizeSpinBoxes[1].value = 30
        widget.cropSizeSpinBoxes[2].value = 7

        widget.cropOriginSpinBoxes[0].value = 2
        widget.cropOriginSpinBoxes[1].value = 3
        widget.cropOriginSpinBoxes[2].value = 4
        widget.downsampleBox.value = 2

        process_events()

        crop_roi_node.GetXYZ(center)
        crop_roi_node.GetRadiusXYZ(radius)
        self.assert_almost_equal(center, (-3.6 + 0.3 / 2, 42.8 + 0.4 / 2, -6.25 - 0.5 / 2))
        self.assert_almost_equal(radius, (3.0, 6.0, 1.75))

        widget.onLoadClicked()

        reduced_node = slicer.mrmlScene.GetFirstNodeByName("tomo_small_reduced")
        self.assert_almost_equal(reduced_node.GetSpacing(), (0.6, 0.8, 1.0))
        self.assert_almost_equal(reduced_node.GetOrigin(), (-0.6, 48.8, -8))
