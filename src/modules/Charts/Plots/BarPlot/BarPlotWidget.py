from .AngleAxisItem import AngleAxisItem
from .BarPlotWidgetModel import BarPlotWidgetModel
from ..BasePlotWidget import BasePlotWidget
from ltrace.slicer.helpers import segmentListAndProportionsFromSegmentation

from pyqtgraph.Qt import QtGui, QtCore

import logging
import numpy as np
import os
import pandas as pd
from pandas.api.types import is_string_dtype
import pyqtgraph as pg
import slicer


class BarPlotWidget(BasePlotWidget):
    TYPE = "Transition"

    def __init__(self, plotLabel="", *args, **kwargs):
        super().__init__(plotType=self.TYPE, plotLabel=plotLabel, *args, **kwargs)
        self.__model = BarPlotWidgetModel(self)

    def setupUi(self):
        """Initialize widgets"""
        layout = QtGui.QVBoxLayout()
        self.__graphicsLayoutWidget = pg.GraphicsLayoutWidget()
        self.__graphicsLayoutWidget.setBackground("w")
        axisBottom = AngleAxisItem(angle=45, orientation="bottom")
        axisItems = {"bottom": axisBottom}
        self.__plotItem = self.__graphicsLayoutWidget.addPlot(row=0, col=0, rowspan=5, colspan=5, axisItems=axisItems)

        legend = pg.LegendItem(size=(20, 20))
        self.__plotItem.legend = legend
        self.__graphicsLayoutWidget.addItem(legend, row=0, col=6, rowspan=1, colspan=1)

        self.__tableWidget = QtGui.QTableWidget()
        self.__tableWidget.setAlternatingRowColors(True)
        self.__tableWidget.setSizePolicy(QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Expanding)

        layout.addWidget(self.__graphicsLayoutWidget, 10)
        layout.addWidget(self.__tableWidget)

        widget = QtGui.QWidget()
        widget.setLayout(layout)

        self.setLayout(layout)

        self.updatePlot()

    def appendData(self, dataNode):
        """Wrapper method for inserting data into the widget"""
        return self.__model.appendData(dataNode)

    def __graphDataAsDataFrame(self):
        graphDataList = self.__model.graphDataList
        if len(graphDataList) <= 0:
            return None

        graphData = graphDataList[0]
        orig_df = graphData.df()
        df = orig_df.select_dtypes(include=[np.number])

        if df.shape[0] == df.shape[1]:
            if is_string_dtype(orig_df.iloc[:, 0]) and type(orig_df.columns) is pd.RangeIndex:
                labels = {i: col for i, col in enumerate(orig_df.iloc[:, 0].to_list())}
                df = df.reset_index(drop=True)
                df = df.rename(index=labels)
                df = df.rename(columns=labels)
            else:
                # If table doesn't have index labels, then check if
                # has the same amount of columns and rows, to use columns labels as index labels
                df = df.rename(index={i: col for i, col in enumerate(df.columns)})
        elif is_string_dtype(orig_df.iloc[:, 0]) and (len(df.columns) - 1) == len(df.index):
            orig_df = orig_df.T.reset_index().T
            labels = {i: col for i, col in enumerate(orig_df.iloc[:, 0].to_list())}
            df = df.T.reset_index().T
            df = df.rename(columns=labels)
            df = df.reset_index(drop=True)
            df = df.rename(index=labels)
            df = df[df.columns].apply(pd.to_numeric, errors="coerce")

        if df.shape[0] != df.shape[1]:
            raise ValueError("Transition plot requires the number of rows to be equal to the number of columns.")

        return df

    def updatePlot(self):
        data = self.__graphDataAsDataFrame()
        if data is None:
            return

        self.__writeDataToTable(data)

        # Retrieve colors from reference node's colors node
        colorsRelation = self.__getColorsRelationFromNode()

        columnWidth = 0.8
        currentHeights = np.array(data.sum(axis=0, numeric_only=True))

        for indexLabel, row in data.iterrows():
            row = np.array(row)
            # values

            heightValues = [row[i] for i in range(len(row))]
            heightValues = [currentHeights[i] - heightValues[i] for i in range(len(heightValues))]

            # style
            rgbList = np.random.randint(256, size=3)
            # If there is a color node, then it will use it as a color reference, and if some label doesn't have a color, it will be painted as black.
            # Otherwise, if there is not a color node reference, it will use a random color to paint it.
            if len(colorsRelation.keys()) > 0:
                rgbList = colorsRelation.get(indexLabel, [0, 0, 0])

            rgbColor = QtGui.QColor().fromRgb(rgbList[0], rgbList[1], rgbList[2], 255)

            brush = QtGui.QBrush(rgbColor)

            # legend
            name = indexLabel

            xIndex = range(len(row))
            bar = CustomBarGraph(
                x=xIndex, width=columnWidth, y0=currentHeights, y1=heightValues, brush=brush, name=name
            )

            currentHeights = heightValues

            self.__plotItem.addItem(bar)

        # Apply plot customization
        self.__plotItem.showGrid(x=True, y=True)
        self.__plotItem.setLabel(axis="left", text="Amplitude")
        self.__plotItem.setLimits(xMin=-1, xMax=len(data.columns))

        # Changes axis indexes to the related name
        def truncate(text, value: int):
            text = (text[:value] + "...") if len(text) > value else text
            return text

        columnLabels = [data.columns[i] for i in range(len(data.columns))]
        truncatecolumnLabels = [truncate(text, 20) for text in columnLabels]
        ticks = [list(zip(range(len(data.columns)), truncatecolumnLabels))]

        xAxis = self.__plotItem.getAxis("bottom")
        xAxis.setTicks(ticks)

        self.__updateLegendLayout()

    def __updateLegendLayout(self):
        legendRowCount = self.__plotItem.legend.rowCount
        self.__graphicsLayoutWidget.ci.layout.setRowMaximumHeight(0, 20 * legendRowCount)

    def __writeDataToTable(self, dataFrame):
        if dataFrame is None:
            return

        dataColumns = list(dataFrame)
        headers = dataColumns

        self.__tableWidget.setRowCount(dataFrame.shape[0])
        self.__tableWidget.setColumnCount(dataFrame.shape[1])
        self.__tableWidget.setHorizontalHeaderLabels(headers)
        self.__tableWidget.setVerticalHeaderLabels(headers)
        self.__tableWidget.horizontalHeader().setResizeMode(QtGui.QHeaderView.ResizeToContents)

        dataFrameArray = dataFrame.values
        for row in range(dataFrame.shape[0]):
            for column in range(dataFrame.shape[1]):
                dataCell = dataFrameArray[row, column]
                tableItem = None
                if type(dataCell) == str and dataCell.isnumeric():
                    dataCell = float(dataCell)
                elif type(dataCell) != str and type(dataCell) != float:
                    dataCell = dataCell.item()
                else:
                    continue

                tableItem = QtGui.QTableWidgetItem("{:0.4f}".format(dataCell))
                tableItem.setFlags(tableItem.flags() & ~QtCore.Qt.ItemIsEditable)
                tableItem.setTextAlignment(QtCore.Qt.AlignCenter)
                self.__tableWidget.setItem(row, column, tableItem)

    def __getColorsRelationFromNode(self):
        """Retrieve pixel colors relation from the references node's colors node."""
        table_node = self.__model.graphDataList[0].node
        reference_node_id = table_node.GetAttribute("ReferenceVolumeNode")
        if reference_node_id is None:
            return dict()

        reference_node = slicer.mrmlScene.GetNodeByID(reference_node_id)
        if reference_node is None:
            logging.warning(
                "Couldn't load a color relation because the reference node volume doesn't exist in the current project."
            )
            return dict()

        colors_relation = dict()
        if reference_node.IsA(slicer.vtkMRMLSegmentationNode.__name__):
            colors_relation = self.__get_colors_relation_from_segmentation_node(reference_node)
        else:  # Probably a LabelMapVolume
            colors_relation = self.__get_colors_relation_from_labelmap_node(reference_node)
        return colors_relation

    def __get_colors_relation_from_segmentation_node(self, reference_node):
        colors_relation = dict()
        segments = segmentListAndProportionsFromSegmentation(reference_node, roiNode=None, referenceNode=None)
        for label in segments:
            segment = segments[label]
            rgb_color = [int(c * 255) for c in segment["color"][:3]]
            pixel_name = segment["name"]
            colors_relation[pixel_name] = rgb_color

        return colors_relation

    def __get_colors_relation_from_labelmap_node(self, reference_node):
        colors_relation = dict()
        colors_node = reference_node.GetDisplayNode().GetColorNode()
        if colors_node is not None:
            for i in range(1, colors_node.GetNumberOfColors()):
                color = np.zeros(4)
                colors_node.GetColor(i, color)
                rgb_color = (color * 255).round().astype(int)[:-1]
                pixel_name = colors_node.GetColorName(i)
                colors_relation[pixel_name] = rgb_color

        return colors_relation


class CustomBarGraph(pg.BarGraphItem):
    """Class that enhance BarGraphItem class"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def hoverEvent(self, event):
        """Overwrite hoverEvent handler for pg.BarGraphItem.
           Exception Handling is a mess because there is some failing checks inside current pg.HoverEvent class version
        Args:
            event (QEvent): the QEvent object

        Returns:
            bool: The event handling status
        """
        try:
            point = QtCore.QPoint(event.lastScreenPos().x(), event.lastScreenPos().y())
            QtGui.QToolTip.showText(point, str(self.name()))
        except:
            pass
        finally:
            return True
