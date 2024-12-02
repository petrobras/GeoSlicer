import logging
import os
from collections import namedtuple
from pathlib import Path

import ctk
import numpy as np
import qt
import slicer
import vtk
from scipy.ndimage import zoom

from ltrace.slicer.helpers import triggerNodeModified
from ltrace.slicer_utils import *
from ltrace.transforms import transformPoints
from ltrace.units import global_unit_registry as ureg
from ltrace.slicer.node_attributes import ImageLogDataSelectable
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar

try:
    from Test.QualityIndicatorTest import QualityIndicatorTest
except ImportError:
    QualityIndicatorTest = None


class QualityIndicator(LTracePlugin):
    SETTING_KEY = "QualityIndicator"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Quality Indicator"
        self.parent.categories = ["Tools", "ImageLog"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = QualityIndicator.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class QualityIndicatorWidget(LTracePluginWidget):
    WINDOW_SIZE = "windowSize"
    MINIMUM_WAVELENGTH = "minimumWavelength"
    MAXIMUM_WAVELENGTH = "maximumWavelength"
    MULTIPLICATION_FACTOR = "multiplicationFactor"
    SMOOTHSTEP_FACTOR = "smoothstepFactor"
    OUTPUT_AS_IMAGE = "outputAsImage"

    Parameters = namedtuple(
        "Parameters",
        [
            "inputVolume",
            "outputName",
            WINDOW_SIZE,
            MINIMUM_WAVELENGTH,
            MAXIMUM_WAVELENGTH,
            MULTIPLICATION_FACTOR,
            SMOOTHSTEP_FACTOR,
            OUTPUT_AS_IMAGE,
        ],
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def getWindowSize(self):
        return QualityIndicator.get_setting(self.WINDOW_SIZE, default="40")

    def getMinimumWavelength(self):
        return QualityIndicator.get_setting(self.MINIMUM_WAVELENGTH, default="4")

    def getMaximumWavelength(self):
        return QualityIndicator.get_setting(self.MAXIMUM_WAVELENGTH, default="100")

    def getMultiplicationFactor(self):
        return QualityIndicator.get_setting(self.MULTIPLICATION_FACTOR, default="1")

    def getSmoothstepFactor(self):
        return QualityIndicator.get_setting(self.SMOOTHSTEP_FACTOR, default="0.02")

    def getOutputAsImage(self):
        return QualityIndicator.get_setting(self.OUTPUT_AS_IMAGE, default=str(True))

    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = QualityIndicatorLogic(self.parent, self.progressBar)
        self.logic.processFinished.connect(lambda: self.updateApplyCancelButtonsEnablement(True))

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
        self.inputVolume.setToolTip("Select the input image to the algorithm.")
        self.inputVolume.currentNodeChanged.connect(self.onInputVolumeCurrentNodeChanged)
        self.inputVolume.objectName = "Transit Time Combo Box"
        inputFormLayout.addRow("Transit Time:", self.inputVolume)
        inputFormLayout.addRow(" ", None)

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.windowSizeDoubleSpinBox = qt.QDoubleSpinBox()
        self.windowSizeDoubleSpinBox.setRange(1, 100)
        self.windowSizeDoubleSpinBox.setDecimals(0)
        self.windowSizeDoubleSpinBox.setSingleStep(1)
        self.windowSizeDoubleSpinBox.setValue(float(self.getWindowSize()))
        self.windowSizeDoubleSpinBox.setToolTip("Size of the moving window in meters used to compute de indicator.")
        self.windowSizeDoubleSpinBox.objectName = "Window Size Spin Box"
        parametersFormLayout.addRow("Window size (m):", self.windowSizeDoubleSpinBox)

        self.minimumWavelengthDoubleSpinBox = qt.QDoubleSpinBox()
        self.minimumWavelengthDoubleSpinBox.setRange(1, 100)
        self.minimumWavelengthDoubleSpinBox.setDecimals(0)
        self.minimumWavelengthDoubleSpinBox.setSingleStep(1)
        self.minimumWavelengthDoubleSpinBox.setValue(float(self.getMinimumWavelength()))
        self.minimumWavelengthDoubleSpinBox.setToolTip("Minimum vertical wavelength of the spiraling effect in meters.")
        self.minimumWavelengthDoubleSpinBox.objectName = "Minimum Wavelength Spin Box"
        parametersFormLayout.addRow("Minimum wavelength (m):", self.minimumWavelengthDoubleSpinBox)

        self.maximumWavelengthDoubleSpinBox = qt.QDoubleSpinBox()
        self.maximumWavelengthDoubleSpinBox.setRange(1, 500)
        self.maximumWavelengthDoubleSpinBox.setDecimals(0)
        self.maximumWavelengthDoubleSpinBox.setSingleStep(1)
        self.maximumWavelengthDoubleSpinBox.setValue(float(self.getMaximumWavelength()))
        self.maximumWavelengthDoubleSpinBox.setToolTip("Maximum vertical wavelength of the spiraling effect in meters.")
        self.maximumWavelengthDoubleSpinBox.objectName = "Maximum Wavelength Spin Box"
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
        self.multiplicationFactorDoubleSpinBox.objectName = "Filtering Factor Spin Box"
        advancedSettingsFormLayout.addRow("Filtering factor:", self.multiplicationFactorDoubleSpinBox)

        self.smoothstepFactorDoubleSpinBox = qt.QDoubleSpinBox()
        self.smoothstepFactorDoubleSpinBox.setRange(0.001, 0.1)
        self.smoothstepFactorDoubleSpinBox.setDecimals(3)
        self.smoothstepFactorDoubleSpinBox.setSingleStep(0.001)
        self.smoothstepFactorDoubleSpinBox.setValue(float(self.getSmoothstepFactor()))
        self.smoothstepFactorDoubleSpinBox.setToolTip(
            "Step length of the filter spectrum band. Higher this values, more smooth the step of the band width."
        )
        self.smoothstepFactorDoubleSpinBox.objectName = "Band Spectrum Step Length Spin Box"
        advancedSettingsFormLayout.addRow("Band spectrum step length:", self.smoothstepFactorDoubleSpinBox)
        advancedSettingsFormLayout.addRow(" ", None)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.outputPrefixLineEdit = qt.QLineEdit()
        self.outputPrefixLineEdit.setToolTip("Set the output prefix.")
        self.outputPrefixLineEdit.objectName = "Output Prefix Line Edit"
        outputFormLayout.addRow("Output prefix:", self.outputPrefixLineEdit)

        self.outputAsImage = qt.QCheckBox("Output as image")
        self.outputAsImage.setChecked(self.getOutputAsImage() == "True")
        self.outputAsImage.setToolTip("Generate the output as an image, instead of a table.")
        self.outputAsImage.objectName = "Output As Image Check Box"
        outputFormLayout.addRow(self.outputAsImage)
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

    def updateApplyCancelButtonsEnablement(self, applyEnabled):
        self.applyButton.enabled = applyEnabled and self.inputVolume.currentNode() is not None
        self.cancelButton.enabled = not applyEnabled

    def onInputVolumeCurrentNodeChanged(self, node):
        if node is not None:
            self.outputPrefixLineEdit.setText(node.GetName())
        else:
            self.outputPrefixLineEdit.setText("")

        self.applyButton.enabled = node is not None

    def onApplyButtonClicked(self):
        try:
            if self.inputVolume.currentNode() is None:
                raise QualityIndicatorInfo("Input image is required.")
            if not self.outputPrefixLineEdit.text:
                raise QualityIndicatorInfo("Output image name prefix is required.")
            if self.minimumWavelengthDoubleSpinBox.value >= self.maximumWavelengthDoubleSpinBox.value:
                raise QualityIndicatorInfo("Maximum wavelength must be larger than minimum wavelength.")

            QualityIndicator.set_setting(self.WINDOW_SIZE, self.windowSizeDoubleSpinBox.value)
            QualityIndicator.set_setting(self.MINIMUM_WAVELENGTH, self.minimumWavelengthDoubleSpinBox.value)
            QualityIndicator.set_setting(self.MAXIMUM_WAVELENGTH, self.maximumWavelengthDoubleSpinBox.value)
            QualityIndicator.set_setting(self.MULTIPLICATION_FACTOR, self.multiplicationFactorDoubleSpinBox.value)
            QualityIndicator.set_setting(self.SMOOTHSTEP_FACTOR, self.smoothstepFactorDoubleSpinBox.value)
            QualityIndicator.set_setting(self.OUTPUT_AS_IMAGE, str(self.outputAsImage.isChecked()))

            parameters = self.Parameters(
                self.inputVolume.currentNode(),
                slicer.mrmlScene.GenerateUniqueName(self.outputPrefixLineEdit.text + "_Quality"),
                self.windowSizeDoubleSpinBox.value * ureg.meter,
                self.minimumWavelengthDoubleSpinBox.value * ureg.meter,
                self.maximumWavelengthDoubleSpinBox.value * ureg.meter,
                self.multiplicationFactorDoubleSpinBox.value,
                self.smoothstepFactorDoubleSpinBox.value,
                self.outputAsImage.isChecked(),
            )

            self.logic.process(parameters)
            self.updateApplyCancelButtonsEnablement(False)
        except QualityIndicatorInfo as e:
            slicer.util.infoDisplay(str(e))
            return

    def onCancelButtonClicked(self):
        self.logic.cancel()


class QualityIndicatorLogic(LTracePluginLogic):
    processFinished = qt.Signal()

    def __init__(self, parent, progressBar):
        LTracePluginLogic.__init__(self, parent)
        self.cliNode = None
        self.progressBar = progressBar

    def process(self, p):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        self.inputVolumeItemParent = subjectHierarchyNode.GetItemParent(
            subjectHierarchyNode.GetItemByDataNode(p.inputVolume)
        )

        self.outputVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", p.outputName)
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(self.outputVolumeNode), self.inputVolumeItemParent
        )

        p.inputVolume.CreateDefaultDisplayNodes()
        self.outputVolumeNode.CreateDefaultDisplayNodes()
        inputVolumeDisplayNode = p.inputVolume.GetDisplayNode()
        outputVolumeDisplayNode = self.outputVolumeNode.GetDisplayNode()
        outputVolumeDisplayNode.SetAndObserveColorNodeID(inputVolumeDisplayNode.GetColorNodeID())
        outputVolumeDisplayNode.AutoWindowLevelOff()
        outputVolumeDisplayNode.SetWindowLevelMinMax(0, 1)

        nullValue = p.inputVolume.GetAttribute("NullValue")
        self.outputVolumeNode.SetAttribute("NullValue", nullValue)

        self.outputVolumeNode.HideFromEditorsOn()
        triggerNodeModified(self.outputVolumeNode)

        self.outputAsImage = p.outputAsImage

        cliParams = {
            "inputVolume1": p.inputVolume.GetID(),
            "outputVolume_std": self.outputVolumeNode.GetID(),
            "window_size": p.windowSize.m,
            "wlength_max": p.maximumWavelength.m,
            "wlength_min": p.minimumWavelength.m,
            "nullable": nullValue,
            "multip_factor": p.multiplicationFactor,
            "smoothstep_factor": p.smoothstepFactor,
        }

        self.cliNode = slicer.cli.run(slicer.modules.qualityindicatorcli, None, cliParams)
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.processCallback)

    def processCallback(self, caller, event):
        if caller is None:
            self.cliNode = None
            return
        if self.cliNode is None:
            return
        status = caller.GetStatusString()
        if "Completed" in status or status == "Cancelled":
            logging.info(status)
            if status == "Completed":
                if self.outputAsImage:
                    self.outputVolumeNode.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
                    self.outputVolumeNode.HideFromEditorsOff()
                    triggerNodeModified(self.outputVolumeNode)
                else:
                    array = slicer.util.arrayFromVolume(self.outputVolumeNode)

                    qualities = array[:, 0, 0]
                    ijkDepths = [[0, 0, k] for k in range(len(array))]

                    try:
                        nullValue = float(self.outputVolumeNode.GetAttribute("NullValue"))
                        indexes = np.where(qualities == nullValue)
                        qualities = np.delete(qualities, indexes)
                        ijkDepths = np.delete(ijkDepths, indexes, axis=0)
                    except:
                        pass  # if there is not such attribute, or it could not be converted to float

                    matrix = vtk.vtkMatrix4x4()
                    self.outputVolumeNode.GetIJKToRASMatrix(matrix)
                    rasDepths = transformPoints(matrix, ijkDepths)[:, 2][::-1] * -1

                    table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
                    table.SetName(self.outputVolumeNode.GetName())
                    table.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)

                    # Reducing the number of data points to 1/10
                    shrinkFactor = 0.1
                    reducedRasDepths = zoom(rasDepths, shrinkFactor)
                    if reducedRasDepths[0] > reducedRasDepths[-1]:
                        reducedRasDepths = np.flip(reducedRasDepths)
                    reducedQualities = zoom(qualities, shrinkFactor)

                    tableArray = [reducedRasDepths, reducedQualities]

                    slicer.util.updateTableFromArray(table, tableArray)

                    table.RenameColumn(0, "DEPTH")
                    table.RenameColumn(1, "QUALITY")

                    subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
                    subjectHierarchyNode.SetItemParent(
                        subjectHierarchyNode.GetItemByDataNode(table), self.inputVolumeItemParent
                    )
                    slicer.mrmlScene.RemoveNode(self.outputVolumeNode)
            elif status == "Cancelled":
                slicer.mrmlScene.RemoveNode(self.outputVolumeNode)
                slicer.util.infoDisplay("Processing cancelled.")
            else:
                slicer.mrmlScene.RemoveNode(self.outputVolumeNode)
                slicer.util.errorDisplay("Processing failed.")

        if not self.cliNode.IsBusy():
            self.cliNode = None
            self.processFinished.emit()

    def cancel(self):
        if self.cliNode is None:
            return
        self.cliNode.Cancel()


class QualityIndicatorInfo(RuntimeError):
    pass
