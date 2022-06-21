import importlib
import logging
import sys
from pathlib import Path
from typing import Union, List, Dict

from ltrace.remote.hosts.base import Host

HOSTS_DIR = Path(__file__).parent


def get_host_subclasses_from_module(module: "module") -> List[Host]:
    classes = []
    for attribute in dir(module):
        attr = getattr(module, attribute)
        try:
            if issubclass(attr, Host) and attr != Host:
                logging.debug(f"{attr.__name__} is a subclass of 'Host'")
                classes.append(attr)
        except Exception:
            continue

    return classes


def get_module_from_path(path: Path) -> Union["module", None]:
    try:
        spec = importlib.util.spec_from_file_location(path.stem, path.as_posix())
        module = importlib.util.module_from_spec(spec)
        if module.__name__ not in sys.modules:
            spec.loader.exec_module(module)
        return module
    except FileNotFoundError:
        logging.error(f"File not found at path: {path}")
        return None
    except Exception as e:
        logging.error(f"Error loading module from {path.as_posix()}: {e}")
        return None


def get_modules() -> List[Path]:
    modules = []
    for file in HOSTS_DIR.rglob("*.py"):
        if file.stem == "__init__":
            continue
        module = get_module_from_path(file)
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
    for host in subclasses:
        if host.protocol:
            protocols[host.protocol] = host

    return protocols
