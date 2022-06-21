import os
from pathlib import Path

import ctk
import cv2
import numpy as np
import qt
import slicer
import vtk
from Customizer import Customizer

import ImageLogInstanceSegmenter
from InstanceSegmenterEditorLib.widget.FilterableTableWidgets import (
    GenericTableWidget,
)
from InstanceSegmenterEditorLib.widget.FilterableTableWidgets import SidewallSampleTableWidget, StopsTableWidget
from ltrace.algorithms.measurements import (
    sidewall_sample_instance_properties,
    generic_instance_properties,
    instance_depth,
)
from ltrace.algorithms.stops import fit_line
from ltrace.slicer.helpers import highlight_error, reset_style_on_valid_text
from ltrace.slicer.node_attributes import ImageLogDataSelectable
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer_utils import dataFrameToTableNode
from ltrace.transforms import transformPoints


class InstanceSegmenterEditor(LTracePlugin):
    SETTING_KEY = "InstanceSegmenterEditor"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Image Log Instance Segmenter Editor"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = InstanceSegmenterEditor.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class InstanceSegmenterEditorWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.editedRow = False
        self.labelMapObserverID = None

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = InstanceSegmenterEditorLogic()
        self.logic.viewsRefreshed.connect(self.updateWarning)

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        # Input section
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        formLayout.addRow(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.inputTableNodeComboBox = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLTableNode"], onChange=self.onInputTableNodeChanged
        )
        # self.inputTableNodeComboBox.addNodeAttributeFilter("InstanceSegmenter")
        self.inputTableNodeComboBox.setToolTip("Select the instance segmenter report table.")
        self.inputTableNodeComboBox.resetStyleOnValidNode()
        inputFormLayout.addRow("Report table:", self.inputTableNodeComboBox)
        inputFormLayout.addRow(" ", None)

        self.warningLabel = qt.QLabel()
        self.warningLabel.visible = False
        self.warningLabel.setStyleSheet("QLabel {color: yellow}")
        inputFormLayout.addRow(self.warningLabel)

        # Filter section
        self.parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        self.parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(self.parametersCollapsibleButton)
        self.parametersFormLayout = qt.QFormLayout(self.parametersCollapsibleButton)

        self.tableWidget = None
        self.parametersCollapsibleButton.setVisible(False)
        self.parametersCollapsibleButton.clicked.connect(self.onParametersCollapsibleButtonClicked)

        # Edit section
        self.editCollapsibleButton = ctk.ctkCollapsibleButton()
        self.editCollapsibleButton.setText("Edit")
        self.editCollapsibleButton.collapsed = True
        self.editCollapsibleButton.setVisible(False)
        formLayout.addRow(self.editCollapsibleButton)
        editFormLayout = qt.QFormLayout(self.editCollapsibleButton)

        self.addSegmentButton = qt.QPushButton("Add")
        self.addSegmentButton.setIcon(qt.QIcon(str(Customizer.ADD_ICON_PATH)))
        self.addSegmentButton.clicked.connect(self.onAddSegmentButtonClicked)

        self.editSegmentButton = qt.QPushButton("Edit")
        self.editSegmentButton.setIcon(qt.QIcon(str(Customizer.EDIT_ICON_PATH)))
        self.editSegmentButton.clicked.connect(self.onEditSegmentButtonClicked)

        self.applySegmentButton = qt.QPushButton("Apply")
        self.applySegmentButton.setIcon(qt.QIcon(str(Customizer.APPLY_ICON_PATH)))
        self.applySegmentButton.setEnabled(False)
        self.applySegmentButton.clicked.connect(self.onApplySegmentButtonClicked)

        self.cancelSegmentButton = qt.QPushButton("Cancel")
        self.cancelSegmentButton.setIcon(qt.QIcon(str(Customizer.CANCEL_ICON_PATH)))
        self.cancelSegmentButton.setEnabled(False)
        self.cancelSegmentButton.clicked.connect(self.onCancelSegmentButtonClicked)

        self.declineSegmentButton = qt.QPushButton("Decline")
        self.declineSegmentButton.setIcon(qt.QIcon(str(Customizer.DELETE_ICON_PATH)))
        self.declineSegmentButton.clicked.connect(self.onDeclineSegmentButtonClicked)

        editButtonsHBoxLayout = qt.QHBoxLayout()
        editButtonsHBoxLayout.addWidget(self.addSegmentButton)
        editButtonsHBoxLayout.addWidget(self.editSegmentButton)
        editButtonsHBoxLayout.addWidget(self.declineSegmentButton)
        editButtonsHBoxLayout.addWidget(self.applySegmentButton)
        editButtonsHBoxLayout.addWidget(self.cancelSegmentButton)
        editFormLayout.addRow(editButtonsHBoxLayout)

        brushSizeSlider = ctk.ctkSliderWidget()
        brushSizeSlider.decimals = 0
        brushSizeSlider.minimum = 1
        brushSizeSlider.maximum = 16
        brushSizeSlider.tracking = False
        brushSizeSlider.valueChanged.connect(self.onBrushSizeChanged)
        brushSizeSlider.setValue(4)
        editFormLayout.addRow("Brush size:", brushSizeSlider)
        editFormLayout.addRow(" ", None)

        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.outputSuffixLineEdit = qt.QLineEdit("Edited")
        outputFormLayout.addRow("Output suffix:", self.outputSuffixLineEdit)
        outputFormLayout.addRow(" ", None)
        reset_style_on_valid_text(self.outputSuffixLineEdit)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setFixedHeight(40)
        self.applyButton.clicked.connect(self.onApplyButtonClicked)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.applyButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        formLayout.addRow(buttonsHBoxLayout)

        self.spacerItem = qt.QSpacerItem(10, 10, qt.QSizePolicy.Minimum, qt.QSizePolicy.Expanding)
        self.layout.addItem(self.spacerItem)

    def onBrushSizeChanged(self, value):
        self.logic.setBrushSize(value)

    def onDeclineSegmentButtonClicked(self):
        tableView = self.tableWidget.tableView
        selectedIndexes = tableView.selectedIndexes()
        if len(selectedIndexes) > 0:
            message = "Are you sure you want to decline the selected segment?"
            if slicer.util.confirmYesNoDisplay(message):
                model = tableView.model()
                label = int(selectedIndexes[model.labelIndex()].data())
                self.logic.declineLabel(model._data, label)
                model.removeRow(selectedIndexes[0].row())
        else:
            slicer.util.infoDisplay("Please select an instance from the table.")

        self.tableWidget.setAllRangeWidgetValues(resetValues=False)
        self.tableWidget.filterValuesChanged()

    def onAddSegmentButtonClicked(self):
        self.editedRow = "Add"
        self.addSegmentButton.setEnabled(False)
        self.editSegmentButton.setEnabled(False)
        self.declineSegmentButton.setEnabled(False)
        self.cancelSegmentButton.setEnabled(True)

        dataFrame = self.tableWidget.pandasTableModel._data
        lastLabelValue = max(dataFrame["label"])
        self.logic.addOrEditSegment(lastLabelValue + 1)

        observerID = self.logic.labelMapNode.AddObserver("ModifiedEvent", self.onLabelMapModified)
        self.labelMapObserverID = observerID

    def onEditSegmentButtonClicked(self):
        selectedIndexes = self.tableWidget.tableView.selectedIndexes()
        if len(selectedIndexes) > 0:
            self.editedRow = selectedIndexes[0].row()
            self.addSegmentButton.setEnabled(False)
            self.editSegmentButton.setEnabled(False)
            self.declineSegmentButton.setEnabled(False)
            self.cancelSegmentButton.setEnabled(True)

            tableView = self.tableWidget.tableView
            selectedIndexes = tableView.selectedIndexes()
            originalLabel = int(selectedIndexes[tableView.model().labelIndex()].data())

            dataFrame = self.tableWidget.pandasTableModel._data
            lastLabelValue = max(dataFrame["label"])
            self.logic.addOrEditSegment(lastLabelValue + 1, originalLabel=originalLabel)

            observerID = self.logic.labelMapNode.AddObserver("ModifiedEvent", self.onLabelMapModified)
            self.labelMapObserverID = observerID
        else:
            slicer.util.infoDisplay("Please select an instance from the table.")

    def onLabelMapModified(self, caller, event):
        self.applySegmentButton.setEnabled(True)

    def onApplySegmentButtonClicked(self):
        rowData = self.logic.applySegment()

        if rowData is None:
            slicer.util.infoDisplay("A segment can not be empty. Cancelling.")
            self.onCancelSegmentButtonClicked()
            return

        self.logic.labelMapNode.RemoveObserver(self.labelMapObserverID)
        self.labelMapObserverID = None

        self.addSegmentButton.setEnabled(True)
        self.editSegmentButton.setEnabled(True)
        self.declineSegmentButton.setEnabled(True)
        self.applySegmentButton.setEnabled(False)
        self.cancelSegmentButton.setEnabled(False)

        model = self.tableWidget.tableView.model()

        if self.editedRow == "Add":
            model.addRow(rowData)
            model.sortDefault()
            row = model.getRowByLabel(rowData["label"])
            self.tableWidget.tableView.setCurrentIndex(model.index(row, 0))
        else:
            if "sidewall_sample" in self.logic.getInstanceType():
                del rowData["n depth (m)"]
                del rowData["desc"]
                del rowData["cond"]
            model.editRow(self.editedRow, rowData)

        # To center the added or edited element both in the table view and slice view
        self.tableWidget.reselectCurrentItem()

        self.tableWidget.setAllRangeWidgetValues(resetValues=False)
        self.tableWidget.filterValuesChanged()
        self.editedRow = False

        # self.tableWidget.tableView.model().sortDefault() @TODO reactivate this after implementing sortproxymodel

        # self.logic.removeOrphanLabels(model._data)

    def onCancelSegmentButtonClicked(self):
        self.logic.cancelSegment()

        self.logic.labelMapNode.RemoveObserver(self.labelMapObserverID)
        self.labelMapObserverID = None

        self.addSegmentButton.setEnabled(True)
        self.editSegmentButton.setEnabled(True)
        self.declineSegmentButton.setEnabled(True)
        self.applySegmentButton.setEnabled(False)
        self.cancelSegmentButton.setEnabled(False)

    def onApplyButtonClicked(self):
        # If a segment is still being edited, show a message to let the user decide what he wants to do
        if self.applySegmentButton.enabled == True:
            slicer.util.infoDisplay("A segment is currently being edited. Please finish it by applying or cancelling.")
            return

        try:
            if self.inputTableNodeComboBox.currentNode() is None:
                highlight_error(self.inputTableNodeComboBox)
                return
            if self.outputSuffixLineEdit.text.strip() == "":
                highlight_error(self.outputSuffixLineEdit)
                return

            dataFrame = self.tableWidget.pandasTableModel._data
            self.logic.apply(dataFrame, self.outputSuffixLineEdit.text)
            self.inputTableNodeComboBox.setCurrentNode(None)
        except InstanceSegmenterEditorInfo as e:
            slicer.util.infoDisplay(str(e))
            return

    def onCancelButtonClicked(self):
        # If a segment is still being edited, cancel it before cancelling everything
        if self.editedRow:
            self.cancelSegmentButton.click()
        self.logic.cancel()
        self.inputTableNodeComboBox.setCurrentNode(None)

    def onParametersCollapsibleButtonClicked(self):
        if self.parametersCollapsibleButton.collapsed:
            self.layout.addItem(self.spacerItem)
        else:
            self.layout.removeItem(self.spacerItem)

    def onInputTableNodeChanged(self, itemId):
        self.warningLabel.visible = False
        self.logic.restoreLabelMapNode()

        self.layout.removeItem(self.spacerItem)
        self.parametersCollapsibleButton.setVisible(False)
        self.editCollapsibleButton.setVisible(False)

        tableNode = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(itemId)
        if tableNode:
            if tableNode.GetAttribute("InstanceSegmenter") is None:
                self.updateWarning()
                self.layout.addItem(self.spacerItem)
                return

            self.logic.setTableNode(tableNode)

            if self.tableWidget:
                self.parametersFormLayout.removeWidget(self.tableWidget)
                self.tableWidget.deleteLater()

            instanceType = self.logic.getInstanceType()
            if "sidewall_sample" in instanceType:
                self.tableWidget = SidewallSampleTableWidget(self.logic)
            elif ImageLogInstanceSegmenter.MODEL_IMAGE_LOG_STOPS in instanceType:
                self.tableWidget = StopsTableWidget(self.logic)
            else:
                self.tableWidget = GenericTableWidget(self.logic)
            self.tableWidget.setTableNode(tableNode)

            self.parametersFormLayout.addRow(self.tableWidget)
            self.parametersFormLayout.addRow(None)

            self.parametersCollapsibleButton.setVisible(True)
            self.editCollapsibleButton.setVisible(True)

            self.tableWidget.tableView.model().sortDefault()
        else:
            self.layout.addItem(self.spacerItem)
        self.updateWarning()

    def enter(self) -> None:
        super().enter()
        if self.logic.saveObserver is None:
            self.logic.saveObserver = slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartSaveEvent, self.onStartSave)

    def onStartSave(self, *args):
        self.onCancelButtonClicked()
        slicer.app.processEvents()

    def updateWarning(self):
        currentNode = self.inputTableNodeComboBox.currentNode()
        if not type(currentNode) is slicer.vtkMRMLTableNode:
            self.warningLabel.visible = False
            return

        if currentNode.GetAttribute("InstanceSegmenter") is None:
            self.warningLabel.text = "Invalid report table."
            self.warningLabel.visible = True
            return

        if currentNode.GetAttribute("InstanceSegmenter"):
            if not self.logic.isCurrentImageVisible():
                self.warningLabel.text = "The instances are not currently visible in any of the image log views."
                self.warningLabel.visible = True
            else:
                self.warningLabel.visible = False
            return


