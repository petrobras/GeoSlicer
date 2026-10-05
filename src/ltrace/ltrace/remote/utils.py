import json
import logging
from pathlib import Path, PurePosixPath
import re
from typing import Any, Callable
from datetime import datetime
import time

from ltrace.slicer.app import getApplicationVersion
from ltrace.remote import errors
from ltrace.remote.paths import ClusterStorage
from ltrace.remote.constants import (
    DISCONNECT_BACKOFF_MAX_SECONDS,
    JOB_EVENT_PROGRESS,
    JOB_POLL_INTERVAL_SECONDS,
    JOB_STATE_CANCELLED,
    JOB_STATE_COMPLETED,
    JOB_STATE_FAILED,
    JOB_STATE_IDLE,
    JOB_STATE_NOTCONNECTED,
    JOB_STATE_PENDING,
    JOB_STATE_RUNNING,
    JOB_TERMINAL_STATES,
)


def argstring(params):
    cli_kwargs = []
    for key, value in params.items():
        if value is None:
            continue

        if isinstance(value, (list, tuple)):
            str_value = ",".join([str(v) for v in value])
        else:
            str_value = str(value)

        # handle a case where a string contains a json structure
        if str_value.startswith("{") and str_value.endswith("}"):
            try:
                # escape all double quotes and single quotes
                str_value = str_value.replace('"', '\\"').replace("'", '\\"')

                json.loads(str_value)
            except json.JSONDecodeError:
                pass

        if " " in str_value and not str_value.startswith('"'):
            str_value = rf'"{str_value}"'

        suffix = "--" if len(key) > 1 else "-"
        cli_kwargs.append(f"{suffix}{key} {str_value}")

    kwargs = " ".join(cli_kwargs)

    return kwargs


def remote_hash(client, location: Path):
    out = client.run_command(f'md5sum "{location}"')

    if len(out["stderr"]) > 0:
        logging.error(f"Error during hash check: {out['stderr']}")
        raise TimeoutError()

    tokens = out["stdout"].split("  ")
    return tokens[0]


def sacct(client, jobs: list):
    """Get job information from slurm
    client: connection
    jobs: list of job ids
    """
    import logging

    if not jobs:
        return []

    job_id = ",".join(jobs)
    output = client.run_command(f"sacct -P -ojobid,state,elapsed,start,end -j{job_id}")

    if len(output["stderr"]) > 0:
        logging.error("Error during sacct: ", output["stderr"])
        raise RuntimeError(output["stderr"])

    try:
        lines = output["stdout"].strip().split("\n")
        header = lines[0].split("|")
        data = [line.split("|") for line in lines[1:]]
        jobs = [{header[i].lower(): value for i, value in enumerate(row)} for row in data]
        return jobs
    except IndexError as e:
        content = output["stdout"]
        logging.info(f"Unable to parse sacct output. Returning empty list. Received:\n{content}")
        raise RuntimeError(e)
    except Exception as e:
        logging.error(f"Error during sacct parsing: {repr(e)}")
        raise RuntimeError(e)


def any_running(jobs: list):
    """Check if any jobs are running
    jobs: list of job dictionaries
    """
    if not jobs:
        raise RuntimeError("Job list is empty")

    for job in jobs:
        if job["state"] == JOB_STATE_RUNNING:
            return True
    return False


def all_complete(jobs: list):
    """Check if all jobs are complete
    jobs: list of job dictionaries
    """
    if not jobs:
        raise RuntimeError("Job list is empty")

    for job in jobs:
        if job["state"] != JOB_STATE_COMPLETED:
            return False
    return True


def any_failed(jobs: list):
    """Check if any jobs failed
    jobs: list of job dictionaries
    """
    if not jobs:
        raise RuntimeError("Job list is empty")

    for job in jobs:
        if job["state"] == JOB_STATE_FAILED:
            return True
    return False


def all_failed(jobs: list):
    """Check if all jobs failed
    jobs: list of job dictionaries
    """
    if not jobs:
        raise RuntimeError("Job list is empty")

    for job in jobs:
        if job["state"] != JOB_STATE_FAILED:
            return False
    return True


def all_done(jobs: list):
    """Check if all jobs are done
    jobs: list of job dictionaries
    """
    if not jobs:
        raise RuntimeError("Job list is empty")

    for job in jobs:
        state = job["state"]
        if state != JOB_STATE_COMPLETED and state != JOB_STATE_FAILED and JOB_STATE_CANCELLED not in state:
            return False
    return True


