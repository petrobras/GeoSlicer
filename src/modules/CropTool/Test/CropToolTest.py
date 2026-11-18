from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events, wait
from commons.slicer import helpers
import slicer
import vtk
import numpy as np
from commons.transforms import ijkToRAS, rasToIJK


class CropToolTest(LTracePluginTest):
    def post_setup(self):
        self.widget = self._module_widget

        CropTool = slicer.modules.CropToolInstance
        CropTool.set_setting("PreviousCrop/Size", None)
        CropTool.set_setting("PreviousCrop/Center", None)

    def tear_down(self):
        # for volume in self.byproducts:
        #     if volume and slicer.mrmlScene.GetNodeByID(volume.GetID()):
        #         slicer.mrmlScene.RemoveNode(volume)

        CropTool = slicer.modules.CropToolInstance
        CropTool.set_setting("PreviousCrop/Size", None)
        CropTool.set_setting("PreviousCrop/Center", None)
        self.widget = None

    def __addNewNodeByClass(self, className, name=None):
        node = slicer.mrmlScene.AddNewNodeByClass(className, name)
        # self.byproducts.append(node)
        return node

    def __createSampleVolume(
        self, name, shape=(20, 20, 20), dtype=np.uint16, range_=None, fill_grid: tuple = None, fill_value=1
    ):
        range_ = range_ or (0, np.iinfo(dtype).max)
        image = np.random.randint(*range_, size=shape, dtype=dtype)
        if fill_grid:
            if len(fill_grid) != len(shape):
                raise ValueError("fill_grid should have the same number of dimensions as shape")

            slices = tuple([slice(b, e) for b, e in fill_grid])
            image[slices] = fill_value

        volumeNode = self.__addNewNodeByClass("vtkMRMLVectorVolumeNode", name)
        volumeNode.SetAttribute("TestAttr", "TestValue")
        slicer.util.updateVolumeFromArray(volumeNode, image)
        volumeNode.Modified()

        return volumeNode

    def test_01_add_and_remove_volumes(self):
        self.assertEqual(self.widget.volumeInputTableWidget.volumeTableWidget.rowCount, 0)

        # Add a volume
        volumeNode = self.__createSampleVolume("TestVolume")

        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode)
        self.widget.volumeInputTableWidget.addButton.click()
        process_events()

        self.assertEqual(self.widget.volumeInputTableWidget.volumeTableWidget.rowCount, 1)
        self.assertEqual(self.widget.volumeInputTableWidget.volumeTableWidget.item(0, 1).text(), "TestVolume")

        # Remove the volume
        removeButton = self.widget.volumeInputTableWidget.volumeTableWidget.cellWidget(0, 2)
        removeButton.click()
        process_events()

        self.assertEqual(self.widget.volumeInputTableWidget.volumeTableWidget.rowCount, 0)

    def test_02_crop_auto_roi_and_keep(self):
        # Create and add a volume
        volumeNode = self.__createSampleVolume("TestVolume", shape=(20, 30, 40))

        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode)
        self.widget.volumeInputTableWidget.addButton.click()
        process_events()

        # An internal ROI should have been created
        self.assertIsNotNone(self.widget.roiNode)
        original_roi_name = self.widget.roiNode.GetName()

        # Set crop parameters
        self.widget.gridSizeWidget.setValues(10, 10, 10)
        self.widget.gridCenterWidget.setValues(10, 15, 20)
        process_events()

        # Configure and crop
        self.widget.copyAttributesCheckBox.setChecked(True)
        self.widget.keepROIAfterCropCheckBox.setChecked(True)
        self.widget.onCropButtonClicked()
        process_events()

        # Verify cropped volume
        croppedNode = slicer.util.getNode("TestVolume_Cropped")
        self.assertIsNotNone(croppedNode)
        self.assertEqual(croppedNode.GetAttribute("TestAttr"), "TestValue")

        # Verify ROI is kept and made permanent
        self.assertIsNone(self.widget.roiNode)  # Should be detached
        kept_roi = slicer.util.getNode(original_roi_name)
        self.assertIsNotNone(kept_roi)
        self.assertFalse(helpers.isTemporaryNode(kept_roi))

    def test_03_crop_auto_roi_and_discard(self):
        # Create and add a volume
        volumeNode = self.__createSampleVolume("TestVolume", shape=(20, 30, 40))
        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode)
        self.widget.volumeInputTableWidget.addButton.click()
        process_events()

        # An internal ROI should have been created
        self.assertIsNotNone(self.widget.roiNode)
        original_roi_name = self.widget.roiNode.GetName()

        # Configure and crop
        self.widget.keepROIAfterCropCheckBox.setChecked(False)
        self.widget.onCropButtonClicked()
        process_events()
        wait(1)  # Allow time for dangling objects to be deleted

        # Verify ROI is deleted
        self.assertIsNone(self.widget.roiNode)
        self.assertIsNone(helpers.tryGetNode(original_roi_name))

    def test_04_crop_with_copied_roi(self):
        # Create a volume and an external ROI
        volumeNode = self.__createSampleVolume("TestVolume", shape=(50, 50, 50))
        externalRoi = self.__addNewNodeByClass("vtkMRMLMarkupsROINode", "ExternalROI")
        externalRoi.SetCenter(10, 20, 30)
        externalRoi.SetRadiusXYZ(5, 5, 5)

        # Add volume to widget
        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode)
        self.widget.volumeInputTableWidget.addButton.click()
        process_events()

        # Select external ROI to be copied
        self.widget.roiSelector.setCurrentNode(externalRoi)
        process_events()

        # A new temporary ROI should have been created by copying the external one
        self.assertIsNotNone(self.widget.roiNode)
        self.assertNotEqual(self.widget.roiNode.GetName(), "ExternalROI")

        center = [0, 0, 0]
        self.widget.roiNode.GetCenter(center)
        self.assertTrue(np.allclose(center, [10, 20, 30]))

        # Crop and keep the copied ROI
        self.widget.keepROIAfterCropCheckBox.setChecked(True)
        self.widget.onCropButtonClicked()
        process_events()

        # Verify external ROI is untouched and copied one is permanent
        self.assertIsNotNone(slicer.util.getNode("ExternalROI"))
        self.assertTrue(len(slicer.util.getNodes("Crop ROI for TestVolume*")) > 0)

    def test_05_ui_and_roi_synchronization(self):
        # Create and add a volume
        volumeNode = self.__createSampleVolume("TestVolume", shape=(20, 20, 20))

        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode)
        self.widget.volumeInputTableWidget.addButton.click()
        process_events()

        # An internal ROI should be created
        roiNode = self.widget.roiNode
        self.assertIsNotNone(roiNode)

        # 1. Test UI to ROI sync
        self.widget.gridCenterWidget.setValues(5, 6, 7)
        self.widget.gridSizeWidget.setValues(8, 9, 10)
        process_events()

        center_ras = ijkToRAS(volumeNode, (5, 6, 7))
        radius_ras = [4.0, 4.5, 5.0]  # Assuming spacing is (1,1,1)

        actual_center = [0, 0, 0]
        roiNode.GetCenter(actual_center)
        actual_radius = [0, 0, 0]
        roiNode.GetRadiusXYZ(actual_radius)

        self.assertTrue(np.allclose(actual_center, center_ras, atol=1e-1))
        self.assertTrue(np.allclose(actual_radius, radius_ras, atol=1e-1))

        # 2. Test ROI to UI sync
        roiNode.SetCenter(1, 2, 3)
        roiNode.SetRadiusXYZ(2, 3, 4)
        # Manually invoke modified event as programmatic changes don't fire it
        self.widget.onRoiModified(roiNode, None)
        process_events()

        center_ui = self.widget.gridCenterWidget.values()
        size_ui = self.widget.gridSizeWidget.values()

        center_ijk = rasToIJK(volumeNode, (1, 2, 3))

        self.assertTrue(np.allclose(center_ui, center_ijk, atol=1e-1))
        self.assertTrue(np.allclose(size_ui, (4, 6, 8), atol=1e-1))

    def test_06_crop_at_boundaries_using_roi(self):
        # Create a volume
        volumeNode = self.__createSampleVolume(
            "BoundaryTestVolume", shape=(20, 20, 20), fill_grid=((0, 5), (0, 5), (0, 5)), fill_value=1
        )

        # Add volume to widget
        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode)
        self.widget.volumeInputTableWidget.addButton.click()
        process_events()

        roiNode = self.widget.roiNode
        self.assertIsNotNone(roiNode)

        # 2. Test ROI to UI sync
        roiNode.SetCenter(0, 0, 0)
        roiNode.SetRadiusXYZ(4.5, 4.5, 4.5)
        # Manually invoke modified event as programmatic changes don't fire it
        self.widget.onRoiModified(roiNode, None)
        process_events()

        # Crop
        self.widget.onCropButtonClicked()
        process_events()

        # Verify result
        croppedNode = slicer.util.getNode("BoundaryTestVolume_Cropped")
        self.assertIsNotNone(croppedNode)

        croppedArray = slicer.util.arrayFromVolume(croppedNode)
        self.assertEqual(croppedArray.shape, (5, 5, 5))
        self.assertTrue(np.all(croppedArray == 1))

    def test_07_crop_vector_volume(self):
        # Create a vector volume
        vectorVolumeNode = self.__createSampleVolume("VectorVolume", shape=(20, 20, 20, 3), dtype=np.uint8)

        # Add volume to widget
        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(vectorVolumeNode)
        self.widget.volumeInputTableWidget.addButton.click()
        process_events()

        # Set crop parameters
        self.widget.gridSizeWidget.setValues(10, 10, 10)
        self.widget.gridCenterWidget.setValues(10, 10, 10)
        process_events()

        # Crop
        self.widget.onCropButtonClicked()
        process_events()

        # Verify result
        croppedNode = slicer.util.getNode("VectorVolume_Cropped")
        self.assertIsNotNone(croppedNode)
        self.assertEqual(croppedNode.GetClassName(), "vtkMRMLVectorVolumeNode")

        croppedArray = slicer.util.arrayFromVolume(croppedNode)
        self.assertEqual(croppedArray.shape, (10, 10, 10, 3))

    def test_08_multi_volume_roi_switching(self):
        # Create two volumes of different sizes
        volumeNode1 = self.__createSampleVolume("Volume1", shape=(10, 10, 10))
        volumeNode2 = self.__createSampleVolume("Volume2", shape=(20, 20, 20))

        # Add both to widget
        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode1)
        self.widget.volumeInputTableWidget.addButton.click()
        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode2)
        self.widget.volumeInputTableWidget.addButton.click()
        process_events()

        # ROI should be fitted to Volume 1
        size_ui1 = self.widget.gridSizeWidget.values()
        self.assertEqual(size_ui1, (10, 10, 10))

        # Make Volume 2 visible
        self.widget.volumeInputTableWidget.volumeTableWidget.cellWidget(1, 0).click()
        process_events()

        # ROI should be fitted to Volume 2
        size_ui2 = self.widget.gridSizeWidget.values()
        self.assertEqual(size_ui2, (20, 20, 20))

    def test_09_crop_empty_input(self):
        # Ensure no volumes are in the list
        self.assertEqual(self.widget.volumeInputTableWidget.volumeTableWidget.rowCount, 0)

        # Mock slicer.util.infoDisplay to check if it's called
        self.infoDisplayCalled = False

        def mockInfoDisplay(text):
            self.infoDisplayCalled = True
            self.assertEqual(text, "No images to be cropped.")

        originalInfoDisplay = slicer.util.infoDisplay
        slicer.util.infoDisplay = mockInfoDisplay

        # Click crop
        self.widget.onCropButtonClicked()
        process_events()

        # Restore original method
        slicer.util.infoDisplay = originalInfoDisplay

        # Verify info message was shown
        self.assertTrue(self.infoDisplayCalled)

    def test_10_multi_volume_different_dtype_same_size(self):
        # Create two volumes of different sizes
        volumeNode1 = self.__createSampleVolume(
            "Volume1", shape=(20, 20, 20), fill_grid=((5, 15), (5, 15), (5, 15)), fill_value=1
        )
        volumeNode2 = self.__createSampleVolume(
            "Volume2",
            shape=(20, 20, 20, 3),
            dtype=np.uint8,
            fill_grid=((5, 15), (5, 15), (5, 15), (0, 3)),
            fill_value=255,
        )

        # Add both to widget
        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode1)
        self.widget.volumeInputTableWidget.addButton.click()
        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode2)
        self.widget.volumeInputTableWidget.addButton.click()
        process_events()

        # ROI should be fitted to Volume 1
        size_ui1 = self.widget.gridSizeWidget.values()
        self.assertEqual(size_ui1, (20, 20, 20))

        # Set crop parameters
        self.widget.gridSizeWidget.setValues(10, 10, 10)
        self.widget.gridCenterWidget.setValues(9.5, 9.5, 9.5)
        process_events()

        # Click crop
        self.widget.onCropButtonClicked()
        process_events()

        # Verify result
        croppedNode = slicer.util.getNode("Volume1_Cropped")
        self.assertIsNotNone(croppedNode)

        croppedArray = slicer.util.arrayFromVolume(croppedNode)
        self.assertEqual(croppedArray.shape, (10, 10, 10))
        self.assertTrue(np.all(croppedArray == 1))

        croppedVectorNode = slicer.util.getNode("Volume2_Cropped")
        self.assertIsNotNone(croppedVectorNode)

        croppedVectorArray = slicer.util.arrayFromVolume(croppedVectorNode)
        self.assertEqual(croppedVectorArray.shape, (10, 10, 10, 3))
        self.assertTrue(np.all(croppedVectorArray == 255))

    def test_11_crop_history(self):
        CropTool = slicer.modules.CropToolInstance
        # Clear existing history for clean test
        CropTool.set_setting("PreviousCrop/Size", [])
        CropTool.set_setting("PreviousCrop/Center", [])

        # Create a volume to allow cropping
        volumeNode = self.__createSampleVolume("HistoryVolume", shape=(50, 50, 50))
        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode)
        self.widget.volumeInputTableWidget.addButton.click()
        process_events()

        # 1. Test basic history saving
        self.widget.gridSizeWidget.setValues(10, 11, 12)
        self.widget.gridCenterWidget.setValues(20, 21, 22)
        self.widget.onCropButtonClicked()
        process_events()

        size_history = CropTool.get_setting("PreviousCrop/Size")
        center_history = CropTool.get_setting("PreviousCrop/Center")

        self.assertEqual(len(size_history), 1)
        self.assertEqual(size_history[0], (10.0, 11, 12))
        self.assertEqual(center_history[0], (20, 21, 22))

        # 2. Test duplicate handling (should move to top, not duplicate)
        # Add a different one first
        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode)
        self.widget.volumeInputTableWidget.addButton.click()
        self.widget.gridSizeWidget.setValues(30, 31, 32)
        self.widget.gridCenterWidget.setValues(40, 41, 42)
        self.widget.onCropButtonClicked()
        process_events()

        # Add the first one again
        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode)
        self.widget.volumeInputTableWidget.addButton.click()
        self.widget.gridSizeWidget.setValues(10, 11, 12)
        self.widget.gridCenterWidget.setValues(20, 21, 22)
        self.widget.onCropButtonClicked()
        process_events()

        size_history = CropTool.get_setting("PreviousCrop/Size")
        self.assertEqual(len(size_history), 2)
        self.assertEqual(size_history[0], (10, 11, 12))  # Most recent at top

        # 3. Test 10 entries limit
        for i in range(15):
            self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode)
            self.widget.volumeInputTableWidget.addButton.click()
            self.widget.gridSizeWidget.setValues(i, i, i)
            self.widget.gridCenterWidget.setValues(i, i, i)
            self.widget.onCropButtonClicked()
            process_events()

        size_history = CropTool.get_setting("PreviousCrop/Size")
        self.assertEqual(len(size_history), 10)
        self.assertEqual(size_history[0], (14, 14, 14))

    def __rotateRoi(self, roiNode, angleDegrees, axis=(0, 0, 1)):
        center = [0.0] * 3
        roiNode.GetCenter(center)

        transform = vtk.vtkTransform()
        transform.RotateWXYZ(angleDegrees, *axis)

        matrix = vtk.vtkMatrix4x4()
        matrix.DeepCopy(transform.GetMatrix())
        for axisIndex in range(3):
            matrix.SetElement(axisIndex, 3, center[axisIndex])

        roiNode.SetAndObserveObjectToNodeMatrix(matrix)

    def test_12_crop_with_rotated_roi(self):
        volumeNode = self.__createSampleVolume("ObliqueVolume", shape=(40, 40, 40, 3), dtype=np.uint8)
        volumeNode.SetSpacing(0.1, 0.2, 0.4)

        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode)
        self.widget.volumeInputTableWidget.addButton.click()
        process_events()

        roiNode = self.widget.roiNode
        self.assertFalse(self.widget.logic.isRoiRotated(roiNode))

        roiNode.SetCenter(2.0, 4.0, 8.0)
        roiNode.SetRadiusXYZ(1.0, 2.0, 4.0)
        self.__rotateRoi(roiNode, 90)
        self.assertTrue(self.widget.logic.isRoiRotated(roiNode))

        # A 90 degree turn about S swaps the R and A axes, so the ROI axes take the swapped
        # spacings (0.2, 0.1, 0.4) rather than the volume's own (0.1, 0.2, 0.4).
        announcedSize = self.widget.logic.getSelectionSize(volumeNode, roiNode)
        self.assertEqual(announcedSize, (10, 40, 20))

        self.widget.onCropButtonClicked()
        process_events()

        croppedNode = slicer.util.getNode("ObliqueVolume - Cropped")
        self.assertEqual(croppedNode.GetImageData().GetDimensions(), announcedSize)

    def test_13_rotated_roi_size_round_trip(self):
        volumeNode = self.__createSampleVolume("RoundTripVolume", shape=(40, 40, 40, 3), dtype=np.uint8)
        volumeNode.SetSpacing(0.1, 0.2, 0.4)

        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode)
        self.widget.volumeInputTableWidget.addButton.click()
        process_events()

        roiNode = self.widget.roiNode
        roiNode.SetCenter(2.0, 4.0, 8.0)
        roiNode.SetRadiusXYZ(1.0, 2.0, 4.0)
        self.__rotateRoi(roiNode, 90)

        size = self.widget.logic.getSelectionSize(volumeNode, roiNode)
        self.widget.logic.setXYZRadiusFromIJK(volumeNode, roiNode, size)
        self.assertEqual(self.widget.logic.getSelectionSize(volumeNode, roiNode), size)

    def test_14_unrotated_roi_size_is_unchanged(self):
        volumeNode = self.__createSampleVolume("RoundVolume", shape=(64, 64, 64))
        volumeNode.SetSpacing(0.1, 0.1, 0.1)

        self.widget.volumeInputTableWidget.volumeInputComboBox.setCurrentNode(volumeNode)
        self.widget.volumeInputTableWidget.addButton.click()
        process_events()

        roiNode = self.widget.roiNode
        roiNode.SetRadiusXYZ(1.99, 1.99, 1.99)

        # 2 * 1.99 / 0.1 = 39.8. The unrotated path must keep rounding up, as its numpy slicing
        # honours the requested size literally; the resampler would floor it to 39.
        self.assertEqual(self.widget.logic.getSelectionSize(volumeNode, roiNode), (40, 40, 40))

    def test_15_rotated_labelmap_preserves_labels(self):
        labelMapNode = self.__addNewNodeByClass("vtkMRMLLabelMapVolumeNode", "ObliqueLabelMap")
        image = np.zeros((40, 40, 40), dtype=np.uint8)
        image[10:30, 10:30, 10:30] = 3
        slicer.util.updateVolumeFromArray(labelMapNode, image)
        labelMapNode.SetSpacing(0.1, 0.1, 0.1)

        roiNode = self.__addNewNodeByClass("vtkMRMLMarkupsROINode", "ObliqueLabelRoi")
        roiNode.SetCenter(2.0, 2.0, 2.0)
        roiNode.SetRadiusXYZ(1.5, 1.5, 1.5)
        self.__rotateRoi(roiNode, 33)

        croppedNode = self.widget.logic.crop(labelMapNode, roiNode, None)

        # Linear interpolation would smear labels 1 and 2 into the 0/3 boundary.
        labels = sorted(np.unique(slicer.util.arrayFromVolume(croppedNode)).tolist())
        self.assertEqual(labels, [0, 3])

    def test_16_rotated_crop_reports_unsupported_image_type(self):
        # Imported here because CropTool imports this suite before defining CropInfo.
        from CropTool import CropInfo

        # A vector volume holding single component data cannot be resampled by the crop volume
        # CLI, which reports success while writing nothing. The crop must fail loudly instead.
        volumeNode = self.__createSampleVolume("DegenerateVolume", shape=(40, 40, 40))
        self.assertEqual(volumeNode.GetImageData().GetNumberOfScalarComponents(), 1)

        roiNode = self.__addNewNodeByClass("vtkMRMLMarkupsROINode", "DegenerateRoi")
        roiNode.SetCenter(20.0, 20.0, 20.0)
        roiNode.SetRadiusXYZ(5.0, 5.0, 5.0)
        self.__rotateRoi(roiNode, 45)

        with self.assertRaises(CropInfo):
            self.widget.logic.crop(volumeNode, roiNode, None)
