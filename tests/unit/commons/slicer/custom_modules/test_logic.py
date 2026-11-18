import os
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from commons.slicer.custom_modules import logic
from commons.slicer.custom_modules.logic import (
    CustomModule,
    CustomModuleRegistry,
    FolderStatus,
    ModuleFolder,
    ModuleStatus,
    PathOrigin,
    parsePathList,
)
from commons.slicer.module_info import ModuleInfo

MODULE_SOURCE = """
from commons.slicer_utils import LTracePlugin


class {name}(LTracePlugin):
    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.categories = ["Tools"]
"""


class FakeSettings:
    def __init__(self, path):
        self.values = {}
        self.path = path

    def fileName(self):
        return str(self.path)

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        pass


def writeModule(folder, name):
    moduleDir = folder / name
    moduleDir.mkdir(parents=True)
    (moduleDir / f"{name}.py").write_text(MODULE_SOURCE.format(name=name))
    return moduleDir


@pytest.fixture
def settings(monkeypatch, tmp_path_factory):
    fake = FakeSettings(tmp_path_factory.mktemp("settings") / "GeoSlicer.ini")
    monkeypatch.setattr(logic.slicer.app, "userSettings", lambda: fake)
    monkeypatch.delenv(logic.ENVIRONMENT_VARIABLE, raising=False)
    return fake


@pytest.fixture
def slicerModules(monkeypatch):
    """Fake module factory and loader: every module passed to loadModules loads successfully."""
    registered = set()
    loadedBatches = []

    factory = MagicMock()
    factory.isRegistered.side_effect = lambda key: key in registered
    monkeypatch.setattr(logic.slicer.app, "moduleManager", lambda: SimpleNamespace(factoryManager=lambda: factory))

    appContext = SimpleNamespace(modules=MagicMock(availableModules={"Segmenter": object()}))
    modules = SimpleNamespace(AppContextInstance=appContext)
    monkeypatch.setattr(logic.slicer, "modules", modules)
    monkeypatch.setattr(logic, "usePlaceholderIconIfMissing", lambda slicerModule: None)

    def loadModules(infos):
        for info in infos:
            registered.add(info.key)
            setattr(modules, info.key.lower(), SimpleNamespace())
            info.loaded = True
        loadedBatches.append([info.key for info in infos])

    monkeypatch.setattr(logic, "loadModules", loadModules)
    return SimpleNamespace(registered=registered, loadedBatches=loadedBatches, appContext=appContext)


class TestPaths:
    def test_parse_path_list(self):
        value = os.pathsep.join(["/a", " /b ", "", "/c"])
        assert parsePathList(value) == ["/a", "/b", "/c"]
        assert parsePathList(None) == []
        assert parsePathList("") == []

    @pytest.mark.parametrize("stored, expected", [(None, []), ("/a", ["/a"]), (("/a", "/b"), ["/a", "/b"])])
    def test_user_paths_from_settings(self, settings, stored, expected):
        settings.values[logic.SETTINGS_KEY] = stored
        assert logic.getUserPaths() == expected

    def test_add_and_remove_user_path(self, settings, tmp_path):
        assert logic.addUserPath(str(tmp_path))
        assert not logic.addUserPath(str(tmp_path / "." / ""))  # same folder, different spelling
        assert logic.getUserPaths() == [str(tmp_path)]

        assert logic.removeUserPath(str(tmp_path))
        assert not logic.removeUserPath(str(tmp_path))
        assert logic.getUserPaths() == []

    def test_add_path_already_set_by_environment(self, settings, monkeypatch, tmp_path):
        monkeypatch.setenv(logic.ENVIRONMENT_VARIABLE, str(tmp_path))
        assert not logic.addUserPath(str(tmp_path))
        assert logic.getUserPaths() == []

    def test_registered_paths_put_environment_first(self, settings, monkeypatch, tmp_path):
        shared, own = str(tmp_path / "shared"), str(tmp_path / "own")
        settings.values[logic.SETTINGS_KEY] = [own, shared]
        monkeypatch.setenv(logic.ENVIRONMENT_VARIABLE, shared)

        assert logic.getRegisteredPaths() == [(shared, PathOrigin.ENVIRONMENT), (own, PathOrigin.USER)]

    def test_browse_starts_next_to_the_last_added_folder(self, settings, tmp_path):
        assert logic.browseStartDirectory() == ""

        moduleDir = writeModule(tmp_path, "Foo")
        logic.setLastAddedFolder(str(moduleDir))
        assert logic.browseStartDirectory() == str(tmp_path)

    def test_browse_start_skips_folders_that_no_longer_exist(self, settings, tmp_path):
        logic.setLastAddedFolder(str(tmp_path / "Gone" / "AlsoGone" / "Foo"))
        assert logic.browseStartDirectory() == str(tmp_path)

    def test_dropped_folders(self, tmp_path):
        moduleDir = writeModule(tmp_path, "Foo")
        otherDir = writeModule(tmp_path, "Bar")
        archive = tmp_path / "Baz.zip"
        archive.write_bytes(b"")
        missing = tmp_path / "Missing"

        dropped = [str(moduleDir), str(moduleDir / "Foo.py"), str(otherDir / "Bar.py"), str(archive), str(missing)]
        folders, ignored = logic.droppedFolders(dropped)

        assert folders == [str(moduleDir), str(otherDir)]
        assert ignored == [str(archive), str(missing)]


