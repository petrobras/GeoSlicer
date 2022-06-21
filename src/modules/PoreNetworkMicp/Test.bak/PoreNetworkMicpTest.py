from ltrace.slicer.tests.ltrace_plugin_test import LTracePluginTest
from ltrace.slicer.tests.utils import load_project
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer_utils import tableNodeToDict
from unittest.mock import patch
from ltrace.pore_networks.functions import geo2spy
from ltrace.pore_networks.constants import PN_PROPERTIES

import os
import qt
import slicer

import numpy as np
import pandas as pd

TEST_RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "Resources")
SIMULATE_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "multiscale_1100_crop", "multiscale_1100_crop.mrml")
ANISOTROPIC_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "anisotropic", "anisotropic.mrml")


def mock_module_environment():
    return NodeEnvironment.MICRO_CT.value


class PoreNetworkMicpTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = {}
        widgets_str = "Widgets:\n\n"
        for name, widget in self._module_widget.widgetsDict.items():
            self._widgets[name] = self.find_widget(name)
            widgets_str += f"{name}: {type(widget).__name__}\n"
            assert self._widgets[name] is widget

        dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(dir, "widgets_reference.txt")
        with open(file_path, "w") as file:
            file.write(widgets_str)

    def tear_down(self):
        pass

    def test_default(self):
        load_project(SIMULATE_PROJECT_FILE)
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        dir = os.path.dirname(os.path.abspath(__file__))

        pore_map_node = slicer.util.getNode("pore_map")
        self.assertIsNotNone(pore_map_node)
        pore_map_node_id = folderTree.GetItemByDataNode(pore_map_node)
        self._widgets["Filter Selector"].setCurrentItem(pore_map_node_id)
        self._widgets["Smoothing Factor Edit"].text = "2"
        self._widgets["Filter Button"].clicked()

        preprocess_node = slicer.util.getNode("preprocessed_volume")
        preprocess_array = slicer.util.arrayFromVolume(preprocess_node)

        preprocess_template_path = os.path.join(dir, "preprocess_template.npy")
        preprocess_template_array = np.load(preprocess_template_path)
        preprocess_pass = np.isclose(
            preprocess_array,
            preprocess_template_array,
            rtol=0,
            atol=1,
        ).all()
        assert preprocess_pass

        preprocess_node_id = folderTree.GetItemByDataNode(preprocess_node)
        self._widgets["Local Porosity Selector"].setCurrentItem(preprocess_node_id)
        self._widgets["Extract Button"].clicked()

        multiphase_node = slicer.util.getNode("multiphase volume")
        multiphase_array = slicer.util.arrayFromVolume(multiphase_node)

        multiphase_template_path = os.path.join(dir, "multiphase_template.npy")
        multiphase_template_array = np.load(multiphase_template_path)
        multiphase_pass = np.isclose(
            multiphase_array,
            multiphase_template_array,
            rtol=0,
            atol=1,
        ).all()
        assert multiphase_pass

        pore_table = slicer.util.getNode("Multiscale_PN_pore_table")
        pore_df = slicer.util.dataframeFromTable(pore_table)
        pore_template_path = os.path.join(dir, "pore_template.pd")
        pore_template_df = pd.read_pickle(pore_template_path)
        tolerance = 0.05
        diff = (pore_df - pore_template_df).abs()
        if (diff <= tolerance).all().all():
            pore_table_pass = True
        else:
            pore_table_pass = False
        assert pore_table_pass

        throat_table = slicer.util.getNode("Multiscale_PN_throat_table")
        throat_df = slicer.util.dataframeFromTable(throat_table)
        throat_template_path = os.path.join(dir, "throat_template.pd")
        throat_template_df = pd.read_pickle(throat_template_path)
        tolerance = 0.05
        diff = (throat_df - throat_template_df).abs()
        if (diff <= tolerance).all().all():
            throat_table_pass = True
        else:
            throat_table_pass = False
        assert throat_table_pass

        spy = geo2spy(pore_table)
        for key in PN_PROPERTIES.keys():
            property_shape = spy[key].shape[1] if len(spy[key].shape) > 1 else 1
            assert PN_PROPERTIES[key] == property_shape

    def test_anisotropic(self):
        load_project(ANISOTROPIC_PROJECT_FILE)
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        dir = os.path.dirname(os.path.abspath(__file__))

        pore_map_node = slicer.util.getNode("pore_map")
        self.assertIsNotNone(pore_map_node)
        pore_map_node_id = folderTree.GetItemByDataNode(pore_map_node)

        phases_node = slicer.util.getNode("phases")
        self.assertIsNotNone(phases_node)
        phases_node_id = folderTree.GetItemByDataNode(phases_node)

        self._widgets["Local Porosity Selector"].setCurrentItem(pore_map_node_id)
        self._widgets["Phases Volume Selector"].setCurrentItem(phases_node_id)
        self._widgets["Extract Button"].clicked()

        multiphase_node = slicer.util.getNode("multiphase volume")
        multiphase_array = slicer.util.arrayFromVolume(multiphase_node)

        multiphase_template_path = os.path.join(dir, "aniso_multiphase_template.npy")
        multiphase_template_array = np.load(multiphase_template_path)
        multiphase_pass = np.isclose(
            multiphase_array,
            multiphase_template_array,
            rtol=0,
            atol=1,
        ).all()
        assert multiphase_pass

        pore_table = slicer.util.getNode("Multiscale_PN_pore_table")
        pore_df = slicer.util.dataframeFromTable(pore_table)
        pore_template_path = os.path.join(dir, "aniso_pore_template.pd")
        pore_template_df = pd.read_pickle(pore_template_path)
        tolerance = 0.05
        diff = (pore_df - pore_template_df).abs()
        if (diff <= tolerance).all().all():
            pore_table_pass = True
        else:
            pore_table_pass = False
        assert pore_table_pass

        throat_table = slicer.util.getNode("Multiscale_PN_throat_table")
        throat_df = slicer.util.dataframeFromTable(throat_table)
        throat_template_path = os.path.join(dir, "aniso_throat_template.pd")
        throat_template_df = pd.read_pickle(throat_template_path)
        tolerance = 0.05
        diff = (throat_df - throat_template_df).abs()
        if (diff <= tolerance).all().all():
            throat_table_pass = True
        else:
            throat_table_pass = False
        assert throat_table_pass

        spy = geo2spy(pore_table)
        for key in PN_PROPERTIES.keys():
            property_shape = spy[key].shape[1] if len(spy[key].shape) > 1 else 1
            assert PN_PROPERTIES[key] == property_shape

    def generate_default(self):
        load_project(SIMULATE_PROJECT_FILE)
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        dir = os.path.dirname(os.path.abspath(__file__))

        pore_map_node = slicer.util.getNode("pore_map")
        self.assertIsNotNone(pore_map_node)
        pore_map_node_id = folderTree.GetItemByDataNode(pore_map_node)
        self._widgets["Filter Selector"].setCurrentItem(pore_map_node_id)
        self._widgets["Smoothing Factor Edit"].text = "2"
        self._widgets["Filter Button"].clicked()

        preprocess_node = slicer.util.getNode("preprocessed_volume")
        preprocess_array = slicer.util.arrayFromVolume(preprocess_node)

        preprocess_path = os.path.join(dir, "preprocess_template.npy")
        np.save(preprocess_path, preprocess_array)

        preprocess_node_id = folderTree.GetItemByDataNode(preprocess_node)
        self._widgets["Local Porosity Selector"].setCurrentItem(preprocess_node_id)
        self._widgets["Extract Button"].clicked()

        multiphase_node = slicer.util.getNode("multiphase volume")
        multiphase_array = slicer.util.arrayFromVolume(multiphase_node)
        multiphase_path = os.path.join(dir, "multiphase_template.npy")
        np.save(multiphase_path, multiphase_array)

        pore_table = slicer.util.getNode("Multiscale_PN_pore_table")
        pore_df = slicer.util.dataframeFromTable(pore_table)
        pore_path = os.path.join(dir, "pore_template.pd")
        pore_df.to_pickle(pore_path)

        throat_table = slicer.util.getNode("Multiscale_PN_throat_table")
        throat_df = slicer.util.dataframeFromTable(throat_table)
        throat_path = os.path.join(dir, "throat_template.pd")
        throat_df.to_pickle(throat_path)

    def generate_anisotropic(self):
        load_project(ANISOTROPIC_PROJECT_FILE)
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        dir = os.path.dirname(os.path.abspath(__file__))

        pore_map_node = slicer.util.getNode("pore_map")
        self.assertIsNotNone(pore_map_node)
        pore_map_node_id = folderTree.GetItemByDataNode(pore_map_node)

        phases_node = slicer.util.getNode("phases")
        self.assertIsNotNone(phases_node)
        phases_node_id = folderTree.GetItemByDataNode(phases_node)

        self._widgets["Local Porosity Selector"].setCurrentItem(pore_map_node_id)
        self._widgets["Phases Volume Selector"].setCurrentItem(phases_node_id)
        self._widgets["Extract Button"].clicked()

        multiphase_node = slicer.util.getNode("multiphase volume")
        multiphase_array = slicer.util.arrayFromVolume(multiphase_node)
        multiphase_path = os.path.join(dir, "aniso_multiphase_template.npy")
        np.save(multiphase_path, multiphase_array)

        pore_table = slicer.util.getNode("Multiscale_PN_pore_table")
        pore_df = slicer.util.dataframeFromTable(pore_table)
        pore_path = os.path.join(dir, "aniso_pore_template.pd")
        pore_df.to_pickle(pore_path)

        throat_table = slicer.util.getNode("Multiscale_PN_throat_table")
        throat_df = slicer.util.dataframeFromTable(throat_table)
        throat_path = os.path.join(dir, "aniso_throat_template.pd")
        throat_df.to_pickle(throat_path)
