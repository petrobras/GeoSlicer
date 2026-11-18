from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, process_events
from commons.slicer.helpers import tryGetNode
from commons.slicer import metadata
from pathlib import Path

# At the moment, we use the ImageLogCropVolume test image, as it fits our needs
PROJECT_FILE = (
    Path(__file__).parent
    / ".."
    / ".."
    / "ImageLogCropVolume"
    / "Test"
    / "Resources"
    / "IMAGELOG_CROP_VOLUME"
    / "IMAGELOG_CROP_VOLUME.mrml"
)


class CLAHEToolTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied before reloading the widgets"""
        self._widgets = {
            "input": self.find_widget("inputImage"),
            "kernel_x": self.find_widget("kernelSizeX"),
            "kernel_y": self.find_widget("kernelSizeY"),
            "clip_limit": self.find_widget("clipLimit"),
            "nbins_input": self.find_widget("nBinsInput"),
            "output_prefix": self.find_widget("outputPrefix"),
            "apply_button": self.find_widget("applyButton"),
            "progress_bar": self.find_widget("progressBar"),
        }
        self.default_clip_limit = 0.01
        self.default_nbins_input = 256

    def tear_down(self):
        pass

    def test_default_interface_configuration(self):
        assert self._widgets["input"].currentNode() is None
        assert self._widgets["clip_limit"].value == self.default_clip_limit
        assert self._widgets["nbins_input"].value == self.default_nbins_input
        assert self._widgets["output_prefix"].text == ""
        assert self._widgets["apply_button"].enabled is False
        assert self._widgets["progress_bar"].value == 0

    def test_process_completed(self):
        import slicer

        input = self._widgets["input"]
        kernel_x = self._widgets["kernel_x"]
        kernel_y = self._widgets["kernel_y"]
        clip_limit = self._widgets["clip_limit"]
        nbins_input = self._widgets["nbins_input"]
        output_prefix = self._widgets["output_prefix"]
        progress_bar = self._widgets["progress_bar"]
        apply_button = self._widgets["apply_button"]

        load_project(project_file_path=PROJECT_FILE)

        inputNode = tryGetNode("FORGE 78B-32_UBI_AMP [dB]")

        assert inputNode is not None

        # Making sure the propagation of the metadata will be tested
        metadata.Metadata(inputNode)["DummyMetadataTest"] = "test_value"

        input.setCurrentNode(inputNode)

        # If failing here, something changed regarding the default kernel size
        assert kernel_x.value == int(min(2048, inputNode.GetImageData().GetDimensions()[0] / 8))
        assert kernel_y.value == int(min(2048, inputNode.GetImageData().GetDimensions()[2] / 8))

        # In principle, these shouldn't have changed atfter we selected the input volume:
        assert clip_limit.value == self.default_clip_limit
        assert nbins_input.value == self.default_nbins_input

        assert output_prefix.text == f"{inputNode.GetName()}_CLAHE"

        apply_button.clicked()
        process_events()

        outputNode = tryGetNode(f"{inputNode.GetName()}_clahe")
        assert outputNode is not None
        assert outputNode.GetImageData().GetDimensions() == inputNode.GetImageData().GetDimensions()
        assert outputNode.GetOrigin() == inputNode.GetOrigin()
        assert progress_bar.value == 100

        # Verify metadata propagation

        assert metadata.get_node_metadata(outputNode) == metadata.get_node_metadata(inputNode)
        # TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        input_itemID = subjectHierarchyNode.GetItemByDataNode(inputNode)  # the hierarchy item ID corresponding to node
        output_itemID = subjectHierarchyNode.GetItemByDataNode(outputNode)
        assert subjectHierarchyNode.GetItemAttributeNames(input_itemID) == subjectHierarchyNode.GetItemAttributeNames(
            output_itemID
        )

        assert inputNode.GetNumberOfNodeReferences("referenceImageGeometryRef") == outputNode.GetNumberOfNodeReferences(
            "referenceImageGeometryRef"
        )
        assert inputNode.GetNumberOfNodeReferences("referenceVolume") == outputNode.GetNumberOfNodeReferences(
            "referenceVolume"
        )
