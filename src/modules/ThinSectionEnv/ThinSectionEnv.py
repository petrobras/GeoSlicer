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
            svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "Register.svg"),
            "Register",
            [relatedModules["ThinSectionRegistration"], relatedModules["ThinSectionAutoRegistration"]],
            self.modulesToolbar,
        )

        self.setupSegmentation()

        addAction(relatedModules["ThinSectionFlows"], self.modulesToolbar)
        addAction(relatedModules["MultipleImageAnalysis"], self.modulesToolbar)
        addAction(relatedModules["ThinSectionExport"], self.modulesToolbar)

        self.setupTools()
        self.setupLoaders()

        self.getModuleManager().setEnvironment(("Thin Section", "ThinSectionEnv"))

    def setupSegmentation(self):
        modules = self.getModuleManager().fetchByCategory(("Thin Section",), intersectWith="Segmentation")

        addMenu(
            svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "Layers.svg"),
            "Segmentation",
            [
                modules["CustomizedSegmentEditor"],
                modules["Segmenter"],
                modules["SegmentInspector"],
                # modules["ThinSectionInstanceSegmenter"],
                # modules["ThinSectionInstanceEditor"],
                modules["LabelMapEditor"],
                modules["PoreStats"],
            ],
            self.modulesToolbar,
        )

        segmentEditor = slicer.util.getModuleWidget("CustomizedSegmentEditor")
        segmentEditor.configureEffectsForThinSectionEnvironment()

    def enter(self) -> None:
        layoutNode = slicer.app.layoutManager().layoutLogic().GetLayoutNode()
        if layoutNode.GetViewArrangement() != slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView:
            layoutNode.SetViewArrangement(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)

    # def setupEnviron(self):
    #     addAction(self.__modulesInfo["CustomizedData"], self.modulesToolbar)
    #     addAction(self.__modulesInfo["ThinSectionLoader"], self.modulesToolbar)
    #     addAction(self.__modulesInfo["QEMSCANLoader"], self.modulesToolbar)
    #     addAction(self.__modulesInfo["CustomizedCropVolume"], self.modulesToolbar)
    #     addAction(self.__modulesInfo["ImageTools"], self.modulesToolbar)
    #     addMenu(
    #         svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "Register.svg"),
    #         "Register",
    #         [self.__modulesInfo["ThinSectionRegistration"], self.__modulesInfo["ThinSectionAutoRegistration"]],
    #         self.modulesToolbar,
    #     )
    #
    #     segmentation = getattr(slicer.modules, "SegmentationEnvInstance")
    #     segmentation.environment.modulesToolbar = self.modulesToolbar
    #     segmentation.environment.setupEnv(self.__modulesInfo)  # TODO Move sets to args maybe?
    #
    #     addAction(self.__modulesInfo["ThinSectionFlows"], self.modulesToolbar)
    #     addAction(self.__modulesInfo["MultipleImageAnalysis"], self.modulesToolbar)
    #     addAction(self.__modulesInfo["ThinSectionExport"], self.modulesToolbar)

    # @classmethod
    # def addAction(cls, module, toolbar, parent=None):
    #     if not parent:
    #         parent = toolbar
    #     m = getattr(slicer.modules, module.key.lower())
    #     button = CustomToolButton(parent)
    #     action = qt.QAction(m.icon, m.title, parent)
    #     action.setToolTip(m.title)
    #     action.triggered.connect(lambda _, name=module.key: slicer.util.selectModule(name))
    #     button.setDefaultAction(action)
    #     toolbar.addWidget(button)
    #
    # @classmethod
    # def addMenuEntry(cls, module, menu, parent=None):
    #     if not parent:
    #         parent = menu
    #     m = getattr(slicer.modules, module.key.lower())
    #     action = qt.QAction(m.icon, m.title, parent)
    #     action.triggered.connect(lambda _, name=module.key: slicer.util.selectModule(name))
    #     #menu.setToolButtonStyle(qt.Qt.ToolButtonTextBesideIcon)
    #     menu.addAction(action)
    #
    # @classmethod
    # def addMenu(cls, icon, folder, modules, parent):
    #     tool_button = CustomToolButton(parent)
    #     tool_button.setIcon(icon)
    #     tool_button.setText(folder)
    #     tool_button.setToolTip(folder)
    #
    #     menu = qt.QMenu(tool_button)
    #     for module in modules:
    #         cls.addMenuEntry(module, menu, parent)
    #     tool_button.setMenu(menu)
    #
    #     tool_button.setPopupMode(qt.QToolButton.MenuButtonPopup)
    #
    #     parent.addWidget(tool_button)


