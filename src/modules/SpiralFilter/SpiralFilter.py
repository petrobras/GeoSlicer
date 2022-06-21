import logging
import os
from collections import namedtuple
from pathlib import Path

import ctk
import qt
import slicer

from ltrace.slicer.node_attributes import ImageLogDataSelectable
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer import helpers
from ltrace.slicer_utils import *
from ltrace.units import global_unit_registry as ureg

# Checks if closed source code is available
try:
    from Test.SpiralTest import SpiralTest
except ImportError:
    SpiralTest = None  # tests not deployed to final version or closed source


class SpiralFilter(LTracePlugin):
    SETTING_KEY = "SpiralFilter"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Spiral Filter"
        self.parent.categories = ["LTrace Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = SpiralFilter.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class SpiralFilterWidget(LTracePluginWidget):
    MINIMUM_WAVELENGTH = "minimumWavelength"
    MAXIMUM_WAVELENGTH = "maximumWavelength"
    MULTIPLICATION_FACTOR = "multiplicationFactor"
    SMOOTHSTEP_FACTOR = "smoothstepFactor"

    FilterParameters = namedtuple(
        "FilterParameters",
        [
            "inputVolume",
            "outputVolumeName",
            MINIMUM_WAVELENGTH,
            MAXIMUM_WAVELENGTH,
            MULTIPLICATION_FACTOR,
            SMOOTHSTEP_FACTOR,
        ],
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def getMinimumWavelength(self):
        return SpiralFilter.get_setting(self.MINIMUM_WAVELENGTH, default="4")

    def getMaximumWavelength(self):
        return SpiralFilter.get_setting(self.MAXIMUM_WAVELENGTH, default="100")

    def getMultiplicationFactor(self):
        return SpiralFilter.get_setting(self.MULTIPLICATION_FACTOR, default="1")

    def getSmoothstepFactor(self):
        return SpiralFilter.get_setting(self.SMOOTHSTEP_FACTOR, default="0.02")

    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = SpiralFilterLogic(self.progressBar)
        self.logic.filterFinished.connect(lambda: self.updateApplyCancelButtonsEnablement(True))

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

        self.inputVolume = slicer.qMRMLNodeComboBox()
        self.inputVolume.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.inputVolume.selectNodeUponCreation = True
        self.inputVolume.addEnabled = False
        self.inputVolume.removeEnabled = False
        self.inputVolume.noneEnabled = True
        self.inputVolume.showHidden = False
        self.inputVolume.showChildNodeTypes = False
        self.inputVolume.setMRMLScene(slicer.mrmlScene)
        self.inputVolume.setToolTip("Select the image input to the algorithm.")
        self.inputVolume.currentNodeChanged.connect(self.onInputVolumeCurrentNodeChanged)
        self.inputVolume.objectName = "Image Input"
        inputFormLayout.addRow("Image:", self.inputVolume)
        inputFormLayout.addRow(" ", None)

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.minimumWavelengthDoubleSpinBox = qt.QDoubleSpinBox()
        self.minimumWavelengthDoubleSpinBox.setRange(1, 100)
        self.minimumWavelengthDoubleSpinBox.setDecimals(0)
        self.minimumWavelengthDoubleSpinBox.setSingleStep(1)
        self.minimumWavelengthDoubleSpinBox.setValue(float(self.getMinimumWavelength()))
        self.minimumWavelengthDoubleSpinBox.setToolTip("Minimum vertical wavelength of the spiraling effect in meters.")
        self.minimumWavelengthDoubleSpinBox.objectName = "Minimum Wave Length Input"
        parametersFormLayout.addRow("Minimum wavelength (m):", self.minimumWavelengthDoubleSpinBox)

        self.maximumWavelengthDoubleSpinBox = qt.QDoubleSpinBox()
        self.maximumWavelengthDoubleSpinBox.setRange(1, 500)
        self.maximumWavelengthDoubleSpinBox.setDecimals(0)
        self.maximumWavelengthDoubleSpinBox.setSingleStep(1)
        self.maximumWavelengthDoubleSpinBox.setValue(float(self.getMaximumWavelength()))
        self.maximumWavelengthDoubleSpinBox.setToolTip("Maximum vertical wavelength of the spiraling effect in meters.")
        self.maximumWavelengthDoubleSpinBox.objectName = "Maximum Wave Length Input"
        parametersFormLayout.addRow("Maximum wavelength (m):", self.maximumWavelengthDoubleSpinBox)
        parametersFormLayout.addRow(" ", None)

        advancedSettingsCollapsibleButton = ctk.ctkCollapsibleButton()
        advancedSettingsCollapsibleButton.flat = True
        advancedSettingsCollapsibleButton.text = "Advanced Settings"
        advancedSettingsCollapsibleButton.collapsed = True
        parametersFormLayout.addRow(advancedSettingsCollapsibleButton)

        # Layout within the dummy collapsible button
        advancedSettingsFormLayout = qt.QFormLayout(advancedSettingsCollapsibleButton)

        self.multiplicationFactorDoubleSpinBox = qt.QDoubleSpinBox()
        self.multiplicationFactorDoubleSpinBox.setRange(0, 1)
        self.multiplicationFactorDoubleSpinBox.setDecimals(2)
        self.multiplicationFactorDoubleSpinBox.setSingleStep(0.01)
        self.multiplicationFactorDoubleSpinBox.setValue(float(self.getMultiplicationFactor()))
        self.multiplicationFactorDoubleSpinBox.setToolTip(
            "Multiplicative factor of the filter. 0 leads to  no filtering at all. 1 leads to the maximum filtering."
        )
        self.multiplicationFactorDoubleSpinBox.objectName = "Filtering Factor Input"
        advancedSettingsFormLayout.addRow("Filtering factor:", self.multiplicationFactorDoubleSpinBox)

        self.smoothstepFactorDoubleSpinBox = qt.QDoubleSpinBox()
        self.smoothstepFactorDoubleSpinBox.setRange(0.001, 0.1)
        self.smoothstepFactorDoubleSpinBox.setDecimals(3)
        self.smoothstepFactorDoubleSpinBox.setSingleStep(0.001)
        self.smoothstepFactorDoubleSpinBox.setValue(float(self.getSmoothstepFactor()))
        self.smoothstepFactorDoubleSpinBox.setToolTip(
            "Step length of the filter spectrum band. Higher this values, more smooth the step of the band width."
        )
        self.smoothstepFactorDoubleSpinBox.objectName = "Band Spectrum Step Length Input"
        advancedSettingsFormLayout.addRow("Band spectrum step length:", self.smoothstepFactorDoubleSpinBox)
        advancedSettingsFormLayout.addRow(" ", None)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.outputVolumePrefixLineEdit = qt.QLineEdit()
        self.outputVolumePrefixLineEdit.setToolTip("Set the output image prefix.")
        self.outputVolumePrefixLineEdit.textChanged.connect(self.onOutputPrefixTextChanged)
        self.outputVolumePrefixLineEdit.objectName = "Output Prefix Input"
        outputFormLayout.addRow("Output prefix:", self.outputVolumePrefixLineEdit)
        outputFormLayout.addRow(" ", None)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setFixedHeight(40)
        self.applyButton.clicked.connect(self.onApplyButtonClicked)
        self.applyButton.objectName = "Apply Button"
        self.applyButton.enabled = False

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)
        self.cancelButton.objectName = "Cancel Button"
        self.cancelButton.enabled = False

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.applyButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        formLayout.addRow(buttonsHBoxLayout)

        self.layout.addWidget(self.progressBar)

        self.layout.addStretch()

    def onOutputPrefixTextChanged(self, text: str) -> None:
        if text.replace(" ", "") != "":
            return

        self.updateOutputVolumePrefix(self.inputVolume.currentNode())

    def updateOutputVolumePrefix(self, node) -> None:
        if node is None:
            self.outputVolumePrefixLineEdit.setText("Spiral")
            return

        self.outputVolumePrefixLineEdit.setText(f"{node.GetName()}_Spiral")

    def onInputVolumeCurrentNodeChanged(self, node) -> None:
        self.updateOutputVolumePrefix(node)

        self.applyButton.enabled = node is not None

    def onApplyButtonClicked(self):
        try:
            if self.inputVolume.currentNode() is None:
                raise FilterInfo("Input image is required.")
            if not self.outputVolumePrefixLineEdit.text:
                raise FilterInfo("Output image name is required.")
            if self.minimumWavelengthDoubleSpinBox.value >= self.maximumWavelengthDoubleSpinBox.value:
                raise FilterInfo("Maximum wavelength must be larger than minimum wavelength.")

            SpiralFilter.set_setting(self.MINIMUM_WAVELENGTH, self.minimumWavelengthDoubleSpinBox.value)
            SpiralFilter.set_setting(self.MAXIMUM_WAVELENGTH, self.maximumWavelengthDoubleSpinBox.value)
            SpiralFilter.set_setting(self.MULTIPLICATION_FACTOR, self.multiplicationFactorDoubleSpinBox.value)
            SpiralFilter.set_setting(self.SMOOTHSTEP_FACTOR, self.smoothstepFactorDoubleSpinBox.value)

            filterParameters = self.FilterParameters(
                self.inputVolume.currentNode(),
                slicer.mrmlScene.GenerateUniqueName(self.outputVolumePrefixLineEdit.text + "_Output"),
                self.minimumWavelengthDoubleSpinBox.value * ureg.meter,
                self.maximumWavelengthDoubleSpinBox.value * ureg.meter,
                self.multiplicationFactorDoubleSpinBox.value,
                self.smoothstepFactorDoubleSpinBox.value,
            )

            self.logic.filter(filterParameters)
            self.updateApplyCancelButtonsEnablement(False)
        except FilterInfo as e:
            slicer.util.infoDisplay(str(e))
            return

    def onCancelButtonClicked(self):
        self.logic.cancel()

    def updateApplyCancelButtonsEnablement(self, applyEnabled):
        self.applyButton.enabled = applyEnabled and self.inputVolume.currentNode() is not None
        self.cancelButton.enabled = not applyEnabled


class SpiralFilterLogic(LTracePluginLogic):
    filterFinished = qt.Signal()

    def __init__(self, progressBar):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar
        self.outputVolumeNodeId = None

    def filter(self, p):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        inputVolumeItemParent = subjectHierarchyNode.GetItemParent(
            subjectHierarchyNode.GetItemByDataNode(p.inputVolume)
        )

        outputVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", p.outputVolumeName)
        self.outputVolumeNodeId = outputVolumeNode.GetID()
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(outputVolumeNode), inputVolumeItemParent
        )

        helpers.copy_display(p.inputVolume, outputVolumeNode)

        nullValue = p.inputVolume.GetAttribute("NullValue")
        outputVolumeNode.SetAttribute("NullValue", nullValue)

        cliParams = {
            "inputVolume1": p.inputVolume.GetID(),
            "outputVolume_std": outputVolumeNode.GetID(),
            "wlength_max": p.maximumWavelength.m,
            "wlength_min": p.minimumWavelength.m,
            "nullable": nullValue,
            "multip_factor": p.multiplicationFactor,
            "smoothstep_factor": p.smoothstepFactor,
        }

        self.cliNode = slicer.cli.run(slicer.modules.spiralfilteringcli, None, cliParams)
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.filterCallback)

    def filterCallback(self, caller, event):
        if self.cliNode is None:
            return

        if caller is None:
            del self.cliNode
            self.cliNode = None
            return

        status = caller.GetStatusString()
        outputVolumeNode = helpers.tryGetNode(self.outputVolumeNodeId)
        if "Completed" in status or status == "Cancelled":
            logging.debug(status)

            if status == "Cancelled":
                slicer.mrmlScene.RemoveNode(outputVolumeNode)
                slicer.util.infoDisplay("Filtering cancelled.")
            elif status != "Completed":
                slicer.mrmlScene.RemoveNode(outputVolumeNode)
                slicer.util.errorDisplay("Filtering failed.")

        outputVolumeNode.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)

        if not self.cliNode.IsBusy():
            self.outputVolumeNodeId = None
            del self.cliNode
            self.cliNode = None
            self.filterFinished.emit()

    def cancel(self):
        if self.cliNode is None:
            return
        self.cliNode.Cancel()


class FilterInfo(RuntimeError):
    pass
