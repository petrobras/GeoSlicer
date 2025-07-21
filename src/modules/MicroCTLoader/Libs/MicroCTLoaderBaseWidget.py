import ctk
import qt
import slicer

import json
import logging
import ltrace.algorithms.detect_cups as cups
import traceback

from .ManualCylinderCrop import ManualCylinderCropWidget
from .RawLoader import RawLoaderWidget
from dataclasses import dataclass, field
from ltrace.slicer import microct, tescan
from ltrace.slicer.helpers import (
    highlight_error,
    BlockSignals,
)
from ltrace.slicer.ui import DirOrFileWidget
from ltrace.slicer_utils import *
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.units import global_unit_registry as ureg
from ltrace.utils.callback import Callback
from pathlib import Path
from threading import Lock

COLORS = [(1, 0, 0), (0, 0.5, 1), (1, 0, 1)]


@dataclass
class LoadParameters:
    callback: Callback = Callback()
    imageSpacing1: float = 1.0 * ureg.micrometer
    imageSpacing2: float = 1.0 * ureg.micrometer
    imageSpacing3: float = 1.0 * ureg.micrometer
    centerVolume: bool = True
    invertDirections: list[bool] = field(default_factory=lambda: [True, True, False])
    loadAsLabelmap: bool = False


class MicroCTLoaderBaseWidget(LTracePluginWidget):
    # Settings constants
    DIALOG_DIRECTORY = "MicroCTLoader/dialogDirectory"
    IMAGE_SPACING_1 = "MicroCTLoader/imageSpacing1"
    IMAGE_SPACING_2 = "MicroCTLoader/imageSpacing2"
    IMAGE_SPACING_3 = "MicroCTLoader/imageSpacing3"
    CENTER_VOLUME = "MicroCTLoader/centerVolume"

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.moduleName = "MicroCTLoader"
        self.is3dBatch = False
        self.loadOrigin = [0 * ureg.millimeter] * 3

    def exit(self):
        self.rawWidget.exit()

    def getImageSpacing1(self):
        return slicer.app.settings().value(self.IMAGE_SPACING_1, "1")

    def getImageSpacing2(self):
        return slicer.app.settings().value(self.IMAGE_SPACING_2, "1")

    def getImageSpacing3(self):
        return slicer.app.settings().value(self.IMAGE_SPACING_3, "1")

    def getCenterVolume(self):
        return slicer.app.settings().value(self.CENTER_VOLUME, str(True))

    def setupNormalWidget(self):
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        outputLayout = qt.QFormLayout(outputCollapsibleButton)

        self.imageSpacingValidator = qt.QRegExpValidator(qt.QRegExp("[+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?"))

        tooltip = "Voxel size in micrometers."
        self.imageSpacing1LineEdit = qt.QLineEdit(self.getImageSpacing1())
        self.imageSpacing1LineEdit.setValidator(self.imageSpacingValidator)
        self.imageSpacing1LineEdit.setToolTip(tooltip)
        self.imageSpacing1LineEdit.setObjectName("Image Spacing 1")

        self.imageSpacing2LineEdit = qt.QLineEdit(self.getImageSpacing2())
        self.imageSpacing2LineEdit.setValidator(self.imageSpacingValidator)
        self.imageSpacing2LineEdit.setToolTip(tooltip)
        self.imageSpacing2LineEdit.setObjectName("Image Spacing 2")

        self.imageSpacing3LineEdit = qt.QLineEdit(self.getImageSpacing3())
        self.imageSpacing3LineEdit.setValidator(self.imageSpacingValidator)
        self.imageSpacing3LineEdit.setToolTip(tooltip)
        self.imageSpacing3LineEdit.setObjectName("Image Spacing 3")

        loadHBoxLayout = qt.QHBoxLayout()
        loadHBoxLayout.addWidget(self.imageSpacing1LineEdit)
        loadHBoxLayout.addWidget(self.imageSpacing2LineEdit)
        loadHBoxLayout.addWidget(self.imageSpacing3LineEdit)
        voxelSizeLabel = qt.QLabel("Voxel size (μm):")
        voxelSizeLabel.setObjectName("voxelSizeLabel")
        outputLayout.addRow(voxelSizeLabel, loadHBoxLayout)

        self.centerVolumeCheckbox = qt.QCheckBox("Center volume")
        self.centerVolumeCheckbox.setChecked(self.getCenterVolume() == "True")
        self.loadAsLabelmapCheckBox = qt.QCheckBox("Load as Labelmap")
        self.loadAsLabelmapCheckBox.setToolTip(
            "If selected, a labelmap volume will be created instead of scalar volume."
        )
        self.loadAsSequenceCheckBox = qt.QCheckBox("Load volumes as sequence")
        self.loadAsSequenceCheckBox.setToolTip(
            "If selected, the multiple 3D volumes import will output a single sequence instead of multiple singular volumes."
        )
        self.loadAsSequenceCheckBox.setEnabled(False)

        self.widthDirectionCheckbox = qt.QCheckBox("Width (x)")
        self.widthDirectionCheckbox.setChecked(True)
        self.widthDirectionCheckbox.setObjectName("invertWidth")

        self.lengthDirectionCheckbox = qt.QCheckBox("Length (y)")
        self.lengthDirectionCheckbox.setChecked(True)
        self.lengthDirectionCheckbox.setObjectName("invertLength")

        self.heightDirectionCheckbox = qt.QCheckBox("Height (z)")
        self.heightDirectionCheckbox.setChecked(False)
        self.heightDirectionCheckbox.setObjectName("invertHeight")

        invertHelpButton = HelpButton(
            "By default, GeoSlicer reverses the orientation of the width and length in imported 3D .tif files. To maintain the original settings, uncheck the options below."
        )

        optionsLayout = qt.QHBoxLayout()
        optionsLayout.addWidget(self.widthDirectionCheckbox)
        optionsLayout.addWidget(self.lengthDirectionCheckbox)
        optionsLayout.addWidget(self.heightDirectionCheckbox)
        optionsLayout.addWidget(invertHelpButton)

        self.optionsWidgets = qt.QWidget()
        self.optionsWidgets.setLayout(optionsLayout)
        self.optionsWidgets.setVisible(False)
        self.invertLabel = qt.QLabel("Invert directions:")
        self.invertLabel.setVisible(False)

        outputLayout.addRow("", self.centerVolumeCheckbox)
        outputLayout.addRow("", self.loadAsLabelmapCheckBox)
        outputLayout.addRow("", self.loadAsSequenceCheckBox)
        outputLayout.addRow(self.invertLabel, self.optionsWidgets)
        outputLayout.addRow(" ", None)

        self.loadButton = qt.QPushButton("Load micro CTs")
        self.loadButton.setFixedHeight(40)
        self.loadButton.enabled = False
        outputLayout.addRow(self.loadButton)

        self.loadButton.clicked.connect(self.onLoadButtonClicked)

        statusLabel = qt.QLabel("Status: ")
        self.currentStatusLabel = qt.QLabel("Idle")
        statusHBoxLayout = qt.QHBoxLayout()
        statusHBoxLayout.addStretch(1)
        statusHBoxLayout.addWidget(statusLabel)
        statusHBoxLayout.addWidget(self.currentStatusLabel)
        outputLayout.addRow(statusHBoxLayout)

        self.progressBar = qt.QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        outputLayout.addRow(self.progressBar)

        self.manualCylinderWidget = ManualCylinderCropWidget()
        outputLayout.addRow(self.manualCylinderWidget)
        self.outputLayout = outputLayout
        self.progressBar.hide()

        self.progressMux = Lock()

        self._setInvertWidgetVisibility(False)

        return outputCollapsibleButton

    def setupRawWidget(self):
        rawWidget = RawLoaderWidget(self)
        rawParamsSection = rawWidget.parametersCollapsibleButton
        return rawWidget, rawParamsSection

    def setup(self):
        LTracePluginWidget.setup(self)

        self.unloaded = True

        main_frame = qt.QFrame()
        main_layout = qt.QVBoxLayout(main_frame)
        self.layout.addWidget(main_frame)

        frame = qt.QFrame()
        main_layout.addWidget(frame)

        self.loadFormLayout = qt.QFormLayout(frame)
        self.loadFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.loadFormLayout.setContentsMargins(0, 0, 0, 0)

        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")

        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)

        globs = [f"*{ext}" for ext in microct.MICRO_CT_LOADER_FILE_EXTENSIONS]
        globs += ["*.raw"]
        self.pathWidget = DirOrFileWidget(
            settingKey=self.DIALOG_DIRECTORY,
            fileCaption="Choose a microtomography image",
            dirCaption="Choose a folder of microtomography images",
            filters=f"Image files ({' '.join(globs)});;Any files (*)",
        )
        self.pathInfoLabel = qt.QLabel()

        self.pathWidget.pathSelected.connect(self.onPathSelected)

        inputFormLayout.addRow(" ", None)
        inputFormLayout.addRow(self.pathWidget)
        inputFormLayout.addRow(self.pathInfoLabel)
        inputFormLayout.addRow(" ", None)

        self.loadFormLayout.addRow(inputCollapsibleButton)

        self.normalWidget = self.setupNormalWidget()
        self.rawWidget, self.rawParamsSection = self.setupRawWidget()

        # For subclasses
        self.processingSection = ctk.ctkCollapsibleButton()
        self.processingSection.text = "Processing"
        processingLayout = qt.QFormLayout(self.processingSection)
        self.cropCylinderCheckBox = qt.QCheckBox("Auto-crop rock cylinder")
        self.cropCylinderCheckBox.setToolTip(
            "Automatically detect upright rock cylinder and crop it. The original image will also be loaded."
        )
        cropCylinderChecked = slicer.app.settings().value("MicroCTLoader/CropCylinderChecked", "False") == "True"
        self.cropCylinderCheckBox.setChecked(cropCylinderChecked)

        processingLayout.addRow(self.cropCylinderCheckBox)

        self.loadFormLayout.addRow(self.rawParamsSection)
        self.loadFormLayout.addRow(self.processingSection)
        self.loadFormLayout.addRow(self.rawWidget)
        self.loadFormLayout.addRow(self.normalWidget)

        self.layout.addStretch()

        self.rawWidget.visible = False
        self.rawParamsSection.visible = False
        self.normalWidget.visible = False
        self.enableProcessing(False)

        if self.pathWidget.path != "":
            # Path is set from settings
            self.onPathSelected(self.pathWidget.path)

    def enableProcessing(self, enable):
        self.processingSection.collapsed = not enable
        self.processingSection.enabled = enable
        self.cropCylinderCheckBox.setChecked(enable)

    def onPathSelected(self, path):
        self.pathWidget.pathLineEdit.setStyleSheet("")

        if self.pathWidget.path.strip() == "":
            message = "No images found"
            self._setInvertWidgetVisibility(False)
            highlight_error(self.pathWidget.pathLineEdit)
            self.pathInfoLabel.setText(message)
            return

        path = Path(path)
        isFile = path.is_file() and path.is_absolute()

        self.rawWidget.visible = False
        self.rawParamsSection.visible = False
        self.normalWidget.visible = True

        self.enableProcessing(True)

        self.is3dBatch = False

        if path.suffix in (".nc", ".h5", ".hdf5"):
            self._setImageSpacingVisibility(False)
            self._setInvertWidgetVisibility(False)
            filetype = "NetCDF" if path.suffix == ".nc" else "HDF5"
            message = f"Will import image(s) from {filetype} file"
            self.loadButton.enabled = True
        elif path.suffix == ".raw":
            self.rawWidget.visible = True
            self.rawParamsSection.visible = True
            self.normalWidget.visible = False
            message = "Will import a single image from RAW file"
            self.rawWidget.onCurrentPathChanged(path)
        else:  # File path is a directory or a single file
            tescan_info = tescan.get_tescan_info(path)
            if tescan_info is None:
                spacing = microct.detectSpacing(Path(self.pathWidget.path))
                mmSpacing = [f"{s.m_as('micrometer'):.3f}" for s in spacing] if spacing else None
                self._setImageSpacingVisibility(True, values=mmSpacing)
            else:
                self._setImageSpacingVisibility(True, values=(str(tescan_info.spacing * 1000),) * 3)
                with BlockSignals(self.pathWidget):
                    path = tescan_info.image_dir
                    self.pathWidget.path = path
                self.loadOrigin = [o * ureg.millimeter for o in tescan_info.origin_xyz]

            self.pathInfoLabel.setText("Analyzing...")
            slicer.app.processEvents()
            sliceCount, images, is3dBatch = microct.getCountsAndLoadPathsForImageFiles(path)

            if images and images[0].suffix == ".nc":
                self._setImageSpacingVisibility(False)
                message = "Will import image(s) from NetCDF file"
                self.loadButton.enabled = True
            else:
                self.loadButton.enabled = sliceCount > 0

                if sliceCount == 0:
                    message = "No images found"
                    self._setInvertWidgetVisibility(False)
                    highlight_error(self.pathWidget.pathLineEdit)
                elif sliceCount == 1:
                    message = f"Will import a single slice from {images[0].name}"
                    self._setInvertWidgetVisibility(True)
                elif sliceCount > 1:
                    if is3dBatch:
                        self.is3dBatch = True
                        message = f"Will import {sliceCount} volumes"
                        self._setInvertWidgetVisibility(True)
                    else:
                        message = f"Will import a volume with {sliceCount} slices from {images[0].name}"
                        self._setInvertWidgetVisibility(isFile)

        self._setLoadAsSequenceEnabled(self.is3dBatch)

        self.pathInfoLabel.setText(message)

    def onLoadButtonClicked(self):
        if self.manualCylinderWidget.cylinderRoi:
            self.manualCylinderWidget.finishCrop()

        callback = self.updateStatus
        try:
            self.pathInfoLabel.setText("")

            path = Path(self.pathWidget.path)
            if not (
                self.imageSpacing1LineEdit.text and self.imageSpacing2LineEdit.text and self.imageSpacing3LineEdit.text
            ):
                raise LoadInfo("Voxel size is required.")
            slicer.app.settings().setValue(self.IMAGE_SPACING_1, self.imageSpacing1LineEdit.text)
            slicer.app.settings().setValue(self.IMAGE_SPACING_2, self.imageSpacing2LineEdit.text)
            slicer.app.settings().setValue(self.IMAGE_SPACING_3, self.imageSpacing3LineEdit.text)
            slicer.app.settings().setValue(self.CENTER_VOLUME, str(self.centerVolumeCheckbox.isChecked()))

            imageSpacing = (
                float(self.imageSpacing1LineEdit.text) * ureg.micrometer,
                float(self.imageSpacing2LineEdit.text) * ureg.micrometer,
                float(self.imageSpacing3LineEdit.text) * ureg.micrometer,
            )
            invertDirections = [
                self.widthDirectionCheckbox.isChecked(),
                self.lengthDirectionCheckbox.isChecked(),
                self.heightDirectionCheckbox.isChecked(),
            ]

            callback("Loading...", 10, True)
            firstNode, *otherNodes = microct.load(
                path,
                callback=callback,
                imageSpacing=imageSpacing,
                imageOrigin=self.loadOrigin,
                centerVolume=self.centerVolumeCheckbox.isChecked(),
                invertDirections=invertDirections,
                loadAsLabelmap=self.loadAsLabelmapCheckBox.isChecked(),
                loadAsSequence=self.loadAsSequenceCheckBox.isChecked(),
            )
            if firstNode and not len(otherNodes) > 0:
                processingSettings = self.checkProcessingSettings()
                willCrop = processingSettings.get("willCrop", False)
                self.postProcessing(node=firstNode, willCrop=willCrop, callback=callback)
        except LoadInfo as e:
            slicer.util.infoDisplay(str(e))
            return
        finally:
            callback("", 100)

    def _setLoadAsSequenceEnabled(self, enabled):
        self.loadAsSequenceCheckBox.setEnabled(enabled)
        if not enabled:
            self.loadAsSequenceCheckBox.setChecked(qt.Qt.Unchecked)

    def _setInvertWidgetVisibility(self, isVisible):
        self.centerVolumeCheckbox.setVisible(isVisible)
        self.loadAsLabelmapCheckBox.setVisible(isVisible)
        self.loadAsSequenceCheckBox.setVisible(isVisible)
        if not isVisible:
            self.loadAsLabelmapCheckBox.setChecked(qt.Qt.Unchecked)
        self.optionsWidgets.setVisible(isVisible)
        self.invertLabel.setVisible(isVisible)

    def _setImageSpacingVisibility(self, isVisible, values=None):
        if not values:
            values = ("1", "1", "1")
        self.imageSpacing1LineEdit.parent().findChild(qt.QLabel, "voxelSizeLabel").setVisible(isVisible)
        self.imageSpacing1LineEdit.setText(values[0])
        self.imageSpacing1LineEdit.setVisible(isVisible)
        self.imageSpacing2LineEdit.setText(values[1])
        self.imageSpacing2LineEdit.setVisible(isVisible)
        self.imageSpacing3LineEdit.setText(values[2])
        self.imageSpacing3LineEdit.setVisible(isVisible)
        self.centerVolumeCheckbox.setVisible(isVisible)

    def updateStatus(self, message, progress=None, processEvents=True):
        self.progressBar.show()
        self.currentStatusLabel.text = message
        if progress == -1:
            self.progressBar.setRange(0, 0)
        else:
            self.progressBar.setRange(0, 100)
            self.progressBar.setValue(progress)
            if self.progressBar.value == 100:
                self.progressBar.hide()
                self.currentStatusLabel.text = "Idle"
        if not processEvents:
            return
        if self.progressMux.locked():
            return
        with self.progressMux:
            slicer.app.processEvents()

    def checkProcessingSettings(self, *args, **kwargs) -> dict:
        return {
            "willCrop": self.cropCylinderCheckBox.isChecked(),
        }

    def normalize(self, *args, **kwargs) -> None:
        """Abstract method for normalization logic"""
        self.postProcessing(*args, **kwargs)

    def postProcessing(self, *args, **kwargs) -> None:
        """Apply post processing to the output based on the settings."""
        node = kwargs.get("node", None)
        willCrop = kwargs.get("willCrop", False)
        slicer.app.settings().setValue("MicroCTLoader/CropCylinderChecked", str(willCrop))

        if not node or not willCrop:
            return

        callback = kwargs.get("callback", lambda *a: None)
        manualCylinderWidget = kwargs.get("manualCylinderWidget", self.manualCylinderWidget)

        self.handleAutoCrop(node=node, willCrop=willCrop, manualCylinderWidget=manualCylinderWidget, callback=callback)

    def handleAutoCrop(
        self,
        node: slicer.vtkMRMLNode,
        willCrop: bool,
        manualCylinderWidget: ManualCylinderCropWidget,
        callback=lambda *args: None,
    ):
        slicer.app.settings().setValue("MicroCTLoader/CropCylinderChecked", str(willCrop))

        if not willCrop:
            return

        manualCylinderWidget.volumeInput.setCurrentNode(node)
        manualCylinderWidget.onVolumeChanged(node)

        array = slicer.util.arrayFromVolume(node)

        callback("Detecting rock cylinder...", 20)
        try:
            cylinder = cups.detect_rock_cylinder(array)
        except Exception as e:
            logging.error(f"Failed to detect rock cylinder: {e}.\n{traceback.format_exc()}")
            cylinder = None
        finally:
            if not cylinder:
                logging.debug("No rock cylinder detected.")

        if cylinder:
            float_cylinder = [float(x) for x in cylinder]
            node.SetAttribute("RockCylinder", json.dumps(float_cylinder))

            manualCylinderWidget.onAdjustButtonClicked()
            manualCylinderWidget.instructionLabel.set_instruction(ManualCylinderCropWidget.SUCCESS_INSTRUCTION)
        else:
            manualCylinderWidget.onAdjustButtonClicked()
            manualCylinderWidget.instructionLabel.set_instruction(ManualCylinderCropWidget.ERROR_INSTRUCTION)

        manualCylinderWidget.section.collapsed = False


class LoadInfo(RuntimeError):
    pass
