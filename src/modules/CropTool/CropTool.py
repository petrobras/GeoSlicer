import logging
import os
import typing
from collections.abc import Iterable
from pathlib import Path
from threading import Lock

import ctk
import qt
import slicer
from ltrace.slicer import ui, helpers
from ltrace.slicer.helpers import (
    copy_display,
    copy_attributes,
    copy_hierarchy_attributes,
)
from ltrace.slicer.metadata import copy_metadata
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer_utils import *
from ltrace.transforms import ijkToRAS, rasToIJK
from ltrace.utils.callback import Callback

try:
    from Test.CropToolTest import CropToolTest
except ImportError as e:
    CropToolTest = None
    print(f"CropToolTest could not be imported: {e}")
except Exception as e:
    print(f"[Exception] CropToolTest could not be imported: {e}")


class VectorInputWidget(qt.QWidget):
    def __init__(self, parent=None, separator="×", inputBoxBuilder: typing.Callable = None):
        super().__init__(parent)
        self.setLayout(qt.QHBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().setSpacing(4)
        self.layout().setAlignment(qt.Qt.AlignLeft)
        self.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Fixed)

        if inputBoxBuilder is None:
            inputBoxBuilder = lambda: ui.numberParam((-99999999.0, 99999999.0), step=0.5, decimals=1)

        self.xSpinBox = inputBoxBuilder()
        self.ySpinBox = inputBoxBuilder()
        self.zSpinBox = inputBoxBuilder()

        self.layout().addWidget(self.xSpinBox)
        self.layout().addWidget(qt.QLabel(separator))
        self.layout().addWidget(self.ySpinBox)
        self.layout().addWidget(qt.QLabel(separator))
        self.layout().addWidget(self.zSpinBox)

    def onCopyButtonClicked(self):
        text = f"({self.xSpinBox.value}, {self.ySpinBox.value}, {self.zSpinBox.value})"
        qt.QApplication.clipboard().setText(text)

    def values(self):
        return self.xSpinBox.value, self.ySpinBox.value, self.zSpinBox.value

    def setValues(self, x, y, z):
        self.xSpinBox.setValue(x)
        self.ySpinBox.setValue(y)
        self.zSpinBox.setValue(z)

    def setRange(self, x, y, z):
        self.xSpinBox.setRange(-x, x)
        self.ySpinBox.setRange(-y, y)
        self.zSpinBox.setRange(-z, z)

    def blockSignals(self, state):
        self.xSpinBox.blockSignals(state)
        self.ySpinBox.blockSignals(state)
        self.zSpinBox.blockSignals(state)

    def hasFocus(self):
        return any([box.hasFocus() for box in (self.xSpinBox, self.ySpinBox, self.zSpinBox)])

    def addButton(self, button):
        index = self.layout().count()
        self.layout().insertWidget(index, button)


