import os
from unittest.mock import patch

import numpy as np
import pandas as pd
import slicer
import vtk
from vtk.util import numpy_support

from commons.pore_networks.constants import PN_PROPERTIES
from commons.pore_networks.functions_extract import geo2spy
from commons.pore_networks.synthetic import DEFAULT_RADII, sphere_grid_3x3x3
from commons.slicer.node_attributes import NodeEnvironment
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import wait_cli_to_finish, load_project, wait
from commons.slicer_utils import tableNodeToDict
from .network_util import populate_widgets


def sort_throat_table(df):
    return df.sort_values(by=["throat.equivalent_diameter", "throat.volume", "throat.total_length"]).reset_index(
        drop=True
    )


def sort_pore_table(df):
    return df.sort_values(by=["pore.radius", "pore.volume", "pore.extended_diameter"]).reset_index(drop=True)


class PoreNetworkExtractorTest(LTracePluginTest):
    TEST_RESOURCES_DIR = os.path.join(
        os.path.dirname(__file__),
        "Resources",
    )
    FULL_EXTRACT_PROJECT_FILE = os.path.join(
        TEST_RESOURCES_DIR,
        "pnm_full_extraction_test",
        "pnm_full_extraction_test.mrml",
    )
    MULTISCALE_EXTRACT_PROJECT_FILE = os.path.join(
        TEST_RESOURCES_DIR,
        "pnm_multiscale_extraction",
        "pnm_multiscale_extraction.mrml",
    )

    def pre_setup(self):
        self.__envPatcher = patch("commons.slicer.helpers.getCurrentEnvironment", lambda: NodeEnvironment.THIN_SECTION)
        self.__envPatcher.start()

    def tear_down(self):
        self.__envPatcher.stop()

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = dict()
        populate_widgets(self)

    def test_full_extract(self):
        load_project(self.FULL_EXTRACT_PROJECT_FILE)

        labelmap_node = slicer.util.getNode("Segmentation_Inspector_LabelMap")
        self.assertIsNotNone(labelmap_node)

        labelmap_combo_box = self._widgets["Input Selector"]
        labelmap_combo_box.setCurrentNode(labelmap_node)

        generate_visualization_checkbox = self._widgets["Generate Visualization Checkbox"]
        generate_visualization_checkbox.checked = True

        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)

        wait_cli_to_finish(cli_node)
        assert cli_node.GetStatusString() == "Completed", (
            f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
        )

        # Check
        pore_node = slicer.util.getNode("Segmentation_Inspector_LabelMap_pore_model_phase_1")
        self.assertIsNotNone(pore_node)

        # Check pore data
        pore_data = numpy_support.vtk_to_numpy(pore_node.GetPolyData().GetPoints().GetData())
        expected_pore_data = numpy_support.vtk_to_numpy(
            slicer.util.getNode("ExpectedResult_pore_model_phase_1").GetPolyData().GetPoints().GetData()
        )
        np.testing.assert_almost_equal(pore_data, expected_pore_data, decimal=5)

    # Anisotropic spacing, a non-zero origin and flipped axes, so that any mix-up between IJK, RAS and
    # numpy axis order shows up as misplaced pores.
    SYNTHETIC_IJK_TO_RAS = np.array(
        [
            [-0.010, 0, 0, 1.5],
            [0, -0.013, 0, -2.0],
            [0, 0, 0.017, 0.7],
            [0, 0, 0, 1],
        ]
    )

    def _check_synthetic_spheres_network(self, prefix, grid, input_node):
        """Checks the outputs of an extraction of the 27-sphere grid, created by ``_add_synthetic_volume``.

        Property values are checked by the unit tests (tests/unit/commons/pore_networks/test_extract_synthetic.py);
        here only what depends on the Slicer side is verified: output nodes, spatial metadata and RAS placement.
        """
        pore_table = slicer.util.getNode(f"{prefix}_pore_table")
        throat_table = slicer.util.getNode(f"{prefix}_throat_table")
        summary_df = slicer.util.dataframeFromTable(slicer.util.getNode(f"{prefix}_summary_table"))
        summary = dict(zip(summary_df["Property"], summary_df["Value"]))
        self.assertEqual(int(summary["Number of Pores"]), len(grid.radii))
        self.assertEqual(int(summary["Number of Throats"]), len(grid.pairs))
        self.assertEqual(pore_table.GetNumberOfRows(), len(grid.radii))
        self.assertEqual(throat_table.GetNumberOfRows(), len(grid.pairs))
        self.assertEqual(pore_table.GetNodeReference("throat_table"), throat_table)

        spacing = input_node.GetSpacing()
        for axis, value in zip("xyz", spacing):
            self.assertAlmostEqual(float(pore_table.GetAttribute(f"{axis}_spacing")), value)
        origin = [float(v) for v in pore_table.GetAttribute("origin").split(";")]
        np.testing.assert_allclose(origin, input_node.GetOrigin())

        # Pore glyphs must be centered on the spheres, in RAS. Glyphs are emitted in pore order and
        # every glyph has the same number of points, so the mean of each chunk is a pore center.
        pore_model = slicer.util.getNode(f"{prefix}_pore_model_phase_1")
        points = numpy_support.vtk_to_numpy(pore_model.GetPolyData().GetPoints().GetData())
        centers_ras = points.reshape(len(grid.radii), -1, 3).mean(axis=1)

        ijk_to_ras = vtk.vtkMatrix4x4()
        input_node.GetIJKToRASMatrix(ijk_to_ras)
        ijk_to_ras = slicer.util.arrayFromVTKMatrix(ijk_to_ras)
        # Pores touching the volume borders are placed on them, so compare against the snapped positions.
        coords_ijk = grid.expected["pore.coords"][:, ::-1]
        expected_ras = (ijk_to_ras[:3, :3] @ coords_ijk.T).T + ijk_to_ras[:3, 3]

        distances = np.linalg.norm(centers_ras[:, None, :] - expected_ras[None, :, :], axis=2)
        nearest = distances.min(axis=1)
        self.assertLess(nearest.max(), min(spacing), f"Pores are misplaced in RAS: {nearest}")
        self.assertEqual(len(set(distances.argmin(axis=1))), len(grid.radii))

    def _add_synthetic_volume(self, array, name, node_class):
        return slicer.util.addVolumeFromArray(
            array, ijkToRAS=self.SYNTHETIC_IJK_TO_RAS, name=name, nodeClassName=node_class
        )

    def test_synthetic_spheres_labelmap(self):
        grid = sphere_grid_3x3x3(distance=24, radii=np.array(DEFAULT_RADII) * 24 / 84, size=73)
        node = self._add_synthetic_volume(grid.labels, "synthetic_labels", "vtkMRMLLabelMapVolumeNode")

        self._widgets["Generate Visualization Checkbox"].checked = True
        self._run_extract(node)

        self._check_synthetic_spheres_network("synthetic_labels", grid, node)

    def test_synthetic_spheres_porosity_map(self):
        grid = sphere_grid_3x3x3(distance=24, radii=np.array(DEFAULT_RADII) * 24 / 84, size=73)
        node = self._add_synthetic_volume(
            grid.binary.astype(np.float32), "synthetic_porosity", "vtkMRMLScalarVolumeNode"
        )

        self._widgets["Generate Visualization Checkbox"].checked = True
        self._run_extract(node)

        self._check_synthetic_spheres_network("synthetic_porosity", grid, node)
        watershed = slicer.util.getNode("synthetic_porosity_watershed")
        self.assertEqual(int(slicer.util.arrayFromVolume(watershed).max()), len(grid.radii))

    def _run_extract(self, pore_map_node):
        self.assertIsNotNone(pore_map_node)

        self._widgets["Input Selector"].setCurrentNode(pore_map_node)
        self._widgets["Apply Button"].clicked()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)
        wait_cli_to_finish(cli_node)
        assert cli_node.GetStatusString() == "Completed", (
            f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
        )

    # TODO(pore-specialist): Templates need regeneration after the porespy upgrade (PL-3053).
    # The porespy upgrade renamed snow2()'s `parallelization` -> `parallel_kw` (already fixed in
    # functions_extract.py) but also changed the numerical output of snow2(), making the old
    # pore_template.pd / throat_template.pd stale.  For the w_pores variant the expected result
    # is 12 pores (one per watershed label) but a preliminary re-run produced 27, suggesting the
    # watershed label-map may not have been passed through correctly -- needs investigation before
    # committing new baselines.  Use generate_multiscale_extract() / generate_multiscale_extract_with_pores()
    # to regenerate once the correct behaviour is confirmed.
    def _multiscale_extract_base(self, poremap_node_name):
        load_project(self.MULTISCALE_EXTRACT_PROJECT_FILE)
        dir = os.path.dirname(os.path.abspath(__file__))

        pore_map_node = slicer.util.getNode(poremap_node_name)
        self._run_extract(pore_map_node)

        pore_table = slicer.util.getNode(f"{poremap_node_name}_pore_table")
        pore_df = slicer.util.dataframeFromTable(pore_table)
        pore_template_path = os.path.join(dir, "pore_template.pd")
        pore_template_df = pd.read_pickle(pore_template_path)
        tolerance = 0.05
        pore_df = sort_pore_table(pore_df)
        pore_template_df = sort_pore_table(pore_template_df)
        diff = (pore_df - pore_template_df).abs()
        if (diff <= tolerance).all().all():
            pore_table_pass = True
        else:
            pore_table_pass = False
        assert pore_table_pass

        throat_table = slicer.util.getNode(f"{poremap_node_name}_throat_table")
        throat_df = slicer.util.dataframeFromTable(throat_table)
        throat_template_path = os.path.join(dir, "throat_template.pd")
        throat_template_df = pd.read_pickle(throat_template_path)
        tolerance = 0.05
        throat_df = sort_throat_table(throat_df)
        throat_template_df = sort_throat_table(throat_template_df)
        diff = (throat_df - throat_template_df).abs()
        if (diff <= tolerance).all().all():
            throat_table_pass = True
        else:
            throat_table_pass = False
        assert throat_table_pass

        pore_network = tableNodeToDict(pore_table)
        throat_network = tableNodeToDict(throat_table)

        spy = geo2spy(pore_network, throat_network)
        for key in PN_PROPERTIES.keys():
            property_shape = spy[key].shape[1] if len(spy[key].shape) > 1 else 1
            assert PN_PROPERTIES[key] == property_shape

    def test_multiscale_extract_int(self):
        self._multiscale_extract_base("pore_map")

    def test_multiscale_extract_float(self):
        self._multiscale_extract_base("pore_map_float")

    def test_multiscale_extract_float_100(self):
        self._multiscale_extract_base("pore_map_float_100")

    def test_multiscale_extract_different_spacing(self):
        load_project(self.MULTISCALE_EXTRACT_PROJECT_FILE)

        pore_map_node = slicer.util.getNode("pore_map")
        pore_map_node.SetSpacing(0.005, 0.005, 0.005)
        self._run_extract(pore_map_node)
        summary_table_node = slicer.util.getNode("pore_map_summary_table")
        self.assertIsNotNone(summary_table_node)
        summary_table_df = slicer.util.dataframeFromTable(summary_table_node)
        resolved_porosity_0 = summary_table_df["Value"][
            summary_table_df["Property"] == "Throat Resolved Porosity (%)"
        ].values[0]

        pore_map_node = slicer.util.getNode("pore_map")
        pore_map_node.SetSpacing(0.0051, 0.0051, 0.0051)
        self._run_extract(pore_map_node)
        summary_table_node = slicer.util.getNode("pore_map_summary_table_1")
        self.assertIsNotNone(summary_table_node)
        summary_table_df = slicer.util.dataframeFromTable(summary_table_node)
        resolved_porosity_1 = summary_table_df["Value"][
            summary_table_df["Property"] == "Throat Resolved Porosity (%)"
        ].values[0]

        self.assertAlmostEqual(resolved_porosity_0, resolved_porosity_1)

    def test_multiscale_extract_w_pores(self):
        load_project(self.MULTISCALE_EXTRACT_PROJECT_FILE)
        dir = os.path.dirname(os.path.abspath(__file__))

        pore_map_node = slicer.util.getNode("pore_map")
        self.assertIsNotNone(pore_map_node)
        watershed_node = slicer.util.getNode("watershed")
        self.assertIsNotNone(watershed_node)

        self._widgets["Input Selector"].setCurrentNode(pore_map_node)
        self._widgets["Pores Selector"].setCurrentNode(watershed_node)

        self._widgets["Apply Button"].clicked()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)

        wait_cli_to_finish(cli_node)
        assert cli_node.GetStatusString() == "Completed", (
            f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
        )

        pore_table = slicer.util.getNode("pore_map_pore_table")
        pore_df = slicer.util.dataframeFromTable(pore_table)
        pore_template_path = os.path.join(dir, "pore_template_w_pores.pd")
        pore_template_df = pd.read_pickle(pore_template_path)
        tolerance = 0.05
        pore_df = sort_pore_table(pore_df)
        pore_template_df = sort_pore_table(pore_template_df)
        diff = (pore_df - pore_template_df).abs()
        if (diff <= tolerance).all().all():
            pore_table_pass = True
        else:
            pore_table_pass = False
        assert pore_table_pass

        throat_table = slicer.util.getNode("pore_map_throat_table")
        throat_df = slicer.util.dataframeFromTable(throat_table)
        throat_template_path = os.path.join(dir, "throat_template_w_pores.pd")
        throat_template_df = pd.read_pickle(throat_template_path)
        tolerance = 0.05
        throat_df = sort_throat_table(throat_df)
        throat_template_df = sort_throat_table(throat_template_df)
        diff = (throat_df - throat_template_df).abs()
        if (diff <= tolerance).all().all():
            throat_table_pass = True
        else:
            throat_table_pass = False
        assert throat_table_pass

        pore_network = tableNodeToDict(pore_table)
        throat_network = tableNodeToDict(throat_table)

        spy = geo2spy(pore_network, throat_network)

        for key in PN_PROPERTIES.keys():
            property_shape = spy[key].shape[1] if len(spy[key].shape) > 1 else 1
            assert PN_PROPERTIES[key] == property_shape

    def test_cancel_button_behavior(self):
        cancelButton = self._widgets["Cancel Button"]
        self.assertTrue(cancelButton.isVisible())
        self.assertFalse(cancelButton.isEnabled())

        load_project(self.FULL_EXTRACT_PROJECT_FILE)
        labelmap_node = slicer.util.getNode("Segmentation_Inspector_LabelMap")
        self.assertIsNotNone(labelmap_node)
        labelmap_combo_box = self._widgets["Input Selector"]
        labelmap_combo_box.setCurrentNode(labelmap_node)

        applyButton = self._widgets["Apply Button"]
        self.assertTrue(applyButton.isEnabled())

        applyButton.clicked()
        slicer.app.processEvents()

        self.assertTrue(cancelButton.isEnabled())

        cliNode = self._module_widget.logic.cliNode
        self.assertIsNotNone(cliNode)
        self.assertTrue(cliNode.IsBusy())

        wait(3)

        cancelButton.clicked()
        slicer.app.processEvents()

        wait_cli_to_finish(cliNode)
        self.assertEqual(cliNode.GetStatusString(), "Cancelled")
        self.assertFalse(cancelButton.isEnabled())
        self.assertTrue(applyButton.isEnabled())

    def test_generate_visualization_from_tables(self):
        # Load a project with pre-existing pore and throat tables
        load_project(self.FULL_EXTRACT_PROJECT_FILE)

        # Get the generated pore table
        pore_table_node = slicer.util.getNode("ExpectedResult_pore_table")
        self.assertIsNotNone(pore_table_node)

        # Select the pore table in the new selector
        self._widgets["Pore Table Selector"].setCurrentNode(pore_table_node)

        # Click the generate visualization button
        generate_button = self._widgets["Generate Visualization Button"]
        generate_button.clicked()

        wait(1)  # Allow events to process and nodes to be created

        # Assert that model nodes are created and visible
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        # Check for the visualization folder
        pore_table_item_id = shNode.GetItemByDataNode(pore_table_node)
        parent_item_id = shNode.GetItemParent(pore_table_item_id)
        visualization_folder_name = f"{pore_table_node.GetName()}_Visualization"
        visualization_folder_item_id = shNode.GetItemChildWithName(parent_item_id, visualization_folder_name)
        self.assertNotEqual(
            visualization_folder_item_id, 0, f"Visualization folder '{visualization_folder_name}' not found."
        )

        # Check for pore models
        pore_model_phase_1 = slicer.util.getNode("pore_model_phase_1")
        self.assertIsNotNone(pore_model_phase_1)
        self.assertTrue(pore_model_phase_1.GetDisplayNode().GetVisibility())
        self.assertNotEqual(
            shNode.GetItemParent(shNode.GetItemByDataNode(pore_model_phase_1)),
            0,
            "Pore model not in subject hierarchy.",
        )

        # Check for throat models
        throat_model_phase_1 = slicer.util.getNode("throat_model_phase_1")
        self.assertIsNotNone(throat_model_phase_1)
        self.assertTrue(throat_model_phase_1.GetDisplayNode().GetVisibility())
        self.assertNotEqual(
            shNode.GetItemParent(shNode.GetItemByDataNode(throat_model_phase_1)),
            0,
            "Throat model not in subject hierarchy.",
        )

        # Check that they are children of the visualization folder
        self.assertEqual(
            shNode.GetItemParent(shNode.GetItemByDataNode(pore_model_phase_1)), visualization_folder_item_id
        )
        self.assertEqual(
            shNode.GetItemParent(shNode.GetItemByDataNode(throat_model_phase_1)), visualization_folder_item_id
        )

    def generate_full_extract(self):
        load_project(self.FULL_EXTRACT_PROJECT_FILE)

        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        labelmap_node = slicer.util.getNode("Segmentation_Inspector_LabelMap")
        self.assertIsNotNone(labelmap_node)

        pore_table = "ExpectedResult_pore_table"
        throat_table = "ExpectedResult_throat_table"
        pore_model = "pore_model_phase_1"
        throat_model = "throat_model_phase_1"
        folder_name = "ExpectedResult_Pore_Network"

        folderID = shNode.GetItemByName(folder_name)
        self.assertNotEqual(folderID, 0)
        shNode.RemoveItem(folderID)

        for node_name in (pore_table, throat_table, pore_model, throat_model):
            with self.assertRaises(slicer.util.MRMLNodeNotFoundException):
                slicer.util.getNode(node_name)

        labelmap_combo_box = self._widgets["Input Selector"]
        labelmap_combo_box.setCurrentNode(labelmap_node)

        generate_visualization_checkbox = self._widgets["Generate Visualization Checkbox"]
        generate_visualization_checkbox.checked = True

        output_prefix = self._widgets["Output Prefix"]
        output_prefix.setText("ExpectedResult")

        apply_button = self._widgets["Apply Button"]
        apply_button.clicked()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)

        wait_cli_to_finish(cli_node)
        assert cli_node.GetStatusString() == "Completed", (
            f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
        )

        slicer.modules.AppContextInstance.projectEventsLogic.saveScene()

    def generate_multiscale_extract(self):
        load_project(self.MULTISCALE_EXTRACT_PROJECT_FILE)
        dir = os.path.dirname(os.path.abspath(__file__))

        pore_map_node = slicer.util.getNode("pore_map")
        self.assertIsNotNone(pore_map_node)

        self._widgets["Input Selector"].setCurrentNode(pore_map_node)

        self._widgets["Apply Button"].clicked()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)

        wait_cli_to_finish(cli_node)
        assert cli_node.GetStatusString() == "Completed", (
            f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
        )

        pore_table = slicer.util.getNode("pore_map_pore_table")
        pore_df = slicer.util.dataframeFromTable(pore_table)
        pore_path = os.path.join(dir, "pore_template.pd")
        pore_df.to_pickle(pore_path)

        throat_table = slicer.util.getNode("pore_map_throat_table")
        throat_df = slicer.util.dataframeFromTable(throat_table)
        throat_path = os.path.join(dir, "throat_template.pd")
        throat_df.to_pickle(throat_path)

    def generate_multiscale_extract_with_pores(self):
        load_project(self.MULTISCALE_EXTRACT_PROJECT_FILE)
        dir = os.path.dirname(os.path.abspath(__file__))

        pore_map_node = slicer.util.getNode("pore_map")
        self.assertIsNotNone(pore_map_node)
        watershed_node = slicer.util.getNode("watershed")
        self.assertIsNotNone(watershed_node)

        self._widgets["Input Selector"].setCurrentNode(pore_map_node)
        self._widgets["Pores Selector"].setCurrentNode(watershed_node)

        self._widgets["Apply Button"].clicked()

        cli_node = self._module_widget.logic.cliNode
        self.assertIsNotNone(cli_node)

        wait_cli_to_finish(cli_node)
        assert cli_node.GetStatusString() == "Completed", (
            f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
        )

        pore_table = slicer.util.getNode("pore_map_pore_table")
        pore_df = slicer.util.dataframeFromTable(pore_table)
        pore_path = os.path.join(dir, "pore_template_w_pores.pd")
        pore_df.to_pickle(pore_path)

        throat_table = slicer.util.getNode("pore_map_throat_table")
        throat_df = slicer.util.dataframeFromTable(throat_table)
        throat_path = os.path.join(dir, "throat_template_w_pores.pd")
        throat_df.to_pickle(throat_path)
