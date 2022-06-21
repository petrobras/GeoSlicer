import csv
import os
import subprocess
import time
import traceback
import logging
from pathlib import Path
from typing import Tuple, Union

import ctk
import numpy as np
import pandas as pd
import qt
import slicer
import slicer.util
import vtk

import ltrace.pore_networks.functions as pn
from ltrace.image import optimized_transforms
from ltrace.slicer import ui
from ltrace.slicer_utils import (
    LTracePlugin,
    LTracePluginWidget,
    LTracePluginLogic,
    slicer_is_in_developer_mode,
    dataFrameToTableNode,
)
from ltrace.utils.ProgressBarProc import ProgressBarProc

try:
    from Test.PoreNetworkExtractorTest import PoreNetworkExtractorTest
except ImportError:
    PoreNetworkExtractorTest = None  # tests not deployed to final version or closed source

MIN_THROAT_RATIO = 0.7
PNE_TIMEOUT = 3600  # seconds


#
# PoreNetworkExtractor
#
class PoreNetworkExtractor(LTracePlugin):
    SETTING_KEY = "PoreNetworkExtractor"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "PoreNetworkExtractor"
        self.parent.categories = ["Micro CT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = PoreNetworkExtractor.help()
        self.parent.acknowledgementText = ""

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PoreNetworkExtractorParamsWidget(ctk.ctkCollapsibleButton):
    def __init__(self):
        super().__init__()

        self.text = "Parameters"
        parametersFormLayout = qt.QFormLayout(self)

        # Method selector
        self.methodSelector = qt.QComboBox()
        self.methodSelector.addItem("PoreSpy")
        if slicer_is_in_developer_mode():
            self.methodSelector.addItem("PNExtract")
        self.methodSelector.setToolTip("Choose the method used to extract the PN")
        parametersFormLayout.addRow("Extraction method: ", self.methodSelector)


#
# PoreNetworkExtractorWidget
#
class PoreNetworkExtractorWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = PoreNetworkExtractorLogic()

        #
        # Input Area: inputFormLayout
        #
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.text = "Input"
        self.layout.addWidget(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)

        # Input volume selector
        self.inputSelector = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLLabelMapVolumeNode", "vtkMRMLScalarVolumeNode"],
            onChange=self.onInputSelectorChange,
        )
        self.inputSelector.showEmptyHierarchyItems = False
        self.inputSelector.objectName = "Input Selector"
        self.inputSelector.setToolTip("Pick a label volume node.")
        inputFormLayout.addRow("Input Volume: ", self.inputSelector)

        self.poresSelectorLabel = qt.QLabel("Pores Labelmap Selector: ")
        self.poresSelectorLabel.visible = False
        self.poresSelector = ui.hierarchyVolumeInput(nodeTypes=["vtkMRMLLabelMapVolumeNode"], hasNone=True)
        self.poresSelector.showEmptyHierarchyItems = False
        self.poresSelector.visible = False
        self.poresSelector.objectName = "Pores Selector"
        inputFormLayout.addRow(self.poresSelectorLabel, self.poresSelector)

        #
        # Parameters Area: parametersFormLayout
        #
        self.paramsWidget = PoreNetworkExtractorParamsWidget()
        self.layout.addWidget(self.paramsWidget)

        #
        # Output Area: outputFormLayout
        #
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.text = "Output"
        self.layout.addWidget(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)

        # Output name prefix
        self.outputPrefix = qt.QLineEdit()
        outputFormLayout.addRow("Output Prefix: ", self.outputPrefix)
        self.outputPrefix.setToolTip("Select prefix text to be used as the name of the output nodes/data.")
        self.outputPrefix.setText("")
        self.outputPrefix.objectName = "Output Prefix"

        #
        # Extract Button
        #
        self.extractButton = ui.ApplyButton(tooltip="Extract the pore-throat network.")
        self.extractButton.objectName = "Apply Button"
        self.layout.addWidget(self.extractButton)
        self.warningsLabel = qt.QLabel("")
        self.warningsLabel.setStyleSheet("QLabel { color: red; font: bold; background-color: black;}")
        self.warningsLabel.setVisible(False)
        self.layout.addWidget(self.warningsLabel)

        #
        # Connections
        #
        self.extractButton.clicked.connect(self.onExtractButton)
        self.onInputSelectorChange(None)

        # Add vertical spacer
        self.layout.addStretch(1)

    def onExtractButton(self):
        self.warningsLabel.setText("")
        self.warningsLabel.setVisible(False)
        try:
            with ProgressBarProc() as pb:
                pb.setMessage("Extracting network")
                pb.setProgress(10)
                extract_result = self.logic.extract(
                    self.inputSelector.currentNode(),
                    self.poresSelector.currentNode(),
                    self.outputPrefix.text,
                    self.paramsWidget.methodSelector.currentText,
                )
                if extract_result:
                    pore_table, throat_table = extract_result
                else:
                    self.setWarning("No connected network was identified. Possible cause: unsegmented pore space.")
                    return

                pb.setMessage("Generating visualization")
                pb.setProgress(80)
                self.logic.visualize(pore_table, throat_table, self.inputSelector.currentNode())
                pb.setMessage("Done")
                pb.setProgress(100)
                time.sleep(0.5)
        except FileNotFoundError:
            self.setWarning("PNExtract failed with input volume.")
        except PoreNetworkExtractorError as e:
            self.setWarning(str(e))

    def setWarning(self, message):
        self.warningsLabel.setText(message)
        logging.warning(message)
        self.warningsLabel.setVisible(True)

    def onInputSelectorChange(self, item):
        input_node = self.inputSelector.currentNode()

        if input_node:
            if not self.isValidPoreNode(input_node):
                self.setWarning("Not a valid input node selected.")
            else:
                self.warningsLabel.setText("")
                self.warningsLabel.setVisible(False)

            self.outputPrefix.setText(input_node.GetName())
            if input_node.IsA("vtkMRMLLabelMapVolumeNode"):
                self.poresSelectorLabel.visible = False
                self.poresSelector.visible = False
            else:
                self.poresSelectorLabel.visible = True
                self.poresSelector.visible = True
                self.poresSelector.setCurrentNode(None)
        else:
            self.outputPrefix.setText("")

    def isValidPoreNode(self, node):
        if node.IsA("vtkMRMLLabelMapVolumeNode"):
            return True

        vrange = node.GetImageData().GetScalarRange()
        is_float = node.GetImageData().GetScalarType() == vtk.VTK_FLOAT
        vmin = 0.0
        vmax = 1.0 if is_float else 100
        return vmin <= vrange[0] <= vmax and vmin <= vrange[1] <= vmax


