import os
from pathlib import Path

import slicer

from ltrace.slicer.helpers import svgToQIcon
from ltrace.slicer.widget.custom_toolbar_buttons import addAction, addMenu
from ltrace.slicer_utils import LTracePlugin, LTracePluginLogic, LTraceEnvironmentMixin, getResourcePath


class CoreEnv(LTracePlugin):
    SETTING_KEY = "CoreEnv"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Core Environment"
        self.parent.categories = ["Environment", "Core"]
        self.parent.dependencies = []
        self.parent.hidden = True
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ""
        self.environment = CoreEnvLogic()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CoreEnvLogic(LTracePluginLogic, LTraceEnvironmentMixin):
    def __init__(self):
        super().__init__()
        self.__modulesToolbar = None

    @property
    def modulesToolbar(self):
        if not self.__modulesToolbar:
            raise AttributeError("Modules toolbar not set")
        return self.__modulesToolbar

    @modulesToolbar.setter
    def modulesToolbar(self, value):
        self.__modulesToolbar = value

    def setupEnvironment(self):
        relatedModules = self.getModuleManager().fetchByCategory([self.category])

        addAction(relatedModules["CustomizedData"], self.modulesToolbar)
        addAction(relatedModules["Multicore"], self.modulesToolbar)
        addAction(relatedModules["CorePhotographLoader"], self.modulesToolbar)
        addAction(relatedModules["CustomizedCropVolume"], self.modulesToolbar)

        addAction(relatedModules["MulticoreTransforms"], self.modulesToolbar)
        self.setupSegmentation()
        addAction(relatedModules["CoreInpaint"], self.modulesToolbar)
        addAction(relatedModules["MulticoreExport"], self.modulesToolbar)

        self.getModuleManager().setEnvironment(("Core", "CoreEnv"))

    def setupSegmentation(self):
        modules = self.getModuleManager().fetchByCategory(("Core",), intersectWith="Segmentation")

        addMenu(
            svgToQIcon(getResourcePath("Icons") / "svg" / "Layers.svg"),
            "Segmentation",
            [
                modules["CustomizedSegmentEditor"],
                modules["Segmenter"],
                modules["SegmentInspector"],
                modules["LabelMapEditor"],
                modules["PoreStats"],
            ],
            self.modulesToolbar,
        )

        segmentEditor = slicer.util.getModuleWidget("CustomizedSegmentEditor")
        segmentEditor.configureEffects()
