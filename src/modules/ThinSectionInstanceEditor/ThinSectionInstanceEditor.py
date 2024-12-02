import logging
import os
from enum import Enum
from pathlib import Path

import ctk
import cv2
import numpy as np
import qt
import scipy
import slicer
import vtk

from ThinSectionInstanceEditorLib.widget.FilterableTableWidgets import GenericTableWidget
from ltrace.algorithms.measurements import LabelStatistics2D
from ltrace.slicer.helpers import highlight_error, reset_style_on_valid_text, tryGetNode
from ltrace.slicer.node_attributes import ImageLogDataSelectable
from ltrace.slicer.volume_operator import VolumeOperator
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, getResourcePath
from ltrace.slicer import ui
from ltrace.slicer_utils import dataFrameToTableNode
from ltrace.transforms import transformPoints


def calculate_instance_properties(mask, node):
    spacing = node.GetSpacing()

    properties = {"width (mm)": -1, "height (mm)": -1, "confidence (%)": 100}

    statistics = {
        "area (mm^2)": 0,
        "max_feret (mm)": 0,
        "min_feret (mm)": 0,
        "aspect_ratio": 0,
        "elongation": 0,
        "eccentricity": 0,
        "perimeter (mm)": 0,
    }

    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contour = contours[0]
    x, y, w, h = cv2.boundingRect(contour)
    properties["width (mm)"] = w * spacing[0]
    properties["height (mm)"] = h * spacing[1]

    # Statistics
    mask_filt = mask.squeeze()
    voxel_area = np.product(spacing)
    # TODO check that the inspector API is not being used correctly
    volumeOperator = VolumeOperator(node)
    operator = LabelStatistics2D(mask_filt, spacing, direction=None, size_filter=0)
    pointsInRAS = np.array(np.where(mask_filt)).T
    stats = operator.strict_calculate(mask_filt, pointsInRAS)
    statistics["area (mm^2)"] = stats[2]
    statistics["max_feret (mm)"] = stats[4] * spacing[0]
    statistics["min_feret (mm)"] = stats[5] * spacing[0]
    statistics["aspect_ratio"] = stats[8]
    statistics["elongation"] = stats[9]
    statistics["eccentricity"] = stats[10]
    statistics["perimeter (mm)"] = stats[14] * spacing[0]
    properties.update(statistics)

    return properties


class ThinSectionInstanceEditMode(Enum):
    ADD = 1
    PAINT = 2
    ERASE = 3


