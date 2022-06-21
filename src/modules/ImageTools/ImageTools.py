import os
from pathlib import Path

import slicer.util
from Customizer import Customizer
from ltrace.slicer_utils import *

from ImageToolsLib import *


class ImageTools(LTracePlugin):
    SETTING_KEY = "ImageTools"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Image Tools"
        self.parent.categories = ["LTrace Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ImageTools.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ImageToolsWidget(LTracePluginWidget):
    TOOL_NONE = 0
    TOOL_BRIGHTNESS_CONTRAST = 1
    TOOL_SATURATION = 2
    TOOL_HISTOGRAM_EQUALIZATION = 3
    TOOL_SHADING_CORRECTION = 4

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.currentNode = None
        self.toolWidgets = {}
        self.currentToolWidget = None
        self.currentToolIndex = self.TOOL_NONE
        self.imageArray = None

    def setup(self):
        LTracePluginWidget.setup(self)

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        self.formLayout = qt.QFormLayout(frame)
        self.formLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.imageComboBox = slicer.qMRMLNodeComboBox()
        self.imageComboBox.nodeTypes = ["vtkMRMLVectorVolumeNode"]
        self.imageComboBox.addEnabled = False
        self.imageComboBox.removeEnabled = False
        self.imageComboBox.noneEnabled = True
        self.imageComboBox.noneDisplay = "Select an image"
        self.imageComboBox.setMRMLScene(slicer.mrmlScene)
        self.imageComboBox.setToolTip("Select an image.")
        self.imageComboBox.currentNodeChanged.connect(self.onImageComboBoxCurrentNodeChanged)

        self.showImageButton = qt.QPushButton("Show image")
        self.showImageButton.setFixedWidth(150)
        self.showImageButton.setToolTip("Show the selected image in the slice views.")
        self.showImageButton.enabled = False
        self.showImageButton.clicked.connect(self.onShowImageButtonClicked)

        imageHBoxLayout = qt.QHBoxLayout()
        imageHBoxLayout.addWidget(self.imageComboBox)
        imageHBoxLayout.addWidget(self.showImageButton)
        self.formLayout.addRow("Image:", imageHBoxLayout)

        self.toolLabel = qt.QLabel("Tool:")
        self.toolLabel.setVisible(False)
        self.toolComboBox = qt.QComboBox()
        self.toolComboBox.addItem("Select a tool", self.TOOL_NONE)
        self.toolComboBox.addItem("Brightness/Contrast", self.TOOL_BRIGHTNESS_CONTRAST)
        self.toolComboBox.addItem("Saturation", self.TOOL_SATURATION)
        self.toolComboBox.addItem("Histogram Equalization", self.TOOL_HISTOGRAM_EQUALIZATION)
        self.toolComboBox.addItem("Shading Correction", self.TOOL_SHADING_CORRECTION)
        self.toolComboBox.setCurrentIndex(self.TOOL_NONE)
        self.toolComboBox.setVisible(False)
        self.toolComboBox.setToolTip("Select an image tool.")
        self.toolComboBox.currentIndexChanged.connect(self.onToolComboBoxCurrentIndexChanged)
        self.formLayout.addRow(self.toolLabel, self.toolComboBox)

        # Tool widgets
        self.addToolWidget(BrightnessContrastWidget)
        self.addToolWidget(SaturationWidget)
        self.addToolWidget(NewHistogramEqualizationWidget)
        self.addToolWidget(ShadingCorrectionWidget)
        self.hideToolWidgets()

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setIcon(qt.QIcon(str(Customizer.APPLY_ICON_PATH)))
        self.applyButton.setToolTip(
            "Apply the current tool changes. These changes can be undone, unless you click Save."
        )
        self.applyButton.enabled = False
        self.applyButton.clicked.connect(self.onApplyButtonClicked)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setIcon(qt.QIcon(str(Customizer.CANCEL_ICON_PATH)))
        self.cancelButton.setToolTip("Cancel the current tool changes.")
        self.cancelButton.enabled = False
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        self.undoButton = qt.QPushButton("Undo")
        self.undoButton.setIcon(qt.QIcon(str(Customizer.UNDO_ICON_PATH)))
        self.undoButton.setToolTip(
            "Undo applied tool changes. The earliest undo is where the image was loaded or saved."
        )
        self.undoButton.enabled = False
        self.undoButton.clicked.connect(self.onUndoButtonClicked)

        self.redoButton = qt.QPushButton("Redo")
        self.redoButton.setIcon(qt.QIcon(str(Customizer.REDO_ICON_PATH)))
        self.redoButton.setToolTip("Redo applied tool changes.")
        self.redoButton.enabled = False
        self.redoButton.clicked.connect(self.onRedoButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.applyButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        buttonsHBoxLayout.addWidget(self.undoButton)
        buttonsHBoxLayout.addWidget(self.redoButton)
        self.formLayout.addRow(buttonsHBoxLayout)

        self.saveButton = qt.QPushButton("Save")
        self.saveButton.setIcon(qt.QIcon(str(Customizer.SAVE_ICON_PATH)))
        self.saveButton.setToolTip("Save the applied tool changes. This action cannot be undone.")
        self.saveButton.enabled = False
        self.saveButton.clicked.connect(self.onSaveButtonClicked)

        self.resetButton = qt.QPushButton("Reset")
        self.resetButton.setIcon(qt.QIcon(str(Customizer.RESET_ICON_PATH)))
        self.resetButton.setToolTip("Reset the applied tool changes to the last saved state.")
        self.resetButton.enabled = False
        self.resetButton.clicked.connect(self.onResetButtonClicked)

        saveResetButtonsHBoxLayout = qt.QHBoxLayout()
        saveResetButtonsHBoxLayout.addWidget(self.saveButton)
        saveResetButtonsHBoxLayout.addWidget(self.resetButton)
        self.formLayout.addRow(saveResetButtonsHBoxLayout)

        self.layout.addStretch()

    def addToolWidget(self, toolWidgetClass):
        self.toolWidgets[toolWidgetClass.__name__] = toolWidgetClass(self)
        self.formLayout.addRow(self.toolWidgets[toolWidgetClass.__name__])

    def resetToolWidgets(self):
        for key, value in self.toolWidgets.items():
            value.reset()

        if (
            self.currentToolIndex == self.TOOL_HISTOGRAM_EQUALIZATION
            or self.currentToolIndex == self.TOOL_SHADING_CORRECTION
        ):
            self.currentToolWidget.setVisible(False)
            self.currentToolWidget = None
            self.toolComboBox.blockSignals(True)
            self.toolComboBox.setCurrentIndex(self.TOOL_NONE)
            self.toolComboBox.blockSignals(False)
            self.currentToolIndex = self.TOOL_NONE

    def hideToolWidgets(self):
        for key, value in self.toolWidgets.items():
            value.setVisible(False)

    def onCancelButtonClicked(self):
        slicer.util.updateVolumeFromArray(self.currentNode, self.imageArray)
        self.configureButtonsState()
        self.resetToolWidgets()

    def onApplyButtonClicked(self):
        node = self.currentNode
        dataType = self.imageArray.dtype
        newArray = slicer.util.arrayFromVolume(node).copy()
        if np.issubdtype(dataType, np.integer):
            newArray = np.around(newArray)
        newArray = newArray.astype(dataType)
        slicer.util.updateVolumeFromArray(node, self.imageArray)
        slicer.mrmlScene.SaveStateForUndo(node)
        slicer.util.updateVolumeFromArray(node, newArray)
        self.imageArray = slicer.util.arrayFromVolume(node).copy()
        self.configureButtonsState()
        self.resetToolWidgets()

    def onShowImageButtonClicked(self):
        slicer.util.setSliceViewerLayers(background=self.imageComboBox.currentNode())
        slicer.util.resetSliceViews()

    def onImageComboBoxCurrentNodeChanged(self, node):
        if self.applyButton.isEnabled():
            message = "The current tool changes to the image were not applied and will be lost. Are you sure you want to exit the current tool?"
            if slicer.util.confirmYesNoDisplay(message):
                slicer.util.updateVolumeFromArray(self.currentNode, self.imageArray)
                self.applyButton.enabled = False
                self.cancelButton.enabled = False
            else:
                self.imageComboBox.blockSignals(True)
                self.imageComboBox.setCurrentNode(self.currentNode)
                self.imageComboBox.blockSignals(False)
                return

        saveImageAnswer = None
        if slicer.mrmlScene.GetNumberOfUndoLevels() > 0 or slicer.mrmlScene.GetNumberOfRedoLevels() > 0:
            messageBox = qt.QMessageBox()
            saveImageAnswer = messageBox.question(
                self.__mainWindow,
                "GeoSlicer confirmation",
                "Save the changes to the image before exiting?",
                qt.QMessageBox.Yes | qt.QMessageBox.No | qt.QMessageBox.Cancel,
            )
            if saveImageAnswer == qt.QMessageBox.Cancel:
                self.imageComboBox.blockSignals(True)
                self.imageComboBox.setCurrentNode(self.currentNode)
                self.imageComboBox.blockSignals(False)
            else:
                if saveImageAnswer == qt.QMessageBox.Yes:
                    self.endUndoRedoState(False)
                else:
                    self.endUndoRedoState(True)
                self.configureButtonsState()

        self.resetToolWidgets()
        if saveImageAnswer != qt.QMessageBox.Cancel:
            self.hideToolWidgets()
            self.currentNode = node

            self.toolComboBox.blockSignals(True)
            self.toolComboBox.setCurrentIndex(self.TOOL_NONE)
            self.toolComboBox.blockSignals(False)
            self.toolLabel.setVisible(node is not None)
            self.toolComboBox.setVisible(node is not None)

            if node is not None:
                node.GetDisplayNode().SetAutoWindowLevel(0)  # To avoid brightness adjustments cancellation
                self.imageArray = slicer.util.arrayFromVolume(node).copy()
                self.showImageButton.enabled = True
                self.startUndoRedoState()
            else:
                self.showImageButton.enabled = False

    def onToolComboBoxCurrentIndexChanged(self, index):
        if self.applyButton.isEnabled():
            message = "The current changes to the image are not applied and will be lost. Are you sure you want to exit the current tool?"
            if slicer.util.confirmYesNoDisplay(message):
                slicer.util.updateVolumeFromArray(self.currentNode, self.imageArray)
                self.applyButton.enabled = False
                self.cancelButton.enabled = False
            else:
                self.toolComboBox.blockSignals(True)
                self.toolComboBox.setCurrentIndex(self.currentToolIndex)
                self.toolComboBox.blockSignals(False)
                return

        self.currentToolIndex = index

        if self.currentToolWidget:
            self.currentToolWidget.reset()
            self.currentToolWidget.setVisible(False)

        if index == self.TOOL_NONE:
            self.currentToolWidget = None
            return
        elif index == self.TOOL_BRIGHTNESS_CONTRAST:
            self.currentToolWidget = self.toolWidgets[BrightnessContrastWidget.__name__]
        elif index == self.TOOL_SATURATION:
            self.currentToolWidget = self.toolWidgets[SaturationWidget.__name__]
        elif index == self.TOOL_HISTOGRAM_EQUALIZATION:
            self.currentToolWidget = self.toolWidgets[NewHistogramEqualizationWidget.__name__]
        elif index == self.TOOL_SHADING_CORRECTION:
            self.currentToolWidget = self.toolWidgets[ShadingCorrectionWidget.__name__]
        self.currentToolWidget.setVisible(True)
        self.currentToolWidget.select()

    def startUndoRedoState(self):
        slicer.mrmlScene.SetUndoOn()
        if self.currentNode is not None:
            self.currentNode.UndoEnabledOn()

    def endUndoRedoState(self, resetImage):
        if resetImage:
            for i in range(slicer.mrmlScene.GetNumberOfUndoLevels()):
                slicer.mrmlScene.Undo()
        slicer.mrmlScene.ClearUndoStack()
        slicer.mrmlScene.ClearRedoStack()
        if self.currentNode:
            self.currentNode.UndoEnabledOff()
        slicer.mrmlScene.SetUndoOff()

    def onUndoButtonClicked(self):
        self.onUndoOrRedoButtonClicked(slicer.mrmlScene.Undo)

    def onRedoButtonClicked(self):
        self.onUndoOrRedoButtonClicked(slicer.mrmlScene.Redo)

    def onUndoOrRedoButtonClicked(self, undoOrRedoFunction):
        message = f"The current tool changes to the image were not applied and will be lost. Are you sure you want to {undoOrRedoFunction.__name__.lower()}?"
        if self.applyButton.isEnabled():
            if slicer.util.confirmYesNoDisplay(message):
                slicer.util.updateVolumeFromArray(self.currentNode, self.imageArray)
            else:
                return
        undoOrRedoFunction()
        self.imageArray = slicer.util.arrayFromVolume(self.currentNode).copy()
        self.resetToolWidgets()
        self.configureButtonsState()

    def configureButtonsState(self):
        numberOfUndoLevels = slicer.mrmlScene.GetNumberOfUndoLevels()
        numberOfRedoLevels = slicer.mrmlScene.GetNumberOfRedoLevels()
        self.undoButton.enabled = numberOfUndoLevels
        self.redoButton.enabled = numberOfRedoLevels
        if numberOfUndoLevels > 0 or numberOfRedoLevels > 0:
            self.saveButton.enabled = True
            self.resetButton.enabled = True
        else:
            self.saveButton.enabled = False
            self.resetButton.enabled = False
        self.applyButton.enabled = False
        self.cancelButton.enabled = False

    def onSaveButtonClicked(self):
        newNode = self.cloneVolume(self.currentNode)
        self.endUndoRedoState(True)
        self.resetToolWidgets()
        self.startUndoRedoState()
        self.configureButtonsState()

        self.currentNode = newNode
        self.imageArray = slicer.util.arrayFromVolume(self.currentNode).copy()
        self.imageComboBox.setCurrentNode(self.currentNode)

        self.onShowImageButtonClicked()

    def cloneVolume(self, volume):
        newVolumeName = slicer.mrmlScene.GenerateUniqueName(volume.GetName())
        newVolume = slicer.mrmlScene.AddNewNodeByClass(volume.GetClassName(), newVolumeName)
        slicer.util.updateVolumeFromArray(newVolume, slicer.util.arrayFromVolume(volume).copy())
        newVolume.SetOrigin(volume.GetOrigin())
        newVolume.SetSpacing(volume.GetSpacing())
        directions = np.eye(3)
        volume.GetIJKToRASDirections(directions)
        newVolume.SetIJKToRASDirections(directions)

        displayNode = volume.GetDisplayNode()
        newVolume.CreateDefaultDisplayNodes()
        newVolume.CreateDefaultStorageNode()
        newVolumeDisplayNode = newVolume.GetDisplayNode()
        newVolumeDisplayNode.AutoWindowLevelOff()
        newVolumeDisplayNode.SetWindowLevel(displayNode.GetWindow(), displayNode.GetLevel())

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(volume))
        subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(newVolume), itemParent)

        return newVolume

    def onResetButtonClicked(self):
        self.endUndoRedoState(True)
        self.imageArray = slicer.util.arrayFromVolume(self.currentNode).copy()
        self.startUndoRedoState()
        self.resetToolWidgets()
        self.configureButtonsState()

    def reset(self):
        self.endUndoRedoState(True)

        node = self.currentNode
        if node is not None:
            slicer.util.updateVolumeFromArray(node, self.imageArray)
            self.imageArray = None
            self.currentNode = None

        self.imageComboBox.blockSignals(True)
        self.imageComboBox.setCurrentNode(None)
        self.imageComboBox.blockSignals(False)

        if self.currentToolWidget is not None:
            self.currentToolWidget.setVisible(False)
            self.currentToolWidget = None
        self.resetToolWidgets()

        self.toolComboBox.blockSignals(True)
        self.toolComboBox.setCurrentIndex(self.TOOL_NONE)
        self.toolComboBox.blockSignals(False)
        self.toolLabel.setVisible(False)
        self.toolComboBox.setVisible(False)
        self.currentToolIndex = self.TOOL_NONE

        self.configureButtonsState()

    def exit(self):
        if self.applyButton.isEnabled():
            message = (
                "The current changes in the image were not applied and will be lost. Do you want to save the changes?"
            )
            if slicer.util.confirmYesNoDisplay(message):
                self.onApplyButtonClicked()
                self.onSaveButtonClicked()
            else:
                slicer.util.updateVolumeFromArray(self.currentNode, self.imageArray)

        if slicer.mrmlScene.GetNumberOfUndoLevels() > 0 or slicer.mrmlScene.GetNumberOfRedoLevels() > 0:
            messageBox = qt.QMessageBox()
            saveImageAnswer = messageBox.question(
                slicer.util.mainWindow(),
                "GeoSlicer confirmation",
                "Save the changes to the image before exiting?",
                qt.QMessageBox.Yes | qt.QMessageBox.No,  # | qt.QMessageBox.Cancel,
            )
            # if saveImageAnswer == qt.QMessageBox.Cancel:
            #     pass  # @TODO find a way to stop a module from exiting
            # else:
            if saveImageAnswer == qt.QMessageBox.Yes:
                self.endUndoRedoState(False)
            else:
                self.endUndoRedoState(True)
            self.imageArray = slicer.util.arrayFromVolume(self.currentNode).copy()
        self.reset()

    def configureInterfaceForThinSectionRegistrationModule(self):
        self.formLayout.setContentsMargins(0, 0, 0, 0)
        self.showImageButton.setVisible(False)  # To not mess with the comparison view
        self.saveButton.setVisible(False)  # It's only to help placing the landmarks


class ImageToolsInfo(RuntimeError):
    pass
