import os
from pathlib import Path

import qt
import slicer
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget

from CustomizedCropVolume import CustomizedCropVolume
from CustomizedData import CustomizedData
from ImageTools import ImageTools
from QEMSCANLoader import QEMSCANLoader
from ThinSectionLoader import ThinSectionLoader
from ThinSectionRegistration import ThinSectionRegistration
from SegmentationEnv import SegmentationEnv


class ThinSectionEnv(LTracePlugin):
    SETTING_KEY = "ThinSectionEnv"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Thin Section Environment"
        self.parent.categories = ["Environments"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = (
            ThinSectionEnv.help()
            + CustomizedData.help()
            + ThinSectionLoader.help()
            + QEMSCANLoader.help()
            + CustomizedCropVolume.help()
            + ImageTools.help()
            + ThinSectionRegistration.help()
            + SegmentationEnv.help()
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ThinSectionEnvWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        self.mainTab = qt.QTabWidget()

        self.dataTab = qt.QTabWidget()
        self.dataTab.addTab(slicer.modules.customizeddata.createNewWidgetRepresentation(), "Explorer")
        self.dataTab.addTab(slicer.modules.thinsectionloader.createNewWidgetRepresentation(), "Import")
        self.dataTab.addTab(slicer.modules.qemscanloader.createNewWidgetRepresentation(), "Import QEMSCAN")
        self.dataTab.addTab(slicer.modules.thinsectionexport.createNewWidgetRepresentation(), "Export")
        self.mainTab.addTab(self.dataTab, "Data")
        self.mainTab.addTab(slicer.modules.customizedcropvolume.createNewWidgetRepresentation(), "Crop")
        self.mainTab.addTab(slicer.modules.imagetools.createNewWidgetRepresentation(), "Image Tools")
        segEnv = slicer.modules.thinsectionsegmentationenv.createNewWidgetRepresentation()
        self.mainTab.addTab(segEnv, "Segmentation")  # remove histogram from thin section

        # Registration tab
        thinSectionRegistrationWidget = slicer.modules.thinsectionregistration.createNewWidgetRepresentation()
        thinSectionAutoRegistrationWidget = slicer.modules.thinsectionautoregistration.widgetRepresentation()
        self.registrationTab = qt.QTabWidget()
        self.registrationTab.addTab(thinSectionRegistrationWidget, "Manual")
        self.registrationTab.addTab(thinSectionAutoRegistrationWidget, "Automatic")
        self.mainTab.addTab(self.registrationTab, "Registration")

        self.multipleImageAnalysisWidget = slicer.modules.multipleimageanalysis.widgetRepresentation()
        self.mainTab.addTab(self.multipleImageAnalysisWidget, "Multi-Image Analysis")

        self.lastAccessedWidget = self.dataTab.widget(0)

        self.dataTab.tabBarClicked.connect(self.onDataTabClicked)
        self.mainTab.tabBarClicked.connect(self.onMainTabClicked)
        self.layout.addWidget(self.mainTab)

        # Configure manual segment editor effects
        segEnv.self().segmentEditorWidget.self().selectParameterNodeByTag(ThinSectionEnv.SETTING_KEY)
        segEnv.self().segmentEditorWidget.self().configureEffectsForThinSectionEnvironment()

    def onMainTabClicked(self, index):
        if self.lastAccessedWidget != self.mainTab.widget(
            index
        ):  # To avoid calling exit by clicking over the active tab
            self.lastAccessedWidget.exit()
            self.lastAccessedWidget = self.mainTab.widget(index)
            if type(self.lastAccessedWidget) is qt.QTabWidget:
                self.lastAccessedWidget = self.lastAccessedWidget.currentWidget()
            self.lastAccessedWidget.enter()

    def onDataTabClicked(self, index):
        self.lastAccessedWidget.exit()
        self.lastAccessedWidget = self.dataTab.widget(index)
        self.lastAccessedWidget.enter()

    def enter(self) -> None:
        super().enter()
        self.layoutNode = slicer.app.layoutManager().layoutLogic().GetLayoutNode()
        self.previousLayout = self.layoutNode.GetViewArrangement()
        self.layoutNode.SetViewArrangement(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
        self.lastAccessedWidget.enter()

    def exit(self):
        self.lastAccessedWidget.exit()

        # If layout was not changed from red slice, restore to previous one
        if self.layoutNode.GetViewArrangement() == slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView:
            self.layoutNode.SetViewArrangement(self.previousLayout)

    def switchToMultipleImageAnalysis(self):
        self.mainTab.setCurrentWidget(self.multipleImageAnalysisWidget)
