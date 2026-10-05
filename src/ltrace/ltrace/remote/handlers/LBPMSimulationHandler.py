"""Job handler for an LBPM simulation, identical for a cluster and for this machine.

The backend is a :class:`~ltrace.lbpm.scheduler.Scheduler` (SLURM or local) and the transport is whatever
client the host provides (SSH or subprocess). Everything else — deployment, submission, polling, progress
reporting, cancellation, collection — is shared, which is the whole point: a local run behaves like a
cluster run, including surviving an application restart.
"""

import logging
import shlex
import shutil
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Optional

from ltrace.lbpm.scheduler import (
    LOG_NAME,
    SCRIPT_NAME,
    STAGING_SUBFOLDER,
    STATE_CANCELLED,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_PENDING,
    STATE_RUNNING,
    STATE_UNKNOWN,
    LBPMJobSpec,
    Scheduler,
    SlurmScheduler,
    parse_progress,
    progress_command,
)
from ltrace.remote.constants import (
    JOB_EVENT_CANCEL,
    JOB_EVENT_COLLECT,
    JOB_EVENT_DEPLOY,
    JOB_EVENT_DISCONNECTED,
    JOB_EVENT_PROGRESS,
    JOB_EVENT_START,
    JOB_STATE_CANCELLED,
    JOB_STATE_COMPLETED,
    JOB_STATE_DEPLOYING,
    JOB_STATE_FAILED,
    JOB_STATE_NOTCONNECTED,
    JOB_STATE_PENDING,
    JOB_STATE_RUNNING,
    JOB_TERMINAL_STATES,
)
from ltrace.remote.paths import storage_for
from ltrace.remote.utils import SlurmJobStatusMixin, is_benign_scancel_error

JOB_TYPE = "lbpm"
MAX_UNKNOWN_POLLS = 12
"""How long an unrecognizable status is tolerated before the job is called failed (12 polls ~ 1 minute)."""


