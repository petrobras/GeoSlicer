import datetime
import logging
import os
from collections import namedtuple
from pathlib import Path

import ctk
import numpy as np
import qt
import slicer
from ltrace.slicer.helpers import (
    triggerNodeModified,
    highlight_error,
    reset_style_on_valid_node,
    reset_style_on_valid_text,
)
from ltrace.slicer.widgets import SingleShotInputWidget
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer_utils import slicer_is_in_developer_mode, LTracePlugin, LTracePluginWidget, LTracePluginLogic
from scipy.ndimage import zoom


class ThinSectionAutoRegistration(LTracePlugin):
    SETTING_KEY = "ThinSectionAutoRegistration"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Thin Section Auto Registration"
        self.parent.categories = ["Registration"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ThinSectionAutoRegistration.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ThinSectionAutoRegistrationWidget(LTracePluginWidget):

    RegisterParameters = namedtuple(
        "RegisterParameters",
        [
            "fixedNode",
            "fixedNodeSegments",
            "movingNode",
            "movingNodeSegments",
            "outputPrefix",
        ],
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = CTAutoRegistrationLogic(self.progressBar)

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

        self.fixedNodeInputWidget = SingleShotInputWidget(
            hideImage=True,
            hideSoi=True,
            hideCalcProp=True,
            requireSourceVolume=False,
            allowedInputNodes=[
                "vtkMRMLLabelMapVolumeNode",
                "vtkMRMLSegmentationNode",
            ],
            rowTitles={
                "main": "   Fixed segmentation",
                "reference": "Reference",
            },
        )
        inputFormLayout.addRow(self.fixedNodeInputWidget)
        reset_style_on_valid_node(self.fixedNodeInputWidget.mainInput)
        self.fixedNodeInputWidget.segmentSelectionChanged.connect(
            lambda: self.fixedNodeInputWidget.segmentListWidget.setStyleSheet("")
        )

        self.movingNodeInputWidget = SingleShotInputWidget(
            hideImage=True,
            hideSoi=True,
            hideCalcProp=True,
            requireSourceVolume=False,
            allowedInputNodes=["vtkMRMLLabelMapVolumeNode"],
            rowTitles={
                "main": "Moving segmentation",
                "reference": "Reference",
            },
        )
        self.movingNodeInputWidget.onMainSelected = self.movingNodeChanged
        inputFormLayout.addRow(self.movingNodeInputWidget)
        reset_style_on_valid_node(self.movingNodeInputWidget.mainInput)
        self.movingNodeInputWidget.segmentSelectionChanged.connect(
            lambda: self.movingNodeInputWidget.segmentListWidget.setStyleSheet("")
        )

        inputFormLayout.addRow(" ", None)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.outputPrefixLineEdit = qt.QLineEdit()
        outputFormLayout.addRow("Output prefix:", self.outputPrefixLineEdit)
        outputFormLayout.addRow(" ", None)
        reset_style_on_valid_text(self.outputPrefixLineEdit)

        self.registerButton = qt.QPushButton("Apply")
        self.registerButton.setFixedHeight(40)
        self.registerButton.clicked.connect(self.onRegisterButtonClicked)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.registerButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        formLayout.addRow(buttonsHBoxLayout)

        self.layout.addWidget(self.progressBar)

        self.layout.addStretch()

    def movingNodeChanged(self, node):
        if node:
            outputPrefix = node.GetName()
        else:
            outputPrefix = ""
        self.outputPrefixLineEdit.text = outputPrefix

    def onRegisterButtonClicked(self):
        try:

            if self.fixedNodeInputWidget.mainInput.currentNode() is None:
                highlight_error(self.fixedNodeInputWidget.mainInput)
                return

            if len(self.fixedNodeInputWidget.getSelectedSegments()) == 0:
                highlight_error(self.fixedNodeInputWidget.segmentListWidget)
                return

            if self.movingNodeInputWidget.mainInput.currentNode() is None:
                highlight_error(self.movingNodeInputWidget.mainInput)
                return

            if len(self.movingNodeInputWidget.getSelectedSegments()) == 0:
                highlight_error(self.movingNodeInputWidget.segmentListWidget)
                return

            if self.outputPrefixLineEdit.text.strip() == "":
                highlight_error(self.outputPrefixLineEdit)
                return

            registerParameters = self.RegisterParameters(
                self.fixedNodeInputWidget.mainInput.currentNode(),
                self.fixedNodeInputWidget.getSelectedSegments(),
                self.movingNodeInputWidget.mainInput.currentNode(),
                self.movingNodeInputWidget.getSelectedSegments(),
                self.outputPrefixLineEdit.text,
            )
            self.logic.register(registerParameters)
        except RegistrationInfo as e:
            slicer.util.infoDisplay(str(e))
            return

    def onCancelButtonClicked(self):
        self.logic.cancel()


class CTAutoRegistrationLogic(LTracePluginLogic):
    def __init__(self, progressBar):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar

    def downsampleVolume(self, volume):
        realSpacing = np.array(volume.GetSpacing())
        targetSpacing = np.array([0.01, 0.01, 0.01])
        downsamplingFactor = realSpacing / targetSpacing
        volume.SetSpacing(targetSpacing)
        array = slicer.util.arrayFromVolume(volume)
        rescaledArray = zoom(array, [1, downsamplingFactor[1], downsamplingFactor[0]], order=1, cval=np.min(array))
        slicer.util.updateVolumeFromArray(volume, rescaledArray)

    def getFilteredBinaryScalarNode(self, node, segmentIndexes):
        volumesLogic = slicer.modules.volumes.logic()
        if type(node) is slicer.vtkMRMLSegmentationNode:
            filteredLabelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
            slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
                node, filteredLabelMapNode, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
            )
        elif type(node) is slicer.vtkMRMLLabelMapVolumeNode:
            filteredLabelMapNode = volumesLogic.CloneVolume(node, "")
        else:
            raise RuntimeError("Invalid node type.")

        segmentIndexes = np.array(segmentIndexes) + 1
        array = slicer.util.arrayFromVolume(filteredLabelMapNode)
        array[np.isin(array, np.array(segmentIndexes))] = -1
        array[array != -1] = 0
        array[array == -1] = 1

        filteredBinaryScalarNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        volumesLogic.CreateScalarVolumeFromVolume(slicer.mrmlScene, filteredBinaryScalarNode, filteredLabelMapNode)

        slicer.mrmlScene.RemoveNode(filteredLabelMapNode)

        return filteredBinaryScalarNode

    def removeSmallIslands(self, binaryScalarNode):
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")

        # Create segment editor to get access to effects
        segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
        segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
        segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)
        segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(binaryScalarNode)
        addedSegmentID = segmentationNode.GetSegmentation().AddEmptySegment("")
        segmentEditorWidget.setSegmentationNode(segmentationNode)
        segmentEditorWidget.setSourceVolumeNode(binaryScalarNode)
        segmentEditorWidget.setCurrentSegmentID(addedSegmentID)

        # Thresholding
        segmentEditorWidget.setActiveEffectByName("Threshold")
        effect = segmentEditorWidget.activeEffect()
        effect.setParameter("MinimumThreshold", "1")
        effect.setParameter("MaximumThreshold", "1")
        effect.self().onApply()

        # Removing small islands
        segmentEditorWidget.setActiveEffectByName("Islands")
        effect = segmentEditorWidget.activeEffect()
        effect.setParameter("Operation", "REMOVE_SMALL_ISLANDS")
        effect.setParameter("MinimumSize", "100")
        effect.self().onApply()

        # Extracting a new binary scalar node
        segmentEditorWidget.setActiveEffectByName("Mask volume")
        effect = segmentEditorWidget.activeEffect()
        segmentEditorNode.SetMaskSegmentID(addedSegmentID)
        effect.setParameter("Operation", "FILL_OUTSIDE")
        effect.setParameter("FillValue", 0)
        effect.self().outputVolumeSelector.setCurrentNode(binaryScalarNode)
        effect.self().onApply()

        slicer.mrmlScene.RemoveNode(segmentationNode)
        slicer.mrmlScene.RemoveNode(segmentEditorNode)

        return binaryScalarNode

    def register(self, p):
        print("Thin Section Auto Registration start time: " + str(datetime.datetime.now()))

        self.movingNode = p.movingNode
        self.outputPrefix = p.outputPrefix

        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        self.movingNodeItemParent = subjectHierarchyNode.GetItemParent(
            subjectHierarchyNode.GetItemByDataNode(p.movingNode)
        )

        if type(p.fixedNode) is slicer.vtkMRMLSegmentationNode:
            subjectHierarchyNode.SetItemDisplayVisibility(subjectHierarchyNode.GetItemByDataNode(p.fixedNode), False)

        if type(p.movingNode) is slicer.vtkMRMLSegmentationNode:
            subjectHierarchyNode.SetItemDisplayVisibility(subjectHierarchyNode.GetItemByDataNode(p.movingNode), False)

        qt.QTimer.singleShot(1, self.delayedSetSliceViewerLayers)

        self.fixedBinaryScalarNode = self.getFilteredBinaryScalarNode(p.fixedNode, p.fixedNodeSegments)
        self.fixedBinaryScalarNode.SetName(p.outputPrefix + " - Binary fixed")
        self.downsampleVolume(self.fixedBinaryScalarNode)
        self.removeSmallIslands(self.fixedBinaryScalarNode)
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(self.fixedBinaryScalarNode), self.movingNodeItemParent
        )

        self.movingBinaryScalarNode = self.getFilteredBinaryScalarNode(p.movingNode, p.movingNodeSegments)
        self.movingBinaryScalarNode.SetName(p.outputPrefix + " - Binary moving")
        self.downsampleVolume(self.movingBinaryScalarNode)
        self.removeSmallIslands(self.movingBinaryScalarNode)
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(self.movingBinaryScalarNode), self.movingNodeItemParent
        )

        if not slicer_is_in_developer_mode():
            self.fixedBinaryScalarNode.HideFromEditorsOn()
            triggerNodeModified(self.fixedBinaryScalarNode)

            self.movingBinaryScalarNode.HideFromEditorsOn()
            triggerNodeModified(self.movingBinaryScalarNode)

        # Output linear transform
        self.outputLinearTransform = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLLinearTransformNode",
            p.outputPrefix + " - Registration transform",
        )
        self.outputLinearTransform.HideFromEditorsOn()
        triggerNodeModified(self.outputLinearTransform)
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(self.outputLinearTransform), self.movingNodeItemParent
        )

        # See https://www.slicer.org/w/index.php/Documentation/Nightly/Modules/BRAINSFit
        cliParams = {
            "fixedVolume": self.fixedBinaryScalarNode.GetID(),
            "movingVolume": self.movingBinaryScalarNode.GetID(),
            "samplingPercentage": 1,
            "transformType": "ScaleSkewVersor3D",
            "minimumStepLength": 0.00001,
            "numberOfIterations": 300,
            "translationScale": 100,
            "linearTransform": self.outputLinearTransform.GetID(),
        }

        self.cliNode = slicer.cli.run(slicer.modules.brainsfit, None, cliParams)
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.registrationCLICallback)

    def delayedSetSliceViewerLayers(self):
        slicer.util.setSliceViewerLayers(background=None, foreground=None, label=None)

    def registrationCLICallback(self, caller, event):
        if caller is None:
            self.cliNode = None
            return
        if self.cliNode is None:
            return
        status = caller.GetStatusString()
        if "Completed" in status or status == "Cancelled":
            logging.info(status)
            self.cliNode = None
            if not slicer_is_in_developer_mode():
                slicer.mrmlScene.RemoveNode(self.fixedBinaryScalarNode)
                slicer.mrmlScene.RemoveNode(self.movingBinaryScalarNode)
            if status == "Completed":
                self.outputLinearTransform.HideFromEditorsOff()
                triggerNodeModified(self.outputLinearTransform)

                volumesLogic = slicer.modules.volumes.logic()
                transformedMovingNode = volumesLogic.CloneVolume(self.movingNode, self.outputPrefix + " - Registered")
                transformedMovingNode.SetAndObserveTransformNodeID(self.outputLinearTransform.GetID())
                transformedMovingNode.HardenTransform()

                subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
                subjectHierarchyNode.SetItemParent(
                    subjectHierarchyNode.GetItemByDataNode(transformedMovingNode), self.movingNodeItemParent
                )

                slicer.util.setSliceViewerLayers(
                    background=None, foreground=transformedMovingNode, label=None, fit=True
                )
                print("Thin Section Auto Registration end time: " + str(datetime.datetime.now()))
                slicer.util.infoDisplay("Registration completed.")
            elif status == "Cancelled":
                slicer.mrmlScene.RemoveNode(self.outputLinearTransform)
                slicer.util.infoDisplay("Registration cancelled.")
            else:
                slicer.mrmlScene.RemoveNode(self.outputLinearTransform)
                slicer.util.errorDisplay("Registration failed.")

    def cancel(self):
        if self.cliNode is None:
            return  # nothing running, nothing to do
        self.cliNode.Cancel()


class RegistrationInfo(RuntimeError):
    pass
