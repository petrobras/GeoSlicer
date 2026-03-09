"""
View controller related classes (view popup).
"""

import re
import ctk
import qt
import slicer

from ltrace.slicer.helpers import themeIsDark
from ltrace.slicer.node_attributes import TableType, ImageLogDataSelectable, DataOrigin
from ltrace.slicer.ui import filteredNodeComboBox
from ltrace.slicer.widget.elided_label import ElidedLabel
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer_utils import getResourcePath
from ImageLogDataLib.viewdata.ViewData import GraphicViewData
from ImageLogDataLib.viewdata.ViewData import SliceViewData
from ImageLogDataLib.view.View import CustomPlotItem


class ViewControllerWidget(qt.QWidget):
    def __init__(self, logic, identifier, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logic = logic
        self._identifier = identifier
        self.setupControllerBar(identifier)

    @property
    def identifier(self):
        return self._identifier

    def changeIdentifier(self, new_id):
        self._identifier = new_id
        self.onIdentifierChanged(new_id)

    def setupControllerBar(self, identifier):
        scaleAndControllerLayout = qt.QVBoxLayout(self)

        self.setObjectName("viewControllerWidget")
        self.showScale = False

        scaleLabel = qt.QLabel("Horizontal/Vertical Scale: 1/1")
        scaleLabel.setObjectName("scaleLabel")
        scaleLabel.setVisible(False)
        scaleAndControllerLayout.addWidget(scaleLabel, 0, qt.Qt.AlignCenter)

        controllerBarLayout = qt.QHBoxLayout(self)
        controllerBarLayout.setObjectName("controllerBarLayout")
        scaleAndControllerLayout.addLayout(controllerBarLayout)

        self.settingsToolButton = qt.QToolButton()
        self.settingsToolButton.setObjectName("settingsToolButton" + str(self.identifier))
        self.settingsToolButton.setCheckable(True)
        self.settingsToolButton.setIconSize(qt.QSize(16, 16))

        iconsRes = getResourcePath("Icons")
        settingsButtonIcon = qt.QIcon()
        settingsButtonIcon.addFile(iconsRes / "png" / "PushPinIn.png", qt.QSize(), qt.QIcon.Normal, qt.QIcon.On)
        settingsButtonIcon.addFile(iconsRes / "png" / "PushPinOut.png", qt.QSize(), qt.QIcon.Normal, qt.QIcon.Off)
        self.settingsToolButton.setIcon(settingsButtonIcon)
        controllerBarLayout.addWidget(self.settingsToolButton)

        self.viewLabel = ElidedLabel("View " + str(self.identifier + 1))
        self.viewLabel.setToolTip("Mouse drag to reposition this view.")
        self.viewLabel.setObjectName("viewLabel" + str(self.identifier))
        self.viewLabel.setStyleSheet("font-size: 12px; font-weight: bold")
        self.viewLabel.setAlignment(qt.Qt.AlignCenter)
        self.viewLabel.setMouseTracking(True)
        self.viewLabel.setAttribute(qt.Qt.WA_TransparentForMouseEvents, False)
        self.viewLabel.setAttribute(qt.Qt.WA_Hover, True)
        self.viewLabel.installEventFilter(self.logic.dragAndDropViewEventFilter)
        # Scroll area to allow widget resize less than the total text length
        viewLabelScrollArea = qt.QScrollArea()
        viewLabelScrollArea.setObjectName("viewLabelScrollArea")
        viewLabelScrollArea.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        viewLabelScrollArea.setVerticalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        viewLabelScrollArea.setWidgetResizable(True)
        viewLabelScrollArea.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Fixed)
        viewLabelScrollArea.setFixedHeight(21)
        viewLabelScrollArea.setWidget(self.viewLabel)
        controllerBarLayout.addWidget(viewLabelScrollArea, 1)

        self.settingsPopup = ctk.ctkPopupWidget(self.settingsToolButton)
        self.settingsPopup.setStyleSheet(
            "ctkPopupWidget {background-color:#" f"{'000000' if themeIsDark() else 'AAAAAA'}" ";}"
        )
        self.settingsPopup.setObjectName("settingsPopup" + str(self.identifier))
        self.settingsPopup.installEventFilter(self.logic.dragAndDropViewEventFilter)
        self.settingsPopup.setAcceptDrops(True)
        self.settingsPopup.animationEffect = 1
        # settingsPopup.alignment = qt.Qt.AlignHCenter | qt.Qt.AlignBottom
        self.settingsToolButton.toggled.connect(self.settingsPopup.pinPopup)
        self.settingsToolButton.toggled.connect(self.onViewControllerSettingsToolButtonToggled)
        self.settingsPopupFormLayout = qt.QFormLayout(self.settingsPopup)
        self.settingsPopupFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        removeViewButton = qt.QPushButton()
        removeViewButton.setToolTip("Remove this view.")
        removeViewButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Cancel.png"))
        removeViewButton.setIconSize(qt.QSize(12, 14))
        removeViewButton.clicked.connect(self.onRemoveViewButton)
        controllerBarLayout.addWidget(removeViewButton)

        # Primary node combo box (defines the type of view to be set)
        self.primaryNodeFrame = qt.QFrame()
        self.primaryNodeFrame.setObjectName("primaryNodeFrame")
        self.primaryNodeLayout = qt.QHBoxLayout(self.primaryNodeFrame)
        self.primaryNodeLayout.setObjectName("primaryNodeLayout")
        self.primaryNodeLayout.setContentsMargins(0, 0, 0, 0)

        nodeWarning = HelpButton("Volumes marked with gray might be unable to be displayed.")

        self.primaryNodeComboBox = filteredNodeComboBox(
            nodeTypes=[
                "vtkMRMLScalarVolumeNode",
                "vtkMRMLTableNode",
                "vtkMRMLLabelMapVolumeNode",
                "vtkMRMLVectorVolumeNode",
            ],
        )
        self.primaryNodeComboBox.addAttributeFilter(TableType.name(), TableType.HISTOGRAM_IN_DEPTH.value)
        self.primaryNodeComboBox.addAttributeFilter(TableType.name(), TableType.MEAN_IN_DEPTH.value)
        self.primaryNodeComboBox.addAttributeFilter(TableType.name(), TableType.BASIC_PETROPHYSICS.value)
        self.primaryNodeComboBox.addAttributeFilter(TableType.name(), TableType.IMAGE_LOG.value)
        self.primaryNodeComboBox.addAttributeFilter(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
        self.primaryNodeComboBox.setObjectName("primaryNodeComboBox" + str(self.identifier))
        self.primaryNodeComboBox.view().setMinimumWidth(250)
        self.primaryNodeComboBox.nodeAboutToBeRemoved.connect(self.onPrimaryNodeAboutToBeRemoved)
        self.primaryNodeComboBox.currentNodeChanged.connect(self.onPrimaryNodeChanged)
        self.primaryNodeLayout.addWidget(self.primaryNodeComboBox, 10)
        self.primaryNodeLayout.addWidget(nodeWarning, 1)
        self.settingsPopupFormLayout.addRow("Data:", self.primaryNodeFrame)

    def onIdentifierChanged(self, newId):
        self.primaryNodeComboBox.setObjectName("primaryNodeComboBox" + str(newId))
        self.settingsPopup.setObjectName("settingsPopup" + str(newId))
        self.viewLabel.setObjectName("viewLabel" + str(newId))
        self.settingsToolButton.setObjectName("settingsToolButton" + str(newId))

    def onViewControllerSettingsToolButtonToggled(self):
        self.logic.viewControllerSettingsToolButtonToggled(self.identifier)

    def onRemoveViewButton(self):
        self.logic.removeView(self.identifier)

    def onPrimaryNodeAboutToBeRemoved(self):
        self.logic.onNodeAboutToBeRemoved(self.identifier, self.primaryNodeComboBox.currentNode())

    def onPrimaryNodeChanged(self):
        self.logic.primaryNodeChanged(self.identifier, self.primaryNodeComboBox.currentNode())


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
        self.showHidePrimaryNodeButton = qt.QPushButton()
        self.showHidePrimaryNodeButton.setCheckable(True)
        self.showHidePrimaryNodeButton.setObjectName("showHidePrimaryNodeButton" + str(self.identifier))
        self.showHidePrimaryNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "EyeOpen.png"))
        self.showHidePrimaryNodeButton.setIconSize(qt.QSize(14, 14))
        self.showHidePrimaryNodeButton.setFixedWidth(30)
        self.showHidePrimaryNodeButton.clicked.connect(self.onShowHidePrimaryNodeButton)

        self.primaryNodeLayout.insertWidget(1, self.showHidePrimaryNodeButton)

        # Segmentation node combo box
        segmentationNodeFrame = qt.QFrame()
        self.segmentationNodeLayout = qt.QHBoxLayout(segmentationNodeFrame)
        self.segmentationNodeLayout.setContentsMargins(0, 0, 0, 0)
        self.segmentationNodeComboBox = slicer.qMRMLNodeComboBox()
        self.segmentationNodeComboBox.setObjectName("segmentationNodeComboBox" + str(self.identifier))
        self.segmentationNodeComboBox.nodeTypes = ["vtkMRMLSegmentationNode", "vtkMRMLLabelMapVolumeNode"]
        self.segmentationNodeComboBox.selectNodeUponCreation = False
        self.segmentationNodeComboBox.addEnabled = False
        self.segmentationNodeComboBox.removeEnabled = False
        self.segmentationNodeComboBox.noneEnabled = True
        self.segmentationNodeComboBox.showHidden = False
        self.segmentationNodeComboBox.showChildNodeTypes = False
        self.segmentationNodeComboBox.setMRMLScene(slicer.mrmlScene)
        self.segmentationNodeComboBox.children()[2].view().setMinimumWidth(250)
        self.segmentationNodeComboBox.nodeAboutToBeRemoved.connect(self.onSegmentationNodeAboutToBeRemoved)

        # Calling the Image Data Logic to let it decide the correct view to the newly selected segmentation node
        self.segmentationNodeComboBox.currentNodeChanged.connect(self.onSegmentationNodeChanged)

        self.segmentationNodeLayout.addWidget(self.segmentationNodeComboBox)
        self.settingsPopupFormLayout.addRow("Seg:", segmentationNodeFrame)

        # Segmentation node show/hide button
        self.showHideSegmentationNodeButton = qt.QToolButton()
        self.showHideSegmentationNodeButton.setCheckable(True)
        self.showHideSegmentationNodeButton.setPopupMode(qt.QToolButton.MenuButtonPopup)
        self.showHideSegmentationNodeButton.setObjectName("showHideSegmentationNodeButton" + str(self.identifier))
        self.showHideSegmentationNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "EyeOpen.png"))
        self.showHideSegmentationNodeButton.setIconSize(qt.QSize(14, 14))
        self.showHideSegmentationNodeButton.setFixedWidth(30)
        self.showHideSegmentationNodeButton.clicked.connect(self.onShowHideSegmentationNodeButton)

        # Segmentation node opacity slider
        self.segmentationOpacitySlider = ctk.ctkSliderWidget(self)
        self.segmentationOpacitySlider.setObjectName("segmentationOpacitySlider" + str(self.identifier))
        self.segmentationOpacitySlider.setVisible(False)
        sliderDoubleSlider = self.segmentationOpacitySlider.children()[1]
        sliderDoubleSlider.maximum = 1
        sliderDoubleSlider.singleStep = 0.01
        sliderDoubleSlider.pageStep = 0.1
        segmentationMenu = qt.QMenu("Segmentation", self.showHideSegmentationNodeButton)
        opacityAction = qt.QWidgetAction(self.segmentationOpacitySlider)
        opacityAction.setDefaultWidget(sliderDoubleSlider)
        segmentationMenu.addAction(opacityAction)
        self.showHideSegmentationNodeButton.setMenu(segmentationMenu)
        sliderDoubleSlider.valueChanged.connect(lambda value, arg=None: self.onSliderDoubleSliderValueChanged(value))

        currentSegmentationOpacity = self.logic.segmentationOpacity
        sliderDoubleSlider.setValue(currentSegmentationOpacity)
        self.logic.changeOpacitySegmentationNode(self.identifier, currentSegmentationOpacity)

        self.segmentationNodeLayout.addWidget(self.showHideSegmentationNodeButton)

        # Proportions node information
        proportionsNodeFrame = qt.QFrame()
        proportionsNodeLayout = qt.QHBoxLayout(proportionsNodeFrame)
        proportionsNodeLayout.setContentsMargins(0, 0, 0, 0)
        self.proportionsNodeLineEdit = qt.QLineEdit()
        self.proportionsNodeLineEdit.setObjectName("proportionsNodeLineEdit" + str(self.identifier))
        self.proportionsNodeLineEdit.setReadOnly(True)
        proportionsNodeLayout.addWidget(self.proportionsNodeLineEdit)

        # Proportions node show/hide
        self.showHideProportionsNodeButton = qt.QPushButton()
        self.showHideProportionsNodeButton.setCheckable(True)
        self.showHideProportionsNodeButton.setObjectName("showHideProportionsNodeButton" + str(self.identifier))
        self.showHideProportionsNodeButton.setIconSize(qt.QSize(14, 14))
        self.showHideProportionsNodeButton.setFixedWidth(30)
        self.showHideProportionsNodeButton.clicked.connect(self.onShowHideProportionsNodeButtonClicked)
        proportionsNodeLayout.addWidget(self.showHideProportionsNodeButton)
        self.settingsPopupFormLayout.addRow("Prop:", proportionsNodeFrame)

    def onShowHidePrimaryNodeButton(self):
        self.logic.showHidePrimaryNode(self.identifier)

    def onSegmentationNodeAboutToBeRemoved(self):
        self.logic.onNodeAboutToBeRemoved(self.identifier, self.segmentationNodeComboBox.currentNode())

    def onSegmentationNodeChanged(self):
        self.logic.segmentationNodeChanged(self.identifier, self.segmentationNodeComboBox.currentNode())

    def onShowHideSegmentationNodeButton(self):
        self.logic.showHideSegmentationNode(self.identifier)

    def onSliderDoubleSliderValueChanged(self, value):
        self.logic.changeOpacitySegmentationNode(self.identifier, value)

    def onShowHideProportionsNodeButtonClicked(self):
        self.logic.showHideProportionsNode(self.identifier)

    def onIdentifierChanged(self, newIdentifier):
        self.showHideProportionsNodeButton.setObjectName("showHideProportionsNodeButton" + str(newIdentifier))
        self.proportionsNodeLineEdit.setObjectName("proportionsNodeLineEdit" + str(newIdentifier))
        self.segmentationOpacitySlider.setObjectName("segmentationOpacitySlider" + str(newIdentifier))
        self.showHideSegmentationNodeButton.setObjectName("showHideSegmentationNodeButton" + str(newIdentifier))
        self.segmentationNodeComboBox.setObjectName("segmentationNodeComboBox" + str(newIdentifier))
        self.showHidePrimaryNodeButton.setObjectName("showHidePrimaryNodeButton" + str(newIdentifier))
        super().onIdentifierChanged(newIdentifier)


