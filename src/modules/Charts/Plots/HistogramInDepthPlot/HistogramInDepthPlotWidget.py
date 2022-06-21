from ..BasePlotWidget import BasePlotWidget
from .HistogramInDepthPlotWidgetModel import HistogramInDepthPlotWidgetModel
from ltrace.slicer.helpers import export_las_from_histogram_in_depth_data
from pyqtgraph.Qt import QtGui

import pyqtgraph as pg
import numpy as np


class HistogramInDepthPlotWidget(BasePlotWidget):
    TYPE = "Histograms in depth"

    def __init__(self, plotLabel="", *args, **kwargs):
        super().__init__(plotType=self.TYPE, plotLabel=plotLabel, *args, **kwargs)
        self.__model = HistogramInDepthPlotWidgetModel(self)

    def setupUi(self):
        """Initialize widgets"""
        layout = QtGui.QVBoxLayout()
        self.__graphicsLayoutWidget = pg.GraphicsLayoutWidget()
        self.__plotItem = self.__graphicsLayoutWidget.addPlot(row=0, col=0, rowspan=5, colspan=5)
        layout.addWidget(self.__graphicsLayoutWidget)
        self.setLayout(layout)

        # Create context menu's custom options
        menu = self.__plotItem.getViewBox().menu
        # Export to las Action
        self.export_action = QtGui.QAction("Export to LAS file")
        self.export_action.triggered.connect(self.__on_export_to_las_clicked)
        menu.addAction(self.export_action)

    def appendData(self, dataNode):
        """Wrapper method for inserting data into the widget"""
        return self.__model.appendData(dataNode)

    def updatePlot(self):
        self.__plotItem.clear()
        graph_data_list = self.__model.graphDataList
        for graph_data in graph_data_list:
            x = np.array(graph_data.data["X"])

            for pore, pore_data in graph_data.data.items():
                if pore == "X":
                    continue

                pore_value = float(pore)
                y = pore_data
                color = QtGui.QColor(255, 255, 255, 255)
                brush = QtGui.QBrush(color)
                pen = QtGui.QPen(brush, 0.01)
                plt = self.__plotItem.plot(
                    x, -1 * y + pore_value, fillLevel=pore_value, brush=(50, 50, 200, 255), pen=pen
                )
                plt.setZValue(pore_value)

        # Apply plot customization
        self.__plotItem.showGrid(x=True, y=True)
        self.__plotItem.showAxis("bottom", True)
        self.__plotItem.setLogMode(x=True, y=False)
        self.__plotItem.invertY(True)

    def __on_export_to_las_clicked(self):
        import qt
        import slicer

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
