import configparser
import gc
import json
import logging
import os
import re
import typing
from pathlib import Path

import PySide2
import ctk
import numba
import numpy as np
import pandas as pd
import pyqtgraph as pg
import qt
import slicer
import vtk
from numba import uint32
from numba.types import ListType, Array
from shiboken2 import shiboken2

from ltrace.algorithms.microporosity.modelling import SampleModel, fastMapping, ModelDataTypeError
from ltrace.slicer import helpers, ui, data_utils
from ltrace.slicer.helpers import themeIsDark, BlockSignals
from ltrace.slicer.microct import loadPCRAsTextNode
from ltrace.slicer.ui import hierarchyVolumeInput, FloatInput, ApplyButton
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import (
    GraphicsLayoutWidget,
)
from ltrace.slicer.widget.global_progress_bar import CompanionProgressBar
from ltrace.slicer.widget.histogram_frame import SegmentationModellingHistogramFrame
from ltrace.slicer_utils import LTracePlugin, LTracePluginLogic, LTracePluginWidget


# ----------------


class PCRNotFoundError(Exception):
    """Custom exception for PCR not found errors."""

    def __init__(self, nodeName: str):
        super().__init__(f"No PCR data associated with the image node '{nodeName}'.")


def pcrMinMaxFromTableNode(imageNode):
    try:
        pcrFile = imageNode.GetAttribute("PCR")
        pcrDryTextNode = slicer.mrmlScene.GetNodeByID(pcrFile) if pcrFile else None
        if not pcrDryTextNode:
            raise PCRNotFoundError(imageNode.GetName())

        pcrDry = pcrDryTextNode.GetText()
        parser = configparser.ConfigParser()
        parser.read_string(pcrDry)
        _min = np.float32(parser.getfloat("VolumeData", "Min"))
        _max = np.float32(parser.getfloat("VolumeData", "Max"))

        return _min, _max
    except PCRNotFoundError as e:
        logging.warning(str(e))
        raise
    except Exception as e:
        logging.warning(f"Failed to associate PCR data for Image: {imageNode.GetName()}. Error: {str(e)}")
        raise


def pcrFromFile(targetNode):
    """Open a dialog to select a PCR file, load it as table node and
    return t
    """
    fileDialog = qt.QFileDialog()
    fileDialog.setFileMode(qt.QFileDialog.ExistingFile)
    fileDialog.setNameFilters(["PCR Files (*.pcr)", "Text Files (*.txt)", "All Files (*)"])
    fileDialog.setDirectory(slicer.app.temporaryPath)
    fileDialog.setWindowTitle(f"Select PCR File for {targetNode.GetName()}")
    fileDialog.setModal(True)
    if fileDialog.exec_() == qt.QFileDialog.Accepted:
        try:
            filePath = fileDialog.selectedFiles()[0]
            tableNode = loadPCRAsTextNode(Path(filePath))  # loadPCRInfoIfExist(Path(filePath).parent)
            return tableNode
        except Exception as e:
            logging.error(f"Internal failure: {repr(e)}")
            raise RuntimeError("Failed to load PCR file")

    raise ValueError("No file selected")


