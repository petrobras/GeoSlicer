from ..BasePlotWidget import BasePlotWidget
from ltrace.slicer.graph_data import NodeGraphData
from pyqtgraph.Qt import QtCore
import slicer


class HistogramPlotWidgetModel(QtCore.QObject):
    TYPE = "HistogramPlot"

    def __init__(self, widget: BasePlotWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__widget = widget
        self.__graphDataList = list()

    def appendData(self, dataNode: slicer.vtkMRMLNode):
        """Store and parse node's data. Each data will be available at the table's widget as well.

        Args:
            dataNode (slicer.vtkMRMLNode): the slicer's node object.
        """
        graphData = NodeGraphData(self.__widget, dataNode)
        if graphData in self.__graphDataList:
            return

        graphData.signalVisibleChanged.connect(lambda is_visible: self.__widget.updatePlot())
        graphData.signalModified.connect(self.__widget.updatePlot)
        graphData.signalRemoved.connect(lambda: self.removeGraphDataFromTable(graphData))

        # store GraphData object
        self.__graphDataList.append(graphData)

        # Updata graph data table
        self.__widget.updateGraphDataTable(self.__graphDataList)

    def removeGraphDataFromTable(self, graphData: NodeGraphData):
        """Remove data and objects related to the GraphData object."""
        if not graphData in self.__graphDataList:
            return

        self.__graphDataList.remove(graphData)
        self.__widget.updateGraphDataTable(self.__graphDataList)
        self.__widget.updatePlot()

    @property
    def graphDataList(self):
        return self.__graphDataList
