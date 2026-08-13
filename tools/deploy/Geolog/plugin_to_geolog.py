from enum import Enum
from pathlib import Path
from typing import Union

import argparse
import ctypes
import logging
import os
import re
import stat
import sys
import shutil
import traceback


class ReturnValues(Enum):
    SUCCESS = 0
    PYWIN32_NOT_INSTALLED = 1
    GEOLOG_NOT_FOUND = 2
    PROCESSING_MMU_NOT_FOUND = 3
    PROCESSING_MENU_NOT_FOUND_IN_MMU = 4
    ERROR_PARSING_PROCESSING_MENU = 5
    NO_PERMISSION_PROCESSING_MMU = 6
    NO_PERMISSION_MENUS_PATH = 7
    NO_PERMISSION_RESOURCES_PATH = 8
    LTRACE_ICON_NOT_FOUND = 9


logger = logging.getLogger()
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    logger.addHandler(logging.StreamHandler(sys.stdout))


if sys.platform == "win32":
    try:
        import win32security
        import win32api
        import win32con
    except ModuleNotFoundError:
        logger.exception("ERROR. Please install Python package pywin32 and run again.")
        sys.exit(ReturnValues.PYWIN32_NOT_INSTALLED)


# Windows-only - running elevated not sufficient
def enable_privilege(privilege_str):
    hToken = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY
    )
    privilege_id = win32security.LookupPrivilegeValue(None, privilege_str)
    win32security.AdjustTokenPrivileges(hToken, False, [(privilege_id, win32con.SE_PRIVILEGE_ENABLED)])


def is_elevated():
    if sys.platform == "win32":
        return ctypes.windll.shell32.IsUserAnAdmin()
    else:
        return os.geteuid() == 0


def relaunch_elevated():
    if sys.platform == "win32":
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
    else:
        args = ["sudo", sys.executable] + sys.argv
        os.execvp("sudo", args)


def add_write_permission(path):
    if sys.platform == "win32":
        # Remove read-only if needed
        FILE_ATTRIBUTE_READONLY = 0x01
        attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
        if attrs & FILE_ATTRIBUTE_READONLY:
            ctypes.windll.kernel32.SetFileAttributesW(path, attrs & ~FILE_ATTRIBUTE_READONLY)
        # os.chmod(path, stat.S_IWRITE)
    else:
        os.chmod(path, stat.S_IWUSR | stat.S_IRUSR)


def restore_permissions(geolog_menus_path: str, menu_file_path: str, geolog_resources_path: str, permissions: dict):
    logger.debug(f"Restoring changed permissions to files and folders...")
    os.chmod(geolog_menus_path, permissions["geolog_menus_path"])
    os.chmod(menu_file_path, permissions["menu_file_path"])
    os.chmod(geolog_resources_path, permissions["geolog_resources_path"])


def get_geolog_menus_path(args: argparse.Namespace) -> Path:
    # Locating Geolog
    if args.geolog_path is not None:
        geolog_menus_path = Path(args.geolog_path) / "app-defaults"
        return geolog_menus_path

    if sys.platform == "win32":
        geolog_menus_path = Path(locate_geolog() + "/app-defaults")
        return geolog_menus_path

    geolog_menus_path = shutil.which("geolog")
    if geolog_menus_path is not None:
        geolog_menus_path = Path(geolog_menus_path).parent.resolve() / "app-defaults"
        logger.info(f"geolog-path argument absent. Assuming it is installed in {geolog_menus_path.parent.resolve()}")

    return geolog_menus_path


