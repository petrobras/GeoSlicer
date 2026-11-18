"""The reconnect prompt warns about hosts whose account is from an older version.

It lists the hosts whose jobs are waiting on a sign in. Those jobs are the very
case the warning is about: they are better collected or cancelled from the
version that started them, before the account is created again.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class _Widget:
    """Enough of a Qt widget for the dialog to build itself."""

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        # Everything else the dialog touches is layout and styling plumbing.
        return lambda *args, **kwargs: None


class _Label(_Widget):
    def __init__(self, *args, **kwargs):
        self.text = args[0] if args and isinstance(args[0], str) else ""
        self.visible = True

    def setText(self, text):
        self.text = text

    def setVisible(self, visible):
        self.visible = visible


class _Host:
    def __init__(self, name):
        self.name = name

    def get_key(self):
        return f"ssh://{self.name}"


def load(source, name):
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def reconnect(monkeypatch):
    """The real module, loaded against stubbed Qt."""
    import commons

    qt = types.ModuleType("qt")
    qt.Signal = lambda *args: MagicMock()
    for name in ("QFrame", "QDialog", "QHBoxLayout", "QVBoxLayout"):
        setattr(qt, name, type(name, (_Widget,), {}))
    qt.QLabel = _Label
    qt.QPushButton = MagicMock()
    qt.QDialogButtonBox = MagicMock()
    qt.Qt = MagicMock()
    monkeypatch.setitem(sys.modules, "qt", qt)

    widgets = Path(commons.__file__).parent / "slicer" / "widget" / "remote"
    remote = types.ModuleType("commons.slicer.widget.remote")
    remote.outdated = load(widgets / "outdated.py", "outdated_under_test")
    monkeypatch.setitem(sys.modules, "commons.slicer.widget.remote", remote)
    monkeypatch.setitem(sys.modules, "commons.slicer.widget.remote.outdated", remote.outdated)

    return load(widgets / "reconnect.py", "reconnect_under_test")


def dialog_for(reconnect, hosts, isOutdated=None):
    return reconnect.ReconnectDialog(hosts, jobCounter=lambda host: 1, onConnect=lambda host: 0, isOutdated=isOutdated)


def rows_of(dialog):
    return dialog._ReconnectDialog__rows


def test_the_banner_names_only_the_hosts_from_an_older_version(reconnect):
    old, new = _Host("atena (old)"), _Host("atena")

    dialog = dialog_for(reconnect, [old, new], isOutdated=lambda host: host is old)

    assert dialog.outdatedBanner.visible
    assert "“atena (old)” was configured in an older version" in dialog.outdatedBanner.text
    assert "“atena”" not in dialog.outdatedBanner.text
    assert rows_of(dialog)[old.get_key()].outdatedLabel.visible
    assert not rows_of(dialog)[new.get_key()].outdatedLabel.visible


def test_without_a_check_nothing_is_warned_about(reconnect):
    host = _Host("atena")

    dialog = dialog_for(reconnect, [host])

    assert not dialog.outdatedBanner.visible
    assert not rows_of(dialog)[host.get_key()].outdatedLabel.visible
