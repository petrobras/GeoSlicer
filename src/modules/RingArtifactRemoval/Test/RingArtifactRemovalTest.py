import numpy as np
import slicer
import vtk

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import check_for_message_box, process_events


class RingArtifactRemovalTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied after the widgets are loaded"""
        self._widgets = {
            "input_selector": self.find_widget("Input Selector"),
            "apply_button": self.find_widget("Apply Button"),
            "output_name_line_edit": self.find_widget("Output Name Line Edit"),
        }
        self._nodes = []

    def tear_down(self):
        if getattr(self, "_logic", None) is not None:
            self._logic.exitPreview()
            self._logic.removeCenters()
        for node in self._nodes:
            slicer.mrmlScene.RemoveNode(node)

    def _create_volume(self, name="ring_volume"):
        rng = np.random.default_rng(0)
        node = slicer.util.addVolumeFromArray(rng.normal(100, 5, size=(3, 64, 64)).astype(np.float32), name=name)
        self._nodes.append(node)
        process_events()
        return node

    def test_default_interface_configuration(self):
        apply_button = self._widgets["apply_button"]
        output_name_line_edit = self._widgets["output_name_line_edit"]
        assert apply_button is not None
        assert output_name_line_edit is not None
        assert output_name_line_edit.enabled
        assert output_name_line_edit.text == ""

    def test_attempt_to_click_on_apply_without_node_should_prompt_message(self):
        apply_button = self._widgets["apply_button"]
        self._widgets["input_selector"].setCurrentNode(None)
        process_events()

        with check_for_message_box("Select an input volume."):
            apply_button.clicked()

    def test_attempt_to_click_on_apply_without_output_name_should_prompt_message(self):
        inputNode = self._create_volume()
        self._widgets["input_selector"].setCurrentNode(inputNode)
        process_events()
        self._widgets["output_name_line_edit"].text = ""

        with check_for_message_box("Enter an output name."):
            self._widgets["apply_button"].clicked()

    def test_apply_creates_output_volume(self):
        inputNode = self._create_volume("ring_input")
        self._widgets["input_selector"].setCurrentNode(inputNode)
        process_events()
        assert self._widgets["output_name_line_edit"].text == "ring_input_remove_rings"

        self._widgets["apply_button"].clicked()
        process_events()

        outputNode = slicer.util.getNode("ring_input_remove_rings")
        self._nodes.append(outputNode)
        assert slicer.util.arrayFromVolume(outputNode).shape == slicer.util.arrayFromVolume(inputNode).shape

    def test_preview_stays_visible_after_jumping_to_center_point(self):
        """Clicking a center point jumps the preview views to its depth. The single-slice
        preview volumes must sit at that depth, or the panels go blank."""
        from RingArtifactRemoval import RingArtifactRemovalLogic

        inputNode = self._create_volume("ring_preview_input")
        inputNode.SetOrigin(10.0, 20.0, 30.0)
        inputNode.SetSpacing(0.5, 0.5, 2.0)
        sliceIndex = 2

        ijkToRas = vtk.vtkMatrix4x4()
        inputNode.GetIJKToRASMatrix(ijkToRas)
        pointRas = ijkToRas.MultiplyPoint((32, 32, sliceIndex, 1))[:3]

        self._logic = RingArtifactRemovalLogic()
        self._logic.preview(inputNode, [(32.0, 32.0)], medianSize=17, sliceIndex=sliceIndex)
        process_events()

        layoutManager = slicer.app.layoutManager()
        viewGroup = layoutManager.sliceWidget("RingPreviewBefore").mrmlSliceNode().GetViewGroup()
        slicer.modules.markups.logic().JumpSlicesToLocation(*pointRas, True, viewGroup)
        process_events()

        for viewName in RingArtifactRemovalLogic.PREVIEW_VIEW_NAMES:
            sliceWidget = layoutManager.sliceWidget(viewName)
            volumeId = sliceWidget.mrmlSliceCompositeNode().GetBackgroundVolumeID()
            bounds = [0.0] * 6
            slicer.mrmlScene.GetNodeByID(volumeId).GetRASBounds(bounds)
            offset = sliceWidget.mrmlSliceNode().GetSliceOffset()
            assert bounds[4] <= offset <= bounds[5], f"{viewName}: offset {offset} outside preview {bounds[4:]}"
