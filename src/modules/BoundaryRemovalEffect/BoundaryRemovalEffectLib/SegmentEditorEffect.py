import logging
import os

import SimpleITK as sitk
import ctk
import numpy as np
import qt
import sitkUtils
import slicer
import vtk
import qSlicerSegmentationsEditorEffectsPythonQt as effects
import traceback

from ltrace.slicer import helpers
from ltrace.slicer.lazy import lazy
from ltrace.slicer_utils import LTraceSegmentEditorEffectMixin
from SegmentEditorEffects import *
from typing import Union


FILTER_GRADIENT_MAGNITUDE = "GRADIENT_MAGNITUDE"


class SegmentEditorEffect(AbstractScriptedSegmentEditorEffect, LTraceSegmentEditorEffectMixin):
    def __init__(self, scriptedEffect):
        AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)
        scriptedEffect.name = "Boundary removal"
        scriptedEffect.perSegment = False
        scriptedEffect.requireSegments = True

        self.segment2DFillOpacity = None
        self.segment2DOutlineOpacity = None
        self.previewedSegmentID = None

        # Effect-specific members
        import vtkITK

        self.autoThresholdCalculator = vtkITK.vtkITKImageThresholdCalculator()

        self.timer = qt.QTimer()
        self.previewState = 0
        self.previewStep = 1
        self.previewSteps = 20
        self.timer.connect("timeout()", self.preview)
        self.timer.setParent(self.scriptedEffect.optionsFrame())

        self.isInitialized = False

        self.invisibleSegments = list()

        self.previewPipelines = {}
        self.setupPreviewDisplay()

        self.applyFinishedCallback = lambda: None
        self.setupFinishedCallback = lambda: None
        self.applyAllSupported = True

    def clone(self):
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
            <p>Removes the boundaries of the visible segments using a boundary detection filter.</p>
            <p>Only the visible segments are modified in the process.</p>
            <p>
              Instructions:
              <ol style="feature: 0">
                <li>Choose a boundary detection filter and press <i>Initialize</i>.</li>
                <li>Adjust the threshold while looking at the slice views to find a suitable boundary.</li>
                <li>If the user wants to inspect the filter result, mark the <i>Keep filter result</i> checkbox.</li>
                <li>Click <i>Apply</i>.</li>
              </ol>
            </p>
        </html>"""

    def activate(self):
        self.SetSourceVolumeIntensityMaskOff()

    def deactivate(self):
        self.SetSourceVolumeIntensityMaskOff()
        self.optionsFrame.setVisible(False)
        self.applyButton.setVisible(False)
        self.applyAllButton.setVisible(False)
        self.setEnabledSegmentationButtons(True)

        self.restorePreviewedSegmentTransparency()

        # Clear preview pipeline and stop timer
        self.clearPreviewDisplay()
        self.timer.stop()

        if not self.keepFilterResultCheckBox.isChecked():
            try:
                slicer.mrmlScene.RemoveNode(self.filterOutputVolume)
            except Exception as error:
                logging.debug(f"Error: {error}. Traceback:\n{traceback.format_exc()}")

        try:
            segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
            segmentation = segmentationNode.GetSegmentation()

            self.restoreSegments()

            segmentIDs = vtk.vtkStringArray()
            segmentation.GetSegmentIDs(segmentIDs)
            for index in range(segmentIDs.GetNumberOfValues()):
                segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentIDs.GetValue(index), True)
        except Exception as error:
            logging.debug(f"Error: {error}. Traceback:\n{traceback.format_exc()}")

        # Set views opacity back to normal
        nodes = slicer.util.getNodes("vtkMRMLSliceCompositeNode*")
        for node in nodes.values():
            node.SetBackgroundOpacity(1)
            node.SetForegroundOpacity(0)

    def setCurrentSegmentTransparent(self):
        """Save current segment opacity and set it to zero
        to temporarily hide the segment so that threshold preview
        can be seen better.
        It also restores opacity of previously previewed segment.
        Call restorePreviewedSegmentTransparency() to restore original
        opacity.
        """
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("Segment editor node is not available.")
            return

        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if not segmentationNode:
            return
        displayNode = segmentationNode.GetDisplayNode()
        if not displayNode:
            return
        segmentID = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()

        if segmentID == self.previewedSegmentID:
            # already previewing the current segment
            return

        # If another segment was previewed before, restore that.
        if self.previewedSegmentID:
            self.restorePreviewedSegmentTransparency()

        # Make current segment fully transparent
        if segmentID:
            self.segment2DFillOpacity = displayNode.GetSegmentOpacity2DFill(segmentID)
            self.segment2DOutlineOpacity = displayNode.GetSegmentOpacity2DOutline(segmentID)
            self.previewedSegmentID = segmentID
            displayNode.SetSegmentOpacity2DFill(segmentID, 0)
            displayNode.SetSegmentOpacity2DOutline(segmentID, 0)

    def restorePreviewedSegmentTransparency(self):
        """Restore previewed segment's opacity that was temporarily
        made transparen by calling setCurrentSegmentTransparent()."""
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("Segment editor node is not available.")
            return

        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if not segmentationNode:
            return
        displayNode = segmentationNode.GetDisplayNode()
        if not displayNode:
            return
        if not self.previewedSegmentID:
            # already previewing the current segment
            return
        displayNode.SetSegmentOpacity2DFill(self.previewedSegmentID, self.segment2DFillOpacity)
        displayNode.SetSegmentOpacity2DOutline(self.previewedSegmentID, self.segment2DOutlineOpacity)
        self.previewedSegmentID = None

    def onInitializeButtonClicked(self, _) -> None:
        if self.isInitialized:
            self.deactivate()
            return

        self.initialize()

    def __updateInitializeButtonText(self) -> None:
        text = "Initialize" if not self.isInitialized else "Cancel"
        self.initializeButton.setText(text)

    def setupOptionsFrame(self):
        initializeFrame = qt.QFrame()
        initializeLayout = qt.QHBoxLayout(initializeFrame)

        initializeLayout.addWidget(qt.QLabel("Filter:"))

        self.filterComboBox = qt.QComboBox()
        self.filterComboBox.setToolTip("Select the filter to detect boundaries.")
        self.filterComboBox.addItem("Gradient magnitude", FILTER_GRADIENT_MAGNITUDE)
        initializeLayout.addWidget(self.filterComboBox, 1)

        self.initializeButton = qt.QPushButton("")
        self.__updateInitializeButtonText()
        self.initializeButton.setMinimumSize(130, 25)
        self.initializeButton.clicked.connect(self.onInitializeButtonClicked)
        self.initializeButton.objectName = "Initialize Button"
        initializeLayout.addWidget(self.initializeButton)

        self.scriptedEffect.addOptionsWidget(initializeFrame)

        self.optionsFrame = qt.QFrame()
        self.optionsFrame.setMinimumHeight(160)
        optionsLayout = qt.QVBoxLayout(self.optionsFrame)

        self.enablePulsingCheckbox = qt.QCheckBox("Preview pulse")
        self.enablePulsingCheckbox.setCheckState(qt.Qt.Checked)
        optionsLayout.addWidget(self.enablePulsingCheckbox)

        self.thresholdSliderLabel = qt.QLabel("Threshold adjustment:")
        optionsLayout.addWidget(self.thresholdSliderLabel)

        self.thresholdSlider = ctk.ctkRangeWidget()
        self.thresholdSlider.spinBoxAlignment = qt.Qt.AlignTop
        self.thresholdSlider.singleStep = 0.01
        optionsLayout.addWidget(self.thresholdSlider)

        self.keepFilterResultCheckBox = qt.QCheckBox("Keep filter result")
        self.keepFilterResultCheckBox.setChecked(False)
        optionsLayout.addWidget(self.keepFilterResultCheckBox)

        optionsLayout.addStretch(1)

        self.scriptedEffect.addOptionsWidget(self.optionsFrame)
        self.optionsFrame.setVisible(False)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setMinimumHeight(25)
        self.scriptedEffect.addOptionsWidget(self.applyButton)
        self.applyButton.setVisible(False)
        self.applyButton.objectName = "Boundary Removal Apply Button"

        self.thresholdSlider.connect("valuesChanged(double,double)", self.onThresholdValuesChanged)
        self.applyButton.connect("clicked()", self.onApply)

        self.applyAllButton = qt.QPushButton("Apply All")
        self.applyAllButton.setMinimumHeight(25)
        self.scriptedEffect.addOptionsWidget(self.applyAllButton)
        self.applyAllButton.setVisible(False)
        self.applyAllButton.clicked.connect(self.onApplyAll)

        self.setupFinishedCallback()

    def setEnabledSegmentationButtons(self, enabled: bool):
        if self.isInitialized == (not enabled):
            return
        self.isInitialized = not enabled

        self.__updateInitializeButtonText()

        # While this follows the general idea of finding the editor widget
        # related to this effect, the reliability of this method has not
        # been thoroughly tested and it's not know if it's there's a case for failure
        editorWidget = self.optionsFrame.parent()
        while not isinstance(editorWidget, slicer.qMRMLSegmentEditorWidget):
            if not editorWidget:  # End of tree, no editor widget
                return
            editorWidget = editorWidget.parent()

        segmentationNodeComboBox = editorWidget.findChild(slicer.qMRMLNodeComboBox, "SegmentationNodeComboBox")
        segmentationNodeComboBox.setEnabled(enabled)

        sourceVolumeComboBox = editorWidget.findChild(slicer.qMRMLNodeComboBox, "SourceVolumeNodeComboBox")
        sourceVolumeComboBox.setEnabled(enabled)

        addSegmentButton = editorWidget.findChild(qt.QPushButton, "AddSegmentButton")
        addSegmentButton.setEnabled(enabled)

        hasSelectedSegment = (
            bool(self.scriptedEffect.parameterSetNode().GetSelectedSegmentID())
            if self.scriptedEffect.parameterSetNode() is not None
            else False
        )

        removeSegmentButton = editorWidget.findChild(qt.QPushButton, "RemoveSegmentButton")
        removeSegmentButton.setEnabled(enabled and hasSelectedSegment)

        show3DButton = editorWidget.findChild(slicer.qMRMLSegmentationShow3DButton, "Show3DButton")
        show3DButton.setEnabled(enabled and hasSelectedSegment)

        switchtoSegmentationButton = editorWidget.findChild(qt.QToolButton, "SwitchToSegmentationsButton")
        switchtoSegmentationButton.setEnabled(enabled)

        segmentsForm = editorWidget.findChild(ctk.ctkExpandableWidget, "SegmentsTableResizableFrame")
        segmentsForm.setEnabled(enabled)

        slicer.app.processEvents()

    def createCursor(self, widget):
        # Turn off effect-specific cursor for this effect
        return slicer.modules.AppContextInstance.mainWindow.cursor

    def sourceVolumeNodeChanged(self):
        # Set scalar range of master volume image data to threshold slider

        sourceImageData = self.scriptedEffect.sourceVolumeImageData()
        if sourceImageData:
            lo, hi = sourceImageData.GetScalarRange()
            self.thresholdSlider.setRange(lo, hi)
            self.thresholdSlider.singleStep = (hi - lo) / 1000.0
            if self.scriptedEffect.doubleParameter("MinimumThreshold") == self.scriptedEffect.doubleParameter(
                "MaximumThreshold"
            ):
                # has not been initialized yet
                self.scriptedEffect.setParameter("MinimumThreshold", lo + (hi - lo) * 0.25)
                self.scriptedEffect.setParameter("MaximumThreshold", hi)

    def layoutChanged(self):
        self.setupPreviewDisplay()

    def setMRMLDefaults(self):
        self.scriptedEffect.setParameterDefault("MinimumThreshold", 0.0)
        self.scriptedEffect.setParameterDefault("MaximumThreshold", 0)

    def updateGUIFromMRML(self):
        self.thresholdSlider.blockSignals(True)
        self.thresholdSlider.setMinimumValue(self.scriptedEffect.doubleParameter("MinimumThreshold"))
        self.thresholdSlider.setMaximumValue(self.scriptedEffect.doubleParameter("MaximumThreshold"))
        self.thresholdSlider.blockSignals(False)

    def updateMRMLFromGUI(self):
        with slicer.util.NodeModify(self.scriptedEffect.parameterSetNode()):
            self.scriptedEffect.setParameter("MinimumThreshold", self.thresholdSlider.minimumValue)
            self.scriptedEffect.setParameter("MaximumThreshold", self.thresholdSlider.maximumValue)

    #
    # Effect specific methods (the above ones are the API methods to override)
    #
    def initialize(self):
        if self.scriptedEffect.parameterSetNode() is None:
            logging.warning("Failed to initialize the effect. The selected node is not valid.")
            return

        self.scriptedEffect.saveStateForUndo()
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        segmentIDs = vtk.vtkStringArray()
        segmentation = segmentationNode.GetSegmentation()
        segmentation.GetSegmentIDs(segmentIDs)

        if segmentIDs.GetNumberOfValues() < 3:
            slicer.util.infoDisplay("There must be at least 3 segments to use this tool.")
            return

        self.optionsFrame.setVisible(True)
        self.applyButton.setVisible(True)

        node = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
        self.applyAllButton.visible = self.applyAllSupported and lazy.getParentLazyNode(node) is not None

        self.setCurrentSegmentTransparent()

        # Update intensity range
        self.sourceVolumeNodeChanged()

        # Setup and start preview pulse
        self.setupPreviewDisplay()
        self.timer.start(70)

        # Applying Gradient Magnitude Image Filter
        self.sourceVolumeNode = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
        self.filterOutputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        self.filterOutputVolume.SetName(self.sourceVolumeNode.GetName() + " - Edges")
        simpleFiltersWidget = slicer.modules.simplefilters.createNewWidgetRepresentation()
        if self.filterComboBox.currentData == FILTER_GRADIENT_MAGNITUDE:
            simpleFiltersWidget.self().filterSelector.setCurrentText("GradientMagnitudeImageFilter")
            sitkFilter = simpleFiltersWidget.self().filterParameters.filter
            inputImage = sitk.ReadImage(sitkUtils.GetSlicerITKReadWriteAddress(self.sourceVolumeNode.GetName()))
            outputImage = sitkFilter.Execute(*[inputImage])
            nodeWriteAddress = sitkUtils.GetSlicerITKReadWriteAddress(self.filterOutputVolume.GetName())
            sitk.WriteImage(outputImage, nodeWriteAddress)
            subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            itemParent = subjectHierarchyNode.GetItemParent(
                subjectHierarchyNode.GetItemByDataNode(self.sourceVolumeNode)
            )
            subjectHierarchyNode.SetItemParent(
                subjectHierarchyNode.GetItemByDataNode(self.filterOutputVolume), itemParent
            )

            # """
            # The Magnitude Image Filter generates a volume with few very high intensity value voxels that don't add to the result.
            # The code bellow is to exclude them, to allow a more useful threshold slider widget.
            # """
            # array = slicer.util.arrayFromVolume(self.filterOutputVolume)
            # maxValue = 0
            # step = (np.max(array) - np.min(array)) / 20
            # meaningfullVoxelFraction = array.size / 1000
            # while (array > maxValue).sum() > meaningfullVoxelFraction:
            #     maxValue += step
            # array[array > maxValue] = maxValue
            # slicer.util.updateVolumeFromArray(self.filterOutputVolume, array)
        self.selectedSegment = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()
        self.invisibleSegments = self.removeSegmentationVisibleSegments()

        for index in range(segmentIDs.GetNumberOfValues()):
            segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentIDs.GetValue(index), False)

        self.filterSegmentID = segmentationNode.GetSegmentation().AddEmptySegment("Edges", "Edges")
        segmentationNode.GetSegmentation().GetSegment(self.filterSegmentID).SetColor([0, 0, 1])
        self.scriptedEffect.parameterSetNode().SetAndObserveSourceVolumeNode(self.filterOutputVolume)
        self.scriptedEffect.parameterSetNode().SetSelectedSegmentID(self.filterSegmentID)
        self.autoThreshold()

        layoutManager = slicer.app.layoutManager()
        if layoutManager.layout == 201:  # Side-by-side Segmentation:
            imageLogic = layoutManager.sliceWidget("SideBySideImageSlice").sliceLogic()
            imageComposite = imageLogic.GetSliceCompositeNode()
            imageComposite.SetBackgroundVolumeID(self.filterOutputVolume.GetID())
            imageComposite.SetBackgroundOpacity(0)
            imageComposite.SetForegroundVolumeID(self.sourceVolumeNode.GetID())
            imageComposite.SetForegroundOpacity(1)

            segmentationLogic = layoutManager.sliceWidget("SideBySideSegmentationSlice").sliceLogic()
            segmentationComposite = segmentationLogic.GetSliceCompositeNode()
            segmentationComposite.SetBackgroundVolumeID(self.filterOutputVolume.GetID())
            segmentationComposite.SetBackgroundOpacity(0)
        else:
            slicer.util.setSliceViewerLayers(background=self.filterOutputVolume, foreground=self.sourceVolumeNode)
            nodes = slicer.util.getNodes("vtkMRMLSliceCompositeNode*")
            for node in nodes.values():
                node.SetBackgroundOpacity(0)
                node.SetForegroundOpacity(1)

        self.setEnabledSegmentationButtons(False)

    def onThresholdValuesChanged(self, min, max):
        self.scriptedEffect.updateMRMLFromGUI()

        # This is needed because the function above causes many widgets
        # to be reactivated, although, with the Form expandable widget deactivated,
        # interacting with them doesn't seem to have any immediate effect
        self.setEnabledSegmentationButtons(not self.isInitialized)

    def autoThreshold(self):
        self.autoThresholdCalculator.SetMethodToOtsu()
        sourceImageData = self.scriptedEffect.sourceVolumeImageData()
        self.autoThresholdCalculator.SetInputData(sourceImageData)
        self.autoThresholdCalculator.Update()
        computedThreshold = self.autoThresholdCalculator.GetThreshold()
        sourceVolumeMin, sourceVolumeMax = sourceImageData.GetScalarRange()
        self.scriptedEffect.setParameter("MinimumThreshold", computedThreshold)
        self.scriptedEffect.setParameter("MaximumThreshold", sourceVolumeMax)

    # Returns a list of tuples containing the necessary parameters to add the segments back
    def removeSegmentationVisibleSegments(self):
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("The segment editor node is not available.")
            return None

        removedSegments = list()

        # Always affects the current scriptedEffect's segmentation node directly, as
        # attempts of creating a deep copy have failed to produce results that
        # maintain the same behavior
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()

        if not segmentationNode:
            return None

        segmentation = segmentationNode.GetSegmentation()

        segmentIDs = vtk.vtkStringArray()
        segmentation.GetSegmentIDs(segmentIDs)

        for index in range(segmentIDs.GetNumberOfValues()):
            segID = segmentIDs.GetValue(index)
            if not segmentationNode.GetDisplayNode().GetSegmentVisibility(segID):
                toRemoveSegment = segmentation.GetSegment(segID)
                nextSegmentID = segmentIDs.GetValue(index + 1) if index + 1 < segmentIDs.GetNumberOfValues() else ""
                removedSegments.append((toRemoveSegment, segID, nextSegmentID))
                segmentation.RemoveSegment(segID)
        return removedSegments

    def onApplyAll(self):
        if self.scriptedEffect.parameterSetNode() is None:
            slicer.util.errorDisplay("Failed to apply the effect. The selected node is not valid.")
            return

        def getLazySegmentation(parentName: str) -> Union[None, slicer.vtkMRMLNode]:
            segmentationNode = None
            lazyNodes = slicer.util.getNodesByClass("vtkMRMLTextNode")
            for node in lazyNodes:
                if node.GetName().startswith(parentName) and node.GetName().endswith("_segmented"):
                    segmentationNode = node
                    break
            if segmentationNode is None and len(lazyNodes) > 0:
                segmentationNode = lazyNodes[-1]

            return segmentationNode

        minThreshold = self.scriptedEffect.doubleParameter("MinimumThreshold")
        maxThreshold = self.scriptedEffect.doubleParameter("MaximumThreshold")
        self.deactivate()
        volumeNode = lazy.getParentLazyNode(self.sourceVolumeNode) or self.sourceVolumeNode
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if volumeNode:
            segmentationNode = getLazySegmentation(volumeNode.GetName()) or segmentationNode

        slicer.util.selectModule("BoundaryRemovalBigImage")
        widget = slicer.modules.BoundaryRemovalBigImageWidget

        data = {
            "volumeNode": volumeNode,
            "segmentationNode": segmentationNode,
            "thresholdMinimumValue": minThreshold,
            "thresholdMaximumValue": maxThreshold,
        }

        widget.setParameters(**data)

    def restoreSegments(self):
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        segmentation = segmentationNode.GetSegmentation()
        # Restore in reverse order so next segment exists when current segment is added
        for segToAdd, segID, nextSegID in reversed(self.invisibleSegments):
            segmentation.AddSegment(segToAdd, segID, nextSegID)
        self.invisibleSegments.clear()

    def onApply(self):
        try:
            # Get master volume image data
            import vtkSegmentationCorePython as vtkSegmentationCore

            sourceImageData = self.scriptedEffect.sourceVolumeImageData()
            # Get modifier labelmap
            modifierLabelmap = self.scriptedEffect.defaultModifierLabelmap()
            originalImageToWorldMatrix = vtk.vtkMatrix4x4()
            modifierLabelmap.GetImageToWorldMatrix(originalImageToWorldMatrix)
            # Get parameters
            min = self.scriptedEffect.doubleParameter("MinimumThreshold")
            max = self.scriptedEffect.doubleParameter("MaximumThreshold")
            self.appliedMinMax = (min, max)

            # Perform thresholding
            thresh = vtk.vtkImageThreshold()
            thresh.SetInputData(sourceImageData)
            thresh.ThresholdBetween(min, max)
            thresh.SetInValue(1)
            thresh.SetOutValue(0)
            thresh.SetOutputScalarType(modifierLabelmap.GetScalarType())
            thresh.Update()
            modifierLabelmap.DeepCopy(thresh.GetOutput())
        except IndexError:
            logging.error(f"Error: {error}")
        except Exception as error:
            logging.debug(f"Error: {error}. Traceback:\n{traceback.format_exc()}")
            slicer.util.errorDisplay(f"Failed to apply the effect.\nError: {error}")
            return

        # Apply changes
        self.scriptedEffect.modifySelectedSegmentByLabelmap(
            modifierLabelmap, slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet
        )

        self.restoreSegments()

        # De-select effect
        self.scriptedEffect.selectEffect("")
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if not segmentationNode:
            return
        displayNode = segmentationNode.GetDisplayNode()
        if not displayNode:
            return
        segmentID = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()

        # Make current segment fully opaque
        if segmentID:
            displayNode.SetSegmentOpacity2DFill(segmentID, 1)
            displayNode.SetSegmentOpacity2DOutline(segmentID, 1)

        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        segmentIDs = vtk.vtkStringArray()
        segmentation = segmentationNode.GetSegmentation()
        segmentation.GetSegmentIDs(segmentIDs)
        for index in range(segmentIDs.GetNumberOfValues()):
            segmentationNode.GetDisplayNode().SetSegmentVisibility(segmentIDs.GetValue(index), True)
        self.scriptedEffect.parameterSetNode().SetAndObserveSourceVolumeNode(self.sourceVolumeNode)
        slicer.util.setSliceViewerLayers(background=self.sourceVolumeNode, foreground=None)
        nodes = slicer.util.getNodes("vtkMRMLSliceCompositeNode*")

        layoutManager = slicer.app.layoutManager()
        if layoutManager.layout == 201:  # Side-by-side Segmentation:
            imageLogic = layoutManager.sliceWidget("SideBySideImageSlice").sliceLogic()
            imageComposite = imageLogic.GetSliceCompositeNode()
            imageComposite.SetBackgroundOpacity(1)
        else:
            slicer.util.setSliceViewerLayers(background=self.filterOutputVolume, foreground=self.sourceVolumeNode)
            nodes = slicer.util.getNodes("vtkMRMLSliceCompositeNode*")
            for node in nodes.values():
                node.SetBackgroundOpacity(1)
                node.SetForegroundOpacity(0)

        segmentationNode.GetSegmentation().RemoveSegment(self.filterSegmentID)

        if not self.keepFilterResultCheckBox.isChecked():
            try:
                slicer.mrmlScene.RemoveNode(self.filterOutputVolume)
            except:
                pass
        # restore segment selection enableling effects
        if self.selectedSegment:
            self.scriptedEffect.parameterSetNode().SetSelectedSegmentID(self.selectedSegment)
        self.applyFinishedCallback()

    def clearPreviewDisplay(self):
        for sliceWidget, pipeline in self.previewPipelines.items():
            self.scriptedEffect.removeActor2D(sliceWidget, pipeline.actor)
        self.previewPipelines = {}

    def setupPreviewDisplay(self):
        # Clear previous pipelines before setting up the new ones
        self.clearPreviewDisplay()

        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return

        # Add a pipeline for each 2D slice view
        for sliceViewName in layoutManager.sliceViewNames():
            sliceWidget = layoutManager.sliceWidget(sliceViewName)
            if not self.scriptedEffect.segmentationDisplayableInView(sliceWidget.mrmlSliceNode()):
                continue
            renderer = self.scriptedEffect.renderer(sliceWidget)
            if renderer is None:
                logging.error("setupPreviewDisplay: Failed to get renderer!")
                continue

            # Create pipeline
            pipeline = PreviewPipeline()
            self.previewPipelines[sliceWidget] = pipeline

            # Add actor
            self.scriptedEffect.addActor2D(sliceWidget, pipeline.actor)

    def preview(self):
        try:
            if self.enablePulsingCheckbox.checkState() == qt.Qt.Checked:
                opacity = 0.1 + self.previewState / (2.0 * self.previewSteps)
            else:
                opacity = 1.0
            min = self.scriptedEffect.doubleParameter("MinimumThreshold")
            max = self.scriptedEffect.doubleParameter("MaximumThreshold")

            # Get color of edited segment
            segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
            if not segmentationNode:
                # scene was closed while preview was active
                return
            displayNode = segmentationNode.GetDisplayNode()
            if displayNode is None:
                logging.error("preview: Invalid segmentation display node!")
                color = [0.5, 0.5, 0.5]
            segmentID = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()

            # Make sure we keep the currently selected segment hidden (the user may have changed selection)
            if segmentID != self.previewedSegmentID:
                self.setCurrentSegmentTransparent()

            r, g, b = segmentationNode.GetSegmentation().GetSegment(segmentID).GetColor()

            # Set values to pipelines
            for sliceWidget in self.previewPipelines:
                pipeline = self.previewPipelines[sliceWidget]
                pipeline.lookupTable.SetTableValue(1, r, g, b, opacity)
                layerLogic = self.getSourceVolumeLayerLogic(sliceWidget)
                pipeline.thresholdFilter.SetInputConnection(layerLogic.GetReslice().GetOutputPort())
                pipeline.thresholdFilter.ThresholdBetween(min, max)
                pipeline.actor.VisibilityOn()
                sliceWidget.sliceView().scheduleRender()

            self.previewState += self.previewStep
            if self.previewState >= self.previewSteps:
                self.previewStep = -1
            if self.previewState <= 0:
                self.previewStep = 1
        except Exception as error:
            logging.debug(f"Error {error}. Traceback:\n{traceback.format_exc()}")
            # When an undo action is performed, it causes and exception due the to the removed Edges segment. We deactivate to start fresh all over again
            self.deactivate()

    def processInteractionEvents(self, callerInteractor, eventId, viewWidget):
        abortEvent = False

        sourceImageData = self.scriptedEffect.sourceVolumeImageData()
        if sourceImageData is None:
            return abortEvent

        # Only allow for slice views
        if viewWidget.className() != "qMRMLSliceWidget":
            return abortEvent

        return abortEvent

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

        # logging.warning("Master volume is not set as either the foreground or background")

        foregroundOpacity = 0.0
        if foregroundVolumeNode:
            compositeNode = sliceLogic.GetSliceCompositeNode()
            foregroundOpacity = compositeNode.GetForegroundOpacity()

        if foregroundOpacity > 0.5:
            return foregroundLogic

        return backgroundLogic


