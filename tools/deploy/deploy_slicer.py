import argparse
import datetime
import git
import json
import logging
import os
import patch
import shutil
import subprocess
import sys
import vswhere
import tarfile
import tomllib
import zipfile

from pathlib import Path
from shutil import ignore_patterns
from string import Template
from typing import List, Union

from deploy.utils import FlushStreamHandler, find_submodules_setup_directory, get_repo_root
from deploy.partner_setup import inject_partner_files as _inject_partner_files
from deploy.partner_setup import install_partner_dependencies as _install_partner_dependencies
from deploy.revert_partner_customization import revert_customization
from commons.slicer.module_info import ModuleInfo

logger = logging.getLogger()
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    logger.addHandler(FlushStreamHandler(sys.stdout))

# Non built-in modules are imported after constants definition

if sys.version_info >= (3, 8):

    def xcopytree(a, b, ok):
        return shutil.copytree(a, b, dirs_exist_ok=ok)
else:
    from distutils.dir_util import copy_tree

    def xcopytree(a, b, ok):
        return copy_tree(str(a), str(b)) if ok else shutil.copytree(a, b)


THIS_FILE = Path(__file__).resolve().absolute()
THIS_FOLDER = THIS_FILE.parent
DEPLOY_CONFIG = THIS_FOLDER / "slicer_deploy_config.json"
REQUIREMENTS_FILE = THIS_FOLDER / "requirements.txt"
SLICERLTRACE_REPO_FOLDER = get_repo_root()
MODULES_PACKAGE_FOLDER = SLICERLTRACE_REPO_FOLDER / "src" / "modules"
COMMONS_PACKAGE_FOLDER = SLICERLTRACE_REPO_FOLDER / "src" / "commons"
SUBMODULES_PACKAGE_FOLDER = SLICERLTRACE_REPO_FOLDER / "src" / "third-parties"
PARTNERS_FOLDER = SLICERLTRACE_REPO_FOLDER / "src" / "partners"

GREEN_TAG = "\x1b[32;20m"
RESET_COLOR_TAG = "\x1b[0m"
GREEN_BOLD_TAG = "\x1b[32;1m"

APP_NAME = "GeoSlicer"


