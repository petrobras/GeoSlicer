"""How the dispatcher is told to run LBPM on a cluster, and what it falls back to."""

from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from commons.lbpm.config import WaterflowConfig
from commons.lbpm.scheduler import LBPMJobSpec, SlurmScheduler
from commons.remote.backends import BACKEND_REMOTE
from commons.remote.hosts.ssh.ssh import SshHost
from commons.remote.jobs import JobManager
from commons.slicer import module_utils
from commons.remote.paths import current_platform
from commons.slicer.lbpm import (
    CLUSTER_DEFAULTS,
    REMOTE_FIELDS_LBPM,
    SETTING_REMOTE_ROOT,
    Backend,
    LBPMDispatcher,
    NoBackendAvailable,
    StagingUnavailable,
    open_run,
)
from commons.slicer.widget.execution.options import LOCAL_FIELDS, REMOTE_FIELDS


def test_a_cluster_is_asked_for_the_image_it_runs_lbpm_from():
    keys = [item.key for item in REMOTE_FIELDS_LBPM]

    assert keys[: len(REMOTE_FIELDS)] == [item.key for item in REMOTE_FIELDS], "the common settings come first"
    assert {"container", "binds"} <= set(keys)


def test_the_reference_cluster_is_what_an_untouched_installation_runs_on():
    defaults = {item.key: item.default for item in REMOTE_FIELDS_LBPM}
    assert {key: defaults[key] for key in CLUSTER_DEFAULTS} == CLUSTER_DEFAULTS


def test_the_cluster_defaults_leave_this_computer_alone():
    """Loading a cluster's MPI module on a desktop would break every local run."""
    assert all(item.default is None for item in LOCAL_FIELDS if item.key in CLUSTER_DEFAULTS)
    assert all(item.default is None for item in REMOTE_FIELDS if item.key in ("partition", "account", "modules"))


def test_the_image_is_a_path_on_the_cluster_whatever_this_computer_is():
    binary = LBPMDispatcher._remote_binary(CLUSTER_DEFAULTS["container"], CLUSTER_DEFAULTS["binds"])

    assert isinstance(binary.container, PurePosixPath)
    assert binary.container.as_posix() == CLUSTER_DEFAULTS["container"]
    assert binary.binds == tuple(CLUSTER_DEFAULTS["binds"])

    script = SlurmScheduler(binary).script(LBPMJobSpec(case_dir="/nethome/drp/lbpm/uid", ranks=8, gpu=True))
    assert f"singularity exec --nv -B {CLUSTER_DEFAULTS['binds'][0]} -B .:/sim" in script


def test_without_an_image_the_cluster_runs_its_module_build():
    binary = LBPMDispatcher._remote_binary(None, None)
    assert binary.container is None and binary.binds == ()


@pytest.fixture
def cluster(monkeypatch, tmp_path):
    """A cluster account whose share this computer reaches under ``tmp_path/share``, with no staging setting."""
    import slicer

    monkeypatch.delenv("GEOSLICER_MODE", raising=False)
    settings = {}
    monkeypatch.setattr(
        slicer.app.userSettings.return_value, "value", lambda key, default=None: settings.get(key, default)
    )

    share = tmp_path / "share"
    host = SshHost(
        username="user",
        name="atena",
        address="atena.example",
        storage={"cluster_root": "/nethome", "local_root": {current_platform(): share.as_posix()}},
    )
    jobs = share / "drp" / "servicos" / "LTRACE" / "GEOSLICER" / "jobs"
    jobs.mkdir(parents=True)

    case = tmp_path / "case" / "sim001"
    case.mkdir(parents=True)
    (case / "waterflow.db").write_text("Domain {}\n", encoding="utf-8")

    return SimpleNamespace(host=host, share=share, jobs=jobs, case=case, settings=settings)


def test_staging_says_where_the_cluster_runs_and_where_its_output_is_read(cluster):
    """Both sides are the account's jobs folder: the cluster was told to run in /nethome/drp/lbpm, which it
    may not write to, while the case had been copied under the jobs folder."""
    remote, local = LBPMDispatcher._stage_remote_case(cluster.case, cluster.host, "uid-1")

    assert remote == "/nethome/drp/servicos/LTRACE/GEOSLICER/jobs/lbpm/uid-1"
    assert local == cluster.jobs / "lbpm" / "uid-1"
    assert (local / "waterflow.db").is_file(), "the run's inputs were not copied to the share"


def test_a_staging_folder_is_read_as_the_cluster_sees_it(cluster):
    cluster.settings[SETTING_REMOTE_ROOT] = "/nethome/drp/scratch"
    (cluster.share / "drp" / "scratch").mkdir(parents=True)

    remote, local = LBPMDispatcher._stage_remote_case(cluster.case, cluster.host, "uid-1")

    assert remote == "/nethome/drp/scratch/lbpm/uid-1"
    assert local == cluster.share / "drp" / "scratch" / "lbpm" / "uid-1"


