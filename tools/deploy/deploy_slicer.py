import datetime
import git
import importlib
import json
import logging
import os
import patch
import re
import shutil
import subprocess
import sys
import vswhere
import tarfile
import zipfile

from pathlib import Path
from pathvalidate.argparse import sanitize_filepath_arg
from shutil import ignore_patterns
from string import Template
from typing import List


logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stdout))

# Non built-in modules are imported after constants definition

if sys.version_info >= (3, 8):
    xcopytree = lambda a, b, ok: shutil.copytree(a, b, dirs_exist_ok=ok)
else:
    from distutils.dir_util import copy_tree

    xcopytree = lambda a, b, ok: copy_tree(str(a), str(b)) if ok else shutil.copytree(a, b)

THIS_FILE = Path(__file__).resolve().absolute()
THIS_FOLDER = THIS_FILE.parent
DEPLOY_CONFIG = THIS_FOLDER / "slicer_deploy_config.json"
REQUIREMENTS_FILE = THIS_FOLDER / "requirements.txt"
SLICERLTRACE_REPO_FOLDER = THIS_FOLDER.parent.parent
MODULES_PACKAGE_FOLDER = SLICERLTRACE_REPO_FOLDER / "src" / "modules"
LTRACE_PACKAGE_FOLDER = SLICERLTRACE_REPO_FOLDER / "src" / "ltrace"
SUBMODULES_PACKAGE_FOLDER = SLICERLTRACE_REPO_FOLDER / "src" / "submodules"
LTRACE_PACKAGE_LIB_FOLDER = SLICERLTRACE_REPO_FOLDER / "ltrace"

sys.path.append(THIS_FOLDER.parent.as_posix())  # Workaround to import commons.py module
from commons import sanitize_file_path, filter_path_string

GREEN_TAG = "\x1b[32;20m"
RESET_COLOR_TAG = "\x1b[0m"
GREEN_BOLD_TAG = "\x1b[32;1m"

APP_NAME = "GeoSlicer"

IGNORED_DIRS = "Skeleton, SkeletonCLI"

# Third party modules installation
with open(REQUIREMENTS_FILE) as file:
    for line in file:
        if line[0] == "#":
            continue

        if "#" in line:
            module_name = re.split("#|=", line)[0].strip()
            import_name = line.split("#")[-1].strip()
        else:
            module_name = line.split("=")[0]
            import_name = module_name

        if import_name != "mkdocs-localsearch" and import_name != "mkdocs-material":
            try:
                logger.info(f"Importing python module: {import_name}")
                globals()[import_name] = importlib.__import__(import_name)
            except ModuleNotFoundError:
                logger.info(f"Module {import_name} not found, running pip with requirements file")
                python_interpreter = sys.executable
                runResult = subprocess.run([python_interpreter, "-m", "pip", "install", "-r", REQUIREMENTS_FILE])
                runResult.check_returncode()
                globals()[import_name] = importlib.import_module(import_name)


def generate_slicer_package(
    slicer_archive,
    modules_package_folder,
    slicerltrace_repo_folder,
    output_dir,
    version,
    fast_and_dirty,
    args,
):
    if version is None:
        raise ValueError(
            "Production deployment requires a defined version. Please use the flag '--geoslicer-version' to specify it."
        )

    generic_deploy(
        args,
        slicer_archive,
        modules_package_folder,
        slicerltrace_repo_folder,
        output_dir,
        version,
        fast_and_dirty,
        with_porespy_pyedt=args.with_porespy_pyedt,
        development=False,
    )


def deploy_development_environment(
    slicer_archive,
    modules_package_folder,
    slicerltrace_repo_folder,
    output_dir,
    fast_and_dirty,
    keep_name,
    with_porespy_pyedt,
    args,
):
    generic_deploy(
        args,
        slicer_archive,
        modules_package_folder,
        slicerltrace_repo_folder,
        output_dir,
        None,
        fast_and_dirty,
        development=True,
        with_porespy_pyedt=with_porespy_pyedt,
        keep_name=keep_name,
    )


