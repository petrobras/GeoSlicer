"""
View data classes. Objects of theses classes hold all the information about the current state of the Image Log views interface:
 - The type of each view (slice view or graphic view);
 - The data nodes being displayed in each view;
 - The interface state of the view controllers (which item is selected in a combo box, if the data is hidden, etc);
"""

from ltrace.slicer.graph_data import LINE_PLOT_TYPE
from ltrace.slicer.helpers import themeIsDark

PLOT_TYPE_SYMBOLS = {"―": LINE_PLOT_TYPE, "●": "o", "■": "s", "▲": "t1"}


class ViewData:
    VIEW_NAME_PREFIX = "View"

    def __init__(self, primaryNodeId=None):
        self.primaryNodeId = primaryNodeId
        self.viewControllerSettingsToolButtonToggled = True


class SliceViewData(ViewData):
    VIEW_NAME_PREFIX = "ImageLogSliceView"

    def __init__(
        self,
        primaryNodeId=None,
        segmentationNodeId=None,
        proportionsNodeId=None,
        primaryNodeHidden=False,
        segmentationNodeHidden=False,
        proportionsNodeHidden=True,
    ):
        super().__init__()
        self.primaryNodeId = primaryNodeId
        self.segmentationNodeId = segmentationNodeId
        self.proportionsNodeId = proportionsNodeId
        self.primaryNodeHidden = primaryNodeHidden
        self.segmentationNodeHidden = segmentationNodeHidden
        self.proportionsNodeHidden = proportionsNodeHidden

    def to_json(self):
        return {
            "primaryNodeId": self.primaryNodeId,
            "segmentationNodeId": self.segmentationNodeId,
            "proportionsNodeId": self.proportionsNodeId,
            "primaryNodeHidden": self.primaryNodeHidden,
            "segmentationNodeHidden": self.segmentationNodeHidden,
            "proportionsNodeHidden": self.proportionsNodeHidden,
        }


class GraphicViewData(ViewData):
    VIEW_NAME_PREFIX = "ImageLogGraphicView"

    def __init__(self):
        super().__init__()
        color = "#000000"
        self.primaryTableNodeColumnList = []
        self.primaryTableNodeColumn = ""
        self.primaryTableNodePlotType = LINE_PLOT_TYPE
        self.primaryTableNodePlotColor = color
        self.primaryTableHistogram = False
        self.primaryTableScaleHistogram = 1
        self.secondaryTableNodeId = None
        self.secondaryTableNodeColumnList = []
        self.secondaryTableNodeColumn = ""
        self.secondaryTableNodePlotType = LINE_PLOT_TYPE
        self.secondaryTableNodePlotColor = color
        self.secondaryTableHistogram = False
        self.logMode = False

    def to_json(self):
        return {
            "primaryTableNodeColumnList": self.primaryTableNodeColumnList,
            "primaryTableNodeColumn": self.primaryTableNodeColumn,
            "primaryTableNodePlotType": self.primaryTableNodePlotType,
            "primaryTableNodePlotColor": self.primaryTableNodePlotColor,
            "primaryTableHistogram": self.primaryTableHistogram,
            "primaryTableScaleHistogram": self.primaryTableScaleHistogram,
            "secondaryTableNodeId": self.secondaryTableNodeId,
            "secondaryTableNodeColumnList": self.secondaryTableNodeColumnList,
            "secondaryTableNodeColumn": self.secondaryTableNodeColumn,
            "secondaryTableNodePlotType": self.secondaryTableNodePlotType,
            "secondaryTableNodePlotColor": self.secondaryTableNodePlotColor,
            "secondaryTableHistogram": self.secondaryTableHistogram,
            "logMode": self.logMode,
        }


class EmptyViewData(ViewData):
    VIEW_NAME_PREFIX = "ImageLogEmptyView"

    def __init__(self):
        super().__init__()

    def to_json(self):
        return super().to_json()
