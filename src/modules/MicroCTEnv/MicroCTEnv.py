import os
from pathlib import Path

import slicer

from ltrace.slicer.helpers import svgToQIcon
from ltrace.slicer.widget.custom_toolbar_buttons import addAction, addMenu
from ltrace.slicer_utils import (
    LTracePlugin,
    LTracePluginLogic,
    getResourcePath,
    LTraceEnvironmentMixin,
    slicer_is_in_developer_mode,
)


class MicroCTEnv(LTracePlugin):
    SETTING_KEY = "MicroCTEnv"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Micro CT Environment"
        self.parent.categories = ["Environment", "MicroCT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ""
        self.parent.hidden = True
        self.environment = MicroCTEnvLogic()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MicroCTEnvLogic(LTracePluginLogic, LTraceEnvironmentMixin):
    def __init__(self):
        super().__init__()
        self.__modulesToolbar = None
        self.__customSegmentEditor = None

    def setupEnvironment(self):
        relatedModules = self.getModuleManager().fetchByCategory([self.category])

        pore_network_modules = [
            "PoreNetworkExtractor",
            "PoreNetworkSimulation",
            "PoreNetworkKabsREV",
            "PoreNetworkVisualization",
            "PoreNetworkKrelEda",
            "PoreNetworkProduction",
        ]
        if slicer_is_in_developer_mode():
            pore_network_modules.append("PoreNetworkCompare")

        modules = [
            "CustomizedData",
            "MicroCTLoader",
            "MicroCTExport",
            "CustomizedCropVolume",
            "FilteringTools",
            "CustomResampleScalarVolume",
            self.setupSegmentation,
            "MicrotomRemote",
            (
                "Microporosity",
                [
                    "SegmentationModelling",
                    "PorosityMappingFromSaturation",
                ],
            ),
            "StreamlinedModelling",
            (
                "Register",
                [
                    "MicroCTTransforms",
                    "CTAutoRegistration",
                ],
            ),
            ("Pore Network", pore_network_modules),
            (
                "Multiscale",
                [
                    "MultiScale",
                    "MultiscalePostProcessing",
                ],
            ),
            (
                "BigImage",
                [
                    "BigImage",
                    "PolynomialShadingCorrectionBigImage",
                    "BoundaryRemovalBigImage",
                    "ExpandSegmentsBigImage",
                    "MultipleThresholdBigImage",
                    "StreamlinedSegmentation",
                ],
            ),
        ]

        for module in modules:
            if isinstance(module, str):
                addAction(relatedModules[module], self.modulesToolbar)
            elif isinstance(module, tuple):
                name, modules = module
                modules = [relatedModules.get(m, None) for m in modules]
                modules = [m for m in modules if m is not None]
                if modules:
                    addMenu(
                        svgToQIcon(getResourcePath("Icons") / "svg" / f"{name}.svg"),
                        name,
                        modules,
                        self.modulesToolbar,
                    )
            elif callable(module):
                module()

        self.setupTools(
            tools=["VolumeCalculator", "CustomizedTables", "TableFilter", "Charts", "VariogramAnalysis", "NetCDF"]
        )

        self.setupLoaders()

        self.getModuleManager().setEnvironment(("Volumes", "MicroCTEnv"))

    def setupSegmentation(self):
        modules = self.getModuleManager().fetchByCategory(("MicroCT",), intersectWith="Segmentation")

        addMenu(
            svgToQIcon(getResourcePath("Icons") / "svg" / "Layers.svg"),
            "Segmentation",
            [
                modules["CustomizedSegmentEditor"],
                modules["Segmenter"],
                modules["SegmentInspector"],
                modules["InteractiveSegmenter"],
            ],
            self.modulesToolbar,
        )

        segmentEditor = slicer.util.getModuleWidget("CustomizedSegmentEditor")
        segmentEditor.configureEffects()

    def segmentEditor(self):
        return slicer.util.getModuleWidget("CustomizedSegmentEditor")

    def enter(self) -> None:
        layoutNode = slicer.app.layoutManager().layoutLogic().GetLayoutNode()
        if layoutNode.GetViewArrangement() != slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView:
            layoutNode.SetViewArrangement(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
