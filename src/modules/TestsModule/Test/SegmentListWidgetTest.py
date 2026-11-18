import qt
import slicer

from commons.slicer.widget.combined_inputs import SegmentListWidget
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, wait
from pathlib import Path

VOLUME_PROJECT_PATH = Path(__file__).parent / "Resources" / "Volume" / "Volume.mrml"
RAW_DATA_PROJECT_PATH = Path(__file__).parent / "Resources" / "RawData" / "RawData.mrml"


class SegmentListWidgetTest(LTracePluginTest):
    def post_setup(self) -> None:
        self.widget = SegmentListWidget(parent=self._module_widget.parent)
        self.widget.show()

    def tear_down(self):
        self.widget._clearNodeObservers()
        self.widget.deleteLater()

    def test_segment_list_widget_init(self):
        self.assertIsNotNone(self.widget)
        self.assertFalse(self.widget.checkable)
        self.assertEqual(self.widget.defaultState, qt.Qt.Unchecked)

    def test_set_checkable(self):
        self.widget.setCheckable(True)
        self.assertTrue(self.widget.checkable)
        self.widget.setCheckable(False)
        self.assertFalse(self.widget.checkable)

    def test_set_default_state(self):
        self.widget.setDefaultState(qt.Qt.Checked)
        self.assertEqual(self.widget.defaultState, qt.Qt.Checked)
        self.widget.setDefaultState(qt.Qt.Unchecked)
        self.assertEqual(self.widget.defaultState, qt.Qt.Unchecked)

    def test_create_and_new_item(self):
        self.widget.setCheckable(True)
        self.widget.newItem("Segment 1", (1, 0, 0, 1), "ID1", qt.Qt.Checked)
        self.assertEqual(self.widget.count, 1)
        item = self.widget.item(0)
        self.assertEqual(item.text(), "Segment 1")
        self.assertEqual(item.data(qt.Qt.UserRole), "ID1")
        self.assertEqual(item.checkState(), qt.Qt.Checked)

    def test_get_checked_items(self):
        self.widget.setCheckable(True)
        self.widget.newItem("Segment 1", (1, 0, 0, 1), "ID1", qt.Qt.Checked)
        self.widget.newItem("Segment 2", (0, 1, 0, 1), "ID2", qt.Qt.Unchecked)
        self.widget.newItem("Segment 3", (0, 0, 1, 1), "ID3", qt.Qt.Checked)

        checked_items = self.widget.getCheckedItems()
        self.assertEqual(len(checked_items), 2)
        self.assertIn("ID1", checked_items)
        self.assertIn("ID3", checked_items)

    def test_set_node_segmentation(self):
        load_project(VOLUME_PROJECT_PATH)
        segmentationNode = slicer.util.getNode("Segmentation")

        self.widget.setNode(segmentationNode)

        self.assertEqual(self.widget.count, 4)
        self.assertEqual(self.widget.item(0).text(), "Segment_1")
        self.assertEqual(self.widget.item(1).text(), "Segment_2")
        self.assertEqual(self.widget.item(2).text(), "Segment_3")
        self.assertEqual(self.widget.item(3).text(), "capillary")

    def test_set_node_labelmap(self):
        load_project(VOLUME_PROJECT_PATH)
        labelMapVolumeNode = slicer.util.getNode("Segmentation-label")
        self.widget.setHideBackground(False)
        self.widget.setNode(labelMapVolumeNode)

        self.assertEqual(self.widget.count, 5)  # Background + 4 segments
        self.assertEqual(self.widget.item(1).text(), "Segment 1")
        self.assertEqual(self.widget.item(2).text(), "Segment 2")
        self.assertEqual(self.widget.item(3).text(), "Segment 3")
        self.assertEqual(self.widget.item(4).text(), "capillary")

        self.widget.setHideBackground(True)
        wait(0.5)
        self.assertEqual(self.widget.count, 4)
        self.assertEqual(self.widget.item(0).text(), "Segment 1")
        self.assertEqual(self.widget.item(1).text(), "Segment 2")
        self.assertEqual(self.widget.item(2).text(), "Segment 3")
        self.assertEqual(self.widget.item(3).text(), "capillary")

    def test_check_and_set_state(self):
        self.widget.setCheckable(True)
        self.widget.newItem("Segment 1", (1, 0, 0, 1), "id_0", qt.Qt.Unchecked)
        self.widget.newItem("Segment 2", (0, 1, 0, 1), "id_1", qt.Qt.Unchecked)

        self.widget.check(0)
        self.assertEqual(self.widget.item(0).checkState(), qt.Qt.Checked)

        self.widget.setStateByID("id_1", qt.Qt.Checked)
        self.assertEqual(self.widget.item(1).checkState(), qt.Qt.Checked)

        self.widget.setStateByIndex(1, qt.Qt.Unchecked)
        self.assertEqual(self.widget.item(1).checkState(), qt.Qt.Unchecked)

    def test_modified_segmentation_node(self):
        load_project(VOLUME_PROJECT_PATH)
        segmentationNode = slicer.util.getNode("Segmentation")

        self.widget.setNode(segmentationNode)

        self.assertEqual(self.widget.count, 4)
        self.assertEqual(self.widget.item(0).text(), "Segment_1")
        self.assertEqual(self.widget.item(1).text(), "Segment_2")
        self.assertEqual(self.widget.item(2).text(), "Segment_3")
        self.assertEqual(self.widget.item(3).text(), "capillary")

        segmentation = segmentationNode.GetSegmentation()
        segmentation.GetNthSegment(0).SetName("Segment_1b")
        segmentation.Modified()

        wait(1)

        self.assertEqual(self.widget.item(0).text(), "Segment_1b")

    def test_modified_labelmap_node(self):
        load_project(VOLUME_PROJECT_PATH)
        labelMapVolumeNode = slicer.util.getNode("Segmentation-label")
        self.widget.setHideBackground(False)
        self.widget.setNode(labelMapVolumeNode)

        self.assertEqual(self.widget.count, 5)  # Background + 4 segments
        self.assertEqual(self.widget.item(0).text(), "Background")
        self.assertEqual(self.widget.item(1).text(), "Segment 1")
        self.assertEqual(self.widget.item(2).text(), "Segment 2")
        self.assertEqual(self.widget.item(3).text(), "Segment 3")
        self.assertEqual(self.widget.item(4).text(), "capillary")

        inputColors = labelMapVolumeNode.GetDisplayNode().GetColorNode()
        inputColors.SetColorName(1, "Segment 1 b")
        inputColors.Modified()
        labelMapVolumeNode.Modified()

        self.widget.setHideBackground(True)
        self.assertEqual(self.widget.count, 4)
        self.assertEqual(self.widget.item(0).text(), "Segment 1 b")
        self.assertEqual(self.widget.item(1).text(), "Segment 2")
        self.assertEqual(self.widget.item(2).text(), "Segment 3")
        self.assertEqual(self.widget.item(3).text(), "capillary")

    def test_changing_nodes(self):
        load_project(VOLUME_PROJECT_PATH)
        segmentationNode = slicer.util.getNode("Segmentation")
        labelMapVolumeNode = slicer.util.getNode("Segmentation-label")

        self.widget.setNode(segmentationNode)
        wait(0.5)
        self.assertEqual(self.widget.count, 4)
        self.assertEqual(len(self.widget._SegmentListWidget__nodeObservers), 1)
        self.assertEqual(self.widget._SegmentListWidget__nodeObservers[0].node, segmentationNode)
        self.assertEqual(self.widget.currentNodeId, segmentationNode.GetID())

        self.widget.setNode(labelMapVolumeNode)
        wait(0.5)
        self.assertEqual(self.widget.count, 4)
        self.assertEqual(len(self.widget._SegmentListWidget__nodeObservers), 1)
        self.assertEqual(self.widget._SegmentListWidget__nodeObservers[0].node, labelMapVolumeNode)
        self.assertEqual(self.widget.currentNodeId, labelMapVolumeNode.GetID())

        self.widget.setNode(None)
        wait(0.5)
        self.assertEqual(self.widget.count, 0)
        self.assertEqual(len(self.widget._SegmentListWidget__nodeObservers), 0)
        self.assertEqual(self.widget.currentNodeId, None)

    def test_set_hide_background(self):
        load_project(VOLUME_PROJECT_PATH)
        labelMapVolumeNode = slicer.util.getNode("Segmentation-label")
        self.widget.setHideBackground(True)
        self.widget.setNode(labelMapVolumeNode)
        self.assertEqual(self.widget.count, 4)
        self.assertEqual(self.widget.item(0).text(), "Segment 1")
        self.widget.setHideBackground(False)
        self.widget.setNode(labelMapVolumeNode)
        self.assertEqual(self.widget.count, 5)
        self.assertEqual(self.widget.item(0).text(), "Background")

    def test_label_map_from_raw_data(self):
        load_project(RAW_DATA_PROJECT_PATH)
        labelMapVolumeNode = slicer.util.getNode("LabelMap")
        self.widget.setHideBackground(True)
        self.widget.setNode(labelMapVolumeNode)
        wait(0.5)
        self.assertEqual(self.widget.count, 1)
        self.assertEqual(self.widget.item(0).text(), "Pore")

        self.widget.setHideBackground(False)
        wait(0.5)
        self.assertEqual(self.widget.count, 2)
        self.assertEqual(self.widget.item(0).text(), "Solid")
        self.assertEqual(self.widget.item(1).text(), "Pore")

    def test_segmentation_node_with_not_visible_segments(self):
        load_project(VOLUME_PROJECT_PATH)
        segmentationNode = slicer.util.getNode("Segmentation")
        segmentation = segmentationNode.GetSegmentation()
        displayNode = segmentationNode.GetDisplayNode()
        assert displayNode is not None
        displayNode.SetSegmentVisibility("Segment_1", False)
        displayNode.SetSegmentVisibility("Segment_2", False)
        displayNode.Modified()
        segmentation.Modified()

        self.widget.setNode(segmentationNode)
        wait(0.5)
        self.assertEqual(self.widget.count, 4)
        self.assertEqual(self.widget.item(0).text(), "Segment_1")
        self.assertEqual(self.widget.item(1).text(), "Segment_2")
        self.assertEqual(self.widget.item(2).text(), "Segment_3")
        self.assertEqual(self.widget.item(3).text(), "capillary")

        self.widget.setStateByID("Segment_3", qt.Qt.Checked)
        wait(0.5)
        indexes = self.widget.getCheckedIndexes()
        self.assertEqual(len(indexes), 1)
        self.assertEqual(indexes[0], 2)