class SlicerDeployer:
    """Class responsible for deploying GeoSlicer."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.archive_path = Path(args.archive).resolve().absolute() if args.archive else None
        self.development = args.dev
        self.fast_and_dirty = args.fast_and_dirty
        self.geoslicer_version = get_version_string(args.geoslicer_version)
        self.output_dir = parse_output_dir(args) or (self.archive_path.parent if self.archive_path else None)
        self.keep_name = args.keep_name
        self.no_git = args.no_git

    def run(self):
        """Run the deployment process."""
        if self.development:
            if self.geoslicer_version:
                raise RuntimeError("Can't deploy the development version together with production version")
            self._deploy_development()
        else:
            if self.geoslicer_version is None:
                raise ValueError(
                    "Production deployment requires a defined version. Please use the flag '--geoslicer-version' to specify it."
                )
            self._deploy_production()

    def _deploy_production(self):
        self._generic_deploy(version_string=self.geoslicer_version)
        logger.info(
            f"{GREEN_TAG}The application has been deployed in {GREEN_BOLD_TAG}production{RESET_COLOR_TAG}{GREEN_TAG} mode.{RESET_COLOR_TAG}"
        )

    def _deploy_development(self):
        self._generic_deploy(version_string=None)
        logger.info(
            f"\n{GREEN_TAG}The application has been deployed in {GREEN_BOLD_TAG}development{RESET_COLOR_TAG}{GREEN_TAG} mode.{RESET_COLOR_TAG}"
        )

    def _generic_deploy(self, version_string: Union[str, None]):
        logger.info("Extracting")
        slicer_dir: Path = self._extract_archive()

        # Update submodules
        if self.no_git:
            logger.info("Skipping submodule update (--no-git).")
        else:
            logger.info("Updating submodules...")
            repo = git.Repo(SLICERLTRACE_REPO_FOLDER)
            repo.git.submodule("update", "--init", "--recursive")

        # getting the 3D Slicer version
        slicer_version = self._get_slicer_version(slicer_dir)
        logger.info(f"Slicer version {slicer_version}")
        self._apply_pre_patches(slicer_dir, slicer_version)

        if not self.fast_and_dirty:
            self._install_dependencies(slicer_dir)

        logger.info("Copying extensions")
        modules_to_add = self._handle_extensions(slicer_dir)

        logger.info("Building GeoSlicer manual")
        build_manual()

        logger.info("Installing customizer")
        self._install_customizer(slicer_dir, modules_to_add, self._find_extensions(slicer_dir), version_string)

        logger.info("Copying assets")
        self._copy_extra_files(slicer_dir, slicer_version)

        logger.info("Removing unwanted files")
        self._remove_unwanted_files(slicer_dir, slicer_version)

        logger.info("Copying notebooks")
        self._copy_notebooks(slicer_dir)

        if self.args.plugin_to_geolog:
            subprocess.run(
                [
                    sys.executable,
                    "./tools/deploy/Geolog/plugin_to_geolog.py",
                    "--geolog-path",
                    self.args.plugin_to_geolog,
                    "--geoslicer-path",
                    slicer_dir,
                ]
            )

        logger.info("Applying patches")
        self._apply_patches(slicer_dir, slicer_version)

        if not self.development:
            self._finalize_production_build(slicer_dir, version_string)

    def _extract_archive(self) -> Path:
        if self.archive_path.is_dir():
            return self.archive_path

        slicer_archive_stem = self.archive_path.stem
        if slicer_archive_stem.endswith(".tar"):
            slicer_archive_stem = slicer_archive_stem[:-4]
        extract_dir = self.output_dir / slicer_archive_stem

        shutil.unpack_archive(str(self.archive_path), str(self.output_dir))
        return extract_dir

    @staticmethod
    def _get_slicer_version(slicer_dir: Path) -> str:
        lib_dir = slicer_dir / "lib"
        lib_dir_subdirs = [f.name for f in lib_dir.iterdir() if f.is_dir()]
        slicer_version = [s[len(APP_NAME) + 1 :] for s in lib_dir_subdirs if APP_NAME + "-" in s][0]
        return slicer_version

    def _install_dependencies(self, slicer_dir: Path):
        logger.info("Uninstalling local packages")
        self._uninstall_packages(slicer_dir=slicer_dir, package="commons")

        logger.info("Installing pip dependencies")
        self._install_pip_dependencies(slicer_dir, COMMONS_PACKAGE_FOLDER)

        microtom_path = MODULES_PACKAGE_FOLDER / "MicrotomRemote" / "Libs" / "microtom"
        if (microtom_path / "setup.py").exists():
            logger.info(f"Uninstalling microtom {microtom_path} packages")
            self._uninstall_packages(slicer_dir=slicer_dir, package="microtom")
            self._install_pip_dependencies(slicer_dir, microtom_path)

        # Installing packages from partner
        for partner_name in self.args.partner:
            slicer_python = self._get_python_slicer_path(slicer_dir)
            _install_partner_dependencies(
                partner_name, self.development, SLICERLTRACE_REPO_FOLDER, sys_executable=str(slicer_python)
            )

        # Installing packages from submodules
        submodules_dict = {path.name: path for path in find_submodules_setup_directory(SUBMODULES_PACKAGE_FOLDER)}

        for submodule_name, path in submodules_dict.items():
            if self.args.without_porespy and submodule_name == "porespy" and self.development:
                continue

            logger.info(f"Uninstalling current version from submodule '{submodule_name}'")
            self._uninstall_packages(slicer_dir=slicer_dir, package=submodule_name)
            logger.info(f"Installing submodule '{submodule_name}'")
            self._install_module_from_folder(slicer_dir, path)

        # Last, deliberately: anything installed after this can pull the GUI
        enforce_headless_opencv(slicer_dir)

    def _get_python_slicer_path(self, slicer_dir: Path) -> Path:
        executable_name = "PythonSlicer.exe" if sys.platform.startswith("win32") else "PythonSlicer"
        slicer_python = slicer_dir / "bin" / executable_name
        return slicer_python

    def _compile_bytecode(self, slicer_dir: Path) -> None:
        """Ship bytecode for all Python files: a read-only installation can't cache it, so it would compile them on
        every launch. Hash-based bytecode stays valid when archiving changes file times, as zip does."""
        logger.info("Compiling Python bytecode")
        slicer_python = self._get_python_slicer_path(slicer_dir)
        # The base's ptvsd copies are Python 2. Third-party packages' syntax warnings would only clutter the log
        subprocess.run(
            [
                str(slicer_python),
                "-W",
                "ignore::SyntaxWarning",
                "-m",
                "compileall",
                "-q",
                "-f",
                "-j0",
                "--invalidation-mode",
                "checked-hash",
                "-x",
                "ptvsd",
                str(slicer_dir),
            ],
            check=True,
        )

    def _uninstall_packages(self, slicer_dir: Path, package: str) -> None:
        slicer_python = self._get_python_slicer_path(slicer_dir)
        subprocess.run([str(slicer_python), "-m", "pip", "uninstall", "-y", package], check=True)

    def _install_pip_dependencies(self, slicer_dir: Path, lib_folder: Path):
        slicer_python = self._get_python_slicer_path(slicer_dir)
        pip_call = [str(slicer_python), "-m", "pip", "install"]
        if self.development:
            pip_call.append("--editable")
        pip_call.append(str(lib_folder))

        subprocess.run(
            [str(slicer_python), "-m", "pip", "install", "--upgrade", "pip==25.3", "setuptools==80.10.1"], check=True
        )
        subprocess.run(pip_call, check=True)

    def _install_module_from_folder(self, slicer_dir: Path, folder: Path):
        slicer_python = self._get_python_slicer_path(slicer_dir)
        pip_call = [str(slicer_python), "-m", "pip", "install"]
        if self.development:
            pip_call.append("--editable")
        pip_call.append(str(folder))

        subprocess.run(pip_call, check=True)

    def _handle_extensions(self, slicer_dir: Path) -> List[Path]:
        if self.development:
            modules_to_add = list(self._find_plugins_source(MODULES_PACKAGE_FOLDER))
            modules_to_add.extend(self._find_cli_source(MODULES_PACKAGE_FOLDER))
            return modules_to_add

        discarded_patterns = ("*CLI",) if self.args.keep_tests else ("*CLI", "*Test")
        modules_to_add = list(
            self._copy_extensions(
                slicer_dir,
                self._find_plugins_source(MODULES_PACKAGE_FOLDER),
                "qt-scripted-modules",
                ignore_patterns(*discarded_patterns),
            )
        )
        modules_to_add.extend(
            self._copy_extensions(slicer_dir, self._find_cli_source(MODULES_PACKAGE_FOLDER), "cli-modules")
        )

        for module in modules_to_add:
            logger.info(f"module to add: {module}")
        return modules_to_add

    def _copy_extensions(self, slicer_dir: Path, extensions: List[Path], location: str, ignore=None):
        extensions_dir = get_plugins_dir(slicer_dir)
        for source_dir in extensions:
            current_dir = extensions_dir / location / source_dir.name

            if current_dir.exists():
                shutil.rmtree(current_dir, onexc=make_directory_writable)

            shutil.copytree(source_dir, current_dir, ignore=ignore)

            yield current_dir

    def _find_plugins_source(self, modules_package_folder: Path):
        for current_path in modules_package_folder.iterdir():
            if current_path.is_dir() and not current_path.name.endswith("CLI"):
                extension_main_file = current_path / (current_path.name + ".py")
                if extension_main_file.exists():
                    yield current_path

    def _find_cli_source(self, modules_package_folder: Path, level=1):
        for current_path in modules_package_folder.iterdir():
            if current_path.name.endswith("CLI"):
                extension_main_file = current_path / (current_path.name + ".py")
                extension_xml_file = current_path / (current_path.name + ".xml")
                if extension_main_file.exists() and extension_xml_file.exists():
                    yield current_path
                else:
                    yield from self._find_cli_source(current_path, level=level)
            elif level > 0 and current_path.is_dir():
                yield from self._find_cli_source(current_path, level=level - 1)

    def _find_extensions(self, slicer_dir: Path) -> List[Path]:
        extensions_dir = slicer_dir / "extensions"
        if not extensions_dir.exists():
            return []

        paths = []
        for extension in extensions_dir.iterdir():
            if not extension.is_dir():
                continue

            paths.extend(get_plugins_dir(extension).glob("*-modules"))

        return paths

    def _install_customizer(self, slicer_dir: Path, modules: List[Path], extensions: List[Path], version: str):
        src_path = THIS_FOLDER / "slicerrc.py"
        dest_path = slicer_dir / ".slicerrc.py"

        shutil.copy(src_path, dest_path)

        use_git = not self.no_git
        commit_hash, is_dirty = get_repo_metadata(use_git)

        module_index = self._index_modules(slicer_dir, modules)

        json_output = {
            "name": "GeoSlicer",
            "itk_module": None,
            "GEOSLICER_VERSION": version,
            "GEOSLICER_HASH": repr(commit_hash),
            "GEOSLICER_HASH_DIRTY": repr(is_dirty),
            "GEOSLICER_BUILD_TIME": str(datetime.datetime.now()),
            "GEOSLICER_DEV_ENVIRONMENT": repr(self.development),
            "GEOSLICER_MODULES": module_index,
            "PARTNER": self.args.partner or None,
            "PARTNER_COMMIT": self.args.partner_commit if self.args.partner else None,
        }

        json_path = get_plugins_dir(slicer_dir) / "qt-scripted-modules" / "Resources" / "json" / "GeoSlicer.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w") as json_file:
            json.dump(json_output, json_file, indent=4)

        self._install_default_settings(slicer_dir, module_index)

    def _index_modules(self, slicer_dir: Path, modules: List[Path]) -> List[dict]:
        """List the installed modules so GeoSlicer doesn't scan for them on startup. Paths are relative to the
        installation, except in development, where modules are loaded from the repository."""
        index = []
        for module_dir in modules:
            for info in ModuleInfo.findModules(str(module_dir), 0):
                path = Path(info.path) if self.development else Path(info.path).relative_to(slicer_dir)
                index.append(
                    {"key": info.key, "path": path.as_posix(), "categories": info.categories, "hidden": info.hidden}
                )
        return index

    def _install_default_settings(self, slicer_dir: Path, module_index: List[dict]):
        """Install the settings a new user starts with. Slicer reads module search paths from them before loading
        any module, so the startup modules load on the first launch without writing settings to the installation."""
        with open(DEPLOY_CONFIG) as f:
            startup_modules = json.load(f)["StartupModules"]

        startup_entries = [m for m in module_index if m["key"] in startup_modules or m["key"].endswith("CLI")]
        missing = set(startup_modules) - {m["key"] for m in startup_entries}
        if missing:
            raise RuntimeError(f"StartupModules in {DEPLOY_CONFIG.name} not found among the modules: {sorted(missing)}")

        search_paths = dict.fromkeys(Path(m["path"]).parent.as_posix() for m in startup_entries)
        template = (THIS_FOLDER / "Assets" / f"{APP_NAME}DefaultSettings.ini").read_text()
        settings = Template(template).substitute(additional_module_paths=", ".join(f'"{p}"' for p in search_paths))
        (slicer_dir / "share" / get_plugins_dir(slicer_dir).name / f"{APP_NAME}DefaultSettings.ini").write_text(
            settings
        )

        # Defaults only fill in settings that are missing, so revision settings left by an earlier deploy (with
        # module paths from that deploy) would override them
        for revision_settings in (slicer_dir / "LTrace").glob(f"{APP_NAME}-*.ini"):
            revision_settings.unlink()

    def _copy_notebooks(self, slicer_dir: Path):
        notebooks_dir = MODULES_PACKAGE_FOLDER / "Notebooks"
        target_dir = slicer_dir / "Notebooks"
        if target_dir.exists():
            shutil.rmtree(target_dir, onexc=make_directory_writable)

        copy_file_or_tree(notebooks_dir, target_dir, exist_ok=True)

    def _copy_extra_files(self, slicer_dir: Path, slicer_version: str):
        for source, target in self._get_extra_files_to_copy(slicer_version):
            is_glob = source.endswith("*")
            if is_glob:
                source = source[:-1]
            source = SLICERLTRACE_REPO_FOLDER / Path(source)
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
                self._update_slicer_version_placeholders(target, slicer_version)

        if sys.platform.startswith("win32") and not self.fast_and_dirty and not self.development:
            self._copy_windows_dlls(slicer_dir)

    def _get_extra_files_to_copy(self, slicer_version: str):
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

    def _update_slicer_version_placeholders(self, source: Path, slicer_version: str):
        with open(SLICERLTRACE_REPO_FOLDER / source) as f:
            new_text = f.read()
            new_text = Template(new_text).substitute(slicer_dir=f"{APP_NAME}-{slicer_version}")
        with open(SLICERLTRACE_REPO_FOLDER / source, "w") as f:
            f.write(new_text)

    def _remove_unwanted_files(self, slicer_dir: Path, slicer_version: str):
        with open(DEPLOY_CONFIG) as f:
            config = json.JSONDecoder().decode(f.read())

        platform = "linux" if sys.platform.startswith("linux") else "win32"
        files_to_remove = config["FilesToRemove"].get(platform, [])
        for target in files_to_remove:
            target = Template(target).substitute(slicer_dir=f"{APP_NAME}-{slicer_version}")
            target = slicer_dir / target
            if target.exists():
                target.unlink()

    def _apply_patches(self, slicer_dir: Path, slicer_version: str, config_key="Patches"):
        with open(DEPLOY_CONFIG) as f:
            config = json.JSONDecoder().decode(f.read())

        platform = "linux" if sys.platform.startswith("linux") else sys.platform
        patches = config[config_key].get(platform, [])
        for patch_folder_name, target_folder, strip_folders in patches:
            patch_folder = THIS_FOLDER / "Patches" / patch_folder_name
            target_folder = Template(target_folder).substitute(slicer_dir=f"{APP_NAME}-{slicer_version}")
            target_folder = slicer_dir / Path(target_folder)
            for patch_file in sorted(patch_folder.glob("*.patch")):
                logger.info(f"Applying patch {patch_file} to {target_folder}")
                patch_set = patch.fromfile(patch_file)
                if patch_set:
                    patch_set.apply(strip=strip_folders, root=target_folder)

    def _apply_pre_patches(self, slicer_dir: Path, slicer_version: str):
        try:
            self._apply_patches(slicer_dir, slicer_version, config_key="PrePatches")
        except Exception as e:
            logger.exception(f"Error applying pre-patches: {e}")

    def _copy_windows_dlls(self, slicer_dir: Path):
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
        crt_path = None
        for _version, path in versions:
            if _version < min_version:
                raise RuntimeError(f"MSVC minimum requirement ({min_version.public}) not met")
            potential_crt_path = list(path.joinpath("x64").glob("*.CRT"))
            if len(potential_crt_path) >= 1:
                crt_path = potential_crt_path[0]
                break
        else:
            raise RuntimeError(".CRT folder not found (MSVC installation)")

        files_to_copy.extend(crt_path.glob("*.dll"))

        target_dir = slicer_dir / "bin"
        for dll in files_to_copy:
            try:
                shutil.copy2(dll, target_dir)
            except Exception:
                pass

    def _finalize_production_build(self, slicer_dir: Path, version_string: str):
        version_name = f"GeoSlicer-{version_string}"
        archive_folder_name = slicer_dir.with_name(version_name)
        if self.args.output_dir is not None:
            archive_folder_name = Path(self.args.output_dir) / version_name

        if slicer_dir.name != version_name:
            try:
                shutil.move(slicer_dir, archive_folder_name)
            except OSError:
                # Ignoring Windows issue related to access denied
                pass

        self._compile_bytecode(archive_folder_name)

        if not self.fast_and_dirty and not self.args.disable_archiving:
            logger.info("Archiving")
            make_archive(self.args, archive_folder_name, self.archive_path.with_name(version_name))


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
    """The opencv-python-headless pin as the commons package declares it."""
    pyproject = COMMONS_PACKAGE_FOLDER / "pyproject.toml"
    with open(pyproject, "rb") as file:
        dependencies = tomllib.load(file)["project"]["dependencies"]

    for entry in dependencies:
        if entry.replace("_", "-").lower().startswith(OPENCV_HEADLESS_PACKAGE):
            return entry

    raise RuntimeError(f"{pyproject} doesn't declare {OPENCV_HEADLESS_PACKAGE}")


def enforce_headless_opencv(slicer_dir: Path) -> None:
    """Leave exactly one OpenCV installed, the headless one.

    mmcv, mmengine and sahi all declare a dependency on the GUI `opencv-python`,
    so pip installs it regardless of what the commons package pins. Both wheels
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


