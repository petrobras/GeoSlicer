"""The uid a cluster job is started under."""

import importlib
import uuid
from pathlib import Path

import pytest

MODULE_DIR = Path(__file__).parents[4] / "src" / "modules" / "RemoteService"


@pytest.fixture
def service(monkeypatch):
    # Slicer puts each module's folder on the path, which is how the module finds its JobLoader package.
    monkeypatch.syspath_prepend(str(MODULE_DIR))
    return importlib.import_module("modules.RemoteService.RemoteService")


def _run(service, monkeypatch, connected=True, **kwargs):
    """Start a job as a module would, with the connection dialog answered ``connected``."""
    managed, scheduled = [], []
    monkeypatch.setattr(service.JobManager, "manage", managed.append)
    monkeypatch.setattr(service.JobManager, "schedule", lambda uid, event: scheduled.append((uid, event)))

    logic = service.RemoteServiceLogic()
    monkeypatch.setattr(logic, "initiateConnectionDialog", lambda **kwargs: ("cluster", connected))

    uid = logic.run(lambda *args, **kwargs: None, name="job", job_type="lbpm", **kwargs)
    return uid, managed, scheduled


def test_a_job_is_started_under_the_uid_it_is_given(service, monkeypatch):
    uid, managed, scheduled = _run(service, monkeypatch, uid="staged-uid")

    assert uid == "staged-uid"
    assert [job.uid for job in managed] == ["staged-uid"]
    assert scheduled == [("staged-uid", "DEPLOY")]


def test_a_job_given_no_uid_gets_a_new_one(service, monkeypatch):
    first, managed, _ = _run(service, monkeypatch)
    second, _, _ = _run(service, monkeypatch)

    assert uuid.UUID(first) and first != second
    assert [job.uid for job in managed] == [first]


def test_a_cancelled_connection_starts_nothing(service, monkeypatch):
    uid, managed, scheduled = _run(service, monkeypatch, connected=None, uid="staged-uid")

    assert uid is None
    assert managed == [] and scheduled == []