# scancel writes to stderr for job ids that slurm no longer holds. None of
# these mean the connection or the cancellation is broken: the remote job is
# simply already gone, which is exactly the outcome a cancel asks for.
BENIGN_SCANCEL_PATTERNS = (
    "invalid job id",
    "already completing or completed",
    "already completed",
    "already finished",
    "job/step already completing or completed",
)


def is_benign_scancel_error(stderr: str) -> bool:
    """True when every line scancel wrote to stderr only says the job is already gone.

    Treating those as failures marks a job GHOST/NOT CONNECTED over a perfectly
    healthy connection, and the resulting state is one the user can no longer
    cancel — so the entry becomes impossible to remove.
    """
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]

    if not lines:
        return True

    return all(any(pattern in line.lower() for pattern in BENIGN_SCANCEL_PATTERNS) for line in lines)


def try_scancel(client, job_ids) -> "str | None":
    """Cancel remote slurm jobs, reporting only failures that really are failures.

    Returns None when the remote jobs are gone (cancelled now, or already
    finished), or a reason string when the cancellation could not be confirmed
    and the local entry would no longer mirror a known remote state.
    """
    ids = [str(jid).strip() for jid in (job_ids or []) if jid is not None and str(jid).strip()]

    if not ids:
        return None

    if client is None:
        return "No connection to the host: the remote job could not be cancelled."

    try:
        output = client.run_command(f"scancel {','.join(ids)}")
    except Exception as e:
        return repr(e)

    stderr = (output or {}).get("stderr", "")

    if stderr and not is_benign_scancel_error(stderr):
        return stderr

    return None


def find_submitted_jobs(jobid: str, logs: dict):
    for filename, log in logs.items():
        if jobid in filename:
            subjobs = []
            for item in log.split("\n"):
                if "Submitted batch job " in item:
                    jid = item[20:].strip()
                    subjobs.append(jid)
            return subjobs
    return None


def look_for_general_tracebacks_on_slurm_logs(client, deploy_path: Path):
    error_check = client.run_command(
        f'if grep -q "Traceback (most recent call last)" {deploy_path}/slurm-*.out; then echo yes; else echo no; fi'
    )

    return error_check["stdout"].strip() == "yes"


