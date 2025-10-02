import math
import os
from collections import namedtuple
from pathlib import Path

import ctk
import numpy as np
import qt
import slicer
import vtk

from ltrace.slicer.helpers import triggerNodeModified
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, getResourcePath
from ltrace.units import global_unit_registry as ureg, SLICER_LENGTH_UNIT


class UnwrapRegistration(LTracePlugin):
    SETTING_KEY = "UnwrapRegistration"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Unwrap Registration"
        self.parent.categories = ["Tools", "ImageLog"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = UnwrapRegistration.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class UnwrapRegistrationWidget(LTracePluginWidget):

    ApplyParameters = namedtuple(
        "ApplyParameters",
        [
            "inputImage",
            "depth",
            "orientation",
        ],
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.registering = False
        self.transformNode = None
        self.transformArray = None
        self.imageNode = None
        self.imageArray = None
        self.observers = []
        self.inputCalled = False
        self.cumulativeDepthChange = 0
        self.cumulativeOrientationChange = 0

    def setup(self):
        LTracePluginWidget.setup(self)

        self.logic = UnwrapRegistrationLogic()

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

        self.imageComboBox = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode"], onChange=self.onInputImageChanged
        )
        self.imageComboBox.addNodeAttributeIncludeFilter("Volume type", "Well unwrap")
        self.imageComboBox.setToolTip("Select the input unwrap image.")
        inputFormLayout.addRow("Input unwrap image:", self.imageComboBox)
        inputFormLayout.addRow(" ", None)

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.depthSliderWidget = slicer.qMRMLSliderWidget()
        self.depthSliderWidget.maximum = 3
        self.depthSliderWidget.minimum = -3
        self.depthSliderWidget.decimals = 2
        self.depthSliderWidget.singleStep = 0.01
        self.depthSliderWidget.setEnabled(False)
        self.depthSliderWidget.setToolTip("Adjust the depth of the input unwrap image.")
        self.depthSliderWidget.valueChanged.connect(self.onDepthChanged)
        parametersFormLayout.addRow("Depth (m):", self.depthSliderWidget)

        self.orientationSliderWidget = slicer.qMRMLSliderWidget()
        self.orientationSliderWidget.maximum = 360
        self.orientationSliderWidget.minimum = 0
        self.orientationSliderWidget.decimals = 1
        self.orientationSliderWidget.singleStep = 0.1
        self.orientationSliderWidget.setEnabled(False)
        self.orientationSliderWidget.setToolTip("Adjust the orientation of the input unwrap image.")
        self.orientationSliderWidget.valueChanged.connect(self.onOrientationChanged)
        parametersFormLayout.addRow("Orientation (°):", self.orientationSliderWidget)
        parametersFormLayout.addRow(" ", None)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Apply.png"))
        self.applyButton.setToolTip("Apply the current changes. These changes can be undone, unless you click Save.")
        self.applyButton.enabled = False
        self.applyButton.clicked.connect(self.onApplyButtonClicked)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Cancel.png"))
        self.cancelButton.setToolTip("Cancel the current changes.")
        self.cancelButton.enabled = False
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        self.undoButton = qt.QPushButton("Undo")
        self.undoButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Undo.png"))
        self.undoButton.setToolTip(
            "Undo the applied changes. The earliest undo is where the volume was loaded or saved."
        )
        self.undoButton.enabled = False
        self.undoButton.clicked.connect(self.onUndoButtonClicked)

        self.redoButton = qt.QPushButton("Redo")
        self.redoButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Redo.png"))
        self.redoButton.setToolTip("Redo the applied changes.")
        self.redoButton.enabled = False
        self.redoButton.clicked.connect(self.onRedoButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.applyButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        buttonsHBoxLayout.addWidget(self.undoButton)
        buttonsHBoxLayout.addWidget(self.redoButton)
        formLayout.addRow(buttonsHBoxLayout)

        self.saveButton = qt.QPushButton("Save")
        self.saveButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Save.png"))
        self.saveButton.setToolTip("Save the applied changes. This action cannot be undone.")
        self.saveButton.enabled = False
        self.saveButton.clicked.connect(self.onSaveButtonClicked)

        self.resetButton = qt.QPushButton("Reset")
        self.resetButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Reset.png"))
        self.resetButton.setToolTip("Reset the applied changes to the last saved state.")
        self.resetButton.enabled = False
        self.resetButton.clicked.connect(self.onResetButtonClicked)

        saveResetButtonsHBoxLayout = qt.QHBoxLayout()
        saveResetButtonsHBoxLayout.addWidget(self.saveButton)
        saveResetButtonsHBoxLayout.addWidget(self.resetButton)
        formLayout.addRow(saveResetButtonsHBoxLayout)

        self.layout.addStretch(1)

    def onDepthChanged(self):
        transformMatrix = vtk.vtkMatrix4x4()
        transformMatrix.SetElement(2, 3, self.transformArray[2, 3] + self.depthSliderWidget.value * 1000)
        self.transformNode.SetMatrixTransformToParent(transformMatrix)

    def onOrientationChanged(self):
        inputImage = self.imageComboBox.currentNode()
        rollValue = int(np.round((self.orientationSliderWidget.value / 360) * self.imageArray.shape[2]))
        newInputImageArray = np.roll(self.imageArray, rollValue, axis=2)
        slicer.util.updateVolumeFromArray(inputImage, newInputImageArray)

    def onInputImageChanged(self, itemId):
        self.stopRegistration()

        self.depthSliderWidget.setEnabled(False)
        self.orientationSliderWidget.setEnabled(False)

        if self.imageComboBox.currentNode():
            self.startRegistration()
            self.depthSliderWidget.setEnabled(True)
            self.orientationSliderWidget.setEnabled(True)

        self.configureInterfaceState()

    def onApplyButtonClicked(self):
        depthChange = self.depthSliderWidget.value
        if depthChange != 0:
            newTransformMatrix = slicer.util.arrayFromTransformMatrix(self.transformNode)
            slicer.util.updateTransformMatrixFromArray(self.transformNode, self.transformArray)
            slicer.mrmlScene.SaveStateForUndo(self.transformNode)
            slicer.util.updateTransformMatrixFromArray(self.transformNode, newTransformMatrix)
            self.transformArray = newTransformMatrix
            self.cumulativeDepthChange += depthChange

        orientationChange = self.orientationSliderWidget.value
        if orientationChange != 0:
            inputImage = self.imageComboBox.currentNode()
            newInputImageArray = slicer.util.arrayFromVolume(inputImage)
            slicer.util.updateVolumeFromArray(inputImage, self.imageArray)
            slicer.mrmlScene.SaveStateForUndo(inputImage)
            slicer.util.updateVolumeFromArray(inputImage, newInputImageArray)
            self.imageArray = newInputImageArray
            self.cumulativeOrientationChange += orientationChange

        self.configureInterfaceState()

    def onUndoButtonClicked(self):
        slicer.mrmlScene.Undo()
        self.transformArray = slicer.util.arrayFromTransformMatrix(self.transformNode)
        self.imageArray = slicer.util.arrayFromVolume(self.imageNode)
        self.configureInterfaceState()
        self.resetSliderWidgets()

    def onRedoButtonClicked(self):
        slicer.mrmlScene.Redo()
        self.transformArray = slicer.util.arrayFromTransformMatrix(self.transformNode)
        self.imageArray = slicer.util.arrayFromVolume(self.imageNode)
        self.configureInterfaceState()
        self.resetSliderWidgets()

    def onSaveButtonClicked(self):
        self.logic.save(
            self.imageNode, self.cumulativeDepthChange * ureg.meter, self.cumulativeOrientationChange * ureg.degree
        )
        slicer.mrmlScene.ClearUndoStack()
        slicer.mrmlScene.ClearRedoStack()
        self.startRegistration()
        self.configureInterfaceState()
        slicer.util.infoDisplay("Save completed. All Multicore volumes (cores and unwraps) were updated.")

    def onResetButtonClicked(self):
        for i in range(slicer.mrmlScene.GetNumberOfUndoLevels()):
            slicer.mrmlScene.Undo()
        slicer.mrmlScene.ClearUndoStack()
        slicer.mrmlScene.ClearRedoStack()

        self.transformArray = slicer.util.arrayFromTransformMatrix(self.transformNode)
        self.imageArray = slicer.util.arrayFromVolume(self.imageNode)
        self.configureInterfaceState()

    def onCancelButtonClicked(self):
        slicer.util.updateTransformMatrixFromArray(self.transformNode, self.transformArray)
        slicer.util.updateVolumeFromArray(self.imageNode, self.imageArray)
        self.configureInterfaceState()

    def startRegistration(self):
        if self.registering:
            self.stopRegistration()

        slicer.mrmlScene.SetUndoOn()

        # Transform
        self.transformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode")
        self.transformNode.HideFromEditorsOn()
        triggerNodeModified(self.transformNode)
        self.transformArray = slicer.util.arrayFromTransformMatrix(self.transformNode)
        transformObserverID = self.transformNode.AddObserver(
            slicer.vtkMRMLTransformNode.TransformModifiedEvent, self.onNodeModified
        )
        self.observers.append([transformObserverID, self.transformNode])
        self.transformNode.UndoEnabledOn()

        # Image
        self.imageNode = self.imageComboBox.currentNode()
        self.imageNode.SetAndObserveTransformNodeID(self.transformNode.GetID())
        self.imageArray = slicer.util.arrayFromVolume(self.imageNode)
        imageObserverID = self.imageNode.AddObserver(
            slicer.vtkMRMLScalarVolumeNode.ImageDataModifiedEvent, self.onNodeModified
        )
        self.observers.append([imageObserverID, self.imageNode])
        self.imageNode.UndoEnabledOn()

        self.registering = True

    def stopRegistration(self):
        if not self.registering:
            return

        for i in range(slicer.mrmlScene.GetNumberOfUndoLevels()):
            slicer.mrmlScene.Undo()

        slicer.mrmlScene.RemoveNode(self.transformNode)

        for observerID, node in self.observers:
            node.RemoveObserver(observerID)

        slicer.mrmlScene.ClearUndoStack()
        slicer.mrmlScene.ClearRedoStack()
        slicer.mrmlScene.SetUndoOff()

        self.registering = False
        self.transformNode = None
        self.transformArray = None
        self.imageNode = None
        self.imageArray = None
        self.observers = []

    def onNodeModified(self, *args):
        self.applyButton.enabled = True
        self.cancelButton.enabled = True
        self.saveButton.enabled = False
        self.resetButton.enabled = False
        self.undoButton.enabled = False
        self.redoButton.enabled = False

    def configureInterfaceState(self):
        numberOfUndoLevels = slicer.mrmlScene.GetNumberOfUndoLevels()
        numberOfRedoLevels = slicer.mrmlScene.GetNumberOfRedoLevels()
        self.undoButton.enabled = numberOfUndoLevels
        self.redoButton.enabled = numberOfRedoLevels
        self.saveButton.enabled = numberOfUndoLevels or numberOfRedoLevels
        self.resetButton.enabled = numberOfUndoLevels or numberOfRedoLevels
        self.applyButton.enabled = False
        self.cancelButton.enabled = False

        self.resetSliderWidgets()
        self.depthSliderWidget.setEnabled(self.registering)
        self.orientationSliderWidget.setEnabled(self.registering)

    def resetSliderWidgets(self):
        self.depthSliderWidget.blockSignals(True)
        self.depthSliderWidget.value = 0
        self.depthSliderWidget.blockSignals(False)
        self.orientationSliderWidget.blockSignals(True)
        self.orientationSliderWidget.value = 0
        self.orientationSliderWidget.blockSignals(False)


class UnwrapRegistrationLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def save(self, imageNode, depthIncrement, orientationIncrement):
        from Multicore import MulticoreLogic

        imageNode.HardenTransform()

        transformArray = self.getRegistrationTransformArray(depthIncrement, orientationIncrement)

        multicoreLogic = MulticoreLogic()
        coreVolumes = multicoreLogic.getCoreVolumes()
        for coreVolume in coreVolumes:
            self.applyRegistrationTransform(coreVolume, transformArray)
            multicoreLogic.setDepth(coreVolume, multicoreLogic.getDepth(coreVolume) + depthIncrement)
            multicoreLogic.setOrientationAngle(coreVolume)

            # Adjusting the depth for the original volume it exists
            originalVolume = multicoreLogic.getNodesByBaseNameAndNodeType(
                coreVolume.GetAttribute(multicoreLogic.BASE_NAME), multicoreLogic.NODE_TYPE_ORIGINAL_VOLUME
            )
            if len(originalVolume) == 1:
                multicoreLogic.configureVolumeDepth(originalVolume[0], multicoreLogic.getDepth(coreVolume))

            # Adjusting the depth of the ROI if it exists
            if depthIncrement != 0:
                try:
                    roi = slicer.util.getNode(coreVolume.GetName() + " ROI")
                    xyz = np.zeros(3)
                    roi.GetXYZ(xyz)
                    xyz[2] += depthIncrement.m_as(SLICER_LENGTH_UNIT)
                    roi.SetXYZ(xyz)
                except slicer.util.MRMLNodeNotFoundException:
                    pass

            unwrapVolume = multicoreLogic.getUnwrapVolume(coreVolume)
            if len(unwrapVolume) == 1:
                if depthIncrement != 0:
                    multicoreLogic.configureVolumeDepth(unwrapVolume[0], multicoreLogic.getDepth(coreVolume))
                    multicoreLogic.setDepth(unwrapVolume[0], multicoreLogic.getDepth(unwrapVolume[0]) + depthIncrement)
                if orientationIncrement != 0:
                    multicoreLogic.updateCoreUnwrapVolume(coreVolume)

    def getRegistrationTransformArray(self, depthChange, orientationChange):
        orientationChangeInRadians = orientationChange.m_as(ureg.radian)
        transformArray = np.array(
            [
                [math.cos(orientationChangeInRadians), -math.sin(orientationChangeInRadians), 0, 0],
                [math.sin(orientationChangeInRadians), math.cos(orientationChangeInRadians), 0, 0],
                [0, 0, 1, depthChange.m_as(SLICER_LENGTH_UNIT)],
                [0, 0, 0, 1],
            ]
        )
        return transformArray

    def applyRegistrationTransform(self, node, transformArray):
        vtkTransformationMatrix = vtk.vtkMatrix4x4()
        vtkTransformationMatrix.DeepCopy(list(transformArray.flat))
        transformNode = slicer.vtkMRMLTransformNode()
        slicer.mrmlScene.AddNode(transformNode)
        node.SetAndObserveTransformNodeID(transformNode.GetID())
        transformNode.SetMatrixTransformToParent(vtkTransformationMatrix)
        node.HardenTransform()
        slicer.mrmlScene.RemoveNode(transformNode)
