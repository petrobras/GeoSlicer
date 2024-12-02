import numpy as np
import qt
import pyqtgraph as pg
import PySide2
import shiboken2
import slicer

from .base_view_widget import BaseViewWidget
from collections import namedtuple
from ImageLogDataLib.view.View import PlotControlsEventFilter
from ltrace.slicer.helpers import export_las_from_histogram_in_depth_data, tryGetNode, hex2Rgb
from ltrace.slicer.graph_data import NodeGraphData, LINE_PLOT_TYPE, SCATTER_PLOT_TYPE
from ltrace.slicer.node_attributes import PlotScaleXAxisAttribute
from Plots.HistogramInDepthPlot.HistogramInDepthPlotWidgetModel import HistogramInDepthPlotWidgetModel
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

PlotInformation = namedtuple("PlotInformation", ["graph_data", "x_parameter", "y_parameter"])


class HistogramInDepthViewWidget(BaseViewWidget):
    def __init__(self, parent, view_data, primary_node):
        super().__init__(parent)
        self.view_data = view_data

        view_widget_layout = qt.QVBoxLayout(parent)
        view_widget_layout.setContentsMargins(0, 0, 0, 0)
        self.curve_plot = PlotWidget()
        self.curve_plot.setSamples(view_data.primaryTableNodeColumn)
        self.curve_plot._plotItem.setContentsMargins(-7, -7, -6, -6)
        self.curve_plot._plotItem.hideButtons()
        self.curve_plot._plotItem.hideAxis("left")
        self.curve_plot._plotItem.hideAxis("bottom")
        self.curve_plot._plotItem.showAxis("top")

        # Primary table node
        if view_data.primaryTableNodeColumn != "":
            self.curve_plot.appendData(
                primary_node,
                color=view_data.primaryTableNodePlotColor,
                scaleHistogram=view_data.primaryTableScaleHistogram,
            )

        # Secondary table node
        secondary_table_node = tryGetNode(view_data.secondaryTableNodeId)
        if secondary_table_node is not None and view_data.secondaryTableNodeColumn != "":
            if view_data.secondaryTableNodePlotType == LINE_PLOT_TYPE:
                secondary_plot_type = LINE_PLOT_TYPE
                secondary_plot_symbol = None
            else:
                secondary_plot_type = SCATTER_PLOT_TYPE
                secondary_plot_symbol = view_data.secondaryTableNodePlotType
            if view_data.secondaryTableNodeId != view_data.primaryNodeId:
                self.curve_plot.addSecondCurve(
                    data_node=secondary_table_node,
                    x_parameter=view_data.secondaryTableNodeColumn,
                    y_parameter="DEPTH",
                    plot_type=secondary_plot_type,
                    color=view_data.secondaryTableNodePlotColor,
                    symbol=secondary_plot_symbol,
                )

        self.pyside_qvbox_layout = shiboken2.wrapInstance(hash(view_widget_layout), PySide2.QtWidgets.QVBoxLayout)
        self.pyside_qvbox_layout.addWidget(self.curve_plot)

    def clear(self):
        if self.curve_plot is not None:
            self.curve_plot.clear()
            del self.curve_plot

        for child in self.children():
            del child

        del self.pyside_qvbox_layout

    def getPlot(self):
        return self.curve_plot

    def set_range(self, current_range):
        min_depth = current_range[1] / 1000
        max_depth = current_range[0] / 1000
        if self.curve_plot is not None:
            self.curve_plot.set_y_range(min_depth, max_depth)

    def getGraphX(self, view_x, width):
        range = self.curve_plot._plotItem.viewRange()
        hDif = range[0][1] - range[0][0]
        if hDif == 0:
            xScale = 1
            xOffset = 0
        else:
            xScale = width / hDif
            xOffset = range[0][0] * xScale

        xDepth = (view_x + xOffset) / xScale
        if self.curve_plot._getPlotScale() == PlotScaleXAxisAttribute.LINEAR_SCALE.value:
            return xDepth
        else:
            return 10**xDepth

    def getBounds(self):
        bounds = self.curve_plot.getDataRange()
        y_min, y_max = bounds
        y_min = y_min if y_min is not None else 0
        y_max = y_max if y_max is not None else 0
        bounds = (-1000 * y_max, -1000 * y_min)
        return bounds

    def getValue(self, x, y):
        return self.curve_plot.getValue(x, y)


