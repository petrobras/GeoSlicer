from commons.algorithms.measurements import AXIS_LENGTH_COLUMNS, CENTROID_COLUMNS, ORIENTATION_COLUMNS, PRINCIPAL_AXES
from commons.slicer.segment_report_navigator import index_to_ras, label_bounding_boxes, locate_label
from commons.slicer.tests.utils import wait_cli_to_finish, load_project, process_events
from commons.slicer import widgets
from decimal import Decimal
from math import log, floor
from scipy import ndimage
import numpy as np
import os
import pandas as pd
import qt
import slicer
import sys
import vtk


TEST_RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "Resources")
QEMSCAN_RAW_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "QEMSCAN_RAW", "QEMSCAN_RAW.mrml")
QEMSCAN_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "QEMSCAN", "QEMSCAN.mrml")
BEREA_RAW_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "BEREA_RAW", "BEREA_RAW.mrml")
BEREA_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "BEREA", "BEREA.mrml")
ELLIPSES_RAW_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "Ellipses_RAW", "Ellipses_RAW.mrml")
ELLIPSES_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "Ellipses", "Ellipses.mrml")
SYNTHETIC_STAR_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "SYNTHETIC_STAR", "SYNTHETIC_STAR.mrml")
THINSEC_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "THINSEC", "THINSEC.mrml")
VOLUME_FROM_RAW_FILE_PROJECT_PATH = os.path.join(
    TEST_RESOURCES_DIR, "VOLUME_FROM_RAW_FILE", "VOLUME_FROM_RAW_FILE.mrml"
)
VOLUME_FROM_RAW_FILE_RAW_PROJECT_PATH = os.path.join(
    TEST_RESOURCES_DIR, "VOLUME_FROM_RAW_FILE_RAW", "VOLUME_FROM_RAW_FILE_RAW.mrml"
)

WATERSHED_METHOD_LABEL = "Over-Segmented Watershed"
ISLANDS_METHOD_LABEL = "Islands"
MINERALOGY_METHOD_LABEL = "Transition analysis"
BASIC_PETROPHYSICS_METHOD_LABEL = "Basic Petrophysics"
MEDIAL_SURFACE_METHOD_LABEL = "Medial surface segmentation"
RELATIVE_TOLERANCE = 1e-03
ABSOLUTE_TOLERANCE = 1e-02
ROUNDING_PRECISION = 6  # Necessary because table values are rounded when saved (6 is the default precision used by vtk)


def populate_widgets(cls):
    """Initialize dictionary with module's interface widgets reference."""
    single_shot_radio_button = cls.find_widget("Single-Shot")
    batch_radio_button = cls.find_widget("Batch")
    segmentation_combo_box = cls.find_widget("Segmentation ComboBox")
    image_segments_combo_box = cls.find_widget("Image Segments ComboBox")
    region_soi_combo_box = cls.find_widget("SOI ComboBox")
    methods_combo_box = cls.find_widget("Methods ComboBox")
    preprocessing_checkbox = cls.find_widget("Preprocessing CheckBox")
    apply_button = cls.find_widget("SegmentInspector.ApplyButton")
    cancel_button = cls.find_widget("SegmentInspector.CancelButton")
    output_prefix_line_edit = cls.find_widget("Output Prefix Line Edit")
    include_background_checkbox = cls.find_widget("Include Background CheckBox")
    segment_list = cls.find_widget("Segment List")
    watershed_size_filter = cls.find_widget("Watershed Size Filter SpinBox")
    minimum_distance = cls.find_widget("Minimum Distance SpinBox")
    smooth_factor = cls.find_widget("Smooth Factor SpinBox")
    islands_size_filter = cls.find_widget("Islands Size Filter SpinBox")
    throat_analysis_checkbox_on_watershed = cls.find_widget("2D Throat analysis CheckBox on Watershed")
    orientation_line = cls.find_widget("Orientation line ComboBox")
    smooth_filter_sigma = cls.find_widget("Smooth Filter Sigma SpinBox")
    num_processes = cls.find_widget("Number Processes SpinBox")
    coordination_number_checkbox = cls.find_widget("CoordinationNumberCheckBox")
    centroid_checkbox = cls.find_widget("Centroid CheckBox")
    orientation_checkbox = cls.find_widget("Orientation CheckBox")
    axis_lengths_checkbox = cls.find_widget("Axis Lengths CheckBox")

    # Assert widget existance
    cls.assertIsNotNone(single_shot_radio_button)
    cls.assertIsNotNone(batch_radio_button)
    cls.assertIsNotNone(segmentation_combo_box)
    cls.assertIsNotNone(image_segments_combo_box)
    cls.assertIsNotNone(region_soi_combo_box)
    cls.assertIsNotNone(methods_combo_box)
    cls.assertIsNotNone(apply_button)
    cls.assertIsNotNone(cancel_button)
    cls.assertIsNotNone(include_background_checkbox)
    cls.assertIsNotNone(segment_list)
    cls.assertIsNotNone(watershed_size_filter)
    cls.assertIsNotNone(minimum_distance)
    cls.assertIsNotNone(smooth_factor)
    cls.assertIsNotNone(islands_size_filter)
    cls.assertIsNotNone(throat_analysis_checkbox_on_watershed)
    cls.assertIsNotNone(orientation_line)
    cls.assertIsNotNone(smooth_filter_sigma)
    cls.assertIsNotNone(num_processes)
    cls.assertIsNotNone(coordination_number_checkbox)
    cls.assertIsNotNone(centroid_checkbox)
    cls.assertIsNotNone(orientation_checkbox)
    cls.assertIsNotNone(axis_lengths_checkbox)

    cls._widgets["single_shot_radio_button"] = single_shot_radio_button
    cls._widgets["batch_radio_button"] = batch_radio_button
    cls._widgets["segmentation_combo_box"] = segmentation_combo_box
    cls._widgets["image_segments_combo_box"] = image_segments_combo_box
    cls._widgets["region_soi_combo_box"] = region_soi_combo_box
    cls._widgets["methods_combo_box"] = methods_combo_box
    cls._widgets["preprocessing_checkbox"] = preprocessing_checkbox
    cls._widgets["apply_button"] = apply_button
    cls._widgets["cancel_button"] = cancel_button
    cls._widgets["output_prefix_line_edit"] = output_prefix_line_edit
    cls._widgets["include_background_checkbox"] = include_background_checkbox
    cls._widgets["segment_list"] = segment_list
    cls._widgets["watershed_size_filter"] = watershed_size_filter
    cls._widgets["minimum_distance"] = minimum_distance
    cls._widgets["smooth_factor"] = smooth_factor
    cls._widgets["islands_size_filter"] = islands_size_filter
    cls._widgets["throat_analysis_checkbox_on_watershed"] = throat_analysis_checkbox_on_watershed
    cls._widgets["orientation_line"] = orientation_line
    cls._widgets["smooth_filter_sigma"] = smooth_filter_sigma
    cls._widgets["num_processes"] = num_processes
    cls._widgets["coordination_number_checkbox"] = coordination_number_checkbox
    cls._widgets["centroid_checkbox"] = centroid_checkbox
    cls._widgets["orientation_checkbox"] = orientation_checkbox
    cls._widgets["axis_lengths_checkbox"] = axis_lengths_checkbox


