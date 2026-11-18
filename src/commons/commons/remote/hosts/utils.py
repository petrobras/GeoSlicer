import importlib
import fnmatch
import logging
import os
import sys
from pathlib import Path
from typing import Union, List, Dict

from commons.remote.hosts.base import Host

HOSTS_DIRS = [Path(__file__).parent]


def rglob(path: Path, pattern: str) -> List[Path]:
    file_list = []
    for root, dirs, files in os.walk(path, followlinks=True):
        for file in files:
            if fnmatch.fnmatch(file, pattern):
                file_path = Path(root) / file
                file_list.append(file_path)

    return file_list


def get_host_subclasses_from_module(module: object) -> List[Host]:
    classes = []
    for attribute in dir(module):
        attr = getattr(module, attribute)
        try:
            if isinstance(attr, type) and issubclass(attr, Host) and attr != Host:
                classes.append(attr)
        except Exception:
            continue

    return classes


def get_module_from_path(path: Path, parent_dir: Path) -> Union[object, None]:
    try:
        # Use a more unique name to avoid collisions with installed packages
        # Replacing separators with dots and removing extension
        rel_path = path.relative_to(parent_dir.parents[3])
        module_name = f"remote.{rel_path.with_suffix('').as_posix().replace('/', '.').replace('\\', '.')}"

        spec = importlib.util.spec_from_file_location(module_name, path.as_posix())
        module = importlib.util.module_from_spec(spec)
        if module.__name__ not in sys.modules:
            spec.loader.exec_module(module)
        return module
    except FileNotFoundError:
        return None
    except Exception as e:
        logging.error(f"Error loading module from {path.as_posix()}: {e}")
        return None


def get_modules() -> List[object]:
    modules = []
    for host_dir in HOSTS_DIRS:
        for file in rglob(host_dir, "*.py"):
            if Path(file).stem == "__init__":
                continue
            module = get_module_from_path(file, host_dir)
            if module:
                modules.append(module)
    return modules


def get_host_subclasses() -> List[Host]:
    modules = get_modules()
    subclasses = []
    for module in modules:
        subcls = get_host_subclasses_from_module(module)
        subclasses.extend(subcls)

        if not subcls:
            del module

    return subclasses


def protocol_to_host() -> Dict[str, Host]:
    subclasses = get_host_subclasses()
    protocols = {}
    for host in set(subclasses):
        if hasattr(host, "protocol") and host.protocol:
            protocols[host.protocol] = host

    return protocols
