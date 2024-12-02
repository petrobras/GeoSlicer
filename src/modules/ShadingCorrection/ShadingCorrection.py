import logging
import os
import math
from collections import namedtuple
from pathlib import Path

import ctk
import qt
import slicer

from ltrace.slicer import ui
from ltrace.slicer.helpers import (
    createTemporaryVolumeNode,
    getSourceVolume,
    makeTemporaryNodePermanent,
    copy_display,
    getVolumeNullValue,
    setVolumeNullValue,
    extractSegmentInfo,
    highlight_error,
)
from ltrace.slicer.widgets import InputState, PixelLabel, get_input_widget_color
from ltrace.slicer_utils import *


class ShadingCorrection(LTracePlugin):
    SETTING_KEY = "ShadingCorrection"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Shading correction - Gaussian"
        self.parent.categories = ["Tools", "MicroCT", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ShadingCorrection.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ShadingCorrectionWidget(LTracePluginWidget):
    # Settings constants
    ballRadius = "ballRadius"
    OUTPUT_SUFFIX = "_ShadingCorrection"

    ShadingParameters = namedtuple(
        "ShadingParameters", ["inputVolume", "inputMask", "inputShadingMask", ballRadius, "outputVolumeName"]
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def getBallRadius(self):
        return ShadingCorrection.get_setting(self.ballRadius, default="50")

    def setup(self):
        LTracePluginWidget.setup(self)

        self.progressBar = slicer.qSlicerCLIProgressBar()
        self.logic = ShadingCorrectionLogic(self, self.progressBar)

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        # Input section
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        formLayout.addRow(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.inputImageComboBox = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode"], onChange=self._on_input_node_changed
        )
        self.inputImageComboBox.setToolTip("Select the input image.")
        inputFormLayout.addRow("Input image:", self.inputImageComboBox)

        self.inputMaskComboBox = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLLabelMapVolumeNode", "vtkMRMLSegmentationNode"],
            onChange=self._on_mask_node_changed,
            showSegments=True,
        )
        self.inputMaskComboBox.setToolTip("Select the mask.")
        inputFormLayout.addRow("Input mask:", self.inputMaskComboBox)

        self.inputShadingMaskComboBox = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLLabelMapVolumeNode", "vtkMRMLSegmentationNode"],
            onChange=self._on_shading_mask_node_changed,
            showSegments=True,
        )
        self.inputShadingMaskComboBox.setToolTip("Select the segmentation.")
        inputFormLayout.addRow("Input shading mask:", self.inputShadingMaskComboBox)

        inputFormLayout.addRow(" ", None)

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.outputVolumeNameLineEdit = qt.QLineEdit()

        self.ballRadiusSpinBox = ui.numberParam(vrange=(1, 1000), value=float(self.getBallRadius()))
        self.ballRadiusSpinBox.toolTip = (
            "The standard deviation of the Gaussian filter used to estimate the background."
        )
        stdBoxLayout = qt.QHBoxLayout()
        stdBoxLayout.addWidget(self.ballRadiusSpinBox)
        pixel_label = PixelLabel(value_input=self.ballRadiusSpinBox, node_input=self.inputImageComboBox)
        stdBoxLayout.addWidget(pixel_label)
        pixel_label.setSizePolicy(qt.QSizePolicy.Maximum, qt.QSizePolicy.Fixed)
        parametersFormLayout.addRow("Gaussian filter STD (mm):", stdBoxLayout)

        parametersFormLayout.addRow(" ", None)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        outputFormLayout.addRow("Output image name:", self.outputVolumeNameLineEdit)

        outputFormLayout.addRow(" ", None)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setFixedHeight(40)
        self.applyButton.clicked.connect(self.onApplyButtonClicked)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.applyButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        formLayout.addRow(buttonsHBoxLayout)

        self.layout.addStretch()

        self.layout.addWidget(self.progressBar)

    def onApplyButtonClicked(self):
        self.applyButton.setEnabled(False)
        try:
            if self.inputImageComboBox.currentNode() is None:
                highlight_error(self.inputImageComboBox)
                logging.warning("Missing input image.")
                return

            inputNode = self.inputImageComboBox.currentNode()

            try:
                inputMaskNode = extractSegmentInfo(self.inputMaskComboBox.currentItem(), refNode=inputNode)
            except Exception as e:
                import traceback

                traceback.print_exc()
                logging.warning("Invalid input mask. Cause:" + repr(e))
                highlight_error(self.inputMaskComboBox)
                return

            try:
                inputShadingMaskNode = extractSegmentInfo(
                    self.inputShadingMaskComboBox.currentItem(), refNode=inputNode
                )
            except Exception as e:
                import traceback

                traceback.print_exc()
                logging.warning("Invalid input shading mask. Cause:" + repr(e))
                highlight_error(self.inputShadingMaskComboBox)
                return

            if not self.outputVolumeNameLineEdit.text:
                highlight_error(self.outputVolumeNameLineEdit)
                logging.warning("Output image name is required.")

            pixel_size = min([x for x in inputNode.GetSpacing()])
            std_px_value = math.ceil(float(self.ballRadiusSpinBox.value) / pixel_size)

            ShadingCorrection.set_setting(self.ballRadius, std_px_value)

            shadingParameters = self.ShadingParameters(
                inputNode,
                inputMaskNode,
                inputShadingMaskNode,
                std_px_value,
                self.outputVolumeNameLineEdit.text,
            )

            self.logic.apply(shadingParameters)

        finally:
            self.applyButton.setEnabled(True)

    def onCancelButtonClicked(self):
        self.logic.cancel()

    def _on_input_node_changed(self, item_id):
        input_node = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(item_id)

        self.inputMaskComboBox.setCurrentNode(None)
        self.inputShadingMaskComboBox.setCurrentNode(None)

        if input_node is None:
            self.outputVolumeNameLineEdit.setText("")
        else:
            self._set_input_state(self.inputImageComboBox, InputState.OK)
            segmentation_nodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
            for segmentation_node in segmentation_nodes:
                if getSourceVolume(segmentation_node) == input_node:
                    self.inputMaskComboBox.setCurrentNode(segmentation_node)
                    self.inputShadingMaskComboBox.setCurrentNode(segmentation_node)
                    break

            self.outputVolumeNameLineEdit.setText(input_node.GetName() + self.OUTPUT_SUFFIX)

    def _on_mask_node_changed(self, item_id):
        input_node = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(item_id)
        if input_node is not None:
            self._set_input_state(self.inputMaskComboBox, InputState.OK)

    def _on_shading_mask_node_changed(self, item_id):
        input_node = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(item_id)
        if input_node is not None:
            self._set_input_state(self.inputShadingMaskComboBox, InputState.OK)

    def _set_input_state(self, input_combobox, state):
        color = get_input_widget_color(state)
        if color:
            input_combobox.setStyleSheet("QComboBox { background-color: " + color + "; }")
        else:
            input_combobox.setStyleSheet("")


