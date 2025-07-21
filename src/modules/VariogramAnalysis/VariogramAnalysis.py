import cv2
import os
from pathlib import Path

import vtk, qt, ctk, slicer

import numpy as np
from numba import jit
import pyqtgraph as pg
import pyqtgraph.exporters
import PySide2 as pyside
import ScreenCapture
import shiboken2
import warnings

from fft.crop import getInscribedCuboidLimits
from ltrace.conventions.petrobras_raw_file_name import PetrobrasRawFileName
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget
from ltrace.slicer.widgets import InputState, SingleShotInputWidget
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.algorithms.variogram import GeneralizedVariogram
from ltrace.algorithms.Variogram_FFT.variogram import VariogramFFT
from ltrace.slicer.helpers import createTemporaryVolumeNode, createMaskWithROI, highlight_error, highlight_warning
from ltrace.transforms import volume_ijk_to_ras
from ltrace.units import global_unit_registry as ureg, SLICER_LENGTH_UNIT
from ltrace.utils.ProgressBarProc import ProgressBarProc
from ltrace.utils.report_builder import ReportBuilder

# -*- extra imports -*-
from ltrace.wrappers import timeit


def useProgressBar(func):
    def wrapper(*args, **kwargs):
        self = args[0]
        with ProgressBarProc() as bar:
            self.progressBarProc = bar
            try:
                result = func(*args, **kwargs)
            finally:
                self.progressBarProc = None
        return result

    return wrapper


