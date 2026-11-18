"""ObjectTransfer classes efficiently write objects to the filesystem avoiding some persistent file-copying issues.

The Transfers first write the files representing an object to a local temporary directory. For large files, the data is
written using functions implemented in C. The resulting files are then moved to the shared directory, using robocopy
on Windows and shutil on Linux.

This approach addresses two problems:
- When writing large files from a Python threading.Thread, the GIL periodically deschedule the writing thread to allow
  other threads to run. For large files, this can cause the write operation to be repeatedly interrupted, resulting in
  significant scheduling and context-switching overhead. Writing the data through C functions avoids this behavior.
- Writing or moving files directly to a shared directory (particularly from Windows to Linux) using Python can
  occasionally freeze due to the protocol used to communicate between the filesystems. Using robocopy avoids that.
"""

import json
import pickle
import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np


class ObjectTransfer(ABC):
    def __init__(self, directory: str, filename: str, no_temp: bool = False):
        """Base for the object transfer classes
        Write object to a temp dir, then moves it to destination.

        Args:
            directory (str): Destination directory
            filename (str): Name of the final file(s)
            no_temp (bool): If True, skip the temp dir and write directly to destination
        """
        self.directory = directory
        self.filename = filename
        self.no_temp = no_temp
        self.temp_dir = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__remove_temp_dir()
        return False

    def save(self, obj):
        if self.no_temp:
            self._save(obj, self.directory)
        else:
            temp_dir = self.__create_temp_dir()
            dumped_files = self._save(obj, temp_dir)
            for file in dumped_files:
                self._move(temp_dir, self.directory, file)
            self.__remove_temp_dir()

    def load(self):
        return self._load()

    def exists(self) -> bool:
        return (Path(self.directory) / self.filename).exists()

    def __create_temp_dir(self) -> str:
        temp_dir = Path(tempfile.mkdtemp())
        self.temp_dir = str(temp_dir)
        return self.temp_dir

    def __remove_temp_dir(self):
        if self.temp_dir is not None:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.temp_dir = None

    @abstractmethod
    def _save(self, obj, directory: str) -> list:
        pass

    @abstractmethod
    def _load(self):
        pass

    @staticmethod
    def _move(origin_dir: str, destination_dir: str, filename: str):
        if sys.platform.startswith("linux"):
            shutil.move(str(Path(origin_dir) / filename), destination_dir)
        else:
            move_result = subprocess.run(
                ["robocopy", origin_dir, destination_dir, filename, "/MOVE"], shell=True, check=False
            )
            if move_result.returncode > 1:
                raise subprocess.CalledProcessError(move_result.returncode, move_result.args)


class VolumeNodeObjectTransfer(ObjectTransfer):
    def __init__(self, directory: str, filename: str, no_temp: bool = False):
        """Save VolumeNode as .npy and .json files to a temp dir, then move them to the destination.

        Args:
            directory (str): Destination directory
            filename (str): Name for the object files, without extension
            no_temp (bool): If True, skip the temp dir and write directly to destination
        """
        super().__init__(directory, filename, no_temp)

    def _save(self, obj, directory: str) -> list:
        import slicer

        dumped_files = []

        volume_array = slicer.util.arrayFromVolume(obj)
        np.save(str(Path(directory) / self.filename), volume_array)
        dumped_files.append(self._get_numpy_file_name())

        header_dict = {"spacing": obj.GetSpacing()}
        json_filename = self._get_json_file_name()
        with open(str(Path(directory) / json_filename), "w") as f:
            json.dump(header_dict, f)
        dumped_files.append(json_filename)

        return dumped_files

    def exists(self):
        return (Path(self.directory) / self._get_numpy_file_name()).exists() and (
            Path(self.directory) / self._get_json_file_name()
        ).exists()

    def _load(self):
        volume_array = np.load(str(Path(self.directory) / self._get_numpy_file_name()))
        with open(str(Path(self.directory) / self._get_json_file_name()), "r") as f:
            header_dict = json.load(f)
        return volume_array, header_dict

    def _get_numpy_file_name(self):
        return f"{self.filename}.npy"

    def _get_json_file_name(self):
        return f"{self.filename}.json"


class NumpyArrayObjectTransfer(ObjectTransfer):
    def __init__(self, directory: str, filename: str, no_temp: bool = False):
        super().__init__(directory, filename, no_temp)

    def _save(self, obj, directory: str) -> list:
        npy_filename = self._get_numpy_file_name()
        np.save(str(Path(directory) / npy_filename), obj)
        return [npy_filename]

    def exists(self) -> bool:
        return (Path(self.directory) / self._get_numpy_file_name()).exists()

    def _load(self):
        return np.load(str(Path(self.directory) / self._get_numpy_file_name()))

    def _get_numpy_file_name(self) -> str:
        return self.filename if self.filename.endswith(".npy") else f"{self.filename}.npy"


class JsonObjectTransfer(ObjectTransfer):
    def __init__(self, directory: str, filename: str, no_temp: bool = False):
        super().__init__(directory, filename, no_temp)

    def _save(self, obj, directory: str) -> list:
        with open(str(Path(directory) / self.filename), "w") as f:
            json.dump(obj, f)
        return [self.filename]

    def _load(self):
        with open(str(Path(self.directory) / self.filename), "r") as f:
            json_content = json.load(f)
        return json_content


class PickleObjectTransfer(ObjectTransfer):
    def __init__(self, directory: str, filename: str, no_temp: bool = False):
        super().__init__(directory, filename, no_temp)

    def _save(self, obj, directory: str) -> list:
        # Writing must be done by numpy instead of pickle because numpy uses compiled C
        # and this avoids GIL interruptions
        data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
        pickle_array = np.frombuffer(data, dtype=np.uint8)
        pickle_array.tofile(str(Path(directory) / self.filename))
        return [self.filename]

    def _load(self):
        pickle_array = np.fromfile(str(Path(self.directory) / self.filename), dtype=np.uint8)
        pickle_data = pickle.loads(pickle_array.tobytes())
        return pickle_data
