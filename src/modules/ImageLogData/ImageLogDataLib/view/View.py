"""
View related classes.
"""

import warnings
from collections import namedtuple

import numpy as np
import pyqtgraph as pg
import qt
import slicer
from ltrace.slicer.graph_data import NodeGraphData, LINE_PLOT_TYPE, SCATTER_PLOT_TYPE
from pyqtgraph.Qt import QtGui, QtCore, QtWidgets
from typing import Union

# PyQtGraph message when in log mode
warnings.filterwarnings("ignore", message="invalid value encountered in multiply")


class ColorBarWidget(qt.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.currentWidth = 0
        self.setup()

    def setup(self):
        layout = qt.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.pixmapLabel = qt.QLabel()
        self.pixmapLabel.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Preferred)
        layout.addWidget(self.pixmapLabel, 0, 0, 1, 3)

        self.minLabel = OutlinedLabel(" 0")
        self.minLabel.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.maxLabel = OutlinedLabel("100 ")
        self.maxLabel.setStyleSheet("font-size: 16px; font-weight: bold;")

        layout.addWidget(self.minLabel, 0, 0, qt.Qt.AlignVCenter)
        layout.addWidget(self.maxLabel, 0, 2, qt.Qt.AlignRight)

    def setColorTableNode(self, colorTableNode):
        self.pixmap = self.getColorPixmap(colorTableNode)
        self.pixmapLabel.setPixmap(self.pixmap.scaled(self.currentWidth, 20))

    def getColorPixmap(self, colorTableNode):
        colorTableComboBox = slicer.qMRMLColorTableComboBox()
        colorTableComboBox.setMRMLScene(slicer.mrmlScene)
        ctkTreeComboBox = colorTableComboBox.children()[-1]
        index = ctkTreeComboBox.findText(colorTableNode.GetName())
        icon = ctkTreeComboBox.itemIcon(index)
        return icon.pixmap(500, 50).scaled(100, 20)

    def updateWidth(self, width):
        self.currentWidth = width
        self.pixmapLabel.setPixmap(self.pixmap.scaled(width, 20))

    def updateInformation(self, window, level):
        self.minLabel.setText(" " + str(int(np.around(level - window / 2))))
        self.maxLabel.setText(str(int(np.around(level + window / 2))) + " ")


