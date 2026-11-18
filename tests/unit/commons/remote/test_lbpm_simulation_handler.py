"""What Cancel/Delete does to an LBPM job: stop the run, drop the job, delete the copy of its case on the cluster."""

import uuid
from types import SimpleNamespace

import pytest

from commons.lbpm.binary import LBPMBinary
from commons.lbpm.scheduler import LBPMJobSpec, LocalScheduler, SlurmScheduler
from commons.remote.constants import (
    JOB_EVENT_COLLECT,
    JOB_STATE_CANCELLED,
    JOB_STATE_COMPLETED,
    JOB_STATE_NOTCONNECTED,
    JOB_STATE_RUNNING,
)
from commons.remote.handlers.LBPMSimulationHandler import LBPMSimulationHandler
from commons.remote.hosts.ssh.ssh import SshHost
from commons.remote.paths import current_platform

UID = str(uuid.uuid4())
STAGED = f"/nethome/drp/servicos/LTRACE/GEOSLICER/jobs/lbpm/{UID}"
SLURM_ID = "6854163"


class Manager:
    """The part of the job manager a handler talks to, recording what it was told."""

    def __init__(self, job):
        self.jobs = {job.uid: job}
        self.states = []
        self.removed = []
        self.scheduled = []

    def set_state(self, uid, status, progress=None, message=None, traceback=None, details=None, **kwargs):
        self.states.append(status)
        job = self.jobs[uid]
        job.status = status
        if details is not None:
            job.details = {**(job.details or {}), **details}

    def schedule(self, uid, event, delay=None):
        self.scheduled.append(event)

    def persist(self, uid):
        pass

    def remove(self, uid):
        self.removed.append(uid)
        self.jobs.pop(uid, None)


class Client:
    """Runs nothing: records each command, and answers it with the stdout and stderr of the first prefix it
    starts with."""

    def __init__(self, errors=None, outputs=None):
        self.errors = errors or {}
        self.outputs = outputs or {}
        self.commands = []

    def run_command(self, cmd, **kwargs):
        self.commands.append(cmd)
        stdout = next((text for prefix, text in self.outputs.items() if cmd.startswith(prefix)), "")
        stderr = next((text for prefix, text in self.errors.items() if cmd.startswith(prefix)), "")
        return {"stdout": stdout, "stderr": stderr}


@pytest.fixture
def share(tmp_path):
    """The cluster's share as this computer reaches it, holding the run's staged copy of its case."""
    root = tmp_path / "share"
    copy = root / "drp" / "servicos" / "LTRACE" / "GEOSLICER" / "jobs" / "lbpm" / UID
    copy.mkdir(parents=True)
    (copy / "waterflow.db").write_text("Domain {}\n", encoding="utf-8")
    return SimpleNamespace(root=root, copy=copy)


def _clusterJob(share, status=JOB_STATE_RUNNING):
    host = SshHost(
        username="user",
        name="atena",
        address="atena.example",
        storage={"cluster_root": "/nethome", "local_root": {current_platform(): share.root.as_posix()}},
    )
    return Manager(SimpleNamespace(uid=UID, status=status, host=host, details=None))


def _clusterHandler(directory=STAGED, job_id=SLURM_ID):
    handler = LBPMSimulationHandler(spec=LBPMJobSpec(case_dir=directory), scheduler=SlurmScheduler(LBPMBinary()))
    handler.job_id = job_id
    return handler


def test_a_running_cluster_job_is_stopped_dropped_and_its_copy_deleted(share):
    manager, client = _clusterJob(share), Client()

    _clusterHandler().cancel(manager, UID, client)

    assert client.commands == [f"scancel {SLURM_ID}", f"rm -rf {STAGED}"]
    assert manager.removed == [UID]
    assert manager.states == [JOB_STATE_CANCELLED], "the job is marked cancelled before it goes"


