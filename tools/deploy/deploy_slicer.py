import argparse
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
import traceback
import zipfile

from pathlib import Path
from shutil import ignore_patterns
from string import Template
from typing import List, Union


class FlushStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(FlushStreamHandler(sys.stdout))

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

GREEN_TAG = "\x1b[32;20m"
RESET_COLOR_TAG = "\x1b[0m"
GREEN_BOLD_TAG = "\x1b[32;1m"

APP_NAME = "GeoSlicer"

IGNORED_DIRS = "Skeleton, SkeletonCLI"


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
        development=False,
    )


def deploy_development_environment(
    slicer_archive,
    modules_package_folder,
    slicerltrace_repo_folder,
    output_dir,
    fast_and_dirty,
    keep_name,
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
        keep_name=keep_name,
    )


def generic_deploy(
    args,
    slicer_archive,
    modules_package_folder,
    slicerltrace_repo_folder,
    output_dir,
    version_string: str,
    fast_and_dirty,
    development,
    keep_name=False,
):
    logger.info("Extracting")
    slicer_dir: Path = extract_archive(slicer_archive, output_dir)

    # Update submodules
    if args.no_git:
        logger.info("Skipping submodule update (--no-git).")
    else:
        logger.info("Updating submodules...")
        repo = git.Repo(slicerltrace_repo_folder)
        repo.git.submodule("update", "--init", "--recursive")

    # getting the 3D Slicer version
    slicer_version = get_slicer_version(slicer_dir)
    logger.info("Slicer version " + str(slicer_version))
    apply_pre_patches(slicer_dir, slicer_version)

    if args.no_pip and not fast_and_dirty:
        logger.info("Skipping pip dependency installation (--no-pip).")

    if not fast_and_dirty and not args.no_pip:
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
            if (
                args.without_porespy
                and submodule_name
                in [
                    "porespy",
                ]
                and development
            ):
                continue

            logger.info(f"Uninstalling current version from submodule '{submodule_name}'")
            uninstall_packages(slicer_dir=slicer_dir, package=submodule_name)
            logger.info(f"Installing submodule '{submodule_name}'")
            install_module_from_folder(slicer_dir, path, development)

        # Last, deliberately: anything installed after this can pull the GUI
        # OpenCV back in as a dependency and reintroduce the second Qt.
        enforce_headless_opencv(slicer_dir)

    logger.info("Copying extensions")
    if development:
        modules_to_add = list(find_plugins_source(modules_package_folder))
        modules_to_add.extend(find_cli_source(modules_package_folder))
    else:
        if args.keep_tests:
            discarded_patterns = ("*CLI",)
        else:
            discarded_patterns = ("*CLI", "*Test")
        modules_to_add = list(
            copy_extensions(
                slicer_dir,
                find_plugins_source(modules_package_folder),
                "qt-scripted-modules",
                ignore_patterns(*discarded_patterns),
            )
        )
        modules_to_add.extend(copy_extensions(slicer_dir, find_cli_source(modules_package_folder), "cli-modules"))

    logger.info("Building GeoSlicer manual")
    build_manual()

    logger.info("Installing customizer")
    install_customizer(
        slicer_dir,
        modules_to_add,
        find_extensions(slicer_dir),
        version_string,
        development,
        use_git=not args.no_git,
    )

    logger.info("Copying assets")
    copy_extra_files(slicer_dir, slicer_version, slicerltrace_repo_folder, fast_and_dirty, development)

    logger.info("Removing unwanted files")
    remove_unwanted_files(slicer_dir, slicer_version)

    logger.info("Copying notebooks")
    copy_notebooks(slicer_dir, modules_package_folder)

    if args.plugin_to_geolog:
        subprocess.run(
            [
                sys.executable,
                "./tools/deploy/Geolog/plugin_to_geolog.py",
                "--geolog-path",
                args.plugin_to_geolog,
                "--geoslicer-path",
                slicer_dir,
            ]
        )

    logger.info("Applying patches")
    apply_patches(slicer_dir, slicer_version)

    if not development:
        version_name = "GeoSlicer-{}".format(version_string)
        archive_folder_name = slicer_dir.with_name(version_name)
        if args.output_dir is not None:
            archive_folder_name = Path(args.output_dir) / version_name

        if slicer_dir.name != version_name:
            try:
                shutil.move(slicer_dir, archive_folder_name)
            except OSError:
                # Ignoring Windows issue related to access denied
                # when trying to remove the file from the older path
                pass

        sign_code(args, archive_folder_name)

        if not fast_and_dirty and not args.disable_archiving:
            logger.info("Archiving")
            make_archive(args, archive_folder_name, slicer_archive.with_name(version_name))


