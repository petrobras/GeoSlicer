from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, process_events, wait

import os
import slicer
import time

TEST_RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "Resources")
VISUALIZE_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "pnm_visualization_test", "pnm_visualization_test.mrml")


class PoreNetworkVisualizationTest(LTracePluginTest):
    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = dict()

        widgets_names = [
            "Input Selector",
            "Step Slider",
            # "X Clip Slider",  # PL-1105
            # "Y Clip Slider",  # PL-1105
            # "Z Clip Slider",  # PL-1105
            "Sw label",
            "Pc label",
            "Krw label",
            "Kro label",
            "Run animation checkbox",
            "Speed Slider",
            # "Threshold Slider",
        ]

        for widget in widgets_names:
            self._widgets[widget] = self.find_widget(widget)
            self.assertIsNotNone(self._widgets[widget])

    def test_visualization(self):
        load_project(VISUALIZE_PROJECT_FILE)

        visualization_node = slicer.util.getNode("cycle_node_0")
        self.assertIsNotNone(visualization_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(visualization_node)
        process_events()
        time.sleep(5)

        step_slider = self._widgets["Step Slider"]

        step_slider.setValue(1)
        process_events()
        self.assertEqual(float(self._widgets["Sw label"].text), 0.96)
        self.assertEqual(float(self._widgets["Pc label"].text), 3057730.0)
        self.assertEqual(float(self._widgets["Krw label"].text), 0.644849)
        self.assertEqual(float(self._widgets["Kro label"].text), 0)

        step_slider.setValue(10)
        process_events()

        self.assertEqual(float(self._widgets["Sw label"].text), 0.785)
        self.assertEqual(float(self._widgets["Pc label"].text), 4587730.0)
        self.assertEqual(float(self._widgets["Krw label"].text), 0.110155)
        self.assertEqual(float(self._widgets["Kro label"].text), 0)

        step_slider.setValue(0)
        process_events()
        self.assertEqual(float(self._widgets["Sw label"].text), 0.97)
        self.assertEqual(float(self._widgets["Pc label"].text), 2543780.0)
        self.assertEqual(float(self._widgets["Krw label"].text), 0.745138)
        self.assertEqual(float(self._widgets["Kro label"].text), 0)

        # threshold_slider = self._widgets["Threshold Slider"]
        # threshold_slider.slider.setValues(0.1, 1.0)
        # threshold_slider.slider.setValues(0.1, 0.8)
        # threshold_slider.slider.setValues(0.0, 0.8)

        if False:  # PL-1105
            x_axis_slider = self._widgets["X Clip Slider"]
            x_axis_slider.slider.setValues(0.1, 1.0)
            x_axis_slider.slider.setValues(0.1, 0.8)
            x_axis_slider.slider.setValues(0.0, 0.8)

            y_axis_slider = self._widgets["Y Clip Slider"]
            y_axis_slider.slider.setValues(0.1, 1.0)
            y_axis_slider.slider.setValues(0.1, 0.8)
            y_axis_slider.slider.setValues(0.0, 0.8)

            z_axis_slider = self._widgets["Z Clip Slider"]
            z_axis_slider.slider.setValues(0.1, 1.0)
            z_axis_slider.slider.setValues(0.1, 0.8)
            z_axis_slider.slider.setValues(0.0, 0.8)

        # # Wait for signals to trigger its callback
        process_events()

    def test_animation(self):
        load_project(VISUALIZE_PROJECT_FILE)

        visualization_node = slicer.util.getNode("cycle_node_0")
        self.assertIsNotNone(visualization_node)

        step_slider = self._widgets["Step Slider"]

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(visualization_node)
        process_events()
        self.assertEqual(step_slider.value, 0)

        run_animation_checkbox = self._widgets["Run animation checkbox"]
        run_animation_checkbox.setChecked(True)
        wait(5)
        run_animation_checkbox.setChecked(False)
        process_events()
        self.assertGreater(step_slider.value, 10)

    def test_animation_speed(self):
        load_project(VISUALIZE_PROJECT_FILE)

        visualization_node = slicer.util.getNode("cycle_node_0")
        self.assertIsNotNone(visualization_node)

        step_slider = self._widgets["Step Slider"]

        input_selector = self._widgets["Input Selector"]
        self.assertIsNotNone(input_selector)
        input_selector.setCurrentNode(visualization_node)
        process_events()
        self.assertEqual(step_slider.value, 0)

        run_animation_checkbox = self._widgets["Run animation checkbox"]
        self.assertIsNotNone(run_animation_checkbox)

        speed_slider = self._widgets["Speed Slider"]

        # High speed
        high_speed = 100
        speed_slider.setValue(high_speed)
        run_animation_checkbox.setChecked(True)
        process_events()
        self.assertEqual(speed_slider.value, high_speed)
        self.assertEqual(run_animation_checkbox.isChecked(), True)
        wait(2)
        run_animation_checkbox.setChecked(False)
        process_events()
        self.assertEqual(run_animation_checkbox.isChecked(), False)
        high_speed_steps = step_slider.value

        # Reset
        step_slider.setValue(0)
        process_events()

        # Low speed
        low_speed = 1
        speed_slider.setValue(low_speed)
        run_animation_checkbox.setChecked(True)
        process_events()
        self.assertEqual(speed_slider.value, low_speed)
        self.assertEqual(run_animation_checkbox.isChecked(), True)
        wait(2)
        run_animation_checkbox.setChecked(False)
        process_events()
        self.assertEqual(run_animation_checkbox.isChecked(), False)
        low_speed_steps = step_slider.value

        self.assertGreater(high_speed_steps, low_speed_steps)
