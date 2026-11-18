import os
from pathlib import Path

import numpy as np
import pyqtgraph as pg
import qt
import slicer
from pyqtgraph import QtCore

from commons.lmath.image_quality_api import CnrOptions, CuppingOptions, MtfOptions, QualityOptions
from commons.slicer import ui
from commons.slicer.data_utils import tableNodeToDataFrame
from commons.slicer.helpers import getPythonQtWidget
from commons.slicer.image_quality import appendResultRow, clearResultsTable, measureNodes, resultsTableNode
from commons.slicer.node_attributes import NodeEnvironment
from commons.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget
from commons.slicer.widget.help_button import HelpButton
from commons.slicer_utils import LTracePlugin, LTracePluginLogic, LTracePluginWidget

try:
    from Test.ImageQualityMetricsTest import ImageQualityMetricsTest
except ImportError:
    ImageQualityMetricsTest = None  # tests not deployed to final version or closed source

# Markdown shown by the help button next to each metric
ALL_SEGMENTS = "__all__"  # data of the "All segments" item of the cupping selector

PLOT_CURVE_COLOR = "#4da3ff"
PLOT_F50_COLOR = "#ffb347"
PLOT_F10_COLOR = "#ff6b6b"

HELP_TEXTS = {
    "SNR": """**SNR: signal-to-noise ratio**

How noisy a region is: its mean gray level divided by its standard deviation.

- **Higher is better.** The image is cleaner and small contrasts are easier to see.
- Pick **homogeneous** regions (for example the water inside the tube), away from edges and artifacts. Anything that varies and is not noise (a gradient, a rim, a crack) is counted as noise and lowers the SNR.
- One value is reported for each checked segment, in the columns `SNR [segment]`.
- More kV, current or exposure, or more projections, normally raise the SNR. A concentrated contrast agent such as NaI absorbs more of the beam and lowers the SNR of that region.
- It is a relative number: compare scans of the same material.""",
    "CNR": """**CNR: contrast-to-noise ratio**

How well two phases can be told apart: the difference between their mean gray levels divided by the noise of both, |mean A - mean B| / sqrt(std A^2 + std B^2).

- **Higher is better.** As a rule of thumb, below about 3 the two phases overlap too much to be separated reliably by a threshold.
- Phase A and Phase B do **not** need to touch. Pick homogeneous areas, away from interfaces.
- A lower kV raises the contrast but also the noise. A filter lowers the absolute contrast, yet it can raise the CNR by removing beam hardening artifacts.
- Reported in the columns `CNR` and `CNR phases`.""",
    "Cupping": """**Cupping: beam hardening**

A homogeneous material should have the same gray level everywhere. The low-energy photons are absorbed first, so the beam gets harder as it crosses the sample and the center comes out darker than its wall.

**Cupping (%) = (edge - center) / edge x 100**, where *center* is the mean up to 20% of the radius and *edge* the mean between 80% and 95% (both configurable; the outer 5% is skipped because of the blur at the interface).

- **Near 0 is good.** Positive: center darker than the wall, the typical beam hardening. Negative: center brighter, which can come from an over-corrected beam hardening.
- **All segments** (default) takes the whole sample as one region, which suits a mineralogical segmentation. Pick a single segment to measure just that material, or the tube of a phantom. The region should be the **whole cross-section**; the axis is assumed parallel to Z and to go through its center.
- If the segmentation has a pore or air segment, pick the segments of the sample one by one instead of "All segments", because the pore would pull the radial average.
- A metal filter (Al, Cu) or a higher kV reduces cupping. A high atomic number agent such as NaI increases it.
- The *Radial profile* plot shows the whole curve.""",
    "MTF": """**MTF: spatial resolution**

The voxel size is not the real resolution: the focal spot, the detector, the geometry and the reconstruction blur the image. The MTF says how much of the contrast of a detail survives as the detail gets finer.

It is measured across a sharp **edge**, such as the wall of the tube: the gray level goes from one material to the other (edge profile), its derivative is the line spread function (LSF) and the Fourier transform of the LSF is the MTF curve, which starts at 1 and falls.

- **Resolvable at 50% / 10% (um):** the MTF tells how much of the contrast of a detail is kept as the detail gets smaller. These two values are the sizes of the detail that keeps **half** (50%) and **a tenth** (10%) of its original contrast. **Smaller is sharper.**
    - **50%:** details of this size are still clearly visible. Use it to compare scanners or settings, because it sits in the high-contrast part of the curve and is little affected by noise.
    - **10%:** the practical limit. Details smaller than this are lost in the noise, and those between the two values appear with weak contrast. The curve is lower here, so the value is more sensitive to noise.
    - Example with 10 um voxels: 50% = 30 um and 10% = 18 um means that 30 um details are seen with half of their contrast, those between 18 and 30 um fade, and anything under 18 um is not resolved.
    - The MTF plot shows the contrast kept for each frequency as the size of the detail it resolves (size = 500 / f, in um); the plot marks these two sizes.
- **LSF FWHM (um):** width of the blurred edge at half height. Smaller is sharper.

Side A and Side B must **touch** (inside and outside the tube, for example). The edge should be roughly perpendicular to the slices. **Edge band** is the half-width used around the edge: use at least 4 times the blur you expect (the default of 10 voxels suits edges blurred over a few voxels).""",
}


