from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, wait_cli_to_finish, wait
from commons.slicer.data_utils import tableNodeToDataFrame

import os

import slicer
import pandas as pd

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_RESOURCES_DIR = os.path.join(TEST_DIR, "Resources")
SIMULATE_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "blobs", "blobs.mrml")
MULTISCALE_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "multiscale_kabs_rev", "multiscale_kabs_rev.mrml")


class PoreNetworkKabsREVTest(LTracePluginTest):
    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = dict()

        widgets_names = [
            "Input Selector",
            "Fractions SpinBox",
            "Min Length Fraction",
            "Solver ComboBox",
            "Model Type ComboBox",
            "Subscale Model Selector",
            "Pressure Curve Selector",
            "Throat Radius Curve Selector",
            "Output Prefix Line Edit",
            "Apply Button",
            "Cancel Button",
        ]

        for widget in widgets_names:
            self._widgets[widget] = self.find_widget(widget)
            self.assertIsNotNone(self._widgets[widget])

    def tear_down(self):
        pass

    def test_kabs_rev_simulation(self, generate=False):
        dir_ = TEST_DIR
        load_project(SIMULATE_PROJECT_FILE)

        node = slicer.util.getNode("blobs")
        self.assertIsNotNone(node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(node)

        fractions_spinbox = self._widgets["Fractions SpinBox"]
        fractions_spinbox.setValue(3)

        min_length_lineedit = self._widgets["Min Length Fraction"]
        min_length_lineedit.setText("10")

        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)

        wait_cli_to_finish(cli_node)
        assert cli_node.GetStatusString() == "Completed", (
            f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
        )

        # Check
        expected_nodes = [
            "kabs_rev_x",
            "kabs_rev_y",
            "kabs_rev_z",
            "Kabs REV x",
            "Kabs REV y",
            "Kabs REV z",
        ]
        for node in expected_nodes:
            self.assertIsNotNone(slicer.util.getNode(node))

        for direction in "xyz":
            kabs_rev_table = slicer.util.getNode(f"kabs_rev_{direction}")
            results_df = tableNodeToDataFrame(kabs_rev_table)

            template_path = os.path.join(dir_, f"kabs_rev_{direction}.pd")
            if generate:
                results_df.to_pickle(template_path)
            template_df = pd.read_pickle(template_path)

            pd.testing.assert_frame_equal(template_df, results_df)

    def generate_kabs_rev_simulation(self):
        self.test_kabs_rev_simulation(generate=True)

    def test_kabs_rev_simulation_multiscale(self, generate=False):
        dir_ = TEST_DIR
        load_project(MULTISCALE_PROJECT_FILE)

        node = slicer.util.getNode("Downscaled")
        self.assertIsNotNone(node)

        table_node = slicer.util.getNode("MICP_table")
        self.assertIsNotNone(table_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(node)

        subscale_model_selector = self._widgets["Subscale Model Selector"]
        subscale_model_selector.setCurrentText("Pressure Curve")

        pressure_curve_selector = self._widgets["Pressure Curve Selector"]
        pressure_curve_selector.setCurrentNode(table_node)

        fractions_spinbox = self._widgets["Fractions SpinBox"]
        fractions_spinbox.setValue(3)

        min_length_lineedit = self._widgets["Min Length Fraction"]
        min_length_lineedit.setText("10")

        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)

        wait_cli_to_finish(cli_node)
        self.assertEqual(
            cli_node.GetStatusString(),
            "Completed",
            f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'",
        )

        # Check
        expected_nodes = [
            "kabs_rev_x",
            "kabs_rev_y",
            "kabs_rev_z",
            "Kabs REV x",
            "Kabs REV y",
            "Kabs REV z",
        ]
        for node_name in expected_nodes:
            self.assertIsNotNone(slicer.util.getNode(node_name))

        for direction in "xyz":
            kabs_rev_table = slicer.util.getNode(f"kabs_rev_{direction}")
            results_df = tableNodeToDataFrame(kabs_rev_table)

            template_path = os.path.join(dir_, f"kabs_rev_{direction}_multiscale.pd")
            if generate:
                results_df.to_pickle(template_path)

            template_df = pd.read_pickle(template_path)

            pd.testing.assert_frame_equal(template_df, results_df)

    def generate_kabs_rev_simulation_multiscale(self):
        self.test_kabs_rev_simulation_multiscale(generate=True)

    def test_cancel_button_behavior(self):
        cancelButton = self._widgets["Cancel Button"]
        self.assertTrue(cancelButton.isVisible())
        self.assertFalse(cancelButton.isEnabled())

        load_project(SIMULATE_PROJECT_FILE)
        node = slicer.util.getNode("blobs")
        self.assertIsNotNone(node)
        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(node)

        applyButton = self._widgets["Apply Button"]
        self.assertTrue(applyButton.isEnabled())

        applyButton.clicked()
        slicer.app.processEvents()

        self.assertTrue(cancelButton.isEnabled())

        logic = self._module_widget.logic
        self.assertIsNotNone(logic)
        cliNode = logic.cliNode
        self.assertIsNotNone(cliNode)
        self.assertTrue(cliNode.IsBusy())

        wait(3)

        cancelButton.clicked()
        slicer.app.processEvents()

        wait_cli_to_finish(cliNode)
        self.assertEqual(cliNode.GetStatusString(), "Cancelled")
        self.assertFalse(cancelButton.isEnabled())
        self.assertTrue(applyButton.isEnabled())

    def test_ui_on_cli_error(self):
        applyButton = self._widgets["Apply Button"]
        cancelButton = self._widgets["Cancel Button"]

        load_project(SIMULATE_PROJECT_FILE)
        node = slicer.util.getNode("blobs")
        self.assertIsNotNone(node)
        self._widgets["Input Selector"].setCurrentNode(node)

        applyButton.clicked()
        slicer.app.processEvents()

        self.assertFalse(applyButton.isEnabled())
        self.assertTrue(cancelButton.isEnabled())

        logic = self._module_widget.logic
        cliNode = logic.cliNode
        self.assertIsNotNone(cliNode)

        cliNode.SetStatus(slicer.vtkMRMLCommandLineModuleNode.CompletedWithErrors)

        logic.CLICallback(cliNode, None)
        slicer.app.processEvents()

        self.assertTrue(applyButton.isEnabled(), "Apply button should be enabled after CLI error")
        self.assertFalse(cancelButton.isEnabled(), "Cancel button should be disabled after CLI error")
        self.assertIsNone(logic.cliNode, "Logic's cliNode should be cleared after completion")
