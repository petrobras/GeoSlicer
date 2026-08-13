import datetime
import logging
import os
import traceback
from collections import namedtuple
from enum import Enum
from pathlib import Path

import ctk
import numpy as np
import qt
import slicer
import vtk
from scipy.interpolate import interp1d
from scipy.ndimage import gaussian_filter1d

from ltrace.algorithms.shading_correction import compute_polynomial_shading_correction, normalize_z
from ltrace.flow.util import createSimplifiedSegmentEditor, onSegmentEditorEnter, onSegmentEditorExit
from ltrace.slicer import helpers
from ltrace.slicer.app import MANUAL_BASE_URL
from ltrace.slicer.helpers import (
    highlight_error,
    reset_style_on_valid_text,
    copy_display,
    getVolumeNullValue,
    setVolumeNullValue,
    remove_highlight,
    copy_subject_hierarchy_item_parent,
)
from ltrace.slicer.lazy import lazy
from ltrace.slicer.metadata import copy_metadata
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer.widget.status_panel import StatusPanel
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic

try:
    from Test.PolynomialShadingCorrectionTest import PolynomialShadingCorrectionTest
except ImportError:
    PolynomialShadingCorrectionTest = None  # tests not deployed to final version or closed source


class PolynomialShadingCorrection(LTracePlugin):
    SETTING_KEY = "PolynomialShadingCorrection"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Shading correction - Polynomial"
        self.parent.categories = ["Tools", "MicroCT", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.setHelpUrl("Volumes/Filter/Filter.html#polynomial-shading-correction", NodeEnvironment.MICRO_CT)
        self.setHelpUrl(
            "Multiscale/VolumesPreProcessing/VolumesPreProcessing.html#shading-correction", NodeEnvironment.MULTISCALE
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PolynomialShadingCorrectionWidget(LTracePluginWidget):
    # Settings constants
    SLICE_GROUP_SIZE = "sliceGroupSize"
    FUNCTION_TYPE = "functionType"
    POLYNOMIAL_ORDER = "polynomialOrder"
    FITTING_POINTS_PERCENTAGE = "fittingPointsPercentage"
    OUTPUT_SUFFIX = "_ShadingCorrection"

    ProcessParameters = namedtuple(
        "ProcessParameters",
        [
            "inputImage",
            "shadingMask",
            SLICE_GROUP_SIZE,
            "fittingPointsPercentage",
            FUNCTION_TYPE,
            POLYNOMIAL_ORDER,
            "useCustomCenter",
            "centerX",
            "centerY",
            "outputImageName",
        ],
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.normalizedVolume = None
        self.samplingMaskSegmentation = None
        self.labelMapNode = None
        self.centerFiducialNode = None
        self.pointAddedObserverTag = None

    def getSliceGroupSize(self):
        return PolynomialShadingCorrection.get_setting(self.SLICE_GROUP_SIZE, default="1")

    def __updateApplyToAll(self):
        inputNode = self.inputImageComboBox.currentNode()
        virtualInputNode = lazy.getParentLazyNode(inputNode) if inputNode is not None else None
        hasVirtualNode = virtualInputNode is not None
        self.applyFullButton.visible = hasVirtualNode

    class WidgetState(Enum):
        INITIAL = "initial"
        THRESHOLD = "threshold"
        PROCESS = "process"

    def updateWidgetsVisibility(self, state):
        if state == self.WidgetState.INITIAL:
            self.inputCollapsibleButton.collapsed = False
            self.parametersCollapsibleButton.visible = False
            self.outputCollapsibleButton.visible = False
            self.thresholdCollapsibleButton.visible = False
            self.statusPanel.set_instruction("Choose the input image to correct.")
        elif state == self.WidgetState.THRESHOLD:
            self.inputCollapsibleButton.collapsed = True
            self.parametersCollapsibleButton.visible = False
            self.outputCollapsibleButton.visible = False
            self.thresholdCollapsibleButton.visible = True
            self.samplingMaskSegmentation.GetDisplayNode().SetVisibility(True)
            slicer.util.setSliceViewerLayers(background=self.normalizedVolume, fit=True)
            self.statusPanel.set_instruction("Adjust the threshold to create a sampling mask.")
        elif state == self.WidgetState.PROCESS:
            self.inputCollapsibleButton.collapsed = True
            self.parametersCollapsibleButton.visible = True
            self.outputCollapsibleButton.visible = True
            self.thresholdCollapsibleButton.visible = False
            self.samplingMaskSegmentation.GetDisplayNode().SetVisibility(False)
            self.apply.setEnabled(True)
            self.statusPanel.set_instruction("Choose the parameters and run.")

    def setup(self):
        LTracePluginWidget.setup(self)

        # Ensure CustomizedSegmentEditor is initialized
        slicer.util.getModuleWidget("CustomizedSegmentEditor")

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        self.statusPanel = StatusPanel("")
        self.statusPanel.statusLabel.setWordWrap(True)
        formLayout.addRow(self.statusPanel)

        manualPath = f"{MANUAL_BASE_URL}Volumes/Filter/Filter.html#polynomial-shading-correction"

        # --- Input section ---
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        formLayout.addRow(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.inputCollapsibleButton = inputCollapsibleButton

        self.inputImageComboBox = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode"], onChange=self.onInputImageChanged
        )
        self.inputImageComboBox.setObjectName("inputImageComboBox")
        self.inputImageComboBox.setToolTip("Select the input image.")
        self.inputImageComboBox.resetStyleOnValidNode()

        inputImageHelp = HelpButton(
            "Select the scalar volume (image) that you want to apply the shading correction to."
            "\n\n-----\n[More]({path_to_manual})",
            replacer=lambda x: x.format(path_to_manual=manualPath),
        )

        inputImageHBox = qt.QHBoxLayout()
        inputImageHBox.setContentsMargins(0, 0, 0, 0)
        inputImageHBox.addWidget(self.inputImageComboBox)
        inputImageHBox.addWidget(inputImageHelp)
        inputFormLayout.addRow("Input image:", inputImageHBox)

        self.keepNormalizedBox = qt.QCheckBox("Keep intermediate image")
        self.keepNormalizedBox.setToolTip(
            "The image slices are pre-normalized to make the thresholding step easier. "
            "If this option is checked, the normalized image will be kept in the project."
        )

        keepNormalizedHelp = HelpButton(
            "During the 'Initialize' step, the image slices are pre-normalized along the Z-axis. This makes the thresholding step easier by reducing brightness variations between slices.\n\n"
            "Check this box if you want to keep this normalized image in your project scene after the process finishes. Otherwise, it is used temporarily and discarded."
            "\n\n-----\n[More]({path_to_manual})",
            replacer=lambda x: x.format(path_to_manual=manualPath),
        )

        keepNormalizedHBox = qt.QHBoxLayout()
        keepNormalizedHBox.setContentsMargins(0, 0, 0, 0)
        keepNormalizedHBox.addWidget(self.keepNormalizedBox)
        keepNormalizedHBox.addWidget(keepNormalizedHelp)
        keepNormalizedHBox.addStretch(1)
        inputFormLayout.addRow("", keepNormalizedHBox)

        self.initializeButton = qt.QPushButton("Initialize")
        self.initializeButton.setObjectName("initializeButton")
        self.initializeButton.setToolTip("Normalize the input volume and prepare for thresholding.")
        self.initializeButton.clicked.connect(self.onInitializeButtonClicked)
        inputFormLayout.addRow("", self.initializeButton)

        # --- Segment Editor (Threshold section) ---
        widget, _, self.sourceVolumeBox, self.segmentationBox = createSimplifiedSegmentEditor()
        widget.setObjectName("thresholdEditor")
        effects = ["Threshold"]
        widget.setEffectNameOrder(effects)
        widget.unorderedEffectsVisible = False
        tableView = widget.findChild(qt.QTableView, "SegmentsTable")
        tableView.setFixedHeight(100)

        self.thresholdCollapsibleButton = ctk.ctkCollapsibleButton()
        self.thresholdCollapsibleButton.setText("Threshold")
        formLayout.addRow(self.thresholdCollapsibleButton)
        thresholdLayout = qt.QVBoxLayout(self.thresholdCollapsibleButton)

        thresholdHelp = HelpButton(
            "Adjust the threshold bounds to isolate a **homogenous phase** of the image (e.g., only the pore space or only the matrix).\n\n"
            "This creates a sampling mask. The shading algorithm strictly uses the voxel values within this mask to calculate the mathematical curve. "
            "Isolating a single material ensures the model fits the *illumination artifact* and not the physical material differences."
            "\n\n-----\n[More]({path_to_manual})",
            replacer=lambda x: x.format(path_to_manual=manualPath),
        )

        thresholdHeaderLayout = qt.QHBoxLayout()
        thresholdHeaderLayout.setContentsMargins(0, 0, 0, 4)
        thresholdLabel = qt.QLabel("Define sampling mask:")
        thresholdHeaderLayout.addWidget(thresholdLabel)
        thresholdHeaderLayout.addWidget(thresholdHelp)
        thresholdHeaderLayout.addStretch(1)

        thresholdLayout.addLayout(thresholdHeaderLayout)
        thresholdLayout.addWidget(widget)
        self.segmentEditorWidget = widget

        # --- Parameters section ---
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        self.parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        self.parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.parametersCollapsibleButton = parametersCollapsibleButton

        self.functionTypeComboBox = qt.QComboBox()
        self.functionTypeComboBox.setObjectName("functionTypeComboBox")
        self.functionTypeComboBox.addItems(["Polynomial", "Polynomial Radial", "Spline Radial"])
        self.functionTypeComboBox.setCurrentText(
            PolynomialShadingCorrection.get_setting(self.FUNCTION_TYPE, default="Polynomial Radial")
        )
        self.functionTypeComboBox.setToolTip("Select the mathematical model for the shading correction.")
        self.functionTypeComboBox.currentTextChanged.connect(self.onFunctionTypeChanged)

        functionTypeHelp = HelpButton(
            "Select the mathematical model for the shading correction:\n\n"
            "- **Polynomial**: Fits a 2D Cartesian surface. Best for general, non-symmetric shading gradients across the image.\n"
            "- **Polynomial Radial**: Fits a curve based strictly on the distance from the center. Best for broad, circular shading effects like standard beam hardening.\n"
            "- **Spline Radial**: Calculates a median radial profile and uses splines to handle fine, high-frequency ring artifacts."
            "\n\n-----\n[More]({path_to_manual})",
            replacer=lambda x: x.format(path_to_manual=manualPath),
        )

        functionTypeHBox = qt.QHBoxLayout()
        functionTypeHBox.setContentsMargins(0, 0, 0, 0)
        functionTypeHBox.addWidget(self.functionTypeComboBox)
        functionTypeHBox.addWidget(functionTypeHelp)
        self.parametersFormLayout.addRow("Function:", functionTypeHBox)

        # Center Definition
        centerLayout = qt.QHBoxLayout()
        self.useCustomCenterCheckBox = qt.QCheckBox("Set")
        self.useCustomCenterCheckBox.setObjectName("useCustomCenterCheckBox")
        self.useCustomCenterCheckBox.setToolTip("Define a custom center for the mathematical curve fitting.")
        self.useCustomCenterCheckBox.toggled.connect(self.onUseCustomCenterToggled)

        self.centerXSpinBox = qt.QSpinBox()
        self.centerXSpinBox.setObjectName("centerXSpinBox")
        self.centerXSpinBox.setRange(0, 100000)
        self.centerXSpinBox.setEnabled(False)

        self.centerYSpinBox = qt.QSpinBox()
        self.centerYSpinBox.setObjectName("centerYSpinBox")
        self.centerYSpinBox.setRange(0, 100000)
        self.centerYSpinBox.setEnabled(False)

        self.pickCenterButton = qt.QPushButton("Pick Red View")
        self.pickCenterButton.setObjectName("pickCenterButton")
        self.pickCenterButton.setEnabled(False)
        self.pickCenterButton.clicked.connect(self.onPickCenterClicked)

        centerHelp = HelpButton(
            "Define the center point for the radial mathematical curve fitting:\n\n"
            "- **Default**: Automatically uses the geometric center of the image.\n"
            "- **Custom**: Check to manually input the X and Y center coordinates.\n"
            "- **Pick on Z**: Click to interactively select the center point directly on the Red slice view."
            "\n\n-----\n[More]({path_to_manual})",
            replacer=lambda x: x.format(path_to_manual=manualPath),
        )

        centerLayout.addWidget(self.useCustomCenterCheckBox)
        centerLayout.addStretch(1)
        centerLayout.addWidget(qt.QLabel("X"))
        centerLayout.addWidget(self.centerXSpinBox)
        centerLayout.addWidget(qt.QLabel("Y"))
        centerLayout.addWidget(self.centerYSpinBox)
        centerLayout.addStretch(1)
        centerLayout.addWidget(self.pickCenterButton)
        centerLayout.addWidget(centerHelp)
        self.parametersFormLayout.addRow("Center:", centerLayout)

        self.polynomialOrderComboBox = qt.QComboBox()
        self.polynomialOrderComboBox.setObjectName("polynomialOrderComboBox")
        self.polynomialOrderComboBox.addItems(["2", "4", "6"])
        self.polynomialOrderComboBox.setCurrentText(
            PolynomialShadingCorrection.get_setting(self.POLYNOMIAL_ORDER, default="6")
        )
        self.polynomialOrderComboBox.setToolTip(
            "Select the degree of the polynomial. Not used if Spline Radial is selected."
        )

        polynomialOrderHelp = HelpButton(
            "Select the complexity of the polynomial curve (2, 4, or 6):\n\n"
            "- **Lower orders (2)**: Capture broad, gentle shading gradients. Less prone to errors.\n"
            "- **Higher orders (6)**: Allow for more complex, wavy curves but increase the risk of overfitting to local image features instead of the overall shading trend.\n\n"
            "*Note: This parameter is ignored if 'Spline Radial' is selected.*"
            "\n\n-----\n[More]({path_to_manual})",
            replacer=lambda x: x.format(path_to_manual=manualPath),
        )

        self.polynomialOrderWidget = qt.QWidget()
        polynomialOrderHBox = qt.QHBoxLayout(self.polynomialOrderWidget)
        polynomialOrderHBox.setContentsMargins(0, 0, 0, 0)
        polynomialOrderHBox.addWidget(self.polynomialOrderComboBox)
        polynomialOrderHBox.addWidget(polynomialOrderHelp)
        self.parametersFormLayout.addRow("Order:", self.polynomialOrderWidget)

        self.sliceGroupSize = qt.QSpinBox()
        self.sliceGroupSize.setObjectName("sliceGroupSize")
        self.sliceGroupSize.setRange(1, 9)
        self.sliceGroupSize.setSingleStep(2)
        self.sliceGroupSize.setValue(int(self.getSliceGroupSize()))
        tooltip_text = (
            "This parameter will cause the polynomial function to be fitted for the central slice in the group of slices. "
            "All the other slices of the group will use the same fitted function. "
            "Smaller values yield better results but increase processing time."
        )

        self.sliceGroupSize.setToolTip(tooltip_text)
        self.sliceGroupSize.valueChanged.connect(lambda: self.sliceGroupSize.setStyleSheet(""))

        sliceGroupHelp = HelpButton(
            "This parameter will cause the polynomial function to be fitted for the central slice in the group of slices. "
            "All the other slices of the group will use the same fitted function.\n\n"
            "**Note:** Smaller values yield better results, but processing is slower."
            "\n\n-----\n[More]({path_to_manual})",
            replacer=lambda x: x.format(path_to_manual=manualPath),
        )

        sliceGroupHBox = qt.QHBoxLayout()
        sliceGroupHBox.setContentsMargins(0, 0, 0, 0)
        sliceGroupHBox.addWidget(self.sliceGroupSize)
        sliceGroupHBox.addWidget(sliceGroupHelp)
        self.parametersFormLayout.addRow("Group size:", sliceGroupHBox)

        self.fittingPointsPercentage = ctk.ctkSliderWidget()
        self.fittingPointsPercentage.decimals = 0
        self.fittingPointsPercentage.minimum = 1
        self.fittingPointsPercentage.maximum = 100
        self.fittingPointsPercentage.value = 60
        spin_box = self.fittingPointsPercentage.findChild(qt.QDoubleSpinBox)
        if spin_box:
            spin_box.setMinimumWidth(150)
        self.fittingPointsPercentage.setObjectName("fittingPointsPercentage")
        self.fittingPointsPercentage.setToolTip(
            "Percentage of points used in the function fitting process. "
            "Larger values yield better results but increase processing time."
        )

        fittingPointsHelp = HelpButton(
            "Percentage of points used in the function fitting process.\n\n"
            "**Note:** Larger values yield better results, but processing is slower."
            "\n\n-----\n[More]({path_to_manual})",
            replacer=lambda x: x.format(path_to_manual=manualPath),
        )

        fittingPointsHBox = qt.QHBoxLayout()
        fittingPointsHBox.setContentsMargins(0, 0, 0, 0)
        fittingPointsHBox.addWidget(self.fittingPointsPercentage)
        fittingPointsHBox.addWidget(fittingPointsHelp)
        self.parametersFormLayout.addRow("Fitting points (%):", fittingPointsHBox)

        self.parametersFormLayout.addRow(" ", None)

        # --- Output section ---
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.outputCollapsibleButton = outputCollapsibleButton

        self.outputImageNameLineEdit = qt.QLineEdit()
        self.outputImageNameLineEdit.setObjectName("outputImageNameLineEdit")
        reset_style_on_valid_text(self.outputImageNameLineEdit)

        outputNameHelp = HelpButton(
            "The desired name for the corrected output image volume." "\n\n-----\n[More]({path_to_manual})",
            replacer=lambda x: x.format(path_to_manual=manualPath),
        )

        outputNameHBox = qt.QHBoxLayout()
        outputNameHBox.setContentsMargins(0, 0, 0, 0)
        outputNameHBox.addWidget(self.outputImageNameLineEdit)
        outputNameHBox.addWidget(outputNameHelp)
        outputFormLayout.addRow("Output image name:", outputNameHBox)
        outputFormLayout.addRow(" ", None)

        self.apply = qt.QPushButton("Apply")
        self.apply.setObjectName("applyButton")
        self.apply.setFixedHeight(40)
        self.apply.clicked.connect(self.onRegisterButtonClicked)
        self.apply.setEnabled(False)

        self.applyFullButton = qt.QPushButton("Apply to full volume")
        self.applyFullButton.setFixedHeight(40)
        self.applyFullButton.toolTip = "Run the algorithm on the full volume."
        self.applyFullButton.clicked.connect(self.onApplyFull)
        self.applyFullButton.visible = False
        self.applyFullButton.setObjectName("applyAllButton")

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setObjectName("cancelButton")
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.setEnabled(False)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.apply)
        buttonsHBoxLayout.addWidget(self.applyFullButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        outputFormLayout.addRow(buttonsHBoxLayout)

        self.statusLabel = qt.QLabel()
        self.statusLabel.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        self.statusLabel.hide()
        formLayout.addRow(self.statusLabel)

        self.progressBar = qt.QProgressBar()
        self.progressBar.setValue(0)
        self.progressBar.hide()
        formLayout.addRow(self.progressBar)

        self.logic = PolynomialShadingCorrectionLogic(self.statusLabel, self.progressBar)

        self.layout.addStretch(1)

        self.onFunctionTypeChanged(self.functionTypeComboBox.currentText)
        self.reset()

    def onFunctionTypeChanged(self, text):
        is_spline = text == "Spline Radial"

        if hasattr(self, "polynomialOrderWidget") and hasattr(self, "parametersFormLayout"):
            self.polynomialOrderWidget.setVisible(not is_spline)

            label = self.parametersFormLayout.labelForField(self.polynomialOrderWidget)
            if label:
                label.setVisible(not is_spline)

    def onUseCustomCenterToggled(self, isChecked):
        self.centerXSpinBox.setEnabled(isChecked)
        self.centerYSpinBox.setEnabled(isChecked)
        self.pickCenterButton.setEnabled(isChecked)

    def onPickCenterClicked(self):
        if not self.centerFiducialNode:
            self.centerFiducialNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "ShadingCenter")
            displayNode = self.centerFiducialNode.GetDisplayNode()
            displayNode.SetSelectedColor(1, 0, 0)
            displayNode.RemoveAllViewNodeIDs()
            displayNode.AddViewNodeID("vtkMRMLSliceNodeRed")
            self.centerFiducialNode.SetHideFromEditors(True)

        self.centerFiducialNode.RemoveAllControlPoints()

        interactionNode = slicer.mrmlScene.GetNodeByID("vtkMRMLInteractionNodeSingleton")
        selectionNode = slicer.mrmlScene.GetNodeByID("vtkMRMLSelectionNodeSingleton")

        selectionNode.SetReferenceActivePlaceNodeClassName("vtkMRMLMarkupsFiducialNode")
        selectionNode.SetActivePlaceNodeID(self.centerFiducialNode.GetID())
        interactionNode.SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.Place)

        if self.pointAddedObserverTag is None:
            self.pointAddedObserverTag = self.centerFiducialNode.AddObserver(
                slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent, self.onCenterPointAdded
            )

    def onCenterPointAdded(self, caller, event):
        interactionNode = slicer.mrmlScene.GetNodeByID("vtkMRMLInteractionNodeSingleton")
        interactionNode.SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.ViewTransform)

        pos = [0.0, 0.0, 0.0]
        self.centerFiducialNode.GetNthControlPointPositionWorld(0, pos)

        volumeNode = self.inputImageComboBox.currentNode()
        if not volumeNode:
            return

        transform = vtk.vtkGeneralTransform()
        slicer.vtkMRMLTransformNode.GetTransformBetweenNodes(None, volumeNode.GetParentTransformNode(), transform)
        pos_volume = transform.TransformPoint(pos)

        ijkMatrix = vtk.vtkMatrix4x4()
        volumeNode.GetRASToIJKMatrix(ijkMatrix)

        ijk = [0, 0, 0, 1]
        ijkMatrix.MultiplyPoint(np.append(pos_volume, 1.0), ijk)

        i, j = int(round(ijk[0])), int(round(ijk[1]))

        self.centerXSpinBox.setValue(i)
        self.centerYSpinBox.setValue(j)

        self.centerFiducialNode.RemoveAllControlPoints()

    def onInputImageChanged(self, itemId):
        self.reset()

        inputImage = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(itemId)
        if inputImage:
            outputImageName = inputImage.GetName() + self.OUTPUT_SUFFIX

            imageData = inputImage.GetImageData()
            if imageData:
                dims = imageData.GetDimensions()

                if hasattr(self, "centerXSpinBox") and hasattr(self, "centerYSpinBox"):
                    self.centerXSpinBox.setValue(dims[0] // 2)
                    self.centerYSpinBox.setValue(dims[1] // 2)
        else:
            outputImageName = ""

        if hasattr(self, "outputImageNameLineEdit"):
            self.outputImageNameLineEdit.setText(outputImageName)

        self.__updateApplyToAll()

    def reset(self):
        if self.samplingMaskSegmentation:
            slicer.mrmlScene.RemoveNode(self.samplingMaskSegmentation)
            self.samplingMaskSegmentation = None
        if self.labelMapNode:
            slicer.mrmlScene.RemoveNode(self.labelMapNode)
            self.labelMapNode = None
        if self.normalizedVolume and hasattr(self, "keepNormalized") and not self.keepNormalized:
            slicer.mrmlScene.RemoveNode(self.normalizedVolume)
            self.normalizedVolume = None
        if self.centerFiducialNode:
            slicer.mrmlScene.RemoveNode(self.centerFiducialNode)
            self.centerFiducialNode = None
            self.pointAddedObserverTag = None
        self.inputNode = None

        if hasattr(self, "useCustomCenterCheckBox"):
            self.useCustomCenterCheckBox.setChecked(False)

        onSegmentEditorExit(self.segmentEditorWidget)
        self.updateWidgetsVisibility(self.WidgetState.INITIAL)

    def exit(self):
        self.reset()

    def onInitializeButtonClicked(self):
        inputNode = self.inputImageComboBox.currentNode()
        if not inputNode:
            highlight_error(self.inputImageComboBox)
            return

        onSegmentEditorEnter(self.segmentEditorWidget, "ShadingMask")

        self.statusLabel.setText("Status: Normalizing volume...")
        self.statusLabel.show()
        self.progressBar.setValue(0)
        self.progressBar.show()
        slicer.app.processEvents()

        try:
            inputArray = slicer.util.arrayFromVolume(inputNode)

            self.progressBar.setValue(30)
            slicer.app.processEvents()

            nullValue = getVolumeNullValue(inputNode)
            normalizedArray = normalize_z(inputArray, null_value=nullValue)

            self.progressBar.setValue(60)
            slicer.app.processEvents()

            self.reset()

            self.inputNode = inputNode
            self.keepNormalized = self.keepNormalizedBox.isChecked()

            volumeName = inputNode.GetName() + "_PreNormalized"
            self.normalizedVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", volumeName)
            self.normalizedVolume.CopyOrientation(inputNode)
            copy_display(inputNode, self.normalizedVolume)
            slicer.util.updateVolumeFromArray(self.normalizedVolume, normalizedArray)
            if not self.keepNormalizedBox.isChecked():
                self.normalizedVolume.SetHideFromEditors(True)
                self.normalizedVolume.SaveWithSceneOff()

            self.progressBar.setValue(80)
            slicer.app.processEvents()

            self.samplingMaskSegmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
            self.samplingMaskSegmentation.SetName(inputNode.GetName() + "_sampling_mask")
            self.samplingMaskSegmentation.CreateDefaultDisplayNodes()
            self.samplingMaskSegmentation.SetReferenceImageGeometryParameterFromVolumeNode(self.normalizedVolume)
            self.samplingMaskSegmentation.GetSegmentation().AddEmptySegment("Sampling Mask", "Sampling Mask")
            self.samplingMaskSegmentation.SetHideFromEditors(True)
            self.samplingMaskSegmentation.SaveWithSceneOff()

            self.segmentationBox.setCurrentNode(self.samplingMaskSegmentation)
            self.sourceVolumeBox.setCurrentNode(self.normalizedVolume)
            self.segmentEditorWidget.setActiveEffectByName("Threshold")

            maskingWidget = self.segmentEditorWidget.findChild(qt.QGroupBox, "MaskingGroupBox")
            maskingWidget.visible = False
            maskingWidget.setFixedHeight(0)

            self.updateWidgetsVisibility(self.WidgetState.THRESHOLD)

            effect = self.segmentEditorWidget.effectByName("Threshold")

            vMin, vMax = np.percentile(normalizedArray, [10, 99])

            effect.self().thresholdSlider.minimum = vMin
            effect.self().thresholdSlider.maximum = vMax

            pMin, pMax = np.percentile(normalizedArray, [60, 90])
            effect.setParameter("MinimumThreshold", str(pMin))
            effect.setParameter("MaximumThreshold", str(pMax))

            applyThresholdButton = effect.self().applyButton
            applyThresholdButton.clicked.connect(self.onThresholdApplied)

            if hasattr(effect.self(), "enablePulsingCheckbox"):
                pulseBox = effect.self().enablePulsingCheckbox
                pulseBox.setChecked(False)
                pulseBox.hide()

            frame = effect.optionsFrame()
            for groupBox in frame.findChildren(ctk.ctkCollapsibleGroupBox):
                groupBox.hide()

            if hasattr(self, "centerXSpinBox") and hasattr(self, "centerYSpinBox"):
                imageData = inputNode.GetImageData()
                if imageData:
                    dims = imageData.GetDimensions()
                    self.centerXSpinBox.setValue(dims[0] // 2)
                    self.centerYSpinBox.setValue(dims[1] // 2)

            self.statusLabel.setText("Status: Ready")
            self.progressBar.setValue(0)

        except Exception as e:
            traceback.print_exc()
            self.statusLabel.setText("Status: Error during initialization")
            slicer.util.errorDisplay(f"Failed to initialize: {str(e)}")
        finally:
            slicer.app.processEvents()

    def onThresholdApplied(self):
        if not self.labelMapNode:
            self.labelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
            self.labelMapNode.SetName(self.inputNode.GetName() + "_shading_labelmap")
            self.labelMapNode.SetHideFromEditors(True)

        slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
            self.samplingMaskSegmentation, self.labelMapNode, self.inputNode
        )

        self.updateWidgetsVisibility(self.WidgetState.PROCESS)

    def onApplyFull(self):
        slicer.util.selectModule("PolynomialShadingCorrectionBigImage")
        widget = slicer.modules.PolynomialShadingCorrectionBigImageWidget

        if not self.samplingMaskSegmentation:
            slicer.util.errorDisplay("Please initialize and create a threshold segment first.")
            return

        params = {
            "inputNode": self.inputNode,
            "inputShadingMaskNode": self.samplingMaskSegmentation,
            "sliceGroupSize": self.sliceGroupSize.value,
            "fittingPointsPercentage": int(self.fittingPointsPercentage.value),
            "functionType": self.functionTypeComboBox.currentText,
            "polynomialOrder": int(self.polynomialOrderComboBox.currentText),
        }

        widget.setParameters(**params)

    def resetInputWidgetsStyle(self):
        remove_highlight(self.inputImageComboBox)
        remove_highlight(self.sliceGroupSize)
        remove_highlight(self.fittingPointsPercentage)
        remove_highlight(self.outputImageNameLineEdit)

    def onRegisterButtonClicked(self):
        self.unrequireField(self.sliceGroupSize)

        try:
            if self.inputImageComboBox.currentNode() is None:
                highlight_error(self.inputImageComboBox)
                return

            if not self.samplingMaskSegmentation or not self.labelMapNode:
                slicer.util.errorDisplay("Please initialize and create a threshold segment first.")
                return

            if self.sliceGroupSize.value % 2 == 0:
                highlight_error(self.sliceGroupSize)
                return

            if self.outputImageNameLineEdit.text.strip() == "":
                highlight_error(self.outputImageNameLineEdit)
                return

            inputNode = self.inputImageComboBox.currentNode()

            functionType = self.functionTypeComboBox.currentText
            polynomialOrder = int(self.polynomialOrderComboBox.currentText)

            PolynomialShadingCorrection.set_setting(self.SLICE_GROUP_SIZE, self.sliceGroupSize.value)
            PolynomialShadingCorrection.set_setting(self.FUNCTION_TYPE, functionType)
            PolynomialShadingCorrection.set_setting(self.POLYNOMIAL_ORDER, str(polynomialOrder))
            PolynomialShadingCorrection.set_setting(self.FITTING_POINTS_PERCENTAGE, self.fittingPointsPercentage.value)

            self.resetInputWidgetsStyle()
            self.apply.setEnabled(False)
            self.applyFullButton.setEnabled(False)
            self.cancelButton.setEnabled(True)
            self.statusLabel.setText("Status: Running")
            self.statusLabel.show()
            self.progressBar.setValue(0)
            self.progressBar.show()
            slicer.app.processEvents()

            processParameters = self.ProcessParameters(
                inputNode,
                self.labelMapNode,
                self.sliceGroupSize.value,
                int(self.fittingPointsPercentage.value),
                functionType,
                polynomialOrder,
                self.useCustomCenterCheckBox.isChecked(),
                self.centerXSpinBox.value,
                self.centerYSpinBox.value,
                self.outputImageNameLineEdit.text,
            )

            if self.logic.process(processParameters):
                self.statusLabel.setText("Status: Completed")
                self.progressBar.setValue(100)

            self.reset()

        except ProcessInfo as e:
            self.statusLabel.setText("Status: Not completed")
            slicer.util.infoDisplay(str(e))
        except RuntimeError as e:
            self.statusLabel.setText("Status: Not completed")
            slicer.util.infoDisplay("An unexpected error has occurred: " + str(e))
        finally:
            self.apply.setEnabled(True)
            self.applyFullButton.setEnabled(True)
            self.cancelButton.setEnabled(False)

    def onCancelButtonClicked(self):
        self.statusLabel.setText("Status: Canceled")
        self.progressBar.hide()
        self.logic.cancel()
        helpers.removeTemporaryNodes()
        self.apply.setEnabled(True)
        self.applyFullButton.setEnabled(True)
        self.cancelButton.setEnabled(False)

    def requireField(self, widget):
        widget.setStyleSheet("QWidget {background-color: #600000}")

    def unrequireField(self, widget):
        widget.setStyleSheet("")


class PolynomialShadingCorrectionLogic(LTracePluginLogic):
    def __init__(self, statusLabel, progressBar):
        LTracePluginLogic.__init__(self)
        self.statusLabel = statusLabel
        self.progressBar = progressBar
        self.cancelProcess = False

    def cancel(self):
        self.cancelProcess = True

    def process(self, parameters: PolynomialShadingCorrectionWidget.ProcessParameters) -> bool:
        self.cancelProcess = False

        self.inputImage = parameters.inputImage
        inputImageArray = slicer.util.arrayFromVolume(self.inputImage)

        shadingMask = parameters.shadingMask
        shadingMaskArray = slicer.util.arrayFromVolume(shadingMask)

        nullValue = getVolumeNullValue(self.inputImage)

        try:
            outputImageArray = self.polynomialShadingCorrection(
                inputImageArray=inputImageArray,
                inputShadingMaskArray=shadingMaskArray,
                sliceGroupSize=parameters.sliceGroupSize,
                fittingPointsPercentage=parameters.fittingPointsPercentage,
                functionType=parameters.functionType,
                polynomialOrder=parameters.polynomialOrder,
                useCustomCenter=parameters.useCustomCenter,
                centerX=parameters.centerX,
                centerY=parameters.centerY,
                input_null_value=nullValue,
            )

            if self.cancelProcess:
                return False

            outputImage = slicer.modules.volumes.logic().CloneVolume(self.inputImage, parameters.outputImageName)
            slicer.util.updateVolumeFromArray(outputImage, outputImageArray)
            copy_metadata(self.inputImage, outputImage)
            setVolumeNullValue(outputImage, nullValue)
            copy_subject_hierarchy_item_parent(self.inputImage, outputImage)

            slicer.util.setSliceViewerLayers(background=outputImage, foreground=None, label=None, fit=True)
        except Exception as e:
            traceback.print_exc()
            slicer.util.infoDisplay("An unexpected error has occurred during the shading correction process: " + str(e))
        finally:
            helpers.removeTemporaryNodes()

        return True

    def polynomialShadingCorrection(
        self,
        inputImageArray,
        inputShadingMaskArray,
        sliceGroupSize=1,
        fittingPointsPercentage=60,
        functionType="Polynomial Radial",
        polynomialOrder=4,
        useCustomCenter=False,
        centerX=0,
        centerY=0,
        input_null_value=None,
    ):
        start = datetime.datetime.now()

        def on_progress(current_slice, total_slices):
            elapsed = datetime.datetime.now() - start
            self.statusLabel.setText(f"Status: Running ({np.round(elapsed.total_seconds(), 1)})")
            self.progressBar.setValue(round(100 * (current_slice / total_slices)))
            slicer.app.processEvents()

        def on_cancel():
            return self.cancelProcess

        outputImageArray = compute_polynomial_shading_correction(
            inputImageArray=inputImageArray,
            inputShadingMaskArray=inputShadingMaskArray,
            sliceGroupSize=sliceGroupSize,
            fittingPointsPercentage=fittingPointsPercentage,
            functionType=functionType,
            polynomialOrder=polynomialOrder,
            useCustomCenter=useCustomCenter,
            centerX=centerX,
            centerY=centerY,
            inputNullValue=input_null_value,
            progressCallback=on_progress,
            cancelCallback=on_cancel,
        )

        logging.info(
            "Polynomial shading correction elapsed time: " + str((datetime.datetime.now() - start).total_seconds())
        )
        return outputImageArray


class ProcessInfo(RuntimeError):
    pass
