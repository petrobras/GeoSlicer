import slicer
import xarray as xr
import numpy as np
import tempfile
from pathlib import Path
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.netcdf import import_dataset
from commons.slicer.tests.utils import process_events, wait, wait_cli_to_finish
from commons.slicer.lazy import lazy
from unittest.mock import patch
from commons.slicer.node_attributes import NodeEnvironment

RESOURCES = Path(__file__).parent / "Resources"
TOMO_SMALL_NC_FILE = RESOURCES / "tomo_small" / "tomo_small.nc"


def getSegmentsSizes(segmentationNode):
    segmentsName = ["Background", "Macroporosity", "Microporosity", "Solid", "High Attenuation"]
    output = {}
    for segmentName in segmentsName:
        try:
            array = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentName)
            output[segmentName] = list(np.bincount(array.flatten()))
        except Exception:
            output[segmentName] = [0, 0]

    return output


class StreamlinedSegmentationTest(LTracePluginTest):
    def pre_setup(self):
        self.__envPatcher = patch("commons.slicer.helpers.getCurrentEnvironment", lambda: NodeEnvironment.THIN_SECTION)
        self.__envPatcher.start()

    def tear_down(self):
        self.__envPatcher.stop()
        self._module_widget.editor.setActiveEffectByName("")
        self._module_widget.volumeSelector.setCurrentNode(None)
        self._module_widget.customVolumeComboBox.setCurrentNode(None)
        self._module_widget.segmentationNodeComboBox.setCurrentNode(None)
        self._module_widget.sourceVolumeNodeComboBox.setCurrentNode(None)
        self._module_widget.multipleThresholdEffect.deactivate()
        self._module_widget.boundaryRemovalEffect.deactivate()

    def __setMultipleThresholdSegmentsTransitions(self, transitions: list[tuple]) -> None:
        self._module_widget.multipleThresholdEffect.transitions = transitions
        self._module_widget.multipleThresholdEffect.redrawHistogram()

    def test_segmentation(self):
        path = TOMO_SMALL_NC_FILE.as_posix()
        with xr.open_dataset(path, engine="h5netcdf") as dataset:
            node = next(import_dataset(dataset))

        lazyData = lazy.LazyNodeData(url=("file://" + path), var="tomo_small")
        lazyNode = lazyData.to_node()
        node.SetAttribute("ParentLazyNode", lazyNode.GetID())
        node.SetName("tomo_sample")

        widget = self._module_widget

        widget.customVolumeComboBox.setCurrentNode(node)

        segmentationNode = slicer.mrmlScene.GetFirstNodeByName(f"{node.GetName()}_Segmentation")

        # Maintain multiple threshold without a background segment
        self.widgets["Add Background CheckBox"].setChecked(False)

        self.assertEqual(segmentationNode.GetSegmentation().GetNumberOfSegments(), 4)
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(0).GetName(), "Macroporosity")
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(1).GetName(), "Microporosity")
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(2).GetName(), "Solid")
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(3).GetName(), "High Attenuation")

        process_events()
        wait(1)  # Wait for the auto KMeans apply

        transitions = np.array([9785.00, 9948.00, 9999.00, 10049.00, 10228.00])
        self.__setMultipleThresholdSegmentsTransitions(transitions)

        self.assertFalse(widget.applyGroup.visible)
        self.assertTrue(widget.multipleThresholdEffect.applyButton.visible)

        widget.multipleThresholdEffect.applyButton.click()

        process_events()
        wait(3)

        self.assertFalse(widget.multipleThresholdEffect.applyButton.visible)
        self.assertTrue(widget.boundaryRemovalEffect.applyButton.visible)

        widget.boundaryRemovalEffect.applyButton.click()

        process_events()

        segmentsSizeAfterStreamlinedFlow = getSegmentsSizes(segmentationNode=segmentationNode)
        expected = {
            "Background": [0, 0],
            "Macroporosity": [19487, 5513],
            "Microporosity": [19954, 5046],
            "Solid": [15321, 9679],
            "High Attenuation": [20238, 4762],
        }
        self.assertEqual(segmentsSizeAfterStreamlinedFlow, expected)

        self.assertFalse(widget.multipleThresholdEffect.applyButton.visible)
        self.assertFalse(widget.boundaryRemovalEffect.applyButton.visible)

        self.assertTrue(widget.applyGroup.visible)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "test_segmentation.nc"
            widget.exportPathEdit.setCurrentPath(path.as_posix())
            widget.applyButton.click()

            process_events()
            cliNode = widget.logic._cli_node
            wait_cli_to_finish(cliNode)
            assert cliNode.GetStatusString() == "Completed", f"CLI error: {cliNode.GetErrorText()}"

            with xr.open_dataset(path, engine="h5netcdf") as dataset:
                array = dataset["tomo_small_segmented"].data
                self.assertEqual(array.shape, (10, 50, 50))
                self.assertEqual((array == 0).sum(), 0)

    def test_segmentation_with_background(self):
        path = TOMO_SMALL_NC_FILE.as_posix()
        with xr.open_dataset(path, engine="h5netcdf") as dataset:
            node = next(import_dataset(dataset))

        lazyData = lazy.LazyNodeData(url=("file://" + path), var="tomo_small")
        lazyNode = lazyData.to_node()
        node.SetAttribute("ParentLazyNode", lazyNode.GetID())
        node.SetName("tomo_sample")

        widget = self._module_widget

        widget.customVolumeComboBox.setCurrentNode(node)

        segmentationNode = slicer.mrmlScene.GetFirstNodeByName(f"{node.GetName()}_Segmentation")

        # Maintain multiple threshold without a background segment
        self.widgets["Add Background CheckBox"].setChecked(True)

        wait(1)
        transitions = np.array([9785.00, 9932.82, 9978.77, 10020.10, 10066.03, 10228.00])
        self.__setMultipleThresholdSegmentsTransitions(transitions)

        self.assertEqual(segmentationNode.GetSegmentation().GetNumberOfSegments(), 5)
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(0).GetName(), "Background")
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(1).GetName(), "Macroporosity")
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(2).GetName(), "Microporosity")
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(3).GetName(), "Solid")
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(4).GetName(), "High Attenuation")

        process_events()

        self.assertFalse(widget.applyGroup.visible)
        self.assertTrue(widget.multipleThresholdEffect.applyButton.visible)

        widget.multipleThresholdEffect.applyButton.click()

        process_events()
        wait(3)

        self.assertFalse(widget.multipleThresholdEffect.applyButton.visible)
        self.assertTrue(widget.boundaryRemovalEffect.applyButton.visible)

        widget.boundaryRemovalEffect.applyButton.click()

        process_events()

        segmentsSizeAfterStreamlinedFlow = getSegmentsSizes(segmentationNode=segmentationNode)
        expected = {
            "Background": [21898, 3102],
            "Macroporosity": [17686, 7314],
            "Microporosity": [20285, 4715],
            "Solid": [17932, 7068],
            "High Attenuation": [22199, 2801],
        }
        self.assertEqual(segmentsSizeAfterStreamlinedFlow, expected)

        self.assertEqual(segmentationNode.GetSegmentation().GetNumberOfSegments(), 5)
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(0).GetName(), "Background")
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(1).GetName(), "Macroporosity")
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(2).GetName(), "Microporosity")
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(3).GetName(), "Solid")
        self.assertEqual(segmentationNode.GetSegmentation().GetNthSegment(4).GetName(), "High Attenuation")
