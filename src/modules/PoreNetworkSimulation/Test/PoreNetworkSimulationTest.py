import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import slicer
import vtk

from MercurySimulationLib.SubscaleModelWidget import importSIRR, FixedRadiusWidget, TruncatedGaussianWidget
from commons.file_utils import load_and_parse_data
from commons.pore_networks.pnflow_parameter_defs import PARAMETERS
from commons.slicer.nodes.directory_node import DirectoryNode
from commons.pore_networks.subres_models import estimate_radius
from commons.slicer.data_utils import tableNodeToDataFrame
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, wait_cli_to_finish, process_events

TEST_RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "Resources")
SIMULATE_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "pnm_simulation_test", "pnm_simulation_test.mrml")
EXTRACT_PROJECT_FILE = (
    Path(__file__).parents[2]
    / "PoreNetworkExtractor"
    / "Test"
    / "Resources"
    / "pnm_full_extraction_test"
    / "pnm_full_extraction_test.mrml"
)
MICP_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "MICP_simulation_test", "MICP_simulation_test.mrml")
BENTHEIMER_400_FILE = os.path.join(TEST_RESOURCES_DIR, "bentheimer_400_test", "bentheimer_400_test.mrml")
ONE_PHASE_TEMPLATE_PATH = os.path.join(
    TEST_RESOURCES_DIR,
    "one_phase_template.txt",
)
TEMP_DIR = Path(tempfile.TemporaryDirectory().name)


def vtkTableToDataFrame(tableNode):
    table = tableNode.GetTable()
    num_columns = table.GetNumberOfColumns()
    data_dict = {}
    for col_idx in range(num_columns):
        col_name = table.GetColumnName(col_idx)
        col_data = vtk.util.numpy_support.vtk_to_numpy(table.GetColumn(col_idx))
        data_dict[col_name] = col_data
    df = pd.DataFrame(data_dict)
    return df


def getNodesInRelativeFolder(relativeFolder):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    folderID = shNode.GetSceneItemID()
    for folder in relativeFolder.split("/"):
        folderID = shNode.GetItemChildWithName(folderID, folder)

    nodes = []
    children = vtk.vtkIdList()
    shNode.GetItemChildren(folderID, children)
    for i in range(children.GetNumberOfIds()):
        childID = children.GetId(i)
        node = shNode.GetItemDataNode(childID)
        nodes.append(node)

    return folderID, nodes


