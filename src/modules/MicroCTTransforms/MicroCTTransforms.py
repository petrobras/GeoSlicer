import os
from pathlib import Path

import ctk
import numpy as np
import qt
import slicer
import vtk
from Customizer import Customizer
from ltrace.slicer_utils import *


def normalize_angle(angle):
    return (angle + 180) % 360 - 180


class MicroCTTransforms(LTracePlugin):
    SETTING_KEY = "MicroCTTransforms"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Micro CT Transforms"
        self.parent.categories = ["Micro CT"]
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
        maxValueSpinBox = minMaxWidget.findChild(qt.QObject, "MaxValueSpinBox")
        maxValueSpinBox.setValue(10)

        self.rotationSliders = transformWidget.findChild(qt.QObject, "RotationSliders")
        self.transformNodeSelector = transformWidget.findChild(qt.QObject, "TransformNodeSelector")

        translationSliders = transformWidget.findChild(qt.QObject, "TranslationSliders")
        for i, sliderName in enumerate(["LRSlider", "PASlider", "ISSlider"]):
            slider = translationSliders.findChild(slicer.qMRMLLinearTransformSlider, sliderName)
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

        self.lastRotationValues = [0, 0, 0]
        self.sliderCumulativeDelta = [0, 0, 0]
        for i, sliderName in enumerate(["LRSlider", "PASlider", "ISSlider"]):
            slider = self.rotationSliders.findChild(slicer.qMRMLLinearTransformSlider, sliderName)
            dial = qt.QDial()
            dial.setWrapping(True)
            dial.valueChanged.connect(
                lambda value, sliderIndex=i, slider=slider: self.updateSlider(sliderIndex, slider, value)
            )
            dial.sliderReleased.connect(self.onSliderReleased)
            dial.setRange(-1800, 1800)
            dial.setOrientation(qt.Qt.Horizontal)
            dial.notchesVisible = True
            dial.setToolTip(f"Click and drag to rotate dial")
            gridLayout.addWidget(dial, 1, i)

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

        hBoxLayout = qt.QHBoxLayout()
        formLayout.addRow(hBoxLayout)

        vBoxLayout = qt.QVBoxLayout()
        self.transformableTreeView = transformWidget.findChild(qt.QObject, "TransformableTreeView")
        self.transformableTreeView.nodeTypes = [slicer.vtkMRMLVolumeNode.__name__]
        vBoxLayout.addWidget(qt.QLabel("Available volumes:"))
        vBoxLayout.addWidget(self.transformableTreeView)
        hBoxLayout.addLayout(vBoxLayout)

        vBoxLayout = qt.QVBoxLayout()
        self.transformToolButton = transformWidget.findChild(qt.QObject, "TransformToolButton")
        vBoxLayout.addWidget(self.transformToolButton)
        self.untransformToolButton = transformWidget.findChild(qt.QObject, "UntransformToolButton")
        vBoxLayout.addWidget(self.untransformToolButton)
        hBoxLayout.addLayout(vBoxLayout)

        vBoxLayout = qt.QVBoxLayout()
        self.transformedTreeView = transformWidget.findChild(qt.QObject, "TransformedTreeView")
        self.transformedTreeView.nodeTypes = [slicer.vtkMRMLVolumeNode.__name__]
        vBoxLayout.addWidget(qt.QLabel("Selected volumes:"))
        vBoxLayout.addWidget(self.transformedTreeView)
        hBoxLayout.addLayout(vBoxLayout)

        displayEditCollapsibleWidget = transformWidget.findChild(
            ctk.ctkCollapsibleButton, "DisplayEditCollapsibleWidget"
        )
        displayEditCollapsibleWidget.setText("Parameters")
        formLayout.addRow(displayEditCollapsibleWidget)

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
        displayEditCollapsibleWidget.layout().addWidget(frame)

        formLayout.addRow(" ", None)

        self.undoButton = qt.QPushButton("Undo")
        self.undoButton.setIcon(qt.QIcon(str(Customizer.UNDO_ICON_PATH)))
        self.undoButton.setToolTip(
            "Undo last change. The earliest undo is when the volume was loaded or transformation was last applied."
        )
        self.undoButton.enabled = False
        self.undoButton.clicked.connect(self.onUndoButtonClicked)

        self.redoButton = qt.QPushButton("Redo")
        self.redoButton.setIcon(qt.QIcon(str(Customizer.REDO_ICON_PATH)))
        self.redoButton.setToolTip("Redo last change.")
        self.redoButton.enabled = False
        self.redoButton.clicked.connect(self.onRedoButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.undoButton)
        buttonsHBoxLayout.addWidget(self.redoButton)
        formLayout.addRow(buttonsHBoxLayout)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setIcon(qt.QIcon(str(Customizer.APPLY_ICON_PATH)))
        self.applyButton.setToolTip("Apply changes. This action cannot be undone.")
        self.applyButton.enabled = False
        self.applyButton.clicked.connect(self.onApplyButtonClicked)

        self.resetButton = qt.QPushButton("Reset")
        self.resetButton.setIcon(qt.QIcon(str(Customizer.RESET_ICON_PATH)))
        self.resetButton.setToolTip("Reset changes to the last applied state.")
        self.resetButton.enabled = False
        self.resetButton.clicked.connect(self.onResetButtonClicked)

        applyResetButtonsHBoxLayout = qt.QHBoxLayout()
        applyResetButtonsHBoxLayout.addWidget(self.applyButton)
        applyResetButtonsHBoxLayout.addWidget(self.resetButton)
        formLayout.addRow(applyResetButtonsHBoxLayout)

        self.layout.addStretch(1)

    def updateSlider(self, sliderIndex, slider, value):
        # Value from dial is integer, but we want to have 1 decimal place precision
        value /= 10
        lastValue = self.lastRotationValues[sliderIndex]
        delta = value - lastValue
        slider.setValue(slider.value + delta)
        self.lastRotationValues[sliderIndex] = value
        self.sliderCumulativeDelta[sliderIndex] += delta
        angle = normalize_angle(self.sliderCumulativeDelta[sliderIndex])
        self.rotationLabels[sliderIndex].setText(f"{angle:+.1f}\u00B0")

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
        self.transformedTreeView.selectAll()
        self.untransformToolButton.click()
        self.renewHiddenTransformNode()
        self.configureButtonsState()

    def onReflectLRButton(self):
        self.logic.reflect(self.transformNodeSelector.currentNode(), "LR")

    def onReflectPAButton(self):
        self.logic.reflect(self.transformNodeSelector.currentNode(), "PA")

    def onReflectISButton(self):
        self.logic.reflect(self.transformNodeSelector.currentNode(), "IS")

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
        self.applyButton.enabled = False
        self.resetButton.enabled = False
        self.undoButton.enabled = False
        self.redoButton.enabled = False

        self.transformInProgress = True

    def enter(self):
        super().enter()
        if not self.transformInProgress:
            slicer.mrmlScene.SetUndoOn()
            self.renewHiddenTransformNode()

    def exit(self):
        if not self.transformInProgress:
            slicer.mrmlScene.SetUndoOff()
            self.transformNodeSelector.currentNode().RemoveObserver(slicer.vtkMRMLTransformNode.TransformModifiedEvent)
            slicer.mrmlScene.RemoveNode(self.transformNodeSelector.currentNode())

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
                matrixArray[0, 0] *= -1
        elif plane == "PA":
            if np.isclose(abs(matrixArray[1, 1]), 1):
                matrixArray[1, 1] *= -1
        elif plane == "IS":
            if np.isclose(abs(matrixArray[2, 2]), 1):
                matrixArray[2, 2] *= -1

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
