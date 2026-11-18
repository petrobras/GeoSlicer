from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events
from commons.slicer.metadata import Metadata
import slicer
import numpy as np


class CustomizedCropTest(LTracePluginTest):
    def test_labelmap_crop(self):
        cropButton = self.widgets["Apply Button"]
        widget = self._module_widget
        widget.enter()

        labelmap = np.random.rand(10, 10, 10) * 5
        labelmap = labelmap.astype(np.uint16)
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "labelmap")
        slicer.util.updateVolumeFromArray(node, labelmap)

        widget.volumeComboBox.setCurrentNode(node)
        for size, box in zip((2, 4, 6), widget.sizeBoxes):
            box.setValue(size)

        process_events()

        # Attribute to test Metadata propagation
        node.SetAttribute("DummyKey", "dummy_val")
        Metadata(node)["DummyKey"] = node.GetAttribute("DummyKey")

        cropButton.click()
        result = slicer.util.getFirstNodeByName("labelmap - Cropped")
        output = slicer.util.arrayFromVolume(result)

        # Crop is centered by default
        np.testing.assert_array_equal(output, labelmap[2:8, 3:7, 4:6])

        # Verify metadata propagation
        assert Metadata(result)["DummyKey"] == Metadata(node)["DummyKey"] == "dummy_val"

    def test_enter_and_exit_crop_roi_creation_and_visibility(self):
        cropButton = self.widgets["Apply Button"]
        widget = self._module_widget
        widget.enter()
        widget.exit()
        widget.enter()

        labelmap = np.random.rand(10, 10, 10) * 5
        labelmap = labelmap.astype(np.uint16)

        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "labelmap")
        node2 = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "labelmap2")

        slicer.util.updateVolumeFromArray(node, labelmap)
        slicer.util.updateVolumeFromArray(node2, labelmap)

        widget.volumeComboBox.setCurrentNode(node2)
        widget.volumeComboBox.setCurrentNode(node)

        roi_nodes = slicer.util.getNodesByClass("vtkMRMLMarkupsROINode")
        roi_node = roi_nodes[0]

        for size, box in zip((2, 4, 6), widget.sizeBoxes):
            box.setValue(size)

        roi_node = slicer.util.getNodesByClass("vtkMRMLMarkupsROINode")
        roi_node = roi_node[0]
        radius = [0.0, 0.0, 0.0]
        roi_node.GetRadiusXYZ(radius)
        dimensions = [2 * r for r in radius]

        assert roi_node.GetDisplayVisibility() == 1
        np.testing.assert_array_equal(node.GetImageData().GetDimensions(), dimensions)

        process_events()

        # Attribute to test Metadata propagation
        node.SetAttribute("DummyKey", "dummy_val")
        Metadata(node)["DummyKey"] = node.GetAttribute("DummyKey")

        cropButton.click()
        result = slicer.util.getFirstNodeByName("labelmap - Cropped")
        output = slicer.util.arrayFromVolume(result)

        # Crop is centered by default
        np.testing.assert_array_equal(output, labelmap[2:8, 3:7, 4:6])

        # Verify metadata propagation
        assert Metadata(result)["DummyKey"] == Metadata(node)["DummyKey"] == "dummy_val"
