import copy
import json
import logging
import os
from pathlib import Path
from typing import List

import ctk
import matplotlib.colors as mcolors
import numpy as np
import qt
import slicer
from ltrace.image.optimized_transforms import binset, DEFAULT_NULL_VALUES
from ltrace.slicer.helpers import setDimensionFrom, getVolumeNullValue
from ltrace.slicer.slicer_matplotlib import MatplotlibCanvasWidget
from ltrace.slicer.ui import hierarchyVolumeInput, volumeInput
from ltrace.slicer_utils import (
    LTracePlugin,
    LTracePluginWidget,
    LTracePluginLogic,
    LTracePluginTest,
)

from collections import deque
from functools import lru_cache

COLORS = [mcolors.TABLEAU_COLORS[name] for name in mcolors.TABLEAU_COLORS]


class Segment:
    @staticmethod
    def defaultName(index: int):
        return f"Class {index}"

    @staticmethod
    def defaultValue(*args):
        return 65535

    @staticmethod
    def defaultColor(*args):
        global COLORS
        color = np.random.choice(COLORS, 1, replace=False)[0]
        return color

    DEFAULT_PREFIX = "Class"
    DEFAULT_THRESH = 65535
    DEFAULT_COLOR_TABLE = list(range(len(COLORS)))
    np.random.shuffle(DEFAULT_COLOR_TABLE)
    CURRENT_COLOR_TABLE_INDEX = 0

    def __init__(self, name=None, value=DEFAULT_THRESH, color=None):
        self.name = name or f"{Segment.DEFAULT_PREFIX}_{int(np.random.random()*1000)}"
        self.upper_threshold = value
        self.color = color or COLORS[Segment.DEFAULT_COLOR_TABLE[Segment.CURRENT_COLOR_TABLE_INDEX]]
        Segment.CURRENT_COLOR_TABLE_INDEX = (Segment.CURRENT_COLOR_TABLE_INDEX + 1) % len(Segment.DEFAULT_COLOR_TABLE)

    def __iter__(self):
        for value in [self.name, self.upper_threshold, self.color]:
            yield value

    @classmethod
    def toJson(cls, segments: list):
        out = []
        for segment in segments:
            if not isinstance(segment, cls):
                continue
            out.append(tuple(segment))
        return json.dumps(out)


def getNodeById(itemId):
    subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    return subjectHierarchyNode.GetItemDataNode(itemId)


class ColorPickerCell(qt.QWidget):
    def __init__(self, *args, color="#333333", **kwargs):
        super().__init__(*args, **kwargs)

        self.setLayout(qt.QVBoxLayout())

        button = qt.QPushButton("+")
        button.setFixedSize(20, 20)
        button.setStyleSheet(
            "QPushButton {"
            "font-size:11px;"
            f"color:{color};"
            f"background-color:{color};"
            "border: 2px solid #222222 }"
        )

        layout = self.layout()
        layout.addWidget(button)
        layout.setAlignment(qt.Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)

        self.clicked = lambda color: None

        def on_clicked():
            new_color = qt.QColorDialog.getColor()
            if new_color.isValid():
                button.setStyleSheet(
                    "QPushButton {"
                    "font-size:11px;"
                    f"color:{new_color};"
                    f"background-color:{new_color};"
                    "border: 2px solid #222222 }"
                )

                self.clicked(new_color.name())

        button.clicked.connect(on_clicked)


#
# HistogramSegmenter
#
class HistogramSegmenter(LTracePlugin):
    SETTING_KEY = "HistogramSegmenter"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Histogram Segmenter"
        self.parent.categories = ["Image Log"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]  # replace with "Firstname Lastname (Organization)"
        self.parent.helpText = HistogramSegmenter.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


