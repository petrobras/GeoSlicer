import slicer
import re
import os
import time
import json
import pandas as pd
import numpy as np
import shutil

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, wait, process_events, check_for_message_box
from pathlib import Path

from commons.pore_networks.report.StreamlitServer import is_server_running

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
PNM_REPORT_PROJECT = TEST_RESOURCES_DIR / "pnm_report_test" / "pnm_report_test.mrml"


class PoreNetworkWorkflowTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self) -> None:
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = dict()
        self._populate_widgets()

    def tear_down(self) -> None:
        currentPath = self._widgets["StreamlitFolderLineEdit"].currentPath
        if Path(currentPath).exists():
            shutil.rmtree(currentPath)

    def _populate_widgets(self) -> None:
        """Initialize dictionary with module's interface widgets reference."""

        self._widgets = {
            "SingleShotInputWidget": self.find_widget("SingleShotInputWidget"),
            "SensibilityTestComboBox": self.find_widget("SensibilityTestComboBox"),
            "MicroscaleDropdown": self.find_widget("MicroscaleDropdown"),
            "WellNameTextEdit": self.find_widget("WellNameTextEdit"),
            "ToggleServerButton": self.find_widget("ToggleServerButton"),
            "ServerStatusLabel": self.find_widget("ServerStatusLabel"),
            "applyButton": self.find_widget("Apply Button"),
            "StreamlitServerManager": self.find_widget("StreamlitServerManager"),
            "StreamlitFolderLineEdit": self.find_widget("StreamlitFolderLineEdit"),
            "BatchRadioButton": self.find_widget("Batch Mode Radio Button"),
            "BatchPathLineEdit": self.find_widget("BatchPathLineEdit"),
        }

        for key, widget in self._widgets.items():
            assert widget is not None, f"Missing widget: {key}"

    def test_streamlit_server(self):
        status_label = self._widgets["ServerStatusLabel"]
        server_button = self._widgets["ToggleServerButton"]
        server = self._widgets["StreamlitServerManager"]

        self.assertTrue(status_label.text == "Stopped")

        report_path = Path(slicer.app.temporaryPath) / "streamlit_test"
        report_lineedit = self._widgets["StreamlitFolderLineEdit"]
        report_lineedit.setCurrentPath(report_path)
        self.assertTrue(str(report_lineedit.currentPath) == str(report_path))

        server.openBrowser = False

        with check_for_message_box(
            "You are about to create an empty report. To see any results, please run the tool on a project or import an existing project through the Projects Manager page.",
            timeout_sec=10,
        ):
            server_button.clicked()

        index = 0
        ip_addr = None
        while ip_addr is None and index <= 10:
            wait(1)

            message = status_label.text
            pattern = r"http://(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+)"
            matches = re.findall(pattern, message)
            ip_addr = matches[0] if matches else None
            index += 1

        status = is_server_running(f"http://{ip_addr}")
        self.assertTrue(status)

        server_button.clicked()
        process_events()

        server.openBrowser = True

        self.assertTrue(status_label.text == "Stopped")

        status = is_server_running(f"http://{ip_addr}")
        self.assertTrue(not status)

    def test_complete_flow(self, generate=False, timeout_ms=1_000_000):
        load_project(PNM_REPORT_PROJECT)

        report_path = Path(slicer.app.temporaryPath) / "streamlit_test"
        report_lineedit = self._widgets["StreamlitFolderLineEdit"]
        report_lineedit.setCurrentPath(report_path)
        self.assertTrue(str(report_lineedit.currentPath) == str(report_path))

        node = slicer.util.getNode("Cropped_Label")
        self.assertIsNotNone(node)
        input_selector = self._widgets["SingleShotInputWidget"].referenceInput
        input_selector.setCurrentNode(node)
        self.assertTrue(input_selector.currentNode() == node)

        parameters = slicer.util.getNode("simulation_input_parameters")
        self.assertIsNotNone(parameters)
        parameters_selector = self._widgets["SensibilityTestComboBox"]
        parameters_selector.setCurrentNode(parameters)
        self.assertTrue(parameters_selector.currentNode() == parameters)

        microscale_model_dropdown = self._widgets["MicroscaleDropdown"]
        microscale_model_dropdown.setCurrentText("Fixed Radius")
        self.assertTrue(microscale_model_dropdown.currentText == "Fixed Radius")

        well_text_edit = self._widgets["WellNameTextEdit"]
        well_text_edit.setText("Well 1")
        self.assertTrue(well_text_edit.plainText == "Well 1")

        apply_button = self._widgets["applyButton"]
        apply_button.clicked()

        process_events()

        while not self._module_widget.logic.finished:
            time.sleep(0.2)
            process_events()

        self.assertTrue(self._module_widget.logic.extractState)
        self.assertTrue(self._module_widget.logic.kabsOneAngleState)
        self.assertTrue(self._module_widget.logic.kabsMultiAngleState)
        self.assertTrue(self._module_widget.logic.MICPState)
        self.assertTrue(self._module_widget.logic.sensibilityState)

        current_folder = os.path.abspath(os.path.join(os.path.realpath(__file__), ".."))
        streamlit_folder = Path(self._module_widget.server.report_folder) / "static"

        projects_path = os.path.join(streamlit_folder, "projects.json")
        with open(projects_path, "r") as f:
            new_dict = json.load(f)
        json_entry = new_dict[self._module_widget.logic.outputPrefix]

        if generate:
            with open(f"{current_folder}/template_json_entry.json", "w") as f:
                json.dump(json_entry, f)

        with open(f"{current_folder}/template_json_entry.json", "r") as f:
            template_entry = json.load(f)

        self.assertDictEqual(template_entry, json_entry)

        pnm_report_path = os.path.join(streamlit_folder, "folder_report.csv")
        folder_report = pd.read_csv(pnm_report_path, index_col=0)
        folder_report_entry = folder_report.iloc[-1]

        if generate:
            folder_report_entry.to_csv(f"{current_folder}/template_report_entry.pd", mode="w")

        template_folder_report_entry = pd.read_csv(f"{current_folder}/template_report_entry.pd", index_col=0).iloc[:, 0]

        left = template_folder_report_entry
        right = folder_report_entry
        for idx in left.index:
            if idx == "well":
                self.assertTrue(left[idx] == right[idx])
            else:
                np.isclose(float(left[idx]), float(right[idx]), atol=1e-3)

        scene_folder = os.path.join(streamlit_folder, self._module_widget.logic.outputPrefix)
        self.assertTrue(os.path.exists(scene_folder))

    def generate_complete_flow(self):
        self.test_complete_flow(generate=True)

    def test_checksum_files(self):
        self._module_widget.server.report_folder = Path(os.path.realpath(__file__)).parent.parent / "streamlit"
        self.assertTrue(self._module_widget.server.codeHasChanges())

    def generate_checksum_files(self):
        self._module_widget.server.generateHashFile()