@pytest.mark.parametrize(
    "client",
    [None, Client({"scancel": "scancel: error: Kill job error on job id 6854163: Access/permission denied"})],
    ids=["no-connection", "refused"],
)
def test_a_job_that_cannot_be_stopped_stays_listed_with_its_folder(share, client):
    """The entry is what still knows where the folder is: it stays, flagged, to be cancelled again."""
    manager = _clusterJob(share)

    _clusterHandler().cancel(manager, UID, client)

    assert manager.removed == []
    assert manager.states == [JOB_STATE_NOTCONNECTED]
    assert share.copy.is_dir()
    assert client is None or not [command for command in client.commands if command.startswith("rm")]


def test_a_run_that_ended_meanwhile_is_dropped_all_the_same(share):
    manager = _clusterJob(share)
    client = Client({"scancel": "scancel: error: Kill job error on job id 6854163: Invalid job id specified"})

    _clusterHandler().cancel(manager, UID, client)

    assert manager.removed == [UID]
    assert client.commands[-1] == f"rm -rf {STAGED}"


def test_a_finished_job_is_not_stopped_again(share):
    manager, client = _clusterJob(share, status=JOB_STATE_COMPLETED), Client()

    _clusterHandler().cancel(manager, UID, client)

    assert client.commands == [f"rm -rf {STAGED}"]
    assert manager.removed == [UID]


def test_a_job_never_submitted_has_only_its_copy_to_delete(share):
    manager, client = _clusterJob(share), Client()

    _clusterHandler(job_id=None).cancel(manager, UID, client)

    assert client.commands == [f"rm -rf {STAGED}"]
    assert manager.removed == [UID]


def test_a_copy_the_cluster_does_not_delete_is_deleted_through_the_share(share):
    manager = _clusterJob(share)
    client = Client({"rm -rf": f"rm: cannot remove '{STAGED}': Permission denied"})

    _clusterHandler().cancel(manager, UID, client)

    assert manager.removed == [UID]
    assert not share.copy.exists()


def test_a_finished_job_is_deleted_through_the_share_when_the_cluster_is_unreachable(share):
    manager = _clusterJob(share, status=JOB_STATE_COMPLETED)

    _clusterHandler().cancel(manager, UID, None)

    assert manager.removed == [UID]
    assert not share.copy.exists()


@pytest.mark.parametrize(
    "directory",
    [
        "/nethome/drp/cases/rock",
        f"/nethome/drp/elsewhere/{UID}",
        "/nethome/drp/servicos/LTRACE/GEOSLICER/jobs/lbpm/not-a-uid",
    ],
    ids=["a-case", "outside-staging", "not-named-by-a-uid"],
)
def test_only_a_folder_shaped_like_a_staged_copy_is_ever_deleted(share, directory):
    manager, client = _clusterJob(share), Client()

    _clusterHandler(directory=directory).cancel(manager, UID, client)

    assert manager.removed == [UID]
    assert client.commands == [f"scancel {SLURM_ID}"]


def _localRun(tmp_path, status):
    run = tmp_path / "case" / "sim001"
    run.mkdir(parents=True)
    (run / "waterflow.db").write_text("Domain {}\n", encoding="utf-8")

    handler = LBPMSimulationHandler(spec=LBPMJobSpec(case_dir=run.as_posix()), scheduler=LocalScheduler(LBPMBinary()))
    handler.job_id = "25104"
    manager = Manager(SimpleNamespace(uid=UID, status=status, host=SimpleNamespace(name="local"), details=None))
    return run, handler, manager


@pytest.mark.parametrize("stderr", ["", "bash: line 1: kill: (25104) - No such process"], ids=["killed", "gone"])
def test_a_local_run_is_stopped_and_dropped_but_its_folder_is_kept(tmp_path, stderr):
    """It ran in the case folder itself, which is the user's."""
    run, handler, manager = _localRun(tmp_path, JOB_STATE_RUNNING)
    client = Client({"kill": stderr})

    handler.cancel(manager, UID, client)

    assert [command.split()[:3] for command in client.commands] == [["kill", "-TERM", "-25104"]]
    assert manager.removed == [UID]
    assert (run / "waterflow.db").is_file()