def select_segment(widget: qt.QListWidget, segment_labels):
    """Wrapper for segment selection at the segment list widget

    Args:
        widget (qt.QListWidget): the list widget
        segment_labels (list or str): the name of the desired segments to be selected

    Returns:
        bool: True
    """
    if widget is None:
        return False

    if isinstance(segment_labels, str):
        segment_labels = [segment_labels]

    for index in range(widget.count):
        item = widget.item(index)
        if any(map(item.text().__contains__, segment_labels)):
            item.setCheckState(qt.Qt.Checked)

    return True


def common_successful_test_process(cls, *args, **kwargs):
    """Wrapper for different methods's successful test process"""
    method = kwargs.get("method")

    if method == WATERSHED_METHOD_LABEL:
        watershed_successful_test_process(cls, *args, **kwargs)
    elif method == ISLANDS_METHOD_LABEL:
        island_successful_test_process(cls, *args, **kwargs)
    elif method == MINERALOGY_METHOD_LABEL:
        mineralogy_successful_test_process(cls, *args, **kwargs)
    elif method == BASIC_PETROPHYSICS_METHOD_LABEL:
        basic_petrophysics_successful_test_process(cls, *args, **kwargs)
    elif method == MEDIAL_SURFACE_METHOD_LABEL:
        medial_surface_successful_test_process(cls, *args, **kwargs)
    else:
        raise NotImplementedError(f"The method {method} data successful test process was not implemented.")


def watershed_successful_test_process(cls, *args, **kwargs):
    """Handle common interface configurations for single-shot usage.

    Raises:
        RuntimeError: When using invalid input related to the current method.
    """
    method = kwargs.get("method")

    if method != WATERSHED_METHOD_LABEL:
        raise Exception(f"Unable to execute test process for method {method} using the Watershed's method handler.")

    project_file = kwargs.get("project_file")
    segmentation_name = kwargs.get("segmentation_name")
    image_name = kwargs.get("image_name")
    soi_name = kwargs.get("soi_name")
    template_prefix = kwargs.get("template_prefix")
    method = kwargs.get("method")
    do_preprocessing = kwargs.get("do_preprocessing", False)
    size_filter_value = kwargs.get("size_filter_value")
    smooth_factor_value = kwargs.get("smooth_factor_value")
    minimum_distance_value = kwargs.get("minimum_distance_value")
    segments = kwargs.get("segments", [])
    output_prefix_line_edit = cls._widgets["output_prefix_line_edit"]
    generate_throat_analysis = kwargs.get("generate_throat_analysis", False)
    generate_test_data = kwargs.get("generate_test_data", False)
    orientation_line = kwargs.get("orientation_line")
    calculate_coordination_number = kwargs.get("calculate_coordination_number", False)
    if (
        project_file is None
        or segmentation_name is None
        or image_name is None
        or template_prefix is None
        or method is None
    ):
        raise RuntimeError("Invalid inputs")

    if not generate_test_data:
        load_project(project_file)

    segmentation_node = slicer.util.getNode(segmentation_name)
    cls.assertIsNotNone(segmentation_node)

    image_node = slicer.util.getNode(image_name)
    cls.assertIsNotNone(image_node)

    if soi_name is not None:
        soi_node = slicer.util.getNode(soi_name)
        cls.assertIsNotNone(soi_node)
    else:
        soi_node = None
    # Retrieve widgets of interest
    single_shot_radio_button = cls._widgets["single_shot_radio_button"]
    segmentation_combo_box = cls._widgets["segmentation_combo_box"]
    image_segments_combo_box = cls._widgets["image_segments_combo_box"]
    region_soi_combo_box = cls._widgets["region_soi_combo_box"]
    methods_combo_box = cls._widgets["methods_combo_box"]
    preprocessing_checkbox = cls._widgets["preprocessing_checkbox"]
    apply_button = cls._widgets["apply_button"]
    segment_list = cls._widgets["segment_list"]
    throat_analysis_checkbox = cls._widgets["throat_analysis_checkbox_on_watershed"]
    orientation_line_combo_box = cls._widgets["orientation_line"]
    coordination_number_checkbox = cls._widgets["coordination_number_checkbox"]

    # Configure
    single_shot_radio_button.setChecked(True)  # Force Single-Shot
    segmentation_combo_box.setCurrentNode(segmentation_node)  # qMRMLNodeComboBox
    image_segments_combo_box.setCurrentNode(image_node)  # qMRMLNodeComboBox

    if soi_node is not None:
        region_soi_combo_box.setCurrentNode(soi_node)

    methods_combo_box.setCurrentText(method)  # QComboBox
    preprocessing_checkbox.setChecked(do_preprocessing)

    process_events()

    cls.assertTrue(segmentation_combo_box.currentNode() == segmentation_node)
    cls.assertTrue(image_segments_combo_box.currentNode() == image_node)
    cls.assertTrue(region_soi_combo_box.currentNode() == soi_node)
    cls.assertTrue(methods_combo_box.currentText == method)
    cls.assertTrue(apply_button.enabled)
    cls.assertTrue(cls._module_widget.currentMode == widgets.SingleShotInputWidget.MODE_NAME)

    if minimum_distance_value is not None:
        minimum_distance = cls._widgets["minimum_distance"]
        minimum_distance.setValue(minimum_distance_value)

    if smooth_factor_value is not None:
        smooth_factor = cls._widgets["smooth_factor"]
        smooth_factor.setValue(smooth_factor_value)

    if size_filter_value is not None:
        size_filter = cls._widgets["watershed_size_filter"]
        size_filter.setValue(size_filter_value)

    if orientation_line is not None:
        orientation_line_node = slicer.util.getNode(orientation_line)
        cls.assertIsNotNone(orientation_line_node)
        orientation_line_combo_box.setCurrentNode(orientation_line_node)
        cls.assertTrue(orientation_line_combo_box.currentNode() == orientation_line_node)

    coordination_number_checkbox.setChecked(calculate_coordination_number)

    cls.assertTrue(select_segment(segment_list, segments))

    if generate_test_data is True:
        output_prefix_line_edit.setText(template_prefix)

    # Throat analysis
    throat_analysis_checkbox.setChecked(generate_throat_analysis)

    # Run
    apply_button.clicked()

    cli_node = cls._module_widget.logic.cliNode
    cls.assertIsNotNone(cli_node)

    wait_cli_to_finish(cli_node, timeout_sec=200)
    assert cli_node.GetStatusString() == "Completed", (
        f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
    )

    if generate_test_data is True:
        return

    output_prefix = str(output_prefix_line_edit.text).replace("_{type}", "")

    # Templates nodes
    variables_template = f"{template_prefix}_Variables"
    variables_template_node = slicer.util.getNode(variables_template)
    report_template = f"{template_prefix}_Report"
    report_template_node = slicer.util.getNode(report_template)
    label_map_template = f"{template_prefix}_LabelMap"
    label_map_template_node = slicer.util.getNode(label_map_template)
    throat_analysis_template_report_node = (
        slicer.util.getNode(f"{template_prefix}_Throat_Report") if generate_throat_analysis else None
    )
    throat_analysis_template_label_map_node = (
        slicer.util.getNode(f"{template_prefix}_Throat_LabelMap") if generate_throat_analysis else None
    )

    # Output nodes
    variables_output_node = slicer.util.getNode(f"{output_prefix}_Variables")
    report_output_node = slicer.util.getNode(f"{output_prefix}_Report")
    label_map_output_node = slicer.util.getNode(f"{output_prefix}_LabelMap")

    variables_output_df = slicer.util.dataframeFromTable(variables_output_node)
    variables_template_df = slicer.util.dataframeFromTable(variables_template_node)
    report_output_df = slicer.util.dataframeFromTable(report_output_node)
    report_template_df = slicer.util.dataframeFromTable(report_template_node)

    basic_petrophysics_output_node = slicer.mrmlScene.GetFirstNodeByName(f"{output_prefix}_Basic_Petrophysics")

    label_map_output_array = slicer.util.arrayFromVolume(label_map_output_node)
    label_map_template_array = slicer.util.arrayFromVolume(label_map_template_node)

    throat_analysis_output_report_node = (
        slicer.util.getNode(f"{output_prefix}_Throat_Report") if generate_throat_analysis else None
    )
    throat_analysis_output_label_map_node = (
        slicer.util.getNode(f"{output_prefix}_Throat_LabelMap") if generate_throat_analysis else None
    )
    # Assertions
    cls.assertIsNotNone(variables_template_node)
    cls.assertIsNotNone(report_template_node)
    cls.assertIsNotNone(label_map_template_node)
    cls.assertIsNotNone(variables_output_node)
    cls.assertIsNotNone(report_output_node)
    cls.assertIsNotNone(label_map_output_node)
    cls.assertIsNone(basic_petrophysics_output_node)

    if "linux" not in sys.platform:
        # pd.testing.assert_frame_equal and np.testing.assert_array_equal
        # raises exception if df's/arrays are different

        # round_dataframe_to_default_precision(variables_output_df)

        assert_variables_df(output_df=variables_output_df, template_df=variables_template_df)

        ## Note: I will leave the commented code below for future reference
        # limit_index = report_template_df.index[report_template_df["voxelCount"] > 3].argmin()

        assert_report_df(output_df=report_output_df, template_df=report_template_df)

        # label_map_template_array[label_map_template_array >= limit_index] = 0
        # label_map_output_array[label_map_output_array >= limit_index] = 0

        np.testing.assert_array_equal(label_map_output_array, label_map_template_array)

    if generate_throat_analysis:
        cls.assertIsNotNone(throat_analysis_output_report_node)
        cls.assertIsNotNone(throat_analysis_template_report_node)
        if "linux" not in sys.platform:
            throat_report_output_df = slicer.util.dataframeFromTable(throat_analysis_output_report_node)
            throat_report_template_df = slicer.util.dataframeFromTable(throat_analysis_template_report_node)
            round_dataframe_to_default_precision(throat_report_output_df)
            pd.testing.assert_frame_equal(
                throat_report_template_df,
                throat_report_output_df,
                check_exact=False,
                rtol=RELATIVE_TOLERANCE,
                atol=ABSOLUTE_TOLERANCE,
            )
            throat_analysis_template_label_map_array = slicer.util.arrayFromVolume(
                throat_analysis_template_label_map_node
            )
            throat_analysis_output_label_map_array = slicer.util.arrayFromVolume(throat_analysis_output_label_map_node)
            np.testing.assert_array_equal(
                throat_analysis_template_label_map_array, throat_analysis_output_label_map_array
            )


