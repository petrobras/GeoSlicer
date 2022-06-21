import os
import requests
import enum
import vtk, qt, ctk, slicer
import logging

# -*- extra imports -*-
from ltrace.slicer.helpers import install_git_module, GitImportError, config_module_paths, save_path
from ltrace.slicer_utils import base_version, LTracePlugin, LTracePluginWidget, LTracePluginLogic


#
# ModuleInstaller
#


class SourceType(enum.Enum):
    ZIP = 0
    URL = 1


class ModuleInstaller(LTracePlugin):
    SETTING_KEY = "ModuleInstaller"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Module Installer"
        self.parent.categories = ["LTrace Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["Rafael Arenhart (LTrace Geophysics)"]
        self.parent.helpText = """
Imports a new module from a filder, zip file or git URL.
"""
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = """
This file was originally developed by LTrace Geophysics Solutions.
"""


#
# ModuleInstallerWidget
#


class ModuleInstallerWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)
        self.module_logic = ModuleInstallerLogic()

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Module Instaler source")
        formLayout.addRow(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.selector = ctk.ctkPathLineEdit()
        self.selector.setToolTip("Choose module zip file or git HTTPS URL.")
        self.selector.settingKey = "ModuleInstaller/Source"
        inputFormLayout.addRow("Source:", self.selector)

        self.username = qt.QLineEdit()
        self.username.setToolTip("Input user name for the git repository (optional).")
        inputFormLayout.addRow("User name:", self.username)
        import getpass

        user = str(getpass.getuser()).lower()
        self.username.text = user

        self.userpass = qt.QLineEdit()
        self.userpass.setEchoMode(qt.QLineEdit.Password)
        self.userpass.setToolTip("Input user password for git repository (optional).")
        inputFormLayout.addRow("User password:", self.userpass)

        self.apply_button = qt.QPushButton("Apply")
        self.apply_button.toolTip = "Import the module."
        self.apply_button.enabled = True
        inputFormLayout.addRow("Source:", self.apply_button)
        self.layout.addStretch(1)

        self.apply_button.clicked.connect(self.onApplyButton)

    def cleanup(self):
        pass

    def onSelect(self):
        pass

    def onApplyButton(self):
        path = self.selector.currentPath
        save_path(self.selector)
        user = self.username.text
        user = user if user != "" else None
        password = self.userpass.text
        password = password if password != "" else None
        self.module_logic.run(path, user, password)


#
# ModuleInstallerLogic
#


class ModuleInstallerLogic(LTracePluginLogic):
    def __init__(self, *args, **kwargs):
        LTracePluginLogic.__init__(self, *args, **kwargs)
        geoslicer_version = base_version()

        modules_folders = (
            *(os.path.dirname(slicer.app.launcherExecutableFilePath).split("/")),
            *(("lib\\" + geoslicer_version + "\\qt-scripted-modules").split("\\")),
        )
        self.modules_path = os.path.join(modules_folders[0], os.sep, *modules_folders[1:])

        json_folders = (
            *(os.path.dirname(slicer.app.launcherExecutableFilePath).split("/")),
            *(
                ("lib\\" + geoslicer_version + "\\qt-scripted-modules\\Resources\\json\\WelcomeGeoSlicer.json").split(
                    "\\"
                )
            ),
        )
        self.json_path = os.path.join(json_folders[0], os.sep, *json_folders[1:])

    def run(self, source_string, username=None, password=None):

        source_type = self._check_source_type(source_string)

        try:
            if source_type == SourceType.ZIP:
                self._handle_zip_source(source_string)
            elif source_type == SourceType.URL:
                remote = source_string
                if username is not None and password is not None:
                    remote = source_string.split("@")[-1]
                    remote = remote.split("https://")[-1]
                    remote = f"https://{username}:{password}@{remote}"
                install_git_module(remote)
            else:
                qt.QMessageBox.warning(
                    slicer.util.mainWindow(),
                    "Source is not valid",
                    "Given source for module is neither a zip file nor an accessible git repository.",
                )
                return False

            slicer.modules.CustomizerInstance.set_paths()
            qt.QMessageBox.information(
                slicer.util.mainWindow(),
                "Module installation successful",
                "Please restart GeoSlicer to finish new modules setup.",
            )

        except GitImportError as err:
            slicer.util.errorDisplay(
                "Unable to find a GIT executable. " "Please add a git installation directory to your PATH.",
                "Module installation failed",
            )

    def _check_source_type(self, source_string):

        if os.path.isfile(source_string) and source_string[-4:] == ".zip":
            return SourceType.ZIP
        else:
            return SourceType.URL

    def _handle_zip_source(self, source_string):
        new_module_name = os.path.basename(source_string).split(".")[0]
        new_module_path = os.path.join(self.modules_path, new_module_name)
        slicer.util.extractArchive(source_string, self.modules_path)
        config_module_paths(new_module_name, new_module_path, self.json_path)
