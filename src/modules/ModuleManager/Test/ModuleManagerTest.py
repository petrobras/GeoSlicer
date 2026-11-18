import os
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

import psutil
import qt
import slicer

from commons.slicer.custom_modules import logic
from commons.slicer.custom_modules.icon import hasDefaultIcon
from commons.slicer.custom_modules.logic import FolderStatus, ModuleStatus, PathOrigin, customModules
from commons.slicer.custom_modules.menu import _populateMenu, loadModuleFolder, showCrashRecoveryMessage
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events
from commons.slicer.widget.message_banner import MessageLevel
from commons.slicer.widget.module_header import ModuleHeader

RESOURCES_PATH = Path(__file__).parent / "Resources"
DUMMY_MODULE_FOLDER_PATH = RESOURCES_PATH / "DummyModule"

COLLECTION_MODULE_SOURCE = """
from commons.slicer_utils import LTracePlugin


class {name}(LTracePlugin):
    SETTING_KEY = "{name}"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "{name}"
        self.parent.categories = ["Tools"]
"""


def expectLoadErrors():
    """Slicer prints the errors of modules that fail to load through sys.excepthook, which fails the test case. Hands
    them to the original hook while loading modules that are broken on purpose."""
    return patch("sys.excepthook", sys._excepthook)


