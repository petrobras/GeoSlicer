import ctk
import os
import qt
import slicer
import numpy as np
from scipy import ndimage
from numba import njit, prange
from porespy.tools import make_contiguous
import porespy as ps
import skimage as sk
import pandas as pd
import vtk
import qt
from pathlib import Path

from ltrace.slicer import ui
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, dataFrameToTableNode
import ltrace.pore_networks.functions as pn
from pathlib import Path

try:
    from Test.PoreNetworkMicpTest import PoreNetworkMicpTest
except ImportError:
    PoreNetworkMicpTest = None  # tests not deployed to final version or closed source

SOLID = 0
PORE = 1
MICROPORE = 2


class PoreNetworkMicp(LTracePlugin):
    SETTING_KEY = "PoreNetworkMicp"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Pore Network Micp"
        self.parent.categories = ["LTrace Tools"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = PoreNetworkMicp.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PoreNetworkMicpParamsWidget(ctk.ctkCollapsibleButton):
    def __init__(self):
        super().__init__()

        widget = {}
        widget["Extraction Section"] = self
        widget["Extraction Section"].text = "Multiscale Network Extraction"
        widget["Extraction Section"].collapsed = True
        widget["Extraction Section"].setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)
        self.extractFormLayout = qt.QFormLayout(widget["Extraction Section"])

        widget["Local Porosity Selector"] = hierarchyVolumeInput(nodeTypes=["vtkMRMLScalarVolumeNode"])
        widget["Local Porosity Selector"].showEmptyHierarchyItems = False
        self.extractFormLayout.addRow("Local porosity volume:", widget["Local Porosity Selector"])

        self.extractFormLayout.addRow(qt.QLabel("Optional inputs:"))

        widget["Phases Volume Selector"] = hierarchyVolumeInput(nodeTypes=["vtkMRMLLabelMapVolumeNode"], hasNone=True)
        widget["Phases Volume Selector"].showEmptyHierarchyItems = False
        self.extractFormLayout.addRow("Phases labelmap selector:", widget["Phases Volume Selector"])

        widget["Pore Volume Selector"] = hierarchyVolumeInput(nodeTypes=["vtkMRMLLabelMapVolumeNode"], hasNone=True)
        widget["Pore Volume Selector"].showEmptyHierarchyItems = False
        self.extractFormLayout.addRow("Pore labelmap selector:", widget["Pore Volume Selector"])

        widget["Micropore Volume Selector"] = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLLabelMapVolumeNode"], hasNone=True
        )
        widget["Micropore Volume Selector"].showEmptyHierarchyItems = False
        self.extractFormLayout.addRow("Micropore labelmap selector:", widget["Micropore Volume Selector"])

        widget["Watershed Volume Selector"] = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLLabelMapVolumeNode"], hasNone=True
        )
        widget["Watershed Volume Selector"].showEmptyHierarchyItems = False
        self.extractFormLayout.addRow("Watershed selector:", widget["Watershed Volume Selector"])

        self.widget = widget


class PoreNetworkMicpWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = PoreNetworkMicpLogic()
        self.widgetsDict = {}
        widget = self.widgetsDict

        #
        # Parameters section
        #
        widget["Filter Section"] = ctk.ctkCollapsibleButton()
        widget["Filter Section"].text = "Preprocessing Filter"
        widget["Filter Section"].collapsed = True
        widget["Filter Section"].setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)
        filterFormLayout = qt.QFormLayout(widget["Filter Section"])

        # Input section
        widget["Filter Selector"] = hierarchyVolumeInput(nodeTypes=["vtkMRMLScalarVolumeNode"])
        widget["Filter Selector"].showEmptyHierarchyItems = False
        filterFormLayout.addRow("Node selector:", widget["Filter Selector"])

        widget["Smoothing Factor Edit"] = ui.intParam(2)
        filterFormLayout.addRow("Smoothing factor", widget["Smoothing Factor Edit"])

        # widget["Filter Selector"].addNodeAttributeIncludeFilter("type", "multiscale")
        # widget["Filter Selector"].currentItemChanged.connect(self.onChangeMicp)

        # Output section
        # output_section = ctk.ctkCollapsibleButton()
        # output_section.text = "Output"
        # output_section.collapsed = False

        widget["Output Prefix Line Edit"] = qt.QLineEdit()
        widget["Output Prefix Line Edit"].text = "multiscale_test"
        filterFormLayout.addRow("Output prefix:", widget["Output Prefix Line Edit"])

        # Apply button
        widget["Filter Button"] = ui.ApplyButton(
            onClick=self.preprocess_image, tooltip="Run Postprocess MICP", text="Preprocessing Filter"
        )
        widget["Filter Button"].objectName = "Run Postprocess Filter"
        filterFormLayout.addRow("", widget["Filter Button"])

        #
        # Extraction section
        #
        widget["Extraction Section"] = ctk.ctkCollapsibleButton()
        widget["Extraction Section"].text = "Multiscale Network Extraction"
        widget["Extraction Section"].collapsed = True
        widget["Extraction Section"].setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)
        extractFormLayout = qt.QFormLayout(widget["Extraction Section"])

        widget["Local Porosity Selector"] = hierarchyVolumeInput(nodeTypes=["vtkMRMLScalarVolumeNode"])
        widget["Local Porosity Selector"].showEmptyHierarchyItems = False
        extractFormLayout.addRow("Local porosity volume:", widget["Local Porosity Selector"])

        extractFormLayout.addRow(qt.QLabel("Optional inputs:"))

        widget["Phases Volume Selector"] = hierarchyVolumeInput(nodeTypes=["vtkMRMLLabelMapVolumeNode"], hasNone=True)
        widget["Phases Volume Selector"].showEmptyHierarchyItems = False
        extractFormLayout.addRow("Phases labelmap selector:", widget["Phases Volume Selector"])

        widget["Pore Volume Selector"] = hierarchyVolumeInput(nodeTypes=["vtkMRMLLabelMapVolumeNode"], hasNone=True)
        widget["Pore Volume Selector"].showEmptyHierarchyItems = False
        extractFormLayout.addRow("Pore labelmap selector:", widget["Pore Volume Selector"])

        widget["Micropore Volume Selector"] = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLLabelMapVolumeNode"], hasNone=True
        )
        widget["Micropore Volume Selector"].showEmptyHierarchyItems = False
        extractFormLayout.addRow("Micropore labelmap selector:", widget["Micropore Volume Selector"])

        widget["Density Volume Selector"] = hierarchyVolumeInput(nodeTypes=["vtkMRMLScalarVolumeNode"], hasNone=True)
        widget["Density Volume Selector"].showEmptyHierarchyItems = False
        extractFormLayout.addRow("Density scalar selector:", widget["Density Volume Selector"])

        widget["Extract Button"] = ui.ApplyButton(
            onClick=self.start_extract, tooltip="Extract multiscale network", text="Multiscale extract"
        )
        widget["Extract Button"].objectName = "Extract Button"
        extractFormLayout.addRow("", widget["Extract Button"])

        # Update layout
        # self.layout.addWidget(self.micp_selector)
        # self.layout.addWidget(parameters_section)
        # self.layout.addWidget(output_section)
        # self.layout.addWidget(self._apply_button)
        self.layout.addWidget(widget["Filter Section"])
        self.layout.addWidget(widget["Extraction Section"])
        self.layout.addStretch(1)

        for name, widget in widget.items():
            widget.objectName = name

    def preprocess_image(self):
        node = self.widgetsDict["Filter Selector"].currentNode()
        smoothing = int(self.widgetsDict["Smoothing Factor Edit"].text)

        if node is None:
            slicer.util.errorDisplay("Please select an input node.")
            return

        params = {
            "node": node,
            "smoothing": smoothing,
        }

        # preprocessed_image = self.logic.preprocess_image(params)
        output_array = self.logic.preprocess_image(params)
        output_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        output_node.SetName(slicer.mrmlScene.GenerateUniqueName("preprocessed_volume"))
        slicer.util.updateVolumeFromArray(output_node, output_array)

        volumeIJKToRASMatrix = vtk.vtkMatrix4x4()
        node.GetIJKToRASMatrix(volumeIJKToRASMatrix)
        output_node.SetIJKToRASMatrix(volumeIJKToRASMatrix)

        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        node_id = folderTree.GetItemByDataNode(node)
        folder_id = folderTree.GetItemParent(node_id)
        # output_id = folderTree.GetItemByDataNode(output_node)
        _ = folderTree.CreateItem(folder_id, output_node)

    def start_extract(self):
        if self.widgetsDict["Local Porosity Selector"] is None:
            slicer.util.errorDisplay("Please select local porosity node.")
            return

        data = {
            "local_porosity": self.widgetsDict["Local Porosity Selector"].currentNode(),
            "phases_node": self.widgetsDict["Phases Volume Selector"].currentNode(),
            "pore_node": self.widgetsDict["Pore Volume Selector"].currentNode(),
            "micropore_node": self.widgetsDict["Micropore Volume Selector"].currentNode(),
            "watershed_node": self.widgetsDict["Watershed Volume Selector"].currentNode(),
            "micropore_radius": 0.1,
        }

        extract_result = self.logic.run_extract(data=data)
        if extract_result:
            pore_table, throat_table = extract_result
        else:
            print("No connected network was identified.")
            return
        self.logic.visualize(pore_table, throat_table, self.widgetsDict["Local Porosity Selector"].currentNode())

    def _on_input_node_changed(self, vtk_id):
        node = self.widgetsDict["Filter Selector"].currentNode()
        if node is None:
            return

        self.widgetsDict["Output Prefix Line Edit"].text = node.GetName()


class PoreNetworkMicpLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def preprocess_image(self, params):
        input_array = slicer.util.arrayFromVolume(params["node"])

        resolved_array = (input_array == 100).astype(np.uint8)
        unresolved_array = np.logical_and(input_array > 0, input_array < 100).astype(np.uint8)
        structure_element = _sphere_structure(params["smoothing"])
        resolved_array = ndimage.binary_opening(resolved_array, structure=structure_element).astype(np.uint8)
        unresolved_array = ndimage.binary_closing(unresolved_array, structure=structure_element, border_value=1).astype(
            np.uint8
        )
        unresolved_array = ndimage.binary_opening(unresolved_array, structure=structure_element).astype(np.uint8)

        output_array = self._preprocess_image_main_loop(
            input_array,
            resolved_array,
            unresolved_array,
            structure_element,
        )

        connected_array = pn.get_connected_voxel(output_array)
        output_array = np.where(connected_array, output_array, 0)

        return output_array

    @staticmethod
    @njit(parallel=False)
    def _preprocess_image_main_loop(
        input_array,
        resolved_array,
        unresolved_array,
        structure_element,
    ):
        output_array = np.zeros_like(input_array)

        window_iterator = _moving_window_iterator(
            input_array,
            structure_element,
        )
        for (
            i,
            j,
            k,
            min_i,
            max_i,
            min_j,
            max_j,
            min_k,
            max_k,
            min_x,
            max_x,
            min_y,
            max_y,
            min_z,
            max_z,
        ) in window_iterator:
            base_window_slice = (
                slice(min_i, max_i),
                slice(min_j, max_j),
                slice(min_k, max_k),
            )
            window_subwindow_slice = (
                slice(min_x, max_x),
                slice(min_y, max_y),
                slice(min_z, max_z),
            )

            if resolved_array[i, j, k] != 0:
                output_array[i, j, k] = 100
                continue
            if unresolved_array[i, j, k] != 0:
                input_val = input_array[i, j, k]
                if input_val == 0:
                    input_val = 1
                output_array[i, j, k] = input_val
                continue

            resolved_count = (resolved_array[base_window_slice] * structure_element[window_subwindow_slice]).sum()
            unresolved_count = (unresolved_array[base_window_slice] * structure_element[window_subwindow_slice]).sum()
            if (resolved_count == 0) and (unresolved_count == 0):
                pass
            elif resolved_count >= unresolved_count:
                output_array[i, j, k] = 100
            else:  # unresolved_count > resolved_count
                mean_porosity = (
                    input_array[base_window_slice] * structure_element[window_subwindow_slice]
                ).sum() // structure_element[window_subwindow_slice].sum()
                mean_porosity = max(mean_porosity, 1)
                output_array[i, j, k] = mean_porosity

        window_iterator = _moving_window_iterator(
            input_array,
            structure_element,
        )
        for (
            i,
            j,
            k,
            min_i,
            max_i,
            min_j,
            max_j,
            min_k,
            max_k,
            min_x,
            max_x,
            min_y,
            max_y,
            min_z,
            max_z,
        ) in window_iterator:
            if input_array[i, j, k] == 0:
                continue
            base_window_slice = (
                slice(min_i, max_i),
                slice(min_j, max_j),
                slice(min_k, max_k),
            )
            window_subwindow_slice = (
                slice(min_x, max_x),
                slice(min_y, max_y),
                slice(min_z, max_z),
            )
            if output_array[i, j, k] == 0:
                resolved_count = (
                    (output_array[base_window_slice] == 100).astype(np.uint8)
                    * structure_element[window_subwindow_slice]
                ).sum()
                unresolved_count = (
                    np.logical_and(output_array[base_window_slice] > 0, output_array[base_window_slice] < 100).astype(
                        np.uint8
                    )
                    * structure_element[window_subwindow_slice]
                ).sum()
                if resolved_count >= unresolved_count:
                    output_array[i, j, k] = 100
                else:
                    mean_porosity = (
                        input_array[base_window_slice] * structure_element[window_subwindow_slice]
                    ).sum() // structure_element[window_subwindow_slice].sum()
                    mean_porosity = min(mean_porosity, 1)
                    output_array[i, j, k] = mean_porosity

        return output_array

    def run_extract(self, data):
        input_node = data["local_porosity"]
        input_array = slicer.util.arrayFromVolume(input_node)
        resolved_array = (input_array == 100).astype(np.uint8)
        unresolved_array = np.logical_and(input_array > 0, input_array < 100).astype(np.uint8)
        multiphase_array = resolved_array + (2 * unresolved_array)

        volumesLogic = slicer.modules.volumes.logic()
        multiphaseNode = volumesLogic.CloneVolume(slicer.mrmlScene, input_node, "multiphase volume")
        slicer.util.updateVolumeFromArray(multiphaseNode, multiphase_array)

        watershed_volume = data["watershed_node"]

        extract_result = pn.general_pn_extract(
            multiphaseNode,
            prefix="Multiscale_PN",
            method="PoreSpy",
            is_phase=True,
            porosity_map=input_array,
        )

        return extract_result

    def visualize(
        self,
        poreOutputTable: slicer.vtkMRMLTableNode,
        throatOutputTable: slicer.vtkMRMLTableNode,
        inputVolume: slicer.vtkMRMLLabelMapVolumeNode,
    ) -> None:
        return pn.visualize(
            poreOutputTable,
            throatOutputTable,
            inputVolume,
        )

    @staticmethod
    @njit(parallel=False)
    def _increase_nonzero(array, increase_val):
        x, y, z = array.shape
        for i in range(x):
            for j in range(y):
                for k in range(z):
                    if array[i, j, k] == 0:
                        continue
                    else:
                        array[i, j, k] += increase_val

    @staticmethod
    @njit(parallel=True)
    def _stack_watersheds(array_1, array_2):
        output_array = np.zeros_like(array_1)
        x, y, z = array_1.shape
        for i in prange(x):
            for j in range(y):
                for k in range(z):
                    if array_1[i, j, k] > 0:
                        output_array[i, j, k] = array_1[i, j, k]
                    else:
                        output_array[i, j, k] = array_2[i, j, k]
        return output_array

    @staticmethod
    @njit(parallel=True)
    def _mode_filter(input_array):
        """
        Inplace operation on input_array array
        No returns
        """
        x, y, z = input_array.shape
        for i in prange(1, x - 1):
            for j in range(1, y - 1):
                for k in range(1, z - 1):
                    zeros = (input_array[i - 1 : i + 2, j - 1 : j + 2, k - 1 : k + 2] == 0).sum()
                    ones = (input_array[i - 1 : i + 2, j - 1 : j + 2, k - 1 : k + 2] == 1).sum()
                    twos = (input_array[i - 1 : i + 2, j - 1 : j + 2, k - 1 : k + 2] == 2).sum()
                    if ones >= twos and ones >= zeros:
                        input_array[i, j, k] = 1
                    elif twos >= zeros:
                        input_array[i, j, k] = 2
                    else:
                        input_array[i, j, k] = 0


