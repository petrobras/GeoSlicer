"""What the login dialog does with each way a connection can fail.

_enterPassword is a Qt slot, and an exception leaving a slot does not surface
as an error dialog -- it takes the application down. The dialog used to
re-raise anything that was not an AuthException, so pointing an account at an
address that does not answer crashed GeoSlicer instead of reporting a timeout.

A wrong password is the only failure this dialog can fix, so it is the only one
it stays open for. Everything else closes and travels to the caller, which
reports connection failures for the whole flow.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from commons.remote import errors


class _Signal:
    def connect(self, slot):
        pass


class _Widget:
    """Enough of a Qt widget for the dialog to build itself.

    `text` is an attribute rather than a method because that is how PythonQt
    exposes it, and the dialog both reads and assigns it that way.
    """

    def __init__(self, *args, **kwargs):
        self.text = args[0] if args and isinstance(args[0], str) else ""
        self.clicked = _Signal()

    def setText(self, value):
        self.text = value

    def __getattr__(self, name):
        # Everything else the dialog touches is layout and styling plumbing.
        return lambda *args, **kwargs: None


class _Host:
    """A host whose credential lives in a dict standing in for the keyring."""

    name = "slurmlab"
    username = "drp"

    def __init__(self, stored=None):
        self.stored = stored

    def server_name(self):
        return "172.17.0.1"

    def get_password(self):
        return self.stored

    def set_password(self, password):
        self.stored = password

    def delete_password(self):
        self.stored = None


@pytest.fixture
def login(monkeypatch):
    """The real module, loaded against stubbed Qt and connection collaborators."""
    # Ahead of the stubs: importing targets triggers the host-plugin scan, and
    # that scan caches what it finds. Letting it run against a stubbed
    # commons.slicer.widget would leave the ssh host widget missing for every
    # test that follows.
    import commons.remote.targets

    qt = types.ModuleType("qt")
    for name in ("QDialog", "QLabel", "QPushButton", "QVBoxLayout", "QHBoxLayout", "QFormLayout"):
        setattr(qt, name, type(name, (_Widget,), {}))
    qt.Qt = MagicMock()
    monkeypatch.setitem(sys.modules, "qt", qt)

    widgets = types.ModuleType("commons.slicer.widget")
    widgets.PasswordEdit = type("PasswordEdit", (_Widget,), {})
    monkeypatch.setitem(sys.modules, "commons.slicer.widget", widgets)

    # The job monitor makes the connection; the dialog only waits for it.
    connecting = types.ModuleType("commons.slicer.widget.remote.connecting")
    remote = types.ModuleType("commons.slicer.widget.remote")
    remote.connecting = connecting
    widgets = Path(commons.__file__).parent / "slicer" / "widget" / "remote"
    # The real banner, built on the stubs above.
    remote.outdated = load(widgets / "outdated.py", "outdated_under_test")
    monkeypatch.setitem(sys.modules, "commons.slicer.widget.remote", remote)
    monkeypatch.setitem(sys.modules, "commons.slicer.widget.remote.connecting", connecting)
    monkeypatch.setitem(sys.modules, "commons.slicer.widget.remote.outdated", remote.outdated)

    return load(widgets / "login.py", "login_under_test")


def load(source, name):
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dialog_for(login, raising=None, host=None, connected=True):
    """`connected` is what the connection attempt reports; None is a cancel."""
    dialog = login.LoginDialog(host or _Host())
    dialog.outcome = None
    dialog.accept = lambda: setattr(dialog, "outcome", "accepted")
    dialog.reject = lambda: setattr(dialog, "outcome", "rejected")
    dialog.passwordField.text = "hunter2"

    def connect(host, parent=None):
        if raising is not None:
            raise raising
        return connected

    login.connecting.connect = connect
    return dialog


UNREACHABLE = [
    errors.TimeoutException(TimeoutError("timed out"), "172.17.0.1"),
    errors.HostNotFoundError(OSError("name resolution"), "nope.invalid"),
    errors.BadHostKeyException(Exception("key changed"), "host"),
    errors.SSHException(OSError("no route to host"), "host"),
    errors.MissingCredentialsError(ValueError("nothing stored"), "host"),
    RuntimeError("something nobody anticipated"),
]
UNREACHABLE_IDS = ["timeout", "unknown-host", "bad-host-key", "no-route", "no-credentials", "unexpected"]


def test_a_successful_connection_is_accepted(login):
    dialog = dialog_for(login)

    dialog._enterPassword()

    assert dialog.outcome == "accepted"
    assert dialog.output is True
    assert dialog.error is None
    assert dialog.host.stored == "hunter2"


def test_a_rejected_password_keeps_the_dialog_open(login):
    dialog = dialog_for(login, errors.AuthException(ValueError("rejected"), "host"))

    dialog._enterPassword()

    assert dialog.outcome is None
    assert dialog.error is None
    assert "password" in dialog.message.text.lower()
    assert dialog.passwordField.text == ""


def test_an_empty_password_is_not_sent_anywhere(login):
    dialog = dialog_for(login, host=_Host(stored="kept"))
    dialog.passwordField.text = ""

    dialog._enterPassword()

    assert dialog.outcome is None
    assert dialog.host.stored == "kept"


@pytest.mark.parametrize("failure", UNREACHABLE, ids=UNREACHABLE_IDS)
def test_an_unreachable_server_closes_the_dialog(login, failure):
    # The caller reports it: this dialog only asks for a password, and no
    # password would have helped. Raising instead would abort the application.
    dialog = dialog_for(login, failure)

    dialog._enterPassword()

    assert dialog.outcome == "rejected"
    assert dialog.error is failure


@pytest.mark.parametrize("failure", UNREACHABLE, ids=UNREACHABLE_IDS)
def test_an_unconfirmed_password_is_not_kept(login, failure):
    # connect() reads the credential from the keyring, so it has to be written
    # before it can be tried. A server that never confirmed it must not leave
    # it stored as if it had.
    dialog = dialog_for(login, failure, host=_Host(stored=None))

    dialog._enterPassword()

    assert dialog.host.stored is None


@pytest.mark.parametrize("failure", UNREACHABLE, ids=UNREACHABLE_IDS)
def test_an_already_stored_password_is_restored(login, failure):
    dialog = dialog_for(login, failure, host=_Host(stored="previous"))

    dialog._enterPassword()

    assert dialog.host.stored == "previous"


@pytest.mark.parametrize("stored", [None, "previous"], ids=["nothing-stored", "already-stored"])
def test_cancelling_the_connection_returns_to_the_password(login, stored):
    # Cancel on the Connecting dialog abandons this attempt, not the sign in:
    # the password prompt stays up, and the credential is as it was.
    dialog = dialog_for(login, connected=None, host=_Host(stored=stored))

    dialog._enterPassword()

    assert dialog.outcome is None
    assert dialog.error is None
    assert dialog.host.stored == stored


def test_an_account_from_an_older_version_is_warned_about(login, monkeypatch):
    monkeypatch.setattr(login.TargetManager, "outdated", {_Host.name})

    dialog = login.LoginDialog(_Host())

    assert "“slurmlab” was configured in an older version" in dialog.outdatedBanner.text


def test_a_current_account_gets_no_warning(login, monkeypatch):
    monkeypatch.setattr(login.TargetManager, "outdated", set())

    dialog = login.LoginDialog(_Host())

    assert dialog.outdatedBanner.text == ""
