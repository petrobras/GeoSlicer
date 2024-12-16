import json
import math
import os
import shutil
from multiprocessing import cpu_count
from pathlib import Path

import ctk
import mpslib as mps
import numpy as np
import qt
import slicer
from tifffile import tifffile

from ltrace.slicer import helpers
from ltrace.slicer import ui
from ltrace.slicer import widgets
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, getResourcePath
from ltrace.utils.ProgressBarProc import ProgressBarProc

try:
    from Test.MultiScaleTest import MultiScaleTest
except ImportError:
    MultiScaleTest = None  # tests not deployed to final version or closed source

CONVERSION_FACTOR = 1000  # Base (1) should be milimeter
COLOCATE_DIMENSIONS = {
    "X": 0,
    "Y": 1,
    "Z": 2,
}


class MultiScale(LTracePlugin):
    SETTING_KEY = "MultiScale"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Multiscale Image Generation"
        self.parent.categories = ["MicroCT", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = MultiScale.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MultiScaleWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = None
        self.valuesList = []
        self.isViewOn = False
        self.isContinuousCheckBoxLocked = False

    def setup(self):
        LTracePluginWidget.setup(self)

        self.logic = MultiScaleLogic(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.trainingImageWidget = widgets.SingleShotInputWidget(
            hideSoi=True,
            hideCalcProp=False,
            allowedInputNodes=[
                "vtkMRMLScalarVolumeNode",
                "vtkMRMLSegmentationNode",
                "vtkMRMLLabelMapVolumeNode",
            ],
            mainName="Training Image",
            referenceName="TI Reference",
            setDefaultMargins=False,
            objectNamePrefix="Training Image",
        )

        self.trainingImageWidget.formLayout.setContentsMargins(0, 0, 0, 0)
        self.trainingImageWidget.mainInput.currentItemChanged.connect(self.onTrainingImageChange)
        self.trainingImageWidget.onReferenceSelectedSignal.connect(self.updateFinalImageWidgets)
        self.trainingImageWidget.segmentListGroup[1].itemChanged.connect(lambda: self.listItemChange())
        self.trainingImageWidget.autoPorosityCalcCb.stateChanged.connect(self.onTrainingImageChange)

        self.hardDataWidget = widgets.SingleShotInputWidget(
            hideSoi=True,
            allowedInputNodes=[
                "vtkMRMLScalarVolumeNode",
                "vtkMRMLSegmentationNode",
                "vtkMRMLLabelMapVolumeNode",
            ],
            mainName="Hard Data Image",
            referenceName="HD Reference",
            setDefaultMargins=False,
            objectNamePrefix="Hard Data",
        )

        self.hardDataWidget.formLayout.setContentsMargins(0, 0, 0, 0)
        self.hardDataWidget.mainInput.currentItemChanged.connect(self.onHardDataChange)
        self.hardDataWidget.onReferenceSelectedSignal.connect(self.onReferenceChange)
        self.hardDataWidget.segmentListGroup[1].itemChanged.connect(self.listItemChange)
        self.hardDataWidget.autoPorosityCalcCb.stateChanged.connect(
            lambda: self.checkListItems(self.hardDataWidget.segmentListGroup[1])
        )

        self.hardDataResolution = []
        self.hardDataResolutionText = qt.QLabel("0 x 0 x 0 (mm)")
        self.hardDataResolutionText.setToolTip(
            "Resolution of the hard data voxel in mm. For the multiscale simulations, the units are converted to micrometers"
        )
        self.hardDataResolutionText.objectName = "Hard Data Resolution Label"
        self.hardDataResolutionText.hide()

        self.hardDataResolutionLabel = qt.QLabel("HD resolution:")
        self.hardDataResolutionLabel.objectName = "hardDataLabel"
        self.hardDataResolutionLabel.hide()

        self.depthTopSpinBox = qt.QDoubleSpinBox()
        self.depthTopSpinBox.setToolTip(
            "Starting depth of the well that will be used to generate the preview. This option is only available for imagelogs data."
        )
        self.depthTopSpinBox.setDecimals(5)
        self.depthTopSpinBox.objectName = "depthTopSpinBox"

        self.depthBottomSpinBox = qt.QDoubleSpinBox()
        self.depthBottomSpinBox.setToolTip(
            "End depth of the well that will be used to generate the preview. This option is only available for imagelogs data."
        )
        self.depthBottomSpinBox.setDecimals(5)
        self.depthBottomSpinBox.objectName = "depthBottomSpinBox"

        self.previewDimensionSpinBox = qt.QSpinBox()
        self.previewDimensionSpinBox.setRange(30, 150)
        self.previewDimensionSpinBox.setValue(122)
        self.previewDimensionSpinBox.setToolTip(
            "Number of pixels that will be used to generate the well. 122 pixels produces voxels enough to show all imagelog values. This option is only available for imagelogs data."
        )
        self.previewDimensionSpinBox.objectName = "previewDimensionSpinBox"

        self.previewButton = qt.QPushButton()
        self.previewButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeClosed.png"))
        self.previewButton.setFixedWidth(30)
        self.previewButton.enabled = False
        self.previewButton.clicked.connect(self.onViewPreviewToggle)
        self.previewButton.setToolTip(
            "Create a 3d model preview of the hard data. The input must be a segmentation node or labelmap. Also generates a preview of the well for 2d image logs."
        )
        self.previewButton.objectName = "previewButton"

        previewOptionsLayout = qt.QHBoxLayout()
        previewOptionsLayout.addWidget(qt.QLabel("Top Depth (m):"))
        previewOptionsLayout.addWidget(self.depthTopSpinBox)
        previewOptionsLayout.addWidget(qt.QLabel("Bottom Depth (m):"))
        previewOptionsLayout.addWidget(self.depthBottomSpinBox)
        previewOptionsLayout.addWidget(qt.QLabel("Dimension:"))
        previewOptionsLayout.addWidget(self.previewDimensionSpinBox)
        previewOptionsLayout.setContentsMargins(0, 0, 0, 0)

        self.previewOptionsWidget = qt.QWidget()
        self.previewOptionsWidget.setLayout(previewOptionsLayout)
        self.previewOptionsWidget.enabled = False
        self.previewOptionsWidget.objectName = "previewOptionsWidget"

        previewLayout = qt.QHBoxLayout()
        previewLayout.setContentsMargins(0, 0, 0, 0)
        previewLayout.addWidget(self.previewOptionsWidget)
        previewLayout.addWidget(self.previewButton)
        previewLayout.setContentsMargins(0, 0, 0, 0)

        self.previewWidget = qt.QWidget()
        self.previewWidget.setLayout(previewLayout)
        self.previewWidget.hide()
        self.previewWidget.objectName = "previewWidget"
        self.previewLabel = qt.QLabel("Hard Data preview:")
        self.previewLabel.hide()

        self.enableWrapCheckBox = qt.QCheckBox()
        self.enableWrapCheckBox.setText("Wrap cylinder")
        self.enableWrapCheckBox.objectName = "enableWrapCheckBox"
        self.enableWrapCheckBox.setToolTip(
            "If checked, the 2D data will be wrapped into a cylinder, allowing for 3D simulation."
        )
        self.enableWrapCheckBox.enabled = False

        self.continuousDataCheckBox = qt.QCheckBox()
        self.continuousDataCheckBox.setText("Continuous data")
        self.continuousDataCheckBox.objectName = "continuousDataCheckBox"
        self.continuousDataCheckBox.setToolTip(
            "If checked, the data is considered continuous instead of discrete. In this case, the reference volume will be used in the simulation as \
            continuous data for both the training image and hard data. For the training image input, unselected segments will be changed to np.nan, \
            and for the hard data input, the unselected segments areas are not going to be considered hard data."
        )

        dataOptionsLayout = qt.QHBoxLayout()
        dataOptionsLayout.addWidget(self.enableWrapCheckBox)
        dataOptionsLayout.addWidget(self.continuousDataCheckBox)
        dataOptionsLayout.setContentsMargins(0, 0, 0, 0)

        dataOptionsWidgets = qt.QWidget()
        dataOptionsWidgets.setLayout(dataOptionsLayout)

        self.maskWidget = widgets.SingleShotInputWidget(
            hideSoi=True,
            hideCalcProp=False,
            allowedInputNodes=[
                "vtkMRMLSegmentationNode",
                "vtkMRMLLabelMapVolumeNode",
            ],
            mainName="Mask image",
            referenceName="Mask reference",
            setDefaultMargins=False,
            objectNamePrefix="Mask",
        )
        self.maskWidget.formLayout.setContentsMargins(0, 0, 0, 0)

        self.maskWidget.mainInput.currentItemChanged.connect(self.onMaskChange)
        self.maskWidget.onReferenceSelectedSignal.connect(self.updateFinalImageWidgets)
        self.maskWidget.segmentListGroup[1].itemChanged.connect(lambda: self.listItemChange())

        inputFormLayout = qt.QFormLayout(inputSection)
        inputFormLayout.addRow(self.trainingImageWidget)
        inputFormLayout.addRow("", None)
        inputFormLayout.addRow(self.hardDataWidget)
        inputFormLayout.addRow(self.hardDataResolutionLabel, self.hardDataResolutionText)
        inputFormLayout.addRow(self.previewLabel, self.previewWidget)
        inputFormLayout.addRow("", None)
        inputFormLayout.addRow(self.maskWidget)
        inputFormLayout.addRow("", dataOptionsWidgets)

        # Parameters section
        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False
        parametersSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)
        parametersLayout = qt.QFormLayout(parametersSection)

        self.imageSpacingValidator = qt.QRegExpValidator(qt.QRegExp("[+]?[0-9]*\\.?[0-9]{0,5}([eE][-+]?[0-9]+)?"))

        self.finalImageResolution = []
        self.finalImageSize = []
        for _ in range(3):
            dimensionBoxImageResolution = qt.QLineEdit()
            dimensionBoxImageResolution.objectName = f"finalImageResolution_{_}"
            dimensionBoxImageResolution.setValidator(self.imageSpacingValidator)
            self.finalImageResolution.append(dimensionBoxImageResolution)

            dimensionBoxImageSize = qt.QSpinBox()
            dimensionBoxImageSize.objectName = f"finalImageSize_{_}"
            dimensionBoxImageSize.setRange(1, 99999)
            dimensionBoxImageSize.setToolTip("Dimensions of the output 3D image")
            self.finalImageSize.append(dimensionBoxImageSize)

        self.finalImageResolution[0].setToolTip(
            "Voxel size of the output image (x axis) in mm. For the multiscale simulations, the units are converted to micrometers. The spacing will be rounded to 5 decimal places of the mm unit due to the algorithms limitation."
        )
        self.finalImageResolution[1].setToolTip(
            "Voxel size of the output image (y axis) in mm. For the multiscale simulations, the units are converted to micrometers. The spacing will be rounded to 5 decimal places of the mm unit due to the algorithms limitation."
        )
        self.finalImageResolution[2].setToolTip(
            "Voxel size of the output image (z axis) in mm. For the multiscale simulations, the units are converted to micrometers. The spacing will be rounded to 5 decimal places of the mm unit due to the algorithms limitation."
        )

        finalImageResolutionLayout = qt.QHBoxLayout()
        finalImageSizeLayout = qt.QHBoxLayout()
        for dim in range(3):
            finalImageResolutionLayout.addWidget(self.finalImageResolution[dim], 1)
            finalImageSizeLayout.addWidget(self.finalImageSize[dim])
            if dim < 2:
                finalImageResolutionLayout.addWidget(qt.QLabel("x"))
                finalImageSizeLayout.addWidget(qt.QLabel("x"))

        finalImageResolutionLayout.setContentsMargins(0, 0, 0, 0)
        finalImageSizeLayout.setContentsMargins(0, 0, 0, 0)
        finalImageSizeLayout.addStretch()

        self.finalImageResolutionWidget = qt.QWidget()
        self.finalImageResolutionWidget.setMaximumWidth(400)
        self.finalImageResolutionWidget.setLayout(finalImageResolutionLayout)
        self.finalImageSizeWidget = qt.QWidget()
        self.finalImageSizeWidget.setLayout(finalImageSizeLayout)

        parametersLayout.addRow("Final image resolution (mm):", self.finalImageResolutionWidget)
        parametersLayout.addRow("Final image dimensions:", self.finalImageSizeWidget)

        self.ncondSpinBox = qt.QSpinBox()
        self.ncondSpinBox.setToolTip("Set number of conditiong points used in each simulation.")
        self.ncondSpinBox.setRange(1, 9999)
        self.ncondSpinBox.setValue(16)
        self.ncondSpinBox.objectName = "conditioningsNumber"

        self.nrealSpinBox = qt.QSpinBox()
        self.nrealSpinBox.setToolTip(
            "Set number of realizations to be done. Maximum value accepted is total number of available threads minus 1"
        )
        self.nrealSpinBox.setRange(1, 9999)
        self.nrealSpinBox.setValue(cpu_count() - 1)
        self.nrealSpinBox.objectName = "realizationsNumber"

        self.maxIterationsCheckBox = qt.QCheckBox()
        self.maxIterationsCheckBox.setChecked(True)
        self.maxIterationsCheckBox.stateChanged.connect(self.onMaxIterationsCheckBoxChange)
        self.maxIterationsCheckBox.objectName = "maxIterationsCheckBox"
        self.maxIterationsCheckBox.setToolTip(
            "If checked, the chosen max iterations will be used. If left unchecked, the value used will be -1 (whole training image)"
        )
        self.maxIterationsSpinBox = qt.QSpinBox()
        self.maxIterationsSpinBox.setRange(-1, 999999)
        self.maxIterationsSpinBox.setValue(1000)
        self.maxIterationsSpinBox.setToolTip(
            "Set the maximun number of iterations. Use -1 for a full training image scan."
        )
        self.maxIterationsSpinBox.objectName = "maxIterationsValue"

        self.rseedCheckBox = qt.QCheckBox()
        self.rseedCheckBox.stateChanged.connect(self.onRseedCheckBoxChange)
        self.rseedCheckBox.objectName = "randomSeedCheckBox"
        self.rseedCheckBox.setToolTip(
            "If checked, the chosen random seed will be used. If left unchecked, the random seed will be 0"
        )
        self.rseedSpinBox = qt.QSpinBox()
        self.rseedSpinBox.setDisabled(True)
        self.rseedSpinBox.setToolTip(
            "Set a seed value. Use the same value to obtain the same results. Use 0 for random seed"
        )
        self.rseedSpinBox.objectName = "randomSeedValue"

        self.colocateDimensionComboBox = qt.QComboBox()
        self.colocateDimensionComboBox.addItems(list(COLOCATE_DIMENSIONS.keys()))
        self.colocateDimensionComboBox.setToolTip("For a 3D TI make sure the order matters in the last dimensions")
        self.colocateDimensionComboBox.objectName = "colocateDimension"

        max_search_value = 10000
        self.maxSearchRadiusSpinBox = qt.QDoubleSpinBox()
        self.maxSearchRadiusSpinBox.setRange(0, max_search_value)
        self.maxSearchRadiusSpinBox.setValue(max_search_value)
        self.maxSearchRadiusSpinBox.setDecimals(3)
        self.maxSearchRadiusSpinBox.setToolTip(
            "Only conditional data within a radius of max search radius is used as conditioning data."
        )
        self.maxSearchRadiusSpinBox.objectName = "maxSearchRadius"

        self.distanceMaxSpinBox = qt.QDoubleSpinBox()
        self.distanceMaxSpinBox.setRange(0, 1.0)
        self.distanceMaxSpinBox.setSingleStep(0.1)
        self.distanceMaxSpinBox.setDecimals(3)
        self.distanceMaxSpinBox.setValue(0)
        self.distanceMaxSpinBox.setToolTip(
            "Maximum distance what will lead to accepting a conditional template match. If set to 0, it will search of a perfect match."
        )
        self.distanceMaxSpinBox.objectName = "distanceMax"

        self.distancePowerSpinBox = qt.QSpinBox()
        self.distancePowerSpinBox.setRange(0, 2)
        self.distancePowerSpinBox.setToolTip(
            "Set the distace power to weight the conditioning data. Use 0 for no weight. Higher values favors data value of conditional events closer to the center value."
        )
        self.distancePowerSpinBox.objectName = "distancePower"

        parametersLayout.addRow("Number of conditioning points:", self.ncondSpinBox)
        parametersLayout.addRow("Number of realizations:", self.nrealSpinBox)
        parametersLayout.addRow("Use max iterations?", self.maxIterationsCheckBox)
        parametersLayout.addRow("Number of iterations:", self.maxIterationsSpinBox)
        parametersLayout.addRow("Use random seed?", self.rseedCheckBox)
        parametersLayout.addRow("Random seed:", self.rseedSpinBox)
        parametersLayout.addRow("Colocate dimension:", self.colocateDimensionComboBox)
        parametersLayout.addRow("Max search radius (mm):", self.maxSearchRadiusSpinBox)
        parametersLayout.addRow("Max distance (normalized):", self.distanceMaxSpinBox)
        parametersLayout.addRow("Distance power:", self.distancePowerSpinBox)

        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.objectName = "outputPrefix"
        self.outputPrefix.textChanged.connect(self.checkRunButtonState)
        self.outputPrefix.setToolTip("Name of the volumes and file that will be generated")

        self.saveSingleRealizationCheckBox = qt.QCheckBox()
        self.saveSingleRealizationCheckBox.setText("First realization")
        self.saveSingleRealizationCheckBox.setToolTip("If checked, only the first realization will be saved as volume.")
        self.saveSingleRealizationCheckBox.objectName = "saveSingle"
        self.saveSingleRealizationCheckBox.setChecked(qt.Qt.Checked)
        self.saveSingleRealizationCheckBox.stateChanged.connect(
            lambda state: self.onSaveAsVolumeCheckBoxChange(state, True)
        )

        self.saveAllRealizationAsVolumeCheckBox = qt.QCheckBox()
        self.saveAllRealizationAsVolumeCheckBox.setText("All realizations")
        self.saveAllRealizationAsVolumeCheckBox.setToolTip(
            "If checked, each realization will be saved as a single volume node. May be RAM intensive"
        )
        self.saveAllRealizationAsVolumeCheckBox.objectName = "saveAsVolume"
        self.saveAllRealizationAsVolumeCheckBox.stateChanged.connect(
            lambda state: self.onSaveAsVolumeCheckBoxChange(state, False)
        )

        self.saveAllRealizationAsSequenceCheckBox = qt.QCheckBox()
        self.saveAllRealizationAsSequenceCheckBox.setText("As sequence")
        self.saveAllRealizationAsSequenceCheckBox.setToolTip(
            "If checked, all of the realizations outputs will be added to a single sequence node. May be RAM intensive"
        )
        self.saveAllRealizationAsSequenceCheckBox.setChecked(qt.Qt.Checked)
        self.saveAllRealizationAsSequenceCheckBox.objectName = "saveAsSequence"
        self.saveAllRealizationAsSequenceCheckBox.stateChanged.connect(self.checkRunButtonState)

        self.saveAllRealizationAsFileCheckBox = qt.QCheckBox()
        self.saveAllRealizationAsFileCheckBox.setText("TIF files")
        self.saveAllRealizationAsFileCheckBox.stateChanged.connect(self.onSaveAllRealizationAsFileCheckBox)
        self.saveAllRealizationAsFileCheckBox.setToolTip(
            "If checked, all of the realizations will be exported as TIFF files to the selected directory"
        )
        self.saveAllRealizationAsFileCheckBox.objectName = "saveAsFile"

        saveOptionsLayout = qt.QHBoxLayout()
        saveOptionsLayout.setContentsMargins(0, 0, 0, 0)
        saveOptionsLayout.addWidget(self.saveSingleRealizationCheckBox)
        saveOptionsLayout.addWidget(self.saveAllRealizationAsVolumeCheckBox)
        saveOptionsLayout.addWidget(self.saveAllRealizationAsSequenceCheckBox)
        saveOptionsLayout.addWidget(self.saveAllRealizationAsFileCheckBox)

        self.saveOptionsWidgets = qt.QWidget()
        self.saveOptionsWidgets.setLayout(saveOptionsLayout)

        self.exportDirectoryButton = ctk.ctkDirectoryButton()
        self.exportDirectoryButton.setMaximumWidth(374)
        self.exportDirectoryButton.caption = "Export directory"
        self.exportDirectoryButton.setDisabled(True)
        self.exportDirectoryButton.objectName = "fileDirectory"

        outputFormLayout = qt.QFormLayout(outputSection)
        outputFormLayout.addRow("Output prefix:", self.outputPrefix)
        outputFormLayout.addRow("Save:", self.saveOptionsWidgets)
        outputFormLayout.addRow("Export directory:", self.exportDirectoryButton)

        self.runButton = qt.QPushButton("Run")
        self.runButton.objectName = "runSequentialButton"
        self.runButton.enabled = False
        self.runButton.setFixedHeight(40)
        self.runButton.clicked.connect(lambda: self.runLogic(False))
        self.runButton.setToolTip("Run Generalized ENESIM sequential algorithm")

        self.runParallelButton = qt.QPushButton("Run Parallel")
        self.runParallelButton.objectName = "runParallelButton"
        self.runParallelButton.enabled = False
        self.runParallelButton.setFixedHeight(40)
        self.runParallelButton.clicked.connect(lambda: self.runLogic(True))
        self.runParallelButton.setToolTip("Run Generalized ENESIM parallel algorithm")

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.enabled = False
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.clicked.connect(self.onCancel)
        self.cancelButton.objectName = "cancelButton"
        self.cancelButton.setToolTip(
            "Interrupt and cancel the execution of the algorithm. This is only available when running the parallel algorithm."
        )

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.runButton)
        buttonsHBoxLayout.addWidget(self.runParallelButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)

        self.localProgressBar = LocalProgressBar()
        self.localProgressBar.progressBar.setStatusVisibility(0)

        self.statusLabel = qt.QLabel("Status: Idle")
        self.statusLabel.setVisible(False)
        self.statusLabel.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        self.statusLabel.objectName = "MPS Time QLabel"

        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addLayout(buttonsHBoxLayout)
        self.layout.addWidget(self.statusLabel)
        self.layout.addWidget(self.localProgressBar)
        self.layout.addStretch(1)

    def onSaveAllRealizationAsFileCheckBox(self):
        self.exportDirectoryButton.setEnabled(self.saveAllRealizationAsFileCheckBox.isChecked())
        self.checkRunButtonState()

    def onMaxIterationsCheckBoxChange(self):
        self.maxIterationsSpinBox.setEnabled(self.maxIterationsCheckBox.isChecked())

    def onRseedCheckBoxChange(self):
        self.rseedSpinBox.setEnabled(self.rseedCheckBox.isChecked())

    def onSaveAsVolumeCheckBoxChange(self, state, saveSingle):
        if state == qt.Qt.Checked:
            if saveSingle:
                self.saveAllRealizationAsVolumeCheckBox.setChecked(qt.Qt.Unchecked)
            else:
                self.saveSingleRealizationCheckBox.setChecked(qt.Qt.Unchecked)
        self.checkRunButtonState()

    def updateFinalImageWidgets(self, node):
        self.updateOutputPrefix()
        enableWidgets = True
        if self.maskWidget.referenceInput.currentNode() is not None:
            if node != self.maskWidget.referenceInput.currentNode():
                return
            enableWidgets = False
        elif node is None and self.trainingImageWidget.referenceInput.currentNode() is not None:
            node = self.trainingImageWidget.referenceInput.currentNode()

        dimensions = [0, 0, 0]
        spacing = [0, 0, 0]
        rseedMax = 100

        if node is not None:
            spacing = node.GetSpacing()
            dimensions = node.GetImageData().GetDimensions()
            rseedMax = min(dimensions[0] * dimensions[1] * dimensions[2], 2147483647)

        for dim in range(3):
            self.finalImageResolution[dim].setText(round(spacing[dim], 5))
            self.finalImageResolution[dim].enabled = enableWidgets
            self.finalImageSize[dim].setValue(dimensions[dim])
            self.finalImageSize[dim].enabled = enableWidgets
            self.rseedSpinBox.setRange(0, rseedMax)

    def onReferenceChange(self, node=None):
        self.enableWrapCheckBox.enabled = False
        self.enableWrapCheckBox.setChecked(qt.Qt.Unchecked)
        self.updateHardDataResolution(None)
        self.setPreviewValues()
        if node:
            self.hardDataResolution = np.array(node.GetSpacing())
            self.updateHardDataResolution(self.hardDataResolution)
            if node.GetImageData().GetDimensions()[1] == 1:
                self.setPreviewValues(True, node)
                self.enableWrapCheckBox.enabled = True
            else:
                self.setPreviewValues(False, node)
        self.checkRunButtonState()

    def onHardDataChange(self, nodeID):
        self.changePreviewOptionsVisibility()
        self.checkListItems(self.hardDataWidget.segmentListGroup[1])

        node = self.hardDataWidget.mainInput.currentNode()
        if node:
            if isinstance(node, slicer.vtkMRMLLabelMapVolumeNode) or isinstance(node, slicer.vtkMRMLSegmentationNode):
                self.changePreviewOptionsVisibility(True)

            background = None
            if isinstance(node, slicer.vtkMRMLScalarVolumeNode):
                background = node

            elif isinstance(node, slicer.vtkMRMLSegmentationNode):
                sourceVolumeNode = helpers.getSourceVolume(self.hardDataWidget.mainInput.currentNode())
                if sourceVolumeNode:
                    background = sourceVolumeNode

            slicer.util.setSliceViewerLayers(
                background=background,
                label=node if isinstance(node, slicer.vtkMRMLLabelMapVolumeNode) else None,
                fit=True,
            )

            if self.isViewOn:
                with ProgressBarProc() as progressBar:
                    self.changePreviewState(progressBar)

        self.updateOutputPrefix()
        self.updateInputWidgetsVisibility()

    def onMaskChange(self):
        self.updateInputWidgetsVisibility()
        self.updateOutputPrefix()
        self.checkRunButtonState()

    def updateInputWidgetsVisibility(self):
        showHardData = True
        showMask = True

        if self.hardDataWidget.mainInput.currentNode() is not None:
            showMask = False
        else:
            if self.maskWidget.mainInput.currentNode() is not None:
                showHardData = False

        self.hardDataWidget.setVisible(showHardData)
        self.hardDataWidget.enabled = showHardData
        self.maskWidget.setVisible(showMask)
        self.maskWidget.enabled = showMask

    def updateOutputPrefix(self):
        text = ""
        if self.hardDataWidget.mainInput.currentNode() is not None:
            text = f"{self.hardDataWidget.mainInput.currentNode().GetName()}_multiscale"
        elif self.maskWidget.mainInput.currentNode() is not None:
            text = f"{self.maskWidget.mainInput.currentNode().GetName()}_multiscale"
        elif self.trainingImageWidget.mainInput.currentNode() is not None:
            text = f"{self.trainingImageWidget.mainInput.currentNode().GetName()}_multiscale"

        self.outputPrefix.text = text

    def onTrainingImageChange(self):
        self.checkListItems(self.trainingImageWidget.segmentListGroup[1])

    def checkListItems(self, segmentList):
        if segmentList.visible:
            for item in range(segmentList.count):
                segmentList.item(item).setCheckState(qt.Qt.Checked)
        self.updateContinuousCheckBoxState()
        self.checkRunButtonState()

    def changeRunButtonsState(self, state):
        self.runButton.enabled = state
        self.runButton.blockSignals(not state)
        self.runParallelButton.enabled = state
        self.runParallelButton.blockSignals(not state)

    def checkRunButtonState(self):
        trainingImageisValid = (
            self.trainingImageWidget.mainInput.currentNode() is not None
            and self.trainingImageWidget.referenceInput.currentNode() is not None
            and (
                isinstance(self.trainingImageWidget.mainInput.currentNode(), slicer.vtkMRMLScalarVolumeNode)
                or len(self.trainingImageWidget.getSelectedSegments()) > 0
            )
        )

        hardDataIsValid = True
        if self.hardDataWidget.mainInput.currentNode() is not None:
            hardDataIsValid = self.hardDataWidget.referenceInput.currentNode() is not None and (
                type(self.hardDataWidget.mainInput.currentNode()) is slicer.vtkMRMLScalarVolumeNode
                or len(self.trainingImageWidget.getSelectedSegments()) > 0
            )

        maskIsValid = True
        if self.maskWidget.mainInput.currentNode() is not None:
            maskIsValid = len(self.maskWidget.getSelectedSegments()) > 0

        saveOptionSelected = (
            self.saveSingleRealizationCheckBox.isChecked()
            or self.saveAllRealizationAsVolumeCheckBox.isChecked()
            or self.saveAllRealizationAsSequenceCheckBox.isChecked()
            or self.saveAllRealizationAsFileCheckBox.isChecked()
        )

        if (
            trainingImageisValid
            and hardDataIsValid
            and maskIsValid
            and self.outputPrefix.text.replace(" ", "") != ""
            and saveOptionSelected
        ):
            self.changeRunButtonsState(True)
        else:
            self.changeRunButtonsState(False)

    def runLogic(self, isParallel):
        with ProgressBarProc() as progressBar:
            if self.isViewOn:
                self.changePreviewState(progressBar)

            TISegmentation = False
            hardDataSegmentation = False
            maskSegmentation = False
            if isinstance(self.trainingImageWidget.mainInput.currentNode(), slicer.vtkMRMLSegmentationNode):
                TISegmentation = True
                trainingImageLabelMap = self.segmentationInputToLabelmap(
                    self.trainingImageWidget.mainInput.currentNode(), "_TI"
                )

            if isinstance(self.hardDataWidget.mainInput.currentNode(), slicer.vtkMRMLSegmentationNode):
                hardDataSegmentation = True
                hardDataLabelMap = self.segmentationInputToLabelmap(self.hardDataWidget.mainInput.currentNode(), "_HD")
                self.hardDataResolution = np.array(hardDataLabelMap.GetSpacing())

            if isinstance(self.maskWidget.mainInput.currentNode(), slicer.vtkMRMLSegmentationNode):
                maskSegmentation = True
                maskLabelMap = self.segmentationInputToLabelmap(self.maskWidget.mainInput.currentNode(), "_mask")

            try:
                self.changeRunButtonsState(False)

                preprocessing = {
                    "trainingDataVolume": (
                        trainingImageLabelMap if TISegmentation else self.trainingImageWidget.mainInput.currentNode()
                    ),
                    "trainingReference": (
                        self.trainingImageWidget.referenceInput.currentNode()
                        if self.continuousDataCheckBox.isChecked()
                        else None
                    ),
                    "trainingDataSegments": [segment + 1 for segment in self.trainingImageWidget.getSelectedSegments()],
                    "wrapCylinder": self.enableWrapCheckBox.isChecked(),
                }

                if self.hardDataWidget.mainInput.currentNode() is not None:
                    preprocessing["hardDataVolume"] = (
                        hardDataLabelMap if hardDataSegmentation else self.hardDataWidget.mainInput.currentNode()
                    )
                    preprocessing["hardDataReference"] = (
                        self.hardDataWidget.referenceInput.currentNode()
                        if self.continuousDataCheckBox.isChecked()
                        else None
                    )
                    preprocessing["hardDataValues"] = [
                        segment + 1 for segment in self.hardDataWidget.getSelectedSegments()
                    ]
                    preprocessing["hardDataResolution"] = self.hardDataResolution

                if self.maskWidget.mainInput.currentNode() is not None:
                    preprocessing.update(
                        {
                            "maskVolume": maskLabelMap if maskSegmentation else self.maskWidget.mainInput.currentNode(),
                            "maskSegments": [segment + 1 for segment in self.maskWidget.getSelectedSegments()],
                        }
                    ),
                    if self.continuousDataCheckBox.isChecked():
                        preprocessing.update({"maskReference": self.maskWidget.referenceInput.currentNode()}),
                    else:
                        preprocessing.update(
                            {
                                "trainingImageSegmentList": helpers.getSegmentList(
                                    self.trainingImageWidget.mainInput.currentNode()
                                ),
                                "maskSegmentList": helpers.getSegmentList(self.maskWidget.mainInput.currentNode()),
                            }
                        ),

                nreal = self.nrealSpinBox.value
                if self.saveSingleRealizationCheckBox.isChecked() and not (
                    self.saveAllRealizationAsSequenceCheckBox.isChecked()
                    or self.saveAllRealizationAsVolumeCheckBox.isChecked()
                    or self.saveAllRealizationAsFileCheckBox.isChecked()
                ):
                    nreal = 1

                gridResolution = np.array([float(box.text) for box in self.finalImageResolution])
                gridDimensions = np.array([box.value for box in self.finalImageSize])
                flipAxis = False

                tiDimensions = preprocessing["trainingDataVolume"].GetImageData().GetDimensions()
                if tiDimensions[2] > tiDimensions[0]:
                    flipAxis = True

                if self.continuousDataCheckBox.isChecked() and "hardDataReference" in preprocessing:
                    hardDataDimensions = preprocessing["hardDataReference"].GetImageData().GetDimensions()
                    if hardDataDimensions[2] > gridDimensions[0]:
                        flipAxis = True

                elif "maskVolume" in preprocessing and gridDimensions[2] > gridDimensions[0]:
                    flipAxis = True

                if flipAxis:
                    gridResolution = np.flip(gridResolution)
                    gridDimensions = np.flip(gridDimensions)

                mpsConfiguration = {
                    "finalImageResolution": gridResolution,
                    "finalImageSize": gridDimensions,
                    "ncond": self.ncondSpinBox.value,
                    "nreal": nreal,
                    "iterations": self.maxIterationsSpinBox.value if self.maxIterationsCheckBox.isChecked() else -1,
                    "rseed": self.rseedSpinBox.value if self.rseedCheckBox.isChecked() else 0,
                    "colocate_dimensions": COLOCATE_DIMENSIONS[self.colocateDimensionComboBox.currentText],
                    "max_search_radius": int(self.maxSearchRadiusSpinBox.value * 1000),
                    "distance_max": self.distanceMaxSpinBox.value,
                    "distance_power": self.distancePowerSpinBox.value,
                    "distance_measure": self.continuousDataCheckBox.isChecked(),
                }

                saveOptions = {
                    "flipAxis": flipAxis,
                    "saveSingleVolume": self.saveSingleRealizationCheckBox.isChecked(),
                    "saveAllAsSequence": self.saveAllRealizationAsSequenceCheckBox.isChecked(),
                    "saveAllAsVolume": self.saveAllRealizationAsVolumeCheckBox.isChecked(),
                    "saveAllAsFile": self.saveAllRealizationAsFileCheckBox.isChecked(),
                    "name": self.outputPrefix.text.strip(),
                    "directory": self.exportDirectoryButton.directory,
                }

                self.logic.runMultiscale(
                    preprocessing,
                    mpsConfiguration,
                    saveOptions,
                    isParallel,
                    self.localProgressBar,
                    progressBar,
                )

                if isParallel:
                    self.cancelButton.enabled = True
                else:
                    self.changeRunButtonsState(True)
            except:
                self.changeRunButtonsState(True)

    def segmentationInputToLabelmap(self, segmentationNode, volumeType=""):
        labelmapVolumeNode = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLLabelMapVolumeNode", f"{segmentationNode.GetName()}{volumeType}_TMP_LABEL"
        )
        slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
            segmentationNode, labelmapVolumeNode, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
        )
        labelmapVolumeNode.SetAttribute("NodeEnvironment", self.logic.__class__.__name__)
        labelmapVolumeNode.GetDisplayNode().GetColorNode().SetAttribute(
            "NodeEnvironment", self.logic.__class__.__name__
        )
        helpers.makeNodeTemporary(labelmapVolumeNode, hide=True)
        helpers.makeNodeTemporary(labelmapVolumeNode.GetDisplayNode().GetColorNode(), hide=True)
        return labelmapVolumeNode

    def updateHardDataResolution(self, spacing):
        if spacing is not None:
            self.hardDataResolutionText.setText(f"{spacing[0]:.3f} x {spacing[1]:.3f} x {spacing[2]:.3f} (mm)")
            self.hardDataResolutionText.show()
            self.hardDataResolutionLabel.show()
        else:
            self.hardDataResolutionText.setText("0 x 0 x 0 (mm)")
            self.hardDataResolutionText.hide()
            self.hardDataResolutionLabel.hide()

    def getPreviewSegmentationNode(self):
        node = self.hardDataWidget.mainInput.currentNode()
        if isinstance(node, slicer.vtkMRMLSegmentationNode):
            hardDataLabelMap, _ = helpers.createLabelmapInput(node, "previewLabelmap")
            if hardDataLabelMap.GetImageData().GetDimensions()[1] == 1:
                self.previewSegmentationNode = self.logic.generatePreview(
                    hardDataLabelMap,
                    self.previewDimensionSpinBox.value,
                    self.depthTopSpinBox.value,
                    self.depthBottomSpinBox.value,
                )
            else:
                slicer.util.setSliceViewerLayers(background=None, label=hardDataLabelMap, fit=True)
                self.previewSegmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
                slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                    hardDataLabelMap, self.previewSegmentationNode
                )
                self.previewSegmentationNode.SetName("previewSegmentation")
                helpers.makeNodeTemporary(self.previewSegmentationNode, hide=True)

        elif isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
            if node.GetImageData().GetDimensions()[1] == 1:
                self.previewSegmentationNode = self.logic.generatePreview(
                    node,
                    self.previewDimensionSpinBox.value,
                    self.depthTopSpinBox.value,
                    self.depthBottomSpinBox.value,
                )
            else:
                slicer.util.setSliceViewerLayers(background=None, label=node, fit=True)
                self.previewSegmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
                slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                    node, self.previewSegmentationNode
                )
                self.previewSegmentationNode.SetName("previewSegmentation")
                helpers.makeNodeTemporary(self.previewSegmentationNode, hide=True)

        else:
            raise TypeError("Cannot create preview of the the selected input")

    def onViewPreviewToggle(self):
        with ProgressBarProc() as progressBar:
            self.changePreviewState(progressBar)

    def changePreviewState(self, progressBar):
        if not self.isViewOn:
            progressBar.setMessage("Generating preview")
            try:
                self.getPreviewSegmentationNode()
            except TypeError:
                self.previewButton.enabled = False

            self.previewSegmentationNode.GetSegmentation().SetConversionParameter("Smoothing factor", "0.0")
            displayNode = self.previewSegmentationNode.GetDisplayNode()
            displayNode.SetOpacity(1)

            self.checkSegmentsVisibility(displayNode)

            self.previewSegmentationNode.CreateClosedSurfaceRepresentation()

            self.previewButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeOpen.png"))
            self.isViewOn = True

        elif self.isViewOn:
            progressBar.setMessage("Removing preview")
            self.previewSegmentationNode.RemoveClosedSurfaceRepresentation()
            helpers.removeTemporaryNodes()
            self.previewButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeClosed.png"))
            self.isViewOn = False

    def checkSegmentsVisibility(self, displayNode):
        for n in range(self.hardDataWidget.segmentListGroup[1].count):
            if not self.hardDataWidget.segmentListGroup[1].item(n).checkState() == qt.Qt.Checked:
                displayNode.SetSegmentOpacity(self.hardDataWidget.segmentListGroup[1].item(n).text(), 0)

    def onSegmentVisibilityChange(self, id, isVisible):
        if self.isViewOn:
            displayNode = self.previewSegmentationNode.GetDisplayNode()
            displayNode.SetSegmentOpacity(id, 1 if isVisible else 0)

    def listItemChange(self, item=None):
        self.trainingImageWidget.dimensionsGroup.hide()
        self.checkRunButtonState()
        if item and self.isViewOn:
            self.onSegmentVisibilityChange(item.text(), item.checkState() == qt.Qt.Checked)

    def changePreviewOptionsVisibility(self, isVisible: bool = False):
        self.previewLabel.setVisible(isVisible)
        self.previewWidget.setVisible(isVisible)
        self.previewButton.enabled = isVisible

    def updateContinuousCheckBoxState(self):
        tiScalar = False
        hardDataScalar = False
        if self.trainingImageWidget.mainInput.currentNode() is not None:
            tiScalar = self.trainingImageWidget.mainInput.currentNode().GetClassName() == "vtkMRMLScalarVolumeNode"
        if self.hardDataWidget.mainInput.currentNode() is not None:
            hardDataScalar = self.hardDataWidget.mainInput.currentNode().GetClassName() == "vtkMRMLScalarVolumeNode"

        isScalar = tiScalar or hardDataScalar

        self.continuousDataCheckBox.enabled = not isScalar
        if isScalar:
            self.continuousDataCheckBox.setChecked(qt.Qt.Checked)
            self.isContinuousCheckBoxLocked = True
        elif self.isContinuousCheckBoxLocked:
            self.isContinuousCheckBoxLocked = False
            self.continuousDataCheckBox.setChecked(qt.Qt.Unchecked)

    def setPreviewValues(self, enableOptions: bool = False, node=None):
        start = 0
        end = 0
        step = 1

        if node is not None:
            origins = -np.array(node.GetOrigin()) / 1000
            spacing = np.array(node.GetSpacing()) / 1000
            dimensions = np.array(node.GetImageData().GetDimensions())
            start = origins[2]
            end = origins[2] + dimensions[2] * spacing[2]
            step = spacing[2]

        self.previewOptionsWidget.enabled = enableOptions
        self.depthTopSpinBox.setRange(start, end)
        self.depthTopSpinBox.setValue(start)
        self.depthTopSpinBox.setSingleStep(step)
        self.depthBottomSpinBox.setRange(start, end)
        self.depthBottomSpinBox.setValue(end)
        self.depthBottomSpinBox.setSingleStep(step)

    def onCancel(self):
        self.logic.cancelCLI()
        self.cancelButton.enabled = False

    def onCLIEvent(self):
        self.cancelButton.enabled = False
        self.changeRunButtonsState(True)

    def updateTime(self, time):
        self.statusLabel.setVisible(True)
        self.updateStatusLabel("Completed", f" (MPSlib execution took {time:.2f} seconds)")

    def updateStatusLabel(self, status, text=""):
        self.statusLabel.text = f"Status: {status}{text}"


