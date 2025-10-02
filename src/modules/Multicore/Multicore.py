import logging
import os
import pickle
import shutil
import uuid
import warnings
import ctk
import numpy as np
import qt
import slicer
import vtk
import traceback

from collections import namedtuple
from pathlib import Path
from threading import Lock
from DICOMLib.DICOMUtils import TemporaryDICOMDatabase
from ltrace.image.core_box.core_box_depth_table_file import CoreBoxDepthTableFile
from ltrace.slicer.helpers import setVolumeNullValue, save_path
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer.ui import MultiplePathsWidget
from ltrace.slicer_utils import *
from ltrace.transforms import transformPoints, getRoundedInteger
from ltrace.units import global_unit_registry as ureg, SLICER_LENGTH_UNIT
from ltrace.utils.callback import Callback
from scipy.ndimage import gaussian_filter
from ltrace.utils.ProgressBarProc import ProgressBarProc


def useProgressBar(func):
    def wrapper(*args):
        multicoreWidget = args[0]
        with ProgressBarProc() as bar:
            multicoreWidget.progressBarProc = bar
            try:
                result = func(*args)
            finally:
                multicoreWidget.progressBarProc = None
        return result

    return wrapper


class Multicore(LTracePlugin):
    SETTING_KEY = "Multicore"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Multicore"
        self.parent.categories = ["Core", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.setHelpUrl("Core/Multicore.html", NodeEnvironment.CORE)
        self.setHelpUrl("Multiscale/ImportTools/Multicore.html", NodeEnvironment.MULTISCALE)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MulticoreWidget(LTracePluginWidget):
    # Settings constants
    DIALOG_DIRECTORY = "dialogDirectory"
    CORE_BOUNDARIES_FILE = "coreBoundariesFile"
    INITIAL_DEPTH = "initialDepth"
    CORE_GAP = "coreGap"
    CORE_LENGTH = "coreLength"
    CORE_DIAMETER = "coreDiameter"
    WELL_DIAMETER = "wellDiameter"
    UNWRAP_RADIAL_DEPTH = "unwrapRadialDepth"
    ORIENTATION_ALGORITHM = "orientationAlgorithm"
    ORIENTATION_ALGORITHM_NONE = 0
    ORIENTATION_ALGORITHM_SURFACE = 1
    ORIENTATION_ALGORITHM_SINUSOID = 2
    ORIENTATION_ALGORITHM_SURFACE_SINUSOID = 3
    KEEP_ORIGINAL_VOLUMES = "keepOriginalVolumes"
    CORE_RADIAL_CORRECTION = "coreRadialCorrection"
    SMOOTH_CORE_SURFACE = "smoothCoreSurface"
    DEPTH_CONTROL = "depthControl"
    DEPTH_CONTROL_INITIAL_DEPTH = 0
    DEPTH_CONTROL_CORE_BOUNDARIES = 1

    ProcessCoresParameters = namedtuple(
        "ProcessCoresParameters",
        [
            "callback",
            "pathList",
            INITIAL_DEPTH,
            CORE_GAP,
            CORE_DIAMETER,
            CORE_RADIAL_CORRECTION,
            SMOOTH_CORE_SURFACE,
            KEEP_ORIGINAL_VOLUMES,
            CORE_BOUNDARIES_FILE,
            CORE_LENGTH,
            DEPTH_CONTROL,
        ],
    )

    OrientCoresParameters = namedtuple("OrientCoresParameters", ["callback", ORIENTATION_ALGORITHM])

    UnwrapCoresParameters = namedtuple("UnwrapCoresParameters", ["callback", UNWRAP_RADIAL_DEPTH, WELL_DIAMETER])

    ApplyAllParameters = namedtuple(
        "ApplyAllParameters",
        [
            "callback",
            "pathList",
            INITIAL_DEPTH,
            CORE_GAP,
            CORE_DIAMETER,
            CORE_RADIAL_CORRECTION,
            SMOOTH_CORE_SURFACE,
            KEEP_ORIGINAL_VOLUMES,
            ORIENTATION_ALGORITHM,
            UNWRAP_RADIAL_DEPTH,
            WELL_DIAMETER,
            CORE_BOUNDARIES_FILE,
            CORE_LENGTH,
            DEPTH_CONTROL,
        ],
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        # Raise an exception for this kind of warning (when trying to detect circles on alignment phase)
        warnings.filterwarnings("error", message="Mean of empty slice.")

    def getDialogDirectory(self):
        return Multicore.get_setting(self.DIALOG_DIRECTORY, default=str(Path.home()))

    def getInitialDepth(self):
        return Multicore.get_setting(self.INITIAL_DEPTH, default="5422")

    def getCoreLength(self):
        return Multicore.get_setting(self.CORE_LENGTH, default="90")

    def getCoreGap(self):
        return Multicore.get_setting(self.CORE_GAP, default="0")

    def getCoreDiameter(self):
        return Multicore.get_setting(self.CORE_DIAMETER, default="5")

    def getWellDiameter(self):
        return Multicore.get_setting(self.WELL_DIAMETER, default="12")

    def getUnwrapRadialDepth(self):
        return Multicore.get_setting(self.UNWRAP_RADIAL_DEPTH, default="4")

    def getAutomaticOrientation(self):
        return Multicore.get_setting(self.ORIENTATION_ALGORITHM, default=self.ORIENTATION_ALGORITHM_NONE)

    def getRadialCorrection(self):
        return Multicore.get_setting(self.CORE_RADIAL_CORRECTION, default=str(True))

    def getSmoothSurface(self):
        return Multicore.get_setting(self.SMOOTH_CORE_SURFACE, default=str(True))

    def getKeepOriginalVolumes(self):
        return Multicore.get_setting(self.KEEP_ORIGINAL_VOLUMES, default=str(False))

    def getDepthControl(self):
        return Multicore.get_setting(self.DEPTH_CONTROL, default=self.DEPTH_CONTROL_INITIAL_DEPTH)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = MulticoreLogic()

        processCollapsibleButton = ctk.ctkCollapsibleButton()
        processCollapsibleButton.text = "Process, orient and unwrap"
        self.layout.addWidget(processCollapsibleButton)
        processFormLayout = qt.QFormLayout(processCollapsibleButton)
        processFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        processFormLayout.addRow("Data to be processed:", None)
        self.multiplePathsWidget = MultiplePathsWidget(
            self.getDialogDirectory(), self.multiplePathWidgetAddCallback, directoriesOnly=True, singleDirectory=False
        )
        processFormLayout.addRow(self.multiplePathsWidget)
        processFormLayout.addRow(" ", None)

        self.depthControlComboBox = qt.QComboBox()
        self.depthControlComboBox.addItem("Initial depth and core length", self.DEPTH_CONTROL_INITIAL_DEPTH)
        self.depthControlComboBox.addItem("Core boundaries CSV file", self.DEPTH_CONTROL_CORE_BOUNDARIES)
        self.depthControlComboBox.setCurrentIndex(self.depthControlComboBox.findData(self.getDepthControl()))
        self.depthControlComboBox.currentIndexChanged.connect(self.onDepthControlComboBoxCurrentItemChanged)
        processFormLayout.addRow("Depth control:", self.depthControlComboBox)
        self.depthControlComboBox.setToolTip("Select an option to define the core depths")

        self.coreBoundariesLabel = qt.QLabel("Core depth file:")
        self.coreBoundariesFileButton = ctk.ctkPathLineEdit()
        self.coreBoundariesFileButton.filters = ctk.ctkPathLineEdit.Files
        self.coreBoundariesFileButton.setToolTip("Input file with core depths according to the help tab.")
        self.coreBoundariesFileButton.settingKey = "Multicore/CoreBoundariesFile"
        processFormLayout.addRow(self.coreBoundariesLabel, self.coreBoundariesFileButton)

        self.locale = qt.QLocale(qt.QLocale.C)
        self.locale.setNumberOptions(qt.QLocale.RejectGroupSeparator)

        self.initialDepthLabel = qt.QLabel("Initial depth (m):")
        self.initialDepthLineEdit = qt.QLineEdit(self.getInitialDepth())
        self.initialDepthValidator = qt.QDoubleValidator()
        self.initialDepthValidator.setLocale(self.locale)
        self.initialDepthValidator.bottom = 0
        self.initialDepthLineEdit.setValidator(self.initialDepthValidator)
        self.initialDepthLineEdit.setToolTip("Depth at the top of the first core in the batch")
        processFormLayout.addRow(self.initialDepthLabel, self.initialDepthLineEdit)

        self.coreLengthLabel = qt.QLabel("Core length (cm):")
        self.coreLengthLineEdit = qt.QLineEdit(self.getCoreLength())
        self.coreLengthValidator = qt.QDoubleValidator()
        self.coreLengthValidator.setLocale(self.locale)
        self.coreLengthValidator.bottom = 0
        self.coreLengthLineEdit.setValidator(self.coreLengthValidator)
        self.coreLengthLineEdit.setToolTip("Core length in centimeters")
        processFormLayout.addRow(self.coreLengthLabel, self.coreLengthLineEdit)

        processFormLayout.addRow(" ", None)

        self.coreDiameterLineEdit = qt.QLineEdit(self.getCoreDiameter())
        self.coreDiameterValidator = qt.QDoubleValidator()
        self.coreDiameterValidator.setLocale(self.locale)
        self.coreDiameterValidator.bottom = 0
        self.coreDiameterLineEdit.setValidator(self.coreDiameterValidator)
        self.coreDiameterLineEdit.setToolTip("Core diameter in inches")
        processFormLayout.addRow("Core diameter (inch):", self.coreDiameterLineEdit)
        self.coreGapLineEdit = qt.QLineEdit(self.getCoreGap())
        self.coreGapValidator = qt.QDoubleValidator()
        self.coreGapValidator.setLocale(self.locale)
        self.coreGapValidator.bottom = 0
        self.coreGapLineEdit.setValidator(self.coreGapValidator)
        self.coreGapLineEdit.setToolTip("Gap between each core in millimeters")
        # processFormLayout.addRow("Core gap (mm):", self.coreGapLineEdit)
        self.coreRadialCorrectionCheckBox = qt.QCheckBox("Core radial correction")
        self.coreRadialCorrectionCheckBox.setChecked(self.getRadialCorrection() == "True")
        processFormLayout.addRow(None, self.coreRadialCorrectionCheckBox)
        self.smoothCoreSurfaceCheckBox = qt.QCheckBox("Smooth core surface")
        self.smoothCoreSurfaceCheckBox.setChecked(self.getSmoothSurface() == "True")
        processFormLayout.addRow(None, self.smoothCoreSurfaceCheckBox)
        self.keepOriginalVolumesCheckBox = qt.QCheckBox("Keep original volumes")
        self.keepOriginalVolumesCheckBox.setChecked(self.getKeepOriginalVolumes() == "True")
        processFormLayout.addRow(None, self.keepOriginalVolumesCheckBox)
        self.processCoresButton = qt.QPushButton("Process cores")
        processFormLayout.addRow(None, self.processCoresButton)
        processFormLayout.addRow(" ", None)

        self.orientationAlgorithmComboBox = qt.QComboBox()
        self.orientationAlgorithmComboBox.addItem("None", self.ORIENTATION_ALGORITHM_NONE)
        self.orientationAlgorithmComboBox.addItem("Surface", self.ORIENTATION_ALGORITHM_SURFACE)
        self.orientationAlgorithmComboBox.addItem("Sinusoid", self.ORIENTATION_ALGORITHM_SINUSOID)
        self.orientationAlgorithmComboBox.addItem("Surface + Sinusoid", self.ORIENTATION_ALGORITHM_SURFACE_SINUSOID)
        self.orientationAlgorithmComboBox.setCurrentIndex(
            self.orientationAlgorithmComboBox.findData(self.getAutomaticOrientation())
        )
        processFormLayout.addRow("Orientation algorithm:", self.orientationAlgorithmComboBox)
        self.orientCoresButton = qt.QPushButton("Orient cores")
        processFormLayout.addRow(None, self.orientCoresButton)
        processFormLayout.addRow(" ", None)

        self.unwrapRadialDepthLineEdit = qt.QLineEdit(self.getUnwrapRadialDepth())
        self.unwrapRadialDepthValidator = qt.QDoubleValidator()
        self.unwrapRadialDepthValidator.setLocale(self.locale)
        self.unwrapRadialDepthValidator.bottom = 0
        self.unwrapRadialDepthLineEdit.setValidator(self.unwrapRadialDepthValidator)
        self.unwrapRadialDepthLineEdit.setToolTip("Radial distance from the core surface to create the unwrap")
        processFormLayout.addRow("Unwrap radial depth (mm):", self.unwrapRadialDepthLineEdit)
        self.wellDiameterLineEdit = qt.QLineEdit(self.getWellDiameter())
        self.wellDiameterValidator = qt.QDoubleValidator()
        self.wellDiameterValidator.setLocale(self.locale)
        self.wellDiameterValidator.bottom = 0
        self.wellDiameterLineEdit.setValidator(self.wellDiameterValidator)
        self.wellDiameterLineEdit.setToolTip("Well diameter in inches")
        processFormLayout.addRow("Well diameter (inch):", self.wellDiameterLineEdit)
        self.unwrapCoresButton = qt.QPushButton("Unwrap cores")
        processFormLayout.addRow(None, self.unwrapCoresButton)
        processFormLayout.addRow(" ", None)

        self.applyAllButton = qt.QPushButton("Apply all")
        self.applyAllButton.setFixedHeight(40)
        processFormLayout.addRow(self.applyAllButton)
        processFormLayout.addRow(" ", None)

        self.processCoresButton.clicked.connect(self.onProcessCoresButton)
        self.orientCoresButton.clicked.connect(self.onOrientCoresButton)
        self.unwrapCoresButton.clicked.connect(self.onUnwrapCoresButton)
        self.applyAllButton.clicked.connect(self.onApplyAllButton)

        self.onDepthControlComboBoxCurrentItemChanged()

        statusLabel = qt.QLabel("Status: ")
        self.currentStatusLabel = qt.QLabel("Idle")
        statusHBoxLayout = qt.QHBoxLayout()
        statusHBoxLayout.addStretch(1)
        statusHBoxLayout.addWidget(statusLabel)
        statusHBoxLayout.addWidget(self.currentStatusLabel)
        self.layout.addLayout(statusHBoxLayout)

        self.progressBar = qt.QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        self.layout.addWidget(self.progressBar)
        self.progressBar.hide()

        self.progressMux = Lock()

        self.progressBarProc = None

    def onDepthControlComboBoxCurrentItemChanged(self):
        if self.depthControlComboBox.currentData == self.DEPTH_CONTROL_INITIAL_DEPTH:
            self.initialDepthLabel.visible = True
            self.initialDepthLineEdit.visible = True
            self.coreLengthLabel.visible = True
            self.coreLengthLineEdit.visible = True
            self.coreBoundariesLabel.visible = False
            self.coreBoundariesFileButton.visible = False
        else:
            self.initialDepthLabel.visible = False
            self.initialDepthLineEdit.visible = False
            self.coreLengthLabel.visible = False
            self.coreLengthLineEdit.visible = False
            self.coreBoundariesLabel.visible = True
            self.coreBoundariesFileButton.visible = True

    def multiplePathWidgetAddCallback(self, lastPathString):
        Multicore.set_setting(MulticoreWidget.DIALOG_DIRECTORY, lastPathString)

    @useProgressBar
    def processCores(self, callback, pathList):
        Multicore.set_setting(self.INITIAL_DEPTH, self.initialDepthLineEdit.text)
        Multicore.set_setting(self.CORE_GAP, self.coreGapLineEdit.text)
        Multicore.set_setting(self.CORE_DIAMETER, self.coreDiameterLineEdit.text)
        Multicore.set_setting(self.CORE_RADIAL_CORRECTION, str(self.coreRadialCorrectionCheckBox.isChecked()))
        Multicore.set_setting(self.SMOOTH_CORE_SURFACE, str(self.smoothCoreSurfaceCheckBox.isChecked()))
        Multicore.set_setting(self.KEEP_ORIGINAL_VOLUMES, str(self.keepOriginalVolumesCheckBox.isChecked()))
        Multicore.set_setting(self.CORE_LENGTH, self.coreLengthLineEdit.text)
        Multicore.set_setting(self.DEPTH_CONTROL, self.depthControlComboBox.currentData)
        save_path(self.coreBoundariesFileButton)
        processCoresParameters = self.ProcessCoresParameters(
            callback,
            pathList,
            float(self.initialDepthLineEdit.text) * ureg.meter,
            float(self.coreGapLineEdit.text) * ureg.millimeter,
            (float(self.coreDiameterLineEdit.text) * ureg.inch).to(ureg.millimeter),
            self.coreRadialCorrectionCheckBox.isChecked(),
            self.smoothCoreSurfaceCheckBox.isChecked(),
            self.keepOriginalVolumesCheckBox.isChecked(),
            self.coreBoundariesFileButton.currentPath,
            float(self.coreLengthLineEdit.text) * ureg.centimeter,
            self.depthControlComboBox.currentData,
        )
        self.logic.processCores(processCoresParameters)

    def onProcessCoresButton(self):
        callback = Callback(
            on_update=lambda message, percent, processEvents=True: self.updateStatus(
                message,
                progress=percent,
                processEvents=processEvents,
            )
        )
        try:
            pathList = self.multiplePathsWidget.directoryListView.directoryList
            if len(pathList) == 0:
                raise ProcessInfo("There are no data to be loaded. Add directories.")
            if self.depthControlComboBox.currentData == self.DEPTH_CONTROL_INITIAL_DEPTH:
                if not self.initialDepthLineEdit.text:
                    raise ProcessInfo("Initial depth is required.")
                if not self.coreLengthLineEdit.text:
                    raise ProcessInfo("Core length is required.")
            if self.depthControlComboBox.currentData == self.DEPTH_CONTROL_CORE_BOUNDARIES:
                if not self.coreBoundariesFileButton.currentPath:
                    raise ProcessInfo("Core boundaries file is required.")
            # if not self.coreGapLineEdit.text:
            #     raise ProcessInfo("Core gap is required.")
            if not self.coreDiameterLineEdit.text:
                raise ProcessInfo("Core diameter is required.")

            self.processCores(callback, pathList)
        except ProcessInfo as e:
            slicer.util.infoDisplay(str(e))
            return
        except ProcessError as e:
            slicer.util.errorDisplay(str(e))
            return
        finally:
            callback.on_update("Process cores completed.", 100)

    @useProgressBar
    def orientCores(self, callback):
        Multicore.set_setting(self.ORIENTATION_ALGORITHM, self.orientationAlgorithmComboBox.currentData)
        orientCoresParameters = self.OrientCoresParameters(callback, self.orientationAlgorithmComboBox.currentData)
        self.logic.orientCores(orientCoresParameters)

    def onOrientCoresButton(self):
        callback = Callback(
            on_update=lambda message, percent, processEvents=True: self.updateStatus(
                message,
                progress=percent,
                processEvents=processEvents,
            )
        )
        try:
            if self.orientationAlgorithmComboBox.currentData == self.ORIENTATION_ALGORITHM_NONE:
                raise ProcessInfo("Orientation algorithm is required.")
            self.orientCores(callback)
        except ProcessInfo as e:
            slicer.util.infoDisplay(str(e))
            return
        finally:
            callback.on_update("Orient cores completed.", 100)

    @useProgressBar
    def unwrapCores(self, callback):
        Multicore.set_setting(self.WELL_DIAMETER, self.wellDiameterLineEdit.text)
        Multicore.set_setting(self.UNWRAP_RADIAL_DEPTH, self.unwrapRadialDepthLineEdit.text)
        unwrapCoresParameters = self.UnwrapCoresParameters(
            callback,
            float(self.unwrapRadialDepthLineEdit.text) * ureg.millimeter,
            float(self.wellDiameterLineEdit.text) * ureg.inch,
        )
        self.logic.unwrapCores(unwrapCoresParameters)

    def onUnwrapCoresButton(self, callback):
        callback = Callback(
            on_update=lambda message, percent, processEvents=True: self.updateStatus(
                message,
                progress=percent,
                processEvents=processEvents,
            )
        )
        try:
            if not self.wellDiameterLineEdit.text:
                raise ProcessInfo("Well diameter is required.")
            if float(self.wellDiameterLineEdit.text) * ureg.inch < float(self.coreDiameterLineEdit.text) * ureg.inch:
                raise ProcessInfo("Well diameter must be equal or larger than core diameter.")
            if not self.unwrapRadialDepthLineEdit.text:
                raise ProcessInfo("Unwrap radial depth is required.")
            self.unwrapCores(callback)
        except ProcessInfo as e:
            slicer.util.infoDisplay(str(e))
            return
        finally:
            callback.on_update("Unwrap cores completed.", 100)

    @useProgressBar
    def applyAll(self, callback, pathList):
        Multicore.set_setting(self.INITIAL_DEPTH, self.initialDepthLineEdit.text)
        Multicore.set_setting(self.CORE_GAP, self.coreGapLineEdit.text)
        Multicore.set_setting(self.CORE_DIAMETER, self.coreDiameterLineEdit.text)
        Multicore.set_setting(self.CORE_RADIAL_CORRECTION, str(self.coreRadialCorrectionCheckBox.isChecked()))
        Multicore.set_setting(self.SMOOTH_CORE_SURFACE, str(self.smoothCoreSurfaceCheckBox.isChecked()))
        Multicore.set_setting(self.KEEP_ORIGINAL_VOLUMES, str(self.keepOriginalVolumesCheckBox.isChecked()))
        Multicore.set_setting(self.WELL_DIAMETER, self.wellDiameterLineEdit.text)
        Multicore.set_setting(self.UNWRAP_RADIAL_DEPTH, self.unwrapRadialDepthLineEdit.text)
        Multicore.set_setting(self.CORE_LENGTH, self.coreLengthLineEdit.text)
        Multicore.set_setting(self.DEPTH_CONTROL, self.depthControlComboBox.currentData)
        save_path(self.coreBoundariesFileButton)
        applyAllParameters = self.ApplyAllParameters(
            callback,
            pathList,
            float(self.initialDepthLineEdit.text) * ureg.meter,
            float(self.coreGapLineEdit.text) * ureg.millimeter,
            (float(self.coreDiameterLineEdit.text) * ureg.inch).to(ureg.millimeter),
            self.coreRadialCorrectionCheckBox.isChecked(),
            self.smoothCoreSurfaceCheckBox.isChecked(),
            self.keepOriginalVolumesCheckBox.isChecked(),
            self.orientationAlgorithmComboBox.currentData,
            float(self.unwrapRadialDepthLineEdit.text) * ureg.millimeter,
            float(self.wellDiameterLineEdit.text) * ureg.inch,
            self.coreBoundariesFileButton.currentPath,
            float(self.coreLengthLineEdit.text) * ureg.centimeter,
            self.depthControlComboBox.currentData,
        )
        self.logic.applyAll(applyAllParameters)

    def onApplyAllButton(self):
        callback = Callback(
            on_update=lambda message, percent, processEvents=True: self.updateStatus(
                message,
                progress=percent,
                processEvents=processEvents,
            )
        )
        try:
            pathList = self.multiplePathsWidget.directoryListView.directoryList
            if len(pathList) == 0:
                raise ProcessInfo("There are no data to be loaded. Add directories.")
            if self.depthControlComboBox.currentData == self.DEPTH_CONTROL_INITIAL_DEPTH:
                if not self.initialDepthLineEdit.text:
                    raise ProcessInfo("Initial depth is required.")
                if not self.coreLengthLineEdit.text:
                    raise ProcessInfo("Core length is required.")
            if self.depthControlComboBox.currentData == self.DEPTH_CONTROL_CORE_BOUNDARIES:
                if not self.coreBoundariesFileButton.currentPath:
                    raise ProcessInfo("Core boundaries file is required.")
            # if not self.coreGapLineEdit.text:
            #     raise ProcessInfo("Core gap is required.")
            if not self.coreDiameterLineEdit.text:
                raise ProcessInfo("Core diameter is required.")
            if self.orientationAlgorithmComboBox.currentData == self.ORIENTATION_ALGORITHM_NONE:
                raise ProcessInfo("Orientation algorithm is required.")
            if not self.wellDiameterLineEdit.text:
                raise ProcessInfo("Well diameter is required.")
            if float(self.wellDiameterLineEdit.text) * ureg.inch < float(self.coreDiameterLineEdit.text) * ureg.inch:
                raise ProcessInfo("Well diameter must be equal or larger than core diameter.")
            if not self.unwrapRadialDepthLineEdit.text:
                raise ProcessInfo("Unwrap radial depth is required.")
            self.applyAll(callback, pathList)
        except ProcessInfo as e:
            slicer.util.infoDisplay(str(e))
            return
        except ProcessError as e:
            slicer.util.errorDisplay(str(e))
            return
        finally:
            callback.on_update("Apply all completed.", 100)

    def updateStatus(self, message, progress=None, processEvents=True):
        self.progressBar.show()
        self.currentStatusLabel.text = message
        if progress == -1:
            self.progressBar.setRange(0, 0)
        else:
            self.progressBar.setRange(0, 100)
            self.progressBar.setValue(progress)
            if self.progressBarProc:
                self.progressBarProc.setProgress(int(progress))
                self.progressBarProc.setMessage(message)
            if self.progressBar.value == 100:
                self.progressBar.hide()
        if not processEvents:
            return
        if self.progressMux.locked():
            return
        with self.progressMux:
            slicer.app.processEvents()


class MulticoreLogic(LTracePluginLogic):
    HIDDEN_ATTRIBUTE_FLAG = "(hidden) "
    UNWRAP_OUTDATED_FLAG = " (outdated)"
    ROOT_DATASET_DIRECTORY_NAME = "Multicore"
    GLOBAL_DIRECTORY_NAME = "Global"
    BASE_NAME_VOLUME_TYPE_SEPARATOR = " - "
    UNWRAP_THICKNESS = 1
    EMPTY_VOXEL_INTENSITY = -3024

    # Keys
    BASE_NAME = "Base name"
    NODE_TYPE = "Volume type"
    DEPTH = "Depth"
    LENGTH = "Length"
    CORE_DIAMETER = "Core diameter"
    ORIENTATION_ANGLE = "Orientation angle"
    WELL_DIAMETER = "Well diameter"
    UNWRAP_UPDATED = "Unwrap updated"
    UNWRAP_RADIAL_DEPTH = "Unwrap radial depth"
    WINDOW_LEVEL_MIN_MAX = HIDDEN_ATTRIBUTE_FLAG + "Window/level min and max"  # Necessary to global window/level
    ORIGINAL_DISPLAY_NODE_ID = HIDDEN_ATTRIBUTE_FLAG + "Original display node id"  # Necessary when unlinking

    # Node types
    NODE_TYPE_ORIGINAL_VOLUME = "Original"
    NODE_TYPE_CORE_VOLUME = "Core"
    NODE_TYPE_CORE_UNWRAP_VOLUME = "Core unwrap"
    NODE_TYPE_WELL_UNWRAP_VOLUME = "Well unwrap"

    def __init__(self):
        LTracePluginLogic.__init__(self)

    def applyAll(self, p):
        self.processCores(p)
        self.orientCores(p)
        self.unwrapCores(p)

    def processCores(self, p):
        if p.depthControl == MulticoreWidget.DEPTH_CONTROL_INITIAL_DEPTH:
            self.remainingCoreBoundaries = self.getCoreBoundariesFromInitialDepth(p.initialDepth, p.coreLength)
        else:
            self.remainingCoreBoundaries = self.getCoreBoundariesFromFile(p.coreBoundariesFile)

        errors = []
        for directory in p.pathList:
            directory = Path(directory)
            errors += self.processDirectory(p, directory)

        # Post processing
        try:
            windowLevelMinMax = self.calculateGlobalWindowLevelMinMax()
            volumes = self.getVolumes()
            numVolumes = len(volumes)
            for i in range(numVolumes):
                p.callback.on_update(
                    "Applying global window/level to all volumes", getRoundedInteger(i * 100 / numVolumes)
                )
                self.setWindowLevelMinMax(volumes[i], windowLevelMinMax)
            self.sortDirectoriesByCoreDepth()
            self.centerOnFirstCoreVolume()
        except RuntimeWarning as e:
            pass
        except Exception as e:
            errors.append(f"Error while applying global window level: {e}")

        if errors:
            slicer.util.errorDisplay("Errors occurred while processing cores:\n\n" + "\n".join(errors))

    def processDirectory(self, p, directory):
        # Checking if the datasets directory contains .dcm (DICOM) files at the maximum of one subdirectory level bellow
        if ".dcm" not in str(list(directory.glob("*.dcm"))) and ".dcm" not in str(list(directory.glob("*/*.dcm"))):
            raise ProcessInfo("No datasets were detected.")

        # Creates a "unique" directory to store database files
        dataDirectoryPath = Path(slicer.app.temporaryPath).absolute() / uuid.uuid4().hex
        with TemporaryDICOMDatabase(str(dataDirectoryPath / "CtkDICOMDatabase")) as db:
            self.indexDatasets(p, db, directory)
            datasets = slicer.dicomDatabase.patients()

            numDatasetsDetected = len(datasets)
            if numDatasetsDetected == 0:
                raise ProcessInfo("No datasets were detected.")

            coreBoundaries, self.remainingCoreBoundaries = (
                self.remainingCoreBoundaries[:numDatasetsDetected],
                self.remainingCoreBoundaries[numDatasetsDetected:],
            )
            if len(coreBoundaries) < numDatasetsDetected:
                raise ProcessError(
                    "There are insufficient core boundaries for the number of datasets detected. Processing was aborted."
                )

            errors = []
            for i in range(numDatasetsDetected):
                plugin, loadable = self.getPluginLoadableFromDataset(datasets[i])
                baseName = Path(loadable.files[0]).absolute().parent.name
                p.callback.on_update("Processing " + baseName + "...", getRoundedInteger(i * 100 / numDatasetsDetected))

                subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
                # Remove the dataset directory with the same base name (and its contents) if it exists
                subjectHierarchyNode.RemoveItem(subjectHierarchyNode.GetItemByName(baseName))
                # Remove the Global directory because it will be outdated
                subjectHierarchyNode.RemoveItem(subjectHierarchyNode.GetItemByName(self.GLOBAL_DIRECTORY_NAME))

                originalVolume = plugin.load(loadable)
                subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
                subjectID = subjectHierarchyNode.GetItemParent(
                    subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(originalVolume))
                )

                self.configureInitialNodeMetadata(originalVolume, baseName, self.NODE_TYPE_ORIGINAL_VOLUME)
                subjectHierarchyNode.RemoveItem(subjectID)

                try:
                    self.processCore(p, originalVolume, coreBoundaries[i])
                except Exception as error:
                    error = f"Core {originalVolume.GetName()}: {error}"
                    logging.error(f"{error}.\n{traceback.format_exc()}")
                    errors.append(error)
                    extractedCoreVolume = self.getNodesByBaseNameAndNodeType(baseName, self.NODE_TYPE_CORE_VOLUME)
                    if len(extractedCoreVolume) == 1:
                        slicer.mrmlScene.RemoveNode(extractedCoreVolume[0])

                if not p.keepOriginalVolumes:
                    slicer.mrmlScene.RemoveNode(originalVolume)
            return errors

    def indexDatasets(self, p, db, directory):
        try:
            p.callback.on_update("Indexing datasets...", 0)

            def updateProgress(progress):
                p.callback.on_update("Indexing datasets...", progress, processEvents=False)

            self.indexer = ctk.ctkDICOMIndexer()
            assert self.indexer is not None
            self.indexer.connect("progress(int)", updateProgress)
            self.indexer.addDirectory(db, str(directory))
        except Exception:
            import traceback

            traceback.print_exc()
            logging.error("Failed to import DICOM folder " + p.datasetsDirectory)
            raise ProcessError("There were errors during the datasets indexing. Check their integrity.")

    def getPluginLoadableFromDataset(self, dataset):
        for study in slicer.dicomDatabase.studiesForPatient(dataset):
            series = slicer.dicomDatabase.seriesForStudy(study)
            for _, currentSeries in enumerate(series, start=1):
                files = slicer.dicomDatabase.filesForSeries(currentSeries)
                if len(files) < 100:
                    continue
                return self.getPluginAndLoadableForFiles(files)

    def getPluginAndLoadableForFiles(self, files):
        plugin = slicer.modules.dicomPlugins["DICOMScalarVolumePlugin"]()
        loadables = plugin.examine([files])
        loadables.sort(key=lambda x: x.confidence, reverse=True)
        if loadables[0].confidence > 0.1:
            return plugin, loadables[0]

    def getCoreBoundariesFromInitialDepth(self, initialDepth, coreLength):
        coreBoundaries = []
        depthInMeters = initialDepth.m_as(ureg.meter)
        coreLengthInMeters = coreLength.m_as(ureg.meter)
        for i in range(1000):  # Generate an array with a thousand core boundaries. It should be more than enough.
            coreBoundaries.append([depthInMeters, depthInMeters + coreLengthInMeters])
            depthInMeters += coreLengthInMeters
        return np.array(coreBoundaries) * ureg.meter

    def getCoreBoundariesFromFile(self, path):
        coreBondaries = []
        try:
            depth_file = CoreBoxDepthTableFile(path)
        except RuntimeError as e:
            raise ProcessError(str(e))
        for code_box_depths in depth_file.core_boxes_depth_list:
            coreBondaries.append([code_box_depths.start, code_box_depths.end])
        return np.array(coreBondaries) * ureg.meter

    def configureInitialNodeMetadata(
        self, node, baseName, nodeType, depth="", coreLength="", coreDiameter="", wellDiameter="", unwrapRadialDepth=""
    ):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        rootDirID = subjectHierarchyNode.GetItemByName(self.ROOT_DATASET_DIRECTORY_NAME)
        if rootDirID == 0:
            rootDirID = subjectHierarchyNode.CreateFolderItem(
                subjectHierarchyNode.GetSceneItemID(), self.ROOT_DATASET_DIRECTORY_NAME
            )
        dirID = subjectHierarchyNode.GetItemByName(baseName)
        if dirID == 0:
            dirID = subjectHierarchyNode.CreateFolderItem(rootDirID, baseName)
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(node),
            dirID,
        )
        node.SetAttribute(self.BASE_NAME, baseName)
        node.SetAttribute(self.NODE_TYPE, nodeType)
        node.SetName(
            self.BASE_NAME_VOLUME_TYPE_SEPARATOR.join(
                list(filter(None.__ne__, [node.GetAttribute(self.BASE_NAME), node.GetAttribute(self.NODE_TYPE)]))
            )
        )
        node.SetAttribute(self.ORIGINAL_DISPLAY_NODE_ID, node.GetDisplayNode().GetID())

        if nodeType == self.NODE_TYPE_CORE_VOLUME:
            self.setDepth(node, depth)
            self.setCoreLength(node, coreLength)
            node.SetAttribute(self.CORE_DIAMETER, str(np.round(coreDiameter.to(ureg.inch), 2)))
            self.setOrientationAngle(node)

        if nodeType == self.NODE_TYPE_CORE_UNWRAP_VOLUME:
            self.setDepth(node, depth)
            node.SetAttribute(self.UNWRAP_UPDATED, str(True))
            node.SetAttribute(self.UNWRAP_RADIAL_DEPTH, str(unwrapRadialDepth))

        if nodeType == self.NODE_TYPE_WELL_UNWRAP_VOLUME:
            self.setDepth(node, depth)
            node.SetAttribute(self.UNWRAP_UPDATED, str(True))
            node.SetAttribute(self.WELL_DIAMETER, str(wellDiameter))

        if nodeType == self.NODE_TYPE_ORIGINAL_VOLUME:
            node.RemoveAttribute("DICOM.instanceUIDs")
        else:
            setVolumeNullValue(node, self.EMPTY_VOXEL_INTENSITY)

    def configureVolumeDepth(self, volume, depth):
        # Translating the volume to the right depth
        bounds = np.zeros(6)
        volume.GetBounds(bounds)
        translationMatrix = np.array(
            [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, -bounds[5] - depth.m_as(SLICER_LENGTH_UNIT)], [0, 0, 0, 1]]
        )
        self.applyHardenedTransformationMatrix(volume, translationMatrix)

    def processCore(self, p, originalVolume, coreBoundary):
        baseName = originalVolume.GetAttribute(self.BASE_NAME)

        # Core volume extraction
        trueCoreRadius = self.alignCore(originalVolume, p.coreDiameter / 2)
        coreSegmentationNode = self.segmentCore(originalVolume, trueCoreRadius)
        extractedCoreVolume = self.extractCore(originalVolume, trueCoreRadius, coreSegmentationNode)
        self.configureInitialNodeMetadata(
            extractedCoreVolume,
            baseName,
            self.NODE_TYPE_CORE_VOLUME,
            depth=coreBoundary[0],
            coreLength=coreBoundary[1] - coreBoundary[0],
            coreDiameter=2 * trueCoreRadius,
        )

        # Post processing (on this order)
        if p.coreRadialCorrection:
            self.correctVoxelIntensity(extractedCoreVolume)
        if p.smoothCoreSurface:
            self.smoothCoreSurface(extractedCoreVolume)

        # Saving optimal extractedCoreVolume window/level
        windowLevelVolume = slicer.modules.volumes.logic().CloneVolume(
            slicer.mrmlScene, extractedCoreVolume, "Window/level volume"
        )
        self.setWindowLevel(windowLevelVolume, self.findWindowLevel(windowLevelVolume))
        displayNode = windowLevelVolume.GetDisplayNode()
        extractedCoreVolume.SetAttribute(
            self.WINDOW_LEVEL_MIN_MAX,
            str(displayNode.GetWindowLevelMin()) + "," + str(displayNode.GetWindowLevelMax()),
        )
        slicer.mrmlScene.RemoveNode(windowLevelVolume)

        self.configureVolumeDepth(extractedCoreVolume, coreBoundary[0])
        bounds = np.zeros(6)
        extractedCoreVolume.GetBounds(bounds)
        self.configureVolumeDepth(originalVolume, -bounds[5] * SLICER_LENGTH_UNIT)
        self.renderCoreVolume(extractedCoreVolume)

    def alignCore(self, volume, coreRadius):
        """
        Steps (including helper function calls):

        - Get the slice core centers in IJK coordinates and transform to RAS coordinates;
        - Calculate the core center translation matrix to the origin (using the coreSlicePositionsMean for X and Y, and
          the longitudinal boundary for the Z axis). It is necessary to use the boundaries for the Z axes because we
          have chances of not detecting circles in all the slices, which would shift the mean in Z;
        - Calculate the core longitudinal unit vector in RAS coordinates fitted to the slice core centers;
        - Calculate the rotation matrix that turns the longitudinal vector to the IS (Inferior-Superior) axis;
        - Apply the translation matrix to the volume and then the rotation matrix;
        """
        coreSlicePositions, trueCoreRadius = self.calculateCoreGeometry(volume, coreRadius)
        coreSlicePositionsMean = np.mean(coreSlicePositions, axis=0)
        bounds = np.zeros(6)
        volume.GetBounds(bounds)
        coreCenterTranslationMatrix = np.array(
            [
                [1, 0, 0, -coreSlicePositionsMean[0]],
                [0, 1, 0, -coreSlicePositionsMean[1]],
                [0, 0, 1, -(bounds[4] + bounds[5]) / 2],
                [0, 0, 0, 1],
            ]
        )
        coreAlignmentRotationMatrix = self.coreAlignmentRotationMatrix(coreSlicePositions, coreSlicePositionsMean)
        # The rotation is applied last
        self.applyHardenedTransformationMatrix(volume, np.dot(coreAlignmentRotationMatrix, coreCenterTranslationMatrix))
        return trueCoreRadius

    def calculateCoreGeometry(self, volume, coreRadius):
        temporaryDir = Path(slicer.util.tempDirectory(key=slicer.modules.MulticoreInstance.SETTING_KEY))
        coreGeometryDataFile = temporaryDir / "CoreGeometryData"
        parameters = {
            "volume": volume.GetID(),
            "coreRadius": coreRadius.m,
            "coreGeometryDataFile": str(coreGeometryDataFile),
        }
        slicer.cli.runSync(slicer.modules.coregeometrycli, None, parameters)
        if not coreGeometryDataFile.exists():
            raise Exception("Could not detect core geometry. Please check core dimensions and try again.")
        with open(coreGeometryDataFile, "rb") as f:
            coreGeometryData = pickle.loads(f.read())
        shutil.rmtree(temporaryDir)
        return coreGeometryData

    def coreAlignmentRotationMatrix(self, sliceCoreCenters, sliceCoreCentersMean):
        coreOrientationVector = np.linalg.svd(sliceCoreCenters - sliceCoreCentersMean)[2][0]
        # Vector with the same Z axis orientation as the SVD orientation vector (it varies depending on the sample)
        zAxisVector = np.array([0, 0, np.sign(coreOrientationVector[2])])
        # Calculating the core cylindrical segment rotation and translation matrices
        v = np.cross(coreOrientationVector, zAxisVector)
        v_sm = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        rotationMatrix3x3 = v_sm + np.dot(v_sm, v_sm) * (1 / (1 + np.dot(coreOrientationVector, zAxisVector)))
        rotationMatrix = np.identity(4)
        rotationMatrix[:3, :3] += rotationMatrix3x3
        return rotationMatrix

    def applyHardenedTransformationMatrix(self, volume, transformationMatrix):
        vtkTransformationMatrix = vtk.vtkMatrix4x4()
        vtkTransformationMatrix.DeepCopy(list(np.array(transformationMatrix).flat))
        # Applying the transformation to the volume
        transformNode = slicer.vtkMRMLTransformNode()
        slicer.mrmlScene.AddNode(transformNode)
        volume.SetAndObserveTransformNodeID(transformNode.GetID())
        transformNode.SetMatrixTransformToParent(vtkTransformationMatrix)
        volume.HardenTransform()
        slicer.mrmlScene.RemoveNode(transformNode)

    def segmentCore(self, volume, coreRadius):
        """
        For errors in the log file about 'Invalid segment editor parameter set node' see:
        https://discourse.slicer.org/t/threshold-scalar-volume-to-labelmap/4457/11
        """
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLSegmentationNode.__name__)

        # Creating segment editor to get access to effects
        segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
        segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        # slicer.savedWidget = segmentEditorWidget # this was used in 2019 for debugging purposes, now causes an error
        segmentEditorNode = slicer.vtkMRMLSegmentEditorNode()
        slicer.mrmlScene.AddNode(segmentEditorNode)
        segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)

        # Increasing the segmentation resolution
        geometryImageData = slicer.vtkOrientedImageData()
        geometryImageData.SetSpacing(*3 * [0.4])
        geometryString = slicer.vtkSegmentationConverter.SerializeImageGeometry(geometryImageData)
        segmentationNode.GetSegmentation().SetConversionParameter(
            slicer.vtkSegmentationConverter.GetReferenceImageGeometryParameterName(),
            geometryString,
        )

        # Creating the segmentation cylinder
        segmentationNode.CreateDefaultDisplayNodes()
        segmentationCylinder = vtk.vtkCylinderSource()
        segmentationCylinder.SetRadius(coreRadius.m)
        segmentationCylinder.SetHeight(
            1.1 * volume.GetImageData().GetDimensions()[2] * self.getInterSliceSpacing(volume).m
        )
        segmentationCylinder.SetResolution(400)
        coreSegmentRotationMatrix = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]])
        vtkTransformationMatrix = vtk.vtkMatrix4x4()
        vtkTransformationMatrix.DeepCopy(list(coreSegmentRotationMatrix.flat))
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
        segmentEditorWidget.setSourceVolumeNode(volume)

        # Thresholding to get rid of crack voxels inside the core
        segmentEditorWidget.setActiveEffectByName("Threshold")
        effect = segmentEditorWidget.activeEffect()
        # The bellow value is important in processes later (correcting of voxel intensity and surface smoothing). It is
        # slightly above water intensity range to remove noisy points outside the core (taken from Techniques for Using
        # Core CT Data for Facies Identification and Analysis)
        effect.setParameter("MinimumThreshold", "100")
        effect.setParameter("MaximumThreshold", str(volume.GetImageData().GetScalarRange()[1]))
        segmentEditorNode.SetMaskMode(segmentationNode.EditAllowedInsideAllSegments)
        effect.self().onApply()

        # Cleaning up
        slicer.mrmlScene.RemoveNode(transformNode)
        slicer.mrmlScene.RemoveNode(segmentEditorNode)
        return segmentationNode

    def extractCore(self, volume, coreRadius, segmentationNode):
        # Better vertically centering the volume (and the segmentation), now that we have the segmentation bounds
        segmentationBounds = np.zeros(6)
        segmentationNode.GetBounds(segmentationBounds)
        # Refining the volume and segmentation centering on the S axis, using the segmentation bounds
        zCenterTranslationMatrix = np.array(
            [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, -(segmentationBounds[4] + segmentationBounds[5]) / 2], [0, 0, 0, 1]]
        )
        self.applyHardenedTransformationMatrix(volume, zCenterTranslationMatrix)
        self.applyHardenedTransformationMatrix(segmentationNode, zCenterTranslationMatrix)
        # Using the new bounds also as the crop limits of the new extracted core volume
        segmentationNode.GetBounds(segmentationBounds)
        roi = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLMarkupsROINode.__name__)
        roiRadius = 1.05 * coreRadius  # A little extra room for the core
        roi.SetRadiusXYZ(roiRadius.m, roiRadius.m, (segmentationBounds[5] - segmentationBounds[4]) / 2)

        cropVolumeParametersNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLCropVolumeParametersNode.__name__)
        croppedVolume = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLScalarVolumeNode.__name__)
        cropVolumeParametersNode.SetOutputVolumeNodeID(croppedVolume.GetID())
        cropVolumeParametersNode.SetInputVolumeNodeID(volume.GetID())
        cropVolumeParametersNode.SetROINodeID(roi.GetID())
        cropVolumeLogic = slicer.modules.cropvolume.logic()
        cropVolumeLogic.Apply(cropVolumeParametersNode)

        # Create segment editor to get access to effects
        segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
        segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        # slicer.savedWidget = segmentEditorWidget # this was used in 2019 for debugging purposes, now causes an error
        segmentEditorNode = slicer.vtkMRMLSegmentEditorNode()
        slicer.mrmlScene.AddNode(segmentEditorNode)
        segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)
        segmentEditorWidget.setSegmentationNode(segmentationNode)
        segmentEditorWidget.setSourceVolumeNode(croppedVolume)

        # Creating mask to extract the core volume
        segmentEditorWidget.setCurrentSegmentID(segmentationNode.GetSegmentation().GetNthSegmentID(0))
        segmentEditorWidget.setActiveEffectByName("Mask volume")
        effect = segmentEditorWidget.activeEffect()
        segmentEditorNode.SetMaskSegmentID(segmentationNode.GetSegmentation().GetNthSegmentID(0))
        effect.setParameter("Operation", "FILL_OUTSIDE")
        effect.setParameter("FillValue", str(self.EMPTY_VOXEL_INTENSITY))
        effect.self().outputVolumeSelector.setCurrentNode(croppedVolume)
        effect.self().onApply()

        # Cleaning up
        slicer.mrmlScene.RemoveNode(roi)
        slicer.mrmlScene.RemoveNode(segmentationNode)
        return croppedVolume

    def correctVoxelIntensity(self, coreVolume):
        coreArray = slicer.util.arrayFromVolume(coreVolume)
        coreArrayMedian = np.median(coreArray, 0)
        coreArrayMedianShape = np.shape(coreArrayMedian)

        # Create an array of radii
        x, y = np.meshgrid(
            np.arange(-coreArrayMedianShape[0] / 2, coreArrayMedianShape[0] / 2),
            np.arange(-coreArrayMedianShape[1] / 2, coreArrayMedianShape[1] / 2),
        )
        R = np.sqrt(x**2 + y**2)

        # Calculate the median
        f = lambda r: np.median(coreArrayMedian[(R >= r - 0.5) & (R < r + 0.5)])
        radius = getRoundedInteger(
            self.physicalToImageCoordinates(self.getCoreRadius(coreVolume), self.getIntraSliceSpacing(coreVolume)).m
        )
        r = np.linspace(1, radius, num=radius)
        medians = np.vectorize(f)(r)

        for i in range(0, radius):
            coreArrayMedian[(R >= r[i] - 0.5) & (R < r[i] + 0.5)] = medians[i]

        coreArrayPositiveValuesMedian = np.median(coreArrayMedian[coreArrayMedian > 0])
        coreArrayMedian[coreArrayMedian < 0] = coreArrayPositiveValuesMedian

        minScalarValue = np.min(coreArray)
        newValues = (coreArray * coreArrayPositiveValuesMedian) / coreArrayMedian
        indexes = np.where(coreArray > minScalarValue)
        coreArray[indexes] = newValues[indexes]
        slicer.util.updateVolumeFromArray(coreVolume, coreArray)
        slicer.util.arrayFromVolumeModified(coreVolume)

    def smoothCoreSurface(self, coreVolume):
        radiusInPixels = self.physicalToImageCoordinates(
            self.getCoreRadius(coreVolume), self.getIntraSliceSpacing(coreVolume)
        )
        coreArray = slicer.util.arrayFromVolume(coreVolume)
        minIntensityValue = np.min(coreArray)
        coreArray = coreArray - minIntensityValue
        coreArray = self.circularArrayClipping(coreArray, radiusInPixels.m, 0)
        sliceShape = np.shape(coreArray[0])
        amplitude = np.diff(coreVolume.GetImageData().GetScalarRange())[0]
        gaussianFilter = np.full((1, *sliceShape), amplitude)
        gaussianFilter = self.circularArrayClipping(gaussianFilter, radiusInPixels.m, 0)
        gaussianFilter = gaussian_filter(gaussianFilter, sigma=2.5) / amplitude
        filteredArray = (coreArray[None, :, :] * gaussianFilter[0, :, :])[0]
        filteredArray = filteredArray + minIntensityValue
        filteredArray = np.round(filteredArray).astype(np.int16)
        slicer.util.updateVolumeFromArray(coreVolume, filteredArray)

    def circularArrayClipping(self, array, radius, clippingValue):
        xCenter = (len(array[0, :, 0]) - 1) / 2
        yCenter = (len(array[0, 0, :]) - 1) / 2
        arrayShape = np.shape(array)
        for x in range(arrayShape[1]):
            for y in range(arrayShape[2]):
                if np.sqrt((x - xCenter) ** 2 + (y - yCenter) ** 2) >= radius:
                    array[:, x, y] = clippingValue
        return array

    def findWindowLevel(self, coreVolume):
        unwrapArray = self.createUnwrapArray(coreVolume)
        unwrapVolume = self.createUnwrapVolume(unwrapArray, self.getSpacing(coreVolume))
        self.showVolumeInSliceViews(unwrapVolume)  # Necessary to find the window/level, since it uses the slice view
        displayNode = unwrapVolume.GetDisplayNode()
        displayNode.AutoWindowLevelOff()
        unwrapArray = slicer.util.arrayFromVolume(unwrapVolume)
        treatedUnwrapArray = unwrapArray.copy()
        treatedUnwrapArray[treatedUnwrapArray < 0] = np.median(treatedUnwrapArray)
        slicer.util.updateVolumeFromArray(unwrapVolume, treatedUnwrapArray)
        widget = slicer.vtkMRMLWindowLevelWidget()
        widget.SetSliceNode(slicer.util.getNode("vtkMRMLSliceNodeGreen"))
        widget.SetMRMLApplicationLogic(slicer.app.applicationLogic())
        widget.UpdateWindowLevelFromRectangle(0, [0, 0], [10**6, 10**6])
        window = displayNode.GetWindow()
        level = displayNode.GetLevel()
        slicer.mrmlScene.RemoveNode(unwrapVolume)
        return [window, level]

    def calculateGlobalWindowLevelMinMax(self):
        windowLevelMinimums, windowLevelMaximums = [], []
        for coreVolume in self.getCoreVolumes():
            windowLevelMinMax = [float(i) for i in coreVolume.GetAttribute(self.WINDOW_LEVEL_MIN_MAX).split(",")]
            windowLevelMinimums.append(windowLevelMinMax[0])
            windowLevelMaximums.append(windowLevelMinMax[1])
        return [np.mean(windowLevelMinimums), np.mean(windowLevelMaximums)]

    def setWindowLevel(self, volume, windowLevel):
        displayNode = self.getDisplayNode(volume)
        displayNode.AutoWindowLevelOff()
        displayNode.SetWindowLevel(*windowLevel)

    def setWindowLevelMinMax(self, volume, windowLevelMinMax):
        displayNode = self.getDisplayNode(volume)
        displayNode.AutoWindowLevelOff()
        displayNode.SetWindowLevelMinMax(*windowLevelMinMax)

    def getDisplayNode(self, volume):
        if volume.GetDisplayNode() is None:
            volume.CreateDefaultDisplayNodes()
        return volume.GetDisplayNode()

    def showVolumeInSliceViews(self, volume):
        slicer.util.setSliceViewerLayers(background=volume)
        slicer.util.resetSliceViews()

    def renderCoreVolume(self, coreVolume):
        volumeRenderingLogic = slicer.modules.volumerendering.logic()
        layoutManager = slicer.app.layoutManager()
        displayNode = volumeRenderingLogic.CreateDefaultVolumeRenderingNodes(coreVolume)
        displayNode.SetVisibility(True)
        for sliceViewLabel in ["Red", "Yellow", "Green"]:
            sliceView = layoutManager.sliceWidget(sliceViewLabel).sliceView()
            sliceView.mrmlSliceNode().SetSliceVisible(False)
        layoutManager.sliceWidget("Green").sliceLogic().GetSliceCompositeNode().SetBackgroundVolumeID(
            coreVolume.GetID()
        )

    def centerOnFirstCoreVolume(self):
        # Centering the 3D view on the scene
        # (necessary to make the option 'center volume to this volume' to work properly)
        layoutManager = slicer.app.layoutManager()
        threeDWidget = layoutManager.threeDWidget(0)
        threeDView = threeDWidget.threeDView()
        threeDView.resetFocalPoint()

        # Showing the first core volume on the slice views and centering on the 3D scene
        coreVolumes = self.getCoreVolumesSortedByDepth()
        self.showVolumeInSliceViews(coreVolumes[0])
        import SubjectHierarchyPlugins

        scriptedPlugin = slicer.qSlicerSubjectHierarchyScriptedPlugin(None)
        scriptedPlugin.setPythonSource(SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin.filePath)
        SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin(scriptedPlugin).centerToThisVolume(coreVolumes[0])

        # Setting surface smoothing here instead of WelcomeGeoSlicer because the cores must be loaded in order to work
        viewNode = slicer.app.layoutManager().threeDWidget(0).mrmlViewNode()
        viewNode.SetVolumeRenderingSurfaceSmoothing(True)

    def configureAnnotationROIMetadata(self, displayNode):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        volumeNode = displayNode.GetVolumeNode()
        baseName = volumeNode.GetAttribute(self.BASE_NAME)
        nodeType = volumeNode.GetAttribute(self.NODE_TYPE)
        dirID = subjectHierarchyNode.GetItemByName(baseName)
        roiNode = displayNode.GetROINode()
        roiNode.SetName(self.BASE_NAME_VOLUME_TYPE_SEPARATOR.join([baseName, nodeType + " ROI"]))
        subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(roiNode), dirID)

    def getCoreVolumesSortedByDepth(self):
        baseNamesAndDepths, coreVolumesSortedByDepth = [], []
        coreVolumes = self.getCoreVolumes()
        for coreVolume in coreVolumes:
            baseNamesAndDepths.append([coreVolume.GetAttribute(self.BASE_NAME), self.getDepth(coreVolume).m])
        if len(baseNamesAndDepths) > 0:
            baseNamesSortedByDepth = np.array(sorted(baseNamesAndDepths, key=lambda x: x[1]))[:, 0]
            coreVolumesSortedByDepth = []
            for baseName in baseNamesSortedByDepth:
                coreVolumesSortedByDepth.append(
                    self.getNodesByBaseNameAndNodeType(baseName, self.NODE_TYPE_CORE_VOLUME)[0]
                )
        return coreVolumesSortedByDepth

    def sortDirectoriesByCoreDepth(self):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        rootDataDirectory = subjectHierarchyNode.GetItemByName(self.ROOT_DATASET_DIRECTORY_NAME)
        position = 0
        directoryIDsAndDepths = []
        while True:
            directoryID = subjectHierarchyNode.GetItemByPositionUnderParent(rootDataDirectory, position)
            if directoryID == 0:  # Break when reaching all directories
                break
            baseName = subjectHierarchyNode.GetItemName(directoryID)
            if baseName == self.GLOBAL_DIRECTORY_NAME:
                coreDepth = -1
            else:
                coreDepth = self.getDepth(self.getNodesByBaseName(baseName)[0]).m
            directoryIDsAndDepths.append([directoryID, coreDepth])
            position += 1
        if len(directoryIDsAndDepths) > 0:
            directoriesSortedByCoreDepth = np.array(sorted(directoryIDsAndDepths, key=lambda x: x[1]))[:, 0].astype(
                np.int16
            )
            reorderingTemporaryDirectoryID = subjectHierarchyNode.CreateFolderItem(
                subjectHierarchyNode.GetSceneItemID(), "Reordering temporary directory"
            )
            # Moving to a temporary directory, ordered
            for directoryID in directoriesSortedByCoreDepth:
                subjectHierarchyNode.SetItemParent(
                    directoryID,
                    reorderingTemporaryDirectoryID,
                )
            # Moving back to the scene root, ordered
            for directoryID in directoriesSortedByCoreDepth:
                subjectHierarchyNode.SetItemParent(directoryID, rootDataDirectory)
                # This is needed for the True case work (bug)
                subjectHierarchyNode.SetItemExpanded(directoryID, False)
                subjectHierarchyNode.SetItemExpanded(directoryID, True)
            # Deleting the temporary directory
            subjectHierarchyNode.RemoveItem(reorderingTemporaryDirectoryID)

    def orientCores(self, p):
        coreVolumes = self.getCoreVolumesSortedByDepth()
        numCoreVolumes = len(coreVolumes)
        if numCoreVolumes == 0:
            raise ProcessInfo("There are no cores available to orient.")
        wellUnwrapVolumeOutdated = False
        for i in range(1, numCoreVolumes):
            p.callback.on_update(
                "Orienting " + coreVolumes[i].GetName() + "...",
                getRoundedInteger((i - 1) * 100 / (numCoreVolumes - 1)),
            )
            volumeOriented = self.orientCoreVolume(coreVolumes[i], coreVolumes[i - 1], p.orientationAlgorithm)
            if volumeOriented:
                unwrapVolume = self.getUnwrapVolume(coreVolumes[i])
                assert len(unwrapVolume) == 0 or len(unwrapVolume) == 1
                if len(unwrapVolume) == 1:
                    self.updateCoreUnwrapVolume(coreVolumes[i])
                wellUnwrapVolumeOutdated = True
        wellUnwrapVolume = self.getWellUnwrapVolume()
        if len(wellUnwrapVolume) == 1 and wellUnwrapVolumeOutdated:
            self.flagVolumeOutdated(wellUnwrapVolume[0])

    def flagVolumeOutdated(self, volume):
        volume.SetAttribute(self.UNWRAP_UPDATED, str(False))
        volume.SetName(volume.GetName().replace(self.UNWRAP_OUTDATED_FLAG, "") + self.UNWRAP_OUTDATED_FLAG)

    def orientCoreVolume(self, coreVolume, previousCoreVolume, automaticOrientation):
        """
        :return: True if the volume was oriented (angle different than zero was found)
        """
        angle = 0
        if automaticOrientation == MulticoreWidget.ORIENTATION_ALGORITHM_SURFACE:
            angle = self.coreVolumeOrientationAngleBySurface(coreVolume, previousCoreVolume)
        elif automaticOrientation == MulticoreWidget.ORIENTATION_ALGORITHM_SINUSOID:
            angle = self.coreVolumeOrientationAngleBySinusoid(coreVolume, previousCoreVolume)
        elif automaticOrientation == MulticoreWidget.ORIENTATION_ALGORITHM_SURFACE_SINUSOID:
            angle = self.coreVolumeOrientationAngleBySurface(coreVolume, previousCoreVolume)
            if angle == 0:
                angle = self.coreVolumeOrientationAngleBySinusoid(coreVolume, previousCoreVolume)

        foundAngle = angle != 0
        if foundAngle:
            rotationMatrix = np.array(
                [
                    [np.cos(angle), -np.sin(angle), 0, 0],
                    [np.sin(angle), np.cos(angle), 0, 0],
                    [0, 0, 1, 0],
                    [0, 0, 0, 1],
                ]
            )
            self.applyHardenedTransformationMatrix(coreVolume, rotationMatrix)
            self.setOrientationAngle(coreVolume)
        return foundAngle

    def setOrientationAngle(self, node):
        # Always set the orientation value taken directly from the transform matrix
        node.SetAttribute(
            self.ORIENTATION_ANGLE,
            str(
                self.around(
                    self.getVolumeTransformOrientationAngle(node).to(ureg.degree),
                    decimals=1,
                )
            ),
        )

    def coreVolumeOrientationAngleBySurface(self, currentCore, previousCore):
        """
        Orientation by surfaces plane fitting.
        """
        previousCoreBottomSurfacePoints = self.findRASSurfacePoints(previousCore)
        currentCoreTopSurfacePoints = self.findRASSurfacePoints(currentCore, fromTop=True)
        previousPerpendicularVector, previousCoreError = self.findPerpendicularVectorToFittedPlaneByZDistance(
            previousCoreBottomSurfacePoints
        )
        currentPerpendicularVector, currentCoreError = self.findPerpendicularVectorToFittedPlaneByZDistance(
            currentCoreTopSurfacePoints
        )

        # Projecting the vector on the RA plane and normalizing it, to find the orientation angle
        previousProjectedVector = self.normalizeVector(previousPerpendicularVector[:-1])
        currentProjectedVector = self.normalizeVector(currentPerpendicularVector[:-1])

        # Angles with respect to the S axis
        previousAngleToSAxis = np.arccos(np.dot(previousPerpendicularVector, [0, 0, -1]))
        currentAngleToSAxis = np.arccos(np.dot(currentPerpendicularVector, [0, 0, -1]))

        angle = 0
        # If the fitting errors are not large
        errorThresholdForNRMSD = 0.15
        # Minimum angle (radians) of the cut with respect to the S axis to be considered in orientation
        # (too shallow angles do not deliver good results)
        minSawCutAngle = 0.05
        # The two surfaces to be oriented must have equivalent angles (radians) with respect to the S axis
        angleSimilarityRange = 0.02
        if previousCoreError < errorThresholdForNRMSD and currentCoreError < errorThresholdForNRMSD:
            # If the current plane has some meaningful inclination (saw cutting angle) and is close to that of the
            # previous plane, good to continue
            if currentAngleToSAxis > minSawCutAngle and np.isclose(
                currentAngleToSAxis,
                previousAngleToSAxis,
                atol=angleSimilarityRange,
            ):
                # Finding the angle
                dot = np.dot(
                    previousProjectedVector,
                    currentProjectedVector,
                )
                det = np.linalg.det([previousProjectedVector, currentProjectedVector])
                angle = -np.arctan2(det, dot)
        return angle

    def findRASSurfacePoints(self, volume, fromTop=False):
        radius = self.getCoreDiameter(volume) / 2
        # Converting to Slicer's configured units if they change in the future
        radiusShave = (5 * ureg.millimeter).m_as(SLICER_LENGTH_UNIT)
        # Minus shave to guarantee we are inside the core for all query points
        radius = np.around(radius.m_as(SLICER_LENGTH_UNIT) - radiusShave, 3)
        # Minimum intensity value to be considered a surface voxel (not too low in density to avoid loose material)
        minVoxelIntensityValue = 500
        samplePointsPerSliceAxis = 20
        intraSliceStep = 2 * radius / samplePointsPerSliceAxis
        # The search step for the surface in the S axis
        interSliceSpacing = self.getInterSliceSpacing(volume)
        bounds = np.zeros(6)
        volume.GetBounds(bounds)
        volumeRASToIJKMatrix = vtk.vtkMatrix4x4()
        volume.GetRASToIJKMatrix(volumeRASToIJKMatrix)
        volumeArray = slicer.util.arrayFromVolume(volume)

        # Positions at each voxel's center in RAS coordinates
        sRange = np.arange(bounds[4] + interSliceSpacing.m / 2, bounds[5], interSliceSpacing.m)
        if fromTop:
            sRange = sRange[::-1]
        surfacePoints = []
        raRange = np.arange(-radius, radius + intraSliceStep, intraSliceStep)
        for r, a in [(r, a) for r in raRange for a in raRange]:
            if np.sqrt(r**2 + a**2) <= radius:
                for s in sRange:
                    pointIJK = transformPoints(volumeRASToIJKMatrix, [[r, a, s]], True)[0]
                    if volumeArray[tuple(pointIJK)[::-1]] >= minVoxelIntensityValue:
                        surfacePoints.append([r, a, s])
                        break
        return np.array(surfacePoints)

    def findPerpendicularVectorToFittedPlaneByZDistance(self, points):
        """
        Fits a plane by minimizing the z distance from the points to the plane and finds the unit vector perpendicular
        to the plane.
        :return: the perpendicular unit vector to the plane and the fitting error
        """
        x, y, z = points[:, 0], points[:, 1], points[:, 2]
        # Fit plane for equation z = a*x + b*y + c
        A = np.c_[x, y, np.ones(x.shape)]
        coefficients, residuals, _, _ = np.linalg.lstsq(A, z, rcond=None)
        # Coefficients are in the form: a*x + b*y + c*z + d = 0
        a, b, c, d = coefficients[0], coefficients[1], -1, coefficients[2]
        perpendicularUnitVector = self.normalizeVector([a, b, c])  # Unit vector perpendicular to the plane
        rmsd = np.sqrt(residuals / len(points))  # Root Mean Squared Deviation
        nrmsd = rmsd / (np.max(z) - np.min(z))  # Normalized RMSD, to allow comparison with a global error threshold
        return perpendicularUnitVector, nrmsd

    def normalizeVector(self, vector):
        return vector / np.linalg.norm(vector)

    def coreVolumeOrientationAngleBySinusoid(self, coreVolume, previousCoreVolume):
        """
        Orientation by unwrap sinusoid phase.
        """
        previousCoreUnwrapMedianPhase = self.calculateUnwrapMedianPhase(self.createUnwrapArray(previousCoreVolume))
        coreUnwrapMedianPhase = self.calculateUnwrapMedianPhase(self.createUnwrapArray(coreVolume))
        return self.normalizeAngle(previousCoreUnwrapMedianPhase - coreUnwrapMedianPhase)

    def calculateUnwrapMedianPhase(self, unwrapArray):
        _, phases = self.findUnwrapSinusoids(unwrapArray, 50)
        return np.median(phases)

    def normalizeAngle(self, angle):
        angle = angle % (2 * np.pi)
        return angle if angle <= np.pi else angle - 2 * np.pi

    def getVolumeTransformOrientationAngle(self, volume):
        directions = np.eye(3)
        volume.GetIJKToRASDirections(directions)
        return np.arctan2(directions[1, 0], directions[0, 0]) * ureg.radian

    def unwrapCores(self, p):
        coreVolumes = self.getCoreVolumes()

        if len(coreVolumes) == 0:
            raise ProcessInfo("There are no cores available to unwrap.")

        coreVolumesToBeUnwrapped = []
        for coreVolume in coreVolumes:
            unwrapVolume = self.getUnwrapVolume(coreVolume)
            assert len(unwrapVolume) == 0 or len(unwrapVolume) == 1
            if len(unwrapVolume) == 0:
                coreVolumesToBeUnwrapped.append(coreVolume)

        wellUnwrapVolume = self.getNodesByNodeType(self.NODE_TYPE_WELL_UNWRAP_VOLUME)

        if len(coreVolumesToBeUnwrapped) == 0 and (
            len(wellUnwrapVolume) == 1 and wellUnwrapVolume[0].GetAttribute(self.UNWRAP_UPDATED) == str(True)
        ):
            raise ProcessInfo("All unwraps are up to date.")

        for i in range(len(coreVolumesToBeUnwrapped)):
            p.callback.on_update(
                "Unwrapping " + coreVolumesToBeUnwrapped[i].GetName() + "...",
                getRoundedInteger(i * 100 / len(coreVolumesToBeUnwrapped)),
            )
            self.generateCoreUnwrapVolume(coreVolumesToBeUnwrapped[i], p.unwrapRadialDepth)
        if len(wellUnwrapVolume) == 1:
            slicer.mrmlScene.RemoveNode(wellUnwrapVolume[0])
        self.generateWellUnwrapVolume(p.callback, p.wellDiameter, p.unwrapRadialDepth)

        # Needed because of the well unwrap
        self.sortDirectoriesByCoreDepth()

        # Apply window/level to all unwrap volumes
        windowLevelMinMax = self.calculateGlobalWindowLevelMinMax()
        unwrapVolumes = self.getUnwrapVolumes()
        numberOfUnwrapVolumes = len(unwrapVolumes)
        for i in range(numberOfUnwrapVolumes):
            p.callback.on_update(
                "Applying global window/level to all unwrap volumes",
                getRoundedInteger(i * 100 / numberOfUnwrapVolumes),
            )
            self.setWindowLevelMinMax(unwrapVolumes[i], windowLevelMinMax)

        # Show Core and well unwrap on green slice view after finishing all unwraps
        self.renderCoreVolume(self.getWellUnwrapVolume()[0])

    def generateCoreUnwrapVolume(self, coreVolume, unwrapRadialDepth):
        baseName = coreVolume.GetAttribute(self.BASE_NAME)
        unwrapVolume = self.createUnwrapVolume(
            self.createUnwrapArray(coreVolume, unwrapRadialDepth=unwrapRadialDepth), self.getSpacing(coreVolume)
        )

        bounds = np.zeros(6)
        coreVolume.GetBounds(bounds)
        self.configureVolumeDepth(unwrapVolume, -bounds[5] * SLICER_LENGTH_UNIT)

        self.configureInitialNodeMetadata(
            unwrapVolume,
            baseName,
            self.NODE_TYPE_CORE_UNWRAP_VOLUME,
            depth=self.getDepth(coreVolume),
            unwrapRadialDepth=unwrapRadialDepth,
        )
        unwrapVolume.SetAttribute(self.UNWRAP_UPDATED, str(True))

    def updateCoreUnwrapVolume(self, coreVolume):
        unwrapVolume = self.getUnwrapVolume(coreVolume)
        assert len(unwrapVolume) == 0 or len(unwrapVolume) == 1
        if len(unwrapVolume) == 1:
            unwrapVolumeArray = self.createUnwrapArray(
                coreVolume, unwrapRadialDepth=self.getUnwrapRadialDepth(unwrapVolume[0])
            )
            slicer.util.updateVolumeFromArray(unwrapVolume[0], unwrapVolumeArray)

    def createUnwrapVolume(self, unwrapArray, spacing):
        unwrapVolume = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLScalarVolumeNode.__name__)
        unwrapVolume.SetSpacing(*self.getSpacingMagnitudes(spacing))
        slicer.util.updateVolumeFromArray(unwrapVolume, unwrapArray)
        self.centerUnwrapVolumeRLAxis(unwrapVolume)
        unwrapVolume.CreateDefaultDisplayNodes()
        return unwrapVolume

    def centerUnwrapVolumeRLAxis(self, volume):
        bounds = np.zeros(6)
        volume.GetBounds(bounds)
        translationMatrix = np.array([[1, 0, 0, (bounds[0] - bounds[1]) / 2], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        self.applyHardenedTransformationMatrix(volume, translationMatrix)

    def createUnwrapArray(self, volume, radius=None, unwrapRadialDepth=None, intraSliceSpacing=None):
        if radius is None:
            radius = self.getCoreRadius(volume)
        if unwrapRadialDepth is None:
            unwrapRadialDepth = 4 * SLICER_LENGTH_UNIT
        if intraSliceSpacing is None:
            intraSliceSpacing = self.getIntraSliceSpacing(volume)
        volumeArray = slicer.util.arrayFromVolume(volume)
        bounds = np.zeros(6)
        volume.GetBounds(bounds)
        volumeRASToIJKMatrix = vtk.vtkMatrix4x4()
        volume.GetRASToIJKMatrix(volumeRASToIJKMatrix)
        interSliceSpacing = self.getInterSliceSpacing(volume)
        circlePoints = self.circlePoints((radius - unwrapRadialDepth).m, intraSliceSpacing.m)
        cylinderPoints = []
        # s is the position at each voxel's center in RAS coordinates (hence the interSliceSpacing divided by 2)
        for s in np.arange(bounds[5] - interSliceSpacing.m / 2, bounds[4], -interSliceSpacing.m):
            cylinderPoints.insert(0, np.c_[circlePoints, np.full(len(circlePoints), s)])
        pointsIJK = transformPoints(volumeRASToIJKMatrix, np.reshape(cylinderPoints, (-1, 3)), True)
        unwrapArray = volumeArray[tuple(pointsIJK.T)[::-1]].reshape(len(cylinderPoints), 1, -1)
        return unwrapArray

    def circlePoints(self, r, circumferenceStepSize):
        # reversed to adjust Jorge Campos's request
        return [
            (np.cos(angle) * r, np.sin(angle) * r)
            for angle in reversed(np.arange(0, 2 * np.pi, circumferenceStepSize / r))
        ]

    def isDepthAlreadyOccupied(self, depth):
        depthIntervals = self.getCoreDepthIntervals()
        for depthInterval in depthIntervals:
            if depthInterval[0] <= depth < depthInterval[1]:
                return True
        return False

    def getCoreDepthIntervals(self):
        depthIntervals = []
        for coreVolume in self.getCoreVolumesSortedByDepth():
            coreDepth = self.getDepth(coreVolume)
            coreLength = self.getLength(coreVolume)
            # If the depth of the last interval is equal to the current core depth, join the intervals
            if (
                next(
                    reversed(next(reversed(depthIntervals), [])),
                    None,
                )
                == coreDepth
            ):
                depthIntervals[-1][1] = np.around(depthIntervals[-1][1] + coreLength, decimals=3)
            else:
                depthIntervals.append([coreDepth, np.around(coreDepth + coreLength, decimals=3)])
        return depthIntervals

    def getGlobalCoreVolumeScalarRange(self):
        coreVolumes = self.getCoreVolumes()
        minScalarRange, maxScalarRange = 0, 0
        for coreVolume in coreVolumes:
            scalarRange = coreVolume.GetImageData().GetScalarRange()
            if scalarRange[0] < minScalarRange:
                minScalarRange = scalarRange[0]
            if scalarRange[1] > maxScalarRange:
                maxScalarRange = scalarRange[1]
        return [minScalarRange, maxScalarRange]

    def unwrapArrayToImage(self, unwrapArray):
        return unwrapArray[::-1, 0, ::-1]

    def findUnwrapSinusoids(self, unwrapArray, numStartingPositions):
        # Creating volume to send the unwrapImage to CLI
        volume = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLScalarVolumeNode.__name__)
        slicer.util.updateVolumeFromArray(volume, unwrapArray)
        sinusoidsStartingPositions = ",".join(
            str(n) for n in getRoundedInteger(np.linspace(0, len(unwrapArray), num=numStartingPositions))
        )
        temporaryDir = Path(slicer.util.tempDirectory(key=slicer.modules.MulticoreInstance.SETTING_KEY))
        unwrapSinusoidsDataFile = temporaryDir / "UnwrapSinusoidsData"
        parameters = {
            "volume": volume.GetID(),
            "sinusoidsStartingPositions": sinusoidsStartingPositions,
            "unwrapSinusoidsDataFile": str(unwrapSinusoidsDataFile),
        }
        slicer.cli.runSync(slicer.modules.unwrapsinusoidscli, None, parameters)
        with open(unwrapSinusoidsDataFile, "rb") as f:
            unwrapSinusoidsData = pickle.loads(f.read())
        shutil.rmtree(temporaryDir)
        slicer.mrmlScene.RemoveNode(volume)
        return unwrapSinusoidsData

    def getIntraSliceSpacing(self, volumeOrSpacing):
        if type(volumeOrSpacing) is tuple:
            return volumeOrSpacing[0]
        return self.getSpacing(volumeOrSpacing)[0]

    def getInterSliceSpacing(self, volumeOrSpacing):
        if type(volumeOrSpacing) is tuple:
            return volumeOrSpacing[2]
        return self.getSpacing(volumeOrSpacing)[2]

    def getSpacingMagnitudes(self, spacing):
        return tuple(i.m for i in spacing)

    def getGlobalCoreVolumeIntraSliceSpacing(self):
        spacing = self.getGlobalCoreVolumeSpacing()
        return self.getIntraSliceSpacing(spacing) if spacing is not None else None

    def getGlobalCoreVolumeInterSliceSpacing(self):
        spacing = self.getGlobalCoreVolumeSpacing()
        return self.getInterSliceSpacing(spacing) if spacing is not None else None

    def getGlobalCoreVolumeSpacing(self):
        """
        If spacings are different in the 3rd decimal place, generate warning.

        :return: the most common spacing (rounded to the 3rd decimal place) of the loaded data
        """
        spacingsMagnitudes = []
        for coreVolume in self.getCoreVolumes():
            spacingsMagnitudes.append(self.getSpacingMagnitudes(self.getSpacing(coreVolume)))
        spacingsMagnitudes = np.around(spacingsMagnitudes, decimals=3)  # Discard the tiny differences in spacings
        if len(np.unique(spacingsMagnitudes, axis=0)) > 1:
            logging.warning(
                "There are core volumes with different spacings. "
                "The global spacing returned will be the first most common one."
            )
        return tuple(i * SLICER_LENGTH_UNIT for i in self.getMostCommonItemInList(spacingsMagnitudes))

    def getGlobalCoreDiameter(self):
        """
        :return: the minimum core diameter between all processed cores
        """
        coreVolumes = self.getCoreVolumes()
        smallestCoreDiameter = self.getCoreDiameter(coreVolumes[0])
        for coreVolume in coreVolumes[1:]:
            coreDiameter = self.getCoreDiameter(coreVolume)
            if coreDiameter < smallestCoreDiameter:
                smallestCoreDiameter = coreDiameter
        return smallestCoreDiameter

    def getMostCommonItemInList(self, listOfItems):
        if len(listOfItems) == 0:
            return None
        listUnique, indexes = np.unique(listOfItems, axis=0, return_inverse=True)
        return listUnique[np.argmax(np.bincount(indexes))]

    def getNodesByBaseName(self, baseName):
        return self.getNodesByAttributes({self.BASE_NAME: baseName})

    def getNodesByNodeType(self, nodeType):
        return self.getNodesByAttributes({self.NODE_TYPE: nodeType})

    def getNodesByBaseNameAndNodeType(self, baseName, nodeType):
        return self.getNodesByAttributes({self.BASE_NAME: baseName, self.NODE_TYPE: nodeType})

    def getNodesByAttributes(self, attributes):
        nodes = slicer.util.getNodesByClass(slicer.vtkMRMLNode.__name__)
        selectedNodes = []
        for node in nodes:
            includeNode = True
            for (
                attributeName,
                attributeValue,
            ) in attributes.items():
                if node.GetAttribute(attributeName) != attributeValue:
                    includeNode = False
                    break
            if includeNode:
                selectedNodes.append(node)
        return selectedNodes

    def getOriginalVolumes(self):
        return self.getNodesByNodeType(self.NODE_TYPE_ORIGINAL_VOLUME)

    def getCoreVolumes(self):
        return self.getNodesByNodeType(self.NODE_TYPE_CORE_VOLUME)

    def getCoreUnwrapVolumes(self):
        return self.getNodesByNodeType(self.NODE_TYPE_CORE_UNWRAP_VOLUME)

    def getWellUnwrapVolume(self):
        return self.getNodesByNodeType(self.NODE_TYPE_WELL_UNWRAP_VOLUME)

    def getUnwrapVolumes(self):
        return np.concatenate((self.getCoreUnwrapVolumes(), self.getWellUnwrapVolume()))

    def getCoreVolume(self, node):
        return self.getNodesByBaseNameAndNodeType(node.GetAttribute(self.BASE_NAME), self.NODE_TYPE_CORE_VOLUME)

    def getUnwrapVolume(self, node):
        return self.getNodesByBaseNameAndNodeType(node.GetAttribute(self.BASE_NAME), self.NODE_TYPE_CORE_UNWRAP_VOLUME)

    def getVolumes(self):
        return np.concatenate(
            (self.getOriginalVolumes(), self.getCoreVolumes(), self.getCoreUnwrapVolumes(), self.getWellUnwrapVolume())
        )

    def physicalToImageCoordinates(self, value, spacing):
        return value / spacing

    def imageToPhysicalCoordinates(self, value, spacing):
        return value * spacing

    def getCoreDiameter(self, core):
        return ureg.parse_expression(core.GetAttribute(self.CORE_DIAMETER)).to(ureg.millimeter)

    def getUnwrapRadialDepth(self, unwrap):
        return ureg.parse_expression(unwrap.GetAttribute(self.UNWRAP_RADIAL_DEPTH))

    def getCoreRadius(self, core):
        return self.getCoreDiameter(core) / 2

    def getDepth(self, node):
        return ureg.parse_expression(node.GetAttribute(self.DEPTH))

    def getCoreBoundary(self, node):
        roi = slicer.util.getNode(node.GetName() + " ROI")
        bounds = np.zeros(6)
        roi.GetBounds(bounds)
        return (np.array([bounds[5], bounds[4]]) * SLICER_LENGTH_UNIT).to(ureg.meter)

    def setDepth(self, node, value):
        node.SetAttribute(self.DEPTH, str(self.around(value, decimals=3)))

    def setCoreLength(self, node, value):
        node.SetAttribute(self.LENGTH, str(self.around(value, decimals=1)))

    def getLength(self, node):
        return ureg.parse_expression(node.GetAttribute(self.LENGTH))

    def getSpacing(self, node):
        return tuple(i * SLICER_LENGTH_UNIT / ureg.pixel for i in node.GetSpacing())

    def around(self, value, decimals):
        value = np.around(value, decimals=decimals)
        # Workaround to avoid -0.0 (Pint has a bug when comparing to zero, we don't need to get the absolute value .m)
        if value == 0:
            if type(value) == ureg.Quantity:
                value = 0 * value.units
            else:
                value = 0
        return value

    def generateWellUnwrapVolume(self, callback, wellDiameter, unwrapRadialDepth):
        callback.on_update("Generating well unwrap...", 0)
        coreVolumes = self.getCoreVolumesSortedByDepth()
        firstCoreVolume = coreVolumes[0]
        lastCoreVolume = coreVolumes[-1]

        roi = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLMarkupsROINode.__name__)
        firstCoreVolumeBounds = np.zeros(6)
        firstCoreVolume.GetBounds(firstCoreVolumeBounds)
        lastCoreVolumeBounds = np.zeros(6)
        lastCoreVolume.GetBounds(lastCoreVolumeBounds)
        radiusXYZ = [
            (firstCoreVolumeBounds[1] - firstCoreVolumeBounds[0]) / 2,
            (firstCoreVolumeBounds[3] - firstCoreVolumeBounds[2]) / 2,
            (firstCoreVolumeBounds[5] - lastCoreVolumeBounds[4]) / 2,
        ]
        xyz = [0, 0, firstCoreVolumeBounds[5] - (firstCoreVolumeBounds[5] - lastCoreVolumeBounds[4]) / 2]
        roi.SetRadiusXYZ(radiusXYZ)
        roi.SetXYZ(xyz)

        cropVolumeParametersNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLCropVolumeParametersNode.__name__)
        croppedVolume = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLScalarVolumeNode.__name__)
        cropVolumeParametersNode.SetOutputVolumeNodeID(croppedVolume.GetID())
        cropVolumeParametersNode.SetInputVolumeNodeID(firstCoreVolume.GetID())
        cropVolumeParametersNode.SetROINodeID(roi.GetID())
        cropVolumeParametersNode.SetFillValue(self.EMPTY_VOXEL_INTENSITY)
        cropVolumeLogic = slicer.modules.cropvolume.logic()
        cropVolumeLogic.Apply(cropVolumeParametersNode)

        smallestCoreDiameter = self.getCoreDiameter(firstCoreVolume)

        numCoreVolumes = len(coreVolumes)
        for i in range(1, numCoreVolumes):
            callback.on_update(
                "Generating well unwrap...",
                getRoundedInteger((i - 1) * 100 / (numCoreVolumes - 1)),
            )

            coreVolumeArray = slicer.util.arrayFromVolume(coreVolumes[i])
            coreVolumeArray -= self.EMPTY_VOXEL_INTENSITY

            parameters = {
                "inputVolume1": croppedVolume.GetID(),
                "inputVolume2": coreVolumes[i].GetID(),
                "outputVolume": croppedVolume.GetID(),
                "interpolation order": 0,
            }
            slicer.cli.runSync(slicer.modules.addscalarvolumes, None, parameters)

            coreVolumeArray += self.EMPTY_VOXEL_INTENSITY

            coreDiameter = self.getCoreDiameter(coreVolumes[i])
            if coreDiameter < smallestCoreDiameter:
                smallestCoreDiameter = coreDiameter

        croppedVolume.SetAttribute(self.CORE_DIAMETER, str(smallestCoreDiameter))

        unwrapVolume = self.createUnwrapVolume(
            self.createUnwrapArray(croppedVolume, unwrapRadialDepth=unwrapRadialDepth),
            self.getSpacing(croppedVolume),
        )

        bounds = np.zeros(6)
        firstCoreVolume.GetBounds(bounds)
        self.configureVolumeDepth(unwrapVolume, -bounds[5] * SLICER_LENGTH_UNIT)
        self.configureInitialNodeMetadata(
            unwrapVolume,
            self.GLOBAL_DIRECTORY_NAME,
            self.NODE_TYPE_WELL_UNWRAP_VOLUME,
            depth=self.getDepth(firstCoreVolume),
            wellDiameter=wellDiameter,
        )
        unwrapVolume.SetAttribute(self.UNWRAP_UPDATED, str(True))

        # Cleaning up
        slicer.mrmlScene.RemoveNode(roi)
        slicer.mrmlScene.RemoveNode(croppedVolume)


class ProcessInfo(RuntimeError):
    pass


class ProcessError(RuntimeError):
    pass