class ThinSectionInstanceEditor(LTracePlugin):
    SETTING_KEY = "ThinSectionInstanceEditor"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Instance Editor"
        self.parent.categories = ["Segmentation", "Thin Section"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ThinSectionInstanceEditor.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ThinSectionInstanceEditorWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.editedRow = False
        self.labelMapObserverID = None
        self.compositeNodeObserverID = None
        self.closeSceneObserver = None

    def warningDisplay(self):
        logging.warning(
            "Current report do not correspond to the selected class."
        )  # TODO (PL-2158): FOR SOME REASON, infoDisplay() DOESN'T WORK HERE (GEOSLICER CRASHES).
        return

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = ThinSectionInstanceEditorLogic()
        self.logic.viewsRefreshed.connect(self.updateWarning)
        self.logic.warningSignal.connect(self.warningDisplay)

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

        self.inputTableNodeComboBox = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLTableNode"], onChange=self.onInputTableNodeChanged
        )
        self.inputTableNodeComboBox.setToolTip("Select the instance report table.")
        self.inputTableNodeComboBox.resetStyleOnValidNode()
        inputFormLayout.addRow("Report table:", self.inputTableNodeComboBox)
        inputFormLayout.addRow(" ", None)

        self.warningLabel = qt.QLabel()
        self.warningLabel.visible = False
        self.warningLabel.setStyleSheet("QLabel {color: yellow}")
        inputFormLayout.addRow(self.warningLabel)

        # Filter section
        self.parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        self.parametersCollapsibleButton.setText("Labels")
        formLayout.addRow(self.parametersCollapsibleButton)
        self.parametersFormLayout = qt.QFormLayout(self.parametersCollapsibleButton)

        self.tableWidget = None
        self.parametersCollapsibleButton.setVisible(False)
        self.parametersCollapsibleButton.clicked.connect(self.onParametersCollapsibleButtonClicked)

        # Edit section
        self.editCollapsibleButton = ctk.ctkCollapsibleButton()
        self.editCollapsibleButton.setText("Edit")
        self.editCollapsibleButton.setVisible(False)
        formLayout.addRow(self.editCollapsibleButton)
        editFormLayout = qt.QFormLayout(self.editCollapsibleButton)

        self.addSegmentButton = qt.QPushButton("Add")
        self.addSegmentButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Add.png"))
        self.addSegmentButton.clicked.connect(self.onAddSegmentButtonClicked)

        self.paintButton = qt.QPushButton("Paint")
        self.paintButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Edit.png"))
        self.paintButton.clicked.connect(self.onPaintButtonClicked)

        self.eraseButton = qt.QPushButton("Erase")
        self.eraseButton.setIcon(qt.QIcon(getResourcePath("Icons") / "IconSet-dark" / "Eraser.png"))
        self.eraseButton.clicked.connect(self.onEraseButtonClicked)

        self.applySegmentButton = qt.QPushButton("Apply")
        self.applySegmentButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Apply.png"))
        self.applySegmentButton.setEnabled(False)
        self.applySegmentButton.clicked.connect(self.onApplySegmentButtonClicked)

        self.cancelSegmentButton = qt.QPushButton("Cancel")
        self.cancelSegmentButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Cancel.png"))
        self.cancelSegmentButton.setEnabled(False)
        self.cancelSegmentButton.clicked.connect(self.onCancelSegmentButtonClicked)

        self.declineSegmentButton = qt.QPushButton("Decline")
        self.declineSegmentButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Delete.png"))
        self.declineSegmentButton.clicked.connect(self.onDeclineSegmentButtonClicked)

        editButtonsHBoxLayout = qt.QHBoxLayout()
        editButtonsHBoxLayout.addWidget(self.addSegmentButton)
        editButtonsHBoxLayout.addWidget(self.paintButton)
        editButtonsHBoxLayout.addWidget(self.eraseButton)
        editButtonsHBoxLayout.addWidget(self.declineSegmentButton)
        editButtonsHBoxLayout.addWidget(self.applySegmentButton)
        editButtonsHBoxLayout.addWidget(self.cancelSegmentButton)
        editFormLayout.addRow(editButtonsHBoxLayout)

        brushSizeSlider = ctk.ctkSliderWidget()
        brushSizeSlider.decimals = 0
        brushSizeSlider.minimum = 1
        brushSizeSlider.maximum = 50
        brushSizeSlider.tracking = False
        brushSizeSlider.valueChanged.connect(self.onBrushSizeChanged)
        brushSizeSlider.setValue(10)
        editFormLayout.addRow("Brush diameter:", brushSizeSlider)
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

        self.applyCancelButtons = ui.ApplyCancelButtons(
            onApplyClick=self.onApplyButtonClicked,
            onCancelClick=self.onCancelButtonClicked,
            applyTooltip="Apply changes",
            cancelTooltip="Cancel",
            applyText="Apply",
            cancelText="Cancel",
            enabled=True,
            applyObjectName="Apply Button",
            cancelObjectName=None,
        )
        formLayout.addWidget(self.applyCancelButtons)

        self.spacerItem = qt.QSpacerItem(10, 10, qt.QSizePolicy.Minimum, qt.QSizePolicy.Expanding)
        formLayout.addItem(self.spacerItem)

        self.switchEditionMode(editMode=None)

    def onSegmentClicked(self, *args):
        try:
            instanceIndex = self.logic.getHoveredInstance()

            if self.logic.getHoveredInstance() > 0:
                currentlySelectedLabelMap = slicer.util.getNode(
                    slicer.mrmlScene.GetNthNodeByClass(0, "vtkMRMLSliceCompositeNode").GetLabelVolumeID()
                )
                correspondingTableNode = slicer.util.getNode(
                    currentlySelectedLabelMap.GetAttribute("ThinSectionInstanceTableNode")
                )
                self.inputTableNodeComboBox.setCurrentNode(correspondingTableNode)

                dataFrame = self.tableWidget.pandasTableModel._data
                rowIndex = dataFrame[dataFrame["label"] == instanceIndex].index[0]
                self.tableWidget.tableView.setCurrentIndex(self.tableWidget.tableView.model().index(rowIndex, 0))
        except Exception as error:
            logging.debug(error)

    def onBrushSizeChanged(self, value):
        self.logic.setBrushSize(value)

    def onDeclineSegmentButtonClicked(self):
        tableView = self.tableWidget.tableView
        selectedIndexes = tableView.selectedIndexes()
        if len(selectedIndexes) > 0:
            message = "Are you sure you want to decline the selected segment?"
            if slicer.util.confirmYesNoDisplay(message):
                model = tableView.model()
                label = int(float(selectedIndexes[model.labelIndex()].data()))
                self.logic.declineLabel(model._data, label)
                model.removeRow(selectedIndexes[0].row())
        else:
            slicer.util.infoDisplay("Please select an instance from the table.")

        self.tableWidget.setAllRangeWidgetValues(resetValues=False)
        self.tableWidget.filterValuesChanged()

    def onLabelChanged(self, observer, event):
        compositeNode = slicer.mrmlScene.GetNthNodeByClass(0, "vtkMRMLSliceCompositeNode")
        labelVolumeID = compositeNode.GetLabelVolumeID()
        if not labelVolumeID:
            return

        currentNode = self.inputTableNodeComboBox.currentNode()
        if not currentNode:
            return

        referenceID = currentNode.GetNodeReferenceID("referenceNode")
        labelmapID = currentNode.GetNodeReferenceID("InstanceEditorLabelMap")
        if labelVolumeID == labelmapID:
            return

        if self.editedRow is not None:
            message = "Are you sure you want to save the current edit?\n(the results will be saved with the specified output suffix)"
            if slicer.util.confirmYesNoDisplay(message):
                slicer.util.setSliceViewerLayers(
                    background=slicer.mrmlScene.GetNodeByID(referenceID),
                    label=slicer.mrmlScene.GetNodeByID(labelmapID),
                    fit=False,
                )
                if self.applySegmentButton.enabled == True:
                    self.applySegmentButton.click()
                self.applyCancelButtons.applyBtn.click()
            else:
                self.applyCancelButtons.cancelBtn.click()

        labelVolumeNode = slicer.mrmlScene.GetNodeByID(labelVolumeID)
        tableNodeID = labelVolumeNode.GetAttribute("ThinSectionInstanceTableNode")
        if tableNodeID:
            tableNode = slicer.mrmlScene.GetNodeByID(tableNodeID)
            self.inputTableNodeComboBox.setCurrentNode(tableNode)

    def onAddSegmentButtonClicked(self):
        self.editedRow = "Add"
        self.addSegmentButton.setEnabled(False)
        self.paintButton.setEnabled(False)
        self.eraseButton.setEnabled(True)
        self.declineSegmentButton.setEnabled(False)
        self.cancelSegmentButton.setEnabled(True)

        self.tableWidget.tableView.clearSelection()

        dataFrame = self.tableWidget.pandasTableModel._data
        lastLabelValue = self.logic.getLastLabelValue(dataFrame)
        self.logic.addOrEditSegment(lastLabelValue + 1)
        self.switchEditionMode(editMode=ThinSectionInstanceEditMode.ADD)

        labelMapNode = tryGetNode(self.logic.labelMapNodeID)
        if not labelMapNode:
            raise ValueError("Invalid node reference.")

        if self.labelMapObserverID:
            labelMapNode.RemoveObserver(self.labelMapObserverID)

        self.labelMapObserverID = labelMapNode.AddObserver("ModifiedEvent", self.onLabelMapModified)

    def onPaintButtonClicked(self):
        self.segmentEditionButtonsBehaviour(
            ThinSectionInstanceEditMode.PAINT
            if not self.logic.isEditingInAddMode()
            else ThinSectionInstanceEditMode.ADD
        )

    def onEraseButtonClicked(self):
        self.segmentEditionButtonsBehaviour(ThinSectionInstanceEditMode.ERASE)

    def onLabelMapModified(self, caller, event):
        self.applySegmentButton.setEnabled(True)

    def onApplySegmentButtonClicked(self):
        model = self.tableWidget.tableView.model()
        rowsData = self.logic.applySegment(model._data)

        if not rowsData:
            slicer.util.infoDisplay("A segment can not be empty. Cancelling.")
            self.onCancelSegmentButtonClicked()
            return

        self.switchEditionMode(editMode=None)

        labelMapNode = tryGetNode(self.logic.labelMapNodeID)
        if not labelMapNode:
            raise ValueError("Invalid node reference.")
        labelMapNode.RemoveObserver(self.labelMapObserverID)
        self.labelMapObserverID = None

        self.addSegmentButton.setEnabled(True)
        self.paintButton.setEnabled(True)
        self.eraseButton.setEnabled(True)
        self.declineSegmentButton.setEnabled(True)
        self.applySegmentButton.setEnabled(False)
        self.cancelSegmentButton.setEnabled(False)

        if self.editedRow == "Add":
            for rowData in rowsData:
                model.addRow(rowData)
                model.sortDefault()
                row = model.getRowByLabel(rowData["label"])
                # self.tableWidget.tableView.setCurrentIndex(model.index(row, 0)) # centralize new segments in screen
        else:
            model.editRow(self.editedRow, rowsData[0])
            for rowData in rowsData[1:]:
                model.addRow(rowData)
                model.sortDefault()
                row = model.getRowByLabel(rowData["label"])
                # self.tableWidget.tableView.setCurrentIndex(model.index(row, 0)) # centralize edited segments in screen

        # To center the added or edited element both in the table view and slice view
        self.tableWidget.reselectCurrentItem()

        self.tableWidget.setAllRangeWidgetValues(resetValues=False)
        self.tableWidget.filterValuesChanged()

    def onCancelSegmentButtonClicked(self):
        self.logic.cancelSegment()
        self.switchEditionMode(editMode=None)

        labelMapNode = tryGetNode(self.logic.labelMapNodeID)
        if not labelMapNode:
            raise ValueError("Invalid node reference.")
        labelMapNode.RemoveObserver(self.labelMapObserverID)
        self.labelMapObserverID = None

        self.addSegmentButton.setEnabled(True)
        self.paintButton.setEnabled(True)
        self.eraseButton.setEnabled(True)
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
            self.editedRow = None
        except ThinSectionInstanceEditorInfo as e:
            slicer.util.infoDisplay(str(e))
            return

    def onCancelButtonClicked(self):
        # If a segment is still being edited, cancel it before cancelling everything
        if self.editedRow is not None:
            self.cancelSegmentButton.click()
        self.logic.cancel()
        self.inputTableNodeComboBox.setCurrentNode(None)
        self.editedRow = None

    def onParametersCollapsibleButtonClicked(self):
        if self.parametersCollapsibleButton.collapsed:
            self.layout.addItem(self.spacerItem)
        else:
            self.layout.removeItem(self.spacerItem)

    def selectReferenceToTableNode(self, tableNode):
        dialog = qt.QDialog(slicer.modules.AppContextInstance.mainWindow)
        dialog.setWindowFlags(dialog.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint)
        dialog.setWindowTitle("Select corresponding reference and labelmap node")
        formLayout = qt.QFormLayout()

        referenceNodeComboBox = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLVectorVolumeNode"],
        )
        referenceNodeComboBox.setToolTip("Select the corresponding reference node.")

        labelMapNodeComboBox = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLLabelMapVolumeNode"],
        )
        labelMapNodeComboBox.setToolTip("Select the corresponding labelmap node.")

        formLayout.addRow("Volume (PX):", referenceNodeComboBox)
        formLayout.addRow("LabelMap:", labelMapNodeComboBox)

        buttonBox = qt.QDialogButtonBox(dialog)
        buttonBox.setGeometry(qt.QRect(30, 240, 341, 32))
        buttonBox.setOrientation(qt.Qt.Horizontal)
        buttonBox.setStandardButtons(qt.QDialogButtonBox.Cancel | qt.QDialogButtonBox.Ok)
        formLayout.addRow(buttonBox)

        buttonBox.accepted.connect(dialog.accept)
        buttonBox.rejected.connect(dialog.reject)

        dialog.setFixedSize(400, 90)
        dialog.setLayout(formLayout)

        status = bool(dialog.exec())
        if not status:
            return False

        referenceNode = referenceNodeComboBox.currentNode()
        node = labelMapNodeComboBox.currentNode()
        if node is not None and referenceNode is not None:
            numLabels = np.max(slicer.util.arrayFromVolume(node))
            table = tableNode.GetTable()
            col_data = vtk.util.numpy_support.vtk_to_numpy(table.GetColumn(0))
            if numLabels == col_data[-1]:
                tableNode.SetAttribute("InstanceEditor", node.GetName())
                tableNode.SetAttribute("ReferenceVolumeNode", node.GetID())
                tableNode.AddNodeReferenceID("InstanceEditorLabelMap", node.GetID())
                tableNode.AddNodeReferenceID("referenceNode", referenceNode.GetID())
                node.SetAttribute("ThinSectionInstanceTableNode", tableNode.GetID())
            else:
                slicer.util.infoDisplay(
                    "The number of labels in this labelmap do not agree with entries on table. Aborting."
                )
                return False
        else:
            slicer.util.infoDisplay("Need to select both volume (PX) and labelmap. Aborting.")
            return False

        return status

    def onInputTableNodeChanged(self, itemId):
        self.warningLabel.visible = False
        self.logic.restoreLabelMapNode()

        self.layout.removeItem(self.spacerItem)
        self.parametersCollapsibleButton.setVisible(False)
        self.editCollapsibleButton.setVisible(False)

        if not itemId:
            return

        tableNode = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(itemId)
        if tableNode:
            if tableNode.GetAttribute("InstanceEditor") is None:
                self.updateWarning()
                self.layout.addItem(self.spacerItem)
                status = self.selectReferenceToTableNode(tableNode)
                if not status:
                    return

            self.logic.setTableNode(tableNode)

            if self.tableWidget:
                self.parametersFormLayout.removeWidget(self.tableWidget)
                self.tableWidget.deleteLater()

            self.tableWidget = GenericTableWidget(self.logic)
            self.tableWidget.setTableNode(tableNode)

            self.parametersFormLayout.addRow(self.tableWidget)
            self.parametersFormLayout.addRow(None)

            self.parametersCollapsibleButton.setVisible(True)
            self.editCollapsibleButton.setVisible(True)

            self.tableWidget.tableView.model().sortDefault()

            if self.compositeNodeObserverID is None:
                compositeNode = slicer.mrmlScene.GetNthNodeByClass(0, "vtkMRMLSliceCompositeNode")
                self.compositeNodeObserverID = compositeNode.AddObserver(
                    vtk.vtkCommand.ModifiedEvent, self.onLabelChanged
                )
        else:
            self.layout.addItem(self.spacerItem)
            if self.compositeNodeObserverID is not None:
                compositeNode = slicer.mrmlScene.GetNthNodeByClass(0, "vtkMRMLSliceCompositeNode")
                compositeNode.RemoveObserver(self.compositeNodeObserverID)
                self.compositeNodeObserverID = None

        self.updateWarning()

    def enter(self) -> None:
        super().enter()
        if self.logic.saveObserver is None:
            self.logic.saveObserver = slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartSaveEvent, self.onStartSave)

        if self.closeSceneObserver is None:
            self.closeSceneObserver = slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndCloseEvent, self.onCloseScene)

    def onStartSave(self, *args):
        self.onCancelButtonClicked()
        slicer.app.processEvents()

    def onCloseScene(self, *args):
        self.onCancelButtonClicked()
        self.onInputTableNodeChanged(None)
        self.layout.addItem(self.spacerItem)
        if self.compositeNodeObserverID is not None:
            compositeNode = slicer.mrmlScene.GetNthNodeByClass(0, "vtkMRMLSliceCompositeNode")
            compositeNode.RemoveObserver(self.compositeNodeObserverID)
            self.compositeNodeObserverID = None
        slicer.app.processEvents()

    def updateWarning(self):
        currentNode = self.inputTableNodeComboBox.currentNode()
        if not type(currentNode) is slicer.vtkMRMLTableNode:
            self.warningLabel.visible = False
            return

        if currentNode.GetAttribute("InstanceEditor") is None:
            self.warningLabel.text = "Invalid report table."
            self.warningLabel.visible = True
            return

        if currentNode.GetAttribute("InstanceEditor"):
            referenceNodeID = currentNode.GetNodeReferenceID("referenceNode")
            labelmapID = currentNode.GetNodeReferenceID("InstanceEditorLabelMap")
            currentReferenceNode = slicer.util.getNode(referenceNodeID)
            currentLabelmap = slicer.util.getNode(labelmapID)
            slicer.util.setSliceViewerLayers(background=currentReferenceNode, label=currentLabelmap, fit=False)

            if not self.logic.isCurrentImageAndLabelVisible(currentReferenceNode, currentLabelmap):
                self.warningLabel.text = "The instances are not currently visible on the view."
                self.warningLabel.visible = True
            else:
                self.warningLabel.visible = False
            return

    def segmentEditionButtonsBehaviour(self, editMode):
        selectedIndexes = self.tableWidget.tableView.selectedIndexes()
        if len(selectedIndexes) > 0 or self.logic.isEditingInAddMode():
            if self.logic.editMode["current"] is None:
                self.editedRow = selectedIndexes[0].row()

                tableView = self.tableWidget.tableView
                originalLabel = (
                    int(float(selectedIndexes[tableView.model().labelIndex()].data()))
                    if len(selectedIndexes) > 0
                    else self.logic.editedLabelValue
                )

                self.logic.addOrEditSegment(originalLabel, originalLabel=originalLabel)

                labelMapNode = tryGetNode(self.logic.labelMapNodeID)
                if not labelMapNode:
                    raise ValueError("Invalid node reference.")

                if self.labelMapObserverID:
                    labelMapNode.RemoveObserver(self.labelMapObserverID)

                self.labelMapObserverID = labelMapNode.AddObserver("ModifiedEvent", self.onLabelMapModified)

            self.switchEditionMode(editMode=editMode)
            enteringEraseMode = self.logic.isInEraseMode()

            self.addSegmentButton.setEnabled(False)
            self.paintButton.setEnabled(enteringEraseMode)
            self.eraseButton.setEnabled(not enteringEraseMode)
            self.declineSegmentButton.setEnabled(False)
            self.cancelSegmentButton.setEnabled(True)
        else:
            slicer.util.infoDisplay("Please select an instance from the table.")

    def switchEditionMode(self, editMode):
        changeObservers = len(self.logic.observers) == 0 or (
            (editMode is None) ^ (self.logic.editMode["current"] is None)
        )
        self.logic.editMode["previous"] = self.logic.editMode["current"]
        self.logic.editMode["current"] = editMode

        if not changeObservers:
            return

        self.logic.removeObservers(self.logic.observers)

        layoutManager = slicer.app.layoutManager()
        for sliceViewName in layoutManager.sliceViewNames():
            sliceView = layoutManager.sliceWidget(sliceViewName).sliceView()

            sliceViewInteractorStyle = (
                sliceView.interactorObserver()
                if hasattr(sliceView, "interactorObserver")
                else sliceView.sliceViewInteractorStyle()
            )
            if editMode is not None:
                sliceView.setViewCursor(qt.Qt.CrossCursor)

                observerID = sliceViewInteractorStyle.AddObserver(
                    "LeftButtonPressEvent", self.logic.onMouseButtonClickedOrHeld
                )
                self.logic.observers.append([observerID, sliceViewInteractorStyle])
            else:
                sliceView.unsetViewCursor()

                observerID = sliceViewInteractorStyle.AddObserver("LeftButtonPressEvent", self.onSegmentClicked)
                self.logic.observers.append([observerID, sliceViewInteractorStyle])

        if editMode is not None:
            self.logic.crosshairNode = slicer.util.getNode("Crosshair")
            observerID = self.logic.crosshairNode.AddObserver(
                slicer.vtkMRMLCrosshairNode.CursorPositionModifiedEvent, self.logic.onMouseButtonClickedOrHeld
            )
            self.logic.observers.append([observerID, self.logic.crosshairNode])

            tableView = self.tableWidget.tableView
            tableView.setSelectionMode(qt.QTableView.NoSelection)
            self.inputTableNodeComboBox.setEnabled(False)

            selectedIndexes = tableView.selectedIndexes()
            if len(selectedIndexes) > 0:
                tableView.scrollTo(tableView.model().index(selectedIndexes[0].row(), 0))
            else:
                tableView.scrollToBottom()
        else:
            if self.tableWidget is not None:
                tableView = self.tableWidget.tableView
                tableView.setSelectionMode(qt.QTableView.SelectRows)
                self.inputTableNodeComboBox.setEnabled(True)


