from humanize import naturalsize
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import (
    load_project,
    check_for_message_box,
    process_events,
    save_project,
    close_project,
    showTableInLayout,
)
from commons.slicer.segment_inspector.inspector_files.inspector_report_file import InspectorReportFile
from commons.slicer.segment_inspector.inspector_files.inspector_variables_file import InspectorVariablesFile
from commons.slicer.node_attributes import NodeEnvironment
from commons.slicer import widgets
from commons.slicer.helpers import get_memory_usage
from unittest.mock import patch
from commons.slicer.helpers import make_directory_writable
from commons.slicer.segment_report_navigator import LABELMAP_REPORT_ROLE, REPORT_LABELMAP_ROLE
from commons.slicer.segment_report_picker import SegmentPicker
from .util_inspector import (
    ELLIPSES_PROJECT_FILE,
    ELLIPSES_RAW_PROJECT_FILE,
    populate_widgets,
    common_successful_test_process,
    QEMSCAN_PROJECT_FILE,
    BEREA_PROJECT_FILE,
    SYNTHETIC_STAR_PROJECT_FILE,
    WATERSHED_METHOD_LABEL,
    ISLANDS_METHOD_LABEL,
    MEDIAL_SURFACE_METHOD_LABEL,
    MINERALOGY_METHOD_LABEL,
    BASIC_PETROPHYSICS_METHOD_LABEL,
    BEREA_RAW_PROJECT_FILE,
    QEMSCAN_RAW_PROJECT_FILE,
    THINSEC_PROJECT_FILE,
    VOLUME_FROM_RAW_FILE_PROJECT_PATH,
    VOLUME_FROM_RAW_FILE_RAW_PROJECT_PATH,
    select_segment,
    click_report_row,
    assert_views_frame_label,
    click_segment,
    selected_report_label,
)

from pathlib import Path
import qt
import slicer
import shutil
import time
import tempfile


MEM_DIFF_TOL = 200 * 1024 * 1024  # 150 MB


class SegmentInspectorTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def pre_setup(self):
        self.__envPatcher = patch("commons.slicer.helpers.getCurrentEnvironment", lambda: NodeEnvironment.THIN_SECTION)
        self.__envPatcher.start()

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = dict()
        populate_widgets(self)
        # Create temporary directory to save the project
        self.__temp_dir_path = Path(tempfile.mkdtemp()).resolve()

    def tear_down(self):
        # Delete the temporary directory
        shutil.rmtree(self.__temp_dir_path, onexc=make_directory_writable)
        self.__envPatcher.stop()

    def test_default_single_shot_interface_state(self):
        single_shot_radio_button = self._widgets["single_shot_radio_button"]
        batch_radio_button = self._widgets["batch_radio_button"]
        apply_button = self._widgets["apply_button"]

        self.assertIsNotNone(single_shot_radio_button)
        self.assertIsNotNone(batch_radio_button)

        single_shot_radio_button.setChecked(True)
        self.assertFalse(batch_radio_button.isChecked())
        self.assertTrue(self._module_widget.currentMode == widgets.SingleShotInputWidget.MODE_NAME)
        self.assertFalse(apply_button.enabled)

    def test_default_batch_interface_state(self):
        single_shot_radio_button = self._widgets["single_shot_radio_button"]
        batch_radio_button = self._widgets["batch_radio_button"]
        apply_button = self._widgets["apply_button"]

        self.assertIsNotNone(single_shot_radio_button)
        self.assertIsNotNone(batch_radio_button)

        batch_radio_button.setChecked(True)
        self.assertFalse(single_shot_radio_button.isChecked())
        self.assertTrue(self._module_widget.currentMode == widgets.BatchInputWidget.MODE_NAME)
        self.assertFalse(apply_button.enabled)

    def test_qemscan_single_shot_mineralogy_without_background_with_qemscan_input(
        self,
        generate_test_data=False,
    ):
        # Mineralogy method configuration:
        # Segmentation: QemScan
        # Region: None
        # Image: QemScan
        # Include Background: False
        common_successful_test_process(
            cls=self,
            method=MINERALOGY_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Without_Background",
            include_background=False,
            do_preprocessing=True,
            generate_test_data=generate_test_data,
        )

    def test_qemscan_single_shot_mineralogy_with_background_with_qemscan_input(
        self,
        generate_test_data=False,
    ):
        # Mineralogy method configuration:
        # Segmentation: QemScan
        # Region: None
        # Image: QemScan
        # Include Background: True
        common_successful_test_process(
            cls=self,
            method=MINERALOGY_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_With_Background",
            include_background=True,
            do_preprocessing=True,
            generate_test_data=generate_test_data,
        )

    def test_qemscan_single_shot_basic_petrophysics_with_qemscan_input(
        self,
        generate_test_data=False,
    ):
        # Basic Petrophysics method configuration:
        # Segmentation: QemScan
        # Region: None
        # Image: QemScan
        common_successful_test_process(
            cls=self,
            method=BASIC_PETROPHYSICS_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Basic_Petrophysics",
            do_preprocessing=True,
            generate_test_data=generate_test_data,
        )

    def test_erasing_output_prefix_auto_update_to_default_name(self):
        load_project(QEMSCAN_PROJECT_FILE)

        segmentation_node = slicer.util.getNode("QemScan")
        self.assertIsNotNone(segmentation_node)

        segmentation_combo_box = self._widgets["segmentation_combo_box"]
        segmentation_combo_box.setCurrentNode(segmentation_node)

        output_prefix_line_edit = self._widgets["output_prefix_line_edit"]
        output_prefix_line_edit.setText("")

        # Wait for signals to trigger its callback
        process_events()

        # Check
        self.assertTrue(output_prefix_line_edit.text == "QemScan_Inspector")

    def test_mineralogy_for_memory_leak(self, timeout_ms=50 * 60 * 1000):
        # Same process as 'test_single_shot_mineralogy_without_background_with_qemscan_input' test case
        def process():
            common_successful_test_process(
                cls=self,
                method=MINERALOGY_METHOD_LABEL,
                project_file=QEMSCAN_PROJECT_FILE,
                segmentation_name="QemScan",
                image_name="QemScan",
                template_prefix="QemScan_Template_Without_Background",
                include_background=False,
                do_preprocessing=True,
            )

        memory_use_before = get_memory_usage()

        for _ in range(8):
            # Run process
            process()
            close_project()

        time.sleep(5)
        process_events()
        memory_use_after = get_memory_usage()
        diff_memory_use = memory_use_after - memory_use_before
        assert diff_memory_use <= MEM_DIFF_TOL, (
            f"Memory leak detected! Memory usage:\n  Before: ({naturalsize(memory_use_before)})\n  After: ({naturalsize(memory_use_after)})\n  Diff: ({naturalsize(diff_memory_use)})"
        )

    def test_single_shot_watershed_not_running_without_segment_selection(self):
        slicer.util.loadScene(QEMSCAN_PROJECT_FILE)

        qemscan_node = slicer.util.getNode("QemScan")
        self.assertIsNotNone(qemscan_node)

        # Retrieve widgets of interest
        single_shot_radio_button = self._widgets["single_shot_radio_button"]
        segmentation_combo_box = self._widgets["segmentation_combo_box"]
        image_segments_combo_box = self._widgets["image_segments_combo_box"]
        methods_combo_box = self._widgets["methods_combo_box"]
        apply_button = self._widgets["apply_button"]
        include_background_checkbox = self._widgets["include_background_checkbox"]

        # Configure
        single_shot_radio_button.setChecked(True)
        include_background_checkbox.setChecked(True)
        segmentation_combo_box.setCurrentNode(qemscan_node)  # qMRMLNodeComboBox
        image_segments_combo_box.setCurrentNode(qemscan_node)  # qMRMLNodeComboBox
        methods_combo_box.setCurrentText(WATERSHED_METHOD_LABEL)  # QComboBox

        self.assertTrue(segmentation_combo_box.currentNode() == qemscan_node)
        self.assertTrue(image_segments_combo_box.currentNode() == qemscan_node)
        self.assertTrue(methods_combo_box.currentText == WATERSHED_METHOD_LABEL)
        self.assertTrue(apply_button.enabled)
        self.assertTrue(self._module_widget.currentMode == widgets.SingleShotInputWidget.MODE_NAME)

        message = "Please, select at least one segment by checking the segment box on the segment list."
        with check_for_message_box(message):
            # Used the apply button's callback directly because otherwise, it won't be blockant and it won't be able
            # to recognize the exception throw,
            self._module_widget._onApplyClicked()

    def test_qemscan_single_shot_watershed_with_qemscan_input_without_soi_region_1(
        self,
        generate_test_data=False,
    ):
        # Watershed method configuration:
        # Segmentation: QemScan
        # Region: None
        # Image: QemScan
        # Segments: Calcita (0% a 1% MgO), Calcita (1% a 4% MgO), Calcita (4% a 7% MgO)
        # size filter: 0
        # smooth factor: 0.0054
        # minimum distance: 3
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Watershed_1",
            size_filter_value=0,
            smooth_factor_value=0.0054,
            minimum_distance_value=3,
            segments=[
                "Calcita (0% a 1%MgO)",
                "Calcita (1% a 4%MgO)",
                "Calcita (4% a 7%MgO)",
            ],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_qemscan_single_shot_watershed_with_qemscan_input_without_soi_region_2(
        self,
        generate_test_data=False,
    ):
        # Watershed method configuration:
        # Segmentation: QemScan
        # Region: None
        # Image: QemScan
        # Segments: Calcita (0% a 1% MgO), Calcita (1% a 4% MgO), Calcita (4% a 7% MgO)
        # size filter: 0
        # smooth factor: 0.5
        # minimum distance: 3
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Watershed_2",
            size_filter_value=0,
            smooth_factor_value=0.5,
            minimum_distance_value=3,
            segments=[
                "Calcita (0% a 1%MgO)",
                "Calcita (1% a 4%MgO)",
                "Calcita (4% a 7%MgO)",
            ],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_qemscan_single_shot_watershed_with_qemscan_input_without_soi_region_3(
        self,
        generate_test_data=False,
    ):
        # Watershed method configuration:
        # Segmentation: QemScan
        # Region: None
        # Image: QemScan
        # Segments: Calcita (0% a 1% MgO), Calcita (1% a 4% MgO), Calcita (4% a 7% MgO)
        # size filter: 0
        # smooth factor: 1
        # minimum distance: 3
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Watershed_3",
            size_filter_value=0,
            smooth_factor_value=1,
            minimum_distance_value=3,
            segments=[
                "Calcita (0% a 1%MgO)",
                "Calcita (1% a 4%MgO)",
                "Calcita (4% a 7%MgO)",
            ],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_qemscan_single_shot_watershed_with_qemscan_input_without_soi_region_4(
        self,
        generate_test_data=False,
    ):
        # Watershed method configuration:
        # Segmentation: QemScan
        # Region: None
        # Image: QemScan
        # Segments: Calcita (0% a 1% MgO), Calcita (1% a 4% MgO), Calcita (4% a 7% MgO)
        # size filter: 0
        # smooth factor: 0.0054
        # minimum distance: 10.0
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Watershed_4",
            size_filter_value=0,
            smooth_factor_value=0.0054,
            minimum_distance_value=10,
            segments=[
                "Calcita (0% a 1%MgO)",
                "Calcita (1% a 4%MgO)",
                "Calcita (4% a 7%MgO)",
            ],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_qemscan_single_shot_watershed_with_qemscan_input_without_soi_region_5(
        self,
        generate_test_data=False,
    ):
        # Watershed method configuration:
        # Segmentation: QemScan
        # Region: None
        # Image: QemScan
        # Segments: Calcita (0% a 1% MgO), Calcita (1% a 4% MgO), Calcita (4% a 7% MgO)
        # size filter: 0.5
        # smooth factor: 0.0054
        # minimum distance: 3
        # Orientation Line: None
        # Note: previously used size filter 1 (mm), which only barely let 2 regions through
        # (max_feret ~1.24mm and ~1.77mm in the stored template) - a razor-thin margin that a
        # small upstream numeric drift can push under the threshold, filtering out everything
        # and causing the report node to never be created (see SegmentInspector.py's
        # `if len(output_report_data.index) > 0` guard). Lowered to 0.5 for a safer margin.
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Watershed_5",
            size_filter_value=0.5,
            smooth_factor_value=0.0054,
            minimum_distance_value=3,
            segments=[
                "Calcita (0% a 1%MgO)",
                "Calcita (1% a 4%MgO)",
                "Calcita (4% a 7%MgO)",
            ],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_watershed_for_memory_leak(self, timeout_ms=50 * 60 * 1000):
        # Same process as 'test_single_shot_watershed_with_qemscan_input_without_soi_region_1' test case
        def process():
            common_successful_test_process(
                cls=self,
                method=WATERSHED_METHOD_LABEL,
                project_file=QEMSCAN_PROJECT_FILE,
                segmentation_name="QemScan",
                image_name="QemScan",
                template_prefix="QemScan_Template_Watershed_1",
                size_filter_value=0,
                smooth_factor_value=0.0054,
                minimum_distance_value=3,
                segments=[
                    "Calcita (0% a 1%MgO)",
                    "Calcita (1% a 4%MgO)",
                    "Calcita (4% a 7%MgO)",
                ],
                do_preprocessing=True,
            )

        memory_use_before = get_memory_usage()

        for _ in range(8):
            # Run process
            process()
            close_project()

        time.sleep(5)
        process_events()
        memory_use_after = get_memory_usage()
        diff_memory_use = memory_use_after - memory_use_before
        assert diff_memory_use <= MEM_DIFF_TOL, (
            f"Memory leak detected! Memory usage:\n  Before: ({naturalsize(memory_use_before)})\n  After: ({naturalsize(memory_use_after)})\n  Diff: ({naturalsize(diff_memory_use)})"
        )

    def test_qemscan_single_shot_islands_with_qemscan_input_without_soi_region_1(
        self,
        generate_test_data=False,
    ):
        # Islands method configuration:
        # Segmentation: QemScan
        # Region: None
        # Image: QemScan
        # Segments: Calcita (0% a 1% MgO), Calcita (1% a 4% MgO), Calcita (4% a 7% MgO)
        # size filter: 0
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=ISLANDS_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Islands_1",
            size_filter_value=0,
            segments=[
                "Calcita (0% a 1%MgO)",
                "Calcita (1% a 4%MgO)",
                "Calcita (4% a 7%MgO)",
            ],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_qemscan_single_shot_islands_with_qemscan_input_without_soi_region_2(
        self,
        generate_test_data=False,
    ):
        # Islands method configuration:
        # Segmentation: QemScan
        # Region: None
        # Image: QemScan
        # Segments: Calcita (0% a 1% MgO), Calcita (1% a 4% MgO), Calcita (4% a 7% MgO)
        # size filter: 1
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=ISLANDS_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Islands_2",
            size_filter_value=1,
            segments=[
                "Calcita (0% a 1%MgO)",
                "Calcita (1% a 4%MgO)",
                "Calcita (4% a 7%MgO)",
            ],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_qemscan_single_shot_islands_with_qemscan_input_without_soi_region_3(
        self,
        generate_test_data=False,
    ):
        # Islands method configuration:
        # Segmentation: QemScan
        # Region: None
        # Image: QemScan
        # Segments: Calcita (0% a 1% MgO), Calcita (1% a 4% MgO), Calcita (4% a 7% MgO)
        # size filter: 2
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=ISLANDS_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Islands_3",
            size_filter_value=2,
            segments=[
                "Calcita (0% a 1%MgO)",
                "Calcita (1% a 4%MgO)",
                "Calcita (4% a 7%MgO)",
            ],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_islands_method_for_memory_leak(self, timeout_ms=50 * 60 * 1000):
        # Same process as 'test_single_shot_islands_with_qemscan_input_without_soi_region_1' test case
        def process():
            common_successful_test_process(
                cls=self,
                method=ISLANDS_METHOD_LABEL,
                project_file=QEMSCAN_PROJECT_FILE,
                segmentation_name="QemScan",
                image_name="QemScan",
                template_prefix="QemScan_Template_Islands_1",
                size_filter_value=0,
                segments=[
                    "Calcita (0% a 1%MgO)",
                    "Calcita (1% a 4%MgO)",
                    "Calcita (4% a 7%MgO)",
                ],
                do_preprocessing=True,
            )

        memory_use_before = get_memory_usage()

        for _ in range(4):
            # Run process
            process()
            close_project()

        time.sleep(5)
        process_events()
        memory_use_after = get_memory_usage()
        diff_memory_use = memory_use_after - memory_use_before
        assert diff_memory_use <= MEM_DIFF_TOL, (
            f"Memory leak detected! Memory usage:\n  Before: ({naturalsize(memory_use_before)})\n  After: ({naturalsize(memory_use_after)})\n  Diff: ({naturalsize(diff_memory_use)})"
        )

    def test_berea_single_shot_watershed_with_berea_input_1(self, generate_test_data=False):
        # Watershed method configuration:
        # Segmentation: Berea_Segmentation
        # Region: SOI
        # Image: 0000
        # Segments: Segment_1, Segment_2, Segment_3
        # size filter: 0
        # smooth factor: 0.0847
        # minimum distance: 3
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Watershed_1",
            size_filter_value=0,
            smooth_factor_value=0.0847,
            minimum_distance_value=3,
            segments=["Segment_1", "Segment_2", "Segment_3"],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_berea_single_shot_watershed_with_berea_input_2(self, generate_test_data=False):
        # Watershed method configuration:
        # Segmentation: Berea_Segmentation
        # Region: SOI
        # Image: 0000
        # Segments: Segment_1, Segment_2, Segment_3
        # size filter: 0
        # smooth factor: 0.0847
        # minimum distance: 5
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Watershed_2",
            size_filter_value=0,
            smooth_factor_value=0.0847,
            minimum_distance_value=5,
            segments=["Segment_1", "Segment_2", "Segment_3"],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_berea_single_shot_watershed_with_berea_input_3(self, generate_test_data=False):
        # Watershed method configuration:
        # Segmentation: Berea_Segmentation
        # Region: SOI
        # Image: 0000
        # Segments: Segment_1, Segment_2, Segment_3
        # size filter: 0
        # smooth factor: 0.0847
        # minimum distance: 8
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Watershed_3",
            size_filter_value=0,
            smooth_factor_value=0.0847,
            minimum_distance_value=8,
            segments=["Segment_1", "Segment_2", "Segment_3"],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_berea_single_shot_watershed_with_berea_input_4(self, generate_test_data=False):
        # Watershed method configuration:
        # Segmentation: Berea_Segmentation
        # Region: SOI
        # Image: 0000
        # Segments: Segment_1, Segment_2, Segment_3
        # size filter: 0
        # smooth factor: 1
        # minimum distance: 3
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Watershed_4",
            size_filter_value=0,
            smooth_factor_value=1,
            minimum_distance_value=3,
            segments=["Segment_1", "Segment_2", "Segment_3"],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_berea_single_shot_watershed_with_berea_input_5(self, generate_test_data=False):
        # Watershed method configuration:
        # Segmentation: Berea_Segmentation
        # Region: SOI
        # Image: 0000
        # Segments: Segment_1, Segment_2, Segment_3
        # size filter: 0
        # smooth factor: 2
        # minimum distance: 3
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Watershed_5",
            size_filter_value=0,
            smooth_factor_value=2,
            minimum_distance_value=3,
            segments=["Segment_1", "Segment_2", "Segment_3"],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_berea_single_shot_watershed_with_berea_input_6(self, generate_test_data=False):
        # Watershed method configuration:
        # Segmentation: Berea_Segmentation
        # Region: SOI
        # Image: 0000
        # Segments: Segment_1, Segment_2, Segment_3
        # size filter: 0.0847
        # smooth factor: 0.0847
        # minimum distance: 3
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Watershed_6",
            size_filter_value=0.0847,
            smooth_factor_value=0.0847,
            minimum_distance_value=3,
            segments=["Segment_1", "Segment_2", "Segment_3"],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_berea_single_shot_islands_with_berea_input_1(self, generate_test_data=False):
        # Islands method configuration:
        # Segmentation: Berea_Segmentation
        # Region: SOI
        # Image: 0000
        # Segments: Segment_1, Segment_2, Segment_3
        # size filter: 0
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=ISLANDS_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Islands_1",
            size_filter_value=0,
            segments=["Segment_1", "Segment_2", "Segment_3"],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_berea_single_shot_islands_with_berea_input_2(self, generate_test_data=False):
        # Islands method configuration:
        # Segmentation: Berea_Segmentation
        # Region: SOI
        # Image: 0000
        # Segments: Segment_1, Segment_2, Segment_3
        # size filter: 0.0847
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=ISLANDS_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Islands_2",
            size_filter_value=0.0847,
            segments=["Segment_1", "Segment_2", "Segment_3"],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_berea_single_shot_islands_with_berea_input_3(self, generate_test_data=False):
        # Islands method configuration:
        # Segmentation: Berea_Segmentation
        # Region: SOI
        # Image: 0000
        # Segments: Segment_1, Segment_2, Segment_3
        # size filter: 1
        # Orientation Line: None
        common_successful_test_process(
            cls=self,
            method=ISLANDS_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Islands_3",
            size_filter_value=1,
            segments=["Segment_1", "Segment_2", "Segment_3"],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_qemscan_single_shot_islands_with_centroids(self):
        # Same configuration as test_qemscan_single_shot_islands_with_qemscan_input_without_soi_region_1, with the
        # centroid columns: they are checked against the output labelmap, the other columns against the template
        common_successful_test_process(
            cls=self,
            method=ISLANDS_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Islands_1",
            size_filter_value=0,
            segments=[
                "Calcita (0% a 1%MgO)",
                "Calcita (1% a 4%MgO)",
                "Calcita (4% a 7%MgO)",
            ],
            do_preprocessing=True,
            include_centroid=True,
        )

    def test_berea_single_shot_islands_with_centroids(self):
        # Same configuration as test_berea_single_shot_islands_with_berea_input_1, with the centroid columns
        common_successful_test_process(
            cls=self,
            method=ISLANDS_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Islands_1",
            size_filter_value=0,
            segments=["Segment_1", "Segment_2", "Segment_3"],
            do_preprocessing=True,
            include_centroid=True,
        )

    def test_berea_single_shot_islands_with_principal_axes(self):
        # Same configuration as test_berea_single_shot_islands_with_berea_input_1, with the principal axes columns:
        # they are checked for consistency, the other columns against the template
        common_successful_test_process(
            cls=self,
            method=ISLANDS_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Islands_1",
            size_filter_value=0,
            segments=["Segment_1", "Segment_2", "Segment_3"],
            do_preprocessing=True,
            include_orientation=True,
            include_axis_lengths=True,
        )

    def test_principal_axes_options_are_only_for_3d_images(self):
        reference_combo_box = self._widgets["image_segments_combo_box"]
        methods_combo_box = self._widgets["methods_combo_box"]
        options = (self._widgets["orientation_checkbox"], self._widgets["axis_lengths_checkbox"])
        self._widgets["single_shot_radio_button"].setChecked(True)

        load_project(QEMSCAN_PROJECT_FILE)
        self._widgets["segmentation_combo_box"].setCurrentNode(slicer.util.getNode("QemScan"))
        reference_combo_box.setCurrentNode(slicer.util.getNode("QemScan"))
        process_events()
        self.assertTrue(all(option.isHidden() for option in options), "Hidden for a 2D reference")

        load_project(BEREA_PROJECT_FILE)
        self._widgets["segmentation_combo_box"].setCurrentNode(slicer.util.getNode("Berea_Segmentation"))
        reference_combo_box.setCurrentNode(slicer.util.getNode("0000"))
        process_events()
        self.assertTrue(all(not option.isHidden() for option in options), "Shown for a 3D reference")

        methods_combo_box.setCurrentText(ISLANDS_METHOD_LABEL)
        process_events()
        self.assertTrue(all(option.enabled for option in options))
        methods_combo_box.setCurrentText(MINERALOGY_METHOD_LABEL)
        process_events()
        self.assertTrue(all(not option.enabled for option in options), "No per-segment report for this method")

    def test_clicking_a_report_row_frames_its_segment(self):
        common_successful_test_process(
            cls=self,
            method=ISLANDS_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Islands_1",
            size_filter_value=0,
            segments=["Segment_1", "Segment_2", "Segment_3"],
            do_preprocessing=True,
        )
        self.__assert_report_row_clicks_frame_segments()

    def test_clicking_a_2d_report_row_frames_its_segment(self):
        common_successful_test_process(
            cls=self,
            method=ISLANDS_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Islands_1",
            size_filter_value=0,
            segments=[
                "Calcita (0% a 1%MgO)",
                "Calcita (1% a 4%MgO)",
                "Calcita (4% a 7%MgO)",
            ],
            do_preprocessing=True,
        )
        self.__assert_report_row_clicks_frame_segments()

    def test_pick_mode_shows_3d_segment_data(self):
        common_successful_test_process(
            cls=self,
            method=ISLANDS_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Islands_1",
            size_filter_value=0,
            segments=["Segment_1", "Segment_2", "Segment_3"],
            do_preprocessing=True,
        )
        self.__assert_pick_mode_shows_segment(label=2, expected_columns=("volume", "max_feret", "elongation"))

    def test_pick_mode_shows_2d_segment_data(self):
        common_successful_test_process(
            cls=self,
            method=ISLANDS_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Islands_1",
            size_filter_value=0,
            segments=[
                "Calcita (0% a 1%MgO)",
                "Calcita (1% a 4%MgO)",
                "Calcita (4% a 7%MgO)",
            ],
            do_preprocessing=True,
        )
        self.__assert_pick_mode_shows_segment(label=2, expected_columns=("area", "max_feret", "min_feret"))

    def __assert_pick_mode_shows_segment(self, label, expected_columns):
        output_prefix = str(self._widgets["output_prefix_line_edit"].text).replace("_{type}", "")
        report_node = slicer.util.getNode(f"{output_prefix}_Report")
        label_map_node = slicer.util.getNode(f"{output_prefix}_LabelMap")
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
        slicer.util.setSliceViewerLayers(label=label_map_node)
        process_events()
        interaction_node = slicer.app.applicationLogic().GetInteractionNode()
        picker = SegmentPicker()
        self.assertIsNotNone(picker.action, "The pick button is in the mouse mode toolbar")

        picker.action.trigger()
        process_events()
        try:
            self.assertEqual(interaction_node.GetCurrentInteractionMode(), slicer.vtkMRMLInteractionNode.User)

            click_segment("Red", label_map_node, label)
            tooltip = qt.QToolTip.text()
            self.assertIn(f"Segment {label}", tooltip)
            for column in expected_columns:
                self.assertIn(column, tooltip)

            click_segment("Red", label_map_node, label, ctrl=True)
            self.assertEqual(selected_report_label(report_node), str(label))
        finally:
            if picker.action.checked:
                picker.action.trigger()
                process_events()

        self.assertEqual(interaction_node.GetCurrentInteractionMode(), slicer.vtkMRMLInteractionNode.ViewTransform)

    def __assert_report_row_clicks_frame_segments(self):
        output_prefix = str(self._widgets["output_prefix_line_edit"].text).replace("_{type}", "")
        report_node = slicer.util.getNode(f"{output_prefix}_Report")
        label_map_node = slicer.util.getNode(f"{output_prefix}_LabelMap")
        number_of_segments = report_node.GetNumberOfRows()
        self.assertGreater(number_of_segments, 3)

        # Linked by node references, which survive node ID changes on import
        self.assertEqual(report_node.GetNodeReferenceID(REPORT_LABELMAP_ROLE), label_map_node.GetID())
        self.assertEqual(label_map_node.GetNodeReferenceID(LABELMAP_REPORT_ROLE), report_node.GetID())

        # Slice views. Sorting makes the view's rows differ from the table's: a fresh report has labels 1 to N.
        table_view = showTableInLayout(report_node, slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpTableView)
        table_view.sortByColumn(report_node.GetColumnIndex("label"), qt.Qt.DescendingOrder)
        process_events()

        for label in (number_of_segments - 3, 1):
            click_report_row(table_view, label)
            assert_views_frame_label(label_map_node, label)

        # 3D view
        table_view = showTableInLayout(report_node, slicer.vtkMRMLLayoutNode.SlicerLayout3DTableView)
        click_report_row(table_view, 2)
        assert_views_frame_label(label_map_node, 2)

    def test_single_shot_medial_surface_with_synthetic_star_input(self, generate_test_data=False):
        # Medial surface method configuration:
        # Segmentation: Pores_Synthetic_6
        # Segments: Segment_1
        # smoothe filter sigma: 2
        # number of processes: 4
        common_successful_test_process(
            cls=self,
            method=MEDIAL_SURFACE_METHOD_LABEL,
            project_file=SYNTHETIC_STAR_PROJECT_FILE,
            segmentation_name="Pores_Synthetic_6",
            template_prefix="Pores_Synthetic_6_Inspector",
            do_preprocessing=False,
            smooth_filter_sigma=2,
            num_processes=4,
            segments=["Segment 1"],
            generate_test_data=generate_test_data,
        )

    def test_berea_single_shot_mineralogy_without_background_with_berea_input(
        self,
        generate_test_data=False,
    ):
        # Mineralogy method configuration:
        # Segmentation: Berea_Segmentation
        # Region: SOI
        # Image: 0000
        # Include Background: False
        common_successful_test_process(
            cls=self,
            method=MINERALOGY_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Mineralogy_1",
            include_background=False,
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_berea_single_shot_mineralogy_with_background_with_berea_input(
        self,
        generate_test_data=False,
    ):
        # Mineralogy method configuration:
        # Segmentation: Berea_Segmentation
        # Region: SOI
        # Image: 0000
        # Include Background: True
        common_successful_test_process(
            cls=self,
            method=MINERALOGY_METHOD_LABEL,
            project_file=BEREA_PROJECT_FILE,
            segmentation_name="Berea_Segmentation",
            image_name="0000",
            soi_name="SOI",
            template_prefix="Berea_Segmentation_Template_Mineralogy_2",
            include_background=True,
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_qemscan_single_shot_watershed_generate_throat_analysis(
        self,
        generate_test_data=False,
    ):
        # Watershed method configuration:
        # Segmentation: QemScan
        # Region: None
        # Image: QemScan
        # Segments: Calcita (0% a 1% MgO), Calcita (1% a 4% MgO), Calcita (4% a 7% MgO)
        # size filter: 0
        # smooth factor: 0.0052
        # minimum distance: 5
        # Orientation Line: None
        # Generate Throat Analysis: True
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Watershed_Throat_Analysis",
            segments=[
                "Calcita (0% a 1%MgO)",
                "Calcita (1% a 4%MgO)",
                "Calcita (4% a 7%MgO)",
            ],
            size_filter_value=0,
            smooth_factor_value=0.0052,
            minimum_distance_value=5,
            generate_throat_analysis=True,
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_ellipses_single_shot_watershed_with_orientation_line_vertical(self, generate_test_data=False):
        # Watershed method configuration:
        # Segmentation: Segmentation
        # Region: None
        # Image: elipses_low
        # Orientation line: L_vert
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=ELLIPSES_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="elipses_low",
            template_prefix="Segmentation_Inspector_Template_vert",
            size_filter_value=0,
            orientation_line="L_vert",
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_ellipses_single_shot_watershed_with_orientation_line_45_degree(self, generate_test_data=False):
        # Watershed method configuration:
        # Segmentation: Segmentation
        # Region: None
        # Image: elipses_low
        # Orientation line: L_vert
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=ELLIPSES_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="elipses_low",
            template_prefix="Segmentation_Inspector_Template_45",
            size_filter_value=0,
            orientation_line="L_45",
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_ellipses_single_shot_watershed_with_orientation_line_horizontal(self, generate_test_data=False):
        # Watershed method configuration:
        # Segmentation: Segmentation
        # Region: None
        # Image: elipses_low
        # Orientation line: L_hor
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=ELLIPSES_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="elipses_low",
            template_prefix="Segmentation_Inspector_Template_hor",
            size_filter_value=0,
            orientation_line="L_hor",
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def test_size_filter_defaults_to_3_pixels_from_reference_spacing(self):
        self._widgets["single_shot_radio_button"].setChecked(True)
        load_project(BEREA_PROJECT_FILE)
        self._widgets["segmentation_combo_box"].setCurrentNode(slicer.util.getNode("Berea_Segmentation"))
        image_node = slicer.util.getNode("0000")
        self._widgets["image_segments_combo_box"].setCurrentNode(image_node)
        process_events()

        expected_value = round(min(image_node.GetSpacing()) * 3, 6)
        for size_filter in (self._widgets["watershed_size_filter"], self._widgets["islands_size_filter"]):
            self.assertAlmostEqual(size_filter.value, expected_value, places=6)

    def test_inspector_output_files(self):
        slicer.util.loadScene(QEMSCAN_RAW_PROJECT_FILE)
        self.test_qemscan_single_shot_mineralogy_with_background_with_qemscan_input(generate_test_data=True)
        self.test_qemscan_single_shot_watershed_with_qemscan_input_without_soi_region_1(generate_test_data=True)
        self.test_qemscan_single_shot_islands_with_qemscan_input_without_soi_region_2(generate_test_data=True)

        # Save project to store and access the table nodes files.
        temp_project_file = self.__temp_dir_path / "test" / "test.mrml"
        assert save_project(temp_project_file), "Failed to save temporary project."
        process_events()

        # Retrieve node references
        mineralogy_variables_output_node = slicer.util.getNode("QemScan_Template_With_Background_Variables")
        watershed_report_output_node = slicer.util.getNode("QemScan_Template_Watershed_1_Report")
        watershed_variables_output_node = slicer.util.getNode("QemScan_Template_Watershed_1_Variables")
        island_report_output_node = slicer.util.getNode("QemScan_Template_Islands_2_Report")
        island_variables_output_node = slicer.util.getNode("QemScan_Template_Islands_2_Variables")

        watershed_petrophysics_output_node = slicer.mrmlScene.GetFirstNodeByName(
            "QemScan_Template_Watershed_1_Basic_Petrophysics"
        )
        island_petrophysics_output_node = slicer.mrmlScene.GetFirstNodeByName(
            "QemScan_Template_Islands_2_Basic_Petrophysics"
        )

        # Assert output file class initialization
        def assert_inspector_file(cls, node):
            assert node is not None
            file_path = node.GetStorageNode().GetFileName()
            assert cls(file_path) is not None, f"Invalid inspector output file: {file_path}"

        assert_inspector_file(InspectorVariablesFile, mineralogy_variables_output_node)
        assert_inspector_file(InspectorReportFile, watershed_report_output_node)
        assert_inspector_file(InspectorVariablesFile, watershed_variables_output_node)
        assert_inspector_file(InspectorReportFile, island_report_output_node)
        assert_inspector_file(InspectorVariablesFile, island_variables_output_node)
        self.assertIsNone(watershed_petrophysics_output_node)
        self.assertIsNone(island_petrophysics_output_node)

    def test_segment_selection_interface(self):
        load_project(BEREA_PROJECT_FILE)
        soi_widget = self._widgets["region_soi_combo_box"]
        seg_widget = self._widgets["segmentation_combo_box"]

        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        segmentation_id = sh.GetItemByName("Segmentation")
        segment_id = sh.GetItemByName("Segment_1")

        for widget in (soi_widget, seg_widget):
            # Should be able to select a segmentation
            widget.setCurrentItem(segmentation_id)
            process_events()
            self.assertEqual(widget.currentItem(), segmentation_id)

            # Should not be able to select a segment, instead resetting to the scene id
            widget.setCurrentItem(segment_id)
            process_events()
            self.assertEqual(widget.currentItem(), 0)

    def test_if_segments_selection_covers_entire_image_ask_for_confirmation(self):
        slicer.util.loadScene(THINSEC_PROJECT_FILE)

        seg_node = slicer.util.getNode("Segmentation")
        self.assertIsNotNone(seg_node)

        # Retrieve widgets of interest
        single_shot_radio_button = self._widgets["single_shot_radio_button"]
        segmentation_combo_box = self._widgets["segmentation_combo_box"]
        image_segments_combo_box = self._widgets["image_segments_combo_box"]
        region_soi_combo_box = self._widgets["region_soi_combo_box"]
        methods_combo_box = self._widgets["methods_combo_box"]
        apply_button = self._widgets["apply_button"]
        segment_list = self._widgets["segment_list"]

        # Configure
        single_shot_radio_button.setChecked(True)
        segmentation_combo_box.setCurrentNode(seg_node)

        segments = ["Pore", "Solid"]

        self.assertTrue(select_segment(segment_list, segments))

        self.assertTrue(segmentation_combo_box.currentNode() == seg_node)
        self.assertTrue(region_soi_combo_box.currentNode() is None)
        self.assertTrue(image_segments_combo_box.currentNode() is not None)
        self.assertTrue(methods_combo_box.currentText == WATERSHED_METHOD_LABEL)
        self.assertTrue(apply_button.enabled)
        self.assertTrue(self._module_widget.currentMode == widgets.SingleShotInputWidget.MODE_NAME)

        with check_for_message_box(
            "The combination of the selected segments covers the entire image. "
            "This can lead to unexpected results. Do you want to proceed?",
            buttonTextToClick="&No",
        ):
            # Used the apply button's callback directly because otherwise, it won't be blockant and it won't be able
            # to recognize the exception throw,
            self._module_widget._onApplyClicked()

        self.assertTrue(apply_button.enabled)
        # TODO how to assert the message box was NOT shown?

    def generate_qemscan_data(self):
        """Script to generate template data related to QEMSCAN project.
        How to:
        1) Add 'test_' prefix to this test
        2) Remove the 'test_' prefix from others tests
        3) Change 'after_clear' flag on test class constructor to 'False'
        4) Run test session
        5) Wait test session to finish
        6) Save the current project as a new project (QEMSCAN at Resources folder, as example)
        """
        slicer.util.loadScene(QEMSCAN_RAW_PROJECT_FILE)

        self.test_qemscan_single_shot_watershed_with_coordination_number(generate_test_data=True)
        self.test_qemscan_single_shot_mineralogy_without_background_with_qemscan_input(generate_test_data=True)
        self.test_qemscan_single_shot_mineralogy_with_background_with_qemscan_input(generate_test_data=True)
        self.test_qemscan_single_shot_basic_petrophysics_with_qemscan_input(generate_test_data=True)
        self.test_qemscan_single_shot_watershed_with_qemscan_input_without_soi_region_1(generate_test_data=True)
        self.test_qemscan_single_shot_watershed_with_qemscan_input_without_soi_region_2(generate_test_data=True)
        self.test_qemscan_single_shot_watershed_with_qemscan_input_without_soi_region_3(generate_test_data=True)
        self.test_qemscan_single_shot_watershed_with_qemscan_input_without_soi_region_4(generate_test_data=True)
        self.test_qemscan_single_shot_watershed_with_qemscan_input_without_soi_region_5(generate_test_data=True)
        self.test_qemscan_single_shot_islands_with_qemscan_input_without_soi_region_1(generate_test_data=True)
        self.test_qemscan_single_shot_islands_with_qemscan_input_without_soi_region_2(generate_test_data=True)
        self.test_qemscan_single_shot_islands_with_qemscan_input_without_soi_region_3(generate_test_data=True)
        self.test_qemscan_single_shot_watershed_generate_throat_analysis(generate_test_data=True)

        assert save_project(project_path=QEMSCAN_PROJECT_FILE), "Failed to save generated data to project."

    def test_qemscan_single_shot_watershed_with_coordination_number(self, generate_test_data=False):
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=QEMSCAN_PROJECT_FILE,
            segmentation_name="QemScan",
            image_name="QemScan",
            template_prefix="QemScan_Template_Watershed_Coordination_Number",
            size_filter_value=0,
            smooth_factor_value=0.0054,
            minimum_distance_value=3,
            segments=[
                "Calcita (0% a 1%MgO)",
                "Calcita (1% a 4%MgO)",
                "Calcita (4% a 7%MgO)",
            ],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
            calculate_coordination_number=True,
        )

    def generate_berea_data(self):
        """Script to generate template data related to Bereas project.
        How to:
        1) Add 'test_' prefix to this test
        2) Remove the 'test_' prefix from others tests
        3) Change 'after_clear' flag on test class constructor to 'False'
        4) Run test session
        5) Wait test session to finish
        6) Save the current project as a new project (Berea at Resources folder, as example)
        """
        slicer.util.loadScene(BEREA_RAW_PROJECT_FILE)
        self.test_berea_single_shot_watershed_with_berea_input_1(generate_test_data=True)
        self.test_berea_single_shot_watershed_with_berea_input_2(generate_test_data=True)
        self.test_berea_single_shot_watershed_with_berea_input_3(generate_test_data=True)
        self.test_berea_single_shot_watershed_with_berea_input_4(generate_test_data=True)
        self.test_berea_single_shot_watershed_with_berea_input_5(generate_test_data=True)
        self.test_berea_single_shot_watershed_with_berea_input_6(generate_test_data=True)
        self.test_berea_single_shot_islands_with_berea_input_1(generate_test_data=True)
        self.test_berea_single_shot_islands_with_berea_input_2(generate_test_data=True)
        self.test_berea_single_shot_islands_with_berea_input_3(generate_test_data=True)
        self.test_berea_single_shot_mineralogy_without_background_with_berea_input(generate_test_data=True)
        self.test_berea_single_shot_mineralogy_with_background_with_berea_input(generate_test_data=True)

        assert save_project(project_path=BEREA_PROJECT_FILE), "Failed to save generated data to project."

    def generate_ellipses_data(self):
        """Script to generate template data related to Ellipses project.
        How to:
        1) Add 'test_' prefix to this test
        2) Remove the 'test_' prefix from others tests
        3) Change 'after_clear' flag on test class constructor to 'False'
        4) Run test session
        5) Wait test session to finish
        6) Save the current project as a new project (Ellipses at the Resources folder, as example)
        """
        slicer.util.loadScene(ELLIPSES_RAW_PROJECT_FILE)
        self.test_ellipses_single_shot_watershed_with_orientation_line_vertical(generate_test_data=True)
        self.test_ellipses_single_shot_watershed_with_orientation_line_45_degree(generate_test_data=True)
        self.test_ellipses_single_shot_watershed_with_orientation_line_horizontal(generate_test_data=True)

        assert save_project(project_path=ELLIPSES_PROJECT_FILE), "Failed to save generated data to project."

    def test_label_map_single_segment_from_raw_data(self, generate_test_data=False):
        common_successful_test_process(
            cls=self,
            method=WATERSHED_METHOD_LABEL,
            project_file=VOLUME_FROM_RAW_FILE_PROJECT_PATH,
            segmentation_name="LabelMap",
            image_name="LabelMap",
            soi_name=None,
            template_prefix="LabelMap_Template_Inspector",
            size_filter_value=0,
            smooth_factor_value=0.0020,
            minimum_distance_value=5,
            segments=["Pore"],
            generate_test_data=generate_test_data,
            do_preprocessing=True,
        )

    def generate_commons_data(self):
        load_project(VOLUME_FROM_RAW_FILE_RAW_PROJECT_PATH)
        self.test_label_map_single_segment_from_raw_data(generate_test_data=True)
        assert save_project(project_path=VOLUME_FROM_RAW_FILE_PROJECT_PATH), "Failed to save generated data to project."
