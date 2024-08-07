from datetime import datetime
from typing import Union, List
from pathlib import Path

import logging
import re
import shutil


class CacheFiles:
    """Class responsible to handle files designed to be stored for a certain specific time only."""

    def __init__(self, name: str, expiration_days: int, root_directory_path: Union[Path, str]) -> None:
        root_directory_path = self._get_path(root_directory_path)

        self.__name = name
        self.__expiration_days = expiration_days
        self.__cache_dir = root_directory_path / name

        self._setup()

    @property
    def name(self) -> str:
        """Retrieve related cache's tag

        Returns:
            str: the related cache's tag.
        """
        return self.__name

    @property
    def expiration_days(self) -> int:
        """Retrieve defined expiration days for cached files.

        Returns:
            int: the maximum days until remotion since last modified stat from the cached file;
        """
        return self.__expiration_days

    @expiration_days.setter
    def expiration_days(self, days: int) -> None:
        """Update the expiration days parameter. After new definition, the cached files will be verified.

        Args:
            int: the maximum days until remotion since last modified stat from the cached file;
        """
        if self.__expiration_days == days:
            return

        self.__expiration_days = days
        self._check_cached_files()

    @property
    def directory(self) -> Path:
        """Retrieve cache directory

        Returns:
            Path: the Path object related to the cache directory.
        """
        return self.__cache_dir

    def _setup(self) -> None:
        """Handle class setup. Certifies cache directory is created and check existent files with the defined rules."""

        self.__cache_dir.mkdir(parents=True, exist_ok=True)
        # if not self.__cache_dir.exists():
        #     self.__cache_dir.mkdir(parents=True)
        self._check_cached_files()

    def _get_cached_files(self, pattern: str = "*") -> List[Path]:
        """Retrieve the cached files list.

        Args:
            pattern (str, optional): The file name pattern to search for. Defaults to "*".

        Returns:
            List[Path]: The list of Path objects related to the cached files.
        """
        return self.__cache_dir.glob(pattern)

    def _check_cached_files(self) -> None:
        """Check cached files expiration.
        If the last modified time pass the defined expiration days, the file will be erased."""

        now_dt = datetime.now()
        for file in self._get_cached_files():
            file_stat = file.stat()
            file_last_modified_dt = datetime.fromtimestamp(file_stat.st_mtime)
            diff_dt = now_dt - file_last_modified_dt
            if diff_dt.days <= self.__expiration_days:
                continue

            logging.info(f"Cached file {file.as_posix()} expired! Deleting it...")
            file.unlink()

    def is_file_cached(self, file_path: Union[Path, str], check_extension=True) -> List[Path]:
        """Retrieve if the input file path is cached.

        Args:
            file_path (Union[Path, str]): the valid file path input.

        Returns:
            List[Path]: Returns a list of Path object for related file names found in cache file directory.
                                     If the file is not cached, returns None.
        """
        file_path = self._get_path(file_path)
        cached_files_name = [file.name for file in self._get_cached_files()]
        if check_extension:
            pattern = rf"^{file_path.name}$"
        else:
            pattern = rf"^{file_path.stem}(\.|$)"

        filtered_cached_files = list(filter(re.compile(pattern).match, cached_files_name))
        filtered_cached_files_path = [self.__cache_dir / file_name for file_name in filtered_cached_files]
        return filtered_cached_files_path

    def _get_path(self, file_path: Union[Path, str]) -> Path:
        """Wrapper to retrieve related Path object from any valid file path input.

        Args:
            file_path (Union[Path, str]): Valid inputs for file path.

        Returns:
            Path: the related Path object.
        """
        if not isinstance(file_path, Path):
            file_path = Path(file_path)

        return file_path

    def add_file(self, file_path: Union[Path, str]) -> bool:
        """Add file to cache.

        Args:
            file_path (Union[Path, str]): The valid file path input.

        Returns:
            bool: True if files was added to cache directory, otherwise returns False.
        """
        file_path = self._get_path(file_path)

        if self.is_file_cached(file_path):

            logging.info(f"File {file_path.as_posix()} is already cached!")
            print(f"File {file_path.as_posix()} is already cached!")
            return False

        result = ""
        try:
            result = shutil.move(file_path, self.__cache_dir / file_path.name)
        except Exception as error:
            logging.info(f"Failed to add file to cache directory: {error}")
            print(f"Failed to add file to cache directory: {error}")
            return False

        return Path(result) == (self.__cache_dir / file_path.name)

    def remove_file(self, file_path: Union[Path, str]) -> bool:
        """Remove file from cache.

        Args:
            file_path (Union[Path, str]): the file path valid input.

        Returns:
            bool: True if files was cached and removed, otherwise returns False.
        """
        file_path = self._get_path(file_path)
        if not self.is_file_cached(file_path):
            return False

        file_path.unlink()
        return True
