import os
from pathlib import Path

from ltrace.slicer.helpers import svgToQIcon
from ltrace.slicer.module_utils import loadModules
from ltrace.slicer.widget.custom_toolbar_buttons import addMenu
from ltrace.slicer_utils import *
from ltrace.slicer_utils import getResourcePath


#
# SegmentationEnv
#
class SegmentationEnv(LTracePlugin):
    SETTING_KEY = "SegmentationEnv"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Segmentation Tools"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.hidden = True
        self.parent.contributors = ["LTrace Geophysics Team"]  # replace with "Firstname Lastname (Organization)"
        self.parent.helpText = ""
        self.parent.acknowledgementText = ""

        self.environment = SegmentationEnvLogic()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


#
#
# def ManualSegmentationTab():
#     return slicer.modules.customizedsegmenteditor.createNewWidgetRepresentation()
#
#
# def SmartSegmenterTab():
#     return slicer.modules.segmenter.createNewWidgetRepresentation()
#
#
# def PoreStatsTab():
#     return slicer.modules.porestats.createNewWidgetRepresentation()
#
#
# def ThinSectionInstanceSegmenterTab():
#     return slicer.modules.thinsectioninstancesegmenter.createNewWidgetRepresentation()
#
#
# def ThinSectionInstanceEditorTab():
#     return slicer.modules.thinsectioninstanceeditor.createNewWidgetRepresentation()
#
#
# def SegmentInspectorTab():
#     return slicer.modules.segmentinspector.createNewWidgetRepresentation()
#
#
# def ThinSectionSegmentInspectorTab():
#     return slicer.modules.thinsectionsegmentinspector.createNewWidgetRepresentation()
#
#
# def LabelMapEditorTab():
#     return slicer.modules.labelmapeditor.createNewWidgetRepresentation()
#
#
# def SegmentationModellingTab():
#     return slicer.modules.segmentationmodelling.createNewWidgetRepresentation()
#
#
# def HistogramTab():
#     return slicer.modules.histogramsegmenter.createNewWidgetRepresentation()
#
#
# class SegmentationEnvWidget(LTracePluginWidget):
#     def __init__(self, parent):
#         LTracePluginWidget.__init__(self, parent)
#         self.hasModelling = False
#         self.hasPetrography = False
#         self.isThinSection = False
#
#     def setup(self):
#         LTracePluginWidget.setup(self)
#
#         self.currentTabIndex = 0
#
#         # Instantiate and connect widgets ...
#
#         self.tabsWidget = qt.QTabWidget()
#         self.segmentEditorWidget = ManualSegmentationTab()
#         self.smartSegWidget = SmartSegmenterTab()
#         self.poreStatsWdiget = PoreStatsTab()
#         self.tabsWidget.addTab(self.segmentEditorWidget, "Manual")
#         self.tabsWidget.addTab(self.smartSegWidget, "Smart-seg")
#         if self.hasPetrography:
#             self.petrographyWidget = ThinSectionInstanceSegmenterTab()
#             self.tabsWidget.addTab(self.petrographyWidget, "Instance")
#             self.tabsWidget.addTab(ThinSectionInstanceEditorTab(), "Instance Editor")
#         if self.isThinSection:
#             self.tabsWidget.addTab(ThinSectionSegmentInspectorTab(), "Inspector")
#             self.tabsWidget.addTab(self.poreStatsWdiget, "Pore Stats")
#         else:
#             self.tabsWidget.addTab(SegmentInspectorTab(), "Inspector")
#         self.tabsWidget.addTab(LabelMapEditorTab(), "Label Editor")
#         if self.hasModelling:
#             self.tabsWidget.addTab(SegmentationModellingTab(), "Modelling")
#
#         tabsWidgetLayout = qt.QVBoxLayout(self.tabsWidget)
#         tabsWidgetLayout.addStretch(1)
#
#         self.layout.addWidget(self.tabsWidget)
#         self.tabsWidget.tabBarClicked.connect(self.onTabBarClicked)
#
#     def enter(self) -> None:
#         super().enter()
#         self.tabsWidget.widget(self.currentTabIndex).enter()
#         self.smartSegWidget.self().enter()
#         if self.hasPetrography:
#             self.petrographyWidget.self().enter()
#
#     def exit(self):
#         self.tabsWidget.widget(self.currentTabIndex).exit()
#
#     def onTabBarClicked(self, index):
#         self.exit()
#         self.currentTabIndex = index
#         self.enter()
#
#     def removeTab(self, index):
#         self.tabsWidget.removeTab(index)
#

#
# SegmentationEnvLogic
#
class SegmentationEnvLogic(LTracePluginLogic):
    def __init__(self):
        super().__init__()
        self.__modulesToolbar = None
        self.__modulesInfo = None

    @property
    def modulesToolbar(self):
        if not self.__modulesToolbar:
            raise AttributeError("Modules toolbar not set")
        return self.__modulesToolbar

    @modulesToolbar.setter
    def modulesToolbar(self, value):
        self.__modulesToolbar = value

    def setModules(self, modules):
        self.__modulesInfo = {module.key: module for module in modules}

    def onStartupCompleted(self):
        pass

    def setupEnviron(self):
        pass

    def setupEnv(self, moduleManager):
        modulesForThinSection = set(moduleManager["Thin Section"])
        modulesForSegmentation = set(moduleManager["Segmentation"])
        modulesForSegmentationTools = set(moduleManager["Tools"])
        modules = modulesForSegmentation.intersection(modulesForThinSection)
        modules.update(modulesForSegmentation.intersection(modulesForSegmentationTools))

        loadModules(modules, permanent=False, favorite=False)
        self.setModules(modules)

        addMenu(
            svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "Layers.svg"),
            "Segmentation",
            [
                self.__modulesInfo["CustomizedSegmentEditor"],
                self.__modulesInfo["Segmenter"],
                self.__modulesInfo["SegmentInspector"],
                self.__modulesInfo["ThinSectionInstanceSegmenter"],
                self.__modulesInfo["ThinSectionInstanceEditor"],
                self.__modulesInfo["LabelMapEditor"],
                self.__modulesInfo["PoreStats"],
            ],
            self.modulesToolbar,
        )
