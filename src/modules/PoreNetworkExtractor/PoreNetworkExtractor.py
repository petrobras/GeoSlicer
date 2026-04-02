import json
import logging
import os
import shutil
from pathlib import Path
from typing import Tuple, Union

import ctk
import qt
import slicer
import slicer.util
import vtk

from ltrace.pore_networks.functions_extract import ExtractionNodesCreator
from ltrace.remote.handlers.PoreNetworkExtractorHandler import PoreNetworkExtractorHandler
from ltrace.slicer import ui
from ltrace.slicer.app import MANUAL_BASE_URL
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, slicer_is_in_developer_mode

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

    def onExtractButton(self):
        localMode = self.paramsWidget.localQRadioButton.isChecked()
        if localMode:
            self.extractButton.setEnabled(False)
            self.cancelButton.setEnabled(True)
            self.warningsLabel.setText("")
            self.warningsLabel.setVisible(False)

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
            localMode,
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
                for widget in self.paramsWidget.blurWidgets:
                    widget.visible = False
            else:
                self.poresSelectorLabel.visible = True
                self.poresSelector.visible = True
                self.poresSelectorHelp.visible = True
                self.poresSelector.setCurrentNode(None)
                self.extractButton.setEnabled(True)
                for widget in self.paramsWidget.blurWidgets:
                    widget.visible = True
        else:
            self.outputPrefix.setText("")

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

    def extract(
        self,
        inputVolumeNode: slicer.vtkMRMLScalarVolumeNode,
        inputLabelMap: slicer.vtkMRMLLabelMapVolumeNode,
        prefix: str,
        visualization: bool,
        method: str,
        watershed_blur: list,
        localMode: bool,
    ) -> Union[Tuple[slicer.vtkMRMLTableNode, slicer.vtkMRMLTableNode], bool]:
        self.params = {"prefix": prefix, "method": method}

        self.visualization = visualization
        self.localMode = localMode

        self.inputNodeID = inputVolumeNode.GetID()
        self.labelNodeID = None
        if inputLabelMap:
            self.labelNodeID = inputLabelMap.GetID()

        if inputVolumeNode.IsA("vtkMRMLLabelMapVolumeNode") and inputLabelMap is None:
            self.params["is_multiscale"] = False
        elif inputVolumeNode:
            self.params["is_multiscale"] = True
        else:
            logging.warning("Not a valid input.")
            return

        self.params["watershed_blur"] = watershed_blur

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

        self.cwd = Path(slicer.util.tempDirectory())
        self.prefix = prefix

        if localMode:
            cliParams = {"cwd": str(self.cwd)}
            cliParams["volume"] = self.inputNodeID
            if self.labelNodeID:
                cliParams["label"] = self.labelNodeID
            with open(str(self.cwd / "extractor_params_dict.json"), "w") as file:
                json.dump(self.params, file)
            self.cliNode = slicer.cli.run(slicer.modules.porenetworkextractorcli, None, cliParams)
            self.progressBar.setCommandLineModuleNode(self.cliNode)
            self.cliNode.AddObserver("ModifiedEvent", self.extractCLICallback)
        else:
            job_name = f"PNM Extract: {self.prefix}"
            self.handler = PoreNetworkExtractorHandler(
                self.inputNodeID, self.labelNodeID, self.visualization, self.params
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

        extraction_nodes_creator = ExtractionNodesCreator(metadata, self.cwd, self.prefix, self.visualization)
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


class PoreNetworkExtractorError(RuntimeError):
    pass
