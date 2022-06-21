import os
import qt
import slicer
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from pathlib import Path

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
        self.parent.categories = ["LTrace Tools"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = NetCDF.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class NetCDFWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        main_tab = qt.QTabWidget()
        main_tab.addTab(slicer.modules.netcdfloader.createNewWidgetRepresentation(), "Import")
        main_tab.addTab(slicer.modules.netcdfexport.createNewWidgetRepresentation(), "Export")
        self.layout.addWidget(main_tab)
        self.layout.addStretch(1)


class NetCDFLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
