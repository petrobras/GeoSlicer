import os
from pathlib import Path

import qt
import slicer
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget

from CTAutoRegistration import CTAutoRegistration
from CustomizedCropVolume import CustomizedCropVolume
from CustomizedData import CustomizedData
from Multicore import Multicore
from MulticoreTransforms import MulticoreTransforms
from SegmentationEnv import SegmentationEnv


class CoreEnv(LTracePlugin):
    SETTING_KEY = "CoreEnv"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Core Environment"
        self.parent.categories = ["Environments"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = (
            CoreEnv.help()
            + CustomizedData.help()
            + Multicore.help()
            + MulticoreTransforms.help()
            + CustomizedCropVolume.help()
            + SegmentationEnv.help()
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CoreEnvWidget(LTracePluginWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lastAccessedWidget = None

    def setup(self):
        LTracePluginWidget.setup(self)
        self.mainTab = qt.QTabWidget()
        self.layout.addWidget(self.mainTab)

        # Data tab
        dataTab = qt.QTabWidget()
        dataTab.addTab(slicer.modules.customizeddata.createNewWidgetRepresentation(), "Explorer")
        dataTab.addTab(slicer.modules.multicore.createNewWidgetRepresentation(), "CT Import")
        dataTab.addTab(slicer.modules.corephotographloader.createNewWidgetRepresentation(), "Photo Import (beta)")
        dataTab.addTab(slicer.modules.multicoreexport.createNewWidgetRepresentation(), "Export")

        self.mainTab.addTab(dataTab, "Data")
        self.mainTab.addTab(slicer.modules.multicoretransforms.createNewWidgetRepresentation(), "Transforms")
        self.mainTab.addTab(slicer.modules.customizedcropvolume.createNewWidgetRepresentation(), "Crop")
        self.segmentationEnv = slicer.modules.segmentationenv.createNewWidgetRepresentation()
        self.mainTab.addTab(self.segmentationEnv, "Segmentation")
        self.mainTab.addTab(slicer.modules.coreinpaint.createNewWidgetRepresentation(), "Inpaint")

        self.lastAccessedWidget = dataTab.widget(0)

        self.segmentationEnv.self().segmentEditorWidget.self().selectParameterNodeByTag(CoreEnv.SETTING_KEY)

        # Start connections
        self.mainTab.tabBarClicked.connect(self.onMainTabClicked)

    def onMainTabClicked(self, index):
        self.lastAccessedWidget.exit()
        self.lastAccessedWidget = self.mainTab.widget(index)
        if type(self.lastAccessedWidget) is qt.QTabWidget:
            self.lastAccessedWidget = self.lastAccessedWidget.currentWidget()
        self.lastAccessedWidget.enter()

    def enter(self) -> None:
        super().enter()
        if self.lastAccessedWidget is None:
            return

        self.lastAccessedWidget.enter()

    def exit(self):
        if self.lastAccessedWidget is None:
            return

        self.lastAccessedWidget.exit()
