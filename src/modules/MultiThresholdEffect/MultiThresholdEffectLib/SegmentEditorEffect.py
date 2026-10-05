import os
from ast import literal_eval
from functools import partial
import logging
import numpy as np
import pyqtgraph as pg
import PySide2 as ps

import vtk, qt, slicer, ctk
from SegmentEditorEffects import *
from SegmentEditorEffects.SegmentEditorThresholdEffect import PreviewPipeline

from ltrace.algorithms.common import randomChoice
from ltrace.image.optimized_transforms import DEFAULT_NULL_VALUES
from ltrace.slicer.helpers import getVolumeNullValue, getPythonQtWidget, hide_masking_widget, tryGetNode
from ltrace.slicer.ui import numberParamInt
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget

from ltrace.slicer_utils import LTraceSegmentEditorEffectMixin
from ltrace.slicer.debounce_caller import DebounceCaller


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

        self.nullValue = lambda: self.defaults.get("nullableValue", DEFAULT_NULL_VALUES)
        self.ranges = list()
        self.linkEndpoints = True
        self._observerHandlers = list()
        self.segmentationNode = None
        self.svalues = None
        self._hist_bars = None
        self.binsNumber = 400

        self.previewState = 0
        self.previewStep = 1
        self.previewSteps = 7
        self.timer = qt.QTimer(self.scriptedEffect.optionsFrame())
        self.timer.timeout.connect(self.preview)
        self.previewPipelines = {}
        self.setupPreviewDisplay()
        self.renderedLayout = None
        self.rederedInSideBySide = None
        self.rederedInConventional = None
        self.tableWidth = 0
        self.stashedRanges = None

        self.applyFinishedCallback = lambda: None
        self.applyAllSupported = True
        self.segmentationChangedDebounceCaller = DebounceCaller(
            parent=self.scriptedEffect.optionsFrame(),
            intervalMs=200,
        )
        self.segmentationChangedDebounceCaller.triggered.connect(self.onSegmentationChangedHandler)

    def cleanup(self):
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None

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
            link_endpoints_str = segmentationNode.GetAttribute("MultipleThresholdLinkEndpoints")
            if transitions_list_str and len(literal_eval(transitions_list_str)) == len(self.getColors()):
                self.ranges = [list(r) for r in literal_eval(transitions_list_str)]
                should_redraw_histogram = True
            if link_endpoints_str is not None:
                self.linkEndpoints = link_endpoints_str == "True"
                self.linkEndpointsButton.blockSignals(True)
                self.linkEndpointsButton.setChecked(self.linkEndpoints)
                self.updateLinkEndpointsButtonAppearance()
                self.linkEndpointsButton.blockSignals(False)
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
        self.clearObservers()
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
        self.parametersCollapsibleButton = qt.QWidget()
        self.scriptedEffect.addOptionsWidget(self.parametersCollapsibleButton)

        self.parametersFormLayout = qt.QFormLayout()
        self.parametersCollapsibleButton.setLayout(self.parametersFormLayout)

        self.figureGroup = ps.QtWidgets.QWidget()
        self.figureGroup.setMinimumWidth(150)
        self.figureGroup.setMaximumHeight(250)

        self.axisLayout = ps.QtWidgets.QHBoxLayout(self.figureGroup)
        self.axisLayout.setContentsMargins(0, 0, 0, 0)
        self.axisLayout.setSpacing(5)

        self.graphicsLayoutWidget = GraphicsLayoutWidget()
        self.graphicsLayoutWidget.setSizePolicy(
            ps.QtWidgets.QSizePolicy.Policy.Expanding, ps.QtWidgets.QSizePolicy.Policy.Expanding
        )

        self.table = ps.QtWidgets.QTableWidget()
        self.table.setSizePolicy(ps.QtWidgets.QSizePolicy.Policy.Fixed, ps.QtWidgets.QSizePolicy.Policy.Expanding)

        self.linkEndpointsButton = ps.QtWidgets.QToolButton()
        self._linkOnIcon = ps.QtGui.QIcon(":/Icons/LinkOn.png")
        self._linkOffIcon = ps.QtGui.QIcon(":/Icons/LinkOff.png")
        self.linkEndpointsButton.setIconSize(ps.QtCore.QSize(16, 16))
        self.linkEndpointsButton.setCheckable(True)
        self.linkEndpointsButton.setChecked(self.linkEndpoints)
        self.linkEndpointsButton.setFixedSize(24, 24)
        self.linkEndpointsButton.toggled.connect(self.onLinkEndpointsChanged)
        self.updateLinkEndpointsButtonAppearance()

        self.axisLayout.addWidget(self.graphicsLayoutWidget, 1)
        self.axisLayout.addWidget(self.table, 0)

        self.hist_plot = self.graphicsLayoutWidget.addPlot()
        self.hist_plot.setMouseEnabled(False, False)
        self.hist_plot.setMenuEnabled(False)
        self.hist_plot.hideAxis("left")

        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["min", "max"])
        self.table.horizontalHeader().setSectionResizeMode(ps.QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.figureGroupPythonQt = getPythonQtWidget(self.figureGroup)
        self.parametersFormLayout.addRow(self.figureGroupPythonQt)

        #
        # Preview settings
        #
        self.enablePulsingCheckbox = qt.QCheckBox("Preview pulse")
        self.enablePulsingCheckbox.setCheckState(qt.Qt.Checked)

        self.pulseAndLinkRow = qt.QWidget()
        pulseAndLinkRowLayout = qt.QHBoxLayout(self.pulseAndLinkRow)
        pulseAndLinkRowLayout.setContentsMargins(0, 0, 0, 0)
        pulseAndLinkRowLayout.addWidget(self.enablePulsingCheckbox)
        pulseAndLinkRowLayout.addStretch(1)
        pulseAndLinkRowLayout.addWidget(getPythonQtWidget(self.linkEndpointsButton))
        self.parametersFormLayout.addRow(self.pulseAndLinkRow)

        self.opacityRow = qt.QWidget()
        opacityRowLayout = qt.QHBoxLayout(self.opacityRow)
        opacityRowLayout.setContentsMargins(0, 0, 0, 0)
        self.previewOpacitySlider = ctk.ctkSliderWidget()
        self.previewOpacitySlider.minimum = 0.0
        self.previewOpacitySlider.maximum = 1.0
        self.previewOpacitySlider.singleStep = 0.05
        self.previewOpacitySlider.value = 0.5
        opacityRowLayout.addWidget(qt.QLabel("Opacity:"))
        opacityRowLayout.addWidget(self.previewOpacitySlider)
        self.opacityRow.setVisible(not self.enablePulsingCheckbox.isChecked())
        self.parametersFormLayout.addRow(self.opacityRow)

        self.enablePulsingCheckbox.stateChanged.connect(
            lambda state: self.opacityRow.setVisible(state != qt.Qt.Checked)
        )

        # Slide bar to zoom the histogram
        zoomGroup = qt.QWidget()
        zoomLayout = qt.QHBoxLayout(zoomGroup)

        zoomLabel = qt.QLabel("X-axis range:")
        zoomLabel.setToolTip("Set the x range of the displayed histogram.")
        self.parametersFormLayout.addRow(zoomLabel)

        self.zoomSlider = ctk.ctkRangeWidget()

        zoomLayout.addWidget(zoomLabel)
        zoomLayout.addWidget(self.zoomSlider)

        self.parametersFormLayout.addRow(zoomGroup)

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
        self.parametersFormLayout.addRow(applyKMeansGroup)

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
        return slicer.modules.AppContextInstance.mainWindow.cursor

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
            if len(self.ranges) != k:
                boundaries = np.linspace(self._min + (self._max - self._min) * 0.2, self._max, len(self.colors))
                boundaries = np.append(self._min, boundaries)
                self.ranges = [[boundaries[i], boundaries[i + 1]] for i in range(len(boundaries) - 1)]

        single_step = (self._max - self._min) / 100
        self.zoomSlider.setRange(self._min, self._max + single_step)
        self.zoomSlider.singleStep = single_step
        if self._percentile_low and self._percentile_high != 0:
            self.zoomSlider.setMinimumValue(self._percentile_low)
            self.zoomSlider.setMaximumValue(self._percentile_high)
        else:
            self.zoomSlider.setMinimumValue(self._min)
            self.zoomSlider.setMaximumValue(self._max)

        if self.stashedRanges is None:
            self.applyKmeans()
        else:
            self.ranges = self.stashedRanges
            segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
            segmentationNode.SetAttribute("MultipleThresholdTransitions", str(self.ranges))
            self.stashedRanges = None
            self.redrawHistogram()

    def getColors(self):
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("Segment editor node is not available.")
            return []

        self.colorsBySegment = dict()
        segmentIDs = vtk.vtkStringArray()
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if segmentationNode is None:
            return []

        segmentation = segmentationNode.GetSegmentation()
        colors = list()
        for index in range(segmentation.GetNumberOfSegments()):
            segmentID = segmentation.GetNthSegmentID(index)
            segment = segmentation.GetSegment(segmentID)
            colors.append(segment.GetColor())
            self.colorsBySegment[segmentID] = segment.GetColor()
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
        if len(self.ranges) > 0:
            if not onlyBars:
                self.lrlist = list()

            if self.ranges[0][0] > self._min:
                x = bin_edges[bin_edges <= self.ranges[0][0]]
                y = hist[bin_edges <= self.ranges[0][0]]
                bg1 = pg.BarGraphItem(x=x, width=wid, height=y, brush=black, pen=gray)
                self.hist_plot.addItem(bg1)

            for i in range(len(self.ranges)):
                rmin, rmax = self.ranges[i]
                x = bin_edges[np.logical_and(bin_edges >= rmin, bin_edges <= rmax)]
                y = hist[np.logical_and(bin_edges >= rmin, bin_edges <= rmax)]
                self._hist_bars = list()
                bg1 = pg.BarGraphItem(
                    x=x, width=wid, height=y, brush=np.array(self.colors[i]) * 255, pen=np.array(self.colors[i]) * 255
                )
                self.hist_plot.addItem(bg1)
                self._hist_bars.append(bg1)
                if not onlyBars:
                    lr = pg.LinearRegionItem([rmin, rmax], swapMode="push")
                    lr.setZValue(-100)
                    self.hist_plot.addItem(lr)
                    lr.sigRegionChanged.connect(partial(self.regionChanged, i, lr))
                    self.lrlist.append(lr)
                hist = hist[bin_edges > rmax]
                bin_edges = bin_edges[bin_edges > rmax]

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
            item.setFlags(ps.QtCore.Qt.ItemFlag.ItemIsEnabled)
            item_color = segmentation.GetSegment(segmentID).GetColor()
            self.table.setVerticalHeaderItem(i, item)

            item.setBackground(ps.QtGui.QColor.fromRgbF(item_color[0], item_color[1], item_color[2]))
            for j in range(2):
                minThresh, maxThresh = self.lrlist[i].getRegion()
                item1 = ps.QtWidgets.QTableWidgetItem()
                item1.setData(ps.QtCore.Qt.ItemDataRole.EditRole, minThresh)
                item2 = ps.QtWidgets.QTableWidgetItem()
                item2.setData(ps.QtCore.Qt.ItemDataRole.EditRole, maxThresh)
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

    def _getCut(self, cutIdx):
        if cutIdx < len(self.ranges):
            return self.ranges[cutIdx][0]
        return self.ranges[cutIdx - 1][1]

    def _setCut(self, cutIdx, value):
        if cutIdx - 1 >= 0:
            self.ranges[cutIdx - 1][1] = value
        if cutIdx < len(self.ranges):
            self.ranges[cutIdx][0] = value

    def onCellChanged(self, rowIdx, colIdx):
        er = ps.QtCore.Qt.ItemDataRole.EditRole
        changedItem = self.table.item(rowIdx, colIdx)
        data = changedItem.data(er)

        self.ranges[rowIdx][colIdx] = data

        if self.linkEndpoints:
            cutIdx = rowIdx if colIdx == 0 else rowIdx + 1
            self._setCut(cutIdx, data)

            i = cutIdx
            while i + 1 <= len(self.ranges) and self._getCut(i + 1) < data:
                self._setCut(i + 1, data)
                i += 1

            i = cutIdx
            while i - 1 >= 0 and self._getCut(i - 1) > data:
                self._setCut(i - 1, data)
                i -= 1

        self.redrawHistogram()

    def updateLinkEndpointsButtonAppearance(self):
        if self.linkEndpoints:
            self.linkEndpointsButton.setIcon(self._linkOnIcon)
            self.linkEndpointsButton.setToolTip(
                "Endpoints are linked: the end of a threshold range is kept equal to the start "
                "of the next one. Click to unlink."
            )
            self.linkEndpointsButton.setStyleSheet(
                "QToolButton { background: rgba(140, 215, 140, 220); border: 1px solid rgba(0, 0, 0, 80); border-radius: 3px; }"
            )
        else:
            self.linkEndpointsButton.setIcon(self._linkOffIcon)
            self.linkEndpointsButton.setToolTip(
                "Endpoints are unlinked: threshold ranges can be edited independently. Click to link."
            )
            self.linkEndpointsButton.setStyleSheet(
                "QToolButton { background: rgba(255, 255, 255, 200); border: 1px solid rgba(0, 0, 0, 80); border-radius: 3px; }"
            )

    def onLinkEndpointsChanged(self, checked):
        self.linkEndpoints = checked
        self.updateLinkEndpointsButtonAppearance()

        parameterSetNode = self.scriptedEffect.parameterSetNode()
        segmentationNode = parameterSetNode.GetSegmentationNode() if parameterSetNode else None
        if segmentationNode:
            segmentationNode.SetAttribute("MultipleThresholdLinkEndpoints", str(self.linkEndpoints))

        if self.linkEndpoints and len(self.ranges) > 1:
            # Re-link neighboring endpoints using the current segment's max as the shared boundary
            for i in range(len(self.ranges) - 1):
                self.ranges[i + 1][0] = self.ranges[i][1]
            self.redrawHistogram()

    def regionChanged(self, segment, lr, test):
        regCurrent = lr.getRegion()
        self.ranges[segment][0] = regCurrent[0]
        self.ranges[segment][1] = regCurrent[1]

        self.lrlist[segment].blockSignals(True)
        self.lrlist[segment].setRegion(regCurrent)
        self.lrlist[segment].blockSignals(False)

        if self.linkEndpoints:
            if segment > 0:
                self.ranges[segment - 1][1] = regCurrent[0]
                regMinus = self.lrlist[segment - 1].getRegion()
                self.lrlist[segment - 1].blockSignals(True)
                self.lrlist[segment - 1].setRegion((regMinus[0], regCurrent[0]))
                self.lrlist[segment - 1].blockSignals(False)
            if segment < len(self.colors) - 1:
                self.ranges[segment + 1][0] = regCurrent[1]
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

            for i in range(segmentation.GetNumberOfSegments()):
                try:
                    # Set current selected segment
                    segmentid = segmentation.GetNthSegmentID(i)
                    self.scriptedEffect.parameterSetNode().SetSelectedSegmentID(segmentid)
                    # Get master volume image data
                    import vtkSegmentationCorePython as vtkSegmentationCore

                    sourceImageData = self.scriptedEffect.sourceVolumeImageData()
                    # Get modifier labelmap
                    modifierLabelmap = self.scriptedEffect.defaultModifierLabelmap()
                    originalImageToWorldMatrix = vtk.vtkMatrix4x4()
                    modifierLabelmap.GetImageToWorldMatrix(originalImageToWorldMatrix)
                    # Get parameters
                    min = self.ranges[i][0]
                    max = self.ranges[i][1]
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

            segmentationNode.SetAttribute("MultipleThresholdTransitions", str(self.ranges))
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

        flatThresholds = [self.ranges[0][0]] + [r[1] for r in self.ranges]
        virtualSegWidget.setParams(self.getParentLazyNode(), flatThresholds, self.colors, segmentNames)

    def clearObservers(self):
        for obj, tag in self._observerHandlers:
            if isinstance(obj, str):  # is a node ID
                obj = tryGetNode(obj)
                if not obj:
                    continue

            obj.RemoveObserver(tag)
        self._observerHandlers.clear()

    def resetObservers(self):
        self.clearObservers()

        if self.segmentationNode is None:
            return

        self._observerHandlers.append(
            (
                self.segmentationNode.GetID(),
                self.segmentationNode.AddObserver(
                    self.segmentationNode.GetSegmentation().RepresentationModified, self.onSegmentationNodeModified
                ),
            )
        )
        self._observerHandlers.append(
            (
                self.segmentationNode.GetID(),
                self.segmentationNode.AddObserver(
                    self.segmentationNode.GetSegmentation().SegmentAdded, self.onSegmentationNodeModified
                ),
            )
        )
        self._observerHandlers.append(
            (
                self.segmentationNode.GetID(),
                self.segmentationNode.AddObserver(
                    self.segmentationNode.GetSegmentation().SegmentRemoved, self.onSegmentationNodeModified
                ),
            )
        )
        self._observerHandlers.append(
            (
                self.segmentationNode.GetID(),
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
        if self.svalues is None:
            logging.debug("Invalid samples values.")
            return

        if self.scriptedEffect.parameterSetNode() is None:
            slicer.util.errorDisplay("Failed to apply. The selected node is invalid.")
            return

        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if segmentationNode is None:
            logging.debug("Invalid segmentation node.")
            return

        from scipy.cluster.vq import kmeans2

        segmentation = segmentationNode.GetSegmentation()
        nsegs = segmentation.GetNumberOfSegments()
        if nsegs == 0:
            logging.debug("Invalid segmentation node. There are no segments.")
            return

        centroids, labelmap = kmeans2(self.svalues.astype(float), int(nsegs), iter=100, minit="points")
        boundaries = self.getTransitions(centroids)
        boundaries = np.append(self._min, boundaries)
        boundaries = np.append(boundaries, self._max)
        self.ranges = [[boundaries[i], boundaries[i + 1]] for i in range(len(boundaries) - 1)]

        self.redrawHistogram()

    def onSegmentationNodeModified(self, caller, event) -> None:
        self.segmentationChangedDebounceCaller()

    def onSegmentationChangedHandler(self, *args, **kwargs) -> None:
        self.clearPreviewDisplay()

        self.colors = self.getColors()

        if len(self.ranges) != len(self.colors):
            boundaries = np.linspace(self._min + (self._max - self._min) * 0.2, self._max, len(self.colors))
            boundaries = np.append(self._min, boundaries)
            self.ranges = [[boundaries[i], boundaries[i + 1]] for i in range(len(boundaries) - 1)]

        self.setupPreviewDisplay()
        self.applyKmeans()

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
            opacity = self.previewOpacitySlider.value
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
                min = self.ranges[i][0]
                max = self.ranges[i][1]
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
        self.stashedRanges = self.ranges
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
