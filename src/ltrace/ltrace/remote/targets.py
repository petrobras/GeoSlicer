import json
import logging
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Dict

from ltrace.remote.hosts.base import Host
from ltrace.remote.hosts import PROTOCOL_HANDLERS


class TargetManager:
    targets: Dict[str, Host] = defaultdict(lambda: None)
    default: Host = None
    targets_storage: Path = None

    @classmethod
    def set_default(cls, hostkey: str):
        cls.default = cls.targets.get(hostkey, None)

    @classmethod
    def set_storage(cls, path: Path):
        cls.targets_storage = path

    @classmethod
    def add_target(cls, host: Host, is_default: bool = False):
        if host.name in cls.targets:
            raise KeyError(f"Host {host.name} already exists. Please use a different name.")

        cls.targets[host.name] = host

        if is_default:
            cls.default = host

    @classmethod
    def del_target(cls, host: Host):
        if host.name not in cls.targets:
            raise KeyError(f"Host {host.name} does not exist.")

        host.delete_password()
        del cls.targets[host.name]

    @classmethod
    def set_target(cls, host: Host):
        cls.targets[host.name] = host

    @classmethod
    def save_targets(cls):
        if cls.targets_storage is None:
            raise ValueError("No storage path set.")

        content = {"hosts": [host.to_dict() for host in cls.targets.values()]}

        if cls.default is not None:
            content["default"] = cls.default.name

        cls.targets_storage.parent.mkdir(parents=True, exist_ok=True)

        with open(cls.targets_storage, "w") as file:
            json.dump(content, file, indent=2)

    @classmethod
    def load_targets(cls):
        if cls.targets_storage is None:
            raise ValueError("No storage path set.")

        if not cls.targets_storage.exists():
            logging.warning(f"Target storage {cls.targets_storage} does not exist. Starting with empty targets.")
            cls.targets = {}
            return

        try:
            with open(cls.targets_storage, "r") as file:
                content = json.load(file)
                cls.targets = {
                    hostDict["name"]: PROTOCOL_HANDLERS[hostDict["protocol"]].from_dict(hostDict)
                    for hostDict in content["hosts"]
                }
                cls.default = cls.targets.get(content.get("default", None), None)
        except Exception as e:
            logging.error(f"Error loading targets: {e}")
            cls.targets = {}

    @classmethod
    def load_host(cls, hostfile: Path) -> Host:
        if not hostfile.exists():
            logging.warning(f"Host file {hostfile} does not exist.")
            return None

        with open(hostfile, "r") as file:
            content = json.load(file)
            return PROTOCOL_HANDLERS[content["protocol"]].from_dict(content)
