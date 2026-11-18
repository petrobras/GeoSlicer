import slicer
import numpy as np
import qt
import vtk
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events, load_project, wait, clickSubjectHierarchyVisibility
from commons.slicer import metadata
from commons.slicer_utils import sliceViewVolumeFractions
from commons.slicer.metadata import Metadata
from commons.slicer import helpers
from pathlib import Path

PROPS_TEST_PATH = Path(__file__).parent / "Resources" / "PropsTest" / "PropsTest.mrml"


class CustomizedDataTest(LTracePluginTest):
    def _set_current_node(self, node):
        sh_node = slicer.mrmlScene.GetSubjectHierarchyNode()
        node_id = sh_node.GetItemByDataNode(node)
        sh_tree = self._module_widget.subjectHierarchyTreeView
        sh_tree.setCurrentItem(node_id)

    def test_scalar_volume_spacing_format(self):
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        slicer.util.updateVolumeFromArray(volume, np.zeros((10, 10, 10)))
        volume.SetSpacing((1000.237000001, 0.001240000000005, 1.0))

        self._set_current_node(volume)
        data_widget = self._module_widget.scalarVolumeWidget
        self.assertTrue(data_widget.visible)
        self.assertEqual(data_widget.imageSpacing1LineEdit.text, "1000.237")
        self.assertEqual(data_widget.imageSpacing2LineEdit.text, "0.00124")
        self.assertEqual(data_widget.imageSpacing3LineEdit.text, "1")

    def test_labelmap_volume_spacing_format(self):
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(volume, np.zeros((10, 10, 10), dtype=np.int16))
        volume.CreateDefaultDisplayNodes()
        volume.GetDisplayNode().SetAndObserveColorNodeID(slicer.mrmlScene.GetFirstNodeByName("Warm1").GetID())
        volume.SetSpacing((1000.237000001, 0.001240000000005, 1.0))

        self._set_current_node(volume)
        data_widget = self._module_widget.labelMapWidget
        self.assertTrue(data_widget.visible)
        self.assertEqual(data_widget.imageSpacing1LineEdit.text, "1000.237")
        self.assertEqual(data_widget.imageSpacing2LineEdit.text, "0.00124")
        self.assertEqual(data_widget.imageSpacing3LineEdit.text, "1")

    def test_vector_volume_spacing_format(self):
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode")
        slicer.util.updateVolumeFromArray(volume, np.zeros((10, 10, 10, 3)))
        volume.SetSpacing((1000.237000001, 0.001240000000005, 1.0))

        self._set_current_node(volume)
        data_widget = self._module_widget.vectorVolumeWidget
        self.assertTrue(data_widget.visible)
        self.assertEqual(data_widget.imageSpacing1LineEdit.text, "1000.237")
        self.assertEqual(data_widget.imageSpacing2LineEdit.text, "0.00124")
        self.assertEqual(data_widget.imageSpacing3LineEdit.text, "1")

    def test_threshold_off_by_default(self):
        array = np.random.rand(200, 200, 200) * 1000
        array[40:70, 40:70] = 21234.56789123456
        array[100, 100, 100] = 100_000
        array[100, 100, 101] = -1
        array = array.astype(np.float32)
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        slicer.util.updateVolumeFromArray(volume, array)

        volume.CreateDefaultDisplayNodes()
        volume.GetDisplayNode().SetVisibility(True)
        self._set_current_node(volume)

        data_widget = self._module_widget.scalarVolumeWidget
        self.assertTrue(data_widget.visible)
        thresh_mode_box = data_widget.findChild(qt.QComboBox, "AutoManualComboBox")
        self.assertEqual(thresh_mode_box.currentText, "Off")
        self.assertAlmostEqual(data_widget.thresholdWidget.lowerThreshold, -1)
        self.assertAlmostEqual(data_widget.thresholdWidget.upperThreshold, 100_000)
        self.assertAlmostEqual(data_widget.thresholdWidget.lowerThresholdBound, -1)
        self.assertAlmostEqual(data_widget.thresholdWidget.upperThresholdBound, 100_000)

        spinBox = data_widget.volumeThresholdRangeWidget.findChild(qt.QWidget, "MaximumSpinBox")
        # I don't know why this needs to run twice
        spinBox.setValue(9999)
        spinBox.setValue(9999)
        process_events()
        self.assertAlmostEqual(data_widget.thresholdWidget.lowerThreshold, -1)
        self.assertAlmostEqual(data_widget.thresholdWidget.upperThreshold, 9999)
        self.assertAlmostEqual(data_widget.thresholdWidget.lowerThresholdBound, -1)
        self.assertAlmostEqual(data_widget.thresholdWidget.upperThresholdBound, 100_000)

    def test_hide_scalar_widget_on_close_scene(self):
        array = np.random.rand(100, 100, 100)
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        slicer.util.updateVolumeFromArray(volume, array)

        widget = self._module_widget.scalarVolumeWidget
        self.assertFalse(widget.visible)

        self._set_current_node(volume)

        self.assertTrue(widget.visible)

        slicer.mrmlScene.Clear(0)
        self.assertFalse(widget.visible)

    def test_hide_labelmap_widget_on_close_scene(self):
        array = (np.random.rand(100, 100, 100) * 5).astype(np.uint16)
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(volume, array)

        widget = self._module_widget.labelMapWidget
        self.assertFalse(widget.visible)

        self._set_current_node(volume)

        self.assertTrue(widget.visible)

        slicer.mrmlScene.Clear(0)
        self.assertFalse(widget.visible)

    def test_hide_vector_widget_on_close_scene(self):
        array = np.random.rand(100, 100, 100, 3)
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode")
        slicer.util.updateVolumeFromArray(volume, array)

        widget = self._module_widget.vectorVolumeWidget
        self.assertFalse(widget.visible)

        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        sh_id = sh.GetItemByDataNode(volume)
        sh_tree = self._module_widget.subjectHierarchyTreeView
        sh_tree.setCurrentItem(sh_id)

        self.assertTrue(widget.visible)

        slicer.mrmlScene.Clear(0)
        self.assertFalse(widget.visible)

    def test_hide_seg_widget_on_close_scene(self):
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        volume.CreateDefaultDisplayNodes()

        widget = self._module_widget.segmentationWidget
        self.assertFalse(widget.visible)

        self._set_current_node(volume)

        self.assertTrue(widget.visible)

        slicer.mrmlScene.Clear(0)
        self.assertFalse(widget.visible)

    def test_hide_table_widget_on_close_scene(self):
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")

        widget = self._module_widget.tableWidget
        self.assertFalse(widget.visible)

        self._set_current_node(node)

        self.assertTrue(widget.visible)

        slicer.mrmlScene.Clear(0)
        self.assertFalse(widget.visible)

    def test_slices_in_3d(self):
        sliceNodes = []
        compositeNodes = []
        for sliceViewLabel in ["Red", "Yellow", "Green"]:
            sliceWidget = slicer.app.layoutManager().sliceWidget(sliceViewLabel)
            sliceView = sliceWidget.sliceView()
            sliceNodes.append(sliceView.mrmlSliceNode())
            compositeNodes.append(sliceWidget.mrmlSliceCompositeNode())
        widget = self._module_widget.scalarVolumeWidget

        # Reset slice visibility in 3D
        for sliceNode in sliceNodes:
            sliceNode.SetSliceVisible(False)

        volumes = []
        for _ in range(2):
            array = np.random.rand(100, 100, 100)
            volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
            slicer.util.updateVolumeFromArray(volume, array)
            volumes.append(volume)

        self._set_current_node(volumes[0])

        # Check that slices are still not visible in 3D
        for sliceNode in sliceNodes:
            self.assertFalse(sliceNode.GetSliceVisible())

        # Check that the checkbox is unchecked
        self.assertFalse(widget.slicesIn3DCheckBox.isChecked())

        widget.slicesIn3DCheckBox.click()
        process_events()

        # Check that slices are now visible in 3D
        for sliceNode in sliceNodes:
            self.assertTrue(sliceNode.GetSliceVisible())

        # Check that the background volume is the one selected
        for compositeNode in compositeNodes:
            self.assertEqual(compositeNode.GetBackgroundVolumeID(), volumes[0].GetID())

        # Select another volume
        self._set_current_node(volumes[1])
        process_events()

        # Check that state is still the same
        for sliceNode in sliceNodes:
            self.assertTrue(sliceNode.GetSliceVisible())
        for compositeNode in compositeNodes:
            self.assertEqual(compositeNode.GetBackgroundVolumeID(), volumes[0].GetID())

        # Check that the checkbox is unchecked now
        self.assertFalse(widget.slicesIn3DCheckBox.isChecked())

        # Going back should check the checkbox again
        self._set_current_node(volumes[0])
        self.assertTrue(widget.slicesIn3DCheckBox.isChecked())

        # Check that state is still the same
        for sliceNode in sliceNodes:
            self.assertTrue(sliceNode.GetSliceVisible())
        for compositeNode in compositeNodes:
            self.assertEqual(compositeNode.GetBackgroundVolumeID(), volumes[0].GetID())

        self._set_current_node(volumes[1])
        process_events()
        widget.slicesIn3DCheckBox.click()
        process_events()

        for sliceNode in sliceNodes:
            self.assertTrue(sliceNode.GetSliceVisible())

        # Should change the background volume
        for compositeNode in compositeNodes:
            self.assertEqual(compositeNode.GetBackgroundVolumeID(), volumes[1].GetID())

        # Check that the checkbox is checked
        self.assertTrue(widget.slicesIn3DCheckBox.isChecked())

        # Uncheck the checkbox
        widget.slicesIn3DCheckBox.click()
        process_events()

        # Check that slices are not visible in 3D
        for sliceNode in sliceNodes:
            self.assertFalse(sliceNode.GetSliceVisible())

        # Select another volume and check that the checkbox is unchecked
        self._set_current_node(volumes[0])
        self.assertTrue(widget.slicesIn3DCheckBox.isChecked())

    def test_slices_in_3d_with_labelmap(self):
        sliceNodes = []
        compositeNodes = []
        for sliceViewLabel in ["Red", "Yellow", "Green"]:
            sliceWidget = slicer.app.layoutManager().sliceWidget(sliceViewLabel)
            sliceView = sliceWidget.sliceView()
            sliceNodes.append(sliceView.mrmlSliceNode())
            compositeNodes.append(sliceWidget.mrmlSliceCompositeNode())
        scalarWidget = self._module_widget.scalarVolumeWidget
        labelMapWidget = self._module_widget.labelMapWidget

        # Reset slice visibility in 3D
        for sliceNode in sliceNodes:
            sliceNode.SetSliceVisible(False)

        array = np.random.rand(100, 100, 100)
        scalarVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        slicer.util.updateVolumeFromArray(scalarVolume, array)

        array = (array * 5).astype(np.uint16)
        labelMapVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(labelMapVolume, array)

        self._set_current_node(scalarVolume)

        # Check that slices are still not visible in 3D
        for sliceNode in sliceNodes:
            self.assertFalse(sliceNode.GetSliceVisible())

        # Check that the checkbox is unchecked
        self.assertTrue(scalarWidget.visible)
        self.assertFalse(labelMapWidget.visible)
        self.assertFalse(scalarWidget.slicesIn3DCheckBox.isChecked())

        scalarWidget.slicesIn3DCheckBox.click()
        process_events()

        # Check that slices are now visible in 3D
        for sliceNode in sliceNodes:
            self.assertTrue(sliceNode.GetSliceVisible())

        # Check that the background volume is the one selected
        for compositeNode in compositeNodes:
            self.assertEqual(compositeNode.GetBackgroundVolumeID(), scalarVolume.GetID())

        # Select another volume
        self._set_current_node(labelMapVolume)
        process_events()

        # Check that state is still the same
        for sliceNode in sliceNodes:
            self.assertTrue(sliceNode.GetSliceVisible())
        for compositeNode in compositeNodes:
            self.assertEqual(compositeNode.GetBackgroundVolumeID(), scalarVolume.GetID())

        # Check that the checkbox is unchecked now
        self.assertFalse(scalarWidget.visible)
        self.assertTrue(labelMapWidget.visible)
        self.assertFalse(labelMapWidget.slicesIn3DCheckBox.isChecked())

        # Going back should check the checkbox again
        self._set_current_node(scalarVolume)
        self.assertTrue(scalarWidget.visible)
        self.assertFalse(labelMapWidget.visible)
        self.assertTrue(scalarWidget.slicesIn3DCheckBox.isChecked())

        # Check that state is still the same
        for sliceNode in sliceNodes:
            self.assertTrue(sliceNode.GetSliceVisible())
        for compositeNode in compositeNodes:
            self.assertEqual(compositeNode.GetBackgroundVolumeID(), scalarVolume.GetID())

        self._set_current_node(labelMapVolume)
        process_events()
        self.assertFalse(scalarWidget.visible)
        self.assertTrue(labelMapWidget.visible)
        labelMapWidget.slicesIn3DCheckBox.click()
        process_events()

        for sliceNode in sliceNodes:
            self.assertTrue(sliceNode.GetSliceVisible())

        # Both volumes should be visible in 3D
        for compositeNode in compositeNodes:
            self.assertEqual(compositeNode.GetBackgroundVolumeID(), scalarVolume.GetID())
            self.assertEqual(compositeNode.GetLabelVolumeID(), labelMapVolume.GetID())

        # Check that the checkbox is checked
        self.assertFalse(scalarWidget.visible)
        self.assertTrue(labelMapWidget.visible)
        self.assertTrue(labelMapWidget.slicesIn3DCheckBox.isChecked())

        # Uncheck the checkbox
        labelMapWidget.slicesIn3DCheckBox.click()
        process_events()

        # Check that slices are not visible in 3D
        for sliceNode in sliceNodes:
            self.assertFalse(sliceNode.GetSliceVisible())

        # Select another volume and check that the checkbox is unchecked
        self._set_current_node(scalarVolume)
        self.assertTrue(scalarWidget.visible)
        self.assertFalse(labelMapWidget.visible)
        self.assertTrue(scalarWidget.slicesIn3DCheckBox.isChecked())

    def test_text_widget_display_and_search(self):
        # Create a vtkMRMLTextNode and set text
        text_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTextNode")
        test_text = "Hello world\nHello Slicer\nHELLO again\nhello"
        text_node.SetText(test_text)

        # Set as current node in the widget
        self._set_current_node(text_node)
        text_widget = self._module_widget.textWidget

        self.assertTrue(text_widget.visible)
        self.assertEqual(text_widget.textEdit.toPlainText(), test_text)

        # Test search highlights (case-insensitive)
        text_widget.searchField.setText("Hello")
        process_events()
        self.assertEqual(len(text_widget.matches), 4)  # "Hello" matches all 4 lines (case-insensitive)

        # Test navigation: scrollToMatch
        text_widget.scrollToMatch(1)
        self.assertEqual(text_widget.currentMatchIndex, 0)
        text_widget.scrollToMatch(1)
        self.assertEqual(text_widget.currentMatchIndex, 1)
        text_widget.scrollToMatch(1)
        self.assertEqual(text_widget.currentMatchIndex, 2)
        text_widget.scrollToMatch(1)
        self.assertEqual(text_widget.currentMatchIndex, 3)
        text_widget.scrollToMatch(1)
        self.assertEqual(text_widget.currentMatchIndex, 0)  # wraps around

        # Test navigation backwards
        text_widget.scrollToMatch(-1)
        self.assertEqual(text_widget.currentMatchIndex, 3)

        # Test search for a string not present
        text_widget.searchField.setText("foobar")
        process_events()
        self.assertEqual(len(text_widget.matches), 0)
        self.assertEqual(text_widget.currentMatchIndex, -1)

        # Test that widget hides when scene is cleared
        slicer.mrmlScene.Clear(0)
        self.assertFalse(text_widget.visible)

    def test_render_in_3d_attributes(self):
        sliceNames = ["Red", "Yellow", "Green"]

        sliceNodes = [slicer.app.layoutManager().sliceWidget(name).mrmlSliceNode() for name in sliceNames]

        scalarWidget = self._module_widget.scalarVolumeWidget
        labelMapWidget = self._module_widget.labelMapWidget

        # Reset slice visibility in 3D
        for sliceNode in sliceNodes:
            sliceNode.SetSliceVisible(False)

        array = np.random.rand(100, 100, 100)
        scalarVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        slicer.util.updateVolumeFromArray(scalarVolume, array)

        array = (array * 5).astype(np.uint16)
        labelMapVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(labelMapVolume, array)

        self._set_current_node(scalarVolume)

        # Check that slices are still not visible in 3D
        for sliceNode in sliceNodes:
            self.assertFalse(sliceNode.GetSliceVisible())

        # Check that the checkbox is unchecked
        self.assertTrue(scalarWidget.visible)
        self.assertFalse(labelMapWidget.visible)
        self.assertFalse(scalarWidget.slicesIn3DCheckBox.isChecked())

        scalarWidget.slicesIn3DCheckBox.click()
        process_events()

        # Check that the attribute is set after clicking the checkbox
        self.assertTrue(scalarVolume.GetAttribute("!Data[ScalarVolume].slicesIn3D") == "True")

        # Check that slices are now visible in 3D
        for sliceNode in sliceNodes:
            self.assertTrue(sliceNode.GetSliceVisible())

        # Test render 3D checkbox

        # Check that the checkbox is unchecked then check it
        self.assertFalse(scalarWidget.renderIn3DCheckBox.isChecked())
        scalarWidget.renderIn3DCheckBox.click()
        process_events()
        # Check that the attribute is set after clicking the checkbox
        self.assertTrue(scalarVolume.GetAttribute("!Data[ScalarVolume].renderIn3D") == "True")
        self.assertTrue(scalarWidget.renderIn3DCheckBox.isChecked())

        viewNode = slicer.app.layoutManager().threeDWidget(0).mrmlViewNode()
        volumeRenderingLogic = slicer.modules.volumerendering.logic()
        renderingNode = volumeRenderingLogic.GetVolumeRenderingDisplayNodeForViewNode(scalarVolume, viewNode)

        # Check if volume is visible in 3D
        self.assertTrue(renderingNode.GetVisibility())

        # Test unchecking the checkbox, the attribute should be set to False
        scalarWidget.renderIn3DCheckBox.click()
        process_events()

        self.assertFalse(scalarWidget.renderIn3DCheckBox.isChecked())
        self.assertFalse(scalarVolume.GetAttribute("!Data[ScalarVolume].renderIn3D") == "True")

        # and 3D visibility off
        renderingNode = volumeRenderingLogic.GetVolumeRenderingDisplayNodeForViewNode(scalarVolume, viewNode)
        self.assertFalse(renderingNode is not None and renderingNode.GetVisibility())

        # Test checking the checkbox again, the attribute should be set to True
        scalarWidget.renderIn3DCheckBox.click()
        process_events()

        self.assertTrue(scalarWidget.renderIn3DCheckBox.isChecked())
        self.assertTrue(scalarVolume.GetAttribute("!Data[ScalarVolume].renderIn3D") == "True")

        # Disable global visibility
        scalarVolume.GetDisplayNode().SetVisibility(False)
        process_events()

        # it must keep the attribute True but the volume must not be visible in 3D
        self.assertTrue(scalarWidget.renderIn3DCheckBox.isChecked())
        self.assertTrue(scalarVolume.GetAttribute("!Data[ScalarVolume].renderIn3D") == "True")
        renderingNode = volumeRenderingLogic.GetVolumeRenderingDisplayNodeForViewNode(scalarVolume, viewNode)
        self.assertFalse(renderingNode.GetVisibility3D() == 0)
        self.assertFalse(renderingNode.GetVisibility() == 0)

        # Select another volume to chekc if the attribute is kept when switching
        self._set_current_node(labelMapVolume)
        self.assertFalse(labelMapWidget.renderIn3DCheckBox.isChecked())

        self.assertTrue(scalarVolume.GetAttribute("!Data[ScalarVolume].renderIn3D") == "True")

        # Go back to the scalar volume, the checkbox must be checked
        self._set_current_node(scalarVolume)
        self.assertTrue(scalarWidget.renderIn3DCheckBox.isChecked())

        self.assertTrue(scalarVolume.GetAttribute("!Data[ScalarVolume].renderIn3D") == "True")

        # by coming back the volume must be visible in 3D
        renderingNode = volumeRenderingLogic.GetVolumeRenderingDisplayNodeForViewNode(scalarVolume, viewNode)
        self.assertTrue(renderingNode.GetVisibility())

    def test_clone_table_node(self):
        # Create a volume node
        volume_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        volume_node.SetName("TestVolume")
        volume_node.SetAttribute("TestAttribute", "TestValue")
        volume_id = volume_node.GetID()

        # Create a table node
        table_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
        table_node.SetName("TestTable")
        table_node.SetAttribute("TestAttribute", "TestValue")
        table_node.SetNodeReferenceID("storage", "vtkMRMLStorageNode")
        table_node.SetNodeReferenceID("volumeRef", volume_id)

        # Add metadata to the node
        with Metadata(table_node) as meta:
            meta["test_key"] = "test_value"
            meta["test_number"] = 123

        # Set as current selected node
        self._set_current_node(table_node)

        # Trigger the clone action
        self._module_widget.cloneAction.trigger()
        process_events()

        # Get the cloned node
        cloned_node = slicer.util.getNode(f"{table_node.GetName()} Copy")
        self.assertIsNotNone(cloned_node)

        # Verify that the attributes are copied
        self.assertEqual(cloned_node.GetAttribute("TestAttribute"), "TestValue")

        # Verify that the metadata is copied
        cloned_meta = Metadata(cloned_node)
        self.assertEqual(cloned_meta.get("test_key"), "test_value")
        self.assertEqual(cloned_meta.get("test_number"), 123)

        # Verify that the references are copied, except for "storage"
        self.assertIsNone(cloned_node.GetNodeReferenceID("storage"))
        self.assertEqual(cloned_node.GetNodeReferenceID("volumeRef"), table_node.GetNodeReferenceID("volumeRef"))

    def test_clone_segmentation_node(self):
        # Create a volume node
        volume_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        volume_node.SetName("TestVolume")
        volume_node.SetAttribute("TestAttribute", "TestValue")
        volume_id = volume_node.GetID()

        # Create a segmentation
        segmentation_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        segmentation_node.SetName("TestSegmentation")
        segmentation_node.SetAttribute("TestAttribute", "TestValue")
        segmentation_node.SetNodeReferenceID("storage", "vtkMRMLStorageNode")
        segmentation_node.SetNodeReferenceID("referenceImageGeometryRef", volume_id)

        # Add metadata to the node
        with Metadata(segmentation_node) as meta:
            meta["test_key"] = "test_value"
            meta["test_number"] = 123

        # Set as current selected node
        self._set_current_node(segmentation_node)

        # Trigger the clone action
        self._module_widget.cloneAction.trigger()
        process_events()

        # Get the cloned node
        cloned_node = slicer.util.getNode(f"{segmentation_node.GetName()} Copy")
        self.assertIsNotNone(cloned_node)

        # Verify that the attributes are copied
        self.assertEqual(cloned_node.GetAttribute("TestAttribute"), "TestValue")

        # Verify that the metadata is copied
        cloned_meta = Metadata(cloned_node)
        self.assertEqual(cloned_meta.get("test_key"), "test_value")
        self.assertEqual(cloned_meta.get("test_number"), 123)

        # Verify that the references are copied, except for "storage"
        self.assertIsNone(cloned_node.GetNodeReferenceID("storage"))
        self.assertEqual(
            cloned_node.GetNodeReferenceID("referenceImageGeometryRef"),
            segmentation_node.GetNodeReferenceID("referenceImageGeometryRef"),
        )

    def test_clone_segments(self):
        # Create a volume node
        volume_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        volume_node.SetName("TestVolume")
        volume_node.SetAttribute("TestAttribute", "TestValue")
        volume_id = volume_node.GetID()

        # Create a segmentation
        segmentation_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        segmentation_node.SetName("TestSegmentation")
        segmentation_node.SetAttribute("TestAttribute", "TestValue")
        segmentation_node.SetNodeReferenceID("storage", "vtkMRMLStorageNode")
        segmentation_node.SetNodeReferenceID("referenceImageGeometryRef", volume_id)

        # Add segments to the segmentation node
        for i in range(3):
            segment = slicer.vtkSegment()
            segment.SetName(f"Segment_{i + 1}")
            segmentation_node.GetSegmentation().AddSegment(segment)

        # Set as current selected node
        sh_node = slicer.mrmlScene.GetSubjectHierarchyNode()
        segmentation_item_id = sh_node.GetItemByDataNode(segmentation_node)
        first_segment_id = sh_node.GetItemChildWithName(segmentation_item_id, "Segment_1")
        sh_tree = self._module_widget.subjectHierarchyTreeView
        sh_tree.setCurrentItem(first_segment_id)

        # Trigger the clone action
        segmentCloneAction = [
            action
            for action in self._module_widget.nodeMenu.actions()
            if action.text == "Clone" and isinstance(action.parent(), slicer.qSlicerSubjectHierarchySegmentsPlugin)
        ][0]
        segmentCloneAction.trigger()
        process_events()

        # Verify if first segment is cloned
        self.assertIsNotNone(segmentation_node)
        self.assertEqual(segmentation_node.GetSegmentation().GetNumberOfSegments(), 4)
        self.assertEqual(segmentation_node.GetSegmentation().GetNthSegment(0).GetName(), "Segment_1")
        self.assertEqual(segmentation_node.GetSegmentation().GetNthSegment(1).GetName(), "Segment_1")
        self.assertEqual(segmentation_node.GetSegmentation().GetNthSegment(2).GetName(), "Segment_2")
        self.assertEqual(segmentation_node.GetSegmentation().GetNthSegment(3).GetName(), "Segment_3")

    def test_clone_scalar_volume_node(self):
        # Create a volume node
        volume_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        volume_node.SetName("TestVolume")
        volume_node.SetAttribute("TestAttribute", "TestValue")
        slicer.util.updateVolumeFromArray(volume_node, np.zeros((10, 10, 10)))

        # Add metadata to the node
        with Metadata(volume_node) as meta:
            meta["test_key"] = "test_value"
            meta["test_number"] = 123

        # Set as current selected node
        self._set_current_node(volume_node)

        # Trigger the clone action
        self._module_widget.cloneAction.trigger()
        process_events()

        # Get the cloned node
        cloned_node = slicer.util.getNode(f"{volume_node.GetName()} Copy")
        self.assertIsNotNone(cloned_node)

        # Verify that the attributes are copied
        self.assertEqual(cloned_node.GetAttribute("TestAttribute"), "TestValue")

        # Verify that the metadata is copied
        cloned_meta = Metadata(cloned_node)
        self.assertEqual(cloned_meta.get("test_key"), "test_value")
        self.assertEqual(cloned_meta.get("test_number"), 123)

    def test_clone_folder(self):
        # Create a folder
        sh_node = slicer.mrmlScene.GetSubjectHierarchyNode()
        folder_name = "TestFolder"
        folder_id = sh_node.CreateFolderItem(sh_node.GetSceneItemID(), folder_name)

        # Set as current selected node
        sh_tree = self._module_widget.subjectHierarchyTreeView
        sh_tree.setCurrentItem(folder_id)

        # Trigger the clone action
        self._module_widget.cloneAction.trigger()
        process_events()

        # Get the cloned folder by its expected name
        cloned_folder_name = f"{folder_name} Copy"
        cloned_folder_id = sh_node.GetItemByName(cloned_folder_name)

        self.assertNotEqual(cloned_folder_id, 0)

    def test_opacity_slider_does_not_crash_when_display_node_modified_without_3d_show(self):
        # Regression test: onOverallOpacityChanged used to raise AttributeError because a
        # display node modification event, while the 3D Show feature was disabled, incorrectly
        # triggered a cleanup that cleared the observed segmentation node reference.
        segmentation_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        segmentation_node.SetName("TestSegmentationOpacity")
        segmentation_node.CreateDefaultDisplayNodes()

        segment = slicer.vtkSegment()
        segment.SetName("Segment_1")
        segmentation_node.GetSegmentation().AddSegment(segment)

        self._set_current_node(segmentation_node)
        process_events()

        widget = self._module_widget.segmentationWidget
        self.assertTrue(widget.visible)

        # The 3D Show feature must be disabled by default
        self.assertFalse(widget.show3DButton._model.show)

        # Simulate a display node modification event, as happens e.g. when segment
        # visibility/color/opacity changes, while 3D Show is still disabled.
        segmentation_node.GetDisplayNode().Modified()
        wait(0.5)

        # The segmentation node reference must remain valid. Before the fix, the modification
        # event handler would incorrectly clean up the observed node reference here.
        self.assertIsNotNone(widget.show3DButton.segmentationNode())

        # Changing the opacity slider must not raise, even after the display node event above.
        widget.opacitySlider.value = 0.75
        process_events()

        self.assertAlmostEqual(segmentation_node.GetDisplayNode().GetOpacity(), 0.75)

    def test_opacity_slider_updates_show_3d_label_opacities(self):
        # Integration test: changing the overall opacity slider in the Segmentation widget
        # must propagate to the per-label opacities of the cloned label map volume used by
        # the "Show 3D" feature, so the 3D rendering stays in sync with the slider value.
        volume_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        slicer.util.updateVolumeFromArray(volume_node, np.zeros((20, 20, 20)))

        label_array = np.zeros((20, 20, 20), dtype=np.uint16)
        label_array[:10] = 1
        label_map_node = slicer.util.addVolumeFromArray(
            label_array, name="TestOpacitySyncLabelMap", nodeClassName="vtkMRMLLabelMapVolumeNode"
        )

        segmentation_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        segmentation_node.SetName("TestSegmentationOpacitySync")
        segmentation_node.CreateDefaultDisplayNodes()
        segmentation_node.GetDisplayNode().SetOpacity(1.0)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(label_map_node, segmentation_node)
        helpers.setSourceVolume(segmentation_node, volume_node)
        slicer.mrmlScene.RemoveNode(label_map_node)

        segment_name = segmentation_node.GetSegmentation().GetNthSegment(0).GetName()

        self._set_current_node(segmentation_node)
        process_events()

        widget = self._module_widget.segmentationWidget
        self.assertTrue(widget.visible)

        # Enable the "Show 3D" feature so the cloned label map volume is created
        widget.show3DButton.click()
        process_events()
        self.assertTrue(widget.show3DButton._model.show)

        labelMapNode = widget.show3DButton._model.labelMapVolume
        self.assertIsNotNone(labelMapNode)

        colorTableBefore = helpers.getColorTableForLabels(labelMapNode=labelMapNode)
        opacitiesBefore = {v["name"]: v["color"][3] for v in colorTableBefore.values() if v.get("name")}
        self.assertAlmostEqual(opacitiesBefore.get(segment_name), 1.0, delta=0.01)

        # Move the opacity slider and check that it propagates to the label map's color table
        widget.opacitySlider.value = 0.4
        process_events()
        wait(1)

        colorTableAfter = helpers.getColorTableForLabels(labelMapNode=labelMapNode)
        opacitiesAfter = {v["name"]: v["color"][3] for v in colorTableAfter.values() if v.get("name")}
        self.assertAlmostEqual(opacitiesAfter.get(segment_name), 0.4, delta=0.01)

        widget.show3DButton.click()
        process_events()
        wait(0.5)
        self.assertFalse(widget.show3DButton._model.show)

    def _common_test_proportions(self, expected_props, node_name, roi_name=None):
        load_project(PROPS_TEST_PATH)
        node = slicer.util.getNode(node_name)
        roi_node = slicer.util.getNode(roi_name) if roi_name else None

        self._set_current_node(node)
        process_events()

        if node.IsA("vtkMRMLLabelMapVolumeNode"):
            widget = self._module_widget.labelMapWidget
        elif node.IsA("vtkMRMLSegmentationNode"):
            widget = self._module_widget.segmentationWidget
            expected_props = {node.GetSegmentation().GetNthSegmentID(i - 1): prop for i, prop in expected_props.items()}

        prop_widget = widget.propsSection.propList

        prop_widget.roiSelector.setCurrentNode(roi_node)

        prop_widget.updateButton.click()
        process_events()

        list_widget = prop_widget.segmentList
        props = getattr(list_widget, f"_{list_widget.__class__.__name__}__props")

        self.assertEqual(props, expected_props)

    def test_proportions_labelmap(self):
        self._common_test_proportions({1: 0.04, 4: 0.06}, "Segmentation-label")

    def test_proportions_labelmap_with_roi(self):
        self._common_test_proportions({4: 1.0}, "Segmentation-label", "SOI")

    def test_proportions_segmentation(self):
        self._common_test_proportions({1: 0.04, 2: 0.03, 3: 0.03, 4: 0.06}, "Segmentation")

    def test_proportions_segmentation_with_roi(self):
        self._common_test_proportions({2: 0.4, 3: 0.6, 4: 1.0}, "Segmentation", "SOI")

    def test_info_and_attributes_tabs(self):
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        slicer.util.updateVolumeFromArray(volume, np.zeros((10, 10, 10)))

        with Metadata(volume) as meta:
            meta["InfoTabTest"] = "Success"

        self._set_current_node(volume)

        # Check if tabs are visible
        self.assertTrue(self._module_widget.tabWidget.visible)

        # Check Info tab (Index 0)
        self.assertEqual(self._module_widget.tabWidget.tabText(0), "Info")
        self.assertTrue(self._module_widget.scalarVolumeWidget.visible)

        # Check Attributes tab (Index 1)
        self.assertEqual(self._module_widget.tabWidget.tabText(1), "Attributes")
        attributes_text = self._module_widget.attributesWidget.textEdit.toPlainText()
        self.assertIn("InfoTabTest", attributes_text)
        self.assertIn("Success", attributes_text)

    def test_attributes_tab_shows_dataset_attributes(self):
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        dataset_folder = sh.CreateFolderItem(sh.GetSceneItemID(), "Dataset")
        sh.SetItemAttribute(dataset_folder, "netcdf_path", "C:/dataset.nc")
        metadata.set_item_metadata(dataset_folder, {"DatasetAttr": "FromFolder"})

        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Volume")
        slicer.util.updateVolumeFromArray(volume, np.zeros((10, 10, 10)))
        with Metadata(volume) as meta:
            meta["NodeAttr"] = "FromNode"
        sh.SetItemParent(sh.GetItemByDataNode(volume), dataset_folder)

        self._set_current_node(volume)
        attributes_text = self._module_widget.attributesWidget.textEdit.toPlainText()
        self.assertIn("# Volume", attributes_text)
        self.assertIn("NodeAttr", attributes_text)
        self.assertIn("# Dataset (Dataset)", attributes_text)
        self.assertIn("DatasetAttr", attributes_text)

        # Export would no longer include the dataset attributes, so the tab shouldn't either
        sh.SetItemParent(sh.GetItemByDataNode(volume), sh.GetSceneItemID())
        self._set_current_node(volume)
        self._module_widget.currentItemChanged(None)
        attributes_text = self._module_widget.attributesWidget.textEdit.toPlainText()
        self.assertIn("NodeAttr", attributes_text)
        self.assertNotIn("DatasetAttr", attributes_text)
        self.assertNotIn("# Volume", attributes_text)

    @staticmethod
    def _addCubeVolume(origin, spacing=1.0, className="vtkMRMLScalarVolumeNode"):
        volume = slicer.mrmlScene.AddNewNodeByClass(className)
        slicer.util.updateVolumeFromArray(volume, np.zeros((50, 50, 50), dtype=np.uint8))
        volume.SetOrigin(origin)
        volume.SetSpacing(spacing, spacing, spacing)
        return volume

    def test_show_volume_from_explorer_fits_only_offscreen_slice_views(self):
        treeView = self._module_widget.subjectHierarchyTreeView
        sliceWidgets = [slicer.app.layoutManager().sliceWidget(name) for name in ("Red", "Yellow", "Green")]

        first = self._addCubeVolume((0, 0, 0))
        overlapping = self._addCubeVolume((0, 0, 0))
        far = self._addCubeVolume((10000, 10000, 10000))
        # 0.5 mm wide, centered in the 50 mm wide far volume
        tiny = self._addCubeVolume((10024.75, 10024.75, 10024.75), spacing=0.01)
        farLabelmap = self._addCubeVolume((-10000, -10000, -10000), className="vtkMRMLLabelMapVolumeNode")

        clickSubjectHierarchyVisibility(treeView, first)
        zoomedFovs = []
        for sliceWidget in sliceWidgets:
            sliceWidget.sliceLogic().FitSliceToBackground()
            sliceNode = sliceWidget.mrmlSliceNode()
            width, height, depth = sliceNode.GetFieldOfView()
            sliceNode.SetFieldOfView(width / 4, height / 4, depth)
            zoomedFovs.append(sliceNode.GetFieldOfView())

        # The views are zoomed into a region the new volume covers, so the zoom is kept
        clickSubjectHierarchyVisibility(treeView, overlapping)
        for sliceWidget, zoomedFov in zip(sliceWidgets, zoomedFovs):
            self.assertEqual(sliceWidget.mrmlSliceCompositeNode().GetBackgroundVolumeID(), overlapping.GetID())
            self.assertEqual(sliceWidget.mrmlSliceNode().GetFieldOfView(), zoomedFov)

        # The new volume is far from every view, so they are fit to show it
        clickSubjectHierarchyVisibility(treeView, far)
        for sliceWidget in sliceWidgets:
            self.assertEqual(sliceWidget.mrmlSliceCompositeNode().GetBackgroundVolumeID(), far.GetID())
            self.assertGreaterEqual(sliceViewVolumeFractions(sliceWidget.mrmlSliceNode(), far).overlap, 0.5)

        # The new volume is fully inside every view but would be a speck, so they are fit to show it
        clickSubjectHierarchyVisibility(treeView, tiny)
        for sliceWidget in sliceWidgets:
            self.assertEqual(sliceWidget.mrmlSliceCompositeNode().GetBackgroundVolumeID(), tiny.GetID())
            self.assertGreaterEqual(sliceViewVolumeFractions(sliceWidget.mrmlSliceNode(), tiny).coverage, 0.5)

        # A labelmap goes to the label layer, and the views are fit to it rather than to the background
        clickSubjectHierarchyVisibility(treeView, farLabelmap)
        for sliceWidget in sliceWidgets:
            compositeNode = sliceWidget.mrmlSliceCompositeNode()
            self.assertEqual(compositeNode.GetLabelVolumeID(), farLabelmap.GetID())
            self.assertEqual(compositeNode.GetBackgroundVolumeID(), tiny.GetID())
            self.assertGreaterEqual(sliceViewVolumeFractions(sliceWidget.mrmlSliceNode(), farLabelmap).overlap, 0.5)

    def test_show_volume_from_explorer_keeps_slice_orientation(self):
        treeView = self._module_widget.subjectHierarchyTreeView
        sliceWidgets = [slicer.app.layoutManager().sliceWidget(name) for name in ("Red", "Yellow", "Green")]
        sliceNodes = [sliceWidget.mrmlSliceNode() for sliceWidget in sliceWidgets]

        # Oblique to every slice view, so Slicer would rotate all of them to the volume's planes
        volume = self._addCubeVolume((0, 0, 0))
        rotation = vtk.vtkTransform()
        rotation.RotateX(30)
        rotation.RotateZ(20)
        volume.SetIJKToRASDirectionMatrix(rotation.GetMatrix())

        def sliceRotation(sliceNode):
            sliceToRAS = sliceNode.GetSliceToRAS()
            return [[sliceToRAS.GetElement(row, col) for col in range(3)] for row in range(3)]

        rotationsBefore = [sliceRotation(sliceNode) for sliceNode in sliceNodes]
        clickSubjectHierarchyVisibility(treeView, volume)
        for sliceWidget, rotationBefore in zip(sliceWidgets, rotationsBefore):
            self.assertEqual(sliceWidget.mrmlSliceCompositeNode().GetBackgroundVolumeID(), volume.GetID())
            np.testing.assert_allclose(sliceRotation(sliceWidget.mrmlSliceNode()), rotationBefore, atol=1e-6)
