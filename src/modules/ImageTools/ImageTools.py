import os
import slicer
import numpy as np
import qt

from pathlib import Path

from ImageToolsLib import *
from ltrace.slicer import ui, helpers
from ltrace.slicer.node_observer import NodeObserver
from ltrace.slicer_utils import *
from ltrace.slicer_utils import getResourcePath
from typing import Union

try:
    from Test.ImageToolsTest import ImageToolsTest
except ImportError:
    ImageToolsTest = None


class ImageTools(LTracePlugin):
    SETTING_KEY = "ImageTools"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Filters"
        self.parent.categories = ["Tools", "Thin Section"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.setHelpUrl("ThinSection/Filters/ImageTools.html")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ImageToolsWidget(LTracePluginWidget):
    TOOL_NONE = 0
    TOOL_BRIGHTNESS_CONTRAST = 1
    TOOL_SATURATION = 2
    TOOL_HISTOGRAM_EQUALIZATION = 3
    TOOL_SHADING_CORRECTION = 4

    def __init__(self, parent) -> None:
        LTracePluginWidget.__init__(self, parent)
        self.toolWidgets = {}
        self.currentToolWidget = None
        self.currentToolIndex = self.TOOL_NONE
        self.imageArray = None
        self.__currentNodeObserver: NodeObserver = None
        self.__referenceNodeObserver: NodeObserver = None

    @property
    def currentNode(self) -> Union[None, slicer.vtkMRMLNode]:
        if self.__currentNodeObserver is None:
            return None

        return self.__currentNodeObserver.node

    @property
    def referenceNode(self) -> Union[None, slicer.vtkMRMLNode]:
        if self.__referenceNodeObserver is None:
            return None

        return self.__referenceNodeObserver.node

    def setup(self) -> None:
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
        self.imageComboBox.objectName = "Image Combo Box"

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
        self.toolComboBox.objectName = "Tool Combo Box"
        self.formLayout.addRow(self.toolLabel, self.toolComboBox)

        # Tool widgets
        self.addToolWidget(BrightnessContrastWidget)
        self.addToolWidget(SaturationWidget)
        self.addToolWidget(NewHistogramEqualizationWidget)
        self.addToolWidget(ShadingCorrectionWidget)
        self.hideToolWidgets()

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Apply.png"))
        self.applyButton.setToolTip(
            "Apply the current tool changes. These changes can be undone, unless you click Save."
        )
        self.applyButton.enabled = False
        self.applyButton.clicked.connect(self.onApplyButtonClicked)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Cancel.png"))
        self.cancelButton.setToolTip("Cancel the current tool changes.")
        self.cancelButton.enabled = False
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        self.undoButton = qt.QPushButton("Undo")
        self.undoButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Undo.png"))
        self.undoButton.setToolTip(
            "Undo applied tool changes. The earliest undo is where the image was loaded or saved."
        )
        self.undoButton.enabled = False
        self.undoButton.clicked.connect(self.onUndoButtonClicked)

        self.redoButton = qt.QPushButton("Redo")
        self.redoButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Redo.png"))
        self.redoButton.setToolTip("Redo applied tool changes.")
        self.redoButton.enabled = False
        self.redoButton.clicked.connect(self.onRedoButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.applyButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        buttonsHBoxLayout.addWidget(self.undoButton)
        buttonsHBoxLayout.addWidget(self.redoButton)
        self.formLayout.addRow(buttonsHBoxLayout)

        self.saveResetButtons = ui.ApplyCancelButtons(
            onApplyClick=self.onSaveButtonClicked,
            onCancelClick=self.onResetButtonClicked,
            applyTooltip="Save the applied tool changes. This action cannot be undone.",
            cancelTooltip="Reset the applied tool changes to the last saved state.",
            applyText="Save",
            cancelText="Reset",
            enabled=False,
            applyObjectName=None,
            cancelObjectName=None,
        )
        self.layout.addWidget(self.saveResetButtons)

        self.layout.addStretch()

    def addToolWidget(self, toolWidgetClass) -> None:
        self.toolWidgets[toolWidgetClass.__name__] = toolWidgetClass(self)
        self.formLayout.addRow(self.toolWidgets[toolWidgetClass.__name__])

    def resetToolWidgets(self) -> None:
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

    def hideToolWidgets(self) -> None:
        for key, value in self.toolWidgets.items():
            value.setVisible(False)

    def onCancelButtonClicked(self) -> None:
        self.__cancelLastChanges()

    def __cancelLastChanges(self) -> None:
        self.resetWorkingNode()
        self.configureButtonsState()
        self.resetToolWidgets()

    def onApplyButtonClicked(self) -> None:
        self.__commitChanges()

    def __commitChanges(self) -> None:
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

    def onShowImageButtonClicked(self) -> None:
        self.__showWorkingImage()

    def __showWorkingImage(self) -> None:
        slicer.util.setSliceViewerLayers(background=self.currentNode)
        slicer.util.resetSliceViews()

    def onImageComboBoxCurrentNodeChanged(self, node) -> None:
        invalidNode = self.referenceNode is None or self.currentNode is None
        if not invalidNode and self.applyButton.isEnabled():
            message = "The current tool changes to the image were not applied and will be lost. Are you sure you want to exit the current tool?"
            if slicer.util.confirmYesNoDisplay(message):
                slicer.util.updateVolumeFromArray(self.currentNode, self.imageArray)
                self.applyButton.enabled = False
                self.cancelButton.enabled = False
            else:
                self.imageComboBox.blockSignals(True)
                self.imageComboBox.setCurrentNode(self.referenceNode)
                self.imageComboBox.blockSignals(False)
                return

        saveImageAnswer = None
        if not invalidNode and (
            slicer.mrmlScene.GetNumberOfUndoLevels() > 0 or slicer.mrmlScene.GetNumberOfRedoLevels() > 0
        ):
            messageBox = qt.QMessageBox()
            saveImageAnswer = messageBox.question(
                slicer.modules.AppContextInstance.mainWindow,
                "GeoSlicer confirmation",
                "Save the changes to the image before exiting?",
                qt.QMessageBox.Yes | qt.QMessageBox.No | qt.QMessageBox.Cancel,
            )
            if saveImageAnswer == qt.QMessageBox.Cancel:
                self.imageComboBox.blockSignals(True)
                self.imageComboBox.setCurrentNode(self.referenceNode)
                self.imageComboBox.blockSignals(False)
                return
            else:
                if saveImageAnswer == qt.QMessageBox.Yes:
                    self.endUndoRedoState(False)
                    self.__saveAllChanges()
                else:
                    self.endUndoRedoState(False)
                self.configureButtonsState()

        self.resetToolWidgets()
        self.clearWorkingNode()
        if saveImageAnswer != qt.QMessageBox.Cancel:
            self.hideToolWidgets()
            if node is not None:
                currentNode = helpers.clone_volume(
                    node, name=f"{node.GetName()}_Processed", as_temporary=True, hidden=True, uniqueName=True
                )
                self.__referenceNodeObserver = NodeObserver(node, parent=self.parent)
                self.__referenceNodeObserver.removedSignal.connect(self.onNodeRemoved)
                self.__currentNodeObserver = NodeObserver(currentNode, parent=self.parent)
                self.__currentNodeObserver.removedSignal.connect(self.onNodeRemoved)
                self.imageArray = slicer.util.arrayFromVolume(currentNode).copy()
            else:
                currentNode = None
                if self.__referenceNodeObserver is not None:
                    del self.__referenceNodeObserver
                    self.__referenceNodeObserver = None

                if self.__currentNodeObserver is not None:
                    del self.__currentNodeObserver
                    self.__currentNodeObserver = None

            self.toolComboBox.blockSignals(True)
            self.toolComboBox.setCurrentIndex(self.TOOL_NONE)
            self.toolComboBox.blockSignals(False)
            self.toolLabel.setVisible(node is not None)
            self.toolComboBox.setVisible(node is not None)

            if currentNode is not None and currentNode.GetImageData() is not None:
                currentNode.GetDisplayNode().SetAutoWindowLevel(0)  # To avoid brightness adjustments cancellation
                self.imageArray = slicer.util.arrayFromVolume(node).copy()
                self.showImageButton.enabled = True
                self.startUndoRedoState()
                self.__showWorkingImage()
            else:
                self.showImageButton.enabled = False

    def onNodeRemoved(self) -> None:
        self.__resetAllChanges()
        self.imageComboBox.setCurrentNode(None)

    def onToolComboBoxCurrentIndexChanged(self, index) -> None:
        if self.applyButton.isEnabled():
            message = "The current changes to the image are not applied and will be lost. Are you sure you want to exit the current tool?"
            if slicer.util.confirmYesNoDisplay(message):
                self.resetWorkingNode()
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

    def startUndoRedoState(self) -> None:
        slicer.mrmlScene.SetUndoOn()
        if (currentNode := self.currentNode) is not None:
            currentNode.UndoEnabledOn()

    def endUndoRedoState(self, resetImage) -> None:
        if resetImage:
            for i in range(slicer.mrmlScene.GetNumberOfUndoLevels()):
                slicer.mrmlScene.Undo()
        slicer.mrmlScene.ClearUndoStack()
        slicer.mrmlScene.ClearRedoStack()
        if (currentNode := self.currentNode) is not None:
            currentNode.UndoEnabledOff()
        slicer.mrmlScene.SetUndoOff()

    def onUndoButtonClicked(self) -> None:
        self.undoRedoProcess(slicer.mrmlScene.Undo)

    def onRedoButtonClicked(self) -> None:
        self.undoRedoProcess(slicer.mrmlScene.Redo)

    def undoRedoProcess(self, undoOrRedoFunction) -> None:
        invalidNode = self.referenceNode is None or self.currentNode is None
        message = f"The current tool changes to the image were not applied and will be lost. Are you sure you want to {undoOrRedoFunction.__name__.lower()}?"
        if not invalidNode and self.applyButton.isEnabled():
            if slicer.util.confirmYesNoDisplay(message):
                slicer.util.updateVolumeFromArray(self.currentNode, self.imageArray)
            else:
                return
        undoOrRedoFunction()
        self.imageArray = slicer.util.arrayFromVolume(self.currentNode).copy()
        self.resetToolWidgets()
        self.configureButtonsState()

    def configureButtonsState(self) -> None:
        numberOfUndoLevels = slicer.mrmlScene.GetNumberOfUndoLevels()
        numberOfRedoLevels = slicer.mrmlScene.GetNumberOfRedoLevels()
        self.undoButton.enabled = numberOfUndoLevels
        self.redoButton.enabled = numberOfRedoLevels
        if numberOfUndoLevels > 0 or numberOfRedoLevels > 0:
            self.saveResetButtons.setEnabled(True)
        else:
            self.saveResetButtons.setEnabled(False)
        self.applyButton.enabled = False
        self.cancelButton.enabled = False

    def persistNode(self) -> None:
        currentNode = self.currentNode
        helpers.makeTemporaryNodePermanent(currentNode, save=True, show=True)
        self.imageArray = slicer.util.arrayFromVolume(currentNode).copy()

    def onSaveButtonClicked(self) -> None:
        self.__saveAllChanges()

    def __saveAllChanges(self) -> None:
        self.persistNode()
        self.endUndoRedoState(False)
        self.resetToolWidgets()
        self.startUndoRedoState()
        self.configureButtonsState()
        self.clearWorkingNode(removeNode=False)
        self.imageComboBox.setCurrentNode(None)

    def onResetButtonClicked(self) -> None:
        self.__resetAllChanges()

    def __resetAllChanges(self) -> None:
        self.endUndoRedoState(True)
        self.startUndoRedoState()
        self.resetToolWidgets()
        self.configureButtonsState()
        self.resetWorkingNode()

    def reset(self) -> None:
        self.endUndoRedoState(True)

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

    def exit(self) -> None:
        if self.applyButton.isEnabled():
            message = (
                "The current changes in the image were not applied and will be lost. Do you want to save the changes?"
            )
            if slicer.util.confirmYesNoDisplay(message):
                self.__commitChanges()
                self.__saveAllChanges()

        invalidNode = self.referenceNode is None or self.currentNode is None
        if not invalidNode and (
            slicer.mrmlScene.GetNumberOfUndoLevels() > 0 or slicer.mrmlScene.GetNumberOfRedoLevels() > 0
        ):
            messageBox = qt.QMessageBox()
            saveImageAnswer = messageBox.question(
                slicer.modules.AppContextInstance.mainWindow,
                "GeoSlicer confirmation",
                "Save the changes to the image before exiting?",
                qt.QMessageBox.Yes | qt.QMessageBox.No,  # | qt.QMessageBox.Cancel,
            )
            # if saveImageAnswer == qt.QMessageBox.Cancel:
            #     pass  # @TODO find a way to stop a module from exiting
            # else:
            if saveImageAnswer == qt.QMessageBox.Yes:
                self.endUndoRedoState(False)
                self.__saveAllChanges()
            else:
                self.endUndoRedoState(True)

        self.clearWorkingNode()
        self.reset()

    def configureInterfaceForThinSectionRegistrationModule(self):
        self.formLayout.setContentsMargins(0, 0, 0, 0)
        self.showImageButton.setVisible(False)  # To not mess with the comparison view
        self.saveResetButtons.applyBtn.setVisible(False)  # It's only to help placing the landmarks

    def clearWorkingNode(self, removeNode: bool = True) -> None:
        workingNode = self.currentNode

        if self.__currentNodeObserver is not None:
            del self.__currentNodeObserver
            self.__currentNodeObserver = None

        if self.__referenceNodeObserver is not None:
            del self.__referenceNodeObserver
            self.__referenceNodeObserver = None

        if removeNode and workingNode is not None:
            slicer.mrmlScene.RemoveNode(workingNode)

        self.imageArray = None

    def resetWorkingNode(self) -> None:
        workingNode = self.currentNode
        referenceNode = self.referenceNode
        if workingNode is None or referenceNode is None:
            return

        referenceArray = slicer.util.arrayFromVolume(referenceNode).copy()
        slicer.util.updateVolumeFromArray(workingNode, referenceArray)
        self.imageArray = slicer.util.arrayFromVolume(workingNode).copy()


class ImageToolsInfo(RuntimeError):
    pass
