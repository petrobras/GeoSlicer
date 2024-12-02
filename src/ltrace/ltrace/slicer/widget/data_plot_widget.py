import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtGui

from ltrace.algorithms.measurements import PORE_SIZE_CATEGORIES
from ltrace.slicer.widget.custom_gradient_legend import CustomGradientLegend
from ltrace.slicer.widget.customized_pyqtgraph.AngleAxisItem import AngleAxisItem
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget

PLOT_MINIMUM_HEIGHT = 480
PLOT_HISTOGRAM_SIZE = 100


class DataPlotWidget(pg.QtWidgets.QWidget):
    toggleLegendSignal = pg.QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.__legendItem = None
        self.__embeddedLegendVisibility = True
        self.__currentColorMap = None
        self.__input_data = {}
        self.__xHistogramPlots = list()
        self.__yHistogramPlots = list()

        self.__graphicsLayoutWidget = GraphicsLayoutWidget()

        self.__graphicsLayoutWidget.setMinimumHeight(PLOT_MINIMUM_HEIGHT)
        # pyqtgraph for python 3.6 is quite buggy. Forcing Y axis inversion to the legend to re-invert
        # the legend's labels
        self.__legendPlotItem = pg.ViewBox(invertY=False, lockAspect=True, enableMenu=False, enableMouse=False)
        self.__legendPlotItem.setContentsMargins(0, 0, 0, 0)
        self.__legendPlotItem.setBackgroundColor((0, 0, 0, 0))
        self.__xLegendLabelItem = pg.LabelItem(angle=0)
        self.__yLegendLabelItem = pg.LabelItem(angle=270)
        self.__zLegendLabelItem = pg.LabelItem(angle=270)
        self.__graphicsLayoutWidget.addItem(self.__xLegendLabelItem, row=3, col=2, colspan=2)
        self.__graphicsLayoutWidget.addItem(self.__yLegendLabelItem, row=1, col=1, rowspan=2)
        self.__graphicsLayoutWidget.addItem(self.__zLegendLabelItem, row=1, col=4, rowspan=2)
        self.__graphicsLayoutWidget.addItem(self.__legendPlotItem, row=1, col=5, rowspan=2)

        axisBottom = AngleAxisItem(angle=45, orientation="bottom")
        axisItems = {"bottom": axisBottom}

        self.__plotItem = self.__graphicsLayoutWidget.addPlot(row=1, col=2, colspan=2, rowspan=2, axisItems=axisItems)

        legendBorderPen = pg.mkPen(QtGui.QColor(0, 0, 0, 255), width=1)
        legendBackgroundBrush = pg.mkBrush(QtGui.QColor(180, 180, 180, 100))
        self.__embeddedLegendItem = self.__plotItem.addLegend(brush=legendBackgroundBrush, pen=legendBorderPen)
        self.__embeddedLegendItem.anchor(itemPos=(1, 0), parentPos=(1, 0), offset=(-10, 10))
        self.__embeddedLegendItem.setVisible(self.__embeddedLegendVisibility)

        self.__plotItem.showGrid(x=True, y=True, alpha=0.8)
        self.__yHistogramPlotItem = self.__graphicsLayoutWidget.addPlot(row=1, col=0, rowspan=2)
        self.__xHistogramPlotItem = self.__graphicsLayoutWidget.addPlot(row=0, col=2, colspan=2)

        self.__xHistogramPlotItem.setXLink(self.__plotItem)
        self.__yHistogramPlotItem.setYLink(self.__plotItem)

        self.__configureHistogramPlots()

        # Plot context menu
        self.__overwritePlotMenu()

        self.__themeNames = ["Light", "Dark"]

    @property
    def widget(self):
        return self.__graphicsLayoutWidget

    @property
    def plotItem(self):
        return self.__plotItem

    @property
    def themes(self):
        return self.__themeNames

    @property
    def embeddedLegendVisibility(self):
        return self.__embeddedLegendVisibility

    @embeddedLegendVisibility.setter
    def embeddedLegendVisibility(self, isVisible):
        if self.__embeddedLegendVisibility == isVisible:
            return

        self.__embeddedLegendVisibility = isVisible
        self.__embeddedLegendItem.setVisible(self.__embeddedLegendVisibility)

    def clear_histogram_x(self):
        self.__xHistogramPlotItem.clear()

    def clear_histogram_y(self):
        self.__yHistogramPlotItem.clear()

    def set_colormap(self, color_map):
        self.__currentColorMap = color_map

    def get_plotted_data(self, name):
        return self.__input_data[name]

    def set_log_mode(self, x, y):
        self.__plotItem.setLogMode(x=x, y=y)

    def add2dPlot(self, graphData, xData, yData, xAxisParameter, yAxisParameter):
        nan_x_data_index = np.isnan(xData)
        nan_y_data_index = np.isnan(yData)
        nan_index = np.array([all(i) for i in zip(nan_x_data_index, nan_y_data_index)])
        xData = xData[~nan_index]
        yData = yData[~nan_index]

        color = QtGui.QColor(graphData.style.color[0], graphData.style.color[1], graphData.style.color[2])
        pen = pg.mkPen(color, width=1)
        brush = pg.mkBrush(color)

        spi = pg.ScatterPlotItem(
            x=xData,
            y=yData,
            pxMode=True,
            symbol=graphData.style.symbol,
            size=graphData.style.size,
            pen=pen,
            brush=brush,
            name=graphData.name,
        )
        self.__plotItem.addItem(spi)

        if graphData.style.line_style is not None:
            line = pg.PlotCurveItem(
                x=xData.to_numpy(),
                y=yData.to_numpy(),
                pen=pg.mkPen(color, width=graphData.style.line_size, style=graphData.style.line_style),
            )
            self.__plotItem.addItem(line)

        self.__xLegendLabelItem.setText(xAxisParameter)
        self.__yLegendLabelItem.setText(yAxisParameter)

        self.__input_data[graphData.name] = {"x": xData, "y": yData, "color": graphData.style.color}

    def add3dPlot(self, graphData, xData, yData, zData, xAxisParameter, yAxisParameter, zAxisParameter, zMin, zMax):
        nan_x_data_index = np.isnan(xData)
        nan_y_data_index = np.isnan(yData)
        nan_z_data_index = np.isnan(zData)
        nan_index = np.array([all(i) for i in zip(nan_x_data_index, nan_y_data_index, nan_z_data_index)])
        xData = xData[~nan_index]
        yData = yData[~nan_index]
        zData = zData[~nan_index]

        if graphData.hasNames(zAxisParameter):
            if "pore_size_class" in zAxisParameter:
                zMin = max(zMin, 0)
                zMax = min(zMax, len(PORE_SIZE_CATEGORIES) - 1)

                labelmap = {lb: i for i, lb in enumerate(PORE_SIZE_CATEGORIES) if zMin <= i <= zMax}
            else:
                # TODO return a labelmap
                namedLabels = graphData.getLabelNames(zAxisParameter).unique()
                labelmap = {label: i for i, label in enumerate(namedLabels) if zMin <= i <= zMax}

            self.__legendItem, gradient = self.__createDiscreteGradientLegend(zData, zMin, zMax, labelmap)

        else:
            self.__legendItem, gradient = self.__createGradientLegend(zData, zMin, zMax)

        colorAlpha = QtGui.QColor(graphData.style.color[0], graphData.style.color[1], graphData.style.color[2], 127)
        pen = pg.mkPen(colorAlpha, width=1)
        brush = gradient

        spi = pg.ScatterPlotItem(
            x=xData,
            y=yData,
            pxMode=True,
            symbol=graphData.style.symbol,
            size=graphData.style.size,
            brush=brush,
            pen=pen,
            name=graphData.name,
        )

        self.__plotItem.addItem(spi)
        self.__xLegendLabelItem.setText(xAxisParameter)
        self.__yLegendLabelItem.setText(yAxisParameter)

        def namedTicks(axiskey, axis):
            ax = self.__plotItem.getAxis(axis)
            if graphData.hasNames(axiskey):
                if "pore_size_class" in axiskey:
                    ticks = [(i, lb) for i, lb in enumerate(PORE_SIZE_CATEGORIES)]
                else:
                    ticks = sorted(set(zip(xData, graphData.getLabelNames(axiskey))), key=lambda it: it[0])
                ax.setTicks([ticks])
                if axis == "bottom":
                    ax.setTicksAngle(45)
            else:
                ax.setTicks(None)
                if axis == "bottom":
                    ax.setTicksAngle(0)

        namedTicks(xAxisParameter, "bottom")
        namedTicks(yAxisParameter, "left")

        self.__input_data[graphData.name] = {"x": xData, "y": yData, "color": graphData.style.color}

    def add_histogram_plot_x(self, graphData, xHistogram, yHistogram):
        color = QtGui.QColor(graphData.style.color[0], graphData.style.color[1], graphData.style.color[2], 80)
        brush = QtGui.QBrush(color)
        curve = pg.PlotCurveItem(xHistogram, yHistogram, stepMode=True, fillLevel=0, brush=brush)
        self.__xHistogramPlots.append(curve)
        self.__xHistogramPlotItem.addItem(item=curve)

    def add_histogram_plot_y(self, graphData, xHistogram, yHistogram):
        color = QtGui.QColor(graphData.style.color[0], graphData.style.color[1], graphData.style.color[2], 80)
        brush = QtGui.QBrush(color)
        curve = pg.PlotCurveItem(xHistogram, yHistogram, stepMode=True, fillLevel=0, brush=brush)
        self.__yHistogramPlots.append(curve)
        curve.rotate(90)
        self.__yHistogramPlotItem.addItem(item=curve)

    def add_curve_plot(self, curve_data):
        new_curve = pg.PlotCurveItem(
            curve_data.x,
            curve_data.y,
            stepMode=False,
            pen=pg.mkPen(curve_data.style.color, width=curve_data.style.line_size, style=curve_data.style.line_style),
            name=curve_data.name,
        )
        self.__plotItem.addItem(new_curve)

    def update_legend_item(self, zAxisParameter):
        if self.__legendItem:
            self.__legendPlotItem.addItem(self.__legendItem)
            self.__zLegendLabelItem.setText(zAxisParameter)

    def __configureHistogramPlots(self):
        self.__yHistogramPlotItem.hideAxis("left")
        self.__yHistogramPlotItem.hideAxis("bottom")
        self.__yHistogramPlotItem.hideButtons()
        self.__yHistogramPlotItem.setFixedWidth(PLOT_HISTOGRAM_SIZE)

        self.__xHistogramPlotItem.hideAxis("bottom")
        self.__xHistogramPlotItem.hideAxis("left")
        self.__xHistogramPlotItem.hideButtons()
        self.__xHistogramPlotItem.setFixedHeight(PLOT_HISTOGRAM_SIZE)

    def _updatePlotsLayout(self, enable_histogram_x, enable_histogram_y, z_axes_parameter):
        availableHeight = self.__graphicsLayoutWidget.height()

        if enable_histogram_x is True and len(self.__xHistogramPlotItem.dataItems) > 0:
            self.__xHistogramPlotItem.setFixedHeight(PLOT_HISTOGRAM_SIZE)
            availableHeight -= PLOT_HISTOGRAM_SIZE
        else:
            self.__xHistogramPlotItem.setFixedHeight(0)

        if enable_histogram_y is True and len(self.__yHistogramPlotItem.dataItems) > 0:
            self.__yHistogramPlotItem.setFixedWidth(PLOT_HISTOGRAM_SIZE)
        else:
            self.__yHistogramPlotItem.setFixedWidth(0)

        availableHeight -= 40  # Bottom legend space

        self.__plotItem.setMaximumHeight(availableHeight)
        self.__legendPlotItem.setFixedHeight(availableHeight)
        self.__yLegendLabelItem.setFixedHeight(availableHeight)

        self.__xLegendLabelItem.setFixedHeight(20)
        self.__yLegendLabelItem.setFixedWidth(20)
        self.__zLegendLabelItem.setFixedHeight(availableHeight)
        for dataItem in self.__legendPlotItem.addedItems:
            if not issubclass(type(dataItem), pg.GradientLegend):
                continue

            dataItem.size = (dataItem.size[0], availableHeight * 0.80)
            dataItem.offset = (15, availableHeight * (1 - 0.95))
            dataItem.update()

        if len(self.__legendPlotItem.addedItems) > 0:
            if "pore_size_class" in z_axes_parameter:
                self.__legendPlotItem.setFixedWidth(160)
            else:
                self.__legendPlotItem.setFixedWidth(100)
            self.__zLegendLabelItem.setFixedWidth(20)
        else:
            self.__legendPlotItem.setFixedWidth(0)
            self.__zLegendLabelItem.setFixedWidth(0)

    def auto_range(self):
        if len(self.__input_data) == 0:
            self.__plotItem.autoRange()
            return

        min_x = np.nan
        max_x = np.nan
        min_y = np.nan
        max_y = np.nan

        for data in self.__input_data.values():
            min_x = np.nanmin([min_x, np.min(data["x"])])
            max_x = np.nanmax([max_x, np.max(data["x"])])
            min_y = np.nanmin([min_y, np.min(data["y"])])
            max_y = np.nanmax([max_y, np.max(data["y"])])

        self.__plotItem.setXRange(min_x, max_x)
        self.__plotItem.setYRange(min_y, max_y)

    def set_theme(self, selectedTheme):
        if selectedTheme not in self.__themeNames:
            selectedTheme = self.__themeNames[0]

        white = 255, 255, 255
        black = 0, 0, 0
        fg_alt_alpha = 200
        bg_alt_alpha = 80

        if selectedTheme == "Dark":
            fg_color = white
            bg_color = black
        elif selectedTheme == "Light":
            fg_color = black
            bg_color = white
        else:
            availableThemes = ", ".join([f"'{t}'" for t in self.__themeNames])
            raise NotImplementedError(f"Invalid selected theme! The available themes are: {availableThemes}.")

        fg_alt_color = (*fg_color, fg_alt_alpha)
        bg_alt_color = (*fg_color, bg_alt_alpha)

        # colorbar label
        self.__graphicsLayoutWidget.setBackground(bg_color)
        if self.__legendItem is not None:
            self.__legendItem.brush = QtGui.QBrush(QtGui.QColor(*bg_color, 0))  # inner background color
            self.__legendItem.textPen = QtGui.QPen(QtGui.QColor(*fg_alt_color))
            self.__legendItem.pen = QtGui.QPen(QtGui.QColor(*bg_color, 0))  ## background paining
            self.__legendItem.update()

        # axes
        for side in self.__plotItem.axes:  # 'left', 'bottom', ...
            ax = self.__plotItem.getAxis(side)
            ax.setPen(QtGui.QColor(*bg_alt_color))  # grid
            ax.setTextPen(QtGui.QPen(QtGui.QColor(*fg_alt_color)))  # labels

        # axes labels
        for labelItem in [self.__xLegendLabelItem, self.__yLegendLabelItem, self.__zLegendLabelItem]:
            labelItem.setText(text=labelItem.text, color=fg_color)

        # histogram
        histogramPlots = self.__yHistogramPlots + self.__xHistogramPlots
        for histogramPlot in histogramPlots:
            histogramPlot.setPen(QtGui.QColor(*fg_color), width=1)  # curve

    def clear_plot(self):
        """Handles plot clearing"""
        self.__removeLegendWidget()
        self.__plotItem.clear()
        self.__xHistogramPlotItem.clear()
        self.__yHistogramPlotItem.clear()
        self.__xLegendLabelItem.setText("")
        self.__yLegendLabelItem.setText("")
        self.__zLegendLabelItem.setText("")
        self.__input_data.clear()

    def __removeLegendWidget(self):
        """Handles legend widget removal."""
        self.__legendPlotItem.clear()
        self.__legendPlotItem.setFixedWidth(0)
        del self.__legendItem
        self.__legendItem = None

    def __overwritePlotMenu(self):
        menu = self.__plotItem.ctrlMenu

        # Remove actions
        actions_to_remove = []
        blackList = ["Transforms", "Downsample", "Average", "Alpha", "Points"]
        for action in menu.actions():
            if action.text() in blackList:
                actions_to_remove.append(action)

        for action in actions_to_remove:
            menu.removeAction(action)

        # Add new actions
        menu.addAction("Toggle legend", self.__toggleLegend)

    def __toggleLegend(self):
        self.embeddedLegendVisibility = not self.embeddedLegendVisibility
        self.toggleLegendSignal.emit()

    def __createGradientLegend(self, z, zMin, zMax):
        """Handles pg.GradientLegend and related objects creation based on the color map chosed."""
        zNormalized = (z - zMin) / (zMax - zMin)
        colorMap = pg.colormap.getFromMatplotlib(self.__currentColorMap)

        height = self.__graphicsLayoutWidget.height() - PLOT_HISTOGRAM_SIZE
        # offset_diff and formatting_template are so scientific notation only happens if there are no visible
        # differences between each label after being truncated to two decimal digits
        offset_diff = int(zMax * 100) - int(zMin * 100)
        formatting_template = "%0.2f" if offset_diff >= 3 else "%0.2e"
        labels = dict([(formatting_template % (v * (zMax - zMin) + zMin), v) for v in np.linspace(0, 1, 4)])

        gradientLegend = CustomGradientLegend(size=(20, height), offset=(15, 0))
        gradientLegend.setGradient(colorMap.getGradient())
        gradientLegend.setLabels(labels)

        gradient = colorMap.mapToQColor(zNormalized)

        return gradientLegend, gradient

    def __createDiscreteGradientLegend(self, z, zMin, zMax, labelmap: dict = None):
        nlabels = len(labelmap)
        zRange = zMax - zMin
        znorm = (z - zMin) / zRange

        colormap = pg.colormap.getFromMatplotlib(self.__currentColorMap)
        colors = colormap.getLookupTable(0.0, 1.0, nPts=nlabels)

        boundaries = np.array([(v - 0.0001, v) for v in range(0, nlabels + 1)]).ravel()[1:-1]
        boundaries /= nlabels
        coloridx = np.array([(v - 1, v) for v in range(0, nlabels + 1)]).ravel()[1:-1]
        colorbounds = colors[coloridx]

        discreteColormap = pg.ColorMap(boundaries, colorbounds)

        tick_labels = [k for k in labelmap.keys()]
        tick_pos = np.array([v for v in labelmap.values()]) + 0.5
        tick_pos /= np.max(tick_pos) + 0.5
        ticks = dict(zip(tick_labels, tick_pos))

        height = self.__graphicsLayoutWidget.height() - PLOT_HISTOGRAM_SIZE
        gradientLegend = pg.GradientLegend(size=(20, height), offset=(15, 0))
        gradientLegend.setColorMap(discreteColormap)
        gradientLegend.setLabels(ticks)

        gradient = discreteColormap.mapToQColor(znorm)

        return gradientLegend, gradient