def island_successful_test_process(cls, *args, **kwargs):
    """Handle common interface configurations for single-shot usage.

    Raises:
        RuntimeError: When using invalid input related to the current method.
    """
    method = kwargs.get("method")

    if method != ISLANDS_METHOD_LABEL:
        raise Exception(f"Unable to execute test process for method {method} using the Island's method handler.")

    project_file = kwargs.get("project_file")
    segmentation_name = kwargs.get("segmentation_name")
    image_name = kwargs.get("image_name")
    soi_name = kwargs.get("soi_name")
    template_prefix = kwargs.get("template_prefix")
    size_filter_value = kwargs.get("size_filter_value")
    smooth_factor_value = kwargs.get("smooth_factor_value")
    minimum_distance_value = kwargs.get("minimum_distance_value")
    do_preprocessing = kwargs.get("do_preprocessing", False)
    segments = kwargs.get("segments", [])
    output_prefix_line_edit = cls._widgets["output_prefix_line_edit"]
    generate_test_data = kwargs.get("generate_test_data", False)
    orientation_line = kwargs.get("orientation_line")
    include_centroid = kwargs.get("include_centroid", False)
    include_orientation = kwargs.get("include_orientation", False)
    include_axis_lengths = kwargs.get("include_axis_lengths", False)

    if (
        project_file is None
        or segmentation_name is None
        or image_name is None
        or template_prefix is None
        or method is None
    ):
        raise RuntimeError("Invalid inputs")

    if not generate_test_data:
        load_project(project_file)

    segmentation_node = slicer.util.getNode(segmentation_name)
    cls.assertIsNotNone(segmentation_node)

    image_node = slicer.util.getNode(image_name)
    cls.assertIsNotNone(image_node)

    if soi_name is not None:
        soi_node = slicer.util.getNode(soi_name)
        cls.assertIsNotNone(soi_node)
    else:
        soi_node = None

    # Retrieve widgets of interest
    single_shot_radio_button = cls._widgets["single_shot_radio_button"]
    segmentation_combo_box = cls._widgets["segmentation_combo_box"]
    image_segments_combo_box = cls._widgets["image_segments_combo_box"]
    region_soi_combo_box = cls._widgets["region_soi_combo_box"]
    methods_combo_box = cls._widgets["methods_combo_box"]
    preprocessing_checkbox = cls._widgets["preprocessing_checkbox"]
    apply_button = cls._widgets["apply_button"]
    segment_list = cls._widgets["segment_list"]
    orientation_line_combo_box = cls._widgets["orientation_line"]
    centroid_checkbox = cls._widgets["centroid_checkbox"]
    orientation_checkbox = cls._widgets["orientation_checkbox"]
    axis_lengths_checkbox = cls._widgets["axis_lengths_checkbox"]

    # Configure
    single_shot_radio_button.setChecked(True)  # Force Single-Shot
    segmentation_combo_box.setCurrentNode(segmentation_node)  # qMRMLNodeComboBox
    image_segments_combo_box.setCurrentNode(image_node)  # qMRMLNodeComboBox

    if soi_node is not None:
        region_soi_combo_box.setCurrentNode(soi_node)

    methods_combo_box.setCurrentText(method)  # QComboBox

    process_events()

    cls.assertTrue(segmentation_combo_box.currentNode() == segmentation_node)
    cls.assertTrue(image_segments_combo_box.currentNode() == image_node)
    cls.assertTrue(region_soi_combo_box.currentNode() == soi_node)
    cls.assertTrue(methods_combo_box.currentText == method)
    cls.assertTrue(apply_button.enabled)
    cls.assertTrue(cls._module_widget.currentMode == widgets.SingleShotInputWidget.MODE_NAME)

    if minimum_distance_value is not None:
        minimum_distance = cls._widgets["minimum_distance"]
        minimum_distance.setValue(minimum_distance_value)

    if smooth_factor_value is not None:
        smooth_factor = cls._widgets["smooth_factor"]
        smooth_factor.setValue(smooth_factor_value)

    if size_filter_value is not None:
        size_filter = cls._widgets["islands_size_filter"]
        size_filter.setValue(size_filter_value)

    if orientation_line is not None:
        orientation_line_node = slicer.util.getNode(orientation_line)
        cls.assertIsNotNone(orientation_line_node)
        orientation_line_combo_box.setCurrentNode(orientation_line_node)
        cls.assertTrue(orientation_line_combo_box.currentNode() == orientation_line_node)

    preprocessing_checkbox.setChecked(do_preprocessing)
    centroid_checkbox.setChecked(include_centroid)
    orientation_checkbox.setChecked(include_orientation)
    axis_lengths_checkbox.setChecked(include_axis_lengths)

    cls.assertTrue(select_segment(segment_list, segments))

    if generate_test_data is True:
        output_prefix_line_edit.setText(template_prefix)

    # Run
    apply_button.clicked()

    cli_node = cls._module_widget.logic.cliNode
    cls.assertIsNotNone(cli_node)

    wait_cli_to_finish(cli_node)
    assert cli_node.GetStatusString() == "Completed", (
        f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
    )

    if generate_test_data is True:
        return

    output_prefix = str(output_prefix_line_edit.text).replace("_{type}", "")

    # Templates nodes
    variables_template = f"{template_prefix}_Variables"
    variables_template_node = slicer.util.getNode(variables_template)
    report_template = f"{template_prefix}_Report"
    report_template_node = slicer.util.getNode(report_template)
    label_map_template = f"{template_prefix}_LabelMap"
    label_map_template_node = slicer.util.getNode(label_map_template)

    # Output nodes
    variables_output_node = slicer.util.getNode(f"{output_prefix}_Variables")
    report_output_node = slicer.util.getNode(f"{output_prefix}_Report")
    label_map_output_node = slicer.util.getNode(f"{output_prefix}_LabelMap")
    basic_petrophysics_output_node = slicer.mrmlScene.GetFirstNodeByName(f"{output_prefix}_Basic_Petrophysics")

    variables_output_df = slicer.util.dataframeFromTable(variables_output_node)
    variables_template_df = slicer.util.dataframeFromTable(variables_template_node)
    report_output_df = slicer.util.dataframeFromTable(report_output_node)
    report_template_df = slicer.util.dataframeFromTable(report_template_node)

    label_map_output_array = slicer.util.arrayFromVolume(label_map_output_node)
    label_map_template_array = slicer.util.arrayFromVolume(label_map_template_node)

    # Assertions
    cls.assertIsNotNone(variables_template_node)
    cls.assertIsNotNone(report_template_node)
    cls.assertIsNotNone(label_map_template_node)
    cls.assertIsNotNone(variables_output_node)
    cls.assertIsNotNone(report_output_node)
    cls.assertIsNotNone(label_map_output_node)
    cls.assertIsNone(basic_petrophysics_output_node)

    centroid_columns = [f"{column} (mm)" for column in CENTROID_COLUMNS]
    if include_centroid:
        assert_report_centroids(report_output_df, label_map_output_node)
        # The other columns must still match the templates, which have no centroids
        report_output_df = report_output_df.drop(columns=centroid_columns)
    else:
        cls.assertFalse(set(centroid_columns) & set(report_output_df.columns))

    axis_length_columns = [f"{column} (mm)" for column in AXIS_LENGTH_COLUMNS]
    principal_axes_columns = (list(ORIENTATION_COLUMNS) if include_orientation else []) + (
        axis_length_columns if include_axis_lengths else []
    )
    if principal_axes_columns:
        assert_report_principal_axes(report_output_df, include_orientation, include_axis_lengths)
        report_output_df = report_output_df.drop(columns=principal_axes_columns)
    unrequested_columns = (set(ORIENTATION_COLUMNS) | set(axis_length_columns)) - set(principal_axes_columns)
    cls.assertFalse(unrequested_columns & set(report_output_df.columns))

    if "linux" not in sys.platform:
        # round_dataframe_to_default_precision(variables_output_df)

        # pd.testing.assert_frame_equal and np.testing.assert_array_equal
        # raises exception if df's/arrays are different

        assert_variables_df(output_df=variables_output_df, template_df=variables_template_df)

        assert_report_df(output_df=report_output_df, template_df=report_template_df)

        np.testing.assert_array_equal(label_map_output_array, label_map_template_array)


