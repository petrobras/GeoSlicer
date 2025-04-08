from ltrace.flow.util import (
    createSimplifiedSegmentEditor,
    onSegmentEditorEnter,
    onSegmentEditorExit,
)

import os
from pathlib import Path

import qt
import slicer
import ctk
from slicer.util import VTKObservationMixin
import qSlicerSegmentationsEditorEffectsPythonQt
import qSlicerSegmentationsModuleWidgetsPythonQt
from ltrace.utils.ProgressBarProc import ProgressBarProc
from collections import OrderedDict
from dataclasses import dataclass

from distinctipy import distinctipy
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget
from ltrace.slicer import helpers

SIDE_BY_SIDE_SEG_LAYOUT = 201


class UnstackedWidget(qt.QFrame):
    """QStackedWidget's size is the maximum size of its children.
    This widget is a workaround to make the size of the widget the size of the current child.
    """

    def __init__(self, parent=None):
        qt.QFrame.__init__(self, parent)
        self.setLayout(qt.QVBoxLayout())
        self._widgets = []
        self._currentWidget = None

    def addWidget(self, widget):
        self.layout().addWidget(widget)
        self._widgets.append(widget)
        widget.visible = False

    def setCurrentIndex(self, index):
        if self._currentWidget:
            self._currentWidget.visible = False
        self._currentWidget = self._widgets[index]
        self._currentWidget.visible = True


class HoverEventFilter(qt.QObject):
    itemHovered = qt.Signal(str)

    def eventFilter(self, obj, event):
        if event.type() == qt.QEvent.HoverMove:
            item = obj.itemAt(event.pos())
            if item:
                self.itemHovered.emit(item.data(HELP_ROLE))
        if event.type() == qt.QEvent.HoverLeave:
            selected = obj.selectedItems()
            if selected:
                first = selected[0]
                self.itemHovered.emit(first.data(HELP_ROLE))
        return False


ENTER_ROLE = qt.Qt.UserRole + 1
EXIT_ROLE = qt.Qt.UserRole + 2
HELP_ROLE = qt.Qt.UserRole + 3

MAIN_SEG_EDITOR_TAG = "Streamlined_Main_Segment_Editor"
SOI_SEG_EDITOR_TAG = "Streamlined_SOI_Segment_Editor"


class StepEnum:
    SELECT_IMAGE = 0
    CROP = 1
    SOI = 2
    FILTER = 3
    MULTIPLE_THRESHOLD = 4
    BOUNDARY_REMOVAL = 5
    MODEL = 6
    FINISH = 7


HELP = {
    StepEnum.SELECT_IMAGE: "<h3>Select image</h3>Select the input microtomography image to be modeled.<br><br>You can load images using the <b>Micro CT Loader</b> module.",
    StepEnum.CROP: "<h3>Crop</h3>Crop the input image to the region of interest.",
    StepEnum.SOI: "<h3>Segment of interest</h3>Specify the region of interest for the modelling.<br><br>Use the '<b>Scissors</b>' effect to manually select the region of interest, or the '<b>Sample segmentation</b>' effect to quickly segment the sample.",
    StepEnum.FILTER: "<h3>Filter</h3>Remove noise from the image using a median filter.<br><br>Each voxel is replaced by the median value of the voxels in a neighborhood around it. You must specify a neighborhood size greater than 1x1x1 for the filter to have an effect.",
    StepEnum.MULTIPLE_THRESHOLD: "<h3>Threshold</h3>Segment the image into macroporosity, microporosity, solid and reference solid.<br><br>Adjust the thresholds by dragging the handles in the histogram. You can zoom in and out on the histogram by using the 'X-axis range' slider.",
    StepEnum.BOUNDARY_REMOVAL: "<h3>Adjust boundaries</h3>The boundary between macroporosity and solid may be misclassified by the thresholding. Specify a boundary region that will be adjusted by removing the boundary from the microporosity segment and then expanding the other segments to fill the gap.<br><br>Adjust the slider until the region in blue matches the boundary between macroporosity and solid.",
    StepEnum.MODEL: "<h3>Model</h3>Compute a porosity map of the volume, where pore is 1 and solid is 0.<br><br>Use the quality control histogram to define air and solid attenuation factors.",
    StepEnum.FINISH: "<h3>Finish</h3>You can check the results or go back to a previous step to make changes.",
}


