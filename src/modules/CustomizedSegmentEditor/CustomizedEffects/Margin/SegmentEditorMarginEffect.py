# fmt: off
import os
import vtk, qt, ctk, slicer
import logging
import math
import qt
from SegmentEditorEffects import *

from ltrace.slicer_utils import LTraceSegmentEditorEffectMixin


class SegmentEditorMarginEffect(AbstractScriptedSegmentEditorEffect, LTraceSegmentEditorEffectMixin):
  """ MaringEffect grows or shrinks the segment by a specified margin
  """

  def __init__(self, scriptedEffect):
    scriptedEffect.name = 'Margin'
    AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)

  def clone(self):
    import qSlicerSegmentationsEditorEffectsPythonQt as effects
    clonedEffect = effects.qSlicerSegmentEditorScriptedEffect(None)
    clonedEffect.setPythonSource(__file__.replace('\\','/'))
    return clonedEffect

  def icon(self):
    iconPath = os.path.join(os.path.dirname(__file__), 'Resources/Icons/Margin.png')
    if os.path.exists(iconPath):
      return qt.QIcon(iconPath)
    return qt.QIcon()

  def helpText(self):
    return "Grow or shrink selected segment by specified margin size."
  
  def activate(self):
    self.SetSourceVolumeIntensityMaskOff()

  def setupOptionsFrame(self):

    operationLayout = qt.QVBoxLayout()

    self.shrinkOptionRadioButton = qt.QRadioButton("Erosion")
    self.growOptionRadioButton = qt.QRadioButton("Dilation")
    operationLayout.addWidget(self.shrinkOptionRadioButton)
    operationLayout.addWidget(self.growOptionRadioButton)
    self.growOptionRadioButton.setChecked(True)

    self.scriptedEffect.addLabeledOptionsWidget("Operation:", operationLayout)

    self.marginSizePxSpinBox = qt.QDoubleSpinBox()
    self.marginSizePxSpinBox.setToolTip("Segment boundaries will be shifted by this distance. Positive value means the segments will grow, negative value means segment will shrink.")
    self.marginSizePxSpinBox.value = 3.0
    self.marginSizePxSpinBox.singleStep = 1.0
    self.marginSizePxSpinBox.setSuffix("px")

    self.marginSizeLabel = qt.QLabel()
    self.marginSizeLabel.setToolTip("Size change in pixel. Computed from the segment's spacing and the specified margin size.")

    marginSizeFrame = qt.QHBoxLayout()
    marginSizeFrame.addWidget(self.marginSizePxSpinBox)
    self.marginSizePxLabel = self.scriptedEffect.addLabeledOptionsWidget("Margin size:", marginSizeFrame)
    self.scriptedEffect.addLabeledOptionsWidget("", self.marginSizeLabel)

    self.applyButton = qt.QPushButton("Apply")
    self.applyButton.objectName = self.__class__.__name__ + 'Apply'
    self.applyButton.setToolTip("Grows or shrinks selected segment by the specified margin.")
    self.scriptedEffect.addOptionsWidget(self.applyButton)

    self.applyButton.connect('clicked()', self.onApply)
    self.marginSizePxSpinBox.editingFinished.connect(self.updateMRMLFromGUI)
    self.growOptionRadioButton.connect("toggled(bool)", self.growOperationToggled)
    self.shrinkOptionRadioButton.connect("toggled(bool)", self.shrinkOperationToggled)

  def createCursor(self, widget):
    # Turn off effect-specific cursor for this effect
    return slicer.util.mainWindow().cursor

  def setMRMLDefaults(self):
    self.scriptedEffect.setParameterDefault("MarginSizePixels", 3)

  def getMarginSizePixel(self):
    return [abs(self.scriptedEffect.doubleParameter("MarginSizePixels"))] * 3

  def updateGUIFromMRML(self):
    marginSizePixels = self.scriptedEffect.doubleParameter("MarginSizePixels")
    wasBlocked = self.marginSizePxSpinBox.blockSignals(True)
    self.marginSizePxSpinBox.value = abs(marginSizePixels)
    self.marginSizePxSpinBox.blockSignals(wasBlocked)

    wasBlocked = self.growOptionRadioButton.blockSignals(True)
    self.growOptionRadioButton.setChecked(marginSizePixels > 0)
    self.growOptionRadioButton.blockSignals(wasBlocked)

    wasBlocked = self.shrinkOptionRadioButton.blockSignals(True)
    self.shrinkOptionRadioButton.setChecked(marginSizePixels < 0)
    self.shrinkOptionRadioButton.blockSignals(wasBlocked)

    selectedSegmentLabelmapSpacing = [1.0, 1.0, 1.0]
    selectedSegmentLabelmap = self.scriptedEffect.selectedSegmentLabelmap()
    if selectedSegmentLabelmap:
      selectedSegmentLabelmapSpacing = selectedSegmentLabelmap.GetSpacing()
      marginSizePixel = self.getMarginSizePixel()
      if marginSizePixel[0] < 1 or marginSizePixel[1] < 1 or marginSizePixel[2] < 1:
        self.marginSizeLabel.text = "Not feasible at current resolution."
        self.applyButton.setEnabled(False)
      else:
        marginSizeMM = self.getMarginSizeMM()
        self.marginSizeLabel.text = "Actual: {0} x {1} x {2} mm".format(*marginSizeMM)
        self.applyButton.setEnabled(True)
    else:
      self.marginSizeLabel.text = "Empty segment"

    self.setWidgetMinMaxStepFromImageSpacing(self.marginSizePxSpinBox, self.scriptedEffect.selectedSegmentLabelmap())

  def growOperationToggled(self, toggled):
    if toggled:
      self.scriptedEffect.setParameter("MarginSizePixels", self.marginSizePxSpinBox.value)

  def shrinkOperationToggled(self, toggled):
    if toggled:
      self.scriptedEffect.setParameter("MarginSizePixels", -self.marginSizePxSpinBox.value)

  def updateMRMLFromGUI(self):
    marginSizePixel = (self.marginSizePxSpinBox.value) if self.growOptionRadioButton.checked else (-self.marginSizePxSpinBox.value)
    self.scriptedEffect.setParameter("MarginSizePixels", marginSizePixel)

  def getMarginSizeMM(self):
    selectedSegmentLabelmapSpacing = [1.0, 1.0, 1.0]
    selectedSegmentLabelmap = self.scriptedEffect.selectedSegmentLabelmap()
    if selectedSegmentLabelmap:
      selectedSegmentLabelmapSpacing = selectedSegmentLabelmap.GetSpacing()

    marginSizePixel = self.getMarginSizePixel()
    marginSizeMM = [abs((marginSizePixel[i])*selectedSegmentLabelmapSpacing[i]) for i in range(3)]
    for i in range(3):
      if marginSizeMM[i] > 0:
        marginSizeMM[i] = round(marginSizeMM[i], max(int(-math.floor(math.log10(marginSizeMM[i]))),1))
    return marginSizeMM

  def onApply(self):
    # Make sure the user wants to do the operation, even if the segment is not visible
    if not self.scriptedEffect.confirmCurrentSegmentVisible():
      return

    self.scriptedEffect.saveStateForUndo()

    # Get modifier labelmap and parameters
    modifierLabelmap = self.scriptedEffect.defaultModifierLabelmap()
    selectedSegmentLabelmap = self.scriptedEffect.selectedSegmentLabelmap()

    marginSizePixels = self.scriptedEffect.doubleParameter("MarginSizePixels")

    # We need to know exactly the value of the segment voxels, apply threshold to make force the selected label value
    labelValue = 1
    backgroundValue = 0
    thresh = vtk.vtkImageThreshold()
    thresh.SetInputData(selectedSegmentLabelmap)
    thresh.ThresholdByLower(0)
    thresh.SetInValue(backgroundValue)
    thresh.SetOutValue(labelValue)
    thresh.SetOutputScalarType(selectedSegmentLabelmap.GetScalarType())
    if (marginSizePixels < 0):
      # The distance filter used in the margin filter starts at zero at the border voxels,
      # so if we need to shrink the margin, it is more accurate to invert the labelmap and
      # use positive distance when calculating the margin
      thresh.SetInValue(labelValue)
      thresh.SetOutValue(backgroundValue)

    import vtkITK
    margin = vtkITK.vtkITKImageMargin()
    margin.SetInputConnection(thresh.GetOutputPort())
    margin.CalculateMarginInMMOff()
    margin.SetOuterMarginVoxels(abs(marginSizePixels))
    margin.Update()

    if marginSizePixels >= 0:
      modifierLabelmap.ShallowCopy(margin.GetOutput())
    else:
      # If we are shrinking then the result needs to be inverted.
      thresh = vtk.vtkImageThreshold()
      thresh.SetInputData(margin.GetOutput())
      thresh.ThresholdByLower(0)
      thresh.SetInValue(labelValue)
      thresh.SetOutValue(backgroundValue)
      thresh.SetOutputScalarType(selectedSegmentLabelmap.GetScalarType())
      thresh.Update()
      modifierLabelmap.ShallowCopy(thresh.GetOutput())

    # Apply changes
    self.scriptedEffect.modifySelectedSegmentByLabelmap(modifierLabelmap, slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet)

    qt.QApplication.restoreOverrideCursor()

  def setWidgetMinMaxStepFromImageSpacing(self, spinbox, imageData):
    if not imageData:
      return
    import math
    stepSize = 1
    spinbox.minimum = stepSize
    spinbox.maximum = math.floor(10**(math.ceil(math.log10(max(imageData.GetSpacing())*100.0)))/max(imageData.GetSpacing()))
    spinbox.singleStep = stepSize