@pytest.fixture
def hangingFolders(monkeypatch):
    """Checking the paths in .paths hangs, like on an unreachable network share, until .release()."""
    hanging = set()
    answer = threading.Event()
    isFolder = logic._isFolder

    def hangingIsFolder(path):
        if str(path) in hanging:
            answer.wait(5)  # Fails a test that waits for it instead of hanging it
        return isFolder(path)

    def release():
        answer.set()
        for thread in list(logic._runningProbes.values()):
            thread.join(5)
        hanging.clear()
        answer.clear()

    monkeypatch.setattr(logic, "_isFolder", hangingIsFolder)
    monkeypatch.setattr(logic, "PROBE_TIMEOUT_S", 0.2)
    folders = SimpleNamespace(paths=hanging, release=release)
    yield folders
    release()


class TestUnreachableFolders:
    def test_probe_does_not_wait_for_a_hanging_folder(self, hangingFolders, tmp_path):
        dead = str(tmp_path / "dead")
        hangingFolders.paths.add(dead)
        missing = str(tmp_path / "missing")

        start = time.monotonic()
        result = logic.probeFolders([dead, str(tmp_path), missing])

        assert time.monotonic() - start < 1
        assert result == {dead: None, str(tmp_path): True, missing: False}

    def test_a_folder_still_hanging_is_not_waited_for_again(self, hangingFolders, monkeypatch, tmp_path):
        dead = str(tmp_path / "dead")
        hangingFolders.paths.add(dead)
        logic.probeFolders([dead])

        monkeypatch.setattr(logic, "PROBE_TIMEOUT_S", 5)
        start = time.monotonic()
        assert logic.probeFolders([dead]) == {dead: None}
        assert time.monotonic() - start < 1

    def test_unreachable_folder_is_skipped_until_the_next_rescan(
        self, settings, slicerModules, hangingFolders, tmp_path
    ):
        dead = writeModule(tmp_path, "Alpha")
        alive = writeModule(tmp_path, "Beta")
        settings.values[logic.SETTINGS_KEY] = [str(dead), str(alive)]
        hangingFolders.paths.add(str(dead))
        registry = CustomModuleRegistry()

        folders = registry.refresh()

        assert [f.status for f in folders] == [FolderStatus.UNREACHABLE, FolderStatus.OK]
        assert folders[0].modules == []
        assert slicerModules.loadedBatches == [["Beta"]]

        hangingFolders.release()
        folders = registry.refresh()

        assert [f.status for f in folders] == [FolderStatus.OK, FolderStatus.OK]
        assert registry.isCustomModule("Alpha")

    @pytest.mark.parametrize("winerror, expected", [(53, None), (3, False)])
    def test_network_errors_are_not_reachable(self, monkeypatch, winerror, expected):
        error = FileNotFoundError(2, "not found")
        error.winerror = winerror

        def failingStat(path):
            raise error

        with monkeypatch.context() as patch:
            patch.setattr(logic.os, "stat", failingStat)
            result = logic._isFolder("//server/share")
        assert result is expected

    def test_browse_start_skips_a_hanging_folder(self, settings, hangingFolders, tmp_path):
        logic.setLastAddedFolder(str(tmp_path / "dead" / "Foo"))
        hangingFolders.paths.add(str(tmp_path / "dead"))

        assert logic.browseStartDirectory() == str(tmp_path)