def sign_code(args: argparse.Namespace, archive_folder_name: Path) -> None:
    if not args.code_signed:
        logger.info("Skipping code signing process.")
        return

    if not sys.platform.startswith("win32"):
        logger.info("Skipping code signing due to platform incompatibility.")
        return

    logger.info("Remote code signing...")
    exe_to_sign = archive_folder_name / f"{APP_NAME}.exe"
    if exe_to_sign.exists():
        codesign_script = SLICERLTRACE_REPO_FOLDER / "tools" / "pipeline" / "remote_codesign.py"
        try:
            subprocess.run(
                [
                    sys.executable,
                    str(codesign_script),
                    "--server",
                    args.codesign_server,
                    "--user",
                    args.codesign_user,
                    "--key",
                    args.codesign_key,
                    "--port",
                    str(args.codesign_port),
                    "--exe",
                    str(exe_to_sign),
                ],
                check=True,
            )
            logger.info("Code signing successful.")
        except subprocess.CalledProcessError as e:
            logger.error(f"Code signing failed: {e}. {traceback.format_exc()}. Skipping code signing.")
    else:
        logger.error(f"Executable not found at {exe_to_sign}. Skipping code signing.")


def parse_output_dir(args: argparse.Namespace) -> Union[Path, None]:
    """Parse the output path argument.

    Args:
        args (argsparse.Namespace): The output path argument.

    Returns:
        Union[Path, None]: The path to the output directory or None if no output path is provided.
    """
    if args.output_dir is None or not args.output_dir.strip():
        return None

    path = Path(args.output_dir)
    if path.is_dir():
        return path

    return path.parent


def get_slicer_version(slicer_dir: Path) -> str:
    lib_dir = slicer_dir / "lib"
    lib_dir_subdirs = [f.name for f in lib_dir.iterdir() if f.is_dir()]
    slicer_version = [s[len(APP_NAME) + 1 :] for s in lib_dir_subdirs if APP_NAME + "-" in s][0]
    return slicer_version


def remove_unwanted_files(slicer_dir, slicer_version):
    with open(DEPLOY_CONFIG) as f:
        config = json.JSONDecoder().decode(f.read())

    platform = "linux" if sys.platform.startswith("linux") else "win32"
    files_to_remove = config["FilesToRemove"].get(platform, [])
    for target in files_to_remove:
        target = Template(target).substitute(slicer_dir=f"{APP_NAME}-{slicer_version}")
        target = slicer_dir / target
        if target.exists():
            target.unlink()


def copy_extensions(slicer_dir, extensions, location, ignore=None):
    extensions_dir = get_plugins_dir(slicer_dir)
    for source_dir in extensions:
        current_dir = extensions_dir / location / source_dir.name

        if current_dir.exists():
            shutil.rmtree(current_dir, onexc=make_directory_writable)

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


def extract_archive(slicer_archive, output_dir: Path):
    if slicer_archive.is_dir():
        return slicer_archive

    slicer_archive_stem = slicer_archive.stem
    if slicer_archive_stem.endswith(".tar"):
        slicer_archive_stem = slicer_archive_stem[:-4]
    extract_dir = output_dir / slicer_archive_stem

    shutil.unpack_archive(str(slicer_archive), str(output_dir))
    return extract_dir


def find_executable(slicer_dir):
    files = [entry for entry in Path(slicer_dir).glob("*Slicer*") if entry.is_file()]
    if len(files) > 0:
        return files[0]
    return None


def uninstall_packages(slicer_dir: Path, package: str) -> None:
    slicer_python = slicer_dir / "bin" / "PythonSlicer"
    subprocess.run([str(slicer_python), "-m", "pip", "uninstall", "-y", package], check=True)