def get_plugins_dir(parent_dir: Path) -> Path:
    """Get the plugins directory for Slicer."""
    matches = list((parent_dir / "lib").glob("*GeoSlicer-*"))
    assert len(matches) == 1, f"matches: {matches} - parent_dir {parent_dir}"
    return matches[0]


def check_init_files() -> None:
    """Check for __init__.py files in the ltrace lib directory."""
    no_init_list = []
    with open(DEPLOY_CONFIG) as f:
        config = json.load(f)

    init_exceptions: list[str] = config.get("InitCheckExceptions", [])

    for d in COMMONS_PACKAGE_FOLDER.rglob("**/"):
        if d == COMMONS_PACKAGE_FOLDER or not d.is_dir():
            continue

        if len(list(d.glob("*.py"))) <= 0:
            continue

        if not (d / "__init__.py").exists():
            if not any([x in d.absolute().resolve().as_posix() for x in init_exceptions]):
                no_init_list.append(d)

    if len(no_init_list) > 0:
        raise RuntimeError("The following ltrace lib modules does not contain a __init__.py file: " + str(no_init_list))


def get_version_string(version: str) -> Union[str, None]:
    """Parse and validate the version string."""
    if version is None:
        return None

    try:
        parts = version.split(".")
        if len(parts) > 3:
            raise ValueError("Too many version parts")

        parsed_version = ["0", "0", "0"]
        for i in range(len(parts)):
            v = parts[i]
            if "RC" in v:
                v = v.replace("RC", "")
            assert int(v) >= 0
            parsed_version[i] = str(parts[i])

        version = ".".join(parsed_version)

    except Exception as error:
        message = f"Invalid version input: {version}."
        if str(error):
            message += f"\nError: {error}"

        raise RuntimeError(message)

    return version


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
    """Remove a directory recursively, handling read-only files."""
    if not path.exists():
        return

    make_directory_writable(path=path.as_posix())
    shutil.rmtree(path.as_posix(), onexc=make_directory_writable)


