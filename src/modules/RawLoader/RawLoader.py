import os
from pathlib import Path
import qt
from ltrace.slicer_utils import *


class RawLoader(LTracePlugin):
    SETTING_KEY = "RawLoader"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Raw Loader (deprecated)"
        self.parent.categories = ["LTrace Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = RawLoader.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class RawLoaderWidget(LTracePluginWidget):
    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.layout.addWidget(qt.QLabel("<b>RAW Import</b> has been moved to <b>Import</b>."))
        self.layout.addWidget(qt.QLabel(""))
        self.layout.addWidget(qt.QLabel("To import a RAW file:"))
        self.layout.addWidget(qt.QLabel("1. Click on the <b>Import</b> tab (left of this tab)."))
        self.layout.addWidget(qt.QLabel("2. Click <b>Choose file...</b>"))
        self.layout.addWidget(qt.QLabel("3. Select a RAW file."))
        self.layout.addStretch(1)
