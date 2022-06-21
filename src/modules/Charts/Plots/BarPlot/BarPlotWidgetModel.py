from ..BasePlotWidget import BasePlotWidget
from ltrace.slicer.graph_data import NodeGraphData
from pyqtgraph.Qt import QtCore


class BarPlotWidgetModel(QtCore.QObject):
    def __init__(self, widget: BasePlotWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__widget = widget
        self.__graphDataList = list()

    def appendData(self, dataNode):
        """Store and parse node's data. Each data will be available at the table's widget as well.

        Args:
            dataNode (slicer.vtkMRMLNode): the slicer's node object.
        """

        self.__graphDataList.clear()
        graphData = NodeGraphData(self.__widget, dataNode)

        df = graphData.df()

        if len(df.index) <= 1:
            raise ValueError("Too few values to plot transitions, at least two rows are required.")

        if len(df.index) > 256:
            raise ValueError("Too much classes to plot transitions, max is 256.")

        if df.shape[0] > df.shape[1]:  # If you have more rows, you will never match the number of rows
            raise ValueError(
                "Transition plot requires the number of rows to be equal to the number of numeric columns."
            )

        graphData.signalVisibleChanged.connect(lambda is_visible: self.__widget.updatePlot())
        graphData.signalModified.connect(self.__widget.updatePlot)
        graphData.signalRemoved.connect(lambda: self.removeGraphDataFromTable(graphData))

        # store GraphData object
        self.__graphDataList.append(graphData)

        # Updata graph data table
        self.__widget.updatePlot()

    def removeGraphDataFromTable(self, graphData: NodeGraphData):
        """Remove data and objects related to the GraphData object."""
        if not graphData in self.__graphDataList:
            return

        self.__graphDataList.remove(graphData)
        self.__widget.updatePlot()

    @property
    def graphDataList(self):
        return list(self.__graphDataList)
