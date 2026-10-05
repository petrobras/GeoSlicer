"""Where to run, how big, and the button that starts it.

Every module that hands work to a backend asks the same three questions and then shows the same progress
bar, so the section is built once here. A module supplies what is its own — which backends exist, how
``auto`` resolves, where the settings are kept — connects two signals, and is done.

    self.execution = ExecutionWidget(
        backends=dispatcher.available_backends,     # anything with kind/name/available/describe()
        resolve=dispatcher.resolve_backend,         # so 'Automatic' can say what it would pick
        settings=ExecutionSettings("MyTool", aliases={"binary": "MyTool/BinaryPath"}),
        defaults={"partition": "gpu"},              # what this tool falls back to, until a user says otherwise
        toolName="MyTool",
    )
    self.execution.runClicked.connect(self.__onRunClicked)
    ...
    job = dispatcher.submit(case_dir, **self.execution.options().asKwargs())

What is asked of every run stays on screen; what belongs to one machine — its program, its modules, its
queue — is behind *Settings…*, which edits the backend that is selected and remembers the answers per
backend.
"""

import logging

import qt
import slicer

from ltrace.remote.backends import BACKEND_AUTO, BACKEND_LOCAL, BACKEND_REMOTE
from ltrace.remote.constants import (
    JOB_STATE_DEPLOYING,
    JOB_STATE_IDLE,
    JOB_STATE_PENDING,
    JOB_STATE_RUNNING,
)
from ltrace.slicer import ui

from .dialog import ExecutionSettingsDialog
from .options import LOCAL_FIELDS, REMOTE_FIELDS, ExecutionOptions, ExecutionSettings, fields_for, with_defaults

AUTOMATIC_LABEL = "Automatic (cluster if available)"


