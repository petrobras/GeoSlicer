# SegmentEditorSmoothingEffect.py
# Copied and modified from 3D Slicer


import ctk
import qt
import vtk
import slicer
import logging
import numpy as np
import os
import traceback

from ltrace.slicer.helpers import getSourceVolume
from pathlib import Path
from SegmentEditorEffects import *
from scipy import ndimage
from slicer.i18n import tr as _
from vtk.util import numpy_support


def _batch_sum_conv_3d(array, kernel_size):
    assert array.ndim == 4
    maxValue = kernel_size[0] * kernel_size[1] * kernel_size[2]
    if maxValue <= 255:
        array = array.astype(np.uint8)
    elif maxValue <= 65535:
        array = array.astype(np.uint16)
    else:
        array = array.astype(np.uint32)

    kernel_x = np.ones(kernel_size[2], dtype=array.dtype)
    kernel_y = np.ones(kernel_size[1], dtype=array.dtype)
    kernel_z = np.ones(kernel_size[0], dtype=array.dtype) if kernel_size[0] > 1 else None

    array = ndimage.convolve1d(array, kernel_x, axis=1, mode="reflect")
    array = ndimage.convolve1d(array, kernel_y, axis=2, mode="reflect")
    if kernel_z is not None:
        array = ndimage.convolve1d(array, kernel_z, axis=3, mode="reflect")

    return array


