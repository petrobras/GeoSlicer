import os
from pathlib import Path

import slicer

from ltrace.slicer.helpers import svgToQIcon
from ltrace.slicer.widget.custom_toolbar_buttons import addAction, addMenu
from ltrace.slicer_utils import LTracePlugin, LTracePluginLogic, getResourcePath, LTraceEnvironmentMixin


class ThinSectionEnv(LTracePlugin):
    SETTING_KEY = "ThinSectionEnv"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Thin Section Environment"
        self.parent.categories = ["Environment", "Thin Section"]
        self.parent.hidden = True
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ""

        self.environment = ThinSectionEnvLogic()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ThinSectionEnvLogic(LTracePluginLogic, LTraceEnvironmentMixin):
    def __init__(self):
        super().__init__()
        self.__modulesToolbar = None

    def setupEnvironment(self):
        relatedModules = self.getModuleManager().fetchByCategory([self.category])

        addAction(relatedModules["CustomizedData"], self.modulesToolbar)
        addAction(relatedModules["ThinSectionLoader"], self.modulesToolbar)
        addAction(relatedModules["QEMSCANLoader"], self.modulesToolbar)
        addAction(relatedModules["CustomizedCropVolume"], self.modulesToolbar)
        addAction(relatedModules["ImageTools"], self.modulesToolbar)
        addMenu(
            svgToQIcon(getResourcePath("Icons") / "svg" / "Register2D.svg"),
            "Register",
            [relatedModules["ThinSectionRegistration"], relatedModules["ThinSectionAutoRegistration"]],
            self.modulesToolbar,
        )

        self.setupSegmentation()

        addAction(relatedModules["ThinSectionFlows"], self.modulesToolbar)
        addAction(relatedModules["MultipleImageAnalysis"], self.modulesToolbar)
        addAction(relatedModules["ThinSectionExport"], self.modulesToolbar)

        self.setupTools(tools=["VolumeCalculator", "CustomizedTables", "TableFilter", "Charts", "NetCDF"])
        self.setupLoaders()

        self.getModuleManager().setEnvironment(("Thin Section", "ThinSectionEnv"))

    def setupSegmentation(self):
        modules = self.getModuleManager().fetchByCategory(("Thin Section",), intersectWith="Segmentation")

        addMenu(
            svgToQIcon(getResourcePath("Icons") / "svg" / "Layers.svg"),
            "Segmentation",
            [
                modules["CustomizedSegmentEditor"],
                modules["Segmenter"],
                modules["SegmentInspector"],
                modules["ThinSectionInstanceEditor"],
                modules["LabelMapEditor"],
                modules["PoreStats"],
                modules["UnsupervisedSegmentation"],
            ],
            self.modulesToolbar,
        )

        segmentEditor = slicer.util.getModuleWidget("CustomizedSegmentEditor")
        segmentEditor.configureEffectsForThinSectionEnvironment()

    def enter(self) -> None:
        layoutNode = slicer.app.layoutManager().layoutLogic().GetLayoutNode()
        if layoutNode.GetViewArrangement() != slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView:
            layoutNode.SetViewArrangement(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