# class ThinSectionEnvWidget(LTracePluginWidget):
#     def __init__(self, parent):
#         LTracePluginWidget.__init__(self, parent)
#         self.previousLayout = None
#
#     def setup(self):
#         LTracePluginWidget.setup(self)
#
#         self.mainTab = qt.QTabWidget()
#
#         self.dataTab = qt.QTabWidget()
#         self.dataTab.addTab(slicer.modules.customizeddata.createNewWidgetRepresentation(), "Explorer")
#         self.dataTab.addTab(slicer.modules.thinsectionloader.createNewWidgetRepresentation(), "Import")
#         self.dataTab.addTab(slicer.modules.qemscanloader.createNewWidgetRepresentation(), "Import QEMSCAN")
#         self.dataTab.addTab(slicer.modules.thinsectionexport.createNewWidgetRepresentation(), "Export")
#         self.dataTab.addTab(slicer.modules.thinsectionflows.createNewWidgetRepresentation(), "Flows")
#         self.mainTab.addTab(self.dataTab, "Data")
#         self.mainTab.addTab(slicer.modules.customizedcropvolume.createNewWidgetRepresentation(), "Crop")
#         self.mainTab.addTab(slicer.modules.imagetools.createNewWidgetRepresentation(), "Image Tools")
#         segEnv = slicer.modules.thinsectionsegmentationenv.createNewWidgetRepresentation()
#         self.mainTab.addTab(segEnv, "Segmentation")  # remove histogram from thin section
#
#         # Registration tab
#         thinSectionRegistrationWidget = slicer.modules.thinsectionregistration.createNewWidgetRepresentation()
#         thinSectionAutoRegistrationWidget = slicer.modules.thinsectionautoregistration.widgetRepresentation()
#         self.registrationTab = qt.QTabWidget()
#         self.registrationTab.addTab(thinSectionRegistrationWidget, "Manual")
#         self.registrationTab.addTab(thinSectionAutoRegistrationWidget, "Automatic")
#         self.mainTab.addTab(self.registrationTab, "Registration")
#
#         self.multipleImageAnalysisWidget = slicer.modules.multipleimageanalysis.widgetRepresentation()
#         self.mainTab.addTab(self.multipleImageAnalysisWidget, "Multi-Image Analysis")
#
#         self.lastAccessedWidget = self.dataTab.widget(0)
#
#         self.dataTab.tabBarClicked.connect(self.onDataTabClicked)
#         self.mainTab.tabBarClicked.connect(self.onMainTabClicked)
#         self.registrationTab.tabBarClicked.connect(self.onRegistrationTabClicked)
#
#         self.layout.addWidget(self.mainTab)
#
#         # Configure manual segment editor effects
#         segEnv.self().segmentEditorWidget.self().selectParameterNodeByTag(ThinSectionEnv.SETTING_KEY)
#         segEnv.self().segmentEditorWidget.self().configureEffectsForThinSectionEnvironment()
#
#     def onMainTabClicked(self, index) -> None:
#         if self.lastAccessedWidget != self.mainTab.widget(
#             index
#         ):  # To avoid calling exit by clicking over the active tab
#             self.lastAccessedWidget.exit()
#             self.lastAccessedWidget = self.mainTab.widget(index)
#             if type(self.lastAccessedWidget) is qt.QTabWidget:
#                 self.lastAccessedWidget = self.lastAccessedWidget.currentWidget()
#             self.lastAccessedWidget.enter()
#
#     def onDataTabClicked(self, index) -> None:
#         self.lastAccessedWidget.exit()
#         self.lastAccessedWidget = self.dataTab.widget(index)
#         self.lastAccessedWidget.enter()
#
#     def onRegistrationTabClicked(self, index) -> None:
#         self.lastAccessedWidget.exit()
#         self.lastAccessedWidget = self.registrationTab.widget(index)
#         self.lastAccessedWidget.enter()
#
#     def enter(self) -> None:
#         super().enter()
#         self.layoutNode = slicer.app.layoutManager().layoutLogic().GetLayoutNode()
#         self.previousLayout = self.layoutNode.GetViewArrangement()
#         self.layoutNode.SetViewArrangement(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
#         self.lastAccessedWidget.enter()
#
#     def exit(self):
#         self.lastAccessedWidget.exit()
#
#         if not self.previousLayout:
#             return
#
#         # If layout was not changed from red slice, restore to previous one
#         if self.layoutNode.GetViewArrangement() == slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView:
#             self.layoutNode.SetViewArrangement(self.previousLayout)
#
#     def switchToMultipleImageAnalysis(self):
#         self.mainTab.setCurrentWidget(self.multipleImageAnalysisWidget)
