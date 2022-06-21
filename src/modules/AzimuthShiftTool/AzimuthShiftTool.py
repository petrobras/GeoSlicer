import ctk
import os
import qt
import slicer

from ltrace.slicer import helpers
from ltrace.slicer.node_attributes import ImageLogDataSelectable
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from pathlib import Path
import numpy as np

try:
    from Test.AzimuthShiftToolTest import AzimuthShiftToolTest
except ImportError:
    AzimuthShiftToolTest = None  # tests not deployed to final version or closed source


class AzimuthShiftTool(LTracePlugin):
    SETTING_KEY = "AzimuthShiftTool"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Azimuth Shift Tool"
        self.parent.categories = ["LTrace Tools"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = AzimuthShiftTool.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class AzimuthShiftToolWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

        self.subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        self.logic = AzimuthShiftToolLogic()

    def setup(self):
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.masterImage = hierarchyVolumeInput(
            onChange=self.onMasterNodeChange,
            nodeTypes=[
                "vtkMRMLVectorVolumeNode",
                "vtkMRMLScalarVolumeNode",
            ],
            hasNone=True,
        )
        self.masterImage.objectName = "masterImage"
        self.masterImage.setToolTip("Select the image to be corrected")

        self.shiftTable = hierarchyVolumeInput(
            onChange=self.onTableNodeChange,
            nodeTypes=[
                "vtkMRMLTableNode",
            ],
            hasNone=True,
        )
        self.shiftTable.objectName = "shiftTable"
        self.shiftTable.setToolTip("Select an  UBI azimuth table to correct the image")

        self.tableColumnComboBox = qt.QComboBox()
        self.tableColumnComboBox.setToolTip("Select the column of the table with the shift values")
        self.tableColumnComboBox.objectName = "tableColumn"

        inputFormLayout = qt.QFormLayout(inputSection)
        inputFormLayout.addRow("Image node:", self.masterImage)
        inputFormLayout.addRow("Azimuth Table:", self.shiftTable)
        inputFormLayout.addRow("Table Column:", self.tableColumnComboBox)

        # Parameters sections
        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False

        self.invertDirection = qt.QCheckBox()
        self.invertDirection.objectName = "invertDirectionCheckBox"
        self.invertDirection.setToolTip("If checked, the image will be shifted anti-clockwise instead.")

        parametersLayout = qt.QFormLayout(parametersSection)
        parametersLayout.addRow("Invert Direction:", self.invertDirection)

        # Output section
        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.objectName = "outputPrefix"
        self.outputPrefix.setToolTip("Name of the corrected image output")
        self.outputPrefix.textChanged.connect(self.checkApplyState)
        outputFormLayout = qt.QFormLayout(outputSection)
        outputFormLayout.addRow("Output prefix:", self.outputPrefix)

        # Apply button
        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.clicked.connect(self.onApplyButtonClicked)
        self.applyButton.objectName = "applyButton"
        self.applyButton.enabled = False
        self.applyButton.setToolTip("Run the azimuth shift correcting tool")

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addWidget(self.applyButton)
        self.layout.addStretch(1)

    def onApplyButtonClicked(self):
        self.applyButton.enabled = False

        self.logic.apply(
            self.masterImage.currentNode(),
            self.shiftTable.currentNode(),
            self.tableColumnComboBox.currentText,
            self.invertDirection.isChecked(),
            self.outputPrefix.text,
        )

        self.applyButton.enabled = True

    def onTableNodeChange(self, itemId):
        tableNode = self.subjectHierarchyNode.GetItemDataNode(itemId)
        if tableNode:
            self.tableColumnComboBox.clear()
            columns = [tableNode.GetColumnName(index) for index in range(tableNode.GetNumberOfColumns())]
            columns.remove("DEPTH")
            self.tableColumnComboBox.addItems(columns)
        else:
            self.tableColumnComboBox.clear()
        self.checkApplyState()

    def onMasterNodeChange(self, itemId):
        volumeNode = self.subjectHierarchyNode.GetItemDataNode(itemId)
        if volumeNode:
            self.outputPrefix.text = f"{self.masterImage.currentNode().GetName()}_corrected"
        else:
            self.outputPrefix.text = ""

    def checkApplyState(self):
        if (
            self.masterImage.currentNode() is not None
            and self.shiftTable.currentNode() is not None
            and self.outputPrefix.text.replace(" ", "") != ""
        ):
            self.applyButton.enabled = True
        else:
            self.applyButton.enabled = False


class AzimuthShiftToolLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def apply(self, volumeNode, tableNode, tableColumn, invertDirection, name):
        volumeArray = slicer.util.arrayFromVolume(volumeNode)
        dataFrame = slicer.util.dataframeFromTable(tableNode)
        shiftArray = np.array(dataFrame[tableColumn])

        volumeArrayCorrected = np.zeros(volumeArray.shape)
        for i in range(volumeArray.shape[0]):
            if np.isnan(shiftArray[i]):
                volumeArrayCorrected[i, 0, :] = volumeArray[i, 0, :]
            else:
                indicesShift = shiftArray[i] * volumeArray.shape[2] / 360
                indicesBase = int(indicesShift)

                indicesToRoll = -indicesBase if invertDirection else indicesBase + 1
                interval = (indicesShift - indicesBase) if invertDirection else (1 - (indicesShift - indicesBase))

                volumeRolled = np.roll(volumeArray[i, 0, :], indicesToRoll)
                volumeRolled = np.append(volumeRolled, volumeRolled[0])
                interpolationPoints = np.arange(volumeArray.shape[2]) + interval

                volumeArrayCorrected[i, :, :] = np.interp(
                    interpolationPoints, np.arange(volumeArray.shape[2] + 1), volumeRolled
                )

        newVolume = slicer.mrmlScene.AddNewNodeByClass(volumeNode.GetClassName(), name)
        newVolume.CopyOrientation(volumeNode)
        newVolume.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
        slicer.util.updateVolumeFromArray(newVolume, volumeArrayCorrected)

        helpers.copy_display(volumeNode, newVolume)

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        parent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(volumeNode))

        subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(newVolume), parent)
