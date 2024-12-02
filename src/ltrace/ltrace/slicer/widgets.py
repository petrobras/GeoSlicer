import qt
import ctk
import slicer
import vtk
import numpy as np
import logging
import math
import re
import traceback

from abc import abstractmethod
from functools import partial
from ltrace.slicer import ui, helpers
from ltrace.slicer.widget.dimensions_label_group import DimensionsLabelGroup, DEFAULT_DIMENSIONS_UNITS

from typing import Union, List, Tuple

from ltrace.slicer_utils import getResourcePath


def findSOISegmentID(segmentation):
    n_segments = segmentation.GetNumberOfSegments()
    for nth_segment in range(n_segments):
        segment = segmentation.GetNthSegment(nth_segment)
        sname = segment.GetName().lower()
        if re.search(r"([\.\-_]soi[\.\-_])|([\.\-_]soi$)|(^soi[\.\-_])", sname):
            return segmentation.GetNthSegmentID(nth_segment)
    return None


def isLabeledData(node):
    return isinstance(node, (slicer.vtkMRMLSegmentationNode, slicer.vtkMRMLLabelMapVolumeNode))


# Shows the selected metric input in pixels
# according to the selected node
class PixelLabel(qt.QLabel):
    def __init__(self, *, value_input, node_input, parent=None):
        super().__init__(parent)

        self.pixel_values = []
        self.pixel_size = 0
        self.current_input_value = 0

        self.value_signal = None
        self.connect_value_input(value_input)
        self.node_signal = None
        self.connect_node_input(node_input)

    def connect_value_input(self, value_input):
        old_value_signal = self.value_signal

        if isinstance(value_input, qt.QLineEdit):
            self.value_signal = value_input.textChanged
            value = value_input.text
        elif isinstance(value_input, qt.QSpinBox) or isinstance(value_input, qt.QDoubleSpinBox):
            self.value_signal = value_input.valueChanged
            value = value_input.value
        else:
            return

        if old_value_signal:
            old_value_signal.disconnect(self._value_changed)
        self.value_signal.connect(self._value_changed)
        self._value_changed(value)

    def connect_node_input(self, node_input):
        old_node_signal = self.node_signal

        if isinstance(node_input, slicer.qMRMLNodeComboBox):
            self.node_signal = node_input.currentNodeChanged
            selected = node_input.currentNode()
        elif isinstance(node_input, slicer.qMRMLSubjectHierarchyComboBox):
            self.node_signal = node_input.currentItemChanged
            selected = node_input.currentItem()
        else:
            return

        if old_node_signal:
            old_node_signal.disconnect(self._node_changed)
        self.node_signal.connect(self._node_changed)
        self._node_changed(selected)

    def get_pixel_values(self):
        return self.pixel_values

    def _node_changed(self, node):
        if isinstance(node, int):
            subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            node = subjectHierarchyNode.GetItemDataNode(node)
        if isinstance(node, slicer.vtkMRMLSegmentationNode):
            node = node.GetNodeReference("referenceImageGeometryRef")
        self.pixel_size = min([x for x in node.GetSpacing()]) if node else 0
        self._value_changed(self.current_input_value)

    def _value_changed(self, input_value):
        self.pixel_values = []
        self.current_input_value = input_value
        values_list = [v for v in str(input_value).replace(" ", "").split(",") if v.replace(".", "", 1).isdigit()]
        if not values_list or self.pixel_size == 0:
            self.setText("")
        else:
            converted_value = math.ceil(float(values_list[0]) / self.pixel_size)
            self.pixel_values.append(converted_value)
            text = f"{converted_value} px"
            for v in values_list[1:]:
                converted_value = math.ceil(float(v) / self.pixel_size)
                self.pixel_values.append(converted_value)
                text += f", {converted_value} px"
            self.setText(text)