def generic_deploy(
    args,
    slicer_archive,
    modules_package_folder,
    slicerltrace_repo_folder,
    output_dir,
    version,
    fast_and_dirty,
    development,
    with_porespy_pyedt,
    keep_name=False,
):
    public_version = False
    if version is not None:
        parts = version.split(".")
        if len(parts) > 3:
            raise RuntimeError("Invalid version: {}".format(version))

        parsed_version = [0, 0, 0]
        for i in range(len(parts)):
            v = parts[i]
            if "RC" in v:
                v = v.replace("RC", "")
            if "-public" in v:
                public_version = True
                v = v.replace("-public", "")
            assert int(v) >= 0
            parsed_version[i] = str(parts[i])

        version = tuple(parsed_version)

    logger.info("Extracting")
    slicer_dir = extract_archive(slicer_archive, output_dir)

    # Update submodules
    logger.info("Updating submodules...")
    repo = git.Repo(slicerltrace_repo_folder)
    repo.git.submodule("update", "--init", "--recursive")

    # getting the 3D Slicer version
    lib_dir = slicer_dir / "lib"
    lib_dir_subdirs = [f.name for f in lib_dir.iterdir() if f.is_dir()]
    slicer_version = [s[len(APP_NAME) + 1 :] for s in lib_dir_subdirs if APP_NAME + "-" in s][0]
    logger.info("Slicer version " + str(slicer_version))

    if not fast_and_dirty:
        # logger.info("Installing extension dependencies")
        # install_extension_dependencies(slicer_dir)

        logger.info("Uninstalling local packages")
        uninstall_packages(slicer_dir=slicer_dir, package="ltrace")

        logger.info("Installing pip dependencies")
        install_pip_dependencies(slicer_dir, LTRACE_PACKAGE_FOLDER, development)

        microtom_path = modules_package_folder / "MicrotomRemote" / "Libs" / "microtom"
        if (microtom_path / "setup.py").exists():
            uninstall_packages(slicer_dir=slicer_dir, package="microtom")
            install_pip_dependencies(slicer_dir, microtom_path, development)

        # Installing packages from submodules
        for path in find_submodules_setup_directory(SUBMODULES_PACKAGE_FOLDER):
            submodule_name = path.name
            if not with_porespy_pyedt and submodule_name in ["porespy", "pyedt"] and development:
                continue

            logger.info(f"Uninstalling current version from submodule '{submodule_name}'")
            uninstall_packages(slicer_dir=slicer_dir, package=submodule_name)
            logger.info(f"Installing submodule '{submodule_name}'")
            install_module_from_folder(slicer_dir, path, development)

    logger.info("Copying extensions")
    if development:
        modules_to_add = list(find_plugins_source(modules_package_folder))
        modules_to_add.extend(find_cli_source(modules_package_folder))
    else:
        modules_to_add = list(
            copy_extensions(
                slicer_dir,
                find_plugins_source(modules_package_folder),
                "qt-scripted-modules",
                ignore_patterns("*CLI*", "*Test"),
            )
        )
        modules_to_add.extend(copy_extensions(slicer_dir, find_cli_source(modules_package_folder), "cli-modules"))

    logger.info("Building GeoSlicer manual")
    wd = os.getcwd()
    os.chdir(THIS_FOLDER / "GeoSlicerManual")
    output_manual_path_str = (THIS_FOLDER / "Resources" / "manual").as_posix()
    subprocess.check_call([sys.executable, "-m", "mkdocs", "build", "--site-dir", output_manual_path_str])
    os.chdir(wd)

    logger.info("Installing customizer")
    install_customizer(slicer_dir, modules_to_add, find_extensions(slicer_dir), version, development)

    logger.info("Copying assets")
    copy_extra_files(slicer_dir, slicer_version, slicerltrace_repo_folder, fast_and_dirty, development)

    logger.info("Removing unwanted files")
    remove_unwanted_files(slicer_dir, slicer_version)

    logger.info("Copying notebooks")
    copy_notebooks(slicer_dir, modules_package_folder)

    logger.info("Applying patches")
    apply_patches(slicer_dir, slicer_version)

    if not development:
        major, minor, revision = version
        if revision:
            version_string = "{}.{}.{}".format(major, minor, revision)
        else:
            version_string = "{}.{}".format(major, minor)

        version_name = "GeoSlicer-{}".format(version_string)
        archive_folder_name = slicer_dir.with_name(version_name)
        if slicer_dir.name != version_name:
            shutil.move(slicer_dir, archive_folder_name)

        if not fast_and_dirty:
            logger.info("Archiving")
            make_archive(args, archive_folder_name, slicer_archive.with_name(version_name))

        logger.info("Done")


