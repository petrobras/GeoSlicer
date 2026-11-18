import numpy as np
import pandas as pd

from commons.slicer_utils import LTracePluginTest
from commons.slicer.graph_data import (
    GraphData,
    GraphStyle,
    DataFrameGraphData,
    TEXT_SYMBOLS,
)
from commons.slicer.tests.utils import process_events, wait
from pyqtgraph import QtCore
from unittest.mock import MagicMock


class GraphDataTest(LTracePluginTest):
    def test_graph_style_initialization(self):
        """Test GraphStyle initialization with default and custom values."""
        # Default
        style = GraphStyle(parent=self.parent())
        self.assertEqual(style.color, (211, 47, 47))
        self.assertEqual(style.symbol, list(TEXT_SYMBOLS.values())[0])
        self.assertEqual(style.size, 10)

        # Custom
        custom_style = GraphStyle(
            parent=self.parent(),
            color=(0, 255, 0),
            symbol="s",
            size=15,
            plot_type="scatter",
            line_style=QtCore.Qt.PenStyle.DashLine,
            line_size=2,
        )
        self.assertEqual(custom_style.color, (0, 255, 0))
        self.assertEqual(custom_style.symbol, "s")
        self.assertEqual(custom_style.size, 15)
        self.assertEqual(custom_style.plot_type, "scatter")
        self.assertEqual(custom_style.line_style, QtCore.Qt.PenStyle.DashLine)
        self.assertEqual(custom_style.line_size, 2)

    def test_graph_style_setters_and_signals(self):
        """Test GraphStyle setters and signal emissions."""
        style = GraphStyle(parent=self.parent())
        styleMock = MagicMock()
        style.signalStyleChanged.connect(styleMock)

        # Change color
        style.color = (1, 2, 3)
        styleMock.assert_called_once()
        self.assertEqual(style.color, (1, 2, 3))

        # Change symbol (valid)
        style.symbol = "t"
        self.assertEqual(styleMock.call_count, 2)
        self.assertEqual(style.symbol, "t")

        # Change symbol (invalid)
        style.symbol = "invalid_symbol"
        self.assertEqual(styleMock.call_count, 2)  # Not called again
        self.assertEqual(style.symbol, "t")  # Unchanged

        # Change line style (valid)
        style.line_style = QtCore.Qt.PenStyle.DotLine
        self.assertEqual(styleMock.call_count, 3)
        self.assertEqual(style.line_style, QtCore.Qt.PenStyle.DotLine)

        # Set same value again
        style.line_style = QtCore.Qt.PenStyle.DotLine
        self.assertEqual(styleMock.call_count, 3)  # Not called again

    def test_graph_data_base_class(self):
        """Test base GraphData class properties and signals."""
        graphData = GraphData(parent=self.parent())
        self.assertEqual(graphData.name, "")
        self.assertIsNone(graphData.df())
        self.assertTrue(graphData.visible)

        # Test visibility signal
        visibleMock = MagicMock()
        graphData.signalVisibleChanged.connect(visibleMock)
        graphData.visible = False
        visibleMock.assert_called_once_with(False)

        # Test style signal
        styleMock = MagicMock()
        graphData.signalStyleChanged.connect(styleMock)
        graphData.style.size = 20
        styleMock.assert_called_once()

        # Test modified signal debouncer
        modifiedMock = MagicMock()
        graphData.signalModified.connect(modifiedMock)
        graphData.signalModifiedDebouncer.emitSignal()
        process_events()
        wait(1)

        modifiedMock.assert_called_once()

    def test_dataframe_graph_data(self):
        """Test DataFrameGraphData initialization."""
        df = pd.DataFrame({"X": [1, 2, 3], "Y": [4, 5, 6]})
        graphData = DataFrameGraphData(parent=self.parent(), dataFrame=df)

        self.assertIs(graphData.df(), df)
        self.assertEqual(len(graphData.data), 2)
        self.assertEqual(list(graphData.data.item()), ["X", "Y"])

    def test_dict_interface(self):
        """Test the DictInterface wrapper."""
        df = pd.DataFrame({"A": [10, 20], "B": [30, 40]})
        graphData = DataFrameGraphData(parent=self.parent(), dataFrame=df)
        data_interface = graphData.data

        pd.testing.assert_series_equal(data_interface.get("A"), pd.Series([10, 20], name="A"))
        self.assertEqual(data_interface.get("C", "default"), "default")
        pd.testing.assert_series_equal(data_interface["B"], pd.Series([30, 40], name="B"))
        with self.assertRaises(KeyError):
            _ = data_interface["C"]

        self.assertEqual(len(data_interface), 2)

        items = list(data_interface.items())
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0][0], "A")
        self.assertTrue(np.array_equal(items[0][1], np.array([10, 20])))
