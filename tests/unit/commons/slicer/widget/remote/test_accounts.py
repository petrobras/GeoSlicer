"""Connecting and disconnecting an account from the Accounts dialog.

Each row has a single connection button: it reads Disconnect while its account
is connected and Connect otherwise. Disconnect hands the host to
ConnectionManager.disconnect -- which closes the connection and keeps the job
monitor from quietly reconnecting -- and marks the row as down, turning the
button back into Connect. Connect picks the account. What ConnectionManager
does with it is test_connection_manager's; this is about the row wiring it up,
including a row rebuilt by Edit.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class _BoundSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class _Signal:
    """Enough of a Qt signal: one per instance, which can connect and emit."""

    def __init__(self, *args):
        self.name = None

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return obj.__dict__.setdefault(self.name, _BoundSignal())


class _Widget:
    """Enough of a Qt widget for the rows to build themselves."""

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        # Everything else the widgets touch is layout and styling plumbing.
        return lambda *args, **kwargs: None


class _Label(_Widget):
    def __init__(self, *args, **kwargs):
        self.text = args[0] if args and isinstance(args[0], str) else ""
        self.visible = True

    def setText(self, text):
        self.text = text

    def setVisible(self, visible):
        self.visible = visible


class _Button(_Widget):
    clicked = _Signal()

    def __init__(self, text="", *args, **kwargs):
        self.text = text
        self.toolTip = ""
        self.visible = True
        self.styleSheet = ""

    def setText(self, text):
        self.text = text

    def setStyleSheet(self, styleSheet):
        self.styleSheet = styleSheet

    def fontMetrics(self):
        return types.SimpleNamespace(horizontalAdvance=len)

    def setToolTip(self, toolTip):
        self.toolTip = toolTip

    def setVisible(self, visible):
        self.visible = visible


class _ListWidgetItem:
    def __init__(self, listWidget=None):
        self.values = {}
        if listWidget is not None:
            listWidget.items.append(self)

    def setData(self, role, value):
        self.values[role] = value

    def data(self, role):
        return self.values.get(role)

    def setSizeHint(self, hint):
        pass


class _ListWidget(_Widget):
    def __init__(self, *args, **kwargs):
        self.items = []
        self.widgets = {}

    @property
    def count(self):
        # An attribute, not a method: that is how PythonQt exposes it.
        return len(self.items)

    def item(self, row):
        return self.items[row]

    def row(self, item):
        return self.items.index(item)

    def takeItem(self, row):
        return self.items.pop(row)

    def setItemWidget(self, item, widget):
        self.widgets[id(item)] = widget

    def itemWidget(self, item):
        return self.widgets.get(id(item))


class _Host:
    def __init__(self, name):
        self.name = name


def load(source, name):
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def accounts(monkeypatch):
    """The real module, loaded against stubbed Qt and collaborators."""
    # Ahead of the stubs: importing these triggers the host-plugin scan, and
    # that scan caches what it finds -- see test_login_dialog.
    import commons.remote.connections
    import commons.remote.targets

    qt = types.ModuleType("qt")
    qt.Signal = _Signal
    qt.QWidget = _Widget
    qt.QDialog = _Widget
    qt.QLabel = _Label
    qt.QHBoxLayout = _Widget
    qt.QVBoxLayout = _Widget
    qt.QPushButton = _Button
    qt.QListWidget = _ListWidget
    qt.QListWidgetItem = _ListWidgetItem
    for name in ("QPalette", "QPixmap", "QPainter", "QColor", "QPen", "QIcon", "QSize", "Qt"):
        setattr(qt, name, MagicMock())
    monkeypatch.setitem(sys.modules, "qt", qt)

    widgets = Path(commons.remote.connections.__file__).parents[1] / "slicer" / "widget" / "remote"

    register = types.ModuleType("commons.slicer.widget.remote.register")
    register.RegisterDialog = MagicMock()
    # The real banner, built on the stubs above.
    outdated = load(widgets / "outdated.py", "outdated_under_test")
    remote = types.ModuleType("commons..slicer.widget.remote")
    remote.register = register
    remote.outdated = outdated
    monkeypatch.setitem(sys.modules, "commons..slicer.widget.remote", remote)
    monkeypatch.setitem(sys.modules, "commons.slicer.widget.remote.register", register)
    monkeypatch.setitem(sys.modules, "commons.slicer.widget.remote.outdated", outdated)

    module = load(widgets / "accounts.py", "accounts_under_test")

    module.ConnectionManager = MagicMock()
    module.ConnectionManager.check_host.return_value = True
    return module


def accounts_with(accounts, host, connected=True):
    widget = accounts.AccountsWidget(backend=MagicMock(), selector=MagicMock())
    widget.addItem(host, status=connected)
    item = widget.accountsListWidget.item(0)
    return widget, item, widget.accountsListWidget.itemWidget(item)


@pytest.mark.parametrize(
    "connected, text", [(True, "Disconnect"), (False, "Connect")], ids=["connected", "disconnected"]
)
def test_the_connection_button_follows_the_status(accounts, connected, text):
    row = accounts.AccountListItemWidget("cluster", connected=connected)

    assert row.connectionButton.text == text


def test_disconnect_disconnects_the_rows_host_and_marks_it_down(accounts):
    host = _Host("cluster")
    widget, item, row = accounts_with(accounts, host)

    row.connectionButton.clicked.emit()

    accounts.ConnectionManager.disconnect.assert_called_once_with(host)
    assert row.status == accounts.AccountListItemWidget.ERROR
    assert row.connectionButton.text == "Connect"


def test_disconnect_does_not_pick_the_account(accounts):
    widget, item, row = accounts_with(accounts, _Host("cluster"))

    row.connectionButton.clicked.emit()

    widget.selector.assert_not_called()


def test_connect_picks_the_account_without_disconnecting(accounts):
    host = _Host("cluster")
    widget, item, row = accounts_with(accounts, host, connected=False)

    row.connectionButton.clicked.emit()

    widget.selector.assert_called_once_with(host)
    accounts.ConnectionManager.disconnect.assert_not_called()


def test_a_disconnected_row_connects_again_from_the_same_button(accounts):
    host = _Host("cluster")
    widget, item, row = accounts_with(accounts, host)

    row.connectionButton.clicked.emit()
    row.connectionButton.clicked.emit()

    accounts.ConnectionManager.disconnect.assert_called_once_with(host)
    widget.selector.assert_called_once_with(host)


def test_an_edited_row_can_still_be_disconnected_and_made_default(accounts):
    """Edit rebuilds the row, and the rebuilt one used to lose some of its
    buttons' wiring -- Set as default did nothing on it."""
    edited = _Host("cluster (edited)")
    accounts.RegisterDialog.editing.return_value = edited
    widget, item, row = accounts_with(accounts, _Host("cluster"))

    row.editButton.clicked.emit()
    rebuilt = widget.accountsListWidget.itemWidget(item)

    assert rebuilt is not row
    assert rebuilt.status == accounts.AccountListItemWidget.OK

    rebuilt.connectionButton.clicked.emit()
    accounts.ConnectionManager.disconnect.assert_called_once_with(edited)

    rebuilt.defaultButton.clicked.emit()
    assert widget.backend.default is edited


