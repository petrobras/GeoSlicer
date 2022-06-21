import os
from pathlib import Path
import ctk
import qt
import slicer
from ltrace.slicer_utils import *

# Checks if closed source code is available
try:
    from Test.MicroCTLoaderTest import MicroCTLoaderTest
except ImportError:
    MicroCTLoaderTest = None


class MicroCTLoader(LTracePlugin):
    SETTING_KEY = "MicroCTLoader"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Micro CT Loader"
        self.parent.categories = ["Micro CT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = MicroCTLoader.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


try:
    from Libs.MicroCTLoaderExtendedWidget import MicroCTLoaderExtendedWidget as PluginWidget
except ImportError:
    from Libs.MicroCTLoaderBaseWidget import MicroCTLoaderBaseWidget as PluginWidget


class MicroCTLoaderWidget(PluginWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
