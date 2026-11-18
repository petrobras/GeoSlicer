"""CONNECT, CLOSE and CANCEL: the requests the monitor thread serves itself.

The paramiko clients belong to the monitor thread. Other threads -- the UI
thread above all -- only ask it to connect, to close, or to cancel a job,
through the agenda.
"""

import threading
import time
from collections import OrderedDict
from queue import PriorityQueue
from unittest.mock import MagicMock

import pytest

from commons.remote.connections import JobExecutor
from commons.remote.constants import (
    JOB_EVENT_CANCEL,
    JOB_EVENT_CLOSE,
    JOB_EVENT_CONNECT,
    JOB_EVENT_PROGRESS,
    JOB_INACTIVE_STATES,
    JOB_STATE_RUNNING,
)
from commons.remote.jobs import JobManager, start_monitor

HOST_KEY = "ssh://user@cluster:22"


@pytest.fixture
def manager(monkeypatch, tmp_path):
    monkeypatch.setattr(JobManager, "jobs", OrderedDict())
    monkeypatch.setattr(JobManager, "agenda", PriorityQueue())
    monkeypatch.setattr(JobManager, "observers", [])
    monkeypatch.setattr(JobManager, "connections", MagicMock())
    monkeypatch.setattr(JobManager, "storage", tmp_path / "jobs.json")
    monkeypatch.setattr(JobManager, "pending_requests", {})
    monkeypatch.setattr(JobManager, "worker", MagicMock(**{"is_alive.return_value": True}))
    monkeypatch.setattr(JobManager, "keep_working", True)
    return JobManager


def next_entry(manager):
    return manager.agenda.get_nowait()


@pytest.mark.parametrize("worker", [None, MagicMock(**{"is_alive.return_value": False})], ids=["none", "dead"])
def test_connect_is_refused_without_a_monitor(manager, monkeypatch, worker):
    """Nothing would ever serve the request, and a dialog would wait on it."""
    monkeypatch.setattr(JobManager, "worker", worker)

    with pytest.raises(RuntimeError):
        manager.request_connect(MagicMock())

    assert manager.agenda.empty()


def test_connect_is_served_ahead_of_overdue_polls(manager):
    """Someone is watching a dialog; the polls can wait."""
    manager.agenda.put((time.monotonic() - 60, "job-uid", JOB_EVENT_PROGRESS, 0))

    manager.request_connect(MagicMock())

    assert next_entry(manager)[2] == JOB_EVENT_CONNECT


def test_requests_due_together_keep_their_order(manager):
    for _ in range(12):
        manager.request_connect(MagicMock())

    served = [next_entry(manager)[1] for _ in range(12)]

    assert served == list(manager.pending_requests)


@pytest.mark.parametrize("client, connected", [(MagicMock(), True), (False, False)], ids=["client", "falsy"])
def test_connect_resolves_to_whether_the_host_is_connected(manager, client, connected):
    manager.connections.connect.return_value = client
    host = MagicMock()
    future = manager.request_connect(host)

    manager.serve_connect(next_entry(manager)[1])

    assert future.result(timeout=0) is connected
    manager.connections.connect.assert_called_once_with(host, user_initiated=True)


def test_connect_never_hands_out_the_client(manager):
    """The client stays with the monitor thread."""
    client = MagicMock()
    manager.connections.connect.return_value = client
    future = manager.request_connect(MagicMock())

    manager.serve_connect(next_entry(manager)[1])

    assert future.result(timeout=0) is not client


def test_connect_failure_reaches_the_waiter(manager):
    failure = RuntimeError("rejected")
    manager.connections.connect.side_effect = failure
    future = manager.request_connect(MagicMock())

    manager.serve_connect(next_entry(manager)[1])

    assert future.exception(timeout=0) is failure


def test_a_cancelled_connect_is_never_attempted(manager):
    future = manager.request_connect(MagicMock())
    future.cancel()

    manager.serve_connect(next_entry(manager)[1])

    manager.connections.connect.assert_not_called()
    assert manager.pending_requests == {}


def test_close_is_queued_for_the_monitor(manager):
    client = MagicMock()

    manager.request_close(HOST_KEY, client)

    entry = next_entry(manager)
    assert entry[2] == JOB_EVENT_CLOSE
    manager.connections.close_now.assert_not_called()

    manager.serve_close(entry[1])

    manager.connections.close_now.assert_called_once_with(HOST_KEY, client)


def test_an_already_settled_request_is_ignored(manager):
    manager.serve_connect("CONNECT-gone")
    manager.serve_close("CLOSE-gone")

    manager.connections.connect.assert_not_called()
    manager.connections.close_now.assert_not_called()


