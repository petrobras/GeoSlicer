import os
from pathlib import Path

from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic

try:
    from ReportLib.StreamlitServer import StreamlitServer, is_server_running
    from ReportLib.ReportForm import ReportForm
    from ReportLib.ReportLogic import ReportLogic
except ImportError:
    StreamlitServer = None

try:
    from Test.PNMReportTest import PNMReportTest
except ImportError:
    PNMReportTest = None


class PNMReport(LTracePlugin):
    SETTING_KEY = "PNMReport"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "PNMReport"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = PNMReport.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PNMReportWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)


class PNMReportLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
