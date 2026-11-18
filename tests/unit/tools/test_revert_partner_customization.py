import pytest
import shutil
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import deploy.revert_partner_customization as rpc
import git


class TestRevertPartnerCustomization:
    def setup_method(self) -> None:
        self.temp_dir = Path(tempfile.TemporaryDirectory().name)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        # Mock repo root as the temp dir
        self.repo_root = self.temp_dir
        (self.repo_root / ".git").mkdir()

    def teardown_method(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    @patch("deploy.revert_partner_customization.get_repo_root")
    @patch("git.Repo")
    def test_revert_customization_success(self, mock_repo_class, mock_get_repo_root):
        mock_get_repo_root.return_value = self.repo_root
        mock_repo = MagicMock()
        mock_repo_class.return_value = mock_repo

        # Mock ls_files to return the path (tracked)
        mock_repo.git.ls_files.side_effect = lambda x: x

        partner_name = "test_partner"
        partner_dir = self.repo_root / "src" / "partners" / partner_name
        partner_dir.mkdir(parents=True)

        overwrite_toml_path = partner_dir / "overwrite.toml"
        overwrite_toml_path.write_text('[overwrites]\n"src/a" = "src/b"\n"src/c" = "src/d"', encoding="utf-8")

        # Create some files to be reverted
        b_path = self.repo_root / "src/b"
        b_path.parent.mkdir(parents=True, exist_ok=True)
        b_path.touch()

        d_path = self.repo_root / "src/d"
        d_path.mkdir(parents=True, exist_ok=True)
        (d_path / "file.txt").touch()

        success = rpc.revert_customization(partner_name)

        assert success is True
        assert not b_path.exists()
        assert not d_path.exists()

        # Check git calls
        assert mock_repo.git.checkout.call_count == 2
        mock_repo.git.checkout.assert_any_call("--", "src/b")
        mock_repo.git.checkout.assert_any_call("--", "src/d")

    @patch("deploy.revert_partner_customization.get_repo_root")
    @patch("git.Repo")
    def test_revert_customization_untracked_file(self, mock_repo_class, mock_get_repo_root):
        mock_get_repo_root.return_value = self.repo_root
        mock_repo = MagicMock()
        mock_repo_class.return_value = mock_repo

        # Mock ls_files to return empty string (untracked)
        mock_repo.git.ls_files.return_value = ""

        partner_name = "test_partner"
        partner_dir = self.repo_root / "src" / "partners" / partner_name
        partner_dir.mkdir(parents=True)

        overwrite_toml_path = partner_dir / "overwrite.toml"
        overwrite_toml_path.write_text('[overwrites]\n"src/a" = "src/untracked"', encoding="utf-8")

        untracked_path = self.repo_root / "src/untracked"
        untracked_path.parent.mkdir(parents=True, exist_ok=True)
        untracked_path.touch()

        success = rpc.revert_customization(partner_name)

        assert success is True
        assert not untracked_path.exists()

        # Checkout and clean should NOT be called for untracked files
        assert mock_repo.git.checkout.call_count == 0
        assert mock_repo.git.clean.call_count == 0

    @patch("deploy.revert_partner_customization.get_repo_root")
    def test_revert_customization_no_partner(self, mock_get_repo_root):
        mock_get_repo_root.return_value = self.repo_root
        success = rpc.revert_customization("non_existent")
        assert success is False

    @patch("deploy.revert_partner_customization.get_repo_root")
    @patch("git.Repo")
    def test_revert_customization_git_failure(self, mock_repo_class, mock_get_repo_root):
        mock_get_repo_root.return_value = self.repo_root
        mock_repo = MagicMock()
        mock_repo_class.return_value = mock_repo
        mock_repo.git.ls_files.return_value = "src/b"
        mock_repo.git.checkout.side_effect = git.GitCommandError("checkout", 1)

        partner_name = "test_partner"
        partner_dir = self.repo_root / "src" / "partners" / partner_name
        partner_dir.mkdir(parents=True)

        overwrite_toml_path = partner_dir / "overwrite.toml"
        overwrite_toml_path.write_text('[overwrites]\n"src/a" = "src/b"', encoding="utf-8")

        success = rpc.revert_customization(partner_name)
        assert success is False

    @patch("deploy.revert_partner_customization.get_repo_root")
    @patch("git.Repo")
    def test_revert_customization_symlink(self, mock_repo_class, mock_get_repo_root):
        mock_get_repo_root.return_value = self.repo_root
        mock_repo = MagicMock()
        mock_repo_class.return_value = mock_repo
        mock_repo.git.ls_files.return_value = "src/b"

        partner_name = "test_partner"
        partner_dir = self.repo_root / "src" / "partners" / partner_name
        partner_dir.mkdir(parents=True)

        overwrite_toml_path = partner_dir / "overwrite.toml"
        overwrite_toml_path.write_text('[overwrites]\n"src/a" = "src/b"', encoding="utf-8")

        # Create a symlink
        b_path = self.repo_root / "src/b"
        b_path.parent.mkdir(parents=True, exist_ok=True)
        target = self.repo_root / "some_target"
        target.touch()

        try:
            os.symlink(target, b_path)
        except OSError:
            pytest.skip("Symlinks not supported on this platform/user")

        assert b_path.is_symlink()

        success = rpc.revert_customization(partner_name)

        assert success is True
        assert not b_path.exists()
        assert not b_path.is_symlink()
