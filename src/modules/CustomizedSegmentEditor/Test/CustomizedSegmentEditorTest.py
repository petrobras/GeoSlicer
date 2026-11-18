import numpy as np
import slicer
import qt
import tempfile
import cv2
import vtk

from pathlib import Path
from commons.slicer import helpers
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import (
    load_project,
    wait,
    process_events,
    check_for_message_box,
)
from unittest.mock import patch


RESOURCES = Path(__file__).parent / "Resources"
BOUNDARY_REMOVAL_PROJECT_FILE = RESOURCES / "BOUNDARY_REMOVAL" / "BOUNDARY_REMOVAL.mrml"
SMALL_VOLUME_EMPTY_SEGMENTATION_PROJECT_FILE = (
    RESOURCES / "small_volume_empty_segmentation" / "small_volume_empty_segmentation.mrml"
)
REDUCED_QEMSCAN_PROJECT_FILE = RESOURCES / "reduced_qemscan" / "reduced_qemscan.mrml"


class CustomizedSegmentEditorTest(LTracePluginTest):
    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        # Input tab
        self.__widgets = {
            "initializeButton": self.find_widget(name="Initialize Button"),
            "boundaryRemovalApplyButton": self.find_widget(name="Boundary Removal Apply Button"),
            "qemscanMaskQEMSCANComboBox": self.find_widget(name="QEMSCAN Mask QEMSCAN ComboBox"),
            "qemscanMaskApplyButton": self.find_widget(name="QEMSCAN Mask Apply Button"),
            "expandSegmentsApplyButton": self.find_widget(name="Expand Segments Apply Button"),
            "SegmentEditorProgressBar": self.find_widget(name="SegmentEditorProgressBar"),
        }

        for objectName, widget in self.__widgets.items():
            assert widget is not None, f"widget related to the objectName '{objectName}' is None!"

    def _selectSourceVolumeNode(self, widget, sourceNode):
        """Select `sourceNode` in the source volume combobox."""
        segmentationNode = widget.segmentationNodeComboBox.currentNode()
        currentReference = helpers.getSourceVolume(segmentationNode) if segmentationNode else None
        hasSegments = segmentationNode is not None and segmentationNode.GetSegmentation().GetNumberOfSegments() > 0
        expectsConfirmation = currentReference is not None and currentReference is not sourceNode and hasSegments

        if expectsConfirmation:
            with check_for_message_box("already references the image", should_accept=True, timeout_sec=5):
                widget.sourceVolumeNodeComboBox.setCurrentNode(sourceNode)
        else:
            widget.sourceVolumeNodeComboBox.setCurrentNode(sourceNode)
        process_events()

    def test_multithreshold_x_range(self):
        load_project(SMALL_VOLUME_EMPTY_SEGMENTATION_PROJECT_FILE)

        widget = self._module_widget
        widget.enter()
        widget.segmentationNodeComboBox.setCurrentNode(slicer.util.getNode("Segmentation"))
        widget.editor.setActiveEffectByName("Multiple Threshold")

        effect = widget.editor.effectByName("Multiple Threshold").self()
        zoom = effect.zoomSlider

        self.assertAlmostEqual(zoom.minimumValue, 5971)
        self.assertAlmostEqual(zoom.maximumValue, 15452.0565)
        self.assertAlmostEqual(zoom.singleStep, 497.01)
        self.assertAlmostEqual(zoom.minimum, 5971)
        self.assertAlmostEqual(zoom.maximum, 56169.01)

        table = effect.table

        # If the table is sized correctly, the horizontal scrollbar should not be visible
        self.assertFalse(table.horizontalScrollBar().isVisible())

    def test_table_thresholds(self):
        load_project(SMALL_VOLUME_EMPTY_SEGMENTATION_PROJECT_FILE)

        widget = self._module_widget
        widget.enter()
        widget.segmentationNodeComboBox.setCurrentNode(slicer.util.getNode("Segmentation"))
        widget.editor.setActiveEffectByName("Multiple Threshold")

        effect = widget.editor.effectByName("Multiple Threshold").self()

        table = effect.table
        # Check that table has three rows and three columns (min, max and proportion)
        self.assertEqual(table.rowCount(), 3)
        self.assertEqual(table.columnCount(), 3)

        er = qt.Qt.EditRole

        def assert_table(*args):
            for i in range(3):
                for j in range(2):
                    expected = args[i][j]
                    got = table.item(i, j).data(er)
                    assert expected == got, f"Table item at ({i}, {j}): expected {expected}, got {got}"

        table.item(0, 0).setData(er, 6000)
        table.item(1, 0).setData(er, 9000)
        table.item(2, 0).setData(er, 10000)
        table.item(2, 1).setData(er, 50000)
        assert_table(
            (6000, 9000),
            (9000, 10000),
            (10000, 50000),
        )

        table.item(0, 1).setData(er, 9500)
        assert_table(
            (6000, 9500),
            (9500, 10000),
            (10000, 50000),
        )

        table.item(0, 0).setData(er, 5000)
        assert_table(
            (5000, 9500),
            (9500, 10000),
            (10000, 50000),
        )

        table.item(0, 1).setData(er, 11000)
        assert_table(
            (5000, 11000),
            (11000, 11000),
            (11000, 50000),
        )

        table.item(2, 1).setData(er, 7000)
        assert_table(
            (5000, 7000),
            (7000, 7000),
            (7000, 7000),
        )

        table.item(1, 1).setData(er, 9000)
        assert_table(
            (5000, 7000),
            (7000, 9000),
            (9000, 9000),
        )

    def test_intensity_mask_isolation(self):
        load_project(SMALL_VOLUME_EMPTY_SEGMENTATION_PROJECT_FILE)

        widget = self._module_widget
        widget.enter()
        widget.segmentationNodeComboBox.setCurrentNode(slicer.util.getNode("Segmentation"))

        effect = widget.editor.effectByName("Paint")

        parameterSetNode = effect.parameterSetNode()
        parameterSetNode.SourceVolumeIntensityMaskOn()
        self.assertTrue(parameterSetNode.GetMasterVolumeIntensityMask())

        effect.selectEffect("Multiple Threshold")
        self.assertFalse(parameterSetNode.GetMasterVolumeIntensityMask())

        effect.selectEffect("Threshold")
        parameterSetNode.SourceVolumeIntensityMaskOn()
        self.assertTrue(parameterSetNode.GetMasterVolumeIntensityMask())

        effect.selectEffect("Multiple Threshold")
        self.assertFalse(parameterSetNode.GetMasterVolumeIntensityMask())

    def test_boundary_removal_initialize_button_behavior(self):
        # Retrieve widgets
        initializeButton = self.__widgets["initializeButton"]
        widget = self._module_widget

        # Load project
        load_project(BOUNDARY_REMOVAL_PROJECT_FILE)

        # Retrieve nodes
        volumeNode = helpers.tryGetNode("Volume")
        segmentationNode = helpers.tryGetNode("Segmentation")

        assert volumeNode is not None
        assert segmentationNode is not None

        # Select the nodes in the interface
        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(volumeNode)

        # Select the boundary removal effect
        widget.editor.setActiveEffectByName("Boundary removal")

        # Assert behavior
        effect = widget.editor.effectByName("Boundary removal").self()
        assert effect.isInitialized is False
        assert helpers.tryGetNode("Volume - Edges") is None
        assert initializeButton.text == "Initialize"

        initializeButton.click()
        wait(0.3)

        assert effect.isInitialized is True
        assert helpers.tryGetNode("Volume - Edges") is not None
        assert initializeButton.text == "Cancel"

        initializeButton.click()
        wait(0.3)

        assert effect.isInitialized is False
        assert helpers.tryGetNode("Volume - Edges") is None
        assert initializeButton.text == "Initialize"

    def test_boundary_removal_initialize_behavior_when_selecting_another_effect(self):
        # Retrieve widgets
        initializeButton = self.__widgets["initializeButton"]
        widget = self._module_widget

        # Load project
        load_project(BOUNDARY_REMOVAL_PROJECT_FILE)

        # Retrieve nodes
        volumeNode = helpers.tryGetNode("Volume")
        segmentationNode = helpers.tryGetNode("Segmentation")

        assert volumeNode is not None
        assert segmentationNode is not None

        # Select the nodes in the interface
        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(volumeNode)

        # Select the boundary removal effect
        widget.editor.setActiveEffectByName("Boundary removal")

        # Assert behavior
        effect = widget.editor.effectByName("Boundary removal").self()
        assert effect.isInitialized is False
        assert helpers.tryGetNode("Volume - Edges") is None
        assert initializeButton.text == "Initialize"

        initializeButton.click()
        wait(0.3)

        assert effect.isInitialized is True
        assert helpers.tryGetNode("Volume - Edges") is not None
        assert initializeButton.text == "Cancel"

        widget.editor.setActiveEffectByName("Paint")
        wait(0.3)

        assert effect.isInitialized is False
        assert helpers.tryGetNode("Volume - Edges") is None
        assert initializeButton.text == "Initialize"

    def test_boundary_removal_initialize_behavior_when_leaving_module(self):
        # Retrieve widgets
        initializeButton = self.__widgets["initializeButton"]
        widget = self._module_widget

        # Load project
        load_project(BOUNDARY_REMOVAL_PROJECT_FILE)

        # Retrieve nodes
        volumeNode = helpers.tryGetNode("Volume")
        segmentationNode = helpers.tryGetNode("Segmentation")

        assert volumeNode is not None
        assert segmentationNode is not None

        # Select the nodes in the interface
        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(volumeNode)

        # Select the boundary removal effect
        widget.editor.setActiveEffectByName("Boundary removal")

        # Assert behavior
        effect = widget.editor.effectByName("Boundary removal").self()
        assert effect.isInitialized is False
        assert helpers.tryGetNode("Volume - Edges") is None
        assert initializeButton.text == "Initialize"

        initializeButton.click()
        wait(0.3)

        assert effect.isInitialized is True
        assert helpers.tryGetNode("Volume - Edges") is not None
        assert initializeButton.text == "Cancel"

        widget.exit()
        wait(0.3)

        assert effect.isInitialized is False
        assert helpers.tryGetNode("Volume - Edges") is None
        assert initializeButton.text == "Initialize"

    def test_boundary_removal_initialize_behavior_when_applying(self):
        # Retrieve widgets
        initializeButton = self.__widgets["initializeButton"]
        applyButton = self.__widgets["boundaryRemovalApplyButton"]
        widget = self._module_widget

        # Load project
        load_project(BOUNDARY_REMOVAL_PROJECT_FILE)

        # Retrieve nodes
        volumeNode = helpers.tryGetNode("Volume")
        segmentationNode = helpers.tryGetNode("Segmentation")

        assert volumeNode is not None
        assert segmentationNode is not None

        # Select the nodes in the interface
        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(volumeNode)

        # Select the boundary removal effect
        widget.editor.setActiveEffectByName("Boundary removal")

        # Assert behavior
        effect = widget.editor.effectByName("Boundary removal").self()
        segmentation = segmentationNode.GetSegmentation()

        assert effect.isInitialized is False
        assert helpers.tryGetNode("Volume - Edges") is None
        assert initializeButton.text == "Initialize"
        self.assertEqual(segmentation.GetSegmentIdBySegmentName("Edges"), "")

        initializeButton.click()
        wait(0.3)

        assert effect.isInitialized is True
        assert helpers.tryGetNode("Volume - Edges") is not None
        assert initializeButton.text == "Cancel"
        self.assertNotEqual(segmentation.GetSegmentIdBySegmentName("Edges"), "")

        applyButton.clicked()
        wait(0.3)

        assert effect.isInitialized is False
        assert helpers.tryGetNode("Volume - Edges") is None
        assert initializeButton.text == "Initialize"
        self.assertEqual(segmentation.GetSegmentIdBySegmentName("Edges"), "")

    def test_smoothing_median_all_visible(self):
        inputArray = np.array(
            [
                [2, 2, 0, 0, 0, 0],
                [2, 3, 0, 0, 0, 0],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 2, 1],
                [0, 0, 1, 1, 3, 0],
                [0, 0, 1, 1, 1, 1],
            ]
        )
        expectedArray = np.array(
            [
                [2, 2, 0, 0, 0, 0],
                [2, 0, 0, 0, 0, 0],
                [0, 0, 0, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
            ]
        )
        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(labelmapNode, inputArray)
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        helpers.setSourceVolume(segmentationNode, labelmapNode)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapNode, segmentationNode)

        widget = self._module_widget
        widget.editor.setActiveEffectByName("Smoothing")
        effect = widget.editor.effectByName("Smoothing").self()

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(labelmapNode)

        effect.methodSelectorComboBox.setCurrentText("Median")
        effect.kernelSizeMMSpinBox.setValue(3)
        effect.applyToAllVisibleSegmentsCheckBox.setChecked(qt.Qt.Checked)
        effect.applyButton.click()

        segmentId = segmentationNode.GetSegmentation().GetNthSegmentID(0)
        segmentationNode.GetSegmentation().CollapseBinaryLabelmaps()
        outputArray = slicer.util.arrayFromSegmentInternalBinaryLabelmap(segmentationNode, segmentId).squeeze()
        np.testing.assert_equal(outputArray, expectedArray, verbose=True)

    def test_smoothing_median_selected_allow_overlap(self):
        inputArray = np.array(
            [
                [2, 2, 0, 0, 0, 0],
                [2, 3, 0, 0, 0, 0],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 2, 1],
                [0, 0, 1, 1, 3, 0],
                [0, 0, 1, 1, 1, 1],
            ]
        )
        expectedArrayLabel1 = np.array(
            [
                [0, 0, 0, 0, 0, 0],
                [0, 0, 0, 0, 0, 0],
                [0, 0, 0, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
            ]
        )
        expectedArrayLabel2 = inputArray == 2

        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(labelmapNode, inputArray)
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        helpers.setSourceVolume(segmentationNode, labelmapNode)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapNode, segmentationNode)

        widget = self._module_widget
        widget.editor.setActiveEffectByName("Smoothing")
        effect = widget.editor.effectByName("Smoothing").self()

        segmentId = segmentationNode.GetSegmentation().GetNthSegmentID(0)

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(labelmapNode)
        widget.editor.setCurrentSegmentID(segmentId)

        effect.methodSelectorComboBox.setCurrentText("Median")
        effect.kernelSizeMMSpinBox.setValue(3)
        effect.applyToAllVisibleSegmentsCheckBox.setChecked(qt.Qt.Unchecked)

        widget.editor.findChild(qt.QComboBox, "OverwriteModeComboBox").setCurrentText("Allow overlap")

        effect.applyButton.click()

        outputArray = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId).squeeze()
        np.testing.assert_equal(outputArray, expectedArrayLabel1, verbose=True)

        segmentId = segmentationNode.GetSegmentation().GetNthSegmentID(1)
        outputArray = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId).squeeze()
        np.testing.assert_equal(outputArray, expectedArrayLabel2, verbose=True)

    def test_smoothing_median_selected(self):
        inputArray = np.array(
            [
                [2, 2, 0, 0, 0, 0],
                [2, 3, 0, 0, 0, 0],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 2, 1],
                [0, 0, 1, 1, 3, 0],
                [0, 0, 1, 1, 1, 1],
            ]
        )
        expectedArray = np.array(
            [
                [2, 2, 0, 0, 0, 0],
                [2, 3, 0, 0, 0, 0],
                [0, 0, 0, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
            ]
        )
        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(labelmapNode, inputArray)
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        helpers.setSourceVolume(segmentationNode, labelmapNode)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapNode, segmentationNode)

        widget = self._module_widget
        widget.editor.setActiveEffectByName("Smoothing")
        effect = widget.editor.effectByName("Smoothing").self()

        segmentId = segmentationNode.GetSegmentation().GetNthSegmentID(0)

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(labelmapNode)
        widget.editor.setCurrentSegmentID(segmentId)

        effect.methodSelectorComboBox.setCurrentText("Median")
        effect.kernelSizeMMSpinBox.setValue(3)
        effect.applyToAllVisibleSegmentsCheckBox.setChecked(qt.Qt.Unchecked)
        effect.applyButton.click()

        outputArray = slicer.util.arrayFromSegmentInternalBinaryLabelmap(segmentationNode, segmentId).squeeze()
        np.testing.assert_equal(outputArray, expectedArray, verbose=True)

    def test_smoothing_fill_holes(self):
        inputArray = np.array(
            [
                [2, 2, 0, 0, 0, 0],
                [2, 3, 0, 0, 0, 0],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 2, 1],
                [0, 0, 1, 1, 3, 0],
                [0, 0, 1, 1, 1, 1],
            ]
        )
        expectedArray = np.array(
            [
                [2, 2, 0, 0, 0, 0],
                [2, 3, 0, 0, 0, 0],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
            ]
        )
        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(labelmapNode, inputArray)
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        helpers.setSourceVolume(segmentationNode, labelmapNode)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapNode, segmentationNode)

        widget = self._module_widget
        widget.editor.setActiveEffectByName("Smoothing")
        effect = widget.editor.effectByName("Smoothing").self()

        segmentId = segmentationNode.GetSegmentation().GetNthSegmentID(0)

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(labelmapNode)
        widget.editor.setCurrentSegmentID(segmentId)

        effect.methodSelectorComboBox.setCurrentText("Fill holes")
        effect.kernelSizeMMSpinBox.setValue(3)
        effect.applyButton.click()

        segmentationNode.GetSegmentation().CollapseBinaryLabelmaps()
        outputArray = slicer.util.arrayFromSegmentInternalBinaryLabelmap(segmentationNode, segmentId).squeeze()
        np.testing.assert_equal(outputArray, expectedArray, verbose=True)

    def test_smoothing_fill_holes_allow_overlap(self):
        inputArray = np.array(
            [
                [2, 2, 0, 0, 0, 0],
                [2, 3, 0, 0, 0, 0],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 2, 1],
                [0, 0, 1, 1, 3, 0],
                [0, 0, 1, 1, 1, 1],
            ]
        )
        expectedArrayLabel1 = np.array(
            [
                [0, 0, 0, 0, 0, 0],
                [0, 0, 0, 0, 0, 0],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
                [0, 0, 1, 1, 1, 1],
            ]
        )
        expectedArrayLabel2 = inputArray == 2

        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(labelmapNode, inputArray)
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        helpers.setSourceVolume(segmentationNode, labelmapNode)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapNode, segmentationNode)

        widget = self._module_widget
        widget.editor.setActiveEffectByName("Smoothing")
        effect = widget.editor.effectByName("Smoothing").self()

        segmentId = segmentationNode.GetSegmentation().GetNthSegmentID(0)

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(labelmapNode)
        widget.editor.setCurrentSegmentID(segmentId)

        effect.methodSelectorComboBox.setCurrentText("Fill holes")
        effect.kernelSizeMMSpinBox.setValue(3)

        widget.editor.findChild(qt.QComboBox, "OverwriteModeComboBox").setCurrentText("Allow overlap")

        effect.applyButton.click()

        outputArray = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId).squeeze()
        np.testing.assert_equal(outputArray, expectedArrayLabel1, verbose=True)

        segmentId = segmentationNode.GetSegmentation().GetNthSegmentID(1)
        outputArray = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId).squeeze()
        np.testing.assert_equal(outputArray, expectedArrayLabel2, verbose=True)

    def _test_qemscan_mask(self, source_node_name, segmentation_node_name, template_node_name):
        load_project(REDUCED_QEMSCAN_PROJECT_FILE)

        widget = self._module_widget
        widget.enter()

        widget.configureEffectsForThinSectionEnvironment()  # Thin Section configuration

        sourceNode = helpers.tryGetNode(source_node_name)
        qemscanNode = helpers.tryGetNode("K_5368_QS - Transformed")
        segmentationNode = helpers.tryGetNode(segmentation_node_name)
        templateSegNode = helpers.tryGetNode(template_node_name)

        assert sourceNode is not None
        assert qemscanNode is not None
        assert segmentationNode is not None
        assert templateSegNode is not None

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(sourceNode)

        widget.editor.setActiveEffectByName("QEMSCAN mask")

        qemscanComboBox = self.__widgets["qemscanMaskQEMSCANComboBox"]
        applyButton = self.__widgets["qemscanMaskApplyButton"]

        assert qemscanComboBox.isEnabled() != sourceNode.IsA(slicer.vtkMRMLLabelMapVolumeNode.__name__)

        if sourceNode is not qemscanNode:
            qemscanComboBox.setCurrentNode(qemscanNode)

        applyButton.clicked()

        resultArray = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, "Segment_1", sourceNode)[0]
        templateArray = slicer.util.arrayFromSegmentBinaryLabelmap(templateSegNode, "Segment_1", sourceNode)[0]

        np.testing.assert_array_almost_equal(resultArray, templateArray)

    def test_qemscan_mask_on_thin_section(self):
        self._test_qemscan_mask(
            source_node_name="K_5368_PP",
            segmentation_node_name="Empty Segmentation PP",
            template_node_name="Template Segmentation PP",
        )

    def test_qemscan_mask_on_qemscan(self):
        self._test_qemscan_mask(
            source_node_name="K_5368_QS - Transformed",
            segmentation_node_name="Empty Segmentation QS",
            template_node_name="Template Segmentation QS",
        )

    def test_color_effects_availability(self):
        def color_effects_visible():
            return all(
                color_effect in widget.editor.effectNameOrder()
                for color_effect in ["Smart foreground", "Color threshold"]
            )

        widget = self._module_widget
        widget.enter()

        widget.configureEffects()  # Micro CT configuration

        assert not color_effects_visible()

        widget.configureEffectsForThinSectionEnvironment()  # Thin Section configuration

        assert color_effects_visible()

        load_project(REDUCED_QEMSCAN_PROJECT_FILE)

        coloredNode = helpers.tryGetNode("K_5368_PP")
        labelmapNode = helpers.tryGetNode("K_5368_QS - Transformed")
        segmentationNode = helpers.tryGetNode("Empty Segmentation PP")
        assert coloredNode is not None
        assert labelmapNode is not None
        assert segmentationNode is not None

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        self._selectSourceVolumeNode(widget, coloredNode)
        assert color_effects_visible()

        self._selectSourceVolumeNode(widget, labelmapNode)
        assert not color_effects_visible()

        self._selectSourceVolumeNode(widget, coloredNode)
        assert color_effects_visible()

    def test_general_effects_availability(self):
        widget = self._module_widget
        widget.enter()

        widget.configureEffects()
        availableEffects = widget.editor.effectNameOrder()
        expectedEffects = [
            "Threshold",
            "Paint",
            "Draw",
            "Erase",
            "Level tracing",
            "Grow from seeds",
            "Fill between slices",
            "Margin",
            "Smoothing",
            "Scissors",
            "Islands",
            "Logical operators",
            "Mask Image",
            "Multiple Threshold",
            "Connectivity",
            "Boundary removal",
            "Expand segments",
            "Sample segmentation",
        ]

        for expectedEffect in expectedEffects:
            assert expectedEffect in availableEffects

    def test_thin_section_effects_availability(self):
        widget = self._module_widget
        widget.enter()

        widget.configureEffectsForThinSectionEnvironment()
        availableEffects = widget.editor.effectNameOrder()
        expectedEffects = [
            "Paint",
            "Draw",
            "Erase",
            "Margin",
            "Smoothing",
            "Scissors",
            "Islands",
            "Logical operators",
            "Mask Image",
            "Connectivity",
            "Level tracing",
            "QEMSCAN mask",
            "Boundary removal",
            "Smart foreground",
            "Color threshold",
        ]

        for expectedEffect in expectedEffects:
            assert expectedEffect in availableEffects, f"Effect '{expectedEffect}' is not available"

    def test_multiple_threshold_applying_kmeans_on_segmentation_changes(self):
        widget = self._module_widget

        # Load project
        load_project(BOUNDARY_REMOVAL_PROJECT_FILE)

        # Retrieve nodes
        volumeNode = helpers.tryGetNode("Volume")
        segmentationNode = helpers.tryGetNode("Segmentation")

        assert volumeNode is not None
        assert segmentationNode is not None

        # Select the nodes in the interface
        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(volumeNode)

        widget.editor.setActiveEffectByName("Multiple Threshold")
        effect = widget.editor.effectByName("Multiple Threshold").self()
        segmentation = segmentationNode.GetSegmentation()

        with patch.object(effect, "applyKmeans") as mockApplyKmeans:
            assert mockApplyKmeans.call_count == 0, f"Expected 0 calls to applyKmeans, got {mockApplyKmeans.call_count}"

            seg1Id = segmentation.AddEmptySegment("Segment_1", "Segment_1")
            wait(1)
            assert mockApplyKmeans.call_count == 1, f"Expected 1 calls to applyKmeans, got {mockApplyKmeans.call_count}"

            seg2Id = segmentation.AddEmptySegment("Segment_2", "Segment_2")
            wait(1)
            assert mockApplyKmeans.call_count == 2, f"Expected 2 calls to applyKmeans, got {mockApplyKmeans.call_count}"

            seg3Id = segmentation.AddEmptySegment("Segment_3", "Segment_3")
            wait(1)
            assert mockApplyKmeans.call_count == 3, f"Expected 3 calls to applyKmeans, got {mockApplyKmeans.call_count}"

            segmentation.RemoveSegment(seg3Id)
            wait(1)
            assert mockApplyKmeans.call_count == 4, f"Expected 4 calls to applyKmeans, got {mockApplyKmeans.call_count}"

            segmentation.RemoveSegment(seg2Id)
            wait(1)
            assert mockApplyKmeans.call_count == 5, f"Expected 5 calls to applyKmeans, got {mockApplyKmeans.call_count}"

            segmentation.RemoveSegment(seg1Id)
            wait(1)
            assert mockApplyKmeans.call_count == 6, f"Expected 6 calls to applyKmeans, got {mockApplyKmeans.call_count}"

            segmentation.RemoveSegment(seg1Id)  # Should not call applyKmeans because the segment is already removed
            wait(1)
            assert mockApplyKmeans.call_count == 6, f"Expected 6 calls to applyKmeans, got {mockApplyKmeans.call_count}"

    def test_expand_segments_effect_behavior_when_segments_are_empty(self):
        load_project(BOUNDARY_REMOVAL_PROJECT_FILE)

        volumeNode = helpers.tryGetNode("Volume")
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        segmentation = segmentationNode.GetSegmentation()
        segmentation.AddEmptySegment("Segment_1", "Segment_1")
        segmentation.AddEmptySegment("Segment_2", "Segment_2")
        segmentation.AddEmptySegment("Segment_3", "Segment_3")

        # Select the nodes in the interface
        widget = self._module_widget
        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(volumeNode)

        process_events()

        # Select the expand segments effect
        widget.editor.setActiveEffectByName("Expand segments")
        effect = widget.editor.effectByName("Expand segments").self()
        assert effect is not None

        with check_for_message_box(
            "Failed to apply the effect. The segmentation node doesn't contain any filled segments."
        ):
            applyButton = self.__widgets["expandSegmentsApplyButton"]
            applyButton.clicked()

        # Assert the label map node created related to the segmentation node is deleted
        labelMapNodes = slicer.util.getNodesByClass("vtkMRMLLabelMapVolumeNode")
        assert len(labelMapNodes) == 0, f"Expected 0 label map nodes, got {len(labelMapNodes)}"

    def test_masking_is_reset_on_effect_change(self):
        load_project(SMALL_VOLUME_EMPTY_SEGMENTATION_PROJECT_FILE)

        widget = self._module_widget
        widget.enter()
        widget.segmentationNodeComboBox.setCurrentNode(slicer.util.getNode("Segmentation"))

        parameterSetNode = widget.parameterSetNode

        # Select Paint effect
        widget.editor.setActiveEffectByName("Paint")

        # Change overwrite and mask modes
        parameterSetNode.SetOverwriteMode(slicer.vtkMRMLSegmentEditorNode.OverwriteNone)
        parameterSetNode.SetMaskMode(slicer.vtkMRMLSegmentEditorNode.OverwriteVisibleSegments)

        self.assertEqual(parameterSetNode.GetOverwriteMode(), slicer.vtkMRMLSegmentEditorNode.OverwriteNone)
        self.assertNotEqual(parameterSetNode.GetMaskMode(), slicer.vtkMRMLSegmentEditorNode.OverwriteAllSegments)

        # Select Draw effect
        widget.editor.setActiveEffectByName("Draw")

        # Check if modes are reset
        self.assertEqual(parameterSetNode.GetOverwriteMode(), slicer.vtkMRMLSegmentEditorNode.OverwriteAllSegments)
        self.assertEqual(parameterSetNode.GetMaskMode(), slicer.vtkMRMLSegmentEditorNode.OverwriteAllSegments)

    def test_effects_being_highlighted_when_selected(self):
        load_project(BOUNDARY_REMOVAL_PROJECT_FILE)

        volumeNode = helpers.tryGetNode("Volume")
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        segmentation = segmentationNode.GetSegmentation()
        segmentation.AddEmptySegment("Segment_1", "Segment_1")

        # Select the nodes in the interface
        widget = self._module_widget
        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(volumeNode)

        process_events()

        # Select the effect by simulating a click in the tool buttons
        editor = widget.editor
        effectGroupBox = [wid for wid in editor.children() if wid.name == "EffectsGroupBox"][0]
        effectToolButtons = effectGroupBox.findChildren(qt.QToolButton)

        assert len(effectToolButtons) > 0

        with tempfile.TemporaryDirectory() as dir:
            dir = Path(dir)
            for effectToolButton in effectToolButtons:
                # Guarantee it is not checked before clicking
                effectToolButton.setChecked(False)
                process_events()
                assert not effectToolButton.isChecked()
                image = effectToolButton.grab()
                uncheckedImageFilePath = dir / f"{effectToolButton.name.lower()}_unchecked.png"
                image.save(uncheckedImageFilePath)

                effectToolButton.click()
                process_events()
                assert effectToolButton.isChecked()
                image = effectToolButton.grab()
                checkedImageFilePath = dir / f"{effectToolButton.name.lower()}_checked.png"
                image.save(checkedImageFilePath)
                process_events()

                img1 = cv2.imread(uncheckedImageFilePath.as_posix())
                img2 = cv2.imread(checkedImageFilePath.as_posix())
                difference = cv2.absdiff(img1, img2)
                assert np.sum(difference) != 0

                wait(0.1)

    def test_boundary_removal_cancel_removes_edges_segment(self):
        # Retrieve widgets
        initializeButton = self.__widgets["initializeButton"]
        widget = self._module_widget

        # Load project
        load_project(BOUNDARY_REMOVAL_PROJECT_FILE)

        # Retrieve nodes
        volumeNode = helpers.tryGetNode("Volume")
        segmentationNode = helpers.tryGetNode("Segmentation")

        self.assertIsNotNone(volumeNode)
        self.assertIsNotNone(segmentationNode)

        # Select the nodes in the interface
        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(volumeNode)

        # Select the boundary removal effect
        widget.editor.setActiveEffectByName("Boundary removal")

        segmentation = segmentationNode.GetSegmentation()

        # Check that "Edges" segment does not exist
        self.assertEqual(segmentation.GetSegmentIdBySegmentName("Edges"), "")

        # Initialize the effect
        initializeButton.click()
        wait(0.3)

        # Check that "Edges" segment exists
        self.assertNotEqual(segmentation.GetSegmentIdBySegmentName("Edges"), "")

        # Cancel the effect
        initializeButton.click()
        wait(0.3)

        # Check that "Edges" segment is removed
        self.assertEqual(segmentation.GetSegmentIdBySegmentName("Edges"), "")

    def test_boundary_removal_progress_bar(self):
        # Retrieve widgets
        initializeButton = self.__widgets["initializeButton"]
        widget = self._module_widget
        progressBar = self.__widgets["SegmentEditorProgressBar"]

        # Load project
        load_project(BOUNDARY_REMOVAL_PROJECT_FILE)

        # Retrieve nodes
        volumeNode = helpers.tryGetNode("Volume")
        segmentationNode = helpers.tryGetNode("Segmentation")

        self.assertIsNotNone(volumeNode)
        self.assertIsNotNone(segmentationNode)

        # Select the nodes in the interface
        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(volumeNode)

        # Select the boundary removal effect
        widget.editor.setActiveEffectByName("Boundary removal")

        # Initial state of global progress bar
        self.assertFalse(progressBar.visible)

        # Track progress values
        progressValues = []

        def onValueChanged(value):
            progressValues.append(value)

        progressBar.valueChanged.connect(onValueChanged)

        # Redirect global progress bar lookup to our local progress bar
        globalWidget = slicer.modules.customizedsegmenteditor.widgetRepresentation().self()
        originalProgressBar = getattr(globalWidget, "progressBar", None)
        globalWidget.progressBar = progressBar

        try:
            # Initialize the effect (triggers GradientMagnitudeImageFilter which reports progress)
            initializeButton.click()
            # Processing happens synchronously but calls processEvents, so by the time click returns, it should be done.

            # Verify progress bar interaction
            self.assertTrue(len(progressValues) > 0, "Progress bar should have emitted valueChanged events")
            self.assertTrue(any(v > 0 for v in progressValues), "Progress bar should have reached values > 0")

        finally:
            progressBar.valueChanged.disconnect(onValueChanged)
            # Restore global progress bar state
            if originalProgressBar is not None:
                globalWidget.progressBar = originalProgressBar
            else:
                del globalWidget.progressBar

        # Final state check
        self.assertFalse(progressBar.visible)

    def test_expand_segments_progress_bar(self):
        # Retrieve widgets
        widget = self._module_widget
        applyButton = self.__widgets["expandSegmentsApplyButton"]
        progressBar = self.__widgets["SegmentEditorProgressBar"]

        # Create a setup where Expand Segments can run
        volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        imageData = vtk.vtkImageData()
        imageData.SetDimensions(20, 20, 20)
        imageData.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        imageData.GetPointData().GetScalars().Fill(0)
        volumeNode.SetAndObserveImageData(imageData)

        # Create labelmap with some data to segment
        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        labelmapNode.CopyOrientation(volumeNode)
        lImageData = vtk.vtkImageData()
        lImageData.SetDimensions(20, 20, 20)
        lImageData.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        lImageData.GetPointData().GetScalars().Fill(0)
        lImageData.SetScalarComponentFromFloat(10, 10, 10, 0, 1)  # Set one pixel to 1
        labelmapNode.SetAndObserveImageData(lImageData)

        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapNode, segmentationNode)

        # Setup widget
        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(volumeNode)

        widget.editor.setActiveEffectByName("Expand segments")

        # Initial state of global progress bar
        self.assertFalse(progressBar.visible)

        # Track progress values
        progressValues = []

        def onValueChanged(value):
            progressValues.append(value)

        progressBar.valueChanged.connect(onValueChanged)

        # Redirect global progress bar lookup to our local progress bar
        globalWidget = slicer.modules.customizedsegmenteditor.widgetRepresentation().self()
        originalProgressBar = getattr(globalWidget, "progressBar", None)
        globalWidget.progressBar = progressBar

        try:
            # Apply the effect
            applyButton.click()

            # Verify progress bar interaction
            self.assertTrue(len(progressValues) > 0, "Progress bar should have emitted valueChanged events")
            self.assertTrue(any(v > 0 for v in progressValues), "Progress bar should have reached values > 0")

        finally:
            progressBar.valueChanged.disconnect(onValueChanged)
            # Restore global progress bar state
            if originalProgressBar is not None:
                globalWidget.progressBar = originalProgressBar
            else:
                del globalWidget.progressBar

        # Final state check
        self.assertFalse(progressBar.visible)

    def test_multithreshold_observer_handling(self):
        load_project(SMALL_VOLUME_EMPTY_SEGMENTATION_PROJECT_FILE)

        widget = self._module_widget
        widget.enter()
        widget.segmentationNodeComboBox.setCurrentNode(slicer.util.getNode("Segmentation"))
        widget.editor.setActiveEffectByName("Multiple Threshold")

        effect = widget.editor.effectByName("Multiple Threshold").self()
        process_events()

        observers = effect._observerHandlers
        assert len(observers) == 4, f"Expected a total of '4' observers. Actual: {len(observers)}"

        effect.applyKmeans()

        process_events()

        effect.applyButton.click()

        wait(1)

        assert len(observers) == 0, f"Expected a total of '0' observers. Actual: {len(observers)}"

    def _create_scalar_volume(self, dimensions, spacing):
        volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        imageData = vtk.vtkImageData()
        imageData.SetDimensions(*dimensions)
        imageData.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        imageData.GetPointData().GetScalars().Fill(0)
        volumeNode.SetAndObserveImageData(imageData)
        volumeNode.SetSpacing(*spacing)
        return volumeNode

    def test_source_volume_reference_syncing(self):
        widget = self._module_widget
        widget.enter()

        volumeA = self._create_scalar_volume((10, 10, 10), (1.0, 1.0, 1.0))
        volumeB = self._create_scalar_volume((20, 20, 20), (0.5, 0.5, 0.5))

        # (has_painted_segments, user_confirms) -> (prompt_expected, reference_after_change)
        scenarios = [
            ("painted + confirmed", True, True, True, volumeB),
            ("painted + cancelled", True, False, True, volumeA),
            ("empty (no prompt)", False, False, False, volumeB),
        ]

        for label, hasSegments, userConfirms, promptExpected, expectedReference in scenarios:
            segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
            helpers.setSourceVolume(segmentationNode, volumeA)
            helpers.rescaleSegmentationGeometry(segmentationNode, volumeA)
            if hasSegments:
                segmentationNode.GetSegmentation().AddEmptySegment("Segment_1", "Segment_1")
            process_events()

            # Selecting the segmentation reflects its reference image in the source combobox.
            widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
            process_events()
            self.assertIs(
                widget.sourceVolumeNodeComboBox.currentNode(), volumeA, f"[{label}] source not synced on selection"
            )

            if promptExpected:
                with check_for_message_box("already references the image", should_accept=userConfirms, timeout_sec=5):
                    widget.sourceVolumeNodeComboBox.setCurrentNode(volumeB)
            else:
                with patch.object(slicer.util, "confirmYesNoDisplay") as mockConfirm:
                    widget.sourceVolumeNodeComboBox.setCurrentNode(volumeB)
                    process_events()
                    mockConfirm.assert_not_called()
            process_events()

            self.assertIs(
                helpers.getSourceVolume(segmentationNode), expectedReference, f"[{label}] wrong reference after change"
            )
            self.assertIs(
                widget.sourceVolumeNodeComboBox.currentNode(),
                expectedReference,
                f"[{label}] combobox not reflecting the resulting reference",
            )

            slicer.mrmlScene.RemoveNode(segmentationNode)

    def test_multithreshold_preview_opacity_control(self):
        load_project(SMALL_VOLUME_EMPTY_SEGMENTATION_PROJECT_FILE)

        widget = self._module_widget
        widget.enter()
        widget.segmentationNodeComboBox.setCurrentNode(slicer.util.getNode("Segmentation"))
        widget.editor.setActiveEffectByName("Multiple Threshold")

        effect = widget.editor.effectByName("Multiple Threshold").self()

        self.assertTrue(effect.enablePulsingCheckbox.isChecked())
        self.assertFalse(effect.opacityRow.isVisible())

        effect.enablePulsingCheckbox.setCheckState(qt.Qt.Unchecked)
        process_events()
        self.assertTrue(effect.opacityRow.isVisible())

        effect.previewOpacitySlider.value = 0.3

        effect.scriptedEffect.optionsFrame().visible = True
        effect.renderedLayout = slicer.app.layoutManager().layout
        segmentationNode = slicer.util.getNode("Segmentation")
        displayNode = segmentationNode.GetDisplayNode()
        for i in range(segmentationNode.GetSegmentation().GetNumberOfSegments()):
            displayNode.SetSegmentVisibility(segmentationNode.GetSegmentation().GetNthSegmentID(i), True)

        effect.setupPreviewDisplay()
        effect.preview()

        pipeline = next(iter(effect.previewPipelines.values()))[0]
        alpha = pipeline.lookupTable.GetTableValue(1)[3]
        self.assertAlmostEqual(alpha, 0.3, delta=0.01)

        effect.enablePulsingCheckbox.setCheckState(qt.Qt.Checked)
        process_events()
        self.assertFalse(effect.opacityRow.isVisible())

    def test_multithreshold_link_endpoints_toggle(self):
        load_project(SMALL_VOLUME_EMPTY_SEGMENTATION_PROJECT_FILE)

        widget = self._module_widget
        widget.enter()
        widget.segmentationNodeComboBox.setCurrentNode(slicer.util.getNode("Segmentation"))
        widget.editor.setActiveEffectByName("Multiple Threshold")

        effect = widget.editor.effectByName("Multiple Threshold").self()
        segmentationNode = slicer.util.getNode("Segmentation")

        self.assertTrue(effect.linkEndpoints)
        self.assertTrue(effect.linkEndpointsButton.isChecked())

        effect.linkEndpointsButton.setChecked(False)
        process_events()
        self.assertFalse(effect.linkEndpoints)
        self.assertEqual(segmentationNode.GetAttribute("MultipleThresholdLinkEndpoints"), "False")

        er = qt.Qt.EditRole
        table = effect.table
        table.item(0, 1).setData(er, 12000)
        # Unlinked: editing one endpoint must not move the neighboring range's start.
        self.assertNotEqual(table.item(1, 0).data(er), 12000)

        effect.linkEndpointsButton.setChecked(True)
        process_events()
        self.assertTrue(effect.linkEndpoints)
        self.assertEqual(segmentationNode.GetAttribute("MultipleThresholdLinkEndpoints"), "True")
        # Re-enabling link mode re-links neighboring endpoints immediately.
        self.assertEqual(table.item(1, 0).data(er), table.item(0, 1).data(er))

        table.item(0, 1).setData(er, 9500)
        self.assertEqual(table.item(1, 0).data(er), 9500)

    def test_multithreshold_cascading_linked_endpoints_multi_hop(self):
        load_project(SMALL_VOLUME_EMPTY_SEGMENTATION_PROJECT_FILE)

        widget = self._module_widget
        widget.enter()
        segmentationNode = slicer.util.getNode("Segmentation")
        segmentation = segmentationNode.GetSegmentation()
        segmentation.AddEmptySegment("Segment_4", "Segment_4")
        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.editor.setActiveEffectByName("Multiple Threshold")

        effect = widget.editor.effectByName("Multiple Threshold").self()
        self.assertTrue(effect.linkEndpoints)

        er = qt.Qt.EditRole
        table = effect.table
        self.assertEqual(table.rowCount(), 4)

        table.item(0, 0).setData(er, 0)
        table.item(0, 1).setData(er, 10)
        table.item(1, 1).setData(er, 20)
        table.item(2, 1).setData(er, 30)
        table.item(3, 1).setData(er, 40)

        def cell(i, j):
            return table.item(i, j).data(er)

        # Push the first cut far enough to cross two downstream ranges at once.
        table.item(0, 1).setData(er, 35)

        self.assertEqual(
            [[cell(i, 0), cell(i, 1)] for i in range(4)],
            [[0, 35], [35, 35], [35, 35], [35, 40]],
        )

    def test_expand_segments_mask_selector_limits_expansion(self):
        shape = (8, 8, 8)

        seedArray = np.zeros(shape, dtype=np.uint8)
        # Must sit inside the mask region (last axis index < 4, see maskArray below), or the
        # pre-existing seed voxel itself would count as "outside the mask".
        seedArray[4, 4, 1] = 1

        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(labelmapNode, seedArray)

        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        helpers.setSourceVolume(segmentationNode, labelmapNode)
        helpers.rescaleSegmentationGeometry(segmentationNode, labelmapNode)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapNode, segmentationNode)

        # Only the first half of the volume (along the last axis) is inside the mask.
        maskArray = np.zeros(shape, dtype=np.uint8)
        maskArray[:, :, :4] = 1

        maskLabelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(maskLabelmapNode, maskArray)

        maskNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        helpers.setSourceVolume(maskNode, maskLabelmapNode)
        helpers.rescaleSegmentationGeometry(maskNode, maskLabelmapNode)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(maskLabelmapNode, maskNode)

        widget = self._module_widget
        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(labelmapNode)
        process_events()

        widget.editor.setActiveEffectByName("Expand segments")
        effect = widget.editor.effectByName("Expand segments").self()
        effect.maskSelector.setCurrentNode(maskNode)

        applyButton = self.__widgets["expandSegmentsApplyButton"]
        applyButton.clicked()
        wait(1)

        resultLabelMap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
            segmentationNode, resultLabelMap, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
        )
        resultArray = slicer.util.arrayFromVolume(resultLabelMap)

        outsideMask = maskArray == 0
        self.assertTrue(
            np.all(resultArray[outsideMask] == 0), "voxels outside the mask must not be assigned to any segment"
        )
        self.assertTrue(np.any(resultArray[~outsideMask] != 0), "expansion should still fill voxels inside the mask")

    def test_source_volume_change_no_confirmation_when_node_is_none(self):
        widget = self._module_widget
        widget.enter()

        volumeA = self._create_scalar_volume((10, 10, 10), (1.0, 1.0, 1.0))
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        helpers.setSourceVolume(segmentationNode, volumeA)
        helpers.rescaleSegmentationGeometry(segmentationNode, volumeA)
        segmentationNode.GetSegmentation().AddEmptySegment("Segment_1", "Segment_1")

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        process_events()

        with patch.object(slicer.util, "confirmYesNoDisplay") as mockConfirm:
            widget.onSourceVolumeNodeChanged(None)
            process_events()
            mockConfirm.assert_not_called()

        self.assertIs(helpers.getSourceVolume(segmentationNode), volumeA)

    def test_source_volume_change_no_confirmation_when_no_segmentation_selected(self):
        widget = self._module_widget
        widget.enter()

        widget.segmentationNodeComboBox.setCurrentNode(None)
        process_events()

        volumeA = self._create_scalar_volume((10, 10, 10), (1.0, 1.0, 1.0))

        with patch.object(slicer.util, "confirmYesNoDisplay") as mockConfirm:
            widget.sourceVolumeNodeComboBox.setCurrentNode(volumeA)
            process_events()
            mockConfirm.assert_not_called()

    def test_source_volume_change_no_confirmation_when_reference_unchanged(self):
        widget = self._module_widget
        widget.enter()

        volumeA = self._create_scalar_volume((10, 10, 10), (1.0, 1.0, 1.0))
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        helpers.setSourceVolume(segmentationNode, volumeA)
        helpers.rescaleSegmentationGeometry(segmentationNode, volumeA)
        segmentationNode.GetSegmentation().AddEmptySegment("Segment_1", "Segment_1")

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        process_events()
        self.assertIs(widget.sourceVolumeNodeComboBox.currentNode(), volumeA)

        # Re-selecting the volume that already is the segmentation's reference must be a no-op.
        with patch.object(slicer.util, "confirmYesNoDisplay") as mockConfirm:
            widget.onSourceVolumeNodeChanged(volumeA)
            process_events()
            mockConfirm.assert_not_called()

        self.assertIs(helpers.getSourceVolume(segmentationNode), volumeA)

    def test_source_volume_change_no_confirmation_when_no_prior_reference(self):
        widget = self._module_widget
        widget.enter()

        volumeA = self._create_scalar_volume((10, 10, 10), (1.0, 1.0, 1.0))
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        segmentationNode.GetSegmentation().AddEmptySegment("Segment_1", "Segment_1")
        self.assertIsNone(helpers.getSourceVolume(segmentationNode))

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        process_events()

        # Even with painted segments, a segmentation without a prior reference image must not prompt.
        with patch.object(slicer.util, "confirmYesNoDisplay") as mockConfirm:
            widget.sourceVolumeNodeComboBox.setCurrentNode(volumeA)
            process_events()
            mockConfirm.assert_not_called()

        self.assertIs(helpers.getSourceVolume(segmentationNode), volumeA)

    def test_source_volume_change_no_confirmation_when_segmentation_has_no_segments(self):
        widget = self._module_widget
        widget.enter()

        volumeA = self._create_scalar_volume((10, 10, 10), (1.0, 1.0, 1.0))
        volumeB = self._create_scalar_volume((20, 20, 20), (0.5, 0.5, 0.5))
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        helpers.setSourceVolume(segmentationNode, volumeA)
        helpers.rescaleSegmentationGeometry(segmentationNode, volumeA)
        self.assertEqual(segmentationNode.GetSegmentation().GetNumberOfSegments(), 0)

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        process_events()

        with patch.object(slicer.util, "confirmYesNoDisplay") as mockConfirm:
            widget.sourceVolumeNodeComboBox.setCurrentNode(volumeB)
            process_events()
            mockConfirm.assert_not_called()

        self.assertIs(helpers.getSourceVolume(segmentationNode), volumeB)

    def test_source_volume_change_confirmation_message_and_rescale(self):
        widget = self._module_widget
        widget.enter()

        volumeA = self._create_scalar_volume((10, 10, 10), (1.0, 1.0, 1.0))
        volumeA.SetName("Volume A")
        volumeB = self._create_scalar_volume((20, 20, 20), (0.5, 0.5, 0.5))
        volumeB.SetName("Volume B")
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        segmentationNode.SetName("My Segmentation")
        helpers.setSourceVolume(segmentationNode, volumeA)
        helpers.rescaleSegmentationGeometry(segmentationNode, volumeA)
        segmentationNode.GetSegmentation().AddEmptySegment("Segment_1", "Segment_1")

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        process_events()

        with (
            patch.object(slicer.util, "confirmYesNoDisplay", wraps=slicer.util.confirmYesNoDisplay) as mockConfirm,
            patch.object(helpers, "rescaleSegmentationGeometry") as mockRescale,
        ):
            with check_for_message_box("already references the image", should_accept=True, timeout_sec=5):
                widget.sourceVolumeNodeComboBox.setCurrentNode(volumeB)
            process_events()

            mockConfirm.assert_called_once()
            args, kwargs = mockConfirm.call_args
            message = args[0] if args else kwargs.get("message")
            self.assertIn("My Segmentation", message)
            self.assertIn("Volume A", message)
            self.assertIn("Volume B", message)
            self.assertEqual(kwargs.get("windowTitle"), "Change reference image")

            mockRescale.assert_called_once_with(segmentationNode, volumeB)

        self.assertIs(helpers.getSourceVolume(segmentationNode), volumeB)

    def test_source_volume_change_cancelled_does_not_rescale(self):
        widget = self._module_widget
        widget.enter()

        volumeA = self._create_scalar_volume((10, 10, 10), (1.0, 1.0, 1.0))
        volumeB = self._create_scalar_volume((20, 20, 20), (0.5, 0.5, 0.5))
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        helpers.setSourceVolume(segmentationNode, volumeA)
        helpers.rescaleSegmentationGeometry(segmentationNode, volumeA)
        segmentationNode.GetSegmentation().AddEmptySegment("Segment_1", "Segment_1")

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        process_events()

        with patch.object(helpers, "rescaleSegmentationGeometry") as mockRescale:
            with check_for_message_box("already references the image", should_accept=False, timeout_sec=5):
                widget.sourceVolumeNodeComboBox.setCurrentNode(volumeB)
            process_events()

            mockRescale.assert_not_called()

        self.assertIs(helpers.getSourceVolume(segmentationNode), volumeA)
        self.assertIs(widget.sourceVolumeNodeComboBox.currentNode(), volumeA)

    def test_source_volume_change_no_confirmation_when_syncing_from_segmentation_selection(self):
        widget = self._module_widget
        widget.enter()

        volumeA = self._create_scalar_volume((10, 10, 10), (1.0, 1.0, 1.0))
        volumeB = self._create_scalar_volume((20, 20, 20), (0.5, 0.5, 0.5))

        segmentationA = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        helpers.setSourceVolume(segmentationA, volumeA)
        helpers.rescaleSegmentationGeometry(segmentationA, volumeA)
        segmentationA.GetSegmentation().AddEmptySegment("Segment_1", "Segment_1")

        segmentationB = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        helpers.setSourceVolume(segmentationB, volumeB)
        helpers.rescaleSegmentationGeometry(segmentationB, volumeB)
        segmentationB.GetSegmentation().AddEmptySegment("Segment_1", "Segment_1")

        widget.segmentationNodeComboBox.setCurrentNode(segmentationA)
        process_events()
        self.assertIs(widget.sourceVolumeNodeComboBox.currentNode(), volumeA)

        # Switching the segmentation (not the source volume combobox) must silently sync the
        # source volume combobox without ever triggering the reference-change confirmation,
        # even though both segmentations have painted segments and different references.
        with patch.object(slicer.util, "confirmYesNoDisplay") as mockConfirm:
            widget.segmentationNodeComboBox.setCurrentNode(segmentationB)
            process_events()
            mockConfirm.assert_not_called()

        self.assertIs(widget.sourceVolumeNodeComboBox.currentNode(), volumeB)
        self.assertIs(helpers.getSourceVolume(segmentationA), volumeA)
        self.assertIs(helpers.getSourceVolume(segmentationB), volumeB)