class LBPMSimulationHandler(SlurmJobStatusMixin):
    def __init__(
        self,
        spec: LBPMJobSpec,
        scheduler: Scheduler,
        collector: Callable[[Dict], None] = None,
        expected_frames: int = None,
        timeout_seconds: int = 600,
        source_dir: str = None,
        output_dir: str = None,
    ) -> None:
        """``source_dir`` is the folder that was submitted and ``output_dir`` where the run writes its frames
        and logs, both as this computer sees them: the spec only says where the run happens, which for a
        cluster is a path on the cluster. They are kept in the job's details, so a restored job can still be
        opened."""
        super().__init__(timeout_seconds=timeout_seconds)
        self.spec = spec
        self.scheduler = scheduler
        self.collector = collector
        self.expected_frames = expected_frames
        self.source_dir = source_dir
        self.output_dir = output_dir
        self.job_id: Optional[str] = None
        self.frames = 0
        self._unknown_polls = 0

        self.__actions = {
            JOB_EVENT_DEPLOY: self.deploy,
            JOB_EVENT_START: self.start,
            JOB_EVENT_PROGRESS: self.progress,
            JOB_EVENT_COLLECT: self.collect,
            JOB_EVENT_CANCEL: self.cancel,
            JOB_EVENT_DISCONNECTED: self.disconnected,
        }

    # -- dispatch -------------------------------------------------------------------------------------
    def __call__(self, caller, uid: str, action: str, **kwargs) -> None:
        handler = self.__actions.get(action)
        if handler is None:
            return
        handler(caller, uid, kwargs.get("client"))

    # -- lifecycle ------------------------------------------------------------------------------------
    def deploy(self, caller, uid: str, client: Any = None) -> None:
        """Write the run script next to the case, then hand over to submission."""
        if client is None:
            self.disconnected(caller, uid, client)
            return

        try:
            script = self.scheduler.script(self.spec)
            directory = self.spec.directory

            output = client.run_command(f"mkdir -p {directory}")
            if output and output["stderr"]:
                raise RuntimeError(output["stderr"])

            if script:
                # A quoted heredoc: the script must arrive verbatim, with no shell expansion on the way.
                write = f"cat > {directory}/{SCRIPT_NAME} <<'LBPM_SCRIPT_EOF'\n{script}LBPM_SCRIPT_EOF"
                output = client.run_command(write)
                if output and output["stderr"]:
                    raise RuntimeError(output["stderr"])

            caller.set_state(
                uid,
                JOB_STATE_DEPLOYING,
                0,
                message=f"Prepared {self.spec.job_name} in {directory}.",
                details={
                    "case_dir": directory,
                    "scheduler": self.scheduler.name,
                    "spec": self.spec.to_dict(),
                    **self._recordedDirs(),
                },
            )
            caller.schedule(uid, JOB_EVENT_START)
        except Exception as error:
            logging.exception("LBPM deployment failed")
            caller.set_state(
                uid,
                JOB_STATE_FAILED,
                0,
                message="Could not prepare the simulation folder.",
                traceback=repr(error),
                end_time=datetime.now().timestamp(),
            )

    def start(self, caller, uid: str, client: Any = None) -> None:
        if client is None:
            self.disconnected(caller, uid, client)
            return

        now = datetime.now().timestamp()
        try:
            output = client.run_command(self.scheduler.submit_command(self.spec), verbose=True)
            self.job_id = self.scheduler.parse_submit(output["stdout"])

            if not self.job_id:
                caller.set_state(
                    uid,
                    JOB_STATE_FAILED,
                    0,
                    message="The simulation could not be submitted.",
                    traceback=output,
                    start_time=now,
                    end_time=now,
                )
                return

            self.slurm_job_ids = [self.job_id]
            caller.set_state(
                uid,
                JOB_STATE_PENDING,
                0,
                message=f"Submitted as {self.job_id}. Waiting for it to start.",
                start_time=now,
                details={
                    "job_id": self.job_id,
                    "case_dir": self.spec.directory,
                    "scheduler": self.scheduler.name,
                    "expected_frames": self.expected_frames,
                    "spec": self.spec.to_dict(),
                    **self._recordedDirs(),
                },
            )
            caller.persist(uid)
            caller.schedule(uid, JOB_EVENT_PROGRESS)
        except Exception as error:
            logging.exception("LBPM submission failed")
            caller.set_state(
                uid,
                JOB_STATE_FAILED,
                0,
                message="The simulation could not be submitted.",
                traceback=repr(error),
                start_time=now,
                end_time=now,
            )

    def progress(self, caller, uid: str, client: Any = None) -> None:
        """Poll the backend for the job state and the case folder for how far it has got."""
        if client is None:
            self.disconnected(caller, uid, client)
            return

        if not self.job_id:
            caller.schedule(uid, JOB_EVENT_START)
            return

        try:
            status = client.run_command(self.scheduler.status_command(self.job_id, self.spec))
            state = self.scheduler.parse_status(status["stdout"], status["stderr"])
            counters = self._readCounters(client)
            self._unknown_polls = 0 if state != STATE_UNKNOWN else self._unknown_polls + 1
        except Exception as error:
            self.disconnected(caller, uid, client, error=error)
            return

        percent, message = self._describeProgress(counters)

        if state in (STATE_RUNNING, STATE_PENDING) or (
            state == STATE_UNKNOWN and self._unknown_polls <= MAX_UNKNOWN_POLLS
        ):
            caller.set_state(
                uid,
                JOB_STATE_RUNNING if state == STATE_RUNNING else JOB_STATE_PENDING,
                percent,
                message=message,
                details=counters,
            )
            caller.schedule(uid, JOB_EVENT_PROGRESS)
            return

        now = datetime.now().timestamp()

        if state == STATE_COMPLETED:
            frames = counters.get("frames", 0)
            caller.set_state(
                uid,
                JOB_STATE_COMPLETED,
                100,
                message=f"Simulation finished: {frames} frames written.",
                end_time=now,
                details=counters,
            )
            # Not collected from here: collecting puts the results in the scene, which only the main thread
            # may touch. The Job Monitor's Open does it, and the module that started the run refreshes itself.
            return

        if state == STATE_CANCELLED:
            caller.set_state(uid, JOB_STATE_CANCELLED, percent, message="Simulation cancelled.", end_time=now)
            return

        caller.set_state(
            uid,
            JOB_STATE_FAILED,
            percent,
            message="The simulation stopped before finishing. Check its log.",
            traceback=self._readLog(client),
            end_time=now,
            details=counters,
        )

    def collect(self, caller, uid: str, client: Any = None) -> None:
        """Hand the run to whoever shows it: the job's details, with its uid, its state and where its folders
        are on this computer (``source_dir`` and ``output_dir``)."""
        if self.collector is None:
            return

        job = caller.jobs.get(uid)
        details = dict(job.details or {}) if job else {}
        details.setdefault("case_dir", self.spec.directory)
        details.update(self._localDirs(job.host if job else None))
        details["uid"] = uid
        details["status"] = job.status if job else None

        try:
            self.collector(details)
        except Exception:
            logging.exception("Collecting the LBPM results failed")

    def cancel(self, caller, uid: str, client: Any = None) -> None:
        """Cancel/Delete: stop the run, drop the job and delete the copy of the case a cluster run was given.

        A run that could not be stopped keeps its entry, flagged, so that it can be cancelled again once its
        host answers: the entry is the only thing that still knows where its folder is. A local run ran in
        the case folder itself, which belongs to the user, so nothing of it is deleted.
        """
        job = caller.jobs.get(uid)
        if job is None:
            return

        # A finished run has nothing left to stop, and its pid may already belong to another process.
        if self.job_id and job.status not in JOB_TERMINAL_STATES:
            reason = self._stop(client)
            if reason:
                caller.set_state(
                    uid,
                    JOB_STATE_NOTCONNECTED,
                    message="The simulation could not be cancelled.",
                    traceback={"cancel": reason},
                )
                return

        # Before the job goes, so whoever follows it can tell a cancel from the Job Monitor's unlink.
        caller.set_state(uid, JOB_STATE_CANCELLED, message="Simulation cancelled.", end_time=datetime.now().timestamp())
        caller.remove(uid)
        self._deleteStagedCopy(job.host, client)

    # -- helpers --------------------------------------------------------------------------------------
    def _recordedDirs(self) -> Dict[str, str]:
        dirs = {"source_dir": self.source_dir, "output_dir": self.output_dir}
        return {key: value for key, value in dirs.items() if value}

    def _localDirs(self, host) -> Dict[str, Optional[str]]:
        """Where the run's folders are on this computer, also for a job recorded before they were kept."""
        if not isinstance(self.scheduler, SlurmScheduler):
            # A local run happens in the folder it was submitted from.
            return {
                "source_dir": self.source_dir or self.spec.directory,
                "output_dir": self.output_dir or self.spec.directory,
            }

        output = self.output_dir
        if output is None and host is not None:
            # The staged copy, through the share the cluster writes it on.
            output = storage_for(host).to_local(self.spec.directory).as_posix()
        return {"source_dir": self.source_dir, "output_dir": output}

    def _stop(self, client) -> Optional[str]:
        """Why the run could not be stopped, or ``None`` once it is not running any more."""
        if client is None:
            return "No connection to the host: the simulation could not be cancelled."

        try:
            output = client.run_command(self.scheduler.cancel_command(self.job_id, self.spec))
        except Exception as error:
            return repr(error)

        stderr = (output or {}).get("stderr", "") or ""
        # A run that ended meanwhile is stopped all the same: scancel then says its job id is invalid, and
        # kill that there is no such process.
        if is_benign_scancel_error(stderr) or "no such process" in stderr.lower():
            return None
        return stderr

    def _stagedCopy(self) -> Optional[PurePosixPath]:
        """The copy of the case a cluster run was started in, as the cluster sees it, or ``None``.

        Only a folder shaped like the ones the dispatcher stages — named by a uid, in the staging subfolder —
        is returned, so a spec that points anywhere else is never deleted. A local run has none.
        """
        if not isinstance(self.scheduler, SlurmScheduler):
            return None

        directory = PurePosixPath(self.spec.directory)
        if directory.parent.name != STAGING_SUBFOLDER:
            return None
        try:
            uuid.UUID(directory.name)
        except ValueError:
            return None
        return directory

    def _deleteStagedCopy(self, host, client) -> None:
        directory = self._stagedCopy()
        if directory is None:
            return

        try:
            # On the cluster: what the run wrote there belongs to the cluster account, and this computer may
            # not be allowed to delete it through the share.
            output = client.run_command(f"rm -rf {shlex.quote(directory.as_posix())}")
            stderr = (output or {}).get("stderr", "")
            if not stderr:
                return
            logging.warning(f"Could not delete {directory} on the cluster: {stderr}")
        except Exception as error:
            logging.warning(f"Could not delete {directory} on the cluster: {error!r}")

        shutil.rmtree(storage_for(host).to_local(directory), ignore_errors=True)

    def _readCounters(self, client) -> Dict[str, int]:
        output = client.run_command(progress_command(self.spec))
        counters = parse_progress(output["stdout"])
        self.frames = counters.get("frames", self.frames)
        return counters

    def _describeProgress(self, counters: Dict[str, int]):
        frames = counters.get("frames", 0)
        rows = counters.get("timelog", 0)

        if self.expected_frames:
            percent = int(min(99, max(1, 100 * frames / self.expected_frames)))
            written = f"{frames} of about {self.expected_frames} frames written"
        else:
            percent = 50 if frames else 5
            written = f"{frames} frames written"

        steady = f", {max(0, rows - 1)} steady points" if rows else ""
        return percent, f"Running: {written}{steady}."

    def _readLog(self, client) -> Dict[str, str]:
        try:
            output = client.run_command(f"tail -n 60 {self.spec.directory}/{LOG_NAME}")
            return {LOG_NAME: output["stdout"]} if output["stdout"] else {}
        except Exception:
            return {}

    def _post_status_update(self, job_manager, uid: str, client: Any, jobstatus: list) -> None:
        """Unused: this handler polls through its scheduler rather than through ``sacct`` directly."""
        return
