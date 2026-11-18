from collections import OrderedDict
from queue import PriorityQueue
from unittest.mock import MagicMock

import pytest

from commons.remote.connections import JobExecutor
from commons.remote.constants import (
    JOB_STATE_CANCELLED,
    JOB_STATE_COMPLETED,
    JOB_STATE_DONE,
    JOB_STATE_FAILED,
    JOB_STATE_IDLE,
    JOB_STATE_NOTCONNECTED,
    JOB_STATE_PENDING,
    JOB_STATE_RUNNING,
)
from commons.remote.jobs import JobManager

UID = "job-uid"


@pytest.fixture
def manager(monkeypatch, tmp_path):
    monkeypatch.setattr(JobManager, "jobs", OrderedDict())
    monkeypatch.setattr(JobManager, "agenda", PriorityQueue())
    monkeypatch.setattr(JobManager, "observers", [])
    monkeypatch.setattr(JobManager, "connections", MagicMock())
    monkeypatch.setattr(JobManager, "compilers", {})
    monkeypatch.setattr(JobManager, "storage", tmp_path / "jobs.json")
    return JobManager


def add_job(manager, uid, status):
    job = JobExecutor(uid, MagicMock(), MagicMock())
    job.status = status
    manager.jobs[uid] = job
    return job


def scheduled_uids(manager):
    uids = []
    while not manager.agenda.empty():
        uids.append(manager.agenda.get_nowait()[1])
    return uids


@pytest.mark.parametrize("status", [JOB_STATE_COMPLETED, JOB_STATE_FAILED, JOB_STATE_CANCELLED, JOB_STATE_DONE])
def test_startup_resume_leaves_finished_jobs_alone(manager, status):
    """resume_all runs before any login dialog, so the connection it triggers
    has no credential yet. Resuming a finished job only earned it a spurious
    NOT CONNECTED — a state the monitor then refused to cancel."""
    job = add_job(manager, UID, status)

    manager.resume_all()

    assert job.status == status
    assert scheduled_uids(manager) == []


@pytest.mark.parametrize("status", [JOB_STATE_RUNNING, JOB_STATE_PENDING, JOB_STATE_NOTCONNECTED])
def test_startup_resume_still_restarts_unfinished_jobs(manager, status):
    add_job(manager, UID, status)

    manager.resume_all()

    assert scheduled_uids(manager) == [UID]


def test_startup_resume_skips_only_the_finished_ones(manager):
    add_job(manager, "done", JOB_STATE_COMPLETED)
    add_job(manager, "live", JOB_STATE_RUNNING)

    manager.resume_all()

    assert scheduled_uids(manager) == ["live"]


def test_remove_notifies_observers_and_drops_the_job(manager):
    job = add_job(manager, UID, JOB_STATE_FAILED)
    seen = []
    manager.observers.append(lambda job_, event: seen.append((job_, event)))

    manager.remove(UID)

    assert UID not in manager.jobs
    assert seen == [(job, "JOB_DELETED")]


def test_remove_of_an_unknown_job_is_a_noop(manager):
    seen = []
    manager.observers.append(lambda job_, event: seen.append(event))

    manager.remove("never-existed")

    assert seen == []


def test_a_failing_observer_does_not_leave_the_job_half_removed(manager):
    """The monitor's own observer can raise while its widget is being torn
    down; the job must still be gone from the registry."""
    add_job(manager, UID, JOB_STATE_FAILED)

    def broken(job_, event):
        raise RuntimeError("widget already deleted")

    seen = []
    manager.observers.append(broken)
    manager.observers.append(lambda job_, event: seen.append(event))

    manager.remove(UID)

    assert UID not in manager.jobs
    assert seen == ["JOB_DELETED"]


