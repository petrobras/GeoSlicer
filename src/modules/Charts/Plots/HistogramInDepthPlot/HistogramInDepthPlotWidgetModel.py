from ..BasePlotWidget import BasePlotWidget
from ltrace.slicer.graph_data import NodeGraphData
from ltrace.slicer.node_attributes import TableDataTypeAttribute, PlotScaleXAxisAttribute
from pyqtgraph.Qt import QtCore
from typing import Union


PORE_DELIMETER_REGEX_PATTERN = r"[\.\-\,\;\_]"
PORE_FOLDER_REGEX_PATTERN = r"[0-9]+" + PORE_DELIMETER_REGEX_PATTERN + r"[0-9]{2}$"


class HistogramInDepthPlotWidgetModel(QtCore.QObject):
    def __init__(self, widget: BasePlotWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__widget = widget
        self.__graphDataList = list()
        self.__plotScale = "linear"

    def appendData(self, dataNode):
        """Store and parse node's data. Each data will be available at the table's widget as well.
           Although its logic is not necessary for this plot, it is used to maintain compatibility
           with current Charts implementation.

        Args:
            dataNode (slicer.vtkMRMLNode): the slicer's node object.
        """
        graphData = NodeGraphData(self.__widget, dataNode)
        if graphData in self.__graphDataList:
            return

        if graphData.data.get("X", None) is None:
            tableDataType = dataNode.GetAttribute(TableDataTypeAttribute.name())
            if not tableDataType:
                raise AttributeError("The selected node is invalid for this plot.")

        # store xscale properties
        self.__plotScale = self.__getPlotScaleFromNode(dataNode)

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

    def __getPlotScaleFromNode(self, dataNode):
        return dataNode.GetAttribute(PlotScaleXAxisAttribute.name()) or PlotScaleXAxisAttribute.LOG_SCALE.value

    @property
    def graphDataList(self):
        return self.__graphDataList

    @property
    def plotScale(self) -> Union[None, str]:
        return self.__plotScale