def medial_surface_successful_test_process(cls, *args, **kwargs):
    """Handle common interface configurations for single-shot usage.

    Raises:
        RuntimeError: When using invalid input related to the current method.
    """
    method = kwargs.get("method")

    if method != MEDIAL_SURFACE_METHOD_LABEL:
        raise Exception(f"Unable to execute test process for method {method} using the Medial surface method handler.")

    project_file = kwargs.get("project_file")
    segmentation_name = kwargs.get("segmentation_name")
    template_prefix = kwargs.get("template_prefix")
    smooth_filter_sigma = kwargs.get("smooth_filter_sigma")
    num_processes = kwargs.get("num_processes")
    segments = kwargs.get("segments", [])
    output_prefix_line_edit = cls._widgets["output_prefix_line_edit"]
    generate_test_data = kwargs.get("generate_test_data", False)

    if project_file is None or segmentation_name is None or template_prefix is None or method is None:
        raise RuntimeError("Invalid inputs")

    if not generate_test_data:
        load_project(project_file)

    segmentation_node = slicer.util.getNode(segmentation_name)
    cls.assertIsNotNone(segmentation_node)

    # Retrieve widgets of interest
    single_shot_radio_button = cls._widgets["single_shot_radio_button"]
    segmentation_combo_box = cls._widgets["segmentation_combo_box"]
    image_segments_combo_box = cls._widgets["image_segments_combo_box"]
    methods_combo_box = cls._widgets["methods_combo_box"]
    apply_button = cls._widgets["apply_button"]
    segment_list = cls._widgets["segment_list"]

    # Configure
    single_shot_radio_button.setChecked(True)  # Force Single-Shot
    segmentation_combo_box.setCurrentNode(segmentation_node)  # qMRMLNodeComboBox

    methods_combo_box.setCurrentText(method)  # QComboBox

    process_events()

    cls.assertTrue(segmentation_combo_box.currentNode() == segmentation_node)
    cls.assertTrue(image_segments_combo_box.currentNode() == segmentation_node)
    cls.assertTrue(methods_combo_box.currentText == method)
    cls.assertTrue(apply_button.enabled)
    cls.assertTrue(cls._module_widget.currentMode == widgets.SingleShotInputWidget.MODE_NAME)

    cls._widgets["smooth_filter_sigma"].setValue(smooth_filter_sigma)
    cls._widgets["num_processes"].setValue(num_processes)

    cls.assertTrue(select_segment(segment_list, segments))

    if generate_test_data is True:
        output_prefix_line_edit.setText(template_prefix)

    # Run
    apply_button.clicked()

    cli_node = cls._module_widget.logic.cliNode
    cls.assertIsNotNone(cli_node)

    wait_cli_to_finish(cli_node)
    assert cli_node.GetStatusString() == "Completed", (
        f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
    )

    if generate_test_data is True:
        return

    output_prefix = str(output_prefix_line_edit.text).replace("_{type}", "")

    # Templates nodes
    variables_template = f"{template_prefix}_Variables"
    variables_template_node = slicer.util.getNode(variables_template)
    report_template = f"{template_prefix}_Report"
    report_template_node = slicer.util.getNode(report_template)
    label_map_template = f"{template_prefix}_LabelMap"
    label_map_template_node = slicer.util.getNode(label_map_template)

    # Output nodes
    variables_output_node = slicer.util.getNode(f"{output_prefix}_Variables")
    report_output_node = slicer.util.getNode(f"{output_prefix}_Report")
    label_map_output_node = slicer.util.getNode(f"{output_prefix}_LabelMap")
    basic_petrophysics_output_node = slicer.mrmlScene.GetFirstNodeByName(f"{output_prefix}_Basic_Petrophysics")

    variables_output_df = slicer.util.dataframeFromTable(variables_output_node)
    variables_template_df = slicer.util.dataframeFromTable(variables_template_node)
    report_output_df = slicer.util.dataframeFromTable(report_output_node)
    report_template_df = slicer.util.dataframeFromTable(report_template_node)

    label_map_output_array = slicer.util.arrayFromVolume(label_map_output_node)
    label_map_template_array = slicer.util.arrayFromVolume(label_map_template_node)

    # Assertions
    cls.assertIsNotNone(variables_template_node)
    cls.assertIsNotNone(report_template_node)
    cls.assertIsNotNone(label_map_template_node)
    cls.assertIsNotNone(variables_output_node)
    cls.assertIsNotNone(report_output_node)
    cls.assertIsNotNone(label_map_output_node)
    cls.assertIsNone(basic_petrophysics_output_node)

    if "linux" not in sys.platform:
        # round_dataframe_to_default_precision(variables_output_df)

        # pd.testing.assert_frame_equal and np.testing.assert_array_equal
        # raises exception if df's/arrays are different

        assert_variables_df(output_df=variables_output_df, template_df=variables_template_df)

        assert_report_df(output_df=report_output_df, template_df=report_template_df)

        np.testing.assert_array_equal(label_map_output_array, label_map_template_array)


