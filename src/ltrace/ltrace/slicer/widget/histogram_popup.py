import qt
import slicer
import ctk

from ltrace.slicer import ui
from ltrace.slicer.widget.histogram_frame import DisplayNodeHistogramFrame


class HistogramPopupWidget(qt.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.node = None
        self.setup()
        self.setWindowFlags(qt.Qt.Tool)
        self.move(200, 200)

    def setup(self):

        contentsFrameLayout = qt.QFormLayout(self)
        contentsFrameLayout.setLabelAlignment(qt.Qt.AlignRight)
        contentsFrameLayout.setContentsMargins(0, 0, 0, 0)

        self.mainInput = ui.volumeInput(hasNone=True, onChange=self.setNode, onActivation=self.setNode)
        contentsFrameLayout.addRow("Node:", self.mainInput)

        volumesWidget = slicer.modules.volumes.createNewWidgetRepresentation()

        self.activeVolumeNodeSelector = volumesWidget.findChild(slicer.qMRMLNodeComboBox, "ActiveVolumeNodeSelector")

        volumeDisplayWidget = volumesWidget.findChild(
            slicer.qSlicerScalarVolumeDisplayWidget, "qSlicerScalarVolumeDisplayWidget"
        )

        self.windowLevelWidget = volumeDisplayWidget.findChild(slicer.qMRMLWindowLevelWidget, "MRMLWindowLevelWidget")
        window_level_combo_box = self.windowLevelWidget.findChild(qt.QComboBox, "AutoManualComboBox")
        window_level_combo_box.setCurrentIndex(2)  # Manual Min/Max
        contentsFrameLayout.addRow("Colormap limits:", self.windowLevelWidget)
        contentsFrameLayout.addRow(" ", None)

        self.thresholdWidget = volumeDisplayWidget.findChild(
            slicer.qMRMLVolumeThresholdWidget, "MRMLVolumeThresholdWidget"
        )
        autoManualComboBox = self.thresholdWidget.findChild(qt.QComboBox, "AutoManualComboBox")
        contentsFrameLayout.addRow("Threshold:", autoManualComboBox)
        self.volumeThresholdRangeWidget = self.thresholdWidget.findChild(
            ctk.ctkRangeWidget, "VolumeThresholdRangeWidget"
        )
        contentsFrameLayout.addRow("", self.volumeThresholdRangeWidget)
        contentsFrameLayout.addRow(" ", None)

        self.histogramFrame = DisplayNodeHistogramFrame(
            region_widget=self.windowLevelWidget,
            view_widget=self.thresholdWidget,
        )
        contentsFrameLayout.addRow(self.histogramFrame)

    def setNode(self, node):
        if isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
            return
        self.node = node
        previousAutoWindowLevel = self.windowLevelWidget.autoWindowLevel
        self.activeVolumeNodeSelector.setCurrentNode(node)
        self.windowLevelWidget.setAutoWindowLevel(previousAutoWindowLevel)
        self.histogramFrame.set_data(self.node)
