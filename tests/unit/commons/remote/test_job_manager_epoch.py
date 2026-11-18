from collections import OrderedDict
from queue import PriorityQueue
from unittest.mock import MagicMock

import pytest

from commons.remote.connections import JobExecutor
from commons.remote.constants import (
    JOB_EVENT_PROGRESS,
    JOB_STATE_COMPLETED,
    JOB_STATE_FAILED,
    JOB_STATE_GHOST,
    JOB_STATE_IDLE,
    JOB_STATE_NOTCONNECTED,
    JOB_STATE_PENDING,
    JOB_STATE_RUNNING,
)
from commons.remote.jobs import JobManager

UID = "job-uid"


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr(JobManager, "jobs", OrderedDict())
    monkeypatch.setattr(JobManager, "agenda", PriorityQueue())
    monkeypatch.setattr(JobManager, "observers", [])
    monkeypatch.setattr(JobManager, "connections", MagicMock())
    monkeypatch.setattr(JobManager, "compilers", {})
    monkeypatch.setattr(JobManager, "keep_working", True)
    return JobManager


def make_job(status=JOB_STATE_RUNNING):
    job = JobExecutor(UID, MagicMock(), MagicMock())
    job.status = status
    return job


def drain(manager):
    entries = []
    while not manager.agenda.empty():
        entries.append(manager.agenda.get_nowait())
    return entries


def test_schedule_stamps_current_epoch(manager):
    job = make_job()
    job.progress_epoch = 7
    manager.jobs[UID] = job

    manager.schedule(UID, JOB_EVENT_PROGRESS, delay=0)

    (entry,) = drain(manager)
    due, uid, event, epoch = entry
    assert uid == UID
    assert event == JOB_EVENT_PROGRESS
    assert epoch == 7


def test_schedule_for_unknown_uid_uses_epoch_zero(manager):
    manager.schedule("", "SHUTDOWN")

    (entry,) = drain(manager)
    assert entry[3] == 0


def test_locked_send_turnstile(manager):
    job = make_job()
    manager.jobs[UID] = job

    manager.locked_send(UID, JOB_EVENT_PROGRESS, epoch=999)
    job.task_handler.assert_not_called()
    assert job.progress_epoch == 0

    manager.locked_send(UID, JOB_EVENT_PROGRESS, epoch=0)
    job.task_handler.assert_called_once()
    assert job.progress_epoch == 1


def test_locked_send_delivers_non_progress_regardless_of_epoch(manager):
    job = make_job()
    manager.jobs[UID] = job

    manager.locked_send(UID, "CANCEL", epoch=999)

    job.task_handler.assert_called_once()
    assert job.progress_epoch == 0


@pytest.mark.parametrize(
    "status",
    [JOB_STATE_FAILED, JOB_STATE_COMPLETED, JOB_STATE_IDLE, JOB_STATE_GHOST],
)
def test_locked_send_drops_events_for_inactive_jobs(manager, status):
    """The job went inactive while the event sat in the agenda -- a race, not a
    caller error, so it is dropped rather than reported."""
    job = make_job(status=status)
    manager.jobs[UID] = job

    manager.locked_send(UID, JOB_EVENT_PROGRESS, epoch=job.progress_epoch)

    job.task_handler.assert_not_called()


@pytest.mark.parametrize(
    "status",
    [JOB_STATE_FAILED, JOB_STATE_COMPLETED, JOB_STATE_IDLE, JOB_STATE_GHOST],
)
def test_schedule_refuses_an_inactive_job(manager, status):
    """Nothing has raced yet at schedule time, so this is the caller's mistake
    and is reported instead of silently queued."""
    manager.jobs[UID] = make_job(status=status)

    manager.schedule(UID, JOB_EVENT_PROGRESS, delay=0)

    assert drain(manager) == []


