from datetime import datetime
from pathlib import Path, PurePosixPath, WindowsPath
import re
import shutil
from typing import Any, Callable

import slicer

from ltrace.remote.utils import argstring
from ltrace.remote.jobs import JobManager
from ltrace.remote import utils as slurm_utils

import ast, json, os

from ThinSectionInstanceSegmenter import (
    rgb2label,
    getVolumeMinSpacing,
    compareVolumeSpacings,
    adjustSpacingAndCrop,
    makeColorsSlices,
    prepareTemporaryInputs,
)


class ThinSectionInstanceSegmenterExecutionHandler:
    REMOTE_DIR = PurePosixPath("/nethome/drp")
    NFS_DIR = WindowsPath("\\\\dfs.petrobras.biz\\cientifico\\cenpes\\res\\drp")

    job_id_pattern = re.compile("job_id = ([a-zA-Z0-9]+)")

    def __init__(
        self,
        result_handler: Callable,
        output_name: str,
        bin_path: Path,
        script_path: Path,
        model_path: Path,
        reference_node_id: str,
        tmp_reference_node_id: str,
        soi_node_id: str,
        ctypes,
        params,
        classes,
        segmentation: bool = True,
        opening_cmd: str = "",
    ) -> None:
        self.LTRACE_DIR = PurePosixPath("servicos/LTRACE/GEOSLICER")

        self.return_results = result_handler

        self.output_name = output_name
        self.report_name = "instances_report"

        self.jobs_remote_path = PurePosixPath(
            (self.REMOTE_DIR / "servicos" / "LTRACE" / "GEOSLICER" / "jobs").as_posix()
        )
        self.jobs_local_path = self.NFS_DIR / "servicos" / "LTRACE" / "GEOSLICER" / "jobs"

        self.bin_path = PurePosixPath(self.REMOTE_DIR / bin_path)
        self.script_path = PurePosixPath(self.REMOTE_DIR / script_path)

        self.model_path = PurePosixPath(
            self.REMOTE_DIR
            / self.LTRACE_DIR
            / "bin"
            / "geoslicer_remote"
            / "slicerltrace"
            / "src"
            / "ltrace"
            / "ltrace"
            / "assets"
            / "trained_models"
            / "ThinSectionEnv"
            / os.path.basename(model_path)
        )

        self.reference_node_id = reference_node_id
        self.tmp_reference_node_id = tmp_reference_node_id
        self.soi_node_id = soi_node_id
        self.ctypes = ctypes
        self.params = json.dumps(params)
        self.classes = classes
        self.segmentation = segmentation

        self.opening_cmd = opening_cmd or 'echo "Opening command not defined. Proceeding with default."'

        self.jobid = None

        self.results = []

    def __call__(self, caller: JobManager, uid: str, action: str, **kwargs):
        client = kwargs.get("client")

        if action == "DEPLOY":
            self.deploy(caller, uid, client)
        elif action == "PROGRESS":
            self.progress(caller, uid, client)
        elif action == "CANCEL":
            self.cancel(caller, uid, client)
        elif action == "COLLECT":
            self.collect(caller, uid, client)
        else:
            raise ValueError(f"Unknown action: {action}")

    def deploy(self, caller: JobManager, uid: str, client: Any):
        acc_query = "sacctmgr -np show assoc user=`whoami` format=Account | cut -d'\|' -f1"

        acc_query_response = client.run_command(acc_query)
        account = acc_query_response["stdout"].strip()

        dirname = JobManager.dirname(caller.jobs[uid])
        job_dir = self.jobs_remote_path / dirname
        stdout = client.run_command(f"mkdir --parents {job_dir} && chmod -R 777 {job_dir}")

        PYTHONSLICER = self.bin_path

        output_filepath = job_dir / self.output_name
        output_table_path = job_dir / self.report_name

        local_job_dir = self.jobs_local_path / dirname

        if not local_job_dir.exists():
            caller.set_state(uid, "FAILED", 0, message=f"Unable to copy data. Cannot find '{local_job_dir}'.")
            return

        reference_node = slicer.util.getNode(self.reference_node_id)
        tmpReferenceNode = slicer.util.getNode(self.tmp_reference_node_id)

        input_image_path = local_job_dir / f"{reference_node.GetID()}.nrrd"
        slicer.util.exportNode(tmpReferenceNode, input_image_path, world=True)

        input_image_remote_path = job_dir / f"{reference_node.GetID()}.nrrd"

        params = dict(
            input_model=self.model_path.as_posix(),
            input_volume=rf'"{input_image_remote_path}"',
            output_volume=rf'"{output_filepath}"',
            output_table=rf'"{output_table_path}"',
            xargs=self.params,
            ctypes=self.ctypes,
        )

        args = argstring(params)
        script = " ".join([str(self.script_path), args])

        main_cmd = rf"run_SLURM.sh -w {PYTHONSLICER} -p gpu -a {account} -u 100 -f '{script}'"
        full_cmd = " && ".join([self.opening_cmd, rf"cd {job_dir}", main_cmd])

        output = client.run_command(full_cmd)

        tsnow = datetime.now().timestamp()

        if len(output["stderr"]) > 0:
            caller.set_state(uid, "FAILED", 0, message=f"Failed to run command: {full_cmd}", traceback=output["stderr"])
            return  # FAILED

        findings = self.job_id_pattern.search(output["stdout"])
        if not findings:
            caller.set_state(uid, "FAILED", 0, message="Failed to match the job id")
            return  # FAILED
        self.jobid = findings.group(1)

        details = {
            "job_id": self.jobid,
            "command": full_cmd,
            "output_name": self.output_name,
            "input_volume_node_id": self.reference_node_id,
            "tmp_reference_node_id": self.tmp_reference_node_id,
            "soi_node_id": self.soi_node_id,
            "params": params,
            "classes": self.classes,
            "segmentation": self.segmentation,
            "script_path": self.script_path.as_posix(),
            "bin_path": self.bin_path.as_posix(),
        }

        caller.set_state(uid, "RUNNING", 37, message="Execution in progress.", start_time=tsnow, details=details)
        caller.persist(uid)

        caller.schedule(uid, "PROGRESS")

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
            caller.set_state(
                uid,
                "RETRYING",
                0,
                message="Unable to check job status. Retrying in 3s...",
                end_time=tsnow,
                traceback=repr(e),
            )
            caller.schedule(uid, "PROGRESS")
            return

        if slurm_utils.all_done(jobstatus):  # job finished and got out of queue
            job_dir = self.jobs_local_path / JobManager.dirname(caller.jobs[uid])
            output_filepath = job_dir / self.output_name
            output_table_path = job_dir / self.report_name

            if not output_filepath.exists():
                caller.set_state(
                    uid,
                    "FAILED",
                    0,
                    message=f"Failed to check job results: '{output_filepath}' not found!",
                    traceback=output["stderr"],
                )
                return  # FAILED

            self.results.append(output_filepath.as_posix())

            if output_table_path.exists() and json.loads(self.params)["calculate_statistics"]:
                self.results.append(output_table_path.as_posix())

            slurm_out = self.get_slurm_log(job_dir)

            """job finished and got out of queue"""
            caller.set_state(uid, "COMPLETED", 100, message="Execution Completed.", end_time=tsnow, traceback=slurm_out)

        else:
            caller.set_state(uid, "RUNNING", 47)
            caller.schedule(uid, "PROGRESS")

    def cancel(self, caller: JobManager, uid: str, client: Any):
        try:
            self.cleanup(caller, uid, client)
            # caller.set_state(uid, "CANCELLED", 0, message="Execution Cancelled.")
        except:
            pass

    def cleanup(self, caller: JobManager, uid: str, client: Any = None):
        ghosted = False
        traceback = None
        if self.jobid:
            try:
                r = client.run_command(f"scancel {self.jobid}")

                if len(r["stderr"]) > 0:
                    raise Exception(r["stderr"])
            except Exception as e:
                ghosted = True
                traceback = repr(e)

        if ghosted:
            caller.set_state(uid, "GHOST", 0, message="Execution cannot be cancelled.", traceback=traceback)
            return

        try:
            job_dir = self.jobs_remote_path / JobManager.dirname(caller.jobs[uid])

            """ Note: must be done remotely because of permissions """
            client.run_command(f"rm -rf {job_dir}")

            caller.remove(uid)
        except Exception:
            local_job_dir = Path(
                str(Path(job_dir)).replace("/nethome/drp", "\\\\dfs.petrobras.biz\\cientifico\\cenpes\\res\\drp")
            )
            if local_job_dir.exists():
                shutil.rmtree(local_job_dir, ignore_errors=True)

    def collect(self, caller: JobManager, uid: str, client: Any = None):
        self.return_results(
            {
                "reference_node_id": self.reference_node_id,
                "tmp_reference_node_id": self.tmp_reference_node_id,
                "soi_node_id": json.dumps(self.soi_node_id),
                "results": self.results,
                "classes": self.classes,
                "output_prefix": self.output_name,
            }
        )

        self.cleanup(caller, uid, client)

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
