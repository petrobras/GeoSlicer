import numpy as np
import pandas as pd
import slicer

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import check_for_message_box, load_project, wait_cli_to_finish, wait, save_project
from pathlib import Path


TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
POROSITY_MAP_FROM_SEGMENTATION_PROJECT_FILE = TEST_RESOURCES_DIR / "Porosity_Map" / "Porosity_Map.mrml"
POROSITY_MAP_FROM_SEGMENTATION_RAW_PROJECT_FILE = TEST_RESOURCES_DIR / "Porosity_Map_RAW" / "Porosity_Map_RAW.mrml"
POROSITY_MAP_FROM_SEGMENTATION_FLOAT_PROJECT_FILE = (
    TEST_RESOURCES_DIR / "Porosity_Map_FLOAT" / "Porosity_Map_FLOAT.mrml"
)
POROSITY_MAP_FROM_SEGMENTATION_RAW_FLOAT_PROJECT_FILE = (
    TEST_RESOURCES_DIR / "Porosity_Map_FLOAT_RAW" / "Porosity_Map_FLOAT_RAW.mrml"
)
PERMEABILITY_MAP_PROJECT_FILE = TEST_RESOURCES_DIR / "Permeability_Map" / "Permeability_Map.mrml"
PERMEABILITY_MAP_PROJECT_FILE_RAW = TEST_RESOURCES_DIR / "Permeability_Map_RAW" / "Permeability_Map_RAW.mrml"
POROSITY_MAP_FROM_SEGMENTATION_METHOD_LABEL = "Porosity Map from Segmentation"
PERMEABILITY_METHOD_LABEL = "Permeability Map"
MICROPOROSITY_SEGMENT = "Microporosity"
MACROPOROSITY_SEGMENT = "Macroporosity"
REFERENCE_SOLID_SEGMENT = "Reference Solid"
SOLID_SEGMENT = "Solid"
RELATIVE_TOLERANCE = 1e-03
ABSOLUT_TOLERANCE = 1e-06