def mineralogy_successful_test_process(cls, *args, **kwargs):
    """Handle common interface configurations for single-shot usage.

    Raises:
        RuntimeError: When using invalid input related to the current method.
    """
    method = kwargs.get("method")

    if method != MINERALOGY_METHOD_LABEL:
        raise Exception(
            f"Unable to execute test process for method {method} using the Transition Analysis method handler."
        )

    project_file = kwargs.get("project_file")
    segmentation_name = kwargs.get("segmentation_name")
    image_name = kwargs.get("image_name")
    soi_name = kwargs.get("soi_name")
    template_prefix = kwargs.get("template_prefix")
    segments = kwargs.get("segments", [])
    include_background = kwargs.get("include_background")
    output_prefix_line_edit = cls._widgets["output_prefix_line_edit"]
    generate_test_data = kwargs.get("generate_test_data", False)

    if (
        project_file is None
        or segmentation_name is None
        or image_name is None
        or template_prefix is None
        or method is None
    ):
        raise RuntimeError("Invalid inputs")

    if not generate_test_data:
        load_project(project_file)

    segmentation_node = slicer.util.getNode(segmentation_name)
    cls.assertIsNotNone(segmentation_node)

    image_node = slicer.util.getNode(image_name)
    cls.assertIsNotNone(image_node)

    if soi_name is not None:
        soi_node = slicer.util.getNode(soi_name)
        cls.assertIsNotNone(soi_node)
    else:
        soi_node = None

    # Retrieve widgets of interest
    single_shot_radio_button = cls._widgets["single_shot_radio_button"]
    segmentation_combo_box = cls._widgets["segmentation_combo_box"]
    image_segments_combo_box = cls._widgets["image_segments_combo_box"]
    region_soi_combo_box = cls._widgets["region_soi_combo_box"]
    methods_combo_box = cls._widgets["methods_combo_box"]
    apply_button = cls._widgets["apply_button"]
    segment_list = cls._widgets["segment_list"]

    # Configure
    single_shot_radio_button.setChecked(True)  # Force Single-Shot
    if include_background is not None:
        include_background_checkbox = cls._widgets["include_background_checkbox"]
        include_background_checkbox.setChecked(include_background)

    segmentation_combo_box.setCurrentNode(segmentation_node)  # qMRMLNodeComboBox
    image_segments_combo_box.setCurrentNode(image_node)  # qMRMLNodeComboBox

    if soi_node is not None:
        region_soi_combo_box.setCurrentNode(soi_node)

    methods_combo_box.setCurrentText(method)  # QComboBox

    process_events()

    cls.assertTrue(segmentation_combo_box.currentNode() == segmentation_node)
    cls.assertTrue(image_segments_combo_box.currentNode() == image_node)
    cls.assertTrue(region_soi_combo_box.currentNode() == soi_node)
    cls.assertTrue(methods_combo_box.currentText == method)
    cls.assertTrue(apply_button.enabled)
    cls.assertTrue(cls._module_widget.currentMode == widgets.SingleShotInputWidget.MODE_NAME)
    cls.assertTrue(select_segment(segment_list, segments))

    if generate_test_data is True:
        output_prefix_line_edit.setText(template_prefix)

    # Run
    apply_button.clicked()

    cli_node = cls._module_widget.logic.cliNode
    cls.assertIsNotNone(cli_node)

    wait_cli_to_finish(cli_node)
    assert cli_node.GetStatusString() == "Completed", (
        f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
    )

    if generate_test_data is True:
        return

    output_prefix = str(output_prefix_line_edit.text).replace("_{type}", "")

    # Templates nodes
    mineralogy_template = f"{template_prefix}_Transitions"
    mineralogy_template_node = slicer.util.getNode(mineralogy_template)

    variables_template = f"{template_prefix}_Variables"
    variables_template_node = slicer.util.getNode(variables_template)

    # Output nodes
    mineralogy_output_node = slicer.util.getNode(f"{output_prefix}_Transitions")
    variables_output_node = slicer.util.getNode(f"{output_prefix}_Variables")
    basic_petrophysics_output_node = slicer.mrmlScene.GetFirstNodeByName(f"{output_prefix}_Basic_Petrophysics")

    mineralogy_output_df = slicer.util.dataframeFromTable(mineralogy_output_node)
    mineralogy_template_df = slicer.util.dataframeFromTable(mineralogy_template_node)
    variables_output_df = slicer.util.dataframeFromTable(variables_output_node)
    variables_template_df = slicer.util.dataframeFromTable(variables_template_node)

    # Assertions
    cls.assertIsNotNone(mineralogy_template_node)
    cls.assertIsNotNone(variables_template_node)
    cls.assertIsNotNone(mineralogy_output_node)
    cls.assertIsNotNone(variables_output_node)
    cls.assertIsNone(basic_petrophysics_output_node)

    round_dataframe_to_default_precision(mineralogy_output_df)
    round_dataframe_to_default_precision(variables_output_df)

    # pd.testing.assert_frame_equal Raises exception if df's are different
    pd.testing.assert_frame_equal(
        mineralogy_output_df,
        mineralogy_template_df,
        check_exact=False,
        rtol=RELATIVE_TOLERANCE,
        atol=ABSOLUTE_TOLERANCE,
    )
    pd.testing.assert_frame_equal(
        variables_output_df,
        variables_template_df,
        check_exact=False,
        rtol=RELATIVE_TOLERANCE,
        atol=ABSOLUTE_TOLERANCE,
    )