class DetailSizeAxis(pg.AxisItem):
    """Frequency axis (lp/mm) of the MTF plot labeled with the size in um of the detail that each frequency resolves
    (1 / 2f). The data stay in lp/mm, only the tick labels change."""

    def tickStrings(self, values, scale, spacing):
        return ["inf" if value <= 0 else f"{500.0 / value:.3g}" for value in values]


class ImageQualityMetrics(LTracePlugin):
    SETTING_KEY = "ImageQualityMetrics"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Image Metrics"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.setHelpUrl("Volumes/ImageQualityMetrics/ImageQualityMetrics.html", NodeEnvironment.MICRO_CT)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ImageQualityMetricsWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = ImageQualityMetricsLogic()

        self.layout.addWidget(self.__buildInputSection())
        self.layout.addWidget(self.__buildMetricsSection())

        self.__applyButton = ui.ApplyButton(
            onClick=self.__onApplyButtonClicked, tooltip="Measure and add a row to the results table", enabled=True
        )
        self.__applyButton.objectName = "Apply Button"
        self.layout.addWidget(self.__applyButton)

        self.layout.addWidget(self.__buildResultsSection())
        self.layout.addStretch(1)

        self.__onSegmentationChanged()

    def __buildInputSection(self):
        section = ui.collapsibleButton("Input")

        self.__volumeSelector = slicer.qMRMLNodeComboBox()
        self.__volumeSelector.objectName = "Volume Selector"
        self.__volumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.__volumeSelector.addEnabled = False
        self.__volumeSelector.removeEnabled = False
        self.__volumeSelector.noneEnabled = True
        self.__volumeSelector.setMRMLScene(slicer.mrmlScene)
        self.__volumeSelector.setToolTip("Reconstructed micro-CT volume")

        self.__segmentationSelector = slicer.qMRMLNodeComboBox()
        self.__segmentationSelector.objectName = "Segmentation Selector"
        self.__segmentationSelector.nodeTypes = ["vtkMRMLSegmentationNode"]
        self.__segmentationSelector.addEnabled = False
        self.__segmentationSelector.removeEnabled = False
        self.__segmentationSelector.noneEnabled = True
        self.__segmentationSelector.setMRMLScene(slicer.mrmlScene)
        self.__segmentationSelector.setToolTip("One segmentation with a segment for each material of the scan")
        self.__segmentationSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.__onSegmentationChanged)

        layout = qt.QFormLayout(section)
        layout.addRow("Volume:", self.__volumeSelector)
        layout.addRow("Segmentation:", self.__segmentationSelector)
        return section

    def __metricGroup(self, title, objectName, tooltip):
        group = qt.QGroupBox(title)
        group.objectName = objectName
        group.setCheckable(True)
        group.setToolTip(tooltip)
        return group, qt.QFormLayout(group)

    def __addMetricGroup(self, layout, group, helpKey):
        """Put `group` and its help button side by side. The button stays outside of the group on purpose: an
        unchecked, checkable group box disables everything inside it and the help must work in that state too."""
        button = HelpButton(HELP_TEXTS[helpKey])
        button.objectName = f"{helpKey} Help Button"
        button.setToolTip(f"What the {helpKey} means")
        row = qt.QHBoxLayout()
        row.addWidget(group, 1)
        row.addWidget(button, 0, qt.Qt.AlignTop)
        layout.addLayout(row)

    @staticmethod
    def __segmentList(objectName, tooltip):
        segmentList = qt.QListWidget()
        segmentList.objectName = objectName
        segmentList.setMaximumHeight(90)
        segmentList.setToolTip(tooltip)
        return segmentList

    def __segmentCombo(self, objectName, tooltip):
        combo = qt.QComboBox()
        combo.objectName = objectName
        combo.setToolTip(tooltip)
        return combo

    def __buildMetricsSection(self):
        section = ui.collapsibleButton("Metrics")
        layout = qt.QVBoxLayout(section)

        group, form = self.__metricGroup(
            "SNR: noise of each region", "SNR Group", "Mean / standard deviation. Pick homogeneous regions."
        )
        self.__segmentIds = []
        self.__snrList = self.__segmentList("SNR Segments List", "One SNR value is reported for each checked segment")
        form.addRow(self.__snrList)
        self.__snrGroup = group
        self.__addMetricGroup(layout, group, "SNR")

        group, form = self.__metricGroup(
            "CNR: contrast between two phases",
            "CNR Group",
            "|mean A - mean B| / sqrt(std A^2 + std B^2). The phases do not need to touch.",
        )
        self.__cnrA = self.__segmentCombo("CNR Segment A Combo", "First phase")
        self.__cnrB = self.__segmentCombo("CNR Segment B Combo", "Second phase")
        form.addRow("Phase A:", self.__cnrA)
        form.addRow("Phase B:", self.__cnrB)
        self.__cnrGroup = group
        self.__addMetricGroup(layout, group, "CNR")

        group, form = self.__metricGroup(
            "Cupping: beam hardening",
            "Cupping Group",
            "Compares the gray level at the center of the sample with the one near its wall.",
        )
        self.__cuppingSegment = self.__segmentCombo(
            "Cupping Segment Combo", "All segments together (the whole sample) or a single segment"
        )
        self.__centerSpin = self.__percentSpin(20, 1, 50)
        self.__edgeStartSpin = self.__percentSpin(80, 50, 99)
        self.__edgeEndSpin = self.__percentSpin(95, 51, 100)
        form.addRow("Region:", self.__cuppingSegment)
        form.addRow("Center (up to):", self.__centerSpin)
        form.addRow("Edge (from):", self.__edgeStartSpin)
        form.addRow("Edge (to):", self.__edgeEndSpin)
        self.__cuppingGroup = group
        self.__addMetricGroup(layout, group, "Cupping")

        group, form = self.__metricGroup(
            "MTF: spatial resolution from an edge",
            "MTF Group",
            "Sharpness of the interface between two touching segments, e.g. the tube wall. Reports the size of the\n"
            "smallest detail that keeps 50% and 10% of its contrast (smaller is sharper).",
        )
        self.__mtfA = self.__segmentCombo("MTF Segment A Combo", "One side of the edge (e.g. inside the tube)")
        self.__mtfB = self.__segmentCombo("MTF Segment B Combo", "The other side, touching side A (e.g. air outside)")
        self.__bandSpin = qt.QDoubleSpinBox()
        self.__bandSpin.objectName = "Edge Band Spin"
        self.__bandSpin.setRange(2, 100)
        self.__bandSpin.setValue(10)
        self.__bandSpin.setSuffix(" voxels")
        self.__bandSpin.setToolTip("Half-width of the band around the interface used to build the edge profile")
        form.addRow("Side A:", self.__mtfA)
        form.addRow("Side B:", self.__mtfB)
        form.addRow("Edge band:", self.__bandSpin)
        self.__mtfGroup = group
        self.__addMetricGroup(layout, group, "MTF")

        return section

    @staticmethod
    def __percentSpin(value, low, high):
        spin = qt.QSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        spin.setSuffix(" % of the radius")
        return spin

    def __buildResultsSection(self):
        section = ui.collapsibleButton("Results")

        self.__graphicsWidget = GraphicsLayoutWidget()
        self.__graphicsWidget.setFixedHeight(220)
        self.__radialPlot = self.__graphicsWidget.addPlot(row=0, col=0, title="Radial profile")
        self.__radialPlot.setLabel("bottom", "radius (mm)")
        self.__radialPlot.showGrid(x=True, y=True, alpha=0.25)
        self.__radialPlot.setLabel("left", "gray level")
        self.__mtfPlot = self.__graphicsWidget.addPlot(
            row=0, col=1, title="MTF", axisItems={"bottom": DetailSizeAxis("bottom")}
        )
        self.__mtfPlot.setLabel("bottom", "detail size (um)")
        self.__mtfPlot.setLabel("left", "MTF")
        self.__mtfPlot.showGrid(x=True, y=True, alpha=0.25)
        figureQtWidget = getPythonQtWidget(self.__graphicsWidget)

        self.__tableView = slicer.qMRMLTableView()
        self.__tableView.objectName = "Results Table"
        self.__tableView.setMinimumHeight(140)
        self.__tableView.setMRMLScene(slicer.mrmlScene)

        clearButton = ui.ButtonWidget(text="Clear table", onClick=self.__onClearTable)
        clearButton.objectName = "Clear Table Button"
        exportButton = ui.ButtonWidget(text="Export CSV", onClick=self.__onExportCsv)
        exportButton.objectName = "Export CSV Button"

        layout = qt.QVBoxLayout(section)
        if figureQtWidget is not None:
            layout.addWidget(figureQtWidget)
        layout.addWidget(self.__tableView)
        layout.addWidget(ui.Row([clearButton, exportButton]))
        return section

    def __onSegmentationChanged(self, *args):
        """Refill every segment selector. SNR starts with all segments, the pairs with the first two."""
        segments = []
        node = self.__segmentationSelector.currentNode()
        if node is not None:
            segmentation = node.GetSegmentation()
            for i in range(segmentation.GetNumberOfSegments()):
                segmentId = segmentation.GetNthSegmentID(i)
                segments.append((segmentation.GetSegment(segmentId).GetName(), segmentId))

        self.__snrList.clear()
        for name, segmentId in segments:
            item = qt.QListWidgetItem(name)
            item.setFlags(item.flags() | qt.Qt.ItemIsUserCheckable)
            item.setCheckState(qt.Qt.Checked)
            item.setData(qt.Qt.UserRole, segmentId)
            self.__snrList.addItem(item)

        self.__segmentIds = [segmentId for _, segmentId in segments]
        for combo in (self.__cnrA, self.__cnrB, self.__cuppingSegment, self.__mtfA, self.__mtfB):
            combo.clear()
            if combo is self.__cuppingSegment and segments:
                combo.addItem("All segments", ALL_SEGMENTS)
            for name, segmentId in segments:
                combo.addItem(name, segmentId)
        if len(segments) > 1:
            self.__cnrB.setCurrentIndex(1)
            self.__mtfB.setCurrentIndex(1)

        self.__snrGroup.setChecked(bool(segments))
        self.__cnrGroup.setChecked(len(segments) > 1)
        self.__cuppingGroup.setChecked(False)
        self.__mtfGroup.setChecked(False)

    @staticmethod
    def __selected(combo):
        return combo.itemData(combo.currentIndex) or None

    @staticmethod
    def __checkedSegments(segmentList):
        """`(checked ids, all checked)` of a list of checkable segments."""
        ids = []
        for row in range(segmentList.count):
            item = segmentList.item(row)
            if item.checkState() == qt.Qt.Checked:
                ids.append(item.data(qt.Qt.UserRole))
        return ids, len(ids) == segmentList.count

    def __collectOptions(self):
        """Read the metric groups. Returns `(QualityOptions, error message)`."""
        options = QualityOptions()
        if self.__snrGroup.isChecked():
            options.snr, _ = self.__checkedSegments(self.__snrList)
            if not options.snr:
                return None, "Check at least one segment for the SNR."
        if self.__cnrGroup.isChecked():
            a, b = self.__selected(self.__cnrA), self.__selected(self.__cnrB)
            if a is None or b is None or a == b:
                return None, "The CNR needs two different segments."
            options.cnr = CnrOptions(a, b)
        if self.__cuppingGroup.isChecked():
            segment = self.__selected(self.__cuppingSegment)
            if segment is None:
                return None, "Select the region for the cupping."
            everything = segment == ALL_SEGMENTS
            options.cupping = CuppingOptions(
                self.__segmentIds if everything else [segment],
                name="All segments" if everything else None,
                center_fraction=self.__centerSpin.value / 100.0,
                edge_fraction=(self.__edgeStartSpin.value / 100.0, self.__edgeEndSpin.value / 100.0),
            )
        if self.__mtfGroup.isChecked():
            a, b = self.__selected(self.__mtfA), self.__selected(self.__mtfB)
            if a is None or b is None or a == b:
                return None, "The MTF needs two different segments."
            options.mtf = MtfOptions(a, b, band_voxels=self.__bandSpin.value)
        if not (options.snr or options.cnr or options.cupping or options.mtf):
            return None, "Select at least one metric."
        return options, None

    def __onApplyButtonClicked(self, state):
        volumeNode = self.__volumeSelector.currentNode()
        segmentationNode = self.__segmentationSelector.currentNode()
        if volumeNode is None:
            slicer.util.errorDisplay("Please select an input volume.")
            return
        if segmentationNode is None:
            slicer.util.errorDisplay("Please select a segmentation.")
            return
        options, error = self.__collectOptions()
        if error:
            slicer.util.errorDisplay(error)
            return

        slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            result = self.logic.measure(volumeNode, segmentationNode, options)
        except ValueError as error:
            slicer.util.errorDisplay(str(error))
            return
        finally:
            slicer.app.restoreOverrideCursor()

        tableNode = self.logic.appendRow(result.metrics)
        self.__tableView.setMRMLTableNode(tableNode)
        self.__plot(result.curves)
        if result.warnings:
            slicer.util.warningDisplay("Some metrics could not be computed:\n\n" + "\n".join(result.warnings))

    def __plot(self, curves):
        self.__radialPlot.clear()
        self.__mtfPlot.clear()
        if "radial" in curves:
            self.__radialPlot.plot(
                curves["radial"]["radius"], curves["radial"]["profile"], pen=pg.mkPen(PLOT_CURVE_COLOR, width=2)
            )
        if "mtf" in curves:
            mtf = curves["mtf"]
            self.__mtfPlot.plot(mtf["frequencies"], mtf["mtf"], pen=pg.mkPen(PLOT_CURVE_COLOR, width=2))
            for level, key, color, labelPosition in (
                (0.5, "f50", PLOT_F50_COLOR, 0.9),
                (0.1, "f10", PLOT_F10_COLOR, 0.6),
            ):
                frequency = mtf.get(key)
                if frequency is None or not np.isfinite(frequency):
                    continue
                self.__mtfPlot.addLine(
                    x=frequency,
                    pen=pg.mkPen(color, width=1.5, style=QtCore.Qt.PenStyle.DashLine),
                    label=f"{level:.0%}: {500.0 / frequency:.1f} um",
                    labelOpts={"position": labelPosition, "color": color, "movable": False},
                )
                self.__mtfPlot.plot([frequency], [level], pen=None, symbol="o", symbolSize=9, symbolBrush=color)
            self.__mtfPlot.setXRange(0, mtf["xmax"])
            self.__mtfPlot.setYRange(0, 1.05)

    def __onClearTable(self, *args):
        self.logic.clearTable()

    def __onExportCsv(self, *args):
        tableNode = self.logic.tableNode()
        if tableNode is None or tableNode.GetNumberOfRows() == 0:
            slicer.util.errorDisplay("The results table is empty.")
            return
        path = qt.QFileDialog.getSaveFileName(
            slicer.util.mainWindow(), "Export results", "image_quality_metrics.csv", "CSV (*.csv)"
        )
        if path:
            tableNodeToDataFrame(tableNode).to_csv(path, index=False)


class ImageQualityMetricsLogic(LTracePluginLogic):
    """Thin wrapper over `commons.slicer.image_quality`, which other modules can call directly."""

    def __init__(self):
        LTracePluginLogic.__init__(self)

    def measure(self, volumeNode, segmentationNode, options: QualityOptions, metadata=None):
        """Return a `QualityResult` (metrics row, plot curves, warnings). See `measure_quality`."""
        return measureNodes(volumeNode, segmentationNode, options, metadata)

    def tableNode(self):
        return resultsTableNode()

    def appendRow(self, row):
        return appendResultRow(row)

    def clearTable(self):
        clearResultsTable()