def test_a_staging_folder_written_as_this_computer_reaches_it_names_the_same_folder(cluster):
    scratch = cluster.share / "drp" / "scratch"
    scratch.mkdir(parents=True)
    cluster.settings[SETTING_REMOTE_ROOT] = scratch.as_posix()

    remote, local = LBPMDispatcher._stage_remote_case(cluster.case, cluster.host, "uid-1")

    assert remote == "/nethome/drp/scratch/lbpm/uid-1"
    assert local == scratch / "lbpm" / "uid-1"


def test_an_unreachable_share_is_reported_before_anything_is_copied(cluster, tmp_path):
    cluster.host.storage["local_root"][current_platform()] = (tmp_path / "not-mounted").as_posix()

    with pytest.raises(StagingUnavailable, match="/nethome/drp/servicos/LTRACE/GEOSLICER/jobs"):
        LBPMDispatcher._stage_remote_case(cluster.case, cluster.host, "uid-1")

    assert not (tmp_path / "not-mounted").exists(), "a folder no cluster reads was created on this computer"


def _submitting_to(cluster, monkeypatch, outcome):
    """Make ``cluster`` the backend a submission resolves to, with a case that can run, and stand in for the
    remote service: ``outcome`` receives what the job was started with and returns what ``run`` would."""
    import slicer

    config = WaterflowConfig.default()
    config.set("Domain", "Filename", "rock.raw")
    config.write(cluster.case / "waterflow.db")

    backend = Backend(kind=BACKEND_REMOTE, name=cluster.host.name, available=True, host=cluster.host)
    monkeypatch.setattr(LBPMDispatcher, "resolve_backend", lambda *args, **kwargs: backend)

    calls = []

    def run(handler, **kwargs):
        # The folders on the share at the moment the job would have started.
        staging = cluster.jobs / "lbpm"
        staged = sorted(path.name for path in staging.iterdir()) if staging.is_dir() else []
        calls.append(dict(kwargs, staged=staged, handler=handler))
        return outcome(kwargs)

    monkeypatch.setattr(slicer.modules, "RemoteServiceInstance", SimpleNamespace(cli=SimpleNamespace(run=run)))
    return calls


def test_a_cluster_job_runs_in_the_folder_named_after_it(cluster, monkeypatch):
    """The id Job Monitor shows is the name of the folder on the share."""
    calls = _submitting_to(cluster, monkeypatch, outcome=lambda kwargs: kwargs["uid"])

    submission = LBPMDispatcher.submit(cluster.case, backend=BACKEND_REMOTE)

    assert [call["uid"] for call in calls] == [submission.uid], "the job was started under another uid"
    assert calls[0]["staged"] == [submission.uid], "the job's inputs were staged under another name"
    assert submission.case_dir == f"/nethome/drp/servicos/LTRACE/GEOSLICER/jobs/lbpm/{submission.uid}"
    assert Path(submission.local_dir) == cluster.jobs / "lbpm" / submission.uid


def _connection_failed(kwargs):
    raise RuntimeError("connection failed")


@pytest.mark.parametrize(
    "outcome, error",
    [(lambda kwargs: None, NoBackendAvailable), (_connection_failed, RuntimeError)],
    ids=["cancelled", "failed"],
)
def test_a_cluster_job_that_never_starts_leaves_nothing_on_the_share(cluster, monkeypatch, outcome, error):
    calls = _submitting_to(cluster, monkeypatch, outcome)

    with pytest.raises(error):
        LBPMDispatcher.submit(cluster.case, backend=BACKEND_REMOTE)

    assert calls and calls[0]["staged"], "nothing was staged, so there was nothing to clean up"
    assert not list((cluster.jobs / "lbpm").iterdir()), "the inputs of a job that never started were kept"


def test_cancelling_goes_through_the_job_monitor_request_queue(monkeypatch):
    """A CANCEL put on the agenda by itself is taken for a request id that was never made, and dropped."""
    requested = []
    monkeypatch.setattr(JobManager, "request_cancel", lambda uid: requested.append(uid) or "future")
    monkeypatch.setattr(JobManager, "schedule", lambda *args, **kwargs: pytest.fail("CANCEL was scheduled"))

    assert LBPMDispatcher.cancel("uid-1") == "future"
    assert requested == ["uid-1"]


def test_a_cluster_job_is_opened_from_where_its_run_is_on_this_computer(cluster, monkeypatch):
    calls = _submitting_to(cluster, monkeypatch, outcome=lambda kwargs: kwargs["uid"])

    submission = LBPMDispatcher.submit(cluster.case, backend=BACKEND_REMOTE)

    handler = calls[0]["handler"]
    assert handler.collector is open_run, "the Job Monitor's Open would do nothing"
    assert handler.source_dir == cluster.case.as_posix()
    assert handler.output_dir == submission.local_dir