class WidgetEnum:
    SELECT_IMAGE = 0
    CROP = 1
    SOI = 2
    FILTER = 3
    SEGMENTATION = 4
    MODEL = 5
    FINISH = 6


@dataclass
class FlowState:
    scalarVolume: slicer.vtkMRMLScalarVolumeNode = None
    segmentation: slicer.vtkMRMLSegmentationNode = None
    soi: slicer.vtkMRMLSegmentationNode = None
    finished: bool = False

    def selectImage(self, scalarVolume):
        self.scalarVolume = scalarVolume
        self.segmentation = None
        self.soi = None
        self.finished = False

    def selectSegmentation(self, segmentation):
        self.segmentation = segmentation
        self.finished = False

    def availableSteps(self):
        steps = [StepEnum.SELECT_IMAGE]
        if self.scalarVolume is not None:
            steps += [StepEnum.CROP, StepEnum.SOI, StepEnum.FILTER, StepEnum.MULTIPLE_THRESHOLD]
        if self.segmentation is not None:
            steps += [StepEnum.BOUNDARY_REMOVAL, StepEnum.MODEL]
        if self.finished:
            steps += [StepEnum.FINISH]
        return steps


def setNodesVisibility(flowState, scalar=False, segmentation=False, soi=False):
    if flowState.scalarVolume is not None and scalar:
        slicer.util.setSliceViewerLayers(background=flowState.scalarVolume, fit=True)
    if flowState.segmentation is not None:
        flowState.segmentation.SetDisplayVisibility(segmentation)
    if flowState.soi is not None:
        flowState.soi.SetDisplayVisibility(soi)


