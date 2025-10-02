import os
import qt
import slicer

from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.widget.save_netcdf import SaveNetcdfWidget
from ltrace.slicer.node_attributes import NodeEnvironment
from pathlib import Path
from typing import Union

# Checks if closed source code is available
try:
    from Test.NetCDFTest import NetCDFTest
except ImportError:
    NetCDFTest = None


class NetCDF(LTracePlugin):
    SETTING_KEY = "NetCDF"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "NetCDF"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.setHelpUrl("Volumes/MoreTools/NetCDF/Introduction.html", NodeEnvironment.MICRO_CT)
        self.setHelpUrl("ThinSection/MoreTools/NetCDF/Introduction.html", NodeEnvironment.THIN_SECTION)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class NetCDFWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        self.importModule = slicer.modules.netcdfloader.createNewWidgetRepresentation()
        self.exportModule = slicer.modules.netcdfexport.createNewWidgetRepresentation()
        self.saveModule = SaveNetcdfWidget()

        self.mainTab = qt.QTabWidget()
        self.mainTab.addTab(self.importModule, "Import")
        self.mainTab.addTab(self.saveModule, "Save")
        self.mainTab.addTab(self.exportModule, "Export")

        self.layout.addWidget(self.mainTab)
        self.layout.addStretch(1)

    def selectTab(self, tabName: str) -> Union[qt.QWidget, None]:
        for i in range(self.mainTab.count):
            if self.mainTab.tabText(i) != tabName:
                continue

            self.mainTab.setCurrentIndex(i)
            widget = self.mainTab.currentWidget()
            if hasattr(self.mainTab.currentWidget(), "self"):
                widget = self.mainTab.currentWidget().self()
            return widget

        return


class NetCDFLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