def write_new_menu_file(menu_file_path, geolog_menus_path, geolog_resources_path, permissions, working_dir):
    lines = []
    with open(menu_file_path, "r") as f:
        lines = f.readlines()

    # Writing to a copy of processing.mmu and replacing it (plus a backup)
    if any("ltrace_menu" in line for line in lines):
        logger.warning("ltrace_menu already present.")
    else:
        # 1. Locate "Menu processing_menu"
        menu_start = None
        for i, line in enumerate(lines):
            if "Menu processing_menu" in line:
                menu_start = i
                break

        if menu_start is None:
            logger.error("FAILED. Menu processing_menu not found.")
            restore_permissions(geolog_menus_path, menu_file_path, geolog_resources_path, permissions)
            return ReturnValues.PROCESSING_MENU_NOT_FOUND_IN_MMU
        else:
            # 2. Find #endifs and closing brace
            endif_indices = []
            brace_index = -1
            brace_level = 0

            for i in range(menu_start, len(lines)):
                if "{" in lines[i]:
                    brace_level += lines[i].count("{")
                if "}" in lines[i]:
                    brace_level -= lines[i].count("}")
                    if brace_level == 0:
                        brace_index = i
                        break
                if "#endif" in lines[i]:
                    endif_indices.append(i)

            if brace_index == -1:
                logger.error("FAILED. Malformed processing.mmu file. Check 'Menu processing_menu' field.")
                return ReturnValues.ERROR_PARSING_PROCESSING_MENU

            # 2.a.: Insert above #endifs
            line_geoslicer = '"LTrace (GeoSlicer)" +  f.menu ltrace_menu'
            if endif_indices:
                for idx in reversed(endif_indices):
                    lines.insert(idx, f"  {line_geoslicer}\n")
            # or insert above closing brace
            else:
                lines.insert(brace_index, f"  {line_geoslicer}\n")

            # 3. Find regions of #includes after the closing brace above. There should be 2 (MUI_WELL and MUI_PROJECT)...
            next_includes = []
            for i in range(brace_index, len(lines)):
                if "#if defined ( MUI_WELL )" in lines[i]:
                    next_includes.append(i)
                elif "#if defined ( MUI_PROJECT )" in lines[i]:
                    next_includes.append(i)

            next_endifs = []
            for n in range(len(next_includes)):
                endifs_to_go = 1
                for i in range(next_includes[n] + 1, len(lines)):
                    if "#if" in lines[i]:
                        endifs_to_go += 1
                    elif "#endif" in lines[i]:
                        if endifs_to_go == 1:
                            next_endifs.append(i)
                            break
                        endifs_to_go -= 1

            line_geoslicer = "#include <ltrace.mmu>"
            for idx in reversed(next_endifs):
                lines.insert(idx, f"{line_geoslicer}\n")

            # Save the modified file
            modified_file_path = (working_dir / "processing_new.mmu").as_posix()
            with open(modified_file_path, "w") as f2:
                f2.writelines(lines)

            try:
                # Create a backup
                shutil.copyfile(menu_file_path, Path(str(menu_file_path) + ".bak").as_posix())
                # Replace the original
                os.remove(menu_file_path)
                shutil.move(modified_file_path, menu_file_path)
            except PermissionError:
                logger.error(f"ERROR deleting original {menu_file_path}.")
                restore_permissions(geolog_menus_path, menu_file_path, geolog_resources_path, permissions)
                return ReturnValues.NO_PERMISSION_PROCESSING_MMU
    logger.debug("SUCCESS. GeoSlicer added to Geolog Well and Project menus.")
    return ReturnValues.SUCCESS


