from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Union, List
from unittest.mock import MagicMock, patch
import shutil
import tempfile
import pytest

from commons.slicer.cache.cache_files import CacheFiles


@dataclass
class FakeFileStat:
    """Fake Path.stat() dataclass for test purposes."""

    st_mtime: int


TEMP_DIR = Path(tempfile.TemporaryDirectory().name)


class TestCacheFiles:
    """Test suite for CacheFiles class"""

    def setup_method(self):
        pass

    def teardown_method(self):
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)

    @patch("commons.slicer.cache.cache_files.CacheFiles._check_cached_files")
    def test_properties(self, check_cached_files_mock: MagicMock) -> None:
        """Test every property attribute from CacheFiles.

        Args:
            check_cached_files_mock (MagicMock): the CacheFiles._check_cached_files method mock.
        """
        cache_files = CacheFiles(name="Test", expiration_days=5, root_directory_path=TEMP_DIR)
        assert check_cached_files_mock.call_count == 1  # called on setup

        assert cache_files.name == "Test"
        assert cache_files.expiration_days == 5
        assert cache_files.directory == TEMP_DIR / cache_files.name

        with pytest.raises(AttributeError):
            cache_files.name = "new_name"

        with pytest.raises(AttributeError):
            cache_files.directory = "new_name"

        cache_files.expiration_days = 3
        assert check_cached_files_mock.call_count == 2  # called on expiration_days setter

    @pytest.mark.parametrize(
        "file_1_last_modified_day, file_1_should_be_deleted, file_2_last_modified_day, file_2_should_be_deleted",
        [
            pytest.param(7, True, 7, True, id="no_valid_files"),
            pytest.param(1, False, 7, True, id="one_file_still_valid"),
            pytest.param(3, False, 4, False, id="all_files_still_valid"),
        ],
    )
    @patch("commons.slicer.cache.cache_files.CacheFiles._get_cached_files")
    def test_check_cached_files_on_constructor_parametrized(
        self,
        get_cached_files_mock: MagicMock,
        file_1_last_modified_day: int,
        file_1_should_be_deleted: bool,
        file_2_last_modified_day: int,
        file_2_should_be_deleted: bool,
    ) -> None:
        """Test _check_cached_files method called during CacheFiles constructor.

        Args:
            get_cached_files_mock (MagicMock): the CacheFiles._get_cached_files method mock.
            file_1_last_modified_day (int): The day(s) number since mocked file 'file_1' was last modified.
            file_1_should_be_deleted (bool): The expectation from file_1 removal method.
            file_2_last_modified_day (int): The day(s) number since mocked file 'file_2' was last modified.
            file_2_should_be_deleted (bool): The expectation from file_1 removal method.
        """
        # Create mock for cached files
        file1 = MagicMock()
        file2 = MagicMock()

        type(file1.stat).return_value = FakeFileStat(
            st_mtime=(datetime.now() - timedelta(days=file_1_last_modified_day)).timestamp()
        )
        type(file2.stat).return_value = FakeFileStat(
            st_mtime=(datetime.now() - timedelta(days=file_2_last_modified_day)).timestamp()
        )

        get_cached_files_mock.return_value = [file1, file2]

        # Create CacheFile that check cached files on setup at the constructor
        CacheFiles(name="Test", expiration_days=5, root_directory_path=TEMP_DIR)

        # Assert attempts to delete the cached files
        assert (file1.unlink.call_count > 0) is file_1_should_be_deleted
        assert (file2.unlink.call_count > 0) is file_2_should_be_deleted

    @pytest.mark.parametrize(
        "target_file, cached_file_list, check_extension, expected_return",
        [
            pytest.param(
                Path("test_file"),
                [Path("test_file2"), Path("test_file"), Path("test_file3")],
                True,
                [TEMP_DIR / "Test" / "test_file"],
                id="file_is_cached",
            ),
            pytest.param(
                Path("test_file"),
                [Path("test_file2"), Path("test_file"), Path("test_file3")],
                False,
                [TEMP_DIR / "Test" / "test_file"],
                id="file_is_cached_dont_check_extension",
            ),
            pytest.param(
                "",
                [TEMP_DIR / "Test" / "test_file2", TEMP_DIR / "Test" / "test_file", TEMP_DIR / "Test" / "test_file3"],
                True,
                [],
                id="empty_input",
            ),
            pytest.param(
                "",
                [TEMP_DIR / "Test" / "test_file2", TEMP_DIR / "Test" / "test_file", TEMP_DIR / "Test" / "test_file3"],
                False,
                [],
                id="empty_input_dont_check_extension",
            ),
            pytest.param(
                " ",
                [TEMP_DIR / "Test" / "test_file2", TEMP_DIR / "Test" / "test_file"],
                True,
                [],
                id="whitespace_input",
            ),
            pytest.param(
                " ",
                [TEMP_DIR / "Test" / "test_file2", TEMP_DIR / "Test" / "test_file"],
                False,
                [],
                id="whitespace_input_dont_check_extension",
            ),
            pytest.param("test_file", [], True, [], id="empty_cache_directory"),
            pytest.param("test_file", [], False, [], id="empty_cache_directory_dont_check_extension"),
            pytest.param(
                "test", [TEMP_DIR / "Test" / "teste", TEMP_DIR / "Test" / "test_file"], True, [], id="false_positive"
            ),
            pytest.param(
                "test",
                [TEMP_DIR / "Test" / "teste", TEMP_DIR / "Test" / "test_file"],
                False,
                [],
                id="false_positive_dont_check_extension",
            ),
            pytest.param(
                "test.htm",
                [TEMP_DIR / "Test" / "test.html", TEMP_DIR / "Test" / "test_file"],
                True,
                [],
                id="false_positive_2",
            ),
            pytest.param(
                "test.htm",
                [TEMP_DIR / "Test" / "test.html", TEMP_DIR / "Test" / "test_file"],
                False,
                [TEMP_DIR / "Test" / "test.html"],
                id="false_positive_2_dont_check_extension",
            ),
            pytest.param(
                Path.home() / "test_file",
                [TEMP_DIR / "Test" / "test_file", TEMP_DIR / "Test" / "test_file_2"],
                True,
                [TEMP_DIR / "Test" / "test_file"],
                id="different_path_from_target_same_name",
            ),
            pytest.param(
                Path.home() / "test_file",
                [TEMP_DIR / "Test" / "test_file", TEMP_DIR / "Test" / "test_file_2"],
                False,
                [TEMP_DIR / "Test" / "test_file"],
                id="different_path_from_target_same_name_dont_check_extension",
            ),
            pytest.param(
                "test",
                [TEMP_DIR / "Test" / "test.html", TEMP_DIR / "Test" / "test.htm"],
                False,
                [TEMP_DIR / "Test" / "test.html", TEMP_DIR / "Test" / "test.htm"],
                id="false_positive_3_dont_check_extension",
            ),
        ],
    )
    @patch("commons.slicer.cache.cache_files.CacheFiles._get_cached_files")
    def test_is_file_cached(
        self,
        get_cached_files_mock: MagicMock,
        target_file: Union[Path, str],
        cached_file_list: List[Path],
        check_extension: bool,
        expected_return: Union[List[Path], None],
    ) -> None:
        """Test case for is_file_cached method.

        Args:
            get_cached_files_mock (MagicMock): the CacheFiles._get_cached_files method mock.
            target_file (Path/str): the file to be checked in cached files.
            cached_file_list (List[Path]): the cached file list retrieved from mock.
            is_cached (bool): the expectation from target file being in the cached file list.
        """
        get_cached_files_mock.side_effect = [[], cached_file_list]  # Avoid call from setup method to do anything

        cache_files = CacheFiles(name="Test", expiration_days=5, root_directory_path=TEMP_DIR)
        print(f"test expected_return {expected_return}")
        assert cache_files.is_file_cached(file_path=target_file, check_extension=check_extension) == expected_return

    @pytest.mark.parametrize(
        "input_file_path, expected_file_path_output",
        [
            pytest.param(Path("test_file"), Path("test_file"), id="from_Path_object_input"),
            pytest.param("test_file", Path("test_file"), id="from_str_simple_input"),
            pytest.param(
                "C:\\User\\my_name\\GeoSlicer\\LTrace\\cache\\test\\file",
                Path("C:\\User\\my_name\\GeoSlicer\\LTrace\\cache\\test\\file"),
                id="from_str_windows_input",
            ),
            pytest.param(
                "/home/my_name/GeoSlicer/LTrace/cache/test/file",
                Path("/home/my_name/GeoSlicer/LTrace/cache/test/file"),
                id="from_str_linux_input",
            ),
        ],
    )
    def test_get_path(self, input_file_path: Union[Path, str], expected_file_path_output: Path) -> None:
        """Test case for _get_path method.

        Args:
            get_cached_files_mock (MagicMock): the CacheFiles._get_cached_files method mock.
            input_file_path (Path/str): the input for _get_path method.
            expected_file_path_output (Path): the expected path retrieved from _get_path method.
        """
        cache_files = CacheFiles(name="Test", expiration_days=5, root_directory_path=TEMP_DIR)
        assert cache_files._get_path(input_file_path) == expected_file_path_output

    @pytest.mark.parametrize(
        "input_file_path, cached_file_path_list, expected_result",
        [
            pytest.param(
                TEMP_DIR / "file2",
                [TEMP_DIR / "file1", TEMP_DIR / "file3"],
                True,
                id="new_file_is_moved_from_Path_input",
            ),
            pytest.param(
                (TEMP_DIR / "file2").as_posix(),
                [TEMP_DIR / "file1", TEMP_DIR / "file3"],
                True,
                id="new_file_is_moved_from_str_as_posix_input",
            ),
            pytest.param(
                str(TEMP_DIR / "file2"),
                [TEMP_DIR / "file1", TEMP_DIR / "file3"],
                True,
                id="new_file_is_moved_from_platform_based_input",
            ),
            pytest.param(
                TEMP_DIR / "file2",
                [TEMP_DIR / "file1", TEMP_DIR / "file2"],
                False,
                id="already_cached_file_nothing_happens",
            ),
        ],
    )
    @patch("commons.slicer.cache.cache_files.shutil.move")
    @patch("commons.slicer.cache.cache_files.CacheFiles._get_cached_files")
    def test_add_file(
        self,
        get_cached_files_mock: MagicMock,
        shutil_move_mock: MagicMock,
        input_file_path: Union[Path, str],
        cached_file_path_list: List[Path],
        expected_result: bool,
    ) -> None:
        """Test case for _get_path method.

        Args:
            shutil_move_mock (MagicMock): the shutil.move method mock.
            get_cached_files_mock (MagicMock): the CacheFiles._get_cached_files method mock.
            input_file_path (Path/str): the file to be added in cached files.
            cached_file_path_list (List[Path]): the cached file list retrieved from mock.
        """
        # Define mocks behaviours
        get_cached_files_mock.side_effect = [[], cached_file_path_list]  # Avoid call from setup method to do anything
        shutil_move_mock.return_value = TEMP_DIR / "Test" / Path(input_file_path).name

        # Test
        cache_files = CacheFiles(name="Test", expiration_days=5, root_directory_path=TEMP_DIR)
        assert cache_files.add_file(input_file_path) is expected_result
        assert (shutil_move_mock.call_count == 1) is expected_result

    @pytest.mark.parametrize(
        "input_file_path, cached_file_path_list, expected_result",
        [
            pytest.param(
                TEMP_DIR / "file2",
                [TEMP_DIR / "file1", TEMP_DIR / "file3"],
                False,
                id="nothing_happens_file_not_cached",
            ),
            pytest.param(
                (TEMP_DIR / "file2").as_posix(),
                [TEMP_DIR / "file1", TEMP_DIR / "file2"],
                True,
                id="remove_cached_file_input_as_posix",
            ),
            pytest.param(
                TEMP_DIR / "file2",
                [TEMP_DIR / "file1", TEMP_DIR / "file2"],
                True,
                id="remove_cached_file_input_as_path",
            ),
        ],
    )
    @patch("commons.slicer.cache.cache_files.CacheFiles._get_cached_files")
    def test_remove_file(
        self,
        get_cached_files_mock: MagicMock,
        input_file_path: Union[Path, str],
        cached_file_path_list: List[Path],
        expected_result: bool,
    ) -> None:
        """Test case for _get_path method.

        Args:
            get_cached_files_mock (MagicMock): the CacheFiles._get_cached_files method mock.
            input_file_path (Path/str): the file to be added in cached files.
            cached_file_path_list (List[Path]): the cached file list retrieved from mock.
        """
        # Define mocks behaviours
        get_cached_files_mock.side_effect = [[], cached_file_path_list]  # Avoid call from setup method to do anything

        # Test
        cache_files = CacheFiles(name="Test", expiration_days=5, root_directory_path=TEMP_DIR)

        if expected_result:
            with pytest.raises(FileNotFoundError):
                cache_files.remove_file(input_file_path)
        else:
            assert cache_files.remove_file(input_file_path) is False

    @patch("commons.slicer.cache.cache_files.CacheFiles._check_cached_files")
    def test_mkdir_on_setup(self, check_cached_files_mock: MagicMock) -> None:
        """Test the behavior of creating cache directory right after CacheFiles class initialization.

        Args:
            check_cached_files_mock (MagicMock): the CacheFiles._check_cached_files method mock.
        """
        assert TEMP_DIR.exists() is False
        cache_files = CacheFiles(name="Test", expiration_days=5, root_directory_path=TEMP_DIR)
        assert TEMP_DIR.exists() is True
        assert cache_files.directory.exists()
        assert check_cached_files_mock.call_count == 1