class TestRegistry:
    def test_single_module_and_collection_folders(self, settings, slicerModules, tmp_path):
        single = writeModule(tmp_path, "Alpha")
        collection = tmp_path / "collection"
        writeModule(collection, "Beta")
        writeModule(collection, "Gamma")
        settings.values[logic.SETTINGS_KEY] = [str(single), str(collection)]

        folders = CustomModuleRegistry().refresh()

        assert [f.status for f in folders] == [FolderStatus.OK, FolderStatus.OK]
        assert [m.info.key for m in folders[0].modules] == ["Alpha"]
        assert sorted(m.info.key for m in folders[1].modules) == ["Beta", "Gamma"]
        assert all(m.status == ModuleStatus.LOADED for f in folders for m in f.modules)
        slicerModules.appContext.modules.addModules.assert_called_once()

    def test_nested_collection_folders(self, settings, slicerModules, tmp_path):
        beta = writeModule(tmp_path / "group", "Beta")
        writeModule(beta, "BetaCLI")
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path)]

        folders = CustomModuleRegistry().refresh()

        assert sorted(m.info.key for m in folders[0].modules) == ["Beta", "BetaCLI"]

    def test_is_custom_module(self, settings, slicerModules, tmp_path):
        writeModule(tmp_path, "Alpha")
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path)]
        registry = CustomModuleRegistry()
        assert not registry.isCustomModule("Alpha")

        registry.refresh()

        assert registry.isCustomModule("Alpha")
        assert not registry.isCustomModule("Segmenter")

    def test_missing_and_empty_folders(self, settings, slicerModules, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path / "missing"), str(empty)]

        folders = CustomModuleRegistry().refresh()

        assert [f.status for f in folders] == [FolderStatus.MISSING, FolderStatus.EMPTY]
        assert slicerModules.loadedBatches == []

    def test_unreadable_folder_does_not_stop_the_scan(self, settings, slicerModules, monkeypatch, tmp_path):
        writeModule(tmp_path / "locked", "Alpha")
        writeModule(tmp_path / "open", "Beta")
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path / "locked"), str(tmp_path / "open")]
        listdir = os.listdir

        def deniedListdir(path):
            if "locked" in str(path):
                raise PermissionError(13, "Access is denied", str(path))
            return listdir(path)

        monkeypatch.setattr("commons.slicer.module_info.os.listdir", deniedListdir)
        folders = CustomModuleRegistry().refresh()

        assert [f.status for f in folders] == [FolderStatus.EMPTY, FolderStatus.OK]
        assert slicerModules.loadedBatches == [["Beta"]]

    def test_package_folders_are_not_modules(self, settings, slicerModules, tmp_path):
        library = writeModule(tmp_path, "Library")
        (library / "__init__.py").write_text("")
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path)]

        folders = CustomModuleRegistry().refresh()

        assert folders[0].status == FolderStatus.EMPTY

    def test_name_clashes_are_not_loaded(self, settings, slicerModules, tmp_path):
        writeModule(tmp_path / "first", "Alpha")
        writeModule(tmp_path / "second", "Alpha")
        writeModule(tmp_path / "second", "Segmenter")  # built-in module name
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path / "first"), str(tmp_path / "second")]

        first, second = CustomModuleRegistry().refresh()

        assert first.modules[0].status == ModuleStatus.LOADED
        statuses = {m.info.key: m for m in second.modules}
        assert statuses["Alpha"].status == ModuleStatus.CONFLICT
        assert "also provided by" in statuses["Alpha"].message
        assert statuses["Segmenter"].status == ModuleStatus.CONFLICT
        assert "GeoSlicer already has" in statuses["Segmenter"].message
        assert slicerModules.loadedBatches == [["Alpha"]]

    def test_refresh_loads_only_new_modules(self, settings, slicerModules, tmp_path):
        writeModule(tmp_path, "Alpha")
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path)]
        registry = CustomModuleRegistry()
        registry.refresh()

        writeModule(tmp_path, "Beta")
        folders = registry.refresh()

        assert slicerModules.loadedBatches == [["Alpha"], ["Beta"]]
        assert all(m.status == ModuleStatus.LOADED for m in folders[0].modules)

    def test_removed_folder_leaves_the_menu(self, settings, slicerModules, tmp_path):
        writeModule(tmp_path, "Alpha")
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path)]
        registry = CustomModuleRegistry()
        registry.refresh()
        assert [m.info.key for m in registry.menuModules()] == ["Alpha"]

        settings.values[logic.SETTINGS_KEY] = []
        registry.refresh()

        assert registry.menuModules() == []

    def test_failed_load(self, settings, slicerModules, monkeypatch, tmp_path):
        writeModule(tmp_path, "Alpha")
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path)]
        monkeypatch.setattr(logic, "loadModules", lambda infos, **kwargs: None)

        folders = CustomModuleRegistry().refresh()

        assert folders[0].modules[0].status == ModuleStatus.FAILED
        slicerModules.appContext.modules.addModules.assert_not_called()


