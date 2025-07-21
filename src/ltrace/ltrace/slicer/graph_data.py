import numpy as np
import pandas as pd
import slicer
import vtk

from pandas.api.types import is_numeric_dtype
from ltrace.slicer.node_attributes import TableDataOrientation
from ltrace.algorithms.measurements import (
    CLASS_LABEL_SUFFIX,
    get_pore_size_class_label_field,
    PORE_SIZE_CATEGORIES,
    GRAIN_SIZE_CATEGORIES,
)
from ltrace.slicer.helpers import tryGetNode
from pyqtgraph import QtCore
from ltrace.slicer import data_utils as dutils


TEXT_SYMBOLS = {
    "● Circle": "o",
    "■ Square": "s",
    "▲ Triangle-upwards": "t1",
    "▶ Triangle-rightwards": "t2",
    "▼ Triangle-downwards": "t",
    "◀ Triangle-leftwards": "t3",
    "⧫ Lozange": "x",
    "◆ Diamond": "d",
    "⬟ Pentagon": "p",
    "⬢ Hexagon": "h",
    "★ Star": "star",
    "+ Plus-sign": "+",
    "↑ Arrow-upwards": "arrow_up",
    "→ Arrow-rightwards": "arrow_right",
    "↓ Arrow-downwards": "arrow_down",
    "← Arrow-leftwards": "arrow_left",
}

LINE_STYLES = {
    "None": None,
    "Solid": QtCore.Qt.SolidLine,
    "Dashed": QtCore.Qt.DashLine,
    "Dotted": QtCore.Qt.DotLine,
    "Dash-Dot": QtCore.Qt.DashDotLine,
    "Dash-Dot-Dot": QtCore.Qt.DashDotDotLine,
}

SYMBOL_TEXT = {v: k for k, v in TEXT_SYMBOLS.items()}
LINE_STYLES_TEXT = {v: k for k, v in LINE_STYLES.items()}
SCATTER_PLOT_TYPE = "scatter"
LINE_PLOT_TYPE = "line"