def remove_unwanted_files(slicer_dir, slicer_version):
    with open(DEPLOY_CONFIG) as f:
        config = json.JSONDecoder().decode(f.read())

    for target in config["FilesToRemove"]:
        target = Template(target).substitute(slicer_dir=f"{APP_NAME}-{slicer_version}")
        target = slicer_dir / target
        if target.exists():
            target.unlink()


def copy_extensions(slicer_dir, extensions, location, ignore=None):
    extensions_dir = get_plugins_dir(slicer_dir)
    for source_dir in extensions:
        current_dir = extensions_dir / location / source_dir.name

        if current_dir.exists():
            shutil.rmtree(current_dir)

        shutil.copytree(source_dir, current_dir, ignore=ignore)

        yield current_dir


def find_plugins_source(modules_package_folder):
    for current_path in modules_package_folder.iterdir():
        if current_path.name.endswith(IGNORED_DIRS):
            continue

        if current_path.is_dir() and not current_path.name.endswith("CLI"):
            extension_main_file = current_path / (current_path.name + ".py")
            if extension_main_file.exists():
                yield current_path


def find_cli_source(modules_package_folder, level=1):
    for current_path in modules_package_folder.iterdir():
        if current_path.name.endswith(IGNORED_DIRS):
            continue

        if current_path.name.endswith("CLI"):
            extension_main_file = current_path / (current_path.name + ".py")
            extension_xml_file = current_path / (current_path.name + ".xml")
            if extension_main_file.exists() and extension_xml_file.exists():
                yield current_path
            else:
                yield from find_cli_source(current_path, level=level)
        elif level > 0 and current_path.is_dir():
            yield from find_cli_source(current_path, level=level - 1)


def extract_archive(slicer_archive, output_dir):
    if slicer_archive.is_dir():
        return slicer_archive

    slicer_archive_stem = slicer_archive.stem
    if slicer_archive_stem.endswith(".tar"):
        slicer_archive_stem = slicer_archive_stem[:-4]
    extract_dir = output_dir / slicer_archive_stem

    slicer_archive_str = filter_path_string(slicer_archive.as_posix())
    output_dir_str = filter_path_string(output_dir.as_posix())
    shutil.unpack_archive(slicer_archive_str, output_dir_str)
    return extract_dir


def find_executable(slicer_dir):
    files = [entry for entry in sanitize_file_path(slicer_dir).glob("*Slicer*") if entry.is_file()]
    if len(files) > 0:
        return files[0]
    return None


def install_extension_dependencies(slicer_dir):
    install_extensions_script = THIS_FOLDER / "install_slicer_extensions.py"
    slicer_fp = find_executable(slicer_dir)

    if slicer_fp is None:
        raise ValueError(f"Can't find Slicer or GeoSlicer executable on {slicer_fp}")

    slicer_call = [
        str(slicer_fp),
        "--disable-modules",
        "--python-code",
        "with open(r'{}') as script:\n".format(install_extensions_script)
        + "    exec(script.read())\n"
        + "install_extensions(r'{}')\n".format(DEPLOY_CONFIG)
        + "exit()",
    ]

    logger.info("Running: " + " ".join(slicer_call))
    subprocess.run(slicer_call)


def uninstall_packages(slicer_dir: Path, package: str) -> None:
    slicer_python = slicer_dir / "bin" / "PythonSlicer"
    slicer_python_path_str = filter_path_string(slicer_python.as_posix())
    subprocess.run([slicer_python_path_str, "-m", "pip", "uninstall", "-y", package], check=True)


def install_pip_dependencies(slicer_dir, lib_folder, development=False):
    slicer_python = slicer_dir / "bin" / "PythonSlicer"
    slicer_python_path_str = filter_path_string(slicer_python.as_posix())
    lib_folder_str = filter_path_string(lib_folder.as_posix())
    pip_call = [slicer_python_path_str, "-m", "pip", "install"]
    if development:
        pip_call.append("--editable")
    pip_call.append(lib_folder_str)

    subprocess.run([slicer_python_path_str, "-m", "pip", "install", "--upgrade", "pip==22.3", "setuptools==59.8.0"])
    runResult = subprocess.run(pip_call)
    runResult.check_returncode()