class ExecutionWidget(qt.QWidget):
    runClicked = qt.Signal()
    cancelClicked = qt.Signal()
    backendChanged = qt.Signal(str)

    ACTIVE_STATES = (JOB_STATE_PENDING, JOB_STATE_RUNNING, JOB_STATE_DEPLOYING)

    def __init__(
        self,
        backends,
        settings: ExecutionSettings,
        resolve=None,
        localFields=LOCAL_FIELDS,
        remoteFields=REMOTE_FIELDS,
        defaults=None,
        runText="Run",
        runTooltip="",
        toolName="",
        namePrefix="Execution",
        parent=None,
    ):
        """
        :param backends: callable returning the backends to offer, each with ``kind``, ``name``,
            ``available``, ``describe()`` and optionally ``host``.
        :param settings: where the per-backend settings are kept.
        :param resolve: callable turning ``auto`` into a concrete backend, so *Settings…* can show which
            one it would pick. Without it, ``auto`` has no settings to show.
        :param defaults: what this module's fields fall back to, by field key, e.g.
            ``{"partition": "gpu", "nodes": 2}``. Applies until the backend has an answer of its own, and
            is what *Restore defaults* goes back to.
        :param toolName: what is being run, for the dialog's title ("Solver settings — atena").
        """
        super().__init__(parent)

        self._backendsProvider = backends
        self._resolve = resolve
        self._settings = settings
        self._localFields = with_defaults(localFields, defaults)
        self._remoteFields = with_defaults(remoteFields, defaults)

        unknown = set(defaults or {}) - {item.key for item in self._localFields + self._remoteFields}
        if unknown:
            raise ValueError(f"No field to give a default to: {', '.join(sorted(unknown))}")
        self._toolName = toolName
        self._prefix = namePrefix
        self._backends = {}

        self.__setup(runText, runTooltip)
        self.refreshBackends()

    # -- construction -------------------------------------------------------------------------------
    def __setup(self, runText, runTooltip):
        layout = qt.QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.backendComboBox = qt.QComboBox()
        self.backendComboBox.objectName = f"{self._prefix} Backend ComboBox"
        self.backendComboBox.setToolTip(
            "Where to run. 'Automatic' prefers a configured cluster and falls back to this computer."
        )
        self.backendComboBox.currentIndexChanged.connect(self.__onBackendChanged)

        self.settingsButton = qt.QPushButton("Settings…")
        self.settingsButton.objectName = f"{self._prefix} Settings Button"
        self.settingsButton.clicked.connect(self.openSettings)

        backendLayout = qt.QHBoxLayout()
        backendLayout.setContentsMargins(0, 0, 0, 0)
        backendLayout.addWidget(self.backendComboBox, 1)
        backendLayout.addWidget(self.settingsButton)
        layout.addRow("Run on:", backendLayout)

        self.ranksSpinBox = qt.QSpinBox()
        self.ranksSpinBox.objectName = f"{self._prefix} Ranks SpinBox"
        self.ranksSpinBox.setRange(1, 4096)
        self.ranksSpinBox.setValue(8)
        self.ranksSpinBox.setToolTip("How many processes to run in parallel. On a cluster this drives the task count.")
        layout.addRow("Processes:", self.ranksSpinBox)

        self.gpuCheckBox = qt.QCheckBox("Use GPUs")
        self.gpuCheckBox.objectName = f"{self._prefix} GPU CheckBox"
        self.gpuCheckBox.setToolTip(
            "Run on GPUs where the backend offers them. On a cluster this also asks for the GPU partition."
        )
        layout.addRow(self.gpuCheckBox)

        self.runButton = ui.ApplyButton(onClick=self.__onRunClicked, text=runText, tooltip=runTooltip)
        self.runButton.objectName = f"{self._prefix} Run Button"

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.objectName = f"{self._prefix} Cancel Button"
        self.cancelButton.enabled = False
        self.cancelButton.clicked.connect(self.__onCancelClicked)

        runLayout = qt.QHBoxLayout()
        runLayout.addWidget(self.runButton)
        runLayout.addWidget(self.cancelButton)
        layout.addRow(runLayout)

        self.progressBar = qt.QProgressBar()
        self.progressBar.objectName = f"{self._prefix} Progress Bar"
        self.progressBar.visible = False
        layout.addRow(self.progressBar)

        self.statusLabel = qt.QLabel()
        self.statusLabel.objectName = f"{self._prefix} Status Label"
        self.statusLabel.setWordWrap(True)
        layout.addRow(self.statusLabel)

    @property
    def settings(self) -> ExecutionSettings:
        """Where the per-backend settings are kept, for a module that reads or seeds them itself."""
        return self._settings

    # -- backends -----------------------------------------------------------------------------------
    def refreshBackends(self) -> None:
        """Ask for the backends again, keeping the selection when it is still offered.

        Availability is not fixed: pointing the settings dialog at a program, or adding an account, turns
        a backend from unavailable into the one that will run the job.
        """
        current = self.backendComboBox.currentData

        wasBlocked = self.backendComboBox.blockSignals(True)
        self.backendComboBox.clear()
        self.backendComboBox.addItem(AUTOMATIC_LABEL, BACKEND_AUTO)

        self._backends = {}
        for backend in self._backendsProvider() or []:
            self._backends[backend.name] = backend
            label = backend.describe() if backend.available else f"{backend.name} — not available"
            self.backendComboBox.addItem(label, backend.name)

        if current:
            index = self.backendComboBox.findData(current)
            if index >= 0:
                self.backendComboBox.setCurrentIndex(index)
        self.backendComboBox.blockSignals(wasBlocked)

        self.__refreshSettingsButton()

    def selectedName(self) -> str:
        """Name of the selected backend, or ``auto``."""
        return self.backendComboBox.currentData or BACKEND_AUTO

    def scopeBackend(self):
        """The backend the settings belong to: the selected one, or the one ``auto`` would pick."""
        name = self.selectedName()
        if name != BACKEND_AUTO:
            return self._backends.get(name)

        if self._resolve is None:
            return None

        try:
            return self._resolve(BACKEND_AUTO)
        except Exception as error:  # nothing is configured, or nothing is installed
            logging.info(f"No backend to configure: {error}")
            return None

    def fieldsFor(self, backend):
        return fields_for(getattr(backend, "kind", BACKEND_REMOTE), local=self._localFields, remote=self._remoteFields)

    def settingsValues(self, backend=None) -> dict:
        """Everything stored for a backend, tool-specific fields included."""
        backend = backend or self.scopeBackend()
        if backend is None:
            return {}
        return self._settings.values(backend.name, self.fieldsFor(backend))

    # -- the run ------------------------------------------------------------------------------------
    def options(self) -> ExecutionOptions:
        """What was chosen here, folded together with the settings of the backend it will run on."""
        name = self.selectedName()
        backend = self._backends.get(name) if name != BACKEND_AUTO else None

        if backend is None:
            kind, target = BACKEND_AUTO, None
        elif backend.kind == BACKEND_LOCAL:
            kind, target = BACKEND_LOCAL, None
        else:
            kind, target = BACKEND_REMOTE, backend.name

        return ExecutionOptions.compose(
            kind=kind,
            target=target,
            ranks=self.ranksSpinBox.value,
            gpu=self.gpuCheckBox.checked,
            values=self.settingsValues(),
        )

    def ranks(self) -> int:
        return int(self.ranksSpinBox.value)

    def setRanks(self, ranks: int) -> None:
        self.ranksSpinBox.setValue(max(1, int(ranks)))

    def gpu(self) -> bool:
        return bool(self.gpuCheckBox.checked)

    # -- reporting ----------------------------------------------------------------------------------
    def status(self) -> str:
        return self.statusLabel.text

    def setStatus(self, text: str) -> None:
        self.statusLabel.setText(text or "")

    def setProgress(self, value) -> None:
        self.progressBar.setValue(int(value or 0))

    def setRunning(self, running: bool) -> None:
        """Show the progress bar and offer *Cancel* while something of ours is in flight."""
        self.progressBar.visible = bool(running)
        self.setCancelEnabled(running)

    def setCancelEnabled(self, enabled: bool) -> None:
        """Offer *Cancel*, or stop offering it once asking again would mean nothing."""
        self.cancelButton.enabled = bool(enabled)

    def setJobState(self, status: str, progress=0.0, message: str = "") -> None:
        """Report a managed job's state the way every job-dispatching module shows it."""
        self.progressBar.visible = status not in ("", JOB_STATE_IDLE)
        self.setProgress(progress)
        self.setStatus(f"[{status}] {message}" if message else f"[{status}]")
        self.setCancelEnabled(status in self.ACTIVE_STATES)

    # -- settings dialog ----------------------------------------------------------------------------
    def openSettings(self) -> None:
        backend = self.scopeBackend()
        if backend is None:
            slicer.util.warningDisplay(
                "There is nothing to configure yet: no cluster is registered and no local program was "
                "found. Add an account, or select this computer to point it at the program to run."
            )
            return

        dialog = ExecutionSettingsDialog(
            title=f"{self._toolName} settings — {backend.name}".strip(),
            fields=self.fieldsFor(backend),
            values=self.settingsValues(backend),
            info=self.describeBackend(backend),
            parent=self,
        )
        if not dialog.exec_():
            return

        self._settings.update(backend.name, self.fieldsFor(backend), dialog.values())
        # A program named here is what decides whether the local backend can run at all, so the list has
        # to be asked again rather than kept as it was drawn.
        self.refreshBackends()

    def describeBackend(self, backend) -> str:
        """The part of a backend the settings cannot change, so the dialog says what it is editing."""
        reason = getattr(backend, "reason", "") or "not available"
        lines = [backend.describe() if backend.available else f"{backend.name} — {reason}"]

        host = getattr(backend, "host", None)
        address = getattr(host, "address", "")
        if address:
            lines.append(f"{getattr(host, 'username', '')}@{address}:{getattr(host, 'port', 22)}")

        get_storage = getattr(host, "get_storage", None)
        if callable(get_storage):
            storage = get_storage()
            jobs = storage.remote_dir("geoslicer_jobs")
            lines.append(f"Jobs folder on the cluster: {jobs.as_posix()}")
            lines.append(f"Jobs folder on this computer: {storage.to_local(jobs)}")

        opening = getattr(host, "opening_command", "") or ""
        if opening:
            lines.append(f"Runs before every job: {opening}")

        if self.selectedName() == BACKEND_AUTO:
            lines.insert(0, f"'Automatic' currently resolves to {backend.name}.")

        return "\n".join(lines)

    # -- events -------------------------------------------------------------------------------------
    def __onRunClicked(self):
        self.runClicked.emit()

    def __onCancelClicked(self):
        self.cancelClicked.emit()

    def __onBackendChanged(self, index):
        self.__refreshSettingsButton()
        self.backendChanged.emit(self.selectedName())

    def __refreshSettingsButton(self):
        backend = self.scopeBackend()
        if backend is None:
            self.settingsButton.setToolTip(
                "Settings of the machine that will run this. Nothing is configured to run it yet."
            )
            return

        local = getattr(backend, "kind", "") == BACKEND_LOCAL
        needs = "the program to run, its modules." if local else "queue, account, walltime."
        self.settingsButton.setToolTip(
            f"Settings for {backend.name} — what {'this computer' if local else 'the cluster'} needs: {needs}"
        )
