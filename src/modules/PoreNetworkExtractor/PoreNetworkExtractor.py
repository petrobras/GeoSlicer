import json
import logging
import os
import shutil
from pathlib import Path
from typing import Tuple, Union

import ctk
import numpy as np
import qt
import slicer
import slicer.util
import vtk

from ltrace.pore_networks.functions_extract import ExtractionNodesCreator, visualize_network
from ltrace.pore_networks.simulation_parameters_node import (
    parameter_node_to_dict,
    save_dict_to_parameter_node,
    EXTRACTOR_TYPE,
    PNM_PARAMETER_TYPE_ATTR,
)
from ltrace.remote.handlers.PoreNetworkExtractorHandler import PoreNetworkExtractorHandler
from ltrace.remote.slurm import calculate_slurm_parameters
from ltrace.slicer import ui
from ltrace.slicer.app import MANUAL_BASE_URL
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer_utils import (
    LTracePlugin,
    LTracePluginWidget,
    LTracePluginLogic,
    slicer_is_in_developer_mode,
    getResourcePath,
)
from ltrace.utils.mmap_shared_memory import MmapSharedMemory
from ltrace.pore_networks.simulation_parameters_widgets import LoadParamsLayout, SaveParamsLayout

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
        self.parent.title = "PNM Extraction"
        self.parent.categories = ["MicroCT", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.acknowledgementText = ""
        self.setHelpUrl("Volumes/PNM/PNM.html#extractor", NodeEnvironment.MICRO_CT)
        self.setHelpUrl("Multiscale/PNM/PNM.html#extractor", NodeEnvironment.MULTISCALE)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PoreNetworkExtractorParamsWidget(ctk.ctkCollapsibleButton):
    def __init__(self):
        super().__init__()

        self.text = "Parameters"

        parametersFormLayout = qt.QFormLayout()

        # Execution mode
        optionsLayout = qt.QHBoxLayout()
        optionsLayout.setAlignment(qt.Qt.AlignLeft)
        optionsLayout.setContentsMargins(0, 0, 0, 0)
        self.localQRadioButton = qt.QRadioButton("Local")
        self.remoteQRadioButton = qt.QRadioButton("Remote")
        optionsLayout.addWidget(self.localQRadioButton, 0, qt.Qt.AlignCenter)
        optionsLayout.addWidget(self.remoteQRadioButton, 0, qt.Qt.AlignCenter)
        self.localQRadioButton.setChecked(True)
        parametersFormLayout.addRow("Execution Mode:", optionsLayout)
        parametersFormLayout.addRow(" ", None)

        # Global Watershed Blur Info Help
        watershedUsageHelp = HelpButton(
            "Watershed blur options are used during multiscale extraction (when a porosity map is provided as input). \n\n"
            "Note: For single-scale extractions where the input is already an individualized labeled pore "
            "image (LabelMap), these parameters are bypassed."
        )
        parametersFormLayout.addRow("Watershed Blur Options:", watershedUsageHelp)

        # Watershed blur
        self.blurWidgets = []

        resolvedBlurHelp = HelpButton(
            "Defines gaussian blur to be applied to the resolved "
            "phase image watershed. Values are voxel scaled, and "
            "don't depend on voxel dimension. Higher values lead "
            "to less pores on this phase."
        )
        self.resolvedBlurEdit = ui.floatParam(0.4)
        hbox = qt.QHBoxLayout()
        hbox.addWidget(self.resolvedBlurEdit)
        hbox.addWidget(resolvedBlurHelp)
        self.resolvedBlurLabel = qt.QLabel("Resolved Watershed blur: ")
        parametersFormLayout.addRow(self.resolvedBlurLabel, hbox)
        self.blurWidgets.extend([self.resolvedBlurEdit, resolvedBlurHelp, self.resolvedBlurLabel])

        subscaleBlurHelp = HelpButton(
            "Defines gaussian blur to be applied to the subresolution "
            "phase image watershed. Values are voxel scaled, and "
            "don't depend on voxel dimension. Higher values lead "
            "to less pores on this phase."
        )
        self.subscaleBlurEdit = ui.floatParam(0.8)
        hbox = qt.QHBoxLayout()
        hbox.addWidget(self.subscaleBlurEdit)
        hbox.addWidget(subscaleBlurHelp)
        self.subscaleBlurLabel = qt.QLabel("Subres Watershed blur: ")
        parametersFormLayout.addRow(self.subscaleBlurLabel, hbox)
        self.blurWidgets.extend([self.subscaleBlurEdit, subscaleBlurHelp, self.subscaleBlurLabel])

        # Method selector
        self.methodSelector = qt.QComboBox()
        self.methodSelector.addItem("PoreSpy")
        if slicer_is_in_developer_mode():
            self.methodSelector.addItem("PNExtract")
        self.methodSelector.setToolTip("Choose the method used to extract the PN")
        parametersFormLayout.addRow("Extraction method: ", self.methodSelector)

        # Generate visualization
        self.generateVisualizationCheckbox = qt.QCheckBox()
        self.generateVisualizationCheckbox.objectName = "Generate Visualization Checkbox"
        self.generateVisualizationCheckbox.setToolTip(
            "Enable to generate visualization model nodes. Note: For large projects, the generated model nodes may consume significant disk space when saved."
        )
        parametersFormLayout.addRow("Generate visualization:", self.generateVisualizationCheckbox)

        slurmFrame = ctk.ctkCollapsibleButton()
        slurmFrame.flat = True
        slurmFrame.text = "Slurm"
        slurmFormLayout = qt.QFormLayout(slurmFrame)
        self.slurmCpusPerNode = ui.intParam(40)
        slurmFormLayout.addRow("CPUs per node:", self.slurmCpusPerNode)
        self.slurmMemoryPerNode = ui.intParam(350)
        slurmFormLayout.addRow("Memory per node (GB):", self.slurmMemoryPerNode)

        self.slurmJobsEdit = ui.intParam(4)
        self.slurmJobsEdit.setEnabled(slicer_is_in_developer_mode())
        slurmFormLayout.addRow("SLURM Jobs:", self.slurmJobsEdit)
        self.slurmCoresEdit = ui.intParam(1)
        self.slurmCoresEdit.setEnabled(slicer_is_in_developer_mode())
        slurmFormLayout.addRow("SLURM Cores:", self.slurmCoresEdit)
        self.slurmMemoryEdit = qt.QLineEdit("2GB")
        self.slurmMemoryEdit.setEnabled(slicer_is_in_developer_mode())
        slurmFormLayout.addRow("SLURM Memory:", self.slurmMemoryEdit)

        parallelizationFormLayout = qt.QFormLayout()
        self.divsEdit = ui.intParam(2)
        self.chunkSizeLabel = qt.QLabel("0 MB")
        parallelizationFormLayout.addRow("Divs:", self.divsEdit)
        parallelizationFormLayout.addRow("Chunk size:", self.chunkSizeLabel)
        parallelizationFormLayout.addRow(slurmFrame)

        slurmFrame.setVisible(self.remoteQRadioButton.isChecked())
        self.remoteQRadioButton.toggled.connect(lambda: slurmFrame.setVisible(self.remoteQRadioButton.isChecked()))

        mainLayout = qt.QVBoxLayout(self)
        mainLayout.addLayout(parametersFormLayout)
        mainLayout.addLayout(parallelizationFormLayout)


#
# PoreNetworkExtractorWidget
#
class PoreNetworkExtractorWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = PoreNetworkExtractorLogic(self.parent, self.progressBar)
        self.logic.extractionFinished.connect(self.onExtractionLogicFinished)

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
        self.inputSelector.setToolTip(
            "Select a labelmap volume with individualized pores (generated in Segmentation → Segment Inspector) or a porosity map (generated in the Microporosity tab)."
        )
        manualPath = f"{MANUAL_BASE_URL}Volumes/PNM/PNM.html#extractor"
        inputSelectorHelp = HelpButton(
            "Select a labelmap volume with individualized pores (generated in Segmentation → Segment Inspector) or a porosity map (generated in the Microporosity tab).\n\n"
            "- If a labelmap is selected, extraction will be single-scale;\n\n- If a scalar volume (porosity map) is selected, extraction will be multiscale (resolved + unresolved pores);"
            "\n\n-----\n[More]({path_to_manual})",
            replacer=lambda x: x.format(path_to_manual=manualPath),
        )
        hbox = qt.QHBoxLayout()
        hbox.addWidget(self.inputSelector)
        hbox.addWidget(inputSelectorHelp)

        inputFormLayout.addRow("Input Volume: ", hbox)

        self.poresSelectorLabel = qt.QLabel("Labeled Pores (optional): ")
        self.poresSelectorLabel.visible = False
        self.poresSelector = ui.hierarchyVolumeInput(nodeTypes=["vtkMRMLLabelMapVolumeNode"], hasNone=True)
        self.poresSelector.setToolTip(
            "If a porosity map is selected, you can specify a LabelMap with individualized pores."
        )
        self.poresSelector.showEmptyHierarchyItems = False
        self.poresSelector.visible = False
        self.poresSelector.objectName = "Pores Selector"
        self.poresSelectorHelp = HelpButton(
            "If a porosity map is selected, you can optionally specify a LabelMap with individually labeled pores. The software will compute the mean porosity within each labeled region."
        )
        self.poresSelectorHelp.visible = False
        hbox = qt.QHBoxLayout()
        hbox.addWidget(self.poresSelector)
        hbox.addWidget(self.poresSelectorHelp)

        inputFormLayout.addRow(self.poresSelectorLabel, hbox)

        #
        # Parameters Area: parametersFormLayout
        #
        self.paramsWidget = PoreNetworkExtractorParamsWidget()
        self.paramsWidget.divsEdit.editingFinished.connect(self.updateSlurmParams)
        self.paramsWidget.slurmCpusPerNode.editingFinished.connect(self.updateSlurmParams)
        self.paramsWidget.slurmMemoryPerNode.editingFinished.connect(self.updateSlurmParams)
        self.layout.addWidget(self.paramsWidget)

        #
        # Parameters Management Area (Load and Save together) - Placed inside parameters collapsible
        #
        self.loadParamsLayout = LoadParamsLayout(EXTRACTOR_TYPE, self.onParameterInputLoad)
        self.parameterInputLoadCollapsible = self.loadParamsLayout.collapsible
        self.parameterInputWidget = self.loadParamsLayout.parameterInputWidget
        self.paramsWidget.layout().insertLayout(0, self.loadParamsLayout)

        self.saveParamsLayout = SaveParamsLayout("extraction_input_parameters", self.onParameterInputSave)
        self.parameterInputLineEdit = self.saveParamsLayout.lineEdit
        self.paramsWidget.layout().insertLayout(1, self.saveParamsLayout)

        #
        # Utilities Area
        #
        self.utilitiesCollapsibleButton = ctk.ctkCollapsibleButton()
        self.utilitiesCollapsibleButton.text = "Utilities"
        self.utilitiesCollapsibleButton.collapsed = True
        self.layout.addWidget(self.utilitiesCollapsibleButton)
        utilitiesLayout = qt.QVBoxLayout(self.utilitiesCollapsibleButton)

        generateHintLabel = qt.QLabel("Use this utility to generate the visualization of a pore network from a table.")
        utilitiesLayout.addWidget(generateHintLabel)

        self.poreTableSelector = ui.hierarchyVolumeInput(nodeTypes=["vtkMRMLTableNode"])
        self.poreTableSelector.addNodeAttributeIncludeFilter("table_type", "pore_table")
        self.poreTableSelector.setToolTip("Select a pore network table to generate its visualization.")
        self.poreTableSelector.objectName = "Pore Table Selector"
        generateFormLayout = qt.QFormLayout()
        generateFormLayout.addRow("Pore Table:", self.poreTableSelector)
        utilitiesLayout.addLayout(generateFormLayout)

        self.generateVisualizationButton = ui.ApplyButton(tooltip="Generate the pore network visualization.")
        self.generateVisualizationButton.objectName = "Generate Visualization Button"
        self.generateVisualizationButton.text = "Generate Visualization"
        utilitiesLayout.addWidget(self.generateVisualizationButton)

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

        # Extract Button
        self.extractButton = ui.ApplyButton(tooltip="Extract the pore-throat network.")
        self.extractButton.objectName = "Apply Button"

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.objectName = "Cancel Button"
        self.cancelButton.setToolTip("Cancel the extraction process.")
        self.cancelButton.setEnabled(False)
        self.cancelButton.setSizePolicy(self.extractButton.sizePolicy)

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(self.extractButton)
        buttonsLayout.addWidget(self.cancelButton)
        self.layout.addLayout(buttonsLayout)
        self.warningsLabel = qt.QLabel("")
        self.warningsLabel.setStyleSheet("QLabel { color: yellow;}")
        self.warningsLabel.setVisible(False)
        self.warningsLabel.setWordWrap(True)
        self.layout.addWidget(self.warningsLabel)

        self.layout.addWidget(self.progressBar)

        #
        # Connections
        #
        self.extractButton.clicked.connect(self.onExtractButton)
        self.cancelButton.clicked.connect(self.onCancelButton)
        self.generateVisualizationButton.clicked.connect(self.onGenerateVisualizationButton)
        self.onInputSelectorChange(None)

        # Add vertical spacer
        self.layout.addStretch(1)

    def onCancelButton(self):
        self.logic.cancel()

    def onLocalExtractionFinished(self, success):
        self.extractButton.setEnabled(True)
        self.cancelButton.setEnabled(False)

    def onExtractionLogicFinished(self, success):
        if self.paramsWidget.localQRadioButton.isChecked():
            self.onLocalExtractionFinished(success)
        else:
            self.showJobs()

    def updateSlurmParams(self):
        # Read volume node
        currentNode = self.inputSelector.currentNode()
        if currentNode is None:
            return
        volumeArray = slicer.util.arrayFromVolume(currentNode)
        volumeShape = np.array(volumeArray.shape)

        # Set constants
        numberOfCpusPerNode = int(self.paramsWidget.slurmCpusPerNode.text)
        maximumMemoryPerNodeGb = int(self.paramsWidget.slurmMemoryPerNode.text)

        # Estimate required resources
        divs = int(self.paramsWidget.divsEdit.text)
        divs = max(1, divs)

        # Calculate using the standalone function
        slurm_params = calculate_slurm_parameters(
            volume_shape=volumeShape,
            itemsize=volumeArray.itemsize,
            divs=divs,
            cpus_per_node=numberOfCpusPerNode,
            max_memory_per_node_gb=maximumMemoryPerNodeGb,
        )

        # Extract results
        bytesPerChunk = slurm_params["bytes_per_chunk"]
        slurmJobs = slurm_params["slurm_jobs"]
        slurmCores = slurm_params["slurm_cores"]
        slurmMemory = slurm_params["slurm_memory_gb"]

        # Update parameters
        if slurmMemory > maximumMemoryPerNodeGb:
            self.paramsWidget.slurmMemoryEdit.setStyleSheet(":enabled {color: #600000;} :disabled {color: #600000;}")
            slurmMemory = maximumMemoryPerNodeGb
        else:
            self.paramsWidget.slurmMemoryEdit.setStyleSheet("")

        self.paramsWidget.chunkSizeLabel.text = f"{int(bytesPerChunk // 10**6)} MB"
        self.paramsWidget.slurmJobsEdit.text = str(slurmJobs)
        self.paramsWidget.slurmCoresEdit.text = str(slurmCores)
        self.paramsWidget.slurmMemoryEdit.text = f"{slurmMemory}GB"

    def onExtractButton(self):
        localMode = self.paramsWidget.localQRadioButton.isChecked()
        if localMode:
            self.extractButton.setEnabled(False)
            self.cancelButton.setEnabled(True)
            self.warningsLabel.setText("")
            self.warningsLabel.setVisible(False)
            parallel_params = {
                "divs": int(self.paramsWidget.divsEdit.text),
            }
        else:
            parallel_params = {
                "divs": int(self.paramsWidget.divsEdit.text),
                "slurm_jobs": int(self.paramsWidget.slurmJobsEdit.text),
                "slurm_cores": int(self.paramsWidget.slurmCoresEdit.text),
                "slurm_memory": self.paramsWidget.slurmMemoryEdit.text,
            }

        watershed_blur = {
            "1": float(self.paramsWidget.resolvedBlurEdit.text),
            "2": float(self.paramsWidget.subscaleBlurEdit.text),
        }

        self.logic.extract(
            self.inputSelector.currentNode(),
            self.poresSelector.currentNode(),
            self.outputPrefix.text,
            self.paramsWidget.generateVisualizationCheckbox.isChecked(),
            self.paramsWidget.methodSelector.currentText,
            watershed_blur,
            localMode,
            parallel_params,
        )

    def setWarning(self, message):
        self.warningsLabel.setText(message)
        logging.warning(message)
        self.warningsLabel.setVisible(True)

    def onInputSelectorChange(self, item):
        input_node = self.inputSelector.currentNode()

        if input_node:
            eval_string = self.evalPoreNode(input_node)
            self.setWarning(eval_string)

            self.outputPrefix.setText(input_node.GetName())
            if input_node.IsA("vtkMRMLLabelMapVolumeNode"):
                self.poresSelectorLabel.visible = False
                self.poresSelector.visible = False
                self.poresSelectorHelp.visible = False
                self.poresSelector.setCurrentNode(None)
                self.extractButton.setEnabled(True)
            else:
                self.poresSelectorLabel.visible = True
                self.poresSelector.visible = True
                self.poresSelectorHelp.visible = True
                self.poresSelector.setCurrentNode(None)
                self.extractButton.setEnabled(True)
        else:
            self.outputPrefix.setText("")

        self.updateSlurmParams()

    def evalPoreNode(self, node):
        isLabelMap = node.IsA("vtkMRMLLabelMapVolumeNode")
        vrange = node.GetImageData().GetScalarRange()
        is_float = node.GetImageData().GetScalarType() in [vtk.VTK_FLOAT, vtk.VTK_DOUBLE]

        if isLabelMap:
            eval_string = "Input is a labeled pores image for single scale extraction."
        else:
            eval_string = "Input is a porosity map image for multiscale extraction."
            if is_float and vrange[1] <= 1:
                eval_string += " Values are float type interpreted as porosity ratio between 0 and 1."
            elif is_float:
                eval_string += " Values are float type interpreted as porosity percentage between 0 and 100."
            else:
                eval_string += " Values are int type interpreted as porosity percentage between 0 and 100."
            if vrange[1] > 100:
                eval_string += f" There are numbers over 100 detected ({vrange[1]}), intepreted as 100 porosity."
            if vrange[0] < 0:
                eval_string += f" There are negative numbers detected ({vrange[0]}), intepreted as 0 porosity."
        return eval_string

    def isValidPoreNode(self, node):
        if node.IsA("vtkMRMLLabelMapVolumeNode"):
            return True

        vrange = node.GetImageData().GetScalarRange()
        is_float = node.GetImageData().GetScalarType() == vtk.VTK_FLOAT
        vmin = 0.0
        vmax = 1.0 if is_float else 100
        return vmin <= vrange[0] <= vmax and vmin <= vrange[1] <= vmax

    def showJobs(self):
        """this function open a dialog to confirm and if yes, emit the signal to delete the results"""
        msg = qt.QMessageBox()
        msg.setIcon(qt.QMessageBox.Warning)
        msg.setText("Your job was succesfully scheduled on cluster. Do you want to move to job monitor view?")
        msg.setWindowTitle("Show jobs")
        msg.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
        msg.setDefaultButton(qt.QMessageBox.No)
        if msg.exec_() == qt.QMessageBox.Yes:
            slicer.modules.AppContextInstance.rightDrawer.show(1)

    def onGenerateVisualizationButton(self):
        poreTableNode = self.poreTableSelector.currentNode()
        if not poreTableNode:
            slicer.util.warningDisplay("Please select a Pore Table to generate visualization.")
            return

        # Get throat table node
        throatTableNodeId = poreTableNode.GetNodeReferenceID("throat_table")
        if not throatTableNodeId:
            slicer.util.errorDisplay("Selected Pore Table does not reference a Throat Table.")
            return
        throatTableNode = slicer.mrmlScene.GetNodeByID(throatTableNodeId)
        if not throatTableNode:
            slicer.util.errorDisplay("Referenced Throat Table not found in the scene.")
            return

        # Generate metadata
        try:
            spacing_str = [
                poreTableNode.GetAttribute("x_spacing"),
                poreTableNode.GetAttribute("y_spacing"),
                poreTableNode.GetAttribute("z_spacing"),
            ]
            origin_str = (
                poreTableNode.GetAttribute("origin").split(";")
                if poreTableNode.GetAttribute("origin")
                else ["0.0", "0.0", "0.0"]
            )

            spacing = [float(s) for s in spacing_str]
            origin = [float(o) for o in origin_str]

            watershedNodeId = poreTableNode.GetNodeReferenceID("watershed")
            if not watershedNodeId:
                slicer.util.errorDisplay("Referenced Watershed Volume not found. Cannot determine geometry.")
                return

            watershedNode = slicer.mrmlScene.GetNodeByID(watershedNodeId)
            if not watershedNode:
                slicer.util.errorDisplay("Referenced Watershed Volume not found in the scene.")
                return

            bounds = [0.0] * 6
            watershedNode.GetBounds(bounds)

            ijkToRasMatrix = vtk.vtkMatrix4x4()
            watershedNode.GetIJKToRASDirectionMatrix(ijkToRasMatrix)
            ijktorasmatrix = slicer.util.arrayFromVTKMatrix(ijkToRasMatrix).tolist()

            metadata = {
                "spacing": spacing,
                "origin": origin,
                "ijktorasmatrix": ijktorasmatrix,
                "bounds": bounds,
            }
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            slicer.util.errorDisplay(f"Failed to parse metadata from Pore Table attributes: {e}")
            return

        # Generate visualization
        try:
            model_nodes = visualize_network(poreTableNode, throatTableNode, metadata, prefix="")
            if model_nodes:
                folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

                # Find the parent of the poreTableNode to place the models alongside
                pore_table_item_id = folderTree.GetItemByDataNode(poreTableNode)
                parent_item_id = folderTree.GetItemParent(pore_table_item_id)

                # Create a subfolder for the visualization models
                visualization_folder_name = f"{poreTableNode.GetName()}_Visualization"
                visualization_folder_item_id = folderTree.CreateFolderItem(parent_item_id, visualization_folder_name)

                for node_type in model_nodes:
                    for node in model_nodes[node_type]:
                        node_item_id = folderTree.GetItemByDataNode(node)
                        folderTree.SetItemParent(node_item_id, visualization_folder_item_id)
                        # Make them visible
                        node.SetDisplayVisibility(True)
        except Exception as e:
            slicer.util.errorDisplay(f"Error generating Pore Network Visualization: {e}")

    def getParams(self):
        parameters_dict = {
            "execution_mode": "Local" if self.paramsWidget.localQRadioButton.isChecked() else "Remote",
            "watershed_blur": {
                "1": float(self.paramsWidget.resolvedBlurEdit.text),
                "2": float(self.paramsWidget.subscaleBlurEdit.text),
            },
            "method": self.paramsWidget.methodSelector.currentText,
            "generate_visualization": self.paramsWidget.generateVisualizationCheckbox.isChecked(),
            "divs": int(self.paramsWidget.divsEdit.text),
        }
        return parameters_dict

    def setParams(self, params):
        if "execution_mode" in params:
            if params["execution_mode"] == "Local":
                self.paramsWidget.localQRadioButton.setChecked(True)
            else:
                self.paramsWidget.remoteQRadioButton.setChecked(True)

        wb_dict = params["watershed_blur"]
        if "1" in wb_dict:
            self.paramsWidget.resolvedBlurEdit.text = str(wb_dict["1"])
        if "2" in wb_dict:
            self.paramsWidget.subscaleBlurEdit.text = str(wb_dict["2"])

        if "method" in params:
            self.paramsWidget.methodSelector.setCurrentText(params["method"])
        if "generate_visualization" in params:
            self.paramsWidget.generateVisualizationCheckbox.setChecked(params["generate_visualization"])
        if "divs" in params:
            self.paramsWidget.divsEdit.text = str(params["divs"])

        self.updateSlurmParams()

    def onParameterInputLoad(self):
        selectedNode = self.parameterInputWidget.currentNode()
        if selectedNode:
            parameters_dict = parameter_node_to_dict(selectedNode)
            self.setParams(parameters_dict)
            self.parameterInputLoadCollapsible.collapsed = True

    def onParameterInputSave(self):
        parameterValues = self.getParams()
        currentNode = self.inputSelector.currentNode()
        parameterNode = save_dict_to_parameter_node(
            parameterValues, self.parameterInputLineEdit.text, currentNode, node_type=EXTRACTOR_TYPE
        )
        slicer.app.applicationLogic().GetSelectionNode().SetActiveTableID(parameterNode.GetID())
        slicer.app.applicationLogic().PropagateTableSelection()


#
# PoreNetworkExtractorLogic
#
class PoreNetworkExtractorLogic(LTracePluginLogic):
    extractionFinished = qt.Signal(bool)

    def __init__(self, parent, progressBar):
        LTracePluginLogic.__init__(self, parent)
        self.cliNode = None
        self.progressBar = progressBar
        self.prefix = None
        self.rootDir = None
        self.results = {}
        self.visualization = False
        self.params = None
        self.watershed_output_memory = None
        self.watershed_output_shape = None

    def extract(
        self,
        inputVolumeNode: slicer.vtkMRMLScalarVolumeNode,
        inputLabelMap: slicer.vtkMRMLLabelMapVolumeNode,
        prefix: str,
        visualization: bool,
        method: str,
        watershed_blur: list,
        localMode: bool,
        parallel_params: dict = {},
    ) -> Union[Tuple[slicer.vtkMRMLTableNode, slicer.vtkMRMLTableNode], bool]:
        self.cwd = Path(slicer.util.tempDirectory())
        self.visualization = visualization
        self.localMode = localMode
        self.prefix = prefix
        self.params = {"prefix": prefix, "method": method, "watershed_blur": watershed_blur}
        cliParams = {"cwd": str(self.cwd)}
        self.watershed_output_memory = None

        self.inputNodeID = inputVolumeNode.GetID()
        if inputLabelMap is not None:
            self.labelNodeID = inputLabelMap.GetID()
        else:
            self.labelNodeID = None

        if inputVolumeNode.IsA("vtkMRMLLabelMapVolumeNode") and inputLabelMap is None:
            self.params["is_multiscale"] = False
        elif inputVolumeNode.IsA("vtkMRMLScalarVolumeNode"):
            self.params["is_multiscale"] = True
        else:
            logging.warning("Not a valid input.")
            return

        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        ijkToRasMatrix = vtk.vtkMatrix4x4()
        inputVolumeNode.GetIJKToRASDirectionMatrix(ijkToRasMatrix)

        bounds = [0.0] * 6
        inputVolumeNode.GetBounds(bounds)

        metadata = {
            "spacing": list(inputVolumeNode.GetSpacing()),
            "origin": list(inputVolumeNode.GetOrigin()),
            "ijktorasmatrix": slicer.util.arrayFromVTKMatrix(ijkToRasMatrix).tolist(),
            "bounds": list(bounds),
        }

        self.params.update({"metadata": metadata})

        self.params["scale"] = str(inputVolumeNode.GetSpacing()[::-1])

        if self.params["is_multiscale"] is False:
            self.scalar_memory = None
            label_array = slicer.util.arrayFromVolume(inputVolumeNode)
            self.label_memory = MmapSharedMemory.create_array(label_array)
            label_dtype = label_array.dtype.str
            label_shape = str(label_array.shape)
            self.params["label_dtype"] = label_dtype
            self.params["label_shape"] = label_shape
            cliParams["label"] = self.label_memory.name

        elif self.params["is_multiscale"] is True:
            scalar_array = slicer.util.arrayFromVolume(inputVolumeNode)
            self.scalar_memory = MmapSharedMemory.create_array(scalar_array)
            scalar_dtype = scalar_array.dtype.str
            scalar_shape = str(scalar_array.shape)
            self.params["scalar_dtype"] = scalar_dtype
            self.params["scalar_shape"] = scalar_shape
            cliParams["scalar"] = self.scalar_memory.name

            if inputLabelMap:
                label_array = slicer.util.arrayFromVolume(inputLabelMap)
                self.label_memory = MmapSharedMemory.create_array(label_array)
                label_dtype = label_array.dtype.str
                label_shape = str(label_array.shape)
                self.params["label_dtype"] = label_dtype
                self.params["label_shape"] = label_shape
                cliParams["label"] = self.label_memory.name
            else:
                self.label_memory = None

        if localMode:
            self.semaphore_shm = MmapSharedMemory.create(1)
            self.semaphore_shm.buf[0] = 0
            cliParams["semaphore"] = self.semaphore_shm.name
            cliParams["divs"] = parallel_params["divs"]
            with open(str(self.cwd / "extractor_params_dict.json"), "w") as file:
                json.dump(self.params, file)
            self.cliNode = slicer.cli.run(slicer.modules.porenetworkextractorcli, None, cliParams)
            self.progressBar.setCommandLineModuleNode(self.cliNode)
            self.cliNode.AddObserver("ModifiedEvent", self.extractCLICallback)
        else:
            job_name = f"PNM Extract: {self.prefix}"
            self.handler = PoreNetworkExtractorHandler(
                self.inputNodeID, self.labelNodeID, self.visualization, self.params, parallel_params
            )
            success = slicer.modules.RemoteServiceInstance.cli.run(self.handler, name=job_name, job_type="pnmextractor")
            if success:
                self.extractionFinished.emit(True)

    def cancel(self):
        if self.cliNode is None:
            return
        self.cliNode.Cancel()

    def extractCLICallback(self, caller, event):
        if caller is None:
            self.cliNode = None
            return
        if self.cliNode is None:
            return

        if self.semaphore_shm.buf[0] == 1:
            with open(str(self.cwd / "shm_info.txt"), "r", encoding="utf-8") as f:
                watershed_output_name = f.readline().strip()
                watershed_output_shape = tuple(map(int, f.readline().split()))
            self.watershed_output_memory = MmapSharedMemory.from_file(watershed_output_name)
            self.watershed_output_shape = watershed_output_shape
            self.semaphore_shm.buf[0] = 2

        status = caller.GetStatusString()
        if status in ["Completed", "Cancelled", "Completed with errors"]:
            logging.info(status)
            del self.cliNode
            self.cliNode = None
            if status == "Completed":
                self.onFinish()
                shutil.rmtree(self.cwd)

            self.extractionFinished.emit(True)

    def onFinish(self):
        metadata = self.params["metadata"]
        inputVolumeNode = slicer.mrmlScene.GetNodeByID(self.inputNodeID)
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        inputVolumeItemID = shNode.GetItemByDataNode(inputVolumeNode)
        parentItemID = shNode.GetItemParent(inputVolumeItemID)

        extraction_nodes_creator = ExtractionNodesCreator(
            metadata,
            self.cwd,
            self.prefix,
            self.visualization,
            self.inputNodeID,
            self.watershed_output_memory,
            self.watershed_output_shape,
        )
        try:
            self.results = extraction_nodes_creator.create(parent_folder=parentItemID)
        except FileNotFoundError as e:
            error_message = str(e)
            logging.error(error_message)
            slicer.util.errorDisplay(f"Cannot create Pore Network.\n\n{error_message}", windowTitle="Missing Data")
        except Exception as e:
            # Catch-all for other potential issues during node creation
            logging.error(f"Unexpected error creating nodes: {str(e)}")
            slicer.util.errorDisplay(f"An error occurred: {str(e)}")
        if self.watershed_output_memory is not None:
            self.watershed_output_memory.close()


class PoreNetworkExtractorError(RuntimeError):
    pass
