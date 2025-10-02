import copy
import glob
import importlib
import json
import logging
import math
import os
import pickle
import shutil
from pathlib import Path

from ltrace.slicer.thin_section.instance_segmenter_widget import (
    ThinSectionInstanceSegmenterWidget,
)

import ctk
import cv2
import markdown
import matplotlib.colors as mcolors
import numpy as np
import qt
import slicer
import vtk
from recordtype import recordtype  # mutable

from SegmenterMethods.correlation_distance import CorrelationDistance
from ltrace.algorithms.gabor import get_gabor_kernels
from ltrace.assets_utils import get_metadata, get_pth
from ltrace.slicer import ui, helpers, widgets
from ltrace.slicer.binary_node import createBinaryNode, getBinary
from ltrace.slicer.helpers import (
    clearPattern,
    createLabelmapInput,
    validateSourceVolume,
    rgb2label,
    maskInputWithROI,
    highlight_error,
    hex2Rgb,
    getCurrentEnvironment,
)
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer.widget.trained_model_selector import TrainedModelSelector
from ltrace.slicer.widgets import BaseSettingsWidget, PixelLabel
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, getResourcePath
from ltrace.slicer.cli_queue import CliQueue

# Checks if closed source code is available
try:
    from Test.SegmenterTest import SegmenterTest
except ImportError as e:
    SegmenterTest = None  # tests not deployed to final version or closed source

SegmentLabel = recordtype("SegmentLabel", ["name", "color", "id", "value", ("property", "Solid")])

TAB_COLORS = [name for name in mcolors.TABLEAU_COLORS]


def getVolumeMinSpacing(volumeNode):
    return min(volumeNode.GetSpacing())


def compareVolumeSpacings(volumeNode, referenceNode):
    volumeSpacing = getVolumeMinSpacing(volumeNode)
    referenceSpacing = getVolumeMinSpacing(referenceNode)
    sameMinSpacing = volumeSpacing == referenceSpacing
    delta = volumeSpacing - referenceSpacing
    relativeError = abs(delta / referenceSpacing) if referenceSpacing > 0 else 1
    return sameMinSpacing, relativeError


