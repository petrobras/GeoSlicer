import os
from pathlib import Path

import qt
import slicer

from ltrace.slicer.helpers import svgToQIcon
from ltrace.slicer.widget.custom_toolbar_buttons import addAction, addMenu
from ltrace.slicer_utils import LTracePlugin, LTracePluginLogic, getResourcePath, LTraceEnvironmentMixin
from ltrace.constants import ImageLogConst


class ImageLogEnv(LTracePlugin):
    SETTING_KEY = "ImageLogEnv"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Image Log Environment"
        self.parent.categories = ["Environment", "ImageLog"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ""

        self.environment = ImageLogEnvLogic()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ImageLogEnvLogic(LTracePluginLogic, LTraceEnvironmentMixin):
    def __init__(self):
        super().__init__()
        self.__modulesToolbar = None
        self.previousSliceAnnotationsProperties = {}

    def setupEnvironment(self):
        relatedModules = self.getModuleManager().fetchByCategory([self.category])

        addAction(relatedModules["ImageLogData"], self.modulesToolbar)

        # Imports and Export
        addAction(relatedModules["ImageLogImport"], self.modulesToolbar)
        addAction(relatedModules["ImageLogUnwrapImport"], self.modulesToolbar)
        addAction(relatedModules["ImageLogExport"], self.modulesToolbar)

        # crop
        addAction(relatedModules["ImageLogCropVolume"], self.modulesToolbar)

        # Processing
        processingModules = [
            relatedModules["SpiralFilter"],
            relatedModules["QualityIndicator"],
            relatedModules["HeterogeneityIndex"],
            relatedModules["AzimuthShiftTool"],
            relatedModules["CLAHETool"],
        ]

        if hasattr(slicer.modules, "eccentricity"):
            processingModules.insert(0, relatedModules["Eccentricity"])

        addMenu(
            svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "Spiral.svg"),
            "Processing",
            processingModules,
            self.modulesToolbar,
        )

        # Registration tab
        addAction(relatedModules["UnwrapRegistration"], self.modulesToolbar)

        # Modeling
        addAction(relatedModules["PermeabilityModeling"], self.modulesToolbar)

        # Inpaint tab
        inpaintModules = [
            relatedModules[
                "ImageLogInpaint"
            ],  # ImageLogInpaint is broken until segmentation is working correctly for ImageLog
            relatedModules["CoreInpaint"],
        ]
        addMenu(
            svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "PaintBrush.svg"),
            "Inpainting",
            inpaintModules,
            self.modulesToolbar,
        )

        self.setupSegmentation()
        self.setupTools(tools=["VolumeCalculator", "CustomizedTables", "TableFilter", "Charts"])
        # self.setupLoaders()
        self.setupSliceViewAnnotations()

        self.getModuleManager().setEnvironment(("ImageLog", "ImageLogEnv"))
        self.refreshViews()
        slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndImportEvent, self.__onEndLoadScene)

    def setupSegmentation(self):
        modules = self.getModuleManager().fetchByCategory(("ImageLog",), intersectWith="Segmentation")

        addMenu(
            svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "Layers.svg"),
            "Segmentation",
            [
                modules["ImageLogSegmentEditor"],
                modules["ImageLogInstanceSegmenter"],
                modules["InstanceSegmenterEditor"],
            ],
            self.modulesToolbar,
        )

    def onImageLogViewOpened(self):
        slicer.util.getModuleLogic("SegmentInspector").inspector_process_finished.connect(
            self._on_external_process_finished
        )
        try:
            slicer.util.getModuleLogic("Eccentricity").process_finished.connect(self._on_external_process_finished)
        except:
            pass

    def onImageLogViewClosed(self):
        slicer.util.getModuleLogic("SegmentInspector").inspector_process_finished.disconnect(self.refreshViews)
        try:
            slicer.util.getModuleLogic("Eccentricity").process_finished.disconnect(self.refreshViews)
        except:
            pass

    def refreshViews(self):
        slicer.util.getModuleLogic("ImageLogData").refreshViews("ImageLogEnv.setupEnvironment")

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

    def __onEndLoadScene(self, *args, **kwargs):
        """Handle slicer' end load scene event."""

        # Without this the Image Log segmenter doesn't correctly restore the selected segmentation node
        try:
            slicer.util.getModuleWidget("ImageLogSegmentEditor").initializeSavedNodes()

            # Image Log number of views restoration
            if slicer.app.layoutManager().layout >= ImageLogConst.DEFAULT_LAYOUT_ID_START_VALUE:
                imageLogDataLogic = slicer.util.getModuleLogic("ImageLogData")
                imageLogDataLogic.configurationsNode = None
                imageLogDataLogic.loadConfiguration()

        except ValueError:
            # Widget has been deleted after test
            pass
