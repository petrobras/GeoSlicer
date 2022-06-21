from ..BasePlotBuilder import BasePlotBuilder
from .HistogramInDepthPlotWidget import HistogramInDepthPlotWidget


class HistogramInDepthPlotBuilder(BasePlotBuilder):
    def __init__(self):
        super().__init__(plotWidgetClass=HistogramInDepthPlotWidget)
