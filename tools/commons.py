from typing import Union
from pathlib import Path
import os
import sys
import re

MAX_LOOP_ITERATIONS = 100000


def filter_path_string(path_string: str) -> str:
    return re.sub(r'[^a-zA-Z0-9.\/\\\:-_#@!%*()="\+\- ]', "", path_string)


def sanitize_file_path(path: Union[Path, str]) -> Path:
    """Sanitize file path to avoid invalid characters and path traversal vulnerabilities.
       Same method from ltrace.helpers module. This method was duplicated here to avoid ltrace library dependence.
       Please maintain both updated.

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
