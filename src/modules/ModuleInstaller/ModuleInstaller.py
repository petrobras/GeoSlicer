import shutil
from pathlib import Path

import ctk
import qt
import slicer

from ltrace.slicer.module_utils import loadModules, ModuleInfo
from ltrace.slicer_utils import externalModulesPath, LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer import helpers


try:
    from Test.ModuleInstallerTest import ModuleInstallerTest
except ImportError:
    ModuleInstallerTest = None


class ModuleInstaller(LTracePlugin):
    SETTING_KEY = "ModuleInstaller"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Module Installer"
        self.parent.categories = ["Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = """
Imports a new module from a folder or zip file.
"""
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = """
This file was originally developed by LTrace Geophysics Solutions.
"""


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
        inputCollapsibleButton.setText("Module Installer Source")
        formLayout.addRow(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.selector = ctk.ctkPathLineEdit()
        self.selector.setToolTip("Choose module zip file or folder.")
        self.selector.settingKey = "ModuleInstaller/Source"
        self.selector.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Dirs
        inputFormLayout.addRow("Source:", self.selector)

        self.apply_button = qt.QPushButton("Apply")
        self.apply_button.toolTip = "Import the module."
        self.apply_button.enabled = True
        inputFormLayout.addRow(self.apply_button)
        self.layout.addStretch(1)

        self.apply_button.clicked.connect(self.onApplyButton)

    def onApplyButton(self):
        path = self.selector.currentPath
        if not path:
            slicer.util.warningDisplay("Please select a source file or folder.")
            return

        helpers.save_path(self.selector)
        self.module_logic.run(path)


class ModuleInstallerLogic(LTracePluginLogic):
    def __init__(self, *args, **kwargs):
        LTracePluginLogic.__init__(self, *args, **kwargs)
        self.modules_path = externalModulesPath()

    def run(self, path):
        try:
            modules_to_register = []
            path = Path(path)
            if path.is_file():
                modules_to_register = self._handle_zip_source(path)
            elif path.is_dir():
                modules_to_register = self._handle_folder_source(path)
            else:
                slicer.util.warningDisplay(
                    "The provided source is not a valid zip file or folder.",
                    "Invalid Source",
                )
                return False

            if modules_to_register:
                loadModules(modules_to_register, permanent=True)
                module_manager = slicer.modules.AppContextInstance.modules

                # Add modules to search so it works before a restart
                module_manager.addModules(modules_to_register)
                n_modules = len(modules_to_register)
                prefix = "Module" if n_modules == 1 else f"{n_modules} modules"
                slicer.util.infoDisplay(
                    f"{prefix} successfully installed and loaded into the current session.\nUse the Module Search tool (ctrl+F) to find modules.",
                    "Installation Complete",
                )
            return True

        except Exception as e:
            slicer.util.errorDisplay(
                f"An unexpected error occurred during installation: {e}",
                "Module Installation Failed",
            )
            raise e

    def _handle_zip_source(self, source_string):
        slicer.util.extractArchive(str(source_string), str(self.modules_path))

        new_module_dir_name = Path(source_string).stem
        new_module_path = self.modules_path / new_module_dir_name

        if not new_module_path.exists():
            new_module_path = self.modules_path

        modules = ModuleInfo.findModules(str(new_module_path), depth=2)
        if not modules:
            raise RuntimeError(f"No valid Slicer modules found in {source_string}")

        return modules

    def _handle_folder_source(self, source_string):
        source_path = Path(source_string)
        new_module_dir_name = source_path.name
        new_module_path = self.modules_path / new_module_dir_name

        if new_module_path.exists():
            shutil.rmtree(new_module_path)

        shutil.copytree(source_path, new_module_path)

        modules = ModuleInfo.findModules(str(new_module_path), depth=2)
        if not modules:
            raise RuntimeError(f"No valid Slicer modules found in {source_string}")

        return modules
