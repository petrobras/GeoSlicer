import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import qt
import slicer

from commons.lbpm.config import WaterflowConfig
from commons.remote.backends import BACKEND_AUTO, BACKEND_REMOTE
from commons.remote.connections import JobExecutor
from commons.remote.hosts.local.local import LocalHost
from commons.remote.jobs import JobManager
from commons.slicer.lbpm import (
    CLUSTER_DEFAULTS,
    RESULTS_SOURCE_ATTRIBUTE,
    Backend,
    LBPMDispatcher,
    SubmissionResult,
)
from commons.slicer.widget.execution import ExecutionSettings, ExecutionSettingsDialog, ExecutionWidget
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import check_for_message_box, process_events, wait, waitCondition
from commons.slicer.virtual import folder as virtualFolder
from commons.slicer.virtual.fourd import proxy as fourdProxy
from commons.slicer.virtual.fourd.manager import get_manager as getFourDManager

RESOURCES = Path(__file__).parent / "Resources"
STUB_SIMULATOR = RESOURCES / "fake_lbpm.sh"


class PoreScaleModellingTest(LTracePluginTest):
    """Configure, run and report an LBPM case.

    Runs against a stand-in simulator (``Resources/fake_lbpm.sh``) that writes the same output shape as
    ``lbpm_color_simulator`` in a second, so the whole pipeline is exercised without LBPM installed.
    """

    def pre_setup(self):
        self.workspace = Path(tempfile.mkdtemp(prefix="pore-scale-test-"))
        self.previousHint = LBPMDispatcher.binary_hint()
        self.touchedSettings = []

    def tear_down(self):
        LBPMDispatcher.set_binary_hint(self.previousHint or "")
        for key in self.touchedSettings:
            slicer.app.userSettings().remove(key)
        getFourDManager().closeAll()
        for uid in list(JobManager.jobs):
            JobManager.remove(uid)
        shutil.rmtree(self.workspace, ignore_errors=True)

    # -- fixtures -------------------------------------------------------------------------------------
    def _selectCase(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        widget = self._module_widget
        widget.caseButton.directory = folder.as_posix()
        process_events()
        return widget

    def _labelMapNode(self, shape=(8, 8, 8)):
        array = np.zeros(shape, dtype=np.uint8)
        array[:, :, ::2] = 1  # a striped "pore space"
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "rock")
        slicer.util.updateVolumeFromArray(node, array)
        node.SetSpacing(0.002, 0.002, 0.002)  # 2 micrometers
        return node

    def _prepareRunnableCase(self, folder: Path, timesteps=3000, interval=1000):
        widget = self._selectCase(folder)
        node = self._labelMapNode()
        widget.inputSelector.setCurrentNode(node)
        process_events()
        widget.writeInputButton.click()
        process_events()

        config = widget.configWidget.config
        config.set("Color", "timestepMax", timesteps)
        config.set("Analysis", "visualization_interval", interval)
        widget.configWidget.setConfig(config)
        widget.saveConfigButton.click()
        process_events()
        return widget

    @staticmethod
    def _editOutside(path: Path, section: str, key: str, value):
        """Change the configuration file the way a text editor would: behind the module's back."""
        edited = WaterflowConfig.from_file(path)
        edited.set(section, key, value)
        edited.write(path)

    def _storeBackendSettings(self, execution, backend, values):
        """Answer a backend's settings as the dialog would, and leave the session as it was found."""
        fields = execution.fieldsFor(backend)
        for item in fields:
            if item.key in values:
                self.touchedSettings.append(execution.settings.key(backend.name, item))
        execution.settings.update(backend.name, fields, values)

    @staticmethod
    def _writeFrame(folder: Path, step: int, shape=(8, 8, 8)):
        """A frame as LBPM writes it: one folder per timestep, holding a full-domain 8-bit image."""
        frame = folder / f"vis{step}"
        frame.mkdir(parents=True)
        np.full(shape, step // 1000, dtype=np.uint8).tofile((frame / f"id_t{step}.raw").as_posix())

    def _selectLocalBackend(self, widget):
        execution = widget.executionWidget
        execution.backendComboBox.setCurrentIndex(
            execution.backendComboBox.findData(LBPMDispatcher.local_backend().name)
        )
        execution.setRanks(1)
        process_events()
        return execution

    def _waitForJob(self, uid, timeout=120):
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = JobManager.jobs.get(uid)
            if job is not None and job.status in ("COMPLETED", "FAILED", "CANCELLED"):
                return job
            wait(1)
        return JobManager.jobs.get(uid)

    # -- cases ----------------------------------------------------------------------------------------
    def test_default_configuration_is_offered_for_an_empty_folder(self):
        """An empty folder is a valid starting point: the module writes a default case into it."""
        widget = self._selectCase(self.workspace / "empty")

        assert widget.configWidget.config is not None
        assert "created with default values" in widget.caseLabel.text, widget.caseLabel.text
        # A default case is incomplete on purpose: it has no image yet, and says so.
        assert widget.configWidget.validate()

        widget.saveConfigButton.click()
        process_events()
        assert (self.workspace / "empty" / "waterflow.db").is_file()

    def test_writing_the_input_image_fills_in_the_domain(self):
        """LBPM reads a headerless image, so the geometry has to be carried into the configuration."""
        widget = self._selectCase(self.workspace / "with-image")
        node = self._labelMapNode(shape=(8, 6, 4))
        widget.inputSelector.setCurrentNode(node)
        process_events()

        widget.writeInputButton.click()
        process_events()

        config = widget.configWidget.config
        assert config.domain_shape_zyx() == (8, 6, 4)
        assert config.get_string("Domain", "ReadType") == "8bit"
        assert config.voxel_length_mm() is not None
        assert abs(config.voxel_length_mm() - 0.002) < 1e-9
        assert config.validate() == [], config.validate()

        image = self.workspace / "with-image" / config.get_string("Domain", "Filename")
        assert image.is_file()
        assert image.stat().st_size == 8 * 6 * 4

        # The configuration that reads the image is saved with it, so the case folder is never half updated.
        saved = WaterflowConfig.from_file(self.workspace / "with-image" / "waterflow.db")
        assert saved.get_string("Domain", "Filename") == image.name
        assert saved.domain_shape_zyx() == (8, 6, 4)
        assert image.name in widget.configWidget.imageLabel.text, widget.configWidget.imageLabel.text

    def test_a_reused_case_reads_the_image_written_into_it(self):
        """Reusing a case keeps its image until another one is written; from then on the file reads that one."""
        case = self.workspace / "reused"
        widget = self._selectCase(case)
        widget.inputSelector.setCurrentNode(self._labelMapNode(shape=(8, 8, 8)))
        process_events()
        widget.writeInputButton.click()
        process_events()
        first = widget.configWidget.config.get_string("Domain", "Filename")

        # Come back to the case later, as someone reusing its configuration would.
        widget.caseButton.directory = self.workspace.as_posix()
        process_events()
        widget = self._selectCase(case)
        assert widget.configWidget.config.get_string("Domain", "Filename") == first

        other = self._labelMapNode(shape=(8, 6, 4))
        other.SetName("other")
        widget.inputSelector.setCurrentNode(other)
        process_events()
        # Selecting is not writing: the module says which image a run would still read.
        assert first in widget.caseLabel.text, widget.caseLabel.text
        assert "Write image into the case" in widget.caseLabel.text, widget.caseLabel.text

        widget.writeInputButton.click()
        process_events()

        saved = WaterflowConfig.from_file(case / "waterflow.db")
        assert saved.get_string("Domain", "Filename").startswith("other_4_6_8_"), saved.get_string("Domain", "Filename")
        assert saved.domain_shape_zyx() == (8, 6, 4)
        assert "other_4_6_8_" in widget.configWidget.imageLabel.text, widget.configWidget.imageLabel.text

    def test_the_configuration_file_is_edited_in_a_text_editor(self):
        """The form holds the usual parameters; the file, edited in a text editor and reloaded, holds the rest."""
        case = self.workspace / "editing"
        widget = self._selectCase(case)
        form = widget.configWidget
        form._widgets[("Color", "alpha")][0].setValue(0.004)

        # Stand in for the editor: record the file it would open instead of opening a window.
        opened = []
        with patch.dict(type(widget).setup.__globals__, {"openInTextEditor": lambda path: opened.append(path) or True}):
            widget.editConfigButton.click()
            process_events()

        path = case / "waterflow.db"
        assert [Path(item) for item in opened] == [path], opened
        # The editor opens what the form showed, not what the file held before.
        assert abs(WaterflowConfig.from_file(path).get_float("Color", "alpha") - 0.004) < 1e-9

        self._editOutside(path, "Color", "beta", 0.9)
        widget.reloadConfigButton.click()
        process_events()

        assert abs(form.config.get_float("Color", "beta") - 0.9) < 1e-9
        assert abs(form._widgets[("Color", "beta")][0].value - 0.9) < 1e-9
        assert abs(form.config.get_float("Color", "alpha") - 0.004) < 1e-9

    def test_edits_made_outside_are_never_overwritten_silently(self):
        """Writing the form over a file changed in the editor asks first: reload it, overwrite it, or stop."""
        case = self.workspace / "outside-edits"
        widget = self._selectCase(case)
        beta = widget.configWidget._widgets[("Color", "beta")][0]
        beta.setValue(0.8)
        widget.saveConfigButton.click()
        process_events()
        path = case / "waterflow.db"

        # Reload: the form takes the file's value, and saving keeps it.
        self._editOutside(path, "Color", "beta", 0.9)
        with check_for_message_box("changed outside GeoSlicer", buttonTextToClick="Reload"):
            widget.saveConfigButton.click()
        process_events()
        assert abs(beta.value - 0.9) < 1e-9, beta.value
        assert abs(WaterflowConfig.from_file(path).get_float("Color", "beta") - 0.9) < 1e-9

        # Cancel: nothing is written, and the form is left as it was.
        self._editOutside(path, "Color", "beta", 0.7)
        with check_for_message_box("changed outside GeoSlicer", buttonTextToClick="Cancel"):
            widget.saveConfigButton.click()
        process_events()
        assert abs(beta.value - 0.9) < 1e-9, beta.value
        assert abs(WaterflowConfig.from_file(path).get_float("Color", "beta") - 0.7) < 1e-9

        # Overwrite: the form wins.
        with check_for_message_box("changed outside GeoSlicer", buttonTextToClick="Overwrite"):
            widget.saveConfigButton.click()
        process_events()
        assert abs(WaterflowConfig.from_file(path).get_float("Color", "beta") - 0.9) < 1e-9

        # Once the module wrote the file itself, there is nothing left to ask about.
        beta.setValue(0.85)
        widget.saveConfigButton.click()
        process_events()
        assert abs(WaterflowConfig.from_file(path).get_float("Color", "beta") - 0.85) < 1e-9

    def test_running_the_simulation_reports_progress_and_results(self):
        """The whole local path: a new simNNN folder, a managed job, frames, and a report."""
        assert STUB_SIMULATOR.is_file(), f"missing stub simulator: {STUB_SIMULATOR}"
        LBPMDispatcher.set_binary_hint(STUB_SIMULATOR.as_posix())

        case = self.workspace / "run"
        widget = self._prepareRunnableCase(case, timesteps=3000, interval=1000)

        execution = widget.executionWidget
        execution.backendComboBox.setCurrentIndex(
            execution.backendComboBox.findData(LBPMDispatcher.local_backend().name)
        )
        execution.setRanks(1)
        widget.trackCheckBox.setChecked(True)
        process_events()

        execution.runButton.click()
        process_events()

        uid = widget.logic.uid
        assert uid, "the run should have produced a managed job"

        simulation = widget.simulationDir
        assert simulation is not None and simulation.name == "sim001"
        assert (simulation / "waterflow.db").is_file()

        job = self._waitForJob(uid)
        assert job is not None
        assert job.status == "COMPLETED", f"{job.status}: {job.message} {job.traceback}"
        assert job.progress == 100
        # Written by the job's deployment step, which runs asynchronously after the click.
        assert (simulation / "run_lbpm.sh").is_file()

        frames = sorted(path.name for path in simulation.glob("vis*"))
        assert frames == ["vis1000", "vis2000", "vis3000"], frames

        # Tracking was on, so the frames the run wrote are playable without another step.
        widget.trackButton.click()
        process_events()
        player = widget.playerWidget.player
        assert player is not None, "the run's frames should be surfaced as a sequence"
        assert player.frameCount == 3, player.frameCount

        widget.refreshReportButton.click()
        process_events()

        assert widget.reportWidget.summaryBox.visible
        assert widget.reportWidget.summaryValues["steady_points"].text == "3"

        results = widget.logic.results(simulation)
        assert {curve.key for curve in results.curves()} >= {"relative_permeability", "saturation_history"}

        widget.reportWidget.tablesButton.click()
        process_events()
        tables = [node.GetName() for node in slicer.util.getNodesByClass("vtkMRMLTableNode")]
        assert any("timelog" in name for name in tables), tables

    def test_a_finished_run_opens_again_from_its_job(self):
        """What the Job Monitor's Open does, also after a restart: back to its case, its run, frames and tables."""
        LBPMDispatcher.set_binary_hint(STUB_SIMULATOR.as_posix())
        case = self.workspace / "reopen"
        widget = self._prepareRunnableCase(case, timesteps=3000, interval=1000)
        execution = self._selectLocalBackend(widget)
        widget.trackCheckBox.setChecked(False)
        execution.runButton.click()
        process_events()
        uid, simulation = widget.logic.uid, widget.simulationDir
        job = self._waitForJob(uid)
        assert job is not None and job.status == "COMPLETED", job and f"{job.status}: {job.message}"

        # Somewhere else entirely, as the module is after a restart.
        self._selectCase(self.workspace / "elsewhere")
        assert widget.simulationDir != simulation

        details = job.details
        widget.openRun(details["source_dir"], details["output_dir"], uid=uid)
        process_events()

        assert widget.caseDir == case and widget.simulationDir == simulation
        assert widget.logic.uid == uid, "the module does not follow the job it opened"
        assert "[COMPLETED]" in execution.status(), execution.status()
        assert widget.playerWidget.player is not None and widget.playerWidget.player.frameCount == 3
        assert widget.reportWidget.summaryBox.visible
        tables = self._runTables(simulation)
        assert tables == ["sim001 subphase", "sim001 timelog"], tables

        widget.openRun(details["source_dir"], details["output_dir"], uid=uid)
        process_events()
        assert self._runTables(simulation) == tables, "opening the run again doubled its tables"

    @staticmethod
    def _runTables(folder: Path):
        return sorted(
            node.GetName()
            for node in slicer.util.getNodesByClass("vtkMRMLTableNode")
            if node.GetAttribute(RESULTS_SOURCE_ATTRIBUTE) == folder.as_posix()
        )

    def test_each_run_gets_its_own_folder(self):
        LBPMDispatcher.set_binary_hint(STUB_SIMULATOR.as_posix())

        case = self.workspace / "numbering"
        widget = self._prepareRunnableCase(case, timesteps=1000, interval=1000)
        widget.executionWidget.setRanks(1)
        widget.trackCheckBox.setChecked(False)

        first = widget.logic.nextSimulationDir(case)
        assert first.name == "sim001"
        first.mkdir()

        second = widget.logic.nextSimulationDir(case)
        assert second.name == "sim002"

    def test_cancelling_a_run_stops_it_and_takes_it_off_the_job_list(self):
        """Cancel is the Job Monitor's Cancel/Delete, confirmed first. A local run keeps what it wrote."""
        LBPMDispatcher.set_binary_hint(STUB_SIMULATOR.as_posix())

        case = self.workspace / "cancel"
        # Two hundred frames a tenth of a second apart: still running when Cancel is pressed.
        widget = self._prepareRunnableCase(case, timesteps=200000, interval=1000)
        execution = self._selectLocalBackend(widget)
        widget.trackCheckBox.setChecked(False)
        process_events()

        execution.runButton.click()
        process_events()
        uid = widget.logic.uid
        simulation = widget.simulationDir
        assert uid and simulation is not None

        waitCondition(lambda: any(simulation.glob("vis*")), timeoutSec=60)
        assert any(simulation.glob("vis*")), "the run never started writing frames"
        assert execution.cancelButton.enabled

        # Declining leaves the run alone.
        with check_for_message_box("and remove it from the job list", buttonTextToClick="Keep running"):
            execution.cancelButton.click()
        wait(1)
        assert uid in JobManager.jobs and JobManager.jobs[uid].status == "RUNNING", JobManager.jobs.get(uid)

        with check_for_message_box("and remove it from the job list", buttonTextToClick="Cancel simulation"):
            execution.cancelButton.click()
        waitCondition(lambda: uid not in JobManager.jobs, timeoutSec=30)
        assert uid not in JobManager.jobs, "a cancelled job stays in the job list"

        wait(2)  # the module hears of it on its next poll
        assert not execution.cancelButton.enabled
        assert "Cancelled" in execution.status(), execution.status()

        written = len(list(simulation.glob("vis*")))
        wait(1)
        assert len(list(simulation.glob("vis*"))) == written, "the simulation kept running"
        assert (simulation / "waterflow.db").is_file(), "a local run ran in the case folder, which stays"

    def test_tracking_surfaces_the_frames_as_a_sequence(self):
        """Monitoring a finished run gives the same 4D node an ongoing run would show."""
        case = self.workspace / "tracking"
        simulation = case / "sim001"
        simulation.mkdir(parents=True)

        config = WaterflowConfig.default()
        config.set("Domain", "Filename", "image.raw")
        config.set("Domain", "N", [4, 4, 4])
        config.set("Domain", "n", [4, 4, 4])
        config.write(simulation / "waterflow.db")

        # Frames as LBPM writes them: one folder per timestep, holding a full-domain 8-bit image.
        for step in (1000, 2000):
            frame = simulation / f"vis{step}"
            frame.mkdir()
            np.full((4, 4, 4), step // 1000, dtype=np.uint8).tofile((frame / f"id_t{step}.raw").as_posix())

        widget = self._selectCase(case)
        widget.simulationDir = simulation
        widget.trackCheckBox.setChecked(True)
        widget.trackButton.click()
        process_events()

        player = widget.playerWidget.player
        assert player is not None, "tracking should have created a player"
        assert player.frameCount == 2
        assert widget.playerWidget.visible

    def test_tracking_a_folder_twice_reuses_its_sequence(self):
        """A run that gained frames is the same run: re-tracking refreshes it, it does not clone it."""
        case = self.workspace / "retracking"
        simulation = case / "sim001"
        simulation.mkdir(parents=True)

        config = WaterflowConfig.default()
        config.set("Domain", "N", [4, 4, 4])
        config.set("Domain", "n", [4, 4, 4])
        config.write(simulation / "waterflow.db")

        def writeFrame(step):
            frame = simulation / f"vis{step}"
            frame.mkdir()
            np.full((4, 4, 4), step // 1000, dtype=np.uint8).tofile((frame / f"id_t{step}.raw").as_posix())

        writeFrame(1000)

        widget = self._selectCase(case)
        widget.simulationDir = simulation
        widget.trackButton.click()
        process_events()

        first = widget.playerWidget.player
        assert first.frameCount == 1

        # The player owns whether the view follows the newest frame, so re-tracking must not reset it.
        first.setFollow(True)
        writeFrame(2000)

        widget.trackButton.click()
        process_events()

        assert widget.playerWidget.player is first, "a second node was created for the same folder"
        assert first.frameCount == 2, "re-tracking should have picked up the new frame"
        assert first.follow, "re-tracking must not override the player's own Follow latest"

        proxies = [node for node in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode") if fourdProxy.is_proxy(node)]
        assert len(proxies) == 1, [node.GetName() for node in proxies]

    # -- execution settings ---------------------------------------------------------------------------
    def test_the_settings_dialog_asks_what_the_selected_backend_needs(self):
        """A local run and a cluster run are configured by different things, so they are asked separately."""
        widget = self._selectCase(self.workspace / "settings-dialog")
        execution = widget.executionWidget

        local = [item.key for item in execution.fieldsFor(LBPMDispatcher.local_backend())]
        assert "binary" in local, local
        assert "walltime" not in local, "a queue means nothing on this computer"
        assert "container" not in local, "this computer's program is found, or named as 'binary'"

        cluster = Backend(kind=BACKEND_REMOTE, name="fake cluster", available=True)
        remote = [item.key for item in execution.fieldsFor(cluster)]
        assert {"walltime", "partition", "account", "nodes", "container", "binds"} <= set(remote), remote
        assert "binary" not in remote, "the cluster provides its own program"

        # Never shown: what matters is the form it builds and what it gives back.
        dialog = ExecutionSettingsDialog(
            title=f"LBPM settings — {cluster.name}",
            fields=execution.fieldsFor(cluster),
            values={"walltime": "2-00:00:00", "nodes": 3},
            info=execution.describeBackend(cluster),
            parent=widget.parent,
        )
        try:
            assert dialog.values()["walltime"] == "2-00:00:00"
            assert dialog.values()["nodes"] == 3

            dialog.editor("account").setText("  geo  ")
            dialog.editor("env").setPlainText("OMP_NUM_THREADS=4")
            assert dialog.values()["account"] == "geo"
            assert dialog.values()["env"] == {"OMP_NUM_THREADS": "4"}

            dialog.restoreDefaults()
            # What the reference cluster is run with by hand, until a cluster has answers of its own.
            assert dialog.values()["account"] == CLUSTER_DEFAULTS["account"]
            assert dialog.values()["container"] == CLUSTER_DEFAULTS["container"]
            assert dialog.values()["modules"] == CLUSTER_DEFAULTS["modules"]
            assert dialog.values()["nodes"] == 1, "a default is what the field falls back to, not zero"
        finally:
            dialog.setParent(None)

    def test_settings_are_remembered_for_each_backend(self):
        """Two clusters do not share a queue: what was answered for one must not follow you to the other."""
        store = ExecutionSettings(
            "TestTool",
            settings=qt.QSettings((self.workspace / "execution.ini").as_posix(), qt.QSettings.IniFormat),
        )
        alpha = Backend(kind=BACKEND_REMOTE, name="alpha", available=True)
        beta = Backend(kind=BACKEND_REMOTE, name="beta", available=True)
        execution = ExecutionWidget(backends=lambda: [alpha, beta], settings=store, toolName="Test")

        try:
            fields = execution.fieldsFor(alpha)
            store.update("alpha", fields, {"walltime": "01:00:00", "nodes": 2})
            store.update("beta", fields, {"walltime": "05:00:00", "nodes": 8})

            execution.backendComboBox.setCurrentIndex(execution.backendComboBox.findData("alpha"))
            process_events()
            options = execution.options()
            assert (options.target, options.walltime, options.nodes) == ("alpha", "01:00:00", 2), options

            execution.backendComboBox.setCurrentIndex(execution.backendComboBox.findData("beta"))
            process_events()
            assert execution.options().walltime == "05:00:00"

            # Nothing here can resolve 'auto', so there is nothing to configure for it either.
            execution.backendComboBox.setCurrentIndex(execution.backendComboBox.findData(BACKEND_AUTO))
            process_events()
            assert execution.options().kind == BACKEND_AUTO
            assert execution.scopeBackend() is None
        finally:
            execution.setParent(None)

    def test_a_run_carries_the_settings_of_the_backend_it_runs_on(self):
        """The dialog is not decoration: what it stores reaches the script the simulator is started by."""
        LBPMDispatcher.set_binary_hint(STUB_SIMULATOR.as_posix())

        case = self.workspace / "carried-settings"
        widget = self._prepareRunnableCase(case, timesteps=1000, interval=1000)
        execution = widget.executionWidget

        local = LBPMDispatcher.local_backend()
        execution.backendComboBox.setCurrentIndex(execution.backendComboBox.findData(local.name))
        execution.setRanks(1)
        widget.trackCheckBox.setChecked(False)
        self._storeBackendSettings(execution, local, {"env": {"LBPM_TEST_FLAG": "42"}})
        process_events()

        assert execution.options().env == {"LBPM_TEST_FLAG": "42"}

        execution.runButton.click()
        process_events()

        job = self._waitForJob(widget.logic.uid)
        assert job is not None and job.status == "COMPLETED", f"{job.status}: {job.message}"

        script = (widget.simulationDir / "run_lbpm.sh").read_text()
        assert "export LBPM_TEST_FLAG=42" in script, script

    def test_a_cluster_run_is_told_which_image_to_run(self):
        """The image and its binds are settings of the cluster; they reach the dispatcher with the others."""
        case = self.workspace / "cluster-image"
        widget = self._prepareRunnableCase(case, timesteps=1000, interval=1000)
        widget.trackCheckBox.setChecked(False)
        execution = widget.executionWidget
        cluster = Backend(kind=BACKEND_REMOTE, name="fake cluster", available=True)

        submitted = {}

        def submit(case_dir, **kwargs):
            submitted.update(kwargs)
            return SubmissionResult(uid="", backend=cluster, case_dir=Path(case_dir).as_posix(), spec=None)

        settings = {"container": "/cluster/lbpm.sif", "binds": ["/cluster/libs:/usr/lib/gcc/"]}
        with (
            patch.object(LBPMDispatcher, "submit", side_effect=submit),
            patch.object(type(execution), "settingsValues", return_value=settings),
        ):
            execution.runButton.click()
            process_events()

        assert submitted["container"] == "/cluster/lbpm.sif", submitted
        assert submitted["binds"] == ["/cluster/libs:/usr/lib/gcc/"], submitted

    def test_a_new_run_leaves_the_previous_one_off_the_screen(self):
        """Starting a run drops the last one's sequence and report; playing the new one is the user's call."""
        LBPMDispatcher.set_binary_hint(STUB_SIMULATOR.as_posix())
        widget = self._prepareRunnableCase(self.workspace / "rerun", timesteps=2000, interval=1000)
        execution = self._selectLocalBackend(widget)
        widget.trackCheckBox.setChecked(False)

        execution.runButton.click()
        process_events()
        first = widget.simulationDir
        assert self._waitForJob(widget.logic.uid).status == "COMPLETED"
        widget.trackButton.click()
        widget.refreshReportButton.click()
        process_events()
        assert widget.playerWidget.player is not None and widget.playerWidget.visible
        assert widget.reportWidget.summaryBox.visible

        execution.runButton.click()
        second = widget.simulationDir
        assert second.name == "sim002" and second != first
        assert widget.playerWidget.player is None, "the previous run's sequence is still in the player"
        assert not widget.playerWidget.visible
        assert not widget.reportWidget.summaryBox.visible, "the previous run's report is still shown"
        assert "sim002" in widget.trackButton.text, widget.trackButton.text

        assert self._waitForJob(widget.logic.uid).status == "COMPLETED"
        process_events()
        assert widget.playerWidget.player is None, "tracking was off for this run, so it waits for the button"

        widget.trackButton.click()
        process_events()
        assert Path(widget.playerWidget.player.dataset.root) == second

    def test_a_cluster_run_is_tracked_where_it_writes(self):
        """A cluster run writes into its copy on the shared drive, so that is what is tracked and reported."""
        case = self.workspace / "cluster-output"
        widget = self._prepareRunnableCase(case, timesteps=1000, interval=1000)
        widget.trackCheckBox.setChecked(False)
        share = self.workspace / "share" / "lbpm" / "job-uid"
        cluster = Backend(kind=BACKEND_REMOTE, name="fake cluster", available=True)

        def submit(case_dir, **kwargs):
            # What staging does: the run's inputs are copied to the share, and the cluster runs there.
            share.mkdir(parents=True)
            for item in Path(case_dir).iterdir():
                shutil.copy2(item, share / item.name)
            return SubmissionResult(
                uid="", backend=cluster, case_dir="/cluster/lbpm/job-uid", spec=None, local_dir=share.as_posix()
            )

        with patch.object(LBPMDispatcher, "submit", side_effect=submit):
            widget.executionWidget.runButton.click()
            process_events()

        simulation = widget.simulationDir
        assert simulation.name == "sim001"
        assert widget.logic.outputDir(simulation) == share
        assert share.as_posix() in widget.executionWidget.status(), widget.executionWidget.status()

        self._writeFrame(share, 1000)
        widget.trackButton.click()
        process_events()
        assert Path(widget.playerWidget.player.dataset.root) == share

        # Coming back to the case later still finds where its latest run went.
        widget.caseButton.directory = self.workspace.as_posix()
        process_events()
        widget = self._selectCase(case)
        assert widget.simulationDir == simulation
        assert widget.playerWidget.player is None
        widget.trackButton.click()
        process_events()
        assert Path(widget.playerWidget.player.dataset.root) == share

    def test_cancelling_a_cluster_run_removes_its_time_sequence(self):
        """Its frames were on the cluster and are deleted with it: a sequence of them could not play."""
        case = self.workspace / "cluster-cancel"
        widget = self._prepareRunnableCase(case, timesteps=1000, interval=1000)
        widget.trackCheckBox.setChecked(False)
        share = self.workspace / "share" / "lbpm" / "job-uid"
        cluster = Backend(kind=BACKEND_REMOTE, name="fake cluster", available=True)

        def submit(case_dir, **kwargs):
            share.mkdir(parents=True)
            return SubmissionResult(
                uid="", backend=cluster, case_dir="/cluster/lbpm/job-uid", spec=None, local_dir=share.as_posix()
            )

        with patch.object(LBPMDispatcher, "submit", side_effect=submit):
            widget.executionWidget.runButton.click()
            process_events()

        self._writeFrame(share, 1000)
        widget.trackButton.click()
        process_events()
        node = widget.playerWidget.player.node
        assert slicer.mrmlScene.GetNodeByID(node.GetID()) is not None

        # What Cancel/Delete does on the cluster, then what the job manager tells the module once it is done.
        shutil.rmtree(share)
        widget.logic.jobRemoved.emit(True, True)
        process_events()

        assert slicer.mrmlScene.GetNodeByID(node.GetID()) is None, "the sequence of deleted frames stayed"
        assert not [p for p in getFourDManager().players().values() if Path(p.dataset.root) == share]
        assert virtualFolder.manager().get(share) is None, "the deleted folder is still monitored"
        assert widget.playerWidget.player is None
        assert "time sequence were deleted" in widget.executionWidget.status(), widget.executionWidget.status()
        assert (widget.simulationDir / "waterflow.db").is_file(), "the run keeps its inputs"

    def test_a_run_opened_from_its_output_alone_loses_its_sequence_when_cancelled(self):
        """A job recorded before its run folder was kept opens from its copy on the share, and is followed like
        any other: cancelled, its sequence goes, also once it lost its player, as after reopening a project."""
        widget = self._selectCase(self.workspace / "elsewhere")
        share = self.workspace / "share" / "lbpm" / "job-uid"
        config = WaterflowConfig.default()
        config.set("Domain", "N", [8, 8, 8])
        config.write(share / "waterflow.db")
        self._writeFrame(share, 1000)

        uid = "job-uid"
        job = JobExecutor(uid, None, LocalHost(), name="LBPM rock/sim001", job_type="lbpm")
        job.status = "COMPLETED"
        job.details = {"scheduler": "slurm"}
        JobManager.jobs[uid] = job

        widget.openRun(None, share.as_posix(), uid=uid)
        process_events()
        assert widget.logic.uid == uid and widget.logic.runOutput == share, "the opened run is not followed"
        node = widget.playerWidget.player.node

        # As after reopening the project: the node is in the scene, its player is not.
        widget.playerWidget.clear()
        getFourDManager().close(node)
        assert getFourDManager().player(node) is None and slicer.mrmlScene.GetNodeByID(node.GetID()) is not None

        # What Cancel/Delete does: the copy on the share goes, then the job.
        shutil.rmtree(share)
        JobManager.set_state(uid, "CANCELLED")
        JobManager.remove(uid)
        wait(2)  # the module hears of it on its next poll

        assert slicer.mrmlScene.GetNodeByID(node.GetID()) is None, "the sequence of deleted frames stayed"
        assert virtualFolder.manager().get(share) is None, "the deleted folder is still monitored"
        assert "time sequence were deleted" in widget.executionWidget.status(), widget.executionWidget.status()
