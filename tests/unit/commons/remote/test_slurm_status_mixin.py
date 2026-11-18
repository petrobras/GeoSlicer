import time
import types

from unittest.mock import MagicMock

import pytest

from commons.remote import errors
from commons.remote.constants import (
    DISCONNECT_BACKOFF_MAX_SECONDS,
    JOB_EVENT_PROGRESS,
    JOB_POLL_INTERVAL_SECONDS,
    JOB_STATE_CANCELLED,
    JOB_STATE_COMPLETED,
    JOB_STATE_FAILED,
    JOB_STATE_IDLE,
    JOB_STATE_NOTCONNECTED,
    JOB_STATE_PENDING,
    JOB_STATE_RUNNING,
)
from commons.remote.utils import SlurmJobStatusMixin

TIMEOUT_SECONDS = 600
UID = "job-uid"


class _Handler(SlurmJobStatusMixin):
    def __init__(self):
        super().__init__(timeout_seconds=TIMEOUT_SECONDS)
        self.slurm_job_ids = ["1234"]
        self.post_status_calls = []
        self.post_status_error = None

    def _post_status_update(self, job_manager, uid, client, jobstatus):
        if self.post_status_error is not None:
            raise self.post_status_error
        self.post_status_calls.append(jobstatus)


@pytest.fixture
def job_manager():
    manager = MagicMock()
    job = types.SimpleNamespace(host=MagicMock(), status=JOB_STATE_RUNNING)
    job.host.name = "cluster"
    manager.jobs = {UID: job}
    return manager


@pytest.fixture
def handler():
    return _Handler()


def test_progress_with_no_client_routes_to_disconnected(handler, job_manager):
    handler._sacct_failure_start_time = time.time()

    handler.progress(job_manager, UID, client=None)

    job = job_manager.jobs[UID]
    job_manager.connections.drop_client.assert_called_once_with(job.host, stale_client=None)

    args, kwargs = job_manager.set_state.call_args
    assert args[0] == UID
    assert args[1] == JOB_STATE_NOTCONNECTED
    assert "end_time" not in kwargs
    assert "progress" not in kwargs and len(args) == 2

    job_manager.schedule.assert_called_once_with(UID, JOB_EVENT_PROGRESS, delay=JOB_POLL_INTERVAL_SECONDS)
    assert handler._disconnect_attempts == 1
    assert handler._sacct_failure_start_time is None


def test_disconnected_is_dispatchable_via_action_map_convention(handler, job_manager):
    """Handlers wire DISCONNECTED into their __action_map, which dispatches as
    self.__action_map[action](caller, uid, client) — positional, no error kwarg."""
    client = object()

    handler.disconnected(job_manager, UID, client)

    job = job_manager.jobs[UID]
    job_manager.connections.drop_client.assert_called_once_with(job.host, stale_client=client)

    args, kwargs = job_manager.set_state.call_args
    assert args[1] == JOB_STATE_NOTCONNECTED
    job_manager.schedule.assert_called_once_with(UID, JOB_EVENT_PROGRESS, delay=JOB_POLL_INTERVAL_SECONDS)


def test_disconnected_with_removed_job_is_a_noop(handler, job_manager):
    job_manager.jobs = {}

    handler.disconnected(job_manager, UID, client=None)

    job_manager.connections.drop_client.assert_not_called()
    job_manager.set_state.assert_not_called()
    job_manager.schedule.assert_not_called()


def test_backoff_doubles_and_caps_at_the_configured_maximum(handler, job_manager):
    attempts = 15
    for _ in range(attempts):
        handler.disconnected(job_manager, UID)

    delays = [call.kwargs["delay"] for call in job_manager.schedule.call_args_list]

    expected = [min(JOB_POLL_INTERVAL_SECONDS * 2**i, DISCONNECT_BACKOFF_MAX_SECONDS) for i in range(attempts)]
    assert delays == expected
    assert delays[-1] == DISCONNECT_BACKOFF_MAX_SECONDS
    assert all(delay <= DISCONNECT_BACKOFF_MAX_SECONDS for delay in delays)


def test_successful_poll_resets_backoff_counters(handler, job_manager, monkeypatch):
    jobstatus = [{"state": "RUNNING"}]
    monkeypatch.setattr("commons.remote.utils.sacct", lambda client, jobs: jobstatus)
    handler._disconnect_attempts = 3
    handler._sacct_failure_start_time = time.time()

    handler.progress(job_manager, UID, client=object())

    assert handler.post_status_calls == [jobstatus]
    assert handler._disconnect_attempts == 0
    assert handler._sacct_failure_start_time is None