class VolumeInputTableWidget(qt.QWidget):
    visibilityChanged = qt.Signal(object, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.volumes = []

        self.volumeInputComboBox = slicer.qMRMLNodeComboBox()
        self.volumeInputComboBox.nodeTypes = [
            "vtkMRMLScalarVolumeNode",
            "vtkMRMLVectorVolumeNode",
            "vtkMRMLLabelMapVolumeNode",
        ]
        self.volumeInputComboBox.selectNodeUponCreation = False
        self.volumeInputComboBox.addEnabled = False
        self.volumeInputComboBox.removeEnabled = False
        self.volumeInputComboBox.noneEnabled = True
        self.volumeInputComboBox.showHidden = False
        self.volumeInputComboBox.showChildNodeTypes = False
        self.volumeInputComboBox.setMRMLScene(slicer.mrmlScene)
        self.volumeInputComboBox.setToolTip("Select an image to add to the list.")
        self.addButton = qt.QPushButton("Add")

        inputLayout = qt.QHBoxLayout()
        inputLayout.addWidget(self.volumeInputComboBox)
        inputLayout.addWidget(self.addButton)

        self.volumeTableWidget = qt.QTableWidget()
        self.volumeTableWidget.setColumnCount(3)
        self.volumeTableWidget.setHorizontalHeaderLabels(["Visible", "Name", ""])
        self.volumeTableWidget.horizontalHeader().setSectionResizeMode(0, qt.QHeaderView.ResizeToContents)
        self.volumeTableWidget.horizontalHeader().setSectionResizeMode(1, qt.QHeaderView.Stretch)
        self.volumeTableWidget.horizontalHeader().setSectionResizeMode(2, qt.QHeaderView.ResizeToContents)

        formLayout = qt.QFormLayout(self)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)
        formLayout.addRow("Image: ", inputLayout)
        formLayout.addRow(self.volumeTableWidget)

        self.addButton.clicked.connect(self.onAddButtonClicked)

    def onAddButtonClicked(self):
        node = self.volumeInputComboBox.currentNode()
        if node and node not in self.volumes:
            self.volumes.append(node)
            self.updateVolumeTable()

    def updateVolumeTable(self):
        previousVisibleVolumeIndex = min(self.getVisibleVolumeIndex() or 0, len(self.volumes) - 1)
        self.volumeTableWidget.setRowCount(0)
        self.volumeTableWidget.setRowCount(len(self.volumes))
        for i, node in enumerate(self.volumes):
            visibleButton = qt.QRadioButton()
            visibleButton.setChecked(i == previousVisibleVolumeIndex)
            self.volumeTableWidget.setCellWidget(i, 0, visibleButton)
            visibleButton.toggled.connect(lambda checked, index=i: self.onVisibilityChanged(index, checked))

            item = qt.QTableWidgetItem(node.GetName())
            self.volumeTableWidget.setItem(i, 1, item)

            removeButton = qt.QPushButton("Remove")
            self.volumeTableWidget.setCellWidget(i, 2, removeButton)
            removeButton.clicked.connect(lambda _, index=i: self.onRemoveButtonClicked(index))

        if self.volumes:
            self.onVisibilityChanged(previousVisibleVolumeIndex, True)
        else:
            self.visibilityChanged.emit(None, False)

    def onRemoveButtonClicked(self, index):
        self.volumes.pop(index)
        self.updateVolumeTable()

    def getVisibleVolume(self):
        for i in range(self.volumeTableWidget.rowCount):
            if self.volumeTableWidget.cellWidget(i, 0).isChecked():
                return self.volumes[i]
        return None

    def getVisibleVolumeIndex(self):
        for i in range(self.volumeTableWidget.rowCount):
            if self.volumeTableWidget.cellWidget(i, 0).isChecked():
                return i
        return None

    def onVisibilityChanged(self, index, checked):
        if not checked:
            if not self.getVisibleVolume():
                self.visibilityChanged.emit(None, False)
            return

        for i in range(self.volumeTableWidget.rowCount):
            if i != index:
                self.volumeTableWidget.cellWidget(i, 0).blockSignals(True)
                self.volumeTableWidget.cellWidget(i, 0).setChecked(False)
                self.volumeTableWidget.cellWidget(i, 0).blockSignals(False)

        volume = self.volumes[index]
        self.visibilityChanged.emit(volume, checked)

    def getVolumes(self):
        return self.volumes

    def clear(self):
        self.volumeInputComboBox.setCurrentNode(None)
        self.volumes = []
        self.updateVolumeTable()


