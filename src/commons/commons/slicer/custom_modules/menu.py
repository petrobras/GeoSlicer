import logging
from pathlib import Path

import qt
import slicer

from commons.slicer.custom_modules.logic import CrashRecovery, browseStartDirectory, customModules
from commons.slicer.helpers import svgToQIcon
from commons.slicer.ui import LineSeparator
from commons.slicer.widget.custom_toolbar_buttons import CustomToolButton
from commons.slicer.widget.message_banner import MessageLevel, levelColor
from commons.slicer_utils import getResourcePath

MODULE_MANAGER_NAME = "ModuleManager"


def _iconDir() -> Path:
    return getResourcePath("Icons") / "svg"


def openModuleManager() -> None:
    slicer.util.selectModule(MODULE_MANAGER_NAME)


def chooseModuleFolder(parent) -> str:
    """Ask for a module folder, starting next to the last one added. Returns "" when cancelled."""
    return qt.QFileDialog.getExistingDirectory(parent, "Select a module folder", browseStartDirectory())


def addModuleFolder() -> None:
    """Ask for a module folder and load it."""
    path = chooseModuleFolder(slicer.util.mainWindow())
    if path:
        loadModuleFolder(path)


def loadModuleFolder(path: str) -> None:
    """Register a module folder. Opens the module when the folder holds a single one, otherwise shows the
    result in the module manager."""
    folder = slicer.util.getModuleWidget(MODULE_MANAGER_NAME).addFolder(path)
    module = folder.singleModule() if folder is not None else None
    if module is not None:
        slicer.util.selectModule(module.info.key)
    else:
        openModuleManager()


def crashRecoveryText(recovery: CrashRecovery) -> str:
    names = ", ".join(Path(path).stem for path in recovery.modulePaths)
    return (
        f"GeoSlicer closed unexpectedly last time while loading the custom module {names}, so it was disabled. "
        "You can enable it again in the Module Manager once it is fixed."
    )


def showCrashRecoveryMessage(recovery: CrashRecovery):
    """Tell the user which custom modules were disabled after a crash, without blocking the application."""
    box = qt.QMessageBox(slicer.util.mainWindow())
    box.objectName = "Custom Module Crash Message"
    box.setAttribute(qt.Qt.WA_DeleteOnClose)
    box.setModal(False)
    box.setIcon(qt.QMessageBox.Warning)
    box.setWindowTitle("Custom modules disabled")
    box.setText(crashRecoveryText(recovery))
    openButton = box.addButton("Open Module Manager", qt.QMessageBox.AcceptRole)
    box.addButton(qt.QMessageBox.Close)
    box.buttonClicked.connect(lambda button: openModuleManager() if button == openButton else None)
    box.show()
    return box


def addCustomModulesSection(toolbar) -> None:
    """Append a "My Modules" section, set apart from the built-in modules, to an environment's module toolbar."""
    iconDir = _iconDir()

    toolbar.addWidget(LineSeparator())

    myModulesButton = CustomToolButton(toolbar)
    myModulesButton.objectName = "My Modules Tool Button"
    myModulesButton.setIcon(svgToQIcon(iconDir / "Extensions.svg"))
    myModulesButton.setText("My Modules")
    myModulesButton.setToolTip("Custom modules loaded from your module folders")

    menu = qt.QMenu(myModulesButton)
    # Rebuilt on every show, so folders added in the module manager appear without reloading the environment
    menu.aboutToShow.connect(lambda: _populateMenu(menu))
    myModulesButton.setMenu(menu)
    myModulesButton.setPopupMode(qt.QToolButton.MenuButtonPopup)
    myModulesButton.clicked.connect(lambda _: myModulesButton.showMenu())
    toolbar.addWidget(myModulesButton)

    addButton = CustomToolButton(toolbar)
    addButton.objectName = "Add Module Tool Button"
    accent = levelColor(MessageLevel.SUCCESS)
    addButton.setStyleSheet(f"QToolButton {{ color: {accent}; }}")
    action = qt.QAction(svgToQIcon(iconDir / "FolderPlus.svg", accent), "Add Module", toolbar)
    action.setToolTip("Choose a folder with custom modules to load")
    action.triggered.connect(lambda _: addModuleFolder())
    addButton.setDefaultAction(action)
    toolbar.addWidget(addButton)


def _populateMenu(menu) -> None:
    menu.clear()

    entries = []
    for module in customModules().menuModules():
        slicerModule = getattr(slicer.modules, module.info.key.lower(), None)
        if slicerModule is None:
            logging.warning(f"Custom module {module.info.key} not found in slicer.modules")
            continue
        entries.append((slicerModule.title, slicerModule.icon, module.info.key))

    for title, icon, key in sorted(entries, key=lambda entry: entry[0].lower()):
        action = menu.addAction(icon, title)
        action.triggered.connect(lambda _, name=key: slicer.util.selectModule(name))

    if not entries:
        placeholder = menu.addAction("No custom modules yet")
        placeholder.setEnabled(False)

    menu.addSeparator()
    menu.addAction(svgToQIcon(_iconDir() / "Extensions.svg"), "Manage modules...").triggered.connect(
        lambda _: openModuleManager()
    )