def run(args):
    permissions = {}
    geolog_menus_path = None
    menu_file_path = None
    geolog_resources_path = None

    logger.info(f"{Path(__file__).name} - Installing GeoSlicer shortcut to Geolog Processing menu")

    if not is_elevated():
        logger.warning(f"Relaunching {Path(__file__).name} with elevated privileges...")
        relaunch_elevated()

    if sys.platform == "win32":
        enable_privilege(win32con.SE_TAKE_OWNERSHIP_NAME)
        enable_privilege(win32con.SE_RESTORE_NAME)

    THIS_FILE = Path(__file__).resolve().absolute()
    THIS_FOLDER = THIS_FILE.parent

    geolog_menus_path = get_geolog_menus_path(args)

    if geolog_menus_path is None or not geolog_menus_path.exists():
        logger.error(f"Geolog not found. GeoSlicer shortcut not added.")
        return ReturnValues.GEOLOG_NOT_FOUND

    # Set write permission of geolog_menus_path:
    permissions["geolog_menus_path"] = geolog_menus_path.stat().st_mode
    add_write_permission(geolog_menus_path.as_posix())

    # ltrace.mmu - create and move
    if sys.platform == "win32":
        geolog_menus_path = sanitize_ProgramFiles_path(geolog_menus_path)

    try:
        create_ltrace_mmu(geolog_menus_path.as_posix())

        # launch_geoslicer.bat (or .sh) - create and move
        create_exec_launch_script(Path(args.geoslicer_path).as_posix(), geolog_menus_path)
    except Exception as e:
        logger.error(f"Error {e}. {traceback.print_exc()}")
        return ReturnValues.NO_PERMISSION_MENUS_PATH

    # Set write permission of geolog_resources_path:
    if args.geolog_path:
        geolog_resources_path = Path(args.geolog_path) / "resources"
    else:
        geolog_resources_path = geolog_menus_path.joinpath("..").resolve() / "resources"
    permissions["geolog_resources_path"] = geolog_resources_path.stat().st_mode
    add_write_permission(geolog_resources_path.as_posix())

    # Copy ltrace.svg
    ltrace_icon_path = THIS_FOLDER / "menu_ltrace.svg"
    if not ltrace_icon_path.exists():
        logger.error(f"{ltrace_icon_path} not found. Aborting.")
        return ReturnValues.LTRACE_ICON_NOT_FOUND

    if not copy(ltrace_icon_path, geolog_resources_path):
        return ReturnValues.NO_PERMISSION_RESOURCES_PATH

    # Set write permission of processing.mmu
    menu_file_path = geolog_menus_path / "processing.mmu"

    if not menu_file_path.exists():
        logger.error(f"{menu_file_path} not found. Aborting.")
        return ReturnValues.PROCESSING_MMU_NOT_FOUND

    permissions["menu_file_path"] = os.stat(menu_file_path).st_mode
    add_write_permission(menu_file_path.as_posix())

    # Create a .bak of processing.mmu and replace the original with our edited one
    return_val = write_new_menu_file(
        menu_file_path, geolog_menus_path, geolog_resources_path, permissions, working_dir=THIS_FOLDER
    )

    restore_permissions(geolog_menus_path, menu_file_path, geolog_resources_path, permissions)

    return return_val


def locate_geolog(root_dirs=None):
    roots = [
        os.environ.get("ProgramFiles", r"C:/Program Files") + "/Paradigm",
        os.environ.get("ProgramFiles(x86)", r"C:/Program Files (x86)") + "/Paradigm",
    ]

    pattern = re.compile(rf"^({'|'.join(['geolog'])})[\d\.]+$", re.IGNORECASE)

    for root in roots:
        if not os.path.isdir(root):
            continue
        for entry in os.listdir(root):
            full_path = os.path.join(root, entry)
            if os.path.isdir(full_path) and pattern.match(entry):
                return full_path

    return None


#  Specific to Windows - We have to change "C:/Program Files" (or "Program Files (x86))"
# to "C:/Progra~N", where N is the alphabetical order of apparition of the Program Files folder
# (normally, 1). This is because:
# - *.mmu files don't accept spaces in paths passed to f.exec
# - Also, ambient variables like PG_GEOLOG_HOME can't be retrieved
def sanitize_ProgramFiles_path(full_path: Path) -> Path:
    progfiles_paths = [
        path
        for path in [os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)"), os.getenv("ProgramW6432")]
        if path is not None
    ]
    progfiles_paths = [Path(path).as_posix() for path in progfiles_paths]

    if not full_path.as_posix().startswith(tuple(progfiles_paths)):
        return full_path

    base_dir = Path("C:/")
    prefix = "Progra"

    # List all folders in C:/ that start with "Progra"
    candidate_folders = [f.name for f in base_dir.iterdir() if f.is_dir() and f.name.startswith(prefix)]

    candidate_folders.sort()

    # Find the index of the candidate_folders that matches
    index = 0
    for i, folder in enumerate(candidate_folders):
        if folder == full_path.parts[1]:
            index = i + 1
            break

    # Replace the match with "Progra~N"
    if index > 0:
        short_folder = f"{prefix}~{index}"
        short_path = Path(str(full_path).replace(str(base_dir / full_path.parts[1]), str(base_dir / short_folder)))
    else:
        short_path = full_path  # or do nothing in case of no match (full path is not in a flavor of C:/Program Files)

    return short_path