def install_module_from_folder(slicer_dir, folder, development=False):
    slicer_python = slicer_dir / "bin" / "PythonSlicer"
    slicer_python_path_str = filter_path_string(slicer_python.as_posix())
    folder_str = filter_path_string(folder.as_posix())
    pip_call = [slicer_python_path_str, "-m", "pip", "install"]
    if development:
        pip_call.append("--editable")
    pip_call.append(folder_str)

    runResult = subprocess.run(pip_call)
    runResult.check_returncode()


def find_extensions(slicer_dir):
    extensions_dir = slicer_dir / "extensions"
    if not extensions_dir.exists():
        return []

    paths = []
    for extension in extensions_dir.iterdir():
        if not extension.is_dir():
            continue

        paths.extend(get_plugins_dir(extension).glob("*-modules"))

    return paths


def install_customizer(slicer_dir, modules, extensions, version, dev_environment):
    def format_string_list_to_write(l):
        strings = [repr("{}".format(s)) for s in l]
        return "[\n            {}\n        ]".format(",\n            ".join(strings))

    paths = modules + extensions
    if dev_environment:
        formatted_paths = format_string_list_to_write(paths)
    else:
        formatted_paths = format_string_list_to_write((p.relative_to(slicer_dir) for p in paths))
        paths = (p.relative_to(slicer_dir) for p in paths)

    ltrace_modules_whitelist = []
    for module in modules:
        if module.name.lower().endswith("cli"):
            continue
        module_file = module / (module.name + ".py")
        assert module_file.is_file()
        with open(module_file, encoding="utf-8") as m:
            content = m.read()
            if f"class {module.name}" in content:
                ltrace_modules_whitelist.append(module.name)
            else:
                logger.info(
                    f"Warning: Class {module.name} not found in {module_file.name}. It will not be visible in the menu."
                )

    with open(THIS_FOLDER / "Customizer.py") as f:
        customizer_source = f.read()

    formatted_whitelist = format_string_list_to_write(ltrace_modules_whitelist)

    repo = git.Repo(path=SLICERLTRACE_REPO_FOLDER, search_parent_directories=True)

    plugins_folder_path = sanitize_file_path(get_plugins_dir(slicer_dir))
    customizer_source_path = plugins_folder_path / "qt-scripted-modules" / "Customizer.py"
    with open(customizer_source_path, "w") as f:
        f.write(customizer_source)

    json_output = {
        "name": "WelcomeGeoSlicer",
        "itk_module": None,
        "CUSTOM_REL_PATHS": [str(p) for p in paths],
        "VISIBLE_LTRACE_PLUGINS": ltrace_modules_whitelist,
        "GEOSLICER_VERSION": version,
        "GEOSLICER_HASH": repr(repo.head.object.hexsha),
        "GEOSLICER_HASH_DIRTY": repr(repo.is_dirty()),
        "GEOSLICER_BUILD_TIME": str(datetime.datetime.now()),
        "GEOSLICER_DEV_ENVIRONMENT": repr(dev_environment),
    }

    json_path = plugins_folder_path / "qt-scripted-modules" / "Resources" / "json" / "WelcomeGeoSlicer.json"
    with open(json_path, "w") as json_file:
        json.dump(json_output, json_file, indent=4)


def copy_notebooks(slicer_dir, modules_package_folder):
    notebooks_dir = modules_package_folder / "Notebooks"
    target_dir = slicer_dir / "Notebooks"
    if target_dir.exists():
        shutil.rmtree(target_dir)

    copy_file_or_tree(notebooks_dir, target_dir, exist_ok=True)


def copy_extra_files(slicer_dir, slicer_version, repo_folder, fast_and_dirty, development):
    for source, target in _get_extra_files_to_copy(slicer_version):
        is_glob = source.endswith("*")
        if is_glob:
            source = source[:-1]
        source = repo_folder / source
        target = slicer_dir / target
        if not source.exists():
            raise RuntimeError(f"Required file {source.as_posix()} doesn't exist.")

        if source.suffix == ".zip" and target.is_dir():
            with zipfile.ZipFile(source, "r") as zip_file:
                zip_file.extractall(target)
        elif source.suffix == ".xz" and target.is_dir():
            with tarfile.open(source, "r:xz") as zip_file:
                zip_file.extractall(target)
        elif is_glob:
            for f in source.iterdir():
                copy_file_or_tree(f, target, exist_ok=True)
        else:
            copy_file_or_tree(source, target, exist_ok=True)

        # replacing slicer version placeholders
        if target.suffix == ".ini":
            _update_slicer_version_placeholders(target, slicer_version, repo_folder)

    if sys.platform.startswith("win32") and not fast_and_dirty and not development:
        copy_windows_dlls(slicer_dir)