def maybeAdjustSpacingAndCrop(volumeNode, outputPrefix, soiNode=None, referenceNode=None):
    if volumeNode is None:
        return None

    adjustSpacing = False
    if referenceNode is not None:
        sameMinSpacing, relativeError = compareVolumeSpacings(volumeNode, referenceNode)
        if not sameMinSpacing:
            adjustSpacing = True

    # copy original array
    if soiNode or adjustSpacing:
        volumeNode = helpers.createTemporaryVolumeNode(
            volumeNode.__class__,
            outputPrefix.replace("{type}", "TMP_REFNODE"),
            hidden=True,
            content=volumeNode,
        )

        if referenceNode:
            referenceSpacing = referenceNode.GetSpacing()
            volumeNode.SetSpacing(referenceSpacing)
            volumeOrigin = np.array(volumeNode.GetOrigin())
            volumeNode.SetOrigin((volumeOrigin // referenceSpacing) * referenceSpacing)

    # crop with SOI
    if soiNode:
        volumeNode = maskInputWithROI(volumeNode, soiNode, mask=False)

    return volumeNode


def makeColorsSlices(volumeNode, outputPrefix, deleteOriginal=False):
    # the strategy of making color channels slices is hacky,
    # works only for 2D data and thus should be avoided
    originalNode = volumeNode
    volumeNode = rgb2label(originalNode, outputPrefix.replace("{type}", "TMP_REFNODECM"))
    if deleteOriginal:
        slicer.mrmlScene.RemoveNode(originalNode)
    return volumeNode


def prepareTemporaryInputs(inputNodes, outputPrefix, soiNode=None, referenceNode=None, colorsToSlices=False):
    ctypes = []
    tmpInputNodes = []
    tmpReferenceNode = None
    tmpReferenceNodeDims = None

    for n, node in enumerate(inputNodes):
        if node is None:
            continue

        tmpNode = maybeAdjustSpacingAndCrop(node, outputPrefix, soiNode=soiNode, referenceNode=referenceNode)

        if n == 0:
            tmpReferenceNode = tmpNode
            tmpReferenceNodeDims = tmpReferenceNode.GetImageData().GetDimensions()
        else:
            tmpNodeDims = tmpNode.GetImageData().GetDimensions()
            sameDimensions = all(d1 == d2 for d1, d2 in zip(tmpNodeDims, tmpReferenceNodeDims))
            if not sameDimensions:
                msg = (
                    "Volume arrays inside SOI have different shapes "
                    f"({tmpNodeDims} found while {tmpReferenceNodeDims} was expected)"
                )
                # remove already created tmpInputNodes before cancellation
                for node, tmpNode in zip(inputNodes, tmpInputNodes):
                    if tmpNode != node and node is not None and tmpNode is not None:
                        slicer.mrmlScene.RemoveNode(tmpNode)
                raise Exception(msg)

        ctype = "rgb" if node.IsA("vtkMRMLVectorVolumeNode") else "value"
        ctypes.append(ctype)

        # the strategy of making color channels slices is hacky,
        # works only for 2D data and thus should be avoided
        if colorsToSlices and ctype == "rgb":
            tmpNodeIsCopy = tmpNode != node
            tmpNode = makeColorsSlices(tmpNode, outputPrefix=outputPrefix, deleteOriginal=tmpNodeIsCopy)

        tmpInputNodes.append(tmpNode)
    return tmpInputNodes, ctypes


class Segmenter(LTracePlugin):
    SETTING_KEY = "Segmenter"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "AI Segmenter"
        self.parent.categories = ["Segmentation", "Thin Section", "MicroCT", "ImageLog", "Core", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]  # replace with "Firstname Lastname (Organization)"
        self.parent.acknowledgementText = ""  # replace with organization, grant and thanks.
        self.setHelpUrl("Volumes/Segmentation/MicroCTSegmenter.html", NodeEnvironment.MICRO_CT)
        self.setHelpUrl("ThinSection/Segmentation/ThinSectionSegmenter.html", NodeEnvironment.THIN_SECTION)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class SegmenterWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

        self.__currentEnvironment = None
        self.cliQueue = None
        self.refNodeId = None
        self.filterUpdateThread = None
        self.inputsSelector = None
        self.inputSelectorMode = None
        self.imageLogMode = False
        self.deterministicPreTrainedModels = False
        self.poreCleaningOptionsWidget = None
        self.pxSelectedHandlerConnected = False
        self.currentWidget = None

        self.exclusiveSections = []

        self.hideWhenCreatingClassifier = []
        self.hideWhenLoadingClassifier = []

        self.layoutWidgets = []

        self.thinSectionInstanceSegmenterWidget = ThinSectionInstanceSegmenterWidget()

        self.instanceSegmenterLayout = False
        self.resetPreTrainedModelInterface = False

    def onReload(self) -> None:
        LTracePluginWidget.onReload(self)
        importlib.reload(ui)
        importlib.reload(widgets)
        importlib.reload(helpers)

    def setup(self):
        LTracePluginWidget.setup(self)

        self.layoutWidgets.append(self._setupClassifierSection())
        self.layoutWidgets.append(self._setupInputsSection())
        self.layoutWidgets.append(self._setupCleaningSection())
        self.layoutWidgets.append(self._setupSettingsSection())
        self.layoutWidgets.append(self._setupOutputSection())
        self.layoutWidgets.append(self._setupApplySection())

        self.thinSectionInstanceSegmenterWidget.setup()
        self.thinSectionInstanceSegmenterWidget.layoutWidgets[0].visible = False  # Detector section

        for widget in self.layoutWidgets:
            self.layout.addWidget(widget)

        for widget in self.thinSectionInstanceSegmenterWidget.layoutWidgets:
            self.layout.addWidget(widget)

        # Add vertical spacer
        self.layout.addStretch(1)

        self.exclusiveSections.append(
            (
                self.poreCleaningOptionsWidget,
                lambda: (
                    (self.__currentEnvironment == NodeEnvironment.THIN_SECTION.value)
                    and (self.loadClassifierRadio.isChecked())
                    and (self.modelTypeRadioGroup.checkedButton() == self.poreModelsRadioButton)
                ),
            )
        )

        self._initWidgetsStates()

    def _exchangeLayout(self):
        self.instanceSegmenterLayout = (
            self.loadClassifierRadio.isChecked() and self.texturalStructuresModelsRadioButton.isChecked()
        )
        if self.instanceSegmenterLayout:
            srcWidget = self
            dstWidget = self.thinSectionInstanceSegmenterWidget
        else:
            dstWidget = self
            srcWidget = self.thinSectionInstanceSegmenterWidget

        if dstWidget is self.currentWidget:
            return
        self.currentWidget = dstWidget

        for widget in srcWidget.layoutWidgets[1:]:
            widget.visible = False

        for widget in dstWidget.layoutWidgets[1:]:
            widget.visible = True

        dstWidget.classifierInput.setCurrentText(srcWidget.classifierInput.currentText)
        dstWidget.inputsSelector.soiInput.setCurrentNode(srcWidget.inputsSelector.soiInput.currentNode())
        dstWidget.pxInputCombobox.setCurrentNode(srcWidget.pxInputCombobox.currentNode())
        dstWidget.outputPrefix.setText(srcWidget.outputPrefix.text)

    def _setupClassifierSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Classifier"
        layout = qt.QVBoxLayout(widget)
        layout.setSpacing(4)

        textNodeType = "vtkMRMLTextNode"
        self.userClassifierInput = slicer.qMRMLNodeComboBox()
        self.userClassifierInput.objectName = "User Classifier Input ComboBox"
        self.userClassifierInput.setToolTip("Select user-trained model for segmentation")
        self.userClassifierInput.nodeTypes = (textNodeType,)
        self.userClassifierInput.addAttribute(textNodeType, "Type", "Classifier")
        self.userClassifierInput.setMRMLScene(slicer.mrmlScene)
        self.userClassifierInput.addEnabled = False
        self.userClassifierInput.removeEnabled = False
        self.userClassifierInput.noneEnabled = False
        self.userClassifierInput.setNodeTypeLabel("Classifier", textNodeType)
        self.userClassifierInput.currentNodeChanged.connect(self._onChangedUserClassifier)

        self.modelTypeLabel = qt.QLabel("Model type:")

        self.poreModelsRadioButton = qt.QRadioButton("Pore")
        self.poreModelsRadioButton.objectName = "Pore Models Radio Button"
        self.poreModelsRadioButton.connect("toggled(bool)", self._onModelTypeSelected)
        self.poreModelsRadioButton.setProperty(
            "tags",
            {
                NodeEnvironment.THIN_SECTION.value: ["PoreStats", "SiliciclasticsPore"],
                NodeEnvironment.MICRO_CT.value: ["Pore"],
            },
        )

        self.multiphaseModelsRadioButton = qt.QRadioButton("Multiphase")
        self.multiphaseModelsRadioButton.objectName = "Multiphase Models Radio Button"
        self.multiphaseModelsRadioButton.connect("toggled(bool)", self._onModelTypeSelected)
        self.multiphaseModelsRadioButton.setProperty("tags", {NodeEnvironment.THIN_SECTION.value: ["Multiphase"]})

        self.texturalStructuresModelsRadioButton = qt.QRadioButton("Textural Structures")
        self.texturalStructuresModelsRadioButton.objectName = "Textural Structures Models Radio Button"
        self.texturalStructuresModelsRadioButton.connect("toggled(bool)", self._onModelTypeSelected)
        self.texturalStructuresModelsRadioButton.setProperty(
            "tags", {NodeEnvironment.THIN_SECTION.value: ["TexturalStructures"]}
        )

        self.basinsModelsRadioButton = qt.QRadioButton("Basins")
        self.basinsModelsRadioButton.objectName = "Basins Models Radio Button"
        self.basinsModelsRadioButton.connect("toggled(bool)", self._onModelTypeSelected)
        self.basinsModelsRadioButton.setProperty("tags", {NodeEnvironment.MICRO_CT.value: ["Basins"]})

        self.modelTypeRadioGroup = qt.QButtonGroup()
        self.modelTypeRadioGroup.objectName = "Model Type Radio Buttons Group"
        self.modelTypeRadioGroup.setExclusive(True)
        self.modelTypeRadioGroup.addButton(self.poreModelsRadioButton)
        self.modelTypeRadioGroup.addButton(self.multiphaseModelsRadioButton)
        self.modelTypeRadioGroup.addButton(self.texturalStructuresModelsRadioButton)
        self.modelTypeRadioGroup.addButton(self.basinsModelsRadioButton)

        self.classifierInput = TrainedModelSelector([])

        self.classifierInput.objectName = "Classifier Input ComboBox"
        # self.classifierInput.activated.connect(self._onChangedClassifier)
        self.classifierInput.currentTextChanged.connect(self._onChangedClassifier)
        self.classifierInput.currentIndexChanged.connect(lambda _: self.classifierInput.setStyleSheet(""))

        self.classifierInfo = qt.QLabel()
        self.classifierInfo.setTextFormat(qt.Qt.RichText)
        self.classifierInfo.setOpenExternalLinks(True)
        self.classifierInfo.setTextInteractionFlags(qt.Qt.TextBrowserInteraction)
        self.classifierInfo.setWordWrap(True)

        self.classifierInfoGroupBox = ctk.ctkCollapsibleButton()
        self.classifierInfoGroupBox.text = "Attributes"
        self.classifierInfoGroupBox.flat = True
        self.classifierInfoGroupBox.collapsed = True
        infoLayout = qt.QVBoxLayout(self.classifierInfoGroupBox)
        infoLayout.addWidget(self.classifierInfo)

        self.hideWhenCreatingClassifier.append(self.classifierInfoGroupBox)

        self.createClassifierRadio = qt.QRadioButton("Model Training")
        self.createClassifierRadio.objectName = "Create Classifier Radio"
        if getCurrentEnvironment() == NodeEnvironment.THIN_SECTION:
            manualUrl = "Volumes/Segmentation/MicroCTSegmenter.html"
        else:
            manualUrl = "ThinSection/Segmentation/ThinSectionSegmenter.html"

        createClassifierHelpButton = HelpButton(
            "### Model Training\n\nTrain a model from scratch using a partially annotated image as input. "
            "The model is then used to fully segment the image. This method is more flexible, "
            "as you can choose parameters, filters and annotation for a custom use case."
            "\n\n-----\n[More]({path_to_manual})",
            replacer=lambda x: x.format(path_to_manual=manualUrl),
        )
        self.loadClassifierRadio = qt.QRadioButton("Pre-trained Models")
        self.loadClassifierRadio.objectName = "Load Classifier Radio"

        def loadClassifierUrlReplacer(url):
            if getCurrentEnvironment() == NodeEnvironment.MICRO_CT:
                return url.format(path_to_manual=manualUrl)

            return url.format(path_to_manual=manualUrl)

        self.loadClassifierHelpButton = HelpButton(
            "### Pre-trained Models\n\nSegment using a pre-trained model. Each model was extensively trained "
            "for a specific use case and only requires an image as input. Select a model to view its information."
            "\n\n-----\n[More]({path_to_manual})",
            replacer=loadClassifierUrlReplacer,
        )

        self.userClassifierRadio = qt.QRadioButton("User Custom Pre-trained Models")
        self.userClassifierRadio.objectName = "User Classifier Radio"
        self.userClassifierHelpButton = HelpButton(
            "### User Custom Pre-trained Models\n\nUse a model that was previously trained using the 'Model Training' "
            "option. Input image must have the same number of channels that was used in training."
            "\n\n-----\n[More]({path_to_manual})",
            replacer=lambda x: x.format(path_to_manual=(manual_path / "Semiauto" / "semiauto.html").as_posix()),
        )

        hbox = qt.QHBoxLayout(widget)
        hbox.addWidget(self.createClassifierRadio)
        hbox.addWidget(createClassifierHelpButton)
        layout.addLayout(hbox)

        hbox = qt.QHBoxLayout(widget)
        hbox.addWidget(self.loadClassifierRadio)
        hbox.addWidget(self.loadClassifierHelpButton)
        layout.addLayout(hbox)

        hbox = qt.QHBoxLayout(widget)
        hbox.addWidget(self.userClassifierRadio)
        hbox.addWidget(self.userClassifierHelpButton)
        layout.addLayout(hbox)

        hbox = qt.QHBoxLayout(widget)
        hbox.addWidget(self.modelTypeLabel)
        for modelTypeRadioButton in self.modelTypeRadioGroup.buttons():
            hbox.addWidget(modelTypeRadioButton)
        layout.addLayout(hbox)

        layout.addWidget(self.classifierInput)
        layout.addWidget(self.userClassifierInput)
        layout.addWidget(self.classifierInfoGroupBox)

        vboxClassifierInput = qt.QVBoxLayout()
        vboxClassifierInput.addWidget(self.classifierInput)
        vboxClassifierInput.addWidget(self.userClassifierInput)
        vboxClassifierInput.addWidget(self.classifierInfoGroupBox)
        # set space on the top and bottom of vboxClassifierInput
        vboxClassifierInput.setContentsMargins(0, 8, 0, 8)

        layout.addLayout(vboxClassifierInput)

        self.createClassifierRadio.toggled.connect(self._onCreateClassifierToggled)
        self.loadClassifierRadio.toggled.connect(self._onLoadClassifierRadioToggled)
        self.userClassifierRadio.toggled.connect(self._onUserClassifierRadioToggled)

        return widget

    def _setupCleaningSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Cleaning"
        widget.objectName = "Cleaning Collapsible Button"
        layout = qt.QFormLayout(widget)

        self.removeSpuriousCheckbox = qt.QCheckBox("Remove spurious")
        self.removeSpuriousCheckbox.toolTip = "Detect and remove spurious predictions."
        self.removeSpuriousCheckbox.checked = True
        self.removeSpuriousCheckbox.objectName = "Remove Spurious CheckBox"

        self.cleanResinCheckbox = qt.QCheckBox("Clean resin")
        self.cleanResinCheckbox.toolTip = "Detect and clean bubbles and residues in pore resin."
        self.cleanResinCheckbox.checked = True
        self.cleanResinCheckbox.objectName = "Clean Resin CheckBox"
        self.cleanResinCheckbox.connect("toggled(bool)", self._onCleanResinClicked)

        self.pxForCleaningInput = ui.hierarchyVolumeInput(
            hasNone=True,
            nodeTypes=[
                "vtkMRMLScalarVolumeNode",
                "vtkMRMLVectorVolumeNode",
            ],
            tooltip="Combine PP and PX images for more accurate resin cleaning. If None, only the PP image is used. \
                If a PX image is required as a model input, this selector will remain blocked and set to use the same image.",
            onChange=self._onPxForCleaningSelected,
            onActivation=self._onPxForCleaningSelected,
        )
        self.pxForCleaningInput.objectName = "PX For Cleaning ComboBox"

        self.pxForCleaningInputLabel = qt.QLabel("       PX:")

        self.smartRegCheckbox = qt.QCheckBox("Smart registration")
        self.smartRegCheckbox.toolTip = "Method for registrating PP and PX images for pore resin cleaning. If unchecked, the images will be overlapped so that \
            each one's center will share the same location: recommended when the images seem to be naturally registered already. \
            If checked, the algorithm will decide between just centralizing the images (as in the unchecked case) or cropping their \
            rock region before: recommended when PP and PX have different dimensions or do not seem to overlap naturally."
        self.smartRegCheckbox.objectName = "Smart Registration CheckBox"
        self.smartRegCheckbox.checked = False

        layout.addRow(self.removeSpuriousCheckbox)
        layout.addRow(self.cleanResinCheckbox)
        layout.addRow(self.pxForCleaningInputLabel, self.pxForCleaningInput)
        layout.addRow("", self.smartRegCheckbox)

        self.poreCleaningOptionsWidget = widget

        return widget

    def _setupInputsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Inputs"
        layout = qt.QVBoxLayout(widget)

        self.inputsSelector = widgets.SingleShotInputWidget(
            rowTitles={"main": "Annotations"}, checkable=False, setDefaultMargins=False
        )
        self.inputsSelector.onMainSelectedSignal.connect(self._onInputSelected)
        self.inputsSelector.onReferenceSelectedSignal.connect(self._onReferenceSelected)

        self.inputsSelector.objectName = "SingleShot Input"
        self.hideWhenLoadingClassifier += [
            self.inputsSelector.segmentationLabel,
            self.inputsSelector.mainInput,
            self.inputsSelector.segmentsContainerWidget,
        ]

        maxInputChannels = 3

        extraInputComboboxes = [
            ui.hierarchyVolumeInput(
                hasNone=True,
                nodeTypes=[
                    "vtkMRMLScalarVolumeNode",
                    "vtkMRMLVectorVolumeNode",
                ],
            )
            for i in range(1, maxInputChannels)
        ]

        extraInputLabels = [qt.QLabel("") for i in range(1, maxInputChannels)]

        self.inputComboboxes = [self.inputsSelector.referenceInput, *extraInputComboboxes]
        self.inputLabels = [self.inputsSelector.referenceLabel, *extraInputLabels]

        self.pxInputCombobox = self.inputComboboxes[1]

        for i in range(maxInputChannels):
            combobox = self.inputComboboxes[i]
            label = self.inputLabels[i]

            combobox.objectName = f"Volume {i + 1} ComboBox"
            label.setText(f"Input volume #{i + 1}: ")

            if i > 0:
                self.inputsSelector.formLayout.addRow(label, combobox)

        layout.addWidget(self.inputsSelector)

        return widget

    def _setupSettingsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Parameters"

        formLayout = qt.QFormLayout(widget)
        self.methodSelector = ui.StackedSelector(text="Method: ")
        self.methodSelector.setToolTip("Select the algorithm to perform segmentation.")

        def _onPixelArgumentChanged(v, widget):
            pixelSize_mm = self.inputsSelector.inputVoxelSize
            # widget.validator().setDecimals(getNumberOfDecimals(pixelSize_mm))

            pixel = int(np.round(float(v) / pixelSize_mm))
            widget.setText(f"  {pixel} pixels")

        rf_widget = RandomForestSettingsWidget(radiusInput=ui.FeedbackNumberParam(onChange=_onPixelArgumentChanged))
        self.methodSelector.addWidget(rf_widget)
        node_input = self.inputsSelector.referenceInput
        rf_widget.setImageInput(node_input)

        self.bayes_widget = BayesianInferenceSettingsWidget(
            radiusInput=ui.FeedbackNumberParam(onChange=_onPixelArgumentChanged)
        )
        self.methodSelector.addWidget(self.bayes_widget)
        self.bayes_widget.setImageInput(node_input)

        self.methodSelector.selector.objectName = "Methods ComboBox"
        self.methodSelector.currentWidgetChanged.connect(self._updateWidgetsVisibility)

        formLayout.addRow(self.methodSelector)
        self.hideWhenLoadingClassifier.append(widget)

        return widget

    def _setupOutputSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Output"

        self.keepFeaturesCheckbox = qt.QCheckBox("Keep features")
        self.keepFeaturesCheckbox.toolTip = "Export the result of each feature as volumes."
        self.keepFeaturesCheckbox.checked = False
        self.keepFeaturesCheckbox.objectName = "Keep features CheckBox"
        self.hideWhenLoadingClassifier.append(self.keepFeaturesCheckbox)

        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.objectName = "Output Prefix Line Edit"

        formLayout = qt.QFormLayout(widget)
        formLayout.addRow("", self.keepFeaturesCheckbox)
        formLayout.addRow("Output Prefix: ", self.outputPrefix)

        return widget

    def _setupApplySection(self):
        widget = qt.QWidget()
        vlayout = qt.QVBoxLayout(widget)

        self.applyCancelButtons = ui.ApplyCancelButtons(
            onApplyClick=self._onApplyClicked,
            onCancelClick=self._onCancel,
            applyTooltip="Run segmenter on input data limited by ROI",
            cancelTooltip="Cancel",
            applyText="Apply",
            cancelText="Cancel",
            enabled=False,
            applyObjectName="Apply Button",
            cancelObjectName=None,
        )

        self.stepLabel = qt.QLabel("")
        self.progressBar = LocalProgressBar()

        hlayout = qt.QHBoxLayout()
        hlayout.addWidget(self.applyCancelButtons)
        hlayout.setContentsMargins(0, 8, 0, 8)

        vlayout.addLayout(hlayout)
        vlayout.addWidget(self.stepLabel)
        vlayout.addWidget(self.progressBar)

        return widget

    def _showExclusiveSections(self):
        for section, evaluator in self.exclusiveSections:
            section.visible = evaluator()

    def _onCleanResinClicked(self):
        self.pxForCleaningInput.visible = self.cleanResinCheckbox.checked
        self.pxForCleaningInputLabel.visible = self.cleanResinCheckbox.checked
        self._onPxForCleaningSelected()

    def _onCreateClassifierToggled(self, checked):
        self._updateWidgetsVisibility()
        if checked:
            self._restoreInputBoxes()
        else:
            self.inputsSelector.mainInput.setCurrentNode(None)
            self.inputsSelector.soiInput.enabled = True
            self.inputsSelector.referenceInput.enabled = True
            self._onChangedClassifier(checked)

    def _onLoadClassifierRadioToggled(self, checked):
        if checked:
            if self.resetPreTrainedModelInterface:
                self._resetToggledModelType()
                self.resetPreTrainedModelInterface = False
            else:
                self._onChangedClassifier()

        self._onCleanResinClicked()
        self._updateWidgetsVisibility()

    def _onUserClassifierRadioToggled(self, checked):
        if checked:
            self._onChangedClassifier()

            self._onChangedUserClassifier(self.userClassifierInput.currentNode())

        self._updateWidgetsVisibility()
        self._restoreInputBoxes()

    """ Handlers """

    def enter(self) -> None:
        super().enter()
        enteringNodeEnv = getCurrentEnvironment()
        if enteringNodeEnv is None:
            return
        enteringEnv = enteringNodeEnv.value
        envs = tuple(map(lambda x: x.value, NodeEnvironment))
        if enteringEnv not in envs:
            return

        if enteringEnv != self.__currentEnvironment:
            self.__currentEnvironment = enteringEnv

            if self.loadClassifierRadio.isChecked():
                self._resetToggledModelType()
            else:
                self.resetPreTrainedModelInterface = True

        self._showExclusiveSections()
        self._updateWidgetsVisibility()

    def _resetToggledModelType(self):
        for modelTypeRadioButton in self.modelTypeRadioGroup.buttons():
            if modelTypeRadioButton.visible:
                if modelTypeRadioButton is self.modelTypeRadioGroup.checkedButton():
                    modelTypeRadioButton.toggled(True)  # force emitting signal
                else:
                    modelTypeRadioButton.toggle()
                break

    def _updateModels(self, tags=None):
        if tags:
            self.classifierInput.setTags(tags, modelCategory=self.modelTypeRadioGroup.checkedButton().text)

        if self.classifierInput.currentData is None:
            if self.loadClassifierRadio.isChecked() and self.classifierInput.count == 1:
                self.classifierInput.triggerMissingModel()

    def _onChangedClassifier(self, selected=None):
        if self.instanceSegmenterLayout:
            instanceSegmenterTitle = self.modelTypeRadioGroup.checkedButton().text
            self.thinSectionInstanceSegmenterWidget.classifierInput.setCurrentText(
                f"{instanceSegmenterTitle} - {self.classifierInput.currentText}"
            )

        metadata = self.classifierInput.getSelectedModelMetadata() if self.classifierInput.currentData else dict()
        model_inputs = metadata.get("inputs", dict())
        model_outputs = metadata.get("outputs", dict())
        model_input_names = list(model_inputs.keys())
        model_output_names = list(model_outputs.keys())
        # temporary limitationonly taking one output
        model_output = model_outputs[model_output_names[0]] if model_outputs else dict()
        model_classes = model_output.get("class_names", []) if model_output else []

        for i in range(len(self.inputComboboxes)):
            label = self.inputLabels[i]
            combobox = self.inputComboboxes[i]

            if i < len(model_input_names):
                label.visible = True
                combobox.visible = True

                input_name = model_input_names[i]
                input_name = input_name[0].upper() + input_name[1:]
                label.setText(f"{input_name}: ")
            else:
                label.visible = False
                combobox.visible = False

        space = 2 * " "

        if "description" in metadata:
            model_description = "\n".join([f"**Description:**", "\n", metadata["description"], "\n"])
        else:
            model_description = ""

        model_inputs_description = [f"**Inputs ({len(model_inputs)}):**", "\n"]
        for name, description in model_inputs.items():
            model_inputs_description += [f"{space}- {name}:"]
            spatial_dims = description.get("spatial_dims")
            if spatial_dims is not None:
                model_inputs_description += [f"{2 * space}- Dimensions: {spatial_dims}"]

            n_channels = description.get("n_channels", 1)
            if n_channels is not None:
                model_inputs_description += [f"{2 * space}- Channels: {n_channels}"]
        model_inputs_description = "\n".join(model_inputs_description)

        model_outputs_description = [f"**Outputs ({len(model_outputs)}):**", "\n"]
        for name, description in model_outputs.items():
            is_segmentation = description.get("is_segmentation", True)
            if is_segmentation and len(model_outputs) == 1:
                name = "Segmentation"
            model_outputs_description += [
                f"{space}- {name}:",
            ]
            spatial_dims = description.get("spatial_dims")
            if spatial_dims is not None:
                model_outputs_description += [f"{2 * space}- Dimensions: {spatial_dims}"]

            if is_segmentation:
                models_classes = description.get("model_classes", 1)
                if models_classes is not None:
                    model_outputs_description += [f"{2 * space}- Classes:"]
                    for model_class in model_classes:
                        model_outputs_description += [f"{4 * space}- {model_class}"]
            else:
                n_channels = description.get("n_channels", 1)
                if n_channels is not None:
                    model_outputs_description += [f"{2 * space}- Channels: {n_channels}"]
        model_outputs_description = "\n".join(model_outputs_description)

        msg = "\n\n".join(
            [
                model_description,
                model_inputs_description,
                model_outputs_description,
            ]
        )

        html = markdown.markdown(msg)
        self.classifierInfo.setText(html)
        self.classifierInfo.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Fixed)
        summary = f"Output classes: {len(model_classes)}"
        self.classifierInfoGroupBox.text = summary

        for i, combobox in enumerate(self.inputComboboxes):
            if i >= len(model_inputs):
                combobox.setCurrentNode(None)

        self.inputsSelector.mainInput.setCurrentNode(None)
        self.pxForCleaningInput.enabled = len(model_inputs) == 1
        if not self.pxForCleaningInput.enabled:
            self._onPxSelected()

    def _onChangedUserClassifier(self, selected):
        validNode = selected and selected.IsA("vtkMRMLTextNode")
        if not validNode:
            self.classifierInfo.setText(
                'There are no user classifiers available. You can create one using the "Model Training" option.'
            )
            self.classifierInfoGroupBox.text = "Output classes: None"
            return

        content = pickle.loads(getBinary(selected))
        model_classes = [classes[1] for classes in content["colors"]]
        model_classes = "\n    * ".join(model_classes)
        model = content["model"]
        msg = f"""
* **Model type:** {model.__class__.__name__}
* **Classes:**
* {model_classes}
* **Number of input images:** {content['props']['Number of Extra images'] + 1}
* **Color channels:** {content['props']['Total color channels']}
"""
        html = markdown.markdown(msg)
        self.classifierInfo.setText(html)
        self.classifierInfoGroupBox.text = f"Model: {model.__class__.__name__}, {len(content['colors'])} classes"

    def _restoreInputBoxes(self):
        for i in range(len(self.inputLabels)):
            label = self.inputLabels[i]
            combobox = self.inputComboboxes[i]

            label.setText(f"Input volume #{i + 1}: ")

            if i > 0:
                # only extra (i>0) volume comboboxes are hidden
                label.visible = True
                combobox.visible = True

    def _onModelTypeSelected(self, checked):
        if checked:
            self._updateWidgetsVisibility()
            self._updateModels(
                tags=self.modelTypeRadioGroup.checkedButton().property("tags")[self.__currentEnvironment]
            )

    def _onCreateClassifierToggled(self, checked):
        self._updateWidgetsVisibility()

        if checked:
            self._restoreInputBoxes()
        else:
            self.inputsSelector.mainInput.setCurrentNode(None)
            self.inputsSelector.soiInput.enabled = True
            self.inputsSelector.referenceInput.enabled = True
            self._onChangedClassifier(checked)

    def _onInputSelected(self, node):
        pass

    def _onReferenceSelected(self, node):
        self.refNodeId = node.GetID() if node is not None else None

        self._checkRequirementsForApply()

        if node is None:
            return

        spacing = min([x for x in node.GetSpacing()])
        minSide = min(filter(lambda i: i != 1, node.GetImageData().GetDimensions())) * spacing

        self.outputPrefix.setText(node.GetName())

        for i in range(self.methodSelector.count()):
            self.methodSelector.widget(i).onReferenceChanged(node, False)
            self.methodSelector.widget(i).setPixelSizeAndMinSide(spacing, minSide)

        self.bayes_widget.setImageInput(node)

    def _onPxSelected(self):
        self.pxForCleaningInput.setCurrentNode(self.pxInputCombobox.currentNode())

    def _onPxForCleaningSelected(self):
        self.smartRegCheckbox.visible = self.pxForCleaningInput.visible and (
            self.pxForCleaningInput.currentNode() is not None
        )

    def _checkHaveFilters(self):
        if self.createClassifierRadio.isChecked() and self.methodSelector.currentWidget().METHOD == "random_forest":
            valid = len(self.methodSelector.currentWidget().customFilters) and (self.refNodeId != None)
            return valid
        return True

    def _checkRequirementsForApply(self):
        if self.methodSelector.currentWidget() == None:
            return

        if self.cliQueue == None or not self.cliQueue.is_running():
            self.applyCancelButtons.setEnabled(self.refNodeId is not None)
        else:
            self.applyCancelButtons.setEnabled(False)

    def _currentMethod(self):
        widget = self.methodSelector.currentWidget()
        if not widget:
            return None
        method = widget.METHOD
        if self.loadClassifierRadio.checked:
            method = "random_forest"
        return method

    def _onApplyClicked(self):
        if not self._checkHaveFilters():
            # Can only be random forest
            highlight_error(self.methodSelector.currentWidget().tableFilters)
            return

        segmentationNode = self.inputsSelector.mainInput.currentNode()
        roiSegNode = self.inputsSelector.soiInput.currentNode()
        referenceVolumeNode = self.inputsSelector.referenceInput.currentNode()  ## Can be null

        if not validateSourceVolume(segmentationNode, roiSegNode, referenceVolumeNode):
            return

        self.applyCancelButtons.applyBtn.setEnabled(False)
        self.applyCancelButtons.cancelBtn.setEnabled(True)
        prefix = self.outputPrefix.text + "_{type}"

        if not self.imageLogMode:
            if segmentationNode:
                segmentationNode.GetDisplayNode().SetVisibility(False)
            if roiSegNode:
                roiSegNode.GetDisplayNode().SetVisibility(False)

        extraVolumeNodes = [combobox.currentNode() for combobox in self.inputComboboxes[1:]]

        for node in extraVolumeNodes:
            if node is None:
                continue
            sameMinSpacing, relativeError = compareVolumeSpacings(node, referenceVolumeNode)
            if relativeError > 0.01:
                slicer.util.warningDisplay(
                    "The selected volume nodes have too different voxel sizes " " (difference > 1%)"
                )
                return

        try:
            self.cliQueue = CliQueue(update_display=False, progress_bar=self.progressBar, progress_label=self.stepLabel)

            if self._currentMethod() == "bayesian-inference":
                inputModelDir = None
                params = self.methodSelector.currentWidget().getValuesAsDict()
                logic = BayesianInferenceLogic(self.imageLogMode, parent=self.parent)
                logic.processFinished.connect(self.resetUI)
                logic.run(
                    inputModelDir,
                    segmentationNode,
                    referenceVolumeNode,
                    extraVolumeNodes,
                    roiSegNode,
                    prefix,
                    params,
                    self.cliQueue,
                )
            elif self.createClassifierRadio.checked:
                inputModelDir = None
                params = self.methodSelector.currentWidget().getValuesAsDict()
                logic = SegmenterLogic(self.imageLogMode, parent=self.parent)
                logic.processFinished.connect(self.resetUI)
                logic.run(
                    inputModelDir,
                    segmentationNode,
                    referenceVolumeNode,
                    extraVolumeNodes,
                    roiSegNode,
                    prefix,
                    params,
                    self.keepFeaturesCheckbox.checked,
                    self.cliQueue,
                )
            elif self.userClassifierRadio.checked:
                inputModelDir = self.userClassifierInput.currentNode()
                if not inputModelDir:
                    highlight_error(self.userClassifierInput)
                    raise ValueError("Please select a valid model.")
                params = None
                logic = SegmenterLogic(self.imageLogMode, parent=self.parent)
                logic.processFinished.connect(self.resetUI)
                logic.run(
                    inputModelDir,
                    segmentationNode,
                    referenceVolumeNode,
                    extraVolumeNodes,
                    roiSegNode,
                    prefix,
                    params,
                    self.keepFeaturesCheckbox.checked,
                    self.cliQueue,
                )
            else:
                inputModelComboBox = self.classifierInput
                modelKind = self.classifierInput.getSelectedModelMetadata()["kind"]
                kernelSize = None

                if modelKind == "torch":
                    logic = MonaiModelsLogic(self.imageLogMode, parent=self.parent)
                    logic.processFinished.connect(self.resetUI)
                    tmpReferenceNode, tmpOutNode = logic.run(
                        inputModelComboBox,
                        referenceVolumeNode,
                        extraVolumeNodes,
                        roiSegNode,
                        prefix,
                        self.deterministicPreTrainedModels,
                        self.cliQueue,
                    )
                elif modelKind == "bayesian":
                    kernelSize = int(inputModelComboBox.getSelectedModelPath().split("_")[-1][0])
                    params = None
                    logic = BayesianInferenceLogic(self.imageLogMode, parent=self.parent)
                    logic.processFinished.connect(self.resetUI)
                    tmpReferenceNode, tmpOutNode = logic.run(
                        inputModelComboBox.getSelectedModelPath(),
                        segmentationNode,
                        referenceVolumeNode,
                        extraVolumeNodes,
                        roiSegNode,
                        prefix,
                        params,
                        self.cliQueue,
                    )

                if self.cliQueue and self.poreCleaningOptionsWidget.visible:
                    logic = PoreCleaningLogic(
                        removeSpurious=self.removeSpuriousCheckbox.isChecked(),
                        cleanResin=self.cleanResinCheckbox.isChecked(),
                        selectedPxNode=self.pxForCleaningInput.currentNode(),
                        smartReg=self.smartRegCheckbox.isChecked(),
                        parent=self.parent,
                    )
                    logic.run(tmpReferenceNode, tmpOutNode, roiSegNode, modelKind, kernelSize, self.cliQueue)

            self.cliQueue.run()
        except Exception as e:
            slicer.util.errorDisplay(f"Failed to complete execution. {e}")
            tmpPrefix = prefix.replace("_{type}", "_TMP_*")
            clearPattern(tmpPrefix)
            clearPattern("TMP_P*_ROCK_AREA*")
            self.applyCancelButtons.applyBtn.setEnabled(True)
            self.applyCancelButtons.cancelBtn.setEnabled(False)
            raise

    def _onCancel(self):
        if self.cliQueue is None:
            return
        self.cliQueue.stop(cancelled=True)

    def resetUI(self):
        self._checkRequirementsForApply()
        if self.cliQueue:
            del self.cliQueue
            self.cliQueue = None

    def _updateWidgetsVisibility(self):
        self._exchangeLayout()
        self._showExclusiveSections()

        self._checkRequirementsForApply()

        isCreating = self.createClassifierRadio.isChecked()
        for widget in self.hideWhenLoadingClassifier:
            widget.visible = isCreating
        for widget in self.hideWhenCreatingClassifier:
            widget.visible = not isCreating

        isPreTrainedModelsAvailable = self.classifierInput.count > 0
        if not isPreTrainedModelsAvailable:
            self.loadClassifierRadio.setChecked(False)

        self.loadClassifierRadio.visible = isPreTrainedModelsAvailable
        self.loadClassifierHelpButton.visible = isPreTrainedModelsAvailable

        self.classifierInput.visible = self.loadClassifierRadio.isChecked()
        self.userClassifierInput.visible = self.userClassifierRadio.isChecked()

        self.modelTypeLabel.visible = self.classifierInput.visible

        for modelTypeRadioButton in self.modelTypeRadioGroup.buttons():
            modelTypeRadioButton.visible = self.classifierInput.visible and (
                self.__currentEnvironment in modelTypeRadioButton.property("tags")
            )

        if self.classifierInput.visible:
            if not self.pxSelectedHandlerConnected:
                self.pxInputCombobox.currentItemChanged.connect(self._onPxSelected)
                self.pxSelectedHandlerConnected = True
        else:
            self.pxInputCombobox.currentItemChanged.disconnect()
            self.pxSelectedHandlerConnected = False

        method = self._currentMethod()
        if method and method != "random_forest":
            self.keepFeaturesCheckbox.visible = False

    def _initWidgetsStates(self):
        self.createClassifierRadio.toggle()


def getNumberOfDecimals(value):
    decimalTokens = str(value).split(".")
    if len(decimalTokens) == 2:
        return len(decimalTokens[-1])
    return 1


def copyColorTable(referenceSegmentationNode, destinationNode):
    lockHandle = destinationNode.StartModify()
    priorSegm = referenceSegmentationNode.GetSegmentation()
    outputSegm = destinationNode.GetSegmentation()
    for j in range(outputSegm.GetNumberOfSegments()):
        outputSegment = outputSegm.GetNthSegment(j)
        for i in range(priorSegm.GetNumberOfSegments()):
            priorSegment = priorSegm.GetNthSegment(i)
            if priorSegment.GetLabelValue() == outputSegment.GetLabelValue():
                outputSegment.SetName(str(priorSegment.GetName()))
                outputSegment.SetColor(priorSegment.GetColor())
                break  # Done with this segment

    destinationNode.Modified()
    destinationNode.EndModify(lockHandle)


def revertColorTable(invMap, destinationNode):
    segmentation = destinationNode.GetSegmentation()
    for j in range(segmentation.GetNumberOfSegments()):
        segment = segmentation.GetNthSegment(j)
        try:
            index, name, color = invMap[segment.GetLabelValue() - 1]
            segment.SetName(name)
            segment.SetColor(color[:3])
            # segment.SetLabelValue(index)
        except Exception as e:
            logging.error(
                f"Failed during segment {j} [id: {segmentation.GetNthSegmentID(j)}, name: {segment.GetName()}, label: {segment.GetLabelValue()}]"
            )


def setupResultInScene(segmentationNode, referenceNode, imageLogMode, soiNode=None, croppedReferenceNode=None):
    folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    itemTreeId = folderTree.GetItemByDataNode(referenceNode)
    parentItemId = folderTree.GetItemParent(itemTreeId)
    nodeTreeId = folderTree.CreateItem(parentItemId, segmentationNode)

    if imageLogMode:
        segmentationNode.SetAttribute("ImageLogSegmentation", "True")
    else:
        segmentationNode.GetDisplayNode().SetVisibility(True)
        folderTree.SetItemDisplayVisibility(nodeTreeId, True)

        if soiNode:
            slicer.util.setSliceViewerLayers(background=croppedReferenceNode, fit=True)
            slicer.util.setSliceViewerLayers(background=referenceNode, fit=False)
        else:
            slicer.util.setSliceViewerLayers(background=referenceNode, fit=True)


def hideTmpOutput(caller, event, params):
    if caller.GetStatus() == slicer.vtkMRMLCommandLineModuleNode.Completed:
        slicer.util.setSliceViewerLayers(label=None)


class ClassifierProps:
    """Properties that determine whether specified inputs are compatible
    with a pre-trained classifier.
    """

    def __init__(self, image, extraNodes):
        extraNodes = [node for node in extraNodes if node]
        self.extraNodeCount = len(extraNodes)
        images = extraNodes + [image]
        channels = [helpers.number_of_channels(img) for img in images]
        self.totalChannelCount = sum(channels)

    def to_dict(self):
        return {
            "Number of Extra images": self.extraNodeCount,
            "Total color channels": self.totalChannelCount,
        }

    @staticmethod
    def prettify(dict_):
        return "\n".join(f"{key}: {val}" for key, val in sorted(dict_.items()))


class PoreCleaningLogic(LTracePluginLogic):
    def __init__(self, removeSpurious, cleanResin, selectedPxNode, smartReg, parent: qt.QObject = None):
        super().__init__(parent)
        self.removeSpurious = removeSpurious
        self.cleanResin = cleanResin
        self.selectedPxNode = selectedPxNode
        self.smartReg = smartReg

    def run(self, referenceNode, outNode, soiNode, modelKind, bayesianKernelSize, cliQueue):
        if self.removeSpurious:
            cliConf = {
                "input": referenceNode.GetID(),
                "output": outNode.GetID(),
                "poreSegmentation": outNode.GetID(),
                "poreSegModel": "unet" if modelKind == "torch" else {3: "sbayes", 7: "bbayes"}[bayesianKernelSize],
            }
            cliQueue.create_cli_node(
                slicer.modules.removespuriouscli,
                cliConf,
                progress_text="Removing spurious detections",
                modified_callback=hideTmpOutput,
            )

        if self.cleanResin:
            tmpPpRockAreaNode = helpers.createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, "TMP_PP_ROCK_AREA")
            cliQueue.create_cli_node(
                slicer.modules.smartforegroundcli,
                parameters={"input": referenceNode.GetID(), "outputRock": tmpPpRockAreaNode.GetID()},
                progress_text="Getting PP rock area",
                modified_callback=hideTmpOutput,
            )

            cliConf = {
                "ppImage": referenceNode.GetID(),
                "poreSegmentation": outNode.GetID(),
                "output": outNode.GetID(),
                "ppRockArea": tmpPpRockAreaNode.GetID(),
            }

            tmpPxForCleaningNode = self.selectedPxNode

            if self.selectedPxNode is not None:
                if soiNode is not None:
                    tmpPxForCleaningNode = prepareTemporaryInputs(
                        [tmpPxForCleaningNode],
                        tmpPxForCleaningNode.GetName(),
                        soiNode=soiNode,
                        referenceNode=self.selectedPxNode,
                    )[0][0]

                cliConf.update({"pxImage": tmpPxForCleaningNode.GetID()})

                if self.smartReg:
                    tmpPxRockAreaNode = helpers.createTemporaryVolumeNode(
                        slicer.vtkMRMLLabelMapVolumeNode, "TMP_PX_ROCK_AREA"
                    )
                    cliQueue.create_cli_node(
                        slicer.modules.smartforegroundcli,
                        parameters={
                            "input": tmpPxForCleaningNode.GetID(),
                            "outputRock": tmpPxRockAreaNode.GetID(),
                        },
                        progress_text="Getting PX rock area",
                        modified_callback=hideTmpOutput,
                    )

                    cliConf.update({"pxRockArea": tmpPxRockAreaNode.GetID(), "smartReg": True})

            cliQueue.create_cli_node(
                slicer.modules.cleanresincli,
                cliConf,
                progress_text="Cleaning pore resin",
                modified_callback=hideTmpOutput,
            )


