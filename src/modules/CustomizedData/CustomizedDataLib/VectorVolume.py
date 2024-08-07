import ctk
from ltrace.slicer.node_observer import NodeObserver
from ltrace.slicer.widget.histogram_frame import DisplayNodeHistogramFrame
from ltrace.slicer.widget.pixel_size_editor import PixelSizeEditor
from ltrace.slicer.helpers import getScalarTypesAsString
import qt
import slicer


class VectorVolumeWidget(qt.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.nodeObserver = None
        self.setup()

    def setup(self):
        contentsFrameLayout = qt.QFormLayout(self)
        contentsFrameLayout.setLabelAlignment(qt.Qt.AlignRight)
        contentsFrameLayout.setContentsMargins(0, 0, 0, 0)

        volumesWidget = slicer.modules.volumes.createNewWidgetRepresentation()
        volumesWidget.setParent(self)
        volumesWidget.hide()

        volumeDisplayWidget = volumesWidget.findChild(
            slicer.qSlicerScalarVolumeDisplayWidget, "qSlicerScalarVolumeDisplayWidget"
        )

        self.activeVolumeNodeSelector = volumesWidget.findChild(slicer.qMRMLNodeComboBox, "ActiveVolumeNodeSelector")

        imageDimensionsHBoxLayout = qt.QHBoxLayout()
        self.imageDimensions1LineEdit = qt.QLineEdit()
        self.imageDimensions1LineEdit.setReadOnly(True)
        self.imageDimensions2LineEdit = qt.QLineEdit()
        self.imageDimensions2LineEdit.setReadOnly(True)
        self.imageDimensions3LineEdit = qt.QLineEdit()
        self.imageDimensions3LineEdit.setReadOnly(True)
        imageDimensionsHBoxLayout.addWidget(self.imageDimensions1LineEdit)
        imageDimensionsHBoxLayout.addWidget(self.imageDimensions2LineEdit)
        imageDimensionsHBoxLayout.addWidget(self.imageDimensions3LineEdit)
        contentsFrameLayout.addRow("Dimensions:", imageDimensionsHBoxLayout)

        spacingHBoxLayout = qt.QHBoxLayout()
        self.imageSpacing1LineEdit = qt.QLineEdit()
        self.imageSpacing1LineEdit.setReadOnly(True)
        self.imageSpacing2LineEdit = qt.QLineEdit()
        self.imageSpacing2LineEdit.setReadOnly(True)
        self.imageSpacing3LineEdit = qt.QLineEdit()
        self.imageSpacing3LineEdit.setReadOnly(True)
        spacingHBoxLayout.addWidget(self.imageSpacing1LineEdit)
        spacingHBoxLayout.addWidget(self.imageSpacing2LineEdit)
        spacingHBoxLayout.addWidget(self.imageSpacing3LineEdit)
        contentsFrameLayout.addRow("Pixel size (mm):", spacingHBoxLayout)

        self.pixelSizeEditor = PixelSizeEditor()
        contentsFrameLayout.addRow(self.pixelSizeEditor)
        self.pixelSizeEditor.imageSpacingSet.connect(self.update)

        adjustScaleCollapsibleButton = ctk.ctkCollapsibleButton()
        adjustScaleCollapsibleButton.setText("Adjust Scale")
        adjustScaleCollapsibleButton.collapsed = True
        contentsFrameLayout.addRow(adjustScaleCollapsibleButton)
        adjustScaleFormLayout = qt.QVBoxLayout(adjustScaleCollapsibleButton)
        adjustScaleFormLayout.addWidget(self.pixelSizeEditor)

        # Add scalar type information
        self.scalarTypeLabel = qt.QLabel("")
        contentsFrameLayout.addRow("Scalar Type:", self.scalarTypeLabel)
        contentsFrameLayout.addRow(" ", None)

        self.interpolateCheckBox = volumeDisplayWidget.findChild(qt.QCheckBox, "InterpolateCheckbox")
        contentsFrameLayout.addRow("Interpolate:", self.interpolateCheckBox)
        contentsFrameLayout.addRow(" ", None)

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
            region_widget=self.windowLevelWidget, view_widget=self.thresholdWidget
        )
        self.histogramFrame.view_leeway = 0.05
        self.initializedNodes = []
        contentsFrameLayout.addRow(self.histogramFrame)

    def setNode(self, node):
        self.node = node
        self.pixelSizeEditor.currentNode = node
        self.nodeObserver = NodeObserver(node=node, parent=self)
        self.nodeObserver.modifiedSignal.connect(
            self.update
        )  # updates pixel size and dimensions labels even if they're modified out of the explorer
        self.nodeObserver.removedSignal.connect(self.onNodeRemoved)
        previousAutoWindowLevel = self.windowLevelWidget.autoWindowLevel
        self.activeVolumeNodeSelector.setCurrentNode(node)
        self.windowLevelWidget.setAutoWindowLevel(previousAutoWindowLevel)
        self.update()

    def update(self, *args, **kwargs):
        if self.node is not None:
            spacing = [f"{spacing:.10g}" for spacing in self.node.GetSpacing()]
            imageDimensions = self.node.GetImageData().GetDimensions()
            scalarTypeLabel = getScalarTypesAsString(self.node.GetImageData().GetScalarType())
        else:
            spacing = imageDimensions = ["", "", ""]
            scalarTypeLabel = ""

        self.imageSpacing1LineEdit.text = spacing[0]
        self.imageSpacing2LineEdit.text = spacing[1]
        self.imageSpacing3LineEdit.text = spacing[2]
        self.imageDimensions1LineEdit.text = imageDimensions[0]
        self.imageDimensions2LineEdit.text = imageDimensions[1]
        self.imageDimensions3LineEdit.text = imageDimensions[2]
        self.scalarTypeLabel.text = scalarTypeLabel

        if self.node is not None:
            nodeId = self.node.GetID()
            nodeIsUninitialized = nodeId not in self.initializedNodes
            self.histogramFrame.set_data(self.node, update_plot_auto_zoom=nodeIsUninitialized)
            if nodeIsUninitialized:
                self.initializedNodes.append(nodeId)

    def onNodeRemoved(self):
        if self.nodeObserver is not None:
            self.nodeObserver.clear()
            del self.nodeObserver
            self.nodeObserver = None

        self.node = None
        self.update()