class PoreNetworkSimulationTest(LTracePluginTest):
    def pre_setup(self):
        slicer.mrmlScene.Clear(0)

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = dict()

        widgets_names = [
            "Simulation Selector",
            "Apply Button",
            "Input Selector",
            "Snapshot Selector",
            "Kabs multiangle",
            "Multiangle Steps",
            "init_contact_angle_start",
            "init_contact_angle_stop",
            "init_contact_angle_step",
            "interfacial_tension_start",
            "interfacial_tension_stop",
            "interfacial_tension_step",
            "StatusLabel",
            "create_sequence",
            "keep_temporary",
            "Parameter input",
            "Parameter input load button",
            "Subscale Model Selector",
            "Pressure Curve Selector",
            "Throat Radius Curve Selector",
            "Output Prefix",
            "Simulator Selector",
            "max_subprocesses_entry",
            "pore_fill_algorithm_cbox",
            "Visualization checkbox",
            "Pressure drop",
            "Fluid viscosity",
            "create_drainage_snapshot",
            "enforced_swi_1_start",
            "enforced_swi_2_start",
        ]

        for widget in widgets_names:
            self._widgets[widget] = self.find_widget(widget)
            self.assertIsNotNone(self._widgets[widget])

        TEMP_DIR.mkdir(parents=True, exist_ok=True)

    def tear_down(self):
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)

    def test_one_phase_simulation(self):
        load_project(EXTRACT_PROJECT_FILE)

        pore_table_node = slicer.util.getNode("ExpectedResult_pore_table")
        self.assertIsNotNone(pore_table_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("One-phase")

        visualization_checkbox = self._widgets["Visualization checkbox"]
        visualization_checkbox.setChecked(True)

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
            "flow_rate",
            "permeability",
        ]
        for node in expected_nodes:
            self.assertIsNotNone(slicer.util.getNode(node))

        expected_values = []
        with open(ONE_PHASE_TEMPLATE_PATH, "r") as file:
            for line in file:
                expected_values.append(float(line.strip()))

        permeability_table = slicer.util.getNode("permeability")
        flow_table = slicer.util.getNode("flow_rate")

        for i in range(3):
            self.assertAlmostEqual(
                permeability_table.GetTable().GetValue(0, i).ToFloat(), expected_values[2 * i], delta=1
            )
            self.assertAlmostEqual(flow_table.GetTable().GetValue(0, i).ToFloat(), expected_values[2 * i + 1], delta=1)

        # Check model bounds
        bounds = [0] * 6
        refNode = pore_table_node.GetNodeReference("watershed")
        refNode.GetBounds(bounds)
        bounds_array = np.array(bounds)

        results_folderId, results_nodes = getNodesInRelativeFolder(
            "Micro CT/Snow Results/ExpectedResult_pore_table_Single_Phase_PN_Simulation/Visualization models/z-z folder"
        )
        pressure_node = results_nodes[0]
        boundsmodel = pressure_node.GetPolyData().GetBounds()
        boundsmodel_array = np.array(boundsmodel)

        diff = np.abs(boundsmodel_array - bounds_array).sum()

        self.assertLess(diff, 0.5)

    def test_one_phase_simulation_pressure_viscosity(self):
        load_project(EXTRACT_PROJECT_FILE)

        pore_table_node = slicer.util.getNode("ExpectedResult_pore_table")
        self.assertIsNotNone(pore_table_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("One-phase")

        pressure_drop = self._widgets["Pressure drop"]
        pressure_drop.text = "202650"

        fluid_viscosity = self._widgets["Fluid viscosity"]
        fluid_viscosity.text = "2.0"

        visualization_checkbox = self._widgets["Visualization checkbox"]
        visualization_checkbox.setChecked(True)

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
            "flow_rate",
            "permeability",
        ]
        for node in expected_nodes:
            self.assertIsNotNone(slicer.util.getNode(node))

        expected_values = []
        with open(ONE_PHASE_TEMPLATE_PATH, "r") as file:
            for line in file:
                expected_values.append(float(line.strip()))

        permeability_table = slicer.util.getNode("permeability")
        flow_table = slicer.util.getNode("flow_rate")

        for i in range(3):
            self.assertAlmostEqual(
                permeability_table.GetTable().GetValue(0, i).ToFloat(), expected_values[2 * i], delta=1
            )
            self.assertAlmostEqual(flow_table.GetTable().GetValue(0, i).ToFloat(), expected_values[2 * i + 1], delta=1)

        # Check model bounds
        bounds = [0] * 6
        refNode = pore_table_node.GetNodeReference("watershed")
        refNode.GetBounds(bounds)
        bounds_array = np.array(bounds)

        results_folderId, results_nodes = getNodesInRelativeFolder(
            "Micro CT/Snow Results/ExpectedResult_pore_table_Single_Phase_PN_Simulation/Visualization models/z-z folder"
        )
        pressure_node = results_nodes[0]
        boundsmodel = pressure_node.GetPolyData().GetBounds()
        boundsmodel_array = np.array(boundsmodel)

        diff = np.abs(boundsmodel_array - bounds_array).sum()

        self.assertLess(diff, 0.5)

    def test_multiangle_simulation(self):
        load_project(EXTRACT_PROJECT_FILE)

        pore_table_node = slicer.util.getNode("ExpectedResult_pore_table")
        self.assertIsNotNone(pore_table_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        angles_selector = self._widgets["Kabs multiangle"]
        angles_selector.setCurrentIndex(1)

        steps_edit = self._widgets["Multiangle Steps"]
        steps_edit.text = str(10)

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
            "multiangle_model",
            "multiangle_sphere_model",
            "multiangle_plane_model",
            "multiangle_arrow_model",
        ]
        for node in expected_nodes:
            self.assertIsNotNone(slicer.util.getNode(node))

    def test_two_phase_single_simulation(self):
        # Start simulation
        load_project(SIMULATE_PROJECT_FILE)

        pore_table_node = slicer.util.getNode("Segmentation_Inspector_LabelMap_pore_table")
        self.assertIsNotNone(pore_table_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("Two-phase")

        simulator_selector = self._widgets["Simulator Selector"]
        simulator_selector.setCurrentText("pnflow")
        process_events()

        keep_temporary_checkbox = self._widgets["keep_temporary"]
        keep_temporary_checkbox.setChecked(True)

        patcher = patch("slicer.util.tempDirectory", new=lambda: str(TEMP_DIR))
        patcher.start()
        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        # Wait for signals to trigger its callback
        process_events()
        cli_node = self._module_widget.logic.cliNode
        assert cli_node is not None
        wait_cli_to_finish(cli_node)
        self.assertTrue(cli_node.GetStatusString() == "Completed")

        patcher.stop()

        # Check temporary files
        def get_random_dir():
            for random_dir in TEMP_DIR.iterdir():
                if random_dir.is_dir():
                    return random_dir
            return None

        def regex_search(filename, regex):
            import re

            pattern = re.compile(regex)

            for i, line in enumerate(open(filename)):
                for match in re.finditer(pattern, line):
                    return True
            return False

        random_dir = get_random_dir()
        self.assertIsNotNone(random_dir)
        self.assertTrue(Path(random_dir / "input.txt").exists(), msg=random_dir.name)
        self.assertTrue(Path(random_dir / "Image_link1.dat").exists())
        self.assertTrue(Path(random_dir / "Image_link2.dat").exists())
        self.assertTrue(Path(random_dir / "Image_node1.dat").exists())
        self.assertTrue(Path(random_dir / "Image_node2.dat").exists())

        self.assertTrue(regex_search(Path(random_dir / "input.txt"), r"WaterOilInterface\s+0.03;"))
        self.assertTrue(regex_search(Path(random_dir / "input.txt"), r"Water\s+0.001\s+1\s+1000.0;"))
        self.assertTrue(regex_search(Path(random_dir / "input.txt"), r"Oil\s+0.01\s+1\s+900.0;"))

    def test_two_phase_py_pore_flow_simulation(self):
        # Start simulation
        load_project(SIMULATE_PROJECT_FILE)

        pore_table_node = slicer.util.getNode("Segmentation_Inspector_LabelMap_pore_table")
        self.assertIsNotNone(pore_table_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("Two-phase")

        simulator_selector = self._widgets["Simulator Selector"]
        simulator_selector.setCurrentText("py_pore_flow")

        process_events()

        keep_temporary_checkbox = self._widgets["keep_temporary"]
        keep_temporary_checkbox.setChecked(True)

        patcher = patch("slicer.util.tempDirectory", new=lambda: str(TEMP_DIR))
        patcher.start()
        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        # Wait for signals to trigger its callback
        process_events()
        cli_node = self._module_widget.logic.cliNode
        assert cli_node is not None
        wait_cli_to_finish(cli_node)
        self.assertTrue(cli_node.GetStatusString() == "Completed")

        patcher.stop()

        # Check if temporary files were kept
        for random_dir in TEMP_DIR.iterdir():
            if random_dir.is_dir():
                self.assertTrue(Path(random_dir / "input.txt").exists(), msg=random_dir.name)
                self.assertTrue(Path(random_dir / "Image_link1.dat").exists())
                self.assertTrue(Path(random_dir / "Image_link2.dat").exists())
                self.assertTrue(Path(random_dir / "Image_node1.dat").exists())
                self.assertTrue(Path(random_dir / "Image_node2.dat").exists())

    def _run_two_phase_with_diagnostics(self, level):
        """Run the reference two-phase simulation at a diagnostics level, return its directory."""
        load_project(SIMULATE_PROJECT_FILE)

        pore_table_node = slicer.util.getNode("Segmentation_Inspector_LabelMap_pore_table")
        self.assertIsNotNone(pore_table_node)

        self._widgets["Input Selector"].setCurrentNode(pore_table_node)
        self._widgets["Simulation Selector"].setCurrentText("Two-phase")
        self._widgets["Simulator Selector"].setCurrentText("py_pore_flow")
        process_events()

        self._widgets["diagnostics_level_cbox"].setCurrentText(level)
        process_events()

        self._widgets["Apply Button"].clicked()
        process_events()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)
        wait_cli_to_finish(cli_node)
        self.assertEqual(cli_node.GetStatusString(), "Completed")
        process_events()

        directory_nodes = [
            node for node in slicer.util.getNodesByClass("vtkMRMLTransformNode") if DirectoryNode.isDirectoryNode(node)
        ]
        self.assertEqual(len(directory_nodes), 1, msg="expected exactly one diagnostics directory node")

        diagnostics_dir = DirectoryNode(directory_nodes[0]).getDirPath()
        self.assertTrue(diagnostics_dir.is_dir())
        return diagnostics_dir

    def test_two_phase_diagnostics_off_writes_nothing(self):
        load_project(SIMULATE_PROJECT_FILE)

        pore_table_node = slicer.util.getNode("Segmentation_Inspector_LabelMap_pore_table")
        self._widgets["Input Selector"].setCurrentNode(pore_table_node)
        self._widgets["Simulation Selector"].setCurrentText("Two-phase")
        self._widgets["Simulator Selector"].setCurrentText("py_pore_flow")
        process_events()

        # Off is the default
        self.assertEqual(self._widgets["diagnostics_level_cbox"].currentText, "Off")

        self._widgets["Apply Button"].clicked()
        process_events()
        cli_node = self._module_widget.logic.cliNode
        wait_cli_to_finish(cli_node)
        self.assertEqual(cli_node.GetStatusString(), "Completed")
        process_events()

        directory_nodes = [
            node for node in slicer.util.getNodesByClass("vtkMRMLTransformNode") if DirectoryNode.isDirectoryNode(node)
        ]
        self.assertEqual(directory_nodes, [])

    def test_two_phase_diagnostics_basic_keeps_only_the_aggregates(self):
        diagnostics_dir = self._run_two_phase_with_diagnostics("Basic")

        self.assertTrue((diagnostics_dir / "aggregates.npz").exists())
        self.assertTrue((diagnostics_dir / "diagnostics_manifest.json").exists())
        self.assertTrue((diagnostics_dir / "network.npz").exists())

        manifest = json.loads((diagnostics_dir / "diagnostics_manifest.json").read_text())
        self.assertEqual(manifest["level"], "basic")
        self.assertIn("throat", manifest["aggregates"])

        # the per element spool exists only during the run
        self.assertEqual(list(diagnostics_dir.glob("diagnostics_spool_*.dat")), [])
        self.assertEqual(list(diagnostics_dir.glob("diagnostics_throats_floats_*.dat")), [])

    def test_two_phase_diagnostics_complete_keeps_the_per_element_data(self):
        diagnostics_dir = self._run_two_phase_with_diagnostics("Complete")

        self.assertTrue((diagnostics_dir / "info.dat").exists())
        self.assertTrue((diagnostics_dir / "network.npz").exists())
        self.assertTrue(list(diagnostics_dir.glob("diagnostics_throats_floats_*.dat")))
        self.assertTrue(list(diagnostics_dir.glob("diagnostics_pores_floats_*.dat")))

        manifest = json.loads((diagnostics_dir / "diagnostics_manifest.json").read_text())
        self.assertEqual(manifest["level"], "complete")

    def test_two_phase_simulation(self, generate=True, timeout_ms=500000):
        load_project(SIMULATE_PROJECT_FILE)
        dir = os.path.dirname(os.path.abspath(__file__))

        pore_table_node = slicer.util.getNode("Segmentation_Inspector_LabelMap_pore_table")
        self.assertIsNotNone(pore_table_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("Two-phase")

        process_events()

        contact_angle_widget = self._widgets["init_contact_angle_start"]
        contact_angle_widget.text = str(90)
        contact_angle_widget = self._widgets["init_contact_angle_stop"]
        contact_angle_widget.text = str(100)
        contact_angle_widget = self._widgets["init_contact_angle_step"]
        contact_angle_widget.text = str(2)

        animation_checkbox = self._widgets["create_sequence"]
        animation_checkbox.setChecked(True)

        self._widgets["pore_fill_algorithm_cbox"].setCurrentIndex(1)  # blunt2

        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        # Wait for signals to trigger its callback
        process_events()
        cli_node = self._module_widget.logic.cliNode
        assert cli_node is not None
        wait_cli_to_finish(cli_node)
        self.assertTrue(cli_node.GetStatusString() == "Completed")

        # Check
        expected_nodes = [
            "krel_table_cycle1",
            "krel_table_cycle2",
            "krel_table_cycle3",
            "Krel_results",
            "cycle_node_0",
            "cycle_node_1",
        ]
        for node in expected_nodes:
            self.assertIsNotNone(slicer.util.getNode(node))

        result_cycle_tables = []
        result_cycle_tables.append(tableNodeToDataFrame(slicer.util.getNode("krel_table_cycle1")))
        result_cycle_tables.append(tableNodeToDataFrame(slicer.util.getNode("krel_table_cycle2")))
        result_cycle_tables.append(tableNodeToDataFrame(slicer.util.getNode("krel_table_cycle3")))

        if generate:
            for idx, cycle in enumerate(result_cycle_tables):
                path = os.path.join(dir, f"krel_table_cycle{idx + 1}.pd")
                cycle.to_pickle(path)

        ref_cycle_tables = [pd.read_pickle(os.path.join(dir, f"krel_table_cycle{idx + 1}.pd")) for idx in range(3)]

        for i, order in enumerate((slice(None, None, -1), slice(None)), start=1):
            data_table = result_cycle_tables[i].iloc[order]
            ref_table = ref_cycle_tables[i].iloc[order]

            data_sw = data_table["Sw"].to_numpy().astype(float)
            data_krw = data_table["Krw_0"].to_numpy().astype(float)
            data_kro = data_table["Kro_0"].to_numpy().astype(float)

            sorted_indices = np.argsort(data_sw)
            data_sw = data_sw[sorted_indices]
            data_krw = data_krw[sorted_indices]
            data_kro = data_kro[sorted_indices]

            ref_sw = ref_table["Sw"].to_numpy().astype(float)
            ref_krw = ref_table["Krw_0"].to_numpy().astype(float)
            ref_kro = ref_table["Kro_0"].to_numpy().astype(float)

            data_krw_interpolate = np.interp(ref_sw, data_sw, data_krw)
            data_kro_interpolate = np.interp(ref_sw, data_sw, data_kro)

            krw_error = np.nanmean((ref_krw - data_krw_interpolate) ** 2)
            kro_error = np.nanmean((ref_kro - data_kro_interpolate) ** 2)

            self.assertLess(krw_error, 0.01)
            self.assertLess(kro_error, 0.01)

        # Check animations
        cycle_node = slicer.util.getNode("cycle_node_0")
        point_data = cycle_node.GetPolyData().GetPointData()
        array_names = [point_data.GetArrayName(i) for i in range(point_data.GetNumberOfArrays())]
        saturations = [i for i in array_names if i.startswith("saturation_")]
        condWs = [i for i in array_names if i.startswith("condW_")]
        condOs = [i for i in array_names if i.startswith("condO_")]
        self.assertTrue(len(condWs) == len(saturations))
        self.assertTrue(len(condOs) == len(saturations))

    def test_two_phase_simulation_pressure_curve(self, generate=True, timeout_ms=500000):
        load_project(MICP_PROJECT_FILE)
        dir = os.path.dirname(os.path.abspath(__file__))

        pore_table_node = slicer.util.getNode("Multiscale_PN_pore_table")
        self.assertIsNotNone(pore_table_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("Two-phase")

        self._widgets["Subscale Model Selector"] = self.find_widget("Subscale Model Selector", only_visible=True)
        self._widgets["Subscale Model Selector"].setCurrentText("Pressure Curve")
        self.assertTrue(self._widgets["Subscale Model Selector"].currentText == "Pressure Curve")

        pressure_table_node = slicer.util.getNode("MICP_table")
        self.assertIsNotNone(pressure_table_node)

        self._widgets["Pressure Curve Selector"] = self.find_widget("Pressure Curve Selector", only_visible=True)

        self._widgets["Pressure Curve Selector"].setCurrentNode(pressure_table_node)
        self.assertTrue(self._widgets["Pressure Curve Selector"].currentNode() == pressure_table_node)

        process_events()

        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        # Wait for signals to trigger its callback
        process_events()
        cli_node = self._module_widget.logic.cliNode
        assert cli_node is not None
        wait_cli_to_finish(cli_node)
        self.assertTrue(cli_node.GetStatusString() == "Completed")

        # Check
        expected_nodes = [
            "krel_table_cycle1",
            "krel_table_cycle2",
            "krel_table_cycle3",
            "Krel_results",
        ]
        for node in expected_nodes:
            self.assertIsNotNone(slicer.util.getNode(node))

        result_cycle_tables = []
        result_cycle_tables.append(tableNodeToDataFrame(slicer.util.getNode("krel_table_cycle1")))
        result_cycle_tables.append(tableNodeToDataFrame(slicer.util.getNode("krel_table_cycle2")))
        result_cycle_tables.append(tableNodeToDataFrame(slicer.util.getNode("krel_table_cycle3")))

        if generate:
            for idx, cycle in enumerate(result_cycle_tables):
                path = os.path.join(dir, f"pressure_curve_krel_table_cycle{idx + 1}.pd")
                cycle.to_pickle(path)

        ref_cycle_tables = [
            pd.read_pickle(os.path.join(dir, f"pressure_curve_krel_table_cycle{idx + 1}.pd")) for idx in range(3)
        ]

        for i, order in enumerate((slice(None, None, -1), slice(None)), start=1):
            data_table = result_cycle_tables[i].iloc[order]
            ref_table = ref_cycle_tables[i].iloc[order]

            data_sw = data_table["Sw"].to_numpy(dtype=float)
            data_krw = data_table["Krw_0"].to_numpy(dtype=float)
            data_kro = data_table["Kro_0"].to_numpy(dtype=float)

            sorted_indices = np.argsort(data_sw)
            data_sw = data_sw[sorted_indices]
            data_krw = data_krw[sorted_indices]
            data_kro = data_kro[sorted_indices]

            # Do the same for the reference tables just to be safe
            ref_sw = ref_table["Sw"].to_numpy(dtype=float)
            ref_krw = ref_table["Krw_0"].to_numpy(dtype=float)
            ref_kro = ref_table["Kro_0"].to_numpy(dtype=float)

            data_krw_interpolate = np.interp(ref_sw, data_sw, data_krw)
            data_kro_interpolate = np.interp(ref_sw, data_sw, data_kro)
            krw_error = np.nanmean((ref_krw - data_krw_interpolate) ** 2)
            kro_error = np.nanmean((ref_kro - data_kro_interpolate) ** 2)

            self.assertLess(krw_error, 0.01)
            self.assertLess(kro_error, 0.01)

    def test_two_phase_simulation_reusing_drainage(self):
        load_project(SIMULATE_PROJECT_FILE)

        pore_table_node = slicer.util.getNode("Segmentation_Inspector_LabelMap_pore_table")
        self.assertIsNotNone(pore_table_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("Two-phase")

        simulator_selector = self._widgets["Simulator Selector"]
        simulator_selector.setCurrentText("py_pore_flow")

        process_events()

        contact_angle_widget = self._widgets["init_contact_angle_start"]
        contact_angle_widget.text = str(90)
        contact_angle_widget = self._widgets["init_contact_angle_stop"]
        contact_angle_widget.text = str(100)
        contact_angle_widget = self._widgets["init_contact_angle_step"]
        contact_angle_widget.text = str(5)

        max_subprocesses_widget = self._widgets["max_subprocesses_entry"]
        max_subprocesses_widget.setValue(2)

        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        # Wait for signals to trigger its callback
        process_events()
        cli_node = self._module_widget.logic.cliNode
        assert cli_node is not None
        wait_cli_to_finish(cli_node)
        self.assertTrue(cli_node.GetStatusString() == "Completed")

        # Check
        expected_nodes = [
            "krel_table_cycle1",
            "krel_table_cycle2",
            "krel_table_cycle3",
            "Krel_results",
        ]
        for node in expected_nodes:
            self.assertIsNotNone(slicer.util.getNode(node))

    def test_two_phase_simulation_snapshot_create(self, generate=True, timeout_ms=500000):
        load_project(SIMULATE_PROJECT_FILE)

        pore_table_node = slicer.util.getNode("Segmentation_Inspector_LabelMap_pore_table")
        self.assertIsNotNone(pore_table_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("Two-phase")

        simulator_selector = self._widgets["Simulator Selector"]
        simulator_selector.setCurrentText("py_pore_flow")

        process_events()

        contact_angle_widget = self._widgets["init_contact_angle_start"]
        contact_angle_widget.text = str(90)
        contact_angle_widget = self._widgets["init_contact_angle_stop"]
        contact_angle_widget.text = str(100)
        contact_angle_widget = self._widgets["init_contact_angle_step"]
        contact_angle_widget.text = str(2)

        snapshot_checkbox = self._widgets["create_drainage_snapshot"]
        snapshot_checkbox.setChecked(True)

        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        # Wait for signals to trigger its callback
        process_events()
        cli_node = self._module_widget.logic.cliNode
        assert cli_node is not None
        wait_cli_to_finish(cli_node)
        self.assertTrue(cli_node.GetStatusString() == "Completed")

        # Check
        expected_nodes = [
            "drainage_snapshot",
        ]
        for node in expected_nodes:
            self.assertIsNotNone(slicer.util.getNode(node))

        self.assertEqual(len(slicer.util.dataframeFromTable(slicer.util.getNode("krel_table_cycle1"))), 201)
        self.assertEqual(len(slicer.util.dataframeFromTable(slicer.util.getNode("krel_table_cycle2"))), 201)
        self.assertEqual(len(slicer.util.dataframeFromTable(slicer.util.getNode("krel_table_cycle3"))), 201)

    def test_two_phase_simulation_snapshot_use(self, generate=True, timeout_ms=500000):
        load_project(SIMULATE_PROJECT_FILE)

        pore_table_node = slicer.util.getNode("Segmentation_Inspector_LabelMap_pore_table")
        self.assertIsNotNone(pore_table_node)
        snapshot_node = slicer.util.getNode("drainage_snapshot")
        self.assertIsNotNone(snapshot_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        snapshot_selector = self._widgets["Snapshot Selector"]
        snapshot_selector.setCurrentNode(snapshot_node)

        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("Two-phase")

        simulator_selector = self._widgets["Simulator Selector"]
        simulator_selector.setCurrentText("py_pore_flow")

        process_events()

        contact_angle_widget = self._widgets["init_contact_angle_start"]
        contact_angle_widget.text = str(90)
        contact_angle_widget = self._widgets["init_contact_angle_stop"]
        contact_angle_widget.text = str(100)
        contact_angle_widget = self._widgets["init_contact_angle_step"]
        contact_angle_widget.text = str(2)

        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        # Wait for signals to trigger its callback
        process_events()
        cli_node = self._module_widget.logic.cliNode
        assert cli_node is not None
        wait_cli_to_finish(cli_node)
        self.assertEqual(cli_node.GetStatusString(), "Completed")

        # Check
        expected_nodes = [
            "krel_table_cycle1",
            "krel_table_cycle2",
            "krel_table_cycle3",
            "Krel_results",
        ]
        for node in expected_nodes:
            self.assertIsNotNone(slicer.util.getNode(node))

        self.assertEqual(len(slicer.util.dataframeFromTable(slicer.util.getNode("krel_table_cycle1"))), 0)
        self.assertEqual(len(slicer.util.dataframeFromTable(slicer.util.getNode("krel_table_cycle2"))), 201)
        self.assertEqual(len(slicer.util.dataframeFromTable(slicer.util.getNode("krel_table_cycle3"))), 201)

    def test_two_phase_simulation_limited_swi(self, generate=True, timeout_ms=500000):
        load_project(SIMULATE_PROJECT_FILE)

        pore_table_node = slicer.util.getNode("Segmentation_Inspector_LabelMap_pore_table")
        self.assertIsNotNone(pore_table_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("Two-phase")

        process_events()

        contact_angle_widget = self._widgets["init_contact_angle_start"]
        contact_angle_widget.text = str(100)

        contact_angle_widget = self._widgets["enforced_swi_1_start"]
        contact_angle_widget.text = str(0.4)
        contact_angle_widget = self._widgets["enforced_swi_2_start"]
        contact_angle_widget.text = str(0.8)

        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        # Wait for signals to trigger its callback
        process_events()
        cli_node = self._module_widget.logic.cliNode
        assert cli_node is not None
        wait_cli_to_finish(cli_node)
        self.assertTrue(cli_node.GetStatusString() == "Completed")

        # Check
        expected_nodes = [
            "krel_table_cycle1",
            "krel_table_cycle2",
            "krel_table_cycle3",
        ]
        for node in expected_nodes:
            self.assertIsNotNone(slicer.util.getNode(node))

        table_cycle_1 = tableNodeToDataFrame(slicer.util.getNode("krel_table_cycle1"))
        table_cycle_2 = tableNodeToDataFrame(slicer.util.getNode("krel_table_cycle2"))
        table_cycle_3 = tableNodeToDataFrame(slicer.util.getNode("krel_table_cycle3"))

        # Define a helper function to safely check the DataFrame and assert the values
        def assert_pc0_nan_status(df, sw_target, df_name, expect_nan):
            # 1. Filter the dataframe
            sw_array = df["Sw"].astype(float)
            filtered_df = df[np.isclose(sw_array, sw_target)]

            # 2. Assert the row actually exists before trying to read it
            self.assertFalse(
                filtered_df.empty,
                f"Validation Error: Could not find Sw value close to {sw_target} in {df_name}. "
                f"Available Sw values are: {sw_array.tolist()}",
            )

            # 3. Extract the value safely
            pc0_val = float(filtered_df["Pc_0"].iloc[0])

            # 4. Assert the NaN status with clear messages
            if expect_nan:
                self.assertTrue(
                    np.isnan(pc0_val), f"[{df_name}] Expected 'Pc_0' to be NaN at Sw={sw_target}, but got {pc0_val}."
                )
            else:
                self.assertFalse(
                    np.isnan(pc0_val),
                    f"[{df_name}] Expected 'Pc_0' to be a valid number at Sw={sw_target}, but got NaN.",
                )

        # Check drainage min Swi
        assert_pc0_nan_status(table_cycle_1, 0.385, "table_cycle_1", expect_nan=True)
        assert_pc0_nan_status(table_cycle_1, 0.415, "table_cycle_1", expect_nan=False)

        # Check imbibition max Swi
        assert_pc0_nan_status(table_cycle_2, 0.785, "table_cycle_2", expect_nan=False)
        assert_pc0_nan_status(table_cycle_2, 0.815, "table_cycle_2", expect_nan=True)

        # Check 2nd drainage min Swi
        assert_pc0_nan_status(table_cycle_3, 0.385, "table_cycle_3", expect_nan=True)
        assert_pc0_nan_status(table_cycle_3, 0.415, "table_cycle_3", expect_nan=False)

    def test_load_parameter_node(self):
        load_project(SIMULATE_PROJECT_FILE)

        # Set pn node
        pore_table_node = slicer.util.getNode("Segmentation_Inspector_LabelMap_pore_table")
        self.assertIsNotNone(pore_table_node)
        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        # Set two-phase
        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("Two-phase")
        process_events()

        # Set parameters node
        parameters_node = slicer.util.getNode("simulation_input_parameters")
        self.assertIsNotNone(parameters_node)
        parameters_node_selector = self._widgets["Parameter input"]
        parameters_node_selector.setCurrentNode(parameters_node)

        # Load parameters node
        parameter_node_button = self._widgets["Parameter input load button"]
        parameter_node_button.clicked()
        process_events()

        interfacial_tension_widget = self._widgets["interfacial_tension_start"]
        interfacial_tension_widget.text = str(10)
        interfacial_tension_widget = self._widgets["interfacial_tension_stop"]
        interfacial_tension_widget.text = str(1000)
        interfacial_tension_widget = self._widgets["interfacial_tension_step"]
        interfacial_tension_widget.text = str(3)

    def test_logarithmic_steps(self):
        load_project(SIMULATE_PROJECT_FILE)

        # Set pn node
        pore_table_node = slicer.util.getNode("Segmentation_Inspector_LabelMap_pore_table")
        self.assertIsNotNone(pore_table_node)
        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        # Set two-phase
        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("Two-phase")
        process_events()

        # Set parameters node
        parameters_node = slicer.util.getNode("simulation_input_parameters")
        self.assertIsNotNone(parameters_node)
        parameters_node_selector = self._widgets["Parameter input"]
        parameters_node_selector.setCurrentNode(parameters_node)
        parameter_node_button = self._widgets["Parameter input load button"]
        parameter_node_button.clicked()
        process_events()

        # Run simulation
        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()
        process_events()
        cli_node = self._module_widget.logic.cliNode
        assert cli_node is not None
        wait_cli_to_finish(cli_node)
        assert cli_node.GetStatusString() == "Completed", f"Actual: {cli_node.GetStatusString()}"

        # Check results
        krel_results_node = slicer.util.getNode("Krel_results")
        self.assertIsNotNone(krel_results_node)

        df = slicer.util.dataframeFromTable(krel_results_node)
        self.assertTrue("input-interfacial_tension" in df.columns)
        interfacial_tension_values = np.sort(np.array(df["input-interfacial_tension"]))
        self.assertTrue((interfacial_tension_values == np.array([10.0, 100.0, 1000.0])).all())

    def test_micp_fixed_radius_simulation(self, generate=False):
        subscale_model = "Fixed Radius"
        load_project(MICP_PROJECT_FILE)
        dir = os.path.dirname(os.path.abspath(__file__))

        self._widgets["Simulation Selector"].setCurrentIndex(-1)
        self._widgets["Simulation Selector"].setCurrentText("Mercury injection")
        self.assertTrue(self._widgets["Simulation Selector"].currentText == "Mercury injection")

        process_events()
        from MercurySimulationLib.MercurySimulationLogic import MercurySimulationLogic

        self.assertIsInstance(self._module_widget.logic, MercurySimulationLogic)
        self._widgets["Subscale Model Selector"] = self.find_widget("Subscale Model Selector", only_visible=True)

        pore_table_node = slicer.util.getNode("Full Res_pore_table")
        self.assertIsNotNone(pore_table_node)

        self._widgets["Input Selector"].setCurrentNode(pore_table_node)
        self.assertTrue(self._widgets["Input Selector"].currentNode() == pore_table_node)

        self._widgets["Subscale Model Selector"].setCurrentText(subscale_model)
        self.assertTrue(self._widgets["Subscale Model Selector"].currentText == subscale_model)

        self._widgets["Output Prefix"].setText(subscale_model)
        self.assertTrue(self._widgets["Output Prefix"].text == subscale_model)

        self._widgets["Apply Button"].clicked()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)

        wait_cli_to_finish(cli_node)
        assert cli_node.GetStatusString() == "Completed", (
            f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
        )

        results_folderId, results_nodes = getNodesInRelativeFolder(f"{subscale_model} Mercury Injection Simulation")
        self.assertEqual(len(results_nodes), 13)

        results_table = [i for i in slicer.util.getNodesByClass("vtkMRMLTableNode") if i.GetName() == "MICP"][0]
        results_df = vtkTableToDataFrame(results_table)

        template_path = os.path.join(dir, "template_fixed_radius.pd")
        if generate:
            results_df.to_pickle(template_path)
        template_df = pd.read_pickle(template_path)

        pd.testing.assert_frame_equal(template_df, results_df)

    def test_micp_radius_distrib_simulation(self, generate=False):
        subscale_model = "Throat Radius Curve"
        load_project(MICP_PROJECT_FILE)
        dir = os.path.dirname(os.path.abspath(__file__))

        self._widgets["Simulation Selector"].setCurrentIndex(-1)
        self._widgets["Simulation Selector"].setCurrentText("Mercury injection")
        self.assertTrue(self._widgets["Simulation Selector"].currentText == "Mercury injection")

        process_events()
        from MercurySimulationLib.MercurySimulationLogic import MercurySimulationLogic

        self.assertIsInstance(self._module_widget.logic, MercurySimulationLogic)
        self._widgets["Subscale Model Selector"] = self.find_widget("Subscale Model Selector", only_visible=True)

        pore_table_node = slicer.util.getNode("Multiscale_PN_pore_table")
        self.assertIsNotNone(pore_table_node)

        self._widgets["Input Selector"].setCurrentNode(pore_table_node)
        self.assertTrue(self._widgets["Input Selector"].currentNode() == pore_table_node)

        self._widgets["Subscale Model Selector"].setCurrentText(subscale_model)
        self.assertTrue(self._widgets["Subscale Model Selector"].currentText == subscale_model)

        pressure_table_node = slicer.util.getNode("MICP_table")
        self.assertIsNotNone(pressure_table_node)

        process_events()
        self._widgets["Throat Radius Curve Selector"] = self.find_widget(
            "Throat Radius Curve Selector", only_visible=True
        )

        self._widgets["Throat Radius Curve Selector"].setCurrentNode(pressure_table_node)
        self.assertTrue(self._widgets["Throat Radius Curve Selector"].currentNode() == pressure_table_node)

        self._widgets["Output Prefix"].setText(subscale_model)
        self.assertTrue(self._widgets["Output Prefix"].text == subscale_model)

        self._widgets["Apply Button"].clicked()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)

        wait_cli_to_finish(cli_node)
        assert cli_node.GetStatusString() == "Completed", (
            f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
        )

        results_folderId, results_nodes = getNodesInRelativeFolder(f"{subscale_model} Mercury Injection Simulation")
        self.assertEqual(len(results_nodes), 13)

        results_table = [i for i in slicer.util.getNodesByClass("vtkMRMLTableNode") if i.GetName() == "MICP"][0]
        results_df = vtkTableToDataFrame(results_table)

        template_path = os.path.join(dir, "template_radius_distrib.pd")
        if generate:
            results_df.to_pickle(template_path)
        template_df = pd.read_pickle(template_path)

        pd.testing.assert_frame_equal(template_df, results_df)

    def test_micp_pressure_curve_simulation(self, generate=False):
        subscale_model = "Pressure Curve"
        load_project(MICP_PROJECT_FILE)
        dir = os.path.dirname(os.path.abspath(__file__))

        self._widgets["Simulation Selector"].setCurrentIndex(-1)
        self._widgets["Simulation Selector"].setCurrentText("Mercury injection")
        self.assertTrue(self._widgets["Simulation Selector"].currentText == "Mercury injection")

        process_events()
        from MercurySimulationLib.MercurySimulationLogic import MercurySimulationLogic

        self.assertIsInstance(self._module_widget.logic, MercurySimulationLogic)
        self._widgets["Subscale Model Selector"] = self.find_widget("Subscale Model Selector", only_visible=True)

        pore_table_node = slicer.util.getNode("Multiscale_PN_pore_table")
        self.assertIsNotNone(pore_table_node)

        self._widgets["Input Selector"].setCurrentNode(pore_table_node)
        self.assertTrue(self._widgets["Input Selector"].currentNode() == pore_table_node)

        self._widgets["Subscale Model Selector"].setCurrentText(subscale_model)
        self.assertTrue(self._widgets["Subscale Model Selector"].currentText == subscale_model)

        pressure_table_node = slicer.util.getNode("MICP_table")
        self.assertIsNotNone(pressure_table_node)

        process_events()
        self._widgets["Pressure Curve Selector"] = self.find_widget("Pressure Curve Selector", only_visible=True)

        self._widgets["Pressure Curve Selector"].setCurrentNode(pressure_table_node)
        self.assertTrue(self._widgets["Pressure Curve Selector"].currentNode() == pressure_table_node)

        self._widgets["Output Prefix"].setText(subscale_model)
        self.assertTrue(self._widgets["Output Prefix"].text == subscale_model)

        self._widgets["Apply Button"].clicked()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)

        wait_cli_to_finish(cli_node)
        assert cli_node.GetStatusString() == "Completed", (
            f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
        )

        results_folderId, results_nodes = getNodesInRelativeFolder(f"{subscale_model} Mercury Injection Simulation")
        self.assertEqual(len(results_nodes), 13)

        results_table = [i for i in slicer.util.getNodesByClass("vtkMRMLTableNode") if i.GetName() == "MICP"][0]
        results_df = vtkTableToDataFrame(results_table)

        template_path = os.path.join(dir, "template_pressure_curve.pd")
        if generate:
            results_df.to_pickle(template_path)
        template_df = pd.read_pickle(template_path)

        pd.testing.assert_frame_equal(template_df, results_df)

    def test_no_resolved_throat(self):
        subscale_model = "Throat Radius Curve"
        load_project(BENTHEIMER_400_FILE)

        self._widgets["Simulation Selector"].setCurrentText("One-phase")
        self.assertTrue(self._widgets["Simulation Selector"].currentText == "One-phase")

        pore_table_node = slicer.util.getNode("BIN_Bentheimer_Pores_400_400_400_1660nm_pore_table")
        self.assertIsNotNone(pore_table_node)

        self._widgets["Input Selector"].setCurrentNode(pore_table_node)
        self.assertTrue(self._widgets["Input Selector"].currentNode() == pore_table_node)

        self._widgets["Subscale Model Selector"].setCurrentText(subscale_model)
        self.assertTrue(self._widgets["Subscale Model Selector"].currentText == subscale_model)

        pressure_table_node = slicer.util.getNode("MICP_table")
        self.assertIsNotNone(pressure_table_node)

        self._widgets["Throat Radius Curve Selector"].setCurrentNode(pressure_table_node)
        self.assertTrue(self._widgets["Throat Radius Curve Selector"].currentNode() == pressure_table_node)

        self._widgets["Output Prefix"].setText(subscale_model)
        self.assertTrue(self._widgets["Output Prefix"].text == subscale_model)

        self._widgets["Apply Button"].clicked()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)

        wait_cli_to_finish(cli_node)
        assert cli_node.GetStatusString() == "Completed", (
            f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
        )

    def generate_all(self):
        load_project(EXTRACT_PROJECT_FILE)

        pore_table_node = slicer.util.getNode("ExpectedResult_pore_table")
        self.assertIsNotNone(pore_table_node)

        input_selector = self._widgets["Input Selector"]
        input_selector.setCurrentNode(pore_table_node)

        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("One-phase")

        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        # Wait for signals to trigger its callback
        process_events()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)

        wait_cli_to_finish(cli_node)

        # Check
        expected_nodes = [
            "flow_rate",
            "permeability",
        ]
        for node in expected_nodes:
            self.assertIsNotNone(slicer.util.getNode(node))

        expected_values = []
        permeability_table = slicer.util.getNode("permeability")
        flow_table = slicer.util.getNode("flow_rate")

        for i in range(3):
            expected_values.append(permeability_table.GetTable().GetValue(0, i).ToFloat())
            expected_values.append(flow_table.GetTable().GetValue(0, i).ToFloat())

        with open(ONE_PHASE_TEMPLATE_PATH, "w") as file:
            for number in expected_values:
                file.write(str(number) + "\n")

    def generate_micp_fixed_radius_simulation(self):
        self.test_micp_fixed_radius_simulation(generate=True)

    def generate_micp_pressure_curve_simulation(self):
        self.test_micp_pressure_curve_simulation(generate=True)

    def generate_micp_radius_distrib_simulation(self):
        self.test_micp_radius_distrib_simulation(generate=True)

    def generate_two_phase_simulation(self):
        self.test_two_phase_simulation(generate=True)

    def generate_two_phase_simulation_pressure_curve(self):
        self.test_two_phase_simulation_pressure_curve(generate=True)

    def test_import_sirr_success(self):
        # Locate SIRR.csv relative to this test file
        dir_path = os.path.dirname(os.path.abspath(__file__))

        mercury_simulation_widget = self._module_widget.mercurySimWidget
        subscale_model_widget = mercury_simulation_widget.subscaleModelWidget
        parameter_widgets = subscale_model_widget.parameter_widgets
        throat_radius_curve_combo = subscale_model_widget.parameter_widgets["Throat Radius Curve"].throatRadiusSelector
        pressure_curve_combo = subscale_model_widget.parameter_widgets["Pressure Curve"].pressureCurveSelector
        sirr_input_selector = mercury_simulation_widget.getSirrSelector()

        siff_dirpath = Path(dir_path) / "Resources" / "sirr_files"
        assert siff_dirpath.exists(), f"SIRR test files directory not found at {siff_dirpath}"
        assert siff_dirpath.is_dir(), f"SIRR test files path is not a directory: {siff_dirpath}"

        for test_path in siff_dirpath.iterdir():
            test_file = test_path.name
            assert test_path.exists(), f"Test file not found at {test_file}"
            importSIRR(test_path, parameter_widgets, sirr_input_selector)

            process_events()
            table_node = sirr_input_selector.currentNode()
            assert table_node is not None, "No table node returned after import"
            assert table_node.GetName() == "SIRR imported MICP", "Unexpected table node name"
            assert pressure_curve_combo.currentNode() == table_node, "Pressure curve selector not updated"
            assert throat_radius_curve_combo.currentNode() == table_node, "Throat radius selector not updated"

            # Convert back to dataframe for validation
            df = slicer.util.dataframeFromTable(table_node)

            # Expected columns
            expected_columns = {"pc", "snwp", "dsn", "radii"}
            missing = expected_columns - set(df.columns)
            assert not missing, f"Missing expected columns: {missing} on file {test_file}"

            assert len(df) > 0, f"Imported dataframe is empty on file {test_file}"
            assert df["pc"].dtype in [
                np.float64,
                np.float32,
            ], f"pc column has incorrect dtype {df['pc'].dtype} on file {test_file}"
            assert df["snwp"].dtype in [
                np.float64,
                np.float32,
            ], f"snwp column has incorrect dtype {df['snwp'].dtype} on file {test_file}"

            # Check unit conversion (psi → Pa)
            raw_df = load_and_parse_data(test_path, filter_empty_columns=True)
            first_pc_psi = raw_df["Pressão capilar(psi)"].iloc[0]
            expected_pc_pa = first_pc_psi * 6894.75729

            print(
                f"First pc in psi: {first_pc_psi}, expected in Pa: {expected_pc_pa}, actual in df: {df['pc'].iloc[0]}, actual dtype: {df['pc'].dtype}"
            )
            assert np.isclose(df["pc"].iloc[0], expected_pc_pa, rtol=1e-5), (
                f"Pressure conversion failed on file {test_file}"
            )

            # Check saturation normalization
            first_snwp = raw_df["Saturação de Hg (%)"].iloc[0]
            assert np.isclose(df["snwp"].iloc[0], first_snwp / 100, rtol=1e-6), (
                f"Saturation normalization failed on file {test_file}"
            )

            # Check radius estimation
            expected_radius = (
                estimate_radius(df["pc"]).iloc[0]
                if hasattr(estimate_radius(df["pc"]), "iloc")
                else estimate_radius(df["pc"])[0]
            )
            assert np.isclose(df["radii"].iloc[0], expected_radius, rtol=1e-6), (
                f"Radius estimation mismatch on file {test_file}"
            )

    def test_micp_flow_and_visualization(self):
        load_project(MICP_PROJECT_FILE)

        # 1. Setup MICP Simulation
        self._widgets["Simulation Selector"].setCurrentIndex(-1)
        self._widgets["Simulation Selector"].setCurrentText("Mercury injection")
        process_events()
        from MercurySimulationLib.MercurySimulationLogic import MercurySimulationLogic

        self.assertIsInstance(self._module_widget.logic, MercurySimulationLogic)

        pore_table_node = slicer.util.getNode("Multiscale_PN_pore_table")
        self.assertIsNotNone(pore_table_node)
        self._widgets["Input Selector"].setCurrentNode(pore_table_node)

        self._widgets["Subscale Model Selector"] = self.find_widget("Subscale Model Selector", only_visible=True)
        self._widgets["Subscale Model Selector"].setCurrentText("Pressure Curve")

        pressure_table_node = slicer.util.getNode("MICP_table")
        self.assertIsNotNone(pressure_table_node)
        self._widgets["Pressure Curve Selector"] = self.find_widget("Pressure Curve Selector", only_visible=True)
        self._widgets["Pressure Curve Selector"].setCurrentNode(pressure_table_node)

        self._widgets["Output Prefix"].setText("TestFlow")

        # 2. Run Simulation
        self._widgets["Apply Button"].clicked()
        process_events()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)
        wait_cli_to_finish(cli_node)
        self.assertEqual(cli_node.GetStatusString(), "Completed")

        # 3. Verify Auto-Selection in Visualization
        mercury_sim_widget = self._module_widget.mercurySimWidget
        results_node = mercury_sim_widget.micpSelector.currentNode()
        self.assertIsNotNone(results_node)
        self.assertEqual(results_node.GetName(), "MICP")

        # 4. Verify Unit Switching and Plot Options
        # Initial state: Pa and um (um is default in Radius unit)
        self.assertTrue(mercury_sim_widget.paRadioButton.isChecked())
        self.assertTrue(mercury_sim_widget.umRadioButton.isChecked())

        # Disable log scale to verify linear ratios correctly
        mercury_sim_widget.logPcCheckBox.setChecked(False)
        mercury_sim_widget.logRadiiCheckBox.setChecked(False)
        process_events()

        # Get initial resolution line values (linear)
        res_line_pa = mercury_sim_widget.pcResolutionLine.value()

        # Switch to psi
        mercury_sim_widget.psiRadioButton.setChecked(True)
        process_events()
        res_line_psi = mercury_sim_widget.pcResolutionLine.value()

        # Conversion factor check (Pa to psi is ~0.000145)
        self.assertAlmostEqual(res_line_psi / res_line_pa, 0.000145038, delta=1e-7)
        self.assertEqual(mercury_sim_widget.pcPlotItem.getAxis("bottom").labelText, "Pressure (psi)")

        # Switch to mm
        res_line_um = mercury_sim_widget.radiiResolutionLine.value()
        mercury_sim_widget.mmRadioButton.setChecked(True)
        process_events()
        res_line_mm = mercury_sim_widget.radiiResolutionLine.value()

        self.assertAlmostEqual(res_line_mm / res_line_um, 0.001, delta=1e-7)
        self.assertEqual(mercury_sim_widget.radiiPlotItem.getAxis("bottom").labelText, "Radius (mm)")

        # Test Log Scale toggle
        # res_line_mm is currently linear
        mercury_sim_widget.logRadiiCheckBox.setChecked(True)
        process_events()
        res_line_log = mercury_sim_widget.radiiResolutionLine.value()
        self.assertAlmostEqual(res_line_log, np.log10(res_line_mm), delta=1e-5)

        # 5. Verify Persistence
        # Check that subscale model is still "Pressure Curve"
        self.assertEqual(mercury_sim_widget.subscaleModelWidget.microscale_model_dropdown.currentText, "Pressure Curve")

        # Switch to One-phase
        self._widgets["Simulation Selector"].setCurrentText("One-phase")
        process_events()

        # Verify that "Pressure Curve" and the table are still selected
        self.assertEqual(mercury_sim_widget.subscaleModelWidget.microscale_model_dropdown.currentText, "Pressure Curve")
        self.assertEqual(
            mercury_sim_widget.subscaleModelWidget.parameter_widgets[
                "Pressure Curve"
            ].pressureCurveSelector.currentNode(),
            pressure_table_node,
        )

        # Switch back to Mercury injection
        self._widgets["Simulation Selector"].setCurrentText("Mercury injection")
        process_events()

        # Verify that "Pressure Curve" and the table are still selected
        self.assertEqual(mercury_sim_widget.subscaleModelWidget.microscale_model_dropdown.currentText, "Pressure Curve")
        self.assertEqual(
            mercury_sim_widget.subscaleModelWidget.parameter_widgets[
                "Pressure Curve"
            ].pressureCurveSelector.currentNode(),
            pressure_table_node,
        )

    def test_fixed_radius_widget_set_params_conversion(self):
        widget = FixedRadiusWidget()

        # Test input in mm (e.g. 0.001 mm) should become 1 micron
        params = {"radius": 0.001}
        widget.set_params(params)

        # The widget stores the value in microns in the text field
        # 0.001 mm * 1000 = 1.0 micron
        self.assertEqual(float(widget.micropore_radius.text), 1.0)

        # Verify get_params converts it back to mm
        # 1.0 micron * 0.001 = 0.001 mm
        result_params = widget.get_params()
        self.assertAlmostEqual(result_params["radius"], 0.001)

    def test_truncated_gaussian_widget_set_params_conversion(self):
        widget = TruncatedGaussianWidget()

        params = {
            "mean radius": 0.002,
            "standard deviation": 0.0005,
            "min radius": 0.001,
            "max radius": 0.005,
        }
        widget.set_params(params)

        # Check text fields (values should be in microns)
        self.assertEqual(float(widget.mean_radius.text), 2.0)
        self.assertEqual(float(widget.micropore_std.text), 0.5)
        self.assertEqual(float(widget.minimum_radius.text), 1.0)
        self.assertEqual(float(widget.maximum_radius.text), 5.0)

        # Verify get_params converts it back to mm
        result_params = widget.get_params()
        self.assertAlmostEqual(result_params["mean radius"], 0.002)
        self.assertAlmostEqual(result_params["standard deviation"], 0.0005)
        self.assertAlmostEqual(result_params["min radius"], 0.001)
        self.assertAlmostEqual(result_params["max radius"], 0.005)

    def test_save_and_load_two_phase_parameters(self):
        load_project(SIMULATE_PROJECT_FILE)

        # 1. Select Two-phase simulation mode
        fluids_selector = self._widgets["Simulation Selector"]
        fluids_selector.setCurrentText("Two-phase")
        process_events()

        two_phase_widget = self._module_widget.twoPhaseSimWidget

        # 2. Set distinct non-default values for all parameters in PARAMETERS
        for param_name, param_info in PARAMETERS.items():
            if param_name not in two_phase_widget.widgets:
                continue

            widget = two_phase_widget.widgets[param_name]
            dtype = param_info.get("dtype")

            if dtype == "multifloat":
                widget.set_value(15.5, 45.5)
                widget.set_steps(3)
            elif dtype == "singlefloat":
                widget.set_value(12.34)
            elif dtype in ("singleint", "integerspinbox"):
                widget.set_value(4)
            elif dtype == "singlecheckbox":
                true_val = param_info.get("true_value", "T")
                false_val = param_info.get("false_value", "F")
                current_val = widget.get_value()
                widget.set_value(false_val if current_val == true_val else true_val)
            elif dtype == "checkbox":
                current_val = widget.get_value()
                new_val = "".join("0" if c == "1" else "1" for c in current_val)
                widget.set_value(new_val)
            elif dtype == "combobox":
                if hasattr(widget, "combo_box") and widget.combo_box.count > 1:
                    # Keep contact models at "Model 2" so angle separation parameters remain active/valid
                    if param_name in ("init_contact_model", "equil_contact_model"):
                        idx = widget.combo_box.findText("Model 2 (constant difference)")
                        if idx >= 0:
                            widget.combo_box.setCurrentIndex(idx)
                    else:
                        current_idx = widget.combo_box.currentIndex
                        target_idx = (current_idx + 1) % widget.combo_box.count
                        widget.combo_box.setCurrentIndex(target_idx)

        process_events()

        # 3. Retrieve parameters dictionary prior to saving
        params_before = two_phase_widget.getParams()

        # 4. Save parameters using interface save button logic
        node_name = "test_two_phase_saved_parameters"
        two_phase_widget.parameterInputLineEdit.setText(node_name)
        two_phase_widget.onParameterInputSave()
        process_events()

        saved_node = slicer.util.getNode(node_name)
        self.assertIsNotNone(saved_node, f"Parameter node '{node_name}' was not created.")

        # 5. Mutate/reset widget values to ensure loading actually updates the UI
        for param_name, param_info in PARAMETERS.items():
            if param_name not in two_phase_widget.widgets:
                continue

            widget = two_phase_widget.widgets[param_name]
            dtype = param_info.get("dtype")

            if dtype == "multifloat":
                widget.set_value(0.0, 0.0)
                widget.set_steps(1)
            elif dtype == "singlefloat":
                widget.set_value(0.0)
            elif dtype in ("singleint", "integerspinbox"):
                widget.set_value(1)
            elif dtype == "singlecheckbox":
                widget.set_value(param_info.get("false_value", "F"))
            elif dtype == "checkbox":
                current_val = widget.get_value()
                widget.set_value("0" * len(current_val))
            elif dtype == "combobox":
                if hasattr(widget, "combo_box"):
                    widget.combo_box.setCurrentIndex(0)

        process_events()

        # 6. Load parameters back using interface load button logic
        two_phase_widget.parameterInputWidget.setCurrentNode(saved_node)
        two_phase_widget.onParameterInputLoad()
        process_events()

        # 7. Retrieve parameters dictionary after loading
        params_after = two_phase_widget.getParams()

        # 8. Assert equality for all PARAMETERS present in the UI
        for param_name in PARAMETERS.keys():
            if param_name not in two_phase_widget.widgets:
                continue

            self.assertIn(
                param_name,
                params_before,
                f"Parameter '{param_name}' missing from getParams() before save.",
            )
            self.assertIn(
                param_name,
                params_after,
                f"Parameter '{param_name}' missing from getParams() after load.",
            )

            before_val = params_before[param_name]
            after_val = params_after[param_name]

            if isinstance(before_val, dict):
                for sub_k, sub_v in before_val.items():
                    self.assertIn(
                        sub_k,
                        after_val,
                        f"Sub-key '{sub_k}' missing in loaded dict for '{param_name}'.",
                    )
                    if isinstance(sub_v, float):
                        self.assertAlmostEqual(
                            sub_v,
                            after_val[sub_k],
                            places=4,
                            msg=f"Mismatch for '{param_name}.{sub_k}'",
                        )
                    else:
                        self.assertEqual(
                            sub_v,
                            after_val[sub_k],
                            msg=f"Mismatch for '{param_name}.{sub_k}'",
                        )
            elif isinstance(before_val, float):
                self.assertAlmostEqual(
                    before_val,
                    after_val,
                    places=4,
                    msg=f"Mismatch for parameter '{param_name}'",
                )
            else:
                self.assertEqual(
                    before_val,
                    after_val,
                    msg=f"Mismatch for parameter '{param_name}'",
                )
