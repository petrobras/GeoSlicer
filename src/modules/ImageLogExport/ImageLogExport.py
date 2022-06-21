import os

from pathlib import Path
from ltrace.slicer_utils import LTracePlugin


# Checks if closed source code is available
try:
    from Test.ImageLogExportTest import ImageLogExportTest
except ImportError:
    ImageLogExportTest = None  # tests not deployed to final version or closed source


class ImageLogExport(LTracePlugin):
    SETTING_KEY = "ImageLogExport"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Image Log Export"
        self.parent.categories = ["Image Log"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = ImageLogExport.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


try:
    from ImageLogExportLib.widgets.ImageLogExportClosedSourceWidget import (
        ImageLogExportClosedSourceWidget as PluginWidget,
    )

except ImportError:
    from ImageLogExportLib.widgets.ImageLogExportOpenSourceWidget import (
        ImageLogExportOpenSourceWidget as PluginWidget,
    )


class ImageLogExportWidget(PluginWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