def _get_extra_files_to_copy(slicer_version):
    with open(DEPLOY_CONFIG) as f:
        config = json.JSONDecoder().decode(f.read())

    for e in config["ExtraFilesToCopy"]:
        # replacing slicer version placeholders
        template_dict = {"slicer_dir": f"{APP_NAME}-{slicer_version}"}
        e = [Template(s).substitute(**template_dict) for s in e]

        if len(e) == 2:
            yield e
            continue

        platform, source, target = e
        assert platform in ["windows", "linux"]
        if sys.platform.startswith("win32") and platform == "windows":
            yield source, target
        elif sys.platform.startswith("linux") and platform == "linux":
            yield source, target


def _update_slicer_version_placeholders(source: Path, slicer_version: str, repo_folder: Path):
    with open(repo_folder / source) as f:
        newText = f.read()
        newText = Template(newText).substitute(slicer_dir=f"{APP_NAME}-{slicer_version}")
    with open(repo_folder / source, "w") as f:
        f.write(newText)


def apply_patches(slicer_dir, slicer_version):
    with open(DEPLOY_CONFIG) as f:
        config = json.JSONDecoder().decode(f.read())

    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    patches = config["Patches"].get(platform, [])
    for patch_folder_name, target_folder, strip_folders in patches:
        patch_folder = THIS_FOLDER / "Patches" / patch_folder_name
        target_folder = Template(target_folder).substitute(slicer_dir=f"{APP_NAME}-{slicer_version}")
        target_folder = slicer_dir / target_folder
        for patch_file in sorted(patch_folder.glob("*.patch")):
            patch_set = patch.fromfile(patch_file)
            patch_set.apply(strip=strip_folders, root=target_folder)


def rename_executable(slicer_dir):
    extension = ".exe" if sys.platform.startswith("win32") else ""

    slicer = slicer_dir / ("Slicer" + extension)
    geoslicer = slicer.with_name("GeoSlicer" + extension)
    if slicer.exists():
        shutil.move(slicer, geoslicer)

    slicer_real = slicer_dir / "bin" / ("SlicerApp-real" + extension)
    geoslicer_real = slicer_real.with_name("GeoSlicerApp-real" + extension)
    if slicer_real.exists():
        shutil.move(slicer_real, geoslicer_real)


def copy_windows_dlls(slicer_dir):
    files_to_copy = []
    cuda_path_environment = os.environ.get("CUDA_PATH_V11_2")
    if cuda_path_environment is None:
        raise RuntimeError("CUDA_PATH_V11_2 environment variable not defined")

    cuda_bin = Path(cuda_path_environment) / "bin"
    if not cuda_bin.is_dir():
        raise RuntimeError("CUDA_PATH_V11_2 points to an invalid directory")

    for dll in cuda_bin.glob("*.dll"):
        if dll.name in ["cudart32_110.dll"]:
            continue

        files_to_copy.append(dll)

    if len(re.findall(r"cudnn64_\d+.dll", ",".join(dll.name for dll in files_to_copy))) == 0:
        raise RuntimeError("cudnn64_*.dll not found")

    vs_path_candidates = [i["installationPath"] for i in vswhere.find()]
    version_paths = []
    for vs_path in vs_path_candidates:
        msvc_path = Path(vs_path, "VC", "Redist", "MSVC")
        version_paths += list(msvc_path.glob("*.*.*"))
    from packaging import version

    versions = [(version.parse(path.name), path) for path in version_paths]
    versions.sort(reverse=True)

    min_version = version.parse("14.26.0")
    for version, path in versions:
        if version < min_version:
            raise RuntimeError(f"MSVC minimum requirement ({min_version.public}) not met")
        crt_path = list(path.joinpath("x64").glob("*.CRT"))
        if len(crt_path) >= 1:
            crt_path = crt_path[0]
            break
    else:
        raise RuntimeError(".CRT folder not found (MSVC installation)")

    files_to_copy.extend(crt_path.glob("*.dll"))

    target_dir = slicer_dir / "bin"
    for dll in files_to_copy:
        try:
            shutil.copy2(dll, target_dir)
        except:
            pass


