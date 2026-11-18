import json
import shutil
import tempfile
import deploy.deploy_slicer as ds
import pytest

from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch


def _create_default_arguments_mock() -> MagicMock:
    mock_args = MagicMock()
    mock_args.archive = "None"
    mock_args.dev = False
    mock_args.partner = None
    mock_args.keep_name = False
    mock_args.fast_and_dirty = False
    mock_args.no_git = False
    mock_args.geoslicer_version = None
    mock_args.sfx = False
    mock_args.without_porespy = False
    mock_args.disable_archiving = False
    mock_args.keep_tests = False
    mock_args.output_dir = None
    mock_args.plugin_to_geolog = None
    mock_args.partner = None
    mock_args.partner_commit = "master"
    return mock_args


def _create_deployer(args: MagicMock = None) -> ds.SlicerDeployer:
    return ds.SlicerDeployer(args or _create_default_arguments_mock())


def _create_module_directory_structure(parent: Path, name: str) -> Path:
    """Create a scripted module folder with its main file, a Resources folder and a Test folder."""
    module_dir = parent / name
    (module_dir / "Resources").mkdir(parents=True)
    (module_dir / "Test").mkdir()
    (module_dir / f"{name}.py").touch()
    return module_dir


def _create_scripted_module(parent: Path, name: str) -> Path:
    """Create a module folder whose main file the module indexer recognizes."""
    module_dir = parent / name
    module_dir.mkdir(parents=True)
    (module_dir / f"{name}.py").write_text(
        f"class {name}(LTracePlugin):\n    def __init__(self, parent):\n        self.parent.categories = ['Tools']\n"
    )
    return module_dir


def _create_dummy_files_from_path(paths: List[Path]) -> None:
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


