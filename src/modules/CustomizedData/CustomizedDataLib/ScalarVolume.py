import ctk
import qt
import slicer
from ltrace.slicer.widget.histogram_frame import DisplayNodeHistogramFrame
from ltrace.slicer.widget.labels_table_widget import LabelsTableWidget
from ltrace.slicer.helpers import (
    setVolumeVisibilityIn3D,
    getVolumeVisibilityIn3D,
    setSlicesVisibilityIn3D,
    getScalarTypesAsString,
)
from ltrace.slicer.node_attributes import ColorMapSelectable
from ltrace.slicer.helpers import tryGetNode


class ScalarVolumeWidget(qt.QWidget):
    def __init__(self, isLabelMap, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.isLabelMap = isLabelMap
        self.node = None
        self.browserID = None
        self.setup()

    def setup(self):
        contentsFrameLayout = qt.QFormLayout(self)
        contentsFrameLayout.setLabelAlignment(qt.Qt.AlignRight)
        contentsFrameLayout.setContentsMargins(0, 0, 0, 0)

        volumesWidget = slicer.modules.volumes.createNewWidgetRepresentation()
        self.sequenceModule = slicer.modules.sequences.createNewWidgetRepresentation()

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

        # Add scalar type information
        self.scalarTypeLabel = qt.QLabel("")
        self.memoryLabel = qt.QLabel("")
        sizeHBoxLayout = qt.QHBoxLayout()
        sizeHBoxLayout.addWidget(self.scalarTypeLabel)
        sizeHBoxLayout.addWidget(self.memoryLabel)
        sizeHBoxLayout.addWidget(qt.QLabel(""))
        contentsFrameLayout.addRow("Scalar Type:", sizeHBoxLayout)
        contentsFrameLayout.addRow(" ", None)

        checkBoxLayout = qt.QHBoxLayout()

        if not self.isLabelMap:
            self.interpolateCheckBox = volumeDisplayWidget.findChild(qt.QCheckBox, "InterpolateCheckbox")
            self.interpolateCheckBox.setText("Interpolate")
            checkBoxLayout.addWidget(self.interpolateCheckBox, 1)

        self.renderIn3DCheckBox = qt.QCheckBox("Render in 3D")
        self.renderIn3DCheckBox.stateChanged.connect(
            lambda state: setVolumeVisibilityIn3D(self.node, state == qt.Qt.Checked) if self.node else None
        )

        self.slicesIn3DCheckBox = qt.QCheckBox("Slices in 3D")
        self.slicesIn3DCheckBox.setChecked(True)
        self.slicesIn3DCheckBox.stateChanged.connect(lambda state: setSlicesVisibilityIn3D(state == qt.Qt.Checked))

        checkBoxLayout.addWidget(self.renderIn3DCheckBox, 1)
        checkBoxLayout.addWidget(self.slicesIn3DCheckBox, 1)

        contentsFrameLayout.addRow("", checkBoxLayout)
        contentsFrameLayout.addRow(" ", None)

        self.sequenceBrowserContainerWidget = qt.QWidget()
        sequenceBrowserLayout = qt.QFormLayout(self.sequenceBrowserContainerWidget)
        sequenceBrowserLayout.setContentsMargins(0, 0, 0, 0)

        browserButtons = self.sequenceModule.findChild(
            slicer.qMRMLSequenceBrowserPlayWidget, "sequenceBrowserPlayWidget"
        )
        browserSlider = self.sequenceModule.findChild(
            slicer.qMRMLSequenceBrowserSeekWidget, "sequenceBrowserSeekWidget"
        )

        sequenceBrowserLayout.addWidget(browserButtons)
        sequenceBrowserLayout.addWidget(browserSlider)
        self.sequenceBrowserContainerWidget.hide()
        self.sequenceLabel = qt.QLabel("Sequence controls:")
        self.sequenceLabel.hide()

        contentsFrameLayout.addRow(self.sequenceLabel, self.sequenceBrowserContainerWidget)
        contentsFrameLayout.addRow("", None)

        if self.isLabelMap:
            self.labelsTableWidget = LabelsTableWidget()
            contentsFrameLayout.addRow(self.labelsTableWidget)
        else:
            self.colorTableComboBox = volumeDisplayWidget.findChild(
                slicer.qMRMLColorTableComboBox, "ColorTableComboBox"
            )
            self.colorTableComboBox.nodeTypes = ["vtkMRMLColorTableNode"]
            self.colorTableComboBox.addAttribute(
                "vtkMRMLColorTableNode", ColorMapSelectable.name(), ColorMapSelectable.TRUE.value
            )
            contentsFrameLayout.addRow("Lookup table:", self.colorTableComboBox)
            contentsFrameLayout.addRow(" ", None)

            self.windowLevelWidget = volumeDisplayWidget.findChild(
                slicer.qMRMLWindowLevelWidget, "MRMLWindowLevelWidget"
            )
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
            contentsFrameLayout.addRow(self.histogramFrame)

    def setNode(self, node):
        self.node = node
        if self.isLabelMap:
            self.labelsTableWidget.set_labelmap_node(node)
        else:
            previousAutoWindowLevel = self.windowLevelWidget.autoWindowLevel
            self.windowLevelWidget.setAutoWindowLevel(previousAutoWindowLevel)
        self.node = node
        self.activeVolumeNodeSelector.setCurrentNode(node)
        self.renderIn3DCheckBox.setChecked(getVolumeVisibilityIn3D(node))

        browser_node = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(node)
        if browser_node:
            self.browserID = browser_node.GetID()
        else:
            self.browserID = None

        self.update()

    def update(self):
        if self.node is None:
            return
        spacing = self.node.GetSpacing()
        self.imageSpacing1LineEdit.text = f"{spacing[0]:.10g}"
        self.imageSpacing2LineEdit.text = f"{spacing[1]:.10g}"
        self.imageSpacing3LineEdit.text = f"{spacing[2]:.10g}"
        imageDimensions = self.node.GetImageData().GetDimensions()
        self.imageDimensions1LineEdit.text = imageDimensions[0]
        self.imageDimensions2LineEdit.text = imageDimensions[1]
        self.imageDimensions3LineEdit.text = imageDimensions[2]
        self.scalarTypeLabel.text = getScalarTypesAsString(self.node.GetImageData().GetScalarType())
        gibs = (
            imageDimensions[0]
            * imageDimensions[1]
            * imageDimensions[2]
            * self.node.GetImageData().GetScalarSize()
            / (1024**3)
        )
        if gibs < 1:  # less than 1 GiB. Print in MiB
            self.memoryLabel.text = "In-memory use: {:.2f}".format(gibs * 1024) + " MiB"
        else:
            self.memoryLabel.text = "In-memory use: {:.2f}".format(gibs) + " GiB"

        if not self.isLabelMap:
            self.histogramFrame.set_data(self.node)

        if self.browserID is not None:
            browserNode = tryGetNode(self.browserID)
            if browserNode:
                self.sequenceModule.setActiveBrowserNode(browserNode)
                self.sequenceBrowserContainerWidget.show()
                self.sequenceLabel.show()
        else:
            self.sequenceModule.setActiveBrowserNode(None)
            self.sequenceBrowserContainerWidget.hide()
            self.sequenceLabel.hide()
