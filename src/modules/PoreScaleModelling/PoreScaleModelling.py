import json
import logging
import os
import re
import shutil
import traceback
from pathlib import Path

import ctk
import numpy as np
import qt
import slicer

from ltrace.lbpm.config import WaterflowConfig
from ltrace.lbpm.geometry import CaseGeometry
from ltrace.lbpm.results import LBPMResults
from ltrace.lbpm.scheduler import SlurmScheduler
from ltrace.slicer import ui
from ltrace.slicer.lbpm import (
    REMOTE_FIELDS_LBPM,
    SETTING_BINARY,
    SETTING_REMOTE_ROOT,
    LBPMDispatcher,
    NoBackendAvailable,
    build_result_nodes,
)
from ltrace.slicer.virtual import folder as virtual_folder
from ltrace.slicer.virtual.fourd.manager import get_manager as get_fourd_manager
from ltrace.slicer.widget.execution import ExecutionSettings, ExecutionWidget
from ltrace.slicer.widget.fourd_player import FourDPlayerWidget
from ltrace.slicer_utils import LTracePlugin, LTracePluginLogic, LTracePluginWidget, openInTextEditor
from ltrace.remote.constants import JOB_STATE_CANCELLED
from ltrace.remote.jobs import JobManager

from PoreScaleModellingLib import ConfigFormWidget, ReportWidget

try:
    from Test.PoreScaleModellingTest import PoreScaleModellingTest
except ImportError:
    PoreScaleModellingTest = None  # tests not deployed to final version or closed source

CONFIG_NAME = "waterflow.db"
SIMULATION_PREFIX = "sim"
SIMULATION_PATTERN = re.compile(rf"^{SIMULATION_PREFIX}(\d+)$")
FRAME_PATTERN = r"vis\d+"
RUN_RECORD_NAME = "geoslicer_run.json"
"""Written into each simNNN folder: where that run went, so its output can be found again later."""
JOB_DELETED = "JOB_DELETED"
"""What the job manager tells its observers when a job leaves it."""


