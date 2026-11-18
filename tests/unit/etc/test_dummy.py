from Charts.Plots.BasePlotWidget import BasePlotWidget


class TestDummy:
    """Test suite example using qt widget and pytest fixture"""

    def test_case_1(self, qtbot):
        widget = BasePlotWidget(plotLabel="label_test", plotType="type_test")
        qtbot.addWidget(widget)
        assert widget is not None

    def test_case_2(self, base_plot_widget):
        """Same as test case 1, but using the fixture on conftest"""
        assert base_plot_widget is not None