class TestDeploySlicer:
    def setup_method(self) -> None:
        """Test case setup"""
        self.temp_dir = Path(tempfile.TemporaryDirectory().name)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def teardown_method(self) -> None:
        """Test case teardown"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    @pytest.mark.parametrize(
        "keep_tests, should_exist",
        [
            pytest.param(True, True, id="keep_tests_true"),
            pytest.param(False, False, id="keep_tests_false"),
        ],
    )
    def test_handle_extensions_discards_test_directories(self, keep_tests: bool, should_exist: bool) -> None:
        modules_dir = self.temp_dir / "modules"
        mock_modules_dir = [
            _create_module_directory_structure(modules_dir, "ABC"),
            _create_module_directory_structure(modules_dir, "Test"),
            _create_module_directory_structure(modules_dir, "Module"),
        ]

        slicer_dir = self.temp_dir / "slicer"
        plugins_dir = slicer_dir / "lib" / "GeoSlicer-5.0"

        args = _create_default_arguments_mock()
        args.keep_tests = keep_tests
        with (
            patch("deploy.deploy_slicer.MODULES_PACKAGE_FOLDER", modules_dir),
            patch("deploy.deploy_slicer.get_plugins_dir", return_value=plugins_dir),
        ):
            copied_modules = _create_deployer(args)._handle_extensions(slicer_dir)

        assert len(copied_modules) == len(mock_modules_dir)
        for module_dir in copied_modules:
            assert module_dir.exists()
            assert (module_dir / "Resources").exists()
            assert (module_dir / "Test").exists() == should_exist

    @pytest.mark.parametrize(
        "platform, expected_removed, expected_kept",
        [
            pytest.param("win32", ["file.dll"], ["file.so"], id="win32"),
            pytest.param("linux", ["file.so"], ["file.dll"], id="linux"),
        ],
    )
    @patch("deploy.deploy_slicer.sys")
    @patch("json.JSONDecoder.decode")
    def test_remove_unwanted_files(
        self,
        mock_json_decode: MagicMock,
        mock_sys: MagicMock,
        platform: str,
        expected_removed: List[str],
        expected_kept: List[str],
    ) -> None:
        mock_sys.platform = platform
        mock_json_decode.return_value = {
            "FilesToRemove": {
                "win32": ["file.dll"],
                "linux": ["file.so"],
            }
        }

        all_files = ["file.dll", "file.so"]
        _create_dummy_files_from_path([self.temp_dir / f for f in all_files])

        _create_deployer()._remove_unwanted_files(self.temp_dir, "5.0")

        for f in expected_removed:
            assert not (self.temp_dir / f).exists(), f"{f} should have been removed."

        for f in expected_kept:
            assert (self.temp_dir / f).exists(), f"{f} should not have been removed."

    @patch("deploy.deploy_slicer._revert_partner_customization")
    @patch("deploy.deploy_slicer.SlicerDeployer._deploy_development")
    @patch("deploy.deploy_slicer.SlicerDeployer._deploy_production")
    @patch("deploy.deploy_slicer.check_init_files")
    def test_script_called_with_dev_flag(
        self,
        mock_check_init: MagicMock,
        mock_deploy_production: MagicMock,
        mock_deploy_development: MagicMock,
        mock_revert: MagicMock,
    ) -> None:

        mock_args = _create_default_arguments_mock()
        mock_args.dev = True
        mock_args.archive = "None"

        with patch("deploy.deploy_slicer.Path.resolve", return_value=Path("None")):
            ds.run(mock_args)

        assert mock_deploy_production.call_count == 0
        assert mock_deploy_development.call_count == 1

    @patch("deploy.deploy_slicer.SlicerDeployer._deploy_development")
    @patch("deploy.deploy_slicer.SlicerDeployer._deploy_production")
    @patch("deploy.deploy_slicer.check_init_files")
    @patch("deploy.deploy_slicer._get_partners")
    @patch("deploy.deploy_slicer.revert_customization")
    def test_script_called_with_default_flags(
        self,
        mock_revert_customization: MagicMock,
        mock_get_partners: MagicMock,
        mock_check_init: MagicMock,
        mock_deploy_production: MagicMock,
        mock_deploy_development: MagicMock,
    ) -> None:
        mock_get_partners.return_value = []
        mock_args = _create_default_arguments_mock()
        mock_args.archive = "None"
        mock_args.geoslicer_version = "0.0"
        with patch("deploy.deploy_slicer.Path.resolve", return_value=Path("None")):
            ds.run(mock_args)

        assert mock_deploy_production.call_count == 1
        assert mock_deploy_development.call_count == 0
        assert mock_revert_customization.call_count == 0

    @pytest.mark.parametrize(
        "platform, expected_suffixes",
        [
            pytest.param("win32", [".zip"], id="win32"),
            pytest.param("linux", [".tar", ".gz"], id="linux"),
        ],
    )
    @patch("deploy.deploy_slicer.shutil")
    @patch("deploy.deploy_slicer.sys")
    def test_make_archive_not_sfx(
        self,
        mock_sys: MagicMock,
        mock_shutil: MagicMock,
        platform: str,
        expected_suffixes: List,
    ) -> None:
        mock_args = _create_default_arguments_mock()
        mock_args.sfx = False
        mock_sys.platform = platform

        def dummy_shutil_make_archive(name, _format, root_dir, base_dir):
            suffix = ".zip" if _format == "zip" else ".tar.gz"
            return root_dir / f"{name}{suffix}"

        mock_shutil.make_archive.side_effect = dummy_shutil_make_archive
        source_dir = self.temp_dir / "source_dir"
        target_file_without_extension = self.temp_dir / "target_file_without_extension"

        ds.make_archive(mock_args, source_dir, target_file_without_extension)

        target_arg = mock_shutil.move.call_args.args[1]
        for suffix in expected_suffixes:
            assert suffix in target_arg.suffixes, f"Suffix {suffix} not available in {target_arg.suffixes}"

        assert mock_shutil.make_archive.call_count == 1
        assert mock_shutil.move.call_count == 1

    @pytest.mark.parametrize(
        "platform",
        [
            pytest.param("win32", id="win32"),
            pytest.param("linux", id="linux"),
        ],
    )
    @patch("deploy.deploy_slicer.subprocess")
    @patch("deploy.deploy_slicer.shutil")
    @patch("deploy.deploy_slicer.sys")
    def test_make_archive_sfx(
        self,
        mock_sys: MagicMock,
        mock_shutil: MagicMock,
        mock_subprocess: MagicMock,
        platform: str,
    ) -> None:
        mock_args = _create_default_arguments_mock()
        mock_args.sfx = True
        mock_sys.platform = platform

        source_dir = self.temp_dir / "source_dir"
        target_file_without_extension = self.temp_dir / "target_file_without_extension"

        ds.make_archive(mock_args, source_dir, target_file_without_extension)

        subprocess_run_args = mock_subprocess.run.call_args.args
        command_arg = subprocess_run_args[0]
        packager = "7zG" if platform == "win32" else "7z"
        ext = ".exe" if platform == "win32" else ".sfx"
        assert packager in command_arg
        target_file = target_file_without_extension.parent / f"{target_file_without_extension.name}{ext}"
        assert f"{target_file.as_posix()}" in command_arg, f"Expected {target_file.as_posix()} in {command_arg}"

        assert mock_subprocess.run.call_count == 1
        assert mock_shutil.make_archive.call_count == 0
        assert mock_shutil.move.call_count == 0

    @pytest.mark.parametrize(
        "development, disable_archive, should_archive",
        [
            pytest.param(False, False, True, id="production_extended_version"),
            pytest.param(True, False, False, id="development_extended_version"),
            pytest.param(False, True, False, id="production_extended_version_disable_archiving"),
        ],
    )
    @patch("deploy.deploy_slicer._revert_partner_customization")
    @patch("deploy.deploy_slicer.SlicerDeployer._extract_archive")
    @patch("deploy.deploy_slicer.SlicerDeployer._get_slicer_version")
    @patch("deploy.deploy_slicer.git")
    @patch("deploy.deploy_slicer.SlicerDeployer._uninstall_packages")
    @patch("deploy.deploy_slicer.SlicerDeployer._install_pip_dependencies")
    @patch("deploy.deploy_slicer.find_submodules_setup_directory")
    @patch("deploy.deploy_slicer.SlicerDeployer._install_module_from_folder")
    @patch("deploy.deploy_slicer.SlicerDeployer._find_plugins_source")
    @patch("deploy.deploy_slicer.SlicerDeployer._find_cli_source")
    @patch("deploy.deploy_slicer.SlicerDeployer._copy_extensions")
    @patch("deploy.deploy_slicer.ignore_patterns")
    @patch("deploy.deploy_slicer.subprocess")
    @patch("deploy.deploy_slicer.SlicerDeployer._install_customizer")
    @patch("deploy.deploy_slicer.SlicerDeployer._copy_extra_files")
    @patch("deploy.deploy_slicer.SlicerDeployer._remove_unwanted_files")
    @patch("deploy.deploy_slicer.SlicerDeployer._copy_notebooks")
    @patch("deploy.deploy_slicer.SlicerDeployer._apply_patches")
    @patch("deploy.deploy_slicer.make_archive")
    @patch("deploy.deploy_slicer.shutil")
    @patch("deploy.deploy_slicer.check_init_files")
    def test_archiving_step(
        self,
        mock_check_init: MagicMock,
        mock_shutil: MagicMock,
        mock_make_archive: MagicMock,
        mock_apply_patches: MagicMock,
        mock_copy_notebooks: MagicMock,
        mock_remove_unwanted_files: MagicMock,
        mock_copy_extra_files: MagicMock,
        mock_install_customizer: MagicMock,
        mock_subprocess: MagicMock,
        mock_ignore_patterns: MagicMock,
        mock_copy_extensions: MagicMock,
        mock_find_cli_source: MagicMock,
        mock_find_plugins_source: MagicMock,
        mock_install_module_from_folder: MagicMock,
        mock_find_submodules_setup_directory: MagicMock,
        mock_install_pip_dependencies: MagicMock,
        mock_uninstall_packages: MagicMock,
        mock_git: MagicMock,
        mock_get_slicer_version: MagicMock,
        mock_extract_archive: MagicMock,
        mock_revert: MagicMock,
        development: bool,
        disable_archive: bool,
        should_archive: bool,
    ) -> None:

        mock_args = _create_default_arguments_mock()
        mock_args.dev = development
        mock_args.geoslicer_version = "0.0" if not development else None
        mock_args.disable_archiving = disable_archive
        mock_args.archive = "None"

        with patch("deploy.deploy_slicer.Path.resolve", return_value=Path("None")):
            ds.run(mock_args)

        expect_call_count = 1 if should_archive else 0
        assert mock_make_archive.call_count == expect_call_count

    @patch("deploy.deploy_slicer.make_archive")
    @patch("deploy.deploy_slicer.shutil")
    @patch("deploy.deploy_slicer.SlicerDeployer._compile_bytecode")
    def test_production_build_compiles_bytecode_before_archiving(
        self, mock_compile_bytecode: MagicMock, mock_shutil: MagicMock, mock_make_archive: MagicMock
    ) -> None:
        steps = MagicMock()
        steps.attach_mock(mock_compile_bytecode, "compile_bytecode")
        steps.attach_mock(mock_make_archive, "make_archive")
        slicer_dir = self.temp_dir / "base"
        args = _create_default_arguments_mock()
        args.archive = str(slicer_dir)

        _create_deployer(args)._finalize_production_build(slicer_dir, "1.2.3")

        mock_compile_bytecode.assert_called_once_with(self.temp_dir / "GeoSlicer-1.2.3")
        assert [name for name, _, _ in steps.mock_calls] == ["compile_bytecode", "make_archive"]

    @pytest.mark.parametrize(
        "without_porespy, development",
        [
            pytest.param(True, False, id="without_porespy_production_mode"),
            pytest.param(False, False, id="with_porespy_production_mode"),
            pytest.param(True, True, id="without_porespy_development_mode"),
            pytest.param(False, True, id="with_porespy_development_mode"),
        ],
    )
    @patch("deploy.deploy_slicer._revert_partner_customization")
    @patch("deploy.deploy_slicer.SlicerDeployer._extract_archive")
    @patch("deploy.deploy_slicer.SlicerDeployer._get_slicer_version")
    @patch("deploy.deploy_slicer.SlicerDeployer._uninstall_packages")
    @patch("deploy.deploy_slicer.SlicerDeployer._install_pip_dependencies")
    @patch("deploy.deploy_slicer.git")
    @patch("deploy.deploy_slicer.find_submodules_setup_directory")
    @patch("deploy.deploy_slicer.SlicerDeployer._install_module_from_folder")
    @patch("deploy.deploy_slicer.SlicerDeployer._find_plugins_source")
    @patch("deploy.deploy_slicer.SlicerDeployer._find_cli_source")
    @patch("deploy.deploy_slicer.SlicerDeployer._copy_extensions")
    @patch("deploy.deploy_slicer.ignore_patterns")
    @patch("deploy.deploy_slicer.subprocess")
    @patch("deploy.deploy_slicer.SlicerDeployer._install_customizer")
    @patch("deploy.deploy_slicer.SlicerDeployer._copy_extra_files")
    @patch("deploy.deploy_slicer.SlicerDeployer._remove_unwanted_files")
    @patch("deploy.deploy_slicer.SlicerDeployer._copy_notebooks")
    @patch("deploy.deploy_slicer.SlicerDeployer._apply_patches")
    @patch("deploy.deploy_slicer.make_archive")
    @patch("deploy.deploy_slicer.shutil")
    @patch("deploy.deploy_slicer.check_init_files")
    def test_porespy_flag(
        self,
        mock_check_init: MagicMock,
        mock_shutil: MagicMock,
        mock_make_archive: MagicMock,
        mock_apply_patches: MagicMock,
        mock_copy_notebooks: MagicMock,
        mock_remove_unwanted_files: MagicMock,
        mock_copy_extra_files: MagicMock,
        mock_install_customizer: MagicMock,
        mock_subprocess: MagicMock,
        mock_ignore_patterns: MagicMock,
        mock_copy_extensions: MagicMock,
        mock_find_cli_source: MagicMock,
        mock_find_plugins_source: MagicMock,
        mock_install_module_from_folder: MagicMock,
        mock_find_submodules_setup_directory: MagicMock,
        mock_git: MagicMock,
        mock_install_pip_dependencies: MagicMock,
        mock_uninstall_packages: MagicMock,
        mock_get_slicer_version: MagicMock,
        mock_extract_archive: MagicMock,
        mock_revert: MagicMock,
        without_porespy: bool,
        development: bool,
    ) -> None:

        mock_args = _create_default_arguments_mock()
        mock_args.dev = development
        mock_args.geoslicer_version = "0.0" if not development else None
        mock_args.without_porespy = without_porespy
        mock_args.archive = "None"

        mock_porespy_path = MagicMock()
        mock_porespy_path.name = "porespy"
        mock_find_submodules_setup_directory.return_value = [mock_porespy_path]

        with patch("deploy.deploy_slicer.Path.resolve", return_value=Path("None")):
            ds.run(mock_args)

        expect_uninstall_package_call_count = 2 if without_porespy and development else 3
        expect_instal_module_call_count = 0 if without_porespy and development else 1
        assert mock_uninstall_packages.call_count == expect_uninstall_package_call_count
        assert mock_install_module_from_folder.call_count == expect_instal_module_call_count

    @patch("deploy.deploy_slicer._revert_partner_customization")
    @patch("deploy.deploy_slicer.inject_partner_files")
    @patch("deploy.deploy_slicer.SlicerDeployer.run")
    @patch("deploy.deploy_slicer.check_init_files")
    def test_run_calls_inject_partner_files(
        self, mock_check_init: MagicMock, mock_deployer_run: MagicMock, mock_inject: MagicMock, mock_revert: MagicMock
    ) -> None:
        args = _create_default_arguments_mock()
        args.partner = "some_partner"
        args.archive = "some_archive"
        args.geoslicer_version = "0.0"

        with patch("deploy.deploy_slicer.Path.resolve", return_value=Path("some_archive")):
            ds.run(args)

        mock_inject.assert_called_once_with(args)

    @patch("deploy.deploy_slicer._revert_partner_customization")
    @patch("deploy.deploy_slicer.inject_partner_files")
    @patch("deploy.deploy_slicer.SlicerDeployer.run")
    @patch("deploy.deploy_slicer.check_init_files")
    def test_run_calls_inject_partner_files_dev(
        self, mock_check_init: MagicMock, mock_deployer_run: MagicMock, mock_inject: MagicMock, mock_revert: MagicMock
    ) -> None:
        args = _create_default_arguments_mock()
        args.partner = "some_partner"
        args.archive = "some_archive"
        args.dev = True

        with patch("deploy.deploy_slicer.Path.resolve", return_value=Path("some_archive")):
            ds.run(args)

        mock_inject.assert_called_once_with(args)

    @patch("deploy.deploy_slicer._revert_partner_customization")
    @patch("deploy.deploy_slicer.SlicerDeployer.run")
    @patch("deploy.deploy_slicer.check_init_files")
    def test_run_calls_revert_partner_customization(
        self, mock_check_init: MagicMock, mock_deployer_run: MagicMock, mock_revert: MagicMock
    ) -> None:
        args = _create_default_arguments_mock()
        args.archive = "some_archive"

        with patch("deploy.deploy_slicer.Path.resolve", return_value=Path("some_archive")):
            ds.run(args)

        mock_revert.assert_called_once()

    @patch("deploy.deploy_slicer.revert_customization")
    @patch("deploy.deploy_slicer.PARTNERS_FOLDER")
    def test_revert_partner_customization_logic(
        self, mock_partners_folder: MagicMock, mock_revert_customization: MagicMock
    ) -> None:
        mock_partner1 = MagicMock()
        mock_partner1.is_dir.return_value = True
        mock_partner1.name = "partner1"

        mock_partner2 = MagicMock()
        mock_partner2.is_dir.return_value = True
        mock_partner2.name = "partner2"

        mock_file = MagicMock()
        mock_file.is_dir.return_value = False

        mock_partners_folder.glob.return_value = [mock_partner1, mock_partner2, mock_file]

        ds._revert_partner_customization()

        assert mock_revert_customization.call_count == 2
        mock_revert_customization.assert_any_call("partner1")
        mock_revert_customization.assert_any_call("partner2")

    @patch("deploy.deploy_slicer.SLICERLTRACE_REPO_FOLDER")
    def test_inject_partner_files_no_partner(self, mock_repo_folder: MagicMock) -> None:
        args = _create_default_arguments_mock()
        args.partner = None
        ds.inject_partner_files(args)
        mock_repo_folder.assert_not_called()

    @patch("deploy.deploy_slicer.SLICERLTRACE_REPO_FOLDER")
    def test_inject_partner_files_not_found(self, mock_repo_folder: MagicMock) -> None:
        with patch("deploy.deploy_slicer.SLICERLTRACE_REPO_FOLDER", self.temp_dir):
            with pytest.raises(RuntimeError, match="Partner directory not found"):
                args = _create_default_arguments_mock()
                args.partner = "non_existent"
                ds.inject_partner_files(args)

    @patch("deploy.partner_setup.logger")
    def test_inject_partner_files_no_overwrite_toml(self, mock_logger: MagicMock) -> None:
        partner_name = "test_partner"
        partner_dir = self.temp_dir / "src" / "partners" / partner_name
        partner_dir.mkdir(parents=True)

        with patch("deploy.deploy_slicer.SLICERLTRACE_REPO_FOLDER", self.temp_dir):
            args = _create_default_arguments_mock()
            args.partner = partner_name
            ds.inject_partner_files(args)

        mock_logger.info.assert_any_call(
            f"No overwrite.toml found for partner {partner_name}. Skipping file injection."
        )

    def test_inject_partner_files_success(self) -> None:
        partner_name = "test_partner"
        partner_dir = self.temp_dir / "src" / "partners" / partner_name
        partner_dir.mkdir(parents=True)

        # Create overwrite.toml
        overwrite_toml_path = partner_dir / "overwrite.toml"
        overwrite_toml_path.write_text(
            """