class PoreScaleModelling(LTracePlugin):
    SETTING_KEY = "PoreScaleModelling"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "LBPM"
        self.parent.categories = ["MicroCT", "Multiscale"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = (
            "Configure and run an LBPM colour simulation — locally or on a cluster — watch it write its "
            "frames, and read the resulting relative permeability curves."
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PoreScaleModellingWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = PoreScaleModellingLogic()
        self.caseDir = None
        self.simulationDir = None
        # The configuration file as this module last read or wrote it, to notice edits made outside it.
        self.__configOnDisk = None

    # -- construction ---------------------------------------------------------------------------------
    def setup(self):
        LTracePluginWidget.setup(self)

        self.layout.addWidget(self.__setupCaseSection())
        self.layout.addWidget(self.__setupConfigSection())
        self.layout.addWidget(self.__setupExecutionSection())
        self.layout.addWidget(self.__setupMonitoringSection())
        self.layout.addWidget(self.__setupResultsSection())
        self.layout.addStretch(1)

        self.logic.jobStateChanged.connect(self.__onJobStateChanged)
        self.logic.jobRemoved.connect(self.__onJobRemoved)
        self.inputSelector.currentItemChanged.connect(self.__onInputChanged)
        self.__onCaseSelected(self.caseButton.directory)

    def __setupCaseSection(self):
        section = ctk.ctkCollapsibleButton()
        section.text = "Case"
        section.collapsed = False
        layout = qt.QFormLayout(section)

        self.caseButton = ctk.ctkDirectoryButton()
        self.caseButton.setMaximumWidth(374)
        self.caseButton.objectName = "Case Directory Button"
        self.caseButton.setToolTip(
            f"Folder holding the simulation case. If it has no {CONFIG_NAME}, one is created with defaults."
        )
        saved = PoreScaleModelling.get_setting("CaseDir", None)
        if saved:
            self.caseButton.directory = saved
        self.caseButton.directoryChanged.connect(self.__onCaseSelected)
        layout.addRow("Case folder:", self.caseButton)

        self.inputSelector = ui.hierarchyVolumeInput(
            hasNone=True,
            nodeTypes=["vtkMRMLLabelMapVolumeNode", "vtkMRMLScalarVolumeNode"],
            tooltip="Segmented image to simulate on. Writing it fills in the domain size and voxel length.",
        )
        self.inputSelector.objectName = "Input Image Selector"
        layout.addRow("Input image:", self.inputSelector)

        self.writeInputButton = qt.QPushButton("Write image into the case")
        self.writeInputButton.objectName = "Write Input Button"
        self.writeInputButton.setToolTip(
            "Save the selected image as the RAW file LBPM reads, and update Domain.N, the process grid and "
            f"the voxel length in {CONFIG_NAME} to match it."
        )
        self.writeInputButton.clicked.connect(self.__onWriteInputClicked)
        layout.addRow(self.writeInputButton)

        self.caseLabel = qt.QLabel()
        self.caseLabel.setWordWrap(True)
        self.caseLabel.objectName = "Case Label"
        layout.addRow(self.caseLabel)

        return section

    def __setupConfigSection(self):
        section = ctk.ctkCollapsibleButton()
        section.text = "Configuration"
        section.collapsed = False
        layout = qt.QVBoxLayout(section)

        self.configWidget = ConfigFormWidget()
        layout.addWidget(self.configWidget)

        buttons = qt.QHBoxLayout()
        self.saveConfigButton = qt.QPushButton("Save configuration")
        self.saveConfigButton.objectName = "Save Config Button"
        self.saveConfigButton.setToolTip(f"Write the values above back into {CONFIG_NAME}.")
        self.saveConfigButton.clicked.connect(self.__onSaveConfigClicked)
        buttons.addWidget(self.saveConfigButton)

        self.editConfigButton = qt.QPushButton("Edit in text editor")
        self.editConfigButton.objectName = "Edit Config Button"
        self.editConfigButton.setToolTip(
            f"Save the values above into {CONFIG_NAME} and open it in the system's text editor, for the "
            "settings the form does not show. Press 'Reload from file' once you have saved it there."
        )
        self.editConfigButton.clicked.connect(self.__onEditConfigClicked)
        buttons.addWidget(self.editConfigButton)

        self.reloadConfigButton = qt.QPushButton("Reload from file")
        self.reloadConfigButton.objectName = "Reload Config Button"
        self.reloadConfigButton.setToolTip(
            f"Read {CONFIG_NAME} again, after editing it in a text editor. Values changed above and not "
            "saved are replaced."
        )
        self.reloadConfigButton.clicked.connect(self.__onReloadConfigClicked)
        buttons.addWidget(self.reloadConfigButton)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        return section

    def __setupExecutionSection(self):
        section = ctk.ctkCollapsibleButton()
        section.text = "Execution"
        section.collapsed = False
        layout = qt.QVBoxLayout(section)

        self.executionWidget = ExecutionWidget(
            backends=LBPMDispatcher.available_backends,
            resolve=LBPMDispatcher.resolve_backend,
            # The program and the staging folder are already settings of their own, read by the dispatcher
            # on every submission: the dialog edits those keys rather than a second copy of them.
            settings=ExecutionSettings("LBPM", aliases={"binary": SETTING_BINARY, "remote_root": SETTING_REMOTE_ROOT}),
            remoteFields=REMOTE_FIELDS_LBPM,
            toolName="LBPM",
            runText="Run simulation",
            runTooltip="Start the simulation in a new folder.",
        )
        self.executionWidget.runClicked.connect(self.__onRunClicked)
        self.executionWidget.cancelClicked.connect(self.__onCancelClicked)
        layout.addWidget(self.executionWidget)

        return section

    def __setupMonitoringSection(self):
        section = ctk.ctkCollapsibleButton()
        section.text = "Monitoring"
        section.collapsed = False
        layout = qt.QVBoxLayout(section)

        self.trackCheckBox = qt.QCheckBox("Create a time sequence for this run")
        self.trackCheckBox.objectName = "Track CheckBox"
        self.trackCheckBox.setToolTip(
            "Surface the simulation's frames as a time sequence when the run starts. Whether the view "
            "keeps jumping to the newest frame is the player's own 'Follow latest'."
        )
        self.trackCheckBox.setChecked(True)
        layout.addWidget(self.trackCheckBox)

        self.playerWidget = FourDPlayerWidget()
        self.playerWidget.visible = False
        layout.addWidget(self.playerWidget)

        self.trackButton = qt.QPushButton("Track the case folder now")
        self.trackButton.objectName = "Track Button"
        self.trackButton.enabled = False  # until there is a case to track
        self.trackButton.clicked.connect(self.__onTrackClicked)
        layout.addWidget(self.trackButton)

        return section

    def __setupResultsSection(self):
        section = ctk.ctkCollapsibleButton()
        section.text = "Results"
        section.collapsed = False
        layout = qt.QVBoxLayout(section)

        self.reportWidget = ReportWidget()
        self.reportWidget.tablesButton.clicked.connect(self.__onCreateTablesClicked)
        layout.addWidget(self.reportWidget)

        self.refreshReportButton = qt.QPushButton("Refresh report")
        self.refreshReportButton.objectName = "Refresh Report Button"
        self.refreshReportButton.setToolTip("Read the simulation logs again. Works while the run is still going.")
        self.refreshReportButton.clicked.connect(self.__onRefreshReportClicked)
        layout.addWidget(self.refreshReportButton)

        return section

    # -- events ---------------------------------------------------------------------------------------
    def __onCaseSelected(self, directory):
        path = Path(directory) if directory else None
        if path is None or not path.is_dir():
            self.caseLabel.setText("Select the folder that holds (or will hold) the simulation case.")
            return

        self.caseDir = path
        PoreScaleModelling.set_setting("CaseDir", path.as_posix())

        config, created = self.__loadConfig()

        latest = self.logic.latestSimulation(path)
        self.__showSimulation(latest)
        self.caseLabel.setText(self.logic.describeCase(path, config, created, latest))

    def __onInputChanged(self, _item):
        # Choosing an image changes nothing by itself: writing it is what puts it in the case. Say so when the
        # case still reads another one, or a run would silently simulate that.
        node = self.inputSelector.currentNode()
        config = self.configWidget.config
        if node is None or self.caseDir is None or config is None:
            return

        current = config.get_string("Domain", "Filename")
        if current and current == self.logic.inputImageName(node):
            return

        reads = f"The case reads {current}." if current else "The case has no image yet."
        self.caseLabel.setText(f"{reads} Press 'Write image into the case' to use {node.GetName()}.")

    def __onWriteInputClicked(self):
        node = self.inputSelector.currentNode()
        if node is None or self.caseDir is None:
            slicer.util.errorDisplay("Select a case folder and an input image first.")
            return

        if not self.__settleOutsideEdits():
            return

        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            config = self.configWidget.applyToConfig()
            written = self.logic.writeInputImage(node, self.caseDir, config, ranks=self.executionWidget.ranks())
            # The image and its placement are in the case now; the configuration that reads them goes too, so
            # the folder never describes one image while holding another.
            self.__saveConfig(config)
            self.configWidget.setConfig(config)
            self.caseLabel.setText(f"Wrote {written.name} and updated {CONFIG_NAME} to match it.")
        except Exception as error:
            logging.error(f"Failed to write the input image: {error}\n{traceback.format_exc()}")
            slicer.util.errorDisplay(f"Could not write the input image: {error}")
        finally:
            qt.QApplication.restoreOverrideCursor()

    def __onSaveConfigClicked(self):
        if self.caseDir is None:
            return

        if not self.__settleOutsideEdits():
            return

        config = self.configWidget.applyToConfig()
        problems = self.configWidget.validate()
        path = self.__saveConfig(config)
        message = f"Saved {path.name}."
        if problems:
            message += " It still has problems, listed above."
        self.caseLabel.setText(message)

    def __onEditConfigClicked(self):
        if self.caseDir is None:
            slicer.util.errorDisplay("Select a case folder first.")
            return

        if not self.__settleOutsideEdits():
            return

        # The editor shows the file, so the file is brought up to what the form shows first.
        path = self.__saveConfig(self.configWidget.applyToConfig())
        if not openInTextEditor(path):
            slicer.util.errorDisplay(f"Could not open a text editor. The configuration is at:\n{path}")
            return
        self.caseLabel.setText(f"Opened {path.name} in the text editor. Save it there, then press 'Reload from file'.")

    def __onReloadConfigClicked(self):
        if self.caseDir is None:
            return

        config, created = self.__loadConfig()
        self.caseLabel.setText(
            self.logic.describeCase(self.caseDir, config, created, self.logic.latestSimulation(self.caseDir))
        )

    def __onRunClicked(self):
        if self.caseDir is None:
            slicer.util.errorDisplay("Select a case folder first.")
            return

        if not self.__settleOutsideEdits():
            return

        config = self.configWidget.applyToConfig()
        problems = self.configWidget.validate()
        if problems:
            slicer.util.errorDisplay("This configuration cannot run yet:\n\n" + "\n".join(problems))
            return

        self.__saveConfig(config)

        # The image a cluster runs LBPM from is this tool's own setting, so it is read next to the common ones.
        settings = self.executionWidget.settingsValues()
        try:
            submission = self.logic.run(
                self.caseDir,
                config=config,
                options=self.executionWidget.options(),
                container=settings.get("container"),
                binds=settings.get("binds"),
            )
        except NoBackendAvailable as error:
            slicer.util.errorDisplay(str(error))
            return
        except Exception as error:
            logging.error(f"Failed to start the simulation: {error}\n{traceback.format_exc()}")
            slicer.util.errorDisplay(f"Could not start the simulation: {error}")
            return

        self.__showSimulation(self.logic.simulationDir)
        output = self.__outputDir()
        self.executionWidget.setProgress(0)
        self.executionWidget.setRunning(True)
        writing = "" if output == self.simulationDir else f", writing to {output}"
        self.executionWidget.setStatus(
            f"Submitted to {submission.backend.name}. Running in {self.simulationDir.name}{writing}."
        )

        if self.trackCheckBox.checked:
            # A run that was just submitted has no frames yet, so the sequence starts out following the
            # newest one — which is what the player's own checkbox will then show.
            self.__trackSimulation(output, follow=True)

    # -- configuration file ---------------------------------------------------------------------------
    def __loadConfig(self):
        config, created = self.logic.loadConfig(self.caseDir)
        self.__configOnDisk = self.logic.readConfigText(self.caseDir)
        self.configWidget.setConfig(config)
        self.executionWidget.setRanks(max(1, config.rank_count()))
        return config, created

    def __saveConfig(self, config: WaterflowConfig) -> Path:
        path = self.logic.saveConfig(self.caseDir, config)
        self.__configOnDisk = self.logic.readConfigText(self.caseDir)
        return path

    def __settleOutsideEdits(self) -> bool:
        """Before the configuration file is written: decide what happens to edits made to it elsewhere.

        The file is also edited in a text editor, and writing the form over it would drop those edits
        without a word. When it changed since this module last read or wrote it, the user either reloads it
        — the form then shows the file — or overwrites it with the form. Returns False when they cancel.
        """
        if self.logic.readConfigText(self.caseDir) == self.__configOnDisk:
            return True

        messageBox = qt.QMessageBox(slicer.modules.AppContextInstance.mainWindow)
        messageBox.setWindowTitle("Configuration changed")
        messageBox.setIcon(qt.QMessageBox.Question)
        messageBox.setText(f"{CONFIG_NAME} was changed outside GeoSlicer since it was loaded.")
        messageBox.setInformativeText(
            "Reload it to use those changes, or overwrite them with the values shown in the module."
        )
        reloadButton = messageBox.addButton("Reload", qt.QMessageBox.AcceptRole)
        overwriteButton = messageBox.addButton("Overwrite", qt.QMessageBox.DestructiveRole)
        messageBox.addButton("Cancel", qt.QMessageBox.RejectRole)
        messageBox.setDefaultButton(reloadButton)
        messageBox.exec_()
        clicked = messageBox.clickedButton()
        messageBox.deleteLater()

        if clicked == reloadButton:
            self.__loadConfig()
            return True
        return clicked == overwriteButton

    def __onCancelClicked(self):
        output = self.logic.runOutput
        if self.logic.uid is None or output is None or not self.__confirmCancel(self.logic.simulationDir, output):
            return

        try:
            self.logic.cancel()
        except RuntimeError as error:
            # The job monitor is not running: nothing was sent.
            slicer.util.errorDisplay(f"Nothing was cancelled: {error}")
            return
        self.executionWidget.setCancelEnabled(False)
        self.executionWidget.setStatus("Cancellation requested.")

    def __confirmCancel(self, run, output: Path) -> bool:
        """Cancel is the Job Monitor's Cancel/Delete, so say what goes with the run before it goes."""
        name = run.name if run is not None else output.name

        messageBox = qt.QMessageBox(slicer.modules.AppContextInstance.mainWindow)
        messageBox.setWindowTitle("Cancel simulation")
        messageBox.setIcon(qt.QMessageBox.Warning)
        messageBox.setText(f"Cancel {name} and remove it from the job list?")
        if self.logic.followsClusterRun():
            inputs = f" {run.name} keeps its inputs." if run is not None else ""
            messageBox.setInformativeText(
                f"Everything it wrote on the cluster is deleted with it, in {output}, and its time sequence is "
                f"removed from the scene.{inputs} This cannot be undone."
            )
        else:
            messageBox.setInformativeText(f"The frames and logs it wrote so far stay in {name}.")
        cancelButton = messageBox.addButton("Cancel simulation", qt.QMessageBox.DestructiveRole)
        keepButton = messageBox.addButton("Keep running", qt.QMessageBox.RejectRole)
        messageBox.setDefaultButton(keepButton)
        messageBox.exec_()
        clicked = messageBox.clickedButton()
        messageBox.deleteLater()
        return clicked == cancelButton

    def __onTrackClicked(self):
        target = self.__outputDir()
        if target is None:
            return
        # Tracking on demand shows what is there; following the newest frame is the player's switch.
        self.__trackSimulation(target, follow=False)

    def __showSimulation(self, simulationDir):
        """Point the Monitoring and Results sections at one run, dropping what they showed of another.

        Whether a run is played is the user's call — the checkbox before it starts, the button after — so
        nothing of the previous run stays on screen to be taken for this one.
        """
        self.simulationDir = Path(simulationDir) if simulationDir else None
        self.playerWidget.clear()
        self.playerWidget.visible = False

        target = self.__outputDir()
        name = self.simulationDir.name if self.simulationDir is not None else "the case folder"
        self.trackButton.setText(f"Track {name} now")
        self.trackButton.enabled = target is not None
        self.trackButton.setToolTip(f"Create the time sequence for the frames written in {target}." if target else "")
        self.__refreshReport()

    def __outputDir(self):
        """Where the run shown writes its frames and logs, or the case folder itself when it has no run."""
        if self.simulationDir is not None:
            return self.logic.outputDir(self.simulationDir)
        return self.caseDir

    def __trackSimulation(self, directory: Path, follow: bool):
        try:
            node, player = self.logic.track(directory, follow=follow)
            self.playerWidget.setPlayer(player)
            self.playerWidget.visible = True
            self.executionWidget.setStatus(
                f"{self.executionWidget.status()} Tracking {player.frameCount} frames.".strip()
            )
        except Exception as error:
            logging.info(f"Not tracking {directory}: {error}")
            self.playerWidget.visible = False
            pending = "No frame written yet — the sequence appears once the first one is."
            self.executionWidget.setStatus(f"{self.executionWidget.status()} {pending}".strip())

    def __onJobStateChanged(self, status, progress, message):
        self.executionWidget.setJobState(status, progress, message)

        if status == "COMPLETED":
            self.__refreshReport()
            if self.trackCheckBox.checked and self.simulationDir is not None:
                # The run's sequence already exists if it was created at submit time; this picks up the
                # last frames it wrote. Nothing to follow any more, so a sequence created here starts off.
                self.__trackSimulation(self.__outputDir(), follow=False)

    def __onJobRemoved(self, cancelled: bool, onCluster: bool):
        self.executionWidget.setRunning(False)
        run, output = self.logic.simulationDir, self.logic.runOutput
        name = run.name if run is not None else (output.name if output is not None else "it")

        if not cancelled:
            # The Job Monitor's unlink: nothing was stopped, only nothing follows the run any more.
            self.executionWidget.setStatus(
                "No longer followed: the job was unlinked in the Job Monitor. It may still be running."
            )
            return

        if not onCluster or output is None:
            self.executionWidget.setStatus(f"Cancelled. What it wrote so far stays in {name}.")
            return

        # Its frames and logs were on the cluster and went with it, so none of them stays on screen, nor its
        # time sequence in the scene: that could not play any more.
        player = self.playerWidget.player
        if player is not None and Path(player.dataset.root) == output:
            self.playerWidget.clear()
            self.playerWidget.visible = False
        self.logic.untrack(output)
        if run is not None and self.simulationDir == run:
            self.__showSimulation(run)
        inputs = f"; {run.name} keeps its inputs" if run is not None else ""
        self.executionWidget.setStatus(
            f"Cancelled. Its folder on the cluster and its time sequence were deleted{inputs}."
        )

    def __onRefreshReportClicked(self):
        self.__refreshReport()

    def __refreshReport(self):
        target = self.__outputDir()
        if target is None:
            return
        self.reportWidget.setResults(self.logic.results(target))

    def __onCreateTablesClicked(self):
        target = self.__outputDir()
        if target is None:
            return
        self.__createTables(target)

    def __createTables(self, target: Path, prefix: str = None):
        # Named after the run rather than after its output, which for a cluster run is a folder named by a uid.
        prefix = prefix or (self.simulationDir.name if self.simulationDir is not None else None)
        created = self.logic.createResultNodes(target, prefix=prefix)
        names = ", ".join(node.GetName() for node in created.values()) or "nothing to add"
        slicer.util.showStatusMessage(f"Tables: {names}", 5000)

    # -- opening a run --------------------------------------------------------------------------------
    def openRun(self, simulationDir=None, outputDir=None, uid: str = None) -> None:
        """Show a run as if it had just run from here: its case and the run itself, its frames as a time
        sequence, its report and its tables; and follow its job again while there is one.

        What the Job Monitor's *Open* ends in (see ``ltrace.slicer.lbpm.open_run``). ``simulationDir`` is the
        run's simNNN, ``outputDir`` where it wrote its frames and logs: the run folder itself, or for a cluster
        run its copy on the share. A job recorded before its run folder was kept names only its output: the
        run is then looked for in the case on screen, and without it the output is shown alone.
        """
        run = Path(simulationDir) if simulationDir else None
        if (run is None or not run.is_dir()) and uid and self.caseDir is not None:
            run = self.logic.findRun(self.caseDir, uid)

        if run is None or not run.is_dir():
            self.__openOutput(Path(outputDir) if outputDir else None, uid)
            return

        if self.caseDir != run.parent:
            self.caseButton.directory = run.parent.as_posix()
        self.__showSimulation(run)

        job = JobManager.jobs.get(uid) if uid else None
        if job is not None:
            self.logic.follow(uid, run)
            self.executionWidget.setJobState(job.status, job.progress, job.message or "")

        output = self.__outputDir()
        self.__trackSimulation(output, follow=job is not None and job.status in ExecutionWidget.ACTIVE_STATES)
        self.__createTables(output)

    def __openOutput(self, output, uid: str = None):
        """Show the output of a run whose own folder is not on this computer."""
        if output is None or not output.is_dir():
            slicer.util.errorDisplay(f"The results of this run are not on this computer any more:\n{output}")
            return

        self.playerWidget.clear()
        self.reportWidget.setResults(self.logic.results(output))

        note = f"Showing {output}: the folder the run was started from was not found."
        job = JobManager.jobs.get(uid) if uid else None
        if job is not None:
            # Followed like any run opened here, so that cancelling it, here or in the Job Monitor, also takes
            # its time sequence away.
            self.logic.follow(uid, output_dir=output)
            self.executionWidget.setJobState(job.status, job.progress, job.message or "")
            note = f"{self.executionWidget.status()} {note}"
        self.executionWidget.setStatus(note)

        self.__trackSimulation(output, follow=job is not None and job.status in ExecutionWidget.ACTIVE_STATES)
        self.__createTables(output, prefix=output.name)

    def cleanup(self):
        super().cleanup()
        self.playerWidget.clear()
        self.logic.stop()


class PoreScaleModellingLogic(LTracePluginLogic):
    jobStateChanged = qt.Signal(str, float, str)
    jobRemoved = qt.Signal(bool, bool)
    """The run's job left the job manager: whether it was cancelled rather than only unlinked, and whether it
    ran on a cluster, whose copy of the run Cancel/Delete deletes."""

    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.uid = None
        self.simulationDir = None
        # Where the followed run writes its frames and logs: the run folder, or a cluster run's copy on the share.
        self.runOutput = None
        self._pending = None

        # Job events arrive on the job manager's monitor thread; a timer hands them to the Qt thread, the
        # same arrangement the Job Monitor uses.
        JobManager.add_observer(self.__onJobEvent)
        self._timer = qt.QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.__drain)
        self._timer.start()

    # -- case -----------------------------------------------------------------------------------------
    @staticmethod
    def configPath(case_dir) -> Path:
        return Path(case_dir) / CONFIG_NAME

    @classmethod
    def loadConfig(cls, case_dir):
        """``(config, created)``: the case's configuration, creating a default one when absent."""
        path = cls.configPath(case_dir)
        if path.is_file():
            return WaterflowConfig.from_file(path), False

        config = WaterflowConfig.default()
        config.path = path
        return config, True

    @classmethod
    def saveConfig(cls, case_dir, config: WaterflowConfig) -> Path:
        return config.write(cls.configPath(case_dir))

    @classmethod
    def readConfigText(cls, case_dir):
        """The configuration file's text as it is on disk now, or ``None`` when there is no file."""
        path = cls.configPath(case_dir)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def describeCase(case_dir: Path, config: WaterflowConfig, created: bool, latest: Path = None) -> str:
        shape = config.domain_shape_zyx()
        parts = []
        parts.append(
            f"{CONFIG_NAME} created with default values — set the image and the domain before running."
            if created
            else f"Loaded {CONFIG_NAME}."
        )
        if shape:
            extent = "×".join(str(size) for size in reversed(shape))
            parts.append(f"Domain {extent} voxels, {config.rank_count()} sub-domains.")
        if latest is not None:
            frames = len(list(PoreScaleModellingLogic.outputDir(latest).glob("vis*")))
            parts.append(f"Latest run: {latest.name} ({frames} frames).")
        return " ".join(parts)

    @staticmethod
    def latestSimulation(case_dir):
        candidates = [
            path
            for path in Path(case_dir).glob(f"{SIMULATION_PREFIX}*")
            if path.is_dir() and SIMULATION_PATTERN.match(path.name)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda path: int(SIMULATION_PATTERN.match(path.name).group(1)))

    @staticmethod
    def nextSimulationDir(case_dir) -> Path:
        """A fresh ``simNNN`` folder, so runs never mix their output."""
        case_dir = Path(case_dir)
        used = [
            int(SIMULATION_PATTERN.match(path.name).group(1))
            for path in case_dir.glob(f"{SIMULATION_PREFIX}*")
            if path.is_dir() and SIMULATION_PATTERN.match(path.name)
        ]
        return case_dir / f"{SIMULATION_PREFIX}{(max(used) + 1) if used else 1:03d}"

    # -- input image ----------------------------------------------------------------------------------
    @staticmethod
    def inputImageName(node):
        """The RAW file name :meth:`writeInputImage` gives ``node``: its name, X, Y and Z sizes and voxel size."""
        imageData = node.GetImageData()
        if imageData is None:
            return None
        x, y, z = imageData.GetDimensions()
        nanometers = int(round(float(node.GetSpacing()[0]) * 1e6))
        return f"{node.GetName()}_{x}_{y}_{z}_{nanometers:05d}nm.raw"

    @staticmethod
    def writeInputImage(node, case_dir, config: WaterflowConfig, ranks: int = 1) -> Path:
        """Write ``node`` as the RAW image LBPM reads and align the configuration with it.

        LBPM reads a headerless 8-bit image plus a description of its size, so the geometry has to be
        transferred into the configuration or the run reads garbage.
        """
        array = slicer.util.arrayFromVolume(node)
        if array is None:
            raise ValueError("The selected node holds no image data.")

        labels = np.unique(array)
        if labels.size > 8:
            raise ValueError(
                f"This image has {labels.size} distinct values. LBPM expects a segmented image: solid, "
                "and one label per fluid."
            )

        case_dir = Path(case_dir)
        case_dir.mkdir(parents=True, exist_ok=True)

        micrometers = float(node.GetSpacing()[0]) * 1000.0
        shape_zyx = array.shape
        target = case_dir / PoreScaleModellingLogic.inputImageName(node)

        array.astype(np.uint8).tofile(target.as_posix())

        # LBPM's own configuration cannot express where this image sits, and its results will inherit
        # nothing from it. Record the placement beside the case so the frames come back on top of the
        # image they were computed from instead of at the world origin.
        CaseGeometry.from_volume_node(node).write(case_dir)

        grid = PoreScaleModellingLogic._processGrid(shape_zyx, ranks)
        config.set("Domain", "Filename", target.name)
        config.set("Domain", "ReadType", "8bit")
        config.set("Domain", "N", [shape_zyx[2], shape_zyx[1], shape_zyx[0]])
        config.set("Domain", "nproc", grid)
        config.set(
            "Domain",
            "n",
            [shape_zyx[2] // grid[0], shape_zyx[1] // grid[1], shape_zyx[0] // grid[2]],
        )
        config.set("Domain", "voxel_length", round(micrometers, 6))
        config.set("Domain", "ReadValues", [int(value) for value in labels])
        config.set("Domain", "WriteValues", list(range(len(labels))))

        return target

    @staticmethod
    def _processGrid(shape_zyx, ranks: int):
        """Split the domain along Z first, as LBPM's own examples do, keeping sub-domains whole."""
        ranks = max(1, int(ranks))
        z = shape_zyx[0]
        while ranks > 1 and z % ranks:
            ranks -= 1
        return [1, 1, ranks]

    # -- execution ------------------------------------------------------------------------------------
    def run(self, case_dir, config: WaterflowConfig, options, container: str = None, binds=None):
        """Copy the case into a fresh ``simNNN`` folder and submit it.

        ``options`` is what the execution section holds — where to run and under which settings; see
        :class:`~ltrace.slicer.widget.execution.ExecutionOptions`. ``container`` and ``binds`` are the
        cluster's own way of running LBPM, from the same settings; see :data:`REMOTE_FIELDS_LBPM`.
        """
        case_dir = Path(case_dir)
        simulation_dir = self.nextSimulationDir(case_dir)
        simulation_dir.mkdir(parents=True)

        try:
            config.write(simulation_dir / CONFIG_NAME)

            geometry = CaseGeometry.read(case_dir)
            if geometry is not None:
                geometry.write(simulation_dir)

            image = config.get_string("Domain", "Filename")
            if image:
                source = case_dir / image
                if not source.is_file():
                    raise FileNotFoundError(f"The input image '{image}' is not in {case_dir}.")
                shutil.copy2(source, simulation_dir / image)

            submission = LBPMDispatcher.submit(
                simulation_dir,
                job_name=f"lbpm-{case_dir.name}-{simulation_dir.name}",
                name=f"LBPM {case_dir.name}/{simulation_dir.name}",
                container=container or None,
                binds=list(binds or []),
                **options.asKwargs(),
            )
        except Exception:
            # Nothing runs from the folder, which was made just above: kept, it would pass for the case's
            # latest run and take its number.
            shutil.rmtree(simulation_dir, ignore_errors=True)
            raise

        self.uid = submission.uid
        self.simulationDir = simulation_dir
        self.runOutput = Path(submission.local_dir) if submission.local_dir else simulation_dir
        self.writeRunRecord(simulation_dir, submission)
        return submission

    @staticmethod
    def writeRunRecord(simulation_dir, submission) -> Path:
        """Note beside the run's inputs where it went. A cluster run writes its output into the copy of this
        folder on the shared drive, and nothing else would remember which copy that is."""
        record = {
            "uid": submission.uid,
            "backend": submission.backend.name,
            "output": submission.local_dir or Path(simulation_dir).as_posix(),
            "run_dir": submission.case_dir,
        }
        path = Path(simulation_dir) / RUN_RECORD_NAME
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def outputDir(simulation_dir) -> Path:
        """Where the run in ``simulation_dir`` writes its frames and logs, as this computer sees it.

        A local run writes into the folder itself. A cluster run writes into its staged copy on the shared
        drive, named by the record :meth:`writeRunRecord` left; a folder without one is its own output.
        """
        simulation_dir = Path(simulation_dir)
        try:
            output = json.loads((simulation_dir / RUN_RECORD_NAME).read_text(encoding="utf-8")).get("output")
        except (OSError, ValueError, AttributeError):
            output = None
        return Path(output) if output else simulation_dir

    def cancel(self):
        """Cancel/Delete the run: see :meth:`LBPMDispatcher.cancel`. Raises when the job monitor is not running."""
        if self.uid:
            LBPMDispatcher.cancel(self.uid)

    def follow(self, uid: str, simulation_dir=None, output_dir=None) -> None:
        """Report the job ``uid`` from now on, as the job of the run in ``simulation_dir`` writing into
        ``output_dir``: what :meth:`run` sets up for a run started here, for one opened from the Job Monitor.
        A run opened from its output alone has no ``simulation_dir``."""
        self.uid = uid
        self.simulationDir = Path(simulation_dir) if simulation_dir else None
        output = output_dir or (self.outputDir(simulation_dir) if simulation_dir else None)
        self.runOutput = Path(output) if output else None
        self._pending = None

    def followsClusterRun(self) -> bool:
        """Whether the run followed went to a cluster, whose copy of it Cancel/Delete deletes."""
        return _ranOnCluster(JobManager.jobs.get(self.uid) if self.uid else None)

    @staticmethod
    def findRun(case_dir, uid: str):
        """The run of ``case_dir`` that was submitted as the job ``uid``, from the records its runs left."""
        for path in Path(case_dir).glob(f"{SIMULATION_PREFIX}*"):
            if not (path.is_dir() and SIMULATION_PATTERN.match(path.name)):
                continue
            try:
                record = json.loads((path / RUN_RECORD_NAME).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(record, dict) and record.get("uid") == uid:
                return path
        return None

    # -- monitoring -----------------------------------------------------------------------------------
    def track(self, directory, follow: bool = False):
        """Register the folder for monitoring and surface its frames as a 4D node.

        Tracking a folder that is already tracked returns the sequence showing it, refreshed — a run that
        gained frames is the same run, and a second node for it would only be a second thing to keep in
        sync. ``follow`` seeds a sequence being created; after that the player's own *Follow latest* owns
        it, and re-tracking never overrides what the user set there.
        """
        directory = Path(directory)
        manager = virtual_folder.manager()
        if manager.get(directory) is None:
            manager.register(
                virtual_folder.VirtualFolder(root=directory, deferred=True, monitored=True, pattern=FRAME_PATTERN),
                sync=False,
            )

        fourd = get_fourd_manager()
        existing = fourd.find(directory, pattern=FRAME_PATTERN, variable="phase")
        if existing is None:
            # A sequence restored with the project has no player until it is shown: it gets one, rather than a
            # second node beside it.
            for node in fourd.nodes(directory, pattern=FRAME_PATTERN, variable="phase"):
                existing = fourd.attach(node)
                if existing is not None:
                    break
        if existing is not None:
            existing.refreshFrames()
            return existing.node, existing

        return get_fourd_manager().create(directory, pattern=FRAME_PATTERN, variable="phase", follow=follow)

    @staticmethod
    def untrack(directory) -> int:
        """Undo :meth:`track` for a folder that was deleted: remove the 4D nodes of its frames, their
        previews, and its monitoring. Returns how many 4D nodes were removed.

        A sequence of a deleted folder cannot play: the frames it never read are gone, and the previews it
        did read are dropped as soon as it sees their source missing.
        """
        directory = Path(directory)
        fourd = get_fourd_manager()

        # Every node of the folder, also one restored with the project that was never shown and so has no player.
        nodes = fourd.nodes(directory)
        for node in nodes:
            player = fourd.player(node)
            # Closed first: its builder thread reads the previews that are deleted next.
            fourd.close(node)
            if player is not None:
                player.cache.delete()
            slicer.mrmlScene.RemoveNode(node)

        virtual_folder.manager().unregister(directory, remove_nodes=True)
        return len(nodes)

    # -- results --------------------------------------------------------------------------------------
    @staticmethod
    def results(directory) -> LBPMResults:
        return LBPMResults.load(directory)

    @staticmethod
    def createResultNodes(directory, prefix: str = None):
        """Tables of the logs in ``directory``, named after ``prefix``: made once, then updated."""
        return build_result_nodes(directory, prefix=prefix).get("nodes", {})

    # -- job events -----------------------------------------------------------------------------------
    def __onJobEvent(self, job, event):
        if self.uid and job.uid == self.uid:
            self._pending = (job.status, job.progress or 0, job.message or "", event == JOB_DELETED, _ranOnCluster(job))

    def __drain(self):
        if self._pending is None:
            return
        status, progress, message, removed, onCluster = self._pending
        self._pending = None

        if removed:
            # Cancel/Delete marks the job cancelled just before removing it; the Job Monitor's unlink removes
            # it as it is, still running for all anyone knows.
            self.uid = None
            self.jobRemoved.emit(status == JOB_STATE_CANCELLED, onCluster)
            return
        self.jobStateChanged.emit(status, float(progress), message)

    def stop(self):
        if self._timer is not None:
            self._timer.stop()


def _ranOnCluster(job) -> bool:
    return job is not None and (job.details or {}).get("scheduler") == SlurmScheduler.name