class ModuleManagerTest(LTracePluginTest):
    # Saved and restored as they are, and cleared for each test
    RAW_SETTINGS_KEYS = (
        logic.LAST_FOLDER_SETTINGS_KEY,
        logic.LOAD_ERRORS_SETTINGS_KEY,
    )

    def pre_setup(self):
        settings = slicer.app.userSettings()
        self.__originalUserPaths = logic.getUserPaths()
        self.__originalDisabledPaths = logic.getDisabledModulePaths()
        self.__originalSettings = {key: settings.value(key) for key in self.RAW_SETTINGS_KEYS}
        self.__originalEnvironmentPaths = os.environ.get(logic.ENVIRONMENT_VARIABLE)
        os.environ.pop(logic.ENVIRONMENT_VARIABLE, None)
        logic.setUserPaths([])
        logic._writePathList(logic.DISABLED_SETTINGS_KEY, [])
        for key in self.RAW_SETTINGS_KEYS:
            settings.remove(key)
        # The widget is built from the registry, which still reflects the user's own folders
        customModules().refresh()

    def tear_down(self):
        settings = slicer.app.userSettings()
        logic.setUserPaths(self.__originalUserPaths)
        logic._writePathList(logic.DISABLED_SETTINGS_KEY, self.__originalDisabledPaths)
        for key, value in self.__originalSettings.items():
            if value is None:
                settings.remove(key)
            else:
                settings.setValue(key, value)
        settings.sync()
        if self.__originalEnvironmentPaths is None:
            os.environ.pop(logic.ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[logic.ENVIRONMENT_VARIABLE] = self.__originalEnvironmentPaths
        customModules().refresh()

    def __folderItem(self, path):
        tree = self._module_widget.tree
        for index in range(tree.topLevelItemCount):
            item = tree.topLevelItem(index)
            if Path(item.text(0)) == Path(path):
                return item
        return None

    def __folder(self, path):
        target = logic.normalizePath(path)
        return next(f for f in customModules().folders if logic.normalizePath(f.path) == target)

    def __writeCollection(self):
        """A collection with two modules, at a fixed path so reruns in the same session load the same files."""
        collection = Path(slicer.app.temporaryPath) / "ModuleManagerTest" / "Collection"
        for name in ("DummyCollectionAlpha", "DummyCollectionBeta"):
            moduleDir = collection / name
            moduleDir.mkdir(parents=True, exist_ok=True)
            (moduleDir / f"{name}.py").write_text(COLLECTION_MODULE_SOURCE.format(name=name))
        return collection

    def __moduleItem(self, folderPath, index=0):
        return self.__folderItem(folderPath).child(index)

    def __menuTitles(self):
        menu = qt.QMenu()
        try:
            _populateMenu(menu)
            return [action.text for action in menu.actions()]
        finally:
            menu.delete()

    def __selectedModule(self):
        return slicer.util.moduleSelector().selectedModule

    def __dropOnTree(self, paths):
        """Drag local paths over the folder list and drop them. Returns whether the drop was accepted."""
        mimeData = qt.QMimeData()
        mimeData.setUrls([qt.QUrl.fromLocalFile(str(path)) for path in paths])
        viewport = self._module_widget.tree.viewport()
        position = qt.QPoint(5, 5)

        enterEvent = qt.QDragEnterEvent(position, qt.Qt.CopyAction, mimeData, qt.Qt.LeftButton, qt.Qt.NoModifier)
        qt.QApplication.sendEvent(viewport, enterEvent)
        if not enterEvent.isAccepted():
            return False

        moveEvent = qt.QDragMoveEvent(position, qt.Qt.CopyAction, mimeData, qt.Qt.LeftButton, qt.Qt.NoModifier)
        qt.QApplication.sendEvent(viewport, moveEvent)
        dropEvent = qt.QDropEvent(qt.QPointF(position), qt.Qt.CopyAction, mimeData, qt.Qt.LeftButton, qt.Qt.NoModifier)
        qt.QApplication.sendEvent(viewport, dropEvent)
        process_events()
        return dropEvent.isAccepted()

    def test_drop_module_folder(self):
        self.assertTrue(self.__dropOnTree([DUMMY_MODULE_FOLDER_PATH]), "The folder drop was refused.")

        self.assertIsNotNone(self.__folderItem(DUMMY_MODULE_FOLDER_PATH), "The dropped folder is not listed.")
        self.assertIn("Loaded 1 of 1", self._module_widget.banner.text)
        self.assertEqual(self._module_widget.banner.level, MessageLevel.SUCCESS)

    def test_drop_module_file_and_other_files(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "Archive.zip"
            archive.write_bytes(b"")
            collection = self.__writeCollection()

            dropped = [DUMMY_MODULE_FOLDER_PATH / "DummyModule.py", collection, archive]
            self.assertTrue(self.__dropOnTree(dropped), "The drop was refused.")

            self.assertIsNotNone(self.__folderItem(DUMMY_MODULE_FOLDER_PATH), "The module file's folder was not added.")
            self.assertIsNotNone(self.__folderItem(collection), "The collection was not added.")
            self.assertIsNone(self.__folderItem(archive))
            status = self._module_widget.banner.text
            self.assertIn("Added 2 folder(s) and loaded 3 of 3", status)
            self.assertIn("Ignored Archive.zip", status)
            self.assertEqual(self._module_widget.banner.level, MessageLevel.WARNING)

    def test_drop_without_files_is_refused(self):
        mimeData = qt.QMimeData()
        mimeData.setText("not a folder")
        event = qt.QDragEnterEvent(qt.QPoint(5, 5), qt.Qt.CopyAction, mimeData, qt.Qt.LeftButton, qt.Qt.NoModifier)
        qt.QApplication.sendEvent(self._module_widget.tree.viewport(), event)

        self.assertFalse(event.isAccepted())

    def test_add_module_opens_a_single_module(self):
        slicer.util.selectModule("CustomizedData")
        loadModuleFolder(str(DUMMY_MODULE_FOLDER_PATH))
        process_events()

        self.assertEqual(self.__selectedModule(), "DummyModule")

    def test_add_module_opens_the_manager_for_a_collection(self):
        slicer.util.selectModule("CustomizedData")
        loadModuleFolder(str(self.__writeCollection()))
        process_events()

        self.assertEqual(self.__selectedModule(), "ModuleManager")
        self.assertIn("Loaded 2 of 2", slicer.util.getModuleWidget("ModuleManager").banner.text)

    def test_add_module_opens_the_manager_for_a_folder_without_modules(self):
        with tempfile.TemporaryDirectory() as folder:
            slicer.util.selectModule("CustomizedData")
            loadModuleFolder(folder)
            process_events()

            self.assertEqual(self.__selectedModule(), "ModuleManager")

    def test_disable_and_enable_module(self):
        modulePath = str(DUMMY_MODULE_FOLDER_PATH / "DummyModule.py")
        self._module_widget.addFolder(str(DUMMY_MODULE_FOLDER_PATH))
        process_events()
        self.assertEqual(self.__moduleItem(DUMMY_MODULE_FOLDER_PATH).checkState(0), qt.Qt.Checked)

        self.__moduleItem(DUMMY_MODULE_FOLDER_PATH).setCheckState(0, qt.Qt.Unchecked)
        process_events()

        self.assertIn(logic.normalizePath(modulePath), logic.getDisabledModulePaths())
        item = self.__moduleItem(DUMMY_MODULE_FOLDER_PATH)
        self.assertEqual(item.checkState(0), qt.Qt.Unchecked)
        self.assertEqual(item.text(1), ModuleStatus.DISABLED.value)
        self.assertIn("stays loaded until GeoSlicer is restarted", self._module_widget.banner.text)
        self.assertEqual(self._module_widget.banner.level, MessageLevel.SUCCESS)
        self.assertNotIn("Dummy Module", self.__menuTitles())

        self.__moduleItem(DUMMY_MODULE_FOLDER_PATH).setCheckState(0, qt.Qt.Checked)
        process_events()

        self.assertEqual(logic.getDisabledModulePaths(), [])
        self.assertEqual(self.__moduleItem(DUMMY_MODULE_FOLDER_PATH).text(1), ModuleStatus.LOADED.value)
        self.assertIn("Enabled", self._module_widget.banner.text)
        self.assertIn("Dummy Module", self.__menuTitles())

    def test_enabling_a_disabled_module_loads_it(self):
        # Modules can't be unloaded, so every run needs a module that was never loaded
        name = f"DummyDisabled{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            modulePath = Path(folder) / f"{name}.py"
            modulePath.write_text(COLLECTION_MODULE_SOURCE.format(name=name))
            logic.setModuleEnabled(str(modulePath), False)

            self._module_widget.addFolder(folder)
            process_events()

            self.assertEqual(self.__moduleItem(folder).text(1), ModuleStatus.DISABLED.value)
            self.assertFalse(hasattr(slicer.modules, f"{name}Instance"), "A disabled module was loaded.")

            self.__moduleItem(folder).setCheckState(0, qt.Qt.Checked)
            process_events()

            self.assertTrue(hasattr(slicer.modules, f"{name}Instance"), "Enabling the module did not load it.")
            self.assertEqual(self.__moduleItem(folder).text(1), ModuleStatus.LOADED.value)

    def test_add_module_folder(self):
        self._module_widget.addFolder(str(DUMMY_MODULE_FOLDER_PATH))
        process_events()

        self.assertTrue(hasattr(slicer.modules, "DummyModuleInstance"), "DummyModule was not loaded.")
        self.assertIn(
            logic.normalizePath(DUMMY_MODULE_FOLDER_PATH),
            [logic.normalizePath(p) for p in logic.getUserPaths()],
        )
        self.assertIsNotNone(self.__folderItem(DUMMY_MODULE_FOLDER_PATH), "The folder is not listed.")
        self.assertIn("Loaded 1 of 1", self._module_widget.banner.text)

    def test_folder_picker_starts_next_to_the_last_folder(self):
        self._module_widget.addFolder(str(DUMMY_MODULE_FOLDER_PATH))
        self.assertEqual(Path(logic.browseStartDirectory()), RESOURCES_PATH)

        # Adding a folder that is already registered still moves the picker
        self._module_widget.addFolder(str(self.__writeCollection()))
        self._module_widget.addFolder(str(DUMMY_MODULE_FOLDER_PATH))
        self.assertEqual(Path(logic.browseStartDirectory()), RESOURCES_PATH)

    def test_module_without_an_icon_gets_a_placeholder(self):
        self._module_widget.addFolder(str(DUMMY_MODULE_FOLDER_PATH))
        process_events()

        self.assertFalse(hasDefaultIcon(slicer.modules.dummymodule.icon), "DummyModule kept Slicer's default icon.")

    def test_module_icon_is_kept(self):
        # Modules can't be unloaded, so every run needs a module that was never loaded
        name = f"DummyIcon{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            (Path(folder) / f"{name}.py").write_text(COLLECTION_MODULE_SOURCE.format(name=name))
            iconPath = Path(folder) / "Resources" / "Icons" / f"{name}.png"
            iconPath.parent.mkdir(parents=True)
            pixmap = qt.QPixmap(64, 64)
            pixmap.fill(qt.QColor("#ff8800"))
            pixmap.save(str(iconPath))

            self._module_widget.addFolder(folder)
            process_events()

            size = qt.QSize(64, 64)
            moduleIcon = getattr(slicer.modules, name.lower()).icon.pixmap(size).toImage()
            self.assertEqual(moduleIcon, qt.QIcon(str(iconPath)).pixmap(size).toImage())

    def test_add_collection_folder(self):
        self._module_widget.addFolder(str(RESOURCES_PATH))
        process_events()

        folder = self.__folder(RESOURCES_PATH)
        self.assertEqual(folder.status, FolderStatus.OK)
        self.assertEqual([m.info.key for m in folder.modules], ["DummyModule"])
        self.assertEqual(folder.modules[0].status, ModuleStatus.LOADED)

    def test_add_folder_twice(self):
        self._module_widget.addFolder(str(DUMMY_MODULE_FOLDER_PATH))
        self._module_widget.addFolder(str(DUMMY_MODULE_FOLDER_PATH))
        process_events()

        self.assertEqual(len(logic.getUserPaths()), 1)
        self.assertIn("already registered", self._module_widget.banner.text)
        self.assertEqual(self._module_widget.banner.level, MessageLevel.INFO)

    def test_add_folder_inside_a_registered_folder(self):
        self._module_widget.addFolder(str(RESOURCES_PATH))
        self._module_widget.addFolder(str(DUMMY_MODULE_FOLDER_PATH))
        # The Add Module button opens the manager afterwards, which rebuilds the list
        self._module_widget.enter()
        process_events()

        self.assertEqual([Path(p) for p in logic.getUserPaths()], [RESOURCES_PATH])
        self.assertIsNone(self.__folderItem(DUMMY_MODULE_FOLDER_PATH), "The module is listed twice.")
        banner = self._module_widget.banner
        self.assertIn(f"Dummy Module is already loaded from {RESOURCES_PATH}", banner.text)
        self.assertEqual(banner.level, MessageLevel.INFO)
        self.assertIs(self._module_widget.tree.currentItem(), self.__moduleItem(RESOURCES_PATH))

    def test_add_folder_containing_a_registered_folder(self):
        self._module_widget.addFolder(str(DUMMY_MODULE_FOLDER_PATH))
        self._module_widget.addFolder(str(RESOURCES_PATH))
        process_events()

        # The collection replaces the module folder, so the module is listed once
        self.assertEqual([Path(p) for p in logic.getUserPaths()], [RESOURCES_PATH])
        self.assertIsNone(self.__folderItem(DUMMY_MODULE_FOLDER_PATH))
        self.assertEqual(self.__moduleItem(RESOURCES_PATH).text(1), ModuleStatus.LOADED.value)
        banner = self._module_widget.banner
        self.assertIn(f"Removed {DUMMY_MODULE_FOLDER_PATH} from the list", banner.text)
        self.assertEqual(banner.level, MessageLevel.SUCCESS)

    def test_missing_folder(self):
        missingPath = RESOURCES_PATH / "ThisFolderDoesNotExist"
        self._module_widget.addFolder(str(missingPath))
        process_events()

        item = self.__folderItem(missingPath)
        self.assertIsNotNone(item)
        self.assertEqual(item.text(1), FolderStatus.MISSING.value)

    def test_remove_folder(self):
        self._module_widget.addFolder(str(DUMMY_MODULE_FOLDER_PATH))
        process_events()

        self._module_widget.tree.setCurrentItem(self.__folderItem(DUMMY_MODULE_FOLDER_PATH))
        process_events()
        self.assertTrue(self._module_widget.removeFolderButton.enabled)

        self._module_widget.removeFolderButton.click()
        process_events()

        self.assertEqual(logic.getUserPaths(), [])
        self.assertIsNone(self.__folderItem(DUMMY_MODULE_FOLDER_PATH))

    def test_environment_folder(self):
        os.environ[logic.ENVIRONMENT_VARIABLE] = str(DUMMY_MODULE_FOLDER_PATH)
        self._module_widget.refresh()
        process_events()

        folder = self.__folder(DUMMY_MODULE_FOLDER_PATH)
        self.assertEqual(folder.origin, PathOrigin.ENVIRONMENT)
        self.assertEqual(folder.modules[0].status, ModuleStatus.LOADED)

        # Administrator folders can't be removed by the user
        self._module_widget.tree.setCurrentItem(self.__folderItem(DUMMY_MODULE_FOLDER_PATH))
        process_events()
        self.assertFalse(self._module_widget.removeFolderButton.enabled)

        # Adding the same folder as a user folder is a no-op
        self._module_widget.addFolder(str(DUMMY_MODULE_FOLDER_PATH))
        self.assertEqual(logic.getUserPaths(), [])

    def test_my_modules_menu(self):
        self._module_widget.addFolder(str(DUMMY_MODULE_FOLDER_PATH))
        process_events()

        menu = qt.QMenu()
        try:
            _populateMenu(menu)
            titles = [action.text for action in menu.actions()]
        finally:
            menu.delete()

        self.assertIn("Dummy Module", titles)
        self.assertNotIn("Add module folder...", titles)
        self.assertIn("Manage modules...", titles)

    def test_folder_with_only_a_zip(self):
        with tempfile.TemporaryDirectory() as folder:
            with zipfile.ZipFile(Path(folder) / "DummyModule.zip", "w") as archive:
                archive.write(DUMMY_MODULE_FOLDER_PATH / "DummyModule.py", "DummyModule/DummyModule.py")

            self._module_widget.addFolder(folder)
            process_events()

            self.assertEqual(self.__folder(folder).status, FolderStatus.EMPTY)
            self.assertIn("Extract the zip first", self._module_widget.banner.text)
            self.assertEqual(self._module_widget.banner.level, MessageLevel.WARNING)

    def __writeBrokenModules(self, folder):
        """A healthy module plus one per kind of error. Modules can't be unloaded, so every run uses new names."""
        suffix = uuid.uuid4().hex[:8]
        sources = {
            f"Healthy{suffix}": COLLECTION_MODULE_SOURCE,
            f"ImportError{suffix}": "raise RuntimeError('broken on import')\n" + COLLECTION_MODULE_SOURCE,
            f"InitError{suffix}": COLLECTION_MODULE_SOURCE + "        raise RuntimeError('broken in init')\n",
            f"SyntaxError{suffix}": COLLECTION_MODULE_SOURCE + "        if True\n            pass\n",
            f"NoClass{suffix}": "print('no module here')\n",
        }
        names = {}
        for name, source in sources.items():
            moduleDir = Path(folder) / name
            moduleDir.mkdir()
            (moduleDir / f"{name}.py").write_text(source.format(name=name))
            names[name[: -len(suffix)]] = name
        return names

    def __moduleItemByKey(self, folderPath, key):
        folderItem = self.__folderItem(folderPath)
        for index in range(folderItem.childCount()):
            if Path(folderItem.child(index).toolTip(0)).stem == key:
                return folderItem.child(index)
        return None

    def test_broken_modules_are_reported_and_skipped(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            names = self.__writeBrokenModules(folder)

            with expectLoadErrors():
                self._module_widget.addFolder(folder)
                process_events()

            modules = {m.info.key: m for m in self.__folder(folder).modules}
            self.assertEqual(modules[names["Healthy"]].status, ModuleStatus.LOADED)
            for kind in ("ImportError", "InitError"):
                module = modules[names[kind]]
                self.assertEqual(module.status, ModuleStatus.FAILED, kind)
                self.assertFalse(module.enabled, f"{kind} was not disabled.")
                self.assertIn("RuntimeError: broken", module.message)
                self.assertIn("Traceback", module.details)
            self.assertEqual(modules[names["SyntaxError"]].status, ModuleStatus.INVALID)
            self.assertIn("Syntax error on line", modules[names["SyntaxError"]].message)
            self.assertEqual(modules[names["NoClass"]].status, ModuleStatus.INVALID)
            self.assertIn("No class named", modules[names["NoClass"]].message)

            self.assertEqual(len(logic.getDisabledModulePaths()), 2)
            self.assertEqual(len(logic.getLoadErrors()), 2)
            self.assertFalse(hasattr(slicer.modules, f"{names['ImportError']}Instance"))

            banner = self._module_widget.banner
            self.assertIn("Loaded 1 of 5", banner.text)
            self.assertIn("4 modules could not be loaded", banner.text)
            self.assertEqual(banner.level, MessageLevel.WARNING)

            item = self.__moduleItemByKey(folder, names["InitError"])
            self.assertEqual(item.text(1), ModuleStatus.FAILED.value)
            self.assertEqual(item.checkState(0), qt.Qt.Unchecked)
            self.assertFalse(item.icon(1).isNull(), "Modules with errors should show a warning icon.")
            self.assertTrue(self.__moduleItemByKey(folder, names["Healthy"]).icon(1).isNull())

            # The first module with an error is selected, showing its traceback below the list
            self.assertFalse(self._module_widget.errorPanel.isHidden())
            self.assertIn("RuntimeError: broken", self._module_widget.errorTitle.text)
            self.assertIn("Traceback", self._module_widget.errorDetails.toPlainText())

            self._module_widget.tree.setCurrentItem(self.__moduleItemByKey(folder, names["NoClass"]))
            process_events()
            self.assertIn("No class named", self._module_widget.errorTitle.text)
            self.assertTrue(self._module_widget.errorDetails.isHidden(), "There is no traceback to show.")

            self._module_widget.tree.setCurrentItem(self.__moduleItemByKey(folder, names["Healthy"]))
            process_events()
            self.assertTrue(self._module_widget.errorPanel.isHidden())

    def test_fixed_modules_load_again(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            names = self.__writeBrokenModules(folder)
            with expectLoadErrors():
                self._module_widget.addFolder(folder)
                process_events()

            initError = Path(folder) / names["InitError"] / f"{names['InitError']}.py"
            initError.write_text(COLLECTION_MODULE_SOURCE.format(name=names["InitError"]))
            syntaxError = Path(folder) / names["SyntaxError"] / f"{names['SyntaxError']}.py"
            syntaxError.write_text(COLLECTION_MODULE_SOURCE.format(name=names["SyntaxError"]))

            # A module that failed to load is retried by checking it again
            self.__moduleItemByKey(folder, names["InitError"]).setCheckState(0, qt.Qt.Checked)
            process_events()
            self.assertEqual(self.__moduleItemByKey(folder, names["InitError"]).text(1), ModuleStatus.LOADED.value)
            self.assertIn("Enabled", self._module_widget.banner.text)
            self.assertEqual(len(logic.getLoadErrors()), 1)

            # Retrying a module that is still broken disables it again
            with expectLoadErrors():
                self.__moduleItemByKey(folder, names["ImportError"]).setCheckState(0, qt.Qt.Checked)
                process_events()
            self.assertEqual(self.__moduleItemByKey(folder, names["ImportError"]).checkState(0), qt.Qt.Unchecked)
            self.assertIn("failed to load again", self._module_widget.banner.text)
            self.assertEqual(self._module_widget.banner.level, MessageLevel.ERROR)

            # An invalid file is checked again on every scan
            self._module_widget.rescanButton.click()
            process_events()
            self.assertEqual(self.__moduleItemByKey(folder, names["SyntaxError"]).text(1), ModuleStatus.LOADED.value)

    def test_module_that_crashed_is_disabled(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            name = f"DummyCrash{uuid.uuid4().hex[:8]}"
            moduleDir = Path(folder) / name
            moduleDir.mkdir()
            (moduleDir / f"{name}.py").write_text(COLLECTION_MODULE_SOURCE.format(name=name))
            # What a GeoSlicer that crashed while loading the module leaves behind, named after a PID above every
            # running process
            marker = logic._loadingMarkersPath() / f"{max(psutil.pids()) + 4}.txt"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(str(moduleDir / f"{name}.py"), encoding="utf-8")
            try:
                recovery = logic.recoverFromCrash()
            finally:
                # A marker left behind would disable the module in the next real start
                wasTaken = not marker.exists()
                marker.unlink(missing_ok=True)
            self._module_widget.addFolder(folder)
            process_events()

            self.assertIsNotNone(recovery)
            self.assertTrue(wasTaken, "The marker of the crashed load was not removed.")
            module = self.__folder(folder).modules[0]
            self.assertEqual(module.status, ModuleStatus.FAILED)
            self.assertEqual(module.message, logic.CRASH_MESSAGE)
            self.assertFalse(hasattr(slicer.modules, f"{name}Instance"), "The module that crashed was loaded.")
            self.assertIn(logic.CRASH_MESSAGE, self._module_widget.errorTitle.text)

    def test_crash_recovery_message(self):
        recovery = logic.CrashRecovery([str(Path("modules") / "Foo" / "Foo.py")])
        slicer.util.selectModule("CustomizedData")
        box = showCrashRecoveryMessage(recovery)
        process_events()

        self.assertTrue(box.visible)
        self.assertFalse(box.isModal(), "The message must not block GeoSlicer while it starts.")
        self.assertIn("custom module Foo", box.text)
        openButton = next(button for button in box.buttons() if button.text == "Open Module Manager")
        openButton.click()
        process_events()
        self.assertEqual(self.__selectedModule(), "ModuleManager")

    def test_module_header_dev_tools(self):
        self._module_widget.addFolder(str(DUMMY_MODULE_FOLDER_PATH))
        process_events()

        header = ModuleHeader()
        try:
            header.update("Dummy Module", "", "DummyModule")
            self.assertFalse(header.devTools.isHidden(), "Custom modules should show the dev tools.")

            header.devTools.reloadButton.click()
            process_events()
            moduleWidget = slicer.util.getModuleWidget("DummyModule")
            self.assertIsNotNone(moduleWidget)

            # Don't launch an editor during the test, just check the button reaches the module's own Edit action
            edited = []
            moduleWidget.onEditSource = lambda: edited.append(True)
            try:
                header.devTools.editButton.click()
                process_events()
            finally:
                del moduleWidget.onEditSource
            self.assertEqual(edited, [True])

            header.update("Data", "", "CustomizedData")
            self.assertTrue(header.devTools.isHidden(), "Built-in modules should not show the dev tools.")
        finally:
            header.delete()