class SegmentationModellingTest(LTracePluginTest):
    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = dict()
        populate_widgets(self)

    def tear_down(self):
        method_widget = self._module_widget.method_selector.currentWidget()
        method_widget.clearPlotData()
        del self._widgets

    def test_porosity_map_from_single_shot_doesnt_continue_without_correct_parameters(
        self,
    ):
        load_project(POROSITY_MAP_FROM_SEGMENTATION_PROJECT_FILE)
        segmentation_name = "Segmentation"
        image_name = "IMAGE"

        segmentation_node = slicer.util.getNode(segmentation_name)
        image_node = slicer.util.getNode(image_name)

        self.assertIsNotNone(segmentation_node)
        self.assertIsNotNone(image_node)

        # Retrieve widgets of interest
        segmentation_combo_box = self._widgets["porosity_map_from_segmentation_segmentation_combo_box"]
        image_segments_combo_box = self._widgets["porosity_map_from_segmentation_image_segments_combo_box"]
        region_soi_combo_box = self._widgets["porosity_map_from_segmentation_region_soi_combo_box"]
        methods_combo_box = self._widgets["methods_combo_box"]
        apply_button = self._widgets["apply_button"]

        # Configure
        methods_combo_box.setCurrentText(POROSITY_MAP_FROM_SEGMENTATION_METHOD_LABEL)
        segmentation_combo_box.setCurrentNode(segmentation_node)
        image_segments_combo_box.setCurrentNode(image_node)

        self.assertTrue(segmentation_combo_box.currentNode() == segmentation_node)
        self.assertTrue(image_segments_combo_box.currentNode() == image_node)
        self.assertTrue(region_soi_combo_box.currentNode() is None)
        self.assertTrue(methods_combo_box.currentText == POROSITY_MAP_FROM_SEGMENTATION_METHOD_LABEL)
        self.assertTrue(apply_button.enabled)

        # Assert default parameters configurations
        segment_1_parameter_combobox = self.find_widget("Segment_1 Segment Porosity Map Parameter ComboBox")
        segment_2_parameter_combobox = self.find_widget("Segment_2 Segment Porosity Map Parameter ComboBox")
        segment_3_parameter_combobox = self.find_widget("Segment_3 Segment Porosity Map Parameter ComboBox")
        segment_4_parameter_combobox = self.find_widget("Segment_4 Segment Porosity Map Parameter ComboBox")

        self.assertIsNotNone(segment_1_parameter_combobox)
        self.assertIsNotNone(segment_2_parameter_combobox)
        self.assertIsNotNone(segment_3_parameter_combobox)
        self.assertIsNotNone(segment_4_parameter_combobox)

        self.assertTrue(segment_1_parameter_combobox.currentText == "Microporosity")
        self.assertTrue(segment_2_parameter_combobox.currentText == "Microporosity")
        self.assertTrue(segment_3_parameter_combobox.currentText == "Microporosity")
        self.assertTrue(segment_4_parameter_combobox.currentText == "Microporosity")

        message = 'The user must define the input segments as "Reference Solid", "Microporosity" and "Macroporosity".'
        # Press Apply's button
        with check_for_message_box(message):
            apply_button.clicked()

    def test_porosity_map_from_segmentation_single_shot_successful_quality_control_default_parameters(
        self, generate_data_only=False
    ):
        run_successful_test_process(
            cls=self,
            method=POROSITY_MAP_FROM_SEGMENTATION_METHOD_LABEL,
            project_file=POROSITY_MAP_FROM_SEGMENTATION_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="IMAGE",
            template_prefix="Porosity_Map_From_Segmentation_Template",
            segments={
                "Segment_1": MACROPOROSITY_SEGMENT,
                "Segment_2": MICROPOROSITY_SEGMENT,
                "Segment_3": REFERENCE_SOLID_SEGMENT,
                "Segment_4": SOLID_SEGMENT,
            },
            expected_pore_attenuation_factor_value=0,
            expected_solid_attenuation_factor_value=30.0,
            expected_total_porosity_value=22.93,
            generate_data_only=generate_data_only,
        )

    def test_porosity_map_from_segmentation_single_shot_with_soi_successful_quality_control_default_parameters(
        self, generate_data_only=False
    ):
        run_successful_test_process(
            cls=self,
            method=POROSITY_MAP_FROM_SEGMENTATION_METHOD_LABEL,
            project_file=POROSITY_MAP_FROM_SEGMENTATION_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="IMAGE",
            template_prefix="Porosity_Map_From_Segmentation_With_Soi_Template",
            segments={
                "Segment_1": MACROPOROSITY_SEGMENT,
                "Segment_2": MICROPOROSITY_SEGMENT,
                "Segment_3": REFERENCE_SOLID_SEGMENT,
                "Segment_4": SOLID_SEGMENT,
            },
            soi_name="Segmentation_SOI",
            expected_pore_attenuation_factor_value=0,
            expected_solid_attenuation_factor_value=31.0,
            expected_total_porosity_value=16.29,
            generate_data_only=generate_data_only,
        )

    def test_porosity_map_from_segmentation_single_shot_successful_quality_control_default_parameters_as_label_map(
        self, generate_data_only=False
    ):
        run_successful_test_process(
            cls=self,
            method=POROSITY_MAP_FROM_SEGMENTATION_METHOD_LABEL,
            project_file=POROSITY_MAP_FROM_SEGMENTATION_PROJECT_FILE,
            segmentation_name="Segmentation-label",
            image_name="IMAGE",
            template_prefix="Label_Map_Porosity_Map_From_Segmentation_Template",
            segments={
                "Segment_1": MACROPOROSITY_SEGMENT,
                "Segment_2": MICROPOROSITY_SEGMENT,
                "Segment_3": REFERENCE_SOLID_SEGMENT,
                "Segment_4": SOLID_SEGMENT,
            },
            expected_pore_attenuation_factor_value=0,
            expected_solid_attenuation_factor_value=30.0,
            expected_total_porosity_value=22.93,
            generate_data_only=generate_data_only,
        )

    def test_porosity_map_from_segmentation_single_shot_with_soi_successful_quality_control_default_parameters_as_label_map(
        self, generate_data_only=False
    ):
        run_successful_test_process(
            cls=self,
            method=POROSITY_MAP_FROM_SEGMENTATION_METHOD_LABEL,
            project_file=POROSITY_MAP_FROM_SEGMENTATION_PROJECT_FILE,
            segmentation_name="Segmentation-label",
            image_name="IMAGE",
            template_prefix="Label_Map_Porosity_Map_From_Segmentation_With_Soi_Template",
            segments={
                "Segment_1": MACROPOROSITY_SEGMENT,
                "Segment_2": MICROPOROSITY_SEGMENT,
                "Segment_3": REFERENCE_SOLID_SEGMENT,
                "Segment_4": SOLID_SEGMENT,
            },
            soi_name="Segmentation_SOI",
            expected_pore_attenuation_factor_value=0.0,
            expected_solid_attenuation_factor_value=31.0,
            expected_total_porosity_value=25.89,
            generate_data_only=generate_data_only,
        )

    def test_porosity_map_from_segmentation_single_shot_float_successful_quality_control_default(
        self, generate_data_only=False
    ):
        run_successful_test_process(
            cls=self,
            method=POROSITY_MAP_FROM_SEGMENTATION_METHOD_LABEL,
            project_file=POROSITY_MAP_FROM_SEGMENTATION_FLOAT_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="IMAGE",
            template_prefix="Label_Map_Porosity_Map_From_Segmentation_QC_Float_Template",
            segments={
                "Segment_1": MACROPOROSITY_SEGMENT,
                "Segment_2": MICROPOROSITY_SEGMENT,
                "Segment_3": REFERENCE_SOLID_SEGMENT,
                "Segment_4": SOLID_SEGMENT,
            },
            expected_pore_attenuation_factor_value=0.0,
            expected_solid_attenuation_factor_value=30.0,
            expected_total_porosity_value=9.85,
            generate_data_only=generate_data_only,
        )

    def test_permeability_map_single_shot_successful_quality_control_default_parameters(self, generate_data_only=False):
        run_successful_test_process(
            cls=self,
            method=PERMEABILITY_METHOD_LABEL,
            project_file=PERMEABILITY_MAP_PROJECT_FILE,
            segmentation_name="Segmentation",
            image_name="IMAGE",
            template_prefix="Permeability_Map_Template",
            segments={
                "Segment_1": "line_equation",
                "Segment_2": "line_equation",
                "Segment_3": "timur_coates_equation",
                "Segment_4": "timur_coates_equation",
            },
            generate_data_only=generate_data_only,
        )

    def test_permeability_map_single_shot_successful_quality_control_default_parameters_as_label_map(
        self, generate_data_only=False
    ):
        run_successful_test_process(
            cls=self,
            method=PERMEABILITY_METHOD_LABEL,
            project_file=PERMEABILITY_MAP_PROJECT_FILE,
            segmentation_name="Segmentation-label",
            image_name="IMAGE",
            template_prefix="Label_Map_Permeability_Map_From_Segmentation_Template",
            segments={
                "Segment_1": "line_equation",
                "Segment_2": "line_equation",
                "Segment_3": "timur_coates_equation",
                "Segment_4": "timur_coates_equation",
            },
            generate_data_only=generate_data_only,
        )

    def test_permeability_map_single_shot_successful_using_global_equation(self, generate_data_only=False):
        run_successful_test_process(
            cls=self,
            method=PERMEABILITY_METHOD_LABEL,
            project_file=PERMEABILITY_MAP_PROJECT_FILE,
            segmentation_name=None,
            image_name="IMAGE",
            template_prefix="Permeability_Map_From_Segmentation_Global_Template",
            segments={
                "Global": "line_equation",
            },
            generate_data_only=generate_data_only,
        )

    def test_permeability_map_single_shot_successful_using_global_equation_with_soi(self, generate_data_only=False):
        run_successful_test_process(
            cls=self,
            method=PERMEABILITY_METHOD_LABEL,
            project_file=PERMEABILITY_MAP_PROJECT_FILE,
            segmentation_name=None,
            soi_name=None,
            image_name="IMAGE",
            template_prefix="Permeability_Map_From_Segmentation_Global",
            segments={
                "Global": "line_equation",
            },
            generate_data_only=generate_data_only,
        )

    def test_permeability_map_single_shot_successful_using_multi_equation_with_soi(self, generate_data_only=False):
        run_successful_test_process(
            cls=self,
            method=PERMEABILITY_METHOD_LABEL,
            project_file=PERMEABILITY_MAP_PROJECT_FILE,
            segmentation_name="Segmentation",
            soi_name="SOI",
            image_name="IMAGE",
            template_prefix="Permeability_Map_From_Segmentation_MultiEquations_with_SOI_Template",
            segments={
                "Segment_1": "line_equation",
                "Segment_2": "line_equation",
                "Segment_3": "timur_coates_equation",
                "Segment_4": "timur_coates_equation",
            },
            generate_data_only=generate_data_only,
        )

    def generate_porosity_map_from_segmentation_method_data(self):
        load_project(POROSITY_MAP_FROM_SEGMENTATION_RAW_PROJECT_FILE.as_posix())

        self.test_porosity_map_from_segmentation_single_shot_successful_quality_control_default_parameters_as_label_map(
            generate_data_only=True
        )
        self.test_porosity_map_from_segmentation_single_shot_successful_quality_control_default_parameters(
            generate_data_only=True
        )
        self.test_porosity_map_from_segmentation_single_shot_with_soi_successful_quality_control_default_parameters_as_label_map(
            generate_data_only=True
        )
        self.test_porosity_map_from_segmentation_single_shot_with_soi_successful_quality_control_default_parameters(
            generate_data_only=True
        )

        assert save_project(project_path=POROSITY_MAP_FROM_SEGMENTATION_PROJECT_FILE), (
            "Failed to save generated data to project."
        )

    def generate_porosity_map_from_segmentation_float_method_data(self):
        load_project(POROSITY_MAP_FROM_SEGMENTATION_RAW_FLOAT_PROJECT_FILE.as_posix())

        self.test_porosity_map_from_segmentation_single_shot_float_successful_quality_control_default(
            generate_data_only=True
        )

        assert save_project(project_path=POROSITY_MAP_FROM_SEGMENTATION_FLOAT_PROJECT_FILE), (
            "Failed to save generated data to project."
        )

    def generate_permeability_map_method_data(self):
        load_project(PERMEABILITY_MAP_PROJECT_FILE_RAW.as_posix())

        self.test_permeability_map_single_shot_successful_quality_control_default_parameters(generate_data_only=True)
        self.test_permeability_map_single_shot_successful_quality_control_default_parameters_as_label_map(
            generate_data_only=True
        )
        self.test_permeability_map_single_shot_successful_using_global_equation(generate_data_only=True)
        self.test_permeability_map_single_shot_successful_using_global_equation_with_soi(generate_data_only=True)
        self.test_permeability_map_single_shot_successful_using_multi_equation_with_soi(generate_data_only=True)

        assert save_project(project_path=PERMEABILITY_MAP_PROJECT_FILE), "Failed to save generated data to project."