class SingleShotInputWidget(qt.QWidget):
    segmentSelectionChanged = qt.Signal(list)
    segmentListUpdated = qt.Signal(tuple, dict)
    onMainSelectedSignal = qt.Signal(slicer.vtkMRMLVolumeNode)
    onReferenceSelectedSignal = qt.Signal(slicer.vtkMRMLVolumeNode)
    onSoiSelectedSignal = qt.Signal(slicer.vtkMRMLVolumeNode)

    MODE_NAME = "Single-Shot"

    def __init__(
        self,
        parent=None,
        hideImage=False,
        hideSoi=False,
        hideCalcProp=False,
        requireSourceVolume=True,
        allowedInputNodes=None,
        rowTitles: dict = None,
        checkable=True,
        mainName="Segmentation",
        soiName="Region (SOI)",
        referenceName="Image",
        autoReferenceFetch=True,
        setDefaultMargins=True,
        dependentInputs=("soi", "reference"),
        objectNamePrefix=None,
        dimensionsUnits=DEFAULT_DIMENSIONS_UNITS,
    ):
        super().__init__(parent)

        self.previousState = []
        self.dimensionsUnits = dimensionsUnits

        self.dependentInputs = dependentInputs

        if allowedInputNodes is None:
            allowedInputNodes = ["vtkMRMLSegmentationNode", "vtkMRMLLabelMapVolumeNode"]

        self.allowedInputNodes = allowedInputNodes

        defaultRowTitles = dict(main=mainName, soi=soiName, reference=referenceName)
        if rowTitles is not None:
            for row in defaultRowTitles:
                rowTitles[row] = rowTitles.get(row, defaultRowTitles[row])
        else:
            rowTitles = defaultRowTitles

        self.hasOverlappingLayers = False

        self.inputVoxelSize = 1

        self.formLayout = qt.QFormLayout(self)
        if setDefaultMargins:
            self.formLayout.setContentsMargins(9, 9, 9, 0)

        # This assumes ui.hierarchyVolumeInput and ui.volumeInput have compatible signatures,
        # which at the time of this writing is indeed the case

        self.mainInput = ui.hierarchyVolumeInput(
            hasNone=True,
            nodeTypes=self.allowedInputNodes,
            onChange=self._onMainSelected,
        )
        self.mainInput.setToolTip("Input image segmentation")

        self.mainInput.objectName = "Segmentation ComboBox"

        self.soiInput = ui.hierarchyVolumeInput(
            hasNone=True,
            nodeTypes=["vtkMRMLSegmentationNode"],
            onChange=self._onSOISelected,
        )
        self.soiInput.setToolTip("Segment / Region of Interest (optional)")
        self.soiInput.objectName = "SOI ComboBox"

        self.targetBox = qt.QWidget()
        targetBoxLayout = qt.QHBoxLayout(self.targetBox)
        targetBoxLayout.setContentsMargins(0, 0, 0, 0)

        self.referenceInput = ui.hierarchyVolumeInput(
            hasNone=True,
            nodeTypes=["vtkMRMLScalarVolumeNode", "vtkMRMLVectorVolumeNode"],
            onChange=self._onReferenceSelected,
        )

        self.referenceInput.resetStyleOnValidNode()

        self.referenceInput.setToolTip(
            "Base image used to set a spacial reference when the Segmentation Input "
            "is a Segmentation Node. Usually is the intensity, texture or image node."
        )
        self.referenceInput.objectName = "Image Segments ComboBox"

        self.checkable = checkable

        self.segmentListGroup = (qt.QLabel("Segments: "), qt.QListWidget())
        self.segmentListGroup[1].setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Fixed)
        self.segmentListGroup[1].setFixedHeight(120)
        self.segmentListGroup[1].hide()
        self.segmentListGroup[1].objectName = "Segment List"

        # self.editTargetButton = ActionButton("Edit", self.editTargetSegment)  # only makes sense for segments (?)

        targetBoxLayout.addWidget(self.mainInput)
        # targetBoxLayout.addWidget(self.editTargetButton)

        self.mainLabel = qt.QLabel(f'{rowTitles["main"]}: ')
        self.formLayout.addRow(self.mainLabel, self.targetBox)
        self.segmentationLabel = self.formLayout.labelForField(self.targetBox)

        self.soiLabel = qt.QLabel(f'{rowTitles["soi"]}: ')
        self.formLayout.addRow(self.soiLabel, self.soiInput)
        if hideSoi:
            self.soiLabel.hide()
            self.soiInput.hide()

        self.referenceLabel = qt.QLabel(f'{rowTitles["reference"]}: ')
        self.formLayout.addRow(self.referenceLabel, self.referenceInput)
        if hideImage:
            self.referenceLabel.hide()
            self.referenceInput.hide()
        self.requireSourceVolume = requireSourceVolume

        self.segmentsContainerWidget = ctk.ctkCollapsibleButton()
        self.segmentsContainerWidget.text = "Attributes"
        self.segmentsContainerWidget.flat = True

        segmentsLayout = qt.QFormLayout(self.segmentsContainerWidget)
        segmentsLayout.setContentsMargins(9, 9, 9, 0)
        segmentsLayout.setSpacing(6)

        segmentsLayout.addRow(self.segmentListGroup[0], self.segmentListGroup[1])

        ## start autoPorosityCalcWidget

        self.hideCalcProp = hideCalcProp

        self.autoPorosityCalcWidget = qt.QWidget()
        autoPorosityCalcLayout = qt.QHBoxLayout(self.autoPorosityCalcWidget)
        autoPorosityCalcLayout.setContentsMargins(0, 0, 0, 0)
        autoPorosityCalcLayout.setSpacing(2)

        self.autoPorosityCalcCb = qt.QCheckBox()
        self.autoPorosityCalcCb.setChecked(False)
        self.autoPorosityCalcCb.setToolTip("Enable/Disable the porosity proportion for the current input combination.")

        self.progressInput = qt.QLabel("")

        autoPorosityCalcLayout.addWidget(qt.QLabel("Calculate proportions: "))
        autoPorosityCalcLayout.addWidget(self.autoPorosityCalcCb)
        autoPorosityCalcLayout.addWidget(self.progressInput)
        autoPorosityCalcLayout.addStretch(1)
        ## end autoPorosityCalcWidget

        segmentsLayout.addRow(self.autoPorosityCalcWidget)
        self.autoPorosityCalcWidget.visible = not self.hideCalcProp

        self.segmentListGroup[1].itemChanged.connect(self.checkSelection)

        self.dimensionsGroup = DimensionsLabelGroup(parent=self, units=dimensionsUnits)
        segmentsLayout.addRow(self.dimensionsGroup)

        # initially hide those widgets
        self.segmentsContainerWidget.hide()
        self.dimensionsGroup.hide()

        self.formLayout.addRow(self.segmentsContainerWidget)

        self.soiInput.enabled = False if self.dependentInputs and "soi" in self.dependentInputs else True

        self.referenceInput.enabled = False if self.dependentInputs and "reference" in self.dependentInputs else True
        # self.editTargetButton.enabled = False

        self.autoReferenceFetch = autoReferenceFetch

        self.autoPorosityCalcCb.stateChanged.connect(self._onAutoPoreCalcToggled)

        if objectNamePrefix is not None:
            self.mainInput.objectName = f"{objectNamePrefix} {self.mainInput.objectName}"
            self.soiInput.objectName = f"{objectNamePrefix} {self.soiInput.objectName}"
            self.referenceInput.objectName = f"{objectNamePrefix} {self.referenceInput.objectName}"
            self.segmentListGroup[1].objectName = f"{objectNamePrefix} {self.segmentListGroup[1].objectName}"

    @property
    def segmentListWidget(self):
        return self.segmentListGroup[1]

    def hideSegmentList(self, value: bool = True):
        self.segmentsContainerWidget.collapsed = value

    def hasValidInputs(self) -> bool:
        return self.mainInput.currentNode() is not None or self.referenceInput.currentNode() is not None

    def resetUI(self):
        self.soiInput.enabled = False if self.dependentInputs and "soi" in self.dependentInputs else True
        self.referenceInput.enabled = False if self.dependentInputs and "reference" in self.dependentInputs else True
        self.segmentListGroup[1].clear()
        [s.hide() for s in self.segmentListGroup]
        self.dimensionsGroup.hide()

    def fullResetUI(self):
        node = self.mainInput.currentNode()
        if node is None:
            self._onMainSelected(0)
        else:
            self.mainInput.setCurrentNode(None)

    def checkSelection(self):
        selection = self.getSelectedSegments()
        if not selection:
            helpers.highlight_error(self.segmentListGroup[1])
        else:
            self.segmentListGroup[1].setStyleSheet("")
            self.segmentSelectionChanged.emit(selection)

    def segmentsOn(self):
        self.segmentListGroup[1].enabled = True
        if self.checkable and self.previousState and len(self.previousState) == self.segmentListGroup[1].count:
            for nth in range(self.segmentListGroup[1].count):
                self.segmentListGroup[1].item(nth).setCheckState(self.previousState[nth])

            self.previousState = []

    def segmentsOff(self):
        self.__saveState()
        self.segmentListGroup[1].enabled = False

        if self.checkable:
            for nth in range(self.segmentListGroup[1].count):
                self.segmentListGroup[1].item(nth).setCheckState(qt.Qt.Checked)

    def __saveState(self):
        if not self.previousState or len(self.previousState) != self.segmentListGroup[1].count:
            self.previousState = [
                self.segmentListGroup[1].item(nth).checkState() for nth in range(self.segmentListGroup[1].count)
            ]

    def getSelectedSegments(self):
        selectedItems = []
        for nth in range(self.segmentListGroup[1].count):
            if self.segmentListGroup[1].item(nth).checkState() == qt.Qt.Checked:
                selectedItems.append(nth)

        return selectedItems

    def allSegmentsSelected(self):
        return all(
            self.segmentListGroup[1].item(nth).checkState() == qt.Qt.Checked
            for nth in range(self.segmentListGroup[1].count)
        )

    def _onAutoPoreCalcToggled(self, state):
        mainNode = self.mainInput.currentNode()
        if mainNode:
            self.updateSegmentList(
                helpers.getSegmentList(
                    mainNode,
                    roiNode=self.soiInput.currentNode(),
                    refNode=self.referenceInput.currentNode(),
                    return_proportions=state,
                )
            )

    def updateRefNode(self, node):
        self.referenceInput.setCurrentNode(node)
        self.referenceInput.setStyleSheet("")

    def _onMainSelected(self, item):
        try:
            node = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(item)

            if node is None:
                self.soiInput.setCurrentNode(None)
                self.resetUI()
                if self.autoReferenceFetch:
                    self.updateRefNode(None)
                self.onMainSelectedSignal.emit(None)
                self.autoPorosityCalcWidget.hide()
                self.segmentsContainerWidget.collapsed = True
                return

            self.soiInput.enabled = True
            self.referenceInput.enabled = True
            self.hideSegmentList(False)

            if isLabeledData(node):
                referenceNode = (
                    helpers.getSourceVolume(node) if isinstance(node, slicer.vtkMRMLSegmentationNode) else node
                )
                self.segmentsContainerWidget.show()
                self.dimensionsGroup.show()
            else:
                referenceNode = node
                self.segmentListGroup[1].clear()
                self.segmentsContainerWidget.hide()
                self.dimensionsGroup.hide()

            self.autoPorosityCalcWidget.visible = not self.hideCalcProp and referenceNode is not None

            if self.autoReferenceFetch:
                self.updateRefNode(referenceNode)
            self.onMainSelectedSignal.emit(node)

            if isLabeledData(node):
                self.updateSegmentList(
                    helpers.getSegmentList(
                        node,
                        roiNode=self.soiInput.currentNode(),
                        refNode=referenceNode,
                        return_proportions=self.autoPorosityCalcCb.isChecked(),
                    )
                )  # This needs to be repeated to preserve the consistency of the new selection while also showing automatically selected segments (alternatively, delegate this role to onMainSelected functions that need it)

        except Exception as error:
            logging.debug(f"{error}:\n{traceback.print_exc()}")
            raise error

    def _onSOISelected(self, item):
        node = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(item)
        mainNode = self.mainInput.currentNode()

        # If using pre-trained classifier
        if mainNode is None:
            self.autoPorosityCalcWidget.hide()
            self.onSoiSelectedSignal.emit(node)
            return

        referenceNode = helpers.getSourceVolume(mainNode)

        try:
            if node is None:
                if isLabeledData(mainNode):
                    if self.autoPorosityCalcCb.isChecked():
                        self.progressInput.setText("Calculating Distribution...")
                        slicer.app.processEvents()

                    self.updateSegmentList(
                        helpers.getSegmentList(
                            mainNode,
                            roiNode=None,
                            refNode=referenceNode,
                            return_proportions=self.autoPorosityCalcCb.isChecked(),
                        )
                    )
                self.onSoiSelectedSignal.emit(None)
                return

            if node.GetID() == mainNode.GetID():
                slicer.util.errorDisplay(
                    "The Segment of Interest (SOI) Node must be " "different from the Segmentation input."
                )
                self.soiInput.setCurrentNode(None)
                self.onSoiSelectedSignal.emit(None)
                return

            soi = node.GetSegmentation()

            if soi.GetNumberOfSegments() > 1:
                yesOrNo = slicer.util.confirmYesNoDisplay(
                    "Segment of Interest usually is a segmentation-node with a single segment. "
                    "The selected node has more than one segment. The first one will be used "
                    "as interest region. Do you wish to continue?",
                    windowTitle="Warning",
                )
                if not yesOrNo:
                    self.soiInput.setCurrentNode(None)
                    self.onSoiSelectedSignal.emit(None)
                    return

            if isLabeledData(mainNode):
                if self.autoPorosityCalcCb.isChecked():
                    self.progressInput.setText("Calculating Distribution within SOI...")
                    slicer.app.processEvents()

                self.updateSegmentList(
                    helpers.getSegmentList(
                        mainNode,
                        roiNode=node,
                        refNode=referenceNode,
                        return_proportions=self.autoPorosityCalcCb.isChecked(),
                    )
                )

            self.onSoiSelectedSignal.emit(node)

        except TypeError as ter:
            pass  # TODO check who escapes here?
        except Exception as rex:
            logging.error(repr(rex))
        finally:
            self.progressInput.setText("")

    def _onReferenceSelected(self, _):
        try:
            mainNode = self.mainInput.currentNode()
            node = self.referenceInput.currentNode()

            if node is None and mainNode is None:
                self.onReferenceSelectedSignal.emit(None)
                return

            if node is None and mainNode and self.requireSourceVolume:
                self.segmentListGroup[1].clear()
                [s.hide() for s in self.segmentListGroup]
                self.dimensionsGroup.hide()
                self.toggleDimensions(None)
                self.onReferenceSelectedSignal.emit(None)
                # NOTE: The timer is required to move the UI change to the main thread
                self.referenceInput.blockSignals(True)
                helpers.highlight_error(self.referenceInput, "QComboBox")
                self.referenceInput.blockSignals(False)
                # qt.QTimer.singleShot(150, partial(helpers.highlight_error, self.referenceInput, "QComboBox"))
                # helpers.highlight_error(self.referenceInput)
                # slicer.util.errorDisplay("Please, select a segmentation with a valid reference volume.")
                self.autoPorosityCalcWidget.hide()
                return

            self.autoPorosityCalcWidget.visible = not self.hideCalcProp and mainNode is not None

            self.inputVoxelSize = min(np.array([i for i in node.GetSpacing()])) if node else 1

            soiNode = self.soiInput.currentNode()

            if isLabeledData(mainNode):
                if self.autoPorosityCalcCb.isChecked():
                    self.progressInput.setText("Calculating Distribution...")
                    slicer.app.processEvents()

                self.updateSegmentList(
                    helpers.getSegmentList(
                        mainNode,
                        roiNode=soiNode,
                        refNode=node,
                        return_proportions=self.autoPorosityCalcCb.isChecked(),
                    )
                )
            self.toggleDimensions(node)
            self.onReferenceSelectedSignal.emit(node)
        except Exception as rex:
            logging.error(repr(rex))
        finally:
            self.progressInput.setText("")

    def toggleDimensions(self, node):
        self.dimensionsGroup.setNode(node)
        if node:
            self.dimensionsGroup.show()
        else:
            self.dimensionsGroup.hide()

    def segmentAboutToBeModified(self, segment):
        pass

    def editTargetSegment(self):
        self.showEditTargetDialog(self.mainInput.currentNode())

    def showEditTargetDialog(self, segmentationNode):
        dialogWidget = qt.QDialog(slicer.modules.AppContextInstance.mainWindow)
        dialogWidget.setModal(True)
        dialogWidget.setWindowTitle("Edit Target")

        vertLayout = qt.QVBoxLayout(dialogWidget)

        targetSegmentSelector = slicer.qMRMLSegmentsTableView()
        targetSegmentSelector.selectionMode = qt.QAbstractItemView.ExtendedSelection
        targetSegmentSelector.headerVisible = True
        targetSegmentSelector.visibilityColumnVisible = False
        targetSegmentSelector.opacityColumnVisible = False
        targetSegmentSelector.statusColumnVisible = False
        targetSegmentSelector.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Minimum)
        targetSegmentSelector.SegmentsTableMessageLabel.hide()
        targetSegmentSelector.setMRMLScene(slicer.mrmlScene)

        targetSegmentSelector.connect("segmentAboutToBeModified ( QString )", self.segmentAboutToBeModified)
        # self.targetSegmentSelector.connect("selectionChanged(QItemSelection, QItemSelection)", self.onSegmentSelect)

        # segmentListWidget = qt.QListWidget()
        # segmentListWidget.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Fixed)
        # segmentListWidget.setFixedHeight(120)
        # segmentListWidget.hide()

        vertLayout.addWidget(targetSegmentSelector)
        # vertLayout.addWidget(segmentListWidget)

        targetSegmentSelector.setSegmentationNode(segmentationNode)

        dialogWidget.exec_()

    def updateSegmentList(self, segments):
        self.segmentListGroup[1].clear()
        self.previousState = []  # reset state

        total = segments.pop("total", 0)

        for label in segments:
            segment = segments[label]
            icon = ColoredIcon(*[int(c * 255) for c in segment["color"][:3]])
            item = qt.QListWidgetItem()
            lname = segment["name"] if segment["name"] != "invalid" else f"{label} - Unnamed"
            if "count" in segment:
                item.setText("{} = {:.5f} %".format(lname, segment["count"] * 100 / total))
            else:
                item.setText(f"{lname}")
            item.setIcon(icon)
            if self.checkable:
                item.setFlags(item.flags() | qt.Qt.ItemIsUserCheckable)
                item.setCheckState(qt.Qt.Unchecked)
            self.segmentListGroup[1].addItem(item)

        if len(segments) == 1 and self.checkable:
            self.segmentListGroup[1].item(0).setCheckState(qt.Qt.Checked)

        mainNode = self.mainInput.currentNode()
        soiNode = self.soiInput.currentNode()
        referenceNode = self.referenceInput.currentNode()
        self.segmentListUpdated.emit((mainNode, soiNode, referenceNode), segments)

        # TODO check for overlaps
        for s in self.segmentListGroup:
            s.show()

        self.dimensionsGroup.show()