class LogicBase(LTracePluginLogic):
    processFinished = qt.Signal()
    nodeCreated = qt.Signal(str)

    def __init__(self, parent: qt.QObject = None, imageLogMode: bool = False):
        super().__init__(parent)
        self.imageLogMode = imageLogMode


class SegmenterLogic(LogicBase):
    def __init__(self, imageLogMode, parent=None):
        super().__init__(parent, imageLogMode)

        self.progressUpdate = lambda value: print(value * 100, "%")
        self.filtered_volume_node_id = None
        self.filtered_volume_list = []

    @staticmethod
    def createLabelmapNode(segmentationNode, referenceNode, soiNode, outputPrefix):
        labelmapNode, invmap = createLabelmapInput(
            segmentationNode=segmentationNode,
            name=outputPrefix.replace("{type}", "_TMP_SEG"),
            referenceNode=referenceNode,
        )

        if soiNode:
            original_pixel_segment_count = np.bincount(slicer.util.arrayFromVolume(labelmapNode).ravel())
            labelmapNode = maskInputWithROI(labelmapNode, soiNode)
            soi_pixel_segment_count = np.bincount(
                slicer.util.arrayFromVolume(labelmapNode).ravel(), minlength=len(original_pixel_segment_count)
            )

            # Check for segments outside SOI
            pixel_segment_diff = original_pixel_segment_count - soi_pixel_segment_count
            segments_outside_soi_indexes = [index for index, count in enumerate(pixel_segment_diff) if count > 0]
            segments_fully_outside_soi_indexes = soi_pixel_segment_count[segments_outside_soi_indexes] == 0
            if segments_fully_outside_soi_indexes.any():
                raise RuntimeError(
                    "The segments of the input annotation are not contained by the region of interest delimited by the input SOI."
                )
            segments_outside_soi_names = [
                name for index, name, color in invmap if index in segments_outside_soi_indexes
            ]
            if len(segments_outside_soi_names) > 0:
                segments_outside_soi_names = "\n".join(segments_outside_soi_names)
                slicer.util.warningDisplay(
                    "Annotations outside the SOI region will be ignored.\n"
                    f"The following segments are not fully contained in SOI:\n{segments_outside_soi_names}"
                )

            # Delete missing
            for i, count in enumerate(soi_pixel_segment_count):
                if soi_pixel_segment_count[i] == 0:
                    invmap_index = [index for index, value in enumerate(invmap) if value[0] == i]
                    if len(invmap_index) > 0:
                        del invmap[invmap_index[0]]

        if len(invmap) == 0:
            raise RuntimeError(
                "The segments of the input annotation are not contained by the region of interest delimited by the input SOI."
            )

        labelDataArray = slicer.util.arrayFromVolume(labelmapNode)
        z_coords = []
        x_coords = []
        y_coords = []
        for i in range(len(invmap)):
            label = i + 1
            z_slice, x_slice, y_slice = np.where(labelDataArray == label)
            samples = np.arange(0, min(len(z_slice), 50000)).astype(np.int32)
            np.random.shuffle(samples)
            z_coords.append(z_slice[samples])
            x_coords.append(x_slice[samples])
            y_coords.append(y_slice[samples])

        crop_z_slice = np.concatenate(z_coords)
        crop_x_slice = np.concatenate(x_coords)
        crop_y_slice = np.concatenate(y_coords)

        annotations = np.zeros((1, len(crop_x_slice), 4), dtype=np.float32)
        annotations[0, :, 0] = crop_z_slice
        annotations[0, :, 1] = crop_x_slice
        annotations[0, :, 2] = crop_y_slice
        annotations[0, :, 3] = labelDataArray[crop_z_slice, crop_x_slice, crop_y_slice]
        slicer.util.updateVolumeFromArray(labelmapNode, annotations)
        return labelmapNode, invmap

    def run(
        self,
        inputClassifierNode,
        segmentationNode,
        referenceNode,
        extraNodes,
        soiNode,
        outputPrefix,
        params,
        enableKeepFeatures,
        cliQueue,
    ):
        if not inputClassifierNode and not segmentationNode:
            slicer.util.errorDisplay("Please select a valid Segmentation Node as Annotation input.")
            return

        tmpOutNode = helpers.createNode(slicer.vtkMRMLLabelMapVolumeNode, outputPrefix.replace("{type}", "TMP_OUTNODE"))
        slicer.mrmlScene.AddNode(tmpOutNode)

        inputNodes = [referenceNode, *extraNodes]

        tmpInputNodes, ctypes = prepareTemporaryInputs(
            inputNodes, outputPrefix=outputPrefix, soiNode=soiNode, referenceNode=referenceNode, colorsToSlices=True
        )
        tmpReferenceNode, *tmpExtraNodes = tmpInputNodes

        extraConf = {f"inputVolume{i}": node.GetID() for i, node in enumerate(tmpExtraNodes, start=1)}

        cliConf = dict(
            inputVolume=tmpReferenceNode.GetID(),
            outputVolume=tmpOutNode.GetID(),
            ctypes=",".join(ctypes),
            tempDir=slicer.app.temporaryPath,
            **extraConf,
        )
        classifierPath = str(Path(slicer.app.temporaryPath) / "classifier.pkl")
        if inputClassifierNode and inputClassifierNode.IsA("vtkMRMLTextNode"):
            # Use existing classifier
            content = getBinary(inputClassifierNode)
            with open(classifierPath, "wb") as f:
                f.write(content)

            content = pickle.loads(content)
            props = ClassifierProps(referenceNode, extraNodes).to_dict()
            expectedProps = content["props"]
            if props != expectedProps:
                message = (
                    f"The number of input images/channels must be the same used to "
                    f"train the classifier.\n\n"
                    f'The classifier "{inputClassifierNode.GetName()}" expects:\n\n'
                    f"{ClassifierProps.prettify(expectedProps)}\n\n"
                    f"But the current input is:\n\n"
                    f"{ClassifierProps.prettify(props)}"
                )
                raise RuntimeError(message)

            invmap = content["colors"]
            params = content["params"]

            cliConf["inputClassifier"] = classifierPath
        else:
            # Output a new classifier
            labelmapNode, invmap = SegmenterLogic.createLabelmapNode(
                segmentationNode, referenceNode, soiNode, outputPrefix
            )

            cliConf["outputClassifier"] = classifierPath
            cliConf["labelVolume"] = labelmapNode.GetID()
            cliConf["outputFeaturesResults"] = enableKeepFeatures

        cliConf["xargs"] = json.dumps(params)

        # End Setup Outputs -----------------------------------------------------------------------------

        def onSuccess():
            caller = cliQueue.get_current_node()
            try:
                outNode = helpers.createNode(
                    slicer.vtkMRMLSegmentationNode, outputPrefix.replace("{type}", "Segmentation")
                )
                outNode.SetHideFromEditors(False)
                slicer.mrmlScene.AddNode(outNode)
                outNode.SetReferenceImageGeometryParameterFromVolumeNode(referenceNode)  # use orignal volume

                helpers.updateSegmentationFromLabelMap(outNode, labelmapVolumeNode=tmpOutNode, roiVolumeNode=soiNode)
                revertColorTable(invmap, outNode)

                if len(invmap) != outNode.GetSegmentation().GetNumberOfSegments():
                    slicer.util.warningDisplay(
                        "The quantity of segments at output result different than the number of segments in annotation. This behaviour may be happen by a series of reason, mainly because a misrepresentation in terms of the features choosen or the annotation itself."
                    )

                setupResultInScene(
                    outNode, referenceNode, self.imageLogMode, soiNode=soiNode, croppedReferenceNode=tmpReferenceNode
                )

                if soiNode:
                    s_referenceNode = maybeAdjustSpacingAndCrop(
                        referenceNode, outputPrefix=outputPrefix, soiNode=soiNode
                    )
                    slicer.util.setSliceViewerLayers(background=s_referenceNode, fit=True)
                    slicer.util.setSliceViewerLayers(background=referenceNode, fit=False)
                else:
                    slicer.util.setSliceViewerLayers(background=referenceNode, fit=True)

                if inputClassifierNode:
                    return

                with open(classifierPath, "rb") as f:
                    cli_data = pickle.load(f)
                    model = cli_data["model"]
                    palette = cli_data.get("quantized_palette")
                os.remove(classifierPath)
                classifierName = outputPrefix.replace("{type}", "Classifier")
                content = {
                    "model": model,
                    "quantized_palette": palette,
                    "colors": invmap,
                    "params": params,
                    "props": ClassifierProps(referenceNode, extraNodes).to_dict(),
                }
                outputClassifierNode = createBinaryNode(pickle.dumps(content))
                outputClassifierNode.SetAttribute("Type", "Classifier")
                outputClassifierNode.SetName(slicer.mrmlScene.GenerateUniqueName(classifierName))
                slicer.mrmlScene.AddNode(outputClassifierNode)
                subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
                referenceItemId = subjectHierarchyNode.GetItemByDataNode(referenceNode)
                parentDirId = subjectHierarchyNode.GetItemParent(referenceItemId)
                classifierItemId = subjectHierarchyNode.GetItemByDataNode(outputClassifierNode)
                subjectHierarchyNode.SetItemParent(classifierItemId, parentDirId)

                outputTempDir = slicer.app.temporaryPath + "/segmenter_cli"
                if os.path.exists(outputTempDir):
                    fileList = glob.glob(f"{outputTempDir}/*.npy")
                    for outputFile in fileList:
                        data = np.load(outputFile)
                        filterVolumeSuffix = os.path.basename(outputFile).split(".")[0].capitalize()
                        self.create_node(
                            outputPrefix.replace("{type}", f"Filtered_{filterVolumeSuffix}"), tmpReferenceNode, data
                        )
                    shutil.rmtree(outputTempDir)

                warning = caller.GetParameterAsString("intermediateoutputerror")
                if warning != "":
                    slicer.util.warningDisplay(warning)
                error = caller.GetParameterAsString("variogramerror")
                if error != "":
                    slicer.util.errorDisplay(error)

            except Exception as e:
                logging.error(f"Handle errors on state: {caller.GetStatusString()}")
                tmpPrefix = outputPrefix.replace("_{type}", "_TMP_*")
                clearPattern(tmpPrefix)
                self.progressUpdate(0)
                raise

        def onFinish():
            caller = cliQueue.get_current_node()
            tmpPrefix = outputPrefix.replace("_{type}", "_TMP_*")
            clearPattern(tmpPrefix)
            self.progressUpdate(1.0)
            self.processFinished.emit()

        def onCancel():
            slicer.mrmlScene.RemoveNode(tmpOutNode)

        def onFailure():
            slicer.util.errorDisplay(f"Operation failed on {cliQueue.get_error_message()}")

        cliQueue.signal_queue_successful.connect(onSuccess)
        cliQueue.signal_queue_finished.connect(onFinish)
        cliQueue.signal_queue_cancelled.connect(onCancel)
        cliQueue.signal_queue_failed.connect(onFailure)
        cliQueue.create_cli_node(slicer.modules.segmentercli, cliConf)

        return tmpReferenceNode, tmpOutNode

    def create_node(self, name, reference, data):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        referenceItemId = subjectHierarchyNode.GetItemByDataNode(reference)
        parentDirId = subjectHierarchyNode.GetItemParent(referenceItemId)

        nodeOut = helpers.createNode(slicer.vtkMRMLScalarVolumeNode, name, hidden=False)
        slicer.mrmlScene.AddNode(nodeOut)
        volumeIJKToRASMatrix = vtk.vtkMatrix4x4()
        reference.GetIJKToRASMatrix(volumeIJKToRASMatrix)
        nodeOut.SetIJKToRASMatrix(volumeIJKToRASMatrix)
        nodeOut.SetOrigin(reference.GetOrigin())
        nodeOut.SetSpacing(reference.GetSpacing())
        slicer.util.updateVolumeFromArray(nodeOut, data)

        nodeOutItemId = subjectHierarchyNode.GetItemByDataNode(nodeOut)
        subjectHierarchyNode.SetItemParent(nodeOutItemId, parentDirId)

        return nodeOut