class CropTool(LTracePlugin):
    SETTING_KEY = "CropTool"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Crop"
        self.parent.categories = [
            "Tools",
            "MicroCT",
            "Thin Section",
            "Core",
            "Multiscale",
        ]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]

        self.setHelpUrl("Volumes/Crop/Crop.html", NodeEnvironment.MICRO_CT)
        self.setHelpUrl("ThinSection/Crop/Crop.html", NodeEnvironment.THIN_SECTION)
        self.setHelpUrl("Core/Crop.html", NodeEnvironment.CORE)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CropToolWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = None
        self.roiNode = None
        self.roiObserver = None
        self.is_internal_roi = False

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = CropToolLogic()

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        loadFormLayout = qt.QFormLayout(frame)
        loadFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        loadFormLayout.setContentsMargins(4, 4, 4, 4)

        # Input section
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        self.inputCollapsibleButton = inputCollapsibleButton
        loadFormLayout.addRow(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignLeft)

        self.volumeInputTableWidget = VolumeInputTableWidget()
        self.volumeInputTableWidget.visibilityChanged.connect(self.onVisibilityChanged)
        inputFormLayout.addRow(self.volumeInputTableWidget)

        # Parameters section
        self.parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        self.parametersCollapsibleButton.setText("Parameters")
        loadFormLayout.addRow(self.parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(self.parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignLeft)
        parametersFormLayout.setContentsMargins(8, 8, 8, 8)
        parametersFormLayout.setSpacing(4)

        tipsCollapsibleButton = ctk.ctkCollapsibleButton()
        tipsCollapsibleButton.setText("Tips")
        tipsCollapsibleButton.collapsed = True
        tipsCollapsibleButton.flat = True
        tipsVBoxLayout = qt.QVBoxLayout(tipsCollapsibleButton)
        tipsVBoxLayout.setContentsMargins(0, 0, 0, 0)

        tip1 = qt.QLabel(
            "Tip 1: The crop region can be adjusted on the slice views directly by dragging the grid's edges."
        )
        tip1.setWordWrap(True)
        tipsVBoxLayout.addWidget(tip1)

        tip2 = qt.QLabel(
            "Tip 2: To change the crop region symmetrically around the current center, drag the anchors holding down the alt key."
        )
        tip2.setWordWrap(True)
        tipsVBoxLayout.addWidget(tip2)

        parametersFormLayout.addRow(tipsCollapsibleButton)

        self.roiSelector = slicer.qMRMLNodeComboBox()
        self.roiSelector.nodeTypes = ["vtkMRMLMarkupsROINode"]
        self.roiSelector.selectNodeUponCreation = False
        self.roiSelector.addEnabled = False
        self.roiSelector.removeEnabled = False
        self.roiSelector.noneEnabled = True
        self.roiSelector.showHidden = False
        self.roiSelector.setMRMLScene(slicer.mrmlScene)
        self.roiSelector.setToolTip(
            "(Optional) Select an existing ROI to define the crop region. If none is selected, a new one will be created."
        )
        self.roiSelector.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Fixed)
        parametersFormLayout.addRow("Copy from:", self.roiSelector)

        self.gridCenterWidget = VectorInputWidget(
            inputBoxBuilder=lambda: ui.numberParam((0, 99999999), value=0, step=0.5, decimals=1)
        )
        self.gridCenterWidget.xSpinBox.valueChanged.connect(self.onGridParametersChanged)
        self.gridCenterWidget.ySpinBox.valueChanged.connect(self.onGridParametersChanged)
        self.gridCenterWidget.zSpinBox.valueChanged.connect(self.onGridParametersChanged)

        self.historyCenterButton = qt.QPushButton("...")
        self.historyCenterButton.setFixedWidth(24)
        self.historyCenterButton.setToolTip("Show previous centers")
        self.historyCenterButton.clicked.connect(
            lambda: self.onShowHistory("PreviousCrop/Center", self.gridCenterWidget, self.historyCenterButton)
        )
        self.gridCenterWidget.addButton(self.historyCenterButton)

        parametersFormLayout.addRow("Center:", self.gridCenterWidget)

        self.gridSizeWidget = VectorInputWidget(
            inputBoxBuilder=lambda: ui.numberParam((0, 99999999), value=0.0, step=1, decimals=1)
        )
        self.gridSizeWidget.xSpinBox.valueChanged.connect(self.onGridParametersChanged)
        self.gridSizeWidget.ySpinBox.valueChanged.connect(self.onGridParametersChanged)
        self.gridSizeWidget.zSpinBox.valueChanged.connect(self.onGridParametersChanged)

        self.historySizeButton = qt.QPushButton("...")
        self.historySizeButton.setFixedWidth(24)
        self.historySizeButton.setToolTip("Show previous dimensions")
        self.historySizeButton.clicked.connect(
            lambda: self.onShowHistory("PreviousCrop/Size", self.gridSizeWidget, self.historySizeButton)
        )
        self.gridSizeWidget.addButton(self.historySizeButton)

        parametersFormLayout.addRow("Dimensions:", self.gridSizeWidget)

        self.copyAttributesCheckBox = qt.QCheckBox("Copy attributes and references")
        self.copyAttributesCheckBox.setToolTip(
            "If checked, the cropped volume will inherit all attributes and references from the original volume."
        )
        parametersFormLayout.addRow(self.copyAttributesCheckBox)

        self.keepROIAfterCropCheckBox = qt.QCheckBox("Keep ROI after crop")
        self.keepROIAfterCropCheckBox.setToolTip(
            "If checked, the ROI will be available after cropping. This allows using the same ROI to crop multiple volumes."
        )
        parametersFormLayout.addRow(self.keepROIAfterCropCheckBox)

        self.applyCancelButtons = ui.ApplyCancelButtons(
            onApplyClick=self.onCropButtonClicked,
            onCancelClick=self.onCancelButtonClicked,
            applyTooltip="Crop All",
            cancelTooltip="Cancel",
            applyText="Crop All",
            cancelText="Cancel",
            enabled=True,
        )
        loadFormLayout.addWidget(self.applyCancelButtons)

        statusLabel = qt.QLabel("Status: ")
        self.currentStatusLabel = qt.QLabel("Idle")
        statusHBoxLayout = qt.QHBoxLayout()
        statusHBoxLayout.addStretch(1)
        statusHBoxLayout.addWidget(statusLabel)
        statusHBoxLayout.addWidget(self.currentStatusLabel)
        self.layout.addLayout(statusHBoxLayout)

        self.progressBar = qt.QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        self.layout.addWidget(self.progressBar)
        self.progressBar.hide()

        self.progressMux = Lock()

        self.roiSelector.currentNodeChanged.connect(self.onRoiSelectionChanged)

        self.layout.addStretch()

        self.roiSelector.setEnabled(False)
        self.gridSizeWidget.setEnabled(False)
        self.gridCenterWidget.setEnabled(False)
        self.applyCancelButtons.setEnabled(False)

    def onRoiSelectionChanged(self, node=None):
        if self.roiNode and self.roiObserver:
            self.roiNode.RemoveObserver(self.roiObserver)
            self.roiNode = None
            helpers.removeTemporaryNodes()

        volume = self.volumeInputTableWidget.getVisibleVolume()
        if not volume:
            return

        roiNode = helpers.createTemporaryNode(
            slicer.vtkMRMLMarkupsROINode, f"Crop ROI for {volume.GetName()}", uniqueName=True
        )
        roiNode.SetDisplayVisibility(False)
        roiNode.GetDisplayNode().SetFillOpacity(0.5)

        if node:
            roiNode.CopyContent(node)

        self.roiNode = roiNode

        if self.roiNode:
            self.roiObserver = self.roiNode.AddObserver(
                slicer.vtkMRMLMarkupsROINode.PointModifiedEvent, self.onRoiModified
            )
            self.roiNode.SetDisplayVisibility(True)

        self.updateUiFromRoi()

    def onVisibilityChanged(self, volume, checked):
        # if not checked:
        #     if self.roiNode:
        #         self.roiNode.SetDisplayVisibility(False)
        #     self.updateUiFromRoi()
        #     return

        # Hide all segmentations to avoid confusion with the ROI
        nodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        for node in nodes:
            node.GetDisplayNode().SetVisibility(False)

        if not self.roiSelector.currentNode():
            # self.roiSelector.blockSignals(True)
            # self.roiSelector.setCurrentNode(roiNode)
            # self.roiSelector.blockSignals(False)
            self.onRoiSelectionChanged()

        self.logic.initializeVolume(volume, self.roiNode)
        self.updateUiFromRoi()

    def updateUiFromRoi(self):
        volume = self.volumeInputTableWidget.getVisibleVolume()
        if not self.roiNode or not volume:
            self.roiSelector.setEnabled(False)
            self.gridSizeWidget.setEnabled(False)
            self.gridCenterWidget.setEnabled(False)
            self.applyCancelButtons.setEnabled(False)
            return

        try:
            self.gridSizeWidget.blockSignals(True)
            self.gridCenterWidget.blockSignals(True)

            center = self.logic.getSelectionCenter(volume, self.roiNode)
            self.gridCenterWidget.setValues(*center)

            size = self.logic.getSelectionSize(volume, self.roiNode)
            self.gridSizeWidget.setValues(*size)

            self.gridSizeWidget.blockSignals(False)
            self.gridCenterWidget.blockSignals(False)

            self.roiSelector.setEnabled(True)
            self.gridSizeWidget.setEnabled(True)
            self.gridCenterWidget.setEnabled(True)
            self.applyCancelButtons.setEnabled(True)
        except Exception as e:
            logging.error(f"Failed to update UI from ROI: {e}")
            self.roiSelector.setEnabled(False)
            self.gridSizeWidget.setEnabled(False)
            self.gridCenterWidget.setEnabled(False)
            self.applyCancelButtons.setEnabled(False)

    def onRoiModified(self, caller, event):
        with helpers.BlockSignals(self.roiSelector):
            self.roiSelector.setCurrentNode(None)

        self.updateUiFromRoi()

    def onCropButtonClicked(self):
        callback = Callback(
            on_update=lambda message, percent, processEvents=True: self.updateStatus(
                message,
                progress=percent,
                processEvents=processEvents,
            )
        )
        try:
            volumes = self.volumeInputTableWidget.getVolumes()
            if not volumes:
                raise CropInfo("No images to be cropped.")

            size = self.gridSizeWidget.values()
            center = self.gridCenterWidget.values()

            self.saveHistory("PreviousCrop/Size", size)
            self.saveHistory("PreviousCrop/Center", center)

            deepCopy = self.copyAttributesCheckBox.isChecked()
            keepROI = self.keepROIAfterCropCheckBox.isChecked()

            ijkSize = self.gridSizeWidget.values()
            for i, volume in enumerate(volumes):
                callback.on_update(f"Cropping {volume.GetName()}...", (i / len(volumes)) * 100)
                cropped = self.logic.crop(volume, self.roiNode, ijkSize, deepCopy=deepCopy)
                self.logic.joinScene(volume, cropped)

            if keepROI:
                helpers.makeTemporaryNodePermanent(self.roiNode, show=True)
                self.roiNode.SetDisplayVisibility(False)
                # Detach the ROI node from the widget so it won't be deleted in deleteDanglingObjects
                self.roiNode = None

            self.gridSizeWidget.setValues(0, 0, 0)
            self.gridCenterWidget.setValues(0, 0, 0)

        except CropInfo as e:
            slicer.util.infoDisplay(str(e))
        finally:
            callback.on_update("", 100)
            self.deleteDanglingObjects()
            # Delete the temporary crop volume parameters node because it is probably broken.
            helpers.removeTemporaryNodes()

    def onCancelButtonClicked(self):
        if self.roiNode:
            self.roiNode.SetDisplayVisibility(False)
        self.volumeInputTableWidget.clear()

        self.gridSizeWidget.setValues(0, 0, 0)
        self.gridCenterWidget.setValues(0, 0, 0)
        self.copyAttributesCheckBox.setChecked(False)
        self.keepROIAfterCropCheckBox.setChecked(False)

    def onGridParametersChanged(self, value):
        volume = self.volumeInputTableWidget.getVisibleVolume()
        if volume is None or self.roiNode is None:
            return

        size = self.gridSizeWidget.values()
        center = self.gridCenterWidget.values()

        if self.roiObserver:
            self.roiNode.RemoveObserver(self.roiObserver)

        self.logic.setXYZRadiusFromIJK(volume, self.roiNode, size)
        self.logic.setRoiCenterIjk(volume, self.roiNode, center)

        with helpers.BlockSignals(self.roiSelector):
            self.roiSelector.setCurrentNode(None)

        if self.roiNode:
            self.roiObserver = self.roiNode.AddObserver(
                slicer.vtkMRMLMarkupsROINode.PointModifiedEvent, self.onRoiModified
            )

    def onShowHistory(self, key, widget, button):
        history = CropTool.get_setting(key, [])

        if not history or not isinstance(history, (list, tuple)):
            logging.warning("No history found or history is in an invalid format.")
            slicer.util.infoDisplay("No history found.")
            return

        # Handle migration or invalid data: if first element is not a list, it's old format
        if history and not isinstance(history[0], (list, tuple)):
            logging.warning("History entry is in an invalid format.")
            slicer.util.infoDisplay("Bad format of history found. Resetting history.")
            return

        menu = qt.QMenu(self.parent)
        menu.setStyleSheet(
            "QMenu { border: 1px solid #555555; border-radius: 3px; padding: 3px; }"
        )  # Make the menu scrollable if there are many entries
        for entry in history:
            if not isinstance(entry, (list, tuple)):
                continue
            try:
                text = " × ".join([f"{float(v)}" for v in entry])
                action = menu.addAction(text)
                # Use default argument in lambda to capture 'entry' correctly
                action.triggered.connect(lambda _, e=entry: widget.setValues(*[float(v) for v in e]))
            except (ValueError, TypeError, IndexError):
                continue

        if not menu.isEmpty():
            menu.exec_(button.mapToGlobal(qt.QPoint(0, button.height)))

    def saveHistory(self, key, value):
        history = CropTool.get_setting(key, [])

        if not isinstance(history, list):
            history = list(history) if isinstance(history, Iterable) else []

        lastCropConfig = tuple([int(v) for v in value])

        # Remove if already exists (check as list of strings)
        try:
            history.remove(lastCropConfig)
        except ValueError:
            logging.debug("Current configuration not in history, adding new entry.")

        history = [lastCropConfig, *history[:9]]

        CropTool.set_setting(key, history)

    def enter(self) -> None:
        super().enter()

    def deleteDanglingObjects(self):
        if self.roiNode and self.roiObserver:
            self.roiNode.RemoveObserver(self.roiObserver)
        if self.roiNode:
            slicer.mrmlScene.RemoveNode(self.roiNode)

        self.roiObserver = None
        self.roiNode = None

    def exit(self):
        self.onCancelButtonClicked()
        self.deleteDanglingObjects()

    def updateStatus(self, message, progress=None, processEvents=True):
        self.progressBar.show()
        self.currentStatusLabel.text = message

        if progress == -1:
            self.progressBar.setRange(0, 0)
        else:
            self.progressBar.setRange(0, 100)
            self.progressBar.setValue(progress)
            if self.progressBar.value == 100:
                self.progressBar.hide()
                self.currentStatusLabel.text = "Idle"

        if not processEvents:
            return
        if self.progressMux.locked():
            return

        with self.progressMux:
            slicer.app.processEvents()

    def cleanup(self):
        super().cleanup()
        self.exit()


class CropToolLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def initializeVolume(self, volume, roiNode):
        if volume is not None and roiNode is not None:
            cropVolumeParameters = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLCropVolumeParametersNode.__name__)
            cropVolumeParameters.SetIsotropicResampling(True)
            cropVolumeParameters.SetInputVolumeNodeID(volume.GetID())
            cropVolumeParameters.SetROINodeID(roiNode.GetID())
            slicer.modules.cropvolume.logic().FitROIToInputVolume(cropVolumeParameters)
            roiNode.SetDisplayVisibility(True)
            slicer.util.setSliceViewerLayers(foreground=None, background=volume, label=None, fit=True)
            slicer.mrmlScene.RemoveNode(cropVolumeParameters)
        elif roiNode is not None:
            roiNode.SetDisplayVisibility(False)

    def crop(self, volume, roiNode, ijkSize, deepCopy=False):
        try:
            position_ras = [0] * 3
            if roiNode is not None:
                roiNode.GetCenter(position_ras)

            volumeShape = volume.GetImageData().GetDimensions()

            position_ijk = rasToIJK(volume, position_ras)

            start = [int(round(x - (size / 2.0) + 0.5)) for x, size in zip(position_ijk[:3], ijkSize)]
            end = [int(begin + size) for begin, size in zip(start, ijkSize)]

            start = [0 if st < 0 else st for st in start]
            end = [dim if en > dim else en for en, dim in zip(end, volumeShape)]

            new_origin = ijkToRAS(volume, start)

            resultBufferNode = helpers.createTemporaryVolumeNode(
                volume.__class__, volume.GetName() + "_Cropped", content=volume, uniqueName=True
            )

            self.__sliceVolume(resultBufferNode, start, end, new_origin)

            copy_display(volume, resultBufferNode)
            copy_metadata(volume, resultBufferNode)

            if deepCopy:
                copy_attributes(volume, resultBufferNode)
                copy_hierarchy_attributes(volume, resultBufferNode)
                resultBufferNode.CopyReferences(volume)

            helpers.makeTemporaryNodePermanent(resultBufferNode, show=True)

            return resultBufferNode
        except Exception as e:
            logging.error(f"Error during cropping: {e}")
            raise

    def __sliceVolume(self, volume, start, end, new_origin):
        array = slicer.util.arrayFromVolume(volume)
        slices = tuple([slice(st, en) for st, en in zip(start, end)])
        croppedArray = array[tuple(reversed(slices))]
        slicer.util.updateVolumeFromArray(volume, croppedArray)
        volume.SetOrigin(new_origin)

    def joinScene(self, volume, croppedVolume):
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        outputDir = folderTree.GetItemParent(folderTree.GetItemByDataNode(volume))
        helpers.moveNodeTo(outputDir, croppedVolume, dirTree=folderTree)

        slicer.util.setSliceViewerLayers(background=croppedVolume, fit=True)

    def getSelectionSize(self, volume, roiNode):
        if roiNode is None:
            return 0, 0, 0

        radius = [0] * 3
        roiNode.GetRadiusXYZ(radius)

        rasSize = [r * 2 for r in radius]
        spacing = volume.GetSpacing()

        ijkSizeClipped = tuple(round(rasDim / spacingDim) for rasDim, spacingDim in zip(rasSize, spacing))

        return ijkSizeClipped

    def getSelectionCenter(self, volume, roiNode):
        if roiNode is None:
            return 0, 0, 0

        position = [0] * 3
        roiNode.GetCenter(position)
        return rasToIJK(volume, position)

    def setXYZRadiusFromIJK(self, volume, roiNode, ijkSize):
        if roiNode is None:
            return

        spacing = volume.GetSpacing()
        rasRadius = tuple(0.5 * ijkDim * spacingDim for ijkDim, spacingDim in zip(ijkSize, spacing))
        roiNode.SetRadiusXYZ(rasRadius)

    def setRoiCenterIjk(self, volume, roiNode, ijkCenter):
        if roiNode is None:
            return

        rasCenter = ijkToRAS(volume, ijkCenter)
        roiNode.SetXYZ(rasCenter)


class CropInfo(RuntimeError):
    pass