def install_pip_dependencies(slicer_dir, lib_folder, development=False):
    slicer_python = slicer_dir / "bin" / "PythonSlicer"
    pip_call = [str(slicer_python), "-m", "pip", "install"]
    if development:
        pip_call.append("--editable")
    pip_call.append(str(lib_folder))

    subprocess.run([str(slicer_python), "-m", "pip", "install", "--upgrade", "pip==25.3", "setuptools==80.10.1"])
    runResult = subprocess.run(pip_call)
    runResult.check_returncode()


OPENCV_GUI_PACKAGES = ("opencv-python", "opencv-contrib-python")
OPENCV_HEADLESS_PACKAGE = "opencv-python-headless"


def _site_packages(slicer_python: Path) -> Union[Path, None]:
    try:
        result = subprocess.run(
            [str(slicer_python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, OSError) as error:
        logger.warning(f"Could not locate site-packages. Cause: {repr(error)}")
        return None


def _headless_opencv_requirement() -> str:
    """The opencv-python-headless pin as ltrace's requirements declare it."""
    requirements = LTRACE_PACKAGE_FOLDER / "requirements.txt"
    try:
        for line in requirements.read_text().splitlines():
            entry = line.split("#", 1)[0].strip()
            if entry.replace("_", "-").lower().startswith(OPENCV_HEADLESS_PACKAGE):
                return entry
    except OSError as error:
        logger.warning(f"Could not read {requirements}. Cause: {repr(error)}")

    return OPENCV_HEADLESS_PACKAGE


def enforce_headless_opencv(slicer_dir: Path) -> None:
    """Leave exactly one OpenCV installed, the headless one.

    mmcv, mmengine and sahi all declare a dependency on the GUI `opencv-python`,
    so pip installs it regardless of what ltrace's requirements pin. Both wheels
    own `cv2/`, and whichever lands last wins. When it is the GUI build, its
    cv2 extension links its own bundled Qt 5:

        cv2.abi3.so -> libQt5Core / libQt5Gui / libQt5Widgets / libQt5Test

    so the first `import cv2` loads a SECOND complete Qt into the process,
    beside Slicer's own. Qt's font database, font cache and platform plugin
    registry are process-global singletons; two copies of them corrupt each
    other, and the application dies inside
    QTextEngine::shapeTextWithHarfbuzzNG while painting a QTextEdit -- a
    segfault whose stack says nothing about its cause.

    Must run LAST, after every other pip install, and with --no-deps: without
    it pip re-resolves mmcv/mmengine/sahi and puts the GUI build straight back.
    """
    slicer_python = slicer_dir / "bin" / "PythonSlicer"
    requirement = _headless_opencv_requirement()

    logger.info("Enforcing a single, headless OpenCV")
    # check=False: having nothing to uninstall is not a failure.
    subprocess.run(
        [str(slicer_python), "-m", "pip", "uninstall", "-y", *OPENCV_GUI_PACKAGES, OPENCV_HEADLESS_PACKAGE],
        check=False,
    )
    subprocess.run([str(slicer_python), "-m", "pip", "install", "--no-deps", requirement]).check_returncode()

    site_packages = _site_packages(slicer_python)
    if site_packages is None:
        logger.warning("Skipping the OpenCV Qt check: site-packages was not found.")
        return

    # Uninstalling leaves the bundled-library folder behind, and the Qt inside
    # it is still reachable through a stale RPATH.
    for stale in ("opencv_python.libs", "opencv_contrib_python.libs"):
        folder = site_packages / stale
        if folder.exists():
            logger.info(f"Removing leftover {folder}")
            shutil.rmtree(folder, ignore_errors=True)

    leftovers = sorted(str(path) for path in site_packages.glob("opencv*/**/*Qt5*"))
    if leftovers:
        raise RuntimeError(
            "OpenCV still ships Qt libraries after the headless reinstall, which will crash "
            "GeoSlicer in Qt text rendering: " + ", ".join(leftovers)
        )

    logger.info(f"OpenCV pinned to {requirement}, with no Qt of its own")


def install_module_from_folder(slicer_dir, folder, development=False):
    slicer_python = slicer_dir / "bin" / "PythonSlicer"
    pip_call = [str(slicer_python), "-m", "pip", "install"]
    if development:
        pip_call.append("--editable")
    pip_call.append(str(folder))

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


UNKNOWN_COMMIT_HASH = "unknown"


def get_repo_metadata(use_git=True):
    """Return the ``(hash, dirty)`` pair stamped into GeoSlicer.json.

    GitPython resolves the repository from the working tree, so it fails
    outright when that tree is a git worktree whose gitdir link points somewhere
    the current environment cannot see (a container mounting only the worktree,
    for instance). The pair is build metadata shown in the window title, not
    something the application needs to run, so ``--no-git`` trades it for
    placeholders instead of blocking the deploy.

    The hash is always a string: parseApplicationVersion slices it.
    """
    if not use_git:
        return UNKNOWN_COMMIT_HASH, False

    repo = git.Repo(path=SLICERLTRACE_REPO_FOLDER, search_parent_directories=True)
    return repo.head.object.hexsha, repo.is_dirty()


def install_customizer(slicer_dir, modules, extensions, version, dev_environment, use_git=True):
    src_path = THIS_FOLDER / "slicerrc.py"
    dest_path = slicer_dir / ".slicerrc.py"

    shutil.copy(src_path, dest_path)

    commit_hash, is_dirty = get_repo_metadata(use_git)

    if dev_environment:
        module_dir = modules[0].parent
    else:
        module_dir = modules[0].parent.relative_to(slicer_dir)

    json_output = {
        "name": "GeoSlicer",
        "itk_module": None,
        "GEOSLICER_VERSION": version,
        "GEOSLICER_HASH": repr(commit_hash),
        "GEOSLICER_HASH_DIRTY": repr(is_dirty),
        "GEOSLICER_BUILD_TIME": str(datetime.datetime.now()),
        "GEOSLICER_DEV_ENVIRONMENT": repr(dev_environment),
        "GEOSLICER_MODULES": str(module_dir),
    }

    json_path = get_plugins_dir(slicer_dir) / "qt-scripted-modules" / "Resources" / "json" / "GeoSlicer.json"
    with open(json_path, "w") as json_file:
        json.dump(json_output, json_file, indent=4)


def copy_notebooks(slicer_dir, modules_package_folder):
    notebooks_dir = modules_package_folder / "Notebooks"
    target_dir = slicer_dir / "Notebooks"
    if target_dir.exists():
        shutil.rmtree(target_dir, onexc=make_directory_writable)

    copy_file_or_tree(notebooks_dir, target_dir, exist_ok=True)


def copy_extra_files(slicer_dir, slicer_version, repo_folder, fast_and_dirty, development):
    for source, target in _get_extra_files_to_copy(slicer_version):
        is_glob = source.endswith("*")
        if is_glob:
            source = source[:-1]
        source = repo_folder / Path(source)
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


def _update_slicer_version_placeholders(source, slicer_version, repo_folder):
    with open(repo_folder / Path(source)) as f:
        newText = f.read()
        newText = Template(newText).substitute(slicer_dir=f"{APP_NAME}-{slicer_version}")
    with open(repo_folder / Path(source), "w") as f:
        f.write(newText)


def apply_patches(slicer_dir, slicer_version, config_key="Patches"):
    with open(DEPLOY_CONFIG) as f:
        config = json.JSONDecoder().decode(f.read())

    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    patches = config[config_key].get(platform, [])
    for patch_folder_name, target_folder, strip_folders in patches:
        patch_folder = THIS_FOLDER / "Patches" / patch_folder_name
        target_folder = Template(target_folder).substitute(slicer_dir=f"{APP_NAME}-{slicer_version}")
        target_folder = slicer_dir / Path(target_folder)
        for patch_file in sorted(patch_folder.glob("*.patch")):
            print(f"Applying patch {patch_file} to {target_folder}")
            patch_set = patch.fromfile(patch_file)
            if patch_set:
                patch_set.apply(strip=strip_folders, root=target_folder)


def apply_pre_patches(slicer_dir, slicer_version):
    try:
        apply_patches(slicer_dir, slicer_version, config_key="PrePatches")
    except Exception as e:
        logger.exception(f"Error applying pre-patches: {e}")


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
    vs_path_candidates = [i["installationPath"] for i in vswhere.find(products="*")]
    version_paths = []
    for vs_path in vs_path_candidates:
        msvc_path = Path(vs_path, "VC", "Redist", "MSVC")
        version_paths += list(msvc_path.glob("*.*.*"))
    from packaging import version

    versions = [(version.parse(path.name), path) for path in version_paths]
    versions.sort(reverse=True)

    min_version = version.parse("14.26.0")
    for _version, path in versions:
        if _version < min_version:
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


def make_archive(args, source_dir: Path, target_file_without_extension: Path) -> Path:
    if args.generate_public_version:
        target_file_without_extension = target_file_without_extension.with_name(
            target_file_without_extension.name + "_public"
        )

    if args.sfx:
        ext = ".exe" if sys.platform == "win32" else ".sfx"
        packager = "7zG" if sys.platform == "win32" else "7z"
        target = target_file_without_extension.parent / f"{target_file_without_extension.name}{ext}"
        command = [packager, "a", target.as_posix(), "-mx9", "-sfx", source_dir.as_posix()]
        result = subprocess.run(command, shell=False, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Archiving failed with return code {result.returncode}")
            logger.error(f"STDOUT: {result.stdout}")
            logger.error(f"STDERR: {result.stderr}")
            result.check_returncode()  # Forces the script to raise the exception

    else:
        archive_format = "zip" if sys.platform == "win32" else "gztar"
        result = shutil.make_archive(
            target_file_without_extension.name,
            archive_format,
            root_dir=source_dir.parent,
            base_dir=source_dir.name,
        )

        result = Path(result)
        target = target_file_without_extension.with_name(result.name)
        shutil.move(result, target)

    logger.info(f"Compressed file created: {target.as_posix()}")
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

    Usage : ``shutil.rmtree(path, onexc=make_directory_writable)``
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
    shutil.rmtree(path.as_posix(), onexc=make_directory_writable)


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

    remove_large_files_from_public_repository(args)
    repository.git.add(all=True)

    # Commit and push
    try:
        repository.git.commit("-m", tag_name, "--no-verify")
        repository.git.push(
            public_remote_repository_name, local_public_master_branch_name + ":" + remote_public_master_branch_name
        )
        logger.info(
            f"Git push executed succesfully! Cleaning environment and checking out to "
            f"previously branch: {origin_reference}"
        )
    except git.exc.GitCommandError as error:
        logger.info(f"Unable to execute git commands:\n{error}")
    finally:
        repository.git.clean("-fd")
        repository.git.reset("--hard")
        repository.git.checkout(origin_reference)


def remove_large_files_from_public_repository(args) -> None:
    """Removes large files from the public repository. Expected to use after deploy process and before git commit to public repository

    Args:
        args (argparse.Namespace): The command line arguments
    """
    repository = git.Repo(SLICERLTRACE_REPO_FOLDER)

    with open(DEPLOY_CONFIG) as f:
        config = json.JSONDecoder().decode(f.read())

    if not config:
        logger.warning("No deploy configuration file found.")
        return

    lfs_tracked_files = repository.git.execute(["git", "lfs", "ls-files"])
    for file_or_path in config["LargeFilesClosedSourceHostOnly"]:
        path = SLICERLTRACE_REPO_FOLDER / file_or_path
        if file_or_path in lfs_tracked_files:
            repository.git.execute(["git", "lfs", "untrack", path.as_posix()])
        if path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path.as_posix(), onexc=make_directory_writable)


def remove_closed_source_files(args):
    repository = git.Repo(SLICERLTRACE_REPO_FOLDER, search_parent_directories=True)
    with open(DEPLOY_CONFIG) as f:
        config = json.JSONDecoder().decode(f.read())

    if not config:
        logger.warning("No deploy configuration file found.")
        remove_module_test_directories(args)
        return

    for file_or_path in config["ClosedSourceFiles"]:
        path = SLICERLTRACE_REPO_FOLDER / file_or_path

        if path.is_file():
            path.unlink()
        elif path.is_dir():
            if "submodules" in path.parent.name:
                repository.git.submodule("deinit", "-f", path.resolve().as_posix())
                repository.git.rm(path, r=True, force=True)
                repository.git.add(".gitmodules")
                git_module_path = SLICERLTRACE_REPO_FOLDER / ".git" / "modules" / path.name
                remove_directory_recursively(git_module_path)

            remove_directory_recursively(path)

    remove_module_test_directories(args)


def remove_module_test_directories(args):
    if args.keep_tests:
        return

    for path in MODULES_PACKAGE_FOLDER.rglob("*/Test/"):
        if not path.is_dir():
            continue

        shutil.rmtree(path, onexc=make_directory_writable)


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
    repository.git.submodule("update", "--init", "--recursive")


def prepare_open_source_environment(args):
    """Modify the repository files to prepare it for the public version's deployment .

    Raises:
        RuntimeError: When the current work directory has modified files.
        RuntimeError: When an error occurs during environment's modification.
    """

    repository = git.Repo(SLICERLTRACE_REPO_FOLDER)

    if status := repository.git.status("--porcelain"):
        raise RuntimeError(
            f"Cancelling process because the current work directory has modified files. Please commit or discard the changes. Status:\n{status}"
        )

    try:
        remove_closed_source_files(args)
        add_open_source_files()
    except Exception as error:
        repository.git.clean("-fd")
        repository.git.reset("--hard")
        raise RuntimeError(f"Cancelling process due to an error:\n{error}")


def check_init_files() -> None:
    no_init_list = []
    with open(DEPLOY_CONFIG) as f:
        config = json.load(f)

    init_exceptions: list[str] = config.get("InitCheckExceptions", [])

    for d in LTRACE_PACKAGE_FOLDER.rglob("**/"):
        if d == LTRACE_PACKAGE_FOLDER or not d.is_dir():
            continue

        if len(list(d.glob("*.py"))) <= 0:
            continue

        if not Path.exists(d / "__init__.py"):
            if not any([x in d.absolute().resolve().as_posix() for x in init_exceptions]):
                no_init_list.append(d)

    if len(no_init_list) > 0:
        raise RuntimeError("The following ltrace lib modules does not contain a __init__.py file: " + str(no_init_list))


def get_version_string(version: str) -> str:
    if version is None:
        return None

    try:
        if version is not None:
            parts = version.split(".")
            if len(parts) > 3:
                raise

            parsed_version = ["0", "0", "0"]
            for i in range(len(parts)):
                v = parts[i]
                if "RC" in v:
                    v = v.replace("RC", "")
                if "-public" in v:
                    v = v.replace("-public", "")
                assert int(v) >= 0
                parsed_version[i] = str(parts[i])

            version = tuple(parsed_version)
            version = ".".join(version)

    except Exception as error:
        message = f"Invalid version input: {version}."
        if str(error):
            message += f"\nError: {error}"

        raise RuntimeError(message)

    return version


def run(args):
    if args.code_signed:
        if not args.codesign_server:
            raise ValueError(
                "Code signing server is required when code signing is enabled. Add CODESIGN_SERVER environment variable or use --codesign-server."
            )

        if not args.codesign_user:
            raise ValueError(
                "Code signing user is required when code signing is enabled. Add CODESIGN_USER environment variable or use --codesign-user."
            )

        if not args.codesign_key:
            raise ValueError(
                "Code signing key is required when code signing is enabled. Add CODESIGN_KEY environment variable or use --codesign-key."
            )

        if not args.codesign_port:
            raise ValueError(
                "Code signing port is required when code signing is enabled. Add CODESIGN_SERVER_PORT environment variable or use --codesign-port."
            )

    if not args.public_commit_only:
        if args.archive:
            slicer_archive = Path(args.archive).resolve().absolute()
            output_dir = parse_output_dir(args) or slicer_archive.parent
        else:
            logger.info("error: the following arguments are required: archive")
            exit(1)

    # Checking for __init__.py files on ltrace lib dir
    if not args.dev:
        check_init_files()

    if args.geoslicer_version and args.dev:
        raise RuntimeError("Can't deploy the development version together with production version")

    if args.no_git and (args.generate_public_version or args.public_commit_only):
        # Both are driven entirely by git (branching, committing and pushing to
        # the public repository), so there is nothing left of them without it.
        raise RuntimeError("Can't use --no-git with --generate-public-version or --public-commit-only")

    geoslicer_version = get_version_string(args.geoslicer_version)
    if args.no_public_commit and args.public_commit_only:
        raise RuntimeError("Can't avoid public commit if you want only to make the public commit.")

    if args.dev:
        if args.generate_public_version:
            prepare_open_source_environment(args)

        try:
            deploy_development_environment(
                slicer_archive,
                MODULES_PACKAGE_FOLDER,
                SLICERLTRACE_REPO_FOLDER,
                output_dir,
                fast_and_dirty=args.fast_and_dirty,
                keep_name=args.keep_name,
                args=args,
            )
        except Exception as error:
            logger.exception("A critical error occurred during deployment:")
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
        prepare_open_source_environment(args)
        commit_to_opensource_repository(args, force=True)
    else:  # Production mode
        if args.generate_public_version:
            prepare_open_source_environment(args)

        try:
            generate_slicer_package(
                slicer_archive,
                MODULES_PACKAGE_FOLDER,
                SLICERLTRACE_REPO_FOLDER,
                output_dir,
                geoslicer_version,
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


def build_manual() -> None:
    output_manual_path = THIS_FOLDER / "manual"
    output_manual_path_str = output_manual_path.resolve().absolute().as_posix()

    # Delete old content
    if output_manual_path.exists():
        shutil.rmtree(output_manual_path)

    # Run mkdocs to compile the documentation
    cwd = THIS_FOLDER / "GeoSlicerManual"
    subprocess.check_call([sys.executable, "-m", "mkdocs", "build", "--site-dir", output_manual_path_str], cwd=cwd)

    # Check remaning manual directory inside 'Resources' folder and remove it to avoid it being deployed within the application
    old_manual_path_dir = THIS_FOLDER / "Resources" / "manual"
    if old_manual_path_dir.exists():
        shutil.rmtree(old_manual_path_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Configures a clean Slicer download for deploy or development.")
    parser.add_argument(
        "archive",
        help="Geoslicer instalation downloaded from the LTrace repo. Either the .tar file or the extracted folder.",
        nargs="?",
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
        "--no-git",
        action="store_true",
        help="Don't call git at all: skip the submodule update and stamp placeholder commit metadata. "
        "Use it when the repository folder is not resolvable by git (e.g. a worktree whose gitdir link "
        "points outside this environment). Submodules must already be checked out.",
        default=False,
    )
    parser.add_argument(
        "--no-pip",
        action="store_true",
        help="Skip installing/uninstalling the pip dependencies (ltrace, microtom and the submodules), "
        "keeping whatever is already installed in the target application.",
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
        "--without-porespy",
        action="store_true",
        help="Avoid porespy submodule installation to use the installed version from the base file.",
        default=False,
    )
    parser.add_argument(
        "--plugin-to-geolog",
        help="Path to where Geolog is installed (to add GeoSlicer to the Processing menu of Geolog).",
        default=None,
    )
    parser.add_argument(
        "--no-public-commit",
        action="store_true",
        help="Avoid commiting to the opensource code repository",
        default=False,
    )
    parser.add_argument(
        "--keep-tests",
        action="store_true",
        help="Keeps tests when generating standalone build.",
        default=False,
    )
    parser.add_argument(
        "--disable-archiving",
        action="store_true",
        help="Avoid the archiving step when generating a release build.",
        default=False,
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        help="Define a path to store the application.",
        default=None,
    )
    parser.add_argument(
        "--code-signed",
        action="store_true",
        help="Enable code signing for the Windows application.",
        default=False,
    )
    parser.add_argument(
        "--codesign-server",
        help="Remote server address for code signing.",
        default=os.environ.get("CODESIGN_SERVER"),
    )
    parser.add_argument(
        "--codesign-user",
        help="SSH username for code signing.",
        default=os.environ.get("CODESIGN_USER"),
    )
    parser.add_argument(
        "--codesign-key",
        help="Path to the SSH private key for code signing.",
        default=os.environ.get("CODESIGN_KEY"),
    )
    parser.add_argument(
        "--codesign-port",
        help="Port to the SSH server address.",
        default=os.environ.get("CODESIGN_SERVER_PORT"),
    )
    run(parser.parse_args())