def importError(modulePath):
    """The exception of a module file that raises on import, run through a frame of Python's import machinery."""
    moduleCode = compile("raise RuntimeError('uh oh')", str(modulePath), "exec")
    importCode = compile("exec(moduleCode)", "<frozen importlib._bootstrap_external>", "exec")
    try:
        exec(importCode, {"moduleCode": moduleCode})
    except RuntimeError as error:
        return error


class TestModuleErrors:
    def writeSource(self, folder, name, source):
        moduleDir = folder / name
        moduleDir.mkdir(parents=True)
        (moduleDir / f"{name}.py").write_text(source)
        return moduleDir

    def refresh(self, settings, folder):
        settings.values[logic.SETTINGS_KEY] = [str(folder)]
        return CustomModuleRegistry().refresh()[0]

    @pytest.fixture
    def failingLoad(self, slicerModules, monkeypatch):
        """Loading a module in `failing` leaves its exception in sys.last_exc and the module registered but not
        loaded, as Slicer does."""
        loadModules = logic.loadModules
        slicerModules.failing = {"Alpha"}

        def failSome(infos, **kwargs):
            key = infos[0].key
            if key in slicerModules.failing:
                monkeypatch.setattr(sys, "last_exc", importError(infos[0].path), raising=False)
                slicerModules.registered.add(key)
                slicerModules.loadedBatches.append([key])
                return
            loadModules(infos, **kwargs)

        monkeypatch.setattr(logic, "loadModules", failSome)
        return slicerModules

    @pytest.mark.parametrize(
        "source, message",
        [
            ("class Alpha(LTracePlugin):\n    def __init__(self, parent)\n        pass\n", "Syntax error on line 2"),
            ("print('no module here')\n", "No class named 'Alpha'"),
            ("class Alpha(object):\n    pass\n", "must derive from LTracePlugin"),
            ("class Alpha(LTracePlugin):\n    pass\n", "must set self.parent.categories"),
        ],
    )
    def test_invalid_module_is_reported(self, settings, slicerModules, tmp_path, source, message):
        self.writeSource(tmp_path, "Alpha", source)
        writeModule(tmp_path, "Beta")

        folder = self.refresh(settings, tmp_path)

        assert folder.status == FolderStatus.OK
        modules = {m.info.key: m for m in folder.modules}
        assert modules["Alpha"].status == ModuleStatus.INVALID
        assert modules["Alpha"].hasError
        assert message in modules["Alpha"].message
        assert modules["Beta"].status == ModuleStatus.LOADED
        assert slicerModules.loadedBatches == [["Beta"]]

    def test_syntax_error_details_point_at_the_line(self, settings, slicerModules, tmp_path):
        self.writeSource(tmp_path, "Alpha", "x = (\n")

        module = self.refresh(settings, tmp_path).modules[0]

        assert "Alpha.py" in module.details
        assert "SyntaxError" in module.details

    def test_only_files_named_after_their_folder_are_reported(self, settings, slicerModules, tmp_path):
        moduleDir = writeModule(tmp_path, "Alpha")
        (moduleDir / "helpers.py").write_text("def broken(:\n")
        (moduleDir / "widgets.py").write_text("print('not a module')\n")

        folder = self.refresh(settings, tmp_path)

        assert [(m.info.key, m.status) for m in folder.modules] == [("Alpha", ModuleStatus.LOADED)]

    def test_folder_with_only_an_invalid_module_is_not_empty(self, settings, slicerModules, tmp_path):
        self.writeSource(tmp_path, "Alpha", "print('no module here')\n")

        assert self.refresh(settings, tmp_path).status == FolderStatus.OK

    def test_disabled_invalid_module(self, settings, slicerModules, tmp_path):
        moduleDir = self.writeSource(tmp_path, "Alpha", "print('no module here')\n")
        logic.setModuleEnabled(str(moduleDir / "Alpha.py"), False)

        module = self.refresh(settings, tmp_path).modules[0]

        assert module.status == ModuleStatus.DISABLED
        assert not module.hasError

    def test_failed_module_is_disabled_with_its_traceback(self, settings, failingLoad, tmp_path):
        moduleDir = writeModule(tmp_path, "Alpha")
        writeModule(tmp_path, "Beta")
        modulePath = logic.normalizePath(moduleDir / "Alpha.py")

        folder = self.refresh(settings, tmp_path)

        modules = {m.info.key: m for m in folder.modules}
        alpha = modules["Alpha"]
        assert alpha.status == ModuleStatus.FAILED
        assert not alpha.enabled
        assert alpha.message == "RuntimeError: uh oh"
        assert alpha.details.startswith("Traceback")
        assert "Alpha.py" in alpha.details
        assert "<frozen" not in alpha.details
        assert modules["Beta"].status == ModuleStatus.LOADED
        assert logic.getDisabledModulePaths() == [modulePath]
        assert logic.getLoadErrors()[modulePath]["message"] == "RuntimeError: uh oh"

    def test_failed_module_is_not_loaded_again(self, settings, failingLoad, tmp_path):
        writeModule(tmp_path, "Alpha")
        self.refresh(settings, tmp_path)

        # A new registry stands for the next start
        alpha = self.refresh(settings, tmp_path).modules[0]

        assert alpha.status == ModuleStatus.FAILED
        assert alpha.message == "RuntimeError: uh oh"
        assert failingLoad.loadedBatches == [["Alpha"]]

    def test_enabling_a_failed_module_retries_it(self, settings, failingLoad, tmp_path):
        moduleDir = writeModule(tmp_path, "Alpha")
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path)]
        registry = CustomModuleRegistry()
        registry.refresh()

        logic.setModuleEnabled(str(moduleDir / "Alpha.py"), True)
        assert logic.getLoadErrors() == {}
        alpha = registry.refresh()[0].modules[0]

        assert alpha.status == ModuleStatus.FAILED
        assert failingLoad.loadedBatches == [["Alpha"], ["Alpha"]]

    def test_fixed_module_loads_when_enabled_again(self, settings, failingLoad, tmp_path):
        moduleDir = writeModule(tmp_path, "Alpha")
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path)]
        registry = CustomModuleRegistry()
        registry.refresh()

        # Still registered in Slicer after the failure, which must not read as a clash with a built-in module
        failingLoad.failing.clear()
        logic.setModuleEnabled(str(moduleDir / "Alpha.py"), True)
        alpha = registry.refresh()[0].modules[0]

        assert alpha.status == ModuleStatus.LOADED
        assert alpha.enabled
        assert [m.info.key for m in registry.menuModules()] == ["Alpha"]

    def test_an_older_error_is_not_blamed_on_the_module(self, settings, slicerModules, monkeypatch, tmp_path):
        writeModule(tmp_path, "Alpha")
        monkeypatch.setattr(sys, "last_exc", RuntimeError("an earlier error"), raising=False)
        monkeypatch.setattr(logic, "loadModules", lambda infos, **kwargs: None)

        alpha = self.refresh(settings, tmp_path).modules[0]

        assert alpha.status == ModuleStatus.FAILED
        assert "earlier" not in alpha.message
        assert alpha.details == ""

    def test_load_error_without_an_exception(self):
        message, details = logic.describeLoadError(None)
        assert "See the Python console or the log" in message
        assert details == ""