class InstanceSegmenterEditorLogic(LTracePluginLogic):
    viewsRefreshed = qt.Signal()

    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.imageLogDataLogic = None
        self.labelMapNode = None
        self.tableNode = None
        self.originalLabelMapNodeArray = None
        self.declinedLabels = []
        self.brushSize = None
        self.editObservers = []
        self.saveObserver = None

    def setImageLogDataLogic(self, imageLogDataLogic):
        self.imageLogDataLogic = imageLogDataLogic
        self.imageLogDataLogic.viewsRefreshed.connect(self.viewsRefreshed)

    def centerToDepth(self, depth):
        self.imageLogDataLogic.setDepth(depth)

    def restoreLabelMapNode(self):
        if self.labelMapNode is not None:
            slicer.util.updateVolumeFromArray(self.labelMapNode, self.originalLabelMapNodeArray)
            self.labelMapNode.Modified()

    def declineLabel(self, dataFrame, label):
        repeatedLabelsCount = np.count_nonzero(dataFrame["label"].values == label)
        # If we don't have any other dataframe with the same label reference, we can remove from the labelmap
        if repeatedLabelsCount == 1:
            volumeRASToIJKMatrix = vtk.vtkMatrix4x4()
            self.labelMapNode.GetRASToIJKMatrix(volumeRASToIJKMatrix)
            labelMapArray = slicer.util.arrayFromVolume(self.labelMapNode)
            labelMapArray[labelMapArray == label] = 0
            self.labelMapNode.Modified()
            self.declinedLabels.append(label)

    def setTableNode(self, tableNode):
        self.tableNode = tableNode
        if self.tableNode is not None:
            self.labelMapNode = tableNode.GetNodeReference("InstanceSegmenterLabelMap")
            self.originalLabelMapNodeArray = slicer.util.arrayFromVolume(self.labelMapNode).copy()
        else:
            self.labelMapNode = None
            self.originalLabelMapNodeArray = None
        self.declinedLabels = []

    def apply(self, dataFrame, outputSuffix):
        volumesLogic = slicer.modules.volumes.logic()
        updatedLabelMapNode = volumesLogic.CloneVolume(
            slicer.mrmlScene, self.labelMapNode, self.labelMapNode.GetName() + "_" + outputSuffix
        )
        updatedLabelMapNode.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)

        updatedDataFrame = dataFrame
        updatedDataFrame.drop(updatedDataFrame[updatedDataFrame.label.isin(self.declinedLabels)].index, inplace=True)
        updatedTableNode = dataFrameToTableNode(updatedDataFrame)
        updatedTableNode.SetName(self.tableNode.GetName() + "_" + outputSuffix)
        updatedTableNode.SetAttribute("InstanceSegmenter", self.tableNode.GetAttribute("InstanceSegmenter"))
        updatedTableNode.AddNodeReferenceID("InstanceSegmenterLabelMap", updatedLabelMapNode.GetID())

        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(updatedLabelMapNode),
            subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(self.labelMapNode)),
        )
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(updatedTableNode),
            subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(self.tableNode)),
        )

        self.restoreLabelMapNode()
        self.setTableNode(None)

    def cancel(self):
        self.restoreLabelMapNode()
        self.setTableNode(None)

    def getInstanceType(self):
        return self.tableNode.GetAttribute("InstanceSegmenter")

    def applySegment(self):
        mask = self.editedLabelMapNodeArray.copy().squeeze()
        mask[mask != self.editedLabelValue] = 0
        mask[mask == self.editedLabelValue] = 1

        if 1 not in mask:
            return None

        instanceType = self.getInstanceType()

        if "sidewall_sample" in instanceType:
            properties = sidewall_sample_instance_properties(mask, self.labelMapNode.GetSpacing())
            rowData = properties
            rowData["label"] = self.editedLabelValue
            rowData["n depth (m)"] = 0
            rowData["desc"] = str(0)
            rowData["cond"] = ""
        elif ImageLogInstanceSegmenter.MODEL_IMAGE_LOG_STOPS in instanceType:
            # find mask contour
            contour = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0][0]
            area = cv2.contourArea(contour)
            angle, linearity = fit_line(contour)
            rowData = {"label": self.editedLabelValue, "area": area, "steepness (°)": angle, "linearity": linearity}
        elif (
            ImageLogInstanceSegmenter.MODEL_IMAGE_LOG_ISLANDS in instanceType
            or ImageLogInstanceSegmenter.MODEL_IMAGE_LOG_SNOW in instanceType
        ):
            properties = generic_instance_properties(mask, self.labelMapNode.GetSpacing())
            rowData = properties
            rowData["label"] = self.editedLabelValue
        else:
            raise RuntimeError("Instance type not detected.")

        # Recalculate depth
        rowData["depth (m)"] = instance_depth(self.labelMapNode, self.editedLabelValue)

        # Removing primary node observers
        for observerID, node in self.editObservers:
            node.RemoveObserver(observerID)
        self.editObservers = []

        layoutManager = slicer.app.layoutManager()
        for sliceViewName in layoutManager.sliceViewNames():
            sliceView = layoutManager.sliceWidget(sliceViewName).sliceView()
            sliceView.unsetViewCursor()

        return rowData

    def cancelSegment(self):
        slicer.util.updateVolumeFromArray(self.labelMapNode, self.originalEditedLabelMapNodeArray)
        self.labelMapNode.Modified()

        # Removing primary node observers
        for observerID, node in self.editObservers:
            node.RemoveObserver(observerID)
        self.editObservers = []

        layoutManager = slicer.app.layoutManager()
        for sliceViewName in layoutManager.sliceViewNames():
            sliceView = layoutManager.sliceWidget(sliceViewName).sliceView()
            sliceView.unsetViewCursor()

    def removeOrphanLabels(self, dataFrame):
        dataFramelabels = dataFrame["label"].values
        labelMapArray = slicer.util.arrayFromVolume(self.labelMapNode)
        labelMapArrayLabels = np.unique(labelMapArray)
        labelMapArrayLabels = labelMapArrayLabels[labelMapArrayLabels != 0]
        for label in labelMapArrayLabels:
            if label not in dataFramelabels:
                labelMapArray[labelMapArray == label] = 0
        self.labelMapNode.Modified()

    def addOrEditSegment(self, label, originalLabel=None):
        self.setMouseInteractionToViewTransform()

        self.editedLabelMapNodeArray = slicer.util.arrayFromVolume(self.labelMapNode)
        self.editedLabelValue = label

        self.originalEditedLabelMapNodeArray = self.editedLabelMapNodeArray.copy()

        if originalLabel is not None:
            self.editedLabelMapNodeArray[self.editedLabelMapNodeArray == originalLabel] = label
            self.labelMapNode.Modified()

        self.rastoIJKMatrix = vtk.vtkMatrix4x4()
        self.labelMapNode.GetRASToIJKMatrix(self.rastoIJKMatrix)

        self.crosshairNode = slicer.util.getNode("Crosshair")
        observerID = self.crosshairNode.AddObserver(
            slicer.vtkMRMLCrosshairNode.CursorPositionModifiedEvent, self.onMouseButtonClickedOrHeld
        )
        self.editObservers.append([observerID, self.crosshairNode])

        layoutManager = slicer.app.layoutManager()
        for sliceViewName in layoutManager.sliceViewNames():
            sliceView = layoutManager.sliceWidget(sliceViewName).sliceView()
            sliceView.setViewCursor(qt.Qt.CrossCursor)
            sliceViewInteractorStyle = (
                sliceView.interactorObserver()
                if hasattr(sliceView, "interactorObserver")
                else sliceView.sliceViewInteractorStyle()
            )
            observerID = sliceViewInteractorStyle.AddObserver("LeftButtonPressEvent", self.onMouseButtonClickedOrHeld)
            self.editObservers.append([observerID, sliceViewInteractorStyle])
            observerID = sliceViewInteractorStyle.AddObserver("RightButtonPressEvent", self.onMouseButtonClickedOrHeld)
            self.editObservers.append([observerID, sliceViewInteractorStyle])

    def circle(self, array, point, value):
        # Using cv2
        radius = self.brushSize
        kk, ii = np.mgrid[-radius : radius + 1, -radius : radius + 1]
        circle = ii**2 + kk**2 <= radius**2
        circle = circle.astype(int)
        circle[circle == 1] = -10000
        pi, pj, pk = point
        i = slice(max(pi - radius, 0), min(pi + radius + 1, array.shape[2]))
        k = slice(max(pk - radius, 0), min(pk + radius + 1, array.shape[0]))
        ci = slice(abs(min(pi - radius, 0)), circle.shape[1] - abs(min(array.shape[2] - (pi + radius + 1), 0)))
        ck = slice(abs(min(pk - radius, 0)), circle.shape[0] - abs(min(array.shape[0] - (pk + radius + 1), 0)))
        array[k, 0, i] += circle[ck, ci]
        subArray = array[k, 0, i]
        subArray[subArray < -5000] = value
        array[k, 0, i] = subArray

    def setMouseInteractionToViewTransform(self):
        mouseModeToolBar = slicer.util.findChild(slicer.util.mainWindow(), "MouseModeToolBar")
        mouseModeToolBar.interactionNode().SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.ViewTransform)

    def onMouseButtonClickedOrHeld(self, *args):
        if not slicer.app.mouseButtons():
            return
        pointRAS = [0, 0, 0]
        self.crosshairNode.GetCursorPositionRAS(pointRAS)
        pointIJK = transformPoints(self.rastoIJKMatrix, [pointRAS], returnInt=True)[0]
        try:
            if slicer.app.mouseButtons() == 1:
                self.circle(self.editedLabelMapNodeArray, pointIJK, self.editedLabelValue)
            elif slicer.app.mouseButtons() == 2:
                self.circle(self.editedLabelMapNodeArray, pointIJK, 0)
            self.labelMapNode.Modified()
        except:
            pass

    def setBrushSize(self, brushSize):
        self.brushSize = int(brushSize)

    def isCurrentImageVisible(self):
        return self.imageLogDataLogic.isImageVisible(self.labelMapNode)


class InstanceSegmenterEditorInfo(RuntimeError):
    pass
