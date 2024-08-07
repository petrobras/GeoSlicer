import os
from ast import literal_eval
from functools import partial
import logging
import numpy as np
import pyqtgraph as pg
import PySide2 as ps

import vtk, qt, slicer
from SegmentEditorEffects import *
from SegmentEditorEffects.SegmentEditorThresholdEffect import PreviewPipeline

from ltrace.algorithms.common import randomChoice
from ltrace.image.optimized_transforms import DEFAULT_NULL_VALUE
from ltrace.slicer.helpers import getVolumeNullValue, getPythonQtWidget, hide_masking_widget
from ltrace.slicer.ui import numberParamInt
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget

from ltrace.slicer_utils import LTraceSegmentEditorEffectMixin


class SegmentEditorEffect(AbstractScriptedSegmentEditorEffect, LTraceSegmentEditorEffectMixin):
    """MultiThresholdEffect is an effect that performs thresholding with multiple segments
    at the same time by editing the thresholds on a histogram.
    """

    MAX_SAMPLES = int(3e4)
    SIDE_BY_SIDE_LAYOUT_ID = 201
    CONVENTIONAL_LAYOUT_ID = 2
    HIGH_PERCENTILE = 99.95

    def __init__(self, scriptedEffect):
        AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)

        scriptedEffect.name = "Multiple Threshold"
        scriptedEffect.perSegment = False
        scriptedEffect.requireSegments = True

        self.defaults = {}

        self.nullValue = lambda: self.defaults.get("nullableValue", DEFAULT_NULL_VALUE)
        self.transitions = list()
        self._observerHandlers = list()
        self.segmentationNode = None
        self.svalues = None
        self._hist_bars = None
        self.binsNumber = 400

        self.previewState = 0
        self.previewStep = 1
        self.previewSteps = 7
        self.timer = qt.QTimer()
        self.timer.connect("timeout()", self.preview)
        self.timer.setParent(self.scriptedEffect.optionsFrame())
        self.previewPipelines = {}
        self.setupPreviewDisplay()
        self.renderedLayout = None
        self.rederedInSideBySide = None
        self.rederedInConventional = None
        self.tableWidth = 0

        self.applyFinishedCallback = lambda: None
        self.applyAllSupported = True

    def clone(self):
        import qSlicerSegmentationsEditorEffectsPythonQt as effects

        clonedEffect = effects.qSlicerSegmentEditorScriptedEffect(None)
        clonedEffect.setPythonSource(__file__.replace("\\", "/"))
        return clonedEffect

    def icon(self):
        iconPath = os.path.join(os.path.dirname(__file__), "SegmentEditorEffect.png")
        if os.path.exists(iconPath):
            return qt.QIcon(iconPath)
        return qt.QIcon()

    def helpText(self):
        return """<html>Apply thresholds to multiple segments at a time<br><p>
The user adds the segments via the add segment button on the main segment editor control and selects the thresholds
via controls on the histogram plot or typing in the table next to it.
<b>Initialize with K-means:</b> The thresholds are initialized based on a K-Means segmentation of the dataset using
the number of clusters equal to the number of segments added to the segmentation.
<b>Apply:</b> the thresholds are applied and a segmentation is generated.
<p></html>"""

    def activate(self):
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("Segment editor node is not available.")
            return

        self.SetSourceVolumeIntensityMaskOff()
        hide_masking_widget(self)
        self.sourceVolumeNodeChanged()

        # Hide current segmentation
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if segmentationNode:
            should_redraw_histogram = False
            transitions_list_str = segmentationNode.GetAttribute("MultipleThresholdTransitions")
            histogram_range_str = segmentationNode.GetAttribute("MultipleThresholdXAxisRange")
            number_of_bins_str = segmentationNode.GetAttribute("MultipleThresholdNumberOfBins")
            if transitions_list_str and len(literal_eval(transitions_list_str)) == len(self.getColors()) + 1:
                self.transitions = np.array(literal_eval(transitions_list_str), dtype="float")
                should_redraw_histogram = True
            if histogram_range_str and len(literal_eval(histogram_range_str)):
                histogram_range = literal_eval(histogram_range_str)
                self.zoomSlider.setMinimumValue(histogram_range[0])
                self.zoomSlider.setMaximumValue(histogram_range[1])
                should_redraw_histogram = True
            if number_of_bins_str and 50 <= int(number_of_bins_str) <= 1000:
                self.binsNumber = int(number_of_bins_str)
                should_redraw_histogram = True
            if should_redraw_histogram:
                self.redrawHistogram()
            displayNode = segmentationNode.GetDisplayNode()
            if displayNode:
                displayNode.VisibilityOff()

        layoutManager = slicer.app.layoutManager()
        self.renderedLayout = layoutManager.layout
        # 201 is SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ID
        self.rederedInSideBySide = self.renderedLayout == self.SIDE_BY_SIDE_LAYOUT_ID
        self.rederedInConventional = self.renderedLayout == self.CONVENTIONAL_LAYOUT_ID
        # Setup and start preview pulse
        self.setupPreviewDisplay()
        self.timer.start(200)

    def deactivate(self):
        self.rederedInSideBySide = False
        self.rederedInConventional = False
        self.svalues = None
        self.clearPreviewDisplay()
        self.timer.stop()

        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("Segment editor node is not available.")
            return

        # Show current segmentation
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if segmentationNode:
            displayNode = segmentationNode.GetDisplayNode()
            if displayNode:
                displayNode.VisibilityOn()

        self.SetSourceVolumeIntensityMaskOff()

    def setMRMLDefaults(self):
        pass

    def setupOptionsFrame(self):
        parametersCollapsibleButton = qt.QWidget()
        self.scriptedEffect.addOptionsWidget(parametersCollapsibleButton)

        parametersFormLayout = qt.QFormLayout()
        parametersCollapsibleButton.setLayout(parametersFormLayout)

        self.enablePulsingCheckbox = qt.QCheckBox("Preview pulse")
        self.enablePulsingCheckbox.setCheckState(qt.Qt.Checked)
        parametersFormLayout.addRow(self.enablePulsingCheckbox)

        self.figureGroup = ps.QtWidgets.QWidget()
        self.figureGroup.setMinimumWidth(150)
        self.figureGroup.setMaximumHeight(250)

        axisLayout = ps.QtWidgets.QHBoxLayout(self.figureGroup)
        axisLayout.setContentsMargins(0, 0, 0, 0)
        axisLayout.setSpacing(5)

        graphicsLayoutWidget = GraphicsLayoutWidget()
        graphicsLayoutWidget.setSizePolicy(ps.QtWidgets.QSizePolicy.Expanding, ps.QtWidgets.QSizePolicy.Expanding)
        self.table = ps.QtWidgets.QTableWidget()

        axisLayout.addWidget(graphicsLayoutWidget, 1)
        axisLayout.addWidget(self.table, 0)

        self.table.setSizePolicy(ps.QtWidgets.QSizePolicy.Fixed, ps.QtWidgets.QSizePolicy.Expanding)

        self.hist_plot = graphicsLayoutWidget.addPlot()
        self.hist_plot.setMouseEnabled(False, False)
        self.hist_plot.setMenuEnabled(False)
        self.hist_plot.hideAxis("left")

        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["min", "max"])
        self.table.horizontalHeader().setSectionResizeMode(ps.QtWidgets.QHeaderView.ResizeToContents)

        parametersFormLayout.addRow(getPythonQtWidget(self.figureGroup))

        # Slide bar to zoom the histogram
        zoomGroup = qt.QWidget()
        zoomLayout = qt.QHBoxLayout(zoomGroup)

        zoomLabel = qt.QLabel("X-axis range:")
        zoomLabel.setToolTip("Set the x range of the displayed histogram.")
        parametersFormLayout.addRow(zoomLabel)

        self.zoomSlider = ctk.ctkRangeWidget()

        zoomLayout.addWidget(zoomLabel)
        zoomLayout.addWidget(self.zoomSlider)

        parametersFormLayout.addRow(zoomGroup)

        #
        # Apply Button
        #
        applyKMeansGroup = qt.QWidget()
        hlayout = qt.QHBoxLayout(applyKMeansGroup)

        self.bins_box = numberParamInt(vrange=(50, 1000), value=self.binsNumber)

        buttonStyle = "QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 4px}"
        self.kMeansButton = qt.QPushButton("Initialize with K-means")
        self.kMeansButton.toolTip = "Initialize threshold limits with the K-means algorithm."
        self.kMeansButton.setStyleSheet(buttonStyle)
        self.kMeansButton.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.toolTip = "Run the algorithm."

        self.applyButton.setStyleSheet(buttonStyle)
        self.applyButton.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Minimum)

        self.applyFullButton = qt.QPushButton("Apply to full volume")
        self.applyFullButton.toolTip = "Run the algorithm on the full volume."
        self.applyFullButton.setStyleSheet(buttonStyle)
        self.applyFullButton.visible = False
        self.applyFullButton.clicked.connect(self.onApplyFull)

        hlayout.addWidget(qt.QLabel("Number of bins: "))
        hlayout.addWidget(self.bins_box)
        hlayout.addWidget(self.kMeansButton)
        hlayout.addWidget(self.applyButton)
        hlayout.addWidget(self.applyFullButton)
        parametersFormLayout.addRow(applyKMeansGroup)

        self.bins_box.valueChanged.connect(self.onBinsChanged)

        # connections
        self.zoomSlider.connect("valuesChanged(double,double)", self.onThresholdValuesChanged)
        self.applyButton.connect("clicked()", self.onApply)
        self.kMeansButton.connect("clicked()", self.applyKmeans)
        self.table.cellChanged.connect(self.onCellChanged)

    def onCloseScene(self, *args):
        self.redrawHistogram([], None)

    def onClassRemoval(self):
        pass

    def onBinsChanged(self, value):
        self.binsNumber = value
        self.hist, self.bin_edges = np.histogram(self.svalues, bins=self.binsNumber)
        self.hist += 1
        self.hist = np.log(self.hist)
        self.redrawHistogram()

    def createCursor(self, widget):
        # Turn off effect-specific cursor for this effect
        return slicer.util.mainWindow().cursor

    def getParentLazyNode(self):
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("Segment editor node is not available.")
            return

        node = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
        parentLazyNodeId = node.GetAttribute("ParentLazyNode")
        if parentLazyNodeId:
            lazyNode = slicer.mrmlScene.GetNodeByID(parentLazyNodeId)
            if lazyNode:
                return lazyNode
        return None

    def sourceVolumeNodeChanged(self):
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("Segment editor node is not available.")
            return

        self.applyFullButton.visible = False

        if self.scriptedEffect.parameterSetNode().GetActiveEffectName() != self.scriptedEffect.name:
            return
        node = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()

        self._null = getVolumeNullValue(node) or self.nullValue()
        if node is None:
            narray = None
        else:
            narray = slicer.util.arrayFromVolume(node)
        self.createHistogram(narray)
        self.applyFullButton.visible = self.applyAllSupported and self.getParentLazyNode() is not None

    def createHistogram(self, nparray=None, k=None):
        self.colors = self.getColors()
        if k is None:
            k = len(self.colors)
        if nparray is not None:
            self.svalues = self.sampleDataset(nparray)
            self.hist, self.bin_edges = np.histogram(self.svalues, bins=self.binsNumber)
            self.hist += 1
            self.hist = np.log(self.hist)
            self._min = np.min(self.svalues)
            self._max = np.max(self.svalues)
            self._percentile_low = self._min
            self._percentile_high = np.percentile(self.svalues, self.HIGH_PERCENTILE)
            self.isInt = np.issubdtype(self.svalues.dtype, np.integer)
        if k > 0:
            if len(self.transitions) < 1 or k != len(self.transitions) - 1:
                self.transitions = np.linspace(self._min + (self._max - self._min) * 0.2, self._max, len(self.colors))
                self.transitions = np.append(self._min, self.transitions)

        single_step = (self._max - self._min) / 100
        self.zoomSlider.setRange(self._min, self._max + single_step)
        self.zoomSlider.singleStep = single_step
        if self._percentile_low and self._percentile_high != 0:
            self.zoomSlider.setMinimumValue(self._percentile_low)
            self.zoomSlider.setMaximumValue(self._percentile_high)
        else:
            self.zoomSlider.setMinimumValue(self._min)
            self.zoomSlider.setMaximumValue(self._max)
        self.applyKmeans()

    def getColors(self):
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("Segment editor node is not available.")
            return []

        self.colorsBySegment = dict()
        segmentIDs = vtk.vtkStringArray()
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        segmentation = segmentationNode.GetSegmentation()
        segmentation.GetSegmentIDs(segmentIDs)
        colors = list()
        for index in range(segmentIDs.GetNumberOfValues()):
            segment = segmentation.GetNthSegment(index)
            colors.append(segment.GetColor())
            self.colorsBySegment[segmentIDs.GetValue(index)] = segment.GetColor()
        return colors

    def sampleDataset(self, nparray):
        return self.pooling(np.ravel(nparray), self.MAX_SAMPLES)

    def pooling(self, voxelArray, max_samples):
        samples = np.min([np.size(voxelArray), max_samples])
        voxelArrayPool = randomChoice(voxelArray, samples, self._null)
        min = np.min(voxelArray)
        max = np.max(voxelArray)
        voxelArrayPool[0] = min if min != self._null else voxelArrayPool[0]
        voxelArrayPool[-1] = max if max != self._null else voxelArrayPool[-1]
        return voxelArrayPool

    def getTransitions(self, centroids):
        centroids = np.sort(centroids)
        transitions = (centroids[:-1] + centroids[1:]) / 2
        return transitions

    def redrawHistogram(self, onlyBars=False):
        self.hist_plot.setLimits(xMin=self.zoomSlider.minimumValue, xMax=self.zoomSlider.maximumValue)

        if not onlyBars:
            self.hist_plot.clear()
        if self._hist_bars is not None:
            for item in self._hist_bars:
                self.hist_plot.removeItem(item)
        hist = self.hist
        wid = self.bin_edges[1] - self.bin_edges[0]
        bin_edges = (self.bin_edges[1:] + self.bin_edges[0:-1]) / 2
        gray = (64, 64, 64)
        black = (0, 0, 0)
        if len(self.transitions) > 0:
            if not onlyBars:
                self.lrlist = list()

            if self.transitions[0] > self._min:
                x = bin_edges[bin_edges <= self.transitions[0]]
                y = hist[bin_edges <= self.transitions[0]]
                bg1 = pg.BarGraphItem(x=x, width=wid, height=y, brush=black, pen=gray)
                self.hist_plot.addItem(bg1)

            for i in range(len(self.transitions) - 1):
                x = bin_edges[np.logical_and(bin_edges >= self.transitions[i], bin_edges <= self.transitions[i + 1])]
                y = hist[np.logical_and(bin_edges >= self.transitions[i], bin_edges <= self.transitions[i + 1])]
                self._hist_bars = list()
                bg1 = pg.BarGraphItem(
                    x=x, width=wid, height=y, brush=np.array(self.colors[i]) * 255, pen=np.array(self.colors[i]) * 255
                )
                self.hist_plot.addItem(bg1)
                self._hist_bars.append(bg1)
                if not onlyBars:
                    lr = pg.LinearRegionItem([self.transitions[i], self.transitions[i + 1]], swapMode="push")
                    lr.setZValue(-100)
                    self.hist_plot.addItem(lr)
                    lr.sigRegionChanged.connect(partial(self.regionChanged, i, lr))
                    self.lrlist.append(lr)
                hist = hist[bin_edges > self.transitions[i + 1]]
                bin_edges = bin_edges[bin_edges > self.transitions[i + 1]]

        if len(bin_edges) > 0:
            bg1 = pg.BarGraphItem(x=bin_edges, width=wid, height=hist, brush=black, pen=gray)
            self.hist_plot.addItem(bg1)

        self.drawTable()

    def drawTable(self):
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("Segment editor node is not available.")
            return

        self.table.blockSignals(True)
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        segmentation = segmentationNode.GetSegmentation()
        nSegments = segmentation.GetNumberOfSegments()

        self.table.setRowCount(nSegments)
        for i in range(nSegments):
            segmentID = segmentation.GetNthSegmentID(i)
            segment_name = segmentation.GetSegment(segmentID).GetName()
            item = ps.QtWidgets.QTableWidgetItem("")
            item.setFlags(ps.QtCore.Qt.ItemIsEnabled)
            item_color = segmentation.GetSegment(segmentID).GetColor()
            self.table.setVerticalHeaderItem(i, item)

            item.setBackground(ps.QtGui.QColor.fromRgbF(item_color[0], item_color[1], item_color[2]))
            for j in range(2):
                minThresh, maxThresh = self.lrlist[i].getRegion()
                item1 = ps.QtWidgets.QTableWidgetItem()
                item1.setData(ps.QtCore.Qt.EditRole, minThresh)
                item2 = ps.QtWidgets.QTableWidgetItem()
                item2.setData(ps.QtCore.Qt.EditRole, maxThresh)
                self.table.setItem(i, 0, item1)
                self.table.setItem(i, 1, item2)

        self.table.blockSignals(False)

        # Keep the table width mostly stable
        qApp = ps.QtWidgets.QApplication.instance()
        scrollbarWidth = qApp.style().pixelMetric(ps.QtWidgets.QStyle.PM_ScrollBarExtent)
        vHeaderWidth = self.table.verticalHeader().width()
        hHeaderWidth = self.table.horizontalHeader().length()
        newTableWidth = max(scrollbarWidth + vHeaderWidth + hHeaderWidth, self.tableWidth)
        if newTableWidth > self.tableWidth:
            self.tableWidth = newTableWidth + 10
        self.table.setFixedWidth(self.tableWidth)

    def onCellChanged(self, rowIdx, colIdx):
        er = ps.QtCore.Qt.EditRole
        changedItem = self.table.item(rowIdx, colIdx)
        data = changedItem.data(er)

        transitionIdx = rowIdx + (1 if colIdx == 1 else 0)
        self.transitions[transitionIdx] = data
        for i in range(len(self.transitions)):
            if i < transitionIdx and self.transitions[i] > data:
                self.transitions[i] = data
            if i > transitionIdx and self.transitions[i] < data:
                self.transitions[i] = data

        self.redrawHistogram()

    def regionChanged(self, segment, lr, test):
        regCurrent = lr.getRegion()
        self.transitions[segment] = regCurrent[0]
        self.transitions[segment + 1] = regCurrent[1]

        self.lrlist[segment].blockSignals(True)
        self.lrlist[segment].setRegion(regCurrent)
        self.lrlist[segment].blockSignals(False)

        if segment > 0:
            regMinus = self.lrlist[segment - 1].getRegion()
            self.lrlist[segment - 1].blockSignals(True)
            self.lrlist[segment - 1].setRegion((regMinus[0], regCurrent[0]))
            self.lrlist[segment - 1].blockSignals(False)
        if segment < len(self.colors) - 1:
            regPlus = self.lrlist[segment + 1].getRegion()
            self.lrlist[segment + 1].blockSignals(True)
            self.lrlist[segment + 1].setRegion((regCurrent[1], regPlus[1]))
            self.lrlist[segment + 1].blockSignals(False)

        self.redrawHistogram(onlyBars=True)

    def onApply(self):
        if self.scriptedEffect.parameterSetNode() is None:
            slicer.util.errorDisplay("Failed to apply the effect. The selected node is not valid.")
            return

        self.timer.stop()
        self.clearPreviewDisplay()
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        displayNode = segmentationNode.GetDisplayNode()
        displayNode.VisibilityOn()

        with slicer.util.NodeModify(segmentationNode):
            segmentation = segmentationNode.GetSegmentation()
            self.scriptedEffect.saveStateForUndo()
            segmentIds = vtk.vtkStringArray()
            segmentation.GetSegmentIDs(segmentIds)

            for i in range(segmentIds.GetNumberOfValues()):
                try:
                    # Set current selected segment
                    segmentid = segmentIds.GetValue(i)
                    self.scriptedEffect.parameterSetNode().SetSelectedSegmentID(segmentid)
                    # Get master volume image data
                    import vtkSegmentationCorePython as vtkSegmentationCore

                    sourceImageData = self.scriptedEffect.sourceVolumeImageData()
                    # Get modifier labelmap
                    modifierLabelmap = self.scriptedEffect.defaultModifierLabelmap()
                    originalImageToWorldMatrix = vtk.vtkMatrix4x4()
                    modifierLabelmap.GetImageToWorldMatrix(originalImageToWorldMatrix)
                    # Get parameters
                    min = self.transitions[i]
                    max = self.transitions[i + 1]
                    # Perform thresholding
                    thresh = vtk.vtkImageThreshold()
                    thresh.SetInputData(sourceImageData)
                    if self.isInt:
                        min = np.ceil(min)
                    thresh.ThresholdBetween(min, max)
                    thresh.SetInValue(1)
                    thresh.SetOutValue(0)
                    thresh.SetOutputScalarType(modifierLabelmap.GetScalarType())
                    thresh.Update()
                    modifierLabelmap.DeepCopy(thresh.GetOutput())
                except IndexError:
                    logging.error("apply: Failed to threshold master volume!")
                    # Apply changes
                self.scriptedEffect.modifySelectedSegmentByLabelmap(
                    modifierLabelmap, slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet
                )

            segmentationNode.SetAttribute("MultipleThresholdTransitions", str(self.transitions.tolist()))
            histogram_range = [self.zoomSlider.minimumValue, self.zoomSlider.maximumValue]
            segmentationNode.SetAttribute("MultipleThresholdXAxisRange", str(histogram_range))
            segmentationNode.SetAttribute("MultipleThresholdNumberOfBins", str(self.binsNumber))

            # De-select effect
            self.scriptedEffect.selectEffect("")
            self.applyFinishedCallback()

    def onApplyFull(self):
        if self.scriptedEffect.parameterSetNode() is None:
            slicer.util.errorDisplay("Failed to apply the effect. The selected node is not valid.")
            return

        slicer.util.selectModule("MultipleThresholdBigImage")
        virtualSegWidget = slicer.modules.MultipleThresholdBigImageWidget

        segmentNames = []
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        segmentation = segmentationNode.GetSegmentation()
        segmentIDs = vtk.vtkStringArray()
        segmentation.GetSegmentIDs(segmentIDs)
        for i in range(segmentIDs.GetNumberOfValues()):
            segmentNames.append(segmentation.GetSegment(segmentIDs.GetValue(i)).GetName())

        virtualSegWidget.setParams(self.getParentLazyNode(), self.transitions.tolist(), self.colors, segmentNames)

    def clearObservers(self):
        for object, tag in self._observerHandlers:
            object.RemoveObserver(tag)
        self._observerHandlers.clear()

    def resetObservers(self):
        self.clearObservers()

        if self.segmentationNode is None:
            return

        self._observerHandlers.append(
            (
                self.segmentationNode,
                self.segmentationNode.AddObserver(
                    self.segmentationNode.GetSegmentation().RepresentationModified, self.onSegmentationNodeModified
                ),
            )
        )
        self._observerHandlers.append(
            (
                self.segmentationNode,
                self.segmentationNode.AddObserver(
                    self.segmentationNode.GetSegmentation().SegmentAdded, self.onSegmentationNodeModified
                ),
            )
        )
        self._observerHandlers.append(
            (
                self.segmentationNode,
                self.segmentationNode.AddObserver(
                    self.segmentationNode.GetSegmentation().SegmentRemoved, self.onSegmentationNodeModified
                ),
            )
        )
        self._observerHandlers.append(
            (
                self.segmentationNode,
                self.segmentationNode.AddObserver(
                    self.segmentationNode.GetSegmentation().SegmentModified, self.onSegmentationNodeModified
                ),
            )
        )

    def updateGUIFromMRML(self):
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("Segment editor node is not available.")
            return

        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if self.segmentationNode != segmentationNode:
            self.segmentationNode = segmentationNode
            self.resetObservers()
        if self.svalues is not None:
            _min = np.min(self.svalues)
            _max = np.max(self.svalues)
            self.hist_plot.setXRange(_min, _max)
            _percentile_low = _min
            _percentile_high = np.percentile(self.svalues, self.HIGH_PERCENTILE)
            self._percentile_low = _percentile_low
            self._percentile_high = _percentile_high
            self._min = _min
            self._max = _max

    def applyKmeans(self):
        if self.scriptedEffect.parameterSetNode() is None:
            slicer.util.errorDisplay("Failed to apply. The selected node is invalid.")
            return

        from scipy.cluster.vq import kmeans2

        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        segmentation = segmentationNode.GetSegmentation()
        nsegs = segmentation.GetNumberOfSegments()
        centroids, labelmap = kmeans2(self.svalues.astype("float"), int(nsegs), iter=100, minit="points")
        self.transitions = self.getTransitions(centroids)
        self.transitions = np.append(self._min, self.transitions)
        self.transitions = np.append(self.transitions, self._max)

        self.redrawHistogram()

    def onSegmentationNodeModified(self, caller, event):
        self.clearPreviewDisplay()

        self.colors = self.getColors()

        if len(self.transitions) != len(self.colors) + 1:
            self.transitions = np.linspace(self._min + (self._max - self._min) * 0.2, self._max, len(self.colors))
            self.transitions = np.append(self._min, self.transitions)

        self.setupPreviewDisplay()
        self.redrawHistogram()

    def updateMRMLFromGUI(self):
        pass

    def clearPreviewDisplay(self):
        for sliceWidget, pipelines in self.previewPipelines.items():
            for i in range(len(self.colors)):
                if i < len(pipelines):
                    self.scriptedEffect.removeActor2D(sliceWidget, pipelines[i].actor)

        self.previewPipelines = {}
        self.tableWidth = 0

    def setupPreviewDisplay(self):
        # Clear previous pipelines before setting up the new ones
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return

        # Add a pipeline for each 2D slice view
        for sliceViewName in layoutManager.sliceViewNames():
            sliceWidget = layoutManager.sliceWidget(sliceViewName)
            if not self.scriptedEffect.segmentationDisplayableInView(sliceWidget.mrmlSliceNode()):
                continue
            renderer = self.scriptedEffect.renderer(sliceWidget)
            if renderer is None:
                logging.error("setupPreviewDisplay: Failed to get renderer!")
                continue

            # Create one pipeline for each segment
            pipelines = []

            for i in range(len(self.colors)):
                pipelines.append(PreviewPipeline())

            self.previewPipelines[sliceWidget] = pipelines

            # Add one actor for each pipeline created actor
            for i in range(len(self.colors)):
                self.scriptedEffect.addActor2D(sliceWidget, pipelines[i].actor)

    def preview(self):
        if self.renderedLayout != slicer.app.layoutManager().layout:
            self.changeLayoutPreview(slicer.app.layoutManager().layout)
        if not self.scriptedEffect.optionsFrame().visible:
            return
        if self.enablePulsingCheckbox.checkState() == qt.Qt.Checked:
            # opacity = 0.5 + self.previewState / (2. * self.previewSteps)
            opacity = self.previewState / (self.previewSteps)
        else:
            opacity = 1.0
        # Get color of edited segment
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if not segmentationNode:
            # scene was closed while preview was active
            return
        displayNode = segmentationNode.GetDisplayNode()
        if displayNode is None:
            logging.error("preview: Invalid segmentation display node!")

        for sliceWidget in self.previewPipelines:
            layerLogic = self.getSourceVolumeLayerLogic(sliceWidget)

            for i, key in enumerate(self.colorsBySegment.keys()):
                r, g, b = self.colors[i]
                min = self.transitions[i]
                max = self.transitions[i + 1]
                if i >= len(self.previewPipelines[sliceWidget]):
                    continue
                segmentVisibility = segmentationNode.GetDisplayNode().GetSegmentVisibility(key)
                pipeline = self.previewPipelines[sliceWidget][i]
                if segmentVisibility:
                    pipeline.lookupTable.SetTableValue(1, r, g, b, opacity)
                else:
                    pipeline.lookupTable.SetTableValue(1, r, g, b, 0)
                pipeline.thresholdFilter.SetInputConnection(layerLogic.GetReslice().GetOutputPort())
                if self.isInt:
                    min = np.ceil(min)
                pipeline.thresholdFilter.ThresholdBetween(min, max)
                pipeline.actor.VisibilityOn()

            sliceWidget.sliceView().scheduleRender()

        self.previewState += self.previewStep
        if self.previewState >= self.previewSteps:
            self.previewStep = -1
        if self.previewState <= 0:
            self.previewStep = 1

    def changeLayoutPreview(self, currentLayout):
        self.deactivate()

        if not self.rederedInConventional or not self.rederedInSideBySide:
            self.activate()
            self.renderedLayout = currentLayout
            self.rederedInConventional = True
            self.rederedInSideBySide = True

    def getSourceVolumeLayerLogic(self, sliceWidget):
        sourceVolumeNode = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
        sliceLogic = sliceWidget.sliceLogic()

        backgroundLogic = sliceLogic.GetBackgroundLayer()
        backgroundVolumeNode = backgroundLogic.GetVolumeNode()
        if sourceVolumeNode == backgroundVolumeNode:
            return backgroundLogic

        foregroundLogic = sliceLogic.GetForegroundLayer()
        foregroundVolumeNode = foregroundLogic.GetVolumeNode()
        if sourceVolumeNode == foregroundVolumeNode:
            return foregroundLogic

        # logging.warning("Master volume is not set as either the foreground or background")

        foregroundOpacity = 0.0
        if foregroundVolumeNode:
            compositeNode = sliceLogic.GetSliceCompositeNode()
            foregroundOpacity = compositeNode.GetForegroundOpacity()

        if foregroundOpacity > 0.5:
            return foregroundLogic

        return backgroundLogic

    def onThresholdValuesChanged(self):
        self.redrawHistogram()
