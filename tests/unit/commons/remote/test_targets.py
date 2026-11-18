"""Accounts saved by an older version are flagged, and stay flagged until removed.

An account is outdated when, as stored in config.json, it lacks a top-level key
that every account template of its protocol has. Those accounts are not updated
in place: the user is told to create them again. So the flag has to survive a
save -- which writes every current field of every account, and would make an
old one look current from the next start on -- and to go away only with the
account itself.
"""

import json
import shutil
from pathlib import Path

import pytest

from commons.remote.hosts.base import Host
from commons.remote.hosts.ssh.ssh import SshHost
from commons.remote.targets import OUTDATED_HOSTS_KEY, TargetManager, is_outdated_host

SRC = Path(__file__).parents[4] / "src"
TEMPLATES_DIR = SRC / "modules" / "RemoteService" / "Resources" / "templates"
# Written by 2.9.1, before the templates had "storage" and "remote_paths".
OLD_CONFIG = SRC / "modules" / "JobMonitor" / "Test" / "Resources" / "config.json"

TEMPLATE = {"name": "", "username": "", "address": "", "protocol": "ssh", "storage": {}}


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """TargetManager on a copy of the old accounts file, with the shipped templates."""
    for attribute in ("targets", "default", "targets_storage", "templates_dir", "outdated"):
        monkeypatch.setattr(TargetManager, attribute, getattr(TargetManager, attribute))
    # Removing an account deletes its password; there is no keyring here.
    monkeypatch.setattr(Host, "delete_password", lambda self: None)

    storage = tmp_path / "config.json"
    shutil.copy(OLD_CONFIG, storage)
    TargetManager.set_storage(storage)
    TargetManager.set_templates_dir(TEMPLATES_DIR)
    return TargetManager


def reload(manager):
    manager.save_targets()
    manager.load_targets()


def test_an_account_missing_a_template_key_is_outdated():
    assert is_outdated_host({"name": "a", "username": "u", "address": "h", "protocol": "ssh"}, [TEMPLATE])


def test_an_account_with_every_template_key_is_current_whatever_else_it_has():
    stored = {**TEMPLATE, "mounted_path": "", "remote_version": ""}

    assert not is_outdated_host(stored, [TEMPLATE])


def test_only_the_top_level_keys_are_compared():
    stored = {**TEMPLATE, "storage": {"cluster_root": "/nethome"}}
    template = {**TEMPLATE, "storage": {"cluster_root": "/nethome", "dirs": {}}}

    assert not is_outdated_host(stored, [template])


def test_an_account_whose_protocol_has_no_template_is_never_outdated():
    assert not is_outdated_host({"name": "b", "username": "u", "protocol": "biaep"}, [TEMPLATE])


def test_matching_one_template_of_the_protocol_is_enough():
    stored = {"name": "a", "username": "u", "address": "h", "protocol": "ssh"}
    other = {"name": "", "username": "", "address": "", "protocol": "ssh"}

    assert not is_outdated_host(stored, [TEMPLATE, other])


def test_accounts_saved_by_an_older_version_are_flagged_on_load(manager):
    manager.load_targets()

    assert manager.outdated == {"Atena 02", "Zeus 01"}
    assert manager.is_outdated(manager.targets["Atena 02"])


def test_saving_keeps_them_flagged(manager):
    """The saved account now has every key, yet was never created again."""
    manager.load_targets()
    manager.save_targets()

    content = json.loads(manager.targets_storage.read_text())
    assert all("storage" in host for host in content["hosts"])
    assert content[OUTDATED_HOSTS_KEY] == ["Atena 02", "Zeus 01"]

    manager.load_targets()
    assert manager.outdated == {"Atena 02", "Zeus 01"}


def test_removing_an_account_clears_its_flag(manager):
    manager.load_targets()
    manager.del_target(manager.targets["Atena 02"])
    reload(manager)

    assert manager.outdated == {"Zeus 01"}


def test_an_account_created_again_under_the_same_name_is_current(manager):
    manager.load_targets()
    manager.del_target(manager.targets["Atena 02"])
    manager.add_target(SshHost(username="user1", name="Atena 02", address="atena02"))
    reload(manager)

    assert not manager.is_outdated(manager.targets["Atena 02"])
    assert manager.is_outdated(manager.targets["Zeus 01"])


def test_a_file_with_nothing_outdated_saves_no_flags(manager):
    manager.load_targets()
    for name in list(manager.targets):
        manager.del_target(manager.targets[name])
    manager.add_target(SshHost(username="user1", name="Atena 02", address="atena02"))
    reload(manager)

    assert manager.outdated == set()
    assert OUTDATED_HOSTS_KEY not in json.loads(manager.targets_storage.read_text())


def test_without_templates_nothing_is_flagged(manager):
    manager.set_templates_dir(None)
    manager.load_targets()

    assert manager.outdated == set()
    assert set(manager.targets) == {"Atena 02", "Zeus 01"}


def test_an_unreadable_template_is_skipped(manager, tmp_path):
    templates = tmp_path / "templates"
    shutil.copytree(TEMPLATES_DIR, templates)
    (templates / "broken.json").write_text("{ not json")
    manager.set_templates_dir(templates)

    manager.load_targets()

    assert manager.outdated == {"Atena 02", "Zeus 01"}
