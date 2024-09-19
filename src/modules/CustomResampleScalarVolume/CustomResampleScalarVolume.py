import os
import qt, ctk, slicer, vtk
from ltrace.slicer_utils import *
import logging
from collections import namedtuple
from pathlib import Path
from dataclasses import dataclass
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.units import SLICER_LENGTH_UNIT
from ltrace.slicer import helpers as lsh
from functools import partial
import json


try:
    from Test.CustomResampleScalarVolumeTest import CustomResampleScalarVolumeTest
except ImportError:
    CustomResampleScalarVolumeTest = None  # tests not deployed to final version or closed source

ResampleScalarVolumeData = namedtuple(
    "ResampleScalarVolumeData", ["input", "outputSuffix", "x", "y", "z", "interpolationType"]
)
MAX_ASPECT_RATIO = 10


@dataclass
class DimensionData:
    slider: ctk.ctkSliderWidget
    voxelSizeLabel: qt.QLabel
    spinBox: qt.QDoubleSpinBox
    aspectRatio: int = 1
    defaultSpacing: int = 0


class CustomResampleScalarVolume(LTracePlugin):
    """Module to use Slicer's Resample Scalar Volume CLI algorithm."""

    SETTING_KEY = "Resample Scalar Volume Data"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "LTrace Resample Scalar Volume"
        self.parent.categories = ["LTrace Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = CustomResampleScalarVolume.help()
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = ""

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CustomResampleScalarVolumeWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = CustomResampleScalarVolumeLogic(progressBar=self.progressBar)

        parametersCollapsibleButton = self.__inputWidgetSetup()
        parametersCollapsibleButton = self.__parametersWidgetSetup()
        outputCollapsibleButton = self.__outputWidgetSetup()

        # Resample Button
        self.__resampleButton = qt.QPushButton("Resample")
        self.__resampleButton.objectName = "resampleButton"
        self.__resampleButton.toolTip = "Run the algorithm."
        self.__resampleButton.enabled = False

        self.layout.addWidget(parametersCollapsibleButton)
        self.layout.addWidget(outputCollapsibleButton)
        self.layout.addWidget(self.__resampleButton)
        self.layout.addWidget(self.progressBar)
        self.layout.addStretch(1)

        # connections
        self.__resampleButton.connect("clicked(bool)", self.__onResampleButtonClicked)
        self.__inputSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.__onNodeSelectionChanged)
        self.__lockAspectRatioCheckBox.stateChanged.connect(self.__onLockAspectRatioStateChanged)
        self.__resetAspectRatioButton.clicked.connect(self.__resetAspectValues)
        self.__xAspectRatioSlider.valueIsChanging.connect(
            lambda value: self.__onSliderChanging(self.__xAspectRatioSlider, value)
        )
        self.__xAspectRatioSlider.valueChanged.connect(
            lambda value: self.__onSliderChanged(self.__xAspectRatioSlider, value)
        )
        self.__yAspectRatioSlider.valueIsChanging.connect(
            lambda value: self.__onSliderChanging(self.__yAspectRatioSlider, value)
        )
        self.__yAspectRatioSlider.valueChanged.connect(
            lambda value: self.__onSliderChanged(self.__yAspectRatioSlider, value)
        )
        self.__zAspectRatioSlider.valueIsChanging.connect(
            lambda value: self.__onSliderChanging(self.__zAspectRatioSlider, value)
        )
        self.__zAspectRatioSlider.valueChanged.connect(
            lambda value: self.__onSliderChanged(self.__zAspectRatioSlider, value)
        )
        self.__xValueSpinBox.valueChanged.connect(lambda value: self.__onSpinBoxChanged(self.__xValueSpinBox, value))
        self.__yValueSpinBox.valueChanged.connect(lambda value: self.__onSpinBoxChanged(self.__yValueSpinBox, value))
        self.__zValueSpinBox.valueChanged.connect(lambda value: self.__onSpinBoxChanged(self.__zValueSpinBox, value))
        self.registered_callbacks = list()

        # Applies startup rules
        self.__onNodeSelectionChanged()

    def __inputWidgetSetup(self):
        inputsCollapsibleButton = ctk.ctkCollapsibleButton()
        inputsCollapsibleButton.text = "Input"
        self.layout.addWidget(inputsCollapsibleButton)

        # Layout within the dummy collapsible button
        inputsFormLayout = qt.QFormLayout(inputsCollapsibleButton)
        inputsFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        # input volume selector
        self.__inputSelector = slicer.qMRMLNodeComboBox()
        self.__inputSelector.setObjectName("inputSelector")
        self.__inputSelector.nodeTypes = ["vtkMRMLScalarVolumeNode", "vtkMRMLLabelMapVolumeNode"]
        self.__inputSelector.addEnabled = False
        self.__inputSelector.removeEnabled = False
        self.__inputSelector.noneEnabled = False
        self.__inputSelector.showHidden = False
        self.__inputSelector.showChildNodeTypes = False
        self.__inputSelector.setMRMLScene(slicer.mrmlScene)
        self.__inputSelector.setToolTip("Pick the input to the algorithm.")

        inputsFormLayout.addRow("Input Volume: ", self.__inputSelector)

        return inputsFormLayout

    def __parametersWidgetSetup(self):
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Parameters"
        self.layout.addWidget(parametersCollapsibleButton)

        # Layout within the dummy collapsible button
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        # Inteporlation Type combo box
        if False:
            interpolations = [
                "Linear",
                "Nearest Neighbor",
                "Bspline",
                "Haing",
                "Cosine",
                "Welch",
                "Lanczos",
                "Blackman",
            ]

        self.__interpolationTypeComboBox = qt.QComboBox()
        self.__interpolationTypeComboBox.setObjectName("interpolationTypeComboBox")
        self.__interpolationTypeComboBox.setCurrentIndex(0)

        # Lock Aspect ratio checkbox
        self.__lockAspectRatioCheckBox = qt.QCheckBox()
        self.__lockAspectRatioCheckBox.setObjectName("lockAspectRatioCheckBox")
        self.__lockAspectRatioCheckBox.setChecked(True)

        # Reset aspect ratio button
        self.__resetAspectRatioButton = qt.QPushButton()
        self.__resetAspectRatioButton.text = "Reset"

        optionsLayout = qt.QHBoxLayout()
        optionsLayout.addWidget(qt.QLabel("Lock Aspect Ratio"))
        optionsLayout.addWidget(self.__lockAspectRatioCheckBox)
        optionsLayout.addStretch()
        optionsLayout.addWidget(self.__resetAspectRatioButton)

        # X
        self.__xValueSpinBox = qt.QDoubleSpinBox()
        self.__xValueSpinBox.setObjectName("xValueSpinBox")
        self.__xValueSpinBox.setRange(0, 999999999)
        self.__xValueSpinBox.setValue(0)
        self.__xValueSpinBox.setSuffix(f" {SLICER_LENGTH_UNIT:~P}")
        self.__xValueSpinBox.setKeyboardTracking(False)
        self.__xValueSpinBox.setFixedWidth(100)
        self.__xValueSpinBox.setDecimals(5)

        self.__xVoxelSizeLabel = qt.QLabel("")
        self.__xVoxelSizeLabel.setFixedWidth(70)

        self.__xAspectRatioSlider = ctk.ctkSliderWidget()
        self.__xAspectRatioSlider.tracking = False
        self.__xAspectRatioSlider.singleStep = 0.01
        self.__xAspectRatioSlider.minimum = 0.03
        self.__xAspectRatioSlider.maximum = MAX_ASPECT_RATIO
        self.__xAspectRatioSlider.value = 1
        self.__xAspectRatioSlider.setToolTip("Set the aspect ratio for X value.")

        xLayout = qt.QHBoxLayout()
        xLayout.setSizeConstraint(qt.QLayout.SetFixedSize)
        xLayout.addWidget(qt.QLabel("X:"))
        xLayout.addWidget(self.__xValueSpinBox)
        xLayout.addWidget(self.__xVoxelSizeLabel)
        xLayout.addWidget(qt.QLabel("Ratio:"))
        xLayout.addWidget(self.__xAspectRatioSlider)

        # Y
        self.__yValueSpinBox = qt.QDoubleSpinBox()
        self.__yValueSpinBox.setObjectName("yValueSpinBox")
        self.__yValueSpinBox.setRange(0, 999999999)
        self.__yValueSpinBox.setValue(0)
        self.__yValueSpinBox.setSuffix(f" {SLICER_LENGTH_UNIT:~P}")
        self.__yValueSpinBox.setKeyboardTracking(False)
        self.__yValueSpinBox.setFixedWidth(100)
        self.__yValueSpinBox.setDecimals(5)

        self.__yVoxelSizeLabel = qt.QLabel("")
        self.__yVoxelSizeLabel.setFixedWidth(70)

        self.__yAspectRatioSlider = ctk.ctkSliderWidget()
        self.__yAspectRatioSlider.tracking = False
        self.__yAspectRatioSlider.singleStep = 0.01
        self.__yAspectRatioSlider.minimum = 0.03
        self.__yAspectRatioSlider.maximum = MAX_ASPECT_RATIO
        self.__yAspectRatioSlider.value = 1
        self.__yAspectRatioSlider.setToolTip("Set the aspect ratio for Y value.")

        yLayout = qt.QHBoxLayout()
        yLayout.addWidget(qt.QLabel("Y:"))
        yLayout.addWidget(self.__yValueSpinBox)
        yLayout.addWidget(self.__yVoxelSizeLabel)
        yLayout.addWidget(qt.QLabel("Ratio:"))
        yLayout.addWidget(self.__yAspectRatioSlider)

        # Z
        self.__zValueSpinBox = qt.QDoubleSpinBox()
        self.__zValueSpinBox.setObjectName("zValueSpinBox")
        self.__zValueSpinBox.setRange(0, 999999999)
        self.__zValueSpinBox.setValue(0)
        self.__zValueSpinBox.setSuffix(f" {SLICER_LENGTH_UNIT:~P}")
        self.__zValueSpinBox.setKeyboardTracking(False)
        self.__zValueSpinBox.setFixedWidth(100)
        self.__zValueSpinBox.setDecimals(5)

        self.__zVoxelSizeLabel = qt.QLabel("")
        self.__zVoxelSizeLabel.setFixedWidth(70)

        self.__zAspectRatioSlider = ctk.ctkSliderWidget()
        self.__zAspectRatioSlider.tracking = False
        self.__zAspectRatioSlider.singleStep = 0.01
        self.__zAspectRatioSlider.minimum = 0.03
        self.__zAspectRatioSlider.maximum = MAX_ASPECT_RATIO
        self.__zAspectRatioSlider.value = 1
        self.__zAspectRatioSlider.setToolTip("Set the aspect ratio for Z value.")

        zLayout = qt.QHBoxLayout()
        zLayout.addWidget(qt.QLabel("Z:"))
        zLayout.addWidget(self.__zValueSpinBox)
        zLayout.addWidget(self.__zVoxelSizeLabel)
        zLayout.addWidget(qt.QLabel("Ratio:"))
        zLayout.addWidget(self.__zAspectRatioSlider)

        self.__dimensionWidgetsData = [
            DimensionData(
                slider=self.__xAspectRatioSlider, voxelSizeLabel=self.__xVoxelSizeLabel, spinBox=self.__xValueSpinBox
            ),
            DimensionData(
                slider=self.__yAspectRatioSlider, voxelSizeLabel=self.__yVoxelSizeLabel, spinBox=self.__yValueSpinBox
            ),
            DimensionData(
                slider=self.__zAspectRatioSlider, voxelSizeLabel=self.__zVoxelSizeLabel, spinBox=self.__zValueSpinBox
            ),
        ]

        # Configure the layout
        parametersFormLayout.addRow("Interpolation", self.__interpolationTypeComboBox)
        parametersFormLayout.addRow(" ", qt.QWidget())
        parametersFormLayout.addRow(optionsLayout)
        parametersFormLayout.addRow(" ", qt.QWidget())
        parametersFormLayout.addRow(xLayout)
        parametersFormLayout.addRow(yLayout)
        parametersFormLayout.addRow(zLayout)

        return parametersCollapsibleButton

    def __outputWidgetSetup(self):
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.text = "Output"
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.__outputSuffixLineEdit = qt.QLineEdit("Resampled")
        self.__outputSuffixLineEdit.setObjectName("outputSuffixLineEdit")
        outputFormLayout.addRow("Output Suffix:", self.__outputSuffixLineEdit)

        return outputCollapsibleButton

    def cleanup(self):
        super().cleanup()
        for node, tag in self.registered_callbacks:
            node.RemoveObserver(tag)

    def __onNodeSelectionChanged(self):
        """Handles input/output node selection change event"""
        self.__registerCallbacks()
        self.__resetAspectValues()
        self.__resetInterpolations()

        isSelectionValid = self.__inputSelector.currentNode() is not None
        self.__interpolationTypeComboBox.enabled = isSelectionValid
        self.__resampleButton.enabled = isSelectionValid
        self.__xAspectRatioSlider.enabled = isSelectionValid
        self.__yAspectRatioSlider.enabled = isSelectionValid
        self.__zAspectRatioSlider.enabled = isSelectionValid
        self.__xValueSpinBox.enabled = isSelectionValid
        self.__yValueSpinBox.enabled = isSelectionValid
        self.__zValueSpinBox.enabled = isSelectionValid

    def __registerCallbacks(self):
        for node, tag in self.registered_callbacks:
            node.RemoveObserver(tag)
        self.registered_callbacks.clear()

        node = self.__inputSelector.currentNode()
        if node is None:
            return
        tag = node.AddObserver(
            vtk.vtkCommand.ModifiedEvent,
            self.__resetAspectValues,
        )
        self.registered_callbacks.append((node, tag))

    def __resetInterpolations(self):
        node = self.__inputSelector.currentNode()
        if isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
            interpolations = ["Nearest Neighbor"]
        elif isinstance(node, slicer.vtkMRMLScalarVolumeNode):
            interpolations = ["Linear", "Nearest Neighbor", "Lanczos", "Bspline", "Mean"]
        else:
            interpolations = []
        self.__interpolationTypeComboBox.clear()
        self.__interpolationTypeComboBox.addItems(interpolations)

    def __onResampleButtonClicked(self):
        """Runs resample's algorithm"""
        outputVolumeSuffix = self.__outputSuffixLineEdit.text.strip()
        if outputVolumeSuffix == "":
            slicer.util.errorDisplay("Invalid output suffix. Please, insert a valid suffix.")
            return

        interpolationType = self.__interpolationTypeComboBox.currentText
        data = ResampleScalarVolumeData(
            input=self.__inputSelector.currentNode(),
            outputSuffix=outputVolumeSuffix,
            x=self.__xValueSpinBox.value,
            y=self.__yValueSpinBox.value,
            z=self.__zValueSpinBox.value,
            interpolationType=interpolationType,
        )
        self.logic.run(data)

    def __onSliderChanging(self, sliderWidget, value):
        """Handle slider's changing event.

        Args:
            sliderWidget (ctk.ctkSliderWidget): the related widget
            value (float): the current slider's value
        """
        if self.__inputSelector.currentNode() is None:
            return

        self.__blockWidgetSignals(True)
        ratioLocked = self.__lockAspectRatioCheckBox.isChecked()
        if ratioLocked:
            for dimensionData in self.__dimensionWidgetsData:
                slider = dimensionData.slider
                if slider != sliderWidget:
                    slider.value = value

        inputDims = self.__inputSelector.currentNode().GetImageData().GetDimensions()
        inputSpacing = self.__inputSelector.currentNode().GetSpacing()

        for (
            widgetData,
            inputSize,
            inputSpacing,
        ) in zip(self.__dimensionWidgetsData, inputDims, inputSpacing):
            currentDimensionData = self.__getDimensionDataByAttribute("slider", sliderWidget)
            # If unlocked, update only current axis widgets
            if not ratioLocked and currentDimensionData != widgetData:
                continue

            outputSpacing = widgetData.defaultSpacing * value
            # From ResampleScalarVolume.cxx
            voxelSize = int(inputSize * inputSpacing / outputSpacing + 0.5) if outputSpacing > 0 else inputSize
            widgetData.voxelSizeLabel.setText(f"{voxelSize} px")

        self.__blockWidgetSignals(False)

    def __handleValueChangedWithAspectLocked(self, currentDimensionData: DimensionData, value, sourceWidget):
        """Handles values changes when the aspect ratio is unlocked.

        Args:
            currentDimensionData (DimensionData): the related DimensionData's object
            value (float): the current value from the related widget's change
            sourceWidget (qt.QWidget): The related widget's object.
        """
        if currentDimensionData is None:
            return

        currentAspectRatio = 0
        if isinstance(sourceWidget, qt.QDoubleSpinBox):
            defaultValue = currentDimensionData.defaultSpacing
            currentAspectRatio = value / defaultValue

        elif isinstance(sourceWidget, ctk.ctkSliderWidget):
            currentAspectRatio = sourceWidget.value

        xNewValue = self.__dimensionWidgetsData[0].defaultSpacing * currentAspectRatio
        yNewValue = self.__dimensionWidgetsData[1].defaultSpacing * currentAspectRatio
        zNewValue = self.__dimensionWidgetsData[2].defaultSpacing * currentAspectRatio

        self.__xValueSpinBox.setValue(xNewValue)
        self.__yValueSpinBox.setValue(yNewValue)
        self.__zValueSpinBox.setValue(zNewValue)

        self.__xAspectRatioSlider.value = currentAspectRatio
        self.__yAspectRatioSlider.value = currentAspectRatio
        self.__zAspectRatioSlider.value = currentAspectRatio

    def __handleValueChangedWithoutAspectLocked(self, currentDimensionData: DimensionData, value, sourceWidget):
        """Handles values changes when the aspect ratio is locked.

        Args:
            currentDimensionData (DimensionData): the related DimensionData's object
            value (float): the current value from the related widget's change
            sourceWidget (qt.QWidget): The related widget's object.
        """
        if currentDimensionData is None:
            return

        currentAspectRatio = 0
        if isinstance(sourceWidget, qt.QDoubleSpinBox):
            defaultValue = currentDimensionData.defaultSpacing
            currentAspectRatio = value / defaultValue

        elif isinstance(sourceWidget, ctk.ctkSliderWidget):
            currentAspectRatio = sourceWidget.value
            self.__onSliderChanging(sourceWidget, value)

        newValue = currentDimensionData.defaultSpacing * currentAspectRatio
        currentDimensionData.spinBox.setValue(newValue)
        currentDimensionData.slider.value = currentAspectRatio

    def __blockWidgetSignals(self, mode):
        """(Un)Blocks widgets signals

        Args:
            mode (bool): True to block signals, False to unblock signals emit from the widget.
        """
        for dimensionData in self.__dimensionWidgetsData:
            slider = dimensionData.slider
            spinBox = dimensionData.spinBox

            slider.blockSignals(mode)
            spinBox.blockSignals(mode)

    def __onSliderChanged(self, sliderWidget, value):
        """Handle slider's changed event.

        Args:
            sliderWidget (ctk.ctkSliderWidget): the related widget
            value (float): the current slider's value
        """
        self.__blockWidgetSignals(True)

        dimensionData = self.__getDimensionDataByAttribute("slider", sliderWidget)
        if self.__lockAspectRatioCheckBox.isChecked():
            self.__handleValueChangedWithAspectLocked(
                currentDimensionData=dimensionData, value=value, sourceWidget=sliderWidget
            )
        else:
            self.__handleValueChangedWithoutAspectLocked(
                currentDimensionData=dimensionData, value=value, sourceWidget=sliderWidget
            )

        self.__blockWidgetSignals(False)

    def __onSpinBoxChanged(self, spinBoxWidget, value):
        """Handle spin box's changed event.

        Args:
            spinBoxWidget (qt.QDoubleSpinBox): the related widget
            value (float): the current widget's value
        """
        dimensionData = self.__getDimensionDataByAttribute("spinBox", spinBoxWidget)
        if self.__lockAspectRatioCheckBox.isChecked():
            self.__handleValueChangedWithAspectLocked(
                currentDimensionData=dimensionData, value=value, sourceWidget=spinBoxWidget
            )
        else:
            self.__handleValueChangedWithoutAspectLocked(
                currentDimensionData=dimensionData, value=value, sourceWidget=spinBoxWidget
            )

    def __getDimensionDataByAttribute(self, attribute, value):
        """Retrieve a DimensionData object from the DimensionData list which has the passed attribute with the passed value

        Args:
            attribute (str): The DimensionData attribute's name
            value (object): the expected value from the attribute

        Returns:
            DimensionData: the related DimensionData object
        """
        currentDimensionData = None
        for dimensionData in self.__dimensionWidgetsData:
            if hasattr(dimensionData, attribute) and getattr(dimensionData, attribute) == value:
                currentDimensionData = dimensionData
                break

        return currentDimensionData

    def __onLockAspectRatioStateChanged(self, state):
        """Handles the checkbox change event from the "Lock Aspect Ratio" widget

        Args:
            state (integer): the check state (0 is unchecked, otherwise is checked)
        """
        self.__resetAspectValues()

    def __resetAspectValues(self, *args):
        """Reset input's parameters to a default value"""
        self.__blockWidgetSignals(True)

        inputNode = self.__inputSelector.currentNode()
        self.__nodeSpacing = [0, 0, 0]

        self.__xValueSpinBox.maximum = 1
        self.__yValueSpinBox.maximum = 1
        self.__zValueSpinBox.maximum = 1

        if inputNode is not None:
            self.__nodeSpacing = inputNode.GetSpacing()
            self.__xValueSpinBox.maximum = self.__nodeSpacing[0] * MAX_ASPECT_RATIO
            self.__yValueSpinBox.maximum = self.__nodeSpacing[1] * MAX_ASPECT_RATIO
            self.__zValueSpinBox.maximum = self.__nodeSpacing[2] * MAX_ASPECT_RATIO

        self.__xValueSpinBox.value = self.__nodeSpacing[0]
        self.__yValueSpinBox.value = self.__nodeSpacing[1]
        self.__zValueSpinBox.value = self.__nodeSpacing[2]
        self.__dimensionWidgetsData[0].defaultSpacing = self.__nodeSpacing[0]
        self.__dimensionWidgetsData[1].defaultSpacing = self.__nodeSpacing[1]
        self.__dimensionWidgetsData[2].defaultSpacing = self.__nodeSpacing[2]

        self.__blockWidgetSignals(False)

        # Changing slider values will update voxel size labels
        self.__xAspectRatioSlider.value = 1
        self.__yAspectRatioSlider.value = 1
        self.__zAspectRatioSlider.value = 1