class ThinSectionInstanceEditorLogic(LTracePluginLogic):
    viewsRefreshed = qt.Signal()
    warningSignal = qt.Signal()

    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.imageLogDataLogic = None
        self.labelMapNodeID = None
        self.tableNodeID = None
        self.originalLabelMapNodeArray = None
        self.declinedLabels = []
        self.brushSize = None
        self.observers = []
        self.saveObserver = None
        self.editMode = {"current": None, "previous": None}

    def centerToLabel(self, label):
        node = tryGetNode(self.labelMapNodeID)
        if not node:
            raise ValueError("Invalid node reference.")
        centralizeLabel(node, label)

    def restoreLabelMapNode(self):
        if not self.labelMapNodeID:
            return

        node = tryGetNode(self.labelMapNodeID)
        if node:
            slicer.util.updateVolumeFromArray(node, self.originalLabelMapNodeArray)
            node.Modified()

    def declineLabel(self, dataFrame, label):
        repeatedLabelsCount = np.count_nonzero(dataFrame["label"].values == label)
        # If we don't have any other dataframe with the same label reference, we can remove from the labelmap
        if repeatedLabelsCount == 1:
            node = tryGetNode(self.labelMapNodeID)
            if not node:
                raise ValueError("Invalid node reference.")
            volumeRASToIJKMatrix = vtk.vtkMatrix4x4()
            node.GetRASToIJKMatrix(volumeRASToIJKMatrix)
            labelMapArray = slicer.util.arrayFromVolume(node)
            labelMapArray[labelMapArray == label] = 0
            node.Modified()
            self.declinedLabels.append(label)

    def setTableNode(self, tableNode):
        self.tableNodeID = tableNode.GetID() if tableNode is not None else None
        if self.tableNodeID is not None:
            labelMapNode = tableNode.GetNodeReference("InstanceEditorLabelMap")
            self.labelMapNodeID = labelMapNode.GetID() if labelMapNode is not None else None
            self.originalLabelMapNodeArray = slicer.util.arrayFromVolume(labelMapNode).copy()
        else:
            self.labelMapNodeID = None
            self.originalLabelMapNodeArray = None
        self.declinedLabels = []

    def apply(self, dataFrame, outputSuffix):
        labelMapNode = tryGetNode(self.labelMapNodeID)
        if not labelMapNode:
            raise ValueError("Invalid node reference.")

        tableNode = tryGetNode(self.tableNodeID)
        if not tableNode:
            raise ValueError("Invalid node reference.")

        volumesLogic = slicer.modules.volumes.logic()
        updatedLabelMapNode = volumesLogic.CloneVolume(
            slicer.mrmlScene, labelMapNode, labelMapNode.GetName() + "_" + outputSuffix
        )
        updatedLabelMapNode.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)

        updatedDataFrame = dataFrame
        updatedDataFrame = updatedDataFrame.drop(
            updatedDataFrame[updatedDataFrame.label.isin(self.declinedLabels)].index
        )
        updatedTableNode = dataFrameToTableNode(updatedDataFrame)
        updatedTableNode.SetName(slicer.mrmlScene.GenerateUniqueName(tableNode.GetName() + "_" + outputSuffix))
        updatedTableNode.SetAttribute("InstanceEditor", tableNode.GetAttribute("InstanceEditor"))
        updatedTableNode.SetAttribute("ReferenceVolumeNode", updatedLabelMapNode.GetID())
        updatedTableNode.AddNodeReferenceID("InstanceEditorLabelMap", updatedLabelMapNode.GetID())
        updatedTableNode.AddNodeReferenceID("referenceNode", tableNode.GetNodeReferenceID("referenceNode"))

        updatedLabelMapNode.SetAttribute("ThinSectionInstanceTableNode", updatedTableNode.GetID())

        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(updatedLabelMapNode),
            subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(labelMapNode)),
        )
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(updatedTableNode),
            subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(tableNode)),
        )

        self.restoreLabelMapNode()
        self.setTableNode(None)

    def cancel(self):
        self.restoreLabelMapNode()
        self.setTableNode(None)

    def getInstanceType(self):
        tableNode = tryGetNode(self.tableNodeID)
        if not tableNode:
            raise ValueError("Invalid node reference.")
        return tableNode.GetAttribute("InstanceEditor")

    def removeObservers(self, observers):
        for observerID, node in observers:
            node.RemoveObserver(observerID)
        observers.clear()

    def applySegment(self, dataFrame):
        mask = self.editedLabelMapNodeArray.copy().squeeze()
        mask[mask != self.editedLabelValue] = 0
        mask[mask == self.editedLabelValue] = 1

        if 1 not in mask:
            return None

        rowsData = []
        label, num_labels = scipy.ndimage.label(mask)
        lastTableValue = self.getLastLabelValue(dataFrame)
        k = 1
        for j in range(1, num_labels + 1):  # j is always updated, k is not updated if the single-pixel island happens
            mask = label == j
            try:
                labelMapNode = tryGetNode(self.labelMapNodeID)
                if not labelMapNode:
                    raise ValueError("Invalid node reference.")
                properties = calculate_instance_properties(mask, labelMapNode)
                new_label = (
                    self.editedLabelValue if k == 1 else np.maximum(self.editedLabelValue, lastTableValue) + (k - 1)
                )

                rowData = properties
                rowData["label"] = new_label
                rowsData.append(rowData)

                self.editedLabelMapNodeArray[0][mask == True] = new_label
                k += 1
            except (
                TypeError
            ):  # when single-pixel island happens a TypeError is catched by calculate_instance_properties()
                self.editedLabelMapNodeArray[0][mask == True] = 0

        return rowsData

    def cancelSegment(self):
        labelMapNode = tryGetNode(self.labelMapNodeID)
        if not labelMapNode:
            raise ValueError("Invalid node reference.")
        slicer.util.updateVolumeFromArray(labelMapNode, self.originalEditedLabelMapNodeArray)
        labelMapNode.Modified()

    def removeOrphanLabels(self, dataFrame):
        labelMapNode = tryGetNode(self.labelMapNodeID)
        if not labelMapNode:
            raise ValueError("Invalid node reference.")
        dataFramelabels = dataFrame["label"].values
        labelMapArray = slicer.util.arrayFromVolume(labelMapNode)
        labelMapArrayLabels = np.unique(labelMapArray)
        labelMapArrayLabels = labelMapArrayLabels[labelMapArrayLabels != 0]
        for label in labelMapArrayLabels:
            if label not in dataFramelabels:
                labelMapArray[labelMapArray == label] = 0
        labelMapNode.Modified()

    def addOrEditSegment(self, label, originalLabel=None):
        self.setMouseInteractionToViewTransform()

        labelMapNode = tryGetNode(self.labelMapNodeID)
        if not labelMapNode:
            raise ValueError("Invalid node reference.")

        self.editedLabelMapNodeArray = slicer.util.arrayFromVolume(labelMapNode)
        self.editedLabelValue = label

        self.originalEditedLabelMapNodeArray = self.editedLabelMapNodeArray.copy()

        if originalLabel is not None:
            self.editedLabelMapNodeArray[self.editedLabelMapNodeArray == originalLabel] = label
            labelMapNode.Modified()

        self.rastoIJKMatrix = vtk.vtkMatrix4x4()
        labelMapNode.GetRASToIJKMatrix(self.rastoIJKMatrix)

    def getBrushRegion(self, array, point):
        # Using cv2
        radius = self.brushSize
        kk, ii = np.mgrid[-radius : radius + 1, -radius : radius + 1]
        circle = ii**2 + kk**2 <= radius**2
        circle = circle.astype(int)
        circle[circle == 1] = -10000
        pi, pj, pk = point
        i = slice(max(pi - radius, 0), min(pi + radius + 1, array.shape[2]))
        j = slice(max(pj - radius, 0), min(pj + radius + 1, array.shape[1]))
        ci = slice(abs(min(pi - radius, 0)), circle.shape[1] - abs(min(array.shape[2] - (pi + radius + 1), 0)))
        cj = slice(abs(min(pj - radius, 0)), circle.shape[0] - abs(min(array.shape[1] - (pj + radius + 1), 0)))
        return i, j, ci, cj, circle

    def circle(self, array, value, brushRegion):
        i, j, ci, cj, circle = brushRegion
        array[0, j, i] += circle[cj, ci]
        subArray = array[0, j, i]
        subArray[subArray < -5000] = value
        array[0, j, i] = subArray

    def brushOverwritingAnotherInstance(self, array, value, brushRegion):
        i, j, _, _, _ = brushRegion
        instancesUnderBrush = np.unique(array[0, j, i])
        return np.any([instanceIndex not in [0, value] for instanceIndex in instancesUnderBrush])

    def setMouseInteractionToViewTransform(self):
        mouseModeToolBar = slicer.util.findChild(slicer.modules.AppContextInstance.mainWindow, "MouseModeToolBar")
        mouseModeToolBar.interactionNode().SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.ViewTransform)

    def onMouseButtonClickedOrHeld(self, *args):
        pressedButton = slicer.app.mouseButtons()
        if not pressedButton or pressedButton != 1:  # (1: left)
            return

        currentlySelectedLabelMap = slicer.util.getNode(
            slicer.mrmlScene.GetNthNodeByClass(0, "vtkMRMLSliceCompositeNode").GetLabelVolumeID()
        )
        correspondingTableNodeID = currentlySelectedLabelMap.GetAttribute("ThinSectionInstanceTableNode")
        currentTableNode = self.tableNodeID

        if correspondingTableNodeID != currentTableNode:
            self.warningSignal.emit()
            return

        pointRAS = [0, 0, 0]
        self.crosshairNode.GetCursorPositionRAS(pointRAS)
        pointIJK = transformPoints(self.rastoIJKMatrix, [pointRAS], returnInt=True)[0]
        try:
            instanceIndex = self.getHoveredInstance()
            if (instanceIndex == self.editedLabelValue) or (
                self.editMode["current"] == ThinSectionInstanceEditMode.ADD and instanceIndex == 0
            ):
                brushRegion = self.getBrushRegion(self.editedLabelMapNodeArray, pointIJK)
                value = self.editedLabelValue * int(not self.isInEraseMode())  # 0 if isInEraseMode, 1 otherwise
                if not self.brushOverwritingAnotherInstance(
                    self.editedLabelMapNodeArray, self.editedLabelValue, brushRegion
                ):
                    self.circle(self.editedLabelMapNodeArray, value, brushRegion)
                    labelMapNode = tryGetNode(self.labelMapNodeID)
                    if not labelMapNode:
                        raise ValueError("Invalid node reference.")
                    labelMapNode.Modified()
        except Exception as error:
            logging.debug(error)

    def setBrushSize(self, brushSize):
        self.brushSize = int(brushSize)

    def isCurrentImageAndLabelVisible(self, currentNode, currentLabelmap):
        sliceViewer = slicer.mrmlScene.GetNthNodeByClass(0, "vtkMRMLSliceCompositeNode")
        return (
            sliceViewer.GetLabelVolumeID() == currentLabelmap.GetID()
            and sliceViewer.GetBackgroundVolumeID() == currentNode.GetID()
        )

    def isInEraseMode(self):
        return self.editMode["current"] == ThinSectionInstanceEditMode.ERASE

    def isInAddMode(self):
        return self.editMode["current"] == ThinSectionInstanceEditMode.ADD

    def wasInAddMode(self):
        return self.editMode["previous"] == ThinSectionInstanceEditMode.ADD

    def isEditingInAddMode(self):
        return self.isInAddMode() or (self.isInEraseMode() and self.wasInAddMode())

    def getHoveredInstance(self):
        infoWidget = slicer.modules.DataProbeInstance.infoWidget
        layerValueText = infoWidget.layerValues["L"].text
        firstIndex = layerValueText.rfind("(") + 1
        lastIndex = layerValueText.rfind(")")
        return int(layerValueText[firstIndex:lastIndex])

    def getLastLabelValue(self, dataFrame):
        return int(dataFrame.iloc[-1]["label"]) if not dataFrame.empty else 0


