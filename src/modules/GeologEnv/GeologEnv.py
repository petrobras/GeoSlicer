import os
import qt
from pathlib import Path

import GeologLib
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic

try:
    from Test.GeologEnvTest import GeologEnvTest
except ImportError:
    GeologEnvTest = None  # tests not deployed to final version or closed source


class GeologEnv(LTracePlugin):
    SETTING_KEY = "GeologEnv"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Geolog Integration"
        self.parent.categories = ["Tools", "Multiscale"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.set_manual_path("Modules/Multiscale/GeologEnv.html")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class GeologEnvWidget(LTracePluginWidget):

    GEOLOG_DIRECTORY = "geologDirectory"
    PYTHON_DIRECTORY = "pythonDirectory"
    PROJECTS_DIRECTORY = "projectsDirectory"

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.mainTab = qt.QTabWidget()

        geologImportWidget = GeologLib.GeologImportWidget()
        self.mainTab.addTab(geologImportWidget, "Import from Geolog")

        geologExportWidget = GeologLib.GeologExportWidget()
        self.mainTab.addTab(geologExportWidget, "Export to Geolog")

        geologImportWidget.signalGeologDataFetched.connect(
            lambda instalationPath, projectsPath, project, geologData: self._updateConnectWidget(
                instalationPath, projectsPath, project, geologData, geologExportWidget
            )
        )
        geologExportWidget.signalGeologDataFetched.connect(
            lambda instalationPath, projectsPath, project, geologData: self._updateConnectWidget(
                instalationPath, projectsPath, project, geologData, geologImportWidget
            )
        )

        self.layout.addWidget(self.mainTab)
        self._loadSettings(geologImportWidget, geologExportWidget)

    def _updateConnectWidget(self, geologPath, projectsPath, project, geologData, widget):
        widget.geologConnectWidget.populateFields(geologPath, projectsPath, project)
        widget.onGeologDataFetched(geologData)
        self._saveSettings(geologPath, projectsPath)

    def _saveSettings(self, geologPath, projectsPath):
        GeologEnv.set_setting(self.GEOLOG_DIRECTORY, geologPath)
        GeologEnv.set_setting(self.PROJECTS_DIRECTORY, projectsPath)

    def _loadSettings(self, importWidget, exportWidget):
        geologPath = GeologEnv.get_setting(self.GEOLOG_DIRECTORY, default=str(Path.home()))
        projectsPath = GeologEnv.get_setting(self.PROJECTS_DIRECTORY, default=str(Path.home()))

        importWidget.geologConnectWidget.populateFields(geologPath, projectsPath)
        exportWidget.geologConnectWidget.populateFields(geologPath, projectsPath)


class GeologEnvLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def apply(self, data):
        pass