class _Backend:
    """TargetManager as far as the outdated flag goes."""

    def __init__(self, outdated=()):
        self.outdated = set(outdated)
        self.default = None

    def is_outdated(self, host):
        return host.name in self.outdated

    def mark_outdated(self, host):
        self.outdated.add(host.name)

    def del_target(self, host):
        self.outdated.discard(host.name)

    def set_target(self, host):
        pass

    def save_targets(self):
        pass


def accounts_listing(accounts, outdated, *names):
    widget = accounts.AccountsWidget(backend=_Backend(outdated), selector=MagicMock())
    widget.fillList([(False, _Host(name)) for name in names])
    return widget


def row_of(accounts, widget, name):
    for item in widget.accountsListWidget.items:
        if item.data(accounts.qt.Qt.UserRole).name == name:
            return item, widget.accountsListWidget.itemWidget(item)
    raise KeyError(name)


def test_the_banner_names_only_the_accounts_from_an_older_version(accounts):
    widget = accounts_listing(accounts, {"atena (old)"}, "atena (old)", "atena")

    assert widget.outdatedBanner.visible
    assert "“atena (old)”" in widget.outdatedBanner.text
    assert "“atena”" not in widget.outdatedBanner.text
    assert "collect their results or cancel them in that older version" in widget.outdatedBanner.text
    assert row_of(accounts, widget, "atena (old)")[1].outdatedLabel.visible
    assert not row_of(accounts, widget, "atena")[1].outdatedLabel.visible


