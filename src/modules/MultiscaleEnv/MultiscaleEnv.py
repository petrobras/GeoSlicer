import os
from pathlib import Path

import slicer
import qt

from ltrace.slicer.helpers import svgToQIcon
from ltrace.slicer.widget.custom_toolbar_buttons import addAction, addMenu
from ltrace.slicer_utils import LTracePlugin, LTracePluginLogic, getResourcePath, LTraceEnvironmentMixin
from ltrace.constants import ImageLogConst


class MultiscaleEnv(LTracePlugin):
    SETTING_KEY = "MultiscaleEnv"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Multiscale Environment"
        self.parent.categories = ["Environment", "Multiscale"]
        self.parent.contributors = ["LTrace Geophysics Team"]

        self.environment = MultiscaleEnvLogic()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MultiscaleEnvLogic(LTracePluginLogic, LTraceEnvironmentMixin):
    def __init__(self):
        super().__init__()
        self.__modulesToolbar = None

    def setupEnvironment(self):
        relatedModules = self.getModuleManager().fetchByCategory([self.category])

        modules = [
            "CustomizedData",
            "ImageLogData",
            "GeologEnv",
            # imports
            ("Import Tools", ["ImageLogImport", "ImageLogUnwrapImport", "MicroCTLoader", "Multicore"]),
            # exports
            (
                "Export Tools",
                [
                    "ImageLogExport",
                    "MicroCTExport",
                    "MulticoreExport",
                ],
            ),
            # ImageLog Modules
            ("Image Log Pre-Processing", ["ImageLogCropVolume", "AzimuthShiftTool", "SpiralFilter", "ImageLogInpaint"]),
            # Volumes Modules
            (
                "Volumes Pre-Processing",
                ["CustomizedCropVolume", "CustomResampleScalarVolume", "FilteringTools"],
            ),
            "MicrotomRemote",
            "MultiScale",
            "MultiscalePostProcessing",
            "PoreNetworkSimulation",
        ]

        for module in modules:
            if isinstance(module, str):
                addAction(relatedModules[module], self.modulesToolbar)
            elif isinstance(module, tuple):
                name, modules = module
                iconName = name.replace(" ", "").replace("-", "")
                addMenu(
                    svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / f"{iconName}.svg"),
                    name,
                    [relatedModules[m] for m in modules],
                    self.modulesToolbar,
                )
            elif callable(module):
                module()

        self.setupSegmentation("MicroCT")
        self.setupSegmentation("ImageLog")

        self.modulesToolbar.actions()[1].setVisible(False)
        self.modulesToolbar.actions()[11].setVisible(False)

        self.setupTools()

        self.addImageLogViewOption()

        self.getModuleManager().setEnvironment(("Multiscale", "MultiscaleEnv"))

        self.modulesToolbar.setIconSize(qt.QSize(24, 30))

    def enter(self) -> None:
        slicer.app.layoutManager().layoutChanged.connect(self.switchViewDataModule)

    def setupSegmentation(self, category: str) -> None:
        modules = self.getModuleManager().fetchByCategory((category,), intersectWith="Segmentation")

        if category == "MicroCT":
            name = "Volume"
            segmentationModules = [
                modules["CustomizedSegmentEditor"],
                modules["Segmenter"],
                modules["SegmentInspector"],
            ]
        else:
            name = "Image Log"
            segmentationModules = [
                modules["ImageLogSegmentEditor"],
                modules["ImageLogInstanceSegmenter"],
                modules["InstanceSegmenterEditor"],
            ]

        addMenu(
            svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "Layers.svg"),
            f"{name} Segmentation",
            segmentationModules,
            self.modulesToolbar,
        )

    def switchViewDataModule(self, layoutID: int):
        if self.getModuleManager().currentWorkingDataType[0] == "Multiscale":
            isImageLogView = layoutID > ImageLogConst.DEFAULT_LAYOUT_ID_START_VALUE
            self.modulesToolbar.actions()[0].setVisible(not isImageLogView)
            self.modulesToolbar.actions()[11].setVisible(not isImageLogView)
            self.modulesToolbar.actions()[1].setVisible(isImageLogView)
            self.modulesToolbar.actions()[12].setVisible(isImageLogView)

            if slicer.util.selectedModule() in ["CustomizedData", "ImageLogData"]:
                slicer.util.selectModule("ImageLogData" if isImageLogView else "CustomizedData")
            elif isImageLogView and slicer.util.selectedModule() in [
                "CustomizedSegmentEditor",
                "Segmenter",
                "SegmentInspector",
            ]:
                slicer.util.selectModule("ImageLogSegmentEditor")
            elif not isImageLogView and slicer.util.selectedModule() in [
                "ImageLogSegmentEditor",
                "ImageLogInstanceSegmenter",
                "InstanceSegmenterEditor",
            ]:
                slicer.util.selectModule("CustomizedSegmentEditor")

    def addImageLogViewOption(self) -> None:
        self.viewToolBar = slicer.util.mainWindow().findChild("QToolBar", "ViewToolBar")
        layoutMenu = self.viewToolBar.widgetForAction(self.viewToolBar.actions()[0]).menu()

        imageLogActionText = "ImageLog View"
        imageLogActionInMenu = imageLogActionText in [action.text for action in layoutMenu.actions()]

        if not imageLogActionInMenu:
            self.imageLogLayoutViewAction = qt.QAction(imageLogActionText)
            self.imageLogLayoutViewAction.setIcon(qt.QIcon(getResourcePath("Icons") / "ImageLog.png"))
            self.imageLogLayoutViewAction.triggered.connect(self.__onImagelogLayoutViewActionClicked)

            after3DOnlyActionIndex = next(
                (i for i, action in enumerate(layoutMenu.actions()) if action.text == "3D only"), None
            )
            layoutMenu.insertAction(
                layoutMenu.actions()[after3DOnlyActionIndex + 1], self.imageLogLayoutViewAction
            )  # insert new action before reference

    def __onImagelogLayoutViewActionClicked(self) -> None:
        if self.getModuleManager().currentWorkingDataType[0] in ["ImageLog", "Multiscale"]:
            slicer.util.getModuleLogic("ImageLogData").changeToLayout()
            self.imageLogLayoutViewAction.setData(slicer.modules.AppContextInstance.imageLogLayoutId)
