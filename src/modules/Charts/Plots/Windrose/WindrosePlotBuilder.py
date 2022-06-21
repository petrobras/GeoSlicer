from ..BasePlotBuilder import BasePlotBuilder
from .WindroseWidget import WindroseWidget


class WindrosePlotBuilder(BasePlotBuilder):
    def __init__(self):
        super().__init__(plotWidgetClass=WindroseWidget)
