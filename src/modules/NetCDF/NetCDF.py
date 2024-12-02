import os
import qt
import slicer
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.widget.save_netcdf import SaveNetcdfWidget
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
        self.parent.categories = ["Tools", "MicroCT"]
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

        self.import_module = slicer.modules.netcdfloader.createNewWidgetRepresentation()
        self.export_module = slicer.modules.netcdfexport.createNewWidgetRepresentation()
        self.save_module = SaveNetcdfWidget()

        self.main_tab = qt.QTabWidget()
        self.main_tab.addTab(self.import_module, "Import")
        self.main_tab.addTab(self.save_module, "Save")
        self.main_tab.addTab(self.export_module, "Export")

        self.layout.addWidget(self.main_tab)
        self.layout.addStretch(1)


class NetCDFLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