class MonaiModelsLogic(LogicBase):
    def __init__(self, imageLogMode: bool, parent=None):
        super().__init__(parent, imageLogMode)

        self.imageLogMode = imageLogMode
        self.progressUpdate = lambda value: print(value * 100, "%")

    def loadInvmapFromFile(self, metadata):
        invmap = []

        model_outputs = metadata["outputs"]
        model_output_names = list(model_outputs.keys())

        # temporary limitation: considering only one output
        model_output = model_outputs[model_output_names[0]]
        model_classes = model_output["class_names"]
        index = model_output.get("class_indices", list(range(1, len(model_classes) + 1)))
        name = model_output["class_names"]
        color = list(map(hex2Rgb, model_output["class_colors"]))

        for i in range(len(index)):
            invmap.append([index[i], name[i], color[i]])

        return invmap

    def run(
        self,
        inputModelComboBox,
        referenceNode,
        extraNodes,
        soiNode,
        outputPrefix,
        deterministic,
        cliQueue,
    ):
        tmpOutNode = helpers.createNode(slicer.vtkMRMLLabelMapVolumeNode, outputPrefix.replace("{type}", "TMP_OUTNODE"))
        slicer.mrmlScene.AddNode(tmpOutNode)

        inputNodes = [referenceNode, *extraNodes]

        tmpInputNodes, ctypes = prepareTemporaryInputs(
            inputNodes, outputPrefix=outputPrefix, soiNode=soiNode, referenceNode=referenceNode, colorsToSlices=False
        )
        tmpReferenceNode, *tmpExtraNodes = tmpInputNodes

        extraConf = {f"inputVolume{i}": node.GetID() for i, node in enumerate(tmpExtraNodes, start=1)}

        cliConf = dict(
            inputVolume=tmpReferenceNode.GetID(),
            outputVolume=tmpOutNode.GetID(),
            ctypes=",".join(ctypes),
            **extraConf,
            inputModel=inputModelComboBox.getSelectedModelPth(),
            xargs=json.dumps({"deterministic": deterministic}),
        )

        props = ClassifierProps(referenceNode, extraNodes).to_dict()

        metadata = inputModelComboBox.getSelectedModelMetadata()
        model_inputs = metadata["inputs"]

        total_color_channels = 0
        for name, description in model_inputs.items():
            n_channels = description.get("n_channels", 1)
            if n_channels is not None:
                total_color_channels += n_channels

        expectedProps = {
            "Number of Extra images": len(model_inputs) - 1,
            "Total color channels": total_color_channels,
        }

        if props != expectedProps:
            message = (
                f"The number of input images/channels must be the same used to "
                f"train the classifier.\n\n"
                f'The classifier "{inputModelComboBox.currentText}" expects:\n\n'
                f"{ClassifierProps.prettify(expectedProps)}\n\n"
                f"But the current input is:\n\n"
                f"{ClassifierProps.prettify(props)}"
            )
            raise RuntimeError(message)

        # End Setup Outputs -----------------------------------------------------------------------------

        def onSuccess():
            caller = cliQueue.get_current_node()
            try:
                outNode = helpers.createNode(
                    slicer.vtkMRMLSegmentationNode, outputPrefix.replace("{type}", "Segmentation")
                )
                outNode.SetHideFromEditors(False)
                slicer.mrmlScene.AddNode(outNode)
                outNode.SetReferenceImageGeometryParameterFromVolumeNode(referenceNode)  # use orignal volume

                helpers.updateSegmentationFromLabelMap(outNode, labelmapVolumeNode=tmpOutNode, roiVolumeNode=soiNode)

                invmap = self.loadInvmapFromFile(metadata)
                revertColorTable(invmap, outNode)

                setupResultInScene(
                    outNode, referenceNode, self.imageLogMode, soiNode=soiNode, croppedReferenceNode=tmpReferenceNode
                )
                outNode.GetDisplayNode().SetVisibility(True)

                if soiNode:
                    slicer.util.setSliceViewerLayers(background=tmpReferenceNode, fit=True)
                    slicer.util.setSliceViewerLayers(background=referenceNode, fit=False)
                else:
                    slicer.util.setSliceViewerLayers(background=referenceNode, fit=True)

                self.nodeCreated.emit(outNode.GetID())

            except Exception as e:
                logging.error(f"Handle errors on state: {caller.GetStatusString()}")
                tmpPrefix = outputPrefix.replace("_{type}", "_TMP_*")
                clearPattern(tmpPrefix)
                clearPattern("TMP_P*_ROCK_AREA*")
                self.progressUpdate(0)
                raise

        def onFinish():
            caller = cliQueue.get_current_node()
            tmpPrefix = outputPrefix.replace("_{type}", "_TMP_*")
            clearPattern(tmpPrefix)
            clearPattern("TMP_P*_ROCK_AREA*")
            self.progressUpdate(1.0)
            self.processFinished.emit()

        def onCancel():
            slicer.mrmlScene.RemoveNode(tmpOutNode)

        def onFailure():
            slicer.util.errorDisplay(f"Operation failed on {cliQueue.get_error_message()}")

        cliQueue.signal_queue_successful.connect(onSuccess)
        cliQueue.signal_queue_finished.connect(onFinish)
        cliQueue.signal_queue_cancelled.connect(onCancel)
        cliQueue.signal_queue_failed.connect(onFailure)
        cliQueue.create_cli_node(
            slicer.modules.monaimodelscli,
            cliConf,
            progress_text="Executing phase segmentation",
            modified_callback=hideTmpOutput,
        )

        return tmpReferenceNode, tmpOutNode


