import ctk
import os
import qt
import slicer
import pandas as pd
import numpy as np
import pyqtgraph as pg

from ltrace.slicer import ui
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.helpers import (
    updateSegmentationFromLabelMap,
    createTemporaryVolumeNode,
    setSourceVolume,
    create_color_table,
)
from ltrace.utils.ProgressBarProc import ProgressBarProc
from ltrace.algorithms.segment_cups import segment_cups
from ltrace.algorithms.detect_cups import full_detect, get_origin_offset
from pathlib import Path

from PySide2 import QtWidgets
from shiboken2 import wrapInstance
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget

try:
    from Test.MicroCTCupsAnalysisTest import MicroCTCupsAnalysisTest
except ImportError:
    MicroCTCupsAnalysisTest = None  # tests not deployed to final version or closed source

COLORS = [(1, 0, 0), (0, 0.5, 1), (1, 0, 1)]


def convertMinMax(node, oldMin, oldMax, newMin, newMax):
    def linearRemap(array, oldMin, oldMax, newMin, newMax):
        return newMin + (array - oldMin) * (newMax - newMin) / (oldMax - oldMin)

    with ProgressBarProc() as pb:
        pb.nextStep(0, "Converting to float32")
        array = slicer.util.arrayFromVolume(node).astype(np.float32)
        pb.nextStep(30, "Calculating remapped array")
        array = linearRemap(array, oldMin, oldMax, newMin, newMax)
        pb.nextStep(80, "Updating volume")
        slicer.util.updateVolumeFromArray(node, array)

        for ref in ["Aluminum", "Quartz", "Teflon"]:
            if node.GetAttribute(ref):
                value = float(node.GetAttribute(ref))
                node.SetAttribute(ref, str(linearRemap(value, oldMin, oldMax, newMin, newMax)))

        node.GetDisplayNode().AutoWindowLevelOff()
        node.GetDisplayNode().AutoWindowLevelOn()
        slicer.util.setSliceViewerLayers(background=node, fit=True)


def set_histogram_data(plot, histogram_node):
    histogram_array = slicer.util.arrayFromVolume(histogram_node).squeeze()
    plot.clear()
    for i, color in enumerate(COLORS):
        x = histogram_array[0]
        y = histogram_array[i + 1]
        y = y[:-1]
        color = tuple([int(c * 255) for c in color])
        plot.plot(x, y, stepMode=True, fillLevel=0, pen=pg.mkPen(color, width=2))
    plot.showGrid(x=True, y=True)


def readOnlySpinBox(value=0):
    spinBox = infiniteSpinBox(value)
    spinBox.setReadOnly(True)
    spinBox.setButtonSymbols(qt.QAbstractSpinBox.NoButtons)
    return spinBox


def infiniteSpinBox(value=0):
    spinBox = qt.QDoubleSpinBox()
    spinBox.setMinimum(-999999999)
    spinBox.setMaximum(999999999)
    spinBox.setValue(value)
    spinBox.setDecimals(5)

    return spinBox


def generate_histogram_widget():
    histogramWidget = GraphicsLayoutWidget()
    plot = histogramWidget.addPlot()

    container_widget = qt.QWidget()
    layout = qt.QVBoxLayout(container_widget)

    pyside_layout = wrapInstance(hash(layout), QtWidgets.QVBoxLayout)
    pyside_layout.addWidget(histogramWidget)

    return container_widget, plot


def create_histogram_node(scalar_node, labelmap_node):
    scalar_array = slicer.util.arrayFromVolume(scalar_node)
    labelmap_array = slicer.util.arrayFromVolume(labelmap_node)

    samples = []
    for i in range(3):
        samples.append(scalar_array[labelmap_array == (i + 1)][::1000])

    range_ = min([np.min(s) for s in samples]), max([np.max(s) for s in samples])
    bins = 300

    histogram = []

    y, x = np.histogram(samples[0], bins=bins, range=range_)
    y = np.append(y, 0)
    histogram.append(x)
    histogram.append(y)

    y, x = np.histogram(samples[1], bins=bins, range=range_)
    y = np.append(y, 0)
    histogram.append(y)

    y, x = np.histogram(samples[2], bins=bins, range=range_)
    y = np.append(y, 0)
    histogram.append(y)

    histogram = np.array(histogram)

    histogram_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Histogram")
    histogram_node.HideFromEditorsOn()
    slicer.util.updateVolumeFromArray(histogram_node, histogram)
    return histogram_node