#
# HistogramSegmenterWidget
#
class HistogramSegmenterWidget(LTracePluginWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        """ Slots """
        self.onInputChanged = lambda node: None
        self.onHistogramUpdated = lambda segments: None
        self.onSegmentationCompleted = lambda nodeIn, nodeOut, segments: None
        """----------------------------"""

        self.startCloseEventHandler = None
        self.inputParentId = None

        self.toolWidgets = []

        self.logic = HistogramSegmenterLogic(self)

    def setup(self):
        LTracePluginWidget.setup(self)

        if not self.startCloseEventHandler:
            self.startCloseEventHandler = slicer.mrmlScene.AddObserver(
                slicer.mrmlScene.StartCloseEvent, self.onCloseScene
            )

        # Instantiate and connect widgets ...

        #
        # Parameters Area
        #
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Segmentation"
        self.layout.addWidget(parametersCollapsibleButton)

        # Layout within the dummy collapsible button
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

        #
        # input volume selector
        #
        inputFrame = qt.QHBoxLayout()

        self.inputSelector = hierarchyVolumeInput(onChange=self.onSelect, nodeTypes=["vtkMRMLScalarVolumeNode"])
        self.inputSelector.selectorWidget.setHideChildNodeTypes(
            ["vtkMRMLVectorVolumeNode", "vtkMRMLTensorVolumeNode", "vtkMRMLStreamingVolumeNode"]
        )

        self.inputSelector.setToolTip("Pick the input to the algorithm.")
        self.inputSelector.setStyleSheet("QComboBox {font-size: 11px; font-weight: bold; padding: 6px;}")

        inputSelectorCleanBtn = qt.QPushButton("")
        inputSelectorCleanBtn.icon = qt.QIcon(":/Icons/ClearSelection.png")
        inputSelectorCleanBtn.setToolTip("Clear current selection")
        inputSelectorCleanBtn.clicked.connect(self.onClearSelectionButtonClicked)

        inputFrame.addWidget(self.inputSelector)
        inputFrame.addWidget(inputSelectorCleanBtn)

        parametersFormLayout.addRow("Input Volume: ", inputFrame)

        self.figureGroup = qt.QWidget()
        figureGroupLayout = qt.QHBoxLayout(self.figureGroup)

        tableGroupLayout = qt.QVBoxLayout()

        self.tableWidget = qt.QTableWidget()
        self.tableWidget.setFixedWidth(320)
        self.tableWidget.setFixedHeight(256)
        self.tableWidget.setColumnCount(3)
        self.tableWidget.setHorizontalHeaderLabels(["Class", "Color", "Maximum"])
        self.tableWidget.horizontalHeader().setStretchLastSection(True)
        self.tableWidget.setShowGrid(False)
        self.tableWidget.setAlternatingRowColors(False)
        self.tableWidget.setSelectionBehavior(self.tableWidget.SelectRows)
        self.tableWidget.setSelectionMode(self.tableWidget.ExtendedSelection)
        # self.tableWidget.selectionModel().selectionChanged.connect(
        #   self._on_table_selection_changed
        # )
        #
        self.tableWidget.cellChanged.connect(self.onTableEdited)

        tableGroupLayout.addWidget(self.tableWidget)
        tableGroupLayout.addLayout(self.buildControls())

        figureGroupLayout.addLayout(tableGroupLayout)

        self.figureWidget = MatplotlibCanvasWidget()
        histWidget = self.figureWidget.getPythonQtWidget()
        self.figureWidget.setFixedHeight(256)
        self.figureWidget.figure.set_figwidth(2.56)
        self.figure = self.figureWidget.figure
        self.figure.set_facecolor("#313131")
        self.figureWidget.axes = self.figure.subplots(1, 1)
        self.figureWidget.axes.patch.set_facecolor("#313131")
        # self.figureWidget.axes.hist(np.array([]), bins=20, log=True, color="steelblue")
        self.figureWidget.axes.tick_params(colors="gray", which="both")

        for label in self.figureWidget.axes.get_xticklabels() + self.figureWidget.axes.get_yticklabels():
            label.set_fontsize(8)
            label.set_color("white")

        self.figureWidget.axes.spines["bottom"].set_color("gray")
        self.figureWidget.axes.spines["top"].set_color("gray")
        self.figureWidget.axes.spines["left"].set_color("gray")
        self.figureWidget.axes.spines["right"].set_color("gray")

        self.figure.set_tight_layout(True)

        figureGroupLayout.addWidget(histWidget)

        self.loadingInfoLabel = qt.QLabel("")
        self.loadingInfoLabel.visible = False
        parametersFormLayout.addRow(self.loadingInfoLabel)
        parametersFormLayout.addRow(self.figureGroup)

        #
        # output volume selector
        #
        self.outputSelector = volumeInput(hasNone=True, nodeTypes=["vtkMRMLLabelMapVolumeNode"])
        # self.outputSelector = slicer.qMRMLNodeComboBox()
        # self.outputSelector.nodeTypes = ["vtkMRMLLabelMapVolumeNode"]
        # self.outputSelector.selectNodeUponCreation = True
        self.outputSelector.addEnabled = True
        self.outputSelector.removeEnabled = True
        self.outputSelector.renameEnabled = True
        # self.outputSelector.noneEnabled = True
        # self.outputSelector.showHidden = False
        # self.outputSelector.showChildNodeTypes = False
        # self.outputSelector.setMRMLScene(slicer.mrmlScene)
        self.outputSelector.setToolTip("Pick the output to the algorithm.")
        self.outputSelector.enabled = False
        parametersFormLayout.addRow("Output Volume: ", self.outputSelector)

        #
        # Apply Button
        #
        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.toolTip = "Run the algorithm."
        self.applyButton.enabled = False

        self.applyButton.setStyleSheet("QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 4px}")
        self.applyButton.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Minimum)

        parametersFormLayout.addRow(self.applyButton)

        # connections
        self.applyButton.connect("clicked(bool)", self.onApplyButton)
        self.outputSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSelectOutput)

        # Add vertical spacer
        self.layout.addStretch(1)

    def buildControls(self):

        buttonsLayout = qt.QHBoxLayout()

        buttons = [
            (":/Icons/Add.png", self.onClassInsertion, "Add another class"),
            (":/Icons/Remove.png", self.onClassRemoval, "Remove selected class"),
            (
                self.tableWidget.style().standardIcon(getattr(qt.QStyle, "SP_BrowserReload")),
                self.onReloadHistogram,
                "Recalculate class distribution",
            ),
        ]

        for conf in buttons:
            btn = qt.QPushButton("")
            btn.icon = qt.QIcon(conf[0])
            btn.setToolTip(conf[2])
            btn.clicked.connect(conf[1])
            buttonsLayout.addWidget(btn)

        return buttonsLayout

    def updateLoadingInfo(self, text=None):
        if text is None:
            self.loadingInfoLabel.setText("")
            self.loadingInfoLabel.visible = False
        else:
            self.loadingInfoLabel.setText(text)
            self.loadingInfoLabel.visible = True

    def onCloseScene(self, *args):
        self.fillTable([])
        self.redrawHistogram([], None)

    def onClearSelectionButtonClicked(self):
        self.inputSelector.clearSelection()
        self.updateLoadingInfo()

    def onSelect(self, itemId):
        self.updateLoadingInfo("Loading (step 1/3) ...")

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        self.inputParentId = subjectHierarchyNode.GetItemParent(itemId)

        inputVolumeNode = subjectHierarchyNode.GetItemDataNode(itemId)

        if inputVolumeNode is None:
            self.fillTable([])
            self.redrawHistogram([], None)
            return

        self.outputSelector.baseName = str(inputVolumeNode.GetName())
        self.outputSelector.enabled = True

        self.updateLoadingInfo("Clustering (step 2/3)...")
        self.logic.createHistogram(inputVolumeNode, k=5)

        self.updateLoadingInfo()

        self.onInputChanged(inputVolumeNode.GetID())

    def onSelectOutput(self, outputVolumeNode):
        if outputVolumeNode is None:
            return

        try:
            subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

            dir_id = subjectHierarchyNode.GetItemChildWithName(self.inputParentId, "Segmentations")
            if dir_id == 0:
                dir_id = subjectHierarchyNode.CreateFolderItem(self.inputParentId, "Segmentations")
                subjectHierarchyNode.SetItemAttribute(dir_id, "ScalarVolumeType", "WellProfile")

            slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene).CreateItem(
                dir_id, outputVolumeNode
            )

            setDimensionFrom(getNodeById(self.inputSelector.currentItem()), outputVolumeNode)
            self.applyButton.enabled = True
        except AttributeError as ae:
            print(repr(ae))

    def onReloadHistogram(self):
        inputVolumeNode = getNodeById(self.inputSelector.currentItem())
        self.logic.updateHistogram(inputVolumeNode, only_thresholds=True)

    def onClassRemoval(self):
        rows = sorted(set(index.row() for index in self.tableWidget.selectionModel().selectedIndexes))
        self.logic.dumpSegments(rows)

    def onClassInsertion(self):
        self.logic.appendDefaultSegment()

    def onTableEdited(self, row, col):
        if col == 0:  # edited name
            name_item = self.tableWidget.item(row, col)
            self.logic.segmentName(row, str(name_item.text()))
        elif col == 2:  # edited value
            value_item = self.tableWidget.item(row, col)
            value_f = float(str(value_item.text()))
            self.logic.segmentUpperThreshold(row, value_f)

    def onColorEdited(self, row, color):
        self.logic.segmentColor(row, color)

    def fillTable(self, segments: List[Segment]):
        oldState = self.tableWidget.blockSignals(True)

        self.tableWidget.clearContents()

        self.tableWidget.setRowCount(len(segments))

        for i, segment in enumerate(segments):
            classItem = qt.QTableWidgetItem(segment.name)
            self.tableWidget.setItem(i, 0, classItem)

            colorWidget = ColorPickerCell(color=segment.color)
            colorWidget.clicked = lambda color, index=i: self.onColorEdited(index, color)
            self.tableWidget.setCellWidget(i, 1, colorWidget)

            val = "undef" if segment.upper_threshold is None else str(segment.upper_threshold)

            valueItem = qt.QTableWidgetItem(val)
            self.tableWidget.setItem(i, 2, valueItem)

        self.tableWidget.blockSignals(oldState)

    def redrawHistogram(self, values, segments, bins="auto"):
        self.figureWidget.axes.cla()
        fig = self.figureWidget.figure

        if len(values) > 0:
            if isinstance(bins, int):
                bins = binset(values)
            N, ticks, patches = self.figureWidget.axes.hist(values, bins=bins, log=True, color="steelblue")
            bin_index = deque(range(1, len(ticks)))
            for segment in segments:
                if segment.upper_threshold is None:
                    continue
                while len(bin_index) > 0 and ticks[bin_index[0]] <= segment.upper_threshold:
                    patches[bin_index[0] - 1].set_facecolor(segment.color)
                    bin_index.popleft()

        fig.set_tight_layout(True)
        self.figureWidget.draw()

    def redrawView(self, values, segments, only_histogram=False, bins="auto"):
        if not only_histogram:
            self.fillTable(segments)
        self.redrawHistogram(values, segments, bins)
        self.onHistogramUpdated(segments)

    def onApplyButton(self):
        inputVolumeNode = getNodeById(self.inputSelector.currentItem())
        outputVolumeNode = self.outputSelector.currentNode()
        self.logic.apply(inputVolumeNode, outputVolumeNode)
        self.onSegmentationCompleted(inputVolumeNode.GetID(), outputVolumeNode.GetID(), self.logic.copySegments())


