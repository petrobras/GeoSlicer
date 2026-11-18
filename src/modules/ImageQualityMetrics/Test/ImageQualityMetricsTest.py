import numpy as np
import slicer
from scipy import ndimage

from commons.lmath.image_quality_api import CuppingOptions, QualityOptions
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import check_for_message_box, process_events

VOXEL_SIZE_MM = 0.01


class ImageQualityMetricsTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied after reloading the widgets"""
        names = [
            "Apply Button",
            "Volume Selector",
            "Segmentation Selector",
            "SNR Group",
            "SNR Segments List",
            "Cupping Segment Combo",
            "CNR Group",
            "CNR Segment A Combo",
            "CNR Segment B Combo",
            "Cupping Group",
            "MTF Group",
            "MTF Segment A Combo",
            "MTF Segment B Combo",
            "SNR Help Button",
            "CNR Help Button",
            "Cupping Help Button",
            "MTF Help Button",
        ]
        self._widgets = {name: self.find_widget(name) for name in names}
        self._nodes = []

    def tear_down(self):
        for node in self._nodes:
            slicer.mrmlScene.RemoveNode(node)
        table = slicer.mrmlScene.GetFirstNodeByName("Image Quality Metrics")
        if table is not None:
            slicer.mrmlScene.RemoveNode(table)

    def _create_tube(self, size=128, depth=8, radius=40, sigma=1.5, noise=10.0):
        """A blurred bright cylinder in a dark background, with the segments 'Tube' and 'Outside'."""
        y, x = np.mgrid[:size, :size]
        r = np.hypot(y - (size - 1) / 2, x - (size - 1) / 2)
        inside = r <= radius
        image = ndimage.gaussian_filter(inside.astype(float) * 1000.0, sigma)
        image = image + np.random.default_rng(0).normal(0.0, noise, image.shape)
        array = np.repeat(image[None], depth, axis=0).astype(np.float32)

        volume = slicer.util.addVolumeFromArray(array, name="IQM tube")
        volume.SetSpacing(VOXEL_SIZE_MM, VOXEL_SIZE_MM, VOXEL_SIZE_MM)

        segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "IQM segmentation")
        segmentation.SetReferenceImageGeometryParameterFromVolumeNode(volume)
        for name, mask in (("Tube", inside), ("Outside", ~inside)):
            segment_id = segmentation.GetSegmentation().AddEmptySegment(name, name)
            segmentation.GetSegmentation().GetSegment(segment_id).SetName(name)
            full = np.repeat(mask[None], depth, axis=0).astype(np.uint8)
            slicer.util.updateSegmentBinaryLabelmapFromArray(full, segmentation, segment_id, volume)

        self._nodes += [volume, segmentation]
        return volume, segmentation

    def _select(self, volume, segmentation):
        self._widgets["Volume Selector"].setCurrentNode(volume)
        self._widgets["Segmentation Selector"].setCurrentNode(segmentation)
        process_events()

    def _table(self):
        return slicer.mrmlScene.GetFirstNodeByName("Image Quality Metrics")

    def _columns(self, table):
        return [table.GetColumnName(i) for i in range(table.GetNumberOfColumns())]

    def test_default_interface_configuration(self):
        assert self._widgets["Apply Button"] is not None
        assert self._widgets["Apply Button"].enabled
        assert self._widgets["SNR Segments List"].count == 0
        assert self._widgets["CNR Segment A Combo"].count == 0

    def test_every_metric_has_a_help_button_that_works_while_the_metric_is_off(self):
        volume, segmentation = self._create_tube()
        self._select(volume, segmentation)
        for metric in ("SNR", "CNR", "Cupping", "MTF"):
            self._widgets[f"{metric} Group"].setChecked(False)
            button = self._widgets[f"{metric} Help Button"]
            assert button is not None, metric
            assert button.enabled, metric
            assert len(button.message) > 200, metric

    def test_apply_without_volume_should_prompt_message(self):
        with check_for_message_box("Please select an input volume."):
            self._widgets["Apply Button"].clicked()

    def test_apply_without_segmentation_should_prompt_message(self):
        volume, _ = self._create_tube()
        self._widgets["Volume Selector"].setCurrentNode(volume)
        process_events()
        with check_for_message_box("Please select a segmentation."):
            self._widgets["Apply Button"].clicked()

    def test_segment_selectors_follow_the_segmentation(self):
        volume, segmentation = self._create_tube()
        self._select(volume, segmentation)
        assert self._widgets["SNR Segments List"].count == 2
        for name in ("CNR Segment A Combo", "CNR Segment B Combo", "MTF Segment A Combo"):
            assert self._widgets[name].count == 2
        # the cupping also offers "All segments", which comes first and is the default
        assert self._widgets["Cupping Segment Combo"].count == 3
        assert self._widgets["Cupping Segment Combo"].currentIndex == 0
        # SNR and CNR start enabled, the pairs start with the first two segments
        assert self._widgets["SNR Group"].isChecked() and self._widgets["CNR Group"].isChecked()
        assert not self._widgets["Cupping Group"].isChecked() and not self._widgets["MTF Group"].isChecked()
        assert self._widgets["CNR Segment A Combo"].currentIndex == 0
        assert self._widgets["CNR Segment B Combo"].currentIndex == 1

    def test_apply_without_any_metric_should_prompt_message(self):
        volume, segmentation = self._create_tube()
        self._select(volume, segmentation)
        self._widgets["SNR Group"].setChecked(False)
        self._widgets["CNR Group"].setChecked(False)
        with check_for_message_box("Select at least one metric."):
            self._widgets["Apply Button"].clicked()

    def test_cnr_with_the_same_segment_twice_should_prompt_message(self):
        volume, segmentation = self._create_tube()
        self._select(volume, segmentation)
        self._widgets["CNR Segment B Combo"].setCurrentIndex(0)
        process_events()
        with check_for_message_box("The CNR needs two different segments."):
            self._widgets["Apply Button"].clicked()

    def test_one_apply_measures_every_selected_metric(self):
        volume, segmentation = self._create_tube()
        self._select(volume, segmentation)
        self._widgets["Cupping Group"].setChecked(True)
        self._widgets["Cupping Segment Combo"].setCurrentIndex(1)  # Tube
        self._widgets["MTF Group"].setChecked(True)

        self._widgets["Apply Button"].clicked()
        process_events()
        self._widgets["Apply Button"].clicked()
        process_events()

        table = self._table()
        assert table is not None
        assert table.GetNumberOfRows() == 2
        columns = self._columns(table)
        for expected in (
            "SNR [Tube]",
            "SNR [Outside]",
            "CNR",
            "CNR phases",
            "Cupping (%)",
            "Resolvable at 50% (um)",
            "MTF edge",
            "Volume",
        ):
            assert expected in columns, expected
        assert table.GetCellText(0, columns.index("CNR phases")) == "Tube vs Outside"
        assert float(table.GetCellText(0, columns.index("CNR"))) > 5.0
        assert abs(float(table.GetCellText(0, columns.index("Cupping (%)")))) < 3.0
        assert float(table.GetCellText(0, columns.index("Resolvable at 50% (um)"))) > 0.0

    def test_cupping_of_all_segments_measures_the_whole_sample(self):
        volume, segmentation = self._create_tube()
        self._select(volume, segmentation)
        self._widgets["SNR Group"].setChecked(False)
        self._widgets["CNR Group"].setChecked(False)
        self._widgets["Cupping Group"].setChecked(True)

        self._widgets["Apply Button"].clicked()
        process_events()

        table = self._table()
        columns = self._columns(table)
        assert table.GetCellText(0, columns.index("Cupping segment")) == "All segments"
        assert "Cupping (%)" in columns

    def test_unchecked_segments_are_left_out_of_the_snr(self):
        volume, segmentation = self._create_tube()
        self._select(volume, segmentation)
        self._widgets["SNR Segments List"].item(1).setCheckState(0)  # Qt.Unchecked
        self._widgets["CNR Group"].setChecked(False)

        self._widgets["Apply Button"].clicked()
        process_events()

        table = self._table()
        columns = self._columns(table)
        assert "SNR [Tube]" in columns and "SNR [Outside]" not in columns

    def test_logic_measure_with_a_single_segment(self):
        from ImageQualityMetrics import ImageQualityMetricsLogic

        volume, segmentation = self._create_tube()
        segment_id = segmentation.GetSegmentation().GetNthSegmentID(0)
        options = QualityOptions(snr=[segment_id], cupping=CuppingOptions([segment_id]))
        result = ImageQualityMetricsLogic().measure(volume, segmentation, options)

        assert result.warnings == []
        assert "SNR [Tube]" in result.metrics
        assert "CNR" not in result.metrics and "Resolvable at 50% (um)" not in result.metrics
        assert "radial" in result.curves and "mtf" not in result.curves
        assert abs(result.metrics["Cupping (%)"]) < 3.0
