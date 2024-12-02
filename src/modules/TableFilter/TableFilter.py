import copy
import ctk
import importlib

import ltrace.slicer.widget.color_picker_cell as ColorPicker
import numpy as np
import os
import pandas as pd
import pyqtgraph as pg
import PySide2 as ps
import qt
import slicer
import time

from functools import lru_cache, partial
from ltrace.slicer import ui, helpers, widgets
from ltrace.slicer.helpers import getPythonQtWidget, tryGetNode
from ltrace.slicer_utils import *
from numpy.random import RandomState
from pathlib import Path
from PIL import ImageColor
from sklearn.cluster import KMeans
from slicer.util import dataframeFromTable
from typing import List


CLUSTER_COUNT_WARNING = 50


class Filter:
    def __init__(self, column, filterData: List = None):
        self.column = column
        self.filterData = filterData or []

    def add(self, rule):
        self.filterData.append(rule)

    def __str__(self):
        return ", ".join([repr(val) for val in self.filterData if len(repr(val)) > 0])

    def __repr__(self):
        return str(self)


import matplotlib.colors as mcolors

_COLORS = [mcolors.TABLEAU_COLORS[name] for name in mcolors.TABLEAU_COLORS]
_DEFAULT_COLOR_TABLE = list(range(len(_COLORS)))
_CURRENT_COLOR_TABLE_INDEX = 0
_RANDOMSTATE = RandomState(478126)


def _RESET_COLOR_QUEUE():
    global _CURRENT_COLOR_TABLE_INDEX, _RANDOMSTATE
    _CURRENT_COLOR_TABLE_INDEX = 0
    _RANDOMSTATE = RandomState(4326)
    _RANDOMSTATE.shuffle(_DEFAULT_COLOR_TABLE)


def _NEXT_COLOR():
    global _CURRENT_COLOR_TABLE_INDEX
    newColor = _COLORS[_DEFAULT_COLOR_TABLE[_CURRENT_COLOR_TABLE_INDEX]]
    _CURRENT_COLOR_TABLE_INDEX = (_CURRENT_COLOR_TABLE_INDEX + 1) % len(_DEFAULT_COLOR_TABLE)
    return newColor


def SegmentTuple(label, name, minimum, maximum, color=None, visible=True, discrete=False):
    color_ = color or _NEXT_COLOR()
    segment = None
    if discrete:
        segment = DiscreteTuple(label, name, color_, visible)
    else:
        segment = ContinuousTuple(label, name, minimum, maximum, color_, visible)

    return segment


class DiscreteTuple(object):

    COLUMNS = " ", " ", "Name"

    def __init__(self, label, name, color=None, visible=True):
        self.label = label
        self.name = name
        self.color = color or _NEXT_COLOR()
        self.visible = visible

    def index(self, values):
        try:
            value = type(values.iloc[0])(self.name)
        except (ValueError, IndexError) as error:
            print_debug(error)
        else:
            return values == value

        return None

    def setValues(self, *args):
        self.label = args[0]

    def getValues(self):
        return (self.label,)

    def __str__(self):
        if not self.visible:
            return ""
        return f"{self.name}"

    def __repr__(self):
        return str(self)


class ContinuousTuple(DiscreteTuple):

    COLUMNS = " ", " ", "Name", "Min", "Max"

    def __init__(self, label, name, minimum, maximum, color=None, visible=True):
        super(ContinuousTuple, self).__init__(label, name, color, visible)

        self.minimum = minimum
        self.maximum = maximum

    def index(self, values: np.ndarray):
        return (values >= self.minimum) & (values <= self.maximum)

    def setValues(self, *args):
        self.minimum = args[0]
        self.maximum = args[1]

    def getValues(self):
        return self.minimum, self.maximum

    def __str__(self):
        if not self.visible:
            return ""
        return f"{self.minimum} <= [{self.name}] <= {self.maximum}"

    def __repr__(self):
        return str(self)


class TableFilter(LTracePlugin):
    SETTING_KEY = "TableFilter"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Table Filter"
        self.parent.categories = ["Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = ""
        self.parent.helpText += TableFilter.help()
        self.parent.acknowledgementText = ""

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


def shadowNode(refNode):
    mutableNode = getShadowNode(refNode)

    if not mutableNode:
        oldNode = tryGetNode(shadowNodeName(refNode) + "*")
        if oldNode:
            slicer.mrmlScene.RemoveNode(oldNode)

        mutableNode = helpers.createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, shadowNodeName(refNode))
        mutableNode.CopyOrientation(refNode)

        # Set new color table
        colorNode = slicer.vtkMRMLColorTableNode()
        colorNode.SetTypeToUser()
        colorNode.SetName(str(mutableNode.GetID()) + "_ColorMap")
        colorNode.SetHideFromEditors(0)
        slicer.mrmlScene.AddNode(colorNode)
        mutableNode.GetDisplayNode().SetAndObserveColorNodeID(colorNode.GetID())

    return mutableNode


def getShadowNode(refNode):
    return tryGetNode(shadowNodeName(refNode) + "*")


def shadowNodeName(refNode):
    return f"{refNode.GetID()}_SLIDER_LABELMAP_TMP"