#
# HistogramSegmenterLogic
#
class HistogramSegmenterLogic(LTracePluginLogic):

    MAX_SAMPLES = int(3e5)

    def __init__(self, view: HistogramSegmenterWidget):
        super().__init__()

        self.view = view
        self.segments: List[Segment] = []
        self.defaults = {}

        self.nullValue = lambda: self.defaults.get("nullableValue", DEFAULT_NULL_VALUES)

    @staticmethod
    def hasImageData(volumeNode):
        if not volumeNode:
            logging.debug("hasImageData failed: no volume node")
            return False
        if volumeNode.GetImageData() is None:
            logging.debug("hasImageData failed: no image data in volume node")
            return False
        return True

    @staticmethod
    def isValidInputOutputData(inputVolumeNode, outputVolumeNode):
        """Validates if the output is not the same as input"""
        if not inputVolumeNode:
            logging.debug("isValidInputOutputData failed: no input volume node defined")
            return False
        if not outputVolumeNode:
            logging.debug("isValidInputOutputData failed: no output volume node defined")
            return False
        if inputVolumeNode.GetID() == outputVolumeNode.GetID():
            logging.debug(
                "isValidInputOutputData failed: input and output volume is the same. Create a new volume for output to avoid this error."
            )
            return False
        return True

    def pooling(self, voxelArray, max_samples):
        voxelArray1D = voxelArray.ravel()
        voxelArrayPool = np.zeros(max_samples + 1)
        if voxelArray1D.size > max_samples:
            samples = np.linspace(0, voxelArray1D.size - 1, max_samples, dtype=int)
            voxelArrayPool[0:-1] = voxelArray1D[samples]
        else:
            voxelArrayPool[0 : len(voxelArray1D)] = voxelArray1D
        voxelArrayPool[-1] = np.max(voxelArray)
        voxelArrayPool.sort()
        return np.around(voxelArrayPool, 4)

    @lru_cache(maxsize=None)
    def sampleDataset(self, node):
        inputVoxelArray = slicer.util.arrayFromVolume(node)
        nullValue = getVolumeNullValue(node) or self.nullValue()
        return self.pooling(inputVoxelArray[inputVoxelArray != nullValue], self.MAX_SAMPLES)

    def getTransitions(self, values: np.ndarray, labelmap, centroids):
        transitions = np.ones(len(centroids)) * -np.inf
        for value, cls in zip(values.ravel(), labelmap.ravel()):
            transitions[cls] = max(transitions[cls], value)
        return sorted(set(t for t in transitions if t > -np.inf))

    def updateHistogram(self, node, only_thresholds=False):
        # -------------------------------------------- keep those on top
        from scipy.cluster.vq import kmeans2

        # -------------------------------------------- keep those on top
        values = self.sampleDataset(node)
        seeds = np.array([s.upper_threshold for s in self.segments])
        centroids, labelmap = kmeans2(values, k=seeds, iter=10, minit="points")
        transitions = self.getTransitions(values, labelmap, centroids)

        if only_thresholds and len(self.segments) > 0:
            for thr, segment in zip(transitions, self.segments):
                segment.upper_threshold = thr
        else:
            self.segments = [
                Segment(f"Class {i}", value=t) for i, t in zip(range(1, len(transitions) + 1), transitions)
            ]

        # close guarantee
        self.segments[-1].upper_threshold = values[-1]

        self._updateView()

    def createHistogram(self, node, k=None):
        # -------------------------------------------- keep those on top
        from scipy.cluster.vq import kmeans2

        self.sampleDataset.cache_clear()
        # -------------------------------------------- keep those on top

        if k is None:
            k = len(self.segments) or 2
        values = self.sampleDataset(node)
        centroids, labelmap = kmeans2(values, k, iter=100, minit="points")
        transitions = self.getTransitions(values, labelmap, centroids)

        self.segments = [Segment(f"Class {i}", value=t) for i, t in zip(range(1, len(transitions) + 1), transitions)]

        # close guarantee
        self.segments[-1].upper_threshold = values[-1]

        self._updateView()

    def _addOrCreateColorMap(self, name):
        try:
            colorNode = slicer.util.getNode(name)
        except slicer.util.MRMLNodeNotFoundException as e:
            colorNode = slicer.vtkMRMLColorTableNode()
            colorNode.SetTypeToUser()
            colorNode.SetName(name)
            colorNode.SetHideFromEditors(0)
            slicer.mrmlScene.AddNode(colorNode)
        return colorNode

    def apply(self, inputVolume, outputVolume):
        from PIL import ImageColor

        if not self.isValidInputOutputData(inputVolume, outputVolume):
            slicer.util.errorDisplay("Input volume is the same as output volume. Choose a different output volume.")
            return False

        if not self.hasImageData(inputVolume):
            slicer.util.errorDisplay("Input volume is missing Image Data")
            return False

        logging.info("Processing started")

        inputVoxelArray = slicer.util.arrayFromVolume(inputVolume)
        outputVoxelArray = np.zeros(inputVoxelArray.shape, dtype=np.uint8)

        last_value = np.min(inputVoxelArray)

        colorNode = self._addOrCreateColorMap(f"{outputVolume.GetName()}_ColorMap")
        colorNode.NamesInitialisedOff()
        colorNode.ClearNames()
        colorNode.SetNumberOfColors(1 + len(self.segments))

        colorNode.SetColor(0, "(none)", 0.0, 0.0, 0.0, 0.0)

        for i, segment in enumerate(self.segments, start=1):
            outputVoxelArray[(last_value < inputVoxelArray) & (inputVoxelArray <= segment.upper_threshold)] = i
            rgb = [channel / 256 for channel in ImageColor.getrgb(segment.color)]
            colorNode.SetColor(i, segment.name, *rgb)
            last_value = segment.upper_threshold

        colorNode.NamesInitialisedOn()

        displayNode = slicer.vtkMRMLLabelMapVolumeDisplayNode()
        slicer.mrmlScene.AddNode(displayNode)
        displayNode.SetAndObserveColorNodeID(colorNode.GetID())
        outputVolume.SetAndObserveDisplayNodeID(displayNode.GetID())

        outputVolume.SetAndObserveImageData(None)
        slicer.util.updateVolumeFromArray(outputVolume, outputVoxelArray)
        outputVolume.Modified()

        logging.info("Processing completed")

        return True

    def copySegments(self):
        return copy.deepcopy(self.segments)

    def appendDefaultSegment(self):
        new_pos = len(self.segments) + 1
        self.segments.append(Segment(f"Class {new_pos}"))
        self._updateView()

    def dumpSegments(self, indexes):
        targets = set(indexes)
        self.segments = [segment for i, segment in enumerate(self.segments) if i not in targets]
        self._updateView()

    def segmentName(self, index, name):
        self.segments[index].name = name
        self._updateView()

    def segmentUpperThreshold(self, index, value):
        self.segments[index].upper_threshold = value
        self._updateView()

    def segmentColor(self, index, color):
        self.segments[index].color = color
        self._updateView(only_histogram=True)

    def _updateView(self, only_histogram=False):
        node = getNodeById(self.view.inputSelector.currentItem())
        segments = copy.deepcopy(self.segments)
        bin_method = 256 if node.IsA("vtkMRMLLabelMapVolumeNode") == 1 else "fd"
        self.view.redrawView(self.sampleDataset(node), segments, only_histogram, bins=bin_method)


# TODO check this method in the future
# def kdeCluster(self, values, k=3, **kwargs):
#     from sklearn.neighbors import KernelDensity
#     from scipy.signal import argrelextrema
#
#     k =
#     kde = KernelDensity(kernel='gaussian', bandwidth=k).fit(values[:, np.newaxis])
#     min_, max_ = np.min(values), np.max(values)
#     s = np.linspace(min_, max_)
#     e = kde.score_samples(s.reshape(-1, 1))
#     prob = argrelextrema(e, np.less)[0]
#     turns = [*s[prob], max_]
#     labelmap = np.zeros(values.shape) + 65535
#     for i, turn in enumerate(turns):
#         labelmap[(labelmap != 65535) & (values < turn)] = i
#
#     print(turns)
#
#     return turns, labelmap
