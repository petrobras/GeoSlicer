import qt
import slicer
from ltrace.slicer.widget.proportions import ProportionsSection

from ltrace.slicer.widget.show_3d_segmentation_button import Show3DSegmentationButton


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

        contentsFrameLayout.addRow(" ", None)

        self.propsSection = ProportionsSection()

        contentsFrameLayout.addRow(self.propsSection)
        contentsFrameLayout.addRow(" ", None)

        self.show3DButton = Show3DSegmentationButton()
        contentsFrameLayout.addRow(self.show3DButton)
        self.opacitySlider = slicer.qMRMLSliderWidget()
        self.opacitySlider.maximum = 1
        self.opacitySlider.minimum = 0
        self.opacitySlider.value = 0.5
        self.opacitySlider.singleStep = 0.05
        self.opacitySlider.valueChanged.connect(lambda value: self.onOverallOpacityChanged(value))
        self.opacitySlider.toolTip = """\
            This parameter controls the overall opacity in all views of that segmentation.\
        """
        contentsFrameLayout.addRow("Overall Opacity:", self.opacitySlider)

    def onOverallOpacityChanged(self, value):
        segmentationNode = self.show3DButton.segmentationNode()
        segmentationDisplayNode = segmentationNode.GetDisplayNode()
        segmentationDisplayNode.SetOpacity(value)

    def setNode(self, node):
        self.segmentsTableView.setSegmentationNode(node)
        self.show3DButton.setSegmentationNode(node)
        segmentationDisplayNode = node.GetDisplayNode()
        if segmentationDisplayNode:
            self.opacitySlider.value = segmentationDisplayNode.GetOpacity()
        self.propsSection.setNode(node)