def test_a_finished_local_run_is_not_killed_again(tmp_path):
    """Its pid may already belong to another process."""
    run, handler, manager = _localRun(tmp_path, JOB_STATE_COMPLETED)
    client = Client()

    handler.cancel(manager, UID, client)

    assert client.commands == []
    assert manager.removed == [UID]
    assert run.is_dir()


# -- opening ------------------------------------------------------------------------------------------
SOURCE = "/home/user/cases/rock/sim001"


def test_where_the_run_is_on_this_computer_is_kept_with_the_job(share):
    """In the job's details, which outlive a restart: the spec only says where the cluster runs it."""
    manager = _clusterJob(share, status="DEPLOYING")
    handler = LBPMSimulationHandler(
        spec=LBPMJobSpec(case_dir=STAGED),
        scheduler=SlurmScheduler(LBPMBinary()),
        source_dir=SOURCE,
        output_dir=share.copy.as_posix(),
    )

    handler.start(manager, UID, Client(outputs={"cd": f"Submitted batch job {SLURM_ID}"}))

    details = manager.jobs[UID].details
    assert details["job_id"] == SLURM_ID
    assert (details["source_dir"], details["output_dir"]) == (SOURCE, share.copy.as_posix())


def test_opening_a_job_hands_over_the_run_and_its_job(share):
    opened = []
    manager = _clusterJob(share, status=JOB_STATE_COMPLETED)
    manager.jobs[UID].details = {"job_id": SLURM_ID}
    handler = LBPMSimulationHandler(
        spec=LBPMJobSpec(case_dir=STAGED),
        scheduler=SlurmScheduler(LBPMBinary()),
        collector=opened.append,
        source_dir=SOURCE,
        output_dir=share.copy.as_posix(),
    )

    handler.collect(manager, UID, None)

    assert opened == [
        {
            "job_id": SLURM_ID,
            "case_dir": STAGED,
            "source_dir": SOURCE,
            "output_dir": share.copy.as_posix(),
            "uid": UID,
            "status": JOB_STATE_COMPLETED,
        }
    ]


def test_a_cluster_job_recorded_without_its_folders_is_opened_from_its_copy_on_the_share(share):
    opened = []
    manager = _clusterJob(share, status=JOB_STATE_COMPLETED)
    handler = LBPMSimulationHandler(
        spec=LBPMJobSpec(case_dir=STAGED), scheduler=SlurmScheduler(LBPMBinary()), collector=opened.append
    )

    handler.collect(manager, UID, None)

    assert opened[0]["output_dir"] == share.copy.as_posix()
    assert opened[0]["source_dir"] is None, "a cluster run's own folder cannot be told from its spec"


def test_a_local_job_recorded_without_its_folders_is_opened_where_it_ran(tmp_path):
    opened = []
    run, handler, manager = _localRun(tmp_path, JOB_STATE_COMPLETED)
    handler.collector = opened.append

    handler.collect(manager, UID, None)

    assert (opened[0]["source_dir"], opened[0]["output_dir"]) == (run.as_posix(), run.as_posix())


def test_a_job_with_nothing_to_open_it_with_is_left_alone(share):
    _clusterHandler().collect(_clusterJob(share, status=JOB_STATE_COMPLETED), UID, None)


def test_a_finished_run_is_not_collected_by_the_monitor_thread(share):
    """Collecting fills the scene, which only the main thread may do: the Job Monitor's Open does it."""
    manager = _clusterJob(share)
    client = Client(outputs={"sacct": f"{SLURM_ID}|COMPLETED", "echo frames": "frames=3"})

    _clusterHandler().progress(manager, UID, client)

    assert manager.states == [JOB_STATE_COMPLETED]
    assert JOB_EVENT_COLLECT not in manager.scheduled