class StreamlinedModelling(LTracePlugin):
    SETTING_KEY = "StreamlinedModelling"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Modelling Flow"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = StreamlinedModelling.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class StreamlinedModellingWidget(LTracePluginWidget, VTKObservationMixin):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.parameterSetNode = None
        self.editor = None
        self.__tag = None
        self.__updateEffectRegisteredTimer = qt.QTimer()
        self.__updateEffectRegisteredTimer.setParent(self.parent)
        self.__updateEffectRegisteredTimer.timeout.connect(lambda: self.__handleUpdatePlot())
        self.__updateEffectRegisteredTimer.setInterval(1000)

    def setupSelectImage(self):
        inputWidget = qt.QWidget()
        inputLayout = qt.QFormLayout(inputWidget)
        self.inputVolumeComboBox = hierarchyVolumeInput(
            onChange=self.onInputChanged, nodeTypes=["vtkMRMLScalarVolumeNode"]
        )
        inputLayout.addRow("Input volume:", self.inputVolumeComboBox)
        return inputWidget

    def onInputChanged(self, _=None):
        enabled = self.inputVolumeComboBox.currentNode() is not None
        self.nextButton.enabled = enabled
        # self.nextButton.setToolTip("Continue with the selected volume" if enabled else "You must choose an input volume to continue")

    def enterSelectImage(self):
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
        setNodesVisibility(self.flowState, scalar=True)

        self.backButton.enabled = False
        self.backButton.setToolTip("This is the first step")
        self.skipButton.enabled = False
        self.skipButton.setToolTip("This step cannot be skipped")

        self.onInputChanged()

        self.stepsWidget.setCurrentIndex(WidgetEnum.SELECT_IMAGE)

    def exitSelectImage(self):
        pass

    def setupCrop(self):
        cropModule = slicer.modules.customizedcropvolume.createNewWidgetRepresentation()
        self.cropWidget = cropModule.self()
        self.cropWidget.inputCollapsibleButton.visible = False
        self.cropWidget.applyCancelButtons.visible = False
        return cropModule

    def enterCrop(self):
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
        setNodesVisibility(self.flowState, scalar=True)

        self.backButton.enabled = True
        self.backButton.setToolTip("Go back to the previous step")
        self.skipButton.enabled = True
        self.skipButton.setToolTip("Do not crop this volume for now")
        self.nextButton.enabled = True
        self.nextButton.setToolTip("Crop the image")

        self.cropWidget.enter()
        self.cropWidget.volumeComboBox.setCurrentNode(self.flowState.scalarVolume)
        self.stepsWidget.setCurrentIndex(WidgetEnum.CROP)

    def exitCrop(self):
        self.cropWidget.exit()

    def setupFilter(self):
        filteringTool = slicer.modules.customizedmedianimagefilter.createNewWidgetRepresentation()
        self.filteringToolWidget = filteringTool.self()
        self.filteringToolWidget.inputCollapsibleButton.visible = False
        self.filteringToolWidget.outputCollapsibleButton.visible = False
        self.filteringToolWidget.applyButton.visible = False
        self.filteringToolWidget.cancelButton.visible = False
        logic = self.filteringToolWidget.logic

        def onComplete():
            self.flowState.scalarVolume = self.filteringToolWidget.logic.outputVolume
            self.stepList.setCurrentRow(StepEnum.MULTIPLE_THRESHOLD)

        def onFailure():
            pass

        logic.onComplete = onComplete
        logic.onFailure = onFailure

        return filteringTool

    def enterFilter(self):
        setNodesVisibility(self.flowState, scalar=True)

        self.backButton.enabled = True
        self.backButton.setToolTip("Go back to the previous step")
        self.skipButton.enabled = True
        self.skipButton.setToolTip("Do not filter this volume for now")
        self.nextButton.enabled = True
        self.nextButton.setToolTip("Filter the image")

        self.filteringToolWidget.inputVolumeComboBox.setCurrentNode(self.flowState.scalarVolume)
        self.stepsWidget.setCurrentIndex(WidgetEnum.FILTER)

    def exitFilter(self):
        self.filteringToolWidget.onCancelButtonClicked()

    def setupSegmentation(self):
        (
            self.editor,
            self.effectFactorySingleton,
            self.sourceVolumeNodeComboBox,
            self.segmentationNodeComboBox,
        ) = createSimplifiedSegmentEditor()
        self.editor.findChild(qt.QFrame, "EffectsGroupBox").visible = False

        self.multipleThresholdEffect = self.editor.effectByName("Multiple Threshold").self()
        self.boundaryRemovalEffect = self.editor.effectByName("Boundary removal").self()
        self.expandSegmentsEffect = self.editor.effectByName("Expand segments").self()
        self.multipleThresholdEffect.applyFinishedCallback = self.onMultipleThresholdFinished
        self.boundaryRemovalEffect.applyFinishedCallback = self.onBoundaryRemovalFinished
        self.expandSegmentsEffect.applyFinishedCallback = self.onExpandSegmentsFinished
        self.multipleThresholdEffect.applyAllSupported = False
        self.boundaryRemovalEffect.applyAllSupported = False
        self.expandSegmentsEffect.applyAllSupported = False
        self.multipleThresholdEffect.applyButton.visible = False
        self.multipleThresholdEffect.enablePulsingCheckbox.setCheckState(qt.Qt.Unchecked)
        self.multipleThresholdEffect.enablePulsingCheckbox.visible = False
        self.boundaryRemovalEffect.enablePulsingCheckbox.setCheckState(qt.Qt.Unchecked)
        self.boundaryRemovalEffect.enablePulsingCheckbox.visible = False

        ApplicationObservables().applicationLoadFinished.connect(self.__onApplicationLoadFinished)

        self.multiFinishedTimer = qt.QTimer()
        self.multiFinishedTimer.setSingleShot(True)
        self.multiFinishedTimer.setInterval(100)

        def afterWait():
            with ProgressBarProc() as pb:
                pb.setMessage("Initializing boundary removal")

                # Make all segments invisible except for microporosity
                display = self.segmentationNodeComboBox.currentNode().GetDisplayNode()
                display.SetSegmentVisibility("Macroporosity", False)
                display.SetSegmentVisibility("Microporosity", True)
                display.SetSegmentVisibility("Solid", False)
                display.SetSegmentVisibility("Reference Solid", False)

                self.boundaryRemovalEffect.initialize()
                self.boundaryRemovalEffect.initializeButton.parent().visible = False
                self.boundaryRemovalEffect.applyButton.visible = False

        self.multiFinishedTimer.timeout.connect(afterWait)

        return self.editor

    def enterMultipleThreshold(self):
        if self.flowState.segmentation is not None:
            slicer.mrmlScene.RemoveNode(self.flowState.segmentation)
            self.flowState.selectSegmentation(None)
            self.updateAvailableSteps()

        onSegmentEditorEnter(self.editor, MAIN_SEG_EDITOR_TAG)

        self.backButton.enabled = True
        self.backButton.setToolTip("Go back to the previous step")
        self.skipButton.enabled = False
        self.skipButton.setToolTip("You must create a segmentation to continue")
        self.nextButton.enabled = True
        self.nextButton.setToolTip("Apply multiple threshold effect")

        sourceNode = self.flowState.scalarVolume
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSegmentationNode", sourceNode.GetName() + "_Segmentation"
        )
        segmentationNode.CreateDefaultDisplayNodes()
        segmentNames = ["Macroporosity", "Microporosity", "Solid", "Reference Solid"]

        colors = []
        for i, segmentName in enumerate(segmentNames):
            if i == 0:
                color = (1, 0, 0)
            else:
                color = distinctipy.get_colors(1, colors)[0]
            colors.append(color)
            segmentation = segmentationNode.GetSegmentation()
            segmentation.AddEmptySegment(segmentName)
            segmentation.GetSegment(segmentName).SetColor(color)

        self.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        self.sourceVolumeNodeComboBox.setCurrentNode(sourceNode)
        self.editor.setActiveEffectByName("Multiple Threshold")

        maskingWidget = self.editor.findChild(qt.QGroupBox, "MaskingGroupBox")
        maskingWidget.visible = False

        table = self.editor.findChild(qt.QWidget, "SegmentsTableResizableFrame")
        table.visible = True

        setNodesVisibility(self.flowState, scalar=True, segmentation=True)
        slicer.app.layoutManager().setLayout(SIDE_BY_SIDE_SEG_LAYOUT)

        self.stepsWidget.setCurrentIndex(WidgetEnum.SEGMENTATION)

    def exitMultipleThreshold(self):
        onSegmentEditorExit(self.editor)

        if self.flowState.segmentation is None:
            segmentation = self.segmentationNodeComboBox.currentNode()
            if segmentation is not None:
                slicer.mrmlScene.RemoveNode(segmentation)

    def enterBoundaryRemoval(self):
        slicer.app.layoutManager().setLayout(SIDE_BY_SIDE_SEG_LAYOUT)
        setNodesVisibility(self.flowState, scalar=True)

        onSegmentEditorEnter(self.editor, MAIN_SEG_EDITOR_TAG)

        self.backButton.enabled = True
        self.backButton.setToolTip("Go back to the previous step")
        self.skipButton.enabled = True
        self.skipButton.setToolTip("Skip boundary adjustment")
        self.nextButton.enabled = True
        self.nextButton.setToolTip("Adjust the specified boundaries")

        sourceNode = self.flowState.scalarVolume
        segmentationNode = self.flowState.segmentation
        self.sourceVolumeNodeComboBox.setCurrentNode(sourceNode)
        self.segmentationNodeComboBox.setCurrentNode(segmentationNode)

        self.editor.setActiveEffectByName("Boundary removal")

        self.multiFinishedTimer.start()

        maskingWidget = self.editor.findChild(qt.QGroupBox, "MaskingGroupBox")
        maskingWidget.visible = False

        table = self.editor.findChild(qt.QWidget, "SegmentsTableResizableFrame")
        table.visible = False

        self.stepsWidget.setCurrentIndex(WidgetEnum.SEGMENTATION)

    def exitBoundaryRemoval(self):
        onSegmentEditorExit(self.editor)

    def setupSOI(self):
        self.soiEditor, _, self.soiVolumeComboBox, self.soiSegmentComboBox = createSimplifiedSegmentEditor()
        effects = [
            "Scissors",
            "Sample segmentation",
        ]
        self.soiEditor.setEffectNameOrder(effects)
        self.soiEditor.unorderedEffectsVisible = False
        tableView = self.soiEditor.findChild(qt.QTableView, "SegmentsTable")
        tableView.setFixedHeight(100)
        return self.soiEditor

    def enterSOI(self):
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
        setNodesVisibility(self.flowState, scalar=True, soi=True)

        onSegmentEditorEnter(self.soiEditor, SOI_SEG_EDITOR_TAG)

        self.backButton.enabled = True
        self.backButton.setToolTip("Go back to the previous step")
        self.skipButton.enabled = True
        self.skipButton.setToolTip("Skip SOI selection. Will use the whole volume as SOI.")
        self.nextButton.enabled = True
        self.nextButton.setToolTip("Confirm the SOI selection")

        sourceNode = self.flowState.scalarVolume
        if self.flowState.soi is None:
            soiNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", sourceNode.GetName() + "_SOI")
            soiNode.CreateDefaultDisplayNodes()
            segmentation = soiNode.GetSegmentation()
            segmentation.AddEmptySegment("SOI")
            segmentation.GetSegment("SOI").SetColor(1, 0, 0)
        else:
            soiNode = self.flowState.soi

        self.soiSegmentComboBox.setCurrentNode(soiNode)
        self.soiVolumeComboBox.setCurrentNode(sourceNode)

        self.soiEditor.setCurrentSegmentID("SOI")

        maskingWidget = self.soiEditor.findChild(qt.QGroupBox, "MaskingGroupBox")
        maskingWidget.visible = False

        self.stepsWidget.setCurrentIndex(WidgetEnum.SOI)

    def exitSOI(self):
        if self.soiSegmentComboBox.currentNode().GetID() != self.flowState.soi.GetID():
            slicer.mrmlScene.RemoveNode(self.soiSegmentComboBox.currentNode())

        onSegmentEditorExit(self.soiEditor)

    def setupModelling(self):
        widget = qt.QFrame()
        layout = qt.QVBoxLayout(widget)

        modellingModule = slicer.modules.segmentationmodelling.createNewWidgetRepresentation()
        self.modellingWidget = modellingModule.self()
        layout.addWidget(modellingModule)
        modellingModule.visible = False

        self.microporosityWidget = self.modellingWidget.method_selector.content.widget(0)
        qualityControl = self.microporosityWidget.plotSection
        layout.addWidget(qualityControl)
        qualityControl.visible = True
        qualityControl.collapsed = False

        self.qcInitButton = self.microporosityWidget.microporosityPlot.attenuation_factors.quality_control_button
        self.qcInitButton.visible = False

        layout.addWidget(self.modellingWidget.progress_bar)

        self.modellingWidget.onProcessEnded = self.onModellingFinished

        return widget

    def enterModelling(self):
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
        setNodesVisibility(self.flowState, scalar=True, segmentation=True, soi=False)

        self.backButton.enabled = True
        self.backButton.setToolTip("Go back to the previous step")
        self.skipButton.enabled = False
        self.skipButton.setToolTip("This step can't be skipped.")
        self.nextButton.enabled = True
        self.nextButton.setToolTip("Run modelling")

        inputWidget = self.microporosityWidget.inputWidget
        inputWidget.mainInput.setCurrentNode(self.flowState.segmentation)
        inputWidget.mainInput.itemChangedHandler(inputWidget.mainInput.currentItem())
        inputWidget.soiInput.setCurrentNode(self.flowState.soi)
        inputWidget.soiInput.itemChangedHandler(inputWidget.soiInput.currentItem())
        inputWidget.referenceInput.setCurrentNode(self.flowState.scalarVolume)
        inputWidget.referenceInput.itemChangedHandler(inputWidget.referenceInput.currentItem())

        self.microporosityWidget.poreDistSelector[0].setCurrentText("Macroporosity")
        self.microporosityWidget.poreDistSelector[1].setCurrentText("Microporosity")
        self.microporosityWidget.poreDistSelector[2].setCurrentText("Solid")
        self.microporosityWidget.poreDistSelector[3].setCurrentText("Reference solid")

        self.qcInitButton.click()

        self.stepsWidget.setCurrentIndex(WidgetEnum.MODEL)

    def exitModelling(self):
        pass

    def setupFinish(self):
        widget = qt.QGroupBox()
        layout = qt.QVBoxLayout(widget)
        layout.addWidget(qt.QLabel("Modelling finished. Check the results under the 'Modelling Results' folder"))
        layout.addWidget(slicer.modules.customizeddata.createNewWidgetRepresentation())

        return widget

    def enterFinish(self):
        setNodesVisibility(self.flowState, scalar=False, segmentation=False, soi=False)
        self.backButton.enabled = True
        self.backButton.setToolTip("Go back to the previous step")
        self.skipButton.enabled = False
        self.skipButton.setToolTip("The workflow is finished")
        self.nextButton.enabled = False
        self.nextButton.setToolTip("The workflow is finished")

        self.stepsWidget.setCurrentIndex(WidgetEnum.FINISH)

    def exitFinish(self):
        pass

    def onFlowStart(self):
        return self.onNext(-1)

    def onNext(self, index):
        if index == StepEnum.SELECT_IMAGE:
            self.flowState.selectImage(self.inputVolumeComboBox.currentNode())
            self.stepList.setCurrentRow(StepEnum.CROP)
        elif index == StepEnum.CROP:
            self.cropWidget.onCropButtonClicked()
            self.flowState.scalarVolume = self.cropWidget.logic.lastCroppedVolume
            self.stepList.setCurrentRow(StepEnum.SOI)
        elif index == StepEnum.SOI:
            soiNode = self.soiSegmentComboBox.currentNode()
            array = slicer.util.arrayFromSegmentBinaryLabelmap(soiNode, "SOI")
            if array is None:
                soiIsEmpty = True
            else:
                soiIsEmpty = array.max() == 0

            if soiIsEmpty:
                self.flowState.soi = None
            else:
                self.flowState.soi = soiNode
            self.stepList.setCurrentRow(StepEnum.FILTER)
        elif index == StepEnum.FILTER:
            self.filteringToolWidget.onApplyButtonClicked()
            self.nextButton.enabled = False
            self.nextButton.setToolTip("Filter is already running")
        elif index == StepEnum.MULTIPLE_THRESHOLD:
            self.multipleThresholdEffect.onApply()
        elif index == StepEnum.BOUNDARY_REMOVAL:
            self.boundaryRemovalEffect.onApply()
        elif index == StepEnum.MODEL:
            self.modellingWidget.apply_button.click()
            self.nextButton.enabled = False
            self.nextButton.setToolTip("Modelling is already running")

    def updateAvailableSteps(self):
        availableSteps = self.flowState.availableSteps()
        for i in range(self.stepList.count):
            item = self.stepList.item(i)
            if i in availableSteps:
                item.setFlags(item.flags() | qt.Qt.ItemIsEnabled)
            else:
                item.setFlags(item.flags() & ~qt.Qt.ItemIsEnabled)

    def onStepChange(self, nextWidgetIndex):
        self.updateAvailableSteps()
        if self.currentStepIndex >= 0:
            self.stepList.item(self.currentStepIndex).data(EXIT_ROLE)()
        self.stepList.item(nextWidgetIndex).data(ENTER_ROLE)()
        self.onUpdateHelp(self.stepList.item(nextWidgetIndex).data(HELP_ROLE))
        self.currentStepIndex = nextWidgetIndex

    def onUpdateHelp(self, text):
        self.helpLabel.setText(text)

    def setup(self):
        LTracePluginWidget.setup(self)
        formLayout = qt.QFormLayout()
        self.layout.addLayout(formLayout)

        stepListSection = ctk.ctkCollapsibleButton()
        stepListSection.text = "Step-by-step Overview"
        formLayout.addWidget(stepListSection)

        stepListLayout = qt.QHBoxLayout(stepListSection)

        self.stepList = qt.QListWidget()
        # Set padding for the list
        # make text bold when selected
        # and underline when hovered
        isDark = helpers.themeIsDark()
        self.stepList.setStyleSheet(
            f"""
            QListView {{
                outline: none;
            }}
            QListWidget::item {{
                padding: 4px; 
                border: 0px;
                outline: none;
            }}
            QListWidget::item:selected {{
                padding-left: 10px;
                font-weight: bold;
                background-color: {'#37403A' if isDark else '#d9ebff'};
                border-left: 6px solid #26C252;
                color: {'#ffffff' if isDark else '#000000'};
            }}
            QListWidget::item:hover {{
                background-color: {'#37403A' if isDark else '#d9ebff'};
            }}
        """
        )

        stepListLayout.addWidget(self.stepList)
        stepListLayout.setSpacing(5)

        # Create a help group box with rich text. Add some lorem ipsum
        helpGroupBox = qt.QGroupBox()
        helpLayout = qt.QVBoxLayout()
        helpGroupBox.setLayout(helpLayout)
        self.helpLabel = qt.QLabel()
        self.helpLabel.setWordWrap(True)
        helpLayout.addWidget(self.helpLabel)
        helpLayout.addStretch(1)

        stepListLayout.addWidget(helpGroupBox, 1)

        moduleSection = ctk.ctkCollapsibleButton()
        self.layout.addSpacing(15)
        self.layout.addWidget(moduleSection)
        moduleSection.text = "Current Step"
        moduleLayout = qt.QVBoxLayout(moduleSection)

        self.stepsWidget = UnstackedWidget()
        moduleLayout.addWidget(self.stepsWidget)

        flowGroup = qt.QGroupBox()
        flowLayout = qt.QHBoxLayout(flowGroup)
        self.backButton = qt.QPushButton("\u2190 Back")
        self.backButton.setFixedHeight(40)
        self.skipButton = qt.QPushButton("Skip \u21d2")
        self.skipButton.setFixedHeight(40)
        self.nextButton = qt.QPushButton("Next \u2192")
        self.nextButton.setProperty("class", "actionButtonBackground")
        self.nextButton.setFixedHeight(40)

        flowLayout.addWidget(self.backButton, 1)
        flowLayout.addStretch(1)
        flowLayout.addWidget(self.skipButton, 1)
        flowLayout.addWidget(self.nextButton, 1)

        self.backButton.clicked.connect(lambda: self.stepList.setCurrentRow(self.stepList.currentRow - 1))
        self.skipButton.clicked.connect(lambda: self.stepList.setCurrentRow(self.stepList.currentRow + 1))
        self.nextButton.clicked.connect(lambda: self.onNext(self.stepList.currentRow))

        self.layout.addSpacing(15)
        self.layout.addWidget(flowGroup)
        self.layout.addStretch(1)

        self.stepsWidget.addWidget(self.setupSelectImage())
        self.stepsWidget.addWidget(self.setupCrop())
        self.stepsWidget.addWidget(self.setupSOI())
        self.stepsWidget.addWidget(self.setupFilter())
        self.stepsWidget.addWidget(self.setupSegmentation())
        self.stepsWidget.addWidget(self.setupModelling())
        self.stepsWidget.addWidget(self.setupFinish())

        steps = OrderedDict(
            [
                ("Select image", (self.enterSelectImage, self.exitSelectImage)),
                ("Crop", (self.enterCrop, self.exitCrop)),
                ("Segment of interest", (self.enterSOI, self.exitSOI)),
                ("Filter", (self.enterFilter, self.exitFilter)),
                ("Threshold", (self.enterMultipleThreshold, self.exitMultipleThreshold)),
                ("Adjust boundaries", (self.enterBoundaryRemoval, self.exitBoundaryRemoval)),
                ("Model", (self.enterModelling, self.exitModelling)),
                ("Finish", (self.enterFinish, self.exitFinish)),
            ]
        )
        for i, (title, (enterFunc, exitFunc)) in enumerate(steps.items()):
            self.stepList.addItem(f"{i + 1}. {title}")
            self.stepList.item(i).setData(ENTER_ROLE, enterFunc)
            self.stepList.item(i).setData(EXIT_ROLE, exitFunc)
            self.stepList.item(i).setData(HELP_ROLE, HELP[i])

        self.stepList.currentRowChanged.connect(self.onStepChange)
        hoverFilter = HoverEventFilter()
        hoverFilter.setParent(self.stepList)
        self.stepList.installEventFilter(hoverFilter)
        hoverFilter.itemHovered.connect(self.onUpdateHelp)

        self.currentStepIndex = -1
        self.flowState = FlowState()
        self.stepList.setCurrentRow(0)
        hoverFilter.itemHovered.emit(self.stepList.item(0).text())
        # self.stepsWidget.currentChanged.connect(lambda _: adjustStackedWidgetSize(self.stepsWidget))
        # self.stepsWidget.setSizePolicy(qt.QSizePolicy.MinimumExpanding, qt.QSizePolicy.Preferred)
        # self.stepsWidget.currentChanged.emit(0)

        self.onFlowStart()
        self.enter()

    def onMultipleThresholdFinished(self):
        segmentationNode = self.segmentationNodeComboBox.currentNode()
        self.flowState.selectSegmentation(segmentationNode)

        if self.flowState.soi is not None:
            with helpers.SegmentationNodeArray(segmentationNode, read_only=False) as array:
                with helpers.SegmentationNodeArray(self.flowState.soi, read_only=True) as soiArray:
                    array *= soiArray

        self.stepList.setCurrentRow(StepEnum.BOUNDARY_REMOVAL)

    def onBoundaryRemovalFinished(self):
        self.pb = ProgressBarProc()
        self.pb.setMessage("Expanding segments")
        self.editor.setActiveEffectByName("Expand segments")
        display = self.segmentationNodeComboBox.currentNode().GetDisplayNode()

        # Make all segments visible except for microporosity
        display = self.segmentationNodeComboBox.currentNode().GetDisplayNode()
        display.SetSegmentVisibility("Macroporosity", True)
        display.SetSegmentVisibility("Microporosity", False)
        display.SetSegmentVisibility("Solid", True)
        display.SetSegmentVisibility("Reference Solid", True)

        self.expandSegmentsEffect.applyButton.click()

    def onExpandSegmentsFinished(self):
        with self.pb:
            self.editor.setActiveEffectByName("")
            display = self.segmentationNodeComboBox.currentNode().GetDisplayNode()
            display.SetSegmentVisibility("Microporosity", True)

            if self.flowState.soi is not None:
                with helpers.SegmentationNodeArray(self.flowState.segmentation, read_only=False) as array:
                    with helpers.SegmentationNodeArray(self.flowState.soi, read_only=True) as soiArray:
                        array *= soiArray

        self.stepList.setCurrentRow(StepEnum.MODEL)

    def onModellingFinished(self):
        self.flowState.finished = True
        self.stepList.setCurrentRow(StepEnum.FINISH)

    def __onApplicationLoadFinished(self):
        # Connect observers to scene events
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndImportEvent, self.onSceneEndImport)
        self.activateEditorRegisteredCallback()
        ApplicationObservables().applicationLoadFinished.disconnect(self.__onApplicationLoadFinished)

    def activateEditorRegisteredCallback(self):
        self.effectFactorySingleton.effectRegistered.connect(self.editorEffectRegistered)

    def deactivateEditorRegisteredCallback(self):
        self.effectFactorySingleton.effectRegistered.disconnect(self.editorEffectRegistered)

    def editorEffectRegistered(self, effect=None) -> None:
        """Callback for registres effect signal. A QTimer is used to avoid multiple calls at once when multiple effects are registered.
        The method 'qMRMLSegmentEditorWidget.updateEffectList' causes some widget's to update, it might result in some widgets blinking in the background if parent tree is not defined.
        """
        # if self.__updateEffectRegisteredTimer.isActive():
        #     self.__updateEffectRegisteredTimer.stop()

        # self.__updateEffectRegisteredTimer.start()
        self.editor.updateEffectList()
        self.soiEditor.updateEffectList()

    def __handleUpdatePlot(self) -> None:
        """Wrapper for 'qMRMLSegmentEditorWidget.updateEffectList' through QTimer callback."""
        self.editor.updateEffectList()

    def selectParameterNodeByTag(self, tag: str):
        if not tag:
            raise ValueError("Parameter node 'tag' is empty")

        self.__tag = tag
        self.selectParameterNode()
        instance = self.editor.effectByName("Mask Image")
        effect = instance.self()
        effect.setEnvironment(self.__tag)

    def onSceneStartClose(self, caller, event):
        self.parameterSetNode = None
        self.editor.setSegmentationNode(None)
        self.editor.removeViewObservations()

    def onSceneEndClose(self, caller, event):
        if self.parent.isEntered:
            self.selectParameterNode()
            self.editor.updateWidgetFromMRML()

    def onSceneEndImport(self, caller, event):
        if self.parent.isEntered:
            self.selectParameterNode()
            self.editor.updateWidgetFromMRML()

    def cleanup(self):
        super().cleanup()
        self.removeObservers()
        self.multipleThresholdEffect.applyFinishedCallback = lambda: None
        self.boundaryRemovalEffect.applyFinishedCallback = lambda: None
        self.expandSegmentsEffect.applyFinishedCallback = lambda: None
        self.multiFinishedTimer.stop()
        self.multiFinishedTimer.timeout.disconnect()