def run_successful_test_process(cls, *args, **kwargs):
    method = kwargs.get("method")
    if method == POROSITY_MAP_FROM_SEGMENTATION_METHOD_LABEL:
        porosity_map_from_segmentation_successful_test_process(cls, *args, **kwargs)
    elif method == PERMEABILITY_METHOD_LABEL:
        permeability_map_successful_test_process(cls, *args, **kwargs)
    else:
        raise Exception(f"Unable to execute test process for method {method} using the Porosity Map's method handler.")


def permeability_map_successful_test_process(cls, *args, **kwargs):
    method = kwargs.get("method")
    if method != PERMEABILITY_METHOD_LABEL:
        raise Exception(
            f"Unable to execute test process for method {method} using the Porosity Map from Segmentation method handler."
        )

    project_file = kwargs.get("project_file")
    segmentation_name = kwargs.get("segmentation_name")
    image_name = kwargs.get("image_name")
    soi_name = kwargs.get("soi_name")
    template_prefix = kwargs.get("template_prefix")
    output_prefix_line_edit = cls._widgets["output_prefix_line_edit"]
    generate_data_only = kwargs.get("generate_data_only", False)
    segments = kwargs.get("segments")

    if (
        project_file is None
        or image_name is None
        or template_prefix is None
        or method is None
        or segments is None
        or not isinstance(segments, dict)
    ):
        raise RuntimeError("Invalid inputs")

    if generate_data_only is False:
        load_project(project_file)

    segmentation_node = None
    if segmentation_name is not None:
        segmentation_node = slicer.util.getNode(segmentation_name)
        assert segmentation_node is not None
    else:
        assert len(segments) == 1
        assert "Global" in segments

    image_node = slicer.util.getNode(image_name)
    assert image_node is not None

    if soi_name is not None:
        soi_node = slicer.util.getNode(soi_name)
        assert soi_node is not None
    else:
        soi_node = None

    # Retrieve widgets of interest
    segmentation_combo_box = cls._widgets["permeability_map_segmentation_combo_box"]
    image_segments_combo_box = cls._widgets["permeability_map_image_segments_combo_box"]
    region_soi_combo_box = cls._widgets["permeability_map_region_soi_combo_box"]
    methods_combo_box = cls._widgets["methods_combo_box"]
    apply_button = cls._widgets["apply_button"]

    # Start environment from scratch
    segmentation_combo_box.setCurrentNode(None)
    region_soi_combo_box.setCurrentNode(None)
    image_segments_combo_box.setCurrentNode(None)

    # Configure
    methods_combo_box.setCurrentText(method)  # QComboBox
    segmentation_combo_box.setCurrentNode(segmentation_node)  # qMRMLNodeComboBox
    image_segments_combo_box.setCurrentNode(image_node)  # qMRMLNodeComboBox

    if soi_node is not None:
        region_soi_combo_box.setCurrentNode(soi_node)

    assert segmentation_combo_box.currentNode() == segmentation_node
    assert image_segments_combo_box.currentNode() == image_node
    assert region_soi_combo_box.currentNode() == soi_node
    assert methods_combo_box.currentText == method

    # Update segment equations (Table nodes)
    for seg_name, equation_node_name in segments.items():
        # Retrieve related widget
        combo_box = cls.find_widget(f"{PERMEABILITY_METHOD_LABEL} {seg_name} Equation ComboBox")
        equation_node = slicer.util.getNode(equation_node_name)
        assert combo_box is not None
        assert equation_node is not None
        # Configure segment with related equation node
        combo_box.setCurrentNode(equation_node)
        assert combo_box.currentNode() == equation_node

    if generate_data_only is True:
        output_prefix_line_edit.setText(template_prefix)

    # Run
    apply_button.clicked()

    cli_node = cls._module_widget.logic._method_logic._cliNode

    assert cli_node is not None

    wait_cli_to_finish(cli_node)
    assert cli_node.GetStatusString() == "Completed"

    if generate_data_only is True:
        return

    output_prefix = str(output_prefix_line_edit.text).replace("_{type}", "")

    # Templates nodes
    permeability_map_template = f"{template_prefix}_PermeabilityMap"
    permeability_map_template_node = slicer.util.getNode(permeability_map_template)

    # Output nodes
    permeability_map_output_node = slicer.util.getNode(f"{output_prefix}_PermeabilityMap")

    # Assertions
    assert permeability_map_template_node is not None
    assert permeability_map_output_node is not None

    # PorosityMap volume arrays comparison
    permeability_map_template_array = slicer.util.arrayFromVolume(permeability_map_template_node)
    permeability_map_output_array = slicer.util.arrayFromVolume(permeability_map_output_node)

    np.testing.assert_array_equal(permeability_map_template_array, permeability_map_output_array)


