from dataclasses import dataclass
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
from ltrace.slicer import helpers
from ltrace.utils.Markup import MarkupFiducial

try:
    from Test.CustomizedGradientAnisotropicDiffusionTest import CustomizedGradientAnisotropicDiffusionTest
except ImportError:
    CustomizedGradientAnisotropicDiffusionTest = None


def loading_cursor(func):
    def wrapper(*args, **kwargs):
        slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            return func(*args, **kwargs)
        finally:
            slicer.app.restoreOverrideCursor()

    return wrapper


def loosen_threshold(volume):
    display = volume.GetDisplayNode()
    if not display:
        return
    if not display.GetApplyThreshold():
        return
    if display.GetAutoThreshold():
        return
    low_threshold = display.GetLowerThreshold()
    high_threshold = display.GetUpperThreshold()
    display.SetThreshold(low_threshold - 0.001, high_threshold + 0.001)


class CustomizedGradientAnisotropicDiffusion(LTracePlugin):
    SETTING_KEY = "CustomizedGradientAnisotropicDiffusion"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Gradient Anisotropic Diffusion"
        self.parent.categories = ["LTrace Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = CustomizedGradientAnisotropicDiffusion.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


@dataclass
class FilteringParameters:
    inputVolume: slicer.vtkMRMLScalarVolumeNode = (None,)
    conductance: float = (1.0,)
    iterations: int = (5,)
    timeStep: float = (0.0625,)
    outputVolumeName: str = ("Gradient anisotropic diffusion output",)


class CustomizedGradientAnisotropicDiffusionWidget(LTracePluginWidget):
    # Settings constants
    CONDUCTANCE = "conductance"
    ITERATIONS = "iterations"
    TIME_STEP = "timeStep"
    OUTPUT_SUFFIX = "_GradDiffusion"

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.markup = None

    def getConductance(self):
        return CustomizedGradientAnisotropicDiffusion.get_setting(self.CONDUCTANCE, default="1")

    def getIterations(self):
        return CustomizedGradientAnisotropicDiffusion.get_setting(self.ITERATIONS, default="10")

    def getTimeStep(self):
        return CustomizedGradientAnisotropicDiffusion.get_setting(self.TIME_STEP, default="0.0625")

    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = CustomizedGradientAnisotropicDiffusionLogic(self.progressBar)
        self.logic.filteringStarted.connect(lambda: self.updateApplyButton(enabled=False))
        self.logic.filteringStopped.connect(lambda: self.updateApplyButton(enabled=True))
        self.logic.filteringCompleted.connect(self.exit)

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
        self.conductanceSliderWidget.valueChanged.connect(lambda _: self.onSettingsChanged())
        self.conductanceSliderWidget.tracking = False
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
        self.iterationsSliderWidget.valueChanged.connect(lambda _: self.onSettingsChanged())
        self.iterationsSliderWidget.tracking = False
        parametersFormLayout.addRow("Iterations:", self.iterationsSliderWidget)

        self.timeStepSliderWidget = slicer.qMRMLSliderWidget()
        self.timeStepSliderWidget.maximum = 0.1
        self.timeStepSliderWidget.minimum = 0.0001
        self.timeStepSliderWidget.decimals = 4
        self.timeStepSliderWidget.singleStep = 0.001
        self.timeStepSliderWidget.value = float(self.getTimeStep())
        self.timeStepSliderWidget.toolTip = """\
            The time step depends on the dimensionality of the image. In Slicer the images are 3D and the default (.0625) time step will \
            provide a stable solution.\
        """
        self.timeStepSliderWidget.valueChanged.connect(lambda _: self.onSettingsChanged())
        self.timeStepSliderWidget.tracking = False
        parametersFormLayout.addRow("Time step:", self.timeStepSliderWidget)

        self.togglePreviewButton = qt.QPushButton("Preview")
        self.togglePreviewButton.setFixedHeight(40)
        self.togglePreviewButton.clicked.connect(self.onPreviewButtonClicked)
        self.updatePreviewButton()

        parametersFormLayout.addWidget(self.togglePreviewButton)

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
        self.cancelButton.enabled = False

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.applyButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        formLayout.addRow(buttonsHBoxLayout)

        self.layout.addStretch()

        self.layout.addWidget(self.progressBar)
        self.onInputChanged(self.inputVolumeComboBox.currentNode())

    def exit(self):
        self.inputVolumeComboBox.setCurrentNode(None)
        self.updatePreviewButton()
        if self.markup:
            self.markup.stop_picking()
            self.markup = None

    def onFinishMarkup(self, markup, markupIndex):
        ijk = markup.get_ijk_point_position(markupIndex, volume=self.inputVolumeComboBox.currentNode())
        self.logic.center = tuple(ijk)
        self.logic.setInputSliceView(markup.last_slice_view_name)
        self.onTogglePreview()

    def onPreviewButtonClicked(self):
        if self.logic.previewEnabled:
            self.onTogglePreview()
        else:
            self.togglePreviewButton.setText("Picking a spot in slice view, press Esc to cancel")
            self.togglePreviewButton.enabled = False
            self.markup = MarkupFiducial(finish_callback=self.onFinishMarkup, cancel_callback=self.updatePreviewButton)
            self.markup.markups_node.SetName("Preview Center")
            self.markup.start_picking()

    def onTogglePreview(self):
        self.logic.togglePreview()
        self.onInputChanged(self.inputVolumeComboBox.currentNode())
        self.onSettingsChanged()
        self.updatePreviewButton()

    def updatePreviewButton(self):
        self.togglePreviewButton.setText(
            "Stop previewing and go back to previous layout"
            if self.logic.previewEnabled
            else "Pick spot in slice view to preview"
        )
        cancelIcon = slicer.app.style().standardIcon(qt.QStyle.SP_ArrowLeft)
        markupIcon = qt.QIcon(":/Icons/MarkupsFiducialMouseModePlace.png")
        icon = cancelIcon if self.logic.previewEnabled else markupIcon
        self.togglePreviewButton.setIcon(icon)
        self.togglePreviewButton.enabled = self.inputVolumeComboBox.currentNode() is not None

    def updateApplyButton(self, enabled):
        self.applyButton.enabled = enabled
        self.cancelButton.enabled = not enabled

    def onInputChanged(self, inputNode):
        self.togglePreviewButton.enabled = inputNode is not None
        self.logic.setPreviewInput(inputNode)
        self.onSettingsChanged()

        newOutputName = inputNode.GetName() + self.OUTPUT_SUFFIX if inputNode != None else ""
        self.outputVolumeNameLineEdit.setText(newOutputName)

    def onSettingsChanged(self):
        filteringParameters = FilteringParameters(
            conductance=self.conductanceSliderWidget.value,
            iterations=self.iterationsSliderWidget.value,
            timeStep=self.timeStepSliderWidget.value,
        )
        self.logic.updatePreview(filteringParameters)

    def onApplyButtonClicked(self):
        try:
            if self.inputVolumeComboBox.currentNode() is None:
                raise FilteringInfo("Input image is required.")
            if not self.outputVolumeNameLineEdit.text:
                raise FilteringInfo("Output image name is required.")

            CustomizedGradientAnisotropicDiffusion.set_setting(self.CONDUCTANCE, self.conductanceSliderWidget.value)
            CustomizedGradientAnisotropicDiffusion.set_setting(self.ITERATIONS, self.iterationsSliderWidget.value)
            CustomizedGradientAnisotropicDiffusion.set_setting(self.TIME_STEP, self.timeStepSliderWidget.value)
            filteringParameters = FilteringParameters(
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


class CustomizedGradientAnisotropicDiffusionLogic(LTracePluginLogic):
    filteringStarted = qt.Signal()
    filteringStopped = qt.Signal()
    filteringCompleted = qt.Signal()

    PREVIEW_SIZE = 120
    PREVIEW_DEPTH = 5

    PREVIEW_SIZES = {
        "XY": (PREVIEW_SIZE, PREVIEW_SIZE, PREVIEW_DEPTH),
        "YZ": (PREVIEW_DEPTH, PREVIEW_SIZE, PREVIEW_SIZE),
        "XZ": (PREVIEW_SIZE, PREVIEW_DEPTH, PREVIEW_SIZE),
    }
    MEDICAL_PLANES = {"Axial": "XY", "Sagittal": "YZ", "Coronal": "XZ"}

    def __init__(self, progressBar):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar
        self.computingFilter = False
        self.previewing = False
        self.previewEnabled = False
        self.inputPreviewVolume = None
        self.outputPreviewVolume = None
        self.center = None
        self.orientation = "XY"

    def togglePreview(self):
        self.previewEnabled = not self.previewEnabled

    def setInputSliceView(self, sliceViewName):
        sliceWidget = slicer.app.layoutManager().sliceWidget(sliceViewName)
        if sliceWidget is None:
            return
        orientation = sliceWidget.sliceLogic().GetSliceNode().GetOrientation()
        if orientation in self.MEDICAL_PLANES:
            orientation = self.MEDICAL_PLANES[orientation]
        self.orientation = orientation

    def createPreviewNodes(self, inputVolume):
        self.inputPreviewVolume = helpers.createTemporaryNode(
            slicer.vtkMRMLScalarVolumeNode, "Filter input preview", uniqueName=False
        )
        self.outputPreviewVolume = helpers.createTemporaryNode(
            slicer.vtkMRMLScalarVolumeNode, "Filter output preview", uniqueName=False
        )
        self.inputPreviewVolume.CopyOrientation(inputVolume)
        helpers.copy_display(inputVolume, self.inputPreviewVolume)
        helpers.copy_display(inputVolume, self.outputPreviewVolume)
        loosen_threshold(self.inputPreviewVolume)
        loosen_threshold(self.outputPreviewVolume)

    def removePreviewNodes(self):
        helpers.removeTemporaryNodes()
        self.inputPreviewVolume = None
        self.outputPreviewVolume = None

    @loading_cursor
    def setPreviewInput(self, inputVolume):
        if inputVolume and not self.previewEnabled:
            slicer.util.setSliceViewerLayers(background=inputVolume, fit=True)
        if not inputVolume or not self.previewEnabled:
            if self.previewing:
                self.removePreviewNodes()
                slicer.app.layoutManager().setLayout(self.lastLayout)
                slicer.util.setSliceViewerLayers(background=self.lastVisibleVolume, fit=True)
                self.previewing = False
                self.previewEnabled = False
            return

        if not self.previewing:
            self.lastLayout = slicer.app.layoutManager().layout
            self.lastVisibleVolume = (
                slicer.app.layoutManager()
                .sliceWidget("Red")
                .sliceLogic()
                .GetSliceCompositeNode()
                .GetBackgroundVolumeID()
            )
            slicer.app.layoutManager().setLayout(200)  # Side by side images
            self.previewing = True

            self.createPreviewNodes(inputVolume)

        if not inputVolume:
            self.inputPreviewVolume.SetImageData(None)
            return

        array = slicer.util.arrayFromVolume(inputVolume)
        center = self.center or (sh // 2 for sh in array.shape)
        preview_size = self.PREVIEW_SIZES[self.orientation]
        slices = []
        for center_i, preview_i, array_i in zip(center, preview_size, reversed(array.shape)):
            min_ = center_i - preview_i // 2
            max_ = center_i + preview_i // 2
            offset = -min_
            if offset > 0:
                min_ += offset
                max_ += offset
            offset = max_ - array_i
            if offset > 0:
                min_ -= offset
                max_ -= offset
            slices.append(slice(min_, max_))
        slices = tuple(reversed(slices))
        slicer.util.updateVolumeFromArray(self.inputPreviewVolume, array[slices])

    @loading_cursor
    def updatePreview(self, filteringParameters):
        if self.previewEnabled:
            filteringParameters.inputVolume = self.inputPreviewVolume
            self.apply(filteringParameters, preview=True)

    def apply(self, p, preview=None):
        if preview:
            if not self.inputPreviewVolume:
                return
            if self.computingFilter:
                return
        self.computingFilter = True

        # Removing old cli node if it exists
        slicer.mrmlScene.RemoveNode(self.cliNode)

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        inputVolumeItemParent = subjectHierarchyNode.GetItemParent(
            subjectHierarchyNode.GetItemByDataNode(p.inputVolume)
        )

        if preview:
            qt.QApplication.setOverrideCursor(qt.Qt.BusyCursor)
            self.outputVolume = self.outputPreviewVolume
            self.outputVolume.SetName("Updating preview, please wait...")
        else:
            self.outputVolume = slicer.mrmlScene.AddNewNodeByClass(p.inputVolume.GetClassName())
            self.outputVolume.SetName(p.outputVolumeName)
            self.outputVolume.CreateDefaultDisplayNodes()
            self.outputVolume.GetDisplayNode().Copy(p.inputVolume.GetDisplayNode())
            subjectHierarchyNode.SetItemParent(
                subjectHierarchyNode.GetItemByDataNode(self.outputVolume), inputVolumeItemParent
            )
            self.filteringStarted.emit()

        cliParams = {
            "inputVolume": p.inputVolume.GetID(),
            "outputVolume": self.outputVolume.GetID(),
            "conductance": p.conductance,
            "numberOfIterations": p.iterations,
            "timeStep": p.timeStep,
            "useImageSpacing": "false",
        }

        self.inputVolume = p.inputVolume
        self.cliNode = slicer.cli.run(slicer.modules.gradientanisotropicdiffusion, None, cliParams)
        if preview:
            self.cliNode.AddObserver("ModifiedEvent", self.filteringPreviewCLICallback)
        else:
            self.progressBar.setCommandLineModuleNode(self.cliNode)
            self.cliNode.AddObserver("ModifiedEvent", self.filteringCLICallback)

    def filteringPreviewCLICallback(self, caller, event):
        qt.QApplication.restoreOverrideCursor()
        status = caller.GetStatusString()
        if status == "Completed":
            self.computingFilter = False
            self.cliNode.RemoveAllObservers()
            self.cliNode = None
            self.outputPreviewVolume.SetName("Filter output preview")

            layoutManager = slicer.app.layoutManager()
            widget1 = layoutManager.sliceWidget("SideBySideSlice1")
            widget2 = layoutManager.sliceWidget("SideBySideSlice2")

            widget1.setSliceOrientation(self.orientation)
            widget2.setSliceOrientation(self.orientation)

            imageLogic = widget1.sliceLogic()
            imageComposite = imageLogic.GetSliceCompositeNode()
            imageComposite.SetBackgroundVolumeID(self.inputPreviewVolume.GetID())
            imageLogic.FitSliceToAll()

            imageLogic = widget2.sliceLogic()
            imageComposite = imageLogic.GetSliceCompositeNode()
            imageComposite.SetBackgroundVolumeID(self.outputPreviewVolume.GetID())
            imageLogic.FitSliceToAll()

    def filteringCLICallback(self, caller, event):
        status = caller.GetStatusString()
        if "Completed" in status or status == "Cancelled":
            logging.info(status)
            self.cliNode.RemoveAllObservers()
            self.cliNode = None
            self.computingFilter = False

            self.filteringStopped.emit()
            if status == "Completed":
                slicer.util.setSliceViewerLayers(background=self.outputVolume, fit=True)
                copy_display(self.inputVolume, self.outputVolume)
                loosen_threshold(self.outputVolume)

                # When restoring the layout, show output volume instead of volume user was viewing earlier
                self.lastVisibleVolume = self.outputVolume.GetID()

                self.filteringCompleted.emit()
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
