import os
from pathlib import Path

import qt, slicer

from ltrace.slicer_utils import *

from LabelMapEditor import LabelMapEditor
from ltrace.slicer.node_attributes import NodeEnvironment
from Segmenter import Segmenter
from ThinSectionInstanceSegmenter import ThinSectionInstanceSegmenter
from SegmentInspector import SegmentInspector


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
        self.parent.contributors = ["LTrace Geophysics Team"]  # replace with "Firstname Lastname (Organization)"
        self.parent.helpText = SegmentationEnv.help()
        self.parent.acknowledgementText = ""

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")

    @classmethod
    def help(cls):
        import markdown

        htmlHelp = ""
        with open(cls.readme_path(), "r", encoding="utf-8") as docfile:
            md = markdown.Markdown(extras=["fenced-code-blocks"])
            htmlHelp = md.convert(docfile.read())

        htmlHelp += "\n".join([Segmenter.help(), SegmentInspector.help(), LabelMapEditor.help()])

        return htmlHelp


def ManualSegmentationTab():
    return slicer.modules.customizedsegmenteditor.createNewWidgetRepresentation()


def SmartSegmenterTab():
    return slicer.modules.segmenter.createNewWidgetRepresentation()


def ThinSectionInstanceSegmenterTab():
    return slicer.modules.thinsectioninstancesegmenter.createNewWidgetRepresentation()


def ThinSectionInstanceEditorTab():
    return slicer.modules.thinsectioninstanceeditor.createNewWidgetRepresentation()


def SegmentInspectorTab():
    return slicer.modules.segmentinspector.createNewWidgetRepresentation()


def ThinSectionSegmentInspectorTab():
    return slicer.modules.thinsectionsegmentinspector.createNewWidgetRepresentation()


def LabelMapEditorTab():
    return slicer.modules.labelmapeditor.createNewWidgetRepresentation()


def SegmentationModellingTab():
    return slicer.modules.segmentationmodelling.createNewWidgetRepresentation()


def HistogramTab():
    return slicer.modules.histogramsegmenter.createNewWidgetRepresentation()


class SegmentationEnvWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.hasModelling = False
        self.hasPetrography = False
        self.isThinSection = False

    def setup(self):
        LTracePluginWidget.setup(self)

        self.currentTabIndex = 0

        # Instantiate and connect widgets ...

        self.tabsWidget = qt.QTabWidget()
        self.segmentEditorWidget = ManualSegmentationTab()
        self.smartSegWidget = SmartSegmenterTab()
        self.tabsWidget.addTab(self.segmentEditorWidget, "Manual")
        self.tabsWidget.addTab(self.smartSegWidget, "Smart-seg")
        if self.hasPetrography:
            self.petrographyWidget = ThinSectionInstanceSegmenterTab()
            self.tabsWidget.addTab(self.petrographyWidget, "Instance")
            self.tabsWidget.addTab(ThinSectionInstanceEditorTab(), "Instance Editor")
        if self.isThinSection:
            self.tabsWidget.addTab(ThinSectionSegmentInspectorTab(), "Inspector")
        else:
            self.tabsWidget.addTab(SegmentInspectorTab(), "Inspector")
        self.tabsWidget.addTab(LabelMapEditorTab(), "Label Editor")
        if self.hasModelling:
            self.tabsWidget.addTab(SegmentationModellingTab(), "Modelling")

        tabsWidgetLayout = qt.QVBoxLayout(self.tabsWidget)
        tabsWidgetLayout.addStretch(1)

        self.layout.addWidget(self.tabsWidget)
        self.tabsWidget.tabBarClicked.connect(self.onTabBarClicked)

    def enter(self) -> None:
        super().enter()
        self.tabsWidget.widget(self.currentTabIndex).enter()
        self.smartSegWidget.self().enter()
        if self.hasPetrography:
            self.petrographyWidget.self().enter()

    def exit(self):
        self.tabsWidget.widget(self.currentTabIndex).exit()

    def onTabBarClicked(self, index):
        self.exit()
        self.currentTabIndex = index
        self.enter()

    def removeTab(self, index):
        self.tabsWidget.removeTab(index)


#
# SegmentationEnvLogic
#
class SegmentationEnvLogic(LTracePluginLogic):
    pass
