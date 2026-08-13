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
        self.filter = None
        self.abort = False

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
        self.applyButton.objectName = "Expand Segments Apply Button"
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
        return slicer.modules.AppContextInstance.mainWindow.cursor

    def cancel(self):
        self.abort = True
        if self.filter:
            self.filter.Abort()

    def onApply(self):
        self.abort = False
        if self.scriptedEffect.parameterSetNode() is None:
            slicer.util.errorDisplay("Failed to apply the effect. The selected node is not valid.")

        self.scriptedEffect.saveStateForUndo()

        try:
            with self.progress() as update_progress:
                update_progress(5, label="Starting...")
                segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
                labelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
                slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
                    segmentationNode, labelMapNode, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
                )
                try:
                    array = slicer.util.arrayFromVolume(labelMapNode)
                except AttributeError:  # Array is empty
                    slicer.util.errorDisplay(
                        "Failed to apply the effect. The segmentation node doesn't contain any filled segments."
                    )
                    slicer.mrmlScene.RemoveNode(labelMapNode)
                    return

                if self.abort:
                    raise RuntimeError("AbortGenerateDataOn")

                update_progress(10, label="Masking...")
                # Invisible segments will not be expanded
                segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
                segmentation = segmentationNode.GetSegmentation()
                array = slicer.util.arrayFromVolume(labelMapNode)
                invisibleSegmentsIndexes = []
                for segmentIndex in range(segmentation.GetNumberOfSegments()):
                    segmentID = segmentation.GetNthSegmentID(segmentIndex)
                    if not segmentationNode.GetDisplayNode().GetSegmentVisibility(segmentID):
                        indexes = np.where(array == segmentIndex + 1)
                        invisibleSegmentsIndexes.append([segmentIndex + 1, indexes])
                        array[indexes] = 0
                slicer.util.updateVolumeFromArray(labelMapNode, array)

                if self.abort:
                    raise RuntimeError("AbortGenerateDataOn")

                self.filter = sitk.MorphologicalWatershedFromMarkersImageFilter()
                self.applyButton.setEnabled(False)
                self.applyFullButton.setEnabled(False)

                self.filter.FullyConnectedOff()
                self.filter.MarkWatershedLineOff()
                marks = sitkUtils.PullVolumeFromSlicer(labelMapNode)
                image = sitk.Image(*labelMapNode.GetImageData().GetDimensions(), sitk.sitkUInt8)
                image.SetDirection(marks.GetDirection())
                image.SetOrigin(marks.GetOrigin())
                image.SetSpacing(marks.GetSpacing())
                self.filter.AddCommand(
                    sitk.sitkProgressEvent,
                    lambda: update_progress(
                        10 + self.filter.GetProgress() * 90,
                        label="Expanding segments...",
                    ),
                )
                result = self.filter.Execute(image, marks)
        except RuntimeError as e:
            if "AbortGenerateDataOn" in str(e):
                slicer.mrmlScene.RemoveNode(labelMapNode)
                return
            raise e
        finally:
            self.applyButton.setEnabled(True)
            self.applyFullButton.setEnabled(True)

        sitkUtils.PushVolumeToSlicer(result, targetNode=labelMapNode)

        array = slicer.util.arrayFromVolume(labelMapNode)
        for segmentValue, indexes in invisibleSegmentsIndexes:
            array[indexes] = segmentValue
        slicer.util.updateVolumeFromArray(labelMapNode, array)

        segmentation = segmentationNode.GetSegmentation()
        segmentIDs = []
        for i in range(segmentation.GetNumberOfSegments()):
            segmentIDs.append(segmentation.GetNthSegmentID(i))

        vtkSegmentIDs = vtk.vtkStringArray()
        for segmentID in segmentIDs:
            vtkSegmentIDs.InsertNextValue(segmentID)

        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
            labelMapNode, segmentationNode, vtkSegmentIDs
        )

        for i, segmentID in enumerate(segmentIDs):
            segmentation.SetSegmentIndex(segmentID, i)

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