class BayesianInferenceLogic(LogicBase):
    def __init__(self, imageLogMode: bool, parent=None):
        super().__init__(parent, imageLogMode)

        self.imageLogMode = imageLogMode
        self.progressUpdate = lambda value: print(value * 100, "%")

    @staticmethod
    def createLabelmapNode(segmentationNode, referenceNode, soiNode, outputPrefix):
        labelmapNode, invmap = createLabelmapInput(
            segmentationNode=segmentationNode,
            name=outputPrefix.replace("{type}", "_TMP_SEG"),
            referenceNode=referenceNode,
        )

        if soiNode:
            original_pixel_segment_count = np.bincount(slicer.util.arrayFromVolume(labelmapNode).ravel())
            labelmapNode = maskInputWithROI(labelmapNode, soiNode)
            soi_pixel_segment_count = np.bincount(
                slicer.util.arrayFromVolume(labelmapNode).ravel(), minlength=len(original_pixel_segment_count)
            )

            # Check for segments outside SOI
            pixel_segment_diff = original_pixel_segment_count - soi_pixel_segment_count
            segments_outside_soi_indexes = [index for index, count in enumerate(pixel_segment_diff) if count > 0]
            segments_fully_outside_soi_indexes = soi_pixel_segment_count[segments_outside_soi_indexes] == 0
            if segments_fully_outside_soi_indexes.any():
                raise RuntimeError(
                    "The segments of the input annotation are not contained by the region of interest delimited by the input SOI."
                )
            segments_outside_soi_names = [
                name for index, name, color in invmap if index in segments_outside_soi_indexes
            ]
            if len(segments_outside_soi_names) > 0:
                segments_outside_soi_names = "\n".join(segments_outside_soi_names)
                slicer.util.warningDisplay(
                    "Annotations outside the SOI region will be ignored.\n"
                    f"The following segments are not fully contained in SOI:\n{segments_outside_soi_names}"
                )

            # Delete missing
            for i, count in enumerate(soi_pixel_segment_count):
                if soi_pixel_segment_count[i] == 0:
                    invmap_index = [index for index, value in enumerate(invmap) if value[0] == i]
                    if len(invmap_index) > 0:
                        del invmap[invmap_index[0]]

        if len(invmap) == 0:
            raise RuntimeError(
                "The segments of the input annotation are not contained by the region of interest delimited by the input SOI."
            )

        labelDataArray = slicer.util.arrayFromVolume(labelmapNode)
        z_coords = []
        x_coords = []
        y_coords = []
        for i in range(len(invmap)):
            label = i + 1
            z_slice, x_slice, y_slice = np.where(labelDataArray == label)
            samples = np.arange(0, min(len(z_slice), 50000)).astype(np.int32)
            np.random.shuffle(samples)
            z_coords.append(z_slice[samples])
            x_coords.append(x_slice[samples])
            y_coords.append(y_slice[samples])

        crop_z_slice = np.concatenate(z_coords)
        crop_x_slice = np.concatenate(x_coords)
        crop_y_slice = np.concatenate(y_coords)

        annotations = np.zeros((1, len(crop_x_slice), 4), dtype=np.float32)
        annotations[0, :, 0] = crop_z_slice
        annotations[0, :, 1] = crop_x_slice
        annotations[0, :, 2] = crop_y_slice
        annotations[0, :, 3] = labelDataArray[crop_z_slice, crop_x_slice, crop_y_slice]
        slicer.util.updateVolumeFromArray(labelmapNode, annotations)
        return labelmapNode, invmap

    def loadInvmapFromFile(self, metadata):
        invmap = []

        model_outputs = metadata["outputs"]
        model_output_names = list(model_outputs.keys())
        # temporary limitationonly taking one output
        model_output = model_outputs[model_output_names[0]]

        index = model_output["class_indices"]
        name = model_output["class_names"]
        color = list(map(hex2Rgb, model_output["class_colors"]))

        for i in range(len(index)):
            invmap.append([index[i], name[i], color[i]])

        return invmap

    def run(
        self,
        inputModelDir,
        segmentationNode,
        referenceNode,
        extraNodes,
        soiNode,
        outputPrefix,
        params,
        cliQueue,
    ):
        if not inputModelDir and not segmentationNode:
            slicer.util.errorDisplay("Please select a valid Segmentation Node as Annotation input.")
            return

        tmpOutNode = helpers.createNode(slicer.vtkMRMLLabelMapVolumeNode, outputPrefix.replace("{type}", "TMP_OUTNODE"))
        slicer.mrmlScene.AddNode(tmpOutNode)

        inputNodes = [referenceNode, *extraNodes]

        tmpInputNodes, ctypes = prepareTemporaryInputs(
            inputNodes, outputPrefix=outputPrefix, soiNode=soiNode, referenceNode=referenceNode, colorsToSlices=True
        )
        tmpReferenceNode, *tmpExtraNodes = tmpInputNodes

        extraConf = {f"inputVolume{i}": node.GetID() for i, node in enumerate(tmpExtraNodes, start=1)}

        inputModel = get_pth(inputModelDir).as_posix() if inputModelDir else None
        cliConf = dict(
            inputVolume=tmpReferenceNode.GetID(),
            outputVolume=tmpOutNode.GetID(),
            ctypes=",".join(ctypes),
            **extraConf,
            inputModel=inputModel,
        )

        if inputModelDir:
            metadata = get_metadata(inputModelDir)
            model_inputs = metadata["inputs"]

            total_color_channels = 0
            for name, description in model_inputs.items():
                n_channels = description.get("n_channels", 1)
                if n_channels is not None:
                    total_color_channels += n_channels

            expectedProps = {
                "Number of Extra images": len(model_inputs) - 1,
                "Total color channels": total_color_channels,
            }

            props = ClassifierProps(referenceNode, extraNodes).to_dict()

            if props != expectedProps:
                message = (
                    f"The number of input images/channels must be the same used to "
                    f"train the classifier.\n\n"
                    f'The classifier "{metadata["title"]}" expects:\n\n'
                    f"{ClassifierProps.prettify(expectedProps)}\n\n"
                    f"But the current input is:\n\n"
                    f"{ClassifierProps.prettify(props)}"
                )
                raise RuntimeError(message)

            invmap = self.loadInvmapFromFile(metadata)
        else:
            labelmapNode, invmap = SegmenterLogic.createLabelmapNode(
                segmentationNode, referenceNode, soiNode, outputPrefix
            )
            cliConf["labelVolume"] = labelmapNode.GetID()

        cliConf["xargs"] = json.dumps(params)

        # End Setup Outputs -----------------------------------------------------------------------------

        def onSuccess():
            caller = cliQueue.get_current_node()
            try:
                outNode = helpers.createNode(
                    slicer.vtkMRMLSegmentationNode, outputPrefix.replace("{type}", "Segmentation")
                )
                outNode.SetHideFromEditors(False)
                slicer.mrmlScene.AddNode(outNode)
                outNode.SetReferenceImageGeometryParameterFromVolumeNode(referenceNode)  # use orignal volume

                helpers.updateSegmentationFromLabelMap(outNode, labelmapVolumeNode=tmpOutNode, roiVolumeNode=soiNode)
                revertColorTable(invmap, outNode)

                setupResultInScene(
                    outNode, referenceNode, self.imageLogMode, soiNode=soiNode, croppedReferenceNode=tmpReferenceNode
                )
                outNode.GetDisplayNode().SetVisibility(True)

                if soiNode:
                    s_referenceNode = maybeAdjustSpacingAndCrop(
                        referenceNode, outputPrefix=outputPrefix, soiNode=soiNode
                    )
                    slicer.util.setSliceViewerLayers(background=s_referenceNode, fit=True)
                    slicer.util.setSliceViewerLayers(background=referenceNode, fit=False)
                else:
                    slicer.util.setSliceViewerLayers(background=referenceNode, fit=True)

                self.nodeCreated.emit(outNode.GetID())

            except Exception as e:
                logging.error(f"Handle errors on state: {caller.GetStatusString()}")
                tmpPrefix = outputPrefix.replace("_{type}", "_TMP_*")
                clearPattern(tmpPrefix)
                clearPattern("TMP_P*_ROCK_AREA*")
                self.progressUpdate(0)
                raise

        def onFinish():
            caller = cliQueue.get_current_node()
            tmpPrefix = outputPrefix.replace("_{type}", "_TMP_*")
            clearPattern(tmpPrefix)
            clearPattern("TMP_P*_ROCK_AREA*")
            self.progressUpdate(1.0)
            self.processFinished.emit()

        def onCancel():
            slicer.mrmlScene.RemoveNode(tmpOutNode)

        def onFailure():
            slicer.util.errorDisplay(f"Operation failed on {cliQueue.get_error_message()}")

        cliQueue.signal_queue_successful.connect(onSuccess)
        cliQueue.signal_queue_finished.connect(onFinish)
        cliQueue.signal_queue_cancelled.connect(onCancel)
        cliQueue.signal_queue_failed.connect(onFailure)
        cliQueue.create_cli_node(
            slicer.modules.bayesianinferencecli,
            cliConf,
            progress_text="Executing phase segmentation",
            modified_callback=hideTmpOutput,
        )

        return tmpReferenceNode, tmpOutNode


