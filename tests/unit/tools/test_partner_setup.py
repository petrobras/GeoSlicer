import pytest
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from deploy.partner_setup import (
    inject_partner_files,
    install_partner_dependencies,
)


class TestPartnerSetup:
    def setup_method(self) -> None:
        """Test case setup"""
        self.temp_dir = Path(tempfile.TemporaryDirectory().name)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def teardown_method(self) -> None:
        """Test case teardown"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_inject_partner_files_no_partner(self) -> None:
        # Should return early without doing anything
        with patch("deploy.partner_setup.logger") as mock_logger:
            inject_partner_files(None, repo_root=self.temp_dir)
            mock_logger.info.assert_not_called()

    def test_inject_partner_files_not_found(self) -> None:
        with pytest.raises(RuntimeError, match="Partner directory not found"):
            inject_partner_files("non_existent", repo_root=self.temp_dir)

    def test_inject_partner_files_no_overwrite_toml(self) -> None:
        partner_name = "test_partner"
        partner_dir = self.temp_dir / "src" / "partners" / partner_name
        partner_dir.mkdir(parents=True)

        with patch("deploy.partner_setup.logger") as mock_logger:
            inject_partner_files(partner_name, repo_root=self.temp_dir)
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

        inject_partner_files(partner_name, repo_root=self.temp_dir)

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
""",
            encoding="utf-8",
        )

        src_file = partner_dir / "file1.txt"
        src_file.write_text("content1")

        inject_partner_files(partner_name, development=True, repo_root=self.temp_dir)

        dest_file = self.temp_dir / "dest" / "file1.txt"
        mock_symlink.assert_called_once_with(src_file, dest_file, target_is_directory=False)

    @patch("subprocess.check_call")
    def test_install_partner_dependencies(self, mock_check_call: MagicMock) -> None:
        partner_name = "test_partner"
        partner_dir = self.temp_dir / "src" / "partners" / partner_name
        tp_dir = partner_dir / "src" / "third-parties" / "submod1"
        tp_dir.mkdir(parents=True)
        (partner_dir / "pyproject.toml").touch()
        (tp_dir / "pyproject.toml").touch()

        install_partner_dependencies(partner_name, repo_root=self.temp_dir)

        assert mock_check_call.call_count == 2  # 1 for project dependencies, 1 for submodule dependencies
        args = mock_check_call.call_args_list
        args_call_1 = " ".join(args[0].args[0])
        args_call_2 = " ".join(args[1].args[0])
        assert "pip" in args_call_1 and "install" in args_call_1 and str(partner_dir) in args_call_1
        assert "pip" in args_call_2 and "install" in args_call_2 and str(tp_dir) in args_call_2

    @patch("builtins.input")
    def test_inject_multiple_partners_no_conflicts(self, mock_input: MagicMock) -> None:
        # Create partner A
        partner_a_dir = self.temp_dir / "src" / "partners" / "partner_a"
        partner_a_dir.mkdir(parents=True)
        (partner_a_dir / "overwrite.toml").write_text('[overwrites]\n"file_a.txt" = "dest/file_a.txt"\n')
        (partner_a_dir / "file_a.txt").write_text("content_a")

        # Create partner B
        partner_b_dir = self.temp_dir / "src" / "partners" / "partner_b"
        partner_b_dir.mkdir(parents=True)
        (partner_b_dir / "overwrite.toml").write_text('[overwrites]\n"file_b.txt" = "dest/file_b.txt"\n')
        (partner_b_dir / "file_b.txt").write_text("content_b")

        inject_partner_files(["partner_a", "partner_b"], repo_root=self.temp_dir)

        assert (self.temp_dir / "dest" / "file_a.txt").read_text() == "content_a"
        assert (self.temp_dir / "dest" / "file_b.txt").read_text() == "content_b"
        mock_input.assert_not_called()

    @patch("builtins.input")
    def test_inject_multiple_partners_with_conflicts_resolve_first(self, mock_input: MagicMock) -> None:
        mock_input.return_value = "1"  # Choose first partner (partner_a)

        # Create partner A
        partner_a_dir = self.temp_dir / "src" / "partners" / "partner_a"
        partner_a_dir.mkdir(parents=True)
        (partner_a_dir / "overwrite.toml").write_text('[overwrites]\n"file.txt" = "dest/file.txt"\n')
        (partner_a_dir / "file.txt").write_text("content_a")

        # Create partner B
        partner_b_dir = self.temp_dir / "src" / "partners" / "partner_b"
        partner_b_dir.mkdir(parents=True)
        (partner_b_dir / "overwrite.toml").write_text('[overwrites]\n"file.txt" = "dest/file.txt"\n')
        (partner_b_dir / "file.txt").write_text("content_b")

        inject_partner_files(["partner_a", "partner_b"], repo_root=self.temp_dir)

        assert (self.temp_dir / "dest" / "file.txt").read_text() == "content_a"
        mock_input.assert_called_once()

    @patch("builtins.input")
    def test_inject_multiple_partners_with_conflicts_resolve_second(self, mock_input: MagicMock) -> None:
        mock_input.return_value = "2"  # Choose second partner (partner_b)

        # Create partner A
        partner_a_dir = self.temp_dir / "src" / "partners" / "partner_a"
        partner_a_dir.mkdir(parents=True)
        (partner_a_dir / "overwrite.toml").write_text('[overwrites]\n"file.txt" = "dest/file.txt"\n')
        (partner_a_dir / "file.txt").write_text("content_a")

        # Create partner B
        partner_b_dir = self.temp_dir / "src" / "partners" / "partner_b"
        partner_b_dir.mkdir(parents=True)
        (partner_b_dir / "overwrite.toml").write_text('[overwrites]\n"file.txt" = "dest/file.txt"\n')
        (partner_b_dir / "file.txt").write_text("content_b")

        inject_partner_files(["partner_a", "partner_b"], repo_root=self.temp_dir)

        assert (self.temp_dir / "dest" / "file.txt").read_text() == "content_b"
        mock_input.assert_called_once()

    @patch("builtins.input")
    def test_inject_multiple_partners_with_conflicts_wrong_input_first(self, mock_input: MagicMock) -> None:
        mock_input.side_effect = ["3", "2"]  # Choose second partner (partner_b)

        # Create partner A
        partner_a_dir = self.temp_dir / "src" / "partners" / "partner_a"
        partner_a_dir.mkdir(parents=True)
        (partner_a_dir / "overwrite.toml").write_text('[overwrites]\n"file.txt" = "dest/file.txt"\n')
        (partner_a_dir / "file.txt").write_text("content_a")

        # Create partner B
        partner_b_dir = self.temp_dir / "src" / "partners" / "partner_b"
        partner_b_dir.mkdir(parents=True)
        (partner_b_dir / "overwrite.toml").write_text('[overwrites]\n"file.txt" = "dest/file.txt"\n')
        (partner_b_dir / "file.txt").write_text("content_b")

        inject_partner_files(["partner_a", "partner_b"], repo_root=self.temp_dir)

        assert (self.temp_dir / "dest" / "file.txt").read_text() == "content_b"
        assert mock_input.call_count == 2

    @patch("builtins.input")
    def test_inject_multiple_partners_with_conflicts_handle_eoferror(self, mock_input: MagicMock) -> None:
        mock_input.side_effect = EOFError()  # Choose first partner (partner_a) due to error

        # Create partner A
        partner_a_dir = self.temp_dir / "src" / "partners" / "partner_a"
        partner_a_dir.mkdir(parents=True)
        (partner_a_dir / "overwrite.toml").write_text('[overwrites]\n"file.txt" = "dest/file.txt"\n')
        (partner_a_dir / "file.txt").write_text("content_a")

        # Create partner B
        partner_b_dir = self.temp_dir / "src" / "partners" / "partner_b"
        partner_b_dir.mkdir(parents=True)
        (partner_b_dir / "overwrite.toml").write_text('[overwrites]\n"file.txt" = "dest/file.txt"\n')
        (partner_b_dir / "file.txt").write_text("content_b")

        inject_partner_files(["partner_a", "partner_b"], repo_root=self.temp_dir)

        assert (self.temp_dir / "dest" / "file.txt").read_text() == "content_a"
        mock_input.assert_called_once()

    @patch("builtins.input")
    def test_inject_multiple_partners_with_conflicts_folder_tree_replacement(self, mock_input: MagicMock) -> None:
        mock_input.return_value = "2"

        # Create partner A
        partner_a_dir = self.temp_dir / "src" / "partners" / "partner_a"
        partner_a_subfolder = partner_a_dir / "subfolder"
        partner_a_sub_subfolder = partner_a_subfolder / "a"
        partner_a_sub_subfolder.mkdir(parents=True)
        (partner_a_dir / "overwrite.toml").write_text('[overwrites]\n"subfolder/" = "dest/"\n')
        (partner_a_sub_subfolder / "file.txt").write_text("content_a")

        # Create partner B
        partner_b_dir = self.temp_dir / "src" / "partners" / "partner_b"
        partner_b_subfolder = partner_b_dir / "subfolder"
        partner_b_subfolder.mkdir(parents=True)
        (partner_b_dir / "overwrite.toml").write_text('[overwrites]\n"subfolder/" = "dest/"\n')
        (partner_b_subfolder / "file.txt").write_text("content_b")

        inject_partner_files(["partner_a", "partner_b"], repo_root=self.temp_dir)

        mock_input.assert_called_once()
        assert not (self.temp_dir / "dest" / "a" / "file.txt").exists()
        assert (self.temp_dir / "dest" / "file.txt").read_text() == "content_b"

    @patch("builtins.input")
    def test_inject_multiple_partners_with_conflicts_files_replacement_for_directory(
        self, mock_input: MagicMock
    ) -> None:
        mock_input.return_value = "2"

        # Create partner A
        partner_a_dir = self.temp_dir / "src" / "partners" / "partner_a"
        partner_a_subfolder = partner_a_dir / "subfolder"
        partner_a_subfolder.mkdir(parents=True)
        (partner_a_dir / "overwrite.toml").write_text(
            '[overwrites]\n"subfolder/file1.txt" = "dest/file1.txt"\n"subfolder/file2.txt" = "dest/file2.txt"\n'
        )
        (partner_a_subfolder / "file1.txt").write_text("content_a")
        (partner_a_subfolder / "file2.txt").write_text("content_a")

        # Create partner B
        partner_b_dir = self.temp_dir / "src" / "partners" / "partner_b"
        partner_b_subfolder = partner_b_dir / "subfolder"
        partner_b_subfolder.mkdir(parents=True)
        (partner_b_dir / "overwrite.toml").write_text('[overwrites]\n"subfolder/" = "dest/"\n')
        (partner_b_subfolder / "file.txt").write_text("content_b")

        inject_partner_files(["partner_a", "partner_b"], repo_root=self.temp_dir)

        mock_input.assert_called_once()
        assert (self.temp_dir / "dest" / "file.txt").exists()
        assert (self.temp_dir / "dest" / "file.txt").read_text() == "content_b"

    @patch("builtins.input")
    def test_inject_three_partners_sequential_conflict(self, mock_input: MagicMock) -> None:
        # 1. Partner A vs Partner B (User chooses B)
        # 2. Partner B vs Partner C (User chooses C)
        mock_input.side_effect = ["2", "2"]

        # Partner A
        partner_a_dir = self.temp_dir / "src" / "partners" / "partner_a"
        partner_a_dir.mkdir(parents=True)
        (partner_a_dir / "overwrite.toml").write_text('[overwrites]\n"file.txt" = "dest/file.txt"\n')
        (partner_a_dir / "file.txt").write_text("content_a")

        # Partner B
        partner_b_dir = self.temp_dir / "src" / "partners" / "partner_b"
        partner_b_dir.mkdir(parents=True)
        (partner_b_dir / "overwrite.toml").write_text('[overwrites]\n"file.txt" = "dest/file.txt"\n')
        (partner_b_dir / "file.txt").write_text("content_b")

        # Partner C
        partner_c_dir = self.temp_dir / "src" / "partners" / "partner_c"
        partner_c_dir.mkdir(parents=True)
        (partner_c_dir / "overwrite.toml").write_text('[overwrites]\n"file.txt" = "dest/file.txt"\n')
        (partner_c_dir / "file.txt").write_text("content_c")

        inject_partner_files(["partner_a", "partner_b", "partner_c"], repo_root=self.temp_dir)

        # Assertions
        assert mock_input.call_count == 2
        assert (self.temp_dir / "dest" / "file.txt").read_text() == "content_c"

    @patch("builtins.input")
    def test_three_partners_mixed_directory_and_file_conflict(self, mock_input: MagicMock) -> None:
        # 1. Partner A (files) vs Partner B (directory) -> User selects 2 (Partner B wins, cache hits on second file)
        # 2. Partner B (directory) vs Partner C (single file) -> User selects 2 (Partner C wins specific file)
        mock_input.side_effect = ["2", "2"]

        # Partner A: Specific files
        partner_a_dir = self.temp_dir / "src" / "partners" / "partner_a"
        partner_a_dir.mkdir(parents=True)
        (partner_a_dir / "overwrite.toml").write_text(
            '[overwrites]\n"file1.txt" = "dest/file1.txt"\n"file2.txt" = "dest/file2.txt"\n'
        )
        (partner_a_dir / "file1.txt").write_text("content_a1")
        (partner_a_dir / "file2.txt").write_text("content_a2")

        # Partner B: Umbrella Directory
        partner_b_dir = self.temp_dir / "src" / "partners" / "partner_b"
        partner_b_sub = partner_b_dir / "subfolder"
        partner_b_sub.mkdir(parents=True)
        (partner_b_dir / "overwrite.toml").write_text('[overwrites]\n"subfolder/" = "dest/"\n')
        (partner_b_sub / "file1.txt").write_text("content_b1")
        (partner_b_sub / "file2.txt").write_text("content_b2")

        # Partner C: Snipe-overwrites file1 specifically
        partner_c_dir = self.temp_dir / "src" / "partners" / "partner_c"
        partner_c_dir.mkdir(parents=True)
        (partner_c_dir / "overwrite.toml").write_text('[overwrites]\n"file1.txt" = "dest/file1.txt"\n')
        (partner_c_dir / "file1.txt").write_text("content_c1")

        inject_partner_files(["partner_a", "partner_b", "partner_c"], repo_root=self.temp_dir)

        # Assertions
        assert mock_input.call_count == 2
        assert (self.temp_dir / "dest" / "file1.txt").read_text() == "content_c1"  # C won file1
        assert (self.temp_dir / "dest" / "file2.txt").read_text() == "content_b2"  # B kept file2

    @patch("builtins.input")
    def test_two_partners_independent_conflict_with_base_directory(self, mock_input: MagicMock) -> None:
        # 1. Partner A vs Partner B -> User chooses 2 (Partner B wins)
        # 2. Partner A vs Partner C -> User chooses 2 (Partner C wins)
        # 3. Partner B vs Partner C -> User chooses 2 (Partner C wins the final file)
        mock_input.side_effect = ["2", "2", "2"]

        # Partner A: Base folder
        partner_a_dir = self.temp_dir / "src" / "partners" / "partner_a"
        partner_a_sub = partner_a_dir / "subfolder"
        partner_a_sub.mkdir(parents=True)
        (partner_a_dir / "overwrite.toml").write_text('[overwrites]\n"subfolder/" = "dest/"\n')
        (partner_a_sub / "shared.txt").write_text("content_a")

        # Partner B: Modifies file inside dest/
        partner_b_dir = self.temp_dir / "src" / "partners" / "partner_b"
        partner_b_dir.mkdir(parents=True)
        (partner_b_dir / "overwrite.toml").write_text('[overwrites]\n"b.txt" = "dest/shared.txt"\n')
        (partner_b_dir / "b.txt").write_text("content_b")

        # Partner C: Also modifies file inside dest/
        partner_c_dir = self.temp_dir / "src" / "partners" / "partner_c"
        partner_c_dir.mkdir(parents=True)
        (partner_c_dir / "overwrite.toml").write_text('[overwrites]\n"c.txt" = "dest/shared.txt"\n')
        (partner_c_dir / "c.txt").write_text("content_c")

        inject_partner_files(["partner_a", "partner_b", "partner_c"], repo_root=self.temp_dir)

        # Assertions
        assert mock_input.call_count == 3
        assert (self.temp_dir / "dest" / "shared.txt").read_text() == "content_c"

    @patch("subprocess.check_call")
    def test_install_multiple_partner_dependencies(self, mock_check_call: MagicMock) -> None:
        partner_names = ["test_partner_1", "test_partner_2"]
        for partner_name in partner_names:
            partner_dir = self.temp_dir / "src" / "partners" / partner_name
            submodule_dir = partner_dir / "src" / "third-parties" / "submod1"
            submodule_dir.mkdir(parents=True)
            (partner_dir / "pyproject.toml").touch()
            (submodule_dir / "pyproject.toml").touch()

        install_partner_dependencies(partner_names, repo_root=self.temp_dir)

        assert mock_check_call.call_count == 4  # 1 for each project dependencies, 1 for each submodule dependencies
        args = mock_check_call.call_args_list
        args_call_1 = " ".join(args[0].args[0])
        args_call_2 = " ".join(args[1].args[0])
        args_call_3 = " ".join(args[2].args[0])
        args_call_4 = " ".join(args[3].args[0])
        partner_1_dir = self.temp_dir / "src" / "partners" / "test_partner_1"
        partner_1_submodule_dir = partner_1_dir / "src" / "third-parties" / "submod1"
        partner_2_dir = self.temp_dir / "src" / "partners" / "test_partner_2"
        partner_2_submodule_dir = partner_2_dir / "src" / "third-parties" / "submod1"

        assert f"pip install {str(partner_1_dir)}" in args_call_1, f"Actual call args: {args_call_1}"
        assert f"pip install {str(partner_1_submodule_dir)}" in args_call_2, f"Actual call args: {args_call_2}"
        assert f"pip install {str(partner_2_dir)}" in args_call_3, f"Actual call args: {args_call_3}"
        assert f"pip install {str(partner_2_submodule_dir)}" in args_call_4, f"Actual call args: {args_call_4}"