def porosity_map_from_segmentation_successful_test_process(cls, *args, **kwargs):
    method = kwargs.get("method")
    if method != POROSITY_MAP_FROM_SEGMENTATION_METHOD_LABEL:
        raise Exception(
            f"Unable to execute test process for method {method} using the Porosity Map from Segmentation method handler."
        )

    project_file = kwargs.get("project_file")
    segmentation_name = kwargs.get("segmentation_name")
    image_name = kwargs.get("image_name")
    soi_name = kwargs.get("soi_name")
    template_prefix = kwargs.get("template_prefix")
    output_prefix_line_edit = cls._widgets["output_prefix_line_edit"]
    generate_data_only = kwargs.get("generate_data_only", False)
    segments = kwargs.get("segments")
    expected_pore_attenuation_factor_value = kwargs.get("expected_pore_attenuation_factor_value", 0)
    expected_solid_attenuation_factor_value = kwargs.get("expected_solid_attenuation_factor_value", 0)

    if (
        project_file is None
        or segmentation_name is None
        or image_name is None
        or template_prefix is None
        or method is None
        or segments is None
        or not isinstance(segments, dict)
    ):
        raise RuntimeError("Invalid inputs")

    if generate_data_only is False:
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
    segmentation_combo_box = cls._widgets["porosity_map_from_segmentation_segmentation_combo_box"]
    image_segments_combo_box = cls._widgets["porosity_map_from_segmentation_image_segments_combo_box"]
    region_soi_combo_box = cls._widgets["porosity_map_from_segmentation_region_soi_combo_box"]
    methods_combo_box = cls._widgets["methods_combo_box"]
    apply_button = cls._widgets["apply_button"]
    pore_attenuation_factor_input = cls._widgets["pore_attenuation_factor_input"]
    solid_attenuation_factor_input = cls._widgets["solid_attenuation_factor_input"]

    # Configure
    methods_combo_box.setCurrentText(method)  # QComboBox
    segmentation_combo_box.setCurrentNode(segmentation_node)  # qMRMLNodeComboBox
    image_segments_combo_box.setCurrentNode(image_node)  # qMRMLNodeComboBox

    if soi_node is not None:
        region_soi_combo_box.setCurrentNode(soi_node)
    else:
        region_soi_combo_box.setCurrentNode(None)

    cls.assertTrue(segmentation_combo_box.currentNode() == segmentation_node)
    cls.assertTrue(image_segments_combo_box.currentNode() == image_node)
    cls.assertTrue(region_soi_combo_box.currentNode() == soi_node)
    cls.assertTrue(methods_combo_box.currentText == method)
    cls.assertTrue(apply_button.enabled)

    # Update segment parameters (Macroporosity, Microporosity, Reference Solid and Solid)
    for seg_name, parameter in segments.items():
        # Retrieve related widget
        combo_box = cls.find_widget(f"{seg_name} Segment Porosity Map Parameter ComboBox")
        cls.assertIsNotNone(combo_box)
        # Configure porosity map parameters
        combo_box.setCurrentText(parameter)
        cls.assertTrue(combo_box.currentText == parameter)

    # Assert specific Quality Control Button existance
    quality_control_button = cls.find_widget(f"{method} Quality Control Button")
    cls.assertIsNotNone(quality_control_button)

    # Apply default quality control button configuration
    quality_control_button.clicked()

    wait(seconds=3)

    if not generate_data_only:
        cls.assertEqual(pore_attenuation_factor_input.value, expected_pore_attenuation_factor_value)
        cls.assertEqual(solid_attenuation_factor_input.value, expected_solid_attenuation_factor_value)

    if generate_data_only is True:
        output_prefix_line_edit.setText(template_prefix)

    # Run
    apply_button.clicked()

    cli_node = cls._module_widget.logic._method_logic._cliNode
    cls.assertIsNotNone(cli_node)

    wait_cli_to_finish(cli_node)
    assert cli_node.GetStatusString() == "Completed", (
        f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
    )

    if generate_data_only is True:
        return

    output_prefix = str(output_prefix_line_edit.text).replace("_{type}", "")

    # Templates nodes
    Porosity_Map_From_Segmentation_Template = f"{template_prefix}_PorosityMap"
    Porosity_Map_From_Segmentation_Template_node = slicer.util.getNode(Porosity_Map_From_Segmentation_Template)

    variables_template = f"{template_prefix}_Variables"
    variables_template_node = slicer.util.getNode(variables_template)

    # Output nodes
    porosity_map_output_node = slicer.util.getNode(f"{output_prefix}_PorosityMap")
    variables_output_node = slicer.util.getNode(f"{output_prefix}_Variables")

    # Assertions
    cls.assertIsNotNone(Porosity_Map_From_Segmentation_Template_node)
    cls.assertIsNotNone(variables_template_node)
    cls.assertIsNotNone(porosity_map_output_node)
    cls.assertIsNotNone(variables_output_node)

    # Compare value showed in QLabel with the one from table
    value_widget = cls.find_widget("Segmentation Modelling Total Porosity Output Value")
    cls.assertIsNotNone(value_widget, "Value widget for total porosity not found.")

    variables_output_df = slicer.util.dataframeFromTable(variables_output_node)
    porosity_row = variables_output_df[variables_output_df["Property"].str.contains("Weighted Total Porosity")]
    actual_value_from_table = float(porosity_row["Value"].iloc[0])

    expected_value_str = f"{actual_value_from_table:.2f}%"
    cls.assertEqual(value_widget.text, expected_value_str)

    # PorosityMap volume arrays comparison
    Porosity_Map_From_Segmentation_Template_array = slicer.util.arrayFromVolume(
        Porosity_Map_From_Segmentation_Template_node
    )
    porosity_map_output_array = slicer.util.arrayFromVolume(porosity_map_output_node)

    np.testing.assert_array_equal(Porosity_Map_From_Segmentation_Template_array, porosity_map_output_array)

    # Report comparison
    variables_output_df = slicer.util.dataframeFromTable(variables_output_node)
    variables_template_df = slicer.util.dataframeFromTable(variables_template_node)

    pd.testing.assert_frame_equal(
        variables_output_df,
        variables_template_df,
        check_exact=False,
        rtol=RELATIVE_TOLERANCE,
        atol=ABSOLUT_TOLERANCE,
    )


