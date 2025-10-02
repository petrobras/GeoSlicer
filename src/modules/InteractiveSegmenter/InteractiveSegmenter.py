import os
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget
from ltrace.interactive.seg_widget import InteractiveSegmenterFrame
from pathlib import Path

try:
    from Test.InteractiveSegmenterTest import InteractiveSegmenterTest
except ImportError:
    InteractiveSegmenterTest = None


class InteractiveSegmenterWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.interactive_segmenter_frame = InteractiveSegmenterFrame()
        self.layout.addWidget(self.interactive_segmenter_frame)
        self.layout.addStretch(1)

    def exit(self):
        self.interactive_segmenter_frame.cleanup()


class InteractiveSegmenter(LTracePlugin):
    SETTING_KEY = "InteractiveSegmenter"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Interactive Segmenter"
        self.parent.categories = ["MicroCT", "Segmentation"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = ""
