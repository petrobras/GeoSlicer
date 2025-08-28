import json
import logging
import os
import shutil
from pathlib import Path
from typing import Tuple, Union

import ctk
import pandas as pd
import qt
import slicer
import slicer.util
import vtk

import ltrace.pore_networks.functions as pn
from ltrace.remote.handlers.PoreNetworkExtractorHandler import PoreNetworkExtractorHandler
from ltrace.slicer import ui
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer_utils import (
    LTracePlugin,
    LTracePluginWidget,
    LTracePluginLogic,
    slicer_is_in_developer_mode,
    dataFrameToTableNode,
    getResourcePath,
)

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
        self.parent.helpText = f"file:///{(getResourcePath('manual') / 'Modules/PNM/PNExtraction.html').as_posix()}"
        self.parent.acknowledgementText = ""

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PoreNetworkExtractorParamsWidget(ctk.ctkCollapsibleButton):
    def __init__(self):
        super().__init__()

        self.text = "Parameters"
        parametersFormLayout = qt.QFormLayout(self)

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

        # Watershed blur
        self.blurWidgets = []

        resolvedBlurHelp = HelpButton(
            "Defines gaussian blur to be aplied to the resolved "
            "phase image watershed. Values are voxel scaled, and "
            "don't depend on voxel dimension. Higher values lead "
            "to less pores on this phase."
        )
        self.resolvedBlurEdit = ui.floatParam(0.4)
        hbox = qt.QHBoxLayout()
        hbox.addWidget(self.resolvedBlurEdit)
        hbox.addWidget(resolvedBlurHelp)
        self.resolvedBlurLabel = qt.QLabel("Resolved Watershed blur: ")
        parametersFormLayout.addRow(
            self.resolvedBlurLabel,
            hbox,
        )
        self.blurWidgets.append(self.resolvedBlurEdit)
        self.blurWidgets.append(resolvedBlurHelp)
        self.blurWidgets.append(self.resolvedBlurLabel)

        subscaleBlurHelp = HelpButton(
            "Defines gaussian blur to be aplied to the subresolution "
            "phase image watershed. Values are voxel scaled, and "
            "don't depend on voxel dimension. Higher values lead "
            "to less pores on this phase."
        )
        self.subscaleBlurEdit = ui.floatParam(0.8)
        hbox = qt.QHBoxLayout()
        hbox.addWidget(self.subscaleBlurEdit)
        hbox.addWidget(subscaleBlurHelp)
        self.subscaleBlurLabel = qt.QLabel("Subresolution Watershed blur: ")
        parametersFormLayout.addRow(
            self.subscaleBlurLabel,
            hbox,
        )
        self.blurWidgets.append(self.subscaleBlurEdit)
        self.blurWidgets.append(subscaleBlurHelp)
        self.blurWidgets.append(self.subscaleBlurLabel)

        for widget in self.blurWidgets:
            widget.visible = False

        # Method selector
        self.methodSelector = qt.QComboBox()
        self.methodSelector.addItem("PoreSpy")
        if slicer_is_in_developer_mode():
            self.methodSelector.addItem("PNExtract")
        self.methodSelector.setToolTip("Choose the method used to extract the PN")
        parametersFormLayout.addRow("Extraction method: ", self.methodSelector)

        # Generate visualization
        self.generateVisualizationCheckbox = qt.QCheckBox()
        self.generateVisualizationCheckbox.setToolTip(
            "Enable to generate visualization model nodes. Note: For large projects, the generated model nodes may consume significant disk space when saved."
        )
        parametersFormLayout.addRow("Generate visualization:", self.generateVisualizationCheckbox)