class TableFilterWidget(LTracePluginWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.logic: TableFilterLogic = None
        self.currentReferenceNode = None

    def setup(self):
        LTracePluginWidget.setup(self)

        self.setupUI()

        # Add vertical spacer
        self.layout.addStretch(1)

    def onReload(self) -> None:
        LTracePluginWidget.onReload(self)
        importlib.reload(ColorPicker)
        importlib.reload(ui)

    def setupUI(self):
        self.tableSelector = ui.hierarchyVolumeInput(
            onChange=self.setTableReference,
            hasNone=True,
            nodeTypes=["vtkMRMLTableNode"],
        )
        self.tableSelector.setToolTip("Table Node of shape (n_segments, n_features)")

        self.referenceNodeSelector = ui.hierarchyVolumeInput(
            onChange=self.onReferenceNodeChanged,
            hasNone=True,
            nodeTypes=[
                "vtkMRMLLabelMapVolumeNode",
                "vtkMRMLSegmentationNode",
                "vtkMRMLScalarVolumeNode",
            ],
        )
        self.referenceNodeSelector.setToolTip("LabelMap Node segmented according to the above table node.")
        # Table should automatically set this input, otherwise,
        # select it manually by enabling it first
        self.referenceNodeSelector.enabled = False

        self.groupBySelector = qt.QComboBox()

        self.filterByCountSlider = self.buildSliderFilterByCount()
        self.filterByCountSlider.setToolTip("Select the total number of partition to be shown.")

        inputSection = ctk.ctkCollapsibleButton()
        inputSection.text = "Input"
        inputSection.collapsed = False
        inputSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        inputFormLayout = qt.QFormLayout(inputSection)
        inputFormLayout.addRow("Table: ", self.tableSelector)

        labelmapBox = qt.QHBoxLayout()
        labelmapBox.addWidget(self.referenceNodeSelector)
        # TODO (PL-1081): Doesn't show 'Linked' checkbox until its logic implementation is done.
        # manualReferenceSetOption = ui.CheckBoxWidget(checked=True, onToggle=lambda widget, toggled: None)
        # labelmapBox.addWidget(ui.Row([manualReferenceSetOption, qt.QLabel(" Linked")]))

        self.filterControlSlider = widgets.LTraceDoubleRangeSlider(step=0.01)
        self.filterControlSlider.setRange(-0.5, 7.5)
        self.filterControlSlider.setInitState(-0.5, 7.5)
        self.filterControlSlider.setStep(0.5)

        self.colorByTextLabel = qt.QLabel("No labels")
        self.colorByTextLabel.setStyleSheet("QLabel {padding: 4px;}")
        self.colorByTextLabel.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Minimum)

        self.colorBySetButton = qt.QPushButton("Set")
        self.colorBySetButton.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        self.filterList = qt.QListWidget()
        self.filterAddButton = qt.QPushButton("New")
        self.filterDelButton = qt.QPushButton("Remove")
        self.filterEditButton = qt.QPushButton("Edit")

        filter_Grid = ui.Row(
            [
                self.filterList,
                ui.Col([self.filterAddButton, self.filterEditButton, self.filterDelButton]),
            ]
        )

        inputFormLayout.addRow("Labelmap: ", labelmapBox)

        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False
        parametersSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        paremetersFormLayout = qt.QFormLayout(parametersSection)

        paremetersFormLayout.addRow(
            "Color by: ",
            ui.Row(
                [
                    self.colorByTextLabel,
                    self.colorBySetButton,
                ]
            ),
        )

        self.resultSuffix = qt.QLineEdit()
        self.resultSuffix.setText("Filtered")

        self.numberOfRowsLabel = qt.QLabel("")

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.toolTip = "Save to dataframe."
        self.applyButton.enabled = True
        self.applyButton.setStyleSheet("QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 0px}")
        self.applyButton.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Minimum)

        paremetersFormLayout.addRow("Filtered by: ", filter_Grid)

        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False
        outputSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        outputFormLayout = qt.QFormLayout(outputSection)

        outputFormLayout.addRow("Result suffix: ", self.resultSuffix)
        outputFormLayout.addRow("", self.numberOfRowsLabel)

        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addWidget(self.applyButton)

        self.colorBySetButton.clicked.connect(self.openDialog)
        self.filterAddButton.clicked.connect(self.addFilter)
        self.filterEditButton.clicked.connect(self.editFilter)
        self.filterDelButton.clicked.connect(self.deleteFilters)
        self.applyButton.clicked.connect(self.on_apply_clicked)
        self.filterList.itemDoubleClicked.connect(self.onFilterListItemDoubleClicked)
        self.filterList.itemSelectionChanged.connect(self.onFilterListItemSlectionChanged)

        self.enableFilterControls(False)
        self.setTableReference(self.tableSelector.currentItem())
        self.onReferenceNodeChanged(self.referenceNodeSelector.currentItem())

    def __applyComboBoxFilter(self):
        """Force qMRMLNodeComboBox nodes filter to handle hidden nodes correctly."""
        self.referenceNodeSelector.sortFilterProxyModel().invalidateFilter()

    def onFilterListItemSlectionChanged(self):
        self.filterEditButton.enabled = len(self.filterList.selectedItems()) > 0
        self.filterDelButton.enabled = len(self.filterList.selectedItems()) > 0

    def enableFilterControls(self, enable=True):
        self.colorBySetButton.enabled = enable
        self.filterAddButton.enabled = enable
        self.filterEditButton.enabled = enable and len(self.filterList.selectedItems()) > 0
        self.filterDelButton.enabled = enable and len(self.filterList.selectedItems()) > 0
        self.referenceNodeSelector.enabled = enable

    def buildSliderFilterByCount(self):
        widget = slicer.qMRMLSliderWidget()
        widget.minimum = 0
        widget.maximum = 1000
        widget.value = 1000
        widget.singleStep = 1
        widget.tracking = False
        return widget

    def export(self):
        tableFullName = self.tableSelector.currentNode().GetName() + "_" + self.resultSuffix.text
        referenceFullName = (
            None
            if self.getCurrentMasterNode() is None
            else self.getCurrentMasterNode().GetName() + "_" + self.resultSuffix.text
        )

        self.logic.exportCurrentSelection(
            tableFullName,
            referenceFullName,
            tableNode=self.tableSelector.currentNode(),
            targetNode=self.getCurrentMasterNode(),
        )

    def on_apply_clicked(self):
        table_node = self.tableSelector.currentNode()
        labelmap_node = self.referenceNodeSelector.currentNode()
        invalid_apply = False
        if table_node is None:
            invalid_apply = True

            self.tableSelector.blockSignals(True)
            self.tableSelector.setStyleSheet("QComboBox { background-color: #600000; color: #FFFFFF}")
            self.tableSelector.blockSignals(False)

            if self.referenceNodeSelector.styleSheet != "":
                self.referenceNodeSelector.blockSignals(True)
                self.referenceNodeSelector.setStyleSheet("QComboBox { background-color: #600000; color: #777777}")
                self.referenceNodeSelector.blockSignals(False)

        if labelmap_node is None:
            invalid_apply = True

            text_color = "#FFFFFF" if self.referenceNodeSelector.enabled else "#777777"
            self.referenceNodeSelector.blockSignals(True)
            self.referenceNodeSelector.setStyleSheet(
                "QComboBox { background-color: #600000; color: " + text_color + "}"
            )
            self.referenceNodeSelector.blockSignals(False)

        if invalid_apply:
            return

        self.applyButton.enabled = False
        self.applyButton.blockSignals(True)
        slicer.app.processEvents()
        try:
            self.export()
        except Exception as e:
            print_debug(e)
        slicer.app.processEvents()
        self.applyButton.blockSignals(False)
        self.applyButton.enabled = True

    def openDialog(self):
        self.logic.takeSnapshot()
        item = 0 if self.logic._colorBy == -1 else self.logic.currentColumnColoredBy()
        d = LabelDialog(slicer.modules.AppContextInstance.mainWindow, self.logic, self.getCurrentMasterNode(), item)
        if d.exec_() == 1:
            # Force default column as color parameter
            if self.logic._colorBy == -1:
                self.logic.apply(
                    colorBy=self.logic.getDefaultColorByIndex(),
                    targetNode=self.getCurrentMasterNode(),
                    force=True,
                )

            self.logic.resetSnapshot()
            self.colorByTextLabel.text = f"{self.logic.currentColumnColoredBy()} = {self.logic.labelCount()} segments"
        else:
            self.logic.loadSnapshot()
            if len(self.logic._labels) > 0:
                self.logic.updateLabels(self.logic._labels, self.getCurrentMasterNode())

        self.numberOfRowsLabel.setText(f"{self.logic.rows()} rows")

    def onFilterListItemDoubleClicked(self, item):
        self.filterList.setCurrentItem(item)
        self.editFilter()

    def addFilter(self):
        self.logic.takeSnapshot()
        d = FilterDialog(slicer.modules.AppContextInstance.mainWindow, self.logic, self.getCurrentMasterNode(), 0)
        if d.exec_() == 1 and d.currentFilter is not None:
            filter_ = d.currentFilter
            self.filterList.addItem(repr(filter_))
            self.logic.resetSnapshot()
        else:
            self.logic.loadSnapshot()

        if len(self.logic._labels) > 0:
            self.logic.updateLabels(self.logic._labels, self.getCurrentMasterNode())
        self.numberOfRowsLabel.setText(f"{self.logic.rows()} rows")

    def editFilter(self):
        sitems = self.filterList.selectedItems()
        if len(sitems) == 0:
            slicer.util.infoDisplay("Please, select a filter to edit.")
            return

        findex = self.filterList.row(sitems[0])
        filter_ = self.logic._filters[findex]
        column = filter_.column + 1  # add None position
        self.logic.takeSnapshot()
        d = FilterDialog(
            slicer.modules.AppContextInstance.mainWindow,
            self.logic,
            self.getCurrentMasterNode(),
            column,
            filter_,
        )
        if d.exec_() == 1:
            litem = self.filterList.item(findex)
            litem.setText(repr(filter_))
            self.logic.resetSnapshot()
        else:
            self.logic.loadSnapshot()

        self.logic.updateLabels(self.logic._labels, self.getCurrentMasterNode())
        self.numberOfRowsLabel.setText(f"{self.logic.rows()} rows")

    def deleteFilters(self):
        items = self.filterList.selectedItems()
        for item in items:
            row = self.filterList.row(item)
            self.filterList.takeItem(row)
            del self.logic._filters[row]

        self.logic.updateLabels(self.logic._labels, self.getCurrentMasterNode())
        self.numberOfRowsLabel.setText(f"{self.logic.rows()} rows")

    def setTableReference(self, item):
        node = self.tableSelector.subjectHierarchy.GetItemDataNode(item)
        try:
            if self.logic is not None and len(self.logic._filters) > 0 and self.logic._node != node:
                answer = qt.QMessageBox.question(
                    slicer.modules.AppContextInstance.mainWindow,
                    "Table Filter",
                    "There are changes in the current table selection. Are you sure you want to change table? All filters will be erased.",
                    qt.QMessageBox.Yes | qt.QMessageBox.No,  # | qt.QMessageBox.Cancel,
                )
                if answer != qt.QMessageBox.Yes:
                    self.tableSelector.setCurrentNode(self.logic._node)
                    return

                del self.logic
                self.logic = None
                self.filterList.clear()

            if node is None:
                raise AssertionError()

            self.tableSelector.setStyleSheet("")

            if self.logic is None or self.logic._node != node:
                self.logic = TableFilterLogic(tableNode=node)

            self.numberOfRowsLabel.setText(f"{self.logic.rows()} rows")
            # self._updateQueryOptions()
            refNodeID = node.GetAttribute("ReferenceVolumeNode")
            if refNodeID:
                labelmapNode = slicer.util.getNode(refNodeID)
                self.referenceNodeSelector.setCurrentNode(labelmapNode)
            else:
                self.referenceNodeSelector.setCurrentNode(None)
            self.enableFilterControls()
        except AssertionError as ae:
            self.enableFilterControls(False)
        except Exception as e:
            slicer.util.errorDisplay(repr(e))
        else:
            # Update color by parameters to the default value for the related table's data
            self.logic.apply(
                colorBy=self.logic.getDefaultColorByIndex(),
                targetNode=self.getCurrentMasterNode(),
                force=True,
            )
            self.colorByTextLabel.text = f"{self.logic.currentColumnColoredBy()} = {self.logic.labelCount()} segments"

            self.__applyComboBoxFilter()

    def getCurrentMasterNode(self):
        return self.referenceNodeSelector.currentNode()

    def __removeOldShadowNode(self):
        if self.currentReferenceNode is None:
            self.__applyComboBoxFilter()
            return

        shadowNode = getShadowNode(self.currentReferenceNode)
        if shadowNode is not None:
            slicer.mrmlScene.RemoveNode(shadowNode)

    def onReferenceNodeChanged(self, item):
        node = self.referenceNodeSelector.subjectHierarchy.GetItemDataNode(item)
        if node is None:
            self.__removeOldShadowNode()
            self.currentReferenceNode = node
            self.__applyComboBoxFilter()
            slicer.util.setSliceViewerLayers(label=None)

            return

        self.referenceNodeSelector.setStyleSheet("")
        self.__removeOldShadowNode()
        try:
            self.logic.updateLabels(self.logic._labels, node)
        except Exception as error:
            print_debug(error)
            self.referenceNodeSelector.setCurrentNode(None)
            self.currentReferenceNode = None
            self.__applyComboBoxFilter()
            slicer.util.errorDisplay("Invalid labelmap reference node. Please, select a valid labelmap.")
            return
        else:
            slicer.util.setSliceViewerLayers(label=getShadowNode(node))

        self.currentReferenceNode = node
        self.__applyComboBoxFilter()