def copy_file_or_tree(source, target_dir, exist_ok=False):
    assert source.exists()

    if source.is_dir():
        xcopytree(source, target_dir / source.name, exist_ok)
    else:
        shutil.copy2(source, target_dir)


def make_archive(args, source_dir, target_file_without_extension):
    if args.sfx:
        ext = ".exe" if sys.platform == "win32" else ".sfx"
        packager = "7zG" if sys.platform == "win32" else "7z"
        target = target_file_without_extension.parent / f"{target_file_without_extension.name}{ext}"
        target_str = filter_path_string(target.as_posix())
        source_dir_str = filter_path_string(source_dir.as_posix())
        command = [packager, "a", target_str, "-mx5", "-sfx", source_dir_str]
        subprocess.run(command, shell=False, capture_output=True)

    else:
        archive_format = "zip" if sys.platform == "win32" else "gztar"
        result = shutil.make_archive(
            filter_path_string(target_file_without_extension.name),
            archive_format,
            root_dir=source_dir.parent,
            base_dir=source_dir.name,
        )

        result = sanitize_file_path(result)
        target = target_file_without_extension.with_name(result.name)
        shutil.move(result, target)

    return target


def get_plugins_dir(parent_dir):
    matches = list((parent_dir / "lib").glob("*GeoSlicer-*"))
    assert len(matches) == 1, f"matches: {matches} - parent_dir {parent_dir}"
    return matches[0]


def make_directory_writable(func=None, path=None, exc_info=None):
    """
    Error handler for ``shutil.rmtree``.

    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.

    If the error is for another reason it re-raises the error.

    Usage : ``shutil.rmtree(path, onerror=make_directory_writable)``
    """
    if path is None:
        raise RuntimeError("Invalid path.")

    import stat

    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        if func is not None:
            func(path)


def remove_directory_recursively(path: Path):
    if not path.exists():
        return

    make_directory_writable(path=path.as_posix())
    shutil.rmtree(path.as_posix(), onerror=make_directory_writable)


def commit_to_opensource_repository(args, force):
    """Commits current opensource code to the public repository

    Args:
        ltrace_repo (str): Directory to the SlicerLTrace repository
        force (bool): If False, only commit the changes if the current version has a tag and this tag is not for a RC,
                      otherwise commit the changes anyway.
    """

    if args.no_public_commit:
        logger.info("Skipping commit to public repository' step because it is disabled.")
        return
    local_public_master_branch_name = "GeoSlicerPublic_Master"
    remote_public_master_branch_name = "master"
    public_remote_repository_name = "GeoSlicerPublic"
    public_remote_repository_path = "git@bitbucket.org:ltrace/geoslicerpublic.git"

    # Fetch public repository
    repository = git.Repo(SLICERLTRACE_REPO_FOLDER)
    working_repository_name = repository.remotes.origin.url.split(".git")[0].split("/")[-1]

    if working_repository_name.lower() == public_remote_repository_name.lower():
        logger.info(f"Skipping commit to public repository' step because it is the current working repository.")
        return

    if public_remote_repository_name not in repository.remotes:
        repository.create_remote(public_remote_repository_name, public_remote_repository_path)
    try:
        repository.remotes[public_remote_repository_name].fetch()
        public_master_reference = repository.remotes[public_remote_repository_name].refs[
            remote_public_master_branch_name
        ]
    except IndexError:
        public_master_reference = None

    # Get tag name
    if force:
        tag_name = repository.git.describe("--tags")
    else:
        try:
            tag_name = repository.git.describe("--tags", "--exact-match")
        except git.exc.GitCommandError:
            logger.info("Nothing will be commited to the public repository as there's no tag in current commit")
            clean_repository_changes()
            return
        if "RC" in tag_name:
            logger.info("Nothing will be commited to the public repository because the tag is a RC")
            clean_repository_changes()
            return

    # Add only opensource files
    origin_reference = repository.head.reference
    try:
        repository.delete_head(local_public_master_branch_name, force=True)
    except git.exc.GitCommandError:
        pass
    if public_master_reference:
        repository.create_head(local_public_master_branch_name).checkout()
        repository.head.reset(public_master_reference)
    else:
        repository.git.checkout("--orphan", local_public_master_branch_name)

    repository.git.add(all=True)

    # Commit and push
    try:
        repository.git.commit("-m", tag_name, "--no-verify")
        repository.git.push(
            public_remote_repository_name, local_public_master_branch_name + ":" + remote_public_master_branch_name
        )
        logger.info(
            f"Git push executed succesfully! Cleaning environment and checking out to previously branch: {origin_reference}"
        )
    except git.exc.GitCommandError as error:
        logger.info(f"Unable to execute git commands:\n{error}")
    finally:
        repository.git.clean("-fd")
        repository.git.reset("--hard")
        repository.git.checkout(origin_reference)


