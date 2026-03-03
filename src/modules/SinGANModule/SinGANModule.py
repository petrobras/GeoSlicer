import os
import shutil
from pathlib import Path
from collections import namedtuple

import ctk
import qt
import slicer
import numpy as np
import torch
import time

from CustomResampleScalarVolume import CustomResampleScalarVolumeLogic, ResampleScalarVolumeData
from ltrace.assets_utils import get_metadata
from ltrace.slicer import ui, widgets, helpers
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widget.trained_model_selector import TrainedModelSelector
from ltrace.SinGANLibs.functions import get_generation_params, get_base_volume
from ltrace.SinGANLibs.singan import load_singan_model, reshape_singan_model
from ltrace.SinGANLibs.generator import GENERATION_METHODS
from BigImage import BigImageLogic
from MultiScale import MultiScaleLogic

try:
    from Test.SinGANModuleTest import SinGANModuleTest
except ImportError:
    SinGANModuleTest = None  # tests not deployed to final version or closed source

COLOR_TABLE_TEMPLATE = "SinGANColorTableTemplate.ctbl"

SinGANParameters = namedtuple(
    "SinGANParameters",
    [
        "model",
        "hardData",
        "hardDataSegments",
        "imagelog",
        "imagelogSegments",
        "chosenScale",
        "numberRealizations",
        "outputName",
        "outputPath",
        "saveOptions",
        "reconstruction",
        "harDataResolution",
        "method",
        "base_volume",
        "split_scale",
        "crop_scale",
        "disk_scale",
        "chunks",
        "p2p",
        "partitions",
        "seed",
    ],
)