class TestMount:
    """A compiler normally mutates the job in place, but it is allowed to build
    a replacement. When it does, the registry has to follow: otherwise cls.jobs
    keeps the unmounted original, whose task_handler is None, and every event is
    silently dropped by JobExecutor.process."""

    def _job(self, manager, uid="job-uid", job_type="t", status=JOB_STATE_NOTCONNECTED, track=True):
        job = JobExecutor(uid, MagicMock(), MagicMock())
        job.job_type = job_type
        job.status = status
        if track:
            manager.jobs[uid] = job
        return job

    def test_a_compiler_that_mutates_in_place(self, manager):
        # What all seven shipped loaders do.
        job = self._job(manager)
        manager.register("t", lambda j: (setattr(j, "task_handler", "H"), j)[1])

        assert manager.resume(job) is True
        assert manager.jobs[UID] is job
        assert job.task_handler == "H"

    def test_a_compiler_that_returns_a_replacement(self, manager):
        job = self._job(manager)

        def replacing(original):
            fresh = JobExecutor(original.uid, "NEW_HANDLER", original.host)
            fresh.job_type = original.job_type
            fresh.status = original.status
            return fresh

        manager.register("t", replacing)
        assert manager.resume(job) is True

        replacement = manager.jobs[UID]
        assert replacement is not job
        assert replacement.task_handler == "NEW_HANDLER"
        # resume must go on to work with the replacement, not the object it was
        # handed: the state change and the epoch bump have to land on the one
        # the registry now holds.
        assert replacement.status == JOB_STATE_PENDING
        assert replacement.progress_epoch == 1
        assert job.progress_epoch == 0

    def test_a_compiler_that_forgets_to_return(self, manager):
        job = self._job(manager)
        manager.register("t", lambda j: setattr(j, "task_handler", "H"))

        assert manager.resume(job) is True
        # Never let None into the registry.
        assert manager.jobs[UID] is job

    def test_a_compiler_that_raises(self, manager):
        job = self._job(manager)

        def boom(_):
            raise RuntimeError("bad details")

        manager.register("t", boom)
        assert manager.resume(job) is False
        assert job.status == JOB_STATE_IDLE

    def test_no_compiler_for_the_job_type(self, manager):
        # What a job restored from jobs.json looks like: fromJson builds it with
        # task_handler=None, and nothing fills it in when no loader is
        # registered for its type. Scheduling it would burn a connection and
        # leave it in PENDING for good, since process() drops events for a null
        # handler, so resume has to refuse it instead.
        job = self._job(manager, job_type="unregistered")
        job.task_handler = None

        assert manager.resume(job) is False
        assert job.status == JOB_STATE_IDLE
        assert manager.jobs[UID] is job
        assert scheduled_uids(manager) == []

    def test_an_unmanaged_job_raises(self, manager):
        # Mounting exists to leave cls.jobs holding a mounted object, so a job
        # that is not in there cannot be mounted meaningfully. Failing loudly
        # beats absorbing it: the caller has a bug.
        job = self._job(manager, track=False)
        ran = []
        manager.register("t", lambda j: ran.append(j.uid) or j)

        with pytest.raises(KeyError, match="not managed"):
            manager.mount(job)

        assert ran == [], "the compiler must not run for a job that cannot be mounted"
        assert UID not in manager.jobs


class TestResumeRefusesUnmanagedJobs:
    """The monitor's rows lag removal by up to a second, so a job can be
    cancelled while its row is still clickable. Resuming the resulting stale
    reference used to run the compiler, bump an orphan's epoch, queue an event
    the monitor threw away, and still return True -- so the caller reported
    nothing to the user.

    resume() has no guard of its own: mount() raises, and resume turns that
    into the False its callers already know how to report."""

    def _orphan(self, job_type="t"):
        job = JobExecutor(UID, MagicMock(), MagicMock())
        job.job_type = job_type
        job.status = JOB_STATE_NOTCONNECTED
        return job

    def test_returns_false(self, manager):
        assert manager.resume(self._orphan()) is False

    def test_does_not_run_the_compiler(self, manager):
        # microtom_job_loader reaches into the scene via slicer.util.getNode;
        # it has no business running for a job that no longer exists.
        ran = []
        manager.register("t", lambda j: ran.append(j.uid) or j)

        manager.resume(self._orphan())
        assert ran == []

    def test_queues_nothing(self, manager):
        manager.resume(self._orphan())
        assert manager.agenda.empty()

    def test_leaves_the_stale_object_alone(self, manager):
        job = self._orphan()
        manager.resume(job)

        assert job.progress_epoch == 0
        assert job.status == JOB_STATE_NOTCONNECTED

    def test_does_not_register_it(self, manager):
        manager.resume(self._orphan())
        assert UID not in manager.jobs

    def test_a_managed_job_is_still_resumed(self, manager):
        job = self._orphan()
        manager.jobs[UID] = job

        assert manager.resume(job) is True
        assert job.status == JOB_STATE_PENDING

    @pytest.mark.parametrize("value", [None, "not-a-job", 42])
    def test_rubbish_is_refused_falsily(self, manager, value):
        # RemoteServiceLogic.resume() only warns the user when this is falsy.
        assert not manager.resume(value)