def inject_partner_files(args: argparse.Namespace) -> None:
    """Inject partner-specific files into the repository."""
    _inject_partner_files(args.partner, args.dev, SLICERLTRACE_REPO_FOLDER)


def copy_file_or_tree(source: Path, target_dir: Path, exist_ok: bool = False):
    """Copy a file or directory tree."""
    assert source.exists()

    if source.is_dir():
        xcopytree(source, target_dir / source.name, exist_ok)
    else:
        shutil.copy2(source, target_dir)


def make_archive(args: argparse.Namespace, source_dir: Path, target_file_without_extension: Path) -> Path:
    """Create a compressed archive of the deployed folder."""
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
            result.check_returncode()

    else:
        archive_format = "zip" if sys.platform == "win32" else "gztar"
        result = shutil.make_archive(
            target_file_without_extension.name,
            archive_format,
            root_dir=source_dir.parent,
            base_dir=source_dir.name,
        )

        result_path = Path(result)
        target = target_file_without_extension.with_name(result_path.name)
        shutil.move(result_path, target)

    logger.info(f"Compressed file created: {target.as_posix()}")
    return target


def build_manual() -> None:
    """Build the GeoSlicer manual using mkdocs."""
    output_manual_path = THIS_FOLDER / "manual"
    output_manual_path_str = output_manual_path.resolve().absolute().as_posix()

    # Delete old content
    if output_manual_path.exists():
        shutil.rmtree(output_manual_path)

    # Run mkdocs to compile the documentation
    cwd = THIS_FOLDER / "GeoSlicerManual"
    if cwd.exists():
        subprocess.check_call([sys.executable, "-m", "mkdocs", "build", "--site-dir", output_manual_path_str], cwd=cwd)

    # Check remaning manual directory inside 'Resources' folder and remove it to avoid it being deployed within the application
    old_manual_path_dir = THIS_FOLDER / "Resources" / "manual"
    if old_manual_path_dir.exists():
        shutil.rmtree(old_manual_path_dir)


