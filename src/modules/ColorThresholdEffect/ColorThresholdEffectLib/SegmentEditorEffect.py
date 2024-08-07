import os
import vtk, qt, ctk, slicer
import logging
from SegmentEditorEffects import *

import vtkITK
import SimpleITK as sitk
import sitkUtils
import math
import numpy as np
import qSlicerSegmentationsEditorEffectsPythonQt as effects

import vtk.util.numpy_support as vn

from ltrace.slicer_utils import LTraceSegmentEditorEffectMixin


class SegmentEditorEffect(AbstractScriptedSegmentEditorEffect, LTraceSegmentEditorEffectMixin):
    """LocalThresholdEffect is an effect that can perform a localized threshold when the user ctrl-clicks on the image."""

    HSV_COLOR_AXES = ("H", "S", "V")
    PARAMS = ("min", "max")

    DEFAULT_COLOR_MODE = "HSV"
    DEFAULT_PREVIEW = 1

    def __init__(self, scriptedEffect):
        scriptedEffect.name = "Color threshold"
        AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)

        self.segment2DFillOpacity = None
        self.segment2DOutlineOpacity = None
        self.previewedSegmentID = None

        # Effect-specific members
        import vtkITK

        self.autoThresholdCalculator = vtkITK.vtkITKImageThresholdCalculator()

        self.timer = qt.QTimer()
        self.previewState = 0
        self.previewStep = 1
        self.previewSteps = 5
        self.timer.connect("timeout()", self.preview)

        self.previewPipelines = {}
        self.histogramPipeline = None
        self.setupPreviewDisplay()

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
<p>
Fill segment based on input image HSV/RGB range. 
</p>
<p>
  Options:
  <ul style="feature: 0">
    <li><b>Use HSV instead of RGB:</b> If checked, define color range in terms of hue, saturation and value.
    If not checked, range is defined in terms of red, green and blue color levels.
    </li>
  </ul>
