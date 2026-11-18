import os
from unittest.mock import patch

import numpy as np
import slicer

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, process_events


TEST_RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "Resources")
KREL_EDA_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "pnm_krel_eda_test", "pnm_krel_eda_test.mrml")
SIRR_KREL_CSV_FILE = os.path.join(TEST_RESOURCES_DIR, "sirr_krel_import", "sirr_krel_sample.csv")


class PoreNetworkKrelEdaTest(LTracePluginTest):
    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = {
            "visualization_selector": self.find_widget("Visualization selector"),
            "add_filter_button": self.find_widget("Add filter button"),
            "filter_list_widget": self.find_widget("Filter list"),
            "apply_filters_button": self.find_widget("Apply filters button"),
            "input_parameter_table": self.find_widget("Input parameter table"),
            "estimate_button": self.find_widget("Estimate button"),
            "estimated_parameters_table": self.find_widget("Estimated parameters table"),
            "create_parameter_node_button": self.find_widget("Create parameter node button"),
            "import_csv_button": self.find_widget("Import from csv button"),
            "krel_table_node_selector": self.find_widget("Krel table node selector"),
            "sw_column": self.find_widget("Saturation column"),
            "krw_column": self.find_widget("Krw column"),
            "kro_column": self.find_widget("Kro column"),
            "cycle_column": self.find_widget("Cycle column"),
            "import_output_name": self.find_widget("Krel import output name"),
            "save_krel_table_button": self.find_widget("Save Krel table button"),
        }

    def test_all_views(self):
        load_project(KREL_EDA_PROJECT_FILE)

        input_paramter_table = slicer.util.getNode("Krel_results")
        self.assertIsNotNone(input_paramter_table)
        self._widgets["input_parameter_table"].setCurrentNode(input_paramter_table)

        self._widgets["visualization_selector"].selector.setCurrentText("Krel curves dispersion")
        process_events()
        self._widgets["visualization_selector"].selector.setCurrentText("Crossed error")
        process_events()
        self._widgets["visualization_selector"].selector.setCurrentText("Crossed parameters")
        process_events()
        self._widgets["visualization_selector"].selector.setCurrentText("Parameters and Result correlation")
        process_events()
        self._widgets["visualization_selector"].selector.setCurrentText("Parameters and Error correlation")
        process_events()
        self._widgets["visualization_selector"].selector.setCurrentText("Results selfcorrelation")
        process_events()
        self._widgets["visualization_selector"].selector.setCurrentText("Second order interactions")
        process_events()
        self._widgets["visualization_selector"].selector.setCurrentText("Second order interactions list")
        process_events()
        self._widgets["visualization_selector"].selector.setCurrentText("Third order interactions list")
        process_events()

    def test_estimation(self):
        load_project(KREL_EDA_PROJECT_FILE)

        input_paramter_table = slicer.util.getNode("Krel_results")
        self.assertIsNotNone(input_paramter_table)
        self._widgets["input_parameter_table"].setCurrentNode(input_paramter_table)

        self._widgets["visualization_selector"].selector.setCurrentText("Krel curves dispersion")
        process_events()
        self._widgets["add_filter_button"].clicked()
        process_events()
        self._widgets["filter_list_widget"].filterWidgetList[0].widget.combobox.setCurrentText("swi")
        self._widgets["filter_list_widget"].filterWidgetList[0].widget.minLineEdit.text = "0.01"
        self._widgets["filter_list_widget"].filterWidgetList[0].widget.maxLineEdit.text = "0.01142"
        process_events()
        self._widgets["apply_filters_button"].clicked()
        process_events()
        self._widgets["estimate_button"].clicked()
        process_events()

        expected_values = [
            ("input-water_viscosity", "1.0"),
            ("input-water_density", "1000.0"),
            ("input-oil_viscosity", "10.0"),
            ("input-oil_density", "900.0"),
            ("input-interfacial_tension", "30.0"),
            ("input-init_contact_model", "3"),
            ("input-init_contact_angle", "20.0"),
            ("input-init_contact_angle_range", "10.0"),
            ("input-init_contact_angle_del", "-1.0"),
            ("input-init_contact_angle_eta", "-1.0"),
            ("input-init_contact_angle_rctrl", "rand"),
            ("input-init_contact_angle_separation", "25.2"),
            ("input-second_contact_angle", "20.0"),
            ("input-second_contact_angle_range", "10.0"),
            ("input-second_contact_angle_del", "-1.0"),
            ("input-second_contact_angle_eta", "-1.0"),
            ("input-second_contact_angle_rctrl", "rand"),
            ("input-second_contact_fraction", "0.0"),
            ("input-equil_contact_model", "3"),
            ("input-equil_contact_angle", "20.0"),
            ("input-equil_contact_angle_range", "10.0"),
            ("input-equil_contact_angle_del", "-1.0"),
            ("input-equil_contact_angle_eta", "-1.0"),
            ("input-equil_contact_angle_rctrl", "rand"),
            ("input-equil_contact_angle_separation", "25.2"),
            ("input-frac_contact_angle", "20.0"),
            ("input-frac_contact_angle_range", "10.0"),
            ("input-frac_contact_angle_del", "-1.0"),
            ("input-frac_contact_angle_eta", "-1.0"),
            ("input-frac_contact_angle_rctrl", "rand"),
            ("input-frac_contact_angle_fraction", "0.0"),
            ("input-frac_contact_angle_volbased", "T"),
            ("input-frac_contact_angle_corrdiam", "7.0"),
            ("input-frac_contact_method", "corr"),
            ("input-enforced_swi_1", "0.0"),  ##
            ("input-enforced_pc_1", "200000000.0"),
            ("input-enforced_steps_1", "0.005"),
            ("input-inject_1_left", "T"),
            ("input-inject_1_right", "F"),
            ("input-produce_1_left", "F"),
            ("input-produce_1_right", "T"),
            ("input-enforced_swi_2", "1.0"),
            ("input-enforced_pc_2", "-200000000.0"),
            ("input-enforced_steps_2", "0.005"),
            ("input-inject_2_left", "T"),
            ("input-inject_2_right", "F"),
            ("input-produce_2_left", "F"),
            ("input-produce_2_right", "T"),  ##
            ("input-pore_fill_algorithm", "blunt2"),
            ("input-pore_fill_weight_a1", "0.0"),
            ("input-pore_fill_weight_a2", "0.5"),
            ("input-pore_fill_weight_a3", "1.0"),
            ("input-pore_fill_weight_a4", "2.0"),
            ("input-pore_fill_weight_a5", "5.0"),
            ("input-pore_fill_weight_a6", "10.0"),  ##
            ("input-calc_box_lower_boundary", "0.1"),
            ("input-calc_box_upper_boundary", "0.9"),
            ("input-subresolution_volume", "0.0"),
            ("input-run_third_cycle", ""),
            ("input-create_sequence", "F"),
            ("input-keep_temporary", "0"),
            ("input-max_subprocesses", "8"),
        ]
        estimated_parameters_table = self._widgets["estimated_parameters_table"]
        for i, expected_value_row in enumerate(expected_values):
            parameter_name, estimated_value = expected_value_row
            self.assertEqual(estimated_parameters_table.item(i, 0).text(), parameter_name)
            self.assertEqual(estimated_parameters_table.item(i, 1).text(), estimated_value)

        with self.assertRaises(slicer.util.MRMLNodeNotFoundException):
            slicer.util.getNode("simulation_input_parameters")

        self._widgets["create_parameter_node_button"].clicked()
        process_events()
        simulation_input_parameters = slicer.util.getNode("simulation_input_parameters")
        self.assertIsNotNone(simulation_input_parameters)

    def test_import_from_csv_sirr_format(self):
        with patch(
            "PoreNetworkKrelEda.qt.QFileDialog.getOpenFileName",
            return_value=SIRR_KREL_CSV_FILE,
        ):
            self._widgets["import_csv_button"].clicked()
            process_events()

        imported_node = self._widgets["krel_table_node_selector"].currentNode()
        self.assertIsNotNone(imported_node)
        process_events()

        # Columns should be auto-guessed from the csv header
        self.assertEqual(self._widgets["sw_column"].currentText, "Sw (%)")
        self.assertEqual(self._widgets["krw_column"].currentText, "Krw (%)")
        self.assertEqual(self._widgets["kro_column"].currentText, "Kro (%)")

        self.assertIsNotNone(self._module_widget.krel_df)

        # Values above 1.5 must be interpreted as percentages and normalized to the 0-1 range
        krel_df = self._module_widget.krel_df
        self.assertLessEqual(krel_df["Sw (%)"].max(), 1.0)
        self.assertLessEqual(krel_df["Krw (%)"].max(), 1.0)
        self.assertLessEqual(krel_df["Kro (%)"].max(), 1.0)
        np.testing.assert_allclose(krel_df["Sw (%)"].iloc[0], 1.0)
        np.testing.assert_allclose(krel_df["Krw (%)"].iloc[0], 1.0)

        # Auto-detect cycles should find the drainage (1) and imbibition (2) cycles
        self.assertEqual(self._widgets["cycle_column"].currentText, "Auto detect cycles")
        self.assertEqual(set(krel_df["cycle"].unique().tolist()), {1, 2})

        self._widgets["import_output_name"].text = "sirr_import_test"
        self._widgets["save_krel_table_button"].clicked()
        process_events()

        krel_results_node = slicer.util.getNode("Krel_results*")
        self.assertIsNotNone(krel_results_node)
        self.assertEqual(krel_results_node.GetAttribute("table_type"), "krel_simulation_results")

    def test_import_from_csv_cancelled_dialog(self):
        with patch(
            "PoreNetworkKrelEda.qt.QFileDialog.getOpenFileName",
            return_value="",
        ):
            self._widgets["import_csv_button"].clicked()
            process_events()

        self.assertIsNone(self._widgets["krel_table_node_selector"].currentNode())