def relabelVolume(node, labelmap, colormap=None):
    if node is None:
        slicer.util.errorDisplay("Please, select a valid reference node (Labelmap).")
        return

    referenceLabelmapArray = slicer.util.arrayFromVolume(node).astype(np.uint16)

    _map = np.zeros(len(labelmap) + 1, dtype=np.uint16)
    _map[1:] += labelmap.astype(np.uint16)
    relabeledArray = _map[referenceLabelmapArray]

    mutableNode = shadowNode(node)

    mutableNode.SetAndObserveImageData(None)
    slicer.util.updateVolumeFromArray(mutableNode, relabeledArray)

    if colormap:
        fillColorTableFromSegments(colormap, mutableNode)

    mutableNode.GetDisplayNode().SetVisibility2D(True)

    mutableNode.Modified()

    slicer.util.setSliceViewerLayers(label=mutableNode)


def fillColorTableFromSegments(colormap, labelMapNode):
    colorNode = labelMapNode.GetDisplayNode().GetColorNode()
    colorNode.NamesInitialisedOff()
    colorNode.ClearNames()
    colorNode.SetNumberOfColors(len(colormap) + 1)

    colorNode.SetColor(0, "Background", 0.0, 0.0, 0.0, 0.0)

    for label, name, color in colormap:
        rgb = [channel / 256 for channel in ImageColor.getrgb(color)]
        colorNode.SetColor(label, name, *rgb)

    colorNode.NamesInitialisedOn()


