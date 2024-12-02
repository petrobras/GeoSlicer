import os
import qt

from pathlib import Path
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, slicer_is_in_developer_mode


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
        self.parent.categories = ["ImageLog", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = ImageLogExport.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


if slicer_is_in_developer_mode():
    try:
        from ImageLogExportLib.widgets.ImageLogExportClosedSourceWidget import ImageLogExportClosedSourceWidget
    except ImportError:
        ImageLogExportClosedSourceWidget = lambda: None
    finally:
        from ImageLogExportLib.widgets.ImageLogExportOpenSourceWidget import ImageLogExportOpenSourceWidget

    class ImageLogExportWidget(LTracePluginWidget):
        def setup(self):
            super().setup()
            mainTab = qt.QTabWidget()
            self.versions = {}
            self.versions["open"] = (ImageLogExportOpenSourceWidget(), "Open")
            self.versions["closed"] = (ImageLogExportClosedSourceWidget(), "Closed")

            for _, (widget, name) in self.versions.items():
                mainTab.addTab(widget, name)

            self.layout.addWidget(qt.QLabel("Developer mode is enabled. Two versions of this module are shown:"))
            self.layout.addWidget(mainTab)

else:
    try:
        from ImageLogExportLib.widgets.ImageLogExportClosedSourceWidget import (
            ImageLogExportClosedSourceWidget as PluginWidget,
        )

    except ImportError:
        from ImageLogExportLib.widgets.ImageLogExportOpenSourceWidget import (
            ImageLogExportOpenSourceWidget as PluginWidget,
        )

    class ImageLogExportWidget(LTracePluginWidget):
        def setup(self):
            super().setup()
            self.layout.addWidget(PluginWidget())