class PlotWidget(QtWidgets.QWidget):
    TYPE = "Histograms in depth"

    signal_y_range_changed = QtCore.Signal(object, object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.__model = HistogramInDepthPlotWidgetModel(self)
        self.__curveIndexer = CurveIndexer()
        self.__color = "#000000"
        self.__plots = list()
        self.__graphicsLayoutWidget = None

        self.setupUi()

        self.destroyed.connect(self.__onDestroyed)

    def __onDestroyed(self):
        self.clear()
        del self.__model
        self.__model = None

    def clear(self):
        if hasattr(self.__model, "clear"):
            self.__model.clear()

        if self.__graphicsLayoutWidget is not None:
            self.__graphicsLayoutWidget.clear()

        del self.__curveIndexer

    def setupUi(self):
        """Initialize widgets"""
        layout = QtGui.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.__graphicsLayoutWidget = pg.GraphicsLayoutWidget()
        self._plotItem = self.__graphicsLayoutWidget.addPlot(row=0, col=0, rowspan=5, colspan=5)
        self.viewmain = self._plotItem.getViewBox()
        self.secondview = pg.ViewBox()

        self.plot_controls_event_filter = PlotControlsEventFilter(self._plotItem)
        viewBox = self._plotItem.getViewBox()
        viewBox.installEventFilter(self.plot_controls_event_filter)
        layout.addWidget(self.__graphicsLayoutWidget)
        self.setLayout(layout)

        # Create context menu's custom options
        menu = viewBox.menu
        # Export to las Action
        self.export_action = QtGui.QAction("Export to LAS file")
        self.export_action.triggered.connect(self.__on_export_to_las_clicked)
        menu.addAction(self.export_action)

        self._plotItem.sigYRangeChanged.connect(self.__onYRangeChanged)

        # Hide Contents
        self._plotItem.ctrl.fftCheck.setVisible(False)
        self._plotItem.ctrl.logYCheck.setVisible(False)
        self._plotItem.ctrl.derivativeCheck.setVisible(False)
        self._plotItem.ctrl.phasemapCheck.setVisible(False)

    def appendData(self, dataNode, color, scaleHistogram):
        """Wrapper method for inserting data into the widget"""
        self.__color = color
        self.__scaleHistogram = scaleHistogram
        return self.__model.appendData(dataNode)

    def setSamples(self, samples):
        if samples != "":
            self.__samples = int(samples)
        else:
            self.__samples = 1

    def addSecondCurve(
        self,
        data_node: slicer.vtkMRMLNode,
        x_parameter: str,
        y_parameter: str,
        plot_type=None,
        color=None,
        symbol=None,
        size=None,
    ):
        """Store and parse node's data. Each data will be available at the table's widget as well.

        Args:
            data_node (slicer.vtkMRMLNode): the slicer's node object.
            x_parameter (str): the parameter's name within data node, related to the X axis data
            y_parameter (str): the parameter's name within data node, related to the Y axis data
            color (tuple (r, g, b), optional): The plot's desired RGB color. Defaults to None.
            symbol (str, optional): The plot's symbol. Defaults to None.
            size (integer, optional): The plot's size. Defaults to None.
        """
        if x_parameter is None or x_parameter == "" or y_parameter is None or y_parameter == "":
            raise RuntimeError("Attempt to add data to plot failed due missing axis parameter label")

        graph_data = NodeGraphData(self, dataNode=data_node, plot_type=plot_type, color=color, symbol=symbol, size=size)
        plot_info = PlotInformation(graph_data=graph_data, x_parameter=x_parameter, y_parameter=y_parameter)

        self.__plots.append(plot_info)
        self.updateSecondPlot()

    def updatePlot(self):
        self._plotItem.clear()
        if self.__curveIndexer is not None:
            del self.__curveIndexer

        self.__curveIndexer = CurveIndexer()

        graph_data_list = self.__model.graphDataList
        xMin = xMax = None
        yMin = yMax = None
        for graph_data in graph_data_list:
            # Set pen color and scales
            colorRgb = hex2Rgb(self.__color, normalize=False)
            brush = pg.mkBrush(colorRgb)
            pen = pg.mkPen(colorRgb, width=0.01)
            maxDepth, minDepth = self.getDataRange()

            scale_depth = self.get_scale(graph_data)
            scale_plot = self.__scaleHistogram
            # Get x values
            x = self._getXArray(graph_data)
            if x.size == 0:
                continue

            # Get y values
            if graph_data.data.get("X", None) is not None:
                y_all = np.zeros((graph_data.data.df.shape[1] - 1, graph_data.data.df.shape[0]))
                depth_hist = np.zeros(graph_data.data.df.shape[1] - 1)
                i = 0
                for pore, pore_data in graph_data.data.items():
                    if pore == "X":
                        continue
                    y_all[i, :] = pore_data
                    depth_hist[i] = float(pore) * scale_depth
                    i += 1
            else:
                y_all = np.transpose(graph_data.data.df.values)
                depth_hist = np.array(graph_data.data.df.columns) * scale_depth
                nan_rows = np.any(np.isnan(y_all), axis=1)
                y_all = y_all[~nan_rows]
                depth_hist = depth_hist[~nan_rows]
                ymax = np.max(y_all)
                diff = np.max(np.diff(depth_hist))
                y_all = (y_all / ymax) * diff * 5

            # Apply sampling and plot
            y_scaled = -scale_plot * y_all + np.transpose(depth_hist)[:, np.newaxis]
            y_all = y_all[:: self.__samples, :]
            y_scaled = y_scaled[:: self.__samples, :]
            depth_hist = depth_hist[:: self.__samples]
            self._plotItem.plot(x, y_scaled, fillLevel=depth_hist, brush=brush, pen=pen)
            for i in range(y_scaled.shape[0]):
                self.__curveIndexer.addCurve(x, y_scaled[i, :], y_all[i, :])

            # Apply plot customization
            if minDepth is None or maxDepth is None or x is None:
                continue

            if xMin is None or xMax is None:
                xMin = x[0]
                xMax = x[-1]
            else:
                xMin = min(xMin, x[0])
                xMax = max(xMax, x[-1])

            if yMin is None or yMax is None:
                yMin = minDepth
                yMax = minDepth
            else:
                yMin = min(yMin, minDepth)
                yMax = max(yMax, maxDepth)

        # Apply Log Scale
        if self._getPlotScale() == PlotScaleXAxisAttribute.LOG_SCALE.value:
            self._plotItem.setLogMode(x=True, y=False)

        if xMin is not None and xMax is not None:
            if self._getPlotScale() == PlotScaleXAxisAttribute.LOG_SCALE.value:
                xMin = np.log10(xMin) if xMin > 0 else 0
                xMax = np.log10(xMax) if xMax > 0 else 0

            self._plotItem.setXRange(xMin, xMax)

        if yMin is not None and yMax is not None:
            self._plotItem.setYRange(yMin, yMax)

        # Apply plot customization
        self._plotItem.showGrid(x=True, y=True)
        self._plotItem.showAxis("bottom", True)
        self._plotItem.invertY(True)

    def updateSecondPlot(self):

        for plot_info in self.__plots:
            graph_data = plot_info.graph_data

            xAxisParameter = plot_info.x_parameter
            yAxisParameter = plot_info.y_parameter

            x_data = graph_data.data.get(xAxisParameter, None)
            y_data = graph_data.data.get(yAxisParameter, None)
            if self._getPlotScale() == PlotScaleXAxisAttribute.LOG_SCALE.value:
                x_data = np.log10(x_data)

            color = QtGui.QColor(graph_data.style.color)
            pen = pg.mkPen(color, width=1)
            brush = pg.mkBrush(color)

            plot_handler = self.build_plot_generator(graph_data.style.plot_type)

            plot = plot_handler(
                x=x_data,
                y=y_data,
                pxMode=True,
                symbol=graph_data.style.symbol,
                size=graph_data.style.size,
                pen=pen,
                brush=brush,
            )

            self._plotItem.addItem(plot)

    def getValue(self, x, y):
        return self.__curveIndexer.getValue(x, y)

    def __on_export_to_las_clicked(self):
        filter = "LAS (*.las)"
        path = qt.QFileDialog.getSaveFileName(None, "Save file", "", filter)
        if len(path) == 0:
            return

        table_node = self.__model.graphDataList[0].node
        if table_node is None:
            return

        df = slicer.util.dataframeFromTable(table_node)
        status = export_las_from_histogram_in_depth_data(df=df, file_path=path)

        message = ""
        if status:
            message = "File was exported successfully!"
        else:
            message = "Unable to export the LAS file. Please check the logs for more information."

        qt.QMessageBox.information(None, "Export", message)

    def set_y_range(self, y_min, y_max):
        if self._plotItem is None or self._plotItem.getViewBox() is None:
            return
        self._plotItem.getViewBox().disableAutoRange(axis="y")
        self._plotItem.getViewBox().setRange(yRange=(y_min, y_max), padding=0)

    def getDataRange(self):
        max_depth = None
        min_depth = None

        for graph_data in self.__model.graphDataList:
            for pore in graph_data.data.item():
                if pore == "X":
                    continue
                pore_value = float(pore)
                max_depth = max(pore_value, max_depth) if max_depth is not None else pore_value
                min_depth = min(pore_value, min_depth) if min_depth is not None else pore_value
            if graph_data.data.get("X", None) is None:
                min_depth = min_depth / 1000 if min_depth is not None else None
                max_depth = max_depth / 1000 if max_depth is not None else None
        return max_depth, min_depth

    def setTranslationSpeed(self, translationSpeed):
        self.plot_controls_event_filter.setTranslationSpeed(translationSpeed)

    def setScalingSpeed(self, scalingSpeed):
        self.plot_controls_event_filter.setScalingSpeed(scalingSpeed)

    def __onYRangeChanged(self, cls, tuple_range):
        min_depth = 1000 * tuple_range[0]
        max_depth = 1000 * tuple_range[1]
        self.signal_y_range_changed.emit(cls, (min_depth, max_depth))

    def _getPlotScale(self):
        return self.__model.plotScale

    def _getXArray(self, graph_data):
        """Obtain an array for the X-axis based on the graph data type.
        If the graph data contains the key 'X', the function returns an array
        corresponding to that key. Otherwise, it creates an array based on a logarithmic
        time scale. The logarithmic time scale is calculated based on the number of bins
        and times in the website https://github.com/ruben-charles/NMR_log_visualization/tree/main
        Args:
            GraphData: An object containing graph data.
        Returns:
            array: A NumPy array representing the X-axis.
        """
        if graph_data.data.get("X", None) is not None:
            x = np.array(graph_data.data["X"])
        else:
            tmin = 0.3
            tmax = 3000
            trange = np.log10(tmax) - np.log10(tmin)
            nbins = graph_data.data.__rows__()
            bins = np.arange(nbins)
            bin_step = trange / (len(bins) - 1)
            bins_log10time = (bins * bin_step) + np.log10(tmin)
            bins_time = 10**bins_log10time
            x = bins_time
        return x

    def get_scale(self, graph_data):
        scale = 1.0
        if graph_data.data.get("X", None) is None:
            scale = 0.001
        return scale

    def get_plot_item(self):
        return self._plotItem

    def build_plot_generator(self, plot_type: str = LINE_PLOT_TYPE):
        function = lambda: None
        if plot_type == LINE_PLOT_TYPE:
            function = self._create_curve_plot
        elif plot_type == SCATTER_PLOT_TYPE:
            function = self._create_scatter_plot

        return function

    def _create_scatter_plot(*args, **kwargs):
        x = kwargs.get("x")
        y = kwargs.get("y") / 1000
        pxMode = kwargs.get("pxMode")
        symbol = kwargs.get("symbol")
        size = kwargs.get("size")
        pen = kwargs.get("pen")
        brush = kwargs.get("brush")
        plot = pg.ScatterPlotItem(x=x, y=y, pxMode=pxMode, symbol=symbol, size=size, pen=pen, brush=brush)
        return plot

    def _create_curve_plot(*args, **kwargs):
        x = np.array(kwargs.get("x"))
        y = np.array(kwargs.get("y")) / 1000
        pxMode = kwargs.get("pxMode")
        size = kwargs.get("size")
        pen = kwargs.get("pen")
        brush = kwargs.get("brush")
        plot = pg.PlotCurveItem(x=x, y=y, pxMode=pxMode, symbol=None, size=size, pen=pen, brush=brush)
        return plot


class CurveIndexer:
    MIN_Y = 0
    MAX_Y = 1
    X = 2
    Y = 3
    PORE = 4

    def __init__(self):
        self.__curves = []

    def addCurve(self, xValues, yValues, pore_data):
        if xValues.size == 0 or yValues.size == 0:
            return

        curveDict = {
            self.MIN_Y: np.min(yValues),
            self.MAX_Y: np.max(yValues),
            self.X: xValues,
            self.Y: yValues,
            self.PORE: pore_data,
        }
        self.__curves.append(curveDict)

    def getValue(self, x, y):
        curves = self.__getCurvesInDepth(y)
        for curve in curves:
            value = self.__getValueInCurve(curve, x, y)
            if value is not None:
                return value
        return 0

    def __getCurvesInDepth(self, depth):
        curves = []
        for curve in reversed(self.__curves):
            if curve[self.MIN_Y] <= depth <= curve[self.MAX_Y]:
                curves.append(curve)
        return curves

    def __getValueInCurve(self, curve, x, y):
        nearest_value_index = np.argmin(np.abs(curve[self.X] - x))
        if curve[self.Y][nearest_value_index] <= y:
            return curve[self.PORE][nearest_value_index]
        else:
            return None
