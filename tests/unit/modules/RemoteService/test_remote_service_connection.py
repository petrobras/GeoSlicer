"""How RemoteServiceLogic picks and connects the account a connection is for.

Connecting to the default account normally skips the list -- straight to the
password prompt, or straight to connecting when a password is saved. For an
account configured in an older version that would leave nowhere to say it has
to be created again, so the list, which warns about it, is shown instead.

When the list picks the account a job runs on, sending the job there and
connecting to an account are different choices: Connect only connects, and
the list comes back to send the job from.
"""

import importlib
import sys
import types
from unittest.mock import MagicMock

import pytest

from commons.remote.hosts.ssh.ssh import SshHost
from commons.remote.targets import TargetManager

MODULE_NAME = "modules.RemoteService.RemoteService"


def stub(monkeypatch, name, **attributes):
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.fixture
def service(monkeypatch):
    """The real module, with its Qt side -- plugin base, dialogs, job loaders -- stubbed out.

    Those build Qt classes on import, from whichever qt mock an earlier test
    left behind; only the connection flow is under test here.
    """
    connecting = MagicMock()
    connecting.connect.return_value = True
    stub(monkeypatch, "commons.slicer_utils", LTracePlugin=object, LTracePluginWidget=object)
    stub(monkeypatch, "commons.slicer.widget.remote", login=MagicMock(), accounts=MagicMock(), connecting=connecting)
    stub(monkeypatch, "commons.slicer.widget.remote.reconnect", ReconnectDialog=MagicMock())
    stub(monkeypatch, "commons.slicer.application_observables", ApplicationObservables=MagicMock())
    stub(monkeypatch, "JobLoader", register_job_loaders=MagicMock())

    # Executed afresh for every test, so it binds to this test's stubs; the cached copy is dropped afterwards.
    monkeypatch.setitem(sys.modules, MODULE_NAME, None)
    del sys.modules[MODULE_NAME]
    module = importlib.import_module(MODULE_NAME)

    monkeypatch.setattr(module, "ConnectionManager", MagicMock())
    for attribute in ("targets", "default", "outdated"):
        monkeypatch.setattr(TargetManager, attribute, getattr(TargetManager, attribute))
    return module


def logic_with_default(service, outdated):
    host = SshHost(username="drp", name="atena", address="atena02")
    host.get_password = lambda: "saved"
    TargetManager.targets = {host.name: host}
    TargetManager.default = host
    TargetManager.outdated = {host.name} if outdated else set()

    logic = service.RemoteServiceLogic()
    # Cancelling the list ends the flow.
    logic.showSelectTargetDialog = MagicMock(return_value=(None, False))
    return logic, host


def test_an_outdated_default_account_opens_the_account_list(service):
    logic, host = logic_with_default(service, outdated=True)

    assert logic.initiateConnectionDialog() == (None, None)

    logic.showSelectTargetDialog.assert_called_once()
    service.connecting.connect.assert_not_called()


def test_a_current_default_account_connects_straight_away(service):
    logic, host = logic_with_default(service, outdated=False)

    assert logic.initiateConnectionDialog() == (host, True)

    logic.showSelectTargetDialog.assert_not_called()


def test_a_given_outdated_host_still_connects_straight_away(service):
    """Resuming a job names its host: that is not the default's shortcut."""
    logic, host = logic_with_default(service, outdated=True)

    assert logic.initiateConnectionDialog(host) == (host, True)

    logic.showSelectTargetDialog.assert_not_called()


def test_sending_a_job_picks_its_account_as_the_jobs(service):
    logic, host = logic_with_default(service, outdated=False)
    logic.initiateConnectionDialog = MagicMock(return_value=(None, None))

    logic.run(MagicMock(), name="job")

    logic.initiateConnectionDialog.assert_called_once_with(forJob=True)


def test_connect_while_picking_a_jobs_account_comes_back_to_the_list(service):
    logic, host = logic_with_default(service, outdated=True)
    # Connect on the account, then cancel the list that comes back.
    logic.showSelectTargetDialog.side_effect = [(host, True), (None, False)]

    assert logic.initiateConnectionDialog(forJob=True) == (None, None)

    assert logic.showSelectTargetDialog.call_count == 2
    service.connecting.connect.assert_called_once()


def DISABLED_test_sending_to_an_account_hands_it_to_the_job(service):
    logic, host = logic_with_default(service, outdated=True)
    logic.showSelectTargetDialog.return_value = (host, False)

    assert logic.initiateConnectionDialog(forJob=True) == (host, True)

    logic.showSelectTargetDialog.assert_called_once()


@pytest.mark.parametrize(
    "forJob, send, connectOnly",
    [(True, False, True), (True, True, False), (False, False, False)],
    ids=["connect-for-a-job", "send-for-a-job", "connect-otherwise"],
)
def test_the_list_tells_connecting_from_sending(service, monkeypatch, forJob, send, connectOnly):
    logic = service.RemoteServiceLogic()
    logic.load_templates = MagicMock(return_value=[])
    host = SshHost(username="drp", name="atena", address="atena02")

    def showAccounts(hosts, select, templates=None, forJob=False):
        # Connect calls back with the host alone; the send arrow adds send=True.
        if send:
            select(host, send=True)
        else:
            select(host)
        return True

    monkeypatch.setattr(service.RemoteServiceWidget, "showAccounts", staticmethod(showAccounts))

    assert logic.showSelectTargetDialog([], forJob=forJob) == (host, connectOnly)
