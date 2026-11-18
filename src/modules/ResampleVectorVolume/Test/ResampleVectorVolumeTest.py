from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, wait_cli_to_finish
from commons.slicer.helpers import tryGetNode
from pathlib import Path
import numpy as np
import slicer
import vtk

RESOURCE_DIR = Path(__file__).parent / "Resources"
PROJECT_FILE_PATH = RESOURCE_DIR / "VOLUMES" / "VOLUMES.mrml"


class ResampleVectorVolumeTest(LTracePluginTest):
    def post_setup(self) -> None:
        self._widgets = {}

        self._widgets["inputVolume"] = self.find_widget(name="inputVolume")
        self._widgets["interpolationComboBox"] = self.find_widget(name="interpolationComboBox")
        self._widgets["spacingLineEdit"] = self.find_widget(name="spacingLineEdit")
        self._widgets["resampleButton"] = self.find_widget(name="resampleButton")

        for objectName, widget in self._widgets.items():
            assert widget is not None, f"widget related to the objectName '{objectName}' is None!"

    def _compare_direction_matrices(
        self,
        inputVolume: slicer.vtkMRMLVectorVolumeNode,
        outputVolume: slicer.vtkMRMLVectorVolumeNode,
        templateVolume: slicer.vtkMRMLVectorVolumeNode,
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

    def _get_input_and_output_nodes(self, inputNodeName: str, interpolationMethod: str, outputSpacing: str) -> None:
        load_project(PROJECT_FILE_PATH)
        inputVolumeNode = tryGetNode(inputNodeName)

        self._widgets["inputVolume"].setCurrentNode(inputVolumeNode)
        self._widgets["interpolationComboBox"].setCurrentText(interpolationMethod)
        self._widgets["spacingLineEdit"].setText(outputSpacing)
        self._widgets["resampleButton"].clicked()

        cliNode = self._module_widget.logic.cliNode
        wait_cli_to_finish(cli_entity=cliNode)

        outputVolumeNode = tryGetNode(f"{inputNodeName}_Resampled")
        return inputVolumeNode, outputVolumeNode

    def _test_resampling(
        self, inputNodeName: str, templateNodeName: str, interpolationMethod: str, outputSpacing: str
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
            inputNodeName="Vector Volume",
            templateNodeName=f"Vector Volume - downscaled by {interpolationMethod}",
            interpolationMethod=interpolationMethod,
            outputSpacing="10,10,1",
        )

    def _test_upsampling(self, interpolationMethod: str) -> None:
        self._test_resampling(
            inputNodeName="Vector Volume",
            templateNodeName=f"Vector Volume - upscaled by {interpolationMethod}",
            interpolationMethod=interpolationMethod,
            outputSpacing="0.5,0.5,1",
        )

    def _test_resampling_same_resolution(self, interpolationMethod: str) -> None:
        self._test_resampling(
            inputNodeName="Vector Volume",
            templateNodeName=f"Vector Volume - same resolution by {interpolationMethod}",
            interpolationMethod=interpolationMethod,
            outputSpacing="1,1,1",
        )

    def _test_resampling_all_0_spacing(self, interpolationMethod: str) -> None:
        self._test_resampling(
            inputNodeName="Vector Volume",
            templateNodeName=f"Vector Volume - same resolution by {interpolationMethod}",
            interpolationMethod=interpolationMethod,
            outputSpacing="0,0,0",
        )

    def _test_downsampling_different_aspect_ratio(self, interpolationMethod: str) -> None:
        self._test_resampling(
            inputNodeName="Vector Volume",
            templateNodeName=f"Vector Volume - down-distorted by {interpolationMethod}",
            interpolationMethod=interpolationMethod,
            outputSpacing="10,5,1",
        )

    def _test_upsampling_different_aspect_ratio(self, interpolationMethod: str) -> None:
        self._test_resampling(
            inputNodeName="Vector Volume",
            templateNodeName=f"Vector Volume - up-distorted by {interpolationMethod}",
            interpolationMethod=interpolationMethod,
            outputSpacing="0.5,0.25,1",
        )

    def _test_mixed_resampling_different_aspect_ratio(self, interpolationMethod: str) -> None:
        self._test_resampling(
            inputNodeName="Vector Volume",
            templateNodeName=f"Vector Volume - mix-distorted by {interpolationMethod}",
            interpolationMethod=interpolationMethod,
            outputSpacing="2,0.5,1",
        )

    def _test_spacing_higher_than_dimension(self, interpolationMethod: str) -> None:
        _, outputVolumeNode = self._get_input_and_output_nodes(
            inputNodeName="Vector Volume",
            interpolationMethod=interpolationMethod,
            outputSpacing="3000,3000,3",
        )

        assert all([dimension == 1.0 for dimension in outputVolumeNode.GetImageData().GetDimensions()])

    def _test_error_not_all_0_spacing(self, interpolationMethod: str) -> None:
        _, outputVolumeNode = self._get_input_and_output_nodes(
            inputNodeName="Vector Volume",
            interpolationMethod=interpolationMethod,
            outputSpacing="1,0,0",
        )

        assert outputVolumeNode.GetImageData() is None

    def test_lanczos_downsampling(self) -> None:
        self._test_downsampling("Lanczos")

    def test_lanczos_upsampling(self) -> None:
        self._test_upsampling("Lanczos")

    def test_lanczos_resampling_same_resolution(self) -> None:
        self._test_resampling_same_resolution("Lanczos")

    def test_lanczos_resampling_all_0_spacing(self) -> None:
        self._test_resampling_all_0_spacing("Lanczos")

    def test_lanczos_downsampling_different_aspect_ratio(self) -> None:
        self._test_downsampling_different_aspect_ratio("Lanczos")

    def test_lanczos_upsampling_different_aspect_ratio(self) -> None:
        self._test_upsampling_different_aspect_ratio("Lanczos")

    def test_lanczos_mixed_resampling_different_aspect_ratio(self) -> None:
        self._test_mixed_resampling_different_aspect_ratio("Lanczos")

    def test_lanczos_spacing_higher_than_dimension(self) -> None:
        self._test_spacing_higher_than_dimension("Lanczos")

    def test_lanczos_error_not_all_0_spacing(self) -> None:
        self._test_error_not_all_0_spacing("Lanczos")

    def test_mean_downsampling(self) -> None:
        self._test_downsampling("Mean")

    def test_mean_upsampling(self) -> None:
        self._test_upsampling("Mean")

    def test_mean_resampling_same_resolution(self) -> None:
        self._test_resampling_same_resolution("Mean")

    def test_mean_resampling_all_0_spacing(self) -> None:
        self._test_resampling_all_0_spacing("Mean")

    def test_mean_downsampling_different_aspect_ratio(self) -> None:
        self._test_downsampling_different_aspect_ratio("Mean")

    def test_mean_upsampling_different_aspect_ratio(self) -> None:
        self._test_upsampling_different_aspect_ratio("Mean")

    def test_mean_mixed_resampling_different_aspect_ratio(self) -> None:
        self._test_mixed_resampling_different_aspect_ratio("Mean")

    def test_mean_spacing_higher_than_dimension(self) -> None:
        self._test_spacing_higher_than_dimension("Mean")

    def test_mean_error_not_all_0_spacing(self) -> None:
        self._test_error_not_all_0_spacing("Mean")