class SinGANModule(LTracePlugin):
    SETTING_KEY = "SinGANModule"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "SinGAN Module"
        self.parent.categories = ["Multiscale"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = SinGANModule.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class SinGANModuleWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = SinGANModuleLogic()
        self.parametersCalculated = False
        self.isRunning = False
        self.previewSegmentationNode = None
        self.uiPreviousState = {}

    # Some elements should be disabled while running the CLI and get back to previous styate afterwards
    def __toggleUI(self, enabled: bool) -> None:
        widgets = [self.generateTIPushButton, self.previewHDScales, self.parameterSection]
        if not enabled:
            for widget in widgets:
                self.uiPreviousState[widget] = widget.isEnabled()
                widget.setEnabled(False)
        else:
            for widget in widgets:
                if widget in self.uiPreviousState:
                    widget.setEnabled(self.uiPreviousState[widget])
            self.uiPreviousState = {}

    def setup(self):
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.modelSelector = TrainedModelSelector(["SinGAN"])
        self.modelSelector.currentIndexChanged.connect(self.__onModelSelectorChange)
        self.modelSelector.setToolTip("Select the valid SinGAN model to be used in simulation")
        self.modelSelector.objectName = "Model Selector"

        self.generateTIPushButton = qt.QPushButton("Create TI from model")
        self.generateTIPushButton.clicked.connect(self.__generateTI)
        self.generateTIPushButton.setToolTip(
            "Use the fixed reconstruction noise created during training as input to the selected model to generate the reconstruction of the training image (TI)"
        )
        self.generateTIPushButton.setEnabled(False)
        self.generateTIPushButton.objectName = "Generate TI Push Button"

        self.hardDataWidget = widgets.SingleShotInputWidget(
            hideSoi=True,
            allowedInputNodes=[
                "vtkMRMLSegmentationNode",
                "vtkMRMLLabelMapVolumeNode",
            ],
            mainName="Hard Data Image",
            referenceName="HD Reference",
            setDefaultMargins=False,
            objectNamePrefix="Hard Data",
        )
        self.hardDataWidget.objectName = "Hard Data Widget"
        self.hardDataWidget.mainInput.currentItemChanged.connect(self.__onHardDataChange)
        self.hardDataWidget.segmentListGroup[1].itemChanged.connect(self.__updateApplyButtonStatus)

        layoutScale = qt.QHBoxLayout()
        layoutScale.setContentsMargins(0, 0, 0, 0)

        self.useScaleCheckBox = qt.QCheckBox()
        self.useScaleCheckBox.objectName = "Scale CheckBox"
        self.useScaleCheckBox.setToolTip(
            "If checked, the HD will be added only at the selected scale instead of all scales"
        )
        self.useScaleCheckBox.stateChanged.connect(self.__onScaleCheckBoxChange)

        self.hdScale = qt.QSpinBox()
        self.hdScale.setRange(1, 1)
        self.hdScale.setValue(1)
        self.hdScale.setEnabled(False)
        self.hdScale.objectName = "HD Scale Spin Box"

        layoutScale.addWidget(self.useScaleCheckBox)
        layoutScale.addWidget(self.hdScale)
        layoutScale.setStretch(0, 0)
        layoutScale.setStretch(1, 1)

        self.scaleWidget = qt.QWidget()
        self.scaleWidget.setLayout(layoutScale)

        self.previewHDScales = qt.QPushButton("Create Hard Data preview")
        self.previewHDScales.clicked.connect(self.__previewHD)
        self.previewHDScales.setToolTip(
            "Create a preview of the hard data. If a scale is chooen, only one preview will be generated on that scale. If unchecked, a sequence with all scales will be generated"
        )
        self.previewHDScales.setEnabled(False)
        self.previewHDScales.objectName = "Preview HD Scales Button"

        self.hardDataSection = ctk.ctkCollapsibleButton()
        self.hardDataSection.text = "Hard Data"
        self.hardDataSection.setToolTip(
            "These parameters are auto-calculated. Modifying them may impact performance and results."
        )
        self.hardDataSection.flat = True

        hardDataSectionLayout = qt.QFormLayout(self.hardDataSection)

        hardDataSectionLayout.addRow(self.hardDataWidget)
        hardDataSectionLayout.addRow("Choose scale to use HD:", self.scaleWidget)
        hardDataSectionLayout.addRow(self.previewHDScales)

        self.imagelogWidget = widgets.SingleShotInputWidget(
            hideSoi=True,
            allowedInputNodes=[
                "vtkMRMLSegmentationNode",
                "vtkMRMLLabelMapVolumeNode",
            ],
            mainName="Imagelog Image",
            referenceName="Imagelog Reference",
            setDefaultMargins=False,
            objectNamePrefix="Imagelog",
        )
        self.imagelogWidget.objectName = "Imagelog Widget"
        self.imagelogWidget.mainInput.currentItemChanged.connect(self.__onImagelogChange)
        self.imagelogWidget.segmentListGroup[1].itemChanged.connect(lambda item: self.__listItemChange(item))

        self.imagelogSection = ctk.ctkCollapsibleButton()
        self.imagelogSection.text = "Imagelog"
        self.imagelogSection.setToolTip(
            "These parameters are auto-calculated. Modifying them may impact performance and results."
        )
        self.imagelogSection.flat = True
        self.imagelogSection.collapsed = True

        self.imagelogPreview = qt.QPushButton("Create 3D representation of imagelog")
        self.imagelogPreview.clicked.connect(self.__imagelogWrap)
        self.imagelogPreview.setToolTip(
            "Create a 3D representation of the 2D imagelog wrapped as a cylinder. This preview is intended for visualization purposes and incorporates additional data to improve its surface representation."
        )
        self.imagelogPreview.setEnabled(False)
        self.imagelogPreview.objectName = "Imagelog Preview Button"

        imagelogSectionSectionLayout = qt.QFormLayout(self.imagelogSection)
        imagelogSectionSectionLayout.addRow(self.imagelogWidget)
        imagelogSectionSectionLayout.addRow(self.imagelogPreview)

        # ==== input ====

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Select Model:", self.modelSelector)
        inputLayout.addRow(self.generateTIPushButton)
        inputLayout.addRow(self.hardDataSection)
        inputLayout.addRow(self.imagelogSection)

        # parameters section
        self.parameterSection = ctk.ctkCollapsibleButton()
        self.parameterSection.collapsed = False
        self.parameterSection.text = "Parameters"

        self.parametersButton = qt.QPushButton("Calculate parameters")
        self.parametersButton.clicked.connect(self.__calculateParameters)
        self.parametersButton.objectName = "Calculate Parameters Button"

        self.cropMethodComboBox = qt.QComboBox()
        self.cropMethodComboBox.currentIndexChanged.connect(self.__onMethodSelected)
        self.cropMethodComboBox.objectName = "Crop Method Combo Box"

        self.chunkSizes = []
        chunkLayout = qt.QHBoxLayout()
        for _ in range(3):
            chunkSize = qt.QSpinBox()
            chunkSize.objectName = f"chunk_{_}"
            chunkSize.value = 3
            chunkSize.setRange(1, 9)
            self.chunkSizes.append(chunkSize)
            chunkLayout.addWidget(chunkSize)
            if _ < 2:
                chunkLayout.addWidget(qt.QLabel("x"))

        self.chunkWidget = qt.QWidget()
        self.chunkWidget.setLayout(chunkLayout)
        self.chunkWidget.hide()

        self.chunckLabel = qt.QLabel("Set number of chunk:")
        self.chunckLabel.hide()

        chunkLayout.setContentsMargins(0, 0, 0, 0)
        chunkLayout.addStretch()

        self.baseVolumeSpin = qt.QSpinBox()
        self.baseVolumeSpin.setRange(0, 1000)
        self.baseVolumeSpin.objectName = "Base Volume Spin Box"
        self.splitScaleSpin = qt.QSpinBox()
        self.splitScaleSpin.objectName = "Split Scale Spin Box"
        self.cropScaleSpin = qt.QSpinBox()
        self.cropScaleSpin.objectName = "Crop Scale Spin Box"
        self.diskScaleSpin = qt.QSpinBox()
        self.diskScaleSpin.objectName = "Disk Scale Spin Box"
        self.seedSpin = qt.QSpinBox()
        self.seedSpin.setRange(-1, 100000)
        self.seedSpin.setValue(0)
        self.seedSpin.objectName = "Seed Spin Box"

        self.advancedSection = ctk.ctkCollapsibleButton()
        self.advancedSection.text = "Advanced Parameters"
        self.advancedSection.setToolTip(
            "These parameters are auto-calculated. Modifying them may impact performance and results."
        )
        self.advancedSection.flat = True
        self.advancedSection.collapsed = True
        self.advancedSection.hide()

        advancedSectionLayout = qt.QFormLayout(self.advancedSection)
        advancedSectionLayout.setContentsMargins(10, 0, 0, 0)

        advancedSectionLayout.addRow("Base Volume", self.baseVolumeSpin)
        advancedSectionLayout.addRow("Split Scale", self.splitScaleSpin)
        advancedSectionLayout.addRow("Disk Scale", self.diskScaleSpin)
        advancedSectionLayout.addRow("Seed", self.seedSpin)

        parameterLayout = qt.QFormLayout(self.parameterSection)
        parameterLayout.addRow("Selected method:", self.cropMethodComboBox)
        parameterLayout.addRow(self.chunckLabel, self.chunkWidget)
        parameterLayout.addRow(self.advancedSection)
        parameterLayout.addRow(self.parametersButton)

        self.__updateParameters()

        # Output section
        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.realizationsSpinBox = qt.QSpinBox()
        self.realizationsSpinBox.setToolTip("Set number of output images to be generated")
        self.realizationsSpinBox.setRange(1, 9999)
        self.realizationsSpinBox.setValue(1)
        self.realizationsSpinBox.objectName = "realizationsSpinBox"
        self.realizationsSpinBox.valueChanged.connect(self.__onRealizationsChange)

        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.objectName = "outputPrefix"
        self.outputPrefix.textChanged.connect(self.__updateApplyButtonStatus)
        self.outputPrefix.setToolTip("Name of the volumes and file that will be generated")

        self.saveAsVolumeCheckBox = qt.QCheckBox("As volume")
        self.saveAsVolumeCheckBox.setToolTip(
            "If checked, each realization will be saved as a single volume node. May be RAM intensive"
        )
        self.saveAsVolumeCheckBox.setChecked(qt.Qt.Checked)
        self.saveAsVolumeCheckBox.objectName = "saveAsVolume"
        self.saveAsVolumeCheckBox.stateChanged.connect(self.__updateApplyButtonStatus)

        self.saveAsSequenceCheckBox = qt.QCheckBox("As sequence")
        self.saveAsSequenceCheckBox.setToolTip(
            "If checked, all of the realizations outputs will be added to a single sequence node. May be RAM intensive"
        )
        self.saveAsSequenceCheckBox.objectName = "saveAsSequence"
        self.saveAsSequenceCheckBox.setEnabled(False)
        self.saveAsSequenceCheckBox.stateChanged.connect(self.__updateApplyButtonStatus)

        self.saveAsBigImageCheckBox = qt.QCheckBox("As Large Image node")
        self.saveAsBigImageCheckBox.setToolTip("If checked, each realization will be saved as a Large Image node.")
        self.saveAsBigImageCheckBox.objectName = "saveAsBigImage"
        self.saveAsBigImageCheckBox.hide()
        self.saveAsBigImageCheckBox.stateChanged.connect(self.__updateApplyButtonStatus)

        self.saveAsFileCheckBox = qt.QCheckBox("NetCDF files")
        self.saveAsFileCheckBox.setToolTip(
            "If checked, all of the realizations will be exported as NetCDF files to the selected directory"
        )
        self.saveAsFileCheckBox.objectName = "saveAsFile"
        self.saveAsFileCheckBox.stateChanged.connect(self.__onSaveAsFileChange)

        saveOptionsLayout = qt.QHBoxLayout()
        saveOptionsLayout.setContentsMargins(0, 0, 0, 0)
        saveOptionsLayout.addWidget(self.saveAsBigImageCheckBox)
        saveOptionsLayout.addWidget(self.saveAsVolumeCheckBox)
        saveOptionsLayout.addWidget(self.saveAsSequenceCheckBox)
        saveOptionsLayout.addWidget(self.saveAsFileCheckBox)

        self.saveOptionsWidgets = qt.QWidget()
        self.saveOptionsWidgets.setLayout(saveOptionsLayout)

        self.exportDirectoryButton = ctk.ctkDirectoryButton()
        # self.exportDirectoryButton.setMaximumWidth(374)
        self.exportDirectoryButton.caption = "Export directory"
        self.exportDirectoryButton.setDisabled(True)
        self.exportDirectoryButton.objectName = "fileDirectory"

        self.partitionsSpinBox = qt.QSpinBox()
        # self.partitionsSpinBox.hide()
        self.partitionsSpinBox.setToolTip("Set number of partitioned files that will be generated.")
        self.partitionsSpinBox.setRange(1, 100)
        self.partitionsSpinBox.setValue(3)
        self.partitionsSpinBox.objectName = "partitionsSpinBox"
        self.partitionsSpinBox.valueChanged.connect(self.__checkApplyButtonStatus)

        outputFormLayout = qt.QFormLayout(outputSection)
        outputFormLayout.addRow("Number of realizations:", self.realizationsSpinBox)
        outputFormLayout.addRow("Output prefix:", self.outputPrefix)
        outputFormLayout.addRow("Save:", self.saveOptionsWidgets)
        outputFormLayout.addRow("Export directory:", self.exportDirectoryButton)
        outputFormLayout.addRow("Number of partitions:", self.partitionsSpinBox)

        self.applyButton = ui.ApplyButton(onClick=self.__onApplyButtonClicked, tooltip="Apply changes", enabled=True)
        self.applyButton.objectName = "Apply Button"
        self.applyButton.setEnabled(False)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.enabled = False
        self.cancelButton.clicked.connect(self.__onCancel)
        self.cancelButton.objectName = "cancelButton"
        self.cancelButton.setToolTip("Interrupt and cancel the execution of the model.")

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.applyButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)

        # CLI progress bar
        self.cliProgressBar = LocalProgressBar()

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(self.parameterSection)
        self.layout.addWidget(outputSection)
        self.layout.addLayout(buttonsHBoxLayout)
        self.layout.addWidget(self.cliProgressBar)
        self.layout.addStretch(1)

        self.__updateMethodSelector()
        self.__onModelSelectorChange()

    def __onApplyButtonClicked(self) -> None:
        hardDataNode = self.hardDataWidget.mainInput.currentNode()
        if isinstance(hardDataNode, slicer.vtkMRMLSegmentationNode):
            hardDataNode, _ = helpers.createLabelmapInput(hardDataNode, "tempHDLabelmap")

        imagelogNode = self.imagelogWidget.mainInput.currentNode()
        if isinstance(hardDataNode, slicer.vtkMRMLSegmentationNode):
            imagelogNode, _ = helpers.createLabelmapInput(imagelogNode, "tempHDLabelmap")

        if hardDataNode is None:
            spacingX, spacingY, spacingZ = 1, 1, 1
        else:
            spacingX, spacingY, spacingZ = hardDataNode.GetSpacing()

        HDResolution = (spacingX + spacingY + spacingZ) / 3
        sinGANParameters = SinGANParameters(
            model=self.modelSelector.getSelectedModelPath(),
            hardData=hardDataNode,
            hardDataSegments=np.array(self.hardDataWidget.getSelectedSegments()) + 1,
            imagelog=imagelogNode,
            imagelogSegments=np.array(self.imagelogWidget.getSelectedSegments()) + 1,
            chosenScale=0 if not self.useScaleCheckBox.isChecked() else self.hdScale.value,
            numberRealizations=self.realizationsSpinBox.value,
            outputName=self.outputPrefix.text,
            outputPath=Path(self.exportDirectoryButton.directory),
            saveOptions={
                "saveAll": self.saveAsVolumeCheckBox.isChecked(),
                "saveSequence": self.saveAsSequenceCheckBox.isChecked(),
                "saveBigImage": self.saveAsBigImageCheckBox.isChecked(),
                "saveFiles": self.saveAsFileCheckBox.isChecked(),
            },
            reconstruction=False,
            harDataResolution=HDResolution,
            method=self.cropMethodComboBox.currentData,
            base_volume=self.baseVolumeSpin.value,
            split_scale=self.splitScaleSpin.value,
            crop_scale=self.cropScaleSpin.value,
            disk_scale=self.diskScaleSpin.value,
            chunks=self.__getChunkSizes(),
            p2p=False,
            partitions=self.partitionsSpinBox.value,
            seed=self.seedSpin.value,
        )

        self.cancelButton.setEnabled(True)
        self.__toggleUI(False)

        helpers.removeTemporaryNodes()
        self.previewSegmentationNode = None

        self.logic.apply(sinGANParameters, self.__onCLICompleted, self.cliProgressBar)
        self.isRunning = True
        self.applyButton.setEnabled(False)

    def __checkApplyButtonStatus(self) -> None:
        if (
            self.logic.cliNode
            and self.logic.cliNode.GetStatusString() != "Running"
            and self.logic.cliNode.GetStatusString() != "Idle"
        ):
            self.isRunning = False  # good moment to recover our state from a crash

        if self.isRunning:
            return False

        if self.modelSelector.currentData is None:
            return False

        if self.hardDataWidget.mainInput.currentNode() is not None:
            if not self.hardDataWidget.getSelectedSegments():
                return False
            elif (
                len(self.hardDataWidget.getSelectedSegments()) == 0
                or len(self.hardDataWidget.getSelectedSegments()) == self.hardDataWidget.segmentListGroup[1].count
            ):
                helpers.highlight_error(self.hardDataWidget.segmentListGroup[1])
                return False
            else:
                helpers.remove_highlight(self.hardDataWidget.segmentListGroup[1])

        if self.imagelogWidget.mainInput.currentNode() is not None:
            if len(self.imagelogWidget.getSelectedSegments()) == 0:
                helpers.highlight_error(self.imagelogWidget.segmentListGroup[1])
                return False
            else:
                helpers.remove_highlight(self.imagelogWidget.segmentListGroup[1])

        if not self.outputPrefix.text.replace(" ", "") != "":
            return False

        if not (
            self.saveAsVolumeCheckBox.isChecked()
            or self.saveAsSequenceCheckBox.isChecked()
            or self.saveAsFileCheckBox.isChecked()
        ):
            return False

        if not self.parametersCalculated:
            return False

        return True

    def enter(self) -> None:
        super().enter()

        if self.modelSelector.currentData is None:
            self.modelSelector.triggerMissingModel()

    def exit(self) -> None:
        helpers.removeTemporaryNodes()
        self.previewSegmentationNode = None

    def __calculateParameters(self) -> None:
        if self.modelSelector.currentData is None:
            print("NO MODEL")  # TODO Replace with error
            return

        modelPath = Path(self.modelSelector.getSelectedModelPath())
        self.baseVolume = get_base_volume(0)

        model = load_singan_model(torch.device("cpu"), modelPath)

        if self.hardDataWidget.mainInput.currentNode() is not None:
            spacingX, spacingY, spacingZ = self.hardDataWidget.mainInput.currentNode().GetSpacing()
            HDResolution = (spacingX + spacingY + spacingZ) / 3
            reshape_singan_model(
                model,
                modelPath.as_posix(),
                slicer.util.arrayFromVolume(self.hardDataWidget.mainInput.currentNode()),
                HDResolution,
            )

        self.cropScale, self.diskScale, self.splitScale = get_generation_params(model.shapes, True, security_factor=0.3)

        self.__updateMethodSection(self.baseVolume, self.cropScale, self.diskScale, self.splitScale)

    def __updateMethodSection(self, baseVolume: int, cropScale: int, diskScale: int, splitScale: int) -> None:
        self.__updateParameters(baseVolume, cropScale, diskScale, splitScale)
        self.__changeMethodsByParameters(diskScale, splitScale)
        self.__updateSaveOptions(diskScale >= 0)

    def __updateParameters(
        self, baseVolume: int = 50, cropScale: int = 0, diskScale: int = -1, splitScale: int = -1
    ) -> None:
        if splitScale == -1:
            self.advancedSection.hide()
            self.__updateParametersMinimum(-1)
        else:
            self.advancedSection.show()
            self.__updateParametersMinimum(0)
        self.advancedSection.show()

        self.baseVolumeSpin.setValue(baseVolume)
        self.cropScaleSpin.setValue(cropScale)
        self.diskScaleSpin.setValue(diskScale)
        self.splitScaleSpin.setValue(splitScale)

    def __updateParametersMinimum(self, minimum: int = -1) -> None:
        self.diskScaleSpin.setMinimum(minimum)
        self.splitScaleSpin.setMinimum(minimum)

    def __changeMethodsByParameters(self, diskScale: int, splitScale: int) -> None:
        keys = list(GENERATION_METHODS.keys())
        allowedMethods = []

        if diskScale == -1 and splitScale == -1:
            allowedMethods.append(keys[0])
        elif diskScale >= 0 and splitScale == -1:
            allowedMethods.append(keys[1])
        else:
            allowedMethods.append(keys[2])

        self.__updateMethodSelector(allowedMethods)

    def __updateMethodSelector(self, methodsList: list = []) -> None:
        self.cropMethodComboBox.clear()
        self.cropMethodComboBox.setEnabled(False)
        if methodsList:
            for method in methodsList:
                self.cropMethodComboBox.addItem(method, GENERATION_METHODS[method])
            self.parametersCalculated = True
        else:
            self.cropMethodComboBox.addItem("Calculate parameters first", None)
            self.parametersCalculated = False

        self.__updateApplyButtonStatus()

    def __updateSaveOptions(self, bigImage: bool) -> None:
        self.saveAsFileCheckBox.setEnabled(not bigImage)
        self.saveAsVolumeCheckBox.setEnabled(not bigImage)
        self.saveAsSequenceCheckBox.setEnabled(not bigImage)
        self.saveAsBigImageCheckBox.setEnabled(bigImage)

        if bigImage:
            self.saveAsVolumeCheckBox.setChecked(qt.Qt.Unchecked)
            self.saveAsSequenceCheckBox.setChecked(qt.Qt.Unchecked)
            self.saveAsFileCheckBox.setChecked(qt.Qt.Checked)

            self.saveAsVolumeCheckBox.hide()
            self.saveAsSequenceCheckBox.hide()
            self.saveAsBigImageCheckBox.show()
            self.partitionsSpinBox.show()

        else:
            self.saveAsVolumeCheckBox.show()
            self.saveAsSequenceCheckBox.show()
            self.saveAsBigImageCheckBox.hide()
            self.partitionsSpinBox.hide()
            self.__onRealizationsChange(self.realizationsSpinBox.value)

    def __onMethodSelected(self) -> None:
        self.chunckLabel.hide()
        self.chunkWidget.hide()

        if self.cropMethodComboBox.currentData == GENERATION_METHODS["Generation patch on gpu"]:
            self.saveAsVolumeCheckBox.setEnabled(True)
            self.saveAsFileCheckBox.setEnabled(False)
            self.saveAsBigImageCheckBox.setEnabled(False)
            self.saveAsBigImageCheckBox.setChecked(qt.Qt.Unchecked)
            self.__onRealizationsChange(self.realizationsSpinBox.value)
        if self.cropMethodComboBox.currentData == GENERATION_METHODS["Early crop"]:
            self.saveAsVolumeCheckBox.setChecked(qt.Qt.Unchecked)
            self.saveAsVolumeCheckBox.setEnabled(False)
            self.saveAsFileCheckBox.setEnabled(True)
        if self.cropMethodComboBox.currentData == GENERATION_METHODS["Patch Inference"]:
            self.saveAsVolumeCheckBox.setChecked(qt.Qt.Unchecked)
            self.saveAsVolumeCheckBox.setEnabled(False)
            self.saveAsFileCheckBox.setEnabled(True)

    def __getChunkSizes(self) -> list:
        return [self.chunkSizes[0].value, self.chunkSizes[1].value, self.chunkSizes[2].value]

    def __onModelSelectorChange(self) -> None:
        if self.modelSelector.currentData is None:
            self.generateTIPushButton.setEnabled(False)
            self.previewHDScales.setEnabled(False)
            return

        self.generateTIPushButton.setEnabled(True)

        modelPath = self.modelSelector.getSelectedModelPath()
        modelMetadata = get_metadata(modelPath)

        lastScale = 16
        if "stop_scale" in modelMetadata.keys():
            lastScale = modelMetadata["stop_scale"]

        self.hdScale.setRange(1, lastScale)

    def __updateApplyButtonStatus(self) -> None:
        self.applyButton.setEnabled(self.__checkApplyButtonStatus())

    def __onScaleCheckBoxChange(self) -> None:
        self.hdScale.setEnabled(self.useScaleCheckBox.isChecked())

    def __onRealizationsChange(self, realizations: int) -> None:
        if self.cropMethodComboBox.currentData == GENERATION_METHODS["Generation patch on gpu"]:
            if realizations == 1:
                self.saveAsVolumeCheckBox.setChecked(qt.Qt.Checked)
                self.saveAsSequenceCheckBox.setChecked(qt.Qt.Unchecked)
                self.saveAsSequenceCheckBox.setEnabled(False)
            else:
                self.saveAsSequenceCheckBox.setEnabled(True)

    def __generateTI(self) -> None:
        node = helpers.tryGetNode(f"{self.modelSelector.currentText}_TI")
        if node is not None:
            slicer.mrmlScene.RemoveNode(node)
            del node

        sinGANParameters = SinGANParameters(
            model=self.modelSelector.getSelectedModelPath(),
            hardData=None,
            hardDataSegments=[],
            imagelog=None,
            imagelogSegments=[],
            chosenScale=0,
            numberRealizations=1,
            outputName=f"{self.modelSelector.currentText}_TI",
            outputPath=Path(self.exportDirectoryButton.directory),
            saveOptions={
                "saveAll": True,
                "saveSequence": False,
                "saveBigImage": False,
                "saveFiles": False,
            },
            reconstruction=True,
            harDataResolution=None,
            method=self.cropMethodComboBox.currentData,
            base_volume=self.baseVolumeSpin.value,
            split_scale=self.splitScaleSpin.value,
            crop_scale=self.cropScaleSpin.value,
            disk_scale=self.diskScaleSpin.value,
            chunks=self.__getChunkSizes(),
            p2p=False,
            partitions=self.partitionsSpinBox.value,
            seed=0,
        )

        self.cancelButton.setEnabled(True)
        self.__toggleUI(False)

        self.logic.apply(sinGANParameters, self.__onCLICompleted, self.cliProgressBar)

    def __previewHD(self) -> None:
        if self.modelSelector.currentData is None:
            print("NO MODEL")  # TODO Replace with error
            return

        if self.hardDataWidget.mainInput.currentNode() is None:
            return

        hardDataNode = self.hardDataWidget.mainInput.currentNode()
        if isinstance(hardDataNode, slicer.vtkMRMLSegmentationNode):
            hardDataNode, _ = helpers.createLabelmapInput(hardDataNode, "tempHDLabelmap")

        setScale = -1
        if self.useScaleCheckBox.isChecked():
            setScale = self.hdScale.value

        modelPath = Path(self.modelSelector.getSelectedModelPath())
        progressBar = self.cliProgressBar

        self.logic.generateHDPreview(setScale, modelPath, hardDataNode, progressBar)

    def __onHardDataChange(self) -> None:
        self.__updateApplyButtonStatus()
        self.__updateOutputPrefix()
        self.previewHDScales.setEnabled(
            self.hardDataWidget.mainInput.currentNode() is not None and self.modelSelector.currentData is not None
        )
        self.__updateMethodSelector()

    def __onImagelogChange(self) -> None:
        node = self.imagelogWidget.mainInput.currentNode()
        if node is not None and node.GetImageData().GetDimensions()[1] == 1:
            self.imagelogPreview.setEnabled(True)
        else:
            self.imagelogPreview.setEnabled(False)

    def __imagelogWrap(self) -> None:
        helpers.removeTemporaryNodes()
        if self.previewSegmentationNode is None:
            node = self.imagelogWidget.mainInput.currentNode()

            if isinstance(node, slicer.vtkMRMLSegmentationNode):
                node, _ = helpers.createLabelmapInput(node, "previewLabelmap")
                node.CreateDefaultDisplayNodes()

            self.previewSegmentationNode = MultiScaleLogic().generatePreview(node, 122)
            self.previewSegmentationNode.GetSegmentation().SetConversionParameter("Smoothing factor", "0.0")
            displayNode = self.previewSegmentationNode.GetDisplayNode()
            displayNode.SetOpacity(1)
            self.previewSegmentationNode.CreateClosedSurfaceRepresentation()

            self.imagelogPreview.setText("Remove 3D preview")
        else:
            self.previewSegmentationNode = None
            self.imagelogPreview.setText("Create 3D representation of imagelog")

    def __listItemChange(self, item):
        self.__updateApplyButtonStatus()
        if self.previewSegmentationNode is not None:
            displayNode = self.previewSegmentationNode.GetDisplayNode()
            displayNode.SetSegmentOpacity(item.text(), 1 if item.checkState() == qt.Qt.Checked else 0)

    def __updateOutputPrefix(self) -> None:
        text = ""
        if self.hardDataWidget.mainInput.currentNode() is not None:
            text = self.hardDataWidget.mainInput.currentNode().GetName()

        self.outputPrefix.text = f"{text}_singan"

    def __onSaveAsFileChange(self) -> None:
        self.exportDirectoryButton.setEnabled(self.saveAsFileCheckBox.isChecked())
        self.__updateApplyButtonStatus()

    def __onCancel(self) -> None:
        self.logic.cancelCLI()

    def __onCLICompleted(self) -> None:
        self.isRunning = False
        self.__updateApplyButtonStatus()
        self.cancelButton.setEnabled(False)
        self.__toggleUI(True)


class SinGANModuleLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.cliNodeModifiedObserver = None
        self.temporaryPath = None
        self.hardDataColorTable = None
        self.saveAsSequence = None
        self.saveAsVolume = None
        self.saveAsBigImage = None
        self.outputPath = None

    def apply(self, data: SinGANParameters, onCLICompleted, progressBar=None):
        self.temporaryPath = Path(slicer.util.tempDirectory())
        self.saveAsSequence = data.saveOptions["saveSequence"]
        self.saveAsVolume = data.saveOptions["saveAll"]
        self.saveAsBigImage = data.saveOptions["saveBigImage"]
        self.outputPath = data.outputPath
        self.onCLICompleted = onCLICompleted

        cliConfig = {
            "model_path": data.model,
            "temp_path": self.temporaryPath.as_posix(),
            "use_gpu": True,
            "gpu_device": 0,
            "injection_scale": "hd" if data.chosenScale == 0 else str(data.chosenScale),
            "number_realizations": data.numberRealizations,
            # "injected_class": int(data.hardDataSegments[0] if data.hardDataSegments else 2),
            "out_name": data.outputName,
            "out_path": data.outputPath.as_posix(),
            "save_bin": data.saveOptions["saveAll"] or data.saveOptions["saveSequence"],
            "save_file": data.saveOptions["saveFiles"],
            "rec": data.reconstruction,
            "method": data.method,
            "partitions": data.partitions,
            "seed": data.seed,
        }

        if data.method in [GENERATION_METHODS["By chunks"], GENERATION_METHODS["Early crop"]]:
            cliConfig["base_volume"] = data.base_volume
            cliConfig["split_scale"] = data.split_scale
            cliConfig["crop_scale"] = data.crop_scale
            cliConfig["disk_scale"] = data.disk_scale

        if data.method == GENERATION_METHODS["By chunks"]:
            chunks = r"{},{},{}".format(data.chunks[0], data.chunks[1], data.chunks[2])
            cliConfig["chunks"] = chunks
        elif data.method == GENERATION_METHODS["Early crop"]:
            cliConfig["p2p"] = data.p2p

        if data.hardData is not None:
            tempHardData, _ = helpers.createLabelmapInput(data.hardData, "TEMP_HARD_DATA", tag=self.__class__.__name__)
            cliConfig["cond_img"] = tempHardData.GetID()
            cliConfig["cond_img_resolution"] = data.harDataResolution
            directions = np.eye(3)
            slicer.util.getNode(cliConfig["cond_img"]).GetIJKToRASDirections(directions)
            directions = directions.tolist()
            cliConfig["directions"] = directions

            hardDataSegments = ",".join(map(str, data.hardDataSegments))
            cliConfig["hard_data"] = hardDataSegments

        if data.imagelog is not None:
            tempImagelog, _ = helpers.createLabelmapInput(data.imagelog, "TEMP_IMAGELOG", tag=self.__class__.__name__)
            cliConfig["imagelog"] = tempImagelog.GetID()

            imagelogSegments = ",".join(map(str, data.imagelogSegments))
            cliConfig["imagelog_segments"] = imagelogSegments

        self.cliNode = slicer.cli.run(
            slicer.modules.singancli,
            None,
            cliConfig,
            wait_for_completion=False,
        )

        self.cliNodeModifiedObserver = self.cliNode.AddObserver(
            "ModifiedEvent", lambda c, ev, info=cliConfig: self.__onCliModifiedEvent(c, ev, info)
        )

        if progressBar is not None:
            progressBar.visible = True
            progressBar.setCommandLineModuleNode(self.cliNode)

    def __onCliModifiedEvent(self, caller, event, info):
        if not self.cliNode:
            return

        if caller is None:
            del self.cliNode
            self.cliNode = None
            return

        if caller.IsBusy():
            return

        if caller.GetStatusString() == "Completed":
            if self.saveAsVolume or self.saveAsSequence:
                directions = []
                if "cond_img" in info:
                    directions = info["directions"]

                volumesList = []

                for realization in range(info["number_realizations"]):
                    name = (
                        f"{info['out_name']}_{realization}"
                        if info["number_realizations"] > 1
                        else f"{info['out_name']}"
                    )

                    volumesList.append(
                        self.__createVolume(
                            (self.temporaryPath / f"output_{realization}.npy"), info["model_path"], name, directions
                        )
                    )

                if self.saveAsSequence:
                    background = self.__createSequence(
                        volumesList, info["model_path"], info["out_name"], not self.saveAsVolume
                    )
                else:
                    background = volumesList[-1]

                slicer.util.setSliceViewerLayers(
                    label=background,
                    fit=True,
                )

            if self.saveAsBigImage:
                for realization in range(info["number_realizations"]):
                    BigImageLogic().loadDatasetFromPath((self.outputPath / f"R{realization}"))

        if self.cliNodeModifiedObserver is not None:
            self.cliNode.RemoveObserver(self.cliNodeModifiedObserver)
            self.cliNodeModifiedObserver = None

        del self.cliNode
        self.cliNode = None

        self.__cleanUp()
        self.onCLICompleted()

    def __cleanUp(self) -> None:
        shutil.rmtree(self.temporaryPath, ignore_errors=True)
        helpers.removeTemporaryNodes(environment=self.__class__.__name__)

    def __getModelSpacing(self, modelPath: Path) -> list:
        spacing = get_metadata(modelPath)["ti_resolution_mm"]

        return [spacing, spacing, spacing]

    def __createVolume(
        self, imagePath: Path, modelPath: Path, name: str, IJKToRASDirections: list
    ) -> slicer.vtkMRMLLabelMapVolumeNode:
        image = np.load(imagePath)

        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", name)
        slicer.util.updateVolumeFromArray(volume, image.astype(np.uint8))

        modelSpacing = self.__getModelSpacing(modelPath)

        volume.SetSpacing(modelSpacing)

        if IJKToRASDirections:
            volume.SetIJKToRASDirections(IJKToRASDirections)

        self.__setColorNode(volume)

        transformAdded = volume.AddCenteringTransform()
        if transformAdded:
            volume.HardenTransform()
            slicer.mrmlScene.RemoveNode(slicer.util.getNode(volume.GetName() + " centering transform"))

        return volume

    def __createSequence(self, volumeList: list, name: str, deleteVolumes: bool) -> slicer.vtkMRMLLabelMapVolumeNode:
        sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", f"{name}_sequence")
        sequenceNode.SetIndexUnit("")
        sequenceNode.SetIndexName("Volume")

        browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", f"{name}_browser")
        browserNode.SetIndexDisplayFormat("%.0f")

        for index in range(len(volumeList)):
            node = volumeList[index]
            sequenceNode.SetDataNodeAtValue(node, str(index))

        if deleteVolumes:
            for node in volumeList:
                slicer.mrmlScene.RemoveNode(node)

        browserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())

        proxyNode = browserNode.GetProxyNode(sequenceNode)
        proxyNode.SetName(f"{name}_proxy")

        self.__setColorNode(proxyNode)

        return proxyNode

    def __setColorNode(self, volume: slicer.vtkMRMLLabelMapVolumeNode) -> None:
        colorNode = slicer.util.loadColorTable(Path(__file__).parent / "Resources" / COLOR_TABLE_TEMPLATE)

        volume.CreateDefaultDisplayNodes()
        volume.GetDisplayNode().SetAndObserveColorNodeID(colorNode.GetID())

    def cancelCLI(self) -> None:
        if self.cliNode:
            self.cliNode.Cancel()

    def generateHDPreview(self, setScale, modelPath, hardDataNode, progressBar) -> None:
        resampleLogic = CustomResampleScalarVolumeLogic(progressBar=progressBar)

        modelDimensions = self.__getDimensionsFromModel(-1, modelPath)
        injectionStartScale = self.__getInjectionStartScaleFromModel(modelPath, hardDataNode, modelDimensions)
        if 1 not in modelDimensions.keys():
            return
        baseX, baseY, baseZ = modelDimensions[injectionStartScale][2:5]

        spacingX, spacingY, spacingZ = hardDataNode.GetSpacing()
        condX, condY, condZ = hardDataNode.GetImageData().GetDimensions()

        multiFactorX = condX / baseX
        multiFactorY = condY / baseY
        multiFactorZ = condZ / baseZ
        # Create sequence
        sequenceNode = None
        if setScale == -1:
            sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "HD_PREVIEW")
            sequenceNode.SetIndexUnit("")
            sequenceNode.SetIndexName("scale")

        lastScale = max(modelDimensions.keys())
        scales = [setScale] if setScale != -1 else range(injectionStartScale, lastScale + 1)
        for scale in scales:
            if scale not in modelDimensions.keys():
                continue

            scaleX, scaleY, scaleZ = modelDimensions[scale][2:6]

            newX, newY, newZ = [scaleX * multiFactorX, scaleY * multiFactorY, scaleZ * multiFactorZ]
            newSpacing = [condX / newX * spacingX, condY / newY * spacingY, condZ / newZ * spacingZ]
            resampleData = ResampleScalarVolumeData(
                input=hardDataNode,
                outputSuffix="singan_resample",
                x=newSpacing[0],
                y=newSpacing[1],
                z=newSpacing[2],
                interpolationType="Nearest Neighbor",
            )

            resampleLogic.run(resampleData)
            cliNode = resampleLogic.cliNode

            info = {
                "scale": scale,
                "sequence": sequenceNode,
                "last_scale": lastScale,
                "color_node": hardDataNode.GetDisplayNode().GetColorNodeID(),
            }

            cliNode.AddObserver(
                "ModifiedEvent", lambda caller, event, info=info: self.__sendResampleSignal(caller, event, info)
            )

    def __getDimensionsFromModel(self, setScale, modelPath):
        modelDimensions = {}
        for dir in modelPath.iterdir():
            if not dir.is_dir():
                continue

            modelFile = dir / "shape.pth"
            if modelFile.exists():
                if setScale != -1 and int(dir.name) not in [1, setScale]:
                    continue

                model = torch.load(modelFile)
                modelDimensions[int(dir.name)] = list(model)
                del model

        return modelDimensions

    def __getInjectionStartScaleFromModel(self, modelPath, hardDataNode, modelDimensions):
        tiRes = get_metadata(modelPath)["ti_resolution_mm"]
        modelDimensions = [modelDimensions[i] for i in modelDimensions]
        modelDimensions.sort(key=lambda x: x[4])
        tiSize = np.array([i * tiRes for i in modelDimensions[-1][-3:]])
        resolutions = np.array([[tiSize[-3] / i[-3], tiSize[-2] / i[-2], tiSize[-1] / i[-1]] for i in modelDimensions])
        mean_resolutions = resolutions.mean(axis=1)
        spacingX, spacingY, spacingZ = hardDataNode.GetSpacing()
        HDResolution = (spacingX + spacingY + spacingZ) / 3
        coreCTResolution = HDResolution
        absDiff = np.absolute(mean_resolutions - coreCTResolution)
        return np.argmin(absDiff)

    def __sendResampleSignal(self, caller, event, info):
        if caller.GetStatusString() == "Completed":
            outputNodeName = caller.GetParameterAsString("OutputVolume")
            node = helpers.tryGetNode(outputNodeName)
            node.CreateDefaultDisplayNodes()

            if info["sequence"] is not None:
                helpers.makeNodeTemporary(node, hide=True, save=False)
                info["sequence"].SetDataNodeAtValue(node, str(info["scale"]))
                helpers.removeTemporaryNodes(environment=self.__class__.__name__)

            if info["scale"] == info["last_scale"] and info["sequence"] is not None:
                self.__createBrowserFromSequence(info["sequence"], info["color_node"])
            elif info["sequence"] is None:
                node.SetName(f"HD_PREVIEW_Scale_{info['scale']}")
                slicer.util.setSliceViewerLayers(background=None, label=node)

    def __createBrowserFromSequence(self, sequenceNode, colorNodeID):
        browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "Browser_HD_PREVIEW")
        browserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())

        activeNode = browserNode.GetProxyNode(sequenceNode)
        activeNode.CreateDefaultDisplayNodes()
        activeNode.GetDisplayNode().SetAndObserveColorNodeID(colorNodeID)

        slicer.modules.sequences.toolBar().setActiveBrowserNode(browserNode)
        slicer.modules.sequences.setToolBarVisible(True)
        slicer.util.setSliceViewerLayers(background=None, label=activeNode)