class ShadingCorrectionLogic(LTracePluginLogic):
    def __init__(self, widget, progressBar):
        LTracePluginLogic.__init__(self)
        self.widget = widget
        self.cliNode = None
        self.progressBar = progressBar

    def apply(self, pars):
        # Removing old cli node if it exists
        slicer.mrmlScene.RemoveNode(self.cliNode)

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        inputVolumeItemParent = subjectHierarchyNode.GetItemParent(
            subjectHierarchyNode.GetItemByDataNode(pars.inputVolume)
        )

        # Output volume
        self.outputVolume = createTemporaryVolumeNode(pars.inputVolume.__class__, name=pars.outputVolumeName)
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(self.outputVolume), inputVolumeItemParent
        )

        cliParams = {
            "inputVolume": pars.inputVolume.GetID(),
            "inputMask": pars.inputMask.GetID(),
            "inputShadingMask": pars.inputShadingMask.GetID(),
            "ballRadius": pars.ballRadius,
            "outputVolume": self.outputVolume.GetID(),
        }

        self.inputVolume = pars.inputVolume
        self.cliNode = slicer.cli.run(slicer.modules.shadingcorrectioncli, None, cliParams)
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.filteringCLICallback)

    def filteringCLICallback(self, caller, event):
        status = caller.GetStatusString()
        if "Completed" in status or status == "Cancelled":
            logging.info(status)
            self.cliNode.RemoveAllObservers()
            self.cliNode = None

            slicer.util.setSliceViewerLayers(background=self.outputVolume, fit=True)
            copy_display(self.inputVolume, self.outputVolume)

            if status == "Completed":
                makeTemporaryNodePermanent(self.outputVolume, show=True)
                input_null_value = getVolumeNullValue(self.inputVolume)
                output_null_value = input_null_value if input_null_value != None else 0
                setVolumeNullValue(self.outputVolume, output_null_value)
            elif status == "Cancelled":
                slicer.mrmlScene.RemoveNode(self.outputVolume)
            else:
                slicer.mrmlScene.RemoveNode(self.outputVolume)
                slicer.util.errorDisplay("Filtering failed.")
            self.widget.applyButton.setEnabled(True)

    def cancel(self):
        if self.cliNode is None:
            return  # nothing running, nothing to do
        self.cliNode.Cancel()


class FilteringException(RuntimeError):
    pass