def test_there_is_no_banner_when_every_account_is_current(accounts):
    widget = accounts_listing(accounts, set(), "atena")

    assert not widget.outdatedBanner.visible
    assert widget.outdatedBanner.text == ""


def test_the_banner_names_every_outdated_account(accounts):
    widget = accounts_listing(accounts, {"atena", "zeus"}, "atena", "zeus")

    assert "“atena” and “zeus” were configured in an older version" in widget.outdatedBanner.text


def test_removing_the_outdated_account_takes_the_banner_down(accounts):
    widget = accounts_listing(accounts, {"atena (old)"}, "atena (old)", "atena")
    item, row = row_of(accounts, widget, "atena (old)")

    row.removeButton.clicked.emit()

    assert not widget.outdatedBanner.visible


def test_editing_an_outdated_account_does_not_make_it_current(accounts):
    """Edit fills the new settings from the form, not the template: it still
    has to be created again."""
    edited = _Host("atena (edited)")
    accounts.RegisterDialog.editing.return_value = edited
    widget = accounts_listing(accounts, {"atena"}, "atena")
    item, row = row_of(accounts, widget, "atena")

    row.editButton.clicked.emit()

    assert widget.backend.is_outdated(edited)
    assert widget.accountsListWidget.itemWidget(item).outdatedLabel.visible
    assert "“atena (edited)”" in widget.outdatedBanner.text


def accounts_for_job(accounts, host, connected=True, forJob=True):
    widget = accounts.AccountsWidget(backend=_Backend(), selector=MagicMock(), forJob=forJob)
    widget.addItem(host, status=connected)
    item = widget.accountsListWidget.item(0)
    return widget, item, widget.accountsListWidget.itemWidget(item)


@pytest.mark.parametrize("forJob", [True, False], ids=["picking-for-a-job", "managing"])
def test_the_send_arrow_shows_only_when_picking_the_account_for_a_job(accounts, forJob):
    widget, item, row = accounts_for_job(accounts, _Host("cluster"), forJob=forJob)

    assert row.sendButton.visible is forJob


@pytest.mark.parametrize("connected", [True, False], ids=["connected", "disconnected"])
def test_the_send_arrow_picks_the_account_for_the_job(accounts, connected):
    """A connected account used to offer only Disconnect, so no job could be sent to it."""
    host = _Host("cluster")
    widget, item, row = accounts_for_job(accounts, host, connected=connected)

    row.sendButton.clicked.emit()

    widget.selector.assert_called_once_with(host, send=True)
    accounts.ConnectionManager.disconnect.assert_not_called()


def test_connect_is_not_a_send(accounts):
    host = _Host("cluster")
    widget, item, row = accounts_for_job(accounts, host, connected=False)

    row.connectionButton.clicked.emit()

    widget.selector.assert_called_once_with(host)


def test_an_edited_row_keeps_its_send_arrow(accounts):
    accounts.RegisterDialog.editing.return_value = _Host("cluster (edited)")
    widget, item, row = accounts_for_job(accounts, _Host("cluster"))

    row.editButton.clicked.emit()

    assert widget.accountsListWidget.itemWidget(item).sendButton.visible


def test_disconnect_is_red_and_connect_is_not(accounts):
    widget, item, row = accounts_for_job(accounts, _Host("cluster"), connected=True)
    assert row.connectionButton.styleSheet == accounts.DISCONNECT_STYLE

    row.connectionButton.clicked.emit()

    assert row.connectionButton.text == "Connect"
    assert row.connectionButton.styleSheet == ""


def test_the_dialog_hands_over_whether_the_account_was_sent_to(accounts):
    picked = []
    dialog = accounts.AccountsDialog(backend=_Backend(), onAccept=lambda host, send: picked.append((host, send)))
    host = _Host("cluster")

    dialog.widget.selector(host)
    dialog.widget.selector(host, send=True)

    assert picked == [(host, False), (host, True)]
