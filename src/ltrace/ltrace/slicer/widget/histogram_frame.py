import ctk
import numpy as np
import qt
import slicer
import shiboken2
import PySide2

from ltrace.algorithms.common import randomChoice
from ltrace.slicer.helpers import getVolumeNullValue, themeIsDark, BlockSignals
from ltrace.slicer.node_observer import NodeObserver
from ltrace.slicer.ui import CheckBoxWidget, numberParamInt

import pyqtgraph as pg
from pyqtgraph.Qt import QtGui

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass

import numpy as np

from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import (
    GraphicsLayoutWidget,
)


class HistogramMeta(type(qt.QFrame), ABCMeta):
    pass


class HistogramFrame(qt.QFrame, metaclass=HistogramMeta):
    def __init__(self, parent=None, region_widget=None, view_widget=None):
        super().__init__(parent)

        self.voxel_array = list()
        self.array_colors = list()
        self.null_value = None
        self.histogram_range = None
        self.initialized_nodes = set()

        self.region_leeway = 0
        self.view_leeway = 0

        self.number_of_arrays = 1

        self.region_widget = region_widget

        self.view_widget = view_widget

        self.remove_background_check = CheckBoxWidget(
            tooltip="Remove background points for best Y range", checked=False, onToggle=self._on_checkbox_toggled
        )

        self.number_of_bins_box = numberParamInt(vrange=(10, 1000), value=200)
        self.number_of_bins_box.editingFinished.connect(self._on_number_of_bins_changed)
        self.number_of_bins_box.setToolTip("Number of bins")

        self.number_of_sample_points_box = numberParamInt(vrange=(100, 1000000), value=40000)
        self.number_of_sample_points_box.editingFinished.connect(self._on_number_of_sample_points_changed)
        self.number_of_sample_points_box.setToolTip("Approximate number of sample points")

        self.observer: NodeObserver = None

    def set_data(
        self,
        reference_data=None,
        array_masks=None,
        plot_colors=None,
        update_plot_auto_zoom=False,
    ):
        self.clear_loaded_data()
        if reference_data is None:
            return

        if array_masks is not None:
            masked_arrays = list()
            for i in range(self.number_of_arrays):
                masked_arrays.append(reference_data[array_masks[i]])
            self.voxel_array = masked_arrays
        else:
            self.voxel_array = [reference_data]

        if plot_colors is None:
            plot_colors = [tuple([127.0, 127.0, 127.0])] * len(self.voxel_array)

        self.array_colors = list()
        for i in range(len(self.voxel_array)):
            self.array_colors.append(plot_colors[i])
        self._update_plot(
            self.number_of_bins_box.value,
            number_of_sample_points=min(
                int(self.number_of_sample_points_box.value), sum([len(arr) for arr in self.voxel_array])
            ),
            auto_adjust_zoom=update_plot_auto_zoom,
        )

    def set_region(self, lower_limit, upper_limit):
        self.data_plot.set_region(lower_limit, upper_limit)
        self._set_region_values(lower_limit, upper_limit)

    def has_loaded_data(self):
        if len(self.voxel_array) == 0:
            return False
        else:
            return True

    def clear_loaded_data(self):
        self.data_plot.clear_plots()
        self.data_plot.clear_region()

        for arr in self.voxel_array[:]:
            del arr

        self.voxel_array.clear()
        self.array_colors.clear()

    @abstractmethod
    def _get_region_values(self):
        pass

    @abstractmethod
    def _set_region_values(self, min_, max_):
        pass

    def _set_region_range(self, min_, max_):
        self.data_plot.set_region_range(min_, max_)

    @abstractmethod
    def _on_region_values_changed(self, first_, second_):
        pass

    def _update_plot(self, number_of_bins, number_of_sample_points=40000, auto_adjust_zoom=True):
        if not self.has_loaded_data():
            return
        self.number_of_sample_points_box.value = number_of_sample_points
        numberOfSamplePoints = int(self.number_of_sample_points_box.value)
        region_range_min = np.inf
        region_range_max = np.NINF
        min_x_value = np.inf
        max_x_value = np.NINF

        self.data_plot.clear_plots()
        for i in range(len(self.voxel_array)):
            sampleIntensities = self.voxel_array[i].ravel()
            if self.voxel_array[i].size > numberOfSamplePoints:
                sampleIntensities = randomChoice(sampleIntensities, numberOfSamplePoints, self.null_value)
            else:
                sampleIntensities = sampleIntensities[sampleIntensities != self.null_value]

            if len(sampleIntensities) <= 0:
                continue

            histogram, histogram_edges = np.histogram(sampleIntensities, number_of_bins, self.histogram_range)
            y_values = self.remove_background_max(histogram) if self.remove_background_check.checked else histogram
            region_range_min = min(region_range_min, np.percentile(sampleIntensities, 0.05))
            region_range_max = max(region_range_max, np.percentile(sampleIntensities, 99.95))

            min_x_value = min(min_x_value, histogram_edges[0])
            max_x_value = max(max_x_value, histogram_edges[-1])

            self.data_plot.add_plot(histogram_edges, y_values, self.array_colors[i] + (127,))

        region_diff = (region_range_max - region_range_min) * self.region_leeway
        self._set_region_range(region_range_min - region_diff, region_range_max + region_diff)

        region_min, region_max = self._get_region_values()
        self.set_region(region_min, region_max)

        # Adjust current zoom slider and plot values
        if auto_adjust_zoom:
            view_diff = (region_range_max - region_range_min) * self.view_leeway

            current_data_zoom_range = (
                (min_x_value, max_x_value)
                if auto_adjust_zoom == "minmax"
                else (region_range_min - view_diff, region_range_max + view_diff)
            )

            # Set zoom slider range based on data value boundaries
            self.data_plot.set_view_range(*current_data_zoom_range)
            # Set zoom slider edges based on data value boundaries
            self.data_plot.set_view_edges(*current_data_zoom_range)
        else:
            current_data_zoom_range = (min_x_value, max_x_value)

        self.data_plot.set_graphical_zoom_min_max(*current_data_zoom_range)

    def remove_background_max(self, arr):
        arr = np.array(arr)
        modified_arr = arr.copy()

        if arr[0] == arr.max() and arr[1] == 0:
            modified_arr[0] = 0

        return modified_arr

    def _on_checkbox_toggled(self, checkbox, state):
        self._update_plot(self.number_of_bins_box.value, self.number_of_sample_points_box.value, auto_adjust_zoom=False)

    def _on_number_of_bins_changed(self):
        self._update_plot(self.number_of_bins_box.value, self.number_of_sample_points_box.value, auto_adjust_zoom=False)

    def _on_number_of_sample_points_changed(self):
        self._update_plot(self.number_of_bins_box.value, self.number_of_sample_points_box.value, auto_adjust_zoom=False)

    @abstractmethod
    def _set_region_block_signals(self, block):
        pass

    def _on_region_changed(self):
        min_, max_ = self.data_plot.get_region()
        self._set_region_block_signals(True)
        self._set_region_values(min_, max_)
        self._set_region_block_signals(False)


