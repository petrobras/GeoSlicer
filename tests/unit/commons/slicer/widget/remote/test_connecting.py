"""Connecting through the job monitor, with a way out.

The job monitor makes the connection and keeps the client; connect() only asks
for it and waits behind a 'Connecting...' dialog with a Cancel button. What is
tested here is what connect() reports for each way the wait can end --
connected, failed, cancelled, timed out. The dialog itself is test_waiting's.
"""

from concurrent.futures import Future

import pytest

from commons.remote import errors
from commons.slicer.widget.remote import connecting


class _Host:
    name = "slurmlab"

    def server_name(self):
        return "172.17.0.1"


@pytest.fixture
def future(monkeypatch):
    future = Future()
    monkeypatch.setattr(connecting.JobManager, "request_connect", lambda host: future)
    return future


def wait_by(monkeypatch, behave):
    """Stand in for the dialog: `behave(futures)` plays the person and the monitor."""
    shown = {}

    def wait(futures, **kwargs):
        shown.update(kwargs)
        return behave(futures)

    monkeypatch.setattr(connecting.waiting, "wait", wait)
    return shown


def finish(result):
    def behave(futures):
        futures[0].set_result(result)
        return True

    return behave


def test_says_it_is_connecting_and_offers_cancel(future, monkeypatch):
    shown = wait_by(monkeypatch, finish(True))

    connecting.connect(_Host())

    assert shown["text"] == "Connecting to 172.17.0.1..."
    assert shown["buttonText"] == "Cancel"
    assert shown["timeoutSeconds"] == connecting.CONNECT_TIMEOUT_SECONDS


def test_reports_the_connection_once_the_monitor_answers(future, monkeypatch):
    wait_by(monkeypatch, finish(True))

    assert connecting.connect(_Host()) is True


def test_raises_what_the_connection_attempt_raised(future, monkeypatch):
    # The login dialog tells a wrong password from an unreachable server by
    # the exception, so it has to arrive unchanged.
    failure = errors.AuthException(ValueError("rejected"), "172.17.0.1")

    def behave(futures):
        futures[0].set_exception(failure)
        return True

    wait_by(monkeypatch, behave)

    with pytest.raises(errors.AuthException) as raised:
        connecting.connect(_Host())

    assert raised.value is failure


def test_cancel_drops_an_attempt_the_monitor_has_not_started(future, monkeypatch):
    wait_by(monkeypatch, lambda futures: False)

    assert connecting.connect(_Host()) is None
    assert future.cancelled()


def test_cancel_stops_waiting_on_an_attempt_already_running(future, monkeypatch):
    # The monitor finishes it in the background and caches its client for
    # next time; nobody waits on it any more.
    future.set_running_or_notify_cancel()
    wait_by(monkeypatch, lambda futures: False)

    assert connecting.connect(_Host()) is None
    assert not future.cancelled()


def test_gives_up_when_the_monitor_does_not_answer(future, monkeypatch):
    def behave(futures):
        raise TimeoutError("still waiting")

    wait_by(monkeypatch, behave)

    with pytest.raises(errors.TimeoutException):
        connecting.connect(_Host())

    assert future.cancelled()