class SlurmJobStatusMixin:
    def __init__(self, timeout_seconds, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._timeout_seconds = timeout_seconds
        self._sacct_failure_start_time = None
        self._disconnect_attempts = 0

        self.slurm_job_ids = []

    def progress(self, job_manager, uid: str, client: Any = None):
        if client is None:
            self.disconnected(job_manager, uid, client)
            return

        # A client in hand means the host answered: whatever happens next is a
        # slurm-level problem, so the reconnection backoff must start over
        # instead of compounding across unrelated failures.
        self._disconnect_attempts = 0

        try:
            jobstatus = sacct(client, self.slurm_job_ids)
            if not jobstatus:
                raise RuntimeError("Job list is empty")

            # Reset failure counters on success
            self._sacct_failure_start_time = None

            self._post_status_update(job_manager, uid, client, jobstatus)

        except errors.ChannelError as e:
            # SSH-level failure (mid-command or while reading results):
            # the connection is gone, hand over to the reconnection backoff.
            self.disconnected(job_manager, uid, client, error=e)
        except RuntimeError as e:
            # The command reached the server, so the connection is alive:
            # this is a slurm/parsing failure, not a disconnection.
            self._disconnect_attempts = 0

            if self._sacct_failure_start_time is None:
                self._sacct_failure_start_time = time.time()

            elapsed_time = time.time() - self._sacct_failure_start_time

            if elapsed_time < self._timeout_seconds:
                logging.debug(
                    f"Slurm job status fetch failed for job {self.slurm_job_ids}. Retrying after {elapsed_time:.2f}s (Time out in {self._timeout_seconds}s). Error: {repr(e)}"
                )
                job_manager.set_state(
                    uid,
                    JOB_STATE_PENDING,
                    0,
                    message=f"Requesting job status. Waiting for response (elapsed: {elapsed_time:.2f}s).",
                    traceback=repr(e),
                )
                job_manager.schedule(uid, JOB_EVENT_PROGRESS)
            else:
                logging.error(
                    f"Slurm job status fetch failed for job {self.slurm_job_ids} after timeout ({self._timeout_seconds}s). Error: {repr(e)}"
                )
                # IDLE, not FAILED: nothing is known to have gone wrong with
                # the processing. sacct stopped answering -- slurm restarted
                # and lost the job from its history, the accounting database
                # is down, the account lost authorization -- and the remote
                # job may well still be running. FAILED is terminal, so it
                # would end the polling for good, refuse a reconnect, and (on
                # a host whose client is still cached) leave the row with only
                # a Cancel/Delete that cannot reach the cluster. IDLE stops the
                # polling just the same but stays resumable.
                job_manager.set_state(
                    uid,
                    JOB_STATE_IDLE,
                    message=f"Stopped checking the job status after {self._timeout_seconds}s without an answer. Use 'Reconnect' to resume. Check your connection or account authorization.",
                    traceback=repr(e),
                )

    def disconnected(self, job_manager, uid: str, client: Any = None, error: Exception = None):
        """Handle a lost connection: drop the dead client and retry with backoff.

        Reschedules PROGRESS with an exponentially growing delay (capped at
        DISCONNECT_BACKOFF_MAX_SECONDS) and retries indefinitely; the user can
        reconnect manually at any time, which supersedes the parked retry.
        """
        job = job_manager.jobs.get(uid)
        if job is None:
            # Job removed mid-flight
            return

        job_manager.connections.drop_client(job.host, stale_client=client)

        if job.status in JOB_TERMINAL_STATES:
            # Nothing left to poll: keep the outcome the job already reached
            # instead of rewriting it to NOT CONNECTED (which the monitor
            # refuses to cancel) and stop the retry chain here.
            logging.info(f"Connection lost for finished job {uid} ({job.status}). Not retrying.")
            return

        # The sacct timeout only measures failures over a live connection
        self._sacct_failure_start_time = None

        delay = min(
            JOB_POLL_INTERVAL_SECONDS * 2 ** min(self._disconnect_attempts, 16),
            DISCONNECT_BACKOFF_MAX_SECONDS,
        )
        self._disconnect_attempts += 1

        logging.warning(
            f"Connection to {job.host.name} lost for job {uid}. "
            f"Retrying in {delay:.0f}s (attempt {self._disconnect_attempts}). Error: {repr(error)}"
        )
        job_manager.set_state(
            uid,
            JOB_STATE_NOTCONNECTED,
            message=(
                f"Connection to {job.host.name} lost. Retrying in {delay:.0f}s "
                f"(attempt {self._disconnect_attempts}). Use 'Reconnect' to retry now."
            ),
            traceback={"[WARNING] Connection lost": repr(error)} if error else None,
        )
        job_manager.schedule(uid, JOB_EVENT_PROGRESS, delay=delay)

    def _post_status_update(self, job_manager, uid: str, client: Any, jobstatus: list):
        raise NotImplementedError("Subclasses must implement _post_sacct_progress method")


def get_python_cmd(
    python_cmd_list=[], cli_cmd_list=[], remote_version=None, use_gpu=False, time=None, containers_root=None
):
    python_calls = []
    for python_cmd in python_cmd_list:
        python_calls.append("--cmd '" + python_cmd + "'")
    for cli_cmd in cli_cmd_list:
        python_calls.append("--cli '" + cli_cmd + "'")
    chained_cmds = " ".join(python_calls)

    parameters_list = []
    if use_gpu:
        parameters_list.append("--gpu 1")
    if time is not None:
        parameters_list.append(f'--time "{time}"')
    chained_parameters = " ".join(parameters_list)

    if remote_version == None:
        remote_version = get_posix_friendly_version()
    if containers_root is None:
        # No host in hand: fall back to the shipped default.
        containers_root = ClusterStorage().remote_path("geoslicer_containers")
    geoslicer_path = PurePosixPath(containers_root) / remote_version
    geoslicer_path_string = geoslicer_path.as_posix()
    main_cmd = (
        f'RPS_DIR="{geoslicer_path_string}"; '
        f'bash "$RPS_DIR/scripts/rps.sh" --sif "$RPS_DIR/images/geoslicer-cli.sif" {chained_parameters} '
        f"{chained_cmds}"
    )

    return main_cmd


def get_job_cmd(caller, uid, main_cmd, job_remote_path):
    opening_command = caller.jobs[uid].host.opening_command
    full_cmd = " && ".join(
        command for command in [opening_command, rf"cd {job_remote_path}", main_cmd] if len(command) > 0
    )
    return full_cmd


def get_posix_friendly_version():
    return re.sub(r"[\'*]", "", getApplicationVersion()).replace(" ", "_")
