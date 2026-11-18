"""Custom modules loaded from user-registered folders and from the GEOSLICER_MODULE_PATHS environment variable.

A registered folder may be a single module folder (``Foo/Foo.py``) or a collection of module folders
(``Collection/Foo/Foo.py``, ``Collection/Bar/Bar.py``). Modules are loaded straight from their folders,
so sharing a module is as simple as sharing its folder path.
"""

import json
import logging
import os
import stat
import sys
import threading
import time
import traceback

from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

import psutil
import slicer

from commons.slicer.custom_modules.icon import usePlaceholderIconIfMissing
from commons.slicer.module_info import ModuleInfo
from commons.slicer.module_utils import loadModules

SETTINGS_KEY = "CustomModules/Paths"
DISABLED_SETTINGS_KEY = "CustomModules/Disabled"
LAST_FOLDER_SETTINGS_KEY = "CustomModules/LastFolder"
LOAD_ERRORS_SETTINGS_KEY = "CustomModules/LoadErrors"
ENVIRONMENT_VARIABLE = "GEOSLICER_MODULE_PATHS"

CRASH_MESSAGE = "GeoSlicer closed unexpectedly while loading this module"
LOADING_MARKERS_FOLDER = "CustomModulesLoading"

# Depth 3 covers collections grouped in subfolders, down to their modules' CLI subfolders
# (Collection/Group/Foo/FooCLI/FooCLI.py). Folders are followed through symlinks and junctions.
SCAN_DEPTH = 3

# How long, in total, a scan waits for registered folders to answer. An unreachable network share blocks
# os.path.isdir for about 20 s.
PROBE_TIMEOUT_S = 2.0


class PathOrigin(Enum):
    USER = "User"
    ENVIRONMENT = "Environment"


class FolderStatus(Enum):
    OK = "OK"
    MISSING = "Folder not found"
    UNREACHABLE = "Not reachable"
    EMPTY = "No modules found"


class ModuleStatus(Enum):
    LOADED = "Loaded"
    CONFLICT = "Not loaded"
    INVALID = "Invalid"
    FAILED = "Failed to load"
    DISABLED = "Disabled"


@dataclass
class CustomModule:
    info: ModuleInfo
    status: ModuleStatus
    message: str = ""
    enabled: bool = True
    details: str = ""  # Traceback or other error text behind the message

    @property
    def hasError(self) -> bool:
        return self.status in (ModuleStatus.INVALID, ModuleStatus.FAILED)

    @property
    def isMenuEntry(self) -> bool:
        return (
            self.enabled
            and self.status == ModuleStatus.LOADED
            and not self.info.hidden
            and "CLI" not in self.info.categories
        )


@dataclass
class ModuleFolder:
    path: str
    origin: PathOrigin
    status: FolderStatus
    modules: List[CustomModule] = field(default_factory=list)

    @property
    def isRemovable(self) -> bool:
        return self.origin == PathOrigin.USER

    def singleModule(self) -> Optional[CustomModule]:
        """The folder's only module, if it has exactly one and everything in the folder loaded."""
        entries = [module for module in self.modules if module.isMenuEntry]
        if len(entries) == 1 and all(module.status == ModuleStatus.LOADED for module in self.modules):
            return entries[0]
        return None


def normalizePath(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))


def parsePathList(value: Optional[str]) -> List[str]:
    """Split a PATH-like string (os.pathsep separated) into its non-empty entries."""
    if not value:
        return []

    return [entry.strip() for entry in value.split(os.pathsep) if entry.strip()]


def getEnvironmentPaths() -> List[str]:
    return parsePathList(os.environ.get(ENVIRONMENT_VARIABLE))


def _readPathList(key: str) -> List[str]:
    value = slicer.app.userSettings().value(key)
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple)):
        return [str(path) for path in value if path]
    return []


def _writePathList(key: str, paths: List[str]) -> None:
    settings = slicer.app.userSettings()
    settings.setValue(key, list(paths))
    settings.sync()