class VariogramAnalysis(LTracePlugin):
    SETTING_KEY = "VariogramAnalysis"
    SUBVOLUME_ANALYSIS_TYPE = "edge"

    def __init__(self, parent):
        super().__init__(parent)
        self.parent.title = "Variogram Analysis"
        self.parent.categories = ["Segmentation", "MicroCT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = """
    Performs manual separation and agglutination of labeled objects
"""
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = """
    Developed by LTrace Geophysics Solutions
"""


class VariogramAnalysisWidget(LTracePluginWidget):
    EXPORT_DIRECTORY = "exportDirectory"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.inputVolumeNode = None
        self.inputSegmentationNode = None
        self.inputSegmentIds = ()
        self.inputSOINode = None
        self.volumeAsDataWidgets = ()
        self.segmentAsDataWidgets = ()

        self.progressBarProc = None
        self.has_processed_variogram = False
        self.has_processed_rev = False

    def setup(self):

        super().setup()
        self.logic = VariogramAnalysisLogic()

        # helpCollapsibleButton = ctk.ctkCollapsibleButton()
        # helpCollapsibleButton.setText("Help")
        # helpCollapsibleButton.collapsed = True
        # helpBox = qt.QVBoxLayout(helpCollapsibleButton)
        # helpText = '\n'.join([
        #    'Help text here',
        # ])
        # helpBox.addWidget(qt.QLabel(helpText))
        # self.layout.addWidget(helpCollapsibleButton)

        #
        # SingleShotInputWidget
        #

        inputParametersGroup = ctk.ctkCollapsibleButton()
        inputParametersGroup.text = "Inputs"
        inputParametersFrame = qt.QFrame()
        inputParametersForm = qt.QFormLayout(inputParametersFrame)

        self.inputSelection = SingleShotInputWidget(
            allowedInputNodes=[
                "vtkMRMLScalarVolumeNode",
                "vtkMRMLLabelMapVolumeNode",
                "vtkMRMLSegmentationNode",
            ],
            rowTitles={
                "main": "Input node",
                "soi": "Region (SOI)",
                "reference": "Reference",
            },
        )
        self.inputSelection.mainInput.resetStyleOnValidNode()
        self.inputSelection.referenceInput.resetStyleOnValidNode()
        self.inputSelection.soiInput.resetStyleOnValidNode()
        self.inputSelection.onReferenceSelectedSignal.connect(self._on_reference_node_selected)
        self.inputSelection.onSoiSelectedSignal.connect(self._on_soi_node_selected)
        self.layout.addWidget(self.inputSelection)

        self.warningLabel = qt.QLabel(
            "When the Region (SOI) is not selected, the variogram results could exceed the sample boundaries."
        )
        self.warningLabel.setStyleSheet("QLabel { color : yellow; }")
        self.warningLabel.hide()
        self.layout.addWidget(self.warningLabel)

        inputParametersForm.addRow(self.inputSelection)
        inputParametersForm.addRow(self.warningLabel)
        inputParametersGroup.setLayout(inputParametersForm)

        self.layout.addWidget(inputParametersGroup)

        #
        # Analysis parameters
        #

        analysisParametersGroup = ctk.ctkCollapsibleButton()
        analysisParametersGroup.text = "Parameters"
        analysisParametersFrame = qt.QFrame()
        analysisParametersBox = qt.QVBoxLayout(analysisParametersFrame)

        #
        # Variogram parameters
        #

        parametersFrame = qt.QFrame()
        parametersForm = qt.QFormLayout(parametersFrame)

        self.variogramParametersTitle = self._create_title_widget("Variogram analysis")

        self.useNuggetCheckBox = qt.QCheckBox("Use nugget")

        self.variogramApplyButton = qt.QPushButton("Produce variogram report")
        self.variogramApplyButton.clicked.connect(lambda: self.on_variogram_apply())

        self.variogramResultCollapsible = ctk.ctkCollapsibleButton()
        self.variogramResultCollapsible.flat = True
        self.variogramResultCollapsible.collapsed = True
        self.variogramResultCollapsible.text = "Result"

        self.variogramSampleRateSpinBox = qt.QSpinBox()
        self.variogramSampleRateSpinBox.setSuffix("%")
        self.variogramSampleRateSpinBox.setMinimum(0)
        self.variogramSampleRateSpinBox.setValue(10)
        self.variogramSampleRateSpinBox.setMaximum(100)
        self.variogramSampleRateSpinBox.setSingleStep(1)

        self.variogramMaxSamplesSpinBox = qt.QSpinBox()
        self.variogramMaxSamplesSpinBox.setMinimum(100)
        self.variogramMaxSamplesSpinBox.setMaximum(10_000)
        self.variogramMaxSamplesSpinBox.setSingleStep(100)
        self.variogramMaxSamplesSpinBox.setValue(1_000)

        self.variogramLagsSpinBox = qt.QSpinBox()
        self.variogramLagsSpinBox.setMinimum(1)
        self.variogramLagsSpinBox.setValue(10)
        self.variogramLagsSpinBox.setMaximum(1_000)
        self.variogramLagsSpinBox.setSingleStep(1)

        self.variogramDirectionalToleranceSpinBox = qt.QSpinBox()
        self.variogramDirectionalToleranceSpinBox.setSuffix("°")
        self.variogramDirectionalToleranceSpinBox.setMinimum(0)
        self.variogramDirectionalToleranceSpinBox.setValue(60)
        self.variogramDirectionalToleranceSpinBox.setMaximum(180)
        self.variogramDirectionalToleranceSpinBox.setSingleStep(5)

        self.maximumDistanceLayout = qt.QHBoxLayout()
        self.maximumDistanceSlider = slicer.qMRMLSliderWidget()
        self.maximumDistanceSlider.enabled = False
        self.maximumDistanceSlider.setToolTip("Set maximum distance between two points to be used in variogram")
        self.maximumDistanceSlider.suffix = " mm"
        self.maximumDistanceCheckBox = qt.QCheckBox()
        self.maximumDistanceCheckBox.stateChanged.connect(self._on_maximum_distance_checked)
        self.maximumDistanceCheckBox.setChecked(False)
        self.maximumDistanceCheckBox.setToolTip(
            "If checked maximum distance field will be used. Mean distance will be " "used otherwise."
        )
        self.maximumDistanceLayout.addWidget(self.maximumDistanceCheckBox)
        self.maximumDistanceLayout.addWidget(self.maximumDistanceSlider)

        parametersForm.addRow(self.variogramParametersTitle)
        parametersForm.addRow("Sampling rate: ", self.variogramSampleRateSpinBox)
        parametersForm.addRow("Maximum number of samples: ", self.variogramMaxSamplesSpinBox)
        parametersForm.addRow("Number of lags: ", self.variogramLagsSpinBox)
        parametersForm.addRow("Directional tolerance: ", self.variogramDirectionalToleranceSpinBox)
        parametersForm.addRow("Maximum distance: ", self.maximumDistanceLayout)
        parametersForm.addRow(self.useNuggetCheckBox)
        parametersForm.addRow("", self.variogramApplyButton)
        parametersForm.addRow(self.variogramResultCollapsible)

        #
        # Subvolume parameters
        #

        self.subvolumeParametersTitle = self._create_title_widget("Representative volume analysis")

        self.subvolumeNumSizesSpinBox = qt.QSpinBox()
        self.subvolumeNumSizesSpinBox.setMinimum(2)
        self.subvolumeNumSizesSpinBox.setMaximum(1_000)
        self.subvolumeNumSizesSpinBox.setSingleStep(5)
        self.subvolumeNumSizesSpinBox.setValue(10)

        self.subvolumeMaxSamplesSpinBox = qt.QSpinBox()
        self.subvolumeMaxSamplesSpinBox.setMinimum(1)
        self.subvolumeMaxSamplesSpinBox.setMaximum(10_000)
        self.subvolumeMaxSamplesSpinBox.setSingleStep(5)
        self.subvolumeMaxSamplesSpinBox.setValue(50)

        self.representativeVolumeApplyButton = qt.QPushButton("Produce representative volume report")
        self.representativeVolumeApplyButton.clicked.connect(lambda: self.on_representative_volume_apply())

        self.subvolumeResultCollapsible = ctk.ctkCollapsibleButton()
        self.subvolumeResultCollapsible.flat = True
        self.subvolumeResultCollapsible.collapsed = True
        self.subvolumeResultCollapsible.text = "Result"

        parametersForm.addRow(self.subvolumeParametersTitle)
        parametersForm.addRow("Number of volume sizes: ", self.subvolumeNumSizesSpinBox)
        parametersForm.addRow("Maximum number of samples per volume: ", self.subvolumeMaxSamplesSpinBox)
        parametersForm.addRow("", self.representativeVolumeApplyButton)
        parametersForm.addRow(self.subvolumeResultCollapsible)

        analysisParametersBox.addWidget(parametersFrame)

        self.layout.addSpacing(10)
        applyAllButton = qt.QPushButton("Apply all")
        applyAllButton.clicked.connect(self._on_apply_all)
        analysisParametersBox.addWidget(applyAllButton)

        analysisParametersGroup.setLayout(analysisParametersBox)
        self.layout.addWidget(analysisParametersGroup)

        #
        # Output
        #
        outputGroup = ctk.ctkCollapsibleButton()
        outputGroup.text = "Output"
        outputLayout = qt.QFormLayout(outputGroup)
        self.exportDirectoryButton = ctk.ctkDirectoryButton()
        self.exportDirectoryButton.setMaximumWidth(374)
        self.exportDirectoryButton.caption = "Export directory"
        self.exportDirectoryButton.directory = VariogramAnalysis.get_setting(
            self.EXPORT_DIRECTORY, default=str(Path.home())
        )

        exportButton = qt.QPushButton("Export report")
        exportButton.clicked.connect(self._on_export)

        outputLayout.addRow("Export directory:", self.exportDirectoryButton)
        outputLayout.addRow(exportButton)
        self.layout.addWidget(outputGroup)

        #
        # Variogram report
        #
        variogramReportForm = qt.QFormLayout(self.variogramResultCollapsible)

        variogramReportTitle = self._create_title_widget("Variogram results")
        variogramReportForm.addRow(variogramReportTitle)

        # add pyqtgraph widgets in pyside wrapped layout
        pysideVariogramReportForm = shiboken2.wrapInstance(hash(variogramReportForm), pyside.QtWidgets.QFormLayout)

        self.variogramGraphicsLayout = GraphicsLayoutWidget()
        size_policy = self.variogramGraphicsLayout.sizePolicy()
        size_policy.setRetainSizeWhenHidden(True)
        self.variogramGraphicsLayout.setSizePolicy(size_policy)
        self.variogramGraphicsLayout.setMinimumHeight(400)
        self.variogramBarGraphItem = self.variogramGraphicsLayout.addPlot(row=1, col=1, rowspan=1, colspan=1)
        self.variogramBarGraphItem.showGrid(x=True, y=True, alpha=0.4)
        self.variogramPlotItem = self.variogramGraphicsLayout.addPlot(row=2, col=1, rowspan=5, colspan=1)
        self.variogramPlotItem.showGrid(x=True, y=True, alpha=0.4)
        self.legend = self.variogramPlotItem.addLegend()
        self.legend.setBrush((0, 0, 0, 20))
        axesColors = dict(r=(130, 130, 130), x="r", y="g", z="b")
        axesNames = [*axesColors.keys()]
        self.variogramPoints = {}
        self.variogramCurves = {}
        self.variogramBars = {}
        self.variogramBarGraphItem.setXLink(self.variogramPlotItem)
        self.variogramBarGraphItem.getAxis("bottom").setStyle(showValues=False)
        for axis, color in axesColors.items():
            self.variogramPoints[axis] = self.variogramPlotItem.plot(
                pen=None, symbol="o", symbolSize=5, symbolPen=None, symbolBrush=color
            )
            self.variogramCurves[axis] = self.variogramPlotItem.plot(
                name=axis, pen=color, symbol=None, symbolPen=None, symbolSize=None, symbolBrush=None
            )
            self.variogramBars[axis] = pg.BarGraphItem(x=[0], height=[0], width=0, brush=color)
            self.variogramBarGraphItem.addItem(self.variogramBars[axis])

        self.variogramBarGraphItem.getAxis("left").setLabel("Samples")
        self.variogramPlotItem.getAxis("left").setLabel("Semivariance")
        self.variogramPlotItem.getAxis("bottom").setLabel("Distance (mm)")

        pysideVariogramReportForm.addRow(self.variogramGraphicsLayout)

        variogramResultTitle = self._create_title_widget("Fitted variogram parameters")
        variogramResultFrame = qt.QFrame()
        variogramResultGrid = qt.QGridLayout(variogramResultFrame)

        resultRows = ["", *axesNames]
        resultColumns = ["", "Range", "Sill", "Nugget"]
        self.variogramResultLabels = {r: {} for r in resultRows}
        for row, rowName in enumerate(resultRows):
            for col, colName in enumerate(resultColumns):
                if row == 0:
                    content = colName
                elif col == 0:
                    content = rowName
                else:
                    content = ""

                label = qt.QLabel(content)
                label.setAlignment(qt.Qt.AlignCenter)
                variogramResultGrid.addWidget(label, row, col)
                self.variogramResultLabels[rowName][colName] = label

        variogramReportForm.addRow(qt.QLabel())
        variogramReportForm.addRow(variogramResultTitle)
        variogramReportForm.addRow(variogramResultFrame)

        #
        # Subvolume report
        #
        subvolumeReportForm = qt.QFormLayout(self.subvolumeResultCollapsible)

        subvolumeReportTitle = self._create_title_widget("Representative volume analysis results")
        subvolumeReportForm.addRow(subvolumeReportTitle)

        self.subvolumeGraphicsLayout = GraphicsLayoutWidget()
        size_policy = self.subvolumeGraphicsLayout.sizePolicy()
        size_policy.setRetainSizeWhenHidden(True)
        self.subvolumeGraphicsLayout.setSizePolicy(size_policy)
        self.subvolumeGraphicsLayout.setMinimumHeight(400)
        self.subvolumeBarGraphItem = self.subvolumeGraphicsLayout.addPlot(row=1, col=1, rowspan=1, colspan=1)
        self.subvolumeBarGraphItem.showGrid(x=True, y=True, alpha=0.4)
        self.subvolumePlotItem = self.subvolumeGraphicsLayout.addPlot(row=2, col=1, rowspan=5, colspan=1)
        self.subvolumePlotItem.showGrid(x=True, y=True, alpha=0.4)
        axesNames = [*axesColors.keys()]
        self.subvolumeBarGraphItem.setXLink(self.subvolumePlotItem)
        self.subvolumeBarGraphItem.getAxis("bottom").setStyle(showValues=False)

        self.subvolumeCurve = self.subvolumePlotItem.plot(
            pen=(130, 130, 130), symbol="o", symbolPen=None, symbolSize=5, symbolBrush=(130, 130, 130)
        )
        self.subvolumeBars = pg.BarGraphItem(x=[0], height=[0], width=0, brush=(130, 130, 130))
        self.subvolumeBarGraphItem.addItem(self.subvolumeBars)

        self.subvolumeBarGraphItem.getAxis("left").setLabel("Samples")
        self.subvolumePlotItem.getAxis("left").setLabel("Mean's Standard deviation")
        self.subvolumePlotItem.getAxis("bottom").setLabel("Distance (mm)")

        pysideSubvolumeReportForm = shiboken2.wrapInstance(hash(subvolumeReportForm), pyside.QtWidgets.QFormLayout)
        pysideSubvolumeReportForm.addRow(self.subvolumeGraphicsLayout)

        # Add vertical spacer
        self.layout.addStretch(1)

        # self._on_soi_node_selected(None)

    def enter(self) -> None:
        super().enter()

    def exit(self):
        pass

    def _set_sample_graph_visible(self, visible):
        if visible:
            self.variogramBarGraphItem.show()
            self.variogramGraphicsLayout.setMinimumHeight(400)
            if self.legend.getLabel(self.variogramCurves["r"]) is None:
                self.legend.addItem(self.variogramCurves["r"], "r")
        else:
            self.variogramBarGraphItem.hide()
            self.variogramGraphicsLayout.setMinimumHeight(300)
            if self.legend.getLabel(self.variogramCurves["r"]) is not None:
                self.legend.removeItem(self.variogramCurves["r"])
        self.variogramGraphicsLayout.setMinimumWidth(50)  # This strange code is necessary to avoid graphic being
        self.variogramGraphicsLayout.setMaximumWidth(50)  # stuck at a strange minimum width.
        self.variogramGraphicsLayout.setMaximumWidth(2000)  #

    # def __calculate_variogram(self, coords, values):  # TODO remove or readd; logic?

    def _sequence_to_vtk_string_array(self, strings, array_name=None):
        vtk_string_array = vtk.vtkStringArray()
        if array_name is not None:
            vtk_string_array.SetName(array_name)
        for string in strings:
            vtk_string_array.InsertNextValue(string)
        return vtk_string_array

    def _get_data_and_mask(self, main_node, reference_node, soi_node, selected_segment_indices):
        # setting data up
        if not isinstance(main_node, slicer.vtkMRMLSegmentationNode):
            data = slicer.util.arrayFromVolume(main_node)
        else:
            vtk_segment_ids = vtk.vtkStringArray()
            main_node.GetSegmentation().GetSegmentIDs(vtk_segment_ids)

            selected_segment_ids = [vtk_segment_ids.GetValue(i) for i in selected_segment_indices]
            vtk_selected_segment_ids = self._sequence_to_vtk_string_array(selected_segment_ids, "data_segment_ids")

            # create labelmap
            data_labelmap_node = createTemporaryVolumeNode(
                cls=slicer.vtkMRMLLabelMapVolumeNode,
                name="data_labelmap_node",
            )

            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                main_node,  # segmentationNode
                vtk_selected_segment_ids,  # segmentIds
                data_labelmap_node,  # labelmapNode (output)
                reference_node,  # referenceVolumeNode
            )

            labelmap_array = slicer.util.arrayFromVolume(data_labelmap_node)
            data = (labelmap_array > 0).astype(np.float32)

            if data is None:
                slicer.util.errorDisplay(
                    windowTitle="Input error",
                    text="Could not retrieve data from input node",
                )
                highlight_error(self.inputSelection.referenceInput)

        # setting mask up
        if soi_node is None:
            mask = None
        else:
            slices, mask = createMaskWithROI(reference_node, soi_node)

        return data, mask

    @staticmethod
    @jit(boundscheck=False, nogil=True, nopython=True)
    def sample_nonzero_1d(mask, desired):  # desired must be sorted
        nsamples = desired.size
        idx_sample = np.empty(nsamples, dtype=np.int64)

        samp_cursor = 0
        idx_desired = 0

        for i in range(mask.size):
            if mask[i]:
                while (idx_desired < nsamples) and (samp_cursor == desired[idx_desired]):
                    idx_sample[idx_desired] = i
                    idx_desired += 1
                samp_cursor += 1
        return idx_sample

    def sample_nonzero(self, mask, indices_in_mask_sorted):
        sample_indices = self.sample_nonzero_1d(mask.ravel(), indices_in_mask_sorted)
        return np.unravel_index(sample_indices, mask.shape)

    def sample_mask_indices(self, mask, resample_factor=0.1, max_samples=1_000):
        nsamples_orig = np.sum(mask)
        nsamples = int(np.ceil(resample_factor * nsamples_orig))
        if max_samples is not None:
            nsamples = min(nsamples, max_samples)

        idx_ravel = np.random.randint(nsamples_orig, size=nsamples)
        idx_ravel.sort()

        sample_indices = self.sample_nonzero(mask, idx_ravel)
        sample_indices = np.c_[sample_indices]
        sample_indices = np.random.permutation(sample_indices)
        return sample_indices

    @staticmethod
    def sample_indices(shape, resample_factor=0.1, max_samples=1_000):
        nsamples_orig = np.prod(shape)
        nsamples = int(np.ceil(resample_factor * nsamples_orig))
        if max_samples is not None:
            nsamples = min(nsamples, max_samples)

        idx_ravel = np.random.randint(nsamples_orig, size=nsamples)
        sample_indices = np.unravel_index(idx_ravel, shape)
        sample_indices = np.c_[sample_indices]
        return sample_indices

    @timeit
    def _sample_coords_and_values(self, data, mask=None, resample_factor=0.1, max_samples=1_000):
        if mask is None:
            coords_kji = self.sample_indices(data.shape, resample_factor, max_samples)
        else:
            coords_kji = self.sample_mask_indices(mask, resample_factor, max_samples)

        values = timeit(data.__getitem__)(tuple(coords_kji.T))  # TODO values = data[idx_nonzero]
        coords_ijk = coords_kji[:, ::-1]

        reference_node = self.inputSelection.referenceInput.currentNode()
        coords_ras = timeit(volume_ijk_to_ras)(coords_ijk, reference_node)
        return coords_ras, values

    def update_variogram(self, data, mask=None):
        if data.ndim != 3:
            raise NotImplementedError("Only scalar volume operations are implemented")

        self._set_sample_graph_visible(True)

        coords_ras, values = self._sample_coords_and_values(
            data=data,
            mask=mask,
            resample_factor=self.variogramSampleRateSpinBox.value / 100,
            max_samples=self.variogramMaxSamplesSpinBox.value,
        )

        directional_tolerance = self.variogramDirectionalToleranceSpinBox.value
        direction_options = {
            "r": dict(azimuth=0, dip=0, tolerance=360),
            "x": dict(azimuth=90, dip=0, tolerance=directional_tolerance),
            "y": dict(azimuth=0, dip=0, tolerance=directional_tolerance),
            "z": dict(azimuth=0, dip=-90, tolerance=directional_tolerance),
        }

        variogram = None
        bins = None
        xMax = None
        x = None
        counts = {}
        for i, (axis, options) in enumerate(direction_options.items()):
            if axis == "r":
                # OBS: not using skg sampling for performance issues
                variogram = timeit(GeneralizedVariogram)(
                    coords_ras,
                    values,
                    maxlag=self._get_maximum_distance() or "mean",
                    bin_func="even",
                    n_lags=self.variogramLagsSpinBox.value,
                    use_nugget=self.useNuggetCheckBox.checked,
                    # fit_sigma='sq',
                    **options,
                )
                bins = variogram.bins
                xMax = bins[-1] + bins[0] / 2
                x = np.linspace(0, xMax)
            else:
                variogram.azimuth = options["azimuth"]
                variogram.dip = options["dip"]
                variogram.tolerance = options["tolerance"]
                variogram.fit()

            var_range, var_sill, var_nugget = variogram.parameters
            self.variogramResultLabels[axis]["Range"].setText(f"{var_range:.2g}")
            self.variogramResultLabels[axis]["Sill"].setText(f"{var_sill:.2g}")
            self.variogramResultLabels[axis]["Nugget"].setText(f"{var_nugget:.2g}")

            counts[axis] = np.asarray([lag.size for lag in variogram.lag_classes()])
            self.variogramPoints[axis].setData(bins, variogram.experimental)
            self.variogramCurves[axis].setData(x, variogram.transform(x))
            self.variogramBars[axis].setOpts(
                x=bins + (-1.5 + i) * bins[0] / 2 / 3, height=counts[axis], width=bins[0] / 2 / 4
            )
        self.variogramPlotItem.autoRange()
        self.variogramBarGraphItem.autoRange()
        self.variogramPlotItem.setXRange(0, xMax)
        self.variogramPlotItem.setYRange(0, 1.25 * (var_nugget + var_sill))

    @staticmethod
    @timeit
    def subvolume_property_analysis(array, mask=None, num_sizes=100, max_samples=100):
        array = array.astype(np.float32)

        # mask array
        if mask is not None:
            array[~mask] = np.nan

        # logic needs volume array
        array = np.atleast_3d(array)
        shape = np.asarray(array.shape[:3])
        fake_axes = np.where(shape < 2)[0]
        valid_shape = np.delete(shape, fake_axes)
        min_edge = 2
        max_edge = np.min(valid_shape)
        max_edge_used = max_edge // 2
        num_non_fake_axes = len(valid_shape)

        if VariogramAnalysis.SUBVOLUME_ANALYSIS_TYPE == "volume":
            max_volume_used = max_edge_used**num_non_fake_axes

        # volume edge sizes
        if VariogramAnalysis.SUBVOLUME_ANALYSIS_TYPE == "volume":
            distances = np.linspace(min_edge, max_volume_used, num_sizes)
            size_edges = np.round(distances ** (1 / num_non_fake_axes)).astype(int)
        elif VariogramAnalysis.SUBVOLUME_ANALYSIS_TYPE == "edge":
            distances = np.linspace(min_edge, max_edge_used, num_sizes).astype(int)
            size_edges = distances

        # declare arrays for variance calculation
        size_sq_mean_mean = np.zeros(len(distances))
        size_mean_mean = np.zeros(len(distances))
        size_samples = np.zeros(len(distances), dtype=int)

        for e, edge in enumerate(size_edges):
            available_shape = np.clip(shape - edge, 1, np.infty).astype(int)

            num_samples = int(np.round((max_edge / edge) ** num_non_fake_axes))
            num_samples = min(num_samples, max_samples)
            idx_ravel = np.random.randint(np.prod(available_shape), size=num_samples)
            idx_samples = np.c_[np.unravel_index(idx_ravel, available_shape)]

            for idx in idx_samples:
                x0, y0, z0 = idx
                window = array[x0 : x0 + edge, y0 : y0 + edge, z0 : z0 + edge]

                if window.size == 0:
                    continue

                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    size_mean = np.nanmean(window)

                if np.isnan(size_mean):
                    continue

                size_samples[e] += 1

                # gotcha: normalize denominators of old and new terms of the running mean
                normalizer = (size_samples[e] - 1) / size_samples[e]
                size_mean_mean[e] = (normalizer * size_mean_mean[e]) + (size_mean / size_samples[e])
                size_sq_mean_mean[e] = (normalizer * size_sq_mean_mean[e]) + (size_mean**2 / size_samples[e])

        # calculate variance: var(x) = E[x**2] - E[x]**2
        size_vars = size_sq_mean_mean - (size_mean_mean) ** 2
        size_stds = np.sqrt(size_vars)

        # delete sizes with no samples evaluated
        zero_sampled_sizes = size_samples < 1
        distances = np.delete(distances, zero_sampled_sizes)
        size_samples = np.delete(size_samples, zero_sampled_sizes)
        size_stds = np.delete(size_stds, zero_sampled_sizes)

        return distances, size_samples, size_stds

    def update_subvolume_properties(self, data, mask=None):
        reference_node = self.inputSelection.referenceInput.currentNode()
        if VariogramAnalysis.SUBVOLUME_ANALYSIS_TYPE == "volume":
            voxel_volume = np.prod(reference_node.GetSpacing())
        elif VariogramAnalysis.SUBVOLUME_ANALYSIS_TYPE == "edge":
            voxel_mean = np.mean(reference_node.GetSpacing())

        distances_ijk, samples, stds = self.subvolume_property_analysis(
            data,
            mask,
            num_sizes=self.subvolumeNumSizesSpinBox.value,
            max_samples=self.subvolumeMaxSamplesSpinBox.value,
        )
        self.progressBarProc.setProgress(95)

        if VariogramAnalysis.SUBVOLUME_ANALYSIS_TYPE == "volume":
            distances_ras = voxel_volume * distances_ijk
        elif VariogramAnalysis.SUBVOLUME_ANALYSIS_TYPE == "edge":
            distances_ras = voxel_mean * distances_ijk

        bar_width = (distances_ras[1] - distances_ras[0]) / 2 / 2
        self.subvolumePlotItem.setXRange(np.nanmin(distances_ras), np.nanmax(distances_ras))
        self.subvolumePlotItem.setYRange(np.nanmin(stds), np.nanmax(stds))
        self.subvolumeCurve.setData(distances_ras, stds)
        self.subvolumeBars.setOpts(x=distances_ras, height=samples, width=bar_width)

    def check_input_validity(self):
        main_node = self.inputSelection.mainInput.currentNode()
        reference_node = self.inputSelection.referenceInput.currentNode()
        soi_node = self.inputSelection.soiInput.currentNode()
        selected_segment_indices = self.inputSelection.getSelectedSegments()

        if main_node is None:
            highlight_error(self.inputSelection.mainInput)
        elif reference_node is None:
            highlight_error(self.inputSelection.referenceInput)
        elif isinstance(main_node, slicer.vtkMRMLSegmentationNode) and len(selected_segment_indices) == 0:
            highlight_error(self.inputSelection.segmentListWidget)
        elif soi_node is None:
            highlight_warning(self.inputSelection.soiInput)
            self.warningLabel.show()
            return main_node, reference_node, soi_node, selected_segment_indices
        else:
            return main_node, reference_node, soi_node, selected_segment_indices
        return None

    def on_variogram_apply(self):
        inputs = self.check_input_validity()
        if inputs:
            self._calculate_variogram(*inputs)

    @useProgressBar
    def _calculate_variogram(self, main_node, reference_node, soi_node, selected_segment_indices):
        self.progressBarProc.setMessage("Calculating variogram")
        self.progressBarProc.setProgress(0)

        data, mask = self._get_data_and_mask(main_node, reference_node, soi_node, selected_segment_indices)

        if data is None:
            return

        if mask is not None and mask.shape != data.shape:
            slicer.util.errorDisplay(
                windowTitle="Input error",
                text="Could not match input node with SOI: input dimensions"
                f"are {data.shape}, while SOI dimensions are {mask.shape}.",
            )
            highlight_error(self.inputSelection.soiInput)
            return

        self.progressBarProc.setProgress(20)

        if mask is None:
            self.calculate_fft_variogram(data)
        else:
            self.update_variogram(data, mask)
        self.progressBarProc.setProgress(100)
        self.variogramResultCollapsible.collapsed = False
        self.has_processed_variogram = True

    def on_representative_volume_apply(self):
        inputs = self.check_input_validity()
        if inputs:
            self._calculate_rev(*inputs)

    @useProgressBar
    def _calculate_rev(self, main_node, reference_node, soi_node, selected_segment_indices):
        self.progressBarProc.setMessage("Calculating REV")
        self.progressBarProc.setProgress(0)

        data, mask = self._get_data_and_mask(main_node, reference_node, soi_node, selected_segment_indices)

        if data is None:
            return

        if mask is not None and mask.shape != data.shape:
            slicer.util.errorDisplay(
                windowTitle="Input error",
                text="Could not match input node with SOI: input dimensions"
                f"are {data.shape}, while SOI dimensions are {mask.shape}.",
            )
            return

        self.progressBarProc.setProgress(20)

        self.update_subvolume_properties(data, mask)
        self.progressBarProc.setProgress(100)
        self.subvolumeResultCollapsible.collapsed = False
        self.has_processed_rev = True

    def _on_export(self):
        VariogramAnalysis.set_setting(self.EXPORT_DIRECTORY, self.exportDirectoryButton.directory)
        output_path = Path(self.exportDirectoryButton.directory).absolute()

        current_node = self.inputSelection.referenceInput.currentNode()
        if not current_node:
            slicer.util.errorDisplay(
                windowTitle="Input data error!",
                text="There's no reference node selected",
            )
            return
        dimensions = slicer.util.arrayFromVolume(current_node).shape
        voxel_size = current_node.GetSpacing()
        voxel_size = ["{:~}".format(ureg.Quantity(size, SLICER_LENGTH_UNIT).to_compact()) for size in voxel_size]
        if len(set(voxel_size)) == 1:
            voxel_size = voxel_size[0]
        else:
            voxel_size = f"{voxel_size[0]} x {voxel_size[1]} x {voxel_size[2]}"

        parsed_file_name = PetrobrasRawFileName(current_node.GetName())

        basic_information = {}
        basic_information["well"] = parsed_file_name.well
        basic_information["plug"] = parsed_file_name.sample
        basic_information["condition"] = parsed_file_name.state
        basic_information["acquisition"] = parsed_file_name.type
        basic_information["dimensions"] = f"{dimensions[0]}x{dimensions[1]}x{dimensions[2]}"
        basic_information["voxel_size"] = voxel_size

        distance_correlation = {}
        distance_correlation["range"] = {}
        distance_correlation["range"]["x"] = self.variogramResultLabels["x"]["Range"].text
        distance_correlation["range"]["y"] = self.variogramResultLabels["y"]["Range"].text
        distance_correlation["range"]["z"] = self.variogramResultLabels["z"]["Range"].text
        distance_correlation["range"]["r"] = self.variogramResultLabels["r"]["Range"].text

        report_template_path = Path(__file__).parent.absolute() / "Resources"
        report_template_file_path = report_template_path / "variogram_report_template.html"
        report_builder = ReportBuilder(report_template_file_path)
        report_builder.add_image_file("lTrace.logo", str(report_template_path / "LTrace-logo-original.png"))
        report_builder.add_image_data("slices_image", self._get_slices_image())
        report_builder.add_variable("basic_information", basic_information)
        if self.has_processed_variogram:
            report_builder.add_image_data(
                "variogram_image", self._get_graphic_layout_image(self.variogramGraphicsLayout)
            )
            report_builder.add_variable("distance_correlation", distance_correlation)
        if self.has_processed_rev:
            report_builder.add_image_data(
                "subvolume_image", self._get_graphic_layout_image(self.subvolumeGraphicsLayout)
            )
        report_builder.generate(str(output_path / f"{parsed_file_name.well}_{parsed_file_name.sample}_REV_report.html"))

        if self.has_processed_variogram and self.has_processed_rev:
            slicer.util.infoDisplay("Report successfully exported")
        elif self.has_processed_rev:
            slicer.util.infoDisplay(
                "Report exported with only representative volume result since no variogram analysis was executed for this reference."
            )
        elif self.has_processed_variogram:
            slicer.util.infoDisplay(
                "Report exported with only variogram result since no representative volume analysis was executed for this reference."
            )
        else:
            slicer.util.infoDisplay(
                "Report exported with only basic information since no analysis was executed for this reference."
            )

    def _get_graphic_layout_image(self, garphics_layout):
        exporter = pg.exporters.ImageExporter(garphics_layout.scene())
        tmp_file_path = "LTrace/temp/variogram_analysis_tmp.png"
        exporter.export(tmp_file_path)
        image = cv2.imread(tmp_file_path)
        os.remove(tmp_file_path)
        return image

    def _get_slices_image(self):
        tmp_file_path = "LTrace/temp/variogram_analysis_tmp.png"
        cap = ScreenCapture.ScreenCaptureLogic()
        cap.captureImageFromView(None, tmp_file_path)
        image = cv2.imread(tmp_file_path)
        os.remove(tmp_file_path)
        return image

    def _on_apply_all(self):
        self.on_variogram_apply()
        self.on_representative_volume_apply()

    def calculate_fft_variogram(self, data):
        self._set_sample_graph_visible(False)
        self.variogramPoints["r"].clear()
        self.variogramCurves["r"].clear()

        i_limits, j_limits, k_limits = getInscribedCuboidLimits(
            self.inputSelection.referenceInput.currentNode(), 0.98, 0.90
        )
        clipped_data = data[k_limits[0] : k_limits[1], j_limits[0] : j_limits[1], i_limits[0] : i_limits[1]]
        clipped_data = clipped_data.squeeze()
        self.progressBarProc.setProgress(40)

        variogram_fft = VariogramFFT(clipped_data, self.inputSelection.referenceInput.currentNode().GetSpacing())
        x_axes, y_axes, curve = variogram_fft.calculate(use_nugget=self.useNuggetCheckBox.checked)
        self.progressBarProc.setProgress(95)

        direction_options = ["x", "y", "z"]

        fit_error_occurred = False
        for i in range(clipped_data.ndim):
            axis = direction_options[i]
            var_sill = variogram_fft.get_sill(i)
            var_range = variogram_fft.get_range(i)
            var_nugget = variogram_fft.get_nugget(i)
            self.variogramResultLabels[axis]["Range"].setText(f"{var_range:.2g}")
            self.variogramResultLabels[axis]["Sill"].setText(f"{var_sill:.2g}")
            self.variogramResultLabels[axis]["Nugget"].setText(f"{var_nugget:.2g}")
            self.variogramPoints[axis].setData(x_axes[i], y_axes[i])
            if curve[i] is not None:
                self.variogramCurves[axis].setData(x_axes[i], curve[i])
            else:
                self.variogramCurves[axis].clear()
                fit_error_occurred = True

        self.variogramPlotItem.autoRange()
        self.variogramPlotItem.setXRange(0, 2 * var_range)
        self.variogramPlotItem.setYRange(0, 1.25 * (var_nugget + var_sill))

        if fit_error_occurred:
            slicer.util.warningDisplay(
                windowTitle="Warning",
                text="Could not fit variance values to a function",
            )

    def _on_reference_node_selected(self, current_node):
        self.has_processed_variogram = False
        self.has_processed_rev = False
        self._clear_plots()

        if current_node is None:
            return

        volume_data = slicer.util.arrayFromVolume(current_node)

        # NumPy coords are kji, so reversion is needed
        last_coord_ijk = [i - 1 for i in volume_data.shape[::-1]]
        coords_ras = volume_ijk_to_ras(np.array([(0, 0, 0), last_coord_ijk]), current_node)
        max_ras_diff = coords_ras[1] - coords_ras[0]
        max_distance = np.sqrt(np.sum(np.square(max_ras_diff)))
        initial_max_distance = max_distance / 2
        self.maximumDistanceSlider.maximum = max_distance
        self.maximumDistanceSlider.singleStep = max_distance / 100
        self.maximumDistanceSlider.setValue(initial_max_distance)

    def _on_soi_node_selected(self, current_soi_node):
        enable = current_soi_node is not None
        if enable:
            self.warningLabel.hide()
        # self.variogramDirectionalToleranceSpinBox.enabled = enable
        # self.variogramSampleRateSpinBox.enabled = enable
        # self.variogramMaxSamplesSpinBox.enabled = enable
        # self.variogramLagsSpinBox.enabled = enable
        # self.maximumDistanceCheckBox.enabled = enable
        # self.maximumDistanceSlider.enabled = enable and self.maximumDistanceCheckBox.checked

    def _on_maximum_distance_checked(self, checked):
        self.maximumDistanceSlider.enabled = checked

    def _get_maximum_distance(self):
        if self.maximumDistanceCheckBox.checked:
            return self.maximumDistanceSlider.value
        else:
            return None

    def _create_title_widget(self, title_text):
        title_widget = qt.QLabel(title_text)
        title_widget.setStyleSheet("QLabel { font-size: 12px; font-weight: bold; padding: 10px; margin: 4px; }")
        title_widget.setAlignment(qt.Qt.AlignCenter)
        return title_widget

    def _clear_plots(self):
        direction_options = ["x", "y", "z", "r"]
        for i, axis in enumerate(direction_options):
            self.variogramPoints[axis].clear()
            self.variogramCurves[axis].clear()
            self.variogramBars[axis].setOpts(x=[])
        self.subvolumeCurve.clear()
        self.subvolumeBars.setOpts(x=[])

        self.variogramBarGraphItem.update()
        self.variogramPlotItem.update()
        self.subvolumeBarGraphItem.update()
        self.subvolumePlotItem.update()


class VariogramAnalysisLogic(LTracePluginLogic):
    def run(self):
        pass
