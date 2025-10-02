import ctk
import os
import qt
import slicer
import numpy as np
import vtk
import slicer.util
import json

from ltrace.slicer import ui
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.helpers import (
    createTemporaryVolumeNode,
    getCurrentEnvironment,
    moveNodeTo,
    clone_volume,
    tryGetNode,
    NodeEnvironment,
    removeTemporaryNodes,
)
from ltrace.constants import ImageLogInpaintConst
from CustomizedWidget.RenameDialog import RenameDialog
from pathlib import Path
from typing import Dict
from slicer.parameterNodeWrapper import parameterNodeWrapper
from CoreInpaint import PatchMatch

try:
    from Test.ImageLogInpaintTest import ImageLogInpaintTest
except ImportError:
    ImageLogInpaintTest = None  # tests not deployed to final version or closed source


class ImageLogInpaint(LTracePlugin):
    SETTING_KEY = "ImageLogInpaint"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Image Log Inpaint"
        self.parent.categories = ["Tools", "ImageLog", "Multiscale"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.setHelpUrl("ImageLog/Inpainting/ImageLogInpaint/ImageLogInpaint.html", NodeEnvironment.IMAGE_LOG)
        self.setHelpUrl("Multiscale/ImageLogPreProcessing/Inpaint/ImageLogInpaint.html", NodeEnvironment.MULTISCALE)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


@parameterNodeWrapper
class ImageLogInpaintParameterNode:
    """
    Class to store/retrieve parametes when the project is saved/loaded.
    """

    segmentations: Dict[slicer.vtkMRMLScalarVolumeNode, slicer.vtkMRMLSegmentationNode]
    lastSourceNode: slicer.vtkMRMLScalarVolumeNode


class ImageLogInpaintWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = ImageLogInpaintLogic()
        self.parameterNode = None
        self.inpaintArea = 200

        self._historySize = 10
        self._volumeHistory = []
        self._segmentationHistory = []
        self._historyPointer = 0

        # Temp segmentation is used receive the segment drawn by the user.
        # After each interation its content is cleared. This allow us to get each segment separately for inpainting.
        self._tempSegmentation = None
        self._tempLabelMap = None

        self._observerTags = {}

    def setup(self):
        LTracePluginWidget.setup(self)

        self.customizedSegmentEditorWidget = slicer.util.getNewModuleWidget("CustomizedSegmentEditor")
        self.customizedSegmentEditorWidget.selectParameterNodeByTag(ImageLogInpaint.SETTING_KEY)

        self.segmentEditorWidget = self.customizedSegmentEditorWidget.editor
        self.segmentEditorWidget.setEffectNameOrder(["Scissors"])
        self.segmentEditorWidget.unorderedEffectsVisible = False
        self.segmentEditorWidget.setAutoShowSourceVolumeNode(False)

        self.segmentEditorWidget.findChild(ctk.ctkMenuButton, "Show3DButton").setVisible(False)
        self.segmentEditorWidget.findChild(qt.QLabel, "SourceVolumeNodeLabel").setText("Input image: ")
        self.segmentEditorWidget.findChild(qt.QLabel, "SegmentationNodeLabel").setVisible(False)
        self.segmentEditorWidget.findChild(qt.QPushButton, "AddSegmentButton").setVisible(False)
        self.segmentEditorWidget.findChild(qt.QPushButton, "RemoveSegmentButton").setVisible(False)

        undoButtonWidget = self.segmentEditorWidget.findChild(qt.QToolButton, "UndoButton")
        redoButtonWidget = self.segmentEditorWidget.findChild(qt.QToolButton, "RedoButton")

        undoButtonWidget.visible = False
        redoButtonWidget.visible = False

        self.undoButton = qt.QToolButton()
        self.undoButton.objectName = "undoButtonInpaint"
        self.undoButton.setText("Undo")
        self.undoButton.enabled = False
        self.undoButton.setToolTip(undoButtonWidget.toolTip)
        self.undoButton.setToolButtonStyle(undoButtonWidget.toolButtonStyle)
        self.undoButton.setIcon(undoButtonWidget.icon)
        self.undoButton.setIconSize(undoButtonWidget.iconSize)
        self.undoButton.clicked.connect(self.onUndoClicked)

        self.redoButton = qt.QToolButton()
        self.redoButton.objectName = "redoButtonInpaint"
        self.redoButton.setText("Redo")
        self.redoButton.enabled = False
        self.redoButton.setToolTip(redoButtonWidget.toolTip)
        self.redoButton.setToolButtonStyle(redoButtonWidget.toolButtonStyle)
        self.redoButton.setIcon(redoButtonWidget.icon)
        self.redoButton.setIconSize(redoButtonWidget.iconSize)
        self.redoButton.clicked.connect(self.onRedoClicked)

        self.segmentEditorWidget.findChild(qt.QFrame, "UndoRedoGroupBox").layout().addWidget(self.undoButton, 0, 2)
        self.segmentEditorWidget.findChild(qt.QFrame, "UndoRedoGroupBox").layout().addWidget(self.redoButton, 0, 3)

        self.sourceVolumeComboBox = self.segmentEditorWidget.findChild(
            slicer.qMRMLNodeComboBox, "SourceVolumeNodeComboBox"
        )
        self.sourceVolumeComboBox.objectName = "sourceVolumeNodeComboBox"
        self.sourceVolumeComboBox.showChildNodeTypes = False
        self.sourceVolumeComboBox.noneDisplay = "Select the image log for inpaint"
        self.sourceVolumeComboBox.currentNodeChanged.connect(self.onSourceVolumeChanged)

        self.segmentationComboBox = self.segmentEditorWidget.findChild(
            slicer.qMRMLNodeComboBox, "SegmentationNodeComboBox"
        )
        self.segmentationComboBox.objectName = "segmentationNodeComboBox"
        self.segmentationComboBox.setVisible(False)

        self.cloneButton = ui.ButtonWidget(
            text="Clone Volume",
            tooltip="Clone the input image",
            object_name="cloneVolumeButton",
            enabled=False,
            onClick=self.onCloneClicked,
        )

        self.renameButton = ui.ButtonWidget(
            text="Rename Volume",
            tooltip="Rename the input image",
            object_name="renameVolumeButton",
            enabled=False,
            onClick=self.onRenameClicked,
        )

        self.renameDialog = RenameDialog(self.layout.parentWidget())
        self.renameDialog.objectName = "renameVolumeDialog"

        frame = qt.QFrame()

        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)

        buttonLayout = qt.QHBoxLayout()
        buttonLayout.setContentsMargins(6, 0, 6, 0)
        buttonLayout.addStretch(1)
        buttonLayout.addWidget(self.cloneButton)
        buttonLayout.addWidget(self.renameButton)

        formLayout.addRow(buttonLayout)
        formLayout.addWidget(self.segmentEditorWidget)

        self.layout.addWidget(frame)
        self.layout.addStretch()

        self.saveConfigObserver = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.StartSaveEvent, self.onSaveSceneStartConfig
        )
        self.importConfigObserver = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndImportEvent, self.onImportSceneEndConfig
        )

        self.configEffect()
        self.initParameterNode()

    def onSaveSceneStartConfig(self, caller, event):
        # GeoSlicer has a problem saving empty segmentations.
        self.removeEmptySegmentations()

    def onImportSceneEndConfig(self, caller, event):
        self.initParameterNode()

    def onSaveSceneStart(self, caller, event):
        # Clear the image log view config to not save the current state of the view.
        # Also prevents errors related to the temporary segmentation node.
        if self.logic.imageLogDataLogic is not None:
            if self.logic.imageLogDataLogic.configurationsNode is not None:
                self.logic.imageLogDataLogic.configurationsNode.SetParameter("ImagLogViews", json.dumps([]))

            self.logic.imageLogDataLogic.cleanUp()

        self.clearViews()
        self.resetVars()
        self.removeTempVariables()  # GeoSlicer can't handle some temporary segmentations when saving a project.

        self.parameterNode.lastSourceNode = self.sourceVolumeComboBox.currentNode()

    def onSaveSceneEnd(self, caller, event):
        self.initTempVariables()
        self.sourceVolumeComboBox.setCurrentNode(self.parameterNode.lastSourceNode)

    def onImportSceneStart(self, caller, event):
        self.resetVars()
        self.removeTempVariables()

    def onImportSceneEnd(self, caller, event):
        self.initTempVariables()
        self.sourceVolumeComboBox.setCurrentNode(None)  # Set to None first to trigger the node changed signal
        self.sourceVolumeComboBox.setCurrentNode(self.parameterNode.lastSourceNode)

    def onSourceVolumeChanged(self, node):
        self.resetVars()

        if node is not None:
            if node not in self.parameterNode.segmentations or self.parameterNode.segmentations[node] is None:
                self.parameterNode.segmentations[node] = self.createSegmentation(node)

            segmentation = self.parameterNode.segmentations[node]

            # Add the initial states of sagmentation and volume to history
            initialSegment = self.arrayFromSegmentation(segmentation, node)
            currentImage = slicer.util.arrayFromVolume(node)

            self._segmentationHistory.append(initialSegment)
            self._volumeHistory.append(np.copy(currentImage))

            self._tempSegmentation.SetReferenceImageGeometryParameterFromVolumeNode(node)

            self.showViews(segmentation, node)

            self.cloneButton.enabled = True
            self.renameButton.enabled = True
        else:
            self.cloneButton.enabled = False
            self.renameButton.enabled = False
            self.clearViews()

    def onCloneClicked(self):
        sourceNode = self.sourceVolumeComboBox.currentNode()

        if sourceNode is not None:
            node = clone_volume(sourceNode, sourceNode.GetName() + "_Inpaint", as_temporary=False)
            node.CopyReferences(sourceNode)

            self.moveNodeTo(node, sourceNode)
            self.sourceVolumeComboBox.setCurrentNode(node)

    def onRenameClicked(self):
        sourceNode = self.sourceVolumeComboBox.currentNode()

        if sourceNode is not None:
            self.renameDialog.setOutputName(sourceNode.GetName())
            result = self.renameDialog.exec_()

            if bool(result) and sourceNode.GetName() != self.renameDialog.getOutputName():
                name = slicer.mrmlScene.GenerateUniqueName(self.renameDialog.getOutputName())
                sourceNode.SetName(name)

                self.clearViews()

                segmentation = self.parameterNode.segmentations[sourceNode]
                if segmentation is not None:
                    segmentation.SetName(name + "_Segmentation")
                    self.showViews(segmentation, sourceNode)

    def onUndoClicked(self):
        self._historyPointer = max(self._historyPointer - 1, 0)
        self.redoOrUndo()

    def onRedoClicked(self):
        self._historyPointer = min(self._historyPointer + 1, len(self._volumeHistory) - 1)
        self.redoOrUndo()

    def redoOrUndo(self):
        sourceNode = self.sourceVolumeComboBox.currentNode()
        segmentation = self.parameterNode.segmentations[sourceNode]

        slicer.util.updateVolumeFromArray(sourceNode, self._volumeHistory[self._historyPointer])
        self.updateSegmentationFromArray(segmentation, self._segmentationHistory[self._historyPointer])

        self.updateUndoRedoState()

    def updateUndoRedoState(self):
        if self._historyPointer == 0:
            self.undoButton.enabled = False
        else:
            self.undoButton.enabled = True

        if self._historyPointer == len(self._segmentationHistory) - 1 or len(self._segmentationHistory) == 0:
            self.redoButton.enabled = False
        else:
            self.redoButton.enabled = True

    def initParameterNode(self):
        self.parameterNode = self.logic.getParameterNode()

    def applyInpaint(self, node, event):
        sourceNode = self.sourceVolumeComboBox.currentNode()

        currentSegment = self.arrayFromSegmentation(self._tempSegmentation, sourceNode)
        currentImage = slicer.util.arrayFromVolume(sourceNode)

        # Check for valid segmentation.
        segmentPos = np.where(currentSegment == 1)
        if len(segmentPos[0]) == 0 or len(segmentPos[-1]) == 0:
            return

        # Crop a small area of the original image for inpainting. This makes the patchmatch algorithm run faster.
        cropInitZ = max(segmentPos[0].min() - self.inpaintArea, 0)
        cropEndZ = min(segmentPos[0].max() + self.inpaintArea + 1, currentSegment.shape[0])
        cropInitX = max(segmentPos[-1].min() - self.inpaintArea, 0)
        cropEndX = min(segmentPos[-1].max() + self.inpaintArea + 1, currentSegment.shape[-1])

        # Run Inpainting
        try:
            patchmatch = PatchMatch(n_levels=3)
            processedImage = patchmatch(
                currentImage[cropInitZ:cropEndZ, ..., cropInitX:cropEndX],
                currentSegment[cropInitZ:cropEndZ, ..., cropInitX:cropEndX],
            )
        finally:
            segLogic = slicer.modules.segmentations.logic()
            if not segLogic.ClearSegment(self._tempSegmentation, ImageLogInpaintConst.SEGMENT_ID):
                raise ("Clear segment failed.")

        # Update the image
        currentImage[cropInitZ:cropEndZ, ..., cropInitX:cropEndX] = np.where(
            currentSegment[cropInitZ:cropEndZ, ..., cropInitX:cropEndX] == 1,
            processedImage,
            currentImage[cropInitZ:cropEndZ, ..., cropInitX:cropEndX],
        )
        slicer.util.updateVolumeFromArray(sourceNode, currentImage)

        # Update the segmentation linked to this node
        lastSegment = self._segmentationHistory[self._historyPointer].copy()
        lastSegment[segmentPos] = currentSegment[segmentPos]
        self.updateSegmentationFromArray(self.parameterNode.segmentations[sourceNode], lastSegment)

        # Update history
        self._historyPointer += 1
        self._segmentationHistory.insert(self._historyPointer, lastSegment)
        self._volumeHistory.insert(self._historyPointer, currentImage)

        self.checkTempArraysSize()
        self.updateUndoRedoState()

    def checkTempArraysSize(self):
        if self._historyPointer == self._historySize:
            self._segmentationHistory = self._segmentationHistory[1:]
            self._volumeHistory = self._volumeHistory[1:]
            self._historyPointer = self._historySize - 1

        if self._historyPointer < len(self._segmentationHistory) - 1:
            self._segmentationHistory = self._segmentationHistory[: self._historyPointer + 1]
            self._volumeHistory = self._volumeHistory[: self._historyPointer + 1]

    def createSegmentation(self, node):
        name = slicer.mrmlScene.GenerateUniqueName(node.GetName() + "_Segmentation")

        segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", name)
        segmentation.CreateDefaultDisplayNodes()
        segmentation.SetAttribute("ImageLogSegmentation", "True")
        segmentation.GetSegmentation().AddEmptySegment(ImageLogInpaintConst.SEGMENT_ID, ImageLogInpaintConst.SEGMENT_ID)
        segmentation.SetReferenceImageGeometryParameterFromVolumeNode(node)

        environment = getCurrentEnvironment()

        if environment is not None:
            value = environment if not hasattr(environment, "value") else environment.value
            segmentation.SetAttribute(NodeEnvironment.name(), value)

        self.moveNodeTo(segmentation, node)

        return segmentation

    def getSegmentIds(self, segmentationNode):
        segmentIds = vtk.vtkStringArray()
        segmentIds.InsertNextValue(ImageLogInpaintConst.SEGMENT_ID)
        if self._tempLabelMap is not None:
            self._tempLabelMap.CopyContent(segmentationNode)

        return segmentIds

    def updateSegmentationFromArray(self, segmentationNode, array):
        if segmentationNode is None or array is None:
            raise RuntimeError("Invalid segmentation node or array")

        segmentIds = self.getSegmentIds(segmentationNode)
        slicer.util.updateVolumeFromArray(self._tempLabelMap, array)

        segLogic = slicer.modules.segmentations.logic()
        if not segLogic.ImportLabelmapToSegmentationNode(self._tempLabelMap, segmentationNode, segmentIds):
            raise RuntimeError("Importing of segment failed.")

    def arrayFromSegmentation(self, segmentationNode, sourceNode):
        if segmentationNode is None or sourceNode is None:
            raise RuntimeError("Invalid segmentation node or reference node")

        segmentIds = self.getSegmentIds(segmentationNode)

        segLogic = slicer.modules.segmentations.logic()
        if not segLogic.ExportSegmentsToLabelmapNode(segmentationNode, segmentIds, self._tempLabelMap, sourceNode):
            raise RuntimeError("Export of segment failed.")

        return slicer.util.arrayFromVolume(self._tempLabelMap)

    def moveNodeTo(self, node, destinationNode):
        nodeId = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemByDataNode(destinationNode)
        folder = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemParent(nodeId)

        moveNodeTo(folder, node)

    def removeEmptySegmentations(self):
        newSegmentations = {}

        for node, segmentation in self.parameterNode.segmentations.items():
            if segmentation is not None:
                segmentMap = slicer.util.arrayFromSegmentBinaryLabelmap(segmentation, ImageLogInpaintConst.SEGMENT_ID)

                if segmentMap.max() == 0:
                    proportionNode = tryGetNode(segmentation.GetName() + "_Proportions")

                    if proportionNode is not None:
                        slicer.mrmlScene.RemoveNode(proportionNode)

                    segmentation.GetSegmentation().RemoveAllSegments()
                    slicer.mrmlScene.RemoveNode(segmentation)
                elif node is not None:
                    newSegmentations[node] = segmentation

        self.parameterNode.segmentations = newSegmentations

    def configEffect(self):
        scissorsEffect = self.segmentEditorWidget.effectByName("Scissors")
        scissorsEffect.setOperation(2)
        scissorsEffect.setShape(0)
        scissorsEffect.setSliceCutMode(0)
        scissorsEffect.optionsFrame().setEnabled(False)

    def showViews(self, segmentation, node):
        if self.logic.imageLogDataLogic:
            self.logic.imageLogDataLogic.addInpaintView(self._tempSegmentation, segmentation, node)

    def clearViews(self):
        if self.logic.imageLogDataLogic:
            for id in range(len(self.logic.imageLogDataLogic.imageLogViewList) - 1, -1, -1):
                self.logic.imageLogDataLogic.removeView(id)

    def resetVars(self):
        self._volumeHistory = []
        self._segmentationHistory = []
        self._historyPointer = 0
        self.updateUndoRedoState()

    def initObservers(self):
        if len(self._observerTags) != 0:
            self.removeObservers()

        self._observerTags[slicer.mrmlScene] = [
            slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartSaveEvent, self.onSaveSceneStart),
            slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndSaveEvent, self.onSaveSceneEnd),
            slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartImportEvent, self.onImportSceneStart),
            slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndImportEvent, self.onImportSceneEnd),
        ]

    def removeObservers(self):
        for handler in self._observerTags:
            if type(self._observerTags[handler]) == list:
                for tag in self._observerTags[handler]:
                    handler.RemoveObserver(tag)
            else:
                handler.RemoveObserver(self._observerTags[handler])

        self._observerTags = {}

    def initTempVariables(self):
        self._tempSegmentation = createTemporaryVolumeNode(
            slicer.vtkMRMLSegmentationNode, ImageLogInpaintConst.TEMP_SEGMENTATION_NAME, hidden=False, uniqueName=False
        )
        self._tempLabelMap = createTemporaryVolumeNode(
            slicer.vtkMRMLLabelMapVolumeNode, ImageLogInpaintConst.TEMP_LABEL_MAP_NAME, uniqueName=False
        )

        self._tempSegmentation.SetAttribute("ImageLogSegmentation", "True")
        self._tempSegmentation.GetSegmentation().AddEmptySegment(
            ImageLogInpaintConst.SEGMENT_ID, ImageLogInpaintConst.SEGMENT_ID
        )

        self.segmentationComboBox.setCurrentNode(self._tempSegmentation)
        self.segmentEditorWidget.setCurrentSegmentID(ImageLogInpaintConst.SEGMENT_ID)

        self._observerTags[self._tempSegmentation] = self._tempSegmentation.AddObserver(
            slicer.vtkSegmentation.SourceRepresentationModified, self.applyInpaint
        )

    def removeTempVariables(self):
        if self._tempSegmentation in self._observerTags:
            self._tempSegmentation.RemoveObserver(self._observerTags[self._tempSegmentation])
            del self._observerTags[self._tempSegmentation]

        if self._tempSegmentation is not None:
            tempProportionNode = tryGetNode(self._tempSegmentation.GetName() + "_Proportions")
            if tempProportionNode is not None:
                slicer.mrmlScene.RemoveNode(tempProportionNode)

            self.segmentationComboBox.setCurrentNode(None)
            self._tempSegmentation.GetSegmentation().RemoveAllSegments()

            slicer.mrmlScene.RemoveNode(self._tempSegmentation)

        if self._tempLabelMap is not None and self._tempLabelMap.GetDisplayNode():
            slicer.mrmlScene.RemoveNode(self._tempLabelMap)

        removeTemporaryNodes()
        self._tempLabelMap = None
        self._tempSegmentation = None

    def enter(self):
        super().enter()

        self.configEffect()
        self.initObservers()
        self.initTempVariables()
        self.onSourceVolumeChanged(self.sourceVolumeComboBox.currentNode())  # Recreate views

    def exit(self):
        self.removeObservers()
        self.removeTempVariables()
        self.resetVars()
        self.clearViews()

    def cleanup(self):
        super().cleanup()
        self.customizedSegmentEditorWidget.cleanup()
        slicer.mrmlScene.RemoveObserver(self.saveConfigObserver)
        slicer.mrmlScene.RemoveObserver(self.importConfigObserver)


class ImageLogInpaintLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.imageLogDataLogic = None
        self.isSingletonParameterNode = True
        self.moduleName = ImageLogInpaint.SETTING_KEY
        self.setImageLogDataLogic()

    def getParameterNode(self):
        return ImageLogInpaintParameterNode(super().getParameterNode())

    def setImageLogDataLogic(self):
        """
        Allows Image Log Inpaint to perform changes in the Image Log Data views.
        """
        self.imageLogDataLogic = slicer.util.getModuleLogic("ImageLogData")