def _get_partners() -> List[Path]:
    partner_folders_list = [i for i in PARTNERS_FOLDER.glob("*") if i.is_dir()]
    return partner_folders_list


def _revert_partner_customization() -> None:
    for partner_folder in _get_partners():
        revert_customization(partner_folder.name)


def run(args: argparse.Namespace):
    """Entry point for the script."""
    if not args.archive:
        logger.error("Error: the following arguments are required: archive")
        sys.exit(1)

    if args.partner:
        if isinstance(args.partner, str):
            args.partner = [args.partner]
    else:
        args.partner = []

    _revert_partner_customization()

    if args.partner:
        inject_partner_files(args)

    if not args.dev:
        check_init_files()

    deployer = SlicerDeployer(args)
    try:
        deployer.run()
    except Exception as error:
        logger.exception("An error occurred during deployment:")
        raise error


def main():
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
        "--geoslicer-version", help="Version number to use for GeoSlicer. Examples: 1, 1.2, 1.2.3", default=None
    )
    parser.add_argument(
        "--partner",
        help="Name of the partner to deploy. Defaults to None.",
        nargs="*",
        default=None,
    )
    parser.add_argument(
        "--partner-commit",
        help="Branch name or commit hash of the partner's repository that was checked out. Defaults to master.",
        default="master",
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
    run(parser.parse_args())


if __name__ == "__main__":
    main()