def test_runtime_error_keeps_sacct_retry_path_and_resets_disconnect_attempts(handler, job_manager, monkeypatch):
    def failing_sacct(client, jobs):
        raise RuntimeError("sacct failed")

    monkeypatch.setattr("commons.remote.utils.sacct", failing_sacct)
    handler._disconnect_attempts = 3

    handler.progress(job_manager, UID, client=object())

    assert handler._disconnect_attempts == 0
    job_manager.connections.drop_client.assert_not_called()

    args, kwargs = job_manager.set_state.call_args
    assert args[1] == JOB_STATE_PENDING
    assert "end_time" not in kwargs

    job_manager.schedule.assert_called_once_with(UID, JOB_EVENT_PROGRESS)


def test_runtime_error_after_timeout_goes_idle_without_reschedule(handler, job_manager, monkeypatch):
    def failing_sacct(client, jobs):
        raise RuntimeError("sacct failed")

    monkeypatch.setattr("commons.remote.utils.sacct", failing_sacct)
    handler._sacct_failure_start_time = time.time() - TIMEOUT_SECONDS - 1

    handler.progress(job_manager, UID, client=object())

    # IDLE, not FAILED: the remote job may still be running, so the state stays resumable via Reconnect.
    args, kwargs = job_manager.set_state.call_args
    assert args[1] == JOB_STATE_IDLE
    assert "end_time" not in kwargs
    job_manager.schedule.assert_not_called()


def test_channel_error_from_sacct_routes_to_disconnected(handler, job_manager, monkeypatch):
    error = errors.BadScriptPath(Exception("boom"), "cluster")

    def failing_sacct(client, jobs):
        raise error

    monkeypatch.setattr("commons.remote.utils.sacct", failing_sacct)
    handler._sacct_failure_start_time = time.time()
    client = object()

    handler.progress(job_manager, UID, client=client)

    job = job_manager.jobs[UID]
    job_manager.connections.drop_client.assert_called_once_with(job.host, stale_client=client)

    args, kwargs = job_manager.set_state.call_args
    assert args[1] == JOB_STATE_NOTCONNECTED
    assert kwargs["traceback"] == {"[WARNING] Connection lost": repr(error)}

    job_manager.schedule.assert_called_once_with(UID, JOB_EVENT_PROGRESS, delay=JOB_POLL_INTERVAL_SECONDS)
    assert handler._disconnect_attempts == 1
    assert handler._sacct_failure_start_time is None


def test_channel_error_from_post_status_update_routes_to_disconnected(handler, job_manager, monkeypatch):
    monkeypatch.setattr("commons.remote.utils.sacct", lambda client, jobs: [{"state": "RUNNING"}])
    handler.post_status_error = errors.SSHException(Exception("gone"), "cluster")

    handler.progress(job_manager, UID, client=object())

    args, kwargs = job_manager.set_state.call_args
    assert args[1] == JOB_STATE_NOTCONNECTED
    assert handler._disconnect_attempts == 1
    job_manager.schedule.assert_called_once_with(UID, JOB_EVENT_PROGRESS, delay=JOB_POLL_INTERVAL_SECONDS)


@pytest.mark.parametrize("status", [JOB_STATE_COMPLETED, JOB_STATE_FAILED, JOB_STATE_CANCELLED])
def test_disconnected_leaves_a_finished_job_alone(handler, job_manager, status):
    """A finished job has nothing left to poll.

    Rewriting it to NOT CONNECTED both lost its outcome and moved it into a
    state the monitor refuses to cancel, which is how entries ended up
    impossible to remove from the list.
    """
    job = job_manager.jobs[UID]
    job.status = status

    handler.disconnected(job_manager, UID, client=None)

    job_manager.connections.drop_client.assert_called_once_with(job.host, stale_client=None)
    job_manager.set_state.assert_not_called()
    job_manager.schedule.assert_not_called()
    assert handler._disconnect_attempts == 0


def test_backoff_cap_is_short_enough_to_recover_within_minutes():
    """The cap is what decides how long a job keeps showing NOT CONNECTED
    after the host is reachable again."""
    assert DISCONNECT_BACKOFF_MAX_SECONDS <= 600


def test_reconnecting_resets_the_backoff_before_any_slurm_call(handler, job_manager, monkeypatch):
    """Holding a client means the host answered: later slurm failures must not
    keep compounding the reconnection delay."""
    monkeypatch.setattr("commons.remote.utils.sacct", lambda client, jobs: [{"state": "RUNNING"}])
    handler.post_status_error = errors.SSHException(Exception("gone"), "cluster")
    handler._disconnect_attempts = 9

    handler.progress(job_manager, UID, client=object())

    # Backoff restarts from the first step instead of the parked 9th one
    job_manager.schedule.assert_called_once_with(UID, JOB_EVENT_PROGRESS, delay=JOB_POLL_INTERVAL_SECONDS)
