from ..BasePlotBuilder import BasePlotBuilder
from .BarPlotWidget import BarPlotWidget


class BarPlotBuilder(BasePlotBuilder):
    def __init__(self):
        super().__init__(plotWidgetClass=BarPlotWidget)