def create_ltrace_mmu(geolog_menus_path):
    destination_folder = Path(geolog_menus_path)
    if destination_folder.is_file():
        destination_folder = destination_folder.parent
    destination_folder.mkdir(parents=True, exist_ok=True)
    with open(destination_folder / "ltrace.mmu", "w") as f:
        f.write("Menu ltrace_menu\n")
        f.write("{\n")
        f.write("#if defined ( MUI_WELL )\n")
        if sys.platform == "win32":
            f.write(f'  "Launch GeoSlicer"      f.exec "{geolog_menus_path}/launch_geoslicer.bat"\n')
        else:
            f.write(f'  "Launch GeoSlicer"      f.exec "{geolog_menus_path}/launch_geoslicer.sh"\n')
        f.write("#endif\n")
        f.write("#if defined ( MUI_PROJECT )\n")
        if sys.platform == "win32":
            f.write(f'  "Launch GeoSlicer"      f.exec "{geolog_menus_path}/launch_geoslicer.bat"\n')
        else:
            f.write(f'  "Launch GeoSlicer"      f.exec "{geolog_menus_path}/launch_geoslicer.sh"\n')
        f.write("#endif\n")
        f.write("}\n")
        f.write("\n")
    f.close()


def create_exec_launch_script(geoslicer_path, dest_path):
    fname = None
    destination_folder = Path(dest_path)
    if destination_folder.is_file():
        destination_folder = destination_folder.parent
    destination_folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        fname = destination_folder / "launch_geoslicer.bat"
        with open(fname, "w") as f:
            f.write("@echo off\n")
            f.write("\n")
            f.write(f'start "" {geoslicer_path}/GeoSlicer\n')
        f.close()

    else:
        fname = destination_folder / "launch_geoslicer.sh"
        with open(fname, "w") as f:
            f.write("#!/bin/bash\n")
            f.write("\n")
            f.write(f"{geoslicer_path}/GeoSlicer\n")
        f.close()

    os.chmod(fname, 0o755)

    return fname.name


def copy(path_from: Union[Path, str], path_to: Union[Path, str]) -> bool:
    if isinstance(path_from, str):
        path_from = Path(path_from)

    if isinstance(path_to, str):
        path_to = Path(path_to)

    if not path_from.exists():
        logger.error(f"File '{path_from}' does not exist")
        return False

    destination_folder = path_to.parent if path_to.suffix else path_to
    destination_folder.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copy2(path_from, path_to)
    except OSError as e:
        logger.error(f"Error copying {path_from} to {path_to}.\n{traceback.print_exc()}")
        return False

    return True


def move(path_from: Union[Path, str], path_to: Union[Path, str]) -> bool:
    if isinstance(path_from, str):
        path_from = Path(path_from)

    if isinstance(path_to, str):
        path_to = Path(path_to)

    destination_folder = path_to.parent if path_to.suffix else path_to
    destination_folder.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(path_from, path_to)
    except OSError as e:
        logger.error(f"Error moving {path_from} to {path_to}. {e}\n{traceback.print_exc()}")
        return False
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Edits Paradigm Geolog menus to add shortcut to GeoSlicer.")
    parser.add_argument(
        "-l",
        "--geolog-path",
        help="The path where Geolog is installed.",
        default=None,
    )
    parser.add_argument(
        "-s",
        "--geoslicer-path",
        help="The path where Geoslicer is (or is being) installed.",
        default=None,
    )
    parser.add_argument(
        "-e",
        "--elevate",
        help="For unit testing, for example, we should avoid prompting the user.",
        default=True,
    )
    run(parser.parse_args())
