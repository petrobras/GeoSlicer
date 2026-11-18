"""The parts of the Pore Scale Modelling module that decide what the case folder holds."""

import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from commons.lbpm.config import WaterflowConfig
from commons.slicer.lbpm import LBPMDispatcher, NoBackendAvailable
from modules.PoreScaleModelling.PoreScaleModellingLib.config_form import describe_image

MODULE_DIR = Path(__file__).parents[4] / "src" / "modules" / "PoreScaleModelling"


@pytest.fixture
def logic(monkeypatch):
    # Slicer puts each module's folder on the path, which is how the module finds its Lib package.
    monkeypatch.syspath_prepend(str(MODULE_DIR))
    return importlib.import_module("modules.PoreScaleModelling.PoreScaleModelling").PoreScaleModellingLogic


def _node(name="rock", dimensions_xyz=(4, 6, 8), spacing_mm=0.002):
    node = MagicMock()
    node.GetName.return_value = name
    node.GetSpacing.return_value = (spacing_mm, spacing_mm, spacing_mm)
    node.GetImageData.return_value.GetDimensions.return_value = dimensions_xyz
    return node


def test_the_form_names_the_image_a_case_reads():
    config = WaterflowConfig.default()
    assert "None yet" in describe_image(config)

    config.set("Domain", "Filename", "rock_4_6_8_02000nm.raw")
    config.set("Domain", "N", [4, 6, 8])
    assert describe_image(config) == "rock_4_6_8_02000nm.raw (4×6×8 voxels)"


def test_the_image_name_carries_the_node_geometry(logic):
    """The name tells a reused case whether the selected node is the one it already reads."""
    assert logic.inputImageName(_node()) == "rock_4_6_8_02000nm.raw"
    assert logic.inputImageName(_node(dimensions_xyz=(4, 6, 9))) != logic.inputImageName(_node())
    assert logic.inputImageName(_node(spacing_mm=0.0035)) == "rock_4_6_8_03500nm.raw"


def test_a_node_without_image_data_has_no_image_name(logic):
    node = _node()
    node.GetImageData.return_value = None
    assert logic.inputImageName(node) is None


def test_the_file_on_disk_is_what_outside_edits_are_measured_against(logic, tmp_path):
    assert logic.readConfigText(tmp_path) is None

    config = WaterflowConfig.default()
    logic.saveConfig(tmp_path, config)
    assert logic.readConfigText(tmp_path) == config.to_text()

    # An editor that only rewrites the line endings has not changed the configuration.
    path = logic.configPath(tmp_path)
    path.write_bytes(config.to_text().replace("\n", "\r\n").encode("utf-8"))
    assert logic.readConfigText(tmp_path) == config.to_text()

    edited = WaterflowConfig.from_file(path)
    edited.set("Color", "beta", 0.9)
    edited.write(path)
    assert logic.readConfigText(tmp_path) != config.to_text()


def _submission(output="", uid="uid-1", run_dir="/cluster/lbpm/uid-1"):
    submission = MagicMock()
    submission.uid = uid
    submission.backend.name = "atena"
    submission.local_dir = output
    submission.case_dir = run_dir
    return submission


def test_a_run_without_a_record_is_its_own_output(logic, tmp_path):
    assert logic.outputDir(tmp_path / "sim001") == tmp_path / "sim001"


def test_a_cluster_run_is_found_where_it_writes(logic, tmp_path):
    """Its simNNN keeps the inputs; the frames and logs are written into the staged copy on the share."""
    simulation = tmp_path / "case" / "sim001"
    simulation.mkdir(parents=True)
    share = tmp_path / "share" / "lbpm" / "uid-1"

    logic.writeRunRecord(simulation, _submission(output=share.as_posix()))

    assert logic.outputDir(simulation) == share


def test_a_local_run_records_itself_as_its_output(logic, tmp_path):
    logic.writeRunRecord(tmp_path, _submission(output=""))
    assert logic.outputDir(tmp_path) == tmp_path


def test_an_unreadable_record_falls_back_to_the_folder(logic, tmp_path):
    (tmp_path / "geoslicer_run.json").write_text("not json", encoding="utf-8")
    assert logic.outputDir(tmp_path) == tmp_path


def test_the_case_summary_counts_the_frames_where_they_are_written(logic, tmp_path):
    simulation = tmp_path / "sim001"
    simulation.mkdir()
    share = tmp_path / "share"
    for step in (1000, 2000):
        (share / f"vis{step}").mkdir(parents=True)
    logic.writeRunRecord(simulation, _submission(output=share.as_posix()))

    summary = logic.describeCase(tmp_path, WaterflowConfig.default(), created=False, latest=simulation)
    assert "Latest run: sim001 (2 frames)." in summary


def _cancelled(*args, **kwargs):
    raise NoBackendAvailable("The cluster connection was cancelled.")


@pytest.mark.parametrize(
    "image, error",
    [("", NoBackendAvailable), ("missing.raw", FileNotFoundError)],
    ids=["cancelled", "image-missing"],
)
def test_a_run_that_never_starts_leaves_no_simulation_folder(logic, monkeypatch, tmp_path, image, error):
    """Kept, the folder would be shown as the case's latest run, with no output, and take its number."""
    monkeypatch.setattr(LBPMDispatcher, "submit", _cancelled)
    config = WaterflowConfig.default()
    config.set("Domain", "Filename", image)
    # Only its run is needed: constructing the logic would also start its job event timer.
    instance = logic.__new__(logic)

    with pytest.raises(error):
        instance.run(tmp_path, config=config, options=SimpleNamespace(asKwargs=dict))

    assert logic.latestSimulation(tmp_path) is None
    assert logic.nextSimulationDir(tmp_path) == tmp_path / "sim001"


