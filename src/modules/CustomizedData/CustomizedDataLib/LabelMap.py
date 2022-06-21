import qt
import slicer

from ltrace.slicer.widget.labels_table_widget import LabelsTableWidget


class LabelMapWidget(qt.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup()

    def setup(self):
        contentsFrameLayout = qt.QFormLayout(self)
        contentsFrameLayout.setLabelAlignment(qt.Qt.AlignRight)
        contentsFrameLayout.setContentsMargins(0, 0, 0, 0)

        self.labelsTableWidget = LabelsTableWidget()
        contentsFrameLayout.addRow(self.labelsTableWidget)

    def setNode(self, node):
        self.labelsTableWidget.set_labelmap_node(node)