def fillComboBox(widget, values, hasNone=False, defaultValue=0):
    widget.clear()

    if hasNone:
        widget.addItem("None")

    widget.addItems(values)
    if isinstance(defaultValue, int):
        widget.setCurrentIndex(defaultValue)
    elif isinstance(defaultValue, str):
        widget.setCurrentText(defaultValue)


def isFloat(dtype):
    return dtype in [np.dtype("float64"), np.dtype("float32"), float]


def cluster(values, k=3):
    Y = values.reshape(-1, 1) if values.ndim == 1 else values
    kmeans = KMeans(n_clusters=k, random_state=5932)
    kmeans.fit(Y)
    labeled = kmeans.labels_
    return labeled, kmeans.n_clusters


class TableFilterLogic(LTracePluginLogic):
    def __init__(self, tableNode):
        if tableNode is None:
            raise AttributeError(f"{TableFilterLogic.__name__}.data cannot be set to NoneType.")
        self._node = tableNode
        self._data = dataframeFromTable(tableNode)

        self._labelmap = np.array([])
        self._labels = []
        self._colorBy = self.getDefaultColorByIndex()
        self._activeRows = None
        self._filters: List[Filter] = []

        self._labelmap_snap = np.array([])
        self._labels_snap = []
        self._colorBy_snap = -1
        self._activeRows_snap = None
        self._filters_snap = []

    def getDefaultColorByIndex(self):
        if self._data is None:
            return -1

        whiteList = ["pore_size_class"]
        for idx, col in enumerate(self._data.columns):
            if col in whiteList:
                return idx

        return 0

    @lru_cache
    def unique(self, column):
        return self.__data[column].unique()

    def coloredBy(self):
        return self._data.iloc[:, self._colorBy]

    def columns(self):
        return [col for col in self._data.columns]

    def rows(self):
        return np.count_nonzero(self._labelmap) if len(self._labelmap) > 0 else len(self._data.index)

    def currentColumnColoredBy(self):
        return self._data.columns[self._colorBy]

    def values(self, column):
        if isinstance(column, int):
            return self._data.iloc[:, column]
        elif isinstance(column, str):
            return self._data[:, column]

    def labelCount(self):
        return sum([int(label.visible) for label in self._labels])

    def exportCurrentSelection(self, tableName, referenceName, tableNode, targetNode=None):

        # Select the parent hierarchy tree node to place newly created nodes
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemTreeId = folderTree.GetItemByDataNode(tableNode)
        parentItemId = folderTree.GetItemParent(itemTreeId)

        filteredTableNode = helpers.createTemporaryNode(slicer.vtkMRMLTableNode, tableName, hidden=False)

        nodeTreeId = folderTree.CreateItem(parentItemId, filteredTableNode)
        folderTree.SetItemDisplayVisibility(nodeTreeId, 1)

        indexing = self._labelmap != 0
        df = self._data.iloc[indexing, :].copy()
        df.loc[:, "Segmented by"] = self._labelmap[indexing]
        dataFrameToTableNode(df, tableNode=filteredTableNode)
        helpers.makeTemporaryNodePermanent(filteredTableNode)

        if targetNode:
            mutableNode = shadowNode(targetNode)
            mutableNode.SetName(referenceName)
            helpers.makeTemporaryNodePermanent(mutableNode)
            mutableNode.SetHideFromEditors(False)
            mutableNode.GetDisplayNode().SetVisibility(True)

            nodeTreeId = folderTree.CreateItem(parentItemId, mutableNode)
            folderTree.SetItemDisplayVisibility(nodeTreeId, 1)
            slicer.util.setSliceViewerLayers(label=mutableNode)

    def takeSnapshot(self):
        self._labelmap_snap = np.array(self._labelmap, copy=True)
        self._labels_snap = [v for v in copy.deepcopy(self._labels)]
        self._colorBy_snap = self._colorBy
        self._activeRows_snap = self._activeRows.copy() if self._activeRows is not None else None
        self._filters_snap = [v for v in copy.deepcopy(self._filters)]

    def loadSnapshot(self):
        self._labelmap = self._labelmap_snap
        self._labels = self._labels_snap
        self._colorBy = self._colorBy_snap
        self._activeRows = self._activeRows_snap
        self._filters = self._filters_snap

    def resetSnapshot(self):
        self._labelmap_snap = np.array([])
        self._labels_snap = []
        self._colorBy_snap = self.getDefaultColorByIndex()
        self._activeRows_snap = None
        self._filters_snap = []

    def resetLabelData(self):
        self._labelmap = np.array([])
        self._labels = []
        self._colorBy = self.getDefaultColorByIndex()
        self._activeRows = None

    # def deleteLabels(self, deletedLabels, targetNode):
    #     # TODO not optimize, not required now but should keep an eye
    #     for label in deletedLabels:
    #         self._labelmap[self._labelmap == label] = 0
    #
    #     self._labelmap[:] = relabel_sequential(self._labelmap)[0]
    #     self.relabelVolume(targetNode)

    def getSegmentedRepresentationOf(self, column):
        values: pd.Series = self._data.iloc[:, column]
        if isFloat(values.dtype):
            return [
                ContinuousTuple(
                    1,
                    self._data.columns[column],
                    minimum=values.min(),
                    maximum=values.max(),
                )
            ]
        else:
            uvals = values.unique()
            uvals.sort()
            return [DiscreteTuple(i, val) for i, val in enumerate(uvals)]

    def updateLabels(self, newLabels, targetNode=None):
        labelmap = np.zeros_like(self._labelmap)

        start = time.perf_counter()
        if newLabels and self._activeRows is not None and len(self._activeRows) > 0:
            activeRows = self.filterRows(self._activeRows)
            columnData = self._data.iloc[activeRows, self._colorBy]
            for label in newLabels:
                if label.visible:
                    value_indexes = label.index(columnData)
                    if value_indexes is not None:
                        index = columnData[value_indexes].index
                        labelmap[index] = label.label
        interval = time.perf_counter() - start
        print_debug(f"updateLabels.loop = {interval:0.4g} seconds")

        start = time.perf_counter()
        self._labels = newLabels
        self._labelmap[:] = labelmap
        interval = time.perf_counter() - start
        print_debug(f"updateLabels.attrib = {interval:0.4g} seconds")

        start = time.perf_counter()
        self.relabelVolume(targetNode)
        interval = time.perf_counter() - start
        print_debug(f"relabelVolume = {interval:0.4g} seconds")

    def addFilters(self, column, rules):
        namedFilter = Filter(column, rules)
        self._filters.append(namedFilter)
        return namedFilter

    def apply(self, colorBy: int, targetNode=None, force=False):
        if self._data is None:
            raise AttributeError(f"{TableFilterLogic.__name__}.data cannot be set to NoneType.")

        if colorBy < 0:
            raise IndexError(f"{TableFilterLogic.__name__}.apply expected colorBy > 0, received {colorBy}")

        if colorBy >= len(self._data.columns):
            raise IndexError(
                f"{TableFilterLogic.__name__}.apply expected colorBy < {len(self._data.columns)}, received {colorBy}"
            )

        if len(self._data.index) == 0:
            slicer.util.warningDisplay("Your table is empty.")
            return  # Nothing to do

        start = time.perf_counter()
        self.labelSegmentsBy(colorBy, force)
        interval = time.perf_counter() - start
        print_debug(f"labelSegmentsBy = {interval:0.4g} seconds")

        start = time.perf_counter()
        self._activeRows = self.filterRows(self._data.index)
        interval = time.perf_counter() - start
        print_debug(f"filterRows = {interval:0.4g} seconds")

        start = time.perf_counter()
        self.relabelVolume(targetNode)
        interval = time.perf_counter() - start
        print_debug(f"relabelVolume = {interval:0.4g} seconds")

    def filterRows(self, tableIndex: pd.Series):
        tableIndexCopy = tableIndex.copy(deep=True)

        if len(tableIndexCopy) == 0:
            return tableIndexCopy

        # indexMap = np.ones(len(tableIndexCopy), dtype=bool)
        for filter_ in self._filters:
            values = self._data.iloc[tableIndexCopy, filter_.column]
            tempMap = np.zeros(len(values), dtype=bool)
            for rule in filter_.filterData:
                if isinstance(rule, DiscreteTuple):
                    if rule.visible:
                        tempMap[rule.index(values)] = 1
                else:
                    tempMap[rule.index(values)] = 1

            tableIndexCopy = tableIndexCopy[tempMap]

        return tableIndexCopy

    def updateSegments(self, transitions):
        for i, elem in enumerate(self._labels):
            elem.setValues(*transitions[i])

    def labelSegmentsBy(self, colorBy, force=False):
        values = self._data.iloc[:, colorBy]

        if isFloat(values.dtype):
            k = len(self._labels) if colorBy == self._colorBy else 3
            labeled, n_found = cluster(np.array(values), k=k)

            transitions = []
            for label in range(0, n_found):
                scope = values[labeled == label]
                transitions.append((label, scope.min(), scope.max()))
            transitions.sort(key=lambda item: item[2])

            remap = np.zeros(len(transitions))
            for i in range(len(transitions)):
                remap[transitions[i][0]] = i

            remap = np.array(remap)
            labeled[:] = remap[labeled] + 1

            if (
                len(self._labels) > 0
                and type(self._labels[0]) == ContinuousTuple
                and len(transitions) == len(self._labels)
            ):
                self.updateSegments([(a, b) for _, a, b in transitions])
            else:
                self._labels = [
                    ContinuousTuple(i, f"Cluster {i}", minimum=a, maximum=b)
                    for i, (_, a, b) in enumerate(transitions, start=1)
                ]

        else:
            uvals = values.unique()
            if not force:
                message = ""
                if len(uvals) == len(values):
                    message = (
                        "This attribute has the same number of different values as segments, "
                        "probably this is just the index of your table. Do you wish to proceed?"
                    )

                if len(uvals) > CLUSTER_COUNT_WARNING:
                    if message:
                        message = message.replace(
                            "Do you wish to proceed?",
                            "Given the size of your table, this can slow down the controls responsiveness. "
                            "Do you wish to proceed?",
                        )
                    else:
                        message = (
                            f"This attribute has more than {CLUSTER_COUNT_WARNING} segments, totalling {len(uvals)}, "
                            f"this can slow down filtering controls responsiveness."
                        )

                if message:
                    yesOrNo = slicer.util.confirmYesNoDisplay(message, windowTitle="Warning")

                    if not yesOrNo:
                        raise AssertionError()

            kmap = {val: i for i, val in enumerate(uvals, start=1)}
            labeled = np.array(values.replace(kmap).values, copy=True)

            self._labels = [DiscreteTuple(i, f"{key}") for i, key in enumerate(kmap, start=1)]

        self._labelmap = labeled
        self._colorBy = colorBy

    def relabelVolume(self, targetNode):
        if targetNode is None:
            return

        if len(self._labels) == 0:
            return

        fullLabelRef = np.zeros(len(self._data.index))
        if self._labelmap is not None:
            fullLabelRef += self._labelmap

        colormap = [(lb.label, lb.name, lb.color) for lb in self._labels]
        relabelVolume(targetNode, fullLabelRef, colormap=colormap)

    def filter(self, state):
        scope = state.df[state.columnFilter].values
        mask = (scope >= state.range_[0]) & (scope <= state.range_[1])
        return mask