#
# PoreNetworkExtractorLogic
#
class PoreNetworkExtractorLogic(LTracePluginLogic):
    def extract(
        self,
        inputVolumeNode: slicer.vtkMRMLScalarVolumeNode,
        inputLabelMap: slicer.vtkMRMLLabelMapVolumeNode,
        prefix: str,
        method: str,
    ) -> Union[Tuple[slicer.vtkMRMLTableNode, slicer.vtkMRMLTableNode], bool]:
        if inputVolumeNode.IsA("vtkMRMLLabelMapVolumeNode") and inputLabelMap is None:
            extract_result = pn.general_pn_extract(
                None,
                inputVolumeNode,
                prefix,
                method,
            )
        elif inputVolumeNode:
            extract_result = self.multiscale_extraction(
                inputVolumeNode,
                inputLabelMap,
                prefix,
                method,
            )
        else:
            logging.warning("Not a valid input.")
            return

        return extract_result

    def multiscale_extraction(
        self,
        inputPorosityNode: slicer.vtkMRMLScalarVolumeNode,
        inputWatershed: slicer.vtkMRMLLabelMapVolumeNode,
        prefix: str,
        method: str,
    ):
        porosity_array = slicer.util.arrayFromVolume(inputPorosityNode)
        if np.issubdtype(porosity_array.dtype, np.floating):
            if porosity_array.max() == 1:
                porosity_array = (100 * porosity_array).astype(np.uint8)
            else:
                porosity_array = porosity_array.astype(np.uint8)

        resolved_array = (porosity_array == 100).astype(np.uint8)
        unresolved_array = np.logical_and(porosity_array > 0, porosity_array < 100).astype(np.uint8)
        multiphase_array = resolved_array + (2 * unresolved_array)

        volumesLogic = slicer.modules.volumes.logic()
        multiphaseNode = volumesLogic.CloneVolume(slicer.mrmlScene, inputPorosityNode, "multiphase volume")
        slicer.util.updateVolumeFromArray(multiphaseNode, multiphase_array)

        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemTreeId = folderTree.GetItemByDataNode(inputPorosityNode)
        parentItemId = folderTree.GetItemParent(itemTreeId)
        folderTree.CreateItem(parentItemId, multiphaseNode)

        extract_result = pn.general_pn_extract(
            multiphaseNode,
            inputWatershed,
            prefix=prefix + "_Multiscale",
            method=method,
            porosity_map=porosity_array,
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

    def _pnextract_extract(self, inputVolume: slicer.vtkMRMLLabelMapVolumeNode) -> Union[dict, bool]:
        """
        PNExtract (external application) is unreliably breaking with large volumes.
        This function may be deprecated soon.

        :param inputVolume: The label map volume representing the pore-network.

        :return: A dictionary containing the pore-network properties or False if the input array is None.
        """

        input_array = self._get_connected_array_from_node(inputVolume)

        temporary_folder = slicer.util.tempDirectory()
        output_files = [
            "input_array_link1.dat",
            "input_array_link2.dat",
            "input_array_node1.dat",
            "input_array_node2.dat",
            "input_array_VElems.mhd",
            "input_array_VElems.raw.gz",
        ]

        try:
            array_path = os.path.join(temporary_folder, "input_array.raw")
            if input_array.max() > 1:
                input_array = input_array > 0
            input_array = 1 - input_array
            input_array.astype("uint8").tofile(array_path)
            mhd_path = os.path.join(temporary_folder, "input_array.mhd")
            z, y, x = input_array.shape
            dz, dy, dx = inputVolume.GetSpacing()
            with open(mhd_path, "w") as file:
                file.write(
                    f"""ObjectType =  Image
NDims =       3
ElementType = MET_UCHAR
ElementByteOrderMSB = False

DimSize =    	{x}	{y}	{z}
ElementSize = 	{dx*1000}    {dy*1000}    {dz*1000}
Offset =      	0   	0   	0

ElementDataFile = input_array.raw
VxlPro {{redirect: z }}
''')         
"""
                )

            module_path = os.path.dirname(slicer.util.modulePath("PoreNetworkExtractor"))
            pnextract_path = os.path.join(module_path, "Resources", "pnextract.exe")
            output_path = os.getcwd()
            subprocess.run(
                f"{pnextract_path} {mhd_path}",
                shell=True,
                timeout=PNE_TIMEOUT,
                capture_output=False,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            for file in output_files:
                source_path = os.path.join(output_path, file)
                destination_path = os.path.join(temporary_folder, file)
                os.replace(source_path, destination_path)
            pn_properties = {}

            with open(os.path.join(temporary_folder, "input_array_node1.dat")) as node1_file:
                reader = csv.reader(node1_file, delimiter=" ", skipinitialspace=True)
                _ = reader.__next__()
                pore_coords_0 = []
                pore_coords_1 = []
                pore_coords_2 = []
                for row in reader:
                    pore_coords_0.append(float(row[1].strip()) * 1000)
                    pore_coords_1.append(float(row[2].strip()) * 1000)
                    pore_coords_2.append(float(row[3].strip()) * 1000)
                pn_properties["pore.all"] = np.ones(len(pore_coords_0), dtype=int)
                pn_properties["pore.region_label"] = np.ones(len(pore_coords_0), dtype=int)
                pn_properties["pore.phase"] = np.ones(len(pore_coords_0), dtype=int)
                pn_properties["pore.coords_0"] = np.array(pore_coords_0)
                pn_properties["pore.coords_1"] = np.array(pore_coords_1)
                pn_properties["pore.coords_2"] = np.array(pore_coords_2)
                pn_properties["pore.local_peak_0"] = np.array(pore_coords_0)
                pn_properties["pore.local_peak_1"] = np.array(pore_coords_1)
                pn_properties["pore.local_peak_2"] = np.array(pore_coords_2)
                pn_properties["pore.global_peak_0"] = np.array(pore_coords_0)
                pn_properties["pore.global_peak_1"] = np.array(pore_coords_1)
                pn_properties["pore.global_peak_2"] = np.array(pore_coords_2)
                pn_properties["pore.geometric_centroid_0"] = np.array(pore_coords_0)
                pn_properties["pore.geometric_centroid_1"] = np.array(pore_coords_1)
                pn_properties["pore.geometric_centroid_2"] = np.array(pore_coords_2)

            with open(os.path.join(temporary_folder, "input_array_node2.dat")) as node2_file:
                reader = csv.reader(node2_file, delimiter=" ", skipinitialspace=True)
                pore_equivalent_diameter = []
                pore_region_volume = []
                pore_region_radius = []
                pore_shape_factor = []
                for row in reader:
                    pore_equivalent_diameter.append((6 * float(row[1].strip()) / np.pi) ** (1 / 3) * 1000)
                    pore_region_volume.append(float(row[1].strip()) * 1000**3)
                    pore_region_radius.append(float(row[2].strip()) * 1000)
                    pore_shape_factor.append(float(row[3].strip()))
                pn_properties["pore.equivalent_diameter"] = np.array(pore_equivalent_diameter)
                pn_properties["pore.extended_diameter"] = np.array(pore_equivalent_diameter)
                pn_properties["pore.inscribed_diameter"] = np.array(pore_equivalent_diameter)
                pn_properties["pore.region_volume"] = np.array(pore_region_volume)
                pn_properties["pore.volume"] = np.array(pore_region_volume)
                pn_properties["pore.surface_area"] = (4 * np.pi) * (
                    (3 * np.array(pore_region_volume)) / (4 * np.pi)
                ) ** (2 / 3)
                pn_properties["pore.shape_factor"] = pore_shape_factor
                pn_properties["pore.radius"] = pore_region_radius

            pn_properties["pore.xmin"] = np.zeros(len(pn_properties["pore.all"]), dtype=bool)
            pn_properties["pore.xmax"] = np.zeros(len(pn_properties["pore.all"]), dtype=bool)
            pn_properties["pore.ymin"] = np.zeros(len(pn_properties["pore.all"]), dtype=bool)
            pn_properties["pore.ymax"] = np.zeros(len(pn_properties["pore.all"]), dtype=bool)
            pn_properties["pore.zmin"] = np.zeros(len(pn_properties["pore.all"]), dtype=bool)
            pn_properties["pore.zmax"] = np.zeros(len(pn_properties["pore.all"]), dtype=bool)

            boundary_nodes = []
            with open(os.path.join(temporary_folder, "input_array_link1.dat")) as link1_file:
                reader = csv.reader(link1_file, delimiter=" ", skipinitialspace=True)
                _ = reader.__next__()
                throat_conns_0 = []
                throat_conns_1 = []
                throat_equivalent_diameter = []
                throat_shape_factor = []
                throat_direct_length = []
                for row in reader:
                    index = int(row[0]) + 1
                    left_pore = int(row[1].strip()) - 1
                    right_pore = int(row[2].strip()) - 1
                    if left_pore == -1:
                        pn_properties["pore.xmin"][right_pore] = True
                        boundary_nodes.append(index)
                    if right_pore == -1:
                        pn_properties["pore.xmin"][left_pore] = True
                        boundary_nodes.append(index)
                    if left_pore == -2:
                        pn_properties["pore.xmax"][right_pore] = True
                        boundary_nodes.append(index)
                    if right_pore == -2:
                        pn_properties["pore.xmax"][left_pore] = True
                        boundary_nodes.append(index)
                    throat_conns_0.append(int(row[1].strip()) - 1)
                    throat_conns_1.append(int(row[2].strip()) - 1)
                    throat_equivalent_diameter.append(float(row[3].strip()) * 2000)
                    throat_shape_factor.append(float(row[4].strip()))
                    throat_direct_length.append(float(row[5].strip()) * 1000)
                pn_properties["throat.all"] = np.ones(len(throat_conns_0), dtype=int)
                pn_properties["throat.phases_0"] = np.ones(len(throat_conns_0), dtype=int)
                pn_properties["throat.phases_1"] = np.ones(len(throat_conns_0), dtype=int)
                pn_properties["throat.conns_0"] = np.array(throat_conns_0)
                pn_properties["throat.conns_1"] = np.array(throat_conns_1)
                pn_properties["throat.inscribed_diameter"] = np.array(throat_equivalent_diameter)
                pn_properties["throat.shape_factor"] = np.array(throat_shape_factor)
                pn_properties["throat.direct_length"] = np.array(throat_direct_length)
                pn_properties["throat.total_length"] = np.array(throat_direct_length)
                pn_properties["throat.global_peak_0"] = np.zeros(len(throat_conns_0), dtype=int)
                pn_properties["throat.global_peak_1"] = np.zeros(len(throat_conns_0), dtype=int)
                pn_properties["throat.global_peak_2"] = np.zeros(len(throat_conns_0), dtype=int)
                pn_properties["throat.cross_sectional_area"] = (
                    np.pi * (pn_properties["throat.inscribed_diameter"] / 2) ** 2
                )
                pn_properties["throat.perimeter"] = np.sqrt(
                    pn_properties["throat.cross_sectional_area"] / pn_properties["throat.shape_factor"]
                )
                pn_properties["throat.equivalent_diameter"] = np.array(throat_equivalent_diameter)

            with open(os.path.join(temporary_folder, "input_array_link2.dat")) as link2_file:
                reader = csv.reader(link2_file, delimiter=" ", skipinitialspace=True)
                throat_conns_0_length = []
                throat_conns_1_length = []
                throat_mid_length = []
                throat_volume = []
                for row in reader:
                    index = int(row[0]) + 1
                    throat_conns_0_length.append(float(row[3].strip()) * 1000)
                    throat_conns_1_length.append(float(row[4].strip()) * 1000)
                    throat_mid_length.append(float(row[5].strip()) * 1000)
                    throat_volume.append(float(row[6].strip()) * 1000**3)
                pn_properties["throat.conns_0_length"] = throat_conns_0_length
                pn_properties["throat.conns_1_length"] = throat_conns_1_length
                pn_properties["throat.mid_length"] = throat_mid_length
                pn_properties["throat.volume"] = throat_volume

            for i in range(len(pn_properties["throat.all"])):
                left_pore = pn_properties["throat.conns_0"][i]
                right_pore = pn_properties["throat.conns_1"][i]
                radius = pn_properties["throat.inscribed_diameter"][i]
                for pore, diameter in [
                    (a, b)
                    for a in (left_pore, right_pore)
                    for b in ("pore.equivalent_diameter", "pore.extended_diameter", "pore.inscribed_diameter")
                ]:
                    if pn_properties[diameter][pore] < (radius / MIN_THROAT_RATIO):
                        pn_properties[diameter][pore] = radius / MIN_THROAT_RATIO

        finally:
            e = traceback.extract_stack().format()
            logging.info(e)
            if not slicer_is_in_developer_mode():
                output_files.extend(("input_array.mhd", "input_array.raw"))
                for file in output_files:
                    file_path = os.path.join(temporary_folder, file)
                    os.remove(file_path)
                os.rmdir(temporary_folder)

        return pn_properties


class PoreNetworkExtractorError(RuntimeError):
    pass
