"""
View controller related classes (view popup).
"""

import ctk
import qt
import slicer

from ltrace.slicer.helpers import themeIsDark
from ltrace.slicer.node_attributes import TableType, ImageLogDataSelectable, DataOrigin
from ltrace.slicer.ui import filteredNodeComboBox
from ltrace.slicer.widget.elided_label import ElidedLabel
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer_utils import getResourcePath


class ViewControllerWidget(qt.QWidget):
    def __init__(self, logic, identifier, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logic = logic
        self.identifier = identifier
        self.setupControllerBar()

    def setupControllerBar(self):
        scaleAndControllerLayout = qt.QVBoxLayout(self)

        self.showScale = False

        scaleLabel = qt.QLabel("Horizontal/Vertical Scale: 1/1")
        scaleLabel.setObjectName("scaleLabel")
        scaleLabel.setVisible(False)
        scaleAndControllerLayout.addWidget(scaleLabel, 0, qt.Qt.AlignCenter)

        controllerBarLayout = qt.QHBoxLayout(self)
        scaleAndControllerLayout.addLayout(controllerBarLayout)

        settingsToolButton = qt.QToolButton()
        settingsToolButton.setObjectName("settingsToolButton" + str(self.identifier))
        settingsToolButton.setCheckable(True)
        settingsToolButton.setIconSize(qt.QSize(16, 16))

        iconsRes = getResourcePath("Icons")
        settingsButtonIcon = qt.QIcon()
        settingsButtonIcon.addFile(iconsRes / "png" / "PushPinIn.png", qt.QSize(), qt.QIcon.Normal, qt.QIcon.On)
        settingsButtonIcon.addFile(iconsRes / "png" / "PushPinOut.png", qt.QSize(), qt.QIcon.Normal, qt.QIcon.Off)
        settingsToolButton.setIcon(settingsButtonIcon)
        controllerBarLayout.addWidget(settingsToolButton)

        viewLabel = ElidedLabel("View " + str(self.identifier + 1))
        viewLabel.setObjectName("viewLabel" + str(self.identifier))
        viewLabel.setStyleSheet("font-size: 12px; font-weight: bold")
        viewLabel.setAlignment(qt.Qt.AlignCenter)
        # Scroll area to allow widget resize less than the total text length
        viewLabelScrollArea = qt.QScrollArea()
        viewLabelScrollArea.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        viewLabelScrollArea.setVerticalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        viewLabelScrollArea.setWidgetResizable(True)
        viewLabelScrollArea.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Fixed)
        viewLabelScrollArea.setFixedHeight(21)
        viewLabelScrollArea.setWidget(viewLabel)
        controllerBarLayout.addWidget(viewLabelScrollArea, 1)

        settingsPopup = ctk.ctkPopupWidget(settingsToolButton)
        settingsPopup.setStyleSheet(
            "ctkPopupWidget {background-color:#" f"{'000000' if themeIsDark() else 'AAAAAA'}" ";}"
        )
        settingsPopup.setObjectName("settingsPopup" + str(self.identifier))
        settingsPopup.animationEffect = 1
        # settingsPopup.alignment = qt.Qt.AlignHCenter | qt.Qt.AlignBottom
        settingsToolButton.toggled.connect(lambda toggled, settingsPopup=settingsPopup: settingsPopup.pinPopup(toggled))
        settingsToolButton.toggled.connect(
            lambda arg, identifier=self.identifier: self.logic.viewControllerSettingsToolButtonToggled(identifier)
        )
        self.settingsPopupFormLayout = qt.QFormLayout(settingsPopup)
        self.settingsPopupFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        removeViewButton = qt.QPushButton()
        removeViewButton.setToolTip("Remove this view.")
        removeViewButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Cancel.png"))
        removeViewButton.setIconSize(qt.QSize(12, 14))
        removeViewButton.clicked.connect(lambda arg, identifier=self.identifier: self.logic.removeView(identifier))
        controllerBarLayout.addWidget(removeViewButton)

        # Primary node combo box (defines the type of view to be set)
        primaryNodeFrame = qt.QFrame()
        self.primaryNodeLayout = qt.QHBoxLayout(primaryNodeFrame)
        self.primaryNodeLayout.setContentsMargins(0, 0, 0, 0)

        nodeWarning = HelpButton("Volumes marked with gray might be unable to be displayed.")

        primaryNodeComboBox = filteredNodeComboBox(
            nodeTypes=[
                "vtkMRMLScalarVolumeNode",
                "vtkMRMLTableNode",
                "vtkMRMLLabelMapVolumeNode",
                "vtkMRMLVectorVolumeNode",
            ],
        )
        primaryNodeComboBox.addAttributeFilter(TableType.name(), TableType.HISTOGRAM_IN_DEPTH.value)
        primaryNodeComboBox.addAttributeFilter(TableType.name(), TableType.MEAN_IN_DEPTH.value)
        primaryNodeComboBox.addAttributeFilter(TableType.name(), TableType.BASIC_PETROPHYSICS.value)
        primaryNodeComboBox.addAttributeFilter(TableType.name(), TableType.IMAGE_LOG.value)
        primaryNodeComboBox.addAttributeFilter(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
        primaryNodeComboBox.setObjectName("primaryNodeComboBox" + str(self.identifier))
        primaryNodeComboBox.view().setMinimumWidth(250)
        primaryNodeComboBox.nodeAboutToBeRemoved.connect(
            lambda node=primaryNodeComboBox.currentNode(), identifier=self.identifier: self.logic.onNodeAboutToBeRemoved(
                identifier, node
            )
        )
        primaryNodeComboBox.currentNodeChanged.connect(
            lambda node=primaryNodeComboBox.currentNode(), identifier=self.identifier: self.logic.primaryNodeChanged(
                identifier, node
            )
        )
        self.primaryNodeLayout.addWidget(primaryNodeComboBox, 10)
        self.primaryNodeLayout.addWidget(nodeWarning, 1)
        self.settingsPopupFormLayout.addRow("Data:", primaryNodeFrame)


class EmptyViewControllerWidget(ViewControllerWidget):
    def __init__(self, logic, identifier, *args, **kwargs):
        super().__init__(logic, identifier, *args, **kwargs)
        self.setupSettingsPopup()

    def setupSettingsPopup(self):
        """
        Specific view popup code
        """
        pass


class SliceViewControllerWidget(ViewControllerWidget):
    def __init__(self, logic, identifier, *args, **kwargs):
        super().__init__(logic, identifier, *args, **kwargs)
        self.setupSettingsPopup()

    def setupSettingsPopup(self):
        """
        Specific view popup code
        """
        # Primary node show/hide button
        showHidePrimaryNodeButton = qt.QPushButton()
        showHidePrimaryNodeButton.setCheckable(True)
        showHidePrimaryNodeButton.setObjectName("showHidePrimaryNodeButton" + str(self.identifier))
        showHidePrimaryNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "EyeOpen.png"))
        showHidePrimaryNodeButton.setIconSize(qt.QSize(14, 14))
        showHidePrimaryNodeButton.setFixedWidth(30)
        showHidePrimaryNodeButton.clicked.connect(
            lambda arg=None, identifier=self.identifier: self.logic.showHidePrimaryNode(identifier)
        )
        self.primaryNodeLayout.insertWidget(1, showHidePrimaryNodeButton)

        # Segmentation node combo box
        segmentationNodeFrame = qt.QFrame()
        self.segmentationNodeLayout = qt.QHBoxLayout(segmentationNodeFrame)
        self.segmentationNodeLayout.setContentsMargins(0, 0, 0, 0)
        segmentationNodeComboBox = slicer.qMRMLNodeComboBox()
        segmentationNodeComboBox.setObjectName("segmentationNodeComboBox" + str(self.identifier))
        segmentationNodeComboBox.nodeTypes = ["vtkMRMLSegmentationNode", "vtkMRMLLabelMapVolumeNode"]
        segmentationNodeComboBox.selectNodeUponCreation = False
        segmentationNodeComboBox.addEnabled = False
        segmentationNodeComboBox.removeEnabled = False
        segmentationNodeComboBox.noneEnabled = True
        segmentationNodeComboBox.showHidden = False
        segmentationNodeComboBox.showChildNodeTypes = False
        segmentationNodeComboBox.setMRMLScene(slicer.mrmlScene)
        segmentationNodeComboBox.children()[2].view().setMinimumWidth(250)
        segmentationNodeComboBox.nodeAboutToBeRemoved.connect(
            lambda node=segmentationNodeComboBox.currentNode(), identifier=self.identifier: self.logic.onNodeAboutToBeRemoved(
                identifier, node
            )
        )
        # Calling the Image Data Logic to let it decide the correct view to the newly selected segmentation node
        segmentationNodeComboBox.currentNodeChanged.connect(
            lambda node=segmentationNodeComboBox.currentNode(), identifier=self.identifier: self.logic.segmentationNodeChanged(
                identifier, node
            )
        )
        self.segmentationNodeLayout.addWidget(segmentationNodeComboBox)
        self.settingsPopupFormLayout.addRow("Seg:", segmentationNodeFrame)

        # Segmentation node show/hide button
        showHideSegmentationNodeButton = qt.QToolButton()
        showHideSegmentationNodeButton.setCheckable(True)
        showHideSegmentationNodeButton.setPopupMode(qt.QToolButton.MenuButtonPopup)
        showHideSegmentationNodeButton.setObjectName("showHideSegmentationNodeButton" + str(self.identifier))
        showHideSegmentationNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "EyeOpen.png"))
        showHideSegmentationNodeButton.setIconSize(qt.QSize(14, 14))
        showHideSegmentationNodeButton.setFixedWidth(30)
        showHideSegmentationNodeButton.clicked.connect(
            lambda arg=None, identifier=self.identifier: self.logic.showHideSegmentationNode(identifier)
        )

        # Segmentation node opacity slider
        self.segmentationOpacitySlider = ctk.ctkSliderWidget(self)
        self.segmentationOpacitySlider.setObjectName("segmentationOpacitySlider" + str(self.identifier))
        self.segmentationOpacitySlider.setVisible(False)
        sliderDoubleSlider = self.segmentationOpacitySlider.children()[1]
        sliderDoubleSlider.maximum = 1
        sliderDoubleSlider.singleStep = 0.01
        sliderDoubleSlider.pageStep = 0.1
        segmentationMenu = qt.QMenu("Segmentation", showHideSegmentationNodeButton)
        opacityAction = qt.QWidgetAction(self.segmentationOpacitySlider)
        opacityAction.setDefaultWidget(sliderDoubleSlider)
        segmentationMenu.addAction(opacityAction)
        showHideSegmentationNodeButton.setMenu(segmentationMenu)
        sliderDoubleSlider.valueChanged.connect(
            lambda value, arg=None, identifier=self.identifier: self.logic.changeOpacitySegmentationNode(
                identifier, value
            )
        )
        currentSegmentationOpacity = self.logic.segmentationOpacity
        sliderDoubleSlider.setValue(currentSegmentationOpacity)
        self.logic.changeOpacitySegmentationNode(self.identifier, currentSegmentationOpacity)

        self.segmentationNodeLayout.addWidget(showHideSegmentationNodeButton)

        # Proportions node information
        proportionsNodeFrame = qt.QFrame()
        proportionsNodeLayout = qt.QHBoxLayout(proportionsNodeFrame)
        proportionsNodeLayout.setContentsMargins(0, 0, 0, 0)
        proportionsNodeLineEdit = qt.QLineEdit()
        proportionsNodeLineEdit.setObjectName("proportionsNodeLineEdit" + str(self.identifier))
        proportionsNodeLineEdit.setReadOnly(True)
        proportionsNodeLayout.addWidget(proportionsNodeLineEdit)

        # Proportions node show/hide
        showHideProportionsNodeButton = qt.QPushButton()
        showHideProportionsNodeButton.setCheckable(True)
        showHideProportionsNodeButton.setObjectName("showHideProportionsNodeButton" + str(self.identifier))
        showHideProportionsNodeButton.setIconSize(qt.QSize(14, 14))
        showHideProportionsNodeButton.setFixedWidth(30)
        showHideProportionsNodeButton.clicked.connect(
            lambda arg=None, identifier=self.identifier: self.logic.showHideProportionsNode(identifier)
        )
        proportionsNodeLayout.addWidget(showHideProportionsNodeButton)
        self.settingsPopupFormLayout.addRow("Prop:", proportionsNodeFrame)