def basic_petrophysics_successful_test_process(cls, *args, **kwargs):
    """Handle common interface configurations for single-shot usage.

    Raises:
        RuntimeError: When using invalid input related to the current method.
    """
    method = kwargs.get("method")

    if method != BASIC_PETROPHYSICS_METHOD_LABEL:
        raise Exception(
            f"Unable to execute test process for method {method} using the Transition Analysis method handler."
        )

    project_file = kwargs.get("project_file")
    segmentation_name = kwargs.get("segmentation_name")
    image_name = kwargs.get("image_name")
    soi_name = kwargs.get("soi_name")
    template_prefix = kwargs.get("template_prefix")
    segments = kwargs.get("segments", [])
    output_prefix_line_edit = cls._widgets["output_prefix_line_edit"]
    generate_test_data = kwargs.get("generate_test_data", False)

    if (
        project_file is None
        or segmentation_name is None
        or image_name is None
        or template_prefix is None
        or method is None
    ):
        raise RuntimeError("Invalid inputs")

    if not generate_test_data:
        load_project(project_file)

    segmentation_node = slicer.util.getNode(segmentation_name)
    cls.assertIsNotNone(segmentation_node)

    image_node = slicer.util.getNode(image_name)
    cls.assertIsNotNone(image_node)

    if soi_name is not None:
        soi_node = slicer.util.getNode(soi_name)
        cls.assertIsNotNone(soi_node)
    else:
        soi_node = None

    # Retrieve widgets of interest
    single_shot_radio_button = cls._widgets["single_shot_radio_button"]
    segmentation_combo_box = cls._widgets["segmentation_combo_box"]
    image_segments_combo_box = cls._widgets["image_segments_combo_box"]
    region_soi_combo_box = cls._widgets["region_soi_combo_box"]
    methods_combo_box = cls._widgets["methods_combo_box"]
    apply_button = cls._widgets["apply_button"]
    segment_list = cls._widgets["segment_list"]

    # Configure
    single_shot_radio_button.setChecked(True)  # Force Single-Shot

    segmentation_combo_box.setCurrentNode(segmentation_node)  # qMRMLNodeComboBox
    image_segments_combo_box.setCurrentNode(image_node)  # qMRMLNodeComboBox

    if soi_node is not None:
        region_soi_combo_box.setCurrentNode(soi_node)

    methods_combo_box.setCurrentText(method)  # QComboBox

    process_events()

    cls.assertTrue(segmentation_combo_box.currentNode() == segmentation_node)
    cls.assertTrue(image_segments_combo_box.currentNode() == image_node)
    cls.assertTrue(region_soi_combo_box.currentNode() == soi_node)
    cls.assertTrue(methods_combo_box.currentText == method)
    cls.assertTrue(apply_button.enabled)
    cls.assertTrue(cls._module_widget.currentMode == widgets.SingleShotInputWidget.MODE_NAME)
    cls.assertTrue(select_segment(segment_list, segments))

    if generate_test_data is True:
        output_prefix_line_edit.setText(template_prefix)

    # Run
    apply_button.clicked()

    cli_node = cls._module_widget.logic.cliNode
    cls.assertIsNotNone(cli_node)

    wait_cli_to_finish(cli_node)
    assert cli_node.GetStatusString() == "Completed", (
        f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
    )

    if generate_test_data is True:
        return

    output_prefix = str(output_prefix_line_edit.text).replace("_{type}", "")

    # Templates nodes
    basic_petrophysics_template = f"{template_prefix}_Basic_Petrophysics"
    basic_petrophysics_template_node = slicer.util.getNode(basic_petrophysics_template)

    variables_template = f"{template_prefix}_Variables"
    variables_template_node = slicer.util.getNode(variables_template)

    # Output nodes
    basic_petrophysics_output_node = slicer.util.getNode(f"{output_prefix}_Basic_Petrophysics")
    variables_output_node = slicer.util.getNode(f"{output_prefix}_Variables")

    basic_petrophysics_output_df = slicer.util.dataframeFromTable(basic_petrophysics_output_node)
    basic_petrophysics_template_df = slicer.util.dataframeFromTable(basic_petrophysics_template_node)
    variables_output_df = slicer.util.dataframeFromTable(variables_output_node)
    variables_template_df = slicer.util.dataframeFromTable(variables_template_node)

    # Assertions
    cls.assertIsNotNone(basic_petrophysics_template_node)
    cls.assertIsNotNone(variables_template_node)
    cls.assertIsNotNone(basic_petrophysics_output_node)
    cls.assertIsNotNone(variables_output_node)

    round_dataframe_to_default_precision(basic_petrophysics_output_df)
    # round_dataframe_to_default_precision(variables_output_df)

    # pd.testing.assert_frame_equal Raises exception if df's are different
    pd.testing.assert_frame_equal(
        basic_petrophysics_output_df,
        basic_petrophysics_template_df,
        check_exact=False,
        rtol=RELATIVE_TOLERANCE,
        atol=ABSOLUTE_TOLERANCE,
    )
    pd.testing.assert_frame_equal(
        variables_output_df,
        variables_template_df,
        check_exact=False,
        rtol=RELATIVE_TOLERANCE,
        atol=ABSOLUTE_TOLERANCE,
    )


