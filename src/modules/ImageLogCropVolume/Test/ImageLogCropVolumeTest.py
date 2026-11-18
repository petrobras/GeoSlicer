from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, process_events
from commons.slicer.helpers import tryGetNode
from commons.slicer.metadata import Metadata, get_node_metadata
from commons.constants import DLISImportConst
from pathlib import Path
import numpy as np

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
CROP_PROJECT_FILE = TEST_RESOURCES_DIR / "IMAGELOG_CROP_VOLUME" / "IMAGELOG_CROP_VOLUME.mrml"


class ImageLogCropVolumeTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = {
            "input": self.find_widget("Input combobox"),
            "resolution_label": self.find_widget("Input resolution label"),
            "index_range": self.find_widget("Index range"),
            "depth_range": self.find_widget("Depth range"),
            "output_prefix": self.find_widget("Output Prefix Line Edit"),
            "apply_button": self.find_widget("Apply Button"),
        }
        self.mmToDepthM = 1000

    def tear_down(self):
        pass

    def test_default_interface_configuration(self):
        assert self._widgets["input"].currentNode() is None
        assert self._widgets["resolution_label"].text == ""
        assert self._widgets["index_range"].minimumValue == 0
        assert self._widgets["depth_range"].minimumValue == 0
        assert self._widgets["index_range"].maximumValue == 0
        assert self._widgets["depth_range"].maximumValue == 0
        assert self._widgets["output_prefix"].text == ""
        assert self._widgets["apply_button"].enabled is False

    def test_attempt_to_crop_volume(self):
        import slicer

        input = self._widgets["input"]
        indexSlider = self._widgets["index_range"]
        output_prefix = self._widgets["output_prefix"]
        apply_button = self._widgets["apply_button"]

        load_project(project_file_path=CROP_PROJECT_FILE)

        inputNode = tryGetNode("FORGE 78B-32_UBI_AMP [dB]")

        assert inputNode is not None

        input.setCurrentNode(inputNode)
        inputMetadata = get_node_metadata(inputNode)

        origin = np.array(inputNode.GetOrigin())
        spacing = np.array(inputNode.GetSpacing())
        directions = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        inputNode.GetIJKToRASDirections(directions)
        zdirection = np.sign(np.dot(directions[2], [0, 0, 1]))

        assert output_prefix.text == f"{inputNode.GetName()}_cropped"

        indexSlider.setValues(50, 100)

        apply_button.clicked()
        process_events()

        outputNode = tryGetNode(output_prefix.text)
        assert outputNode is not None

        # Verify geometry...

        outputDimensions = outputNode.GetImageData().GetDimensions()
        outputOrigin = outputNode.GetOrigin()

        assert outputDimensions[2] == 51

        assert np.isclose(
            outputOrigin[2], origin[2] + (zdirection * spacing[2] * indexSlider.minimumValue), rtol=0.05, atol=5e-06
        )

        # Verify metadata propagation
        assert (
            Metadata(outputNode)[DLISImportConst.NULL_VALUE_TAG] == Metadata(inputNode)[DLISImportConst.NULL_VALUE_TAG]
        )
        assert Metadata(outputNode)[DLISImportConst.UNITS_TAG] == Metadata(inputNode)[DLISImportConst.UNITS_TAG]
        assert Metadata(outputNode)[DLISImportConst.WELL_NAME_TAG] == Metadata(inputNode)[DLISImportConst.WELL_NAME_TAG]
        # We can't simply assert get_node_metadata(outputNode) == get_node_metadata(inputNode) because outputNode gets an extra Frame attribute
        assert Metadata(outputNode)["Frame"] == "cropped"
        # The output starts as a clone of the input; writing its metadata must not change the input's
        assert get_node_metadata(inputNode) == inputMetadata

        # TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        input_itemID = subjectHierarchyNode.GetItemByDataNode(inputNode)  # the hierarchy item ID corresponding to node
        output_itemID = subjectHierarchyNode.GetItemByDataNode(outputNode)
        assert subjectHierarchyNode.GetItemAttributeNames(input_itemID) == subjectHierarchyNode.GetItemAttributeNames(
            output_itemID
        )
        # ImageLogCrop add a FRAME_TAG attribute to the output
        input_frame = subjectHierarchyNode.GetItemAttribute(input_itemID, DLISImportConst.FRAME_TAG)
        output_frame = subjectHierarchyNode.GetItemAttribute(output_itemID, DLISImportConst.FRAME_TAG)
        if input_frame:
            assert output_frame == input_frame + "_cropped"
        else:
            assert output_frame == "cropped"
