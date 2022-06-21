import ctk
import os
import qt
import slicer

from ltrace.slicer import ui
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from pathlib import Path

import DLISImportLib
from ltrace.slicer import ui
from ImageLogUnwrapImportLib.TomographicUnwrapLoadWidget import TomographicUnwrapLoadWidget


class ImageLogUnwrapImport(LTracePlugin):
    SETTING_KEY = "ImageLogUnwrapImport"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Image Log Import"
        self.parent.categories = ["LTrace Tools"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = ImageLogUnwrapImport.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ImageLogUnwrapImportWidget(LTracePluginWidget):
    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        super().setup()

        tomographicUnwrapWidget = TomographicUnwrapLoadWidget()
        self.layout.addWidget(tomographicUnwrapWidget)


class ImageLogUnwrapImportLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def apply(self, data):
        pass