class TestEnabled:
    def modulePath(self, moduleDir):
        return str(moduleDir / f"{moduleDir.name}.py")

    def test_setting_round_trip(self, settings, tmp_path):
        path = self.modulePath(writeModule(tmp_path, "Alpha"))
        logic.setModuleEnabled(path, False)
        logic.setModuleEnabled(path, False)
        assert logic.getDisabledModulePaths() == [logic.normalizePath(path)]

        logic.setModuleEnabled(path, True)
        assert logic.getDisabledModulePaths() == []

    def test_disabled_module_is_not_loaded(self, settings, slicerModules, tmp_path):
        logic.setModuleEnabled(self.modulePath(writeModule(tmp_path, "Alpha")), False)
        writeModule(tmp_path, "Beta")
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path)]
        registry = CustomModuleRegistry()

        folders = registry.refresh()

        statuses = {m.info.key: m for m in folders[0].modules}
        assert statuses["Alpha"].status == ModuleStatus.DISABLED
        assert not statuses["Alpha"].enabled
        assert statuses["Beta"].status == ModuleStatus.LOADED
        assert slicerModules.loadedBatches == [["Beta"]]
        assert [m.info.key for m in registry.menuModules()] == ["Beta"]

    def test_enabling_loads_the_module(self, settings, slicerModules, tmp_path):
        path = self.modulePath(writeModule(tmp_path, "Alpha"))
        logic.setModuleEnabled(path, False)
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path)]
        registry = CustomModuleRegistry()
        registry.refresh()

        logic.setModuleEnabled(path, True)
        folders = registry.refresh()

        assert folders[0].modules[0].status == ModuleStatus.LOADED
        assert slicerModules.loadedBatches == [["Alpha"]]
        assert [m.info.key for m in registry.menuModules()] == ["Alpha"]

    def test_disabling_a_loaded_module(self, settings, slicerModules, tmp_path):
        path = self.modulePath(writeModule(tmp_path, "Alpha"))
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path)]
        registry = CustomModuleRegistry()
        registry.refresh()

        logic.setModuleEnabled(path, False)
        module = registry.refresh()[0].modules[0]

        # Slicer can't unload modules: it stays loaded but leaves the menu
        assert module.status == ModuleStatus.LOADED
        assert not module.enabled
        assert "restarted" in module.message
        assert registry.menuModules() == []

        # After a restart it is not loaded at all
        restarted = CustomModuleRegistry().refresh()[0].modules[0]
        assert restarted.status == ModuleStatus.DISABLED
        assert slicerModules.loadedBatches == [["Alpha"]]

    def test_disabled_module_does_not_block_its_name(self, settings, slicerModules, tmp_path):
        logic.setModuleEnabled(self.modulePath(writeModule(tmp_path / "first", "Alpha")), False)
        writeModule(tmp_path / "second", "Alpha")
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path / "first"), str(tmp_path / "second")]

        first, second = CustomModuleRegistry().refresh()

        assert first.modules[0].status == ModuleStatus.DISABLED
        assert second.modules[0].status == ModuleStatus.LOADED


