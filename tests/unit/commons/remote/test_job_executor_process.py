from unittest.mock import MagicMock

import pytest

from commons.remote import errors
from commons.remote.connections import JobExecutor
from commons.remote.constants import (
    JOB_EVENT_PROGRESS,
    JOB_STATE_CANCELLED,
    JOB_STATE_COMPLETED,
    JOB_STATE_FAILED,
    JOB_STATE_NOTCONNECTED,
)

UID = "job-uid"


@pytest.fixture
def job():
    host = MagicMock()
    host.rsa_key = None
    return JobExecutor(UID, MagicMock(), host)


def test_connected_delivers_client_to_handler(job):
    pool = MagicMock()
    tasker = MagicMock()

    job.process(JOB_EVENT_PROGRESS, tasker, pool)

    job.task_handler.assert_called_once_with(tasker, UID, JOB_EVENT_PROGRESS, client=pool.connect.return_value)


def test_auth_failure_flags_job_and_stops_the_polling_chain(job):
    """Rejected credentials cannot succeed on retry, and connect() already
    dropped the stored password: stop here and wait for a manual Reconnect
    instead of spinning a backoff loop that can never authenticate."""
    pool = MagicMock()
    pool.connect.side_effect = errors.AuthException(ValueError("bad password"), "cluster")
    tasker = MagicMock()

    job.process(JOB_EVENT_PROGRESS, tasker, pool)

    args, kwargs = tasker.set_state.call_args
    assert kwargs["status"] == JOB_STATE_NOTCONNECTED
    assert "[ERROR] Authentication failed" in kwargs["traceback"]

    job.task_handler.assert_not_called()


def test_transient_failure_delivers_event_without_client(job):
    pool = MagicMock()
    pool.connect.side_effect = errors.SSHException(Exception("no route to host"), "cluster")
    tasker = MagicMock()

    job.process(JOB_EVENT_PROGRESS, tasker, pool)

    tasker.set_state.assert_not_called()
    job.task_handler.assert_called_once_with(tasker, UID, JOB_EVENT_PROGRESS, client=None)


def test_host_without_rsa_key_attribute_does_not_crash_auth_branch(job):
    """If a host has no rsa_key field; the auth branch must not AttributeError."""
    del job.host.rsa_key
    job.host.mock_add_spec(["get_key", "server_name", "name"])
    pool = MagicMock()
    pool.connect.side_effect = errors.AuthException(ValueError("nope"), "cluster")
    tasker = MagicMock()

    job.process(JOB_EVENT_PROGRESS, tasker, pool)

    args, kwargs = tasker.set_state.call_args
    assert kwargs["status"] == JOB_STATE_NOTCONNECTED


@pytest.mark.parametrize("status", [JOB_STATE_COMPLETED, JOB_STATE_FAILED, JOB_STATE_CANCELLED])
@pytest.mark.parametrize(
    "failure",
    [
        errors.MissingCredentialsError(ValueError("no password"), "cluster"),
        errors.HostNotFoundError(Exception("dns"), "cluster"),
        errors.AuthException(ValueError("bad password"), "cluster"),
        errors.UserDisconnectedError(RuntimeError("disconnected"), "cluster"),
    ],
)
def test_connection_failure_does_not_rewrite_a_finished_job(job, status, failure):
    """A finished job keeps its outcome when the connection fails.

    Overwriting it with NOT CONNECTED lost the result and moved the job into a
    state the monitor refuses to cancel — the entry could then never be
    removed. Clicking 'Open' on a COMPLETED job while the VPN was down was
    enough to trigger it.
    """
    job.status = status
    pool = MagicMock()
    pool.connect.side_effect = failure
    tasker = MagicMock()

    job.process(JOB_EVENT_PROGRESS, tasker, pool)

    args, kwargs = tasker.set_state.call_args
    assert kwargs["status"] == status
    # The reason is still recorded, so 'Details' explains what went wrong
    assert kwargs["traceback"]


def test_connection_failure_still_flags_an_unfinished_job(job):
    pool = MagicMock()
    pool.connect.side_effect = errors.HostNotFoundError(Exception("dns"), "cluster")
    tasker = MagicMock()

    job.process(JOB_EVENT_PROGRESS, tasker, pool)

    args, kwargs = tasker.set_state.call_args
    assert kwargs["status"] == JOB_STATE_NOTCONNECTED


def test_user_disconnect_parks_the_job_and_stops_the_polling_chain(job):
    """The user disconnected from the host: nothing failed, but the event must
    not reach the handler, or its reconnect backoff would keep polling a host
    the user asked to leave alone. Connecting again resumes the job."""
    pool = MagicMock()
    pool.connect.side_effect = errors.UserDisconnectedError(RuntimeError("disconnected"), "cluster")
    tasker = MagicMock()

    job.process(JOB_EVENT_PROGRESS, tasker, pool)

    job.task_handler.assert_not_called()
    args, kwargs = tasker.set_state.call_args
    assert kwargs["status"] == JOB_STATE_NOTCONNECTED
    assert "Reconnect" in kwargs["traceback"]["[INFO] Disconnected"]
    job.host.delete_password.assert_not_called()
