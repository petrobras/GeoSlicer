import os
import sys
import re

from functools import wraps
from ltrace.constants import MAX_LOOP_ITERATIONS
from pathlib import Path
from time import perf_counter
from typing import Union, Tuple, Optional


def timeit(function):
    """
    Decorator to print execution interval of callables in seconds.

    Example 1:
        >>> @timeit
        >>> def function_to_be_optimized(*args, **kwargs):
        >>>     return 'fuction result'
        >>> function_to_be_optimized()
        function_to_be_optimized took 4.31e-09 s
        'fuction result'

    Example 2:
        >>> from time import sleep
        >>> timeit(sleep)(3)
        sleep took 2.999 s
    """

    @wraps(function)
    def wrapper(*args, **kwargs):
        start = perf_counter()
        result = function(*args, **kwargs)
        end = perf_counter()
        interval = end - start
        print(f"{function.__name__} took {interval:0.4g} s")
        return result

    return wrapper


def addAttributes(**attributes):
    """
    Decorator to add attributes to callables (i.e., functions, methods or
    classes)

    Example:
        @addAttributes(context='maths', origin='geometry')
        def pi():
            return 3.14
        print(pi())  # -> 3.14
        print(pi.context)  # -> 'maths'
        print(pi.origin)  # -> 'geometry'
    """

    def _addAttributes(function):
        for key, val in attributes.items():
            setattr(function, key, val)
        return function

    return _addAttributes


def filter_module_name(module_name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9\.\:\_\- ]", "", module_name)


def filter_path_string(path_string: str) -> str:
    return re.sub(r'[^a-zA-Z0-9.\/\\\:-_#@!%*()="\+\- ]', "", path_string)


def sanitize_file_path(path: Union[Path, str]) -> Path:
    """Sanitize file path to avoid invalid characters and path traversal vulnerabilities.

    Args:
        path (Union[Path, str]): The path to be sanitized.

    Returns:
        Path: The sanitized path as a Path object

    Raise:
        ValueError: If the selected path is located in a forbidden base path.
    """
    if isinstance(path, str):
        path = Path(filter_path_string(path))

    if path is None or not path:
        raise ValueError("The path's input is empty. Please select a valid path.")

    path: Path = path.resolve()

    allowed_base_paths = []
    prohibited_base_paths = []
    if sys.platform == "win32":
        env_vars = dict(os.environ.items())
        systemDrive = env_vars.get("SYSTEMDRIVE", path.drive)
        windowsFolder = env_vars.get("SYSTEMROOT", (Path(systemDrive) / "Windows").as_posix())
        appDataFolder = env_vars.get("APPDATA", (Path(systemDrive) / "Users").as_posix())
        programDataFolder = env_vars.get("PROGRAMDATA", (Path(systemDrive) / "ProgramData").as_posix())
        programFilesFolder = env_vars.get("PROGRAMFILES", (Path(systemDrive) / "ProgramFiles").as_posix())
        programFilesx86Folder = env_vars.get("PROGRAMFILES(x86)", (Path(systemDrive) / "ProgramFiles(x86)").as_posix())
        allowed_base_paths = []  # everywhere allowed, except for the prohibited folders
        prohibited_base_paths = [
            appDataFolder,
            programDataFolder,
            windowsFolder,
            programDataFolder,
            programFilesFolder,
            programFilesx86Folder,
            # Adding hardcoded variations to avoid problems with internationalization
            "C:/ProgramData",
            "C:/Program Files",
            "C:/Program Files (x86)",
        ]

    else:
        allowed_base_paths = []  # everywhere allowed, except for the prohibited folders
        prohibited_base_paths = [
            "/bin",
            "/boot",
            "/cdrom",
            "/dev",
            "/etc",
            "/lib",
            "/lib32",
            "/lib64",
            "/libx32",
            "/lost+found",
            "/media",
            "/opt",
            "/proc",
            "/run",
            "/sbin",
            "/snap",
            "/srv",
            "/swapfile",
            "/sys",
            "/usr",
            "/var",
        ]
    allowed_base_paths = [filter_path_string(path) for path in allowed_base_paths]
    prohibited_base_paths = [filter_path_string(path) for path in prohibited_base_paths]

    allowed = len(allowed_base_paths) == 0
    if not allowed:
        for base_path in allowed_base_paths[:MAX_LOOP_ITERATIONS]:
            if path.is_relative_to(base_path):
                allowed = True
                break

    if allowed:
        for base_path in prohibited_base_paths[:MAX_LOOP_ITERATIONS]:
            if path.is_relative_to(base_path):
                allowed = False
                break

    if not allowed:
        raise ValueError(f"The base path for '{path.as_posix()}' is prohibited. Please select another location.")

    return path