class DisplayNodeHistogramFrame(HistogramFrame):
    def __init__(self, parent=None, region_widget=None, view_widget=None):
        super().__init__(parent, region_widget, view_widget)
        layout = qt.QVBoxLayout(self)

        self.data_plot = DisplayNodeDataPlot(zoom_slider=view_widget)
        self.data_plot.region_changed.connect(self._on_region_changed)
        layout.addLayout(self.data_plot)

        # ------------------------------------------------------------------------
        buttonsZ_layout = qt.QHBoxLayout()
        buttonsZ_layout.setSpacing(4)

        remove_background_check_label = qt.QLabel("Remove background points:")
        buttonsZ_layout.addWidget(remove_background_check_label)
        buttonsZ_layout.addWidget(self.remove_background_check)

        buttonsA_layout = qt.QHBoxLayout()
        buttonsA_layout.setSpacing(4)

        bins_label = qt.QLabel("Bins: ")
        buttonsA_layout.addWidget(bins_label)
        buttonsA_layout.addWidget(self.number_of_bins_box)

        buttonsB_layout = qt.QHBoxLayout()
        buttonsB_layout.setSpacing(4)

        sample_points_label = qt.QLabel("Samples: ")
        buttonsB_layout.addWidget(sample_points_label)
        buttonsB_layout.addWidget(self.number_of_sample_points_box)

        controls_layout = qt.QHBoxLayout(self)
        controls_layout.setSpacing(16)
        controls_layout.addStretch(1)
        controls_layout.addLayout(buttonsZ_layout)
        controls_layout.addLayout(buttonsA_layout)
        controls_layout.addLayout(buttonsB_layout)

        layout.addLayout(controls_layout)
        # ------------------------------------------------------------------------

        if self.region_widget is not None:
            self.region_widget.findChild(ctk.ctkDoubleSpinBox, "MinSpinBox").findChild(
                qt.QDoubleSpinBox
            ).setKeyboardTracking(False)
            self.region_widget.findChild(ctk.ctkDoubleSpinBox, "MaxSpinBox").findChild(
                qt.QDoubleSpinBox
            ).setKeyboardTracking(False)
            self.region_widget.findChild(ctk.ctkDoubleSpinBox, "WindowSpinBox").findChild(
                qt.QDoubleSpinBox
            ).setKeyboardTracking(False)
            self.region_widget.findChild(ctk.ctkDoubleSpinBox, "LevelSpinBox").findChild(
                qt.QDoubleSpinBox
            ).setKeyboardTracking(False)

    def update_plot_color(self, colorNode):
        self.data_plot.update_color(colorNode)

    def set_data(
        self,
        reference_data=None,
        array_masks=None,
        plot_colors=None,
        update_plot_auto_zoom=False,
    ):
        self.clear_loaded_data()
        if reference_data is None or reference_data.GetImageData() is None:
            return
        self.null_value = getVolumeNullValue(reference_data)
        input_voxel_array = slicer.util.arrayFromVolume(reference_data)

        super().set_data(input_voxel_array, array_masks, plot_colors, update_plot_auto_zoom)

        volume_node = self.region_widget.mrmlVolumeNode()
        if volume_node is None:
            self.data_plot.clear_region()
            return
        observed_display_node = volume_node.GetDisplayNode()
        if observed_display_node is None:
            return
        if self.observer:
            self.observer.clear()
            del self.observer

        self.observer = NodeObserver(node=observed_display_node, parent=self)
        self.observer.modifiedSignal.connect(self.__on_scene_modified)
        self.observer.removedSignal.connect(self.__on_observed_node_removed)
        self.__on_scene_modified()

    def _set_region_block_signals(self, block):
        if self.observer:
            self.observer.blockSignals(block)

    def _set_region_values(self, min_, max_):
        if self.region_widget is not None:
            if self.region_widget.mrmlVolumeNode() and self.region_widget.mrmlVolumeNode().GetDisplayNode():
                old_window = self.region_widget.mrmlVolumeNode().GetDisplayNode().GetWindow()
                old_level = self.region_widget.mrmlVolumeNode().GetDisplayNode().GetLevel()
                new_window = max_ - min_
                new_level = (max_ + min_) / 2
                diff = abs(new_window - old_window) + abs(new_level - old_level)

                if diff > 0.0001:
                    self.region_widget.setMinMaxRangeValue(min_, max_)
            else:
                self.region_widget.setMinMaxRangeValue(min_, max_)

    def _set_region_range(self, min_, max_):
        super()._set_region_range(min_, max_)
        if self.region_widget is not None:
            self.region_widget.setMinMaxBounds(min_, max_)

    def _get_region_values(self):
        if self.region_widget is not None:
            return self.region_widget.minimumValue, self.region_widget.maximumValue

    def _on_region_values_changed(self, first_, second_):
        if self.has_loaded_data() and self.region_widget is not None:
            region_min = second_ - first_ / 2
            region_max = second_ + first_ / 2
            self.data_plot.set_region(region_min, region_max)

    def __on_scene_modified(self, *args, **kwargs):
        if self.observer and self.observer.node:
            window = self.observer.node.GetWindow()
            level = self.observer.node.GetLevel()
            self._on_region_values_changed(window, level)
            self.update_plot_color(self.observer.node.GetColorNode())

    def __on_observed_node_removed(self, *args, **kwargs):
        if self.observer:
            self.observer.clear()
            del self.observer
            self.observer = None