class RandomForestSettingsWidget(BaseSettingsWidget):
    METHOD = "random_forest"
    DISPLAY_NAME = "Random Forest"

    def __init__(self, parent=None, radiusInput=None, onSelect=None):
        super().__init__(parent)

        self.seed_rng = None

        self.customFilters = {}

        self.pixelSize = 1
        self.minSide = 9999999999

        self.onSelect = onSelect or (lambda: None)

        formLayout = qt.QFormLayout(self)

        self.random_forest_methods = {}
        self.random_forest_methods[CorrelationDistance.NAME] = CorrelationDistance()

        self.customFilterInput = qt.QComboBox()
        self.customFilterInput.addItem("Raw input image", "raw")
        self.customFilterInput.addItem("Quantized image", "quantized")
        self.customFilterInput.addItem("Petrobras model", "petrobras")
        self.customFilterInput.addItem("Gaussian filter", "gaussian")
        self.customFilterInput.addItem("Winvar filter", "winvar")
        self.customFilterInput.addItem("Gabor filters", "gabor")
        self.customFilterInput.addItem("Minkowsky filters", "minkowsky")
        for method in self.random_forest_methods.values():
            self.customFilterInput.addItem(method.DISPLAY_NAME, method.NAME)

        self.customFiltersParameters = qt.QLineEdit()

        self.addFilterButton = qt.QPushButton("+")
        self.addFilterButton.setFixedWidth(50)
        self.addFilterButton.toolTip = "Add new feature to Random Forest method"
        self.addFilterButton.enabled = True
        self.addFilterButton.connect("clicked(bool)", self.addFilter)

        self.delFilterButton = qt.QPushButton("-")
        self.delFilterButton.setFixedWidth(50)
        self.delFilterButton.toolTip = "Delete feature from table"
        self.delFilterButton.enabled = True
        self.delFilterButton.connect("clicked(bool)", self.delFilter)

        if getCurrentEnvironment() == NodeEnvironment.THIN_SECTION:
            manualUrl = "Volumes/Segmentation/MicroCTSegmenter.html"
        else:
            manualUrl = "ThinSection/Segmentation/ThinSectionSegmenter.html"

        self.addFeatureHelpButton = HelpButton("", url=manualUrl)

        hboxLayout = qt.QHBoxLayout()
        hboxLayout.addWidget(self.customFilterInput)
        hboxLayout.addWidget(self.addFilterButton)
        hboxLayout.addWidget(self.delFilterButton)
        hboxLayout.addWidget(self.addFeatureHelpButton)
        formLayout.addRow("Add Feature:", hboxLayout)

        self.tableFilters = qt.QTableWidget()
        self.tableFilters.itemDoubleClicked.connect(self.editFilter)
        self.tableFilters.objectName = "Features Table"
        formLayout.addRow(self.tableFilters)

    def addFilter(self):
        filter_func = self.customFilterInput.currentData

        if filter_func not in self.customFilters:
            self.tableFilters.setStyleSheet("")

            item = qt.QTableWidgetItem(filter_func)

            # Call QtDialog when necessary for taking parameters
            status = self.editFilter(item)

            if status:
                row = self.tableFilters.rowCount
                item.setTextAlignment(qt.Qt.AlignCenter)
                item.setFlags(qt.Qt.ItemIsEnabled)
                self.tableFilters.insertRow(row)
                self.tableFilters.setColumnCount(2)
                self.tableFilters.setItem(row, 0, item)

                string = []
                if isinstance(self.customFilters[filter_func], dict):
                    for keys in self.customFilters[filter_func].keys():
                        string.append(f"{keys}={self.customFilters[filter_func][keys]}")
                    string = ",".join(string)
                else:
                    string = ""

                options = qt.QTableWidgetItem(string)
                options.setTextAlignment(qt.Qt.AlignCenter)
                options.setFlags(qt.Qt.ItemIsEnabled)
                self.tableFilters.setItem(row, 1, options)
                self.tableFilters.setHorizontalHeaderLabels(["Features", "Options"])
                # self.tableFilters.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)
                self.tableFilters.horizontalHeader().setMinimumSectionSize(200)
                self.tableFilters.horizontalHeader().setStretchLastSection(qt.QHeaderView.Stretch)
                self.tableFilters.verticalHeader().hide()
        else:
            dialog = qt.QDialog(slicer.modules.AppContextInstance.mainWindow)
            dialog.setWindowFlags(dialog.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint)
            dialog.setWindowTitle("Feature already been added")

            formLayout = qt.QFormLayout()
            label = qt.QLabel()
            label.setText(
                f"{self.customFilterInput.currentText} already added as feature, please edit its current values by double clicking on it."
            )
            formLayout.addRow(label)

            buttonBox = qt.QDialogButtonBox(dialog)
            buttonBox.setGeometry(qt.QRect(30, 50, 50, 32))
            buttonBox.setOrientation(qt.Qt.Horizontal)
            buttonBox.setStandardButtons(qt.QDialogButtonBox.Cancel | qt.QDialogButtonBox.Ok)
            formLayout.addRow(buttonBox)

            buttonBox.accepted.connect(dialog.accept)
            buttonBox.rejected.connect(dialog.reject)
            dialog.setLayout(formLayout)
            status = dialog.exec()

    def editFilter(self, item):
        try:
            row = item.row()
            filter_func = self.tableFilters.item(row, 0).text()
        except:
            row = self.tableFilters.rowCount
            filter_func = self.customFilterInput.currentData

        status = False

        if filter_func in ("raw", "quantized", "petrobras"):
            self.customFilters[filter_func] = True
            status = True
        else:
            dialog = qt.QDialog(slicer.modules.AppContextInstance.mainWindow)
            dialog.setWindowFlags(dialog.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint)
            dialog.setWindowTitle("Customize applied filters")

            formLayout = qt.QFormLayout()

            label = qt.QLabel()
            label.setText(f"{self.customFilterInput.currentText} parameters:")
            formLayout.addRow(label)

            if filter_func == "gaussian" or filter_func == "winvar":
                sigmaValues = qt.QLineEdit()
                sigmaValues.setToolTip(
                    "Radius in mm on which to apply a gaussian filter. Accepts comma separated values in order to apply more than one filter with different parameter."
                )

                v = qt.QRegExpValidator(qt.QRegExp("\d*(?:\.\d+)?(?:,\d*(?:\.\d+)?)*"), self)
                sigmaValues.setValidator(v)
                sigmaValues.editingFinished.connect(self.truncateValuesCallback(sigmaValues, 0, self.minSide / 4.0))
                sigmaValues.setMinimumWidth(200)

                if filter_func in self.customFilters.keys():
                    options = self.customFilters[filter_func]["sigma"]
                    sigmaValues.setText(",".join(map(str, options)))

                formLayout = qt.QFormLayout()
                boxLayout = qt.QHBoxLayout()

                boxLayout.addWidget(qt.QLabel("Sigma values (mm): "))
                boxLayout.addWidget(sigmaValues)

                pixel_label = PixelLabel(value_input=sigmaValues, node_input=self.image_combo_box)
                boxLayout.addWidget(pixel_label)

                formLayout.addRow(boxLayout)

                dialog.setFixedSize(formLayout.sizeHint())
            elif filter_func == "gabor":
                sigmaValues = qt.QLineEdit()
                sigmaValues.setToolTip(
                    "Radius/standard deviation (mm) of the gaussian envelope in gabor filter. Accepts comma separated values in order to apply more than one filter with different parameter."
                )

                # Valida os valores de sigma e trunca se necessário
                v = qt.QRegExpValidator(qt.QRegExp("\d*(?:\.\d+)?(?:,\d*(?:\.\d+)?)*"), self)
                sigmaValues.setValidator(v)
                sigmaValues.editingFinished.connect(self.truncateValuesCallback(sigmaValues, 0, self.minSide / 4.0))

                directionsQuantity = qt.QLineEdit()
                directionsQuantity.setToolTip(
                    "Quantity of evenly spaced directions of gabor filter application (e.g. 5~10). Only one value."
                )

                # valida o campo se os caracteres forem de 1 a 99
                v = qt.QRegExpValidator(qt.QRegExp("[1-9]\\d{0,1}"), self)
                directionsQuantity.setValidator(v)

                lambdaValues = qt.QLineEdit()
                lambdaValues.setToolTip(
                    "Wavelength of the sinusoidal factor. Accepts comma separated values in order to apply more than one filter with different parameter."
                )

                v = qt.QRegExpValidator(qt.QRegExp("\d*(?:\.\d+)?(?:,\d*(?:\.\d+)?)*"), self)
                lambdaValues.setValidator(v)

                if filter_func in self.customFilters.keys():
                    options = self.customFilters[filter_func]
                    sigmaValues.setText(",".join(map(str, options["sigma"])))
                    directionsQuantity.setText(",".join(map(str, options["rotations"])))
                    lambdaValues.setText(",".join(map(str, options["lambda"])))

                sigmaValues.setMinimumWidth(200)
                lambdaValues.setMinimumWidth(200)

                formLayout = qt.QFormLayout()

                boxLayoutSigma = qt.QHBoxLayout()
                boxLayoutLambda = qt.QHBoxLayout()

                boxLayoutSigma.addWidget(qt.QLabel("Sigma values (mm): "))
                boxLayoutSigma.addWidget(sigmaValues)
                pixel_label_sigma = PixelLabel(value_input=sigmaValues, node_input=self.image_combo_box)
                boxLayoutSigma.addWidget(pixel_label_sigma)

                boxLayoutLambda.addWidget(qt.QLabel("Lambda values (mm): "))
                boxLayoutLambda.addWidget(lambdaValues)
                pixel_label_lambda = PixelLabel(value_input=lambdaValues, node_input=self.image_combo_box)
                boxLayoutLambda.addWidget(pixel_label_lambda)

                input_image = self.image_combo_box.currentNode()
                msg = "Preview is not being shown because no image is selected."
                if input_image:
                    shape = input_image.GetImageData().GetDimensions()
                    squeezed_shape = [s for s in shape if s > 1]
                    is_2d = len(squeezed_shape) == 2
                    if is_2d:
                        msg = "Showing a 2D gabor kernel for each direction."
                    else:
                        msg = "Showing a 3D gabor kernel for each direction. 3D kernels are a cube, so only one slice is shown for each. Size of kernel may be reduced in preview for performance."

                # Show kernel as image
                preview = qt.QLabel()
                preview_caption = qt.QLabel()
                preview_caption.setText(msg)
                preview_caption.setWordWrap(True)
                preview_size = 500

                def updatePreview():
                    try:
                        sigma = float(pixel_label_sigma.get_pixel_values()[0])
                        lambd = float(pixel_label_lambda.get_pixel_values()[0])
                        n_rotations = int(directionsQuantity.text)

                        ksize = int(sigma * 4)
                        # Reduce preview size for performance
                        max_size = 200
                        if not is_2d:
                            max_size = 50
                            if n_rotations > 20:
                                max_size = 25
                            if n_rotations > 40:
                                max_size = 15
                        ratio = 1
                        if ksize > max_size:
                            ratio = max_size / ksize
                            ksize = max_size
                        sigma = sigma * ratio
                        lambd = lambd * ratio

                        kernels = get_gabor_kernels(sigma, lambd, n_rotations, ksize, is_2d)
                        if not is_2d:
                            kernels = [k[:, :, k.shape[-1] // 2] for k in kernels]

                        row_size = round(np.sqrt(len(kernels)))
                        image_rows = [
                            np.concatenate(kernels[i : i + row_size], axis=1) for i in range(0, len(kernels), row_size)
                        ]
                        max_width = max([row.shape[1] for row in image_rows])
                        for i, row in enumerate(image_rows):
                            if row.shape[1] < max_width:
                                image_rows[i] = np.concatenate(
                                    (row, np.zeros((row.shape[0], max_width - row.shape[1]), dtype=np.uint8)), axis=1
                                )
                        kernel_image = np.concatenate(image_rows, axis=0)
                        ratio = preview_size / max(kernel_image.shape)
                        kernel_image = cv2.resize(
                            kernel_image, (0, 0), fx=ratio, fy=ratio, interpolation=cv2.INTER_NEAREST
                        )
                    except:
                        kernel_image = np.zeros((100, preview_size), dtype=np.uint8)

                    # Normalize
                    kernel_image -= kernel_image.min()
                    max_ = kernel_image.max()
                    if max_ > 0:
                        kernel_image /= max_
                    kernel_image *= 255
                    kernel_image = kernel_image.astype(np.uint8)

                    kernel_image = cv2.cvtColor(kernel_image, cv2.COLOR_GRAY2BGRA)
                    kernel_image = np.require(kernel_image, np.uint8, "C")
                    w, h = kernel_image.shape[1], kernel_image.shape[0]
                    image = qt.QImage(kernel_image.tobytes(), w, h, qt.QImage.Format_ARGB32)
                    pixmap = qt.QPixmap.fromImage(image)
                    preview.setPixmap(pixmap)

                sigmaValues.textChanged.connect(updatePreview)
                lambdaValues.textChanged.connect(updatePreview)
                directionsQuantity.textChanged.connect(updatePreview)
                updatePreview()

                formLayout.addRow(boxLayoutSigma)
                formLayout.addRow("Directions quantity: ", directionsQuantity)
                formLayout.addRow(boxLayoutLambda)
                formLayout.addRow("Kernel preview: ", preview)
                formLayout.addRow("", preview_caption)

                dialog.setFixedSize(formLayout.sizeHint())
            elif filter_func == "minkowsky":
                thresholdValues = qt.QLineEdit()
                thresholdValues.setToolTip(
                    "Threshold value for binarization used in Minkowsky filter. Accepts comma separated values in order to apply more than one filter with different parameter."
                )

                v = qt.QRegExpValidator(qt.QRegExp("\d*(?:\.\d+)?(?:,\d*(?:\.\d+)?)*"), self)
                thresholdValues.setValidator(v)
                thresholdValues.editingFinished.connect(self.truncateValuesCallback(thresholdValues, 0, 1))

                kernelSize = qt.QLineEdit()
                kernelSize.setToolTip("Size of the kernel used to calculate Minkowsky functionals.")

                v = qt.QRegExpValidator(qt.QRegExp("\d*(?:\.\d+)?(?:,\d*(?:\.\d+)?)*"), self)
                kernelSize.setValidator(v)
                kernelSize.editingFinished.connect(self.truncateValuesCallback(kernelSize, 0, self.minSide / 4.0))
                kernelSize.setMinimumWidth(200)

                if filter_func in self.customFilters.keys():
                    options = self.customFilters[filter_func]
                    thresholdValues.setText(",".join(map(str, options["threshold"])))
                    kernelSize.setText(",".join(map(str, options["kernel_size"])))

                formLayout = qt.QFormLayout()
                formLayout.addRow("Threshold values (0~1): ", thresholdValues)

                boxLayout = qt.QHBoxLayout()
                boxLayout.addWidget(qt.QLabel("Kernel size (mm): "))
                boxLayout.addWidget(kernelSize)
                pixel_label = PixelLabel(value_input=kernelSize, node_input=self.image_combo_box)
                boxLayout.addWidget(pixel_label)
                formLayout.addRow(boxLayout)
            else:
                method = self.random_forest_methods.get(filter_func)
                if method is not None:
                    formLayout = method.create_layout(self.image_combo_box)

            buttonBox = qt.QDialogButtonBox(dialog)
            buttonBox.setGeometry(qt.QRect(30, 240, 341, 32))
            buttonBox.setOrientation(qt.Qt.Horizontal)
            buttonBox.setStandardButtons(qt.QDialogButtonBox.Cancel | qt.QDialogButtonBox.Ok)
            formLayout.addRow(buttonBox)

            buttonBox.accepted.connect(dialog.accept)
            buttonBox.rejected.connect(dialog.reject)

            dialog.setLayout(formLayout)

            status = dialog.exec()

            if status == True:
                options = {}
                if filter_func == "gaussian" or filter_func == "winvar":
                    options["sigma"] = list(map(float, sigmaValues.text.split(",")))
                elif filter_func == "gabor":
                    self.truncateValuesCallback(sigmaValues, 0, self.minSide / 4.0)
                    options["sigma"] = list(map(float, sigmaValues.text.split(",")))
                    options["rotations"] = list(map(int, directionsQuantity.text.split(",")))
                    options["lambda"] = list(map(float, lambdaValues.text.split(",")))
                elif filter_func == "minkowsky":
                    options["threshold"] = list(map(float, thresholdValues.text.split(",")))
                    options["kernel_size"] = list(map(float, kernelSize.text.split(",")))
                else:
                    method = self.random_forest_methods.get(filter_func)
                    if method is not None:
                        options = method.get_options()

                self.customFilters[filter_func] = options

                string = []
                for keys in options.keys():
                    string.append(f"{keys}={options[keys]}")
                string = ",".join(string)

                optionsTable = qt.QTableWidgetItem(string)
                optionsTable.setTextAlignment(qt.Qt.AlignCenter)
                optionsTable.setFlags(qt.Qt.ItemIsEnabled)
                self.tableFilters.setItem(row, 1, optionsTable)
                self.tableFilters.setHorizontalHeaderLabels(["Features", "Options"])
                # self.tableFilters.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)
                self.tableFilters.horizontalHeader().setMinimumSectionSize(200)
                self.tableFilters.horizontalHeader().setStretchLastSection(qt.QHeaderView.Stretch)
                self.tableFilters.verticalHeader().hide()

        return status

    def truncateValuesCallback(self, lineeditValue, minValue, maxValue):
        def callback():
            if lineeditValue.text != "":
                sigmas = np.array(list(map(float, filter(None, lineeditValue.text.split(",")))))
                sigmas[sigmas > maxValue] = round(maxValue, 2)
                sigmas[sigmas < minValue] = round(minValue, 2)
                lineeditValue.setText(",".join(map(str, sigmas)))

        return callback

    def setImageInput(self, input):
        self.image_combo_box = input

    def delFilter(self):
        row = self.tableFilters.currentRow()
        filter_func = self.tableFilters.item(row, 0).text()
        self.tableFilters.removeRow(row)
        del self.customFilters[filter_func]

    def setPixelSizeAndMinSide(self, pixelSize, minSide):
        self.pixelSize = pixelSize
        self.minSide = minSide

    def getConvertedDict(self):
        customFilterConverted = copy.deepcopy(self.customFilters)
        for filter_func in self.customFilters.keys():
            if isinstance(self.customFilters[filter_func], dict):
                if "sigma" in self.customFilters[filter_func].keys():
                    sigma_px = list(
                        map(lambda x: np.ceil(float(x) / self.pixelSize), self.customFilters[filter_func]["sigma"])
                    )
                    customFilterConverted[filter_func]["sigma"] = sigma_px
                if "lambda" in self.customFilters[filter_func].keys():
                    lambda_px = list(
                        map(lambda x: np.ceil(float(x) / self.pixelSize), self.customFilters[filter_func]["lambda"])
                    )
                    customFilterConverted[filter_func]["lambda"] = lambda_px
                if "kernel_size" in self.customFilters[filter_func].keys():
                    if filter_func == "minkowsky":
                        kernel_size_px = list(
                            map(
                                lambda x: int(np.ceil(float(x) / self.pixelSize)),
                                self.customFilters[filter_func]["kernel_size"],
                            )
                        )
                        customFilterConverted[filter_func]["kernel_size"] = kernel_size_px
                    else:
                        kernel_size_px = math.ceil(
                            float(self.customFilters[filter_func]["kernel_size"][0]) / self.pixelSize
                        )
                        customFilterConverted[filter_func]["kernel_size"] = [kernel_size_px]
        return customFilterConverted

    def getValuesAsDict(self):
        customFilterConverted = self.getConvertedDict()
        return {
            "filters": customFilterConverted,
            "random_seed": self.seed_rng,
        }


class BayesianInferenceSettingsWidget(BaseSettingsWidget):
    METHOD = "bayesian-inference"
    DISPLAY_NAME = "Bayesian Inference"

    def __init__(self, parent=None, radiusInput=None, onSelect=None):
        super().__init__(parent)

        self.onSelect = onSelect or (lambda: None)
        self.input_image = None
        self.minSide = 9999999
        self.spacing = 1

        formLayout = qt.QFormLayout(self)

        v = qt.QRegExpValidator(qt.QRegExp("\d*(?:\.\d+)?(?:,\d*(?:\.\d+)?)*"), self)
        self.kernelSize = qt.QLineEdit()
        self.kernelSize.objectName = "Kernel Size Line Edit"
        self.kernelSize.editingFinished.connect(self.truncateValuesCallback(self.kernelSize))
        self.kernelSize.setValidator(v)
        self.kernelSize.setMinimumWidth(200)
        self.kernelSize.setToolTip("Size of the kernel used to calculate covariance matrix (pixels)")

        self.kernelType = qt.QComboBox()
        self.kernelType.objectName = "Kernel Type ComboBox"
        self.kernelType.addItem("Axes", "axes")
        self.kernelType.addItem("Planes", "planes")
        self.kernelType.addItem("Cubes", "cubes")
        self.kernelType.setToolTip(
            "Kernel type used (axes, planes or full cubes), in 2d images planes and cubes are the same"
        )

        self.unsafememoryCheckBox = qt.QCheckBox("Use unsafe memory optimization")
        self.unsafememoryCheckBox.objectName = "Unsafe Memory CheckBox"
        self.unsafememoryCheckBox.setChecked(1)
        self.unsafememoryCheckBox.setToolTip("Uncheck to use less memory with a small performance loss")

        boxLayout = qt.QHBoxLayout()
        text = qt.QLabel("Kernel size (mm):")
        text.setToolTip("Size of the kernel used to calculate covariance matrix (pixels)")
        boxLayout.addWidget(text)
        boxLayout.addWidget(self.kernelSize)
        self.pixel_label = PixelLabel(value_input=self.kernelSize, node_input=self.input_image)
        boxLayout.addWidget(self.pixel_label)
        formLayout.addRow(boxLayout)

        text = qt.QLabel("Kernel type:")
        text.setToolTip("Kernel type used (axes, planes or full cubes), in 2d images planes and cubes are the same")
        formLayout.addRow(text, self.kernelType)
        formLayout.addRow(self.unsafememoryCheckBox)

    def truncateValuesCallback(self, lineeditValue):
        def callback():
            minValue = self.spacing
            maxValue = self.minSide / 4.0
            if lineeditValue.text != "":
                if float(lineeditValue.text) > maxValue:
                    lineeditValue.setText(round(maxValue, 2))
                elif float(lineeditValue.text) < minValue:
                    lineeditValue.setText(round(minValue, 2))

        return callback

    def setPixelSizeAndMinSide(self, spacing, minSide):
        self.spacing = spacing
        self.minSide = minSide

    def setImageInput(self, input):
        self.image_input = input

        if self.pixel_label:
            self.pixel_label.connect_node_input(self.image_input)

    def getValuesAsDict(self):
        if not self.kernelSize.text:
            raise ValueError("Kernel size must be filled")

        kernel_size_px = math.ceil(float(self.kernelSize.text) / self.spacing)
        return {
            "method": self.METHOD,
            "kernel": kernel_size_px,
            "stride": int(np.ceil(kernel_size_px / 2)),
            "kernel_type": self.kernelType.currentData,
            "unsafe_memory_opt": self.unsafememoryCheckBox.isChecked(),
        }