def populate_widgets(cls):
    """Initialize dictionary with module's interface widgets reference."""
    methods_combo_box = cls.find_widget("Methods ComboBox")
    apply_button = cls.find_widget("Apply Button")
    output_prefix_line_edit = cls.find_widget("Output Prefix Line Edit")
    segment_list = cls.find_widget("Segment List")
    pore_attenuation_factor_input = cls.find_widget("microporosity.AttenuationFactorsWidget[Air Input]")
    solid_attenuation_factor_input = cls.find_widget("microporosity.AttenuationFactorsWidget[Solid Input]")

    # Porosity Map From Segmentation method widgets
    porosity_map_from_segmentation_input_widget = cls.find_widget(
        f"{POROSITY_MAP_FROM_SEGMENTATION_METHOD_LABEL} Single Shot Input Widget"
    )
    porosity_map_from_segmentation_segmentation_combo_box = cls.find_widget(
        obj=porosity_map_from_segmentation_input_widget, name="Segmentation ComboBox"
    )
    porosity_map_from_segmentation_image_segments_combo_box = cls.find_widget(
        obj=porosity_map_from_segmentation_input_widget, name="Image Segments ComboBox"
    )
    porosity_map_from_segmentation_region_soi_combo_box = cls.find_widget(
        obj=porosity_map_from_segmentation_input_widget, name="SOI ComboBox"
    )

    # Permeability method widgets
    permeability_map_input_widget = cls.find_widget(f"{PERMEABILITY_METHOD_LABEL} Single Shot Input Widget")
    permeability_map_segmentation_combo_box = cls.find_widget(
        obj=permeability_map_input_widget, name="Segmentation ComboBox"
    )
    permeability_map_image_segments_combo_box = cls.find_widget(
        obj=permeability_map_input_widget, name="Image Segments ComboBox"
    )
    permeability_map_region_soi_combo_box = cls.find_widget(obj=permeability_map_input_widget, name="SOI ComboBox")

    # Assert widget existance
    cls.assertIsNotNone(porosity_map_from_segmentation_input_widget)
    cls.assertIsNotNone(porosity_map_from_segmentation_segmentation_combo_box)
    cls.assertIsNotNone(porosity_map_from_segmentation_image_segments_combo_box)
    cls.assertIsNotNone(porosity_map_from_segmentation_region_soi_combo_box)
    cls.assertIsNotNone(permeability_map_input_widget)
    cls.assertIsNotNone(permeability_map_segmentation_combo_box)
    cls.assertIsNotNone(permeability_map_image_segments_combo_box)
    cls.assertIsNotNone(permeability_map_region_soi_combo_box)
    cls.assertIsNotNone(methods_combo_box)
    cls.assertIsNotNone(apply_button)
    cls.assertIsNotNone(segment_list)
    cls.assertIsNotNone(pore_attenuation_factor_input)
    cls.assertIsNotNone(solid_attenuation_factor_input)

    cls._widgets["porosity_map_from_segmentation_input_widget"] = porosity_map_from_segmentation_input_widget
    cls._widgets["porosity_map_from_segmentation_segmentation_combo_box"] = (
        porosity_map_from_segmentation_segmentation_combo_box
    )
    cls._widgets["porosity_map_from_segmentation_image_segments_combo_box"] = (
        porosity_map_from_segmentation_image_segments_combo_box
    )
    cls._widgets["porosity_map_from_segmentation_region_soi_combo_box"] = (
        porosity_map_from_segmentation_region_soi_combo_box
    )
    cls._widgets["permeability_map_input_widget"] = permeability_map_input_widget
    cls._widgets["permeability_map_segmentation_combo_box"] = permeability_map_segmentation_combo_box
    cls._widgets["permeability_map_image_segments_combo_box"] = permeability_map_image_segments_combo_box
    cls._widgets["permeability_map_region_soi_combo_box"] = permeability_map_region_soi_combo_box
    cls._widgets["methods_combo_box"] = methods_combo_box
    cls._widgets["apply_button"] = apply_button
    cls._widgets["output_prefix_line_edit"] = output_prefix_line_edit
    cls._widgets["segment_list"] = segment_list
    cls._widgets["pore_attenuation_factor_input"] = pore_attenuation_factor_input
    cls._widgets["solid_attenuation_factor_input"] = solid_attenuation_factor_input