class SegmentationModellingHistogramFrame(HistogramFrame):
    def __init__(self, parent=None, region_widget=None, view_widget=None):
        super().__init__(parent, region_widget, view_widget)
        layout = qt.QVBoxLayout(self)

        self.data_plot = SegmentationModellingDataPlot(zoom_slider=view_widget)
        self.data_plot.region_changed.connect(self._on_region_changed)
        layout.addLayout(self.data_plot)

        buttonsZ_layout = qt.QHBoxLayout()
        buttonsZ_layout.setSpacing(4)

        remove_background_check_label = qt.QLabel("Remove background points:")
        buttonsZ_layout.addWidget(remove_background_check_label)
        buttonsZ_layout.addWidget(self.remove_background_check)

        buttonsA_layout = qt.QHBoxLayout()
        buttonsA_layout.setSpacing(4)

        bins_label = qt.QLabel("Bins: ")
        buttonsA_layout.addWidget(bins_label)
        buttonsA_layout.addWidget(self.number_of_bins_box)

        buttonsB_layout = qt.QHBoxLayout()
        buttonsB_layout.setSpacing(4)

        sample_points_label = qt.QLabel("Samples: ")
        buttonsB_layout.addWidget(sample_points_label)
        buttonsB_layout.addWidget(self.number_of_sample_points_box)

        controls_layout = qt.QHBoxLayout(self)
        controls_layout.setSpacing(16)
        controls_layout.addStretch(1)
        controls_layout.addLayout(buttonsZ_layout)
        controls_layout.addLayout(buttonsA_layout)
        controls_layout.addLayout(buttonsB_layout)

        layout.addLayout(controls_layout)

        self._connect_signals()

    def _set_region_block_signals(self, block):
        self.region_widget.blockSignals(block)

    def _set_region_values(self, min_, max_):
        if self.region_widget is not None:
            self.region_widget.set_min_attenuation_factor(min_)
            self.region_widget.set_max_attenuation_factor(max_)

    def _set_region_range(self, min_, max_):
        super()._set_region_range(min_, max_)
        if self.region_widget is not None:
            self.region_widget.set_factors_value_range(min_, max_)

    def _on_region_values_changed(self, first_, second_):
        if self.has_loaded_data() and self.region_widget is not None:
            self.data_plot.set_region(first_, second_)

    def _get_region_values(self):
        if self.region_widget is not None:
            return (
                self.region_widget.min_attenuation_factor(),
                self.region_widget.max_attenuation_factor(),
            )

    def _connect_signals(self):
        if self.region_widget is not None:
            self.region_widget.signal_editing_finished.connect(self._on_region_values_changed)

        self.data_plot.region_changed.connect(self._on_region_changed)