def test_a_job_given_a_collector_is_opened_with_it(cluster, monkeypatch):
    calls = _submitting_to(cluster, monkeypatch, outcome=lambda kwargs: kwargs["uid"])

    def collector(details):
        return None

    LBPMDispatcher.submit(cluster.case, backend=BACKEND_REMOTE, collector=collector)

    assert calls[0]["handler"].collector is collector


# -- opening a run ------------------------------------------------------------------------------------
RUN_DETAILS = {"uid": "uid-1", "source_dir": "/cases/rock/sim001", "output_dir": "/share/lbpm/uid-1"}


@pytest.fixture
def lbpm_module(monkeypatch):
    """The LBPM module as Slicer holds it, loaded or not, with what selecting and opening it does recorded."""
    import slicer

    widget = MagicMock()
    module = SimpleNamespace(widget=widget, selected=[], loaded=[], info=object())
    modules = SimpleNamespace(
        AppContextInstance=SimpleNamespace(
            modules=SimpleNamespace(availableModules={"PoreScaleModelling": module.info})
        )
    )
    module.modules = modules

    def load(info):
        module.loaded.append(info)
        modules.porescalemodelling = object()

    monkeypatch.setattr(slicer, "modules", modules)
    monkeypatch.setattr(module_utils, "loadModule", load)
    monkeypatch.setattr(slicer.util, "getModuleWidget", lambda name: widget if name == "PoreScaleModelling" else None)
    monkeypatch.setattr(slicer.util, "selectModule", module.selected.append)
    monkeypatch.setattr(slicer.util, "errorDisplay", MagicMock())
    return module


def test_opening_a_run_shows_it_in_the_lbpm_module(lbpm_module):
    lbpm_module.modules.porescalemodelling = object()

    open_run(RUN_DETAILS)

    assert lbpm_module.selected == ["PoreScaleModelling"]
    assert lbpm_module.loaded == [], "a module that is loaded is not loaded again"
    lbpm_module.widget.openRun.assert_called_once_with("/cases/rock/sim001", "/share/lbpm/uid-1", uid="uid-1")


def test_a_run_opens_in_the_lbpm_module_also_where_the_environment_did_not_load_it(lbpm_module):
    open_run(RUN_DETAILS)

    assert lbpm_module.loaded == [lbpm_module.info]
    lbpm_module.widget.openRun.assert_called_once()


def test_a_job_that_does_not_say_where_its_results_are_is_not_opened(lbpm_module):
    import slicer

    open_run({"uid": "uid-1"})

    slicer.util.errorDisplay.assert_called_once()
    assert lbpm_module.selected == [] and not lbpm_module.widget.openRun.called


# -- results tables -----------------------------------------------------------------------------------
class _Table:
    def __init__(self):
        self.attributes, self.name = {}, None

    def SetAttribute(self, key, value):
        self.attributes[key] = value

    def GetAttribute(self, key):
        return self.attributes.get(key)

    def SetName(self, name):
        self.name = name

    def GetName(self):
        return self.name


def test_making_a_runs_tables_again_updates_them(monkeypatch, tmp_path):
    """Opening a run twice, or refreshing a running one, does not leave "timelog 1", "timelog 2"... behind."""
    import pandas as pd
    import slicer

    from commons.slicer import data_utils, helpers, lbpm

    scene, writes = [], []

    def to_table(frame, tableNode=None, replace=False):
        writes.append((tableNode, replace))
        if tableNode is None:
            tableNode = _Table()
            scene.append(tableNode)
        return tableNode

    timelog = pd.DataFrame({"sw": [0.95, 0.9]})
    monkeypatch.setattr(lbpm, "load_results", lambda case_dir: SimpleNamespace(timelog=timelog, subphase=None))
    monkeypatch.setattr(data_utils, "dataFrameToTableNode", to_table)
    monkeypatch.setattr(helpers, "autoDetectColumnType", lambda node: None)
    monkeypatch.setattr(slicer.util, "getNodesByClass", lambda cls: list(scene))
    monkeypatch.setattr(slicer.mrmlScene, "GenerateUniqueName", lambda name: name)

    first = lbpm.build_result_nodes(tmp_path / "sim001", prefix="sim001")["nodes"]["timelog"]
    again = lbpm.build_result_nodes(tmp_path / "sim001", prefix="sim001")["nodes"]["timelog"]
    other = lbpm.build_result_nodes(tmp_path / "sim002", prefix="sim002")["nodes"]["timelog"]

    assert again is first and other is not first
    assert writes == [(None, False), (first, True), (None, False)]
    assert (first.name, other.name) == ("sim001 timelog", "sim002 timelog")
