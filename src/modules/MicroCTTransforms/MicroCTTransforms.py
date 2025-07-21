import os
from pathlib import Path

import ctk
import numpy as np
import qt
import slicer
import vtk

from scipy.spatial.transform import Rotation
from ltrace.slicer_utils import *
from ltrace.slicer.helpers import BlockSignals
from ltrace.slicer_utils import getResourcePath
from ltrace.slicer import ui


def normalize_angle(angle):
    return (angle + 180) % 360 - 180


class MicroCTTransforms(LTracePlugin):
    SETTING_KEY = "MicroCTTransforms"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "MicroCT Manual Registration"
        self.parent.categories = ["MicroCT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = MicroCTTransforms.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MicroCTTransformsWidget(LTracePluginWidget):
    SLIDER_CLASS_NAMES = ["RotationSliders", "TranslationSliders"]
    SLICER_REPLACE_LABELS = {
        "LRLabel": "X",
        "PALabel": "Y",
        "ISLabel": "Z",
        "LRSlider": "X",
        "PASlider": "Y",
        "ISSlider": "Z",
    }

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.transformInProgress = False

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = MicroCTTransformsLogic()
        transformWidget = slicer.modules.transforms.createNewWidgetRepresentation()

        for clsname in self.SLIDER_CLASS_NAMES:
            classes = transformWidget.findChild(qt.QObject, clsname)

            for orig_lb, repl_lb in self.SLICER_REPLACE_LABELS.items():
                widget = classes.findChild(qt.QObject, orig_lb)
                if hasattr(widget, "text"):
                    widget.setText(repl_lb)
                widget.setToolTip(repl_lb + "- axis")

        minMaxWidget = transformWidget.findChild(qt.QObject, "MinMaxWidget")
        minValueSpinBox = minMaxWidget.findChild(qt.QObject, "MinValueSpinBox")
        minValueSpinBox.setValue(-10)
        minValueSpinBox.decimalsChanged.disconnect()
        maxValueSpinBox = minMaxWidget.findChild(qt.QObject, "MaxValueSpinBox")
        maxValueSpinBox.setValue(10)
        maxValueSpinBox.decimalsChanged.disconnect()

        self.rotationSliders = transformWidget.findChild(qt.QObject, "RotationSliders")
        self.transformNodeSelector = transformWidget.findChild(qt.QObject, "TransformNodeSelector")

        translationSliders = transformWidget.findChild(qt.QObject, "TranslationSliders")
        translationSliders.setDecimals(3)
        for i, sliderName in enumerate(["LRSlider", "PASlider", "ISSlider"]):
            slider = translationSliders.findChild(slicer.qMRMLLinearTransformSlider, sliderName)

            # Don't change increment based on range
            slider.setUnitAwareProperties(0)
            slider.singleStep = 0.001
            slider.decimalsChanged.disconnect()

            doubleSlider = slider.findChild(ctk.ctkDoubleSlider, "Slider")
            doubleSlider.sliderReleased.connect(self.onSliderReleased)

        rotationDials = qt.QFrame()
        gridLayout = qt.QGridLayout(rotationDials)
        self.rotationLabels = []
        for i, axis in enumerate("XYZ"):
            label = qt.QLabel(f"Rotate {axis}")
            label.setToolTip(f"Rotate around {axis}-axis")
            label.setAlignment(qt.Qt.AlignCenter)
            gridLayout.addWidget(label, 0, i)
            self.rotationLabels.append(label)

        rotationBox = self.rotationSliders.findChild(qt.QObject, "SlidersGroupBox")
        self.rotationSliders.layout().replaceWidget(rotationBox, rotationDials)
        rotationBox.hide()

        self.dials = []
        self.lastRotationValues = [0, 0, 0]
        self.sliderCumulativeDelta = [0, 0, 0]
        for i, sliderName in enumerate(["LRSlider", "PASlider", "ISSlider"]):
            slider = self.rotationSliders.findChild(slicer.qMRMLLinearTransformSlider, sliderName)
            dial = qt.QDial()
            dial.setWrapping(True)
            dial.valueChanged.connect(lambda value, dialIndex=i: self.updateRotation(dialIndex, value))
            dial.sliderReleased.connect(self.onSliderReleased)
            dial.setRange(-1800, 1800)
            dial.setOrientation(qt.Qt.Horizontal)
            dial.notchesVisible = True
            dial.setToolTip(f"Click and drag to rotate dial")
            gridLayout.addWidget(dial, 1, i)
            self.dials.append(dial)

            incrementLayout = qt.QHBoxLayout()
            incrementSpinBox = ctk.ctkDoubleSpinBox()
            incrementSpinBox.decimals = 4
            incrementSpinBox.singleStep = 0.1
            incrementSpinBox.value = 0.5
            incrementSpinBox.toolTip = f"Set the rotation increment for the arrow buttons"
            incrementSpinBox.minimum = 0.0001
            incrementSpinBox.maximum = 180
            incrementSpinBox.setSizePolicy(qt.QSizePolicy.Fixed, qt.QSizePolicy.Fixed)
            buttons = []
            for mul, label in zip([-1, +1], ["\u2039", "\u203A"]):
                button = qt.QPushButton(label)

                def increment(*args, dial=dial, incBox=incrementSpinBox, mul=mul):
                    inc = incBox.value
                    angle = normalize_angle(dial.value / 10 + inc * mul)
                    dial.setValue(round(angle * 10))
                    self.onSliderReleased()

                button.clicked.connect(increment)
                button.setSizePolicy(qt.QSizePolicy.Maximum, qt.QSizePolicy.Fixed)
                button.setContentsMargins(0, 0, 0, 0)
                button.setMaximumWidth(20)
                button.setToolTip(f"Rotate dial by the current increment")
                buttons.append(button)

            incrementLayout.addWidget(buttons[0])
            incrementLayout.addWidget(incrementSpinBox)
            incrementLayout.addWidget(buttons[1])
            gridLayout.addLayout(incrementLayout, 2, i)

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setContentsMargins(0, 0, 0, 0)

        self.movingNodeSelector = ui.hierarchyVolumeInput(hasNone=True, onChange=self.onTransformedVolumeChanged)
        formLayout.addRow("Moving volume:", self.movingNodeSelector)

        self.transformableTreeView = transformWidget.findChild(qt.QObject, "TransformableTreeView")
        self.transformedTreeView = transformWidget.findChild(qt.QObject, "TransformedTreeView")
        self.transformToolButton = transformWidget.findChild(qt.QObject, "TransformToolButton")
        self.untransformToolButton = transformWidget.findChild(qt.QObject, "UntransformToolButton")

        self.displayEditCollapsibleWidget = transformWidget.findChild(
            ctk.ctkCollapsibleButton, "DisplayEditCollapsibleWidget"
        )
        self.displayEditCollapsibleWidget.setText("Parameters")
        formLayout.addRow(self.displayEditCollapsibleWidget)

        self.reflectLRButton = qt.QPushButton("Reflect X")
        self.reflectLRButton.clicked.connect(self.onReflectLRButton)
        self.reflectPAButton = qt.QPushButton("Reflect Y")
        self.reflectPAButton.clicked.connect(self.onReflectPAButton)
        self.reflectISButton = qt.QPushButton("Reflect Z")
        self.reflectISButton.clicked.connect(self.onReflectISButton)

        frame = qt.QFrame()
        reflectButtonsHBoxLayout = qt.QHBoxLayout(frame)
        reflectButtonsHBoxLayout.addWidget(self.reflectLRButton)
        reflectButtonsHBoxLayout.addWidget(self.reflectPAButton)
        reflectButtonsHBoxLayout.addWidget(self.reflectISButton)
        self.displayEditCollapsibleWidget.layout().addWidget(frame)

        transposeGroup = qt.QGroupBox()
        transposeGroup.setTitle("Transpose axes")
        transposeLayout = qt.QHBoxLayout(transposeGroup)
        transposeLayout.addStretch(0.1)
        transposeLayout.addWidget(qt.QLabel("X Y Z \u2192"))

        self.transposeComboBox = qt.QComboBox()
        self.transposeComboBox.addItems(["X Z Y", "Y X Z", "Y Z X", "Z X Y", "Z Y X"])
        transposeLayout.addWidget(self.transposeComboBox)

        transposeButton = qt.QPushButton("Transpose")
        transposeButton.clicked.connect(lambda: self.onTranspose(self.transposeComboBox.currentText))
        transposeLayout.addWidget(transposeButton)
        transposeLayout.addStretch(1)
        self.displayEditCollapsibleWidget.layout().addWidget(transposeGroup)

        formLayout.addRow(" ", None)

        self.buttonsWidget = qt.QFrame()
        buttonsLayout = qt.QFormLayout(self.buttonsWidget)

        self.undoButton = qt.QPushButton("Undo")
        self.undoButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Undo.png"))
        self.undoButton.setToolTip(
            "Undo last change. The earliest undo is when the volume was loaded or transformation was last applied."
        )
        self.undoButton.enabled = False
        self.undoButton.clicked.connect(self.onUndoButtonClicked)

        self.redoButton = qt.QPushButton("Redo")
        self.redoButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Redo.png"))
        self.redoButton.setToolTip("Redo last change.")
        self.redoButton.enabled = False
        self.redoButton.clicked.connect(self.onRedoButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.undoButton)
        buttonsHBoxLayout.addWidget(self.redoButton)
        buttonsLayout.addRow(buttonsHBoxLayout)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Apply.png"))
        self.applyButton.setToolTip("Apply changes. This action cannot be undone.")
        self.applyButton.enabled = False
        self.applyButton.clicked.connect(self.onApplyButtonClicked)

        self.resetButton = qt.QPushButton("Reset")
        self.resetButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Reset.png"))
        self.resetButton.setToolTip("Reset changes to the last applied state.")
        self.resetButton.enabled = False
        self.resetButton.clicked.connect(self.onResetButtonClicked)

        applyResetButtonsHBoxLayout = qt.QHBoxLayout()
        applyResetButtonsHBoxLayout.addWidget(self.applyButton)
        applyResetButtonsHBoxLayout.addWidget(self.resetButton)
        buttonsLayout.addRow(applyResetButtonsHBoxLayout)

        formLayout.addRow(self.buttonsWidget)

        self.layout.addStretch(1)
        self.onTransformedVolumeChanged()

    def onTransformedVolumeChanged(self):
        slicer.app.processEvents(1000)
        node = self.movingNodeSelector.currentNode()
        visible = node is not None
        self.buttonsWidget.visible = visible
        self.displayEditCollapsibleWidget.visible = visible

        if not visible:
            self.onResetButtonClicked()
            return

        self.transformedTreeView.selectAll()
        self.untransformToolButton.click()

        self.transformableTreeView.setCurrentNode(node)
        self.transformToolButton.click()

    def updateRotation(self, dialIndex, value):
        # Value from dial is integer, but we want to have 1 decimal place precision
        value /= 10
        lastValue = self.lastRotationValues[dialIndex]
        delta = value - lastValue

        self.lastRotationValues[dialIndex] = value
        self.sliderCumulativeDelta[dialIndex] += delta

        angle = normalize_angle(self.sliderCumulativeDelta[dialIndex])

        rot = Rotation.from_euler("xyz"[dialIndex], angle, degrees=True)
        matrix3x3 = rot.as_matrix()

        rotMatrix = np.eye(4)
        rotMatrix[:3, :3] = matrix3x3

        node = self.movingNodeSelector.currentNode()
        nodeMatrix = vtk.vtkMatrix4x4()
        node.GetIJKToRASMatrix(nodeMatrix)
        nodeMatrix = slicer.util.arrayFromVTKMatrix(nodeMatrix)
        invNodeMatrix = np.linalg.inv(nodeMatrix)

        size = node.GetImageData().GetDimensions()
        center = np.array(size) / 2
        centerTranslation = np.eye(4)
        centerTranslation[:3, 3] = center
        invCenterTranslation = np.linalg.inv(centerTranslation)

        lastMatrix = self.transformMatrix
        newMatrix = lastMatrix @ nodeMatrix @ centerTranslation @ rotMatrix @ invCenterTranslation @ invNodeMatrix

        transformNode = self.transformNodeSelector.currentNode()
        slicer.util.updateTransformMatrixFromArray(transformNode, newMatrix)

        self.rotationLabels[dialIndex].setText(f"{angle:+.1f}\u00B0")

    def onSliderReleased(self):
        newTransformMatrix = slicer.util.arrayFromTransformMatrix(self.transformNodeSelector.currentNode())
        slicer.util.updateTransformMatrixFromArray(self.transformNodeSelector.currentNode(), self.transformMatrix)
        slicer.mrmlScene.SaveStateForUndo(self.transformNodeSelector.currentNode())
        slicer.util.updateTransformMatrixFromArray(self.transformNodeSelector.currentNode(), newTransformMatrix)
        self.transformMatrix = slicer.util.arrayFromTransformMatrix(self.transformNodeSelector.currentNode())
        self.configureButtonsState()

        self.sliderCumulativeDelta = [0, 0, 0]
        for axis, label in zip("XYZ", self.rotationLabels):
            label.setText(f"Rotate {axis}")

    def onUndoButtonClicked(self):
        slicer.mrmlScene.Undo()
        self.transformMatrix = slicer.util.arrayFromTransformMatrix(self.transformNodeSelector.currentNode())
        self.configureButtonsState()

    def onRedoButtonClicked(self):
        slicer.mrmlScene.Redo()
        self.transformMatrix = slicer.util.arrayFromTransformMatrix(self.transformNodeSelector.currentNode())
        self.configureButtonsState()

    def onApplyButtonClicked(self):
        selectedVolumeNodeNames = []
        self.transformedTreeView.selectAll()
        for index in self.transformedTreeView.selectedIndexes():
            selectedVolumeNodeNames.append(index.data())
        transformedNodes = self.logic.applyTransform(selectedVolumeNodeNames)
        self.renewHiddenTransformNode()
        for node in transformedNodes:
            self.transformableTreeView.setCurrentNode(node)
            self.transformToolButton.click()
        self.configureButtonsState()

    def onResetButtonClicked(self):
        for dial in self.dials:
            with BlockSignals(dial):
                dial.setValue(0)
        self.setRotationSlidersValues([0, 0, 0])
        self.sliderCumulativeDelta = [0, 0, 0]
        self.lastRotationValues = [0, 0, 0]

        self.transformedTreeView.selectAll()
        self.untransformToolButton.click()
        self.renewHiddenTransformNode()
        self.configureButtonsState()

        self.movingNodeSelector.setCurrentNode(None)

    def reflect(self, plane):
        transformNode = self.transformNodeSelector.currentNode()
        slicer.mrmlScene.SaveStateForUndo(transformNode)
        self.logic.reflect(transformNode, plane)
        self.configureButtonsState()

    def onReflectLRButton(self):
        self.reflect("LR")

    def onReflectPAButton(self):
        self.reflect("PA")

    def onReflectISButton(self):
        self.reflect("IS")

    def onTranspose(self, order):
        transformNode = self.transformNodeSelector.currentNode()
        slicer.mrmlScene.SaveStateForUndo(transformNode)
        order = order.replace(" ", "")
        self.logic.transpose(transformNode, order)
        self.configureButtonsState()

    def renewHiddenTransformNode(self):
        self.setRotationSlidersValues([0, 0, 0])
        if self.transformNodeSelector.currentNode() is not None:
            self.transformNodeSelector.currentNode().RemoveObserver(slicer.vtkMRMLTransformNode.TransformModifiedEvent)
            slicer.mrmlScene.RemoveNode(self.transformNodeSelector.currentNode())  # verify if this is necessary
        slicer.mrmlScene.ClearUndoStack()
        slicer.mrmlScene.ClearRedoStack()
        self.transformNodeSelector.addNode()
        self.transformNodeSelector.currentNode().UndoEnabledOn()
        self.transformMatrix = slicer.util.arrayFromTransformMatrix(self.transformNodeSelector.currentNode())
        self.transformNodeSelector.currentNode().AddObserver(
            slicer.vtkMRMLTransformNode.TransformModifiedEvent, self.onTransformNodeModified
        )

    def onTransformNodeModified(self, *args):
        self.applyButton.enabled = True
        self.resetButton.enabled = True
        self.transformInProgress = True

    def enter(self):
        super().enter()
        if not self.transformInProgress:
            slicer.mrmlScene.SetUndoOn()
            self.renewHiddenTransformNode()

    def exit(self):
        if not self.transformInProgress:
            slicer.mrmlScene.SetUndoOff()
            if self.transformNodeSelector.currentNode():
                self.transformNodeSelector.currentNode().RemoveObserver(
                    slicer.vtkMRMLTransformNode.TransformModifiedEvent
                )
                slicer.mrmlScene.RemoveNode(self.transformNodeSelector.currentNode())
                self.onTransformedVolumeChanged()

    def configureButtonsState(self):
        numberOfUndoLevels = slicer.mrmlScene.GetNumberOfUndoLevels()
        numberOfRedoLevels = slicer.mrmlScene.GetNumberOfRedoLevels()
        self.undoButton.enabled = numberOfUndoLevels
        self.redoButton.enabled = numberOfRedoLevels
        if numberOfUndoLevels > 0 or numberOfRedoLevels > 0:
            self.applyButton.enabled = True
            self.resetButton.enabled = True
            self.transformInProgress = True
        else:
            self.applyButton.enabled = False
            self.resetButton.enabled = False
            self.transformInProgress = False

    def setRotationSlidersValues(self, values):
        sliderNames = ["LRSlider", "PASlider", "ISSlider"]
        for i in range(len(["LRSlider", "PASlider", "ISSlider"])):
            slider = self.rotationSliders.findChild(slicer.qMRMLLinearTransformSlider, sliderNames[i])
            doubleSlider = slider.findChild(ctk.ctkDoubleSlider, "Slider")
            doubleSpinBox = slider.findChild(ctk.ctkDoubleSpinBox, "SpinBox")
            doubleSlider.blockSignals(True)
            doubleSpinBox.blockSignals(True)
            doubleSlider.setValue(values[i])
            doubleSpinBox.setValue(values[i])
            doubleSlider.blockSignals(False)
            doubleSpinBox.blockSignals(False)


class MicroCTTransformsLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def reflect(self, transformNode, plane):
        vtkMatrix = transformNode.GetMatrixTransformToParent()
        matrixArray = slicer.util.arrayFromVTKMatrix(vtkMatrix)
        if plane == "LR":
            if np.isclose(abs(matrixArray[0, 0]), 1):
                matrixArray[:, 0] *= -1
        elif plane == "PA":
            if np.isclose(abs(matrixArray[1, 1]), 1):
                matrixArray[:, 1] *= -1
        elif plane == "IS":
            if np.isclose(abs(matrixArray[2, 2]), 1):
                matrixArray[:, 2] *= -1

        vtkTransformationMatrix = vtk.vtkMatrix4x4()
        vtkTransformationMatrix.DeepCopy(list(np.array(matrixArray).flat))
        transformNode.SetMatrixTransformToParent(vtkTransformationMatrix)

    def transpose(self, transformNode, order):
        vtkMatrix = transformNode.GetMatrixTransformToParent()
        matrixArray = slicer.util.arrayFromVTKMatrix(vtkMatrix)
        columns = matrixArray.T
        reordered = columns.copy()
        map = {"X": 0, "Y": 1, "Z": 2}
        for i, axis in enumerate(order):
            reordered[i] = columns[map[axis]]

        matrixArray = reordered.T
        vtkTransformationMatrix = vtk.vtkMatrix4x4()
        vtkTransformationMatrix.DeepCopy(list(np.array(matrixArray).flat))
        transformNode.SetMatrixTransformToParent(vtkTransformationMatrix)

    def applyTransform(self, volumeNodeNames):
        transformedNodes = []
        for volumeNodeName in volumeNodeNames:
            volumeNode = slicer.util.getNode(volumeNodeName)
            transformedNodes.append(volumeNode)
            volumeNode.HardenTransform()

        return transformedNodes