class GraphStyle(QtCore.QObject):
    """Provides an interface to the parameters related to the graph's style"""

    signalStyleChanged = QtCore.Signal()

    def __init__(
        self,
        plot_type=None,
        color=None,
        symbol=None,
        size=None,
        line_style=None,
        line_size=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        default_color = 211, 47, 47
        default_symbol = list(TEXT_SYMBOLS.values())[0]
        default_size = 10
        default_line_style = None
        default_line_size = 1
        self.__color = color or default_color
        self.__symbol = symbol or default_symbol
        self.__size = size or default_size
        self.__plot_type = plot_type or LINE_PLOT_TYPE
        self.__line_style = line_style or default_line_style
        self.__line_size = line_size or default_line_size

    @property
    def color(self):
        return self.__color

    @color.setter
    def color(self, new_color):
        if new_color == self.__color:
            return

        self.__color = new_color
        self.signalStyleChanged.emit()

    @property
    def symbol(self):
        return self.__symbol

    @symbol.setter
    def symbol(self, new_symbol):
        if new_symbol == self.__symbol or not new_symbol in list(TEXT_SYMBOLS.values()):
            return

        self.__symbol = new_symbol
        self.signalStyleChanged.emit()

    @property
    def size(self):
        return self.__size

    @size.setter
    def size(self, new_size):
        if new_size == self.__size:
            return

        self.__size = new_size
        self.signalStyleChanged.emit()

    @property
    def plot_type(self):
        return self.__plot_type

    @plot_type.setter
    def plot_type(self, new_type):
        if new_type == self.__plot_type:
            return

        self.__plot_type = new_type
        self.signalStyleChanged.emit()

    @property
    def line_size(self):
        return self.__line_size

    @line_size.setter
    def line_size(self, new_line_size):
        if new_line_size == self.__line_size:
            return

        self.__line_size = new_line_size
        self.signalStyleChanged.emit()

    @property
    def line_style(self):
        return self.__line_style

    @line_style.setter
    def line_style(self, new_line_style):
        if new_line_style == self.__line_style or not new_line_style in list(LINE_STYLES.values()):
            return

        self.__line_style = new_line_style
        self.signalStyleChanged.emit()


class DictInterface:
    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df

    def get(self, key, defaults=None):
        if self.df is None:
            return None

        if key in self.df.columns:
            return self.df[key]

        return defaults

    def items(self):
        if self.df is None:
            return None

        for column in self.df.columns:
            yield column, self.df[column].to_numpy()

    def item(self):
        if self.df is None:
            return None

        for column in self.df.columns:
            yield column

    def __getitem__(self, key):
        r = self.get(key)
        if r is None:
            raise KeyError(key)
        return r

    def __setitem__(self, key):
        raise NotImplementedError(
            "This interface dot not allow direct writing to the graph data because this is a plotting module. "
            "Please check your requirements to see if you really need to modify the data."
        )

    def __len__(self):
        if self.df is None:
            return 0

        return len(self.df.columns)

    def __rows__(self):
        if self.df is None:
            return 0

        return self.df.shape[0]


class GraphData(QtCore.QObject):
    """Class to store node and parse its data that could be used as a plot input.

    Raises:
        ValueError: Raises when dataNode argument is not compatible with the parser function
    """

    signalVisibleChanged = QtCore.Signal(bool)
    signalModified = QtCore.Signal()
    signalRemoved = QtCore.Signal()
    signalStyleChanged = QtCore.Signal()

    def __init__(
        self,
        parent,
        plot_type=None,
        color=None,
        symbol=None,
        size=None,
        *args,
        **kwargs,
    ):
        super().__init__(parent)
        self._data = None
        self._name = ""
        self.__visible = True
        self.style = GraphStyle(plot_type, color, symbol, size, *args, **kwargs)
        self.__named_columns = dict()

        self.style.signalStyleChanged.connect(self.signalStyleChanged)

        # destroyed signal only works with a lambda
        self.destroyed.connect(lambda: self._cleanUp())
        from ltrace.slicer.debounce_caller import DebounceCaller

        self.signalModifiedDebouncer = DebounceCaller(parent=self, signal=self.signalModified, qtTimer=QtCore.QTimer)

    def __eq__(self, other):
        if not isinstance(other, GraphData):
            return False

        return self._name == other._name

    def __hash__(self):
        return hash(repr(self))

    def __del__(self):
        del self._data
        del self._name
        del self.__visible
        del self.style

    @property
    def data(self):
        return DictInterface(self._data)

    @property
    def name(self):
        return self._name

    @property
    def visible(self):
        return self.__visible

    @visible.setter
    def visible(self, is_visible):
        if self.__visible == is_visible:
            return

        self.__visible = is_visible
        self.signalVisibleChanged.emit(self.__visible)

    def df(self):
        return self._data

    def _cleanUp(self):
        """Clears current object's data."""
        self._data = None
        self._name = ""

    def getLabelNames(self, column):
        return self._data[self.__named_columns[column]]

    def hasNames(self, column):
        return column in self.__named_columns

    def _handleKnownDataSpecifics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Handles specifics for data mangling before loading.

        ** CALL your handlers from here **

        Args:
            df (pd.DataFrame): DataFrame object as data source.

        """
        if "pore_size_class" in df.columns:
            # This is a inspector result - TODO make a attribute inside the node
            (
                labelColumnName,
                newLabelColumnData,
            ) = GraphData.handleLegacyPoreSizeClassVersions(df.columns.to_list(), df["pore_size_class"])
            if newLabelColumnData is not None:
                df[labelColumnName] = newLabelColumnData

            self.__named_columns[labelColumnName] = "pore_size_class"

        return df

    @staticmethod
    def handleLegacyPoreSizeClassVersions(columns, columnData):
        """Handles projects generated before v1.15.1. These projects do not have the column of labels (numerics) for the pore classes."""

        if columnData.empty:
            is_pore_data = True
        else:
            is_pore_data = "poro" in str(columnData.iloc[0])

        categories = PORE_SIZE_CATEGORIES if is_pore_data else GRAIN_SIZE_CATEGORIES

        try:
            ## Handle even older legacy projects (column with _label as suffix)
            idx = get_pore_size_class_label_field(columns)
            return columns[idx], None
        except ValueError:
            labelColumnName = f"{'pore' if is_pore_data else 'grain'}_size_class[label]"
            newLabelColumnData = columnData.replace(categories, np.arange(0, len(categories), 1))

            return labelColumnName, newLabelColumnData


class NodeGraphData(GraphData):
    """Class to store node and parse its data that could be used as a plot input.

    Raises:
        ValueError: Raises when dataNode argument is not compatible with the parser function
    """

    def __init__(
        self,
        parent,
        dataNode: slicer.vtkMRMLNode,
        plot_type=None,
        color=None,
        symbol=None,
        size=None,
        *args,
        **kwargs,
    ):
        super().__init__(parent, plot_type, color, symbol, size, *args, **kwargs)
        self.__nodeId = None
        self.__observerHandlers = list()

        if not self.__parseData(dataNode):
            raise ValueError("Invalid data type to visualize")

        if self.__nodeId:
            self.__observerHandlers.append((dataNode, dataNode.AddObserver("ModifiedEvent", self.__onNodeModified)))
            self.__observerHandlers.append(
                (
                    slicer.mrmlScene,
                    slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeRemovedEvent, self.__onNodeRemoved),
                )
            )

    def __eq__(self, other):
        if not isinstance(other, GraphData):
            return False

        return self._name == other._name and id(self.__nodeId) == id(other.__nodeId)

    def __del__(self):
        super().__del__()

        for object, tag in self.__observerHandlers:
            object.RemoveObserver(tag)
        del self.__observerHandlers

    @property
    def node(self):
        return tryGetNode(self.__nodeId)

    def __parseData(self, dataNode: slicer.vtkMRMLNode):
        """Internal parser function. Currently only supporting Table's nodes.
           Enhances are welcome!

        Args:
            dataNode (slicer.vtkMRMLNode): the slicer node object.

        Returns:
            bool: True if the parsing was sucessfull. Otherwise, returns false.
        """
        status = False
        self._data = None
        if type(dataNode) == slicer.vtkMRMLTableNode:
            self.__parseTableData(dataNode)
            status = True

        if status is True:
            self._name = dataNode.GetName()
            self.__nodeId = dataNode.GetID()

        return status

    def __parseTableData(self, dataNode: slicer.vtkMRMLTableNode):
        """Handles table's node data parsing.

        Args:
            dataNode (slicer.vtkMRMLTableNode): the table's node object.
        """
        orientation = dataNode.GetAttribute(TableDataOrientation.name())
        if orientation is None:
            orientation = str(TableDataOrientation.COLUMN.value)

        df = dutils.tableNodeToDataFrame(dataNode)
        if orientation == str(TableDataOrientation.ROW.value):
            df = self.transposeDataframe(df)

        self.__tryCastColumnsToNumeric(df)
        self._handleKnownDataSpecifics(df)
        self._data = df

    def __onNodeModified(self, caller, event):
        """Handles node's modification."""
        node = tryGetNode(self.__nodeId)
        if self.__parseData(node) is True:
            self.signalModifiedDebouncer.emit()
        else:
            # notify something went wrong
            self.signalRemoved.emit()
            self._cleanUp()

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def __onNodeRemoved(self, caller, event, callData):
        """Handles node's removal."""
        if callData is None or callData.GetID() != self.__nodeId:
            return

        self.signalRemoved.emit()
        self._cleanUp()

    def _cleanUp(self):
        super()._cleanUp()
        for object, tag in self.__observerHandlers:
            object.RemoveObserver(tag)
        self.__nodeId = None

    @staticmethod
    def transposeDataframe(df: pd.DataFrame) -> pd.DataFrame:
        out = {}
        for idx in range(len(df.index)):
            row = df.iloc[idx]
            out[row.iloc[0]] = row[1:]

        return pd.DataFrame(out)

    def __tryCastColumnsToNumeric(self, df: pd.DataFrame) -> pd.DataFrame:
        columns = df.columns.to_list()
        for columnName in columns:
            columnData = df[columnName]

            if not is_numeric_dtype(columnData):
                df[columnName] = pd.to_numeric(
                    columnData, errors="ignore"
                )  # If ‘ignore’, then invalid parsing will return the input.

        return df


class DataFrameGraphData(GraphData):
    def __init__(
        self,
        parent,
        dataFrame,
        plot_type=None,
        color=None,
        symbol=None,
        size=None,
        *args,
        **kwargs,
    ):
        super().__init__(parent, plot_type, color, symbol, size, *args, **kwargs)
        self._data = dataFrame
