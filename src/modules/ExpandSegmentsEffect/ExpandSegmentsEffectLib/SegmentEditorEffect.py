import os

import SimpleITK as sitk
import numpy as np
import qt
import sitkUtils
import slicer
import vtk
from SegmentEditorEffects import *
from ltrace.slicer.helpers import hide_masking_widget
from typing import Union
from ltrace.slicer import helpers
from ltrace.slicer.lazy import lazy

from ltrace.slicer_utils import LTraceSegmentEditorEffectMixin


class SegmentEditorEffect(AbstractScriptedSegmentEditorEffect, LTraceSegmentEditorEffectMixin):
    def __init__(self, scriptedEffect):
        AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)
        scriptedEffect.name = "Expand segments"
        scriptedEffect.perSegment = False
        scriptedEffect.requireSegments = True

        self.applyFinishedCallback = lambda: None
        self.applyAllSupported = True
        self.editorWidget = None

    def getEditorWidget(self):
        widget = self.applyButton.parent()
        while not isinstance(widget, slicer.qMRMLSegmentEditorWidget):
            if not widget:  # End of tree, no editor widget
                return

            widget = widget.parent()

        return widget

    def activate(self):
        hide_masking_widget(self)
        self.SetSourceVolumeIntensityMaskOff()

        if self.editorWidget is None:
            self.editorWidget = self.getEditorWidget()

            if self.editorWidget is not None:
                sourceVolumeComboBox = self.editorWidget.findChild(slicer.qMRMLNodeComboBox, "SourceVolumeNodeComboBox")
                sourceVolumeComboBox.currentNodeChanged.connect(self.onSourceVolumeNodeChanged)

        node = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
        self.onSourceVolumeNodeChanged(node)

    def clone(self):
        import qSlicerSegmentationsEditorEffectsPythonQt as effects

        clonedEffect = effects.qSlicerSegmentEditorScriptedEffect(None)
        clonedEffect.setPythonSource(__file__.replace("\\", "/"))
        return clonedEffect

    def icon(self):
        iconPath = os.path.join(os.path.dirname(__file__), "SegmentEditorEffect.png")
        if os.path.exists(iconPath):
            return qt.QIcon(iconPath)
        return qt.QIcon()

    def helpText(self):
        return """
        <html><p>
            Applies the watershed process to expand the visible segments filling the empty segmentation spaces.
            The selected visible segments are used as seeds, or minima, from which they are expanded. </p>
            <p>Only the visible segments are modified in the process</p>
        </p></html>
        """

    def setupOptionsFrame(self):
        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setFixedHeight(40)
        self.applyButton.connect("clicked()", self.onApply)
        self.scriptedEffect.addOptionsWidget(self.applyButton)

        self.applyFullButton = qt.QPushButton("Apply to full volume")
        self.applyFullButton.setFixedHeight(40)
        self.applyFullButton.connect("clicked()", self.onApplyFull)
        self.applyFullButton.visible = False
        self.scriptedEffect.addOptionsWidget(self.applyFullButton)

    def onSourceVolumeNodeChanged(self, node):
        self.applyFullButton.visible = self.applyAllSupported and lazy.getParentLazyNode(node) is not None

    def createCursor(self, widget):
        # Turn off effect-specific cursor for this effect
        return slicer.util.mainWindow().cursor

    def onApply(self):
        if self.scriptedEffect.parameterSetNode() is None:
            slicer.util.errorDisplay("Failed to apply the effect. The selected node is not valid.")

        self.scriptedEffect.saveStateForUndo()

        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        labelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
            segmentationNode, labelMapNode, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
        )

        # Invisible segments will not be expanded
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        segmentIDs = vtk.vtkStringArray()
        segmentation = segmentationNode.GetSegmentation()
        segmentation.GetSegmentIDs(segmentIDs)
        array = slicer.util.arrayFromVolume(labelMapNode)
        invisibleSegmentsIndexes = []
        for segmentIndex in range(segmentIDs.GetNumberOfValues()):
            if not segmentationNode.GetDisplayNode().GetSegmentVisibility(segmentIDs.GetValue(segmentIndex)):
                indexes = np.where(array == segmentIndex + 1)
                invisibleSegmentsIndexes.append([segmentIndex + 1, indexes])
                array[indexes] = 0
        slicer.util.updateVolumeFromArray(labelMapNode, array)

        filter = sitk.MorphologicalWatershedFromMarkersImageFilter()
        filter.FullyConnectedOff()
        filter.MarkWatershedLineOff()
        marks = sitkUtils.PullVolumeFromSlicer(labelMapNode)
        image = sitk.Image(*labelMapNode.GetImageData().GetDimensions(), sitk.sitkUInt8)
        image.SetDirection(marks.GetDirection())
        image.SetOrigin(marks.GetOrigin())
        image.SetSpacing(marks.GetSpacing())
        result = filter.Execute(image, marks)
        sitkUtils.PushVolumeToSlicer(result, targetNode=labelMapNode)

        array = slicer.util.arrayFromVolume(labelMapNode)
        for segmentValue, indexes in invisibleSegmentsIndexes:
            array[indexes] = segmentValue
        slicer.util.updateVolumeFromArray(labelMapNode, array)

        segmentIDs = vtk.vtkStringArray()
        segmentation = segmentationNode.GetSegmentation()
        segmentation.GetSegmentIDs(segmentIDs)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
            labelMapNode, segmentationNode, segmentIDs
        )
        slicer.mrmlScene.RemoveNode(labelMapNode)

        self.applyFinishedCallback()

    def onApplyFull(self):
        if self.scriptedEffect.parameterSetNode() is None:
            slicer.util.errorDisplay("Failed to apply the effect. The selected node is not valid.")
            return

        def getLazySegmentation(parentName: str) -> Union[None, slicer.vtkMRMLNode]:
            segmentationNode = None
            lazyNodes = slicer.util.getNodesByClass("vtkMRMLTextNode")
            for node in lazyNodes:
                if node.GetName().startswith(parentName) and node.GetName().endswith("_filtered"):
                    segmentationNode = node
                    break
            if segmentationNode is None and len(lazyNodes) > 0:
                segmentationNode = lazyNodes[-1]
            return segmentationNode

        volumeNode = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
        volumeNode = lazy.getParentLazyNode(volumeNode) or volumeNode
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if volumeNode:
            segmentationNode = getLazySegmentation(volumeNode.GetName()) or segmentationNode
        slicer.util.selectModule("ExpandSegmentsBigImage")
        widget = slicer.modules.ExpandSegmentsBigImageWidget
        data = {
            "segmentationNode": segmentationNode,
        }
        widget.setParameters(**data)
