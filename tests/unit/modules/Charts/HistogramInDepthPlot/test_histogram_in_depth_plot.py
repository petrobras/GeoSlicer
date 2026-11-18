from unittest.mock import Mock, patch, MagicMock, ANY, call
from Charts.Plots.HistogramPlot.HistogramPlotWidgetModel import HistogramPlotWidgetModel

import pytest


class TestHistogramInDepthPlotWidgetModel:
    def test_append_data_none_type(self, base_plot_widget):
        self.model = HistogramPlotWidgetModel(widget=base_plot_widget)
        assert isinstance(self.model, HistogramPlotWidgetModel)
        with pytest.raises(ValueError):
            self.model.appendData(None)

        assert len(self.model.graphDataList) == 0

    @patch("Charts.Plots.HistogramPlot.HistogramPlotWidgetModel.NodeGraphData")
    def test_append_data_table_node(self, graph_data):
        self.model = HistogramPlotWidgetModel(widget=Mock())
        assert isinstance(self.model, HistogramPlotWidgetModel)
        table_node = Mock(name="slicer.vtkMRMLTableNode")
        graph_data.signalVisibleChanged.connect = MagicMock()
        self.model.appendData(table_node)
        assert len(self.model.graphDataList) == 1

        calls = [
            call().signalVisibleChanged.connect(ANY),
            call().signalModified.connect(ANY),
            call().signalRemoved.connect(ANY),
        ]
        graph_data.assert_has_calls(calls, any_order=True)
        assert len(graph_data.mock_calls) == 4

        graph_data.reset_mock()
        self.model.appendData(table_node)
        # Try append same object twice, but the model wont accept
        assert len(self.model.graphDataList) == 1
        with pytest.raises(AssertionError):
            graph_data.assert_has_calls(calls, any_order=True)  # Assert that the signal calls weren't made
