import ctk
import os
import qt
import slicer
import numpy as np
import time

from ltrace.slicer import ui
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.helpers import createTemporaryNode, removeTemporaryNodes, tryGetNode, create_color_table
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from distinctipy import distinctipy

from pathlib import Path


try:
    from Test.UnsupervisedSegmentationTest import UnsupervisedSegmentationTest
except ImportError:
    UnsupervisedSegmentationTest = None  # tests not deployed to final version or closed source


class UnsupervisedSegmentation(LTracePlugin):
    SETTING_KEY = "UnsupervisedSegmentation"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Self-Guided Segmentation"
        self.parent.categories = ["Segmentation", "Thin Section"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = UnsupervisedSegmentation.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class UnsupervisedSegmentationWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.outputSegmentationNode = None

    def setup(self):
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.inputSelector = ui.hierarchyVolumeInput(
            onChange=self.onInputChanged,
            hasNone=False,
            nodeTypes=["vtkMRMLVectorVolumeNode"],
        )
        self.inputSelector.setMRMLScene(slicer.mrmlScene)
        self.inputSelector.setToolTip("Pick a labeled volume node")
        self.extraInputSelector = ui.hierarchyVolumeInput(
            hasNone=True,
            nodeTypes=["vtkMRMLVectorVolumeNode"],
        )
        self.extraInputSelector.setMRMLScene(slicer.mrmlScene)
        self.extraInputSelector.setToolTip("Add extra channels to the input (e.g. PP/PX)")

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Input:", self.inputSelector)
        inputLayout.addRow("Extra Input (optional):", self.extraInputSelector)

        # Parameters section
        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False
        parametersSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        # Minimum segments slider
        self.minSegmentsSlider = ctk.ctkSliderWidget()
        self.minSegmentsSlider.singleStep = 1
        self.minSegmentsSlider.minimum = 2
        self.minSegmentsSlider.maximum = 12
        self.minSegmentsSlider.value = 3
        self.minSegmentsSlider.setDecimals(0)
        self.minSegmentsSlider.setToolTip(
            "Minimum number of segments to produce. The algorithm will stop if it finds fewer."
        )

        self.processingResolutionSlider = ctk.ctkSliderWidget()
        self.processingResolutionSlider.singleStep = 1
        self.processingResolutionSlider.minimum = 100
        self.processingResolutionSlider.maximum = 3000
        self.processingResolutionSlider.value = 1000
        self.processingResolutionSlider.setDecimals(0)
        self.processingResolutionSlider.setToolTip(
            "Image height will be downscaled to this many pixels for processing. The result will be upscaled to the original size."
        )
        parametersLayout = qt.QFormLayout(parametersSection)
        parametersLayout.addRow("Minimum segments:", self.minSegmentsSlider)
        parametersLayout.addRow("Processing resolution:", self.processingResolutionSlider)

        # Output section
        self.outputSection = ctk.ctkCollapsibleButton()
        self.outputSection.text = "Output"
        self.outputSection.collapsed = False
        self.outputSection.visible = False

        self.outputNameEdit = qt.QLineEdit()
        outputFormLayout = qt.QFormLayout(self.outputSection)
        outputFormLayout.addRow("Output name:", self.outputNameEdit)

        self.segmentsTable = slicer.qMRMLSegmentsTableView()
        self.segmentsTable.setStatusColumnVisible(False)
        self.segmentsTable.setOpacityColumnVisible(False)
        outputFormLayout.addRow(self.segmentsTable)

        mergeVisibleSegmentsButton = qt.QPushButton("Merge visible segments")
        mergeVisibleSegmentsButton.setToolTip("Merge all visible segments of the output segmentation into one segment.")
        mergeVisibleSegmentsButton.clicked.connect(self.onMergeVisibleSegments)
        outputFormLayout.addRow(mergeVisibleSegmentsButton)

        self.applyButton = ui.ApplyButton(
            onClick=self.onApplyButtonClicked, tooltip="Run segmentation algorithm", enabled=True
        )

        self.cliProgressBar = LocalProgressBar()

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(self.applyButton)
        self.layout.addWidget(self.cliProgressBar)
        self.layout.addWidget(self.outputSection)
        self.layout.addStretch(1)

        self.onInputChanged()

    def onInputChanged(self):
        node = self.inputSelector.currentNode()
        self.applyButton.enabled = node is not None

        if node is not None:
            shape = slicer.util.arrayFromVolume(node).shape
            imageHeight = shape[1]
            self.processingResolutionSlider.maximum = min(imageHeight, 3000)
        else:
            self.processingResolutionSlider.maximum = 3000

    def onApplyButtonClicked(self, state):
        logic = UnsupervisedSegmentationLogic()
        logic.segmentationFinished.connect(self.onSegmentationFinished)
        logic.apply(
            inputNode=self.inputSelector.currentNode(),
            extraInputNode=self.extraInputSelector.currentNode(),
            resolution=self.processingResolutionSlider.value,
            minSegments=self.minSegmentsSlider.value,
            progressBar=self.cliProgressBar,
        )
        self.outputSection.visible = False

    def onOutputNameChanged(self):
        text = self.outputNameEdit.text.strip()
        self.outputSegmentationNode.SetName(text)

    def onSegmentationFinished(self, segmentationNode):
        if self.outputSegmentationNode is not None:
            prevDisplayNode = self.outputSegmentationNode.GetDisplayNode()
            if prevDisplayNode:
                prevDisplayNode.SetVisibility(False)

        self.outputSegmentationNode = segmentationNode
        self.outputNameEdit.setText(segmentationNode.GetName())
        self.outputNameEdit.editingFinished.connect(self.onOutputNameChanged)
        self.segmentsTable.setSegmentationNode(segmentationNode)
        self.outputSection.visible = True

    def onMergeVisibleSegments(self, state):
        mergeVisibleSegments(self.outputSegmentationNode)


def make_colors_distinct(colors, min_distance=0.5):
    colors = colors.copy()
    for i in range(len(colors)):
        color_a = colors[i]
        for color_b in colors[:i]:
            distance = distinctipy.color_distance(color_a, color_b)
            if distance < min_distance:
                colors[i] = distinctipy.get_colors(1, colors[:i].tolist())[0]
                break
    return colors


def mergeVisibleSegments(segmentationNode):
    labelmap = createTemporaryNode(
        cls=slicer.vtkMRMLLabelMapVolumeNode,
        name=f"{segmentationNode.GetName()}_Merged",
    )
    logic = slicer.modules.segmentations.logic()
    logic.ExportVisibleSegmentsToLabelmapNode(segmentationNode, labelmap)

    # Remove all visible segments
    segmentation = segmentationNode.GetSegmentation()
    display = segmentationNode.GetDisplayNode()
    for segmentId in segmentation.GetSegmentIDs():
        if display.GetSegmentVisibility(segmentId):
            segmentation.RemoveSegment(segmentId)
    array = slicer.util.arrayFromVolume(labelmap)
    array[array > 0] = 1
    slicer.util.updateVolumeFromArray(labelmap, array)
    logic.ImportLabelmapToSegmentationNode(labelmap, segmentationNode)

    removeTemporaryNodes()


class UnsupervisedSegmentationLogic(LTracePluginLogic):
    segmentationFinished = qt.Signal(slicer.vtkMRMLSegmentationNode)

    def __init__(self):
        LTracePluginLogic.__init__(self)

    def apply(self, inputNode, extraInputNode, resolution, minSegments, progressBar):
        outputNode = createTemporaryNode(
            cls=slicer.vtkMRMLLabelMapVolumeNode,
            name=f"{inputNode.GetName()}_LabelMap",
            environment=self.__class__.__name__,
            hidden=True,
        )

        self.imageNode = inputNode

        self.colorTablePath = Path(slicer.app.temporaryPath) / f"UnsupervisedSegColors_{round(time.time() * 1000)}.npy"
        cliConfig = {
            "inputVolume": inputNode.GetID(),
            "extraInputVolume": extraInputNode.GetID() if extraInputNode else None,
            "resolution": resolution,
            "minLabelNum": minSegments,
            "outputVolume": outputNode.GetID(),
            "colorTablePath": self.colorTablePath.as_posix(),
        }

        self.cliNode = slicer.cli.run(
            slicer.modules.unsupervisedsegmentationcli,
            None,
            cliConfig,
            wait_for_completion=False,
        )
        self.cliNodeModifiedObserver = self.cliNode.AddObserver(
            "ModifiedEvent", lambda c, ev, info=cliConfig: self.onCliModifiedEvent(c, ev, info)
        )

        if progressBar is not None:
            progressBar.visible = True
            progressBar.setCommandLineModuleNode(self.cliNode)

    def onCliModifiedEvent(self, caller, event, info):
        if not self.cliNode:
            return

        if caller is None:
            self.cliNode = None
            return

        if caller.IsBusy():
            return

        if caller.GetStatusString() == "Completed":
            labelmapNode = tryGetNode(info["outputVolume"])

            colors = np.load(self.colorTablePath)
            os.unlink(self.colorTablePath)

            colors = colors / 255
            colors[1:] = make_colors_distinct(colors[1:])
            colorNames = [f"Segment_{i}" for i in range(colors.shape[0])]
            colorTable = create_color_table(f"{self.imageNode.GetName()}_Colors", colors, colorNames)
            labelmapNode.GetDisplayNode().SetAndObserveColorNodeID(colorTable.GetID())

            segmentationNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSegmentationNode", f"{self.imageNode.GetName()}_Segmentation"
            )
            segmentationNode.CreateDefaultDisplayNodes()
            segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(self.imageNode)

            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapNode, segmentationNode)
            slicer.util.setSliceViewerLayers(background=self.imageNode)
            segmentationNode.GetDisplayNode().SetVisibility(True)
            self.segmentationFinished.emit(segmentationNode)
        removeTemporaryNodes(environment=self.__class__.__name__)

        if self.cliNodeModifiedObserver is not None:
            self.cliNode.RemoveObserver(self.cliNodeModifiedObserver)
            self.cliNodeModifiedObserver = None

        self.cliNode = None
