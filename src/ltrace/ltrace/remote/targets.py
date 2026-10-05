import json
import logging
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Set

from ltrace.remote.hosts.base import Host
from ltrace.remote.hosts import PROTOCOL_HANDLERS

# config.json key listing the accounts saved by an older version.
OUTDATED_HOSTS_KEY = "outdated_hosts"


def is_outdated_host(stored: Dict, templates: List[Dict]) -> bool:
    """Whether an account, as stored, predates the account templates.

    Only the top-level keys are compared, against the templates of the same
    protocol: an account is current when it has every key of at least one of
    them. A protocol with no template has nothing to be compared with, so its
    accounts are never flagged.
    """
    keys = set(stored)
    candidates = [set(template) for template in templates if template.get("protocol") == stored.get("protocol")]
    return bool(candidates) and not any(template <= keys for template in candidates)


class TargetManager:
    targets: Dict[str, Host] = defaultdict(lambda: None)
    default: Host = None
    targets_storage: Path = None
    templates_dir: Path = None
    # Names of the accounts saved by an older version (see is_outdated_host).
    # They are not migrated: the user is asked to create them again. The flag
    # is saved along with them, because saving writes every field of every
    # account -- an old one would look current from the next start on, still
    # missing the template's values.
    outdated: Set[str] = set()

    @classmethod
    def set_default(cls, hostkey: str):
        cls.default = cls.targets.get(hostkey, None)

    @classmethod
    def set_storage(cls, path: Path):
        cls.targets_storage = path

    @classmethod
    def set_templates_dir(cls, path: Path):
        cls.templates_dir = path

    @classmethod
    def load_templates(cls) -> List[Dict]:
        """The account templates, as shipped."""
        if cls.templates_dir is None:
            return []

        templates = []
        for path in sorted(Path(cls.templates_dir).glob("*.json")):
            try:
                with open(path, "r") as file:
                    templates.append(json.load(file))
            except Exception as e:
                logging.error(f"Error loading account template {path}: {e}")

        return templates

    @classmethod
    def is_outdated(cls, host: Host) -> bool:
        """Whether this account was saved by an older version and must be created again."""
        return host is not None and host.name in cls.outdated

    @classmethod
    def mark_outdated(cls, host: Host):
        cls.outdated.add(host.name)

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
        cls.outdated.discard(host.name)

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

        outdated = sorted(name for name in cls.outdated if name in cls.targets)
        if outdated:
            content[OUTDATED_HOSTS_KEY] = outdated

        cls.targets_storage.parent.mkdir(parents=True, exist_ok=True)

        with open(cls.targets_storage, "w") as file:
            json.dump(content, file, indent=2)

    @classmethod
    def load_targets(cls):
        if cls.targets_storage is None:
            raise ValueError("No storage path set.")

        cls.outdated = set()

        if not cls.targets_storage.exists():
            logging.warning(f"Target storage {cls.targets_storage} does not exist. Starting with empty targets.")
            cls.targets = {}
            return

        try:
            with open(cls.targets_storage, "r") as file:
                content = json.load(file)
                # Checked before from_dict, which fills in every field the
                # account was saved without.
                templates = cls.load_templates()
                outdated = {hostDict["name"] for hostDict in content["hosts"] if is_outdated_host(hostDict, templates)}
                outdated.update(content.get(OUTDATED_HOSTS_KEY, []))

                cls.targets = {
                    hostDict["name"]: PROTOCOL_HANDLERS[hostDict["protocol"]].from_dict(hostDict)
                    for hostDict in content["hosts"]
                }
                cls.default = cls.targets.get(content.get("default", None), None)
                cls.outdated = {name for name in outdated if name in cls.targets}
        except Exception as e:
            logging.error(f"Error loading targets: {e}")
            cls.targets = {}
            cls.outdated = set()

        if cls.outdated:
            logging.warning(f"Accounts saved by an older version, to be created again: {sorted(cls.outdated)}")

    @classmethod
    def load_host(cls, hostfile: Path) -> Host:
        if not hostfile.exists():
            logging.warning(f"Host file {hostfile} does not exist.")
            return None

        with open(hostfile, "r") as file:
            content = json.load(file)
            return PROTOCOL_HANDLERS[content["protocol"]].from_dict(content)
