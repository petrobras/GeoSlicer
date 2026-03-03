import logging
import platform
import re
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, List

import slicer

from ltrace.pore_networks.functions_extract import ExtractionNodesCreator
from ltrace.remote import utils as slurm_utils
from ltrace.remote.jobs import JobManager
from ltrace.remote.utils import argstring, dump_via_slicer_temp, SlurmJobStatusMixin

_1hour = 3600  # seconds


class PoreNetworkExtractorHandler(SlurmJobStatusMixin):
    JOBS_REMOTE_PATH = PurePosixPath(r"/nethome/drp/servicos/LTRACE/GEOSLICER/jobs")
    if platform.system() == "Windows":
        JOBS_LOCAL_PATH = Path(r"\\dfs.petrobras.biz\cientifico\cenpes\res\drp\servicos\LTRACE\GEOSLICER\jobs")
    else:
        JOBS_LOCAL_PATH = Path("/nethome/drp/servicos/LTRACE/GEOSLICER/jobs")
    JOB_ID_PATTERN = re.compile("job_id = ([a-zA-Z0-9]+)")

    def __init__(self, input_node_id, label_node_id, visualization, params) -> None:
        super().__init__(timeout_seconds=_1hour)

        self.input_node_id = input_node_id
        self.label_node_id = label_node_id
        self.visualization = visualization
        self.params = params

        self.job_remote_path = None
        self.job_local_path = None
        self.temp_path = None

        self.last_slurm_out_size = 0

        self.__action_map = {
            "DEPLOY": self.deploy,
            "START": self.start,
            "PROGRESS": self.progress,
            "CANCEL": self.cancel,
            "COLLECT": self.collect,
        }

    def __call__(self, caller: JobManager, uid: str, action: str, **kwargs):
        try:
            client = kwargs.get("client")
            self.__action_map[action](caller, uid, client)
        except KeyError:
            pass

    def deploy(self, caller: JobManager, uid: str, client: Any = None):
        try:
            job_dir_name = JobManager.dirname(caller.jobs[uid])
            self.job_remote_path = self.JOBS_REMOTE_PATH / job_dir_name
            self.job_local_path = self.JOBS_LOCAL_PATH / job_dir_name
            self.temp_path = self.JOBS_REMOTE_PATH / job_dir_name / "temp"

            client.run_command(f"mkdir --parents {self.job_remote_path} && chmod -R 777 {self.job_remote_path}")
            client.run_command(f"mkdir {self.job_remote_path}/temp")

            dump_via_slicer_temp(self.params, "extractor_params_dict.json", self.job_local_path)

            input_node = slicer.mrmlScene.GetNodeByID(self.input_node_id)
            input_node_path = self.job_local_path / f"{self.input_node_id}.nrrd"
            slicer.util.exportNode(input_node, input_node_path, world=True)

            if self.label_node_id:
                label_node = slicer.mrmlScene.GetNodeByID(self.label_node_id)
                label_node_path = self.job_local_path / f"{self.label_node_id}.nrrd"
                slicer.util.exportNode(label_node, label_node_path, world=True)

            self.cli_params = {
                "volume": str(self.job_remote_path / f"{self.input_node_id}.nrrd"),
                "cwd": str(self.job_remote_path),
            }
            if self.label_node_id:
                self.cli_params["label"] = str(self.job_remote_path / f"{self.label_node_id}.nrrd")

            caller.set_state(uid, "DEPLOYING", 10, message="Configuration done. Starting job deployment.")
            caller.schedule(uid, "START")
        except Exception:
            traceback.print_exc()

    def start(self, caller: JobManager, uid: str, client: Any = None):
        ts_start = datetime.now().timestamp()
        try:
            script = " ".join(["PoreNetworkExtractorCLI.PoreNetworkExtractorCLI", argstring(self.cli_params)])
            opening_command = caller.jobs[uid].host.opening_command
            main_cmd = f"RPS_DIR='/atena/users/dibi/containers/geoslicer'; sh $RPS_DIR/scripts/rps.sh --sif $RPS_DIR/images/geoslicer-cli.sif --cli '{script}'"
            full_cmd = " && ".join([opening_command, rf"cd {self.job_remote_path}", main_cmd])

            output = client.run_command(full_cmd, verbose=True)

            match = self.JOB_ID_PATTERN.search(output["stdout"])
            if not match:
                caller.set_state(uid, "FAILED", 100, message=f"Failed to match job id.")
                caller.persist(uid)
                return
            self.slurm_job_ids.append(match.group(1))

            details = {
                "input_node_id": self.input_node_id,
                "label_node_id": self.label_node_id,
                "visualization": self.visualization,
                "params": self.params,
                "job_remote_path": str(self.job_remote_path),
                "job_local_path": str(self.job_local_path),
                "slurm_job_ids": self.slurm_job_ids,
                "command": full_cmd,
                "cli_params": self.cli_params,
            }
            caller.set_state(
                uid,
                "PENDING",
                10,
                message=f"Job submitted for extraction.",
                start_time=ts_start,
                details=details,
            )
            caller.persist(uid)
            caller.schedule(uid, "PROGRESS")
        except Exception:
            traceback.print_exc()
            caller.set_state(
                uid,
                "FAILED",
                100,
                start_time=ts_start,
                end_time=datetime.now().timestamp(),
                message="Execution failed to start jobs on cluster.",
            )
            caller.persist(uid)

    def _post_status_update(self, caller: JobManager, uid: str, client: Any, jobstatus: List[dict]):
        try:
            job_status = slurm_utils.sacct(client, self.slurm_job_ids)
            if slurm_utils.all_done(job_status):
                failed_jobs = []
                for job_id in self.slurm_job_ids:
                    slurm_out = self.job_local_path / f"slurm-{job_id}.out"
                    progress_pct = self.read_last_progress(slurm_out)
                    if progress_pct < 100:
                        failed_jobs.append(
                            {"job_id": job_id, "last_progress": progress_pct, "slurm_out": str(slurm_out)}
                        )

                if failed_jobs:
                    failed_ids = ", ".join([f["job_id"] for f in failed_jobs])
                    caller.set_state(
                        uid,
                        "FAILED",
                        100,
                        message=f"The following jobs did not complete: {failed_ids}.",
                        details={"failed_jobs": failed_jobs},
                        end_time=datetime.now().timestamp(),
                    )
                    caller.persist(uid)
                    return

                caller.set_state(
                    uid, "COMPLETED", 100, message="All jobs completed.", end_time=datetime.now().timestamp()
                )
                caller.persist(uid)
                return
            elif slurm_utils.any_running(job_status):
                total_progress = 0
                count = 0
                for job_id in self.slurm_job_ids:
                    slurm_out = self.job_local_path / f"slurm-{job_id}.out"
                    total_progress += self.read_last_progress(slurm_out)
                    count += 1
                avg_progress = max(total_progress / count, 10) if count > 0 else 10
                caller.set_state(uid, "RUNNING", avg_progress)
                caller.schedule(uid, "PROGRESS")
            else:
                caller.set_state(uid, "PENDING", 10)
                caller.schedule(uid, "PROGRESS")
        except Exception as e:
            traceback.print_exc()
            logging.debug(f"Error in progress: {repr(e)}")

    def read_last_progress(self, slurm_out_file_path):
        last_progress = 0.1
        try:
            with slurm_out_file_path.open("r") as f:
                for line in f:
                    match = re.search(r"<filter-progress>(0(?:\.\d+)?|1(?:\.0+)?)</filter-progress>", line)
                    if match:
                        last_progress = float(match.group(1))
        except FileNotFoundError:
            return 10
        except Exception:
            logging.exception(f"Error reading slurm out file {slurm_out_file_path}")
            return 10
        return last_progress * 100

    def cancel(self, caller: JobManager, uid: str, client: Any = None):
        try:
            self.cleanup(caller, uid, client)
        except Exception:
            traceback.print_exc()

    def cleanup(self, caller: JobManager, uid: str, client: Any = None):
        if self.slurm_job_ids:
            job_list = ",".join(self.slurm_job_ids)
            try:
                output = client.run_command(f"scancel {job_list}")
                if len(output["stderr"]) > 0:
                    raise Exception(output["stderr"])
            except Exception:
                traceback.print_exc()
        try:
            caller.remove(uid)
            client.run_command(f"rm -rf {self.job_remote_path}")
        except Exception:
            local_path = self.job_local_path
            if local_path.exists():
                shutil.rmtree(local_path, ignore_errors=True)

    def collect(self, caller: JobManager, uid: str, client: Any = None):
        metadata = self.params["metadata"]
        extraction_nodes_creator = ExtractionNodesCreator(
            metadata, self.job_local_path, self.params["prefix"], self.visualization
        )
        try:
            self.results = extraction_nodes_creator.create()
        except FileNotFoundError as e:
            error_message = str(e)
            logging.error(error_message)
            slicer.util.errorDisplay(f"Cannot create Pore Network.\n\n{error_message}", windowTitle="Missing Data")
        except Exception as e:
            # Catch-all for other potential issues during node creation
            logging.error(f"Unexpected error creating nodes: {str(e)}")
            slicer.util.errorDisplay(f"An error occurred: {str(e)}")
