import slicer
import logging
import numpy as np

from SegmentEditorEffects import *
from SegmentStatisticsPlugins import *
from ltrace.slicer.helpers import hide_masking_widget
from ltrace.transforms import resample_segmentation

from ltrace.slicer_utils import LTraceSegmentEditorEffectMixin

RESIZE_FACTOR = 0.15

DOWNSAMPLING_FACTOR = 0.5


class SegmentEditorEffect(AbstractScriptedSegmentEditorEffect, LTraceSegmentEditorEffectMixin):
    def __init__(self, scriptedEffect):
        AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)
        scriptedEffect.name = "Sample segmentation"
        scriptedEffect.perSegment = False
        scriptedEffect.requireSegments = True

        # Effect-specific members
        import vtkITK

        self.autoThresholdCalculator = vtkITK.vtkITKImageThresholdCalculator()

        self.downsampledSpacing = None
        self.segmentEditorWidget = None
        self.segmentEditorNode = None
        self.originalGeometryString = None

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
        return """<html><p>Wizard to perform sample segmentation.</p></html>"""

    def setupOptionsFrame(self):
        downsamplingFactorFrame = qt.QFrame()
        downsamplingFactorLayout = qt.QHBoxLayout(downsamplingFactorFrame)
        downsamplingFactorLayout.setContentsMargins(0, 0, 0, 0)
        downsamplingFactorLayout.addWidget(qt.QLabel("Downsampling factor:"))

        self.downsamplingFactorSpinBox = qt.QDoubleSpinBox()
        self.downsamplingFactorSpinBox.setRange(0.1, 1)
        self.downsamplingFactorSpinBox.setDecimals(1)
        self.downsamplingFactorSpinBox.setSingleStep(0.1)
        self.downsamplingFactorSpinBox.setValue(0.5)
        self.downsamplingFactorSpinBox.setToolTip(
            "The downsampling factor of the original segmentation resolution to allow a faster (but less smooth) segmentation."
        )

        downsamplingFactorLayout.addWidget(self.downsamplingFactorSpinBox, 1)
        self.scriptedEffect.addOptionsWidget(downsamplingFactorFrame)

        self.initializeButton = qt.QPushButton("Initialize")
        self.initializeButton.clicked.connect(self.initialize)
        self.scriptedEffect.addOptionsWidget(self.initializeButton)

        self.scriptedEffect.addOptionsWidget(qt.QLabel(""))

        self.optionsFrame = qt.QFrame()
        optionsLayout = qt.QVBoxLayout(self.optionsFrame)
        optionsLayout.setContentsMargins(0, 0, 0, 0)

        optionsLayout.addWidget(qt.QLabel("1. Select the sample region by threshold:"))

        thresholdFrame = qt.QFrame()
        thresholdLayout = qt.QHBoxLayout(thresholdFrame)
        thresholdLayout.setContentsMargins(0, 0, 0, 0)
        self.thresholdSlider = ctk.ctkRangeWidget()
        self.thresholdSlider.spinBoxAlignment = qt.Qt.AlignTop
        self.thresholdSlider.setRange(0, 0)
        self.thresholdSlider.tracking = False
        self.slider = self.thresholdSlider.findChild(ctk.ctkDoubleRangeSlider, "Slider")

        self.sliderEventFilter = SliderEventFilter()
        self.sliderEventFilter.setCallbackFunction(self.onThresholdValuesChanged)
        self.slider.installEventFilter(self.sliderEventFilter)

        minimumSpinBox = self.thresholdSlider.findChild(ctk.ctkDoubleSpinBox, "MinimumSpinBox")
        minimumSpinBox.editingFinished.connect(self.onThresholdValuesChanged)
        maximumSpinBox = self.thresholdSlider.findChild(ctk.ctkDoubleSpinBox, "MaximumSpinBox")
        maximumSpinBox.editingFinished.connect(self.onThresholdValuesChanged)
        thresholdLayout.addWidget(self.thresholdSlider)
        optionsLayout.addWidget(thresholdFrame)

        optionsLayout.addWidget(qt.QLabel(""))

        optionsLayout.addWidget(qt.QLabel("2. Apply sample segmentation steps:"))

        applyFrame = qt.QFrame()
        applyLayout = qt.QHBoxLayout(applyFrame)
        applyLayout.setContentsMargins(0, 0, 0, 0)
        applyLayout.addWidget(qt.QLabel("Throat size threshold (pixels):"))
        self.erodeSpinBox = qt.QSpinBox()
        self.erodeSpinBox.setRange(1, 100)
        self.erodeSpinBox.setValue(10)
        applyLayout.addWidget(self.erodeSpinBox, 1)
        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.clicked.connect(self.applySampleSegmentation)
        applyLayout.addWidget(self.applyButton, 1)
        optionsLayout.addWidget(applyFrame)

        optionsLayout.addWidget(qt.QLabel(""))

        optionsLayout.addWidget(qt.QLabel("3. Calculate segment volume:"))

        calculateVolumeFrame = qt.QFrame()
        calculateVolumeLayout = qt.QVBoxLayout(calculateVolumeFrame)
        calculateVolumeLayout.setContentsMargins(0, 0, 0, 0)
        self.calculateVolumeButton = qt.QPushButton("Calculate volume")
        self.calculateVolumeButton.clicked.connect(self.calculateVolume)
        calculateVolumeLayout.addWidget(self.calculateVolumeButton)
        self.calculateVolumeResultLineEdit = qt.QLineEdit()
        self.calculateVolumeResultLineEdit.setReadOnly(True)
        self.calculateVolumeResultLineEdit.setVisible(False)
        calculateVolumeLayout.addWidget(self.calculateVolumeResultLineEdit)
        optionsLayout.addWidget(calculateVolumeFrame)

        self.scriptedEffect.addOptionsWidget(self.optionsFrame)

    def applySampleSegmentation(self):
        if self.scriptedEffect.parameterSetNode() is None:
            slicer.util.errorDisplay("Failed to apply. The selected node is not valid.")
            return

        self.thresholdSlider.blockSignals(True)
        self.thresholdSlider.setRange(0, 0)
        self.thresholdSlider.blockSignals(False)
        self.thresholdSlider.setEnabled(False)
        self.erodeSpinBox.setEnabled(False)
        self.applyButton.setEnabled(False)

        self.keepLargestIsland()
        self.invertSegmentation()
        self.margin(-self.erodeSpinBox.value * self.downsamplingFactorSpinBox.value)
        self.keepLargestIsland()
        self.margin(self.erodeSpinBox.value * self.downsamplingFactorSpinBox.value)
        self.invertSegmentation()
        self.calculateVolume()

        # Restoring segmentation geometry
        sourceVolumeNode = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        resample_segmentation(segmentationNode, source_node=sourceVolumeNode)

    def calculateVolume(self):
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("Failed to calculate the volume. The selected node is not valid.")
            return

        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()

        visibleSegmentIds = vtk.vtkStringArray()
        segmentationNode.GetDisplayNode().GetVisibleSegmentIDs(visibleSegmentIds)

        plugin = LabelmapSegmentStatisticsPlugin()
        parameterNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLScriptedModuleNode")
        plugin.setParameterNode(parameterNode)
        plugin.getParameterNode().SetParameter("Segmentation", segmentationNode.GetID())
        plugin.requestedKeys = ["volume_mm3"]

        # for segmentIndex in range(visibleSegmentIds.GetNumberOfValues()):
        segmentID = visibleSegmentIds.GetValue(0)
        statistics = plugin.computeStatistics(segmentID)

        self.calculateVolumeResultLineEdit.setText(
            "Total volume: " + str(np.round(statistics["volume_mm3"]).astype(int)) + " mm³."
        )
        self.calculateVolumeResultLineEdit.setVisible(True)

        slicer.mrmlScene.RemoveNode(parameterNode)

    def margin(self, sizeInPixels):
        self.scriptedEffect.saveStateForUndo()
        self.segmentEditorWidget.setActiveEffectByName("Margin")
        effect = self.segmentEditorWidget.activeEffect()
        effect.setParameter("MarginSizePixels", sizeInPixels)
        effect.self().onApply()
        self.segmentEditorWidget.setActiveEffectByName("None")

    def keepLargestIsland(self):
        self.scriptedEffect.saveStateForUndo()
        self.segmentEditorWidget.setActiveEffectByName("Islands")
        effect = self.segmentEditorWidget.activeEffect()
        effect.setParameter("Operation", KEEP_LARGEST_ISLAND)
        effect.self().onApply()
        self.segmentEditorWidget.setActiveEffectByName("None")

    def invertSegmentation(self):
        self.scriptedEffect.saveStateForUndo()
        self.segmentEditorWidget.setActiveEffectByName("Logical operators")
        effect = self.segmentEditorWidget.activeEffect()
        effect.setParameter("Operation", LOGICAL_INVERT)
        effect.self().onApply()
        self.segmentEditorWidget.setActiveEffectByName("None")

    def initialize(self):
        if self.scriptedEffect.parameterSetNode() is None:
            slicer.util.errorDisplay("Failed to initialize the effect. The selected node is not valid.")
            return

        self.scriptedEffect.saveStateForUndo()

        sourceVolumeNode = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()

        # Downsampling to set segmentation geometry
        downsamplingFactor = self.downsamplingFactorSpinBox.value
        resample_segmentation(segmentationNode, factor=downsamplingFactor, source_node=sourceVolumeNode)

        # Create segment editor to get access to effects
        self.segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
        self.segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        self.segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
        self.segmentEditorWidget.setMRMLSegmentEditorNode(self.segmentEditorNode)
        self.segmentEditorWidget.setSegmentationNode(segmentationNode)
        self.segmentEditorWidget.setSourceVolumeNode(sourceVolumeNode)

        self.autoThreshold()

        self.thresholdSlider.setEnabled(True)
        self.erodeSpinBox.setEnabled(True)
        self.applyButton.setEnabled(True)

    def activate(self):
        hide_masking_widget(self)
        self.SetSourceVolumeIntensityMaskOff()
        self.thresholdSlider.blockSignals(True)
        self.thresholdSlider.setRange(0, 0)
        self.thresholdSlider.blockSignals(False)
        self.thresholdSlider.setEnabled(False)
        self.erodeSpinBox.setEnabled(False)
        self.applyButton.setEnabled(False)
        self.calculateVolumeResultLineEdit.setVisible(False)

    def deactivate(self):
        # Cleaning up
        if self.segmentEditorWidget is not None:
            self.segmentEditorWidget.setActiveEffectByName("None")
            slicer.mrmlScene.RemoveNode(self.segmentEditorNode)
            self.segmentEditorWidget = None

    def createCursor(self, widget):
        # Turn off effect-specific cursor for this effect
        return slicer.util.mainWindow().cursor

    def onThresholdValuesChanged(self, *args):
        min = self.thresholdSlider.minimumValue
        max = self.thresholdSlider.maximumValue

        sourceImageData = self.scriptedEffect.sourceVolumeImageData()

        # Get modifier labelmap
        modifierLabelmap = self.scriptedEffect.defaultModifierLabelmap()
        originalImageToWorldMatrix = vtk.vtkMatrix4x4()
        modifierLabelmap.GetImageToWorldMatrix(originalImageToWorldMatrix)

        # Perform thresholding
        thresh = vtk.vtkImageThreshold()
        thresh.SetInputData(sourceImageData)
        thresh.ThresholdBetween(min, max)
        thresh.SetInValue(1)
        thresh.SetOutValue(0)
        thresh.SetOutputScalarType(modifierLabelmap.GetScalarType())
        thresh.Update()
        modifierLabelmap.DeepCopy(thresh.GetOutput())

        # Apply changes
        self.scriptedEffect.modifySelectedSegmentByLabelmap(
            modifierLabelmap, slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet
        )

    def autoThreshold(self):
        self.autoThresholdCalculator.SetMethodToKittlerIllingworth()

        sourceImageData = self.scriptedEffect.sourceVolumeImageData()
        self.autoThresholdCalculator.SetInputData(sourceImageData)
        self.autoThresholdCalculator.Update()
        computedThreshold = self.autoThresholdCalculator.GetThreshold()
        sourceVolumeMin, sourceVolumeMax = sourceImageData.GetScalarRange()

        # Get modifier labelmap
        modifierLabelmap = self.scriptedEffect.defaultModifierLabelmap()
        originalImageToWorldMatrix = vtk.vtkMatrix4x4()
        modifierLabelmap.GetImageToWorldMatrix(originalImageToWorldMatrix)

        # Perform thresholding
        thresh = vtk.vtkImageThreshold()
        thresh.SetInputData(sourceImageData)
        thresh.ThresholdBetween(computedThreshold, sourceVolumeMax)
        thresh.SetInValue(1)
        thresh.SetOutValue(0)
        thresh.SetOutputScalarType(modifierLabelmap.GetScalarType())
        thresh.Update()
        modifierLabelmap.DeepCopy(thresh.GetOutput())

        # Apply changes
        self.scriptedEffect.modifySelectedSegmentByLabelmap(
            modifierLabelmap, slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet
        )

        self.thresholdSlider.blockSignals(True)
        self.thresholdSlider.setRange(sourceVolumeMin, sourceVolumeMax)
        self.thresholdSlider.setMaximumValue(sourceVolumeMax)
        self.thresholdSlider.setMinimumValue(computedThreshold)
        self.thresholdSlider.singleStep = (sourceVolumeMax - sourceVolumeMin) / 1000.0
        self.thresholdSlider.blockSignals(False)

    def cloneVolumeProperties(self, volume):
        newVolume = slicer.mrmlScene.AddNewNodeByClass(volume.GetClassName())
        newVolume.SetOrigin(volume.GetOrigin())
        newVolume.SetSpacing(volume.GetSpacing())
        directions = np.eye(3)
        volume.GetIJKToRASDirections(directions)
        newVolume.SetIJKToRASDirections(directions)

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(volume))
        subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(newVolume), itemParent)

        return newVolume


class SliderEventFilter(qt.QObject):
    def setCallbackFunction(self, function):
        self.callbackFunction = function

    def eventFilter(self, object, event):
        if event.type() == qt.QEvent.MouseButtonRelease:
            self.callbackFunction()