def _following(logic, uid="uid-1"):
    """The logic of a module that has started the job ``uid``, with its signals recorded."""
    instance = logic.__new__(logic)
    instance.uid = uid
    instance._pending = None
    instance.jobStateChanged = MagicMock()
    instance.jobRemoved = MagicMock()
    return instance


def _deliver(instance, status, *events, scheduler="slurm"):
    """Hand ``events`` to the logic as the job manager's thread would, then let the Qt thread drain them."""
    job = SimpleNamespace(uid=instance.uid, status=status, progress=0, message="", details={"scheduler": scheduler})
    for event in events:
        instance._PoreScaleModellingLogic__onJobEvent(job, event)
    instance._PoreScaleModellingLogic__drain()


@pytest.mark.parametrize(
    "status, scheduler, reported",
    [("CANCELLED", "slurm", (True, True)), ("CANCELLED", "local", (True, False)), ("RUNNING", "slurm", (False, True))],
    ids=["cancelled-on-a-cluster", "cancelled-here", "unlinked"],
)
def test_a_job_that_leaves_the_job_list_is_reported_gone(logic, status, scheduler, reported):
    """Cancel/Delete marks the job cancelled before removing it; the Job Monitor's unlink leaves it running.
    Only on a cluster does Cancel/Delete delete what the run wrote."""
    instance = _following(logic)

    _deliver(instance, status, "JOB_MODIFIED", "JOB_DELETED", scheduler=scheduler)

    instance.jobRemoved.emit.assert_called_once_with(*reported)
    instance.jobStateChanged.emit.assert_not_called()
    assert instance.uid is None, "a job that is gone is not followed any more"


def test_a_job_that_changes_is_still_reported_as_it_is(logic):
    instance = _following(logic)

    _deliver(instance, "RUNNING", "JOB_MODIFIED")

    instance.jobStateChanged.emit.assert_called_once_with("RUNNING", 0.0, "")
    instance.jobRemoved.emit.assert_not_called()
    assert instance.uid == "uid-1"


def test_untracking_a_deleted_folder_removes_its_sequences_and_its_monitoring(logic, monkeypatch, tmp_path):
    """Every sequence of the folder goes, whichever variable it shows, and also one restored with the project
    that was never shown, so has no player. The fourd manager only names the folder's own nodes."""
    import slicer

    module = importlib.import_module("modules.PoreScaleModelling.PoreScaleModelling")
    gone = tmp_path / "share" / "lbpm" / "uid-1"
    players = {
        "phase": SimpleNamespace(cache=MagicMock()),
        "pressure": SimpleNamespace(cache=MagicMock()),
    }
    fourd = SimpleNamespace(
        nodes=lambda root: ["phase", "pressure", "restored"] if Path(root) == gone else [],
        player=players.get,
        close=MagicMock(),
    )
    monkeypatch.setattr(module, "get_fourd_manager", lambda: fourd)
    folders = MagicMock()
    monkeypatch.setattr(module.virtual_folder, "manager", lambda: folders)
    monkeypatch.setattr(slicer, "mrmlScene", MagicMock())

    assert logic.untrack(gone) == 3

    assert [call.args[0] for call in fourd.close.call_args_list] == ["phase", "pressure", "restored"]
    assert [call.args[0] for call in slicer.mrmlScene.RemoveNode.call_args_list] == ["phase", "pressure", "restored"]
    players["phase"].cache.delete.assert_called_once()
    players["pressure"].cache.delete.assert_called_once()
    folders.unregister.assert_called_once_with(gone, remove_nodes=True)


def test_tracking_a_folder_reuses_a_sequence_restored_with_the_project(logic, monkeypatch, tmp_path):
    """A restored sequence has no player until it is shown: tracking its folder gives it one."""
    module = importlib.import_module("modules.PoreScaleModelling.PoreScaleModelling")
    player = SimpleNamespace(node="restored", refreshFrames=MagicMock())
    fourd = SimpleNamespace(
        find=lambda root, pattern, variable: None,
        nodes=lambda root, pattern, variable: ["restored"],
        attach=lambda node: player if node == "restored" else None,
        create=MagicMock(),
    )
    monkeypatch.setattr(module, "get_fourd_manager", lambda: fourd)
    monkeypatch.setattr(module.virtual_folder, "manager", lambda: MagicMock())

    # Only its track is needed: constructing the logic would also start its job event timer.
    assert logic.__new__(logic).track(tmp_path) == ("restored", player)

    player.refreshFrames.assert_called_once()
    fourd.create.assert_not_called()


def test_a_run_is_found_in_its_case_by_the_job_it_was_submitted_as(logic, tmp_path):
    """How a job recorded before its run folder was kept still finds it: the uid in the run's record."""
    for name, uid in (("sim001", "uid-1"), ("sim002", "uid-2")):
        (tmp_path / name).mkdir()
        logic.writeRunRecord(tmp_path / name, _submission(uid=uid))
    (tmp_path / "sim003").mkdir()
    (tmp_path / "sim004").mkdir()
    (tmp_path / "sim004" / "geoslicer_run.json").write_text("not json", encoding="utf-8")

    assert logic.findRun(tmp_path, "uid-2") == tmp_path / "sim002"
    assert logic.findRun(tmp_path, "uid-9") is None