def ActionButton(text, action):
    pushButton = qt.QPushButton(text)
    pushButton.setStyleSheet("QPushButton {font-weight: bold; padding: 4px;}")
    pushButton.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Preferred)
    pushButton.clicked.connect(action)
    return pushButton


def ColoredIcon(r, g, b):
    img = qt.QImage(16, 16, qt.QImage.Format_RGB32)
    p = qt.QPainter(img)
    p.fillRect(img.rect(), qt.QColor(r, g, b))
    p.end()
    return qt.QIcon(qt.QPixmap.fromImage(img))


class BatchInputWidget(qt.QWidget):
    MODE_NAME = "Batch"

    def __init__(self, parent=None, settingKey="BatchInputWidget", objectNamePrefix=None):
        super().__init__(parent)

        formLayout = qt.QFormLayout(self)

        self.onDirSelected = lambda volume: None

        self.ioFileInputLabel = qt.QLabel("Directory: ")
        self.ioFileInputLineEdit = ctk.ctkPathLineEdit()
        self.ioFileInputLineEdit.filters = ctk.ctkPathLineEdit.Dirs
        self.ioFileInputLineEdit.settingKey = settingKey
        self.ioFileInputLineEdit.objectName = "Path Line Edit"

        self.ioBatchROITagLabel = qt.QLabel("ROI Tag (.nrrd): ")
        self.ioBatchROITagPattern = qt.QLineEdit()
        self.ioBatchROITagPattern.text = "ROI"

        self.ioBatchSegTagLabel = qt.QLabel("Segmentation Tag (.nrrd): ")
        self.ioBatchSegTagPattern = qt.QLineEdit()
        self.ioBatchSegTagPattern.text = "SEG"

        self.ioBatchValTagLabel = qt.QLabel("Image Tag (.tif): ")
        self.ioBatchValTagPattern = qt.QLineEdit()
        self.ioBatchValTagPattern.text = ""

        self.ioBatchLabelLabel = qt.QLabel("Target Segment Tag: ")
        self.ioBatchLabelPattern = qt.QLineEdit()
        self.ioBatchLabelPattern.text = "Poro"

        formLayout.addRow(self.ioFileInputLabel, self.ioFileInputLineEdit)
        self.ioFileInputLineEdit.setToolTip("Select the directory where the input data/projects are saved.")
        formLayout.addRow(self.ioBatchSegTagLabel, self.ioBatchSegTagPattern)
        self.ioBatchSegTagPattern.setToolTip("Type the Tag that identifies the Segmentation.")
        formLayout.addRow(self.ioBatchROITagLabel, self.ioBatchROITagPattern)
        self.ioBatchROITagPattern.setToolTip("Type the Tag that identifies the Region (SOI) Segment of Interest.")
        formLayout.addRow(self.ioBatchValTagLabel, self.ioBatchValTagPattern)
        self.ioBatchValTagPattern.setToolTip("Type the Tag that identifies input Image.")
        formLayout.addRow(self.ioBatchLabelLabel, self.ioBatchLabelPattern)
        self.ioBatchLabelPattern.setToolTip(
            "Type the Tag that identifies the segment of the Segmentation to be inspected/partitioned."
        )
        # formLayout.addRow('Output Assets Prefix: ', self.outputPrefix)

        self.ioFileInputLineEdit.connect("currentPathChanged(QString)", self._onDirSelected)
        self.inputVoxelSize = 1  # maintain interface

        if objectNamePrefix is not None:
            self.ioFileInputLineEdit.objectName = f"{objectNamePrefix} {self.ioFileInputLineEdit.objectName}"

    def _onDirSelected(self, dirpath):
        self.onDirSelected(dirpath)