#
# PreviewPipeline
#
class PreviewPipeline(object):
    """Visualization objects and pipeline for each slice view for threshold preview"""

    def __init__(self):
        self.lookupTable = vtk.vtkLookupTable()
        self.lookupTable.SetRampToLinear()
        self.lookupTable.SetNumberOfTableValues(2)
        self.lookupTable.SetTableRange(0, 1)
        self.lookupTable.SetTableValue(0, 0, 0, 0, 0)
        self.colorMapper = vtk.vtkImageMapToRGBA()
        self.colorMapper.SetOutputFormatToRGBA()
        self.colorMapper.SetLookupTable(self.lookupTable)
        self.thresholdFilter = vtk.vtkImageThreshold()
        self.thresholdFilter.SetInValue(1)
        self.thresholdFilter.SetOutValue(0)
        self.thresholdFilter.SetOutputScalarTypeToUnsignedChar()

        # Feedback actor
        self.mapper = vtk.vtkImageMapper()
        self.dummyImage = vtk.vtkImageData()
        self.dummyImage.AllocateScalars(vtk.VTK_UNSIGNED_INT, 1)
        self.mapper.SetInputData(self.dummyImage)
        self.actor = vtk.vtkActor2D()
        self.actor.VisibilityOff()
        self.actor.SetMapper(self.mapper)
        self.mapper.SetColorWindow(255)
        self.mapper.SetColorLevel(128)

        # Setup pipeline
        self.colorMapper.SetInputConnection(self.thresholdFilter.GetOutputPort())
        self.mapper.SetInputConnection(self.colorMapper.GetOutputPort())