def watershed_generate_data_test_process(cls, *args, **kwargs):
    """Handle common interface configurations for Watershed's method single-shot usage.

    Raises:
        RuntimeError: When using invalid input related to the current method.
    """
    method = kwargs.get("method")

    if method != WATERSHED_METHOD_LABEL:
        raise Exception(f"Unable to generate test data for method {method} using the Watershed's method handler.")

    kwargs["generate_test_data"] = True
    watershed_successful_test_process(cls, *args, **kwargs)


def island_generate_data_test_process(cls, *args, **kwargs):
    """Handle common interface configurations for Island's method single-shot usage.

    Raises:
        RuntimeError: When using invalid input related to the current method.
    """
    method = kwargs.get("method")

    if method != ISLANDS_METHOD_LABEL:
        raise Exception(f"Unable to generate test data for method {method} using the Island's method handler.")

    kwargs["generate_test_data"] = True
    island_successful_test_process(cls, *args, **kwargs)


def mineralogy_generate_data_test_process(cls, *args, **kwargs):
    method = kwargs.get("method")

    if method != MINERALOGY_METHOD_LABEL:
        raise Exception(
            f"Unable to generate test data for method {method} using the Transition Analysis method handler."
        )

    kwargs["generate_test_data"] = True
    mineralogy_successful_test_process(cls, *args, **kwargs)


def basic_petrophysics_generate_data_test_process(cls, *args, **kwargs):
    method = kwargs.get("method")

    if method != BASIC_PETROPHYSICS_METHOD_LABEL:
        raise Exception(
            f"Unable to generate test data for method {method} using the Basic Petrophysics method handler."
        )

    kwargs["generate_test_data"] = True
    basic_petrophysics_successful_test_process(cls, *args, **kwargs)


def generate_data_test_process(cls, *args, **kwargs):
    """Wrapper for different methods's data generation"""
    method = kwargs.get("method")
    if method == WATERSHED_METHOD_LABEL:
        watershed_generate_data_test_process(cls, *args, **kwargs)
    elif method == ISLANDS_METHOD_LABEL:
        island_generate_data_test_process(cls, *args, **kwargs)
    elif method == MINERALOGY_METHOD_LABEL:
        mineralogy_generate_data_test_process(cls, *args, **kwargs)
    elif method == BASIC_PETROPHYSICS_METHOD_LABEL:
        basic_petrophysics_generate_data_test_process(cls, *args, **kwargs)
    else:
        raise NotImplementedError(f"The method {method} data generation process was not implemented.")


def assert_variables_df(output_df, template_df):
    """
    Note:
    Variables are text dataframes, so we need to convert the Values column to numeric and test it separately.
    We also test it with another precision, since the values are rounded to 2 decimal places.
    Still, we need to test the text values exactly.
    The tests are made separately to make it easier to debug.
    """

    numbers = pd.to_numeric(template_df["Values"], errors="coerce")
    num_mask = numbers.notnull()
    text_mask = ~num_mask

    # Assert table rows
    pd.testing.assert_series_equal(template_df["Properties"], output_df["Properties"])

    # Assert numeric rows on Values column
    pd.testing.assert_series_equal(
        numbers[num_mask], pd.to_numeric(output_df["Values"][num_mask]), check_exact=False, rtol=1e-01, atol=5e-01
    )

    # Assert text rows on Values column
    pd.testing.assert_series_equal(template_df["Values"][text_mask], output_df["Values"][text_mask], check_exact=True)


def assert_report_df(output_df, template_df, exactly=True, limit_index=None):
    if exactly:
        # compare number of rows
        assert output_df.shape[0] == template_df.shape[0]
        # compare number of columns
        assert output_df.shape[1] == template_df.shape[1]

        round_dataframe_to_default_precision(output_df)

        pd.testing.assert_frame_equal(
            output_df[:limit_index],
            template_df[:limit_index],
            check_exact=False,
            atol=ABSOLUTE_TOLERANCE,
            rtol=RELATIVE_TOLERANCE,
        )
    else:  # Check if the same rows exist in both DataFrame, disregarding the label column.
        # Remove label column
        output_df_no_label = output_df.drop("label", axis=1)
        template_df_no_label = template_df.drop("label", axis=1)

        # Merge DataFrames with indicator
        check_df = pd.merge(output_df_no_label, template_df_no_label, indicator="Exist")
        check_df["Exist"] = np.where(check_df.Exist == "both", True, False)

        # All rows should exists in both DataFrames
        exist_list = check_df["Exist"].tolist()
        assert all(exist_list)


def assert_report_centroids(report_df, label_map_node):
    """The centroid columns hold the mean world position of each label's voxels in the output labelmap."""
    array = slicer.util.arrayFromVolume(label_map_node)
    labels = report_df["label"].astype(int).to_numpy()
    voxel_centroids = np.array(ndimage.center_of_mass(array > 0, labels=array, index=labels))

    ijk_to_ras = vtk.vtkMatrix4x4()
    label_map_node.GetIJKToRASMatrix(ijk_to_ras)
    expected_zyx = index_to_ras(voxel_centroids, slicer.util.arrayFromVTKMatrix(ijk_to_ras))[:, ::-1]

    centroid_columns = [f"{column} (mm)" for column in CENTROID_COLUMNS]
    np.testing.assert_allclose(report_df[centroid_columns].to_numpy(dtype=float), expected_zyx, rtol=0, atol=1e-4)


def assert_report_principal_axes(report_df, include_orientation, include_axis_lengths):
    """The principal axes columns are consistent: orthonormal directions pointing toward +z, axis lengths from the
    major to the minor one, and the same ellipsoid as ellipsoid_volume. Values are rounded to 5 decimals."""
    if include_orientation:
        directions = report_df[list(ORIENTATION_COLUMNS)].to_numpy(dtype=float).reshape(-1, 3, 3)
        gram = np.einsum("nij,nkj->nik", directions, directions)
        np.testing.assert_allclose(gram, np.broadcast_to(np.eye(3), gram.shape), atol=1e-4)
        assert np.all(directions[:, :, 0] >= 0), "Every axis must point toward +z (S)"

    if include_axis_lengths:
        lengths = report_df[[f"{axis}_axis_length (mm)" for axis in PRINCIPAL_AXES]].to_numpy(dtype=float)
        assert np.all(np.diff(lengths, axis=1) <= 1e-5), "Axis lengths must go from the major to the minor axis"
        np.testing.assert_allclose(
            report_df["ellipsoid_volume (mm^3)"].to_numpy(dtype=float),
            np.pi / 6 * lengths.prod(axis=1),
            rtol=1e-2,
            atol=1e-5,
        )