class MultiThresholdWidget(qt.QWidget):
    actionClicked = qt.Signal(str)

    def __init__(self, parent=None, tableEditable=True, showColors=True):
        super().__init__(parent)

        self.tableEditable = tableEditable
        self.showColors = showColors
        self.regions = []
        self.rangePos = (2, 3)

        mainLayout = qt.QVBoxLayout()
        self.setLayout(mainLayout)

        self.bins_xaxis = np.array([])
        self.bins_yaxis = np.array([])
        self.binWidth = 1
        self.binsNumber = 100
        self.groups = []
        self.setup()

    def setup(self):

        parametersFormLayout = qt.QFormLayout()

        self.figureGroup = ps.QtWidgets.QWidget()
        self.figureGroup.setMaximumWidth(512)
        self.figureGroup.setMinimumWidth(128)
        self.figureGroup.setMaximumHeight(256)
        self.figureGroup.setContentsMargins(0, 0, 0, 0)

        axisLayout = ps.QtWidgets.QHBoxLayout(self.figureGroup)
        axisLayout.setContentsMargins(0, 0, 0, 0)

        graphicsLayoutWidget = pg.GraphicsLayoutWidget()
        graphicsLayoutWidget.setSizePolicy(ps.QtWidgets.QSizePolicy.Preferred, ps.QtWidgets.QSizePolicy.Minimum)

        axisLayout.addWidget(graphicsLayoutWidget)

        self.histPlot = graphicsLayoutWidget.addPlot()
        self.histPlot.setMouseEnabled(False, False)

        # # Slide bar to zoom the histogram
        zoomLabel = qt.QLabel("X-axis range: ")
        zoomLabel.setToolTip("Set the x range of the displayed histogram.")

        self.zoomSlider = ctk.ctkRangeWidget()
        self.zoomSlider.setMaximumWidth(512)
        self.zoomSlider.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Minimum)

        self.plotView = ui.Col([getPythonQtWidget(self.figureGroup), self.zoomSlider])
        self.plotView.setMaximumWidth(512)

        self.table = qt.QTableWidget()
        self.table.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)
        self.table.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(qt.QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.setColumnCount(5)
        headers = [" ", "name", "min", "max", "show"]
        self.table.setHorizontalHeaderLabels(headers)
        self.__adjustTableColumnSize(headers)

        self.table.setColumnWidth(0, 10)
        self.table.setColumnWidth(1, 50)
        self.table.setColumnWidth(2, 25)
        self.table.setColumnWidth(3, 25)
        self.table.setColumnWidth(4, 10)

        if not self.tableEditable:
            self.table.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)

        self.controls, button_widget_list = self.buildControls()
        self.controls.setMaximumWidth(64)

        self.addClassButton = button_widget_list[0]
        self.removeClassButton = button_widget_list[1]
        self.recalculateClassButton = button_widget_list[2]

        plotRow = ui.Row([self.plotView, self.table, self.controls])
        parametersFormLayout.addRow(plotRow)

        self.layout().addLayout(parametersFormLayout)

        self.zoomSlider.connect("valuesChanged(double,double)", self.onZoomChanged)
        self.table.itemSelectionChanged.connect(self.__onTableSelectionChanged)

        self.plotView.hide()

    def __onTableSelectionChanged(self):
        selectedIndexes = self.table.selectionModel().selectedIndexes

        rows_set = set()
        for modelIndex in selectedIndexes:
            rows_set.add(modelIndex.row())

        self.removeClassButton.setEnabled(len(rows_set) > 0 and self.table.rowCount > 1)

    def buildControls(self):

        container = qt.QWidget()
        buttonsLayout = qt.QVBoxLayout(container)

        buttons = [
            (":/Icons/Add.png", self.addClass, "Add another class"),
            (":/Icons/Remove.png", self.removeClass, "Remove selected class"),
            (
                self.table.style().standardIcon(getattr(ps.QtWidgets.QStyle, "SP_BrowserReload")),
                self.reloadView,
                "Recalculate class distribution",
            ),
        ]

        btn_widget_list = []
        for conf in buttons:
            btn = qt.QPushButton("")
            btn.icon = qt.QIcon(conf[0])
            btn.setToolTip(conf[2])
            btn.clicked.connect(conf[1])
            buttonsLayout.addWidget(btn)
            btn_widget_list.append(btn)

        return container, btn_widget_list

    def controlsOn(self):
        self.controls.show()

    def controlsOff(self):
        self.controls.hide()

    def onZoomChanged(self):
        self.plot()

    def reloadView(self):
        self.actionClicked.emit("reload")
        self.table.selectRow(self.table.rowCount - 1)

    def removeClass(self):
        selected_indexes = sorted(self.table.selectionModel().selectedIndexes)

        if len(selected_indexes) <= 0:
            return

        oldState = self.table.blockSignals(True)
        row = selected_indexes[0].row()
        self.table.removeRow(row)
        self.plot()
        self.table.blockSignals(oldState)
        self.actionClicked.emit("delete")
        self.table.selectRow(self.table.rowCount - 1)

    def addClass(self):
        min_, max_ = self.getZoomRange()
        label = self.table.rowCount + 1
        newseg = SegmentTuple(
            label,
            name=f"New Class {label}",
            minimum=min_,
            maximum=max_,
            discrete=self.__isSegmentsDiscrete(),
        )
        oldState = self.table.blockSignals(True)
        self._appendRow(newseg)
        self.plot()
        self.table.blockSignals(oldState)
        self.actionClicked.emit("append")
        self.table.selectRow(self.table.rowCount - 1)

    def copyTableState(self):
        state = []

        if not self.__isSegmentsDiscrete():
            for row in range(self.table.rowCount):
                state.append(
                    ContinuousTuple(
                        label=row + 1,
                        name=self.table.item(row, 2).text(),
                        minimum=float(self.table.item(row, 3).text()),
                        maximum=float(self.table.item(row, 4).text()),
                        color=self.table.cellWidget(row, 1).currentColor(),
                        visible=bool(self.table.item(row, 0).checkState()),
                    )
                )
        else:
            for row in range(self.table.rowCount):
                state.append(
                    DiscreteTuple(
                        label=row + 1,
                        name=self.table.item(row, 2).text(),
                        color=self.table.cellWidget(row, 1).currentColor(),
                        visible=bool(self.table.item(row, 0).checkState()),
                    )
                )

        return state

    def getZoomRange(self):
        _min = self.zoomSlider.minimumValue
        _max = self.zoomSlider.maximumValue
        return _min, _max

    def setNewRegion(self, i, region):
        movedRange = region.getRegion()

        limits = self.bins_xaxis[0], self.bins_xaxis[-1]

        self.table.blockSignals(True)
        textval = tablefyFloat(max(movedRange[0], limits[0]))
        if self.table.item(i, 3).text() != textval:
            self.table.setItem(i, 3, textval)

        textval = tablefyFloat(min(movedRange[1], limits[1]))
        if self.table.item(i, 4).text() != textval:
            self.table.setItem(i, 4, textval)
        self.table.blockSignals(False)

    def regionChanged(self, i, region):
        if not self.tableEditable:
            return

        self.setNewRegion(i, region)

    def regionChangedFinished(self, i, region):
        self.setNewRegion(i, region)
        self.table.cellChanged.emit(i, 4)

    def plot(self, onlyBars=False):
        if onlyBars:
            for item in self.histPlot.listDataItems():
                if isinstance(item, pg.BarGraphItem):
                    self.histPlot.removeItem(item)
        else:
            self.histPlot.clear()

        _min = self.zoomSlider.minimumValue
        _max = self.zoomSlider.maximumValue

        self.histPlot.setLimits(xMin=_min, xMax=_max)

        for item in self.groups:
            start = float(item.minimum)
            binEdge = float(item.maximum)

            if _min > binEdge > _max:
                continue
            if item.visible:
                selection = (self.bins_xaxis >= start) & (self.bins_xaxis < binEdge)
                _x = self.bins_xaxis[selection]
                _y = self.bins_yaxis[selection]
                plot = pg.BarGraphItem(
                    x=_x,
                    width=self.binWidth,
                    height=_y,
                    brush=item.color,
                    pen=[0, 0, 0, 255],
                )
                self.histPlot.addItem(plot)

        for i in range(self.table.rowCount):
            start_item = self.table.item(i, 3)
            end_item = self.table.item(i, 4)
            if start_item is None or end_item is None:
                continue

            start = float(start_item.text())
            binEdge = float(end_item.text())

            if _min > binEdge > _max:
                continue
            if self.table.item(i, 0).checkState() == qt.Qt.Checked:
                # selection = (self.bins_xaxis >= start) & (self.bins_xaxis < binEdge)
                # _x = self.bins_xaxis[selection]
                # _y = self.bins_yaxis[selection]
                # color = self.table.cellWidget(i, 1).currentColor()
                # plot = pg.BarGraphItem(x=_x, width=self.binWidth, height=_y, brush=color, pen=[0, 0, 0, 255])
                # self.histPlot.addItem(plot)

                if not onlyBars:
                    borderPen = pg.mkPen((255, 0, 0), width=5)
                    lr = pg.LinearRegionItem([start, binEdge], swapMode="push", pen=borderPen)
                    lr.sigRegionChanged.connect(partial(self.regionChanged, i))
                    lr.sigRegionChangeFinished.connect(partial(self.regionChangedFinished, i))
                    lr.setZValue(-100)
                    self.histPlot.addItem(lr)
                    self.regions.append(lr)

    def loadData(self, data, segments, groups=None):
        _min = np.min(data)
        _max = np.max(data)

        self._fillTable(segments)
        if isFloat(data.dtype):
            count, binEdges = np.histogram(data, bins="auto")
            self.binWidth = binEdges[1] - binEdges[0]
            self.bins_xaxis = binEdges[:-1]
            self.bins_yaxis = count

            lock = self.zoomSlider.blockSignals(True)
            zoomOffset = _max * 0.11
            self.zoomSlider.setRange(_min - zoomOffset, _max + zoomOffset)
            self.zoomSlider.singleStep = (_max - _min) / len(data)
            self.zoomSlider.setMinimumValue(_min - zoomOffset)
            self.zoomSlider.setMaximumValue(_max + zoomOffset)
            self.zoomSlider.blockSignals(lock)

            self.groups = groups or segments

            self.plotView.show()
            self.plot()
        else:
            self.histPlot.clear()
            self.plotView.hide()

    def clearTable(self):
        self.table.clear()
        self.table.setRowCount(0)

    def _fillTable(self, segments):
        self.table.blockSignals(True)
        self.clearTable()

        if len(segments) <= 0:
            raise IndexError("TableFilter::_fillTable: Invalid input data.")

        headers = segments[0].COLUMNS
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.__adjustTableColumnSize(headers)

        # Consider using a QTableView if you're willing to display a higher row numbers at once.
        # It will render only a table slice at a time, avoiding a crash as it occurs with QTableWidget
        # when populating it with a data array that has a few thousand elements.
        rowLimitNumber = min(len(segments), 255)
        self.table.setRowCount(rowLimitNumber)

        for row, segment in enumerate(segments[:rowLimitNumber]):
            self._insertRow(segment, at=row)

        if not self.showColors:
            self.table.setColumnHidden(1, True)

        self.table.blockSignals(False)

        # self.table.cellChanged.emit(0, 0)

    def _appendRow(self, values):
        self.table.insertRow(self.table.rowCount)
        row = self.table.rowCount - 1
        self._insertRow(values, at=row)

    def _insertRow(self, values, at=None):
        check = qt.QTableWidgetItem()
        check.setFlags(check.flags() | qt.Qt.ItemIsUserCheckable)
        check.setFlags(check.flags() & ~qt.Qt.ItemIsEditable)
        check.setCheckState(qt.Qt.Checked if values.visible else qt.Qt.Unchecked)
        check.setTextAlignment(qt.Qt.AlignCenter)
        self.table.setItem(at, 0, check)

        colorWidget = ColorPicker.ColorPickerCell(at, 0, color=values.color)
        colorWidget.colorChanged.connect(lambda c, row=at, col=0: self.table.cellChanged.emit(row, col))
        self.table.setCellWidget(at, 1, colorWidget)

        itemName = qt.QTableWidgetItem(str(values.name))
        self.table.setItem(at, 2, itemName)

        for col, val in zip([3, 4], values.getValues()):
            self.table.setItem(at, col, tablefyFloat(val))

    def __adjustTableColumnSize(self, headers):
        for idx, header in enumerate(headers):
            if str(header).lower() == "name":
                self.table.horizontalHeader().setSectionResizeMode(idx, qt.QHeaderView.Stretch)
            else:
                self.table.horizontalHeader().setSectionResizeMode(idx, qt.QHeaderView.ResizeToContents)

    def __isSegmentsDiscrete(self):
        return not self.table.columnCount > 3