class ThinSectionInstanceEditorInfo(RuntimeError):
    pass


def centerSlicerView(origin, dimensions=None, zoom_offset=1.0):
    for viewName in slicer.app.layoutManager().sliceViewNames():
        sliceView = slicer.app.layoutManager().sliceWidget(viewName).sliceView()
        sliceNode = sliceView.mrmlSliceNode()

        sliceNode.JumpSliceByCentering(*origin)

        if dimensions:
            fov = sliceNode.GetFieldOfView()
            if any(fov):
                if viewName == "Red":
                    fov = tuple(map(lambda x: x / min(fov[0], fov[1]), fov))
                elif viewName == "Green":
                    fov = tuple(map(lambda x: x / min(fov[1], fov[2]), fov))
                elif viewName == "Yellow":
                    fov = tuple(map(lambda x: x / min(fov[2], fov[0]), fov))
                boxSize = [max(dimensions)] * 3
                boxSize = tuple(map(lambda x, y: x * y * zoom_offset, fov, boxSize))
                sliceNode.SetFieldOfView(*boxSize)


def centralizeLabel(node, label):
    spacing = node.GetSpacing() if node else [1, 1, 1]
    array = slicer.util.arrayFromVolume(node)
    label_pos = np.where(array == label)[::-1]

    dimensions = []
    origin_array = np.zeros((2, 3))
    for i, d in enumerate(label_pos):
        r0 = np.min(d)
        r1 = np.max(d)
        origin_array[0, i] = (r0 + r1) / 2
        dimensions.append(spacing[i] * (r1 - r0))

    matrix = vtk.vtkMatrix4x4()
    node.GetIJKToRASMatrix(matrix)
    origin = tuple(transformPoints(matrix, origin_array)[0])
    centerSlicerView(origin, dimensions, zoom_offset=1.7)
