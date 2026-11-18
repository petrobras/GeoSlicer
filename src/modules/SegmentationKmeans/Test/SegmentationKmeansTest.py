import slicer
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, check_for_message_box

from pathlib import Path

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
BUZ54_PROJECT_FILE = TEST_RESOURCES_DIR / "BUZ54" / "BUZ54.mrml"


def populate_widgets(cls):
    """Initialize dictionary with module's interface widgets reference."""
    input_section = cls.find_widget("Input")
    spacing_spin_box = cls.find_widget("spacing")
    radii_spin_box = cls.find_widget("radii")
    classes_spin_box = cls.find_widget("classes")
    threads_spin_box = cls.find_widget("threads")
    output_prefix_line_edit = cls.find_widget("Output Prefix Line Edit")
    apply_button = cls.find_widget("Apply")

    # Assert widget existance
    cls.assertIsNotNone(input_section)
    cls.assertIsNotNone(spacing_spin_box)
    cls.assertIsNotNone(radii_spin_box)
    cls.assertIsNotNone(classes_spin_box)
    cls.assertIsNotNone(threads_spin_box)
    cls.assertIsNotNone(output_prefix_line_edit)

    cls._widgets["input_section"] = input_section
    cls._widgets["spacing_spin_box"] = spacing_spin_box
    cls._widgets["radii_spin_box"] = radii_spin_box
    cls._widgets["classes_spin_box"] = classes_spin_box
    cls._widgets["threads_spin_box"] = threads_spin_box
    cls._widgets["output_prefix_line_edit"] = output_prefix_line_edit
    cls._widgets["apply_button"] = apply_button


class SegmentationKmeansTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = dict()
        populate_widgets(self)

    def tear_down(self):
        pass

    def DISABLED_test_default_interface_configuration(self):
        apply_button = self._widgets["apply_button"]
        output_prefix_line_edit = self._widgets["output_prefix_line_edit"]
        assert apply_button is not None
        assert apply_button.enabled
        assert output_prefix_line_edit is not None
        assert output_prefix_line_edit.enabled
        assert output_prefix_line_edit.text == ""

    def DISABLED_test_attempt_to_click_on_apply_without_node_should_prompt_message(self):
        apply_button = self._widgets["apply_button"]
        output_prefix_line_edit = self._widgets["output_prefix_line_edit"]
        output_prefix_line_edit.text = "dummy"

        # Simulate click on apply button
        with check_for_message_box("Please select an input node."):
            apply_button.clicked()

    def DISABLED_test_attempt_to_click_on_apply_without_output_prefix_should_prompt_message(self):
        apply_button = self._widgets["apply_button"]
        output_prefix_line_edit = self._widgets["output_prefix_line_edit"]
        output_prefix_line_edit.text = ""

        # Simulate click on apply button
        with check_for_message_box("Please type an output prefix."):
            apply_button.clicked()

    def DISABLED_test_on_segmentation(self):
        load_project(BUZ54_PROJECT_FILE)
        apply_button = self._widgets["apply_button"]
        input_volume_node = slicer.util.getNode("BUZ54_570700_SUJA_AL_21600nm0244")
        self.assertIsNotNone(input_volume_node)

        input_section = self._widgets["input_section"]
        input_section.setCurrentNode(input_volume_node)

        spacing_spin_box = self._widgets["spacing_spin_box"]
        spacing_spin_box.setText("1, 2, 2")

        # Simulate click on apply button
        with check_for_message_box("Please type an output prefix."):
            apply_button.clicked()