def getUserPaths() -> List[str]:
    return _readPathList(SETTINGS_KEY)


def setUserPaths(paths: List[str]) -> None:
    _writePathList(SETTINGS_KEY, paths)


def addUserPath(path: str) -> bool:
    """Register a folder for the current user. Returns False if it was already registered."""
    paths = getUserPaths()
    registered = {normalizePath(p) for p in paths + getEnvironmentPaths()}
    if normalizePath(path) in registered:
        return False

    setUserPaths(paths + [str(Path(path))])
    return True


def removeUserPath(path: str) -> bool:
    paths = getUserPaths()
    remaining = [p for p in paths if normalizePath(p) != normalizePath(path)]
    if len(remaining) == len(paths):
        return False

    setUserPaths(remaining)
    return True


def getDisabledModulePaths() -> List[str]:
    """Normalized file paths of the modules the user disabled."""
    return _readPathList(DISABLED_SETTINGS_KEY)


def setModuleEnabled(modulePath: str, enabled: bool) -> None:
    """Remember whether the module file at modulePath should be loaded. Enabling a module forgets its last load
    error, so it is loaded again."""
    target = normalizePath(modulePath)
    disabled = [path for path in getDisabledModulePaths() if path != target]
    if not enabled:
        disabled.append(target)
    _writePathList(DISABLED_SETTINGS_KEY, disabled)
    if enabled:
        _setLoadError(modulePath, None)


def getLoadErrors() -> Dict[str, dict]:
    """{normalized module file path: {"message", "details"}} for the modules disabled because they failed to load."""
    value = slicer.app.userSettings().value(LOAD_ERRORS_SETTINGS_KEY)
    return json.loads(value) if value else {}


def _setLoadError(modulePath: str, error: Optional[dict]) -> None:
    errors = getLoadErrors()
    target = normalizePath(modulePath)
    if error is None:
        if target not in errors:
            return
        del errors[target]
    else:
        errors[target] = error

    settings = slicer.app.userSettings()
    settings.setValue(LOAD_ERRORS_SETTINGS_KEY, json.dumps(errors))
    settings.sync()


def _loadingMarkersPath() -> Path:
    return Path(slicer.app.userSettings().fileName()).parent / LOADING_MARKERS_FOLDER


@contextmanager
def _loadingMarker(modulePath: str):
    """Leave a file naming the module while it loads. If GeoSlicer crashes meanwhile, the file outlives the process
    and tells the next start which module to disable. Files are named after the process, so GeoSlicer instances
    running side by side don't blame each other's modules."""
    marker = _loadingMarkersPath() / f"{os.getpid()}.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(modulePath), encoding="utf-8")
    try:
        yield
    finally:
        marker.unlink()


def _takeCrashedLoads() -> List[str]:
    """Remove the markers left by GeoSlicer processes that ended while loading a module, and return those modules.

    Only valid before this process loads any module: a marker with its own PID is from an earlier process."""
    folder = _loadingMarkersPath()
    if not folder.is_dir():
        return []

    modulePaths = []
    for marker in folder.glob("*.txt"):
        pid = int(marker.stem)
        if pid != os.getpid() and psutil.pid_exists(pid):
            continue  # Another GeoSlicer is loading a module right now

        modulePath = marker.read_text(encoding="utf-8").strip()
        marker.unlink()
        if modulePath:
            modulePaths.append(modulePath)
    return modulePaths


@dataclass
class CrashRecovery:
    """What was done at startup about custom modules that crashed GeoSlicer while loading."""

    modulePaths: List[str]


def recoverFromCrash() -> Optional[CrashRecovery]:
    """Disable the modules that were loading when an earlier session crashed. Call once at startup, before loading
    modules. Returns None if there was no such crash."""
    modulePaths = _takeCrashedLoads()
    if not modulePaths:
        return None

    for modulePath in modulePaths:
        logging.error(f"GeoSlicer closed unexpectedly while loading the custom module {modulePath}. It was disabled.")
        setModuleEnabled(modulePath, False)
        _setLoadError(modulePath, {"message": CRASH_MESSAGE, "details": ""})
    return CrashRecovery(modulePaths)


