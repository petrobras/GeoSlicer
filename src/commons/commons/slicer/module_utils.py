import logging

import slicer
import qt

from commons.slicer.module_info import ModuleInfo


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


def loadModules(modules):
    """
    Loads a module in the Slicer factory while Slicer is running
    """
    # Determine which modules in above are not already loaded
    factory = slicer.app.moduleManager().factoryManager()

    modulesToLoad = []

    for myModule in modules:
        if factory.isLoaded(myModule.key):
            logging.info(f"Module {myModule.key} already loaded")
            continue

        # Register requested module(s)
        factory.registerModule(qt.QFileInfo(str(myModule.path)))

        if not factory.isRegistered(myModule.key):
            logging.warning(f"Failed to register module {myModule.key}")
            continue

        modulesToLoad.append(myModule.key)

    for module in modulesToLoad:
        logging.info(f"Loading module {module}")
        if not factory.loadModules([module]):
            logging.error(f"Failed to load module {module}")
            continue

    for myModule in modules:
        myModule.loaded = factory.isLoaded(myModule.key)
        if myModule.loaded:
            logging.info(f"Module {myModule.key} loaded")


def mapByCategory(modules):
    groupedModulesByCategories = {}
    for module in modules:
        for category in module.categories:
            if category not in groupedModulesByCategories:
                groupedModulesByCategories[category] = []
            groupedModulesByCategories[category].append(module)

    return groupedModulesByCategories