class OutlinedLabel(qt.QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def paintEvent(self, event):
        qp = qt.QPainter(self)
        qp.setRenderHint(qt.QPainter.Antialiasing)
        path = qt.QPainterPath()
        point = event.rect().bottomLeft()
        point.setY(point.y() - 3)
        path.addText(qt.QPointF(point), self.font, self.text)
        qp.setPen(qt.QPen(qt.Qt.black, 1))
        qp.setBrush(qt.Qt.white)
        qp.drawPath(path)


class CustomResizeWidget(qt.QWidget):
    def __init__(self, callback):
        qt.QWidget.__init__(self)
        self.callback = callback

    def resizeEvent(self, event):
        qt.QWidget.resizeEvent(self, event)
        self.callback(self.width)


class CustomAxisItem(pg.AxisItem):
    def __init__(self, callback):
        self.callback = callback
        super().__init__("left")

    def resizeEvent(self, evt=None):
        self.emit(pg.QtCore.SIGNAL("resize()"))
        self.callback()


PlotInformation = namedtuple("PlotInformation", ["graph_data", "x_parameter", "y_parameter"])
PLOT_UPDATE_TIMER_INTERVAL_MS = 50
PLOT_MINIMUM_HEIGHT = 200


class CurvePlot(QtWidgets.QWidget):
    signal_plot_removed = QtCore.Signal()
    signal_y_range_changed = QtCore.Signal(object, object)
    signal_x_range_changed = QtCore.Signal(object, object)
    signal_range_changed_manually = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__plots = list()
        self.__x_min_value_range = 0
        self.__y_min_value_range = 0
        self.__x_max_value_range = 0
        self.__y_max_value_range = 0
        self.__create_plot_update_timer()
        self.__setup_widget()

    def __del__(self):
        if self.plot_update_timer.isActive():
            self.plot_update_timer.stop()

        for plot_info in self.__plots:
            graph_data = plot_info.graph_data
            graph_data.signalStyleChanged.disconnect()
            graph_data.signalVisibleChanged.disconnect()
            graph_data.signalModified.disconnect()
            graph_data.signalRemoved.disconnect()

        del self.__plots

    def _build_plot_generator(self, plot_type: str = LINE_PLOT_TYPE):
        function = lambda: None
        if plot_type == LINE_PLOT_TYPE:
            function = self._create_curve_plot
        elif plot_type == SCATTER_PLOT_TYPE:
            function = self._create_scatter_plot

        return function

    def __setup_widget(self):
        layout = QtGui.QVBoxLayout()

        # Plot widgets
        self._graphics_layout_widget = CustomGraphicLayoutWidget()
        self._graphics_layout_widget.setMinimumHeight(PLOT_MINIMUM_HEIGHT)
        self._plot_item = self._graphics_layout_widget.addCustomPlotItem(viewBox=CustomContextMenu())
        self.__configure_plot_item()
        layout.addWidget(self._graphics_layout_widget, 10)
        self.setLayout(layout)

    def logMode(self, activated):
        for plot_info in self.__plots:
            data = plot_info.graph_data.data
            for key, value in data.items():
                if list(data.df).index(key) > 0:  # Do not change the first column
                    if activated:
                        with np.errstate(divide="ignore"):
                            data.df[key] = np.log10(value)
                    else:
                        data.df[key] = 10**value
        self.update_plot()

    def add_data(
        self,
        data_node: slicer.vtkMRMLNode,
        x_parameter: Union[str, list[str]],
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
        graph_data.signalStyleChanged.connect(self.update_plot)
        graph_data.signalVisibleChanged.connect(self.update_plot)
        graph_data.signalModified.connect(self.update_plot)

        for parameter in x_parameter if type(x_parameter) is list else [x_parameter]:
            plot_info = PlotInformation(graph_data=graph_data, x_parameter=parameter, y_parameter=y_parameter)
            graph_data.signalRemoved.connect(lambda: self.remove_plot(plot_info))
            self.__plots.append(plot_info)
        self.update_plot()

        return plot_info

    def __clear_plot(self):
        """Handles plot clearing"""
        self._plot_item.clear()

    def __create_plot_update_timer(self):
        """Initialize timer object that process data to plot"""
        if hasattr(self, "plot_update_timer") and self.plot_update_timer is not None:
            self.plot_update_timer.deleteLater()
            self.plot_update_timer = None

        self.plot_update_timer = QtCore.QTimer()
        self.plot_update_timer.setSingleShot(True)
        self.plot_update_timer.timeout.connect(lambda: self.__handle_update_plot())
        self.plot_update_timer.setInterval(PLOT_UPDATE_TIMER_INTERVAL_MS)

    def update_plot(self):
        """Handler update plot timer start."""
        if self.plot_update_timer.isActive():
            self.plot_update_timer.stop()

        self.plot_update_timer.start()

    def reset_range(self):
        self.__y_min_value_range = None
        self.__y_max_value_range = None
        self.__x_min_value_range = None
        self.__x_max_value_range = None
        self._plot_item.getViewBox().enableAutoRange()

    def remove_plot(self, plot_info: PlotInformation):
        """Remove data and objects related to the GraphData object."""
        if not plot_info in self.__plots:
            return

        self.__plots.remove(plot_info)
        del plot_info
        self.update_plot()

        try:
            self.signal_plot_removed.emit()
        except RuntimeError:
            pass

    def __handle_update_plot(self):
        try:
            """Handles plot updates"""
            self.__clear_plot()

            y_min = None
            y_max = None
            x_max = None
            x_min = None

            for plot_info in self.__plots:
                graph_data = plot_info.graph_data
                if graph_data.visible is False:
                    continue

                xAxisParameter = plot_info.x_parameter
                yAxisParameter = plot_info.y_parameter

                x_data = graph_data.data.get(xAxisParameter, None)
                y_data = graph_data.data.get(yAxisParameter, None)

                if x_data is None or y_data is None:
                    continue

                color = QtGui.QColor(graph_data.style.color)
                pen = pg.mkPen(color, width=1)
                brush = pg.mkBrush(color)

                plot_handler = self._build_plot_generator(graph_data.style.plot_type)
                plot = plot_handler(
                    x=x_data,
                    y=y_data,
                    pxMode=True,
                    symbol=graph_data.style.symbol,
                    size=graph_data.style.size,
                    pen=pen,
                    brush=brush,
                )

                self._plot_item.addItem(plot)

                y_min = self.__update_min_limit(y_min, y_data)
                y_max = self.__update_max_limit(y_max, y_data)
                x_min = self.__update_min_limit(x_min, x_data)
                x_max = self.__update_max_limit(x_max, x_data)

                self._plot_item.invertY()

            self._plot_item.getViewBox().enableAutoRange()

            x_max = self.__x_max_value_range or x_max
            x_min = self.__x_min_value_range or x_min
            y_max = self.__y_max_value_range or y_max
            y_min = self.__y_min_value_range or y_min

        except RuntimeError:
            # If plot widget was aready removed (by closing the scene, por example), ignore
            pass

    def _create_scatter_plot(*args, **kwargs):
        x = kwargs.get("x")
        y = kwargs.get("y")
        pxMode = kwargs.get("pxMode")
        symbol = kwargs.get("symbol")
        size = kwargs.get("size")
        pen = kwargs.get("pen")
        brush = kwargs.get("brush")
        return pg.ScatterPlotItem(x=x, y=y, pxMode=pxMode, symbol=symbol, size=size, pen=pen, brush=brush)

    def _create_curve_plot(*args, **kwargs):
        x = np.array(kwargs.get("x"))
        y = np.array(kwargs.get("y"))
        pxMode = kwargs.get("pxMode")
        size = kwargs.get("size")
        pen = kwargs.get("pen")
        brush = kwargs.get("brush")
        return pg.PlotCurveItem(x=x, y=y, pxMode=pxMode, symbol=None, size=size, pen=pen, brush=brush)

    def __configure_plot_item(self):
        self.plot_controls_event_filter = PlotControlsEventFilter(self._plot_item)

        viewBox = self._plot_item.getViewBox()
        viewBox.installEventFilter(self.plot_controls_event_filter)

        self._plot_item.setMenuEnabled(True)
        self._plot_item.sigYRangeChanged.connect(self.signal_y_range_changed)
        self._plot_item.sigXRangeChanged.connect(self.signal_x_range_changed)
        viewBox.sigRangeChangedManually.connect(
            lambda _: self.signal_range_changed_manually.emit(viewBox.viewRange()[1])
        )

    def __has_valid_y_axis_range(self, y_min, y_max):
        """Check if axis range values are considered valid

        Returns:
            bool: True if ranges are valid. Otherwise, returns False.
        """
        return (
            self.__y_min_value_range is not None
            and self.__y_max_value_range is not None
            and not (y_max == self.__y_max_value_range and y_min == self.__y_min_value_range)
            and y_min < y_max
        )

    def __has_valid_x_axis_range(self, x_min, x_max):
        """Check if axis range values are considered valid

        Returns:
            bool: True if ranges are valid. Otherwise, returns False.
        """
        return (
            self.__x_min_value_range is not None
            and self.__x_max_value_range is not None
            and not (x_max == self.__x_max_value_range and x_min == self.__x_min_value_range)
            and x_min < x_max
        )

    def set_y_range(self, y_min, y_max):
        if not self.__has_valid_y_axis_range(y_min=y_min, y_max=y_max):
            return
        self.__y_min_value_range = y_min
        self.__y_max_value_range = y_max
        self._plot_item.getViewBox().disableAutoRange(axis="y")
        self._plot_item.getViewBox().setRange(yRange=(y_min, y_max), padding=0)

    def set_x_range(self, x_min, x_max):
        if not self.__has_valid_x_axis_range(x_min=x_min, x_max=x_max):
            return
        self.__x_min_value_range = x_min
        self.__x_max_value_range = x_max
        self._plot_item.getViewBox().disableAutoRange(axis="x")
        self._plot_item.getViewBox().setRange(xRange=(x_min, x_max))

    def setTranslationSpeed(self, translationSpeed):
        self.plot_controls_event_filter.setTranslationSpeed(translationSpeed)

    def setScalingSpeed(self, scalingSpeed):
        self.plot_controls_event_filter.setScalingSpeed(scalingSpeed)

    def set_background(self, color):
        self._graphics_layout_widget.setBackground(color)

    def get_data_range(self):
        y_min = None
        y_max = None
        x_max = None
        x_min = None

        for plot_info in self.__plots:
            graph_data = plot_info.graph_data

            xAxisParameter = plot_info.x_parameter
            yAxisParameter = plot_info.y_parameter

            x_data = graph_data.data.get(xAxisParameter, None)
            y_data = graph_data.data.get(yAxisParameter, None)

            if x_data is None or y_data is None:
                continue

            y_min = self.__update_min_limit(y_min, y_data)
            y_max = self.__update_max_limit(y_max, y_data)
            x_min = self.__update_min_limit(x_min, x_data)
            x_max = self.__update_max_limit(x_max, x_data)

        return ((x_min, x_max), (y_min, y_max))

    @staticmethod
    def __update_max_limit(value, array):
        if value is None:
            value = np.nanmax(array)
        else:
            max_value_array = np.nanmax(array)
            value = max(value, max_value_array)

        return value

    @staticmethod
    def __update_min_limit(value, array):
        if value is None:
            value = np.nanmin(array)
        else:
            min_value_array = np.nanmin(array)
            value = min(value, min_value_array)

        return value


class PlotControlsEventFilter(QtCore.QObject):
    def __init__(self, plot_item):
        super().__init__()

        self.__plot_item = plot_item

        self.translationSpeed = 3
        self.scalingSpeed = 3

    def setTranslationSpeed(self, translationSpeed):
        self.translationSpeed = translationSpeed

    def setScalingSpeed(self, scalingSpeed):
        self.scalingSpeed = scalingSpeed

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.GraphicsSceneWheel:
            modifiers = QtWidgets.QApplication.keyboardModifiers()
            if modifiers == QtCore.Qt.ControlModifier:
                # Wheel + Ctrl does the scaling
                mask = (0, 1)

                # Scaling speed formula
                s = (1.00005 + (self.scalingSpeed**1.4) / 1000) ** (
                    event.delta() * self.__plot_item.getViewBox().state["wheelScaleFactor"]
                )

                s = [(None if m == 0 else s) for m in mask]
                self.__plot_item.getViewBox()._resetTarget()
                self.__plot_item.getViewBox().scaleBy(s)
                self.__plot_item.getViewBox().sigRangeChangedManually.emit(mask)
                return True
            else:
                # Wheel does the vertical translation
                pos = event.scenePos()

                # Translation speed formula
                s = (1.00005 + (self.translationSpeed**3) / 2000) ** (
                    event.delta() * self.__plot_item.getViewBox().state["wheelScaleFactor"]
                )

                new_pos = pos * s  # Estimate a new position based on wheel's s value
                dif = new_pos - pos
                mask = (0, 1)  # Define which axis should translate (x, y)
                dif_mask = pg.Point(dif.x() * mask[0], dif.y() * mask[1])
                tr = self.__plot_item.getViewBox().childGroup.transform()
                tr = pg.functions.invertQTransform(tr)
                tr = tr.map(dif_mask) - tr.map(pg.Point(0, 0))
                x = tr.x() if mask[0] == 1 else None
                y = tr.y() if mask[1] == 1 else None
                self.__plot_item.getViewBox()._resetTarget()
                self.__plot_item.getViewBox().translateBy(x=x, y=y)
                self.__plot_item.getViewBox().sigRangeChangedManually.emit(mask)
                return True
        return super().eventFilter(obj, event)


class CustomContextMenu(pg.ViewBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.menu = pg.graphicsItems.ViewBox.ViewBoxMenu.ViewBoxMenu(self)
        self.menuUpdate = True

    def getMenu(self, event=None):
        """Modify the menu. Called by the pyqtgraph.ViewBox raiseContextMenu()
            routine.
        Note: Overwriting the ViewBox.py getMenu() function.
        """

        if self.menuUpdate is True:
            # Modify contents of the original ViewBoxMenu

            # for action in self.menu.actions():
            #     # Modify the original Mouse Mode
            #     if "Mouse Mode" in action.text():
            #         # Change action labels
            #         for mouseAction in self.menu.leftMenu.actions():
            #             if "3 button" in mouseAction.text():
            #                 mouseAction.setText("CustomLabel1")
            #             elif "1 button" in mouseAction.text():
            #                 mouseAction.setText("CustomLabel2")

            # Add custom contents to menu
            self.addContentsToMenu()

            # Remove contents of the menu
            self.removeContentsOfMenu()

            # Set menu update to false
            self.menuUpdate = False

        return self.menu

    def addContentsToMenu(self):
        """Add custom actions to the menu."""
        # Reset X view feature
        self.actionViewX = pg.QtGui.QAction("View X", self.menu)

        # Get an action reference to add the new feature before it
        refAction = None
        for action in self.menu.actions():
            if "X Axis" in action.text():
                refAction = action

        # Add to main menu
        self.menu.insertAction(refAction, self.actionViewX)

        # Connect
        self.actionViewX.triggered.connect(self.autoRangeX)

    def autoRangeX(self):
        bounds = self.childrenBoundingRect()
        xMin, yMin, xMax, yMax = bounds.getCoords()
        self.setXRange(xMin, xMax)

    def removeContentsOfMenu(self):
        # Setting the X Axis -> Link Axis invisible
        self.menu.ctrl[0].label.setVisible(False)
        self.menu.ctrl[0].linkCombo.setVisible(False)

        # Setting the Y Axis -> Invert Axis checkbox invisible
        self.menu.ctrl[1].invertCheck.setVisible(False)

        # Setting the Y Axis -> Link Axis invisible
        self.menu.ctrl[1].label.setVisible(False)
        self.menu.ctrl[1].linkCombo.setVisible(False)


class CustomGraphicLayoutWidget(pg.GraphicsLayoutWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def addCustomPlotItem(self, row=None, col=None, rowspan=1, colspan=1, **kargs):
        """
        Create a CustomPlotItem and place it in the next available cell (or in the cell specified)
        All extra keyword arguments are passed to :func:`PlotItem.__init__ <pyqtgraph.PlotItem.__init__>`
        Returns the created item.
        """
        self.customPlotItem = CustomPlotItem(**kargs)
        self.addItem(self.customPlotItem, row, col, rowspan, colspan)
        return self.customPlotItem


class CustomPlotItem(pg.PlotItem):
    signalLogMode = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hideContents()

    def updateLogMode(self):
        x = self.ctrl.logXCheck.isChecked()
        y = self.ctrl.logYCheck.isChecked()

        self.getAxis("bottom").setLogMode(x)
        self.getAxis("top").setLogMode(x)
        self.getAxis("left").setLogMode(y)
        self.getAxis("right").setLogMode(y)
        self.enableAutoRange(axis="x")
        self.recomputeAverages()

        self.signalLogMode.emit(x)

    def hideContents(self):
        # Setting the Transforms-> Power Spectrum (FFT) invisible
        self.ctrl.fftCheck.setVisible(False)

        # Setting the Transforms-> Log Y invisible
        self.ctrl.logYCheck.setVisible(False)

        # Setting the Transforms-> dy/dx invisible
        self.ctrl.derivativeCheck.setVisible(False)

        # Setting the Transforms-> Y vs Y' invisible
        self.ctrl.phasemapCheck.setVisible(False)