def describeLoadError(error: Optional[BaseException]) -> tuple:
    """(message, details) for the exception that stopped a module from loading: its last line, and its traceback
    without the frames of Python's import machinery."""
    if error is None:
        return "Failed to load. See the Python console or the log for the error.", ""
    text = "".join(traceback.format_exception(error)).strip()
    lines = [line for line in text.splitlines() if not line.lstrip().startswith('File "<frozen ')]
    return lines[-1].strip(), "\n".join(lines)


# Probes still waiting for their folder, by path. Plain daemon threads, not a ThreadPoolExecutor, whose exit
# hook would make closing GeoSlicer wait for a stuck network share.
_runningProbes: Dict[str, threading.Thread] = {}


# Windows errors for a network location that can't be reached, as opposed to a folder that doesn't exist. Once a
# share has timed out, Windows answers from its cache with ERROR_BAD_NETPATH for a while.
_NETWORK_ERRORS = {
    51,  # ERROR_REM_NOT_LIST
    53,  # ERROR_BAD_NETPATH
    64,  # ERROR_NETNAME_DELETED
    67,  # ERROR_BAD_NET_NAME
    1222,  # ERROR_NO_NETWORK
    1231,  # ERROR_NETWORK_UNREACHABLE
}


def _isFolder(path: str) -> Optional[bool]:
    """Whether path is a folder, or None when its network location can't be reached."""
    try:
        return stat.S_ISDIR(os.stat(path).st_mode)
    except OSError as error:
        return None if getattr(error, "winerror", None) in _NETWORK_ERRORS else False


def _probe(path: str, results: Dict[str, Optional[bool]]) -> None:
    try:
        results[path] = _isFolder(path)
    finally:
        _runningProbes.pop(path, None)


def probeFolders(paths: List[str]) -> Dict[str, Optional[bool]]:
    """{path: whether it is a folder} for each path, or None for those that are on an unreachable network location
    or didn't answer within PROBE_TIMEOUT_S in total. The paths are checked in parallel. A path whose check from an
    earlier call is still running is not waited for again."""
    results: Dict[str, Optional[bool]] = {}
    started = []
    for path in dict.fromkeys(paths):
        if path in _runningProbes:
            continue
        thread = threading.Thread(target=_probe, args=(path, results), name="Custom module folder probe", daemon=True)
        _runningProbes[path] = thread
        thread.start()
        started.append(thread)

    deadline = time.monotonic() + PROBE_TIMEOUT_S
    for thread in started:
        thread.join(max(0.0, deadline - time.monotonic()))
    return {path: results.get(path) for path in paths}


def setLastAddedFolder(path: str) -> None:
    settings = slicer.app.userSettings()
    settings.setValue(LAST_FOLDER_SETTINGS_KEY, str(Path(path)))
    settings.sync()


def browseStartDirectory() -> str:
    """Where the folder picker opens: the parent of the last added folder, so its sibling modules are one click
    away. Falls back to the closest folder that still exists and answers, or "" when there is none."""
    last = slicer.app.userSettings().value(LAST_FOLDER_SETTINGS_KEY)
    if not last or not isinstance(last, str):
        return ""

    candidates = [str(candidate) for candidate in Path(last).parents]
    isFolder = probeFolders(candidates)
    return next((candidate for candidate in candidates if isFolder[candidate]), "")


def droppedFolders(paths: List[str]) -> tuple:
    """Sort dropped paths into (folders to add, paths that aren't folders). A dropped module file stands for its
    folder. Duplicates are dropped, keeping the first occurrence."""
    folders = []
    ignored = []
    seen = set()
    for path in paths:
        if os.path.isdir(path):
            folder = path
        elif os.path.isfile(path) and Path(path).suffix.lower() == ".py":
            folder = str(Path(path).parent)
        else:
            ignored.append(path)
            continue

        key = normalizePath(folder)
        if key not in seen:
            seen.add(key)
            folders.append(folder)
    return folders, ignored