[overwrites]
"file1.txt" = "dest/file1.txt"
"folder1" = "dest/folder1"
""",
            encoding="utf-8",
        )

        # Create source files
        (partner_dir / "file1.txt").write_text("content1")
        (partner_dir / "folder1").mkdir()
        (partner_dir / "folder1" / "subfile.txt").write_text("subcontent")

        # Create destination file to be overwritten
        dest_file = self.temp_dir / "dest" / "file1.txt"
        dest_file.parent.mkdir(parents=True)
        dest_file.write_text("old_content")

        with patch("deploy.deploy_slicer.SLICERLTRACE_REPO_FOLDER", self.temp_dir):
            args = _create_default_arguments_mock()
            args.partner = partner_name
            args.dev = False
            ds.inject_partner_files(args)

        assert dest_file.read_text() == "content1"
        assert (self.temp_dir / "dest" / "folder1" / "subfile.txt").read_text() == "subcontent"
        assert not dest_file.is_symlink()

    @patch("os.symlink")
    def test_inject_partner_files_symlink_dev(self, mock_symlink: MagicMock) -> None:
        partner_name = "test_partner"
        partner_dir = self.temp_dir / "src" / "partners" / partner_name
        partner_dir.mkdir(parents=True)

        # Create overwrite.toml
        overwrite_toml_path = partner_dir / "overwrite.toml"
        overwrite_toml_path.write_text(
            """