class GraphicViewControllerWidget(ViewControllerWidget):
    def __init__(self, logic, identifier, *args, **kwargs):
        super().__init__(logic, identifier, *args, **kwargs)
        self.setupSettingsPopup()

    def setupSettingsPopup(self):
        """
        Specific view popup code
        """

        # Primary table node column
        self.primaryTableNodeColumnComboBox = qt.QComboBox()
        self.primaryTableNodeColumnComboBox.view().setMinimumWidth(100)
        self.primaryTableNodeColumnComboBox.setObjectName("primaryTableNodeColumnComboBox" + str(self.identifier))
        self.primaryTableNodeColumnComboBox.currentTextChanged.connect(self.onPrimaryTableNodeColumnComboBoxTextChanged)
        self.primaryNodeLayout.addWidget(self.primaryTableNodeColumnComboBox, 5)
        # Primary plot type
        self.primaryTableNodePlotTypeComboBox = qt.QComboBox()
        self.primaryTableNodePlotTypeComboBox.setObjectName("primaryTableNodePlotTypeComboBox" + str(self.identifier))
        self.primaryTableNodePlotTypeComboBox.setFixedWidth(40)
        self.primaryTableNodePlotTypeComboBox.currentTextChanged.connect(
            self.onPrimaryTableNodePlotTypeComboBoxTextChanged
        )
        self.primaryNodeLayout.addWidget(self.primaryTableNodePlotTypeComboBox, 0)
        # Primary plot color
        self.primaryTableNodePlotColorPicker = ColorPickerCell(
            self, self.identifier, self.logic.primaryTableNodePlotColorChanged
        )
        self.primaryTableNodePlotColorPicker.setObjectName("primaryTableNodePlotColorPicker" + str(self.identifier))
        self.primaryNodeLayout.addWidget(self.primaryTableNodePlotColorPicker, 0)

        # Secondary table node
        secondaryTableNodeFrame = qt.QFrame()
        self.secondaryTableNodeLayout = qt.QHBoxLayout(secondaryTableNodeFrame)
        self.secondaryTableNodeLayout.setContentsMargins(0, 0, 0, 0)

        # Secondary table node node
        self.primaryTableNodePlotColorPicker = filteredNodeComboBox(["vtkMRMLTableNode"])
        self.primaryTableNodePlotColorPicker.addAttributeFilter(TableType.name(), TableType.HISTOGRAM_IN_DEPTH.value)
        self.primaryTableNodePlotColorPicker.addAttributeFilter(TableType.name(), TableType.MEAN_IN_DEPTH.value)
        self.primaryTableNodePlotColorPicker.addAttributeFilter(TableType.name(), TableType.BASIC_PETROPHYSICS.value)
        self.primaryTableNodePlotColorPicker.addAttributeFilter(TableType.name(), TableType.IMAGE_LOG.value)
        self.primaryTableNodePlotColorPicker.addAttributeFilter(DataOrigin.name(), DataOrigin.IMAGE_LOG.value)
        self.primaryTableNodePlotColorPicker.addAttributeFilter(
            ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value
        )
        self.primaryTableNodePlotColorPicker.setObjectName("secondaryTableNodeComboBox" + str(self.identifier))
        self.primaryTableNodePlotColorPicker.view().setMinimumWidth(250)
        self.primaryTableNodePlotColorPicker.nodeAboutToBeRemoved.connect(
            self.onPrimaryTableNodePlotColorPickerToBeRemoved
        )
        self.primaryTableNodePlotColorPicker.currentNodeChanged.connect(
            self.onPrimaryTableNodePlotColorPickerNodeChanged
        )
        self.secondaryTableNodeLayout.addWidget(self.primaryTableNodePlotColorPicker, 10)

        # Secondary table node column
        self.secondaryTableNodeColumnComboBox = qt.QComboBox()
        self.secondaryTableNodeColumnComboBox.view().setMinimumWidth(100)
        self.secondaryTableNodeColumnComboBox.setObjectName("secondaryTableNodeColumnComboBox" + str(self.identifier))
        self.secondaryTableNodeColumnComboBox.currentTextChanged.connect(
            self.secondaryTableNodeColumnComboBoxTextChanged
        )
        self.secondaryTableNodeLayout.addWidget(self.secondaryTableNodeColumnComboBox, 5)

        # Secondary plot type
        self.secondaryTableNodePlotTypeComboBox = qt.QComboBox()
        self.secondaryTableNodePlotTypeComboBox.setObjectName(
            "secondaryTableNodePlotTypeComboBox" + str(self.identifier)
        )
        self.secondaryTableNodePlotTypeComboBox.setFixedWidth(40)
        self.secondaryTableNodePlotTypeComboBox.currentTextChanged.connect(
            self.secondaryTableNodePlotTypeComboBoxTextChanged
        )

        self.secondaryTableNodeLayout.addWidget(self.secondaryTableNodePlotTypeComboBox, 0)

        # Secondary plot color
        self.secondaryTableNodePlotColorPicker = ColorPickerCell(
            self, self.identifier, self.logic.secondaryTableNodePlotColorChanged
        )
        self.secondaryTableNodePlotColorPicker.setObjectName("secondaryTableNodePlotColorPicker" + str(self.identifier))
        self.secondaryTableNodeLayout.addWidget(self.secondaryTableNodePlotColorPicker, 0)

        self.settingsPopupFormLayout.addRow("", secondaryTableNodeFrame)

    def onPrimaryTableNodeColumnComboBoxTextChanged(self):
        self.logic.primaryTableNodeColumnChanged(self.identifier)

    def onPrimaryTableNodePlotTypeComboBoxTextChanged(self):
        self.logic.primaryTableNodePlotTypeChanged(self.identifier)

    def onPrimaryTableNodePlotColorPickerToBeRemoved(self):
        self.logic.onNodeAboutToBeRemoved(self.identifier, self.primaryTableNodePlotColorPicker.currentNode())

    def onPrimaryTableNodePlotColorPickerNodeChanged(self):
        self.logic.secondaryTableNodeChanged(self.identifier, self.primaryTableNodePlotColorPicker.currentNode())

    def secondaryTableNodeColumnComboBoxTextChanged(self):
        self.logic.secondaryTableNodeColumnChanged(self.identifier)

    def secondaryTableNodePlotTypeComboBoxTextChanged(self):
        self.logic.secondaryTableNodePlotTypeChanged(self.identifier)

    # Identifier has to be synchronized in the children which also have one
    def onIdentifierChanged(self, newId):
        self.primaryTableNodeColumnComboBox.setObjectName("primaryTableNodeColumnComboBox" + str(newId))
        self.primaryTableNodePlotTypeComboBox.setObjectName("primaryTableNodePlotTypeComboBox" + str(newId))
        self.primaryTableNodePlotColorPicker.setObjectName("primaryTableNodePlotColorPicker" + str(newId))
        self.primaryTableNodePlotColorPicker.identifier = newId
        self.secondaryTableNodeColumnComboBox.setObjectName("secondaryTableNodeColumnComboBox" + str(newId))
        self.secondaryTableNodePlotTypeComboBox.setObjectName("secondaryTableNodePlotTypeComboBox" + str(newId))
        self.secondaryTableNodePlotColorPicker.setObjectName("secondaryTableNodePlotColorPicker" + str(newId))
        self.secondaryTableNodePlotColorPicker.identifier = newId
        super().onIdentifierChanged(newId)


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
    def event(self, event):
        if event.type() == qt.QEvent.Paint:
            painter = qt.QPainter(self)

            metrics = qt.QFontMetrics(self.font)
            newWidth = self.width if self.parent() is None else self.parent().width
            elided = metrics.elidedText(self.text, qt.Qt.ElideRight, newWidth - 8)

            rect = self.rect
            rect.setWidth(newWidth)
        elif event.type() == qt.QEvent.HoverEnter:
            current_override = qt.QApplication.overrideCursor()
            if current_override is None or current_override.shape() != qt.Qt.OpenHandCursor:
                qt.QApplication.setOverrideCursor(qt.Qt.OpenHandCursor)
        elif event.type() == qt.QEvent.HoverLeave:
            if qt.QApplication.overrideCursor() is not None:
                qt.QApplication.restoreOverrideCursor()
        elif event.type() == qt.QEvent.MouseButtonPress:
            posMouse = qt.QCursor().pos()
            imageLogDataLogic = slicer.util.getModuleLogic("ImageLogData")
            dragViewManager = imageLogDataLogic.dragViewManager
            viewIdUnderMouse = int(re.search(r"\d+$", self.objectName).group())  # "viewLabelN"
            if viewIdUnderMouse >= 0:
                drag = qt.QDrag(self)
                mimeData = qt.QMimeData()
                mimeData.setText("draggingView" + str(viewIdUnderMouse))
                drag.setMimeData(mimeData)
                drag.setDragCursor(qt.QCursor(qt.Qt.ClosedHandCursor).pixmap(), qt.Qt.MoveAction)
                dragViewManager.viewsIdentifiersFromTo[0] = viewIdUnderMouse
                viewWidgetUnderMouse = imageLogDataLogic.viewWidgets[viewIdUnderMouse]
                geom = viewWidgetUnderMouse.geometry
                dragViewManager.logViewScreenshot.setGeometry(
                    posMouse.x() + 10, posMouse.y() + 10, geom.width(), geom.height()
                )
                if type(imageLogDataLogic.imageLogViewList[viewIdUnderMouse].viewData) is SliceViewData:
                    dragViewManager.captureVtkAndDisplay(
                        slicer.app.layoutManager()
                        .sliceWidget(f"ImageLogSliceView{viewIdUnderMouse}")
                        .sliceView()
                        .renderWindow()
                    )
                elif type(imageLogDataLogic.imageLogViewList[viewIdUnderMouse].viewData) is GraphicViewData:
                    plotItem = slicer.util.getModuleWidget("ImageLogData").getGraphicViewPlotItem(viewIdUnderMouse)
                    dragViewManager.capturePyqtgraphAndDisplay(plotItem, geom.width(), geom.height(), imageLogDataLogic)
                else:
                    dragViewManager.displayEmpty()
                dragViewManager.logViewScreenshot.show()
                drag.exec_(qt.Qt.MoveAction)

        return qt.QLabel.event(self, event)
