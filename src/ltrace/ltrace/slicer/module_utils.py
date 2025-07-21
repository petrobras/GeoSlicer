import logging

from pathlib import Path

import slicer, qt

from ltrace.slicer.module_info import ModuleInfo
from pathlib import Path


def fetchAsList(settings, key) -> list:
    # Return a settings value as a list (even if empty or a single value)

    value = settings.value(key)

    if isinstance(value, str):
        return [value]
    elif isinstance(value, tuple):
        return list(value)
    else:
        return []


def loadModule(module: ModuleInfo):
    factory = slicer.app.moduleManager().factoryManager()

    if factory.isLoaded(module.key):
        return

    factory.registerModule(qt.QFileInfo(str(module.path)))
    if not factory.isRegistered(module.key):
        logging.warning(f"Failed to register module {module.key}")
        return False

    if not factory.loadModules([module.key]):
        logging.error(f"Failed to load module {module.key}")

    return True


def loadModules(modules, permanent=False, favorite=False):
    """
    Loads a module in the Slicer factory while Slicer is running
    """
    # Determine which modules in above are not already loaded
    factory = slicer.app.moduleManager().factoryManager()

    # Add module(s) to permanent search paths, if requested
    settings = slicer.app.revisionUserSettings()
    searchPaths = [Path(fp) for fp in fetchAsList(settings, "Modules/AdditionalPaths")]
    npaths = len(searchPaths)

    modulesToLoad = []

    for myModule in modules:
        if factory.isLoaded(myModule.key):
            logging.info(f"Module {myModule.key} already loaded")
            continue

        if permanent:
            rawPath = Path(myModule.searchPath)

            if rawPath not in searchPaths:
                searchPaths.append(rawPath)

        # Register requested module(s)
        factory.registerModule(qt.QFileInfo(str(myModule.path)))

        if not factory.isRegistered(myModule.key):
            logging.warning(f"Failed to register module {myModule.key}")
            continue

        modulesToLoad.append(myModule.key)

    if not factory.loadModules(modulesToLoad):
        logging.error(f"Failed to load some module(s)")
        return

    if len(searchPaths) > npaths:
        settings.setValue("Modules/AdditionalPaths", [str(p) for p in searchPaths])

    for myModule in modules:
        myModule.loaded = factory.isLoaded(myModule.key)
        logging.info(f"Module {myModule.key} loaded")

    if favorite and modulesToLoad:
        favoritedModules = slicer.app.userSettings().value("Modules/FavoriteModules", None)
        favoritedModules = modulesToLoad if not favoritedModules else [*favoritedModules, *modulesToLoad]
        slicer.app.userSettings().setValue("Modules/FavoriteModules", favoritedModules)


def fetchModulesFrom(path, depth=1, name="LTrace"):
    if path is None:
        return {}

    candidates = {}
    try:
        modules = ModuleInfo.findModules(path, depth)
        candidates = {m.key: m for m in modules}
    except Exception as e:
        logging.warning(f"Failed to load modules: {e}")

    logging.info(f"{name} modules loaded: {len(candidates)}")
    return candidates


def mapByCategory(modules):
    groupedModulesByCategories = {}
    for module in modules:
        if module.key == "CustomizedGradientAnisotropicDiffusion":
            pass
        for category in module.categories:
            if category not in groupedModulesByCategories:
                groupedModulesByCategories[category] = []
            groupedModulesByCategories[category].append(module)

    return groupedModulesByCategories
