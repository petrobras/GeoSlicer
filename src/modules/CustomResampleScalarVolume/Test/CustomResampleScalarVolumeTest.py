from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, wait_cli_to_finish, process_events
from commons.slicer.helpers import tryGetNode
from commons.slicer import metadata
from pathlib import Path
import numpy as np
import slicer
import vtk
from typing import Union, Sequence
from numbers import Real

RESOURCE_DIR = Path(__file__).parent / "Resources"
PROJECT_FILE_PATH = RESOURCE_DIR / "VOLUMES" / "VOLUMES.mrml"


class CustomResampleScalarVolumeTest(LTracePluginTest):
    def _compare_direction_matrices(
        self,
        inputVolume: slicer.vtkMRMLScalarVolumeNode,
        outputVolume: slicer.vtkMRMLScalarVolumeNode,
        templateVolume: slicer.vtkMRMLScalarVolumeNode,
    ) -> None:
        inputVolumeMatrix = vtk.vtkMatrix4x4()
        outputVolumeMatrix = vtk.vtkMatrix4x4()
        templateVolumeMatrix = vtk.vtkMatrix4x4()

        inputVolume.GetIJKToRASDirectionMatrix(inputVolumeMatrix)
        outputVolume.GetIJKToRASDirectionMatrix(outputVolumeMatrix)
        templateVolume.GetIJKToRASDirectionMatrix(templateVolumeMatrix)

        for i in range(3):
            for j in range(3):
                assert (
                    inputVolumeMatrix.GetElement(i, j)
                    == outputVolumeMatrix.GetElement(i, j)
                    == templateVolumeMatrix.GetElement(i, j)
                )

    def assert_metadata_propagated(self, inputNode, outputNode):
        assert metadata.get_node_metadata(outputNode) == metadata.get_node_metadata(inputNode)

        # TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        input_itemID = subjectHierarchyNode.GetItemByDataNode(inputNode)  # the hierarchy item ID corresponding to node
        output_itemID = subjectHierarchyNode.GetItemByDataNode(outputNode)
        assert subjectHierarchyNode.GetItemAttributeNames(input_itemID) == subjectHierarchyNode.GetItemAttributeNames(
            output_itemID
        )

    def _get_input_and_output_nodes(
        self, inputNodeName: str, interpolationMethod: str, outputSpacing: Union[Real, Sequence[Real]]
    ) -> None:
        outputSuffix = "Resampled"

        load_project(PROJECT_FILE_PATH)
        inputVolumeNode = tryGetNode(inputNodeName)

        # Making sure the propagation of the metadata will be tested
        metadata.Metadata(inputVolumeNode)["DummyMetadataTest"] = "test_value"

        self.widgets["inputSelector"].setCurrentNode(inputVolumeNode)
        self.widgets["interpolationTypeComboBox"].setCurrentText(interpolationMethod)
        self.widgets["outputSuffixLineEdit"].setText(outputSuffix)

        if not isinstance(outputSpacing, Sequence):
            self.widgets["lockAspectRatioCheckBox"].setChecked(True)
            self.widgets["xValueSpinBox"].setValue(outputSpacing)
        else:
            self.widgets["lockAspectRatioCheckBox"].setChecked(False)
            self.widgets["xValueSpinBox"].setValue(outputSpacing[0])
            self.widgets["yValueSpinBox"].setValue(outputSpacing[1])
            self.widgets["zValueSpinBox"].setValue(outputSpacing[2])

        self.widgets["resampleButton"].clicked()

        cliNode = self._module_widget.logic.cliNode
        wait_cli_to_finish(cli_entity=cliNode)

        outputVolumeNode = tryGetNode(f"{inputNodeName}_{outputSuffix}")

        self.assert_metadata_propagated(inputVolumeNode, outputVolumeNode)

        return inputVolumeNode, outputVolumeNode

    def _test_resampling(
        self,
        inputNodeName: str,
        templateNodeName: str,
        interpolationMethod: str,
        outputSpacing: Union[Real, Sequence[Real]],
    ) -> None:
        inputVolumeNode, outputVolumeNode = self._get_input_and_output_nodes(
            inputNodeName, interpolationMethod, outputSpacing
        )
        templateOutputVolumeNode = tryGetNode(templateNodeName)

        outputArray = slicer.util.arrayFromVolume(outputVolumeNode)
        templateArray = slicer.util.arrayFromVolume(templateOutputVolumeNode)

        np.testing.assert_array_equal(outputArray, templateArray)
        np.testing.assert_array_equal(  # float32 to avoid precision issues with the direct comparison
            np.float32(outputVolumeNode.GetSpacing()), np.float32(templateOutputVolumeNode.GetSpacing())
        )
        np.testing.assert_array_equal(  # float32 to avoid precision issues with the direct comparison
            np.float32(outputVolumeNode.GetOrigin()),
            np.float32(templateOutputVolumeNode.GetOrigin()),
            np.float32(inputVolumeNode.GetOrigin()),
        )
        self._compare_direction_matrices(inputVolumeNode, outputVolumeNode, templateOutputVolumeNode)

    def _test_downsampling(self, interpolationMethod: str) -> None:
        self._test_resampling(
            inputNodeName="Scalar Volume",
            templateNodeName=f"Scalar Volume - downscaled by {interpolationMethod}",
            interpolationMethod=interpolationMethod,
            outputSpacing=10,
        )

    def _test_upsampling(self, interpolationMethod: str) -> None:
        self._test_resampling(
            inputNodeName="Scalar Volume",
            templateNodeName=f"Scalar Volume - upscaled by {interpolationMethod}",
            interpolationMethod=interpolationMethod,
            outputSpacing=0.5,
        )

    def _test_resampling_same_resolution(self, interpolationMethod: str) -> None:
        self._test_resampling(
            inputNodeName="Scalar Volume",
            templateNodeName=f"Scalar Volume - same resolution by {interpolationMethod}",
            interpolationMethod=interpolationMethod,
            outputSpacing=1,
        )

    def _test_downsampling_different_aspect_ratio(self, interpolationMethod: str) -> None:
        self._test_resampling(
            inputNodeName="Scalar Volume",
            templateNodeName=f"Scalar Volume - down-distorted by {interpolationMethod}",
            interpolationMethod=interpolationMethod,
            outputSpacing=(10, 5, 10),
        )

    def _test_upsampling_different_aspect_ratio(self, interpolationMethod: str) -> None:
        self._test_resampling(
            inputNodeName="Scalar Volume",
            templateNodeName=f"Scalar Volume - up-distorted by {interpolationMethod}",
            interpolationMethod=interpolationMethod,
            outputSpacing=(0.5, 0.25, 0.5),
        )

    def _test_mixed_resampling_different_aspect_ratio(self, interpolationMethod: str) -> None:
        self._test_resampling(
            inputNodeName="Scalar Volume",
            templateNodeName=f"Scalar Volume - mix-distorted by {interpolationMethod}",
            interpolationMethod=interpolationMethod,
            outputSpacing=(2, 0.5, 1),
        )

    def _test_spacing_higher_than_dimension(self, interpolationMethod: str) -> None:
        _, outputVolumeNode = self._get_input_and_output_nodes(
            inputNodeName="Scalar Volume Mini",
            interpolationMethod=interpolationMethod,
            outputSpacing=10,  # maximum possible, that's why Scalar Volume Mini is available
        )

        assert all([dimension == 1.0 for dimension in outputVolumeNode.GetImageData().GetDimensions()])

    def test_lanczos_downsampling(self) -> None:
        self._test_downsampling("Lanczos")

    def test_lanczos_upsampling(self) -> None:
        self._test_upsampling("Lanczos")

    def test_lanczos_resampling_same_resolution(self) -> None:
        self._test_resampling_same_resolution("Lanczos")

    def test_lanczos_downsampling_different_aspect_ratio(self) -> None:
        self._test_downsampling_different_aspect_ratio("Lanczos")

    def test_lanczos_upsampling_different_aspect_ratio(self) -> None:
        self._test_upsampling_different_aspect_ratio("Lanczos")

    def test_lanczos_mixed_resampling_different_aspect_ratio(self) -> None:
        self._test_mixed_resampling_different_aspect_ratio("Lanczos")

    def test_lanczos_spacing_higher_than_dimension(self) -> None:
        self._test_spacing_higher_than_dimension("Lanczos")

    def test_mean_downsampling(self) -> None:
        self._test_downsampling("Mean")

    def test_mean_upsampling(self) -> None:
        self._test_upsampling("Mean")

    def test_mean_resampling_same_resolution(self) -> None:
        self._test_resampling_same_resolution("Mean")

    def test_mean_downsampling_different_aspect_ratio(self) -> None:
        self._test_downsampling_different_aspect_ratio("Mean")

    def test_mean_upsampling_different_aspect_ratio(self) -> None:
        self._test_upsampling_different_aspect_ratio("Mean")

    def test_mean_mixed_resampling_different_aspect_ratio(self) -> None:
        self._test_mixed_resampling_different_aspect_ratio("Mean")

    def test_mean_spacing_higher_than_dimension(self) -> None:
        self._test_spacing_higher_than_dimension("Mean")

    def test_observers_handling(self) -> None:
        """Test observer references life-time handling"""
        observers = self._module_widget._observerHandlers
        assert len(observers) == 0, f"Expected a total of '0' observers. Actual: {len(observers)}."
        assert self.widgets["inputSelector"].currentNode() is None, (
            f"Expected no node selected. Actual: {self.widgets['inputSelector'].currentNode().GetName()}"
        )

        load_project(PROJECT_FILE_PATH)
        volumeNode1 = tryGetNode("Scalar Volume")
        volumeNode2 = tryGetNode("Scalar Volume Mini")

        assert volumeNode1 is not None
        assert volumeNode2 is not None

        self.widgets["inputSelector"].setCurrentNode(volumeNode1)
        process_events()

        assert len(observers) == 1, f"Expected a total of '1' observers. Actual: {len(observers)}."
        assert observers[0][0] == volumeNode1.GetID(), (
            f"Expected observer node ID reference to be '{volumeNode1.GetID()}'. Actual: {observers[0][0]}"
        )

        self.widgets["inputSelector"].setCurrentNode(volumeNode2)
        process_events()

        assert len(observers) == 1, f"Expected a total of '1' observers. Actual: {len(observers)}."
        assert observers[0][0] == volumeNode2.GetID(), (
            f"Expected observer node ID reference to be '{volumeNode2.GetID()}'. Actual: {observers[0][0]}"
        )

        self.widgets["inputSelector"].setCurrentNode(None)
        process_events()

        assert len(observers) == 0, f"Expected a total of '0' observers. Actual: {len(observers)}."