class GraphicViewControllerWidget(ViewControllerWidget):
    def __init__(self, logic, identifier, *args, **kwargs):
        super().__init__(logic, identifier, *args, **kwargs)
        self.setupSettingsPopup()

    def setupSettingsPopup(self):
        """
        Specific view popup code
        """

        # Primary table node column
        primaryTableNodeColumnComboBox = qt.QComboBox()
        primaryTableNodeColumnComboBox.view().setMinimumWidth(100)
        primaryTableNodeColumnComboBox.setObjectName("primaryTableNodeColumnComboBox" + str(self.identifier))
        primaryTableNodeColumnComboBox.currentTextChanged.connect(
            lambda arg=None, identifier=self.identifier: self.logic.primaryTableNodeColumnChanged(identifier)
        )
        self.primaryNodeLayout.addWidget(primaryTableNodeColumnComboBox, 5)
        # Primary plot type
        primaryTableNodePlotTypeComboBox = qt.QComboBox()
        primaryTableNodePlotTypeComboBox.setObjectName("primaryTableNodePlotTypeComboBox" + str(self.identifier))
        primaryTableNodePlotTypeComboBox.setFixedWidth(40)
        primaryTableNodePlotTypeComboBox.currentTextChanged.connect(
            lambda arg=None, identifier=self.identifier: self.logic.primaryTableNodePlotTypeChanged(identifier)
        )
        self.primaryNodeLayout.addWidget(primaryTableNodePlotTypeComboBox, 0)
        # Primary plot color
        primaryTableNodePlotColorPicker = ColorPickerCell(
            self, self.identifier, self.logic.primaryTableNodePlotColorChanged
        )
        primaryTableNodePlotColorPicker.setObjectName("primaryTableNodePlotColorPicker" + str(self.identifier))
        self.primaryNodeLayout.addWidget(primaryTableNodePlotColorPicker, 0)

        # Secondary table node
        secondaryTableNodeFrame = qt.QFrame()
        self.secondaryTableNodeLayout = qt.QHBoxLayout(secondaryTableNodeFrame)
        self.secondaryTableNodeLayout.setContentsMargins(0, 0, 0, 0)

        # Secondary table node node
        secondaryTableNodeComboBox = filteredNodeComboBox(["vtkMRMLTableNode"])
        secondaryTableNodeComboBox.addAttributeFilter(TableType.name(), TableType.HISTOGRAM_IN_DEPTH.value)
        secondaryTableNodeComboBox.addAttributeFilter(TableType.name(), TableType.MEAN_IN_DEPTH.value)
        secondaryTableNodeComboBox.addAttributeFilter(TableType.name(), TableType.BASIC_PETROPHYSICS.value)
        secondaryTableNodeComboBox.addAttributeFilter(TableType.name(), TableType.IMAGE_LOG.value)
        secondaryTableNodeComboBox.addAttributeFilter(DataOrigin.name(), DataOrigin.IMAGE_LOG.value)
        secondaryTableNodeComboBox.addAttributeFilter(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
        secondaryTableNodeComboBox.setObjectName("secondaryTableNodeComboBox" + str(self.identifier))
        secondaryTableNodeComboBox.view().setMinimumWidth(250)
        secondaryTableNodeComboBox.nodeAboutToBeRemoved.connect(
            lambda node=secondaryTableNodeComboBox.currentNode(), identifier=self.identifier: self.logic.onNodeAboutToBeRemoved(
                identifier, node
            )
        )
        secondaryTableNodeComboBox.currentNodeChanged.connect(
            lambda node=secondaryTableNodeComboBox.currentNode(), identifier=self.identifier: self.logic.secondaryTableNodeChanged(
                identifier, node
            )
        )
        self.secondaryTableNodeLayout.addWidget(secondaryTableNodeComboBox, 10)

        # Secondary table node column
        secondaryTableNodeColumnComboBox = qt.QComboBox()
        secondaryTableNodeColumnComboBox.view().setMinimumWidth(100)
        secondaryTableNodeColumnComboBox.setObjectName("secondaryTableNodeColumnComboBox" + str(self.identifier))
        secondaryTableNodeColumnComboBox.currentTextChanged.connect(
            lambda arg=None, identifier=self.identifier: self.logic.secondaryTableNodeColumnChanged(identifier)
        )
        self.secondaryTableNodeLayout.addWidget(secondaryTableNodeColumnComboBox, 5)

        # Secondary plot type
        secondaryTableNodePlotTypeComboBox = qt.QComboBox()
        secondaryTableNodePlotTypeComboBox.setObjectName("secondaryTableNodePlotTypeComboBox" + str(self.identifier))
        secondaryTableNodePlotTypeComboBox.setFixedWidth(40)
        secondaryTableNodePlotTypeComboBox.currentTextChanged.connect(
            lambda arg=None, identifier=self.identifier: self.logic.secondaryTableNodePlotTypeChanged(identifier)
        )
        self.secondaryTableNodeLayout.addWidget(secondaryTableNodePlotTypeComboBox, 0)

        # Secondary plot color
        secondaryTableNodePlotColorPicker = ColorPickerCell(
            self, self.identifier, self.logic.secondaryTableNodePlotColorChanged
        )
        secondaryTableNodePlotColorPicker.setObjectName("secondaryTableNodePlotColorPicker" + str(self.identifier))
        self.secondaryTableNodeLayout.addWidget(secondaryTableNodePlotColorPicker, 0)

        self.settingsPopupFormLayout.addRow("", secondaryTableNodeFrame)


class ColorPickerCell(qt.QWidget):
    def __init__(self, parent, identifier, callback, *args, color="#FFFFFF", **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.identifier = identifier
        self.callback = callback
        self.setLayout(qt.QVBoxLayout())
        self.button = qt.QPushButton("+")
        self.button.setFixedSize(20, 20)
        self.button.setStyleSheet(
            "QPushButton {"
            "font-size:11px;"
            f"color:{color};"
            f"background-color:{color};"
            "border: 2px solid #222222 }"
        )
        layout = self.layout()
        layout.addWidget(self.button)
        layout.setAlignment(qt.Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        self.histogramMode = False
        self.currentColor = color
        self.currentValue = 1.0
        self.clicked = lambda color: None

        def onClicked():
            if self.histogramMode:
                self.colorWidget = qt.QWidget()
                self.colorWidget.setWindowTitle("Select Color")
                layoutVert = qt.QVBoxLayout()
                layoutVertGroup = qt.QVBoxLayout()
                groupBox = qt.QGroupBox("Histogram Scale")
                layoutVert.addWidget(groupBox)
                self.spinBox = qt.QDoubleSpinBox()
                self.spinBox.setDecimals(2)
                self.spinBox.setRange(0.01, 10000.0)
                self.spinBox.setValue(self.currentValue)
                layoutVertGroup.addWidget(self.spinBox)
                groupBox.setLayout(layoutVertGroup)
                self.colordialog = qt.QColorDialog(qt.QColor(self.currentColor))
                self.colordialog.setOptions(qt.QColorDialog.DontUseNativeDialog)
                layoutVert.addWidget(self.colordialog)
                self.colorWidget.setLayout(layoutVert)
                self.colorWidget.show()
                self.colordialog.accepted.connect(self.okWindow)
                self.colordialog.rejected.connect(self.cancelWindow)
            else:
                color = qt.QColorDialog.getColor(qt.QColor(self.currentColor))
                if color.isValid():
                    self.button.setStyleSheet(
                        "QPushButton {"
                        "font-size:11px;"
                        f"color:{color};"
                        f"background-color:{color};"
                        "border: 2px solid #222222 }"
                    )
                    self.callback(self.identifier, color.name())

        self.button.clicked.connect(onClicked)

    def okWindow(self):
        self.colorWidget.close()  # close widget
        color = self.colordialog.selectedColor()
        self.currentValue = self.spinBox.value
        self.button.setStyleSheet(
            "QPushButton {"
            "font-size:11px;"
            f"color:{color};"
            f"background-color:{color};"
            "border: 2px solid #222222 }"
        )
        self.callback(self.identifier, color.name(), self.currentValue)

    def cancelWindow(self):
        self.colorWidget.close()  # close widget

    def setColor(self, color):
        self.button.setStyleSheet(
            "QPushButton {"
            "font-size:11px;"
            f"color:{color};"
            f"background-color:{color};"
            "border: 2px solid #222222 }"
        )
        self.currentColor = color

    def setHistogramScaleValue(self, scaleValue):
        self.currentValue = scaleValue

    def setHistogramMode(self, mode):
        self.histogramMode = mode


class ElidedLabel(qt.QLabel):
    def paintEvent(self, event):
        self.setToolTip(self.text)
        painter = qt.QPainter(self)

        metrics = qt.QFontMetrics(self.font)
        newWidth = self.width if self.parent() is None else self.parent().width
        elided = metrics.elidedText(self.text, qt.Qt.ElideRight, newWidth - 8)

        rect = self.rect
        rect.setWidth(newWidth)

        painter.drawText(rect, self.alignment, elided)
