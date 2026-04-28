import json
import pickle
import shutil
import logging
from pathlib import Path
import re
from typing import Any, Callable
from datetime import datetime
import time

import slicer

from ltrace.slicer.app import getApplicationVersion
from ltrace.slicer_utils import print_debug
from ltrace.remote.jobs import JobManager


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
        print("Error during hash check: ", out["stderr"])
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
        print_debug(f"Error during sacct parsing: {repr(e)}")
        raise RuntimeError(e)


def any_running(jobs: list):
    """Check if any jobs are running
    jobs: list of job dictionaries
    """
    if not jobs:
        raise RuntimeError("Job list is empty")

    for job in jobs:
        if job["state"] == "RUNNING":
            return True
    return False


def all_complete(jobs: list):
    """Check if all jobs are complete
    jobs: list of job dictionaries
    """
    if not jobs:
        raise RuntimeError("Job list is empty")

    for job in jobs:
        if job["state"] != "COMPLETED":
            return False
    return True


def any_failed(jobs: list):
    """Check if any jobs failed
    jobs: list of job dictionaries
    """
    if not jobs:
        raise RuntimeError("Job list is empty")

    for job in jobs:
        if job["state"] == "FAILED":
            return True
    return False


def all_failed(jobs: list):
    """Check if all jobs failed
    jobs: list of job dictionaries
    """
    if not jobs:
        raise RuntimeError("Job list is empty")

    for job in jobs:
        if job["state"] != "FAILED":
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
        if state != "COMPLETED" and state != "FAILED" and "CANCELLED" not in state:
            return False
    return True


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


def dump_via_slicer_temp(obj, filename, final_dir, format="json"):
    temp_path = Path(slicer.util.tempDirectory()) / filename
    final_path = Path(final_dir) / filename

    if format == "json":
        with open(temp_path, "w") as f:
            json.dump(obj, f)

    elif format == "pickle":
        with open(temp_path, "wb") as f:
            pickle.dump(obj, f)
    else:
        raise ValueError(f"Unsupported format: {format}")

    shutil.move(str(temp_path), str(final_path))


class SlurmJobStatusMixin:
    def __init__(self, timeout_seconds, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._timeout_seconds = timeout_seconds
        self._sacct_failure_start_time = None

        self.slurm_job_ids = []

    def progress(self, caller: JobManager, uid: str, client: Any = None):
        tsnow = datetime.now().timestamp()
        try:
            jobstatus = sacct(client, self.slurm_job_ids)
            if not jobstatus:
                raise RuntimeError("Job list is empty")

            # Reset failure start time on success
            self._sacct_failure_start_time = None

            self._post_status_update(caller, uid, client, jobstatus)
        except RuntimeError as e:
            if self._sacct_failure_start_time is None:
                self._sacct_failure_start_time = time.time()

            elapsed_time = time.time() - self._sacct_failure_start_time

            if elapsed_time < self._timeout_seconds:
                logging.debug(
                    f"Slurm job status fetch failed for job {self.slurm_job_ids}. Retrying after {elapsed_time:.2f}s (timeout {self._timeout_seconds}s). Error: {repr(e)}"
                )
                caller.set_state(
                    uid,
                    "PENDING",
                    0,
                    message=f"Requesting job status. Waiting for response (elapsed: {elapsed_time:.2f}s).",
                    end_time=tsnow,
                    traceback=repr(e),
                )
                caller.schedule(uid, "PROGRESS")
            else:
                logging.error(
                    f"Slurm job status fetch failed for job {self.slurm_job_ids} after timeout ({self._timeout_seconds}s). Error: {repr(e)}"
                )
                caller.set_state(
                    uid,
                    "FAILED",
                    0,
                    message=f"Failed to get job status after timeout ({self._timeout_seconds}s). Check your connection or account authorization.",
                    end_time=tsnow,
                    traceback=repr(e),
                )

    def _post_status_update(self, caller: JobManager, uid: str, client: Any, jobstatus: list):
        raise NotImplementedError("Subclasses must implement _post_sacct_progress method")


def get_python_cmd(python_cmd_list=[], cli_cmd_list=[], use_gpu=False, time=None):
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

    geoslicer_version = getApplicationVersion()
    geoslicer_path = Path("/atena/users/dibi/containers/geoslicer/") / get_posix_friendly_version()
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