[overwrites]
"file1.txt" = "dest/file1.txt"
"folder1" = "dest/folder1"
""",
            encoding="utf-8",
        )

        # Create source files
        src_file = partner_dir / "file1.txt"
        src_file.write_text("content1")
        src_folder = partner_dir / "folder1"
        src_folder.mkdir()
        (src_folder / "subfile.txt").write_text("subcontent")

        with patch("deploy.deploy_slicer.SLICERLTRACE_REPO_FOLDER", self.temp_dir):
            args = _create_default_arguments_mock()
            args.partner = partner_name
            args.dev = True
            ds.inject_partner_files(args)

        dest_file = self.temp_dir / "dest" / "file1.txt"
        dest_folder = self.temp_dir / "dest" / "folder1"

        mock_symlink.assert_any_call(src_file, dest_file, target_is_directory=False)
        mock_symlink.assert_any_call(src_folder, dest_folder, target_is_directory=True)

    def test_inject_partner_files_src_subfolder(self) -> None:
        partner_name = "test_partner"
        partner_dir = self.temp_dir / "src" / "partners" / partner_name
        partner_dir.mkdir(parents=True)

        # Create overwrite.toml
        overwrite_toml_path = partner_dir / "overwrite.toml"
        overwrite_toml_path.write_text(
            """