class LTraceDoubleRangeSlider(qt.QWidget):
    def __init__(self, parent=None, minimum=0, maximum=1, currentMin=0, currentMax=1, step=0.1):
        super().__init__(parent)

        self.valuesChanged = lambda a, b: None

        boxlayout = qt.QHBoxLayout(self)
        self.slider = ctk.ctkDoubleRangeSlider()
        self.slider.orientation = qt.Qt.Horizontal
        self.slider.setValues(currentMin, currentMax)
        self.slider.minimum = minimum
        self.slider.maximum = maximum
        self.slider.singleStep = step

        self.minSpinBox = qt.QDoubleSpinBox()
        self.minSpinBox.setRange(minimum, maximum)
        self.minSpinBox.value = minimum
        self.minSpinBox.singleStep = step

        self.maxSpinBox = qt.QDoubleSpinBox()
        self.maxSpinBox.setRange(minimum, maximum)
        self.maxSpinBox.value = maximum
        self.maxSpinBox.singleStep = step

        # self.slider.connect('valuesChanged(double,double)', self._onSliderChange)
        # self.minSpinBox.connect('valueChanged(double)', self._onMinSpinChange)
        # self.maxSpinBox.connect('valueChanged(double)', self._onMaxSpinChange)

        self.slider.sliderReleased.connect(self._onSliderReleased)
        self.minSpinBox.editingFinished.connect(self._onMinSpinEditFinished)
        self.maxSpinBox.editingFinished.connect(self._onMaxSpinEditFinished)

        boxlayout.addWidget(self.minSpinBox)
        boxlayout.addWidget(self.slider)
        boxlayout.addWidget(self.maxSpinBox)

    def triggerValuesChanged(self):
        self._onSliderChange(self.slider.minimumValue, self.slider.maximumValue)

    def _onSliderReleased(self):
        self._onSliderChange(self.slider.minimumValue, self.slider.maximumValue)

    def _onMinSpinEditFinished(self):
        self._onMinSpinChange(self.minSpinBox.value)

    def _onMaxSpinEditFinished(self):
        self._onMaxSpinChange(self.maxSpinBox.value)

    def _onValuesChanged(self, currentMin, currentMax):
        self.valuesChanged(currentMin, currentMax)

    def setRange(self, minimum, maximum):
        self.slider.minimum = minimum
        self.slider.maximum = maximum
        self.minSpinBox.setRange(minimum, maximum)
        self.maxSpinBox.setRange(minimum, maximum)

    def setInitState(self, minimum, maximum):
        self.slider.setValues(minimum, maximum)
        self.minSpinBox.value = minimum
        self.maxSpinBox.value = maximum

    def setStep(self, value):
        self.slider.singleStep = value
        self.minSpinBox.singleStep = value
        self.maxSpinBox.singleStep = value

    def _onSliderChange(self, minvalue, maxvalue):
        self._blockSpins()
        try:
            self.minSpinBox.value = minvalue
            self.maxSpinBox.value = maxvalue

            self._onValuesChanged(minvalue, maxvalue)
        except:
            raise
        finally:
            self._unblockSpins()

    def _onMinSpinChange(self, value):
        self._blockSlider()
        try:
            self.slider.setMinimumValue(value)
            self._onValuesChanged(value, self.maxSpinBox.value)
        except:
            raise
        finally:
            self._unblockSlider()

    def _onMaxSpinChange(self, value):
        self._blockSlider()
        try:
            self.slider.setMaximumValue(value)
            self._onValuesChanged(self.minSpinBox.value, value)
        except:
            raise
        finally:
            self._unblockSlider()

    def _blockSpins(self):
        self.minSpinBox.blockSignals(True)
        self.maxSpinBox.blockSignals(True)

    def _unblockSpins(self):
        self.minSpinBox.blockSignals(False)
        self.maxSpinBox.blockSignals(False)

    def _blockSlider(self):
        self.slider.blockSignals(True)

    def _unblockSlider(self):
        self.slider.blockSignals(False)

    # TODO Check requirement
    # def _handleSegmentationWithMultipleLayers(self, node, soiNode):
    #
    #     segmentation = node.GetSegmentation()
    #
    #     if segmentation.GetNumberOfLayers() > 0:
    #         tmpSegNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
    #         tmpSegNode.Copy(node)
    #         tmpSegNode.SetName(tmpSegNode.GetName()+'*')
    #
    #
    #         tmpSegmentation = tmpSegNode.GetSegmentation()
    #         soiSegmentId = findSOISegmentID(tmpSegmentation)
    #         if soiSegmentId:
    #             tmpSegmentation.RemoveSegment(soiSegmentId)
    #             tmpSegmentation.CollapseBinaryLabelmaps()
    #
    #             tmpSOINode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
    #             tmpSOINode.Copy(node)
    #             tmpSOINode.SetName('SOI_'+node.GetName()+'*')
    #             tmpSOISegmentation = tmpSOINode.GetSegmentation()
    #             soiSegmentIdOnTmp = findSOISegmentID(tmpSOISegmentation)
    #             n_segments = tmpSOISegmentation.GetNumberOfSegments()
    #
    #             # Select every spare segment to be removed, leaving only the SOI
    #             # TODO how to create a segment from numpy array
    #             to_remove = []
    #             for nth_segment in range(n_segments):
    #                 sid = segmentation.GetNthSegmentID(nth_segment)
    #                 if sid != soiSegmentIdOnTmp:
    #                     to_remove.append(sid)
    #
    #             # Officially remove
    #             for itemId in to_remove:
    #                 tmpSOISegmentation.RemoveSegment(itemId)
    #
    #         return tmpSegNode, tmpSOINode
    #
    #     return node, self.soiInput.currentNode()

    # def fillTargetOptions(self, node):
    #     segmentation = node.GetSegmentation()
    #     n_segments = segmentation.GetNumberOfSegments()
    #
    #     best_choice = 0
    #
    #     self.targetSegmentInput.clear()
    #     for nth_segment in range(n_segments):
    #         segment = segmentation.GetNthSegment(nth_segment)
    #         icon = ColoredIcon(*[int(c*255) for c in segment.GetColor()])
    #         name = str(segment.GetName())
    #         self.targetSegmentInput.addItem(icon, f'  {name}')
    #         lname = name.lower()
    #         if 'pore' in lname or 'poro' in lname:
    #             best_choice = nth_segment
    #
    #     self.targetSegmentInput.setCurrentIndex(best_choice)
    #
    #     self.segmentListWidget.item(best_choice).setCheckState(qt.Qt.Checked)


class BaseSettingsWidget(qt.QGroupBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @abstractmethod
    def onReferenceChanged(self, node, status):
        pass

    @abstractmethod
    def onSoiChanged(self, node):
        pass

    @abstractmethod
    def onSegmentationChanged(self, node):
        pass

    @abstractmethod
    def onModeChanged(self, mode):
        pass

    @abstractmethod
    def select(self):
        self.onSelect()

    @abstractmethod
    def toJson(self):
        return {}

    @abstractmethod
    def shrink(self):
        pass

    def getOutputInfo(self):
        return []


class InputState:
    OK = 0
    MISSING = 1


def get_input_widget_color(input_state):
    if input_state == InputState.OK:
        return None
    elif input_state == InputState.MISSING:
        return "#600000"
    else:
        return None


class ShowHideButton(qt.QPushButton):
    def __init__(self):
        super().__init__()
        self.setIconSize(qt.QSize(14, 14))
        self.setCheckable(True)
        self.toggled.connect(self.update)
        self.setChecked(True)

    def update(self):
        if self.checked:
            self.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeOpen.png"))
        else:
            self.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeClosed.png"))

    def isOpen(self):
        return self.checked == 1