def remove_closed_source_files():
    repository = git.Repo(SLICERLTRACE_REPO_FOLDER, search_parent_directories=True)
    with open(DEPLOY_CONFIG) as f:
        config = json.JSONDecoder().decode(f.read())
        for file_or_path in config["ClosedSourceFiles"]:
            path = SLICERLTRACE_REPO_FOLDER / file_or_path
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                if "submodules" in path.parent.name:
                    repository.git.submodule("deinit", "-f", path.resolve().as_posix())
                    repository.git.rm(path, r=True)
                    git_module_path = SLICERLTRACE_REPO_FOLDER / ".git" / "modules" / path.name
                    remove_directory_recursively(git_module_path)

                remove_directory_recursively(path)

    remove_module_test_directories()


def remove_module_test_directories():
    for path in MODULES_PACKAGE_FOLDER.rglob("*/Test/"):
        if not path.is_dir():
            continue

        shutil.rmtree(path)


def add_open_source_files():
    repository = git.Repo(SLICERLTRACE_REPO_FOLDER, search_parent_directories=True)
    with open(DEPLOY_CONFIG) as f:
        config = json.JSONDecoder().decode(f.read())
        for file_or_path in config["OpenSourceRepoFiles"]:
            src_path = SLICERLTRACE_REPO_FOLDER / file_or_path[0]
            dst_path = SLICERLTRACE_REPO_FOLDER / file_or_path[1]
            if src_path.is_file():
                shutil.copy(src_path, dst_path)
                repository.git.add(dst_path.resolve().as_posix())


def find_submodules_setup_directory(path: Path) -> List:
    setup_dir_list = []

    for filename in ["setup.py", "pyproject.toml"]:
        setup_base_dir = [file_path.parent for file_path in path.rglob(filename)]
        setup_dir_list.extend(setup_base_dir)

    return set(setup_dir_list)


def clean_repository_changes():
    repository = git.Repo(SLICERLTRACE_REPO_FOLDER)
    repository.git.clean("-fd")
    repository.git.reset("--hard")


def prepare_open_source_environment():
    """Modify the repository files to prepare it for the public version's deployment .

    Raises:
        RuntimeError: When the current work directory has modified files.
        RuntimeError: When an error occurs during environment's modification.
    """

    repository = git.Repo(SLICERLTRACE_REPO_FOLDER)

    if repository.git.status("--porcelain"):
        raise RuntimeError(
            "Cancelling process because the current work directory has modified files. Please commit or discard the changes."
        )

    try:
        remove_closed_source_files()
        add_open_source_files()
    except Exception as error:
        repository.git.clean("-fd")
        repository.git.reset("--hard")
        raise RuntimeError(f"Cancelling process due to an error:\n{error}")


