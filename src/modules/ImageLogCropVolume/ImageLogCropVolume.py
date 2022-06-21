import os
from pathlib import Path
import math
import ctk
import qt
import slicer
import numpy as np

from ltrace.slicer import ui
from ltrace.slicer.helpers import clone_volume, copy_display, highlight_error, remove_highlight
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic


try:
    from Test.ImageLogCropVolumeTest import ImageLogCropVolumeTest
except ImportError:
    ImageLogCropVolumeTest = None  # tests not deployed to final version or closed source


class ImageLogCropVolume(LTracePlugin):
    SETTING_KEY = "ImageLogCropVolume"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Image Log Crop Volume"
        self.parent.categories = ["Image Log"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = ImageLogCropVolume.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ImageLogCropVolumeWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

        self.origins = np.zeros(3)
        self.spacing = np.zeros(3)
        self.dimensions = np.zeros(3)

    def setup(self):
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.InputSelector = ui.hierarchyVolumeInput(
            onChange=self.onInputNodeChange,
            hasNone=True,
            nodeTypes=[
                "vtkMRMLScalarVolumeNode",
                "vtkMRMLVectorVolumeNode",
                "vtkMRMLLabelMapVolumeNode",
            ],
        )
        self.InputSelector.setMRMLScene(slicer.mrmlScene)
        self.InputSelector.setToolTip("Pick a volume node to be cropped")
        self.InputSelector.objectName = "Input combobox"

        self.volumeResolution = qt.QLabel("")
        self.volumeResolution.hide()
        self.volumeResolution.objectName = "Input resolution label"
        self.volumeResolutionLabel = qt.QLabel("Dimensions:")
        self.volumeResolutionLabel.hide()

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Input:", self.InputSelector)
        inputLayout.addRow(self.volumeResolutionLabel, self.volumeResolution)

        # Parameters section
        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False
        parametersSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        depthTopLayout = qt.QHBoxLayout()
        self.depthTopSpinBox = qt.QDoubleSpinBox()
        self.depthTopSpinBox.setSuffix(" m")
        self.depthTopSpinBox.setDecimals(6)
        self.depthTopSpinBox.objectName = "Top depth spinbox"
        self.depthTopSpinBox.valueChanged.connect(self.onTopDepthChange)

        self.indexTopSpinBox = qt.QSpinBox()
        self.indexTopSpinBox.objectName = "Top index spinbox"
        self.indexTopSpinBox.valueChanged.connect(self.onTopDepthIndexChange)

        depthTopLayout.addWidget(qt.QLabel("Top Depth: "))
        depthTopLayout.addWidget(self.depthTopSpinBox)
        depthTopLayout.addWidget(qt.QLabel("  Top index:"))
        depthTopLayout.addWidget(self.indexTopSpinBox)
        depthTopLayout.addStretch()

        self.topWidget = qt.QWidget()
        self.topWidget.setLayout(depthTopLayout)

        depthBottomLayout = qt.QHBoxLayout()
        self.depthBottomSpinBox = qt.QDoubleSpinBox()
        self.depthBottomSpinBox.setSuffix(" m")
        self.depthBottomSpinBox.setDecimals(6)
        self.depthBottomSpinBox.objectName = "Bottom depth spinbox"
        self.depthBottomSpinBox.valueChanged.connect(self.onBottomDepthChange)

        self.indexBottomSpinBox = qt.QSpinBox()
        self.indexBottomSpinBox.objectName = "Bottom index spinbox"
        self.indexBottomSpinBox.valueChanged.connect(self.onBottomDepthIndexChange)

        depthBottomLayout.addWidget(qt.QLabel("Bottom Depth: "))
        depthBottomLayout.addWidget(self.depthBottomSpinBox)
        depthBottomLayout.addWidget(qt.QLabel("  Bottom index: "))
        depthBottomLayout.addWidget(self.indexBottomSpinBox)
        depthBottomLayout.addStretch()

        self.bottomWidget = qt.QWidget()
        self.bottomWidget.setLayout(depthBottomLayout)

        parametersLayout = qt.QFormLayout(parametersSection)
        parametersLayout.addWidget(self.topWidget)
        parametersLayout.addWidget(self.bottomWidget)

        # Output section
        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.objectName = "Output Prefix Line Edit"
        self.outputPrefix.textChanged.connect(self.checkApplyButtonState)
        outputFormLayout = qt.QFormLayout(outputSection)
        outputFormLayout.addRow("Output prefix:", self.outputPrefix)

        # Apply button
        self.applyButton = ui.ApplyButton(
            onClick=self.onApplyButtonClicked, tooltip="Crop image using the indexes", enabled=False
        )
        self.applyButton.objectName = "Apply Button"

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addWidget(self.applyButton)
        self.layout.addStretch(1)

    def onApplyButtonClicked(self, state):
        logic = ImageLogCropVolumeLogic()
        logic.apply(
            self.InputSelector.currentNode(),
            self.indexTopSpinBox.value,
            self.indexBottomSpinBox.value,
            self.outputPrefix.text,
        )

    def checkApplyButtonState(self):
        self.applyButton.enabled = False
        if self.InputSelector.currentNode() is not None and self.outputPrefix.text.replace(" ", "") != "":
            if self.indexBottomSpinBox.value <= self.indexTopSpinBox.value:
                highlight_error(self.indexBottomSpinBox)
                highlight_error(self.indexTopSpinBox)
            else:
                self.applyButton.enabled = True
                remove_highlight(self.indexBottomSpinBox)
                remove_highlight(self.indexTopSpinBox)

    def onInputNodeChange(self, itemId):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        volumeNode = subjectHierarchyNode.GetItemDataNode(itemId)
        if volumeNode:
            self.origins = -np.array(volumeNode.GetOrigin()) / 1000
            self.spacing = np.array(volumeNode.GetSpacing()) / 1000
            self.dimensions = np.array(volumeNode.GetImageData().GetDimensions())

            self.volumeResolution.setText(f"{self.dimensions[0]} x {self.dimensions[1]} x {self.dimensions[2]}")
            self.volumeResolution.show()
            self.volumeResolutionLabel.show()

            self.depthTopSpinBox.setRange(self.origins[2], self.origins[2] + self.dimensions[2] * self.spacing[2])
            self.depthTopSpinBox.setValue(self.origins[2])
            self.depthTopSpinBox.setSingleStep(self.spacing[2])
            self.depthBottomSpinBox.setRange(self.origins[2], self.origins[2] + self.dimensions[2] * self.spacing[2])
            self.depthBottomSpinBox.setValue(self.origins[2] + self.dimensions[2] * self.spacing[2])
            self.depthBottomSpinBox.setSingleStep(self.spacing[2])

            self.indexTopSpinBox.setRange(0, self.dimensions[2])
            self.indexTopSpinBox.setValue(0)
            self.indexBottomSpinBox.setRange(0, self.dimensions[2])
            self.indexBottomSpinBox.setValue(self.dimensions[2])

            self.outputPrefix.text = f"{volumeNode.GetName()}_cropped"
        else:
            self.depthTopSpinBox.setRange(0, 0)
            self.depthBottomSpinBox.setRange(0, 0)
            self.indexTopSpinBox.setRange(0, 0)
            self.indexBottomSpinBox.setRange(0, 0)

            self.volumeResolution.hide()
            self.volumeResolutionLabel.hide()
            self.outputPrefix.text = ""

    def __calculateDepthFromIndex(self, index):
        return self.origins[2] + self.spacing[2] * index

    def __calculateIndexFromDepth(self, depth, isFloor):
        print("floor:", math.floor((depth - self.origins[2]) / self.spacing[2]))
        if isFloor:
            return math.floor((depth - self.origins[2]) / self.spacing[2])
        else:
            return math.ceil((depth - self.origins[2]) / self.spacing[2])

    def onTopDepthChange(self, depth):
        if self.depthTopSpinBox.hasFocus():
            index = self.__calculateIndexFromDepth(depth, True)
            self.indexTopSpinBox.setValue(index)

    def onBottomDepthChange(self, depth):
        if self.depthBottomSpinBox.hasFocus():
            index = self.__calculateIndexFromDepth(depth, False)
            self.indexBottomSpinBox.setValue(index)

    def onTopDepthIndexChange(self, index):
        if self.indexTopSpinBox.hasFocus():
            depth = self.__calculateDepthFromIndex(index)
            self.depthTopSpinBox.setValue(depth)
        self.checkApplyButtonState()

    def onBottomDepthIndexChange(self, index):
        if self.indexBottomSpinBox.hasFocus():
            depth = self.__calculateDepthFromIndex(index)
            self.depthBottomSpinBox.setValue(depth)
        self.checkApplyButtonState()


class ImageLogCropVolumeLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def apply(self, volumeNode, topIndex, bottomIndex, name):
        origins = volumeNode.GetOrigin()
        spacing = volumeNode.GetSpacing()

        nodeArray = slicer.util.arrayFromVolume(volumeNode)
        newNode = clone_volume(volumeNode, name, as_temporary=False)
        slicer.util.updateVolumeFromArray(newNode, nodeArray[topIndex:bottomIndex, :, :])
        newNode.SetOrigin(origins[0], origins[1], origins[2] - topIndex * spacing[2])
        newNode.SetSpacing(spacing)

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(volumeNode))
        subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(newNode), itemParent)

        copy_display(volumeNode, newNode)
