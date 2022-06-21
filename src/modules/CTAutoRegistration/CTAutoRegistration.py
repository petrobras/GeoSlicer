import datetime
import logging
import os
from collections import namedtuple
from pathlib import Path

import ctk
import numpy as np
import qt
import slicer
import vtk
from scipy.ndimage import zoom

from ltrace.slicer.helpers import triggerNodeModified, highlight_error, reset_style_on_valid_text
from ltrace.slicer.ui import hierarchyVolumeInput, numberParamInt
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer_utils import *
from ltrace.transforms import resample_if_needed
from ltrace.units import global_unit_registry as ureg


class CTAutoRegistration(LTracePlugin):
    SETTING_KEY = "CTAutoRegistration"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "CT Auto Registration"
        self.parent.categories = ["Registration"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = CTAutoRegistration.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CTAutoRegistrationWidget(LTracePluginWidget):
    # Settings constants
    RESAMPLE = "resample"
    SAMPLE_RADIUS = "sampleRadius"
    SAMPLING_PERCENTAGE = "samplingPercentage"
    MINIMUM_STEP_LENGTH = "minimumStepLength"
    NUMBER_OF_ITERATIONS = "numberOfIterations"
    DOWNSAMPLING_FACTOR = "downsamplingFactor"
    RIGID_REGISTRATION_PHASE = "rigidRegistrationPhase"
    RIGID_SCALE_REGISTRATION_PHASE = "rigidScaleRegistrationPhase"
    RIGID_SCALE_SKEW_REGISTRATION_PHASE = "rigidScaleSkewRegistrationPhase"

    RegisterParameters = namedtuple(
        "RegisterParameters",
        [
            "fixedVolume",
            "movingVolume",
            RESAMPLE,
            SAMPLE_RADIUS,
            SAMPLING_PERCENTAGE,
            MINIMUM_STEP_LENGTH,
            NUMBER_OF_ITERATIONS,
            DOWNSAMPLING_FACTOR,
            RIGID_REGISTRATION_PHASE,
            RIGID_SCALE_REGISTRATION_PHASE,
            RIGID_SCALE_SKEW_REGISTRATION_PHASE,
            "outputPrefix",
        ],
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def getResample(self):
        return CTAutoRegistration.get_setting(self.RESAMPLE, default=str(True))

    def getSampleRadius(self):
        return CTAutoRegistration.get_setting(self.SAMPLE_RADIUS, default="18")

    def getSamplingPercentage(self):
        return CTAutoRegistration.get_setting(self.SAMPLING_PERCENTAGE, default="0.005")

    def getMinimumStepLength(self):
        return CTAutoRegistration.get_setting(self.MINIMUM_STEP_LENGTH, default="0.0001")

    def getNumberOfIterations(self):
        return CTAutoRegistration.get_setting(self.NUMBER_OF_ITERATIONS, default="1500")

    def getDownsamplingFactor(self):
        return CTAutoRegistration.get_setting(self.DOWNSAMPLING_FACTOR, default="0.3")

    def getRigidRegistrationPhase(self):
        return CTAutoRegistration.get_setting(self.RIGID_REGISTRATION_PHASE, default=str(True))

    def getRigidScaleRegistrationPhase(self):
        return CTAutoRegistration.get_setting(self.RIGID_SCALE_REGISTRATION_PHASE, default=str(False))

    def getRigidScaleSkewRegistrationPhase(self):
        return CTAutoRegistration.get_setting(self.RIGID_SCALE_SKEW_REGISTRATION_PHASE, default=str(False))

    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = CTAutoRegistrationLogic(self.progressBar, self.enableApply)

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

        self.fixedVolumeComboBox = hierarchyVolumeInput(nodeTypes=["vtkMRMLScalarVolumeNode"])
        self.fixedVolumeComboBox.setToolTip("Select the fixed volume.")
        inputFormLayout.addRow("Fixed volume:", self.fixedVolumeComboBox)
        self.fixedVolumeComboBox.resetStyleOnValidNode()

        self.movingVolumeComboBox = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode"], onChange=self.movingVolumeChanged
        )
        self.movingVolumeComboBox.setToolTip("Select the moving volume.")
        inputFormLayout.addRow("Moving volume:", self.movingVolumeComboBox)
        inputFormLayout.addRow(" ", None)
        self.movingVolumeComboBox.resetStyleOnValidNode()

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.resampleCheckBox = qt.QCheckBox("Resample output to match fixed volume")
        self.resampleCheckBox.setChecked(self.getResample() == "True")
        parametersFormLayout.addRow(self.resampleCheckBox)

        self.sampleRadiusSpinBox = numberParamInt(vrange=(1, 1000), value=int(self.getSampleRadius()))
        self.sampleRadiusSpinBox.setToolTip(
            "Approximate sample radius (in millimeters) used to create a cylindrical mask."
        )
        parametersFormLayout.addRow("Sample radius (mm):", self.sampleRadiusSpinBox)

        self.samplingPercentageSpinBox = qt.QDoubleSpinBox()
        self.samplingPercentageSpinBox.setRange(0.001, 1)
        self.samplingPercentageSpinBox.setDecimals(3)
        self.samplingPercentageSpinBox.setSingleStep(0.001)
        self.samplingPercentageSpinBox.setValue(float(self.getSamplingPercentage()))
        self.samplingPercentageSpinBox.setToolTip(
            "Fraction of voxels of the fixed image that will be used for registration. The number has to be larger than zero and less or equal to one. Higher values increase the computation time but may give more accurate results."
        )
        parametersFormLayout.addRow("Sampling fraction:", self.samplingPercentageSpinBox)

        self.minimumStepLengthSpinBox = qt.QDoubleSpinBox()
        self.minimumStepLengthSpinBox.setRange(0.00001, 1)
        self.minimumStepLengthSpinBox.setDecimals(5)
        self.minimumStepLengthSpinBox.setSingleStep(0.00001)
        self.minimumStepLengthSpinBox.setValue(float(self.getMinimumStepLength()))
        self.minimumStepLengthSpinBox.setToolTip(
            " Each step in the optimization takes steps at least this big. When none are possible, registration is complete. Smaller values allows the optimizer to make smaller adjustments, but the registration time may increase."
        )
        parametersFormLayout.addRow("Minimum step length:", self.minimumStepLengthSpinBox)

        self.numberOfIterationsSpinBox = numberParamInt(vrange=(10, 10000), value=int(self.getNumberOfIterations()))
        self.numberOfIterationsSpinBox.setToolTip(
            "The maximum number of iterations to try before stopping the optimization. When using a lower value (500-1000) then the registration is forced to terminate earlier but there is a higher risk of stopping before an optimal solution is reached."
        )
        parametersFormLayout.addRow("Number of iterations:", self.numberOfIterationsSpinBox)

        self.downsamplingFactorSpinBox = qt.QDoubleSpinBox()
        self.downsamplingFactorSpinBox.setRange(0.01, 1)
        self.downsamplingFactorSpinBox.setDecimals(2)
        self.downsamplingFactorSpinBox.setSingleStep(0.1)
        self.downsamplingFactorSpinBox.setValue(float(self.getDownsamplingFactor()))
        self.downsamplingFactorSpinBox.setToolTip(
            "The downsampling factor of the original data resolution to allow a faster (but possibly more inaccurate) registration."
        )
        parametersFormLayout.addRow("Downsampling factor:", self.downsamplingFactorSpinBox)
        parametersFormLayout.addRow(" ", None)

        parametersFormLayout.addRow("Registration phases:", None)
        self.rigidRegistrationPhaseCheckBox = qt.QCheckBox("Rigid (6 DOF)")
        self.rigidScaleRegistrationPhaseCheckBox = qt.QCheckBox("Rigid + Scale (7 DOF)")
        self.rigidScaleSkewRegistrationPhaseCheckBox = qt.QCheckBox("Rigid + Scale + Skew (10 DOF)")

        self.rigidRegistrationPhaseCheckBox.setChecked(self.getRigidRegistrationPhase() == "True")
        self.rigidScaleRegistrationPhaseCheckBox.setChecked(self.getRigidScaleRegistrationPhase() == "True")
        self.rigidScaleSkewRegistrationPhaseCheckBox.setChecked(self.getRigidScaleSkewRegistrationPhase() == "True")

        parametersFormLayout.addRow(self.rigidRegistrationPhaseCheckBox)
        parametersFormLayout.addRow(self.rigidScaleRegistrationPhaseCheckBox)
        parametersFormLayout.addRow(self.rigidScaleSkewRegistrationPhaseCheckBox)
        parametersFormLayout.addRow(" ", None)

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

        self.layout.addStretch(1)

        self.enableApply()

    def movingVolumeChanged(self, itemId):
        node = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(itemId)
        if node:
            outputPrefix = node.GetName()
        else:
            outputPrefix = ""
        self.outputPrefixLineEdit.text = outputPrefix

    def onRegisterButtonClicked(self):
        self.enableApply(False)
        try:
            if self.fixedVolumeComboBox.currentNode() is None:
                highlight_error(self.fixedVolumeComboBox)
                return

            if self.movingVolumeComboBox.currentNode() is None:
                highlight_error(self.movingVolumeComboBox)
                return

            if (
                not self.rigidRegistrationPhaseCheckBox.isChecked()
                and not self.rigidScaleRegistrationPhaseCheckBox.isChecked()
                and not self.rigidScaleSkewRegistrationPhaseCheckBox.isChecked()
            ):
                raise RegistrationInfo("At least one registration phase is required.")

            minRadius, maxRadius = self.logic.getSampleRadiusInterval(self.fixedVolumeComboBox.currentNode())

            if float(self.sampleRadiusSpinBox.value) < minRadius or float(self.sampleRadiusSpinBox.value) > maxRadius:
                raise RegistrationInfo(
                    "Sample radius must be between " + str(minRadius) + " mm and " + str(maxRadius) + " mm."
                )

            if self.outputPrefixLineEdit.text.strip() == "":
                highlight_error(self.outputPrefixLineEdit)
                return

            CTAutoRegistration.set_setting(self.RESAMPLE, str(self.resampleCheckBox.isChecked()))
            CTAutoRegistration.set_setting(self.SAMPLE_RADIUS, self.sampleRadiusSpinBox.value)
            CTAutoRegistration.set_setting(self.SAMPLING_PERCENTAGE, self.samplingPercentageSpinBox.value)
            CTAutoRegistration.set_setting(self.MINIMUM_STEP_LENGTH, self.minimumStepLengthSpinBox.value)
            CTAutoRegistration.set_setting(self.NUMBER_OF_ITERATIONS, self.numberOfIterationsSpinBox.value)
            CTAutoRegistration.set_setting(self.DOWNSAMPLING_FACTOR, self.downsamplingFactorSpinBox.value)
            CTAutoRegistration.set_setting(
                self.RIGID_REGISTRATION_PHASE, str(self.rigidRegistrationPhaseCheckBox.isChecked())
            )
            CTAutoRegistration.set_setting(
                self.RIGID_SCALE_REGISTRATION_PHASE, str(self.rigidScaleRegistrationPhaseCheckBox.isChecked())
            )
            CTAutoRegistration.set_setting(
                self.RIGID_SCALE_SKEW_REGISTRATION_PHASE, str(self.rigidScaleSkewRegistrationPhaseCheckBox.isChecked())
            )
            registerParameters = self.RegisterParameters(
                self.fixedVolumeComboBox.currentNode(),
                self.movingVolumeComboBox.currentNode(),
                self.resampleCheckBox.isChecked(),
                float(self.sampleRadiusSpinBox.value) * ureg.millimeter,
                float(self.samplingPercentageSpinBox.value),
                float(self.minimumStepLengthSpinBox.value),
                float(self.numberOfIterationsSpinBox.value),
                float(self.downsamplingFactorSpinBox.value),
                self.rigidRegistrationPhaseCheckBox.isChecked(),
                self.rigidScaleRegistrationPhaseCheckBox.isChecked(),
                self.rigidScaleSkewRegistrationPhaseCheckBox.isChecked(),
                self.outputPrefixLineEdit.text,
            )
            self.logic.register(registerParameters)
        except RegistrationInfo as e:
            self.enableApply()
            slicer.util.infoDisplay(str(e))
            return

    def onCancelButtonClicked(self):
        self.logic.cancel()

    def enableApply(self, enabled=True):
        self.registerButton.setEnabled(enabled)
        self.cancelButton.setEnabled(not enabled)
        slicer.app.processEvents()


class CTAutoRegistrationLogic(LTracePluginLogic):
    def __init__(self, progressBar, callback):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar
        self.callback = callback

    def downsampleVolume(self, volume, downsamplingFactor):
        print("Downsampling " + volume.GetName())
        downsampledVolume = self.cloneVolumeProperties(volume, volume.GetName() + " - Downsampled")
        downsampledVolume.HideFromEditorsOn()
        triggerNodeModified(downsampledVolume)
        downsampledVolume.SetSpacing(np.array(volume.GetSpacing()) / downsamplingFactor)
        array = slicer.util.arrayFromVolume(volume)
        rescaledArray = zoom(array, downsamplingFactor, order=1, cval=np.min(array))
        slicer.util.updateVolumeFromArray(downsampledVolume, rescaledArray)
        return downsampledVolume

    def register(self, p):
        # Removing old cli node if it exists
        slicer.mrmlScene.RemoveNode(self.cliNode)

        print("CT Auto Registration start time: " + str(datetime.datetime.now()))

        self.resample = p.resample
        self.originalFixedVolume = p.fixedVolume
        self.fixedVolume = p.fixedVolume
        self.movingVolume = p.movingVolume

        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        fixedVolumeItemParent = subjectHierarchyNode.GetItemParent(
            subjectHierarchyNode.GetItemByDataNode(self.fixedVolume)
        )
        movingVolumeItemParent = subjectHierarchyNode.GetItemParent(
            subjectHierarchyNode.GetItemByDataNode(self.movingVolume)
        )

        # Output volume
        self.outputVolume = slicer.modules.volumes.logic().CloneVolume(self.movingVolume, "Cloned volume")
        self.outputVolume.HideFromEditorsOn()
        self.outputVolume.SetName(p.outputPrefix + " - Registered volume")
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(self.outputVolume), movingVolumeItemParent
        )

        self.downsampledFixedVolume = None
        self.downsampledMovingVolume = None
        if p.downsamplingFactor < 1:
            self.downsampledFixedVolume = self.downsampleVolume(self.fixedVolume, p.downsamplingFactor)
            self.fixedVolume = self.downsampledFixedVolume

            self.downsampledMovingVolume = self.downsampleVolume(self.movingVolume, p.downsamplingFactor)
            self.movingVolume = self.downsampledMovingVolume

        # This is necessary because the direct call was not working if the downsampled volumes where created and being shown
        qt.QTimer.singleShot(1, self.delayedSetSliceViewerLayers)

        # Output linear transform
        self.outputLinearTransform = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLLinearTransformNode",
            p.outputPrefix + " - Registration transform",
        )
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(self.outputLinearTransform), movingVolumeItemParent
        )
        self.outputLinearTransform.HideFromEditorsOn()
        triggerNodeModified(self.outputLinearTransform)

        # Fixed mask volume
        self.fixedMaskLabelMap = self.createCylindricalMask(self.fixedVolume, p.sampleRadius.m, 0.95)
        self.fixedMaskLabelMap.SetName(p.outputPrefix + " - Fixed Volume Registration ROI mask")
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(self.fixedMaskLabelMap), fixedVolumeItemParent
        )

        # Moving mask volume
        self.movingMaskLabelMap = self.createCylindricalMask(self.movingVolume, p.sampleRadius.m, 0.95)
        self.movingMaskLabelMap.SetName(p.outputPrefix + " - Moving Volume Registration ROI Mask")
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(self.movingMaskLabelMap), movingVolumeItemParent
        )

        registrationPhases = ""
        registrationPhases += "Rigid," if p.rigidRegistrationPhase else ""
        registrationPhases += "ScaleVersor3D," if p.rigidScaleRegistrationPhase else ""
        registrationPhases += "ScaleSkewVersor3D," if p.rigidScaleSkewRegistrationPhase else ""
        registrationPhases = registrationPhases[:-1]

        # See https://www.slicer.org/w/index.php/Documentation/Nightly/Modules/BRAINSFit
        cliParams = {
            "fixedVolume": self.fixedVolume.GetID(),
            "movingVolume": self.movingVolume.GetID(),
            "samplingPercentage": p.samplingPercentage,
            "transformType": registrationPhases,
            "interpolationMode": "Linear",
            "outputVolumePixelType": "int",
            "backgroundFillValue": str(np.min(slicer.util.arrayFromVolume(self.movingVolume))),
            "removeIntensityOutliers": 0.005,
            "minimumStepLength": p.minimumStepLength,
            "numberOfIterations": p.numberOfIterations,
            "linearTransform": self.outputLinearTransform.GetID(),
            "maskProcessingMode": "ROI",
            "fixedBinaryVolume": self.fixedMaskLabelMap.GetID(),
            "movingBinaryVolume": self.movingMaskLabelMap.GetID(),
        }

        self.cliNode = slicer.cli.run(slicer.modules.brainsfit, None, cliParams)
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.registrationCLICallback)

    def delayedSetSliceViewerLayers(self):
        slicer.util.setSliceViewerLayers(background=None)

    def createCylindricalMask(self, volume, radius, erosionFactor):
        volumeBounds = np.zeros(6)
        volume.GetBounds(volumeBounds)
        length = (volumeBounds[5] - volumeBounds[4]) * erosionFactor

        # Create segmentation
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")

        # Create segment editor to get access to effects
        segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
        segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
        segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)
        segmentEditorWidget.setSegmentationNode(segmentationNode)
        segmentEditorWidget.setSourceVolumeNode(volume)

        # Creating the segmentation cylinder
        segmentationNode.CreateDefaultDisplayNodes()
        segmentationCylinder = vtk.vtkCylinderSource()
        segmentationCylinder.SetRadius(radius)
        segmentationCylinder.SetHeight(length)
        segmentationCylinder.SetResolution(100)

        # Rotating and centering on the data
        segmentationCylinderTransformationMatrix = np.array(
            [
                [1, 0, 0, (volumeBounds[0] + volumeBounds[1]) / 2],
                [0, 0, -1, (volumeBounds[2] + volumeBounds[3]) / 2],
                [0, 1, 0, (volumeBounds[4] + volumeBounds[5]) / 2],
                [0, 0, 0, 1],
            ]
        )

        vtkTransformationMatrix = vtk.vtkMatrix4x4()
        vtkTransformationMatrix.DeepCopy(list(segmentationCylinderTransformationMatrix.flat))
        transformNode = slicer.vtkMRMLTransformNode()
        slicer.mrmlScene.AddNode(transformNode)
        segmentationNode.SetAndObserveTransformNodeID(transformNode.GetID())
        transformNode.SetMatrixTransformToParent(vtkTransformationMatrix)
        segmentationCylinder.Update()
        segmentationNode.AddSegmentFromClosedSurfaceRepresentation(
            segmentationCylinder.GetOutput(),
            "Cylinder",
            [0, 1, 0],
        )
        segmentationNode.HardenTransform()
        segmentEditorWidget.setSegmentationNode(segmentationNode)

        # Creating mask to extract the core volume
        labelMapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        segmentEditorWidget.setCurrentSegmentID(segmentationNode.GetSegmentation().GetNthSegmentID(0))
        segmentEditorWidget.setActiveEffectByName("Mask volume")
        effect = segmentEditorWidget.activeEffect()
        segmentEditorNode.SetMaskSegmentID(segmentationNode.GetSegmentation().GetNthSegmentID(0))
        effect.setParameter("Operation", "FILL_INSIDE_AND_OUTSIDE")
        effect.setParameter("BinaryMaskFillValueInside", 1)
        effect.setParameter("BinaryMaskFillValueOutside", 0)
        effect.self().outputVolumeSelector.setCurrentNode(labelMapVolumeNode)
        effect.self().onApply()

        # Cleaning up
        slicer.mrmlScene.RemoveNode(segmentationNode)
        slicer.mrmlScene.RemoveNode(transformNode)
        slicer.mrmlScene.RemoveNode(segmentEditorNode)

        return labelMapVolumeNode

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
            slicer.mrmlScene.RemoveNode(self.downsampledFixedVolume)
            slicer.mrmlScene.RemoveNode(self.downsampledMovingVolume)
            if status == "Completed":
                self.outputVolume.SetAndObserveTransformNodeID(self.outputLinearTransform.GetID())
                self.outputVolume.HardenTransform()

                if self.resample:
                    resample_if_needed(input_volume=self.outputVolume, reference_volume=self.originalFixedVolume)

                self.outputVolume.HideFromEditorsOff()
                triggerNodeModified(self.outputVolume)

                self.outputLinearTransform.HideFromEditorsOff()
                triggerNodeModified(self.outputLinearTransform)

                slicer.util.setSliceViewerLayers(background=self.outputVolume, fit=True)
                print("CT Auto Registration end time: " + str(datetime.datetime.now()))
            elif status == "Cancelled":
                slicer.mrmlScene.RemoveNode(self.outputVolume)
                slicer.mrmlScene.RemoveNode(self.outputLinearTransform)
                slicer.mrmlScene.RemoveNode(self.fixedMaskLabelMap)
                slicer.mrmlScene.RemoveNode(self.movingMaskLabelMap)
            else:
                slicer.mrmlScene.RemoveNode(self.outputVolume)
                slicer.mrmlScene.RemoveNode(self.outputLinearTransform)
                slicer.mrmlScene.RemoveNode(self.fixedMaskLabelMap)
                slicer.mrmlScene.RemoveNode(self.movingMaskLabelMap)
            self.callback()

    def cancel(self):
        if self.cliNode is None:
            return  # nothing running, nothing to do
        self.cliNode.Cancel()

    def cloneVolumeProperties(self, volume, newVolumeName):
        newVolume = slicer.mrmlScene.AddNewNodeByClass(volume.GetClassName(), newVolumeName)
        newVolume.SetOrigin(volume.GetOrigin())
        newVolume.SetSpacing(volume.GetSpacing())
        directions = np.eye(3)
        volume.GetIJKToRASDirections(directions)
        newVolume.SetIJKToRASDirections(directions)

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(volume))
        subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(newVolume), itemParent)

        return newVolume

    def getSampleRadiusInterval(self, fixedVolume):
        bounds = np.zeros(6)
        fixedVolume.GetBounds(bounds)
        radius = (np.mean([bounds[i + 1] - bounds[i] for i in [0, 2]]) / 2) * 0.9
        maxRadius = int(radius)
        minRadius = int(radius / 4)
        return minRadius, maxRadius


class RegistrationInfo(RuntimeError):
    pass
