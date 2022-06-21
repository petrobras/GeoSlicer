import qt
import slicer


class SegmentationWidget(qt.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup()

    def setup(self):
        contentsFrameLayout = qt.QFormLayout(self)
        contentsFrameLayout.setLabelAlignment(qt.Qt.AlignRight)
        contentsFrameLayout.setContentsMargins(0, 0, 0, 0)

        self.segmentsTableView = slicer.qMRMLSegmentsTableView()
        self.segmentsTableView.setVisibilityColumnVisible(False)
        self.segmentsTableView.setOpacityColumnVisible(False)
        self.segmentsTableView.setStatusColumnVisible(False)
        self.segmentsTableView.setReadOnly(True)
        contentsFrameLayout.addRow(self.segmentsTableView)
        self.show3DButton = slicer.qMRMLSegmentationShow3DButton()
        contentsFrameLayout.addRow(self.show3DButton)

    def setNode(self, node):
        self.segmentsTableView.setSegmentationNode(node)
        self.show3DButton.setSegmentationNode(node)
