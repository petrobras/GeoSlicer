from SegmentInspector import SegmentInspector, SegmentInspectorWidget

try:
    from Test.ThinSectionSegmentInspectorTest import ThinSectionSegmentInspectorTest
except ImportError:
    ThinSectionSegmentInspectorTest = None


class ThinSectionSegmentInspector(SegmentInspector):
    def __init__(self, parent):
        SegmentInspector.__init__(self, parent)
        self.parent.title = "Thin Section Segment Inspector"


class ThinSectionSegmentInspectorWidget(SegmentInspectorWidget):
    def __init__(self, parent):
        SegmentInspectorWidget.__init__(self, parent)
        self.supports3D = False
