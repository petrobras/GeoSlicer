import logging
import shutil

from pathlib import Path

import slicer, qt

from ltrace.slicer.module_info import ModuleInfo


def fetchAsList(settings, key) -> list:
    # Return a settings value as a list (even if empty or a single value)

    value = settings.value(key)

    if isinstance(value, str):
        return [value]

    return [] if value is None else value


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

    # Instantiate and load requested module(s)
    # if len(modules) != len(modulesToLoad):
    #     slicer.util.errorDisplay("The module factory manager reported an error. \
    #              One or more of the requested module(s) and/or \
    #              dependencies thereof may not have been loaded.")

    if favorite and len(modulesToLoad) > 0:
        favoriteModules = slicer.app.userSettings().value("Modules/FavoriteModules") or []
        favorites = [*favoriteModules, *modulesToLoad]
        slicer.app.userSettings().setValue("Modules/FavoriteModules", favorites)


def fetchModulesFrom(path, depth=1, name="LTrace"):
    from ltrace.slicer_utils import base_version

    if path is None:
        return {}

    candidates = {}

    try:
        if isinstance(path, str) and path.endswith(".git"):
            geoslicer_version = base_version()
            dest = Path(slicer.app.slicerHome) / "lib" / geoslicer_version / "qt-scripted-extern-modules"
            dest.mkdir(parents=True, exist_ok=True)

            try:
                # Clone or update the repository
                path = clone_or_update_repo(path, dest, branch="master")
            except RuntimeError as re:
                if len(candidates) == 0:
                    shutil.rmtree(dest, ignore_errors=True)

        # Get list of modules in specified path
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


def clone_or_update_repo(remote_url: str, destination_dir: Path, branch: str = "master") -> None:
    """
    Clone the repository from `remote_url` into `destination_dir`.
    If the repository already exists, update it by pulling the latest changes.

    Args:
        remote_url (str): URL of the remote repository.
        destination_dir (str | Path): Path where the repository should be cloned or updated.

    Raises:
        ValueError: If the existing repository in `destination_dir` has a different remote URL.

    Returns:
        str: A message indicating the action taken.
    """
    import os

    os.environ["GIT_PYTHON_REFRESH"] = "quiet"
    import git

    try:
        remote_repo = remote_url.split("/")[-1].split(".")[0]

        destination_dir = destination_dir / remote_repo

        if destination_dir.exists():
            # If the directory exists, open the repo and check the remote URL
            repo = git.Repo(destination_dir)
            if repo.remotes.origin.url != remote_url:
                raise ValueError(f"Directory exists but points to a different repository: {repo.remotes.origin.url}")

            # Pull the latest changes if the remote URL matches
            try:
                repo.remotes.origin.pull(branch).raise_if_error()
            except git.GitCommandError as e:
                repo.remotes.origin.pull("main").raise_if_error()

            logging.info(f"Updated '{branch}' branch in repository at '{destination_dir}'.")
        else:
            # Clone the repository if the directory does not exist
            git.Repo.clone_from(remote_url, destination_dir, env={"GIT_SSL_NO_VERIFY": "1"})
            logging.info(f"Cloned repository '{remote_repo}' into '{destination_dir}'.")
    except git.GitCommandError as e:
        raise RuntimeError(f"Failed to fetch {remote_url}")

    return destination_dir
