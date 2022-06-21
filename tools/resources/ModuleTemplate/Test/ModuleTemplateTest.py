from ltrace.slicer.tests.ltrace_plugin_test import LTracePluginTest
from ltrace.slicer.tests.utils import check_for_message_box


class {{name}}Test(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = {
            "apply_button": self.find_widget("Apply Button"),
            "output_prefix_line_edit": self.find_widget("Output Prefix Line Edit"),
        }

    def tear_down(self):
        pass

    def test_default_interface_configuration(self):
        apply_button = self._widgets["apply_button"]
        output_prefix_line_edit = self._widgets["output_prefix_line_edit"]
        assert apply_button is not None
        assert apply_button.enabled == True
        assert output_prefix_line_edit is not None
        assert output_prefix_line_edit.enabled == True
        assert output_prefix_line_edit.text == ""

    def test_attempt_to_click_on_apply_without_node_should_prompt_message(self):
        apply_button = self._widgets["apply_button"]
        output_prefix_line_edit = self._widgets["output_prefix_line_edit"]
        output_prefix_line_edit.text = "dummy"

        # Simulate click on apply button
        with check_for_message_box("Please select an input node."):
            apply_button.clicked()

    def test_attempt_to_click_on_apply_without_output_prefix_should_prompt_message(self):
        apply_button = self._widgets["apply_button"]
        output_prefix_line_edit = self._widgets["output_prefix_line_edit"]
        output_prefix_line_edit.text = ""

        # Simulate click on apply button
        with check_for_message_box("Please type an output prefix."):
            apply_button.clicked()