[overwrites]
"file2.txt" = "dest/file2.txt"
""",
            encoding="utf-8",
        )

        # Create source file under src/
        (partner_dir / "src").mkdir()
        (partner_dir / "src" / "file2.txt").write_text("content2")

        with patch("deploy.deploy_slicer.SLICERLTRACE_REPO_FOLDER", self.temp_dir):
            args = _create_default_arguments_mock()
            args.partner = partner_name
            ds.inject_partner_files(args)

        assert (self.temp_dir / "dest" / "file2.txt").read_text() == "content2"

    @patch("deploy.deploy_slicer.subprocess.check_call")
    @patch("deploy.deploy_slicer.shutil.rmtree")
    @patch("deploy.deploy_slicer.Path.exists")
    def test_build_manual(self, mock_exists, mock_rmtree, mock_check_call):
        mock_exists.return_value = True
        ds.build_manual()
        assert mock_rmtree.call_count == 2
        mock_check_call.assert_called_once()

    def test_get_slicer_version(self, tmp_path):
        slicer_dir = tmp_path / "slicer"
        lib_dir = slicer_dir / "lib"
        lib_dir.mkdir(parents=True)
        (lib_dir / "GeoSlicer-5.0").mkdir()

        version = _create_deployer()._get_slicer_version(slicer_dir)
        assert version == "5.0"

    @patch("deploy.deploy_slicer.git")
    def test_repo_metadata_comes_from_git_by_default(self, mock_git: MagicMock) -> None:
        mock_git.Repo.return_value.head.object.hexsha = "abc123"
        mock_git.Repo.return_value.is_dirty.return_value = True

        assert ds.get_repo_metadata(use_git=True) == ("abc123", True)

    @patch("deploy.deploy_slicer.git")
    def test_repo_metadata_uses_placeholders_without_git(self, mock_git: MagicMock) -> None:
        assert ds.get_repo_metadata(use_git=False) == (ds.UNKNOWN_COMMIT_HASH, False)
        mock_git.Repo.assert_not_called()

    def test_placeholder_hash_is_a_string(self) -> None:
        """parseApplicationVersion slices GEOSLICER_HASH, so None would crash
        the application at startup instead of the deploy."""
        commit_hash, is_dirty = ds.get_repo_metadata(use_git=False)

        assert isinstance(commit_hash, str)
        assert is_dirty is False

    @pytest.mark.parametrize(
        "no_git",
        [
            pytest.param(False, id="with_git"),
            pytest.param(True, id="without_git"),
        ],
    )
    @patch("deploy.deploy_slicer.SlicerDeployer._install_default_settings")
    @patch("deploy.deploy_slicer.get_repo_metadata", return_value=("abc123", False))
    @patch("deploy.deploy_slicer.get_plugins_dir")
    def test_customizer_reads_repo_metadata_according_to_no_git(
        self,
        mock_get_plugins_dir: MagicMock,
        mock_get_repo_metadata: MagicMock,
        mock_install_default_settings: MagicMock,
        no_git: bool,
    ) -> None:
        slicer_dir = self.temp_dir / "slicer"
        slicer_dir.mkdir()
        mock_get_plugins_dir.return_value = self.temp_dir / "plugins"
        args = _create_default_arguments_mock()
        args.dev = True
        args.no_git = no_git

        _create_deployer(args)._install_customizer(slicer_dir, [self.temp_dir / "modules" / "Mod"], [], None)

        mock_get_repo_metadata.assert_called_once_with(not no_git)

    @pytest.mark.parametrize(
        "no_git, expect_submodule_update",
        [
            pytest.param(False, True, id="submodule_update_with_git"),
            pytest.param(True, False, id="submodule_update_skipped_without_git"),
        ],
    )
    @patch("deploy.deploy_slicer._revert_partner_customization")
    @patch("deploy.deploy_slicer.build_manual")
    @patch("deploy.deploy_slicer.git")
    @patch("deploy.deploy_slicer.SlicerDeployer._extract_archive")
    @patch("deploy.deploy_slicer.SlicerDeployer._get_slicer_version")
    @patch("deploy.deploy_slicer.SlicerDeployer._apply_pre_patches")
    @patch("deploy.deploy_slicer.SlicerDeployer._install_dependencies")
    @patch("deploy.deploy_slicer.SlicerDeployer._handle_extensions")
    @patch("deploy.deploy_slicer.SlicerDeployer._find_extensions")
    @patch("deploy.deploy_slicer.SlicerDeployer._install_customizer")
    @patch("deploy.deploy_slicer.SlicerDeployer._copy_extra_files")
    @patch("deploy.deploy_slicer.SlicerDeployer._remove_unwanted_files")
    @patch("deploy.deploy_slicer.SlicerDeployer._copy_notebooks")
    @patch("deploy.deploy_slicer.SlicerDeployer._apply_patches")
    def test_submodule_update_is_skipped_without_git(
        self,
        mock_apply_patches: MagicMock,
        mock_copy_notebooks: MagicMock,
        mock_remove_unwanted_files: MagicMock,
        mock_copy_extra_files: MagicMock,
        mock_install_customizer: MagicMock,
        mock_find_extensions: MagicMock,
        mock_handle_extensions: MagicMock,
        mock_install_dependencies: MagicMock,
        mock_apply_pre_patches: MagicMock,
        mock_get_slicer_version: MagicMock,
        mock_extract_archive: MagicMock,
        mock_git: MagicMock,
        mock_build_manual: MagicMock,
        mock_revert: MagicMock,
        no_git: bool,
        expect_submodule_update: bool,
    ) -> None:
        mock_args = _create_default_arguments_mock()
        mock_args.dev = True
        mock_args.no_git = no_git

        ds.run(mock_args)

        assert mock_git.Repo.called == expect_submodule_update

    @pytest.mark.parametrize(
        "partner, partner_commit, expected_partner, expected_partner_commit",
        [
            pytest.param(["petrobras"], "PL-3200", ["petrobras"], "PL-3200", id="partner_with_custom_commit"),
            pytest.param(["petrobras"], "master", ["petrobras"], "master", id="partner_with_default_commit"),
            pytest.param(None, "master", None, None, id="no_partner"),
        ],
    )
    @patch("deploy.deploy_slicer.SlicerDeployer._install_default_settings")
    @patch("deploy.deploy_slicer.git")
    def test_install_customizer_records_partner_commit_metadata(
        self,
        mock_git: MagicMock,
        mock_install_default_settings: MagicMock,
        partner,
        partner_commit,
        expected_partner,
        expected_partner_commit,
    ) -> None:
        mock_repo = MagicMock()
        mock_repo.head.object.hexsha = "deadbeef"
        mock_repo.is_dirty.return_value = False
        mock_git.Repo.return_value = mock_repo

        slicer_dir = self.temp_dir / "GeoSlicer-1.0"
        lib_dir = slicer_dir / "lib" / "GeoSlicer-1.0"
        lib_dir.mkdir(parents=True)

        mock_args = _create_default_arguments_mock()
        mock_args.archive = "None"
        mock_args.partner = partner
        mock_args.partner_commit = partner_commit

        deployer = ds.SlicerDeployer(mock_args)
        modules = [slicer_dir / "modules" / "SomeModule"]

        deployer._install_customizer(slicer_dir, modules, [], "1.0.0")

        json_path = lib_dir / "qt-scripted-modules" / "Resources" / "json" / "GeoSlicer.json"
        with open(json_path) as f:
            data = json.load(f)

        assert data["PARTNER"] == expected_partner
        assert data["PARTNER_COMMIT"] == expected_partner_commit

    def test_default_settings_point_startup_modules_and_clis_into_the_installation(self) -> None:
        slicer_dir = self.temp_dir / "GeoSlicer-1.0"
        plugins_dir = slicer_dir / "lib" / "GeoSlicer-5.10"
        (slicer_dir / "share" / "GeoSlicer-5.10").mkdir(parents=True)
        modules = [
            _create_scripted_module(plugins_dir / "qt-scripted-modules", "Startup"),
            _create_scripted_module(plugins_dir / "qt-scripted-modules", "Lazy"),
            _create_scripted_module(plugins_dir / "cli-modules", "SomeCLI"),
        ]
        staleRevisionSettings = slicer_dir / "LTrace" / "GeoSlicer-1234.ini"
        _create_dummy_files_from_path([staleRevisionSettings])
        config = self.temp_dir / "config.json"
        config.write_text(json.dumps({"StartupModules": ["Startup"]}))

        deployer = _create_deployer()
        with patch.object(ds, "DEPLOY_CONFIG", config):
            index = deployer._index_modules(slicer_dir, modules)
            deployer._install_default_settings(slicer_dir, index)

        assert {m["key"]: m["path"] for m in index} == {
            "Startup": "lib/GeoSlicer-5.10/qt-scripted-modules/Startup/Startup.py",
            "Lazy": "lib/GeoSlicer-5.10/qt-scripted-modules/Lazy/Lazy.py",
            "SomeCLI": "lib/GeoSlicer-5.10/cli-modules/SomeCLI/SomeCLI.py",
        }
        settings = (slicer_dir / "share" / "GeoSlicer-5.10" / "GeoSlicerDefaultSettings.ini").read_text()
        assert (
            'AdditionalPaths="lib/GeoSlicer-5.10/qt-scripted-modules/Startup", "lib/GeoSlicer-5.10/cli-modules/SomeCLI"\n'
            in settings
        )
        assert not staleRevisionSettings.exists()

    def test_default_settings_reject_missing_startup_module(self) -> None:
        slicer_dir = self.temp_dir / "GeoSlicer-1.0"
        (slicer_dir / "lib" / "GeoSlicer-5.10").mkdir(parents=True)
        config = self.temp_dir / "config.json"
        config.write_text(json.dumps({"StartupModules": ["Renamed"]}))

        with patch.object(ds, "DEPLOY_CONFIG", config), pytest.raises(RuntimeError, match="Renamed"):
            _create_deployer()._install_default_settings(slicer_dir, [])


@pytest.mark.parametrize(
    "version, expected_string",
    [
        pytest.param("2.3.1", "2.3.1", id="2.3.1"),
        pytest.param("1.10", "1.10.0", id="1.10"),
        pytest.param("2.5.0RC2", "2.5.0RC2", id="2.5.0RC2"),
        pytest.param("3", "3.0.0", id="3"),
        pytest.param("0.0", "0.0.0", id="0.0"),
    ],
)
def test_get_version_string(version, expected_string) -> None:
    generated_string = ds.get_version_string(version)
    assert generated_string == expected_string, f"Expected '{version}', got '{generated_string}'"


def test_parse_output_directory() -> None:
    args = _create_default_arguments_mock()

    with tempfile.TemporaryDirectory() as temp_dir:
        args.output_dir = temp_dir
        temp_dir_path = Path(temp_dir)
        assert ds.parse_output_dir(args) == temp_dir_path

        temp_file_path = temp_dir_path / "file.txt"
        temp_file_path.touch()
        args.output_dir = temp_file_path.as_posix()
        assert ds.parse_output_dir(args) == temp_dir_path

    args.output_dir = None
    assert ds.parse_output_dir(args) is None

    args.output_dir = ""
    assert ds.parse_output_dir(args) is None

    args.output_dir = "  "
    assert ds.parse_output_dir(args) is None


def test_headless_opencv_requirement_is_pinned_by_commons() -> None:
    """Without the pin, the deploy installs whatever OpenCV version is latest."""
    assert ds._headless_opencv_requirement().startswith(f"{ds.OPENCV_HEADLESS_PACKAGE}==")