class CustomResampleScalarVolumeLogic(LTracePluginLogic):
    def __init__(self, progressBar):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar

    def run(self, data: ResampleScalarVolumeData, cli_wait=False):
        """
        Run the resample algorithm
        """
        inputVolume = data.input

        try:
            outputVolume = lsh.createTemporaryVolumeNode(
                inputVolume.__class__, name=f"{inputVolume.GetName()}_{data.outputSuffix}"
            )

            subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(inputVolume))
            subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(outputVolume), itemParent)

            if isinstance(outputVolume, slicer.vtkMRMLLabelMapVolumeNode):
                outputVolume.CreateDefaultDisplayNodes()
                outputVolume.CreateDefaultStorageNode()
                lsh.copyColorNode(
                    outputVolume, source_color_node=inputVolume.GetDisplayNode().GetColorNode(), copy_names=True
                )
            elif isinstance(outputVolume, slicer.vtkMRMLScalarVolumeNode):
                lsh.copy_display(inputVolume, outputVolume)

            logging.info("Processing started")

            interpolationType = data.interpolationType[0].lower() + data.interpolationType[1:].replace(" ", "")
            spacing = r"{},{},{}".format(data.x, data.y, data.z)

            if interpolationType != "mean":
                # This CLI is a 3D Slicer CLI, thats why we need to use a different CLI interface
                cliParams = {
                    "InputVolume": inputVolume.GetID(),
                    "OutputVolume": outputVolume.GetID(),
                    "outputPixelSpacing": spacing,
                }

                cliParams["interpolationType"] = interpolationType
                resampleModule = slicer.modules.resamplescalarvolume
            else:
                cliParams = {
                    "inputVolume": inputVolume.GetID(),
                    "outputVolume": outputVolume.GetID(),
                    "outputImageSpacing": spacing,
                    "volumeType": "scalar",
                }
                resampleModule = slicer.modules.meanresamplecli

            self.cliNode = slicer.cli.run(resampleModule, None, cliParams, wait_for_completion=cli_wait)
            self.progressBar.setCommandLineModuleNode(self.cliNode)
            self.cliNode.AddObserver("ModifiedEvent", partial(self.eventHandler, outputVolumeID=outputVolume.GetID()))

        except Exception as e:
            slicer.util.errorDisplay(f"Failed to run the resampling")
            logging.error(repr(e))
            lsh.removeTemporaryNodes(nodes=[outputVolume])

    def eventHandler(self, caller, event, outputVolumeID=None):
        if self.cliNode is None:
            return

        try:
            outputNode = lsh.tryGetNode(outputVolumeID)

            status = caller.GetStatusString()
            if status == "Completed":
                logging.info(status)
                lsh.makeTemporaryNodePermanent(outputNode, show=True)
            elif status == "Cancelled":
                logging.info(status)
                lsh.removeTemporaryNodes(nodes=[outputNode])

        except Exception as e:
            logging.error(f'Exception on Event Handler: {repr(e)} with status "{status}"')
            lsh.removeTemporaryNodes(nodes=[outputNode])