class TestSingleModule:
    def folder(self, *modules):
        return ModuleFolder("/folder", PathOrigin.USER, FolderStatus.OK, list(modules))

    def module(self, key, status=ModuleStatus.LOADED, categories=("Tools",)):
        return CustomModule(ModuleInfo(f"/folder/{key}/{key}.py", categories=list(categories)), status)

    def test_single_module(self):
        alpha = self.module("Alpha")
        assert self.folder(alpha).singleModule() is alpha

    def test_module_with_its_cli(self):
        alpha = self.module("Alpha")
        assert self.folder(alpha, self.module("AlphaCLI", categories=["CLI"])).singleModule() is alpha

    def test_collection(self):
        assert self.folder(self.module("Alpha"), self.module("Beta")).singleModule() is None

    @pytest.mark.parametrize("status", [ModuleStatus.FAILED, ModuleStatus.CONFLICT])
    def test_problem_in_the_folder(self, status):
        assert self.folder(self.module("Alpha", status)).singleModule() is None
        assert self.folder(self.module("Alpha"), self.module("AlphaCLI", status, ["CLI"])).singleModule() is None

    def test_empty_folder(self):
        assert self.folder().singleModule() is None

    def test_disabled_module_in_the_folder(self):
        disabledCli = self.module("AlphaCLI", ModuleStatus.DISABLED, ["CLI"])
        disabledCli.enabled = False
        assert self.folder(self.module("Alpha"), disabledCli).singleModule() is None


