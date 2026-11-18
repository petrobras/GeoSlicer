from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, process_events
from commons.slicer.data_utils import tableNodeToDataFrame

import os
import slicer

import numpy as np
import pandas as pd

TEST_RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "Resources")
PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "pnm_production_test", "pnm_production_test.mrml")


class PoreNetworkProductionTest(LTracePluginTest):
    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = dict()

        widgets_names = [
            "Apply Button",
            "Visualization Input",
            "Input Selector",
        ]

        for widget in widgets_names:
            self._widgets[widget] = self.find_widget(widget)
            self.assertIsNotNone(self._widgets[widget])

    def test_visualization(self, generate=False):
        load_project(PROJECT_FILE)
        dir = os.path.dirname(os.path.abspath(__file__))

        permeability_table_node = slicer.util.getNode("Krel_results")
        self.assertIsNotNone(permeability_table_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(permeability_table_node)

        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        visualization_table_node = slicer.util.getNode("krel_table_cycle2_visualization")
        self.assertIsNotNone(visualization_table_node)

        visualization_selector = self._widgets["Visualization Input"]
        visualization_selector.setCurrentNode(visualization_table_node)

        # Wait for signals to trigger its callback
        process_events()

        # Check
        expected_nodes = [
            "fractional_flow_table",
            "details_table",
        ]
        for node in expected_nodes:
            self.assertIsNotNone(slicer.util.getNode(node))

        result_production_node = slicer.util.getNode("krel_table_cycle2_visualization")
        result_production = tableNodeToDataFrame(result_production_node)
        result_fraction_flow_node = slicer.util.getNode("fractional_flow_table")
        result_fraction_flow = tableNodeToDataFrame(result_fraction_flow_node)

        ref_production_path = os.path.join(dir, "ref_production.pd")
        if generate:
            result_production.to_pickle(ref_production_path)
        ref_production = pd.read_pickle(ref_production_path)

        ref_fraction_flow_path = os.path.join(dir, "ref_fraction_flow.pd")
        if generate:
            result_fraction_flow.to_pickle(ref_fraction_flow_path)
        ref_fraction_flow = pd.read_pickle(ref_fraction_flow_path)

        for reference, result in (
            (ref_production, result_production),
            (ref_fraction_flow, result_fraction_flow),
        ):
            for key in reference.keys():
                error = np.nanmax(np.abs(reference[key] - result[key]))
                assert error < 0.04, f"Error in {key}: {error}"

    def generate_visualization(self):
        self.test_visualization(generate=True)
