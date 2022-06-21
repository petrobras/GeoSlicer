import ctk
import numpy as np
import qt
import slicer
from ltrace.lmath.filtering import DistributionFilter
from ltrace.slicer.helpers import getVolumeNullValue
from ltrace.slicer.widget.histogram_frame import DisplayNodeHistogramFrame
from ltrace.slicer.node_attributes import ColorMapSelectable
from ltrace.slicer_utils import slicer_is_in_developer_mode


class TrackImageWidget(qt.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.distribution_filter = None
        self.arraymin = None
        self.arraymax = None
        self.objectName = "Track Image Widget"
        self.setup()

    def setup(self):
        contentsFrameLayout = qt.QFormLayout(self)
        contentsFrameLayout.setLabelAlignment(qt.Qt.AlignRight)
        contentsFrameLayout.setContentsMargins(0, 0, 0, 0)

        self.scalarVolumeDisplayWidget = slicer.qSlicerScalarVolumeDisplayWidget()
        self.scalarVolumeDisplayWidget.setMRMLScene(slicer.mrmlScene)

        if slicer_is_in_developer_mode():
            devModeBox = qt.QGroupBox("Developer mode")
            devModeForm = qt.QFormLayout()

            initialDepthHBoxLayout = qt.QHBoxLayout()
            self.initialDepthLineEdit = qt.QLineEdit()
            self.initialDepthLineEdit.setReadOnly(True)
            self.finalDepthLineEdit = qt.QLineEdit()
            self.finalDepthLineEdit.setReadOnly(True)
            initialDepthHBoxLayout.addWidget(self.initialDepthLineEdit)
            initialDepthHBoxLayout.addWidget(self.finalDepthLineEdit)
            devModeForm.addRow("Depth range (m):", initialDepthHBoxLayout)

            imageDimensionsMetersHBoxLayout = qt.QHBoxLayout()
            self.imageDimensionsMeters1LineEdit = qt.QLineEdit()
            self.imageDimensionsMeters1LineEdit.setReadOnly(True)
            self.imageDimensionsMeters3LineEdit = qt.QLineEdit()
            self.imageDimensionsMeters3LineEdit.setReadOnly(True)
            imageDimensionsMetersHBoxLayout.addWidget(self.imageDimensionsMeters1LineEdit)
            imageDimensionsMetersHBoxLayout.addWidget(self.imageDimensionsMeters3LineEdit)
            devModeForm.addRow("Perimeter/Length (m):", imageDimensionsMetersHBoxLayout)

            imageDimensionsPixelsHBoxLayout = qt.QHBoxLayout()
            self.imageDimensionsPixels1LineEdit = qt.QLineEdit()
            self.imageDimensionsPixels1LineEdit.setReadOnly(True)
            self.imageDimensionsPixels3LineEdit = qt.QLineEdit()
            self.imageDimensionsPixels3LineEdit.setReadOnly(True)
            imageDimensionsPixelsHBoxLayout.addWidget(self.imageDimensionsPixels1LineEdit)
            imageDimensionsPixelsHBoxLayout.addWidget(self.imageDimensionsPixels3LineEdit)
            devModeForm.addRow("Perimeter/Length (pixels):", imageDimensionsPixelsHBoxLayout)

            spacingHBoxLayout = qt.QHBoxLayout()
            self.imageSpacing1LineEdit = qt.QLineEdit()
            self.imageSpacing1LineEdit.setReadOnly(True)
            self.imageSpacing3LineEdit = qt.QLineEdit()
            self.imageSpacing3LineEdit.setReadOnly(True)
            spacingHBoxLayout.addWidget(self.imageSpacing1LineEdit)
            spacingHBoxLayout.addWidget(self.imageSpacing3LineEdit)
            devModeForm.addRow("Pixel size (mm):", spacingHBoxLayout)

            devModeBox.setLayout(devModeForm)
            contentsFrameLayout.addRow(devModeBox)
            contentsFrameLayout.addRow(" ", None)

        self.interpolateCheckBox = self.scalarVolumeDisplayWidget.findChild(qt.QCheckBox, "InterpolateCheckbox")
        contentsFrameLayout.addRow("Interpolate:", self.interpolateCheckBox)
        contentsFrameLayout.addRow(" ", None)

        self.colorTableComboBox = self.scalarVolumeDisplayWidget.findChild(
            slicer.qMRMLColorTableComboBox, "ColorTableComboBox"
        )

        self.colorTableComboBox.nodeTypes = ["vtkMRMLColorTableNode"]
        self.colorTableComboBox.addAttribute(
            "vtkMRMLColorTableNode", ColorMapSelectable.name(), ColorMapSelectable.TRUE.value
        )
        contentsFrameLayout.addRow("Lookup table:", self.colorTableComboBox)
        contentsFrameLayout.addRow(" ", None)

        contentsFrameLayout.addWidget(self.createStdPanel())

        self.windowLevelWidget = self.scalarVolumeDisplayWidget.findChild(
            slicer.qMRMLWindowLevelWidget, "MRMLWindowLevelWidget"
        )
        self.windowLevelComboBox = self.windowLevelWidget.findChild(qt.QComboBox, "AutoManualComboBox")
        self.windowLevelComboBox.currentIndexChanged.connect(self.onWindowLevelModeChanged)
        self.setAutoWindowLevel(slicer.qMRMLWindowLevelWidget.ManualMinMax)
        contentsFrameLayout.addRow("Colormap limits:", self.windowLevelWidget)
        contentsFrameLayout.addRow(" ", None)

        self.thresholdWidget = self.scalarVolumeDisplayWidget.findChild(
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
        self.histogramFrame.view_leeway = 0.05
        self.initializedNodes = []
        contentsFrameLayout.addRow(self.histogramFrame)

    def setNode(self, node):
        self.node = node
        previousAutoWindowLevel = self.windowLevelWidget.autoWindowLevel
        self.scalarVolumeDisplayWidget.setMRMLVolumeNode(node)
        self.setAutoWindowLevel(previousAutoWindowLevel)
        self.update()

    def update(self):
        spacing = self.node.GetSpacing()
        imageDimensionsPixels = self.node.GetImageData().GetDimensions()
        imageDimensionsMeters = [imageDimensionsPixels[i] * spacing[i] / 1000 for i in range(3)]
        bounds = np.zeros(6)
        self.node.GetBounds(bounds)
        depthRange = -1 * np.array([bounds[5], bounds[4]]) / 1000
        if slicer_is_in_developer_mode():
            self.initialDepthLineEdit.text = np.around(depthRange[0], 3)
            self.finalDepthLineEdit.text = np.around(depthRange[1], 3)
            self.imageSpacing1LineEdit.text = np.around(spacing[0], 3)
            self.imageSpacing3LineEdit.text = np.around(spacing[2], 3)
            self.imageDimensionsPixels1LineEdit.text = imageDimensionsPixels[0]
            self.imageDimensionsPixels3LineEdit.text = imageDimensionsPixels[2]
            self.imageDimensionsMeters1LineEdit.text = np.around(imageDimensionsMeters[0], 3)
            self.imageDimensionsMeters3LineEdit.text = np.around(imageDimensionsMeters[2], 3)

        node_id = self.node.GetID()
        node_is_uninitialized = node_id not in self.initializedNodes
        self.histogramFrame.set_data(self.node, update_plot_auto_zoom=node_is_uninitialized)
        if node_is_uninitialized:
            self.initializedNodes.append(node_id)

        self.setAutoWindowLevel(slicer.qMRMLWindowLevelWidget.ManualMinMax)
        self.updateLimits()

        # Maintain QWidget update behavior
        qt.QWidget.update(self)

    def createStdPanel(self):
        frame = qt.QFrame()

        hBoxLayout = qt.QHBoxLayout()
        self.meanlabel = qt.QLabel("Mean:")
        hBoxLayout.addWidget(self.meanlabel)
        self.stdlabel = qt.QLabel("Std:")
        hBoxLayout.addWidget(self.stdlabel)
        self.minLabel = qt.QLabel("Min:")
        hBoxLayout.addWidget(self.minLabel)
        self.maxLabel = qt.QLabel("Max:")
        hBoxLayout.addWidget(self.maxLabel)
        hBoxLayout.setSpacing(10)
        hBoxLayout.setMargin(0)
        hBoxLayout.addStretch()

        vBoxLayout = qt.QVBoxLayout(frame)
        vBoxLayout.addLayout(hBoxLayout)
        self.stdEditField = self.createStdEditField()
        vBoxLayout.addWidget(self.stdEditField)
        return frame

    def createStdEditField(self):
        frame = qt.QFrame()
        frame.objectName = "STD Edit Field"
        formLayout = qt.QHBoxLayout(frame)
        stdHBoxLayout = qt.QHBoxLayout()
        self.stdSpinBox = qt.QDoubleSpinBox()
        stdApply = qt.QPushButton("Set")
        stdHBoxLayout.addWidget(qt.QLabel("No. of STDs: "))
        stdHBoxLayout.addWidget(self.stdSpinBox)
        stdHBoxLayout.addWidget(stdApply)
        stdHBoxLayout.setSpacing(4)
        stdHBoxLayout.setMargin(0)

        minMaxstdApply = qt.QPushButton("Use Min/Max")

        stdApply.clicked.connect(self.__on_std_apply)
        minMaxstdApply.clicked.connect(self.__apply_minmax)

        formLayout.addLayout(stdHBoxLayout)
        formLayout.addWidget(minMaxstdApply)
        formLayout.setSpacing(8)
        formLayout.setMargin(0)
        formLayout.addStretch()

        size_policy = frame.sizePolicy
        size_policy.setRetainSizeWhenHidden(True)
        frame.setSizePolicy(size_policy)
        frame.enabled = False
        return frame

    def __apply_minmax(self):
        if self.windowLevelWidget is not None:
            self.setAutoWindowLevel(slicer.qMRMLWindowLevelWidget.ManualMinMax)
            self.windowLevelWidget.setMinimumValue(self.arraymin)
            self.windowLevelWidget.setMaximumValue(self.arraymax)

    def __on_std_apply(self):
        if self.windowLevelWidget is not None:
            min_, max_ = self.distribution_filter.get_filter_min_max(self.stdSpinBox.value)
            self.setAutoWindowLevel(slicer.qMRMLWindowLevelWidget.ManualMinMax)
            self.windowLevelWidget.setMinimumValue(min_)
            self.windowLevelWidget.setMaximumValue(max_)
            self.node.GetDisplayNode().SetAttribute("num_of_stds", str(self.stdSpinBox.value))

    def updateLimits(self):
        arr_view = np.ravel(slicer.util.arrayFromVolume(self.node))
        arr_view = arr_view[arr_view != getVolumeNullValue(self.node)]

        self.distribution_filter = DistributionFilter(arr_view)

        self.arraymin = np.nanmin(arr_view)
        self.arraymax = np.nanmax(arr_view)
        self.meanlabel.setText("Mean: {:.2f}".format(self.distribution_filter.mean))
        self.stdlabel.setText("Std: {:.2f}".format(self.distribution_filter.std))
        self.minLabel.setText("Min: {:.2f}".format(self.arraymin))
        self.maxLabel.setText("Max: {:.2f}".format(self.arraymax))

        self.node.CreateDefaultDisplayNodes()
        self.stdSpinBox.value = int(float(self.node.GetDisplayNode().GetAttribute("num_of_stds") or "2"))

    def onWindowLevelModeChanged(self, window_level_mode_index):
        if self.stdEditField:
            self.stdEditField.enabled = window_level_mode_index == 2

    def setAutoWindowLevel(self, levelIndex: int) -> None:
        self.windowLevelWidget.setAutoWindowLevel(levelIndex)
        self.windowLevelComboBox.setCurrentIndex(levelIndex)

        # windowLevelComboBox doesn't emit currentIndexChanged signal when changed programmatically
        self.onWindowLevelModeChanged(levelIndex)
