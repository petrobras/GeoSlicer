import os
import vtk, qt, ctk, slicer
from pathlib import Path

from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, LTracePluginTest

from PoreNetworkExtractor import PoreNetworkExtractor
from PoreNetworkSimulation import PoreNetworkSimulation
from PoreNetworkVisualization import PoreNetworkVisualization
from PoreNetworkProduction import PoreNetworkProduction
from PoreNetworkCompare import PoreNetworkCompare


#
# PoreNetworkEnv
#
class PoreNetworkEnv(LTracePlugin):
    SETTING_KEY = "PoreNetworkEnv"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "PoreNetworkEnv"
        self.parent.categories = []
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = (
            PoreNetworkSimulation.help()
            + PoreNetworkExtractor.help()
            + PoreNetworkVisualization.help()
            + PoreNetworkProduction.help()
            + PoreNetworkCompare.help()
        )

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

        htmlHelp += "\n".join(
            [
                PoreNetworkExtractor.help(),
                PoreNetworkSimulation.help(),
                PoreNetworkVisualization.help(),
                PoreNetworkProduction.help(),
                PoreNetworkCompare.help(),
            ]
        )

        return htmlHelp


#
# PoreNetworkEnvWidget
#
class PoreNetworkEnvWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)
        self.mainTab = qt.QTabWidget()

        for module, name in (
            (slicer.modules.segmentinspector, "Inspector"),
            (slicer.modules.porenetworkextractor, "Extraction"),
            (slicer.modules.porenetworksimulation, "Simulation"),
            (slicer.modules.porenetworkvisualization, "Cycles Visualization"),
            (slicer.modules.porenetworkproduction, "Production Prediction"),
            (slicer.modules.porenetworkkreleda, "Krel EDA"),
            (slicer.modules.porenetworkcompare, "Compare Models"),
        ):
            self.mainTab.addTab(module.createNewWidgetRepresentation(), name)

        self.layout.addWidget(self.mainTab)
