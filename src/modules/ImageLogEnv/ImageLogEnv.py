import os
from pathlib import Path

import qt
import slicer
from Customizer import Customizer
from ltrace.slicer_utils import *

import DLISImportLib
from CustomizedSegmentEditor import CustomizedSegmentEditor
from ImageLogInstanceSegmenter import ImageLogInstanceSegmenter
from ImageLogsLib.PermeabilityModeling import PermeabilityModelingWidget
from InstanceSegmenterEditor import InstanceSegmenterEditor
from SegmentInspector import SegmentInspector
from UnwrapRegistration import UnwrapRegistration
from AzimuthShiftTool import AzimuthShiftTool

# Checks if closed source code is available
try:
    from ImageLogsLib.Eccentricity import EccentricityWidget
except:
    EccentricityWidget = None
try:
    from Test.EccentricityTest import EccentricityTest
except ImportError:
    EccentricityTest = None

from QualityIndicator import QualityIndicator
from SpiralFilter import SpiralFilter
from ImageLogExport import ImageLogExport
from ImageLogCropVolume import ImageLogCropVolume


class ImageLogEnv(LTracePlugin):
    SETTING_KEY = "ImageLogEnv"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Image Log Environment"
        self.parent.categories = ["Environments"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]

        eccentricityHelp = EccentricityWidget.help() if EccentricityWidget else ""

        self.parent.helpText = (
            ImageLogEnv.help()
            + ImageLogExport.help()
            + ImageLogCropVolume.help()
            + eccentricityHelp
            + SpiralFilter.help()
            + QualityIndicator.help()
            + CustomizedSegmentEditor.help()
            + ImageLogInstanceSegmenter.help()
            + InstanceSegmenterEditor.help()
            + SegmentInspector.help()
            + UnwrapRegistration.help()
            + PermeabilityModelingWidget.help()
            + AzimuthShiftTool.help()
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ImageLogEnvWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = ImageLogEnvLogic()

        self.mainTab = qt.QTabWidget()

        dataTab = qt.QTabWidget()
        processingTab = qt.QTabWidget()
        self.segmentationTab = qt.QTabWidget()
        registrationTab = qt.QTabWidget()
        self.imageLogDataWidget = slicer.modules.imagelogdata.widgetRepresentation()
        self.imageLogCropVolume = slicer.modules.imagelogcropvolume.widgetRepresentation()
        self.segment_inspector_env = slicer.modules.segmentinspector.createNewWidgetRepresentation()
        self.imageLogSegmenterWidget = slicer.modules.imagelogsegmenter.widgetRepresentation()
        self.instanceSegmenterWidget = slicer.modules.imageloginstancesegmenter.widgetRepresentation()
        self.instanceSegmenterEditorWidget = slicer.modules.instancesegmentereditor.widgetRepresentation()
        self.imageLogUnwrapImportWidget = slicer.modules.imagelogunwrapimport.widgetRepresentation()
        self.imageLogExportWidget = slicer.modules.imagelogexport.widgetRepresentation()
        self.spiralFiterWidget = slicer.modules.spiralfilter.widgetRepresentation()
        self.qualityIndicatorWidget = slicer.modules.qualityindicator.widgetRepresentation()
        self.heterogeneityIndexWidget = slicer.modules.heterogeneityindex.widgetRepresentation()
        self.unwrapRegistrationWidget = slicer.modules.unwrapregistration.widgetRepresentation()
        self.AzimuthShiftToolWidget = slicer.modules.azimuthshifttool.widgetRepresentation()

        self.segment_inspector_env.self().blockVisibilityChanges = True

        imageDataLogic = self.imageLogDataWidget.self().logic
        imageDataLogic.layoutViewOpened.connect(self.onImageLogViewOpened)
        imageDataLogic.layoutViewClosed.connect(self.onImageLogViewClosed)

        self.imageLogSegmenterWidget.self().logic.setImageLogDataLogic(imageDataLogic)
        self.instanceSegmenterEditorWidget.self().logic.setImageLogDataLogic(imageDataLogic)
        self.imageLogDataWidget.self().logic.setImageLogSegmenterWidget(self.imageLogSegmenterWidget)

        logImportWidget = DLISImportLib.WellLogImportWidget()
        logImportWidget.setAppFolder("Well Logs")

        self.eccentricityWidget = EccentricityWidget() if EccentricityWidget else None

        permeabilityModelingWidget = PermeabilityModelingWidget()

        cornerButtonsFrame = qt.QFrame()
        cornerButtonsLayout = qt.QHBoxLayout(cornerButtonsFrame)
        cornerButtonsLayout.setContentsMargins(0, 0, 0, 0)

        # Show all button
        self.fitButton = qt.QPushButton()
        self.fitButton.setIcon(qt.QIcon(str(Customizer.FIT_ICON_PATH)))
        self.fitButton.setFixedWidth(25)
        self.fitButton.setToolTip("Reset the views to fit all data.")
        cornerButtonsLayout.addWidget(self.fitButton)
        self.fitButton.clicked.connect(self.fit)

        # Adjust to real aspect ratio button
        self.fitRealAspectRatio = qt.QPushButton()
        self.fitRealAspectRatio.setIcon(qt.QIcon(str(Customizer.FIT_REAL_ASPECT_RATIO_ICON_PATH)))
        self.fitRealAspectRatio.clicked.connect(self.imageLogDataWidget.self().logic.fitToAspectRatio)
        self.fitRealAspectRatio.setFixedWidth(25)
        self.fitRealAspectRatio.setToolTip("Adjust the views to their real aspect ratio.")
        cornerButtonsLayout.addWidget(self.fitRealAspectRatio)

        # Add view button
        self.addViewButton = qt.QPushButton("Add view")
        self.addViewButton.setIcon(qt.QIcon(str(Customizer.ADD_ICON_PATH)))
        cornerButtonsLayout.addWidget(self.addViewButton)
        self.addViewButton.clicked.connect(self.addView)
        self.mainTab.setCornerWidget(cornerButtonsFrame)

        # Data tab
        dataTab.addTab(self.imageLogDataWidget, "Explorer")
        dataTab.addTab(logImportWidget, "Import")
        dataTab.addTab(self.imageLogUnwrapImportWidget, "Unwrap import")
        dataTab.addTab(self.imageLogExportWidget, "Export")

        # Processing tab
        if self.eccentricityWidget:
            processingTab.addTab(self.eccentricityWidget, "Eccentricity")
        processingTab.addTab(self.spiralFiterWidget, "Spiral Filter")
        processingTab.addTab(self.qualityIndicatorWidget, "Quality Indicator")
        processingTab.addTab(self.heterogeneityIndexWidget, "Heterogeneity Index")
        processingTab.addTab(self.AzimuthShiftToolWidget, "Azimuth Shift Tool")

        # Segmentation tab
        smartSegWidget = slicer.modules.imagelogsmartsegmenter.createNewWidgetRepresentation()
        self.segmentationTab.addTab(self.imageLogSegmenterWidget, "Manual")
        self.segmentationTab.addTab(smartSegWidget, "Smart")
        self.segmentationTab.addTab(self.instanceSegmenterWidget, "Instance")
        self.segmentationTab.addTab(self.instanceSegmenterEditorWidget, "Instance Editor")
        self.segmentationTab.addTab(self.segment_inspector_env, "Inspector")

        # Registration tab
        registrationTab.addTab(self.unwrapRegistrationWidget, "Unwrap Registration")

        self.mainTab.addTab(dataTab, "Data")
        self.mainTab.addTab(self.imageLogCropVolume, "Crop")
        self.mainTab.addTab(processingTab, "Processing")
        self.mainTab.addTab(self.segmentationTab, "Segmentation")
        self.mainTab.addTab(registrationTab, "Registration")

        self.mainTab.addTab(permeabilityModelingWidget, "Modeling")

        self.lastAccessedWidget = dataTab.widget(0)

        self.mainTab.tabBarClicked.connect(self.onMainTabClicked)
        self.segmentationTab.tabBarClicked.connect(self.onSegmentationTabClicked)
        self.layout.addWidget(self.mainTab)

    def onMainTabClicked(self, index):
        if self.lastAccessedWidget != self.mainTab.widget(
            index
        ):  # To avoid calling exit by clicking over the active tab
            self.lastAccessedWidgetExit()
            self.lastAccessedWidget = self.mainTab.widget(index)
            if type(self.lastAccessedWidget) is qt.QTabWidget:
                self.lastAccessedWidget = self.lastAccessedWidget.currentWidget()
            self.lastAccessedWidgetEnter()

    def onSegmentationTabClicked(self, index):
        if self.lastAccessedWidget != self.segmentationTab.widget(
            index
        ):  # To avoid calling exit by clicking over the active tab
            self.lastAccessedWidgetExit()
            self.lastAccessedWidget = self.segmentationTab.widget(index)
            self.lastAccessedWidgetEnter()

    def onImageLogViewOpened(self):
        self.segment_inspector_env.self().logic.inspector_process_finished.connect(self._on_external_process_finished)
        if self.eccentricityWidget:
            self.eccentricityWidget.logic.process_finished.connect(self._on_external_process_finished)

    def onImageLogViewClosed(self):
        self.segment_inspector_env.self().logic.inspector_process_finished.disconnect(
            self._on_external_process_finished
        )
        if self.eccentricityWidget:
            self.eccentricityWidget.logic.process_finished.disconnect(self._on_external_process_finished)

    def enter(self) -> None:
        super().enter()
        self.logic.setupSliceViewAnnotations()
        self.lastAccessedWidgetEnter()
        self.imageLogDataWidget.self().logic.changeToLayout()
        self.imageLogDataWidget.self().logic.loadConfiguration()
        self.imageLogDataWidget.self().logic.refreshViews()

    def exit(self):
        self.lastAccessedWidgetExit()
        self.logic.restoreSliceViewAnnotationsPreviousValues()

    def lastAccessedWidgetEnter(self):
        try:
            self.lastAccessedWidget.enter()
        except:
            pass  # In case the widget does not have an enter function

    def lastAccessedWidgetExit(self):
        try:
            self.lastAccessedWidget.exit()
        except:
            pass  # In case the widget does not have an exit function

    def _on_external_process_finished(self):
        self.imageLogDataWidget.self().logic.refreshViews()

    def addView(self):
        self.addViewButton.setEnabled(False)
        self.imageLogDataWidget.self().addView()
        qt.QTimer.singleShot(self.imageLogDataWidget.self().logic.REFRESH_DELAY + 100, self.enableAddView)

    def enableAddView(self):
        self.addViewButton.setEnabled(True)

    def fit(self):
        self.imageLogDataWidget.self().logic.fit()


class ImageLogEnvLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.previousSliceAnnotationsProperties = {}

    def setupSliceViewAnnotations(self):
        sliceAnnotations = slicer.modules.DataProbeInstance.infoWidget.sliceAnnotations
        self.previousSliceAnnotationsProperties[
            "sliceViewAnnotationsEnabled"
        ] = sliceAnnotations.sliceViewAnnotationsEnabled
        sliceAnnotations.sliceViewAnnotationsEnabled = False
        sliceAnnotations.updateSliceViewFromGUI()

    def restoreSliceViewAnnotationsPreviousValues(self):
        sliceAnnotations = slicer.modules.DataProbeInstance.infoWidget.sliceAnnotations
        sliceAnnotations.sliceViewAnnotationsEnabled = self.previousSliceAnnotationsProperties.get(
            "sliceViewAnnotationsEnabled"
        )
        sliceAnnotations.updateSliceViewFromGUI()