def tablefyFloat(val):
    val = " - " if val is None else "{n:5.2g}".format(n=val)
    valueItem = qt.QTableWidgetItem(val)
    return valueItem


class LabelDialog(qt.QDialog):
    def __init__(self, parent=None, logic=None, masterNode=None, item=0):
        super().__init__(parent)

        self.logic: TableFilterLogic = logic
        self.masterNode = masterNode

        layout = qt.QVBoxLayout()
        layout.setSizeConstraint(qt.QLayout.SetFixedSize)
        self.setLayout(layout)

        self.indexSelector = qt.QComboBox()
        self.indexSelector.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Minimum)

        self.threshWidget = MultiThresholdWidget()

        buttons = qt.QDialogButtonBox()
        buttons.addButton(qt.QDialogButtonBox.Ok)
        buttons.addButton(qt.QDialogButtonBox.Cancel)

        layout.addWidget(self.indexSelector)
        layout.addWidget(self.threshWidget)
        layout.addWidget(buttons)
        layout.addStretch(1)

        self.indexSelector.currentTextChanged.connect(self.onColorByChanged)

        self.threshWidget.table.cellChanged.connect(self.onTableEdited)
        self.threshWidget.actionClicked.connect(self.handleRequestedAction)
        self.threshWidget.addClassButton.setEnabled(False)
        self.threshWidget.removeClassButton.setEnabled(False)
        self.threshWidget.recalculateClassButton.setEnabled(False)

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self._updateQueryOptions()
        if isinstance(item, int):
            self.indexSelector.setCurrentIndex(item)
        elif isinstance(item, str):
            self.indexSelector.setCurrentText(item)

    def _updateQueryOptions(self):
        lock = self.indexSelector.blockSignals(True)
        blackListParameters = ["label"]
        columns = [col for col in self.logic.columns() if col not in blackListParameters]
        fillComboBox(self.indexSelector, columns, hasNone=False, defaultValue="None")
        self.indexSelector.blockSignals(lock)

    def onColorByChanged(self, itemText):
        if self.logic is None:
            slicer.util.errorDisplay("TableFilterWidget.colorBy cannot run without a valid logic instance.")
            return

        self.threshWidget.addClassButton.setEnabled(itemText != "None")
        self.threshWidget.recalculateClassButton.setEnabled(itemText != "None")

        if itemText == "None":
            self.threshWidget.clearTable()
            self.threshWidget.plotView.hide()
            self.logic.resetLabelData()
            return

        alwaysValidItemIndex = self.logic.columns().index(itemText)
        if alwaysValidItemIndex == self.logic._colorBy:

            self.logic.updateLabels(self.logic._labels, self.masterNode)
            self._redrawHistogram()
        else:
            self.updateViews(alwaysValidItemIndex)

    def updateViews(self, itemIndex):
        try:
            self.logic.apply(colorBy=itemIndex, targetNode=self.masterNode)
            self._redrawHistogram()
        except Exception as e:
            print_debug(f"TableFilter::updateViews: {repr(e)}")
            self.indexSelector.setCurrentIndex(self.logic.getDefaultColorByIndex())

    def onTableEdited(self):
        self.logic.updateLabels(self.threshWidget.copyTableState(), self.masterNode)
        self._redrawHistogram(onlyBars=True)

    def handleRequestedAction(self, action: str):
        if action == "reload":
            self.logic._labels = self.threshWidget.copyTableState()
            self.updateViews(self.logic._colorBy)
            self._redrawHistogram(onlyBars=True)
        elif action == "delete":
            self.logic.updateLabels(self.threshWidget.copyTableState(), self.masterNode)
            self._redrawHistogram(onlyBars=True)
        elif action == "append":
            self.logic.updateLabels(self.threshWidget.copyTableState(), self.masterNode)
            self._redrawHistogram(onlyBars=True)
        else:
            raise ValueError(f'handleRequestedAction.action invalid value "{action}')

    def _redrawHistogram(self, onlyBars=False):
        self.threshWidget.show()
        start = time.perf_counter()
        self.threshWidget.loadData(self.logic.coloredBy(), self.logic._labels)
        interval = time.perf_counter() - start
        print_debug(f"Load Data = {interval:0.4g} seconds")
        # self.threshWidget.plot(onlyBars)


