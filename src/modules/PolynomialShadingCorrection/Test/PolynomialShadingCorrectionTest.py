import qt
import vtk
import numpy as np
import slicer

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, wait, process_events
from commons.slicer import helpers
from commons.slicer import metadata
from typing import Tuple, Union
from pathlib import Path
from scipy.ndimage import gaussian_filter1d
from unittest.mock import patch


TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
SYNTHETIC_RADIAL_SHADING_1_PROJECT_FILE = (
    TEST_RESOURCES_DIR / "SYNTHETIC_RADIAL_SHADING_1" / "SYNTHETIC_RADIAL_SHADING_1.mrml"
)

SHADED_RADIAL_RANGE = (65, 243)
SHADED_PCR_RANGE = (0.08, 0.10)


class PolynomialShadingCorrectionTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def test_synthetic_radial_shading_correction(self):
        """
        Here we are testing if the module as a whole works, produces the output and if the output is corrected, by measuring the decrease in
        the standard deviation of the data, an indicator that the radial shading was reduced.
        """
        load_project(SYNTHETIC_RADIAL_SHADING_1_PROJECT_FILE)

        inputImage = slicer.util.getNode("shaded")
        array = slicer.util.arrayFromVolume(inputImage)
        beforeStd = np.std(array[array > 0])

        inputDataType = array.dtype
        self._configure_inputs(
            projectPath=SYNTHETIC_RADIAL_SHADING_1_PROJECT_FILE,
            inputImageNodeName="shaded",
            thresholdRange=SHADED_RADIAL_RANGE,
            outputImageName="shaded_shading_correction",
            sliceGroupSizeValue=1,
            fittingPointsPercentageValue=100,
            functionType="Polynomial Radial",
            polynomialOrder=4,
        )

        metadata.Metadata(inputImage)["DummyKey"] = "dummy_val"

        self.widgets["applyButton"].clicked()
        wait(0.2)

        outputImage = slicer.util.getNode("shaded_shading_correction")
        self.assertIsNotNone(outputImage)
        array = slicer.util.arrayFromVolume(outputImage)
        outputDataType = array.dtype
        afterStd = np.std(array[array > 0])

        self.assertLess(
            afterStd, beforeStd, "Standard deviation after correction should be less than before correction"
        )
        self.assertEqual(inputDataType, outputDataType)

        assert metadata.Metadata(outputImage)["DummyKey"] == metadata.Metadata(inputImage)["DummyKey"] == "dummy_val"

    def TODO_test_virtual_nodes_enable_apply_to_all_volume_button(self):
        load_project(SYNTHETIC_RADIAL_SHADING_1_PROJECT_FILE)
        applyAllButton = self.widgets["applyAllButton"]

        # Usual nodes
        inputImage = slicer.util.getNode("shaded")
        shadingMask = slicer.util.getNode("shading_mask")
        self.assertIsNotNone(inputImage)
        self.assertIsNotNone(shadingMask)

        # Mock text nodes as "virtual" nodes
        virtualInputImage = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTextNode.__name__)
        virtualShadingMaskImage = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTextNode.__name__)
        self.assertIsNotNone(virtualInputImage)
        self.assertIsNotNone(virtualShadingMaskImage)

        # Add parent attributes
        inputImage.SetAttribute("ParentLazyNode", virtualInputImage.GetID())
        shadingMask.SetAttribute("ParentLazyNode", virtualShadingMaskImage.GetID())

        # The button should be visible only when all the 2 selected nodes have a parent virtual node
        inputImageComboBox = self.widgets["inputImageComboBox"]
        inputImageComboBox.setCurrentNode(inputImage)
        wait(0.1)
        assert applyAllButton.visible is False

        inputShadingMaskComboBox = self.widgets["inputShadingMaskComboBox"]
        inputShadingMaskComboBox.setCurrentNode(shadingMask)
        wait(0.1)
        assert applyAllButton.visible is True

    def test_synthetic_radial_shading_correction_with_pcr(self):
        """
        Here we are testing if the module as a whole works, produces the output and if the output is corrected, by measuring the decrease in
        the standard deviation of the data, an indicator that the radial shading was reduced.
        """
        load_project(SYNTHETIC_RADIAL_SHADING_1_PROJECT_FILE)

        inputImage = slicer.util.getNode("shaded_pcr")
        array = slicer.util.arrayFromVolume(inputImage)
        inputDataType = array.dtype
        beforeStd = np.std(array[array > 0])

        self._configure_inputs(
            projectPath=SYNTHETIC_RADIAL_SHADING_1_PROJECT_FILE,
            inputImageNodeName="shaded_pcr",
            thresholdRange=SHADED_PCR_RANGE,
            outputImageName="shaded_shading_correction",
            sliceGroupSizeValue=1,
            fittingPointsPercentageValue=100,
            functionType="Polynomial Radial",
            polynomialOrder=4,
        )

        metadata.Metadata(inputImage)["DummyKey"] = "dummy_val"

        self.widgets["applyButton"].clicked()
        wait(0.2)

        outputImage = slicer.util.getNode("shaded_shading_correction")
        self.assertIsNotNone(outputImage)
        array = slicer.util.arrayFromVolume(outputImage)
        outputDataType = array.dtype
        afterStd = np.std(array[array > 0])

        self.assertLess(
            afterStd, beforeStd, "Standard deviation after correction should be less than before correction"
        )
        self.assertEqual(inputDataType, outputDataType)

        # assert metdata propagation
        assert metadata.Metadata(outputImage)["DummyKey"] == metadata.Metadata(inputImage)["DummyKey"] == "dummy_val"
        assert inputImage.GetNumberOfNodeReferences(
            "referenceImageGeometryRef"
        ) == outputImage.GetNumberOfNodeReferences("referenceImageGeometryRef")
        assert inputImage.GetNumberOfNodeReferences("referenceVolume") == outputImage.GetNumberOfNodeReferences(
            "referenceVolume"
        )

    def test_custom_center_feature(self):
        """
        Test the custom center UI toggle and verify the shading correction runs successfully with a custom center.
        """
        load_project(SYNTHETIC_RADIAL_SHADING_1_PROJECT_FILE)

        useCustomCenterCheckBox = self.widgets["useCustomCenterCheckBox"]
        centerXSpinBox = self.widgets["centerXSpinBox"]
        centerYSpinBox = self.widgets["centerYSpinBox"]
        pickCenterButton = self.widgets["pickCenterButton"]

        # Check default UI logic
        self.assertFalse(useCustomCenterCheckBox.isChecked())
        self.assertFalse(centerXSpinBox.isEnabled())
        self.assertFalse(centerYSpinBox.isEnabled())
        self.assertFalse(pickCenterButton.isEnabled())

        # Check toggled UI logic
        useCustomCenterCheckBox.setChecked(True)
        self.assertTrue(centerXSpinBox.isEnabled())
        self.assertTrue(centerYSpinBox.isEnabled())
        self.assertTrue(pickCenterButton.isEnabled())

        # Uncheck for clean state before _configure_inputs handles it
        useCustomCenterCheckBox.setChecked(False)

        # Configure and run with a custom center
        self._configure_inputs(
            projectPath=None,  # Already loaded
            inputImageNodeName="shaded",
            thresholdRange=SHADED_RADIAL_RANGE,
            outputImageName="shaded_custom_center",
            sliceGroupSizeValue=1,
            fittingPointsPercentageValue=100,
            functionType="Polynomial Radial",
            polynomialOrder=4,
            useCustomCenter=True,
            centerX=50,
            centerY=50,
        )

        self.widgets["applyButton"].clicked()
        wait(0.2)

        outputImage = slicer.util.getNode("shaded_custom_center")
        self.assertIsNotNone(outputImage)
        array = slicer.util.arrayFromVolume(outputImage)

        # Verify output exists and was processed correctly
        self.assertTrue(np.any(array > 0), "The resulting volume from a custom center operation is empty.")

    def test_pick_center_feature(self):
        """
        Test the 'Pick on Z' feature: creating the fiducial node, entering place mode,
        and correctly translating a 3D point into the 2D spinboxes.
        """
        load_project(SYNTHETIC_RADIAL_SHADING_1_PROJECT_FILE)

        # We configure inputs just enough to have a valid input node active
        # so the coordinate transform has a volume to refer to.
        self._configure_inputs(
            projectPath=None,
            inputImageNodeName="shaded",
            thresholdRange=SHADED_RADIAL_RANGE,
            outputImageName="shaded_pick_center",
            sliceGroupSizeValue=1,
            fittingPointsPercentageValue=100,
            useCustomCenter=True,
        )

        centerXSpinBox = self.widgets["centerXSpinBox"]
        centerYSpinBox = self.widgets["centerYSpinBox"]
        pickCenterButton = self.widgets["pickCenterButton"]

        # Ensure we start with 0 for tracking purposes
        centerXSpinBox.setValue(0)
        centerYSpinBox.setValue(0)

        # Click the pick center button
        pickCenterButton.clicked()
        wait(0.1)

        # 1. Verify Fiducial Node is created
        fiducialNode = slicer.mrmlScene.GetFirstNodeByName("ShadingCenter")
        self.assertIsNotNone(fiducialNode, "Fiducial node 'ShadingCenter' was not created.")

        # 2. Verify Interaction Mode changed to Place
        interactionNode = slicer.mrmlScene.GetNodeByID("vtkMRMLInteractionNodeSingleton")
        self.assertEqual(interactionNode.GetCurrentInteractionMode(), slicer.vtkMRMLInteractionNode.Place)

        # 3. Simulate placing a point safely within the bounds of the image
        volumeNode = slicer.util.getNode("shaded")
        dims = volumeNode.GetImageData().GetDimensions()
        target_i, target_j = dims[0] // 2, dims[1] // 2

        # Convert the target IJK directly to RAS to guarantee a positive coordinate inside the image
        ijkToRas = vtk.vtkMatrix4x4()
        volumeNode.GetIJKToRASMatrix(ijkToRas)
        pos_ras = ijkToRas.MultiplyPoint([target_i, target_j, 0, 1])

        # Adding the point. Depending on Slicer's exact version, this might fire the observer automatically.
        fiducialNode.AddControlPointWorld(vtk.vtkVector3d(pos_ras[0], pos_ras[1], pos_ras[2]))

        # If the point wasn't removed yet, it means the event didn't fire automatically, so we invoke it.
        if fiducialNode.GetNumberOfControlPoints() > 0:
            fiducialNode.InvokeEvent(slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent)

        wait(0.1)

        # 4. Verify Interaction Mode is reset back to ViewTransform
        self.assertEqual(interactionNode.GetCurrentInteractionMode(), slicer.vtkMRMLInteractionNode.ViewTransform)

        # 5. Verify spinboxes are updated with the newly calculated IJK coordinates
        self.assertEqual(
            centerXSpinBox.value,
            target_i,
            f"Center X spinbox was not updated correctly. Expected {target_i}, got {centerXSpinBox.value}",
        )
        self.assertEqual(
            centerYSpinBox.value,
            target_j,
            f"Center Y spinbox was not updated correctly. Expected {target_j}, got {centerYSpinBox.value}",
        )

        # 6. Verify control points are cleaned up (so it doesn't leave clutter on the image)
        self.assertEqual(fiducialNode.GetNumberOfControlPoints(), 0, "Temporary control points were not removed.")

    def _configure_inputs(
        self,
        projectPath: Union[Path, None],
        inputImageNodeName: str,
        thresholdRange: Tuple[float, float],
        outputImageName: str,
        sliceGroupSizeValue: int,
        fittingPointsPercentageValue: int,
        functionType: str = "Polynomial Radial",
        polynomialOrder: int = 4,
        useCustomCenter: bool = False,
        centerX: int = 0,
        centerY: int = 0,
    ) -> None:
        if projectPath is not None:
            load_project(projectPath)
        editor = self.widgets["thresholdEditor"]

        inputImage = slicer.util.getNode(inputImageNodeName)

        self.assertIsNotNone(inputImage)

        self.widgets["inputImageComboBox"].setCurrentNode(inputImage)
        self.widgets["initializeButton"].clicked()

        slider = editor.activeEffect().self().thresholdSlider
        apply = editor.activeEffect().self().applyButton
        slider.setMinimumValue(thresholdRange[0])
        slider.setMaximumValue(thresholdRange[1])
        process_events()

        apply.clicked()
        process_events()

        self.widgets["outputImageNameLineEdit"].setText(outputImageName)
        sliceGroupSize = self.widgets["sliceGroupSize"]
        sliceGroupSize.setValue(sliceGroupSizeValue)
        fittingPointsPercentage = self.widgets["fittingPointsPercentage"]
        fittingPointsPercentage.setValue(fittingPointsPercentageValue)

        functionTypeComboBox = self.widgets.get("functionTypeComboBox")
        functionTypeComboBox.setCurrentText(functionType)

        polynomialOrderComboBox = self.widgets.get("polynomialOrderComboBox")
        polynomialOrderComboBox.setCurrentText(str(polynomialOrder))

        # Handle custom center parameter injection using widget keys
        useCustomCenterCheckBox = self.widgets.get("useCustomCenterCheckBox")
        if useCustomCenterCheckBox:
            useCustomCenterCheckBox.setChecked(useCustomCenter)
            if useCustomCenter:
                self.widgets["centerXSpinBox"].setValue(centerX)
                self.widgets["centerYSpinBox"].setValue(centerY)

        process_events()

    def test_apply_and_cancel(self):
        """
        Here we are testing if the module as a whole works, produces the output and if the output is corrected, by measuring the decrease in
        the standard deviation of the data, an indicator that the radial shading was reduced.
        """
        self._configure_inputs(
            projectPath=SYNTHETIC_RADIAL_SHADING_1_PROJECT_FILE,
            inputImageNodeName="shaded_pcr",
            thresholdRange=SHADED_PCR_RANGE,
            outputImageName="shaded_shading_correction",
            sliceGroupSizeValue=1,
            fittingPointsPercentageValue=100,
        )

        applyButton = self.widgets["applyButton"]
        cancelButton = self.widgets["cancelButton"]

        def cancel():
            cancelButton.clicked()

        qt.QTimer.singleShot(100, cancel)
        applyButton.clicked()
        wait(0.2)

        outputImage = helpers.tryGetNode("shaded_shading_correction")
        assert outputImage is None

        possibleTemporaryNode = helpers.tryGetNode("TMP-LABELMAP*")
        assert possibleTemporaryNode is None

    def test_no_input_image_node(self):
        inputImageComboBox = self.widgets["inputImageComboBox"]
        assert inputImageComboBox.styleSheet == "", (
            f"Expected empty stylesheet, but got '{inputImageComboBox.styleSheet}'"
        )

        self.widgets["initializeButton"].clicked()

        wait(0.2)

        assert inputImageComboBox.styleSheet != "", (
            f"Expected a custom stylesheet, but got '{inputImageComboBox.styleSheet}'"
        )

    def test_wrong_output_image_name(self):
        self._configure_inputs(
            projectPath=SYNTHETIC_RADIAL_SHADING_1_PROJECT_FILE,
            inputImageNodeName="shaded_pcr",
            thresholdRange=SHADED_PCR_RANGE,
            outputImageName="",
            sliceGroupSizeValue=1,
            fittingPointsPercentageValue=100,
        )

        outputImageNameLineEdit = self.widgets["outputImageNameLineEdit"]
        assert outputImageNameLineEdit.styleSheet == "", (
            f"Expected empty stylesheet, but got '{outputImageNameLineEdit.styleSheet}'"
        )

        self.widgets["applyButton"].clicked()

        wait(0.2)

        assert outputImageNameLineEdit.styleSheet != "", (
            f"Expected a custom stylesheet, but got '{outputImageNameLineEdit.styleSheet}'"
        )

    def test_wrong_slice_group_size(self):
        self._configure_inputs(
            projectPath=SYNTHETIC_RADIAL_SHADING_1_PROJECT_FILE,
            inputImageNodeName="shaded_pcr",
            thresholdRange=SHADED_PCR_RANGE,
            outputImageName="shaded_shading_correction",
            sliceGroupSizeValue=2,
            fittingPointsPercentageValue=100,
        )

        sliceGroupSizeWidget = self.widgets["sliceGroupSize"]
        assert sliceGroupSizeWidget.styleSheet == "", (
            f"Expected empty stylesheet, but got '{sliceGroupSizeWidget.styleSheet}'"
        )

        self.widgets["applyButton"].clicked()

        wait(0.2)

        assert sliceGroupSizeWidget.styleSheet != "", (
            f"Expected a custom stylesheet, but got '{sliceGroupSizeWidget.styleSheet}'"
        )

    def test_output_image_has_same_type_as_input(self) -> None:
        inputDataType = np.int16
        slicer.util.addVolumeFromArray(
            np.random.random((100, 100, 100)).astype(inputDataType),
            name="TestInputVolume",
            nodeClassName="vtkMRMLScalarVolumeNode",
        )

        self._configure_inputs(
            projectPath=None,
            inputImageNodeName="TestInputVolume",
            thresholdRange=SHADED_PCR_RANGE,
            outputImageName="TestOutputVolume",
            sliceGroupSizeValue=1,
            fittingPointsPercentageValue=100,
        )

        self.widgets["applyButton"].clicked()
        wait(0.2)

        outputImage = slicer.util.getNode("TestOutputVolume")
        self.assertIsNotNone(outputImage)
        array = slicer.util.arrayFromVolume(outputImage)
        outputDataType = array.dtype

        self.assertEqual(inputDataType, outputDataType)

    def _common_test_nan_handling(self):
        load_project(SYNTHETIC_RADIAL_SHADING_1_PROJECT_FILE)

        inputNode = slicer.util.getNode("shaded")
        inputArray = slicer.util.arrayFromVolume(inputNode)

        # Use a numeric null value (-1000.0) to strictly test value preservation and mask handling
        null_val = -1000.0
        inputArray = inputArray.astype(np.float32)

        # Insert nulls
        # 1. A full slice at index 0.
        # Ideally, we put it at index 0 to ensure it is picked up by the downsampling in normalize_z
        # (which usually takes strided slices starting from 0). If normalize_z handles nulls incorrectly,
        # the statistics from this slice will corrupt the normalization of neighbors.
        inputArray[0, :, :] = null_val
        # 2. A small block to test local masking preservation
        inputArray[10:15, 50:60, 50:60] = null_val

        slicer.util.updateVolumeFromArray(inputNode, inputArray)
        helpers.setVolumeNullValue(inputNode, null_val)

        # Configure and run
        self._configure_inputs(
            projectPath=None,  # Already loaded
            inputImageNodeName="shaded",
            thresholdRange=SHADED_RADIAL_RANGE,
            outputImageName="shaded_nan_corrected",
            sliceGroupSizeValue=1,
            fittingPointsPercentageValue=100,
        )

        self.widgets["applyButton"].clicked()
        wait(0.2)

        outputNode = helpers.tryGetNode("shaded_nan_corrected")
        self.assertIsNotNone(outputNode)
        outputArray = slicer.util.arrayFromVolume(outputNode)

        # Check matching nulls
        # The logic should preserve null values exactly where they were in the input
        input_mask = inputArray == null_val
        output_mask = outputArray == null_val

        if not np.array_equal(input_mask, output_mask):
            self.fail("Null value masks do not match between input and output.")

        # Ensure no unexpected NaNs (since we use a numeric null value)
        unexpected_nans = np.isnan(outputArray)
        if np.any(unexpected_nans):
            self.fail("Output contains unexpected NaNs.")

        # Verify that slices adjacent to the fully-null slice (0) were properly corrected, not zeroed out.
        # Without gaussian_filter1d_nans, NaN from the empty correction field at slice 0 propagates to
        # neighboring slices during smoothing. Those neighbors then output 0 instead of corrected values
        # (NaN correction → NaN output → fallback to 0), which this check detects.
        adjacent_slice_output = outputArray[1]
        adjacent_slice_non_null = inputArray[1] != null_val
        if adjacent_slice_non_null.any() and not np.any(adjacent_slice_output[adjacent_slice_non_null] != 0):
            self.fail(
                "All non-null pixels in slice 1 (adjacent to the fully-null slice 0) are zero. "
                "This indicates NaN propagation from the correction field — gaussian_filter1d_nans is required."
            )

    def test_nan_handling(self):
        """Test that the shading correction handles null values correctly without propagation"""
        self._common_test_nan_handling()

    def test_nan_handling_mutation_normalize_z(self):
        """Test that normalize_z preserves null positions; fails if null handling is broken.

        normalize_z is used to create the normalized volume for mask/display purposes, so
        its null handling is tested directly here rather than through the full pipeline.
        """
        import PolynomialShadingCorrection

        original_normalize_z = PolynomialShadingCorrection.normalize_z

        null_val = -1000.0
        # Synthetic volume: slice 0 is entirely null (corrupts quantile stats if not excluded),
        # plus a small null block elsewhere.
        data = np.full((20, 60, 60), 150.0, dtype=np.float32)
        data[0, :, :] = null_val
        data[5:8, 20:25, 20:25] = null_val
        expected_null_mask = data == null_val

        with patch(
            "PolynomialShadingCorrection.normalize_z",
            side_effect=lambda *a, **kw: original_normalize_z(
                *a,
                **{**kw, "null_value": 7},  # Force wrong null value — null positions won't be preserved
            ),
        ):
            with self.assertRaises(AssertionError):
                result = PolynomialShadingCorrection.normalize_z(data, null_value=null_val)
                actual_null_mask = result == null_val
                if not np.array_equal(actual_null_mask, expected_null_mask):
                    raise AssertionError("Null value masks do not match in normalize_z output.")

    def test_nan_handling_mutation_gaussian(self):
        """Test that fails when the Gaussian filter is not NaN-aware"""

        def mocked_gaussian(input_array, sigma, truncate=4.0, axis=-1):
            # Use standard gaussian filter which propagates NaNs, unlike the custom NaN-safe one.
            # This will cause NaNs from the empty slice (index 0) to spread to neighbors,
            # triggering the unexpected_nans check.
            return gaussian_filter1d(input_array, sigma, truncate=truncate, axis=axis)

        with patch("commons.algorithms.shading_correction.gaussian_filter1d_nans", side_effect=mocked_gaussian):
            with self.assertRaises(AssertionError):
                self._common_test_nan_handling()
