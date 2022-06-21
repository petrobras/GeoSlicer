from ..BasePlotBuilder import BasePlotBuilder
from .CrossplotWidget import CrossplotWidget


class CrossplotBuilder(BasePlotBuilder):
    def __init__(self):
        super().__init__(plotWidgetClass=CrossplotWidget)
