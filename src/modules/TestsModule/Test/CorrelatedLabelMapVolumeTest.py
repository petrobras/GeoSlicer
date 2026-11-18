import slicer

from commons.slicer import helpers
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, process_events, wait
from commons.utils.CorrelatedLabelMapVolume import ProportionLabelMapVolume
from pathlib import Path
from unittest.mock import MagicMock, patch


TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
IMAGE_LOG_DATA_RESOURCES_DIR = Path(__file__).parents[2] / "ImageLogData" / "Test" / "Resources"
SEGMENTED_VOLUME_PROJECT_FILE = IMAGE_LOG_DATA_RESOURCES_DIR / "SegmentedVolume" / "SegmentedVolume.mrml"


class CorrelatedLabelMapVolumeTest(LTracePluginTest):
    @patch("commons.utils.CorrelatedLabelMapVolume.CorrelatedLabelMapVolume._cleanUp")
    @patch("commons.utils.CorrelatedLabelMapVolume.CorrelatedLabelMapVolume._CorrelatedLabelMapVolume__onNodeModified")
    def test_proportions_label_map_behavior(self, onNodeModifiedMock: MagicMock, cleanUpMock: MagicMock):
        load_project(SEGMENTED_VOLUME_PROJECT_FILE)

        segmentationNode = helpers.tryGetNode("Segmentation")
        assert segmentationNode is not None

        proportions = ProportionLabelMapVolume(referenceNode=segmentationNode, name="Proportions")

        assert proportions.labelMapVolumeNode.GetName() == "Segmentation_Proportions", (
            f"Expected: 'Proportions', got '{proportions.labelMapVolumeNode.GetName()}'"
        )
        assert isinstance(proportions.labelMapVolumeNode, slicer.vtkMRMLLabelMapVolumeNode), (
            f"Proportion node is a {type(proportions.labelMapVolumeNode)} is not a vtkMRMLLabelMapVolumeNode"
        )
        assert onNodeModifiedMock.call_count == 0
        assert cleanUpMock.call_count == 0

        segmentationNode.Modified()  # Simulate node modified event
        segmentationNode.InvokeEvent(segmentationNode.GetSegmentation().RepresentationModified)
        segmentationNode.InvokeEvent(segmentationNode.GetSegmentation().SegmentAdded)
        segmentationNode.InvokeEvent(segmentationNode.GetSegmentation().SegmentRemoved)
        segmentationNode.InvokeEvent(segmentationNode.GetSegmentation().SegmentModified)
        process_events()
        assert onNodeModifiedMock.call_count == 5, (
            f"Expected 5 calls to onNodeModified, got {onNodeModifiedMock.call_count}"
        )

        slicer.mrmlScene.RemoveNode(segmentationNode)  # Simulate node removed event
        process_events()
        assert cleanUpMock.call_count == 1, f"Expected 1 call to cleanUp, got {cleanUpMock.call_count}"

    @patch("commons.utils.CorrelatedLabelMapVolume.ProportionLabelMapVolume._ProportionLabelMapVolume__process")
    def test_correlated_label_map_calling_callback_in_constructor(self, callbackMock: MagicMock) -> None:
        load_project(SEGMENTED_VOLUME_PROJECT_FILE)

        segmentationNode = helpers.tryGetNode("Segmentation")
        assert segmentationNode is not None

        ProportionLabelMapVolume(referenceNode=segmentationNode, name="Proportions")
        process_events()
        assert callbackMock.call_count == 1, f"Expected 1 calls to callback, got {callbackMock.call_count}"

    def test_correlated_label_map_removed_when_reference_node_is_removed(self):
        load_project(SEGMENTED_VOLUME_PROJECT_FILE)

        segmentationNode = helpers.tryGetNode("Segmentation")
        assert segmentationNode is not None

        proportions = ProportionLabelMapVolume(referenceNode=segmentationNode, name="Proportions")

        assert proportions.labelMapVolumeNode.GetName() == "Segmentation_Proportions", (
            f"Expected: 'Proportions', got '{proportions.labelMapVolumeNode.GetName()}'"
        )
        assert isinstance(proportions.labelMapVolumeNode, slicer.vtkMRMLLabelMapVolumeNode), (
            f"Proportion node is a {type(proportions.labelMapVolumeNode)} is not a vtkMRMLLabelMapVolumeNode"
        )

        slicer.mrmlScene.RemoveNode(segmentationNode)
        process_events()

        assert proportions.labelMapVolumeNode is None

    def test_proportion_label_map_exists_when_segmentation_is_empty(self):
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLSegmentationNode.__name__, "Segmentation")
        proportion = ProportionLabelMapVolume(referenceNode=segmentationNode, name="Proportions")

        assert proportion.labelMapVolumeNode is not None
        assert proportion.referenceNode is segmentationNode

    def test_proportion_label_map_exists_when_label_map_is_empty(self):
        labelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "LabelMap")
        proportion = ProportionLabelMapVolume(referenceNode=labelMapNode, name="Proportions")

        assert proportion.labelMapVolumeNode is not None
        assert proportion.referenceNode is labelMapNode

    def test_observers_handling(self) -> None:
        """Test observers life-time handling"""
        load_project(SEGMENTED_VOLUME_PROJECT_FILE)

        segmentationNode = helpers.tryGetNode("Segmentation")
        labelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "LabelMap")

        assert segmentationNode is not None

        proportionSegmentation = ProportionLabelMapVolume(referenceNode=segmentationNode, name="Proportions-seg")
        proportionLabelMap = ProportionLabelMapVolume(referenceNode=labelMapNode, name="Proportions-label")

        propSegmentationObservers = proportionSegmentation._observerHandlers
        propLabelMapObservers = proportionLabelMap._observerHandlers

        assert len(propSegmentationObservers) == 6, (
            f"Expected a total of '6' observers. Actual: {len(propSegmentationObservers)} "
        )
        assert len(propLabelMapObservers) == 2, (
            f"Expected a total of '2' observers. Actual: {len(propLabelMapObservers)} "
        )

        proportionSegmentation._cleanUp()
        proportionLabelMap._cleanUp()

        wait(0.5)

        assert len(propSegmentationObservers) == 0, (
            f"Expected a total of '0' observers. Actual: {len(propSegmentationObservers)} "
        )
        assert len(propLabelMapObservers) == 0, (
            f"Expected a total of '0' observers. Actual: {len(propLabelMapObservers)} "
        )