class HistogramPGWidget(GraphicsLayoutWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setMinimumSize(self.minimumWidth(), 200)
        self.setMaximumSize(self.maximumWidth(), 200)

        self.plotItem = self.addPlot()
        self.plotItem.showGrid(x=False, y=False)
        self.plotItem.setMouseEnabled(x=False, y=False)
        self.plotItem.getViewBox().setMouseMode(pg.ViewBox.RectMode)

        self.region = pg.LinearRegionItem()
        self.plotItem.addItem(self.region)

        self.histograms = []

    def onRegionChanged(self, handler):
        self.region.sigRegionChanged.connect(lambda item: handler(*item.getRegion()))

    def add_data(self, x, y, color=(255, 0, 0, 150, 127), logY=False):
        if logY:
            y = np.log10(y)
            self.plotItem.setLogMode(y=True)

        if len(color) == 3:
            color = color + (127,)
        histogram = pg.PlotCurveItem(x, y, stepMode="center", fillLevel=0, brush=color)
        self.plotItem.addItem(histogram)
        self.histograms.append(histogram)
        self.update_plot_range()

    def set_region(self, min_val, max_val):
        with BlockSignals(self.region):
            self.region.setRegion([min_val, max_val])

    def get_region(self):
        return self.region.getRegion()

    # def update_range(self):
    #     min_val, max_val = self.region.getRegion()
    #     self.plotItem.setXRange(min_val, max_val, padding=0)

    def set_xrange(self, min_val, max_val):
        self.plotItem.setXRange(min_val, max_val, padding=0.1)

    def update_plot_range(self):
        if not self.histograms:
            return

        min_x = min(histogram.xData[0] for histogram in self.histograms)
        max_x = max(histogram.xData[-1] for histogram in self.histograms)

        # min_y = min(min(histogram.yData) for histogram in self.histograms)
        # max_y = max(max(histogram.yData) for histogram in self.histograms)
        self.plotItem.setXRange(min_x, max_x, padding=0.1)
        # self.region.setRegion([min_x, max_x])

    def set_theme(self, background_color, axis_color, plot_background_color):
        self.setBackground(background_color)
        self.plotItem.getViewBox().setBackgroundColor(plot_background_color)
        self.plotItem.getAxis("left").setPen(pg.mkPen(axis_color))
        self.plotItem.getAxis("bottom").setPen(pg.mkPen(axis_color))
        self.plotItem.getAxis("right").setPen(pg.mkPen(axis_color))
        self.plotItem.getAxis("top").setPen(pg.mkPen(axis_color))
        self.plotItem.getAxis("left").setTextPen(pg.mkPen(axis_color))
        self.plotItem.getAxis("bottom").setTextPen(pg.mkPen(axis_color))
        self.plotItem.getAxis("right").setTextPen(pg.mkPen(axis_color))
        self.plotItem.getAxis("top").setTextPen(pg.mkPen(axis_color))
        self.plotItem.showAxes([True, True, True, True], showValues=True, size=False)


class HistogramWidget(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        qt.QVBoxLayout(self)

        frame = qt.QFrame(self)
        frameLayout = qt.QVBoxLayout(frame)
        frameLayout.setContentsMargins(0, 0, 0, 0)
        pysideLayout = shiboken2.wrapInstance(hash(frameLayout), PySide2.QtWidgets.QVBoxLayout)
        #
        self.histogramWidget = HistogramPGWidget()
        pysideLayout.addWidget(self.histogramWidget)

        self.layout().addWidget(frame)

        bg_color, fg_color, plot_bg_color = (
            ("#3E3E3E", "#FFFFFF", "#1E1E1E") if themeIsDark() else ("#FFFFFF", "#000000", "#FFFFFF")
        )

        self.histogramWidget.set_theme(bg_color, fg_color, plot_bg_color)

        self.logY = True

    def add_data(self, x, y, color=(255, 0, 0, 150)):
        self.histogramWidget.add_data(x, y, color, logY=self.logY)

    def set_region(self, min_val, max_val):
        self.histogramWidget.set_region(min_val, max_val)
        self.histogramWidget.set_region(min_val, max_val)

    def set_limits(self, min_val, max_val):
        self.histogramWidget.set_xrange(min_val, max_val)


def getAssociatedSegmentationNodes(scalarVolumeNode):
    """
    This function receives a scalar volume node and returns all segmentation nodes associated with it.
    """
    if not scalarVolumeNode:
        return []

    associatedSegmentationNodes = []
    scalarVolumeNodeID = scalarVolumeNode.GetID()
    for node in slicer.mrmlScene.GetNodesByClass("vtkMRMLSegmentationNode"):
        if (
            node.GetNodeReferenceID("referenceVolume") == scalarVolumeNodeID
            or node.GetNodeReferenceID("referenceImageGeometryRef") == scalarVolumeNodeID
        ):
            associatedSegmentationNodes.append(node)
    return associatedSegmentationNodes


class ObservableWidget(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._observers = []

    def addObserver(self, observer):
        self._observers.append(observer)

    def notifyObservers(self, *args, **kwargs):
        for observer in self._observers:
            observer(*args, **kwargs)


class SegmentedImageInputWidget(ObservableWidget):

    imageSelected = qt.Signal(str)
    segmentationSelected = qt.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.imageNodeInput = None
        self.segmentationNodeSelectorInput = None

        self.setup()

    def setup(self):
        qt.QFormLayout(self)
        self.setupInputs()
        self.setupConnections()

    def setupInputs(self):
        self.imageNodeInput = hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLScalarVolumeNode"])

        self.segmentationNodeSelectorInput = qt.QComboBox()
        self.segmentationNodeSelectorInput.addItem("None")
        self.addObserver(self.updateSegmentation)

        self.layout().addRow("Image: ", self.imageNodeInput)
        self.layout().addRow("Segmentation: ", self.segmentationNodeSelectorInput)

    def setupConnections(self):
        self.imageNodeInput.currentItemChanged.connect(self.imageSelectedHandler)
        self.segmentationNodeSelectorInput.currentIndexChanged.connect(self.segmentationSelectedHandler)

    def imageSelectedHandler(self, itemHierarchyTreeId):
        treeNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        node = treeNode.GetItemDataNode(itemHierarchyTreeId)

        if not node:
            return

        segmentations = getAssociatedSegmentationNodes(node)

        self.notifyObservers(segmentations)

        self.imageSelected.emit(node.GetID())

    def segmentationSelectedHandler(self, index):
        segmentation = self.segmentationNodeSelectorInput.itemData(index)
        if segmentation:
            self.segmentationSelected.emit(segmentation.GetID())

    def updateSegmentation(self, segmentations):
        self.segmentationNodeSelectorInput.clear()
        self.segmentationNodeSelectorInput.addItem("None")
        for segmentation in segmentations:
            self.segmentationNodeSelectorInput.addItem(segmentation.GetName(), segmentation)


class SegmentedImageWithROIInputWidget(SegmentedImageInputWidget):

    roiSelected = qt.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def setupInputs(self):
        super().setupInputs()

        self.roiNodeSelectorInput = qt.QComboBox()
        self.roiNodeSelectorInput.addItem("None")

        self.addObserver(self.updateROI)

        self.layout().addRow("Mask: ", self.roiNodeSelectorInput)

    def setupConnections(self):
        super().setupConnections()

        self.roiNodeSelectorInput.currentIndexChanged.connect(self.roiSelectedHandler)

    def roiSelectedHandler(self, index):
        roi = self.roiNodeSelectorInput.itemData(index)
        if roi:
            self.roiSelected.emit(roi.GetID())

    def updateROI(self, segmentations):
        self.roiNodeSelectorInput.clear()
        self.roiNodeSelectorInput.addItem("None")
        for segmentation in segmentations:
            self.roiNodeSelectorInput.addItem(segmentation.GetName(), segmentation)


class CheckableSegmentListBoard(qt.QWidget):

    itemChanged = qt.Signal(qt.QListWidgetItem)

    def __init__(self, defaultState=qt.Qt.Unchecked, parent=None):
        super().__init__(parent)

        self.defaultState = defaultState

        qt.QVBoxLayout(self)

        self.segmentList = qt.QListWidget()
        self.segmentList.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Fixed)
        self.segmentList.setFixedHeight(120)

        self.segmentListCollapsible = ctk.ctkCollapsibleButton()
        self.segmentListCollapsible.text = "Segments"
        self.segmentListCollapsible.collapsed = True
        self.segmentListCollapsible.flat = True

        bodyLayout = qt.QVBoxLayout(self.segmentListCollapsible)
        bodyLayout.addWidget(self.segmentList)

        self.layout().addWidget(self.segmentListCollapsible)

        self.segmentList.itemChanged.connect(self.itemChanged)

    def showBoard(self):
        self.segmentListCollapsible.collapsed = False

    def setData(self, node):
        self.segmentList.clear()

        if node is None:
            return

        segmentation = node.GetSegmentation()

        for index in range(segmentation.GetNumberOfSegments()):
            segment = segmentation.GetNthSegment(index)
            if segment:
                self.segmentList.addItem(
                    self.createItem(
                        segment.GetName(),
                        np.array(segment.GetColor() + (1,)),
                        segmentation.GetNthSegmentID(index),
                        self.defaultState,
                    )
                )

    def setStateByID(self, id, state):
        for index in range(self.segmentList.count):
            item = self.segmentList.item(index)
            if item.data(qt.Qt.UserRole) == id:
                item.setCheckState(state)

    def getCheckedItems(self) -> typing.List[str]:
        checkedItems = []
        for index in range(self.segmentList.count):
            item = self.segmentList.item(index)
            if item.checkState() == qt.Qt.Checked:
                if item.data(qt.Qt.UserRole):
                    checkedItems.append(item.data(qt.Qt.UserRole))
        return checkedItems

    @classmethod
    def createItem(cls, name, color, segmentID=None, state=qt.Qt.Unchecked):
        from ltrace.slicer.widgets import ColoredIcon

        item = qt.QListWidgetItem(name)
        item.setFlags(item.flags() | qt.Qt.ItemIsUserCheckable)
        item.setCheckState(state)
        icon = ColoredIcon(*[int(c * 255) for c in color[:3]])
        item.setIcon(icon)
        item.setData(qt.Qt.UserRole, segmentID)
        return item


class DoubleImageWithSegmentationInputWidget(qt.QWidget):

    imageSelected = qt.Signal(str)
    segmentationSelected = qt.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = qt.QFormLayout(self)

        self.saturatedImageNodeInput = hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLScalarVolumeNode"])
        self.saturatedPCRTableNodeInput = hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLTableNode"])
        self.dryImageNodeInput = hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLScalarVolumeNode"])
        self.dryPCRTableNodeInput = hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLTableNode"])

        segmentationSelectorLayout = qt.QHBoxLayout()
        self.segmentationNodeSelectorInput = qt.QComboBox()
        self.segmentationNodeSelectorInput.addItem("None")
        self.roiNodeSelectorInput = qt.QComboBox()
        self.roiNodeSelectorInput.addItem("Optional")

        self.allEnablerCheckBox = qt.QCheckBox("All")

        segmentationSelectorLayout.addWidget(self.segmentationNodeSelectorInput)
        segmentationSelectorLayout.addWidget(self.allEnablerCheckBox)

        self.segmentsBoard = CheckableSegmentListBoard(defaultState=qt.Qt.Checked)

        layout.addRow("Saturated Image: ", self.saturatedImageNodeInput)
        layout.addRow("Dry Image: ", self.dryImageNodeInput)
        layout.addRow("Segmentation: ", segmentationSelectorLayout)
        layout.addRow("Region: ", self.roiNodeSelectorInput)
        layout.addRow(self.segmentsBoard)

        self.saturatedImageNodeInput.currentItemChanged.connect(self.imageSelectedHandler)
        self.dryImageNodeInput.currentItemChanged.connect(self.imageSelectedHandler)

        self.segmentationNodeSelectorInput.currentIndexChanged.connect(self.segmentationSelectedHandler)

        self.segmentationSelected.connect(self.drawSegmentListBoard)

        self.allEnablerCheckBox.toggled.connect(lambda checked: self.updateSegmentation(useAll=checked))

    def imageSelectedHandler(self, itemHierarchyTreeId):
        treeNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        node = treeNode.GetItemDataNode(itemHierarchyTreeId)

        if not node:
            return

        self.updateSegmentation(useAll=self.allEnablerCheckBox.isChecked())

        self.imageSelected.emit(node.GetID())
        self.checkInput(node)

    def updateSegmentation(self, useAll=False):

        self.segmentationNodeSelectorInput.clear()
        self.segmentationNodeSelectorInput.addItem("None")

        self.roiNodeSelectorInput.clear()
        self.roiNodeSelectorInput.addItem("None")

        if useAll:
            for node in slicer.mrmlScene.GetNodesByClass("vtkMRMLSegmentationNode"):
                segName = node.GetName()
                self.segmentationNodeSelectorInput.addItem(segName, node)
                self.roiNodeSelectorInput.addItem(segName, node)
        else:
            saturatedSegmentations = getAssociatedSegmentationNodes(self.saturatedImageNodeInput.currentNode())
            drySegmentations = getAssociatedSegmentationNodes(self.dryImageNodeInput.currentNode())

            set_ = {s.GetID(): s for s in [*saturatedSegmentations, *drySegmentations]}

            for segmentation in set_.values():
                segName = segmentation.GetName()
                self.segmentationNodeSelectorInput.addItem(segName, segmentation)
                self.roiNodeSelectorInput.addItem(segName, segmentation)

    def segmentationSelectedHandler(self, index):
        segmentation = self.segmentationNodeSelectorInput.itemData(index)
        self.segmentationSelected.emit(segmentation.GetID() if segmentation else None)

    def drawSegmentListBoard(self):
        segmentation = self.segmentationNodeSelectorInput.currentData
        self.segmentsBoard.setData(segmentation)
        self.segmentsBoard.showBoard()

    def checkInput(self, node):
        # TODO PCR here is ok? maybe another place
        try:
            minPCR, maxPCR = pcrMinMaxFromTableNode(node)
            logging.info(f"PCR data linked to {node.GetName()} with min: {minPCR} and max: {maxPCR}")
        except:
            pass
            # try:
            #     pcrNode = pcrFromFile(node)
            #
            #     if pcrNode:
            #         node.SetAttribute("PCR", pcrNode.GetID())
            #
            #     minPCR, maxPCR = pcrMinMaxFromTableNode(node)
            #
            #     logging.info(f"PCR file loaded for {node.GetName()} with min: {minPCR} and max: {maxPCR}")
            # except FileNotFoundError:
            #     logging.debug("No PCR file found in the directory")
            # except:
            #     import traceback
            #
            #     traceback.print_exc()
            #     logging.warning(f"Failed to load PCR for Image: {node.GetName()}")


class FactorsWidget(qt.QWidget):

    fieldFactorChanged = qt.Signal(float, float)

    def __init__(self, lowerInputText: str, higherInputText: str, parent=None):
        super().__init__(parent)

        self.normalized = False

        self.dataSource: SampleModel = None
        self.num_bins = 500

        # ---- UI ----
        layout = qt.QVBoxLayout(self)

        inputsForm = qt.QFrame()
        input_layout = qt.QFormLayout(inputsForm)

        self.lowerInput = FloatInput()
        self.lowerInput.objectName = "pormapfromsat.Factor[{lowerInputText}]"
        input_layout.addRow(qt.QLabel(f"{lowerInputText}: "), self.lowerInput)

        self.higherInput = FloatInput()
        self.higherInput.objectName = f"pormapfromsat.Factor[{higherInputText}]"
        input_layout.addRow(qt.QLabel(f"{higherInputText}: "), self.higherInput)

        self.histogramPlot = HistogramWidget()

        layout.addWidget(inputsForm)
        layout.addWidget(self.histogramPlot)

        self.lowerInput.editingFinished.connect(self.factorsChanged)
        self.higherInput.editingFinished.connect(self.factorsChanged)

    def setDataSource(self, dataSource: SampleModel):
        self.dataSource = dataSource
        self.histogramPlot.histogramWidget.onRegionChanged(self.regionChanged)
        self.fieldFactorChanged.connect(self.histogramPlot.set_region)

    def plotData(self):
        for var in self.dataSource.variables.values():
            # y, x = np.histogram(var.values, bins=self.num_bins)
            x = np.arange(var.start, var.start + len(var.values) + 1)
            self.histogramPlot.add_data(x, var.values, color=var.color)

        limits = self.dataSource.limits
        self.histogramPlot.set_limits(*limits)

        regionLimits = sorted(
            [
                self.dataSource.threshold("Porous", self.normalized)[0],
                self.dataSource.threshold("Calcite", self.normalized)[0],
            ]
        )

        self.setFactors(regionLimits)
        self.factorsChanged()

    def regionChanged(self, lowerValue: float, higherValue: float):
        self.dataSource.setThreshold("Porous", np.array([lowerValue]), self.normalized)
        self.dataSource.setThreshold("Calcite", np.array([higherValue]), self.normalized)

        self.setFactors([lowerValue, higherValue])  ## TODO move that to a signal/callback

    def factorsChanged(self):
        self.fieldFactorChanged.emit(self.lowerInput.value, self.higherInput.value)

    def setFactors(self, thresholds):
        with BlockSignals(self.lowerInput):
            self.lowerInput.setValue(np.round(thresholds[0], 4))

        with BlockSignals(self.higherInput):
            self.higherInput.setValue(np.round(thresholds[-1], 4))


class PorosityMapHistogramFrame(SegmentationModellingHistogramFrame):
    def __init__(self, parent=None, region_widget=None, view_widget=None):
        super().__init__(parent, region_widget, view_widget, num_channels=2)

    def _get_region_values(self):
        if self.region_widget is not None:
            return (
                self.region_widget.min_attenuation_factor(),
                self.region_widget.max_attenuation_factor(),
            )
        return 0, 65535


# ----------------


class PorosityMappingFromSaturation(LTracePlugin):
    SETTING_KEY = "PorosityMappingFromSaturation"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Porosity Mapping From Saturation"
        self.parent.categories = ["MicroCT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ""

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PorosityMappingFromSaturationWidget(LTracePluginWidget):
    def __init__(self, parent=None) -> None:
        LTracePluginWidget.__init__(self, parent)

    def enter(self):
        if self.inputWidget.dryImageNodeInput.currentNode() or self.inputWidget.saturatedImageNodeInput.currentNode():
            index = self.inputWidget.segmentationNodeSelectorInput.currentIndex
            self.inputWidget.segmentationNodeSelectorInput.setCurrentIndex(0)
            self.inputWidget.segmentationNodeSelectorInput.setCurrentIndex(index)
            roiIndex = self.inputWidget.roiNodeSelectorInput.currentIndex
            self.inputWidget.roiNodeSelectorInput.setCurrentIndex(0)
            self.inputWidget.roiNodeSelectorInput.setCurrentIndex(roiIndex)

    def setup(self):
        LTracePluginWidget.setup(self)

        self.logic = PorosityMappingFromSaturationLogic()

        self.setupInputPanel()
        self.setupTunningPanel()

        self.outputFormWidget = qt.QWidget()
        formOutput = qt.QFormLayout(self.outputFormWidget)
        self.prefixOutputLineEdit = qt.QLineEdit()
        self.prefixOutputLineEdit.objectName = "pormapfromsat.prefixOutputLineEdit"
        formOutput.addRow("Output Image:", self.prefixOutputLineEdit)

        self.prefixOutputLineEdit.setText("Porosity Map")

        self.applyCancelButton = ui.ApplyCancelButtons(
            onApplyClick=self.onApplyClicked, onCancelClick=self.onCancelClicked
        )

        self.progressBar = CompanionProgressBar()

        self.layout.addWidget(self.outputFormWidget)
        self.layout.addWidget(self.applyCancelButton)
        self.layout.addWidget(self.progressBar)

        self.layout.addStretch(1)

        self.computeButton.setEnabled(False)
        self.applyCancelButton.setEnabled(False)

        self.logic.addProgressObserver(lambda value: self.progressBar.update(value))

    def setupInputPanel(self):

        self.inputWidget = DoubleImageWithSegmentationInputWidget()
        self.inputWidget.setObjectName("pormapfromsat.inputWidget")

        self.messageLabel = qt.QLabel()
        self.messageLabel.setWordWrap(True)
        self.messageLabel.setText("Select the images and the segmentation to compute the porosity mapping.")

        self.porousSegmentSelector = qt.QComboBox()
        self.referenceSolidSegmentSelector = qt.QComboBox()

        comboWidget = qt.QWidget()
        comboForm = qt.QFormLayout(comboWidget)
        comboForm.addRow("Porous Segment: ", self.porousSegmentSelector)
        comboForm.addRow("Ref. Solid Segment: ", self.referenceSolidSegmentSelector)
        comboForm.addRow(self.messageLabel)

        self.computeButton = ApplyButton(text="Initialize")

        self.inputCollapsible = ctk.ctkCollapsibleButton()
        self.inputCollapsible.text = "Inputs"
        layout = qt.QVBoxLayout(self.inputCollapsible)

        layout.addWidget(self.inputWidget)
        layout.addWidget(comboWidget)
        layout.addWidget(self.computeButton)

        self.layout.addWidget(self.inputCollapsible)

        def setupSegments():

            self.porousSegmentSelector.clear()
            self.referenceSolidSegmentSelector.clear()

            segmentationNode = self.inputWidget.segmentationNodeSelectorInput.currentData
            if not segmentationNode:
                return

            segmentation = segmentationNode.GetSegmentation()
            checkedSegments = self.inputWidget.segmentsBoard.getCheckedItems()
            _, backgroundSegmentId = self.logic.getSegmentIdFor(
                segmentation, checkedSegments, "background", "bg", "fundo", "ignore", "nda"
            )

            self.inputWidget.segmentsBoard.setStateByID(backgroundSegmentId, qt.Qt.Unchecked)

            checkedSegments = self.inputWidget.segmentsBoard.getCheckedItems()

            self.porousSegmentSelector.clear()
            self.referenceSolidSegmentSelector.clear()

            self.porousSegmentSelector.addItem("None", None)
            self.referenceSolidSegmentSelector.addItem("None", None)

            for sid in checkedSegments:
                segment = segmentation.GetSegment(sid)
                self.porousSegmentSelector.addItem(segment.GetName(), sid)
                self.referenceSolidSegmentSelector.addItem(segment.GetName(), sid)

            calciteLabel, calciteSegmentId = self.logic.getSegmentIdFor(segmentation, checkedSegments, "calcit")
            porousLabel, porousSegmentId = self.logic.getSegmentIdFor(segmentation, checkedSegments, "poro", "pore")

            self.porousSegmentSelector.setCurrentIndex(self.porousSegmentSelector.findData(porousSegmentId))
            self.referenceSolidSegmentSelector.setCurrentIndex(
                self.referenceSolidSegmentSelector.findData(calciteSegmentId)
            )

        def initialization():

            try:
                if not self.computeInputsAreAvailable(0):
                    slicer.util.warningDisplay("Please select valid inputs before applying.")
                    return

                pcrOption = self.askPCRFiles()
                if not pcrOption:
                    return

                pcrDryRange, pcrWetRange = pcrOption

                self.progressBar.start("model_building", timeout=3600)

                try:
                    tic = timer()
                    models = self.logic.dryWetModel(
                        self.inputWidget.dryImageNodeInput.currentNode(),
                        self.inputWidget.saturatedImageNodeInput.currentNode(),
                        self.inputWidget.segmentationNodeSelectorInput.currentData,
                        self.inputWidget.segmentsBoard.getCheckedItems(),
                        [self.porousSegmentSelector.currentData, self.referenceSolidSegmentSelector.currentData],
                        pcrDryRange,
                        pcrWetRange,
                        self.inputWidget.roiNodeSelectorInput.currentData,
                    )
                    toc = timer()
                    print("Elapsed time 1", toc - tic)
                except Exception as e:
                    slicer.util.errorDisplay(f"Failed to compute models. {str(e)}")
                    return

                if len(models) != 2:
                    slicer.util.warningDisplay(f"Failed to compute models. Expected 2, received {len(models)} models.")
                    return

                self.factorTunningDry.setDataSource(models[0])
                self.factorTunningDry.plotData()

                self.factorTunningWet.setDataSource(models[1])
                self.factorTunningWet.plotData()

                gc.collect()

                self.applyCancelButton.setEnabled(True)
            except Exception as e:
                import traceback

                traceback.print_exc()
                slicer.util.warningDisplay("Failed to compute some result nodes. Check the error logs.")
            finally:
                # TODO implement completed with errors
                if self.progressBar.isRunning():
                    self.progressBar.update(1.0)

        self.computeButton.clicked.connect(initialization)
        self.inputWidget.segmentationSelected.connect(setupSegments)
        self.inputWidget.segmentsBoard.itemChanged.connect(lambda _: setupSegments())
        self.porousSegmentSelector.currentIndexChanged.connect(self.computeInputsAreAvailable)
        self.referenceSolidSegmentSelector.currentIndexChanged.connect(self.computeInputsAreAvailable)

    def setupTunningPanel(self):

        self.tunningTabs = qt.QTabWidget()

        self.factorTunningDry = FactorsWidget("Dry porous", "Dry calcite")

        self.factorTunningWet = FactorsWidget("Wet porous", "Wet calcite")

        self.tunningTabs.addTab(self.factorTunningDry, "Dry")
        self.tunningTabs.addTab(self.factorTunningWet, "Wet")

        self.tunningCollapsible = ctk.ctkCollapsibleButton()
        self.tunningCollapsible.text = "Tunning"
        layout = qt.QVBoxLayout(self.tunningCollapsible)
        layout.addWidget(self.tunningTabs)

        self.layout.addWidget(self.tunningCollapsible)

    def askPCRFiles(self):
        dryImageNode = self.inputWidget.dryImageNodeInput.currentNode()
        wetImageNode = self.inputWidget.saturatedImageNodeInput.currentNode()

        missing = []
        try:
            pcrDryRange = self.logic.getMinMaxFromPCR(dryImageNode)
        except:
            missing.append("dry")

        try:
            pcrWetRange = self.logic.getMinMaxFromPCR(wetImageNode)
        except:
            missing.append("saturated")

        if not missing:
            return pcrDryRange, pcrWetRange

        message = (
            f"Cannot find PCR in the [{', '.join(missing)}] image(s) node(s). To add PCR files, please select "
            f"the images again and a window to find the file will show.\n"
            f"Do you really want to continue without PCRs?"
        )
        confirmed = slicer.util.confirmYesNoDisplay(message)

        if not confirmed:
            return None

        pcrDryRange = dryImageNode.GetImageData().GetScalarRange()
        pcrWetRange = wetImageNode.GetImageData().GetScalarRange()

        return pcrDryRange, pcrWetRange

    def showFactorsOnHistogram(self):
        dialog = qt.QDialog()
        dialog.setWindowTitle("Porosity Mapping")

        dialogLayout = qt.QVBoxLayout(dialog)

        self.histogramPlotDry = PorosityMapHistogramFrame(parent=dialog)
        self.histogramPlotWet = PorosityMapHistogramFrame(parent=dialog)

        segmentationNode = self.inputWidget.segmentationNodeSelectorInput.currentData
        segmentation = segmentationNode.GetSegmentation()

        calciteSegmentId = self.referenceSolidSegmentSelector.currentData
        porousSegmentId = self.porousSegmentSelector.currentData

        to_RGB = lambda color: tuple(np.array(color) * 255)
        colors = [
            to_RGB(segmentation.GetSegment(calciteSegmentId).GetColor()),
            to_RGB(segmentation.GetSegment(porousSegmentId).GetColor()),
        ]

        self.histogramPlotDry.set_data(
            self.logic.cached_dry_result.full_image,
            [self.logic.cached_dry_result.calcite_image > 0, self.logic.cached_dry_result.porous_image > 0],
            colors,
            update_plot_auto_zoom=True,
        )
        self.histogramPlotDry.set_region(
            self.logic.cached_dry_result.porous_image_x_int, self.logic.cached_dry_result.calcite_image_x_int
        )
        self.histogramPlotWet.set_data(
            self.logic.cached_sat_result.full_image,
            [self.logic.cached_sat_result.calcite_image > 0, self.logic.cached_sat_result.porous_image > 0],
            colors,
            update_plot_auto_zoom=True,
        )
        self.histogramPlotWet.set_region(
            self.logic.cached_sat_result.porous_image_x_int, self.logic.cached_sat_result.calcite_image_x_int
        )

        dialogLayout.addWidget(self.histogramPlotDry)
        dialogLayout.addWidget(self.histogramPlotWet)

        dialog.exec_()

    def computeInputsAreAvailable(self, index):
        dryImageNode = self.inputWidget.dryImageNodeInput.currentNode()
        wetImageNode = self.inputWidget.saturatedImageNodeInput.currentNode()

        if not dryImageNode or not wetImageNode:
            self.messageLabel.setText("Select the images and the segmentation to compute the porosity mapping.")
            return False

        if not self.inputWidget.segmentationNodeSelectorInput.currentData:
            self.messageLabel.setText("Select the segmentation to compute the porosity mapping.")
            return False

        if not self.inputWidget.segmentsBoard.getCheckedItems():
            self.messageLabel.setText("Select at least two segments to compute the porosity mapping.")
            return False

        if self.porousSegmentSelector.currentData is None:
            self.messageLabel.setText("Select at least one porous segment to compute the porosity mapping.")
            return False

        if self.referenceSolidSegmentSelector.currentData is None:
            self.messageLabel.setText("Select at least one solid segment to compute the porosity mapping.")
            return False

        self.messageLabel.setText("Setup complete. Click on Initialize to compute the models.")

        self.computeButton.setEnabled(True)

        return True

    def onCancelClicked(self):
        self.showFactorsOnHistogram()

    def onApplyClicked(self):

        if not self.computeInputsAreAvailable(0):
            slicer.util.warningDisplay("Please select valid inputs before applying.")
            return

        self.progressBar.start("volume_computation", timeout=3600)

        try:
            porousId = self.porousSegmentSelector.currentData
            refSolidId = self.referenceSolidSegmentSelector.currentData

            segments = self.inputWidget.segmentsBoard.getCheckedItems()
            targetLabels = [segments.index(porousId) + 1, segments.index(refSolidId) + 1]

            dryImageNode = self.inputWidget.dryImageNodeInput.currentNode()
            wetImageNode = self.inputWidget.saturatedImageNodeInput.currentNode()

            self.progressBar.update(0.11)

            # Create a directory tree to save the results
            folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            workDir = folderTree.GetItemParent(folderTree.GetItemByDataNode(dryImageNode))
            outputDir = folderTree.CreateFolderItem(workDir, "Porosity Mapping Results")

            # compute the results
            self.logic.computeVolume(
                self.factorTunningDry.dataSource, self.factorTunningWet.dataSource, targetLabels, outputDir
            )

            segNode = self.inputWidget.segmentationNodeSelectorInput.currentData
            segNode.GetDisplayNode().SetVisibility(False)

            roiNode = self.inputWidget.roiNodeSelectorInput.currentData
            if roiNode:
                roiNode.GetDisplayNode().SetVisibility(False)

            self.progressBar.update(0.9)

            segNode = self.inputWidget.segmentationNodeSelectorInput.currentData
            segmentation = segNode.GetSegmentation()

            targets = [segmentation.GetSegment(porousId).GetName(), segmentation.GetSegment(refSolidId).GetName()]
            segmentNames = [segmentation.GetSegment(sid).GetName() for sid in segments]

            self.logic.computeTable(
                "PorosityMap",
                dryImageNode,
                wetImageNode,
                segmentNames,
                targets,
                self.factorTunningDry.dataSource,
                self.factorTunningWet.dataSource,
                outputDir,
            )

        except Exception as e:
            import traceback

            traceback.print_exc()

            slicer.util.warningDisplay("Failed to compute some result nodes. Check the error logs.")
        finally:
            self.progressBar.update(1.0)

    def plotModels(self, models):
        if len(models) != 2:
            slicer.util.warningDisplay(f"Failed to compute models. Expected 2, received {len(models)} models.")
            return

        self.factorTunningDry.setDataSource(models[0])
        self.factorTunningDry.plotData()

        self.factorTunningWet.setDataSource(models[1])
        self.factorTunningWet.plotData()

        gc.collect()


@numba.njit
def inplaceAnd(a: Array, b: Array):
    dimX, dimY, dimZ = a.shape
    for x in range(dimX):
        for y in range(dimY):
            for z in range(dimZ):
                a[x, y, z] *= (a[x, y, z] > 0) & b[x, y, z]
    return a


@numba.njit
def jittedMultiConditionBinCountUInt32(
    imageArray: Array, conditions: ListType(Array), expectations: ListType(uint32), size: uint32
):
    result = np.zeros(size + 1, dtype=np.uint32)
    dimX, dimY, dimZ = imageArray.shape
    maxvalue = 0
    for x in range(dimX):
        for y in range(dimY):
            for z in range(dimZ):

                for i in range(len(conditions)):
                    condition = conditions[i]
                    target = expectations[i]
                    if condition[x, y, z] != target:
                        break
                else:
                    value = imageArray[x, y, z]
                    result[value] += 1

                    if value > maxvalue:
                        maxvalue = value

    return result[: maxvalue + 1]


# @numba.njit
# def fast3DBinCount(imageArray: Array, buffer: Array):
#     dimX, dimY, dimZ = imageArray.shape
#     maxvalue = 0
#
#     for x in range(dimX):
#         for y in range(dimY):
#             for z in range(dimZ):
#                 value = imageArray[x, y, z]
#                 buffer[value] += 1
#
#                 if value > maxvalue:
#                     maxvalue = value
#
#     return buffer[: maxvalue + 1]


def multiConditionBinCountUInt32(imageArray, conditions, size):
    conds = [cond for cond, _ in conditions]
    evalues = [np.uint32(val) for _, val in conditions]

    return jittedMultiConditionBinCountUInt32(imageArray, conds, evalues, np.uint32(size))


def numpyTest(imageArray, filters):
    R = imageArray * ((filters[0][0] == filters[0][1]) & (filters[1][0] == filters[1][1]))
    return np.bincount(R.ravel())


def numpyExpr(imageArray, filters):
    import numexpr as ne

    # R = imageArray * ((filters[0][0] == filters[0][1]) & (filters[1][0] == filters[1][1]))
    R = ne.evaluate(
        "a * ((ba == bv) & (ca == cv))",
        local_dict={
            "a": imageArray,
            "ba": filters[0][0],
            "bv": filters[0][1],
            "ca": filters[1][0],
            "cv": filters[1][1],
        },
    )
    return np.bincount(R.ravel())


def modelRegionX(imageArray, filters):
    # Compute the attenuation factor for the modelled region
    return multiConditionBinCountUInt32(imageArray, filters, 65535)
    # return litehistogram(imageArray, 1000, filters[0][0] == filters[0][1] & filters[1][0] == filters[1][1], 1)


from timeit import default_timer as timer


# def convertToNumpyArray(imageData):
#     point_data = imageData.GetPointData().GetScalars()
#     arr = vn.vtk_to_numpy(point_data)
#     dimensions = imageData.GetDimensions()
#     return arr.reshape(dimensions[::-1])
#
#
# def applyMask(imageData, maskData):
#     calciteFilter = vtk.vtkImageMask()
#     calciteFilter.SetInputData(imageData)
#     calciteFilter.SetMaskInputData(maskData)
#     calciteFilter.Update()
#     return calciteFilter.GetOutput()


class PorosityMappingFromSaturationLogic(LTracePluginLogic):
    def __init__(self):
        self.__lastLabelsArray = None
        self.__lastMaskArray = None
        self.__lastReferenceNodeID = None
        self.__progressCallback = lambda p: None
        self.__expectedPrefix = ""

    def addProgressObserver(self, callback):
        self.__progressCallback = callback

    def modelRegionBench(self, imageArray, filters):
        funcs = [(numpyTest, "numpy"), (numpyExpr, "expr"), (modelRegionX, "model")]
        options = np.random.choice([0, 1, 2], 100, replace=True)
        timings = {"numpy": [], "expr": [], "model": []}
        for i in options:
            f = funcs[i]
            tic = timer()
            f[0](imageArray, filters)
            toc = timer()
            if len(timings[f[1]]) < 7:
                timings[f[1]].append(toc - tic)

            if all(len(timings[k]) == 7 for k in timings):
                break

        print(
            "numpy",
            np.mean(timings["numpy"]),
            np.std(timings["numpy"]),
            np.min(timings["numpy"]),
            np.max(timings["numpy"]),
            len(timings["numpy"]),
        )
        print(
            "expr",
            np.mean(timings["expr"]),
            np.std(timings["expr"]),
            np.min(timings["expr"]),
            np.max(timings["expr"]),
            len(timings["expr"]),
        )
        print(
            "model",
            np.mean(timings["model"]),
            np.std(timings["model"]),
            np.min(timings["model"]),
            np.max(timings["model"]),
            len(timings["model"]),
        )

    # def runDryWetModel(self, dryImageNode, wetImageNode, segmentationNode, segments, targets, maskNode=None):
    #
    #     dry_min, dry_max = self.getMinMaxFromPCR(dryImageNode)
    #     wet_min, wet_max = self.getMinMaxFromPCR(wetImageNode)
    #
    #     segmentation = segmentationNode.GetSegmentation()
    #
    #     targetNames = ["Porous", "Calcite"]
    #
    #     if len(targets) != len(targetNames):
    #         raise ValueError("Targets and targetNames must have the same length")
    #
    #     targetLabelMapNode = exportSelectedSegments(segments, segmentationNode, dryImageNode)
    #
    #     to_RGB = lambda color: tuple(np.array(color) * 255)
    #
    #     cliArgs = {
    #         "dryImageNode": dryImageNode.GetID(),
    #         "wetImageNode": wetImageNode.GetID(),
    #         "labelsNode": targetLabelMapNode.GetID(),
    #         "maskNode": maskNode.GetID() if maskNode else None,
    #         "params": json.dumps({
    #             "segments": segments,
    #             "labels": {tid: segments.index(tid) + 1 for tid in targets},
    #             "pcr_dry": (float(dry_min), float(dry_max)),
    #             "pcr_wet": (float(wet_min), float(wet_max)),
    #             "colors": {tid: to_RGB(segmentation.GetSegment(tid).GetColor()) for tid in targets},
    #             "names": {tid: targetNames[i] for i, tid in enumerate(targets)},
    #             "outputBuffer": str(Path(slicer.app.temporaryPath).absolute() / "pms_output_buffer.pkl")
    #         }),
    #     }
    #
    #     cliNode = slicer.cli.run(slicer.modules.pmsmodelbuildcli, None, cliArgs)
    #
    #     return cliNode

    def captureExpectedName(self, name):
        # replace all mentions for dry, wet, sat, limpa, seca. Name example: RJS704_F9018H_SAT_P_38000nm.
        # All those words has underscores around them. Must be case insensitive
        return re.sub(r"_(dry|wet|sat|limpa|seca)_", "_", name, flags=re.IGNORECASE)

    def getPrefixName(self):
        return self.__expectedPrefix

    def dryWetModel(
        self, dryImageNode, wetImageNode, segmentationNode, segments, targets, pcrDryRange, pcrWetRange, maskNode=None
    ):
        to_RGB = lambda color: tuple(np.array(color) * 255)

        # TODO inform factor UI that there is no normalization

        segmentation = segmentationNode.GetSegmentation()
        porousSegmentId, calciteSegmentId = targets

        targetLabelMapNode = exportSelectedSegments(segments, segmentationNode, dryImageNode)

        self.__progressCallback(0.17)

        try:
            # must be copied because its gonna be edited inplace
            labeledArray = slicer.util.arrayFromVolume(targetLabelMapNode)

            if maskNode:
                # TODO trocar para o binary oriented
                maskSegments = [maskNode.GetSegmentation().GetSegmentIDs()[0]]
                maskLabelMapNode = exportSelectedSegments(maskSegments, maskNode, dryImageNode)
                maskArray = np.array(slicer.util.arrayFromVolume(maskLabelMapNode), copy=True, dtype=np.bool8)
                labeledArray = labeledArray * maskArray
            else:
                maskArray = labeledArray > 0

            self.__progressCallback(0.26)

            models = []
            for imageNode, pcr in [(dryImageNode, pcrDryRange), (wetImageNode, pcrWetRange)]:
                imageArray = slicer.util.arrayFromVolume(imageNode)

                sample = SampleModel(pcr)
                sample.addData(imageArray, maskArray, color=(128, 128, 128, 128))

                porousLabel = segments.index(porousSegmentId) + 1
                sample.addSubGroup(
                    "Porous",
                    labeledArray == porousLabel,
                    porousLabel,
                    to_RGB(segmentation.GetSegment(porousSegmentId).GetColor()),
                    markers=[0.5],
                )

                calciteLabel = segments.index(calciteSegmentId) + 1
                sample.addSubGroup(
                    "Calcite",
                    labeledArray == calciteLabel,
                    calciteLabel,
                    to_RGB(segmentation.GetSegment(calciteSegmentId).GetColor()),
                    markers=[0.5],
                )

                models.append(sample)

            self.__progressCallback(0.83)

            self.__lastLabelsArray = np.array(labeledArray, copy=True, dtype=np.uint32)
            self.__lastMaskArray = maskArray
            self.__lastReferenceNodeID = dryImageNode.GetID()
            self.__expectedPrefix = self.captureExpectedName(dryImageNode.GetName())

            return models
        except ModelDataTypeError as mde:
            raise RuntimeError(f"Please, check the input data TYPE. {str(mde)}")
        except Exception as e:
            import traceback

            traceback.print_exc()
            raise
        finally:
            helpers.removeTemporaryNodes()

    def getSegmentIdFor(self, segmentation, segments, *suffixes):
        # TODO make it KISS or use a better function name
        import re

        patterns = "|".join(suffixes) if len(suffixes) > 1 else suffixes[0]
        pattern = re.compile(rf"^{patterns}.*", re.IGNORECASE)
        for i, sid in enumerate(segments):
            segment = segmentation.GetSegment(sid)
            segname = segment.GetName().lower()
            if pattern.match(segname):
                return i + 1, sid

        return 0, None

    def getMinMaxFromPCR(self, node):
        minPCR, maxPCR = pcrMinMaxFromTableNode(node)
        return minPCR, maxPCR

    def computeVolume(self, dryModel: SampleModel, wetModel: SampleModel, targets, outputDir):

        if self.__lastReferenceNodeID is None or self.__lastLabelsArray is None:
            slicer.util.warningDisplay(
                "No previous model found. Please, select the inputs and click on the initialize "
                "button to compute a new porosity model."
            )
            return

        try:
            porousWet = wetModel.threshold("Porous", normalized=True)
            calciteWet = wetModel.threshold("Calcite", normalized=True)
            porousDry = dryModel.threshold("Porous", normalized=True)
            calciteDry = dryModel.threshold("Calcite", normalized=True)

            factor = porousWet - calciteWet - porousDry + calciteDry

            def piecewiseDiff():
                # Hack note: Normalization uses too much memory, so we need to do it in place
                arr = wetModel.getImage(normalized=True)
                arr -= calciteWet
                gc.collect()
                arr -= dryModel.getImage(normalized=True)
                arr += calciteDry
                arr /= factor
                gc.collect()
                return arr

            porosityImageFloat = fastMapping(piecewiseDiff(), self.__lastLabelsArray, self.__lastMaskArray, targets)

            self.__progressCallback(0.85)

            volume = helpers.createTemporaryVolumeNode(slicer.vtkMRMLScalarVolumeNode, "PorosityMap")
            slicer.util.updateVolumeFromArray(volume, porosityImageFloat)
            volume.Modified()

            refNode = slicer.util.getNode(self.__lastReferenceNodeID)
            volume.CopyOrientation(refNode)
            volume.Modified()
            helpers.moveNodeTo(outputDir, volume)

            helpers.makeTemporaryNodePermanent(volume, show=True)
            slicer.util.setSliceViewerLayers(background=volume, foreground=None, label=None, fit=True)
            volume.GetDisplayNode().SetVisibility(False)
            volume.GetDisplayNode().SetVisibility(True)

        except Exception as e:
            logging.error(f"Failed to compute volume: {e}")
            raise
        finally:
            helpers.removeTemporaryNodes()
            gc.collect()

    def computeTable(
        self,
        resultName: str,
        dryImageNode,
        wetImageNode,
        segments,
        targets,
        dryModel: SampleModel,
        wetModel: SampleModel,
        outputDir,
    ):

        try:
            resultNode = helpers.tryGetNode(resultName)
            if not resultNode:
                return

            resultArray = slicer.util.arrayFromVolume(resultNode)
            porosityMean = np.mean(resultArray[self.__lastMaskArray])

            bins = np.bincount(self.__lastLabelsArray.ravel())
            bins[0] = 0
            total = np.sum(bins)

            proportions = 100 * bins / total

            tableNode = helpers.createTemporaryNode(slicer.vtkMRMLTableNode, "Porosity Map Info")
            tableDF = pd.DataFrame(
                data={
                    "Dry Volume": dryImageNode.GetName(),
                    "Saturated Volume": wetImageNode.GetName(),
                    "Porous Segment": targets[0],
                    "Ref. Solid Segment": targets[1],
                    "Porosity": porosityMean,
                    "Calcite Dry": dryModel.threshold("Calcite", normalized=False),
                    "Calcite Wet": wetModel.threshold("Calcite", normalized=False),
                    "Porous Dry": dryModel.threshold("Porous", normalized=False),
                    "Porous Wet": wetModel.threshold("Porous", normalized=False),
                    **{f"{segments[i - 1]}%": proportions[i] for i in range(1, len(segments) + 1)},
                }
            )

            data_utils.dataFrameToTableNode(tableDF, tableNode)
            resultNode.SetAttribute("info", tableNode.GetID())
            tableNode.Modified()

            helpers.moveNodeTo(outputDir, tableNode)
            helpers.makeTemporaryNodePermanent(tableNode, show=True)
        except Exception as e:
            logging.error(f"Failed to compute table: {e}")
            raise
        finally:
            helpers.removeTemporaryNodes()
            gc.collect()


def convertListToVTKArray(segments: typing.List[str]):
    vtkSegmentIds = vtk.vtkStringArray()
    for segment_id in segments:
        vtkSegmentIds.InsertNextValue(segment_id)
    return vtkSegmentIds


def exportSelectedSegments(segments, segmentationNode, referenceNode, outputNode=None):
    if not outputNode:
        outputNode = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLLabelMapVolumeNode, "TempLabelmap", uniqueName=True, hidden=False
        )

    vtkSegmentIds = convertListToVTKArray(segments)
    slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
        segmentationNode, vtkSegmentIds, outputNode, referenceNode
    )

    return outputNode


# TODO suffix name
# TODO mover apply pro CLI
# TODO mask não precisa ir pra cache
