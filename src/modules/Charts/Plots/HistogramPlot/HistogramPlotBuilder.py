from ..BasePlotBuilder import BasePlotBuilder
from .HistogramPlotWidget import HistogramPlotWidget


class HistogramPlotBuilder(BasePlotBuilder):
    def __init__(self):
        super().__init__(plotWidgetClass=HistogramPlotWidget)
