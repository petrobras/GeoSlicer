import datetime
import logging
import os
from collections import namedtuple
from pathlib import Path

import ctk
import qt
import slicer
from ltrace.slicer.helpers import copy_display
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer_utils import *


class CustomizedCurvatureAnisotropicDiffusion(LTracePlugin):
    SETTING_KEY = "CustomizedCurvatureAnisotropicDiffusion"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Curvature Anisotropic Diffusion"
        self.parent.categories = ["Tools", "MicroCT", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.setHelpUrl("Volumes/Filter/GradientAnisotropicDiffusion/GradientAnisotropicDiffusion.html")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CustomizedCurvatureAnisotropicDiffusionWidget(LTracePluginWidget):
    # Settings constants
    CONDUCTANCE = "conductance"
    ITERATIONS = "iterations"
    TIME_STEP = "timeStep"
    OUTPUT_SUFFIX = "_CurvDiffusion"

    FilteringParameters = namedtuple(
        "FilteringParameters", ["inputVolume", CONDUCTANCE, ITERATIONS, TIME_STEP, "outputVolumeName"]
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def getConductance(self):
        return CustomizedCurvatureAnisotropicDiffusion.get_setting(self.CONDUCTANCE, default="1")

    def getIterations(self):
        return CustomizedCurvatureAnisotropicDiffusion.get_setting(self.ITERATIONS, default="5")

    def getTimeStep(self):
        return CustomizedCurvatureAnisotropicDiffusion.get_setting(self.TIME_STEP, default="0.0625")

    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = CustomizedCurvatureAnisotropicDiffusionLogic(self.progressBar)

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

        self.conductanceSliderWidget = slicer.qMRMLSliderWidget()
        self.conductanceSliderWidget.maximum = 10
        self.conductanceSliderWidget.minimum = 0
        self.conductanceSliderWidget.decimals = 2
        self.conductanceSliderWidget.singleStep = 0.01
        self.conductanceSliderWidget.value = float(self.getConductance())
        self.conductanceSliderWidget.toolTip = """\
            Conductance controls the sensitivity of the conductance term. As a general rule, the lower the value, the more strongly the \
            filter preserves edges. A high value will cause diffusion (smoothing) across edges. Note that the number of iterations controls \
            how much smoothing is done within regions bounded by edges.\
        """
        parametersFormLayout.addRow("Conductance:", self.conductanceSliderWidget)

        self.iterationsSliderWidget = slicer.qMRMLSliderWidget()
        self.iterationsSliderWidget.maximum = 30
        self.iterationsSliderWidget.minimum = 1
        self.iterationsSliderWidget.decimals = 0
        self.iterationsSliderWidget.singleStep = 1
        self.iterationsSliderWidget.value = int(self.getIterations())
        self.iterationsSliderWidget.toolTip = """\
            The more iterations, the more smoothing. Each iteration takes the same amount of time. If it takes 10 seconds for one iteration, \
            then it will take 100 seconds for 10 iterations. Note that the conductance controls how much each iteration smooths across edges.\
        """
        parametersFormLayout.addRow("Iterations:", self.iterationsSliderWidget)

        self.timeStepSliderWidget = slicer.qMRMLSliderWidget()
        self.timeStepSliderWidget.maximum = 0.0625
        self.timeStepSliderWidget.minimum = 0.0015
        self.timeStepSliderWidget.decimals = 4
        self.timeStepSliderWidget.singleStep = 0.001
        self.timeStepSliderWidget.value = float(self.getTimeStep())
        self.timeStepSliderWidget.toolTip = """\
            The time step depends on the dimensionality of the image. In Slicer the images are 3D and the default (.0625) time step will \
            provide a stable solution.\
        """
        parametersFormLayout.addRow("Time step:", self.timeStepSliderWidget)

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
            if self.inputVolumeComboBox.currentNode() is None:
                raise FilteringInfo("Input image is required.")
            if not self.outputVolumeNameLineEdit.text:
                raise FilteringInfo("Output image name is required.")

            CustomizedCurvatureAnisotropicDiffusion.set_setting(self.CONDUCTANCE, self.conductanceSliderWidget.value)
            CustomizedCurvatureAnisotropicDiffusion.set_setting(self.ITERATIONS, self.iterationsSliderWidget.value)
            CustomizedCurvatureAnisotropicDiffusion.set_setting(self.TIME_STEP, self.timeStepSliderWidget.value)
            filteringParameters = self.FilteringParameters(
                self.inputVolumeComboBox.currentNode(),
                self.conductanceSliderWidget.value,
                self.iterationsSliderWidget.value,
                self.timeStepSliderWidget.value,
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


class CustomizedCurvatureAnisotropicDiffusionLogic(LTracePluginLogic):
    def __init__(self, progressBar):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar

    def apply(self, p):
        # Removing old cli node if it exists
        slicer.mrmlScene.RemoveNode(self.cliNode)
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
            "conductance": p.conductance,
            "numberOfIterations": p.iterations,
            "timeStep": p.timeStep,
        }

        self.input_volume = p.inputVolume
        self.cliNode = slicer.cli.run(slicer.modules.curvatureanisotropicdiffusion, None, cliParams)
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.filteringCLICallback)

    def filteringCLICallback(self, caller, event):
        status = caller.GetStatusString()
        if "Completed" in status or status == "Cancelled":
            logging.info(status)
            self.cliNode.RemoveAllObservers()
            self.cliNode = None

            slicer.util.setSliceViewerLayers(background=self.outputVolume, fit=True)
            copy_display(self.input_volume, self.outputVolume)

            if status == "Completed":
                pass
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