class TestStartupCredentials:
    """At startup nothing can ask for a password: resume runs on the monitor
    thread. Jobs whose host has no stored credential are reported instead of
    being pushed into a connection that can only fail."""

    class _Host:
        def __init__(self, name, password=None):
            self.name = name
            self._password = password

        def get_key(self):
            return f"ssh://{self.name}"

        def get_password(self):
            return self._password

    def _job(self, manager, uid, host, status):
        job = JobExecutor(uid, MagicMock(), host)
        job.status = status
        manager.jobs[uid] = job
        return job

    def test_a_host_with_a_credential_is_resumed(self, manager):
        host = self._Host("atena02", password="stored")
        self._job(manager, "a", host, JOB_STATE_RUNNING)

        assert manager.resume_all() == []
        assert not manager.agenda.empty()

    def test_a_host_without_one_is_reported_not_attempted(self, manager):
        host = self._Host("atena03")
        job = self._job(manager, "a", host, JOB_STATE_RUNNING)

        pending = manager.resume_all()

        assert [h.name for h in pending] == ["atena03"]
        assert manager.agenda.empty(), "a doomed connection must not be scheduled"
        assert job.status == JOB_STATE_NOTCONNECTED
        assert "Sign in to atena03" in (job.message or "")

    def test_each_host_is_reported_once(self, manager):
        host = self._Host("atena03")
        for uid in ("a", "b", "c"):
            self._job(manager, uid, host, JOB_STATE_RUNNING)

        assert len(manager.resume_all()) == 1

    def test_finished_jobs_never_trigger_a_prompt(self, manager):
        # Resuming them would flicker a progress stage on work that is done.
        host = self._Host("atena03")
        for uid, status in (("a", JOB_STATE_COMPLETED), ("b", JOB_STATE_FAILED)):
            self._job(manager, uid, host, status)

        assert manager.resume_all() == []
        assert manager.agenda.empty()

    def test_only_waiting_jobs_are_revived_by_a_sign_in(self, manager):
        host = self._Host("atena03")
        done = self._job(manager, "done", host, JOB_STATE_COMPLETED)
        self._job(manager, "idle", host, JOB_STATE_IDLE)
        self._job(manager, "lost", host, JOB_STATE_NOTCONNECTED)

        waiting = manager.jobs_awaiting_connection(host)

        assert sorted(job.uid for job in waiting) == ["idle", "lost"]
        assert done not in waiting

    def test_resume_host_restarts_only_those(self, manager):
        host = self._Host("atena03", password="stored")
        done = self._job(manager, "done", host, JOB_STATE_COMPLETED)
        self._job(manager, "idle", host, JOB_STATE_IDLE)

        assert manager.resume_host(host) == 1
        assert done.status == JOB_STATE_COMPLETED

    def test_other_hosts_are_left_alone(self, manager):
        wanted = self._Host("atena03", password="stored")
        other = self._Host("atena04", password="stored")
        self._job(manager, "mine", wanted, JOB_STATE_NOTCONNECTED)
        elsewhere = self._job(manager, "theirs", other, JOB_STATE_NOTCONNECTED)

        assert manager.resume_host(wanted) == 1
        assert elsewhere.status == JOB_STATE_NOTCONNECTED

    def test_a_host_that_cannot_be_read_counts_as_needing_a_sign_in(self, manager):
        class Broken(self._Host):
            def get_password(self):
                raise RuntimeError("keyring unavailable")

        self._job(manager, "a", Broken("atena05"), JOB_STATE_RUNNING)

        assert len(manager.resume_all()) == 1
        assert manager.agenda.empty()