#
# PoreNetworkExtractorWidget
#
class PoreNetworkExtractorWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = PoreNetworkExtractorLogic(self.parent, self.progressBar)

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
        manual_path = getResourcePath("manual") / "Modules" / "PNM"
        inputSelectorHelp = HelpButton(
            "Select a labelmap volume with individualized pores (generated in Segmentation → Segment Inspector) or a porosity map (generated in the Microporosity tab).\n\n"
            "- If a labelmap is selected, extraction will be single-scale;\n\n- If a scalar volume (porosity map) is selected, extraction will be multiscale (resolved + unresolved pores);"
            "\n\n-----\n[More]({path_to_manual})",
            replacer=lambda x: x.format(path_to_manual=(manual_path / "PNExtraction.html").as_posix()),
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

        self.layout.addWidget(self.progressBar)

        #
        # Connections
        #
        self.extractButton.clicked.connect(self.onExtractButton)
        self.onInputSelectorChange(None)

        # Add vertical spacer
        self.layout.addStretch(1)

    def onExtractButton(self):
        localMode = self.paramsWidget.localQRadioButton.isChecked()
        if localMode:
            self.extractButton.setEnabled(False)
            self.warningsLabel.setText("")
            self.warningsLabel.setVisible(False)
            callback = self.extractButton.setEnabled
        else:
            callback = self.showJobs

        watershed_blur = {
            1: float(self.paramsWidget.resolvedBlurEdit.text),
            2: float(self.paramsWidget.subscaleBlurEdit.text),
        }
        self.logic.extract(
            self.inputSelector.currentNode(),
            self.poresSelector.currentNode(),
            self.outputPrefix.text,
            self.paramsWidget.generateVisualizationCheckbox.isChecked(),
            self.paramsWidget.methodSelector.currentText,
            watershed_blur,
            callback,
            localMode,
        )

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
                self.poresSelectorHelp.visible = False
                self.poresSelector.setCurrentNode(None)
                for widget in self.paramsWidget.blurWidgets:
                    widget.visible = False
            else:
                self.poresSelectorLabel.visible = True
                self.poresSelector.visible = True
                self.poresSelectorHelp.visible = True
                self.poresSelector.setCurrentNode(None)
                for widget in self.paramsWidget.blurWidgets:
                    widget.visible = True
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


#
# PoreNetworkExtractorLogic
#
class PoreNetworkExtractorLogic(LTracePluginLogic):
    def __init__(self, parent, progressBar):
        LTracePluginLogic.__init__(self, parent)
        self.cliNode = None
        self.progressBar = progressBar
        self.prefix = None
        self.rootDir = None
        self.results = {}
        self.visualization = False

    def extract(
        self,
        inputVolumeNode: slicer.vtkMRMLScalarVolumeNode,
        inputLabelMap: slicer.vtkMRMLLabelMapVolumeNode,
        prefix: str,
        visualization: bool,
        method: str,
        watershed_blur: list,
        callback,
        localMode,
    ) -> Union[Tuple[slicer.vtkMRMLTableNode, slicer.vtkMRMLTableNode], bool]:
        params = {"prefix": prefix, "method": method}

        self.visualization = visualization

        self.inputNodeID = inputVolumeNode.GetID()
        labelNodeID = None
        if inputLabelMap:
            labelNodeID = inputLabelMap.GetID()

        if inputVolumeNode.IsA("vtkMRMLLabelMapVolumeNode") and inputLabelMap is None:
            params["is_multiscale"] = False
        elif inputVolumeNode:
            params["is_multiscale"] = True
        else:
            logging.warning("Not a valid input.")
            return

        params["watershed_blur"] = watershed_blur

        self.cwd = Path(slicer.util.tempDirectory())
        self.callback = callback
        self.prefix = prefix

        if localMode:
            cliParams = {"cwd": str(self.cwd)}
            cliParams["volume"] = self.inputNodeID
            if labelNodeID:
                cliParams["label"] = labelNodeID
            with open(str(self.cwd / "params_dict.json"), "w") as file:
                json.dump(params, file)
            self.cliNode = slicer.cli.run(slicer.modules.porenetworkextractorcli, None, cliParams)
            self.progressBar.setCommandLineModuleNode(self.cliNode)
            self.cliNode.AddObserver("ModifiedEvent", self.extractCLICallback)
        else:
            self.handler = PoreNetworkExtractorHandler(self.inputNodeID, labelNodeID, params)
            success = slicer.modules.RemoteServiceInstance.cli.run(
                self.handler, name="PoreNetworkExtractor", job_type="pnmextractor"
            )
            if success:
                self.callback()

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

        status = caller.GetStatusString()
        if status in ["Completed", "Cancelled", "Completed with errors"]:
            logging.info(status)
            del self.cliNode
            self.cliNode = None
            if status == "Completed":
                self.onFinish()
                shutil.rmtree(self.cwd)

            self.callback(True)

    def _create_table(self, table_type):
        table = slicer.mrmlScene.CreateNodeByClass("vtkMRMLTableNode")
        table.AddNodeReferenceID("PoresLabelMap", self.inputNodeID)
        table.SetName(slicer.mrmlScene.GenerateUniqueName(f"{self.prefix}_{table_type}_table"))
        table.SetAttribute("table_type", f"{table_type}_table")
        table.SetAttribute("is_multiscale", "false")  # TODO check if needed, case positive, set it correctly
        slicer.mrmlScene.AddNode(table)
        return table

    def _create_tables(self, algorithm_name):
        poreOutputTable = self._create_table("pore")
        throatOutputTable = self._create_table("throat")
        networkOutputTable = self._create_table("network")
        poreOutputTable.SetAttribute("extraction_algorithm", algorithm_name)
        edge_throats = "none" if (algorithm_name == "porespy") else "x"
        poreOutputTable.SetAttribute("edge_throats", edge_throats)
        return throatOutputTable, poreOutputTable, networkOutputTable

    def onFinish(self):
        inputNode = slicer.mrmlScene.GetNodeByID(self.inputNodeID)

        df_pores = pd.read_pickle(str(self.cwd / "pores.pd"))
        df_throats = pd.read_pickle(str(self.cwd / "throats.pd"))
        df_network = pd.read_pickle(str(self.cwd / "network.pd"))

        throatOutputTable, poreOutputTable, networkOutputTable = self._create_tables("porespy")

        self.results["pore_table"] = poreOutputTable
        self.results["throat_table"] = throatOutputTable
        self.results["network_table"] = networkOutputTable

        dataFrameToTableNode(df_pores, poreOutputTable)
        dataFrameToTableNode(df_throats, throatOutputTable)
        dataFrameToTableNode(df_network, networkOutputTable)

        ### Include size infomation ###
        bounds = [0, 0, 0, 0, 0, 0]
        inputNode.GetBounds(bounds)  # In millimeters
        poreOutputTable.SetAttribute("x_size", str(bounds[1] - bounds[0]))
        poreOutputTable.SetAttribute("y_size", str(bounds[3] - bounds[2]))
        poreOutputTable.SetAttribute("z_size", str(bounds[5] - bounds[4]))
        poreOutputTable.SetAttribute("origin", f"{bounds[0]};{bounds[2]};{bounds[4]}")

        ### Move table nodes to hierarchy nodes ###
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemTreeId = folderTree.GetItemByDataNode(inputNode)
        parentItemId = folderTree.GetItemParent(itemTreeId)
        currentDir = folderTree.CreateFolderItem(parentItemId, f"{self.prefix}_Pore_Network")

        folderTree.CreateItem(currentDir, poreOutputTable)
        folderTree.CreateItem(currentDir, throatOutputTable)
        folderTree.CreateItem(currentDir, networkOutputTable)

        if self.visualization:
            self.results["model_nodes"] = self.visualize(poreOutputTable, throatOutputTable, inputNode)

    def visualize(
        self,
        poreOutputTable: slicer.vtkMRMLTableNode,
        throatOutputTable: slicer.vtkMRMLTableNode,
        inputVolume: slicer.vtkMRMLLabelMapVolumeNode,
    ):
        return pn.visualize(
            poreOutputTable,
            throatOutputTable,
            inputVolume,
        )


class PoreNetworkExtractorError(RuntimeError):
    pass
