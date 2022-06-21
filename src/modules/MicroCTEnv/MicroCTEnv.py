import os
from pathlib import Path

import qt
import slicer
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget

from CTAutoRegistration import CTAutoRegistration
from CustomizedCropVolume import CustomizedCropVolume
from CustomizedData import CustomizedData
from FilteringTools import FilteringTools
from MicroCTLoader import MicroCTLoader
from MicroCTTransforms import MicroCTTransforms
from RawLoader import RawLoader
from SegmentationEnv import SegmentationEnv
from CustomResampleScalarVolume import CustomResampleScalarVolume
from PoreNetworkEnv import PoreNetworkEnv
from ShadingCorrection import ShadingCorrection
from MultiScale import MultiScale
from MultiscalePostProcessing import MultiscalePostProcessing

# Checks if closed source code is available
try:
    from MicrotomRemote import MicrotomRemote
except ImportError:
    MicrotomRemote = None


class MicroCTEnv(LTracePlugin):
    SETTING_KEY = "MicroCTEnv"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Micro CT Environment"
        self.parent.categories = ["Environments"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = (
            MicroCTEnv.help()
            + CustomizedData.help()
            + MicroCTLoader.help()
            + RawLoader.help()
            + CustomizedCropVolume.help()
            + FilteringTools.help()
            + ShadingCorrection.help()
            + MicroCTTransforms.help()
            + CTAutoRegistration.help()
            + SegmentationEnv.help()
            + ((MicrotomRemote.help() + PoreNetworkEnv.help()) if MicrotomRemote else "" + PoreNetworkEnv.help())
            + MultiScale.help()
            + MultiscalePostProcessing.help()
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MicroCTEnvWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)
        self.mainTab = qt.QTabWidget()

        dataTab = qt.QTabWidget()
        dataTab.addTab(slicer.modules.customizeddata.createNewWidgetRepresentation(), "Explorer")
        dataTab.addTab(slicer.modules.microctloader.createNewWidgetRepresentation(), "Import")
        dataTab.addTab(slicer.modules.rawloader.createNewWidgetRepresentation(), "RAW import")
        dataTab.addTab(slicer.modules.microctexport.createNewWidgetRepresentation(), "Export")

        self.mainTab.addTab(dataTab, "Data")
        self.mainTab.addTab(slicer.modules.customizedcropvolume.createNewWidgetRepresentation(), "Crop")
        self.mainTab.addTab(slicer.modules.filteringtools.createNewWidgetRepresentation(), "Filtering Tools")

        # Registration sub tab
        self.transformTab = qt.QTabWidget()
        self.transformTab.addTab(
            slicer.modules.customresamplescalarvolume.createNewWidgetRepresentation(), "Resampling"
        )
        self.transformTab.addTab(slicer.modules.microcttransforms.createNewWidgetRepresentation(), "Manual Register")
        self.transformTab.addTab(slicer.modules.ctautoregistration.createNewWidgetRepresentation(), "Auto Register")
        self.transformTab.tabBarClicked.connect(self.onTransformTabClicked)
        self.mainTab.addTab(self.transformTab, "Transforms")

        # Segmentation sub tab
        self.segmentationEnv = slicer.modules.microctsegmentationenv.createNewWidgetRepresentation()
        self.segmentationEnv.self().segmentEditorWidget.self().selectParameterNodeByTag(MicroCTEnv.SETTING_KEY)
        self.mainTab.addTab(self.segmentationEnv, "Segmentation")

        # Simulation sub tab
        self.simulationTab = qt.QTabWidget()
        if MicrotomRemote:
            self.simulationTab.addTab(slicer.modules.microtomremote.createNewWidgetRepresentation(), "Microtom")
        self.simulationTab.addTab(slicer.modules.porenetworkenv.createNewWidgetRepresentation(), "Pore Network")
        self.mainTab.addTab(self.simulationTab, "Simulation")

        # Multiscale sub tab
        self.multiscaleTab = qt.QTabWidget()
        self.multiscaleTab.addTab(slicer.modules.multiscale.createNewWidgetRepresentation(), "Image generation")
        self.multiscaleTab.addTab(
            slicer.modules.multiscalepostprocessing.createNewWidgetRepresentation(),
            "Post-processing",
        )
        self.mainTab.addTab(self.multiscaleTab, "Multiscale")

        self.lastAccessedWidget = dataTab.widget(0)

        self.mainTab.tabBarClicked.connect(self.onMainTabClicked)
        self.layout.addWidget(self.mainTab)

    def onMainTabClicked(self, index):
        self.lastAccessedWidget.exit()
        self.lastAccessedWidget = self.mainTab.widget(index)
        if type(self.lastAccessedWidget) is qt.QTabWidget:
            self.lastAccessedWidget = self.lastAccessedWidget.currentWidget()
        self.lastAccessedWidget.enter()

    def onTransformTabClicked(self, index):
        self.lastAccessedWidget.exit()
        self.lastAccessedWidget = self.transformTab.widget(index)
        self.lastAccessedWidget.enter()

    def enter(self) -> None:
        super().enter()
        self.lastAccessedWidget.enter()

    def exit(self):
        self.lastAccessedWidget.exit()