class MicroPorosityHistogramFrame(SegmentationModellingHistogramFrame):
    def __init__(self, parent=None, region_widget=None, view_widget=None):
        super().__init__(parent, region_widget, view_widget)
        self.number_of_arrays = 3

    def set_data(
        self,
        reference_data=None,
        array_masks=None,
        plot_colors=None,
        update_plot_auto_zoom=False,
    ):
        if reference_data is None:
            self.clear_loaded_data()
            return
        self.null_value = getVolumeNullValue(reference_data)
        input_voxel_array = slicer.util.arrayFromVolume(reference_data)

        super().set_data(input_voxel_array, array_masks, plot_colors, update_plot_auto_zoom)


# /\ Histogram classes
# -----------------------------------------------------------------------------------------------------------
# \/ Data plot classes


@dataclass
class DataPlotPalette:
    bg: str
    fg: str
    plot_bg: str


class DataPlotMeta(type(qt.QFrame), ABCMeta):
    pass


class DataPlot(qt.QFormLayout, metaclass=DataPlotMeta):
    region_changed = qt.Signal()

    def __init__(self, parent=None, zoom_slider=None):
        super().__init__(parent)

        self.zoom_slider = None
        self.linear_region = None
        self.region_min_limit = np.NINF
        self.region_max_limit = np.inf

        # Maximum zoom out for the graph
        self.zoom_min = np.NINF
        self.zoom_max = np.inf

        self.plot_item_list = []

        palette = (
            DataPlotPalette("#3E3E3E", "#FFFFFF", "#1E1E1E")
            if themeIsDark()
            else DataPlotPalette("#FFFFFF", "#000000", "#FFFFFF")
        )

        pysideReportForm = shiboken2.wrapInstance(hash(self), PySide2.QtWidgets.QFormLayout)
        subvolumeGraphicsLayout = GraphicsLayoutWidget()
        subvolumeGraphicsLayout.setMinimumSize(subvolumeGraphicsLayout.minimumWidth(), 200)
        subvolumeGraphicsLayout.setMaximumSize(subvolumeGraphicsLayout.maximumWidth(), 200)
        subvolumeGraphicsLayout.setBackground(palette.bg)
        pysideReportForm.addRow(subvolumeGraphicsLayout)

        pen = QtGui.QPen(palette.fg)
        pen.setWidth(2)
        pen.setStyle(QtGui.Qt.SolidLine)
        pen.setCapStyle(QtGui.Qt.SquareCap)

        self.plot_item = subvolumeGraphicsLayout.addPlot()
        self.plot_item.setMouseEnabled(False, False)
        self.plot_item.getViewBox().setBackgroundColor(palette.plot_bg)
        self.plot_item.getAxis("bottom").setPen(pen)
        self.plot_item.getAxis("left").setPen(pen)
        self.plot_item.getAxis("right").setPen(pen)
        self.plot_item.getAxis("top").setPen(pen)
        self.plot_item.getAxis("bottom").setTextPen(pen)
        self.plot_item.getAxis("left").setTextPen(pen)
        self.plot_item.getAxis("right").setTextPen(pen)
        self.plot_item.getAxis("top").setTextPen(pen)
        self.plot_item.showAxes([True, True, True, True], showValues=True, size=False)

        if zoom_slider is None:
            self.zoom_slider = ctk.ctkRangeWidget()
            self.zoom_slider.valuesChanged.connect(self._set_graphic_range)
            self.addRow("Zoom:", self.zoom_slider)

    def add_plot(self, data_x, data_y, color):
        if type(color) is tuple:
            color = QtGui.QColor(*color[:4])
        else:
            color = QtGui.QColor(color)
        brush = QtGui.QBrush(color)
        new_curve_item = pg.PlotCurveItem(data_x, data_y, stepMode=True, fillLevel=0, brush=brush)
        self.plot_item_list.append(new_curve_item)
        self.plot_item.addItem(new_curve_item)

        self._set_graphic_range(*self.get_view_edges())

    def clear_plots(self):
        for item in self.plot_item_list:
            self.plot_item.removeItem(item)
        self.plot_item_list.clear()

    def set_region_range(self, min_, max_):
        if self.linear_region:
            self.linear_region.setBounds((min_, max_))
        # For when self.linear_region get initialized:
        self.region_min_limit = min_
        self.region_max_limit = max_

    def set_region(self, min_, max_):
        if self.linear_region:
            with BlockSignals(self.linear_region):
                self.linear_region.setRegion((min_, max_))
        else:
            self.linear_region = pg.LinearRegionItem((min_, max_))
            self.linear_region.setRegion((min_, max_))
            self.set_region_range(self.region_min_limit, self.region_max_limit)
            self.linear_region.sigRegionChanged.connect(self._on_region_changed)
            self.plot_item.addItem(self.linear_region)

    def set_graphical_zoom_min_max(self, min_, max_):
        """Don't allow plot to zoom out more than it currently has."""
        self.zoom_min = min_
        self.zoom_max = max_
        self._set_graphic_range(*self.get_view_edges())
        if self.zoom_slider is not None and hasattr(self.zoom_slider, "singleStep"):
            self.zoom_slider.singleStep = 0.001 * (max_ - min_)

    def get_region(self):
        if self.linear_region:
            return self.linear_region.getRegion()
        else:
            return None, None

    @abstractmethod
    def get_view_range(self):
        pass

    @abstractmethod
    def get_view_edges(self):
        pass

    @abstractmethod
    def set_view_range(self, min_, max_):
        pass

    @abstractmethod
    def set_view_edges(self, min_, max_):
        pass

    def clear_region(self):
        self.plot_item.removeItem(self.linear_region)
        self.linear_region = None
        self.region_min_limit = np.NINF
        self.region_max_limit = np.inf

    def _set_graphic_range(self, min_, max_):
        min_ = max(min_, self.zoom_min) if min_ else self.zoom_min
        max_ = min(max_, self.zoom_max) if max_ else self.zoom_max

        if min_ in [np.inf, np.NINF] or max_ in [np.inf, np.NINF]:
            return

        self.plot_item.setXRange(min_, max_, padding=0)

    def _on_region_changed(self):
        self.region_changed.emit()
        self.set_region(*self.get_region())