class SegmentEditorSmoothingEffect(AbstractScriptedSegmentEditorPaintEffect):
    """SmoothingEffect is an Effect that smoothes a selected segment"""

    def __init__(self, scriptedEffect):
        AbstractScriptedSegmentEditorPaintEffect.__init__(self, scriptedEffect)
        scriptedEffect.name = "Smoothing"
        scriptedEffect.title = _("Smoothing")

    def clone(self):
        import qSlicerSegmentationsEditorEffectsPythonQt as effects

        clonedEffect = effects.qSlicerSegmentEditorScriptedPaintEffect(None)
        clonedEffect.setPythonSource(__file__.replace("\\", "/"))
        return clonedEffect

    def icon(self):
        iconPath = Path(__file__).parent.parent / "Resources" / "Icons" / "Smoothing.png"
        if iconPath.exists():
            return qt.QIcon(str(iconPath))
        return qt.QIcon()

    def helpText(self):
        return """<html>Make segment boundaries smoother<br> by removing extrusions and filling small holes. The effect can be either applied locally
(by painting in viewers) or to the whole segment (by clicking Apply button). Available methods:<p>
<ul style="margin: 0">
<li><b>Median:</b> removes small details while keeps smooth contours mostly unchanged. Applied to one or more segments at once, preserving segment boundaries.</li>
<li><b>Opening:</b> removes extrusions smaller than the specified kernel size. Applied to selected segment only.</li>
<li><b>Fill holes:</b> fills contiguous empty spaces smaller than the specified kernel size.</li>
<li><b>Gaussian:</b> smoothes all contours, tends to shrink the segment. Applied to selected segment only.</li>
</ul><p></html>"""

    def setupOptionsFrame(self):
        self.methodSelectorComboBox = qt.QComboBox()
        self.methodSelectorComboBox.addItem("Median", MEDIAN)
        self.methodSelectorComboBox.addItem("Opening (remove extrusions)", MORPHOLOGICAL_OPENING)
        self.methodSelectorComboBox.addItem("Fill holes", MORPHOLOGICAL_CLOSING)
        self.methodSelectorComboBox.addItem("Gaussian", GAUSSIAN)
        # self.methodSelectorComboBox.addItem("Joint smoothing", JOINT_TAUBIN)
        self.scriptedEffect.addLabeledOptionsWidget("Smoothing method:", self.methodSelectorComboBox)

        self.kernelSizeMMSpinBox = slicer.qMRMLSpinBox()
        self.kernelSizeMMSpinBox.setMRMLScene(slicer.mrmlScene)
        self.kernelSizeMMSpinBox.setToolTip(
            "Diameter of the neighborhood that will be considered around each voxel. Higher value makes smoothing stronger (more details are suppressed)."
        )
        self.kernelSizeMMSpinBox.quantity = "length"
        self.kernelSizeMMSpinBox.minimum = 0.0
        self.kernelSizeMMSpinBox.value = 3.0
        self.kernelSizeMMSpinBox.singleStep = 1.0

        self.kernelSizePixel = qt.QLabel()
        self.kernelSizePixel.setToolTip(
            "Diameter of the neighborhood in pixel. Computed from the segment's spacing and the specified kernel size."
        )

        kernelSizeFrame = qt.QHBoxLayout()
        kernelSizeFrame.addWidget(self.kernelSizeMMSpinBox)
        kernelSizeFrame.addWidget(self.kernelSizePixel)
        self.kernelSizeMMLabel = self.scriptedEffect.addLabeledOptionsWidget("Kernel size:", kernelSizeFrame)

        self.gaussianStandardDeviationMMSpinBox = slicer.qMRMLSpinBox()
        self.gaussianStandardDeviationMMSpinBox.setMRMLScene(slicer.mrmlScene)
        self.gaussianStandardDeviationMMSpinBox.setToolTip(
            "Standard deviation of the Gaussian smoothing filter coefficients. Higher value makes smoothing stronger (more details are suppressed)."
        )
        self.gaussianStandardDeviationMMSpinBox.quantity = "length"
        self.gaussianStandardDeviationMMSpinBox.value = 3.0
        self.gaussianStandardDeviationMMSpinBox.singleStep = 1.0
        self.gaussianStandardDeviationMMLabel = self.scriptedEffect.addLabeledOptionsWidget(
            "Standard deviation:", self.gaussianStandardDeviationMMSpinBox
        )

        self.jointTaubinSmoothingFactorSlider = ctk.ctkSliderWidget()
        self.jointTaubinSmoothingFactorSlider.setToolTip("Higher value means stronger smoothing.")
        self.jointTaubinSmoothingFactorSlider.minimum = 0.01
        self.jointTaubinSmoothingFactorSlider.maximum = 1.0
        self.jointTaubinSmoothingFactorSlider.value = 0.5
        self.jointTaubinSmoothingFactorSlider.singleStep = 0.01
        self.jointTaubinSmoothingFactorSlider.pageStep = 0.1
        self.jointTaubinSmoothingFactorLabel = self.scriptedEffect.addLabeledOptionsWidget(
            "Smoothing factor:", self.jointTaubinSmoothingFactorSlider
        )

        self.applyToAllVisibleSegmentsCheckBox = qt.QCheckBox()
        self.applyToAllVisibleSegmentsCheckBox.setToolTip(
            "Apply smoothing effect to all visible segments in this segmentation node. \
                                                      This operation may take a while."
        )
        self.applyToAllVisibleSegmentsCheckBox.objectName = self.__class__.__name__ + "ApplyToAllVisibleSegments"
        self.applyToAllVisibleSegmentsLabel = self.scriptedEffect.addLabeledOptionsWidget(
            "Apply to visible segments:", self.applyToAllVisibleSegmentsCheckBox
        )

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.objectName = self.__class__.__name__ + "Apply"
        self.applyButton.setToolTip("Apply smoothing to selected segment")
        self.scriptedEffect.addOptionsWidget(self.applyButton)

        self.methodSelectorComboBox.currentIndexChanged.connect(self.updateMRMLFromGUI)
        self.kernelSizeMMSpinBox.valueChanged.connect(self.updateMRMLFromGUI)
        self.gaussianStandardDeviationMMSpinBox.valueChanged.connect(self.updateMRMLFromGUI)
        self.jointTaubinSmoothingFactorSlider.valueChanged.connect(self.updateMRMLFromGUI)
        self.applyToAllVisibleSegmentsCheckBox.stateChanged.connect(self.updateMRMLFromGUI)
        self.applyButton.clicked.connect(self.onApplyButtonClicked)

        # Customize smoothing brush
        self.scriptedEffect.setColorSmudgeCheckboxVisible(False)
        self.paintOptionsGroupBox = ctk.ctkCollapsibleGroupBox()
        self.paintOptionsGroupBox.setTitle("Smoothing brush options")
        self.paintOptionsGroupBox.setLayout(qt.QVBoxLayout())
        self.paintOptionsGroupBox.layout().addWidget(self.scriptedEffect.paintOptionsFrame())
        self.paintOptionsGroupBox.collapsed = True
        self.scriptedEffect.addOptionsWidget(self.paintOptionsGroupBox)

    def setMRMLDefaults(self):
        self.scriptedEffect.setParameterDefault("ApplyToAllVisibleSegments", 0)
        self.scriptedEffect.setParameterDefault("GaussianStandardDeviationMm", 3)
        self.scriptedEffect.setParameterDefault("JointTaubinSmoothingFactor", 0.5)
        self.scriptedEffect.setParameterDefault("KernelSizeMm", 3)
        self.scriptedEffect.setParameterDefault("SmoothingMethod", MEDIAN)

    def updateParameterWidgetsVisibility(self):
        methodIndex = self.methodSelectorComboBox.currentIndex
        smoothingMethod = self.methodSelectorComboBox.itemData(methodIndex)
        morphologicalMethod = (
            smoothingMethod == MEDIAN
            or smoothingMethod == MORPHOLOGICAL_OPENING
            or smoothingMethod == MORPHOLOGICAL_CLOSING
        )
        self.kernelSizeMMLabel.setVisible(morphologicalMethod)
        self.kernelSizeMMSpinBox.setVisible(morphologicalMethod)
        self.kernelSizePixel.setVisible(morphologicalMethod)
        self.gaussianStandardDeviationMMLabel.setVisible(smoothingMethod == GAUSSIAN)
        self.gaussianStandardDeviationMMSpinBox.setVisible(smoothingMethod == GAUSSIAN)
        self.jointTaubinSmoothingFactorLabel.setVisible(smoothingMethod == JOINT_TAUBIN)
        self.jointTaubinSmoothingFactorSlider.setVisible(smoothingMethod == JOINT_TAUBIN)
        self.applyToAllVisibleSegmentsLabel.setVisible(smoothingMethod == MEDIAN)
        self.applyToAllVisibleSegmentsCheckBox.setVisible(smoothingMethod == MEDIAN)

    def getKernelSizePixel(self):
        selectedSegmentLabelmapSpacing = [1.0, 1.0, 1.0]
        selectedSegmentLabelmapDimensions = None
        selectedSegmentLabelmap = self.scriptedEffect.selectedSegmentLabelmap()
        if selectedSegmentLabelmap:
            selectedSegmentLabelmapSpacing = selectedSegmentLabelmap.GetSpacing()
            selectedSegmentLabelmapDimensions = selectedSegmentLabelmap.GetDimensions()

        # size rounded to nearest odd number. If kernel size is even then image gets shifted.
        kernelSizeMM = self.scriptedEffect.doubleParameter("KernelSizeMm")
        kernelSizePixel = [
            int(round((kernelSizeMM / selectedSegmentLabelmapSpacing[componentIndex] + 1) / 2) * 2 - 1)
            for componentIndex in range(3)
        ]
        if selectedSegmentLabelmapDimensions and all(dim > 0 for dim in selectedSegmentLabelmapDimensions):
            # Subtract 1 if dimension is even
            dims = [dim - 1 + dim % 2 for dim in selectedSegmentLabelmapDimensions]
            kernelSizePixel = [min(kernelSize, dim) for kernelSize, dim in zip(kernelSizePixel, dims)]
        return kernelSizePixel

    def updateGUIFromMRML(self):
        methodIndex = self.methodSelectorComboBox.findData(self.scriptedEffect.parameter("SmoothingMethod"))
        wasBlocked = self.methodSelectorComboBox.blockSignals(True)
        self.methodSelectorComboBox.setCurrentIndex(methodIndex)
        self.methodSelectorComboBox.blockSignals(wasBlocked)

        wasBlocked = self.kernelSizeMMSpinBox.blockSignals(True)
        self.setWidgetMinMaxStepFromImageSpacing(
            self.kernelSizeMMSpinBox, self.scriptedEffect.selectedSegmentLabelmap()
        )
        self.kernelSizeMMSpinBox.value = self.scriptedEffect.doubleParameter("KernelSizeMm")
        self.kernelSizeMMSpinBox.blockSignals(wasBlocked)
        kernelSizePixel = self.getKernelSizePixel()
        self.kernelSizePixel.text = f"{kernelSizePixel[0]}x{kernelSizePixel[1]}x{kernelSizePixel[2]} pixel"

        wasBlocked = self.gaussianStandardDeviationMMSpinBox.blockSignals(True)
        self.setWidgetMinMaxStepFromImageSpacing(
            self.gaussianStandardDeviationMMSpinBox, self.scriptedEffect.selectedSegmentLabelmap()
        )
        self.gaussianStandardDeviationMMSpinBox.value = self.scriptedEffect.doubleParameter(
            "GaussianStandardDeviationMm"
        )
        self.gaussianStandardDeviationMMSpinBox.blockSignals(wasBlocked)

        wasBlocked = self.jointTaubinSmoothingFactorSlider.blockSignals(True)
        self.jointTaubinSmoothingFactorSlider.value = self.scriptedEffect.doubleParameter("JointTaubinSmoothingFactor")
        self.jointTaubinSmoothingFactorSlider.blockSignals(wasBlocked)

        applyToAllVisibleSegments = (
            qt.Qt.Unchecked if self.scriptedEffect.integerParameter("ApplyToAllVisibleSegments") == 0 else qt.Qt.Checked
        )
        wasBlocked = self.applyToAllVisibleSegmentsCheckBox.blockSignals(True)
        self.applyToAllVisibleSegmentsCheckBox.setCheckState(applyToAllVisibleSegments)
        self.applyToAllVisibleSegmentsCheckBox.blockSignals(wasBlocked)

        self.updateParameterWidgetsVisibility()

    def onApplyButtonClicked(self, state):
        self.onApply()

    def updateMRMLFromGUI(self, *args, **kwargs):
        methodIndex = self.methodSelectorComboBox.currentIndex
        smoothingMethod = self.methodSelectorComboBox.itemData(methodIndex)
        self.scriptedEffect.setParameter("SmoothingMethod", smoothingMethod)
        self.scriptedEffect.setParameter("KernelSizeMm", self.kernelSizeMMSpinBox.value)
        self.scriptedEffect.setParameter("GaussianStandardDeviationMm", self.gaussianStandardDeviationMMSpinBox.value)
        self.scriptedEffect.setParameter("JointTaubinSmoothingFactor", self.jointTaubinSmoothingFactorSlider.value)
        applyToAllVisibleSegments = 1 if self.applyToAllVisibleSegmentsCheckBox.isChecked() else 0
        self.scriptedEffect.setParameter("ApplyToAllVisibleSegments", applyToAllVisibleSegments)

        self.updateParameterWidgetsVisibility()

    #
    # Effect specific methods (the above ones are the API methods to override)
    #

    def showStatusMessage(self, msg, timeoutMsec=500):
        slicer.util.showStatusMessage(msg, timeoutMsec)
        slicer.app.processEvents()

    def onApply(self, maskImage=None, maskExtent=None):
        """maskImage: contains nonzero where smoothing will be applied"""
        smoothingMethod = self.scriptedEffect.parameter("SmoothingMethod")

        if smoothingMethod != JOINT_TAUBIN:
            # Make sure the user wants to do the operation, even if the segment is not visible
            if not self.scriptedEffect.confirmCurrentSegmentVisible():
                return

        try:
            # This can be a long operation - indicate it to the user
            qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
            self.scriptedEffect.saveStateForUndo()
            if self.scriptedEffect.parameterSetNode() is None:
                slicer.util.errorDisplay("Failed to apply the effect. The selected node is not valid.")
                return
            if smoothingMethod == JOINT_TAUBIN:
                self.smoothMultipleSegments(maskImage, maskExtent)
            else:
                self.smoothSelectedSegment(maskImage, maskExtent)
        finally:
            qt.QApplication.restoreOverrideCursor()

    def clipImage(self, inputImage, maskExtent, margin):
        clipper = vtk.vtkImageClip()
        clipper.SetOutputWholeExtent(
            maskExtent[0] - margin[0],
            maskExtent[1] + margin[0],
            maskExtent[2] - margin[1],
            maskExtent[3] + margin[1],
            maskExtent[4] - margin[2],
            maskExtent[5] + margin[2],
        )
        clipper.SetInputData(inputImage)
        clipper.SetClipData(True)
        clipper.Update()
        clippedImage = slicer.vtkOrientedImageData()
        clippedImage.ShallowCopy(clipper.GetOutput())
        clippedImage.CopyDirections(inputImage)
        return clippedImage

    def modifySelectedSegmentByLabelmap(
        self, smoothedImage, selectedSegmentLabelmap, modifierLabelmap, maskImage, maskExtent
    ):
        if maskImage:
            smoothedClippedSelectedSegmentLabelmap = slicer.vtkOrientedImageData()
            smoothedClippedSelectedSegmentLabelmap.ShallowCopy(smoothedImage)
            smoothedClippedSelectedSegmentLabelmap.CopyDirections(modifierLabelmap)

            # fill smoothed selected segment outside the painted region to 1 so that in the end the image is not modified by OPERATION_MINIMUM
            fillValue = 1.0
            slicer.vtkOrientedImageDataResample.ApplyImageMask(
                smoothedClippedSelectedSegmentLabelmap, maskImage, fillValue, False
            )
            # set original segment labelmap outside painted region, solid 1 inside painted region
            slicer.vtkOrientedImageDataResample.ModifyImage(
                maskImage, selectedSegmentLabelmap, slicer.vtkOrientedImageDataResample.OPERATION_MAXIMUM
            )
            slicer.vtkOrientedImageDataResample.ModifyImage(
                maskImage, smoothedClippedSelectedSegmentLabelmap, slicer.vtkOrientedImageDataResample.OPERATION_MINIMUM
            )

            updateExtent = [0, -1, 0, -1, 0, -1]
            modifierExtent = modifierLabelmap.GetExtent()
            for i in range(3):
                updateExtent[2 * i] = min(maskExtent[2 * i], modifierExtent[2 * i])
                updateExtent[2 * i + 1] = max(maskExtent[2 * i + 1], modifierExtent[2 * i + 1])

            self.scriptedEffect.modifySelectedSegmentByLabelmap(
                maskImage, slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet, updateExtent
            )
        else:
            modifierLabelmap.DeepCopy(smoothedImage)
            self.scriptedEffect.modifySelectedSegmentByLabelmap(
                modifierLabelmap, slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet
            )

    def getInvertedBinaryLabelmap(self, modifierLabelmap):
        fillValue = 1
        eraseValue = 0
        inverter = vtk.vtkImageThreshold()
        inverter.SetInputData(modifierLabelmap)
        inverter.SetInValue(fillValue)
        inverter.SetOutValue(eraseValue)
        inverter.ReplaceInOn()
        inverter.ThresholdByLower(0)
        inverter.SetOutputScalarType(vtk.VTK_UNSIGNED_CHAR)
        inverter.Update()

        invertedModifierLabelmap = slicer.vtkOrientedImageData()
        invertedModifierLabelmap.ShallowCopy(inverter.GetOutput())
        imageToWorldMatrix = vtk.vtkMatrix4x4()
        modifierLabelmap.GetImageToWorldMatrix(imageToWorldMatrix)
        invertedModifierLabelmap.SetGeometryFromImageToWorldMatrix(imageToWorldMatrix)
        return invertedModifierLabelmap

    def smoothSelectedSegment(self, maskImage=None, maskExtent=None):
        try:
            # Get modifier labelmap
            modifierLabelmap = self.scriptedEffect.defaultModifierLabelmap()
            selectedSegmentLabelmap = self.scriptedEffect.selectedSegmentLabelmap()

            smoothingMethod = self.scriptedEffect.parameter("SmoothingMethod")

            if smoothingMethod == GAUSSIAN:
                maxValue = 255
                radiusFactor = 2.0
                standardDeviationMM = self.scriptedEffect.doubleParameter("GaussianStandardDeviationMm")
                spacing = modifierLabelmap.GetSpacing()
                standardDeviationPixel = [1.0, 1.0, 1.0]
                radiusPixel = [3, 3, 3]
                for idx in range(3):
                    standardDeviationPixel[idx] = standardDeviationMM / spacing[idx]
                    radiusPixel[idx] = int(standardDeviationPixel[idx] * radiusFactor) + 1
                if maskExtent:
                    clippedSelectedSegmentLabelmap = self.clipImage(selectedSegmentLabelmap, maskExtent, radiusPixel)
                else:
                    clippedSelectedSegmentLabelmap = selectedSegmentLabelmap

                thresh = vtk.vtkImageThreshold()
                thresh.SetInputData(clippedSelectedSegmentLabelmap)
                thresh.ThresholdByLower(0)
                thresh.SetInValue(0)
                thresh.SetOutValue(maxValue)
                thresh.SetOutputScalarType(vtk.VTK_UNSIGNED_CHAR)

                gaussianFilter = vtk.vtkImageGaussianSmooth()
                gaussianFilter.SetInputConnection(thresh.GetOutputPort())
                gaussianFilter.SetStandardDeviation(*standardDeviationPixel)
                gaussianFilter.SetRadiusFactor(radiusFactor)

                thresh2 = vtk.vtkImageThreshold()
                thresh2.SetInputConnection(gaussianFilter.GetOutputPort())
                thresh2.ThresholdByUpper(int(maxValue / 2))
                thresh2.SetInValue(1)
                thresh2.SetOutValue(0)
                thresh2.SetOutputScalarType(selectedSegmentLabelmap.GetScalarType())
                thresh2.Update()

                self.modifySelectedSegmentByLabelmap(
                    thresh2.GetOutput(), selectedSegmentLabelmap, modifierLabelmap, maskImage, maskExtent
                )

            else:
                # size rounded to nearest odd number. If kernel size is even then image gets shifted.
                kernelSizePixel = self.getKernelSizePixel()
                useVtk = True

                if maskExtent:
                    clippedSelectedSegmentLabelmap = self.clipImage(
                        selectedSegmentLabelmap, maskExtent, kernelSizePixel
                    )
                else:
                    clippedSelectedSegmentLabelmap = selectedSegmentLabelmap

                if smoothingMethod == MEDIAN:
                    applyToVisible = (
                        int(self.scriptedEffect.parameter("ApplyToAllVisibleSegments")) != 0
                        if self.scriptedEffect.parameter("ApplyToAllVisibleSegments")
                        else False
                    )
                    if maskExtent:
                        smoothingFilter = vtk.vtkImageMedian3D()
                        smoothingFilter.SetInputData(clippedSelectedSegmentLabelmap)
                    elif applyToVisible:
                        useVtk = False

                        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
                        visibleSegmentIds = vtk.vtkStringArray()
                        segmentationNode.GetDisplayNode().GetVisibleSegmentIDs(visibleSegmentIds)

                        nSegments = visibleSegmentIds.GetNumberOfValues()
                        if nSegments == 0:
                            return

                        segmentIds = [visibleSegmentIds.GetValue(i) for i in range(nSegments)]
                        firstSegment = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentIds[0]) > 0

                        batches = np.zeros((nSegments + 1, *firstSegment.shape), dtype=bool)
                        batches[0] = ~firstSegment
                        batches[1] = firstSegment

                        for i, segmentId in enumerate(segmentIds[1:]):
                            array = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId) > 0
                            # 0 is background, 1 was already set
                            batches[i + 2] = array
                            batches[0] &= ~array
                        batches = _batch_sum_conv_3d(batches, kernel_size=kernelSizePixel)
                        labelmap_array = np.argmax(batches, axis=0)

                        for i, segmentId in enumerate(segmentIds):
                            array = (labelmap_array == (i + 1)).astype(np.uint8)
                            selectedSegmentLabelmap.GetPointData().SetScalars(numpy_support.numpy_to_vtk(array.ravel()))
                            self.scriptedEffect.modifySegmentByLabelmap(
                                segmentationNode,
                                segmentId,
                                selectedSegmentLabelmap,
                                slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet,
                            )
                    else:
                        useVtk = False
                        scalars = selectedSegmentLabelmap.GetPointData().GetScalars()
                        dims = selectedSegmentLabelmap.GetDimensions()[::-1]  # Fortran to C order
                        array = numpy_support.vtk_to_numpy(scalars).reshape(dims)
                        array = array > 0

                        array = _batch_sum_conv_3d(array[np.newaxis, ...], kernel_size=kernelSizePixel)
                        maxValue = kernelSizePixel[0] * kernelSizePixel[1] * kernelSizePixel[2]
                        threshold = maxValue // 2
                        array = (array > threshold).astype(np.uint8)

                        selectedSegmentLabelmap.GetPointData().SetScalars(numpy_support.numpy_to_vtk(array.ravel()))
                        self.scriptedEffect.modifySelectedSegmentByLabelmap(
                            selectedSegmentLabelmap,
                            slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet,
                        )
                else:
                    # We need to know exactly the value of the segment voxels, apply threshold to make force the selected label value
                    labelValue = 1
                    backgroundValue = 0
                    thresh = vtk.vtkImageThreshold()
                    thresh.SetInputData(clippedSelectedSegmentLabelmap)
                    thresh.ThresholdByLower(0)
                    thresh.SetInValue(backgroundValue)
                    thresh.SetOutValue(labelValue)
                    thresh.SetOutputScalarType(clippedSelectedSegmentLabelmap.GetScalarType())

                    smoothingFilter = vtk.vtkImageOpenClose3D()
                    smoothingFilter.SetInputConnection(thresh.GetOutputPort())

                    if not maskImage and smoothingMethod == MORPHOLOGICAL_CLOSING:
                        # Invert + islands + invert pipeline
                        selectedSegmentLabelmap = self.scriptedEffect.selectedSegmentLabelmap()
                        originalLabelmap = slicer.vtkOrientedImageData()
                        originalLabelmap.ShallowCopy(selectedSegmentLabelmap)
                        invertedSelectedSegmentLabelmap = self.getInvertedBinaryLabelmap(originalLabelmap)
                        bypassMasking = True
                        self.scriptedEffect.modifySelectedSegmentByLabelmap(
                            invertedSelectedSegmentLabelmap,
                            slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet,
                            bypassMasking,
                        )

                        segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
                        segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
                        segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
                        segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)
                        segmentEditorNode.SetOverwriteMode(slicer.vtkMRMLSegmentEditorNode.OverwriteNone)

                        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
                        segment = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()
                        segmentEditorWidget.setSegmentationNode(segmentationNode)
                        segmentEditorWidget.setCurrentSegmentID(segment)

                        sourceVolumeNode = getSourceVolume(segmentationNode)
                        if sourceVolumeNode:
                            segmentEditorWidget.setSourceVolumeNode(sourceVolumeNode)

                        segmentEditorWidget.setActiveEffectByName("Islands")
                        effect = segmentEditorWidget.activeEffect()
                        effect.setParameter("Operation", REMOVE_SMALL_ISLANDS)
                        effect.setParameter("MinimumSize", kernelSizePixel[0] * kernelSizePixel[1] * kernelSizePixel[2])
                        effect.self().onApply()

                        slicer.mrmlScene.RemoveNode(segmentEditorNode)

                        selectedSegmentLabelmap = self.scriptedEffect.selectedSegmentLabelmap()
                        resultLabelmap = self.getInvertedBinaryLabelmap(selectedSegmentLabelmap)

                        # Selected segment was used as a buffer
                        # Now we restore it without masking and apply the result with masking
                        bypassMasking = True
                        self.scriptedEffect.modifySelectedSegmentByLabelmap(
                            originalLabelmap,
                            slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet,
                            bypassMasking,
                        )
                        bypassMasking = False
                        self.scriptedEffect.modifySelectedSegmentByLabelmap(
                            resultLabelmap,
                            slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet,
                            bypassMasking,
                        )
                        return
                    else:
                        if smoothingMethod == MORPHOLOGICAL_OPENING:
                            smoothingFilter.SetOpenValue(labelValue)
                            smoothingFilter.SetCloseValue(backgroundValue)
                        else:  # must be smoothingMethod == MORPHOLOGICAL_CLOSING:
                            smoothingFilter.SetOpenValue(backgroundValue)
                            smoothingFilter.SetCloseValue(labelValue)

                if useVtk:
                    smoothingFilter.SetKernelSize(kernelSizePixel[0], kernelSizePixel[1], kernelSizePixel[2])
                    smoothingFilter.Update()

                    self.modifySelectedSegmentByLabelmap(
                        smoothingFilter.GetOutput(), selectedSegmentLabelmap, modifierLabelmap, maskImage, maskExtent
                    )

        except Exception as error:
            logging.debug(f"Error: {error}. Traceback:\n{traceback.format_exc()}")

    def smoothMultipleSegments(self, maskImage=None, maskExtent=None):
        import vtkSegmentationCorePython as vtkSegmentationCore

        if self.scriptedEffect.parameterSetNode() is None:
            slicer.util.errorDisplay("Failed to apply smoothing. The selected node is not valid.")
            return

        self.showStatusMessage(f"Joint smoothing ...")
        # Generate merged labelmap of all visible segments
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        visibleSegmentIds = vtk.vtkStringArray()
        segmentationNode.GetDisplayNode().GetVisibleSegmentIDs(visibleSegmentIds)
        if visibleSegmentIds.GetNumberOfValues() == 0:
            logging.info("Smoothing operation skipped: there are no visible segments")
            return

        mergedImage = slicer.vtkOrientedImageData()
        if not segmentationNode.GenerateMergedLabelmapForAllSegments(
            mergedImage, vtkSegmentationCore.vtkSegmentation.EXTENT_UNION_OF_SEGMENTS_PADDED, None, visibleSegmentIds
        ):
            logging.error("Failed to apply smoothing: cannot get list of visible segments")
            return

        segmentLabelValues = []  # list of [segmentId, labelValue]
        for i in range(visibleSegmentIds.GetNumberOfValues()):
            segmentId = visibleSegmentIds.GetValue(i)
            segmentLabelValues.append([segmentId, i + 1])

        # Perform smoothing in voxel space
        ici = vtk.vtkImageChangeInformation()
        ici.SetInputData(mergedImage)
        ici.SetOutputSpacing(1, 1, 1)
        ici.SetOutputOrigin(0, 0, 0)

        # Convert labelmap to combined polydata
        # vtkDiscreteFlyingEdges3D cannot be used here, as in the output of that filter,
        # each labeled region is completely disconnected from neighboring regions, and
        # for joint smoothing it is essential for the points to move together.
        convertToPolyData = vtk.vtkDiscreteMarchingCubes()
        convertToPolyData.SetInputConnection(ici.GetOutputPort())
        convertToPolyData.SetNumberOfContours(len(segmentLabelValues))

        contourIndex = 0
        for segmentId, labelValue in segmentLabelValues:
            convertToPolyData.SetValue(contourIndex, labelValue)
            contourIndex += 1

        # Low-pass filtering using Taubin's method
        smoothingFactor = self.scriptedEffect.doubleParameter("JointTaubinSmoothingFactor")
        smoothingIterations = 100  # according to VTK documentation 10-20 iterations could be enough but we use a higher value to reduce chance of shrinking
        passBand = pow(10.0, -4.0 * smoothingFactor)  # gives a nice range of 1-0.0001 from a user input of 0-1
        smoother = vtk.vtkWindowedSincPolyDataFilter()
        smoother.SetInputConnection(convertToPolyData.GetOutputPort())
        smoother.SetNumberOfIterations(smoothingIterations)
        smoother.BoundarySmoothingOff()
        smoother.FeatureEdgeSmoothingOff()
        smoother.SetFeatureAngle(90.0)
        smoother.SetPassBand(passBand)
        smoother.NonManifoldSmoothingOn()
        smoother.NormalizeCoordinatesOn()

        # Extract a label
        threshold = vtk.vtkThreshold()
        threshold.SetInputConnection(smoother.GetOutputPort())

        # Convert to polydata
        geometryFilter = vtk.vtkGeometryFilter()
        geometryFilter.SetInputConnection(threshold.GetOutputPort())

        # Convert polydata to stencil
        polyDataToImageStencil = vtk.vtkPolyDataToImageStencil()
        polyDataToImageStencil.SetInputConnection(geometryFilter.GetOutputPort())
        polyDataToImageStencil.SetOutputSpacing(1, 1, 1)
        polyDataToImageStencil.SetOutputOrigin(0, 0, 0)
        polyDataToImageStencil.SetOutputWholeExtent(mergedImage.GetExtent())

        # Convert stencil to image
        stencil = vtk.vtkImageStencil()
        emptyBinaryLabelMap = vtk.vtkImageData()
        emptyBinaryLabelMap.SetExtent(mergedImage.GetExtent())
        emptyBinaryLabelMap.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        vtkSegmentationCore.vtkOrientedImageDataResample.FillImage(emptyBinaryLabelMap, 0)
        stencil.SetInputData(emptyBinaryLabelMap)
        stencil.SetStencilConnection(polyDataToImageStencil.GetOutputPort())
        stencil.ReverseStencilOn()
        stencil.SetBackgroundValue(1)  # General foreground value is 1 (background value because of reverse stencil)

        imageToWorldMatrix = vtk.vtkMatrix4x4()
        mergedImage.GetImageToWorldMatrix(imageToWorldMatrix)

        # TODO: Temporarily setting the overwrite mode to OverwriteVisibleSegments is an approach that should be change once additional
        # layer control options have been implemented. Users may wish to keep segments on separate layers, and not allow them to be separated/merged automatically.
        # This effect could leverage those options once they have been implemented.
        oldOverwriteMode = self.scriptedEffect.parameterSetNode().GetOverwriteMode()
        self.scriptedEffect.parameterSetNode().SetOverwriteMode(
            slicer.vtkMRMLSegmentEditorNode.OverwriteVisibleSegments
        )
        for segmentId, labelValue in segmentLabelValues:
            threshold.ThresholdBetween(labelValue, labelValue)
            stencil.Update()
            smoothedBinaryLabelMap = slicer.vtkOrientedImageData()
            smoothedBinaryLabelMap.ShallowCopy(stencil.GetOutput())
            smoothedBinaryLabelMap.SetImageToWorldMatrix(imageToWorldMatrix)
            self.scriptedEffect.modifySegmentByLabelmap(
                segmentationNode,
                segmentId,
                smoothedBinaryLabelMap,
                slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet,
                False,
            )
        self.scriptedEffect.parameterSetNode().SetOverwriteMode(oldOverwriteMode)

    def paintApply(self, viewWidget):
        # Current limitation: smoothing brush is not implemented for joint smoothing
        smoothingMethod = self.scriptedEffect.parameter("SmoothingMethod")
        if smoothingMethod == JOINT_TAUBIN:
            self.scriptedEffect.clearBrushes()
            self.scriptedEffect.forceRender(viewWidget)
            slicer.util.messageBox("Smoothing brush is not available for 'joint smoothing' method.")
            return

        modifierLabelmap = self.scriptedEffect.defaultModifierLabelmap()
        maskImage = slicer.vtkOrientedImageData()
        maskImage.DeepCopy(modifierLabelmap)
        maskExtent = self.scriptedEffect.paintBrushesIntoLabelmap(maskImage, viewWidget)
        self.scriptedEffect.clearBrushes()
        self.scriptedEffect.forceRender(viewWidget)
        if maskExtent[0] > maskExtent[1] or maskExtent[2] > maskExtent[3] or maskExtent[4] > maskExtent[5]:
            return

        self.scriptedEffect.saveStateForUndo()
        self.onApply(maskImage, maskExtent)


MEDIAN = "MEDIAN"
GAUSSIAN = "GAUSSIAN"
MORPHOLOGICAL_OPENING = "MORPHOLOGICAL_OPENING"
MORPHOLOGICAL_CLOSING = "MORPHOLOGICAL_CLOSING"
JOINT_TAUBIN = "JOINT_TAUBIN"
