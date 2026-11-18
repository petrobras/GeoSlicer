import slicer
import qt
import pandas as pd
import numpy as np
import PySide2
import shiboken2

from commons.slicer_utils import LTracePluginTest
from commons.slicer.graph_data import NodeGraphData
from commons.slicer.node_attributes import TableDataOrientation
from commons.slicer import data_utils
from commons.slicer.tests.utils import process_events, wait
from unittest.mock import MagicMock


class NodeGraphDataTest(LTracePluginTest):
    def post_setup(self):
        self.pyQtObject = qt.QObject(self.parent())
        self.pySideObject = shiboken2.wrapInstance(hash(self.pyQtObject), PySide2.QtCore.QObject)

    def _createTableNode(self, data, orientation=TableDataOrientation.COLUMN):
        tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
        df = pd.DataFrame(data)
        data_utils.dataFrameToTableNode(df, tableNode)
        tableNode.SetAttribute(TableDataOrientation.name(), str(orientation.value))
        return tableNode

    def test_initialization_success(self):
        """Test successful initialization with a vtkMRMLTableNode."""
        tableNode = self._createTableNode({"A": [1, 2], "B": [3, 4]})
        graphData = NodeGraphData(parent=self.pySideObject, dataNode=tableNode)
        self.assertEqual(graphData.name, tableNode.GetName())
        self.assertIsNotNone(graphData.data)
        self.assertEqual(graphData.node.GetID(), tableNode.GetID())
        self.assertEqual(len(graphData.data), 2)  # Number of columns

    def test_initialization_fail(self):
        """Test failed initialization with an invalid node type."""
        volume_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        with self.assertRaises(ValueError):
            NodeGraphData(parent=self.pySideObject, dataNode=volume_node)

    def test_data_parsing_column_orientation(self):
        """Test data parsing with column orientation."""
        data = {"Col1": [10, 20, 30], "Col2": [1.1, 2.2, 3.3]}
        tableNode = self._createTableNode(data)
        graphData = NodeGraphData(parent=self.pySideObject, dataNode=tableNode)
        df = graphData.df()
        pd.testing.assert_frame_equal(pd.DataFrame(data).astype({"Col1": "int64", "Col2": "float64"}), df)
        self.assertEqual(list(graphData.data.item()), ["Col1", "Col2"])
        self.assertTrue(np.array_equal(graphData.data["Col1"].values, [10, 20, 30]))

    def test_data_parsing_row_orientation(self):
        """Test data parsing with row orientation (transposition)."""
        # Data where first column contains the headers
        data = {"Header": ["X", "Y"], "Val1": [10, 100], "Val2": [20, 200]}
        tableNode = self._createTableNode(data, orientation=TableDataOrientation.ROW)
        graphData = NodeGraphData(parent=self.pySideObject, dataNode=tableNode)
        df = graphData.df()
        self.assertEqual(list(df.columns), ["X", "Y"])
        self.assertTrue(np.array_equal(df["X"].values, [10, 20]))
        self.assertTrue(np.array_equal(df["Y"].values, [100, 200]))

    def test_numeric_casting(self):
        """Test automatic casting of string columns to numeric."""
        data = {"NumericStr": ["1.5", "2.5", "3.5"], "Mixed": ["a", "2", "3"]}
        tableNode = self._createTableNode(data)
        graphData = NodeGraphData(parent=self.pySideObject, dataNode=tableNode)
        df = graphData.df()
        self.assertTrue(pd.api.types.is_numeric_dtype(df["NumericStr"]))
        self.assertFalse(pd.api.types.is_numeric_dtype(df["Mixed"]))

    def test_node_modified_signal(self):
        """Test signalModified emission on node modification."""
        tableNode = self._createTableNode({"A": [1, 2]})
        graphData = NodeGraphData(parent=self.pySideObject, dataNode=tableNode)

        modifiedMock = MagicMock()
        graphData.signalModified.connect(modifiedMock)

        # Modify the node
        table = tableNode.GetTable()
        table.SetValue(0, 0, 99)
        table.Modified()
        tableNode.Modified()
        wait(1)

        modifiedMock.assert_called_once()
        self.assertEqual(graphData.data["A"][0], 99)

    def test_node_removed_signal(self):
        """Test signalRemoved emission on node removal."""
        tableNode = self._createTableNode({"A": [1, 2]})
        graphData = NodeGraphData(parent=self.pySideObject, dataNode=tableNode)

        removedMock = MagicMock()
        graphData.signalRemoved.connect(removedMock)

        slicer.mrmlScene.RemoveNode(tableNode)
        process_events()

        removedMock.assert_called_once()
        self.assertIsNone(graphData.node)
        self.assertIsNone(graphData.df())

    def test_special_handling_pore_size(self):
        """Test legacy pore_size_class handling."""
        data = {"pore_size_class": ["microporoso", "mesoporoso"]}
        tableNode = self._createTableNode(data)
        graphData = NodeGraphData(parent=self.pySideObject, dataNode=tableNode)
        df = graphData.df()

        expectedLabelCol = "pore_size_class[label]"
        self.assertIn(expectedLabelCol, df.columns)
        self.assertTrue(graphData.hasNames("pore_size_class[label]"))
        labelNames = graphData.getLabelNames(expectedLabelCol)
        self.assertTrue(np.array_equal(labelNames.values, ["microporoso", "mesoporoso"]))

    def test_visibility_signal(self):
        """Test visibility property and signal."""
        tableNode = self._createTableNode({"A": [1]})
        graphData = NodeGraphData(parent=self.pySideObject, dataNode=tableNode)

        visibleMock = MagicMock()
        graphData.signalVisibleChanged.connect(visibleMock)

        self.assertTrue(graphData.visible)
        graphData.visible = False

        visibleMock.assert_called_once_with(False)
        self.assertFalse(graphData.visible)

        # Set to same value, should not emit again
        graphData.visible = False
        visibleMock.assert_called_once()

    def test_observers_handling(self):
        """Test observers reference handling"""
        tableNode = self._createTableNode({"A": [1, 2]})
        graphData = NodeGraphData(parent=self.pySideObject, dataNode=tableNode)

        nodeObservers = graphData._NodeGraphData__observerHandlers
        assert len(nodeObservers) == 2, "Expected a total of '2' observers"

        graphData._NodeGraphData__removeObservers()
        assert len(nodeObservers) == 0, "Expected a total of '0' observers"