</p>
<p>
Apply: set the previewed segmentation in the selected segment. Previous contents of the segment are overwritten.
</p>
</html>"""

    def activate(self):
        self.SetSourceVolumeIntensityMaskOff()
        self.setCurrentSegmentTransparent()

        # Update intensity range
        self.sourceVolumeNodeChanged()

        # Setup and start preview pulse
        self.setupPreviewDisplay()
        self.timer.start(250)

    def deactivate(self):
        self.SetSourceVolumeIntensityMaskOff()
        self.restorePreviewedSegmentTransparency()

        # Clear preview pipeline and stop timer
        self.clearPreviewDisplay()
        self.timer.stop()

    def setCurrentSegmentTransparent(self):
        """Save current segment opacity and set it to zero
        to temporarily hide the segment so that threshold preview
        can be seen better.
        It also restores opacity of previously previewed segment.
        Call restorePreviewedSegmentTransparency() to restore original
        opacity.
        """
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("The segment editor node is not available.")
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

        # If an other segment was previewed before, restore that.
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
            logging.debug("The segment editor node is not available.")
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

    def setCurrentSegmentTransparent(self):
        pass

    def restorePreviewedSegmentTransparency(self):
        pass

    def buildHUEThresholdSliderWidget(self, minColor, maxColor, onChange, initMinColor=None, initMaxColor=None):
        initMinColor = initMinColor or minColor
        initMaxColor = initMaxColor or maxColor
        imageThresholdSlidehueWidget = ctk.ctkRangeWidget()
        imageThresholdSlidehueWidget.singleStep = 1
        imageThresholdSlidehueWidget.minimum = 0
        imageThresholdSlidehueWidget.maximum = 255
        imageThresholdSlidehueWidget.setMinimumValue(initMinColor)
        imageThresholdSlidehueWidget.setMaximumValue(initMaxColor)
        imageThresholdSlidehueWidget.setToolTip(
            "Set threshold value for computing the output image. Voxels that have intensities lower than this value will set to zero."
        )

        imageThresholdSlidehueWidget.connect("valuesChanged(double,double)", onChange)

        return imageThresholdSlidehueWidget

    def setThresholdSlidehueWidgetLimits(self, imageThresholdSlidehueWidget, min_, max_):
        imageThresholdSlidehueWidget.minimum = min_
        imageThresholdSlidehueWidget.maximum = max_

    def setMRMLDefaults(self):
        self.scriptedEffect.setParameterDefault("ColorThresholdEffect.H.min", 0)
        self.scriptedEffect.setParameterDefault("ColorThresholdEffect.H.max", 225)
        self.scriptedEffect.setParameterDefault("ColorThresholdEffect.S.min", 43)
        self.scriptedEffect.setParameterDefault("ColorThresholdEffect.S.max", 100)
        self.scriptedEffect.setParameterDefault("ColorThresholdEffect.V.min", 43)
        self.scriptedEffect.setParameterDefault("ColorThresholdEffect.V.max", 100)
        self.scriptedEffect.setParameterDefault("ColorThresholdEffect.mode", self.DEFAULT_COLOR_MODE)
        self.scriptedEffect.setParameterDefault("ColorThresholdEffect.pulse", self.DEFAULT_PREVIEW)

    def setupOptionsFrame(self):

        # SegmentEditorThresholdEffect.setupOptionsFrame(self)

        # Hide threshold options
        # self.applyButton.setHidden(True)
        # self.useForPaintButton.setHidden(True)

        # thresholdControlsLayout = qt.QFormLayout()

        self.enablePulsingCheckbox = qt.QCheckBox("Preview pulse")
        pulse_enabled = self.DEFAULT_PREVIEW > 0
        self.enablePulsingCheckbox.setChecked(pulse_enabled)
        self.scriptedEffect.addOptionsWidget(self.enablePulsingCheckbox)

        #
        # Hue/Red threshold value
        #
        self.hueThresholdSlider = self.buildHUEThresholdSliderWidget(
            minColor=self.scriptedEffect.doubleParameter("ColorThresholdEffect.H.min"),
            maxColor=self.scriptedEffect.doubleParameter("ColorThresholdEffect.H.max"),
            onChange=self.onThresholdValuesChanged,
            initMinColor=0,
            initMaxColor=220,
        )
        self.hueLabel = qt.QLabel("H: ")
        self.hueWidget = qt.QWidget()
        hueLayout = qt.QHBoxLayout()
        hueLayout.addWidget(self.hueLabel)
        hueLayout.addWidget(self.hueThresholdSlider)
        self.hueWidget.setLayout(hueLayout)
        self.scriptedEffect.addOptionsWidget(self.hueWidget)

        #
        # Saturation/Green threshold value
        #

        self.saturationThresholdSlider = self.buildHUEThresholdSliderWidget(
            minColor=self.scriptedEffect.doubleParameter("ColorThresholdEffect.S.min"),
            maxColor=self.scriptedEffect.doubleParameter("ColorThresholdEffect.S.max"),
            onChange=self.onThresholdValuesChanged,
            initMinColor=43,
            initMaxColor=100,
        )
        self.saturationLabel = qt.QLabel("S: ")
        self.saturationWidget = qt.QWidget()
        saturationLayout = qt.QHBoxLayout()
        saturationLayout.addWidget(self.saturationLabel)
        saturationLayout.addWidget(self.saturationThresholdSlider)
        self.saturationWidget.setLayout(saturationLayout)
        self.scriptedEffect.addOptionsWidget(self.saturationWidget)

        #
        # Value/Blue threshold value
        #
        self.valueThresholdSlider = self.buildHUEThresholdSliderWidget(
            minColor=self.scriptedEffect.doubleParameter("ColorThresholdEffect.V.min"),
            maxColor=self.scriptedEffect.doubleParameter("ColorThresholdEffect.V.max"),
            onChange=self.onThresholdValuesChanged,
            initMinColor=43,
            initMaxColor=100,
        )
        self.valueLabel = qt.QLabel("V: ")
        self.valueWidget = qt.QWidget()
        valueLayout = qt.QHBoxLayout()
        valueLayout.addWidget(self.valueLabel)
        valueLayout.addWidget(self.valueThresholdSlider)
        self.valueWidget.setLayout(valueLayout)
        self.scriptedEffect.addOptionsWidget(self.valueWidget)

        self.hsvCheckBox = qt.QCheckBox("Use HSV instead of RGB")
        hsv_enable = self.DEFAULT_COLOR_MODE == "HSV"
        self.hsvCheckBox.setChecked(hsv_enable)  # enable HSV
        self.scriptedEffect.addOptionsWidget(self.hsvCheckBox)

        self.colormin = qt.QPushButton()
        self.scriptedEffect.addLabeledOptionsWidget("Minimum color: ", self.colormin)
        self.colormax = qt.QPushButton()
        self.scriptedEffect.addLabeledOptionsWidget("Maximum color: ", self.colormax)

        # Apply button
        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.objectName = self.__class__.__name__ + "Apply"
        self.applyButton.setToolTip("Apply segment as image mask. No undo operation available once applied.")
        self.scriptedEffect.addOptionsWidget(self.applyButton)

        self.enablePulsingCheckbox.connect("toggled(bool)", self.updateMRMLFromGUI)
        self.hsvCheckBox.connect("toggled(bool)", self.hsvOptionChanged)
        self.applyButton.connect("clicked()", self.onApply)

        # initializations
        self.selectColorMode(hsv_enable)

    def createCursor(self, widget):
        # Turn off effect-specific cursor for this effect
        return slicer.util.mainWindow().cursor

    def sourceVolumeNodeChanged(self):
        pass

    def layoutChanged(self):
        self.setupPreviewDisplay()

    def hsvOptionChanged(self, checked: bool):
        self.selectColorMode(checked)
        self.updateMRMLFromGUI()

    def selectColorMode(self, checked: bool = True) -> None:
        if checked:
            self.hueThresholdSlider.minimum = 0
            self.hueThresholdSlider.maximum = 720
            self.hueLabel.setText("H: ")

            self.saturationThresholdSlider.minimum = 0
            self.saturationThresholdSlider.maximum = 100
            self.saturationLabel.setText("S: ")

            self.valueThresholdSlider.minimum = 0
            self.valueThresholdSlider.maximum = 100
            self.valueLabel.setText("V: ")
        else:
            self.hueThresholdSlider.minimum = 0
            self.hueThresholdSlider.maximum = 255
            self.hueLabel.setText("R: ")

            self.saturationThresholdSlider.minimum = 0
            self.saturationThresholdSlider.maximum = 255
            self.saturationLabel.setText("G: ")

            self.valueThresholdSlider.minimum = 0
            self.valueThresholdSlider.maximum = 255
            self.valueLabel.setText("B: ")

    def onApply(self):
        try:
            # Get master volume image data
            import vtkSegmentationCorePython as vtkSegmentationCore

            sourceVolumeNode = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
            syncedImageData = self.scriptedEffect.sourceVolumeImageData()

            bufferImageData = slicer.vtkOrientedImageData()
            bufferImageData.DeepCopy(sourceVolumeNode.GetImageData())
            bufferImageData.SetOrigin(syncedImageData.GetOrigin())
            bufferImageData.SetSpacing(syncedImageData.GetSpacing())
            dirMat = vtk.vtkMatrix4x4()
            syncedImageData.GetDirectionMatrix(dirMat)
            bufferImageData.SetDirectionMatrix(dirMat)

            sourceImageData = bufferImageData

            # Get modifier labelmap
            modifierLabelmap = self.scriptedEffect.defaultModifierLabelmap()
            originalImageToWorldMatrix = vtk.vtkMatrix4x4()
            modifierLabelmap.GetImageToWorldMatrix(originalImageToWorldMatrix)

            # Get parameters
            R = (
                (
                    self.scriptedEffect.doubleParameter("ColorThresholdEffect.H.min"),
                    self.scriptedEffect.doubleParameter("ColorThresholdEffect.H.max"),
                ),
                (
                    self.scriptedEffect.doubleParameter("ColorThresholdEffect.S.min"),
                    self.scriptedEffect.doubleParameter("ColorThresholdEffect.S.max"),
                ),
                (
                    self.scriptedEffect.doubleParameter("ColorThresholdEffect.V.min"),
                    self.scriptedEffect.doubleParameter("ColorThresholdEffect.V.max"),
                ),
            )

            R = np.array(R)

            self.scriptedEffect.saveStateForUndo()

            # Perform thresholding
            # thresh = vtk.vtkImageThreshold()
            # thresh.SetInputData(sourceImageData)
            # thresh.ThresholdBetween(R[0][0], R[0][1])
            # thresh.SetInValue(1)
            # thresh.SetOutValue(0)
            # thresh.SetOutputScalarType(modifierLabelmap.GetScalarType())
            # thresh.Update()
            # modifierLabelmap.DeepCopy(thresh.GetOutput())

            rows, cols, _ = sourceImageData.GetDimensions()

            if self.hsvCheckBox.isChecked():
                converter = vtk.vtkImageRGBToHSV()
                converter.SetInputData(sourceImageData)
                converter.Update()
                sourceImageData = converter.GetOutput()

                # Convert all intervals for 0 to 255
                # if the maximum normalized to [0,2pi] is greater or equal than the minimum,
                # it doesnt matter, the user wants it all. So use let the maximum be big
                if (R[0][0] > 361) or ((R[0][1] > 361) and ((R[0][1] % 361) < R[0][0])):
                    R[0][1] = (R[0][1] % 361) * 0.7084
                R[0][0] = (R[0][0] % 361) * 0.7084
                # H

                R[1][0] *= 2.551
                R[1][1] *= 2.551  # S
                R[2][0] *= 2.551
                R[2][1] *= 2.551  # V

            sc = sourceImageData.GetPointData().GetScalars()
            a = vn.vtk_to_numpy(sc)
            arr = a.reshape(rows, cols, -1)

            # Perform thresholding
            # H is circular, if the minimum is greater than maximum, use or instead of and
            if R[0][0] > R[0][1]:
                red_range = np.logical_or(R[0][0] <= arr[:, :, 0], arr[:, :, 0] <= R[0][1])
            else:
                red_range = np.logical_and(R[0][0] <= arr[:, :, 0], arr[:, :, 0] <= R[0][1])
            green_range = np.logical_and(R[1][0] <= arr[..., 1], arr[..., 1] <= R[1][1])
            blue_range = np.logical_and(R[2][0] <= arr[..., 2], arr[..., 2] <= R[2][1])
            valid_range = red_range & green_range & blue_range

            maskArray = np.zeros((arr.shape[0], arr.shape[1], 1), dtype=np.uint8)
            maskArray[valid_range] = 1

            maskImage = vtk.vtkImageData()
            maskImage.SetDimensions(rows, cols, 1)
            maskImage.SetSpacing(sourceImageData.GetSpacing())
            maskImage.SetOrigin(sourceImageData.GetOrigin())

            maskData = vn.numpy_to_vtk(num_array=maskArray.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
            maskData.SetNumberOfComponents(1)
            maskImage.GetPointData().SetScalars(maskData)

            modifierLabelmap.DeepCopy(maskImage)

        except IndexError as ier:
            logging.error("apply: Failed to threshold master volume! Cause: " + repr(ier))
            pass

        # Apply changes
        self.scriptedEffect.modifySelectedSegmentByLabelmap(
            modifierLabelmap,
            slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet,
        )

        # De-select effect
        self.scriptedEffect.selectEffect("")

    def onThresholdValuesChanged(self, cmin, cmax):
        self.updateMRMLFromGUI()

    def updateGUIFromMRML(self):
        sliders = [
            self.hueThresholdSlider,
            self.saturationThresholdSlider,
            self.valueThresholdSlider,
        ]
        for axis, thresholdSlider in zip(self.HSV_COLOR_AXES, sliders):
            thresholdSlider.blockSignals(True)
            thresholdSlider.setMinimumValue(self.scriptedEffect.doubleParameter(f"ColorThresholdEffect.{axis}.min"))
            thresholdSlider.setMaximumValue(self.scriptedEffect.doubleParameter(f"ColorThresholdEffect.{axis}.max"))
            thresholdSlider.blockSignals(False)

        # self.hsvCheckBox.blockSignals(True)
        # hsv_mode = self.scriptedEffect.integerParameter("ColorThresholdEffect.mode") == 1
        # self.hsvCheckBox.setChecked(hsv_mode)
        # self.hsvCheckBox.blockSignals(False)

        # self.hsvOptionChanged(hsv_mode)

    def updateMRMLFromGUI(self):
        with slicer.util.NodeModify(self.scriptedEffect.parameterSetNode()):
            sliders = [
                self.hueThresholdSlider,
                self.saturationThresholdSlider,
                self.valueThresholdSlider,
            ]
            for axis, thresholdSlider in zip(self.HSV_COLOR_AXES, sliders):
                self.scriptedEffect.setParameter(f"ColorThresholdEffect.{axis}.min", thresholdSlider.minimumValue)
                self.scriptedEffect.setParameter(f"ColorThresholdEffect.{axis}.max", thresholdSlider.maximumValue)

            self.scriptedEffect.setParameter(
                "ColorThresholdEffect.mode", "HSV" if self.hsvCheckBox.isChecked() else "RGB"
            )
            self.scriptedEffect.setParameter("ColorThresholdEffect.pulse", int(self.enablePulsingCheckbox.isChecked()))

    def _getColor(self):
        color = [0.5, 0.5, 0.5]
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("The segment editor node is not available.")
            return color

        # Get color of edited segment
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

        # Make sure we keep the currently selected segment hidden (the user may have changed selection)
        if segmentID != self.previewedSegmentID:
            self.setCurrentSegmentTransparent()

        # Change color hue slightly to make it easier to distinguish filled regions from preview
        r, g, b = segmentationNode.GetSegmentation().GetSegment(segmentID).GetColor()
        import colorsys

        colorHsv = colorsys.rgb_to_hsv(r, g, b)
        return colorsys.hsv_to_rgb((colorHsv[0] + 0.2) % 1.0, colorHsv[1], colorHsv[2])

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

        R = (
            (
                self.scriptedEffect.doubleParameter("ColorThresholdEffect.H.min"),
                self.scriptedEffect.doubleParameter("ColorThresholdEffect.H.max"),
            ),
            (
                self.scriptedEffect.doubleParameter("ColorThresholdEffect.S.min"),
                self.scriptedEffect.doubleParameter("ColorThresholdEffect.S.max"),
            ),
            (
                self.scriptedEffect.doubleParameter("ColorThresholdEffect.V.min"),
                self.scriptedEffect.doubleParameter("ColorThresholdEffect.V.max"),
            ),
        )

        hsv_enabled = self.scriptedEffect.parameter("ColorThresholdEffect.mode") == "HSV"

        pulse_enabled = self.scriptedEffect.integerParameter("ColorThresholdEffect.pulse")
        #
        # make a lookup table where inside the threshold is opaque and colored
        # by the label color, while the background is transparent (black)
        # - apply the threshold operation to the currently visible background
        #   (output of the layer logic's vtkImageReslice instance)
        #
        if pulse_enabled > 0:
            opacity = 0.5 + self.previewState / (2.0 * self.previewSteps)
        else:
            opacity = 1.0

        R = np.array(R)
        R2 = np.copy(R)

        r, g, b = self._getColor()
        # Convert all intervals for 0 to 255 for vtk
        if hsv_enabled:
            # if the hue maximum - minimun is greater than the range,
            # it doesnt matter, the user wants it all.
            if R[0][1] - R[0][0] >= 360:
                R[0][0] = 0
                R[0][1] = 360

            R[0][1] = (R[0][1] % 361) * 0.7084
            R[0][0] = (R[0][0] % 361) * 0.7084
            # H

            R[1][0] *= 2.551
            R[1][1] *= 2.551  # S
            R[2][0] *= 2.551
            R[2][1] *= 2.551  # V

            # set the color indicators
            # Qt wants it in [0,255] for SV and in [0,360] for H
            R2[0][0] = R2[0][0] % 360
            R2[0][1] = R2[0][1] % 360  # H
            R2[1][0] *= 2.55
            R2[1][1] *= 2.55  # S
            R2[2][0] *= 2.55
            R2[2][1] *= 2.55  # V

            self.colormin.setStyleSheet(
                "background-color: hsv("
                + str(R2[0][0])
                + ","
                + str(R2[1][0])
                + ","
                + str(R2[2][0])
                + "); border: none;"
            )
            if R[0][1] > 360:
                self.colormax.setStyleSheet(
                    "background-color: hsv(359," + str(R2[1][1]) + "," + str(R2[2][1]) + "); border: none;"
                )
            else:
                self.colormax.setStyleSheet(
                    "background-color: hsv("
                    + str(R2[0][1])
                    + ","
                    + str(R2[1][1])
                    + ","
                    + str(R2[2][1])
                    + "); border: none;"
                )
        else:
            self.colormin.setStyleSheet(
                "background-color: rgb(" + str(R[0][0]) + "," + str(R[1][0]) + "," + str(R[2][0]) + "); border: none;"
            )
            self.colormax.setStyleSheet(
                "background-color: rgb(" + str(R[0][1]) + "," + str(R[1][1]) + "," + str(R[2][1]) + "); border: none;"
            )

        # Set values to pipelines
        for p, sliceWidget in enumerate(self.previewPipelines):
            pipeline = self.previewPipelines[sliceWidget]
            pipeline.lookupTable.SetTableValue(1, r, g, b, opacity)
            layerLogic = self.getSourceVolumeLayerLogic(sliceWidget)

            masterImage = layerLogic.GetReslice().GetOutput()

            rows, cols, rgb = masterImage.GetDimensions()

            # ignore empty slice views
            if rows == 0 or cols == 0:
                continue

            # convert image to hsv if it is the case
            if hsv_enabled:
                converter = vtk.vtkImageRGBToHSV()
                converter.SetInputData(masterImage)
                converter.Update()
                masterImage = converter.GetOutput()

            sc = masterImage.GetPointData().GetScalars()
            a = vn.vtk_to_numpy(sc)
            arr = a.reshape(rows, cols, -1)

            if arr.shape[-1] != 3:  # check for RGB images
                continue

            # H is circular, if the minimum is greater than maximum, use or instead of and
            if R[0][0] > R[0][1]:
                red_range = np.logical_or(R[0][0] <= arr[:, :, 0], arr[:, :, 0] <= R[0][1])
            else:
                red_range = np.logical_and(R[0][0] <= arr[:, :, 0], arr[:, :, 0] <= R[0][1])
            green_range = np.logical_and(R[1][0] <= arr[:, :, 1], arr[:, :, 1] <= R[1][1])
            blue_range = np.logical_and(R[2][0] <= arr[:, :, 2], arr[:, :, 2] <= R[2][1])
            valid_range = red_range & green_range & blue_range

            maskArray = np.zeros((arr.shape[0], arr.shape[1], 1), dtype=np.uint8)
            maskArray[valid_range, 0] = 1

            maskImage = vtk.vtkImageData()

            maskImage.SetDimensions(masterImage.GetDimensions())
            maskImage.SetSpacing(masterImage.GetSpacing())
            maskImage.SetOrigin(masterImage.GetOrigin())

            maskData = vn.numpy_to_vtk(num_array=maskArray.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
            maskData.SetNumberOfComponents(1)
            maskImage.GetPointData().SetScalars(maskData)

            pipeline.colorMapper.SetInputData(maskImage)
            # pipeline.thresholdFilter.SetInputConnection(layerLogic.GetReslice().GetOutputPort())
            # pipeline.thresholdFilter.ThresholdBetween(R[2][0], R[2][1])
            pipeline.actor.VisibilityOn()
            sliceWidget.sliceView().scheduleRender()

        self.previewState += self.previewStep
        if self.previewState >= self.previewSteps:
            self.previewStep = -1
        if self.previewState <= 0:
            self.previewStep = 1

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


# MINIMUM_DIAMETER_MM_PARAMETER_NAME = "MinimumDiameterMm"
# FEATURE_SIZE_MM_PARAMETER_NAME = "FeatureSizeMm"
# SEGMENTATION_ALGORITHM_PARAMETER_NAME = "SegmentationAlgorithm"
# SEGMENTATION_ALGORITHM_MASKING = "Masking"
# SEGMENTATION_ALGORITHM_GROWCUT = "GrowCut"
# SEGMENTATION_ALGORITHM_WATERSHED = "WaterShed"
#
# BACKGROUND_VALUE = 0
# LABEL_VALUE = 1
# SELECTED_ISLAND_VALUE = 2
# OUTSIDE_THRESHOLD_VALUE = 3