class DisplayNodeDataPlot(DataPlot):
    def __init__(self, parent=None, zoom_slider=None):
        super().__init__(parent, zoom_slider)

        self.color_node = None
        self.linear_gradient = None

        self.outline_pen = QtGui.QPen("#FFFFFF") if themeIsDark() else QtGui.QPen("#000000")
        self.outline_pen.setWidth(1)
        self.outline_pen.setCosmetic(True)
        self.outline_pen.setStyle(QtGui.Qt.SolidLine)
        self.outline_pen.setCapStyle(QtGui.Qt.SquareCap)

        if self.zoom_slider is None:
            self.zoom_slider = zoom_slider
            self.zoom_slider.thresholdValuesChanged.connect(self._set_graphic_range)

    def add_plot(self, data_x, data_y, color):
        super().add_plot(data_x, data_y, color)
        self.plot_item_list[-1].setPen(self.outline_pen)

    def update_color(self, colorNode):
        region = self.get_region()
        if self.color_node == colorNode or not colorNode or not all(region):
            return
        self.color_node = colorNode
        self.linear_gradient = QtGui.QLinearGradient(region[0], 0, region[1], 0)
        interval = 1 / (colorNode.GetNumberOfColors() - 1)
        for i in range(colorNode.GetNumberOfColors()):
            color = [0, 0, 0, 0]
            colorNode.GetColor(i, color)
            color = pg.mkColor([int(c * 255) for c in color])
            self.linear_gradient.setColorAt(i * interval, color)
        brush = QtGui.QBrush(self.linear_gradient)
        [plot_item.setBrush(brush) for plot_item in self.plot_item_list]

    def set_region(self, min_, max_):
        super().set_region(min_, max_)
        if self.linear_gradient == None:
            self.update_color(self.color_node)
        else:
            self.linear_gradient.setStart(min_, 0)
            self.linear_gradient.setFinalStop(max_, 0)
            brush = QtGui.QBrush(self.linear_gradient)
            [plot_item.setBrush(brush) for plot_item in self.plot_item_list]

    def get_view_range(self):
        return (
            self.zoom_slider.lowerThresholdBound,
            self.zoom_slider.upperThresholdBound,
        )

    def get_view_edges(self):
        return self.zoom_slider.lowerThreshold, self.zoom_slider.upperThreshold

    def set_view_range(self, min_, max_):
        self.zoom_slider.setThresholdBounds(min_, max_)

    def set_view_edges(self, min_, max_):
        self.zoom_slider.setThreshold(min_, max_)
        self._set_graphic_range(min_, max_)


class SegmentationModellingDataPlot(DataPlot):
    def __init__(self, parent=None, zoom_slider=None):
        super().__init__(parent, zoom_slider)

        if self.zoom_slider is None:
            self.zoom_slider = zoom_slider
            self.zoom_slider.valuesChanged.connect(self._set_graphic_range)

    def get_view_range(self):
        return self.zoom_slider.minimum, self.zoom_slider.maximum

    def get_view_edges(self):
        return self.zoom_slider.minimumValue, self.zoom_slider.maximumValue

    def set_view_range(self, min_, max_):
        self.zoom_slider.setRange(min_, max_)

    def set_view_edges(self, min_, max_):
        self.zoom_slider.setValues(min_, max_)
        self._set_graphic_range(min_, max_)