@njit
def _moving_window_iterator(base_image, moving_window):
    w, h, d = base_image.shape
    x, y, z = moving_window.shape
    mid_x = x // 2
    mid_y = y // 2
    mid_z = z // 2
    for i in range(w):
        # for i in range(100, 115):
        min_i = max(0, i - mid_x)
        max_i = min(w - 1, i + mid_x)
        min_x = mid_x - min(x // 2, i)
        max_x = mid_x + min(x // 2, w - i - 1)
        for j in range(h):
            # for j in range(140,161):
            min_j = max(0, j - mid_y)
            max_j = min(h - 1, j + mid_y)
            min_y = mid_y - min(y // 2, j)
            max_y = mid_y + min(y // 2, h - j - 1)
            for k in range(d):
                # for k in range(100, 115):
                min_k = max(0, k - mid_z)
                max_k = min(d - 1, k + mid_z)
                min_z = mid_z - min(z // 2, k)
                max_z = mid_z + min(z // 2, d - k - 1)

                yield i, j, k, min_i, max_i + 1, min_j, max_j + 1, min_k, max_k + 1, min_x, max_x + 1, min_y, max_y + 1, min_z, max_z + 1


@njit
def _sphere_structure(radius):
    side_length = radius * 2 + 1
    center = side_length // 2
    output_array = np.zeros((side_length, side_length, side_length), dtype=np.uint8)

    for i in range(-radius, radius + 1):
        for j in range(-radius, radius + 1):
            for k in range(-radius, radius + 1):
                if np.sqrt(i**2 + j**2 + k**2) <= radius:
                    output_array[center + i, center + j, center + k] = 1

    return output_array