class MultiScaleLogic(LTracePluginLogic):
    def __init__(self, widget):
        LTracePluginLogic.__init__(self)
        self.image = []
        self.time = 0
        self.cliNode = None
        self.widget = widget
        self.outputName = ""
        self.outputDir = 0
        self.save_options = {}
        self.mask_options = {}
        self.cliObserver = None

    def configureOutput(self, outputPrefix):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        parentItemId = subjectHierarchyNode.GetSceneItemID()
        dirLabel = "Multiscale Results"
        mainDir = subjectHierarchyNode.GetItemByName(dirLabel)
        if not mainDir:
            mainDir = subjectHierarchyNode.CreateFolderItem(parentItemId, dirLabel)

        folderDirName = subjectHierarchyNode.GenerateUniqueItemName(outputPrefix)
        folderDir = subjectHierarchyNode.GetItemByName(folderDirName)
        if not folderDir:
            folderDir = subjectHierarchyNode.CreateFolderItem(mainDir, folderDirName)

        self.outputName = folderDirName
        self.outputDir = folderDir

    def getScalarVolumeValues(self, volume):
        values = set()
        for i, slice in enumerate(slicer.util.arrayFromVolume(volume)):
            values.update(np.unique(slice))
        return np.sort(list(values))

    def mps_preprocessing(self, data: dict, isContinuous: bool, sequentialProgressBar: object):
        """
        Method responsible for the steps before the mps execution, including:
        - Replacing unselected segments with np.nan in the ti.dat
        - Creating necessary files: ti.dat and hard.dat
        """
        sequentialProgressBar.setMessage("Writing TI data file")

        invertHDSelectedSegments = False
        invertTISelectedSegments = False
        nullValueHD = 0
        selectedSegmentsTI = data["trainingDataSegments"]

        if isContinuous:
            simulationTI = slicer.util.arrayFromVolume(data["trainingReference"])
            if "hardDataVolume" in data:
                SimulationHD = data["hardDataReference"]

                if (
                    type(data["hardDataVolume"]) is slicer.vtkMRMLScalarVolumeNode
                    and data["hardDataVolume"] == data["hardDataReference"]
                ):
                    nullValueHD = helpers.getVolumeNullValue(SimulationHD)
                    if nullValueHD:
                        invertHDSelectedSegments = True

            if (
                type(data["trainingDataVolume"]) is slicer.vtkMRMLScalarVolumeNode
                and data["trainingDataVolume"] == data["trainingReference"]
            ):
                nullValueTI = helpers.getVolumeNullValue(data["trainingReference"])
                if nullValueTI:
                    invertTISelectedSegments = True
                    selectedSegmentsTI = [nullValueTI]

        else:
            simulationTI = slicer.util.arrayFromVolume(data["trainingDataVolume"])
            if "hardDataVolume" in data:
                SimulationHD = data["hardDataVolume"]

        if selectedSegmentsTI:
            mask = slicer.util.arrayFromVolume(data["trainingDataVolume"])
            filteredArray = np.where(
                np.isin(mask, selectedSegmentsTI, invert=invertTISelectedSegments), simulationTI, np.nan
            )
            self.createTrainingImagefile(filteredArray, self.temporaryPath)
        else:
            self.createTrainingImagefile(simulationTI, self.temporaryPath)

        if "hardDataVolume" in data:
            sequentialProgressBar.setMessage("Writing hard data file")
            if data["wrapCylinder"]:
                self.createImagelogHardDataFile(
                    SimulationHD,
                    slicer.util.arrayFromVolume(data["hardDataVolume"]),
                    data["hardDataValues"],
                    CONVERSION_FACTOR,
                )
            else:
                hardDataSelectedSegments = [nullValueHD] if invertHDSelectedSegments else data["hardDataValues"]

                self.createHardDataFile(
                    slicer.util.arrayFromVolume(SimulationHD),
                    slicer.util.arrayFromVolume(data["hardDataVolume"]),
                    np.around(np.array(data["hardDataResolution"]) * CONVERSION_FACTOR, 2),
                    hardDataSelectedSegments,
                    invertHDSelectedSegments,
                )

        if "maskVolume" in data and "maskSegments" in data:
            sequentialProgressBar.setMessage("Writing mask file")
            maskArray = np.where(np.isin(slicer.util.arrayFromVolume(data["maskVolume"]), data["maskSegments"]), 1, 0)
            self.createTrainingImagefile(maskArray, self.temporaryPath, "mask.dat")

    def run_parallel(self, run_data: dict, reference_volume, progressBar):
        """
        Method responsible for preparing data and sending to CLI
        """

        params = {
            "finalImageSize": run_data["finalImageSize"].tolist(),
            "finalImageResolution": [
                round(resolution * CONVERSION_FACTOR, 2) for resolution in run_data["finalImageResolution"]
            ],
        }

        cliConfig = {
            "params": json.dumps(params) if params is not None else None,
            "nreal": run_data["nreal"],
            "ncond": run_data["ncond"],
            "iterations": run_data["iterations"],
            "rseed": run_data["rseed"],
            "colocateDimensions": run_data["colocate_dimensions"],
            "maxSearchRadius": run_data["max_search_radius"],
            "distanceMax": run_data["distance_max"],
            "distancePower": run_data["distance_power"],
            "distanceMeasure": 2 if run_data["distance_measure"] else 1,
            "temporaryPath": self.temporaryPath,
        }

        self.cliNode = slicer.cli.run(
            slicer.modules.multiscalecli,
            None,
            cliConfig,
            wait_for_completion=False,
        )

        self.cliObserver = self.cliNode.AddObserver(
            "ModifiedEvent",
            lambda c, ev, info=run_data: self.onCliChangeEvent(c, ev, info, reference_volume),
        )

        if progressBar is not None:
            progressBar.setCommandLineModuleNode(self.cliNode)

        self.widget.updateStatusLabel("Running")

    def run_sequential(self, run_data: dict, reference_volume, progress_bar):
        """
        Method responsible for configuring mps and running sequential algorithm
        """
        self.configureMPSMethod(
            np.array(run_data["finalImageSize"]),
            np.around(np.array(run_data["finalImageResolution"]) * CONVERSION_FACTOR, 2),
            run_data["ncond"],
            run_data["nreal"],
            run_data["iterations"],
            run_data["rseed"],
            run_data["colocate_dimensions"],
            run_data["max_search_radius"],
            run_data["distance_max"],
            run_data["distance_power"],
            2 if run_data["distance_measure"] else 1,
        )

        progress_bar.setMessage("Running algorithm")
        try:
            self.runMPS()
        except RuntimeError as e:
            slicer.util.infoDisplay(str(e))
            return
        finally:
            self.mpslib.delete_local_files()

        self.save_outputs(run_data, reference_volume)

    def save_outputs(self, run_data, reference_volume):
        """
        Method responsible for saving the outputs. self.save_options contain which way it should be saved.
        The mps algorithm results are in attribute self.image so this method can be used by both sequential and parallel implementations.
        """
        # Create output folder
        if (
            self.save_options["saveAllAsSequence"]
            or self.save_options["saveSingleVolume"]
            or self.save_options["saveAllAsVolume"]
        ):
            self.configureOutput(self.save_options["name"])
        else:
            self.outputName = self.save_options["name"]

        # Create sequence node if necessary
        if self.save_options["saveAllAsSequence"]:
            SequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", f"{self.outputName}_sequence")
            SequenceNode.SetIndexUnit("")
            SequenceNode.SetIndexName("Realization")

        color_node_id = None
        if isinstance(reference_volume, slicer.vtkMRMLLabelMapVolumeNode):
            color_node = slicer.mrmlScene.CopyNode(reference_volume.GetDisplayNode().GetColorNode())
            helpers.makeTemporaryNodePermanent(color_node, show=True)
            color_node.SetName(f"{self.outputName}_colortable")
            color_node_id = color_node.GetID()

        # Loop through realization
        for realization in range(run_data["nreal"]):
            # creates volume
            volume = self.createOutputVolume(
                reference_volume,
                run_data["finalImageResolution"],
                realization,
                f"{self.outputName}_r{realization}",
                self.outputDir if self.save_options["saveAllAsVolume"] else None,
                color_node_id,
            )

            # Adds to sequence
            if self.save_options["saveAllAsSequence"]:
                SequenceNode.SetDataNodeAtValue(volume, str(realization))

            # Save first
            if realization == 0 and self.save_options["saveSingleVolume"]:
                volume.SetName(self.outputName)
                self.setSubjectHierarchy(volume, self.outputDir)
            # Remove nodes outside of sequence use last node as proxy
            elif not self.save_options["saveAllAsVolume"] and realization != run_data["nreal"] - 1:
                slicer.mrmlScene.RemoveNode(volume)

        # Finish sequence creation
        if self.save_options["saveAllAsSequence"]:
            if self.save_options["saveAllAsVolume"]:
                newVolume = helpers.clone_volume(volume, f"{volume.GetName()}", True, False)
                self.setSubjectHierarchy(newVolume, self.outputDir)
                if isinstance(newVolume, slicer.vtkMRMLScalarVolumeNode):
                    newVolume.GetDisplayNode().SetAndObserveColorNodeID(volume.GetDisplayNode().GetColorNodeID())

            self.setSubjectHierarchy(volume, self.outputDir)
            volume.SetName(f"{self.outputName}_proxy")
            browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", f"{self.outputName}_browser")
            browserNode.AddProxyNode(volume, SequenceNode, False)
            browserNode.SetAndObserveMasterSequenceNodeID(SequenceNode.GetID())
            browserNode.SetIndexDisplayFormat("%.0f")

        if isinstance(volume, slicer.vtkMRMLLabelMapVolumeNode):
            slicer.util.setSliceViewerLayers(background=None, label=volume)
        else:
            slicer.util.setSliceViewerLayers(label=None, background=volume)

        if self.save_options["saveAllAsFile"]:
            self.saveRealizationFiles(
                run_data["finalImageResolution"], run_data["nreal"], self.save_options["directory"], self.outputName
            )

        self.widget.updateTime(self.time)

        self.cleanUp(self.temporaryPath)

    def runMultiscale(
        self,
        preprocessing_data: dict,
        mps_configuration: dict,
        save_options: dict,
        isParallel: bool,
        progressBar=None,
        sequentialProgressBar=None,
    ):
        self.save_options = save_options
        self.save_options["distance_measure"] = mps_configuration["distance_measure"]
        self.temporaryPath = os.path.join(slicer.util.tempDirectory())

        self.mps_preprocessing(preprocessing_data, mps_configuration["distance_measure"], sequentialProgressBar)

        if "maskVolume" in preprocessing_data:
            self.mask_options["maskSegments"] = preprocessing_data["maskSegments"]
            self.mask_options["trainingDataSegments"] = preprocessing_data["trainingDataSegments"]

            if mps_configuration["distance_measure"]:
                reference_volume = preprocessing_data["maskReference"]
            else:
                reference_volume = preprocessing_data["maskVolume"]
                self.mask_options["maskSegmentList"] = preprocessing_data["maskSegmentList"]
                self.mask_options["trainingImageSegmentList"] = preprocessing_data["trainingImageSegmentList"]
        else:
            TIAsReference = False
            if "hardDataVolume" not in preprocessing_data:
                TIAsReference = True
            elif (
                isinstance(preprocessing_data["trainingDataVolume"], slicer.vtkMRMLLabelMapVolumeNode)
                and isinstance(preprocessing_data["hardDataVolume"], slicer.vtkMRMLLabelMapVolumeNode)
                and len(helpers.getSegmentList(preprocessing_data["trainingDataVolume"]))
                > len(helpers.getSegmentList(preprocessing_data["hardDataVolume"]))
            ):
                TIAsReference = True

            if mps_configuration["distance_measure"]:
                reference_volume = (
                    preprocessing_data["trainingReference"]
                    if TIAsReference
                    else preprocessing_data["hardDataReference"]
                )
            else:
                reference_volume = (
                    preprocessing_data["trainingDataVolume"] if TIAsReference else preprocessing_data["hardDataVolume"]
                )

        sequentialProgressBar.setMessage("Configuring mps algorithm")
        if isParallel:
            self.run_parallel(
                mps_configuration,
                reference_volume,
                progressBar,
            )
        else:
            self.run_sequential(
                mps_configuration,
                reference_volume,
                sequentialProgressBar,
            )

    def onCliChangeEvent(
        self,
        caller,
        event,
        info,
        reference_volume,
    ):
        if caller is None:
            self.cliNode = None
            return

        if caller.IsBusy():
            return

        if caller.GetStatusString() == "Completed":
            self.time = float(caller.GetParameterAsString("mpsTime"))

            for realization in range(info["nreal"]):
                self.image.append(np.load(os.path.join(self.temporaryPath, f"sim_data_{realization}.npy")))

            self.save_outputs(info, reference_volume)

        self.cleanUp(self.temporaryPath, info["nreal"])

        if self.cliObserver is not None:
            self.cliNode.RemoveObserver(self.cliObserver)
            self.cliObserver = None

        del self.cliNode
        self.cliNode = None
        self.widget.onCLIEvent()

    def cleanUp(self, temporaryPath, parallelFiles=None):
        shutil.rmtree(temporaryPath, ignore_errors=True)
        helpers.removeTemporaryNodes(environment=self.__class__.__name__)
        if parallelFiles:
            for thread in range(parallelFiles if parallelFiles < cpu_count() else cpu_count()):
                if os.path.isfile("mps_genesim_%03d.txt" % (thread)):
                    os.remove("mps_genesim_%03d.txt" % (thread))
                if os.path.isfile("ti_thread_%03d.dat" % (thread)):
                    os.remove("ti_thread_%03d.dat" % (thread))
                if os.path.isfile("ti_thread_%03d.dat.gslib" % (thread)):
                    os.remove("ti_thread_%03d.dat.gslib" % (thread))
                if os.path.isdir("thread%03d" % (thread)):
                    shutil.rmtree("thread%03d" % (thread), ignore_errors=True)
            if os.path.isfile("hard.dat"):
                os.remove("hard.dat")

        self.image = []
        self.time = 0
        self.save_options = {}
        self.mask_options = {}

    def cancelCLI(self):
        if self.cliNode:
            self.cliNode.Cancel()
            self.widget.updateStatusLabel("Canceled")

    def createTrainingImagefile(self, array, temporaryPath, filename="ti.dat"):
        flipAxis = self.save_options["flipAxis"]
        flatList = array.flatten("F" if flipAxis else "C").tolist()
        tiShape = array.shape if flipAxis else np.flip(array.shape)

        with open(os.path.join(temporaryPath, filename), "w") as f:
            f.write(" ".join([str(num) for num in tiShape]) + "\n")
            f.write("1" + "\n")
            f.write("Header" + "\n")
            f.write("\n".join([str(num) for num in flatList]))
            f.write("\n")

    def createHardDataFile(
        self, hardDataValues, hardDataMask, hardDataResolution, selectedSegments, invertSelected=False
    ):
        if selectedSegments:
            indicesz, indicesy, indicesx = np.where(np.isin(hardDataMask, selectedSegments, invert=invertSelected))
        else:
            indicesz, indicesy, indicesx = np.where(hardDataMask)

        hardData = np.zeros((len(indicesx), 4))
        if self.save_options["flipAxis"]:
            hardData[:] = np.column_stack(
                (
                    indicesz * hardDataResolution[2],
                    indicesy * hardDataResolution[1],
                    indicesx * hardDataResolution[0],
                    hardDataValues[indicesz, indicesy, indicesx],
                )
            )
        else:
            hardData[:] = np.column_stack(
                (
                    indicesx * hardDataResolution[0],
                    indicesy * hardDataResolution[1],
                    indicesz * hardDataResolution[2],
                    hardDataValues[indicesz, indicesy, indicesx],
                )
            )

        with open("hard.dat", "w") as f:
            f.write("eas title" + "\n")
            f.write("4" + "\n")
            f.write("col0" + "\n")
            f.write("col1" + "\n")
            f.write("col2" + "\n")
            f.write("col3" + "\n")
            np.savetxt(f, hardData, fmt="%.2f")

    def createImagelogHardDataFile(self, imageVolume, mask, values, unitConversionFactor):
        voxelHeight = imageVolume.GetSpacing()[2] * unitConversionFactor
        length, width, height = imageVolume.GetImageData().GetDimensions()

        wellDiameter = (length * imageVolume.GetSpacing()[0] / np.pi) * unitConversionFactor

        z = np.linspace(0, voxelHeight * height, num=height)
        x = np.linspace(0, wellDiameter * np.pi, num=length)
        xx, z_grid = np.meshgrid(x, z)
        x_cylinder = (wellDiameter / 2) * np.cos((2 * np.pi) * xx / (wellDiameter * np.pi)) + (wellDiameter / 2)
        y_cylinder = (wellDiameter / 2) * np.sin((2 * np.pi) * xx / (wellDiameter * np.pi)) + (wellDiameter / 2)
        z_cylinder = z_grid

        imageArray = slicer.util.arrayFromVolume(imageVolume).flatten()
        if values:
            maskArray = np.isin(mask.flatten(), values)
        else:
            maskArray = np.isin(mask.flatten(), mask)

        if self.save_options["flipAxis"]:
            hardData = np.column_stack(
                (
                    z_cylinder.flatten()[maskArray],
                    x_cylinder.flatten()[maskArray],
                    y_cylinder.flatten()[maskArray],
                    imageArray[maskArray],
                )
            )
        else:
            hardData = np.column_stack(
                (
                    x_cylinder.flatten()[maskArray],
                    y_cylinder.flatten()[maskArray],
                    z_cylinder.flatten()[maskArray],
                    imageArray[maskArray],
                )
            )

        mps.eas.write(hardData, "hard.dat")

    def configureMPSMethod(
        self,
        finalImageSize,
        finalImageResolution,
        ncond,
        nreal,
        iterations,
        rseed,
        colocateDimensions,
        maxSearchRadius,
        distanceMax,
        distancePower,
        distanceMeasure,
    ):
        self.mpslib = mps.mpslib(method="mps_genesim")
        self.mpslib.parameter_filename = os.path.join(self.temporaryPath, "mps.txt")
        self.mpslib.par["simulation_grid_size"] = finalImageSize
        self.mpslib.par["grid_cell_size"] = finalImageResolution
        self.mpslib.par["n_cond"] = ncond
        self.mpslib.par["n_real"] = nreal
        self.mpslib.par["ti_fnam"] = os.path.join(self.temporaryPath, "ti.dat")
        self.mpslib.par["out_folder"] = self.temporaryPath
        self.mpslib.par["n_max_ite"] = iterations
        self.mpslib.par["rseed"] = rseed
        self.mpslib.par["hard_data_fnam"] = "hard.dat"
        self.mpslib.par["mask_fnam"] = os.path.join(self.temporaryPath, "mask.dat")
        self.mpslib.par["colocate_dimension"] = colocateDimensions
        self.mpslib.par["max_search_radius"] = maxSearchRadius
        self.mpslib.par["distance_max"] = distanceMax
        self.mpslib.par["distance_pow"] = distancePower
        self.mpslib.par["distance_measure"] = distanceMeasure
        self.mpslib.par["verbose_level"] = -1

    def setSubjectHierarchy(self, node, folderDir):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(node), folderDir)

    def returnFolderDir(self, refVolume):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemTreeId = subjectHierarchyNode.GetItemByDataNode(refVolume)
        parentItemId = subjectHierarchyNode.GetItemParent(itemTreeId)
        foundResultDir = subjectHierarchyNode.GetItemByName("Multiscale Results")
        if not foundResultDir:
            foundResultDir = subjectHierarchyNode.CreateFolderItem(
                subjectHierarchyNode.GetItemParent(parentItemId), "Multiscale Results"
            )
        return foundResultDir

    def createMaskedColorNode(self, colors_list, name):
        colorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLColorTableNode", name)
        colorNode.SetTypeToUser()
        colorNode.SetNumberOfColors(len(colors_list) + 1)
        colorNode.SetNamesInitialised(True)

        colorNode.SetColor(0, "", 0, 0, 0, 0)

        for number in colors_list.keys():
            r, g, b, a = colors_list[number]["color"]
            success = colorNode.SetColor(number, colors_list[number]["name"], r, g, b, a)

        return colorNode

    def createOutputColorNode(self, referenceNode, name):
        referenceColorNode = referenceNode.GetDisplayNode().GetColorNode()
        numberColors = referenceColorNode.GetNumberOfColors()
        colors = np.empty((numberColors, 4))
        for c, color in enumerate(colors):
            referenceColorNode.GetColor(c, color)
        names = [referenceColorNode.GetColorName(n) for n in range(numberColors)]

        outputColorNode = helpers.create_color_table(
            node_name=f"{name}_colorMap", colors=colors, color_names=names, add_background=False
        )

        return outputColorNode

    def createOutputVolume(self, refVolume, spacing, realization, name, outputDir=None, colorNode=None):
        if isinstance(refVolume, slicer.vtkMRMLLabelMapVolumeNode):
            labelmapNode, _ = helpers.createLabelmapInput(refVolume, name)
            labelmapNode.GetDisplayNode().GetColorNode().SetAttribute("NodeEnvironment", self.__class__.__name__)

            if self.save_options["flipAxis"]:
                outputArray = self.image[realization]
                outputSpacing = np.flip(np.around(np.array(spacing), 5))
            else:
                outputArray = np.transpose(self.image[realization])
                outputSpacing = np.around(np.array(spacing), 5)

            if not self.mask_options:
                slicer.util.updateVolumeFromArray(labelmapNode, outputArray.astype(np.int32))
            else:
                new_colors = {}

                for old_color_num in self.mask_options["trainingDataSegments"]:
                    new_color_num = len(new_colors) + 1
                    outputArray = np.where(outputArray == old_color_num, new_color_num, outputArray)
                    new_colors[new_color_num] = self.mask_options["trainingImageSegmentList"][old_color_num]

                for old_color_num in range(1, len(self.mask_options["maskSegmentList"]) + 1, 1):
                    if np.isin(old_color_num, self.mask_options["maskSegments"]):
                        continue

                    new_color_num = len(new_colors) + 1
                    outputArray[slicer.util.arrayFromVolume(refVolume) == old_color_num] = new_color_num
                    new_colors[new_color_num] = self.mask_options["maskSegmentList"][old_color_num]

                slicer.util.updateVolumeFromArray(labelmapNode, outputArray.astype(np.int32))

                if "maskColorNode" in self.mask_options:
                    colorNode = self.mask_options["maskColorNode"]
                else:
                    colorNode = self.createMaskedColorNode(new_colors, f"{name}_colorTable").GetID()
                    self.mask_options["maskColorNode"] = colorNode

            if colorNode is None:
                outputColorNode = self.createOutputColorNode(refVolume, name)

            labelmapNode.GetDisplayNode().SetAndObserveColorNodeID(
                colorNode if colorNode is not None else outputColorNode.GetID()
            )
            helpers.makeTemporaryNodePermanent(labelmapNode, show=True)

            if outputDir:
                self.setSubjectHierarchy(labelmapNode, outputDir)

            labelmapNode.SetSpacing(outputSpacing)
            slicer.util.setSliceViewerLayers(background=None, label=labelmapNode, fit=True)
            return labelmapNode

        else:
            newVolume = slicer.mrmlScene.AddNewNodeByClass(refVolume.GetClassName(), name)
            newVolume.CopyOrientation(refVolume)
            for attrName in refVolume.GetAttributeNames():
                newVolume.SetAttribute(attrName, refVolume.GetAttribute(attrName))

            if self.save_options["flipAxis"]:
                outputArray = self.image[realization]
                outputSpacing = np.flip(np.around(np.array(spacing), 5))
            else:
                outputArray = np.transpose(self.image[realization])
                outputSpacing = np.around(np.array(spacing), 5)

            if self.mask_options:
                referenceArray = slicer.util.arrayFromVolume(refVolume)
                outputArray = np.where(np.isnan(outputArray), referenceArray, outputArray)

            slicer.util.updateVolumeFromArray(newVolume, outputArray)

            if outputDir:
                self.setSubjectHierarchy(newVolume, outputDir)

            newVolume.SetSpacing(outputSpacing)

            slicer.util.setSliceViewerLayers(background=newVolume, label=None, fit=True)
            newVolume.GetDisplayNode().SetAndObserveColorNodeID(refVolume.GetDisplayNode().GetColorNodeID())

            return newVolume

    def saveRealizationFiles(self, grid_cell_size, nreal, directory, name):
        for i in range(nreal):
            tifffile.imwrite(
                f"{directory}/{name}_r{i}.tif",
                np.flip(np.transpose(self.image[i]), axis=0).astype("float32"),
                imagej=True,
                resolution=(1 / (grid_cell_size[0] * CONVERSION_FACTOR), 1 / (grid_cell_size[1] * CONVERSION_FACTOR)),
                metadata={"spacing": grid_cell_size[2] * CONVERSION_FACTOR, "unit": "microns"},
            )

    def runMPS(self):
        self.mpslib.run()
        self.image = self.mpslib.sim
        self.time = self.mpslib.time

    def generatePreview(self, volume, dimension, top, bottom):
        length, width, height = volume.GetImageData().GetDimensions()
        newVolume, _ = helpers.createLabelmapInput(volume, "previewLabelmap")

        wellDiameter = length * volume.GetSpacing()[0] / np.pi
        newVolume.SetSpacing([wellDiameter / dimension, wellDiameter / dimension, volume.GetSpacing()[2]])

        startingDepth = -volume.GetOrigin()[2] / 1000
        topVoxelHeight = round((top - startingDepth) / volume.GetSpacing()[2] * 1000)
        bottomVoxelHeight = round((bottom - startingDepth) / volume.GetSpacing()[2] * 1000)

        imagelogArray = slicer.util.arrayFromVolume(volume)[topVoxelHeight:bottomVoxelHeight, :, :]

        radius = (dimension - 1) / 2
        volumeArray = np.zeros((bottomVoxelHeight - topVoxelHeight, dimension, dimension))

        angles = np.radians(np.arange(0, 360, 0.5))
        y = np.round(radius * np.sin(angles) + radius).astype(int)
        x = np.round(radius * np.cos(angles) + radius).astype(int)
        coords = np.array([[y[0], x[0], 0]])
        for i in range(720):
            lastCoordinate = coords[-1]
            dif = abs(y[i] - lastCoordinate[0]) + abs(x[i] - lastCoordinate[1])
            if dif == 2:
                hypo1 = math.hypot(y[i] - radius, lastCoordinate[1] - radius)
                hypo2 = math.hypot(lastCoordinate[0] - radius, x[i] - radius)
                if hypo1 <= hypo2:
                    coords = np.append(coords, [[y[i], lastCoordinate[1], lastCoordinate[2]]], axis=0)
                else:
                    coords = np.append(coords, [[lastCoordinate[0], x[i], lastCoordinate[2]]], axis=0)
            if dif > 0:
                coords = np.append(coords, [[y[i], x[i], int(math.floor(i / 2 * (length / 360)))]], axis=0)
            else:
                coords[-1][2] = int(math.floor(i / 2 * (length / 360)))

        if (x[0], y[0]) == (x[-1], y[-1]):
            coords = coords[:-1]

        volumeArray[:, coords[:, 0], coords[:, 1]] = imagelogArray[:, 0, coords[:, 2]]

        slicer.util.updateVolumeFromArray(newVolume, volumeArray)
        slicer.util.setSliceViewerLayers(background=None, label=newVolume, fit=True)

        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(newVolume, segmentationNode)
        segmentationNode.SetName("previewSegmentation")
        helpers.makeNodeTemporary(segmentationNode, hide=True)

        return segmentationNode
