from ..BasePlotWidget import BasePlotWidget
from ltrace.slicer.graph_data import NodeGraphData

from pyqtgraph.Qt import QtGui, QtCore
import pyqtgraph as pg
import numpy as np
from ltrace.slicer.widget.custom_color_button import CustomColorButton
import os
from .WindroseWidgetModel import WindroseWidgetModel
from .WindrosePolygon import WindrosePolygonItem
import math
from collections import namedtuple

RESOURCES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Resources")
ICONS_DIR_PATH = os.path.join(RESOURCES_PATH, "Icons")
REMOVE_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "CancelIcon.png")
VISIBLE_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "eye.svg")
NOT_VISIBLE_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "eye-off.svg")
PLOT_UPDATE_TIMER_INTERVAL_MS = 250
AXIS_NONE_PARAMETER = ""


HistogramData = namedtuple("HistogramData", ["x", "y", "originalMinValue", "originalMaxValue"])


class WindroseWidget(BasePlotWidget):
    TYPE = "Rosette diagram"

    def __init__(self, plotLabel="", *args, **kwargs):
        super().__init__(plotType=self.TYPE, plotLabel=plotLabel, *args, **kwargs)
        self.__model = WindroseWidgetModel(self)
        self.__graphDataList = list()
        self.__plotDataArrays = dict()
        self.__createPlotUpdateTimer()
        self.__angleOffsetDegrees = -90

    def setupUi(self):
        """Initialize widgets"""
        layout = QtGui.QVBoxLayout()

        # Data table widget
        self.__tableWidget = QtGui.QTableWidget()
        self.__tableWidget.setColumnCount(2)
        self.__tableWidget.setRowCount(0)
        self.__tableWidget.verticalHeader().setHidden(True)
        self.__tableWidget.horizontalHeader().setResizeMode(0, QtGui.QHeaderView.Stretch)
        self.__tableWidget.horizontalHeader().setResizeMode(1, QtGui.QHeaderView.ResizeToContents)
        self.__tableWidget.setHorizontalHeaderLabels(["Data", "Options"])
        self.__tableWidget.setShowGrid(False)
        self.__tableWidget.setAlternatingRowColors(True)
        self.__tableWidget.setSelectionBehavior(self.__tableWidget.SelectRows)
        self.__tableWidget.setSelectionMode(self.__tableWidget.SingleSelection)
        layout.addWidget(self.__tableWidget, 4)

        # Plot widgets
        self.__graphicsLayoutWidget = pg.GraphicsLayoutWidget()
        self.__informationLabel = pg.LabelItem(justify="left")
        self.__informationLabel.setText("")
        self.__graphicsLayoutWidget.addItem(self.__informationLabel, row=0, rowspan=1, col=0)
        self.__plotItem = self.__graphicsLayoutWidget.addPlot(row=0, rowspan=9, col=0)
        layout.addWidget(self.__graphicsLayoutWidget, 10)

        # Plot options
        optionLayout = QtGui.QFormLayout()
        self.__moduleParameterComboBox = QtGui.QComboBox()
        self.__semiCirclePlotCheckBox = QtGui.QCheckBox()
        self.__semiCirclePlotCheckBox.setChecked(True)

        self.__sectionAngleSpinBox = QtGui.QSpinBox()
        self.__sectionAngleSpinBox.setRange(1, 360)
        self.__sectionAngleSpinBox.setValue(2)

        optionLayout.addRow("Semi circle", self.__semiCirclePlotCheckBox)
        optionLayout.addRow("Bin angle", self.__sectionAngleSpinBox)
        optionLayout.addRow("Parameter", self.__moduleParameterComboBox)
        layout.addLayout(optionLayout)

        self.setLayout(layout)

        # Create connections
        self.__moduleParameterComboBox.currentTextChanged.connect(lambda text: self.updatePlot())
        self.__semiCirclePlotCheckBox.stateChanged.connect(lambda state: self.updatePlot())
        self.__sectionAngleSpinBox.valueChanged.connect(lambda state: self.updatePlot())

    def __onMouseMoved(self, event):
        """Handles mouse moved event over plot widget

        Args:
            event (QEvent): the QEvent object
        """
        if len(self.__plotDataArrays) <= 0:
            self.__informationLabel.setText("")
            return

        pos = event[0]
        if not self.__plotItem.sceneBoundingRect().contains(pos):
            return

        mousePoint = self.__plotItem.vb.mapSceneToView(pos)

        angle = 0
        amplitude = 0

        if len(self.__plotItem.items) > 0:
            x = mousePoint.x()
            y = mousePoint.y()

            if x != 0:
                angle = math.degrees(math.atan(y / x))
            else:
                angle = 0

            if x <= 0.0:
                angle = 180 + angle
            elif x > 0.0 and y < 0:
                angle = 360 + angle

            angle = self.__getAngleWithOffset(angle)

            amplitude = math.floor(math.sqrt(math.pow(x, 2) + math.pow(y, 2)))

        plotsInformationString = ""
        for graphData in self.__graphDataList:
            histogramData = self.__plotDataArrays.get(id(graphData), None)
            if not histogramData:
                continue

            color = graphData.style.color
            value = 0
            if histogramData.originalMinValue < 0.00 or histogramData.originalMaxValue > 360.0:
                value = self.__remapValues(
                    angle, 0, 360, histogramData.originalMinValue, histogramData.originalMaxValue
                )
            else:
                value = angle
            plotsInformationString += (
                "<span style='font-size: 8pt; color: rgb(%d, %d, %d)'> %s value: %0.0f</span><br>"
                % (color[0], color[1], color[2], graphData.name, value)
            )

        self.__informationLabel.setText(
            "<span style='font-size: 12pt'>Angle: %0.1fº,   <span>Amplitude: %0.0f</span><br>%s"
            % (angle, amplitude, plotsInformationString)
        )

    def appendData(self, dataNode):
        """Wrapper method for inserting data into the widget"""
        return self.__model.appendData(dataNode)

    def __clearPlot(self):
        """Handles plot clearing"""
        self.__plotItem.clear()
        self.__informationLabel.setText("")
        self.__plotDataArrays.clear()
        if hasattr(self, "__mouseProxy") and self.__mouseProxy is not None:
            self.__mouseProxy.disconnect()
            self.__mouseProxy = None

    def __createPlotUpdateTimer(self):
        """Initialize timer object that process data to plot"""
        if hasattr(self, "plotUpdateTimer") and self.plotUpdateTimer is not None:
            self.plotUpdateTimer.deleteLater()
            self.plotUpdateTimer = None

        self.plotUpdateTimer = QtCore.QTimer()
        self.plotUpdateTimer.setSingleShot(True)
        self.plotUpdateTimer.timeout.connect(lambda: self.__handleUpdatePlot())
        self.plotUpdateTimer.setInterval(PLOT_UPDATE_TIMER_INTERVAL_MS)

    def updatePlot(self):
        """Handler update plot timer start."""
        if self.plotUpdateTimer.isActive():
            self.plotUpdateTimer.stop()

        self.plotUpdateTimer.start()

    def updateGraphDataTable(self, graphDataList: list):
        """Handles table widget data update"""
        self.__graphDataList = list(graphDataList)
        self.__tableWidget.clearContents()
        self.__tableWidget.setRowCount(0)
        for graphData in self.__graphDataList:
            self.__addDataToTable(graphData)

        self.__updateParameterComboBox()

    def __updateTableVisibleButton(self, button: QtGui.QPushButton, graphData: NodeGraphData):
        """Updates icon of the related visible button (from the table widget)."""
        if graphData.visible is True:
            button.setIcon(QtGui.QIcon(str(VISIBLE_ICON_FILE_PATH)))
        else:
            button.setIcon(QtGui.QIcon(str(NOT_VISIBLE_ICON_FILE_PATH)))

    def __toggleGraphVisible(self, button: QtGui.QPushButton, graphData: NodeGraphData):
        """Updates visible state from GraphData object."""
        graphData.visible = not graphData.visible
        self.__updateTableVisibleButton(button, graphData)

    def __addDataToTable(self, graphData):
        """Creates objects and widgets related to the GraphData inserted."""
        lastRowIndex = self.__tableWidget.rowCount()
        self.__tableWidget.setRowCount(lastRowIndex + 1)

        # Options widget
        optionsWidget = QtGui.QWidget()

        # Visible toggle button
        visibleButton = QtGui.QPushButton("")
        self.__updateTableVisibleButton(visibleButton, graphData)
        visibleButton.setFixedSize(26, 26)
        visibleButton.setIconSize(QtCore.QSize(20, 20))
        visibleButton.setAutoDefault(False)
        visibleButton.setDefault(False)

        # Customize style button
        editButton = CustomColorButton(color=graphData.style.color, symbol=None, line_style=None)
        editButton.setFixedSize(26, 26)
        editButton.setAutoDefault(False)
        editButton.setDefault(False)

        # Remove button
        removeButton = QtGui.QPushButton(QtGui.QIcon(str(REMOVE_ICON_FILE_PATH)), "")
        removeButton.setFixedSize(26, 26)
        removeButton.setIconSize(QtCore.QSize(20, 20))
        removeButton.setAutoDefault(False)
        removeButton.setDefault(False)

        # Options widget layout
        optionsLayout = QtGui.QHBoxLayout()
        optionsLayout.setSizeConstraint(QtGui.QLayout.SetMinimumSize)
        optionsLayout.setSpacing(5)
        optionsLayout.addWidget(visibleButton)
        optionsLayout.addWidget(editButton)
        optionsLayout.addWidget(removeButton)
        optionsWidget.setLayout(optionsLayout)

        # Buttons connections
        visibleButton.clicked.connect(lambda state: self.__toggleGraphVisible(visibleButton, graphData))
        removeButton.clicked.connect(lambda state: self.__model.removeGraphDataFromTable(graphData))
        editButton.sigStyleChanged.connect(
            lambda color, symbol, size: self.__onPlotStyleChanged(graphData, color, symbol, size)
        )

        nameItem = QtGui.QTableWidgetItem(graphData.name)
        nameItem.setFlags(nameItem.flags() & ~QtCore.Qt.ItemIsEditable)
        self.__tableWidget.setItem(lastRowIndex, 0, nameItem)
        self.__tableWidget.setCellWidget(lastRowIndex, 1, optionsWidget)

        # Fix horizontal header stretching over the limits
        self.__tableWidget.horizontalHeader().reset()

    def __onPlotStyleChanged(self, graphData, color, symbol_text, size):
        """Handles plot style update

        Args:
            graphData (NodeGraphData): the related GraphData object
            color (tuple): the RGB tuple chosed
            symbol_text (str): the symbol description chosed
            size (int): the pen size chosed
        """
        graphData.style.color = (color.red(), color.green(), color.blue())
        self.updatePlot()

    def __createPolarGraph(self, radius=20):
        """Handles polar circumference plotting.

        Args:
            radius (int): The circumference's radius
        """
        circleRange = np.linspace(0, radius, 8)
        for r in circleRange:
            circle = pg.QtGui.QGraphicsEllipseItem(-r, -r, r * 2, r * 2)
            pen = pg.mkPen(0.2)
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            circle.setPen(pen)
            self.__plotItem.addItem(circle)

        # Add lines for N bins
        maxAngle = 180 if self.__semiCirclePlotCheckBox.isChecked() is True else 360
        angles = np.arange(0, maxAngle + 1, 30)

        for angle in angles:
            x1 = 0.0
            y1 = 0.0
            x2 = math.cos(math.radians(angle)) * radius
            y2 = math.sin(math.radians(angle)) * radius
            line = pg.QtGui.QGraphicsLineItem(x1, y1, x2, y2)
            pen = pg.mkPen(0.2)
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            line.setPen(pen)
            self.__plotItem.addItem(line)

            if angle == 360:
                continue

            angleWithOffset = self.__getAngleWithOffset(angle)
            angleText = str(angleWithOffset)
            x3 = math.cos(math.radians(angle)) * radius * 1.05
            y3 = math.sin(math.radians(angle)) * radius * 1.05
            textItem = pg.TextItem(text=angleText, color=(255, 255, 255), anchor=(0.5, 0.5))
            textItem.setPos(QtCore.QPointF(x3, y3))
            self.__plotItem.addItem(textItem)

    def __handleUpdatePlot(self):
        """Wrapper for updating the plots related to the user's input (2D or 3D plot)"""
        self.__clearPlot()
        isThereAPlot = False
        maxYHist = 0
        for graphData in self.__graphDataList:
            if graphData.visible is False:
                continue

            moduleParameter = self.__moduleParameterComboBox.currentText()

            moduleData = graphData.data.get(moduleParameter, None)

            if moduleData is None:
                continue

            originalMinValue = np.amin(moduleData)
            originalMaxValue = np.amax(moduleData)

            dist = self.__sectionAngleSpinBox.value()
            bins = int(360 / dist)
            if originalMinValue < 0.00 or originalMaxValue > 360.0:
                moduleData = self.__remapValues(moduleData, originalMinValue, originalMaxValue, 0, 360)

            histY, histX = np.histogram(moduleData, bins=bins, range=(0, 360))

            histogramData = HistogramData(
                x=histX, y=histY, originalMinValue=originalMinValue, originalMaxValue=originalMaxValue
            )
            self.__plotDataArrays[id(graphData)] = histogramData

            maxYHist = max(maxYHist, np.max(histY))
            for i in reversed(range(len(histY))):
                color = QtGui.QColor(graphData.style.color[0], graphData.style.color[1], graphData.style.color[2], 200)
                polItem = WindrosePolygonItem(alpha=dist, radius=histY[i])
                polItem.setZValue(1)
                # WindrosePolygon is created Y axis oriented, so we need to rotated it to the x axis (-90º) and
                # then apply the desired angle (alpha/2 plus section angle)
                rotation = dist / 2 + self.__getAngleWithOffset(np.floor(histX[i + 1]) - 90)
                polItem.setRotation(rotation + 180)
                polItem.setPen(pg.mkPen(color=color, width=0.1))
                polItem.setBrush(pg.mkBrush(color))
                self.__plotItem.addItem(polItem)

            isThereAPlot = True

        if isThereAPlot:
            self.__createPolarGraph(radius=maxYHist)
            self.__mouseProxy = pg.SignalProxy(
                self.__plotItem.scene().sigMouseMoved, rateLimit=20, slot=self.__onMouseMoved
            )

            if self.__semiCirclePlotCheckBox.isChecked() is True:
                self.__plotItem.setLimits(
                    yMin=-maxYHist * 0.02, yMax=maxYHist * 1.6, xMin=-maxYHist * 1.25, xMax=maxYHist * 1.25
                )
            else:
                self.__plotItem.setLimits(
                    yMin=-maxYHist * 1.2, yMax=maxYHist * 1.2, xMin=-maxYHist * 1.6, xMax=maxYHist * 1.6
                )

            self.__plotItem.autoRange(padding=0.2)
            self.__plotItem.setAspectLocked()
            self.__plotItem.showGrid(x=False, y=False)
            self.__plotItem.hideAxis("bottom")
            self.__plotItem.hideAxis("left")

    def __updateParameterComboBox(self):
        """Update axis combo boxes with the existent data's parameters"""
        parametersSet = set()
        for graphData in self.__graphDataList:
            df = graphData.df().select_dtypes(include=[np.number])
            parametersSet.update(df.columns)

        # add empty parameter option
        parameters = [AXIS_NONE_PARAMETER] + list(parametersSet)
        parameters.sort()

        # store old axis selections
        currentModuleAxis = self.__moduleParameterComboBox.currentText()

        # update available parameters
        self.__moduleParameterComboBox.clear()
        self.__moduleParameterComboBox.addItems(parameters)

        # restore old axis selections
        self.__moduleParameterComboBox.setCurrentText(currentModuleAxis)

    def __getAngleWithOffset(self, angle):
        angleWithOffset = angle
        if angle > abs(self.__angleOffsetDegrees):
            angleWithOffset = 360 - angle - self.__angleOffsetDegrees
        else:
            angleWithOffset = abs(angle + self.__angleOffsetDegrees)
        return angleWithOffset

    def __remapValues(self, input, minInputRange, maxInputRange, minOutputRange, maxOutputRange):
        """Re-map values (double or numpy.ndarray) from input range to the output range.

        Args:
            input (double or numpy.ndarray): the input data to be remapped
            minInputRange (double): the input range minimum value
            maxInputRange (double): the input range maximum value
            minOutputRange (double]): the output range minimum value
            maxOutputRange (double]): the output range maximum value

        Returns:
            double or numpy.ndarray: the remapped data
        """
        output = (input - minInputRange) / (maxInputRange - minInputRange) * (
            maxOutputRange - minOutputRange
        ) + minOutputRange
        return output
