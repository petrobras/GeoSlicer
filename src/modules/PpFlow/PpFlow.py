import os
from pathlib import Path

from ltrace.flow.thin_section import ppFlowWidget
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, getResourcePath


try:
    from Test.PpFlowTest import PpFlowTest
except ImportError:
    PpFlowTest = None  # tests not deployed to final version or closed source


class PpFlow(LTracePlugin):
    SETTING_KEY = "PpFlow"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "PP Flow"
        self.parent.categories = ["Tools", "Thin Section"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = (
            f"file:///{(getResourcePath('manual') / 'Modules/Thin_section/Fluxo%20PP.html').as_posix()}"
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PpFlowWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.flowWidget = ppFlowWidget()
        self.layout.addWidget(self.flowWidget)
        self.layout.addStretch(1)

    def enter(self):
        self.flowWidget.enter()

    def exit(self):
        self.flowWidget.exit()
