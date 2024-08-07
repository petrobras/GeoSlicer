import os
import re
import vtk
import qt
import ctk
import logging
import vtk.util.numpy_support as vn

import numpy as np

import slicer
from ltrace.slicer import helpers
from ltrace.image import optimized_transforms
from SegmentEditorEffects import *

from ltrace.slicer_utils import LTraceSegmentEditorEffectMixin


class SegmentEditorEffect(AbstractScriptedSegmentEditorEffect, LTraceSegmentEditorEffectMixin):
    """LocalThresholdEffect is an effect that can perform a localized threshold when the user ctrl-clicks on the image."""

    def __init__(self, scriptedEffect):
        AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)
        scriptedEffect.name = "Connectivity"

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
        return """<html>
<p>
Calculate the connected image in a given direction. The input is a segment from a segmentation. The output is a new segment, which is added to the input segmentation.
</p>
<p>
  Parameters:
  <ul style="feature: 0">
    <li><b>Segmentation: Choose the input segment by selecting it from the segment list</b> </li>        
    <li><b>Connectivity:</b> Maximum number of orthogonal hops to consider a pixel/voxel as a neighbor. Accepted values are ranging from 1 to 3. <br></li>    
    <li><b>Direction:</b> The default is 'z', can be 'y', 'x', 'z+', 'y+', 'x+', 'z-', 'y-', 'x-' or 'all' too. '-' and '+' denotes just one face, in the beggining or the end of the sample, respectively.</li>    
    <li><b>Output prefix:</b> Prefix of the output segment name.</li>
    <li><b>Apply:</b> Click on apply to run the algorithm. </li>    
  </ul>
</p>
<p>
Simple instructions: Select the input segment by selecting it from the segment list, then select a direction and type an output prefix for the output segment.
</p>
</html>"""

    def activate(self):
        currentName = self.scriptedEffect.parameter(f"ConnectivityEffect.OutputVolumeName")
        self.scriptedEffect.setParameterDefault("ConnectivityEffect.OutputVolumeName", currentName)
        self.outputNamePrefixEdit.text = currentName
        helpers.hide_masking_widget(self)

    def deactivate(self):
        pass

    def setMRMLDefaults(self):
        self.scriptedEffect.setParameterDefault("ConnectivityEffect.hops", 1)
        self.scriptedEffect.setParameterDefault("ConnectivityEffect.direction", "z")
        self.scriptedEffect.setParameterDefault("ConnectivityEffect.OutputVolumeName", "Connectivity")

    def setupOptionsFrame(self):
        # SegmentEditorThresholdEffect.setupOptionsFrame(self)

        # input volume selector
        self.hopsNumberSlider = slicer.qMRMLSliderWidget()
        self.hopsNumberSlider.minimum = 1
        self.hopsNumberSlider.maximum = 3
        self.hopsNumberSlider.value = 1
        self.hopsNumberSlider.singleStep = 1
        self.hopsNumberSlider.tracking = False

        CHOICES = ["z", "y", "x", "z+", "y+", "x+", "z-", "y-", "x-", "all", "any"]
        self.directionChoice = qt.QComboBox()
        for choice in CHOICES:
            self.directionChoice.addItem(choice)

        self.outputNamePrefixEdit = qt.QLineEdit()
        self.outputNamePrefixEdit.editingFinished.connect(self.updateMRMLFromGUI)

        # Apply button
        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.objectName = self.__class__.__name__ + "Apply"
        self.applyButton.setToolTip("Calculate the connected image in the direction given.")  #

        self.hopsNumberSlider.valueChanged.connect(self.onHopsChanged)
        self.directionChoice.currentTextChanged.connect(self.onDirectionChanged)
        self.applyButton.connect("clicked()", self.onApply)

        self.scriptedEffect.addLabeledOptionsWidget("Connectivity:", self.hopsNumberSlider)
        self.scriptedEffect.addLabeledOptionsWidget("Direction: ", self.directionChoice)
        self.scriptedEffect.addLabeledOptionsWidget("Output prefix: ", self.outputNamePrefixEdit)
        self.scriptedEffect.addOptionsWidget(self.applyButton)

    def activate(self):
        self.SetSourceVolumeIntensityMaskOff()

    def deactivate(self):
        self.SetSourceVolumeIntensityMaskOff()

    def createCursor(self, widget):
        # Turn off effect-specific cursor for this effect
        return slicer.util.mainWindow().cursor

    def onHopsChanged(self, hops):
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("The segment editor node is not available.")
            return
        sourceVolumeNode = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
        voxelArray = np.squeeze(slicer.util.arrayFromVolume(sourceVolumeNode))
        if hops > voxelArray.ndim:
            slicer.util.errorDisplay("Connectivity cannot be greater than you data dimensionality.")
            return

        self.updateMRMLFromGUI()

    def onDirectionChanged(self, direction):
        self.updateMRMLFromGUI()

    def getSegmentData(self, segmentationNode, sourceVolumeNode):
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("The segment editor node is not available.")
            return

        # Get color of edited segment
        if not segmentationNode:
            # scene was closed while preview was active
            slicer.util.errorDisplay("Segmentation Node must be a valid node.")
            return
        displayNode = segmentationNode.GetDisplayNode()
        if displayNode is None:
            slicer.util.errorDisplay("Segmentation Node must be displayable.")

        segmentID = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()
        labelmap = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentID, sourceVolumeNode)
        return labelmap

    def cropBox(self, referenceNode):
        from ltrace import transforms
        from ltrace.slicer import helpers

        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()

        rasToIJK = vtk.vtkMatrix4x4()
        referenceNode.GetRASToIJKMatrix(rasToIJK)
        ndshape = referenceNode.GetImageData().GetDimensions()  # reverse to use as numpy array

        bounds = np.zeros(6)
        segmentationNode.GetBounds(bounds)
        ijkBounds = transforms.transformPoints(rasToIJK, bounds.reshape((3, 2)).T)
        return helpers.cropBounds(ndshape, ijkBounds)

    def onApply(self):
        try:
            params = self.scriptedEffect.parameterSetNode()
            segmentationNode = params.GetSegmentationNode()
            sourceVolumeNode = params.GetSourceVolumeNode()
            syncedImageData = self.scriptedEffect.sourceVolumeImageData()

            outputNamePrefix = self.scriptedEffect.parameter("ConnectivityEffect.OutputVolumeName")
            hops = int(self.scriptedEffect.integerParameter("ConnectivityEffect.hops"))
            direction = self.scriptedEffect.parameter("ConnectivityEffect.direction")

            inputSegmentName = segmentationNode.GetSegmentation().GetSegment(params.GetSelectedSegmentID()).GetName()
            outputSegmentName = (
                f"{outputNamePrefix}"
                f"_{inputSegmentName}"
                f"_{direction.capitalize()}"
                f"_C{int(self.hopsNumberSlider.value)}"
            )
            outputSegmentName = slicer.mrmlScene.GenerateUniqueName(outputSegmentName)

            voxelArray = np.squeeze(slicer.util.arrayFromVolume(sourceVolumeNode))
            if hops > voxelArray.ndim:
                slicer.util.errorDisplay("Connectivity cannot be greater than you data dimensionality.")
                return

            # Create new node for output
            volumesLogic = slicer.modules.volumes.logic()
            outputVolume = volumesLogic.CreateAndAddLabelVolume(sourceVolumeNode, outputSegmentName)
            helpers.makeNodeTemporary(outputVolume)

            self.scriptedEffect.parameterSetNode().SetNodeReferenceID(
                "ConnectivityEffect.OutputVolume", outputVolume.GetID()
            )

            ndShape = np.array(syncedImageData.GetDimensions()[::-1])

            if np.any(ndShape == 0):
                slicer.util.errorDisplay("Invalid master volume node. Empty dimensions are not allowed.")
                return

            slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
            voxels = self.getSegmentData(segmentationNode, sourceVolumeNode) == 1
            # transposing because numpy slicer data is zyx
            connVoxels = optimized_transforms.connected_image(
                np.transpose(voxels, (2, 1, 0)), connectivity=hops, direction=direction
            )
            connVoxels = np.transpose(connVoxels, (2, 1, 0)).astype(np.int32)
            qt.QApplication.restoreOverrideCursor()

            if not np.any(connVoxels):
                raise ValueError("No connected voxels in segment.")

            slicer.util.updateVolumeFromArray(outputVolume, connVoxels)

            slicer.vtkSlicerSegmentationsModuleLogic.ImportLabelmapToSegmentationNode(outputVolume, segmentationNode)
            segmentation = segmentationNode.GetSegmentation()
            segmentation.GetNthSegment(segmentation.GetNumberOfSegments() - 1).SetName(outputSegmentName)
        except Exception as error:
            slicer.app.restoreOverrideCursor()
            slicer.util.errorDisplay(f"Failed to apply the effect.\nError: {error}.")
        finally:
            helpers.removeTemporaryNodes()

    def updateGUIFromMRML(self):
        self.outputNamePrefixEdit.text = self.scriptedEffect.parameter("ConnectivityEffect.OutputVolumeName")

        self.hopsNumberSlider.blockSignals(True)
        self.hopsNumberSlider.value = self.scriptedEffect.integerParameter("ConnectivityEffect.hops")
        self.hopsNumberSlider.blockSignals(False)

        self.directionChoice.blockSignals(True)
        self.directionChoice.setCurrentText(self.scriptedEffect.parameter("ConnectivityEffect.direction"))
        self.directionChoice.blockSignals(False)

    def updateMRMLFromGUI(self):
        with slicer.util.NodeModify(self.scriptedEffect.parameterSetNode()):
            self.scriptedEffect.setParameter("ConnectivityEffect.OutputVolumeName", self.outputNamePrefixEdit.text)
            self.scriptedEffect.setParameter("ConnectivityEffect.hops", int(self.hopsNumberSlider.value))
            self.scriptedEffect.setParameter("ConnectivityEffect.direction", self.directionChoice.currentText)

    def _getColor(self):
        color = [0.5, 0.5, 0.5]
        # Get color of edited segment
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("The segment editor node is not available.")
            return color

        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if not segmentationNode:
            # scene was closed while preview was active
            return color
        displayNode = segmentationNode.GetDisplayNode()
        if displayNode is None:
            logging.error("preview: Invalid segmentation display node!")
        segmentID = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()
        if segmentID is None:
            return color

        # Change color hue slightly to make it easier to distinguish filled regions from preview
        r, g, b = segmentationNode.GetSegmentation().GetSegment(segmentID).GetColor()
        import colorsys

        colorHsv = colorsys.rgb_to_hsv(r, g, b)
        return colorsys.hsv_to_rgb((colorHsv[0] + 0.2) % 1.0, colorHsv[1], colorHsv[2])

    def getSourceVolumeLayerLogic(self, sliceWidget):
        sourceVolumeNode = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
        sliceLogic = sliceWidget.sliceLogic()

        backgroundLogic = sliceLogic.GetBackgroundLayer()
        backgroundVolumeNode = backgroundLogic.GetVolumeNode()
        if sourceVolumeNode == backgroundVolumeNode:
            return backgroundLogic

        foregroundLogic = sliceLogic.GetForegroundLayer()
        foregroundVolumeNode = foregroundLogic.GetVolumeNode()
        if sourceVolumeNode == foregroundVolumeNode:
            return foregroundLogic

        logging.warning("Master volume is not set as either the foreground or background")

        foregroundOpacity = 0.0
        if foregroundVolumeNode:
            compositeNode = sliceLogic.GetSliceCompositeNode()
            foregroundOpacity = compositeNode.GetForegroundOpacity()

        if foregroundOpacity > 0.5:
            return foregroundLogic

        return backgroundLogic
