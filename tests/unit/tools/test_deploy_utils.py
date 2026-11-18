from pathlib import Path
from unittest.mock import MagicMock, patch
import deploy.utils as utils
import git


class TestDeployUtils:
    @patch("git.Repo")
    @patch("pathlib.Path.cwd")
    def test_get_repo_root_success(self, mock_cwd, mock_repo_class):
        mock_cwd.return_value = Path("/some/path/to/repo/subdir")
        mock_repo = MagicMock()
        mock_repo.working_tree_dir = "/some/path/to/repo"
        mock_repo_class.return_value = mock_repo

        root = utils.get_repo_root()
        # Use resolve() to ensure both paths are comparable in the same way (including drive letters on Windows)
        assert root.resolve() == Path("/some/path/to/repo").resolve()
        mock_repo_class.assert_called_once_with(Path("/some/path/to/repo/subdir"), search_parent_directories=True)

    @patch("git.Repo")
    @patch("pathlib.Path.cwd")
    def test_get_repo_root_no_git(self, mock_cwd, mock_repo_class):
        mock_cwd.return_value = Path("/not/a/repo")
        mock_repo_class.side_effect = git.InvalidGitRepositoryError

        root = utils.get_repo_root()
        assert Path(root) == Path("/not/a/repo").resolve()

    @patch("git.Repo")
    @patch("pathlib.Path.cwd")
    def test_get_repo_root_no_path(self, mock_cwd, mock_repo_class):
        mock_cwd.return_value = Path("/invalid/path")
        mock_repo_class.side_effect = git.NoSuchPathError

        root = utils.get_repo_root()
        assert Path(root) == Path("/invalid/path").resolve()

    def test_find_submodules_setup_directory(self, tmp_path):
        submodule_dir = tmp_path / "submodule"
        submodule_dir.mkdir()
        (submodule_dir / "setup.py").touch()

        another_dir = tmp_path / "another"
        another_dir.mkdir()
        (another_dir / "pyproject.toml").touch()

        no_setup_dir = tmp_path / "empty"
        no_setup_dir.mkdir()

        results = utils.find_submodules_setup_directory(tmp_path)
        assert results == {submodule_dir, another_dir}

    def test_find_submodules_setup_directory_empty(self, tmp_path):
        assert utils.find_submodules_setup_directory(tmp_path) == set()

    def test_find_submodules_setup_directory_returns_set(self, tmp_path):
        assert isinstance(utils.find_submodules_setup_directory(tmp_path), set)

    def test_find_submodules_setup_directory_deduplicates_both_files(self, tmp_path):
        submodule_dir = tmp_path / "submodule"
        submodule_dir.mkdir()
        (submodule_dir / "setup.py").touch()
        (submodule_dir / "pyproject.toml").touch()

        results = utils.find_submodules_setup_directory(tmp_path)
        assert results == {submodule_dir}

    def test_find_submodules_setup_directory_nested(self, tmp_path):
        nested_dir = tmp_path / "a" / "b" / "c"
        nested_dir.mkdir(parents=True)
        (nested_dir / "setup.py").touch()

        results = utils.find_submodules_setup_directory(tmp_path)
        assert results == {nested_dir}

    def test_find_submodules_setup_directory_ignores_venv(self, tmp_path):
        submodule_dir = tmp_path / "submodule"
        submodule_dir.mkdir()
        (submodule_dir / "setup.py").touch()

        venv_pkg_dir = tmp_path / ".venv" / "lib" / "site-packages" / "pkg"
        venv_pkg_dir.mkdir(parents=True)
        (venv_pkg_dir / "setup.py").touch()
        (venv_pkg_dir / "pyproject.toml").touch()

        results = utils.find_submodules_setup_directory(tmp_path)
        assert results == {submodule_dir}

    def test_find_submodules_setup_directory_ignores_nested_venv(self, tmp_path):
        submodule_dir = tmp_path / "submodule"
        venv_dir = submodule_dir / ".venv" / "pkg"
        venv_dir.mkdir(parents=True)
        (submodule_dir / "pyproject.toml").touch()
        (venv_dir / "setup.py").touch()

        results = utils.find_submodules_setup_directory(tmp_path)
        assert results == {submodule_dir}

    def test_find_submodules_setup_directory_keeps_similar_names(self, tmp_path):
        similar_dir = tmp_path / "my.venv"
        similar_dir.mkdir()
        (similar_dir / "setup.py").touch()

        results = utils.find_submodules_setup_directory(tmp_path)
        assert results == {similar_dir}

    def test_find_submodules_setup_directory_venv_above_root_not_excluded(self, tmp_path):
        root = tmp_path / ".venv" / "project"
        root.mkdir(parents=True)
        (root / "setup.py").touch()

        results = utils.find_submodules_setup_directory(root)
        assert results == {root}