class FilterDialog(qt.QDialog):
    def __init__(self, parent=None, logic=None, masterNode=None, index=0, model=None):
        super().__init__(parent)

        self.logic: TableFilterLogic = logic
        self.masterNode = masterNode
        self.currentFilter: Filter = model

        layout = qt.QVBoxLayout()
        layout.setSizeConstraint(qt.QLayout.SetFixedSize)
        self.setLayout(layout)

        self.indexSelector = qt.QComboBox()
        self.indexSelector.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Minimum)

        self.threshWidget = MultiThresholdWidget(tableEditable=False, showColors=False)
        self.threshWidget.controlsOff()

        buttons = qt.QDialogButtonBox()
        buttons.addButton(qt.QDialogButtonBox.Ok)
        buttons.addButton(qt.QDialogButtonBox.Cancel)

        layout.addWidget(self.indexSelector)
        layout.addWidget(self.threshWidget)
        layout.addWidget(buttons)
        layout.addStretch(1)

        self.threshWidget.table.cellChanged.connect(self.onTableEdited)

        self.indexSelector.currentTextChanged.connect(self.updateFilterControls)

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self._updateQueryOptions()

        self.indexSelector.setCurrentIndex(index)
        if self.currentFilter is not None:
            self._redrawHistogram(index - 1)

    def _redrawHistogram(self, filterBy):
        self.threshWidget.show()

        values = self.logic.values(filterBy)

        if self.currentFilter is None or self.currentFilter.column != filterBy:
            elems = self.logic.getSegmentedRepresentationOf(filterBy)
        else:
            elems = self.currentFilter.filterData

        self.threshWidget.loadData(values, elems, groups=self.logic.getSegmentedRepresentationOf(filterBy))

    def _updateQueryOptions(self):
        lock = self.indexSelector.blockSignals(True)
        fillComboBox(self.indexSelector, self.logic.columns(), hasNone=True, defaultValue="None")
        self.indexSelector.blockSignals(lock)

    def updateFilterControls(self, itemText):
        if self.logic is None:
            slicer.util.errorDisplay("TableFilterWidget.colorBy cannot run without a valid logic instance.")
            return

        if itemText == "None":
            self.threshWidget.hide()
            if self.currentFilter is not None:
                self.logic._filters.pop(-1)
                self.currentFilter = None
            return

        alwaysValidItemIndex = self.logic.columns().index(itemText)

        self._redrawHistogram(alwaysValidItemIndex)
        self.onTableEdited()

    def onTableEdited(self):
        itemText = self.indexSelector.currentText
        if itemText == "None":
            return

        alwaysValidItemIndex = self.logic.columns().index(itemText)
        state = self.threshWidget.copyTableState()

        if self.currentFilter is None:
            self.currentFilter = self.logic.addFilters(alwaysValidItemIndex, state)
        else:
            self.currentFilter.filterData = state
            self.currentFilter.column = alwaysValidItemIndex

        if self.masterNode is not None:
            self.logic.updateLabels(self.logic._labels, self.masterNode)