def getRegisteredPaths() -> List[tuple]:
    """Return (path, origin) pairs: administrator paths first, then the user's, without duplicates."""
    result = []
    seen = set()
    for origin, paths in ((PathOrigin.ENVIRONMENT, getEnvironmentPaths()), (PathOrigin.USER, getUserPaths())):
        for path in paths:
            key = normalizePath(path)
            if key in seen:
                continue
            seen.add(key)
            result.append((path, origin))
    return result


def findFolderModules(path: str) -> tuple:
    """(modules, problems) in a folder. problems holds (ModuleInfo, message, details) for the files that look like
    modules but can't be loaded, such as those with syntax errors."""
    problems = []
    try:
        return ModuleInfo.findModules(str(path), SCAN_DEPTH, problems), problems
    except OSError as error:
        logging.warning(f"Failed to scan custom module folder {path}: {error}")
        return [], []


class CustomModuleRegistry:
    """Scans the registered folders and loads their modules into the running application.

    Slicer cannot unload modules, so a module stays loaded until restart even if its folder is removed.
    """

    def __init__(self) -> None:
        self.folders: List[ModuleFolder] = []
        self.__loadedModulePaths: Dict[str, str] = {}  # module key -> normalized module file path
        # Modules that failed to load stay registered in Slicer's module factory. Tracked to tell a retry apart
        # from a clash with a built-in module.
        self.__failedModulePaths: Dict[str, str] = {}

    def refresh(self) -> List[ModuleFolder]:
        """Rescan every registered folder and load modules that are not loaded yet. Folders that don't answer in
        time, such as an unreachable network share, are skipped until the next rescan."""
        folders = []
        claimed: Dict[str, str] = {}  # module key -> folder that provides it in this scan
        pending: List[CustomModule] = []
        disabled = set(getDisabledModulePaths())
        loadErrors = getLoadErrors()
        registered = getRegisteredPaths()
        isFolder = probeFolders([path for path, _ in registered])

        for path, origin in registered:
            if isFolder[path] is None:
                logging.warning(f"Custom module folder {path} is not reachable. It was skipped.")
                folders.append(ModuleFolder(path, origin, FolderStatus.UNREACHABLE))
                continue
            if not isFolder[path]:
                folders.append(ModuleFolder(path, origin, FolderStatus.MISSING))
                continue

            infos, problems = findFolderModules(path)
            folder = ModuleFolder(path, origin, FolderStatus.OK if infos or problems else FolderStatus.EMPTY)
            for info in infos:
                key = normalizePath(info.path)
                module = self.__classify(info, claimed.get(info.key), key not in disabled, loadErrors.get(key))
                folder.modules.append(module)
                if not module.enabled and module.status != ModuleStatus.LOADED:
                    # Leaves the name free for a module with the same name in another folder
                    continue
                claimed.setdefault(info.key, path)
                if module.status != ModuleStatus.CONFLICT and info.key not in self.__loadedModulePaths:
                    pending.append(module)
            for info, message, details in problems:
                # None of their code runs, so they are checked again on every scan and load once fixed
                if normalizePath(info.path) in disabled:
                    folder.modules.append(CustomModule(info, ModuleStatus.DISABLED, enabled=False))
                else:
                    folder.modules.append(CustomModule(info, ModuleStatus.INVALID, message, details=details))
            folders.append(folder)

        self.__load(pending)
        self.folders = folders
        return folders

    def isCustomModule(self, key: str) -> bool:
        return key in self.__loadedModulePaths

    def modules(self) -> List[CustomModule]:
        return [module for folder in self.folders for module in folder.modules]

    def menuModules(self) -> List[CustomModule]:
        return [module for module in self.modules() if module.isMenuEntry]

    def __classify(
        self, info: ModuleInfo, claimedBy: Optional[str], enabled: bool, loadError: Optional[dict]
    ) -> CustomModule:
        loadedPath = self.__loadedModulePaths.get(info.key)
        isLoaded = loadedPath == normalizePath(info.path)
        if not enabled and not isLoaded:
            if loadError:
                return CustomModule(
                    info,
                    ModuleStatus.FAILED,
                    loadError.get("message", ""),
                    enabled=False,
                    details=loadError.get("details", ""),
                )
            return CustomModule(info, ModuleStatus.DISABLED, enabled=False)

        if claimedBy is not None:
            return CustomModule(info, ModuleStatus.CONFLICT, f"'{info.key}' is also provided by {claimedBy}")

        if loadedPath is not None:
            if isLoaded:
                if not enabled:
                    return CustomModule(
                        info, ModuleStatus.LOADED, "It stays loaded until GeoSlicer is restarted", enabled=False
                    )
                return CustomModule(info, ModuleStatus.LOADED)
            return CustomModule(
                info, ModuleStatus.CONFLICT, f"A module named '{info.key}' was already loaded from {loadedPath}"
            )

        isRetry = self.__failedModulePaths.get(info.key) == normalizePath(info.path)
        if not isRetry and self.__isApplicationModule(info.key):
            return CustomModule(info, ModuleStatus.CONFLICT, f"GeoSlicer already has a module named '{info.key}'")

        # Status is settled after loading
        return CustomModule(info, ModuleStatus.FAILED)

    @staticmethod
    def __isApplicationModule(key: str) -> bool:
        factory = slicer.app.moduleManager().factoryManager()
        if factory.isRegistered(key):
            return True

        appContext = getattr(slicer.modules, "AppContextInstance", None)
        return appContext is not None and key in appContext.modules.availableModules

    def __load(self, modules: List[CustomModule]) -> None:
        if not modules:
            return

        loaded = []
        for module in modules:
            with _loadingMarker(module.info.path):
                error = self.__loadReturningError(module.info)
            if getattr(module.info, "loaded", False):
                module.status = ModuleStatus.LOADED
                module.message = ""
                self.__loadedModulePaths[module.info.key] = normalizePath(module.info.path)
                self.__failedModulePaths.pop(module.info.key, None)
                loaded.append(module.info)
                usePlaceholderIconIfMissing(getattr(slicer.modules, module.info.key.lower()))
            else:
                # Disabled so a broken module doesn't run again on every scan and start. Enabling it retries.
                module.status = ModuleStatus.FAILED
                module.message, module.details = describeLoadError(error)
                module.enabled = False
                self.__failedModulePaths[module.info.key] = normalizePath(module.info.path)
                # Slicer keeps the half-imported module, which a retry would reuse instead of the fixed file
                sys.modules.pop(module.info.key, None)
                setModuleEnabled(module.info.path, False)
                _setLoadError(module.info.path, {"message": module.message, "details": module.details})
                logging.error(f"Custom module {module.info.key} failed to load and was disabled: {module.message}")

        appContext = getattr(slicer.modules, "AppContextInstance", None)
        if appContext is not None and loaded:
            # Makes the modules findable through the module search (ctrl+F)
            appContext.modules.addModules(loaded)

    @staticmethod
    def __loadReturningError(info: ModuleInfo) -> Optional[BaseException]:
        """Load a module and return the exception that stopped it, if any. Slicer runs the module file in its C++
        loader, which prints the exception and clears it, but printing it records it in sys.last_exc."""
        lastError = getattr(sys, "last_exc", None)
        loadModules([info])
        error = getattr(sys, "last_exc", None)
        return error if error is not lastError else None


_registry: Optional[CustomModuleRegistry] = None


def customModules() -> CustomModuleRegistry:
    global _registry
    if _registry is None:
        _registry = CustomModuleRegistry()
    return _registry