class MicroCTCupsAnalysis(LTracePlugin):
    SETTING_KEY = "MicroCTCupsAnalysis"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Micro CT Cups Analysis (advanced)"
        self.parent.categories = ["LTrace Tools"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = MicroCTCupsAnalysis.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MicroCTCupsAnalysisWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        scaleLayout = qt.QFormLayout()
        self.layout.addLayout(scaleLayout)

        self.volumeInput = ui.hierarchyVolumeInput(
            onChange=self.onVolumeChanged,
            hasNone=True,
            tooltip="Change scale of this volume",
        )

        minMaxGroup = qt.QGroupBox("Linear remap")
        minMaxGroup.setToolTip("Linearly transform scalars so values on the left become values on the right")
        minMaxLayout = qt.QFormLayout(minMaxGroup)

        arrow = "\u2192"
        self.currentMin = infiniteSpinBox()
        self.newMin = infiniteSpinBox()
        self.newMin.valueChanged.connect(self.onMinMaxChanged)

        minLayout = qt.QHBoxLayout()
        minLayout.addWidget(self.currentMin, 1)
        minLayout.addWidget(qt.QLabel(arrow))
        minLayout.addWidget(self.newMin, 1)
        minLayout.addStretch(2)

        cupsGroup = qt.QGroupBox("Detect")
        cupsLayout = qt.QFormLayout(cupsGroup)

        self.cupsButton = qt.QPushButton("Isolate cylinder and detect reference values")
        self.cupsButton.setToolTip(
            "Isolate rock cylinder in a new volume and detect the median value of each cup (teflon, quartz, aluminum)"
        )
        self.cupsButton.setEnabled(False)
        self.cupsButton.clicked.connect(self.onCupsButtonClicked)
        cupsLayout.addRow(self.cupsButton)

        self.cupsResultGroup = qt.QGroupBox("Results")
        self.cupsResultGroup.visible = False
        cupsLayout.addRow(self.cupsResultGroup)
        cupsResultLayout = qt.QFormLayout(self.cupsResultGroup)

        self.aluminumResult = readOnlySpinBox()
        self.aluminumResult.setToolTip("Detected median value of aluminum cup")

        self.quartzResult = readOnlySpinBox()
        self.quartzResult.setToolTip("Detected median value of quartz cup")

        self.teflonResult = readOnlySpinBox()
        self.teflonResult.setToolTip("Detected median value of teflon cup")

        self.histogramContainer, self.histogramPlot = generate_histogram_widget()
        self.exportHistogramButton = qt.QPushButton("Export histogram as CSV")
        self.exportHistogramButton.clicked.connect(self.onExportHistogramButtonClicked)

        cupsResultLayout.addRow("Teflon:", self.teflonResult)
        cupsResultLayout.addRow("Quartz:", self.quartzResult)
        cupsResultLayout.addRow("Aluminum:", self.aluminumResult)
        cupsResultLayout.addRow(self.histogramContainer)
        cupsResultLayout.addRow(self.exportHistogramButton)

        self.cupsStatus = qt.QLabel("Idle")
        cupsLayout.addRow("Status:", self.cupsStatus)

        minMaxLayout.addRow("Low:", minLayout)

        self.currentMax = infiniteSpinBox()
        self.newMax = infiniteSpinBox(1000)
        self.newMax.valueChanged.connect(self.onMinMaxChanged)

        maxLayout = qt.QHBoxLayout()
        maxLayout.addWidget(self.currentMax, 1)
        maxLayout.addWidget(qt.QLabel(arrow))
        maxLayout.addWidget(self.newMax, 1)
        maxLayout.addStretch(2)

        minMaxLayout.addRow("High:", maxLayout)

        self.applyMinMaxButton = qt.QPushButton("Remap")
        minMaxLayout.addRow(self.applyMinMaxButton)

        self.applyMinMaxButton.clicked.connect(self.onApplyMinMaxButtonClicked)

        scaleLayout.addRow("Volume:", self.volumeInput)
        scaleLayout.addRow(" ", None)
        scaleLayout.addRow(cupsGroup)
        scaleLayout.addRow(" ", None)
        scaleLayout.addRow(minMaxGroup)
        self.onVolumeChanged(None)

        self.layout.addStretch(1)

    def onCupsButtonClicked(self):
        volume = self.volumeInput.currentNode()
        array = slicer.util.arrayFromVolume(volume)

        with ProgressBarProc() as pb:
            cups_callback = lambda progress, message: pb.nextStep(progress * 0.2, message)
            rock, refs, cylinder = full_detect(array, callback=cups_callback)
            offset = get_origin_offset(cylinder)

            if refs is not None:
                volume.SetAttribute("Aluminum", str(refs[0]))
                volume.SetAttribute("Quartz", str(refs[1]))
                volume.SetAttribute("Teflon", str(refs[2]))

                segment_callback = lambda progress, message: pb.nextStep(20 + progress * 0.7, message)
                labelmap_array = segment_cups(
                    array, circle=(x, y, r), initial_centroids=refs[::-1], callback=segment_callback
                )

                pb.nextStep(90, "Creating labelmap")

                labelmap = createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, volume.GetName() + " - Labelmap")
                slicer.util.updateVolumeFromArray(labelmap, labelmap_array)
                labelmap.CopyOrientation(volume)

                color_table = create_color_table(
                    "Cups", [(0, 0, 0)] + COLORS, ["Background", "Teflon", "Quartz", "Aluminum"]
                )
                labelmap.GetDisplayNode().SetAndObserveColorNodeID(color_table.GetID())

                segmentation = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLSegmentationNode", volume.GetName() + " - Cups"
                )
                segmentation.CreateDefaultDisplayNodes()
                setSourceVolume(segmentation, volume)
                updateSegmentationFromLabelMap(segmentation, labelmap)

                histogram_node = create_histogram_node(volume, labelmap)
                volume.SetAttribute("Histogram", histogram_node.GetID())

            if rock is not None:
                pb.nextStep(90, "Creating rock cylinder volume")
                rockNode = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLScalarVolumeNode", volume.GetName() + " - Cylinder"
                )
                rockNode.CreateDefaultDisplayNodes()
                slicer.util.updateVolumeFromArray(rockNode, rock)

                rockNode.CopyOrientation(volume)
                origin = rockNode.GetOrigin()
                spacing = rockNode.GetSpacing()
                origin = (a + (b * s) for a, b, s in zip(origin, offset, spacing))
                rockNode.SetOrigin(*origin)
                if refs is not None:
                    rockNode.SetAttribute("Aluminum", str(refs[0]))
                    rockNode.SetAttribute("Quartz", str(refs[1]))
                    rockNode.SetAttribute("Teflon", str(refs[2]))
                    rockNode.SetAttribute("Histogram", histogram_node.GetID())

                slicer.util.setSliceViewerLayers(background=volume, fit=True)
                self.volumeInput.setCurrentNode(rockNode)

        if rock is None:
            self.cupsStatus.setText("Rock cylinder could not be detected")
        elif refs is None:
            self.cupsStatus.setText("Rock cylinder isolated successfully, but reference cups could not be detected")
        else:
            self.cupsStatus.setText("Rock cylinder isolated and reference cups detected successfully")

    def onVolumeChanged(self, _):
        volume = self.volumeInput.currentNode()
        if volume:
            scalarRange = volume.GetImageData().GetScalarRange()
            self.currentMin.setValue(scalarRange[0])
            self.currentMax.setValue(scalarRange[1])

            self.newMin.setValue(0)
            self.newMax.setValue(1000)

            visible = False
            if volume.GetAttribute("Aluminum"):
                self.aluminumResult.setValue(float(volume.GetAttribute("Aluminum")))
                visible = True
            if volume.GetAttribute("Quartz"):
                self.quartzResult.setValue(float(volume.GetAttribute("Quartz")))
                visible = True
            if volume.GetAttribute("Teflon"):
                self.teflonResult.setValue(float(volume.GetAttribute("Teflon")))
                visible = True
            self.cupsResultGroup.visible = visible

            if volume.GetAttribute("Histogram"):
                histogram_node_id = volume.GetAttribute("Histogram")
                histogram_node = slicer.mrmlScene.GetNodeByID(histogram_node_id)
                if histogram_node:
                    set_histogram_data(self.histogramPlot, histogram_node)
                    self.histogramContainer.visible = True
                    self.exportHistogramButton.visible = True
                else:
                    self.histogramContainer.visible = False
                    self.exportHistogramButton.visible = False

        self.cupsButton.setEnabled(volume is not None)
        self.onMinMaxChanged(None)

    def onExportHistogramButtonClicked(self):
        volume = self.volumeInput.currentNode()
        histogram_node_id = volume.GetAttribute("Histogram")
        histogram_node = slicer.mrmlScene.GetNodeByID(histogram_node_id)
        histogram_array = slicer.util.arrayFromVolume(histogram_node).squeeze()
        histogram_array = histogram_array[:, :-1].transpose()
        df = pd.DataFrame(histogram_array, columns=["Lower bin edge", "Teflon", "Quartz", "Aluminum"])
        key = "MicroCTLoader/CupsHistogramDirectory"
        directory = slicer.util.settingsValue(key, slicer.mrmlScene.GetRootDirectory())
        path = qt.QFileDialog.getSaveFileName(None, "Save histogram as CSV", directory, "CSV files (*.csv)")
        if not path:
            return
        df.to_csv(path, index=False)
        slicer.app.userSettings().setValue("CupsHistogramDirectory", str(Path(path).parent.absolute()))

    def onMinMaxChanged(self, _):
        volume = self.volumeInput.currentNode()
        oldMin = self.currentMin.value
        oldMax = self.currentMax.value
        newMin = self.newMin.value
        newMax = self.newMax.value
        valid = (oldMin != newMin or oldMax != newMax) and newMax > newMin and volume is not None
        self.applyMinMaxButton.enabled = valid

    def onApplyMinMaxButtonClicked(self):
        volume = self.volumeInput.currentNode()
        oldMin = self.currentMin.value
        oldMax = self.currentMax.value
        newMin = self.newMin.value
        newMax = self.newMax.value
        convertMinMax(volume, oldMin, oldMax, newMin, newMax)
        self.onVolumeChanged(None)