@pytest.mark.parametrize("status", [JOB_STATE_RUNNING, JOB_STATE_PENDING, JOB_STATE_NOTCONNECTED])
def test_schedule_accepts_an_active_job(manager, status):
    # NOT CONNECTED included on purpose: it is retrying under backoff, and
    # refusing it here would stop a disconnected job ever coming back.
    manager.jobs[UID] = make_job(status=status)

    manager.schedule(UID, JOB_EVENT_PROGRESS, delay=0)

    assert len(drain(manager)) == 1


def test_shutdown_is_never_refused(manager):
    # SHUTDOWN carries an empty uid and belongs to the monitor loop, not to a
    # job; a job-state guard must not swallow it or the worker never stops.
    manager.jobs[UID] = make_job(status=JOB_STATE_FAILED)

    manager.schedule("", "SHUTDOWN")

    assert len(drain(manager)) == 1


@pytest.mark.parametrize("status", [JOB_STATE_IDLE, JOB_STATE_GHOST])
def test_resume_reactivates_a_dormant_job_before_scheduling(manager, status):
    """Order matters: left dormant, the job's own resume would be refused by
    the guard in schedule()."""
    job = make_job(status=status)
    manager.jobs[UID] = job

    assert manager.resume(job) is True
    assert job.status == JOB_STATE_PENDING
    assert len(drain(manager)) == 1


@pytest.mark.parametrize("status", [JOB_STATE_COMPLETED, JOB_STATE_FAILED])
def test_resume_refuses_a_finished_job(manager, status):
    # Reconnecting to the host is still useful for a finished job, but that is
    # the caller's business; re-arming a polling chain is not.
    job = make_job(status=status)
    manager.jobs[UID] = job

    assert manager.resume(job) is False
    assert job.status == status
    assert drain(manager) == []


def test_resume_kills_parked_chain(manager):
    job = make_job(status=JOB_STATE_NOTCONNECTED)
    manager.jobs[UID] = job

    # A long backoff retry parked in the agenda with the old epoch
    manager.schedule(UID, JOB_EVENT_PROGRESS, delay=10800)
    assert manager.resume(job) is True
    assert job.status == JOB_STATE_PENDING

    entries = sorted(drain(manager))
    assert len(entries) == 2
    parked, fresh = entries[1], entries[0]  # parked entry is due 3h later
    assert parked[3] == 0 and fresh[3] == 1

    # Parked entry from the superseded chain is dropped at delivery
    manager.locked_send(UID, JOB_EVENT_PROGRESS, epoch=parked[3])
    job.task_handler.assert_not_called()

    # The fresh chain delivers and consumes the epoch
    manager.locked_send(UID, JOB_EVENT_PROGRESS, epoch=fresh[3])
    job.task_handler.assert_called_once()
    assert job.progress_epoch == 2


def test_double_resume_yields_single_live_chain(manager):
    job = make_job(status=JOB_STATE_NOTCONNECTED)
    manager.jobs[UID] = job

    # RemoteServiceLogic.resume triggers resume() twice (resume_host + resume)
    manager.resume(job)
    manager.resume(job)

    entries = sorted(drain(manager))
    assert len(entries) == 2

    for entry in entries:
        manager.locked_send(UID, JOB_EVENT_PROGRESS, epoch=entry[3])

    job.task_handler.assert_called_once()


def test_agenda_entries_are_comparable(manager, monkeypatch):
    monkeypatch.setattr("commons.remote.jobs.time.monotonic", lambda: 1000.0)

    job_a = JobExecutor("uid-a", MagicMock(), MagicMock())
    job_b = JobExecutor("uid-b", MagicMock(), MagicMock())
    manager.jobs["uid-a"] = job_a
    manager.jobs["uid-b"] = job_b

    # Same due time everywhere: ties fall through to uid/event/epoch comparison
    manager.schedule("", "SHUTDOWN", delay=5)
    manager.schedule("uid-a", JOB_EVENT_PROGRESS)
    manager.schedule("uid-a", JOB_EVENT_PROGRESS)  # identical tuple
    manager.schedule("uid-b", JOB_EVENT_PROGRESS)

    entries = drain(manager)
    assert len(entries) == 4
    assert all(isinstance(entry[3], int) for entry in entries)