DEAD_PID = 4321  # Not running, unless added to the alive fixture


class TestCrashRecovery:
    @pytest.fixture
    def alive(self, monkeypatch):
        """PIDs of the processes that are running, besides this one."""
        pids = set()
        monkeypatch.setattr(logic.psutil, "pid_exists", lambda pid: pid in pids or pid == os.getpid())
        return pids

    def leaveMarker(self, modulePath, pid=DEAD_PID):
        folder = logic._loadingMarkersPath()
        folder.mkdir(parents=True, exist_ok=True)
        marker = folder / f"{pid}.txt"
        marker.write_text(str(modulePath), encoding="utf-8")
        return marker

    def modulePath(self, moduleDir):
        return moduleDir / f"{moduleDir.name}.py"

    def test_marker_names_the_loading_module(self, settings, slicerModules, monkeypatch, tmp_path):
        moduleDir = writeModule(tmp_path, "Alpha")
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path)]
        markers = []

        def loadModules(infos, **kwargs):
            markers.extend(path.read_text() for path in logic._loadingMarkersPath().glob("*.txt"))

        monkeypatch.setattr(logic, "loadModules", loadModules)
        CustomModuleRegistry().refresh()

        assert markers == [str(self.modulePath(moduleDir))]
        assert list(logic._loadingMarkersPath().glob("*.txt")) == []

    def test_clean_start(self, settings, alive):
        assert logic.recoverFromCrash() is None

    def test_module_that_crashed_is_disabled(self, settings, slicerModules, alive, tmp_path):
        crashed = self.modulePath(writeModule(tmp_path, "Alpha"))
        writeModule(tmp_path, "Beta")
        settings.values[logic.SETTINGS_KEY] = [str(tmp_path)]
        marker = self.leaveMarker(crashed)

        recovery = logic.recoverFromCrash()
        folders = CustomModuleRegistry().refresh()

        assert recovery.modulePaths == [str(crashed)]
        assert not marker.exists()
        modules = {m.info.key: m for m in folders[0].modules}
        assert modules["Alpha"].status == ModuleStatus.FAILED
        assert modules["Alpha"].message == logic.CRASH_MESSAGE
        assert not modules["Alpha"].enabled
        assert modules["Beta"].status == ModuleStatus.LOADED
        assert slicerModules.loadedBatches == [["Beta"]]

    def test_marker_of_a_running_instance_is_left_alone(self, settings, alive, tmp_path):
        crashed = self.modulePath(writeModule(tmp_path, "Alpha"))
        alive.add(1234)
        marker = self.leaveMarker(crashed, pid=1234)

        assert logic.recoverFromCrash() is None
        assert marker.exists()
        assert logic.getDisabledModulePaths() == []

    def test_marker_with_this_process_id_is_from_an_earlier_process(self, settings, alive, tmp_path):
        crashed = self.modulePath(writeModule(tmp_path, "Alpha"))
        self.leaveMarker(crashed, pid=os.getpid())

        assert logic.recoverFromCrash().modulePaths == [str(crashed)]
