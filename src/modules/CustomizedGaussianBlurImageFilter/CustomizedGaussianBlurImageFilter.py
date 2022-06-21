import datetime
import logging
import os
from collections import namedtuple
from pathlib import Path

import ctk
import qt
import slicer
from ltrace.slicer.helpers import copy_display
from ltrace.slicer_utils import *
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widgets import PixelLabel

# from slicer.ScriptedLoadableModule import *


class CustomizedGaussianBlurImageFilter(LTracePlugin):
    SETTING_KEY = "CustomizedGaussianBlurImageFilter"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Gaussian Blur Image Filter"
        self.parent.categories = ["LTrace Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = CustomizedGaussianBlurImageFilter.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CustomizedGaussianBlurImageFilterWidget(LTracePluginWidget):
    # Settings constants
    SIGMA = "sigma"
    OUTPUT_SUFFIX = "_GaussianBlur"

    FilteringParameters = namedtuple("FilteringParameters", ["inputVolume", SIGMA, "outputVolumeName"])

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def getSigma(self):
        return CustomizedGaussianBlurImageFilter.get_setting(self.SIGMA, default="0.001")

    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = CustomizedGaussianBlurImageFilterLogic(self.progressBar)

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

        self.inputVolumeComboBox = slicer.qMRMLNodeComboBox()
        self.inputVolumeComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.inputVolumeComboBox.selectNodeUponCreation = True
        self.inputVolumeComboBox.addEnabled = False
        self.inputVolumeComboBox.removeEnabled = False
        self.inputVolumeComboBox.noneEnabled = True
        self.inputVolumeComboBox.showHidden = False
        self.inputVolumeComboBox.showChildNodeTypes = False
        self.inputVolumeComboBox.setMRMLScene(slicer.mrmlScene)
        self.inputVolumeComboBox.setToolTip("Select the input image.")
        self.inputVolumeComboBox.currentNodeChanged.connect(self.onInputChanged)
        inputFormLayout.addRow("Input image:", self.inputVolumeComboBox)
        inputFormLayout.addRow(" ", None)

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.sigmaDoubleSpinBox = qt.QDoubleSpinBox()
        self.sigmaDoubleSpinBox.setDecimals(3)
        self.sigmaDoubleSpinBox.setSingleStep(0.001)
        self.sigmaDoubleSpinBox.setMinimum(0.001)
        self.sigmaDoubleSpinBox.setValue(float(self.getSigma()))
        self.sigmaDoubleSpinBox.toolTip = "Sigma value in physical units (e.g., mm) of the Gaussian kernel."

        sigmaBoxLayout = qt.QHBoxLayout()
        sigmaBoxLayout.addWidget(self.sigmaDoubleSpinBox)
        pixel_label = PixelLabel(value_input=self.sigmaDoubleSpinBox, node_input=self.inputVolumeComboBox)
        pixel_label.setSizePolicy(qt.QSizePolicy.Maximum, qt.QSizePolicy.Fixed)
        sigmaBoxLayout.addWidget(pixel_label)

        parametersFormLayout.addRow("Sigma (mm):", sigmaBoxLayout)
        parametersFormLayout.addRow(" ", None)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.outputVolumeNameLineEdit = qt.QLineEdit()
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
        try:
            inputVolume = self.inputVolumeComboBox.currentNode()
            if inputVolume is None:
                raise FilteringInfo("Input image is required.")
            if not self.sigmaDoubleSpinBox.text:
                raise FilteringInfo("Sigma is required.")
            if not self.outputVolumeNameLineEdit.text:
                raise FilteringInfo("Output image name is required.")

            inputVolumeArray = slicer.util.arrayFromVolume(inputVolume)
            if min(inputVolumeArray.shape) < 4:
                raise FilteringInfo(
                    "This filter requires a minimum of four pixels along the dimension of the input image to be processed."
                )

            CustomizedGaussianBlurImageFilter.set_setting(self.SIGMA, self.sigmaDoubleSpinBox.text)
            filteringParameters = self.FilteringParameters(
                self.inputVolumeComboBox.currentNode(),
                self.sigmaDoubleSpinBox.text,
                self.outputVolumeNameLineEdit.text,
            )
            self.logic.apply(filteringParameters)
        except FilteringInfo as e:
            slicer.util.infoDisplay(str(e))
            return

    def onCancelButtonClicked(self):
        self.logic.cancel()

    def onInputChanged(self, inputNode):
        newOutputName = inputNode.GetName() + self.OUTPUT_SUFFIX if inputNode != None else ""
        self.outputVolumeNameLineEdit.setText(newOutputName)


class CustomizedGaussianBlurImageFilterLogic(LTracePluginLogic):
    def __init__(self, progressBar):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar

    def apply(self, p):
        # Removing old cli node if it exists
        slicer.mrmlScene.RemoveNode(self.cliNode)

        print("Filtering start time: " + str(datetime.datetime.now()))

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        inputVolumeItemParent = subjectHierarchyNode.GetItemParent(
            subjectHierarchyNode.GetItemByDataNode(p.inputVolume)
        )

        # Output volume
        self.outputVolume = slicer.mrmlScene.AddNewNodeByClass(p.inputVolume.GetClassName())
        self.outputVolume.SetName(p.outputVolumeName)
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(self.outputVolume), inputVolumeItemParent
        )

        cliParams = {
            "inputVolume": p.inputVolume.GetID(),
            "outputVolume": self.outputVolume.GetID(),
            "sigma": p.sigma,
        }

        self.inputVolume = p.inputVolume
        self.cliNode = slicer.cli.run(slicer.modules.gaussianblurimagefilter, None, cliParams)
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
                print("Filtering end time: " + str(datetime.datetime.now()))
            elif status == "Cancelled":
                slicer.mrmlScene.RemoveNode(self.outputVolume)
            else:
                slicer.mrmlScene.RemoveNode(self.outputVolume)
                slicer.util.errorDisplay("Filtering failed.")

    def cancel(self):
        if self.cliNode is None:
            return  # nothing running, nothing to do
        self.cliNode.Cancel()


class FilteringInfo(RuntimeError):
    pass