def test_stopping_settles_every_waiting_request(manager):
    client = MagicMock()
    manager.request_close(HOST_KEY, client)
    future = manager.request_connect(MagicMock())

    manager.settle_requests()

    manager.connections.close_now.assert_called_once_with(HOST_KEY, client)
    with pytest.raises(RuntimeError):
        future.result(timeout=0)
    assert manager.pending_requests == {}


def test_prune_failure_is_contained(manager):
    """A failure here must never starve the job events."""
    manager.connections.prune_closed.side_effect = RuntimeError("boom")

    manager.prune_connections()


def test_prune_without_a_connection_pool(manager, monkeypatch):
    monkeypatch.setattr(JobManager, "connections", None)

    manager.prune_connections()


def add_job(manager, uid, status):
    job = JobExecutor(uid, MagicMock(), MagicMock())
    job.status = status
    manager.jobs[uid] = job
    return job


def test_cancel_is_refused_without_a_monitor(manager, monkeypatch):
    monkeypatch.setattr(JobManager, "worker", None)

    with pytest.raises(RuntimeError):
        manager.request_cancel("job-uid")

    assert manager.agenda.empty()


def test_cancel_is_served_ahead_of_overdue_polls(manager):
    manager.agenda.put((time.monotonic() - 60, "other-uid", JOB_EVENT_PROGRESS, 0))

    manager.request_cancel("job-uid")

    assert next_entry(manager)[2] == JOB_EVENT_CANCEL


@pytest.mark.parametrize("status", sorted(JOB_INACTIVE_STATES | {JOB_STATE_RUNNING}))
def test_cancel_reaches_the_job_whatever_its_state(manager, status):
    """Cancel/Delete is also the remote cleanup of a finished job -- the very
    kind of job schedule() and locked_send() refuse to deliver to."""
    job = add_job(manager, "job-uid", status)
    job.process = MagicMock()
    future = manager.request_cancel("job-uid")

    manager.serve_cancel(next_entry(manager)[1])

    job.process.assert_called_once_with(JOB_EVENT_CANCEL, JobManager, manager.connections)
    assert future.result(timeout=0) is None


def test_cancel_holds_the_read_lock(manager):
    """So it never interleaves with a delivery that takes it too."""
    job = add_job(manager, "job-uid", JOB_STATE_RUNNING)
    held = []
    job.process = MagicMock(side_effect=lambda *args: held.append(JobManager.read_lock.locked()))
    manager.request_cancel("job-uid")

    manager.serve_cancel(next_entry(manager)[1])

    assert held == [True]


def test_cancel_failure_reaches_the_waiter(manager):
    job = add_job(manager, "job-uid", JOB_STATE_RUNNING)
    failure = RuntimeError("scancel refused")
    job.process = MagicMock(side_effect=failure)
    future = manager.request_cancel("job-uid")

    manager.serve_cancel(next_entry(manager)[1])

    assert future.exception(timeout=0) is failure


def test_cancelling_a_job_already_gone_is_not_an_error(manager):
    future = manager.request_cancel("job-uid")

    manager.serve_cancel(next_entry(manager)[1])

    assert future.result(timeout=0) is None


def test_stopping_fails_a_waiting_cancel(manager):
    future = manager.request_cancel("job-uid")

    manager.settle_requests()

    with pytest.raises(RuntimeError):
        future.result(timeout=0)


def wait_until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached in time")
        time.sleep(0.01)


def test_the_monitor_owns_connecting_closing_and_cancelling(manager, monkeypatch):
    """End to end, through a real monitor thread."""
    owner = {}

    def connect(host, user_initiated=False):
        owner["connect"] = threading.current_thread()
        return MagicMock()

    def close_now(host_key, client):
        owner["close"] = threading.current_thread()

    manager.connections.connect.side_effect = connect
    manager.connections.close_now.side_effect = close_now
    job = add_job(manager, "job-uid", JOB_STATE_RUNNING)
    job.process = MagicMock(side_effect=lambda *args: owner.setdefault("cancel", threading.current_thread()))

    worker = start_monitor()
    monkeypatch.setattr(JobManager, "worker", worker)
    try:
        manager.connections.set_closer.assert_called_once_with(JobManager.request_close)

        assert manager.request_connect(MagicMock()).result(timeout=5) is True

        manager.request_close(HOST_KEY, MagicMock())
        wait_until(lambda: "close" in owner)

        assert manager.request_cancel("job-uid").result(timeout=5) is None

        wait_until(lambda: manager.connections.prune_closed.called)
    finally:
        manager.schedule("", "SHUTDOWN")
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert owner == {"connect": worker, "close": worker, "cancel": worker}
    manager.connections.set_closer.assert_called_with(None)