def run(args):
    if args.archive:
        slicer_archive = sanitize_file_path(args.archive)
        output_dir = slicer_archive.parent
    elif not args.public_commit_only:
        logger.info("error: the following arguments are required: archive")
        exit(1)

    # Checking for __init__.py files on ltrace lib dir
    if not args.dev:
        no_init_list = []
        for d in LTRACE_PACKAGE_LIB_FOLDER.rglob("**/"):
            # Directories with data or assets don't need init files
            if not any([x in str(d) for x in ["__pycache__", "assets", "Resources", "resources"]]):
                no_init_list.append(d)

        if len(no_init_list) > 0:
            raise RuntimeError(
                "The following ltrace lib modules does not contain a __init__.py file: " + str(no_init_list)
            )

    if args.geoslicer_version and args.dev:
        raise RuntimeError("Unable to deploy the development version together with production version")

    if args.no_public_commit and args.public_commit_only:
        raise RuntimeError("Unable to avoid public commit if you want only to make the public commit.")

    if args.dev and args.public_commit_only:
        raise RuntimeError("Unable to make the commit to the public repository with the development version.")

    if args.dev:
        if args.generate_public_version:
            prepare_open_source_environment()

        try:
            deploy_development_environment(
                slicer_archive,
                MODULES_PACKAGE_FOLDER,
                SLICERLTRACE_REPO_FOLDER,
                output_dir,
                fast_and_dirty=args.fast_and_dirty,
                keep_name=args.keep_name,
                with_porespy_pyedt=args.with_porespy_pyedt,
                args=args,
            )
        except Exception as error:
            if args.generate_public_version:
                clean_repository_changes()

            raise error
        else:
            if args.generate_public_version:
                logger.info(
                    f"\n{GREEN_TAG}The application's public version has been deployed in {GREEN_BOLD_TAG}development{RESET_COLOR_TAG}{GREEN_TAG} mode."
                )
                logger.info(
                    "The working directory has modified files, so don't forget to reset it before doing any changes."
                )
                logger.info(
                    f"You can do it by using the following git commands: 'git clean -fd ; git reset --hard'{RESET_COLOR_TAG}"
                )
            else:
                logger.info(
                    f"\n{GREEN_TAG}The application's extended version has been deployed in {GREEN_BOLD_TAG}development{RESET_COLOR_TAG}{GREEN_TAG} mode.{RESET_COLOR_TAG}"
                )
    elif args.public_commit_only:
        prepare_open_source_environment()
        commit_to_opensource_repository(args, force=True)
    else:  # Production mode
        if args.generate_public_version:
            prepare_open_source_environment()

        try:
            generate_slicer_package(
                slicer_archive,
                MODULES_PACKAGE_FOLDER,
                SLICERLTRACE_REPO_FOLDER,
                output_dir,
                args.geoslicer_version,
                fast_and_dirty=args.fast_and_dirty,
                args=args,
            )
        except Exception as error:
            if args.generate_public_version:
                clean_repository_changes()

            raise error

        if args.generate_public_version:
            commit_to_opensource_repository(args, force=False)

        if args.generate_public_version:
            logger.info(
                f"\n{GREEN_TAG}The application's public version has been deployed in {GREEN_BOLD_TAG}production{RESET_COLOR_TAG}{GREEN_TAG} mode.{RESET_COLOR_TAG}"
            )
            if args.no_public_commit:
                logger.info(
                    f"{GREEN_TAG}The working directory has modified files, so don't forget to reset it before doing any changes."
                )
                logger.info(
                    f"You can do it by using the following git commands: 'git clean -fd ; git reset --hard'.{RESET_COLOR_TAG}"
                )
        else:
            logger.info(
                f"{GREEN_TAG}The application's extended version has been deployed in {GREEN_BOLD_TAG}production{RESET_COLOR_TAG}{GREEN_TAG} mode.{RESET_COLOR_TAG}"
            )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Configures a clean Slicer download for deploy or development.")
    parser.add_argument(
        "archive",
        help="Geoslicer instalation downloaded from the LTrace repo. Either the .tar file or the extracted folder.",
        nargs="?",
        type=sanitize_filepath_arg,
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Install development environment instead of generating artifact.",
        default=False,
    )
    parser.add_argument(
        "--keep-name",
        action="store_true",
        help="Maintains name as 3D Slicer, avoiding Windows incompatibility with current instalations.",
        default=False,
    )
    parser.add_argument(
        "--fast-and-dirty",
        action="store_true",
        help="Don't install extensions, pip packages, don't copy msvc redist and cuda dlls to slicer folder, don't archive.",
        default=False,
    )

    parser.add_argument(
        "--geoslicer-version", help="Version number to use for GeoSlicer. Examples: 1, 1.2, 1.2.3", default=None
    )

    parser.add_argument(
        "--public-commit-only",
        action="store_true",
        help="Commit the changes in the opensource code to the public repository",
        default=False,
    )
    parser.add_argument(
        "--generate-public-version",
        action="store_true",
        help="Deploy the application's public version. When in deploying production version, it also git commit to the opensource code's repository",
        default=False,
    )
    parser.add_argument(
        "--sfx",
        action="store_true",
        help="Create Self-Extracting File instead of the compreesed file",
        default=False,
    )
    parser.add_argument(
        "--with-porespy-pyedt",
        action="store_true",
        help="Install porespy and pyedt as editable local submodules for development",
        default=False,
    )
    parser.add_argument(
        "--no-public-commit",
        action="store_true",
        help="Avoid commiting to the opensource code repository",
        default=False,
    )
    run(parser.parse_args())