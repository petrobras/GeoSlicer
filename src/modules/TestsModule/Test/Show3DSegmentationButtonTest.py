import slicer

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events, load_project, wait, waitCondition
from commons.slicer.widget.show_3d_segmentation_button import Show3DSegmentationButton, Show3DSegmentationModel
from commons.slicer import helpers
from pathlib import Path
from functools import wraps

VOLUME_PROJECT_PATH = Path(__file__).parent / "Resources" / "Volume" / "Volume.mrml"


def volumeProject(f):
    @wraps(f)
    def wrapper(self):
        load_project(VOLUME_PROJECT_PATH)
        volumeNode = slicer.util.getNode("Volume")
        segmentationNode = slicer.util.getNode("Segmentation")
        labelMapVolumeNode = slicer.util.getNode("Segmentation-label")
        return f(self, volumeNode, segmentationNode, labelMapVolumeNode)

    return wrapper


class Show3DSegmentationButtonTest(LTracePluginTest):
    @volumeProject
    def test_model_set_node(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        model = Show3DSegmentationModel(self._module_widget.parent)
        model.segmentationNode = segmentationNode
        process_events()
        self.assertIsNone(helpers.tryGetNode(model._clonedLabelMapVolumeNodeId))

    @volumeProject
    def test_model_set_node_to_none(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        model = Show3DSegmentationModel(parent=self._module_widget.parent)
        model.segmentationNode = segmentationNode
        process_events()

        clonedNodeId = model._clonedLabelMapVolumeNodeId
        self.assertIsNone(helpers.tryGetNode(clonedNodeId))

        model.segmentationNode = None
        process_events()

        self.assertIsNone(model.labelMapVolume)
        self.assertIsNone(helpers.tryGetNode(clonedNodeId))
        self.assertIsNone(model._nodeId)
        self.assertIsNone(model._nodeObserver)

    @volumeProject
    def test_model_toggle_visibility(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        model = Show3DSegmentationModel(parent=self._module_widget.parent)
        model.segmentationNode = segmentationNode
        process_events()

        self.assertFalse(model.show)
        self.assertIsNone(model.labelMapVolume)

        model.toggleVisibility()
        process_events()
        labelMap = model.labelMapVolume
        self.assertTrue(model.show)
        self.assertTrue(helpers.getVolumeVisibilityIn3D(labelMap))

        model.toggleVisibility()
        process_events()
        self.assertFalse(model.show)
        self.assertFalse(helpers.getVolumeVisibilityIn3D(labelMap))

    @volumeProject
    def test_model_node_modification(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        model = Show3DSegmentationModel(parent=self._module_widget.parent)
        model.segmentationNode = segmentationNode
        process_events()

        self.assertIsNone(model.labelMapVolume)

        model.toggleVisibility()
        process_events()

        labelMapNode = model.labelMapVolume
        self.assertIsNotNone(labelMapNode)

        colorTableBefore = helpers.getColorTableForLabels(labelMapNode=labelMapNode)
        labels = [v.get("name") for v in colorTableBefore.values() if v.get("name")]
        self.assertTrue("Segment_1" in labels)

        # Modify the segmentation
        segmentationNode.GetSegmentation().RemoveSegment("Segment_1")
        wait(1)

        # Check if the label map was updated
        colorTableAfter = helpers.getColorTableForLabels(labelMapNode=labelMapNode)
        labels = [v.get("name") for v in colorTableAfter.values() if v.get("name")]
        self.assertFalse("Segment_1" in labels)

    @volumeProject
    def test_model_segment_visibility_modification(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        segmentationNode.GetDisplayNode().SetOpacity(1.0)
        segmentationNode.GetDisplayNode().SetSegmentVisibility("Segment_1", True)

        model = Show3DSegmentationModel(parent=self._module_widget.parent)
        model.segmentationNode = segmentationNode
        process_events()

        self.assertIsNone(model.labelMapVolume)

        model.toggleVisibility()
        process_events()

        labelMapNode = model.labelMapVolume
        self.assertIsNotNone(labelMapNode)

        colorTableBefore = helpers.getColorTableForLabels(labelMapNode=labelMapNode)
        opacities = {v["name"]: v["color"][3] for v in colorTableBefore.values() if v.get("name")}
        self.assertAlmostEqual(opacities.get("Segment_1"), 1.0, delta=0.01)

        # Modify segment visibility in display node
        displayNode = segmentationNode.GetDisplayNode()
        displayNode.SetSegmentVisibility("Segment_1", False)
        wait(1)

        # Segment_1 remains in the label map but becomes fully transparent
        colorTableAfter = helpers.getColorTableForLabels(labelMapNode=labelMapNode)
        opacities = {v["name"]: v["color"][3] for v in colorTableAfter.values() if v.get("name")}
        self.assertEqual(opacities.get("Segment_1"), 0.0)

    @volumeProject
    def test_model_overall_opacity_modification(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        segmentationNode.GetDisplayNode().SetOpacity(1.0)
        segmentationNode.GetDisplayNode().SetSegmentVisibility("Segment_1", True)
        segmentationNode.GetDisplayNode().SetSegmentVisibility("Segment_2", True)

        model = Show3DSegmentationModel(parent=self._module_widget.parent)
        model.segmentationNode = segmentationNode
        process_events()

        model.toggleVisibility()
        process_events()

        labelMapNode = model.labelMapVolume
        self.assertIsNotNone(labelMapNode)

        colorTableBefore = helpers.getColorTableForLabels(labelMapNode=labelMapNode)
        opacities = {v["name"]: v["color"][3] for v in colorTableBefore.values() if v.get("name")}
        self.assertAlmostEqual(opacities.get("Segment_1"), 1.0, delta=0.01)

        # Change the overall opacity through the segmentation's display node, as it happens
        # when the opacity slider in the CustomizedData module is changed.
        displayNode = segmentationNode.GetDisplayNode()
        displayNode.SetOpacity(0.3)
        wait(1)

        colorTableAfter = helpers.getColorTableForLabels(labelMapNode=labelMapNode)
        opacities = {v["name"]: v["color"][3] for v in colorTableAfter.values() if v.get("name")}
        self.assertAlmostEqual(opacities.get("Segment_1"), 0.3, delta=0.01)
        self.assertAlmostEqual(opacities.get("Segment_2"), 0.3, delta=0.01)

    @volumeProject
    def test_model_overall_opacity_modification_respects_segment_visibility(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        segmentationNode.GetDisplayNode().SetSegmentVisibility("Segment_2", True)

        model = Show3DSegmentationModel(parent=self._module_widget.parent)
        model.segmentationNode = segmentationNode
        process_events()

        model.toggleVisibility()
        process_events()

        labelMapNode = model.labelMapVolume
        self.assertIsNotNone(labelMapNode)

        displayNode = segmentationNode.GetDisplayNode()
        displayNode.SetSegmentVisibility("Segment_1", False)
        wait(1)

        displayNode.SetOpacity(0.4)
        wait(1)

        colorTableAfter = helpers.getColorTableForLabels(labelMapNode=labelMapNode)
        opacities = {v["name"]: v["color"][3] for v in colorTableAfter.values() if v.get("name")}

        # A hidden segment must remain fully transparent regardless of the overall opacity value
        self.assertAlmostEqual(opacities.get("Segment_1"), 0.0)
        # A visible segment must follow the overall opacity value
        self.assertAlmostEqual(opacities.get("Segment_2"), 0.4, delta=0.01)

    @volumeProject
    def test_model_overall_opacity_not_synced_while_3d_show_disabled(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        model = Show3DSegmentationModel(parent=self._module_widget.parent)
        model.segmentationNode = segmentationNode
        process_events()

        self.assertFalse(model.show)

        # Changing the overall opacity while 3D Show is disabled must not raise
        # and there is no label map yet to sync opacities into.
        displayNode = segmentationNode.GetDisplayNode()
        displayNode.SetOpacity(0.3)
        wait(1)

        self.assertIsNone(model.labelMapVolume)
        self.assertFalse(model.show)

    @volumeProject
    def test_model_cleanup_on_node_removal(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        model = Show3DSegmentationModel(parent=self._module_widget.parent)
        model.segmentationNode = segmentationNode
        process_events()

        model.toggleVisibility()
        process_events()

        clonedNodeId = model._clonedLabelMapVolumeNodeId
        self.assertIsNotNone(helpers.tryGetNode(clonedNodeId))

        slicer.mrmlScene.RemoveNode(segmentationNode)
        process_events()

        self.assertIsNone(helpers.tryGetNode(clonedNodeId))
        self.assertFalse(model.show)
        self.assertIsNone(model._nodeId)

    @volumeProject
    def test_widget_creation_and_node_setting(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        widget = Show3DSegmentationButton()
        self.assertEqual(widget.text, "Show 3D")

        widget.setSegmentationNode(segmentationNode)
        self.assertIs(widget.segmentationNode(), segmentationNode)
        self.assertIs(widget._model.segmentationNode, segmentationNode)

    @volumeProject
    def test_widget_click_and_text_change(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        widget = Show3DSegmentationButton()
        widget.setSegmentationNode(segmentationNode)
        process_events()

        self.assertEqual(widget.text, "Show 3D")
        self.assertFalse(widget._model.show)

        # First click: Show 3D
        widget.click()
        process_events()
        self.assertEqual(widget.text, "Hide 3D")
        self.assertTrue(widget._model.show)
        self.assertTrue(helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))

        # Second click: Hide 3D
        widget.click()
        process_events()
        self.assertEqual(widget.text, "Show 3D")
        self.assertFalse(widget._model.show)
        self.assertFalse(helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))

    @volumeProject
    def test_model_without_reference_volume(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        segmentation_no_ref = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "SegmentationNoRef")
        model = Show3DSegmentationModel(parent=self._module_widget.parent)

        with self.assertLogs("root", level="WARNING") as cm:
            model.segmentationNode = segmentation_no_ref
            model.toggleVisibility()
            wait(0.5)
            self.assertTrue(
                any(
                    "Unable to render a Segmentation without a defined Reference Node." in message
                    for message in cm.output
                )
            )

        self.assertIsNone(model.labelMapVolume)
        self.assertIsNone(model._clonedLabelMapVolumeNodeId)

        # Make sure it doesn't crash when toggling
        model.toggleVisibility()
        process_events()
        self.assertFalse(model.show)

    @volumeProject
    def test_display_node_visibility_updates_model(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        model = Show3DSegmentationModel(parent=self._module_widget.parent)
        model.segmentationNode = segmentationNode
        process_events()
        segmentationDisplayNode = model.segmentationNode.GetDisplayNode()
        segmentationDisplayNode.SetVisibility(True)
        process_events()
        self.assertTrue(bool(segmentationDisplayNode.GetVisibility()))

        # Initially show the 3D volume
        model.show = True
        waitCondition(lambda: helpers.getVolumeVisibilityIn3D(model.labelMapVolume))
        self.assertTrue(helpers.getVolumeVisibilityIn3D(model.labelMapVolume))
        self.assertTrue(model.show)
        self.assertTrue(bool(segmentationDisplayNode.GetVisibility()))

        # Hide the main segmentation display node
        segmentationDisplayNode.SetVisibility(False)
        waitCondition(lambda: not helpers.getVolumeVisibilityIn3D(model.labelMapVolume))

        # The cloned label map should also be hidden now even though the button is set to show
        self.assertFalse(model.show)
        self.assertFalse(helpers.getVolumeVisibilityIn3D(model.labelMapVolume))

    @volumeProject
    def test_toggle_button_and_segmentation_visibility(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        widget = Show3DSegmentationButton()
        widget.setSegmentationNode(segmentationNode)

        segmentationDisplayNode = segmentationNode.GetDisplayNode()
        segmentationDisplayNode.SetVisibility(False)
        self.assertEqual(widget.text, "Show 3D")
        self.assertFalse(bool(segmentationDisplayNode.GetVisibility()))
        self.assertFalse(widget._model.show)
        self.assertFalse(helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))

        # Initially show the 3D volume
        widget._onClicked()
        waitCondition(lambda: helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))
        self.assertTrue(helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))
        self.assertTrue(bool(segmentationDisplayNode.GetVisibility()))
        self.assertTrue(widget._model.show)
        self.assertEqual(widget.text, "Hide 3D")

        # Hide the main segmentation display node
        segmentationDisplayNode.SetVisibility(False)
        waitCondition(lambda: not helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))
        self.assertFalse(widget._model.show)
        self.assertFalse(helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))
        self.assertEqual(widget.text, "Show 3D")

        # Toggles to show 3D again
        widget._onClicked()
        waitCondition(lambda: helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))
        self.assertTrue(helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))
        self.assertTrue(bool(segmentationDisplayNode.GetVisibility()))
        self.assertTrue(widget._model.show)
        self.assertEqual(widget.text, "Hide 3D")

        # Toggles to hide 3D
        widget._onClicked()
        waitCondition(lambda: not helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))
        self.assertFalse(helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))
        self.assertTrue(bool(segmentationDisplayNode.GetVisibility()))  # Segmentation still visible
        self.assertFalse(widget._model.show)
        self.assertEqual(widget.text, "Show 3D")

    @volumeProject
    def test_toggle_between_multiple_nodes(
        self,
        volumeNode: slicer.vtkMRMLVolumeNode,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        labelMapVolumeNode: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        def cloneNode(node) -> slicer.vtkMRMLNode:
            subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            itemIDToClone = subjectHierarchyNode.GetItemByDataNode(node)
            clonedItemID = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(
                subjectHierarchyNode, itemIDToClone
            )
            clonedNode = subjectHierarchyNode.GetItemDataNode(clonedItemID)
            process_events()

            return clonedNode

        clonedSegmentationNode = cloneNode(segmentationNode)
        helpers.setSourceVolume(clonedSegmentationNode, volumeNode)  # Forcing reference volume definition
        assert clonedSegmentationNode is not None

        widget = Show3DSegmentationButton()
        self.assertEqual(widget.text, "Show 3D")
        self.assertFalse(widget._model.show)
        self.assertFalse(helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))

        widget.setSegmentationNode(segmentationNode)
        widget._onClicked()

        waitCondition(lambda: helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))
        self.assertTrue(widget._model.segmentationNode is segmentationNode)
        self.assertTrue(helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))
        self.assertTrue(widget._model.show)
        self.assertEqual(widget.text, "Hide 3D")

        # Change segmentation selection to cloned node
        widget.setSegmentationNode(clonedSegmentationNode)
        waitCondition(lambda: widget.text == "Show 3D")

        self.assertEqual(widget.text, "Show 3D")
        self.assertTrue(widget._model.segmentationNode is clonedSegmentationNode)
        self.assertFalse(widget._model.show)
        self.assertFalse(helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))

        widget._onClicked()
        waitCondition(lambda: widget.text == "Hide 3D")
        self.assertTrue(
            widget._model.segmentationNode is clonedSegmentationNode,
            f"Expected: {clonedSegmentationNode.GetID()}, got: {widget._model.segmentationNode.GetID() if widget._model.segmentationNode else 'None'}",
        )
        self.assertTrue(helpers.getVolumeVisibilityIn3D(widget._model.labelMapVolume))
        self.assertTrue(widget._model.show)
        self.assertEqual(widget.text, "Hide 3D")
