from datetime import datetime
import shutil
from typing import Any, Callable
import re
from pathlib import Path, PurePosixPath

import slicer

from ltrace.remote.constants import (
    JOB_EVENT_CANCEL,
    JOB_EVENT_COLLECT,
    JOB_EVENT_DEPLOY,
    JOB_EVENT_PROGRESS,
    JOB_STATE_COMPLETED,
    JOB_STATE_FAILED,
    JOB_STATE_GHOST,
    JOB_STATE_RUNNING,
)
from ltrace.remote.utils import argstring, try_scancel
from ltrace.remote.jobs import JobManager
from ltrace.remote.paths import storage_for
from ltrace.remote import utils as slurm_utils


class PUCModelExecutionHandler:

    job_id_pattern = re.compile("job_id = ([a-zA-Z0-9]+)")

    def __init__(
        self,
        result_handler: Callable,
        output_name: str,
        bin_path: Path,
        script_path: Path,
        image_log_node_id: str,
        class_of_interest: str,
        depth_interval=(0, 0),
        opening_cmd: str = "",
    ) -> None:
        LTRACE_DIR = PurePosixPath("servicos/LTRACE/GEOSLICER")

        self.return_results = result_handler

        self.output_name = output_name

        self._storage = storage_for(None)

        self._bin_path = bin_path
        self._script_path = script_path

        self.image_log_node_id = image_log_node_id
        self.class_of_interest = class_of_interest
        self.depth_interval = depth_interval

        self.opening_cmd = opening_cmd or 'echo "Opening command not defined. Proceeding with default."'

        self.jobid = None

        self.results = []

    @property
    def jobs_remote_path(self) -> PurePosixPath:
        return self._storage.remote_dir("geoslicer_jobs")

    @property
    def jobs_local_path(self) -> Path:
        return self._storage.local_dir("geoslicer_jobs")

    @property
    def bin_path(self) -> PurePosixPath:
        return self._storage.remote_dir("root") / self._bin_path

    @property
    def script_path(self) -> PurePosixPath:
        return self._storage.remote_dir("root") / self._script_path

    def __call__(self, caller: JobManager, uid: str, action: str, **kwargs):
        # Bind to the host's storage layout before doing anything: the handler
        # is constructed before it knows which account it belongs to.
        job = caller.jobs.get(uid)
        if job is not None:
            self._storage = storage_for(job.host)

        client = kwargs.get("client")

        if action == JOB_EVENT_DEPLOY:
            self.deploy(caller, uid, client)
        elif action == JOB_EVENT_PROGRESS:
            self.progress(caller, uid, client)
        elif action == JOB_EVENT_CANCEL:
            self.cancel(caller, uid, client)
        elif action == JOB_EVENT_COLLECT:
            self.collect(caller, uid, client)
        else:
            raise ValueError(f"Unknown action: {action}")

    def deploy(self, caller: JobManager, uid: str, client: Any):
        acc_query = (
            "sacctmgr show assoc user=`whoami` format=User,Account"
            " | awk '{$1=$1};1'"
            " | cut -d' ' -f2"
            " | sed -n '3p'"
        )

        acc_query_response = client.run_command(acc_query)
        account = acc_query_response["stdout"].strip()

        dirname = JobManager.dirname(caller.jobs[uid])
        job_dir = self.jobs_remote_path / dirname
        stdout = client.run_command(f"mkdir --parents {job_dir} && chmod -R 777 {job_dir}")

        PYTHONSLICER = (
            self.bin_path
        )  # self.remote_dir / self.LTRACE_DIR / "bin" / "GeoSlicer-1.17.RC0"  / "bin" / "PythonSlicer"

        output_filepath = job_dir / self.output_name

        local_job_dir = self.jobs_local_path / dirname

        if not local_job_dir.exists():
            caller.set_state(uid, JOB_STATE_FAILED, 0, message=f"Unable to copy data. Cannot find '{local_job_dir}'.")
            return

        image_log_node = slicer.util.getNode(self.image_log_node_id)

        input_image_path = local_job_dir / f"{image_log_node.GetID()}.nrrd"
        slicer.util.exportNode(image_log_node, input_image_path, world=True)

        if self.depth_interval[1] >= self.depth_interval[0]:
            if self.depth_interval[1] > 0:
                raise ValueError("Wrong depth interval.")
            else:
                self.depth_interval = (0, max(image_log_node.GetImageData().GetDimensions()))

        input_image_remote_path = job_dir / f"{image_log_node.GetID()}.nrrd"

        params = dict(
            inputImage=rf'"{input_image_remote_path}"',
            outputLabel=rf'"{output_filepath}"',
            segmentClass=self.class_of_interest,
            depthInterval=self.depth_interval,
        )

        args = argstring(params)
        script = " ".join([str(self.script_path), args])

        main_cmd = rf"run_SLURM.sh -w {PYTHONSLICER} -p gpu -a {account} -u 100 -f '{script}'"
        full_cmd = " && ".join([self.opening_cmd, rf"cd {job_dir}", main_cmd])

        output = client.run_command(full_cmd)

        tsnow = datetime.now().timestamp()

        if len(output["stderr"]) > 0:
            caller.set_state(
                uid, JOB_STATE_FAILED, 0, message=f"Failed to run command: {full_cmd}", traceback=output["stderr"]
            )
            return  # FAILED

        findings = self.job_id_pattern.search(output["stdout"])

        if not findings:
            caller.set_state(uid, JOB_STATE_FAILED, 0, message="Failed to match the job id")
            return  # FAILED

        self.jobid = findings.group(1)

        details = {
            "job_id": self.jobid,
            "command": full_cmd,
            "output_name": self.output_name,
            "input_volume_node_id": image_log_node.GetID(),
            "depth_interval": self.depth_interval,
            "class_of_interest": self.class_of_interest,
            "script_path": self.script_path.as_posix(),
            "bin_path": self.bin_path.as_posix(),
        }

        caller.set_state(
            uid, JOB_STATE_RUNNING, 37, message="Execution in progress.", start_time=tsnow, details=details
        )
        caller.persist(uid)

        caller.schedule(uid, JOB_EVENT_PROGRESS)

    def progress(self, caller: JobManager, uid: str, client: Any):
        tsnow = datetime.now().timestamp()

        output = client.run_command(f"sacct -j{self.jobid} -o jobid,state")

        try:
            jobstatus = slurm_utils.sacct(
                client,
                [
                    self.jobid,
                ],
            )
        except RuntimeError as e:
            # TODO make a count for retries
            caller.set_state(
                uid,
                "RETRYING",
                0,
                message="Unable to check job status. Retrying in 3s...",
                end_time=tsnow,
                traceback=repr(e),
            )
            caller.schedule(uid, JOB_EVENT_PROGRESS)
            return

        if slurm_utils.all_done(jobstatus):  # job finished and got out of queue
            job_dir = self.jobs_local_path / JobManager.dirname(caller.jobs[uid])
            output_filepath = job_dir / self.output_name

            if not output_filepath.exists():
                caller.set_state(
                    uid,
                    JOB_STATE_FAILED,
                    0,
                    message=f"Failed to check job results: '{output_filepath}' not found!",
                    traceback=output["stderr"],
                )
                return  # FAILED

            self.results.append(output_filepath)

            slurm_out = self.get_slurm_log(job_dir)

            """job finished and got out of queue"""
            caller.set_state(
                uid, JOB_STATE_COMPLETED, 100, message="Execution Completed.", end_time=tsnow, traceback=slurm_out
            )

        else:
            caller.set_state(uid, JOB_STATE_RUNNING, 47)
            caller.schedule(uid, JOB_EVENT_PROGRESS)

    def cancel(self, caller: JobManager, uid: str, client: Any):
        try:
            self.cleanup(caller, uid, client)
            # caller.set_state(uid, JOB_STATE_CANCELLED, 0, message="Execution Cancelled.")
        except:
            pass

    def cleanup(self, caller: JobManager, uid: str, client: Any = None):
        # scancel reports "invalid job id" for a slurm job that already
        # finished. That is not a cancellation failure, and marking the job
        # GHOST for it leaves an entry the monitor refuses to cancel, i.e. one
        # the user can never remove.
        ghost_reason = try_scancel(client, [self.jobid])

        if ghost_reason:
            caller.set_state(uid, JOB_STATE_GHOST, 0, message="Execution cannot be cancelled.", traceback=ghost_reason)
            return

        try:
            job_dir = self.jobs_remote_path / JobManager.dirname(caller.jobs[uid])

            """ Note: must be done remotely because of permissions """
            client.run_command(f"rm -rf {job_dir}")

            caller.remove(uid)
        except Exception:
            local_job_dir = to_local(job_dir)
            if local_job_dir.exists():
                shutil.rmtree(local_job_dir, ignore_errors=True)

    def collect(self, caller: JobManager, uid: str, client: Any = None):
        self.return_results(
            {
                "reference_volume_node_id": self.image_log_node_id,
                "results": self.results,
            }
        )

        self.cleanup(caller, uid, client)

    # TODO normalizar essa função (tb é usada no OneResultSlurm)
    def get_slurm_log(self, jobdir: Path):
        try:
            content = {}
            logfilename = f"slurm-{self.jobid}.out"

            slurm_path = jobdir / logfilename

            if slurm_path.exists():
                current_slurm_out_size = slurm_path.stat().st_size

                if self.last_slurm_out_size != current_slurm_out_size:
                    with open(slurm_path, "r") as f:
                        slurm_out_content = f.read().strip()

                    content[logfilename] = slurm_out_content

            return content

        except Exception as e:
            return {
                "slurm_log": f"Failed to read slurm log: {repr(e)}",
            }