def click_report_row(table_view, label):
    """Make the row of a report table view that shows the label current, as a click on it does."""
    model = table_view.model()
    label_column = table_view.mrmlTableNode().GetColumnIndex("label")
    for row in range(model.rowCount()):
        index = model.index(row, label_column)
        if index.data() == str(label):
            table_view.selectionModel().clearCurrentIndex()
            table_view.selectionModel().setCurrentIndex(index, qt.QItemSelectionModel.ClearAndSelect)
            process_events()
            return

    raise AssertionError(f"No row of the table view shows label {label}")


def assert_views_frame_label(label_map_node, label):
    """Slice views cross a voxel of the label and show its whole bounding box; 3D views are centered on the box."""
    array = slicer.util.arrayFromVolume(label_map_node)
    voxels = np.argwhere(array == label)
    assert len(voxels) > 0, f"Label {label} is not in {label_map_node.GetName()}"

    ijk_to_ras_matrix = vtk.vtkMatrix4x4()
    label_map_node.GetIJKToRASMatrix(ijk_to_ras_matrix)
    ijk_to_ras = slicer.util.arrayFromVTKMatrix(ijk_to_ras_matrix)
    voxel_centers = index_to_ras(voxels, ijk_to_ras)
    low = voxels.min(axis=0) - 0.5
    high = voxels.max(axis=0) + 0.5
    corners = index_to_ras(
        [(k, j, i) for k in (low[0], high[0]) for j in (low[1], high[1]) for i in (low[2], high[2])], ijk_to_ras
    )

    layout_manager = slicer.app.layoutManager()
    framed_views = 0
    for view_name in layout_manager.sliceViewNames():
        slice_node = layout_manager.sliceWidget(view_name).mrmlSliceNode()
        if not slice_node.IsMappedInLayout():
            continue

        slice_to_ras = slicer.util.arrayFromVTKMatrix(slice_node.GetSliceToRAS())
        view_center = slice_to_ras[:3, 3]
        assert tuple(slice_node.GetXYZOrigin()) == (0, 0, 0)

        distance_to_plane = np.abs((voxel_centers - view_center) @ slice_to_ras[:3, 2])
        assert distance_to_plane.min() < 1e-3, f"The {view_name} view doesn't cross label {label}"

        in_plane = np.abs((corners - view_center) @ slice_to_ras[:3, :2])
        fov = slice_node.GetFieldOfView()
        assert np.all(in_plane[:, 0] <= fov[0] / 2 + 1e-6), f"Label {label} is wider than the {view_name} view"
        assert np.all(in_plane[:, 1] <= fov[1] / 2 + 1e-6), f"Label {label} is taller than the {view_name} view"
        framed_views += 1

    for index in range(layout_manager.threeDViewCount):
        view_node = layout_manager.threeDWidget(index).mrmlViewNode()
        if not view_node.IsMappedInLayout():
            continue

        camera_node = slicer.modules.cameras.logic().GetViewActiveCameraNode(view_node)
        box_center = (corners.min(axis=0) + corners.max(axis=0)) / 2
        np.testing.assert_allclose(camera_node.GetFocalPoint(), box_center, atol=1e-6)
        framed_views += 1

    assert framed_views > 0, "No view was checked"


def click_segment(view_name, label_map_node, label, ctrl=False):
    """Click on a segment in a slice view, with Qt mouse events on the view's render widget, as the mouse does.

    The view goes through the segment's voxel nearest to its centroid and zooms in, so the click can't reach another
    segment.
    """
    array = slicer.util.arrayFromVolume(label_map_node)
    k, j, i = locate_label(array, label_bounding_boxes(array)[label - 1], label, label_map_node.GetSpacing()[::-1])[0]
    ijk_to_ras = vtk.vtkMatrix4x4()
    label_map_node.GetIJKToRASMatrix(ijk_to_ras)
    ras = ijk_to_ras.MultiplyPoint((float(i), float(j), float(k), 1.0))

    slice_widget = slicer.app.layoutManager().sliceWidget(view_name)
    assert slice_widget.isVisible(), f"The {view_name} view must be in the layout to be clicked"
    slice_node = slice_widget.mrmlSliceNode()
    slice_node.JumpSliceByCentering(*ras[:3])
    width, height, _ = slice_node.GetDimensions()
    field_of_view = 10 * min(label_map_node.GetSpacing())
    slice_node.SetFieldOfView(field_of_view, field_of_view * height / width, slice_node.GetFieldOfView()[2])
    process_events()

    ras_to_xy = vtk.vtkMatrix4x4()
    vtk.vtkMatrix4x4.Invert(slice_node.GetXYToRAS(), ras_to_xy)
    x, y = ras_to_xy.MultiplyPoint(ras)[:2]

    # Slice view XY is VTK's: device pixels from the bottom left. Qt's is logical pixels from the top left.
    render_widget = next(
        child for child in slice_widget.sliceView().findChildren("QWidget") if "VTK" in child.className()
    )
    ratio = render_widget.devicePixelRatioF()
    position = qt.QPointF(x / ratio, (render_widget.height * ratio - 1 - y) / ratio)
    modifiers = qt.Qt.ControlModifier if ctrl else qt.Qt.NoModifier
    for event_type, buttons in (
        (qt.QEvent.MouseButtonPress, qt.Qt.LeftButton),
        (qt.QEvent.MouseButtonRelease, qt.Qt.NoButton),
    ):
        event = qt.QMouseEvent(event_type, position, qt.Qt.LeftButton, buttons, modifiers)
        qt.QApplication.sendEvent(render_widget, event)
    process_events()


def selected_report_label(report_node):
    """Label of the current row in the table views showing the report (layout or Explorer preview), or None."""
    layout_manager = slicer.app.layoutManager()
    table_views = [layout_manager.tableWidget(index).tableView() for index in range(layout_manager.tableViewCount)]
    explorer = getattr(slicer.modules, "CustomizedDataDockedWidget", None)
    if explorer is not None:
        table_views.append(explorer.tableWidget.tableView)

    label_column = report_node.GetColumnIndex("label")
    for table_view in table_views:
        table_node = table_view.mrmlTableNode()
        current = table_view.selectionModel().currentIndex  # a property in PythonQt
        if table_node is not None and table_node.GetID() == report_node.GetID() and current.isValid():
            return table_view.model().index(current.row(), label_column).data()
    return None


def round_dataframe_to_default_precision(df):
    for column_name in df.columns:
        if pd.api.types.is_float_dtype(df[column_name]):
            for value in df[column_name].tolist():
                if value != 0:
                    rounding_digits = Decimal(ROUNDING_PRECISION - 1 - floor(log(abs(value), 10)))
                    offset = Decimal(pow(10, rounding_digits))
                    rounded_value = round(Decimal(value) * offset) / offset
                    df[column_name] = df[column_name].replace(value, float(rounded_value))
