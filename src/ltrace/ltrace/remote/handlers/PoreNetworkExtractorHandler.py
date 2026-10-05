import logging
import re
import shutil
import traceback
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, List

import numpy as np
import slicer
import time

from ltrace.pore_networks.functions_extract import ExtractionNodesCreator
from ltrace.remote import errors
from ltrace.remote import utils as slurm_utils
from ltrace.remote.constants import (
    JOB_EVENT_CANCEL,
    JOB_EVENT_COLLECT,
    JOB_EVENT_DEPLOY,
    JOB_EVENT_DISCONNECTED,
    JOB_EVENT_PROGRESS,
    JOB_EVENT_START,
    JOB_STATE_COMPLETED,
    JOB_STATE_DEPLOYING,
    JOB_STATE_FAILED,
    JOB_STATE_PENDING,
    JOB_STATE_RUNNING,
)
from ltrace.remote.jobs import JobManager
from ltrace.remote.object_transfer import JsonObjectTransfer, VolumeNodeObjectTransfer
from ltrace.remote.utils import argstring, SlurmJobStatusMixin

_1hour = 3600  # seconds


class PoreNetworkExtractorHandler(SlurmJobStatusMixin):
    JOB_ID_PATTERN = re.compile("job_id = ([a-zA-Z0-9]+)")

    def __init__(self, input_node_id, label_node_id, visualization, params, parallel_params) -> None:
        super().__init__(timeout_seconds=_1hour)

        self.input_node_id = input_node_id
        self.label_node_id = label_node_id
        self.visualization = visualization
        self.params = params
        self.parallel_params = parallel_params

        self.job_remote_path = None
        self.job_local_path = None
        self.temp_path = None

        self.last_slurm_out_size = 0

        self.__action_map = {
            JOB_EVENT_DEPLOY: self.deploy,
            JOB_EVENT_DISCONNECTED: self.disconnected,
            JOB_EVENT_START: self.start,
            JOB_EVENT_PROGRESS: self.progress,
            JOB_EVENT_CANCEL: self.cancel,
            JOB_EVENT_COLLECT: self.collect,
        }

    def __call__(self, caller: JobManager, uid: str, action: str, **kwargs):
        try:
            client = kwargs.get("client")
            self.__action_map[action](caller, uid, client)
        except KeyError:
            pass

    def deploy(self, caller: JobManager, uid: str, client: Any = None):
        try:
            job_executor = caller.jobs[uid]
            storage = job_executor.host.get_storage()
            job_dir_name = JobManager.dirname(job_executor)
            self.job_remote_path = storage.remote_dir("geoslicer_jobs") / job_dir_name
            self.job_local_path = storage.local_dir("geoslicer_jobs") / job_dir_name
            self.temp_path = storage.remote_dir("geoslicer_jobs") / job_dir_name / "temp"

            client.run_command(f"mkdir --parents {self.job_remote_path} && chmod -R 777 {self.job_remote_path} && mkdir {self.job_remote_path}/temp")

            time.sleep(1.0)
            caller.set_state(uid, JOB_STATE_DEPLOYING, 5, message="Copying volume files to job path...")

            with JsonObjectTransfer(self.job_local_path, "extractor_params_dict.json") as transfer:
                transfer.save(self.params)

            input_node = slicer.mrmlScene.GetNodeByID(self.input_node_id)
            with VolumeNodeObjectTransfer(self.job_local_path, self.input_node_id) as transfer:
                transfer.save(input_node)

            if self.label_node_id:
                label_node = slicer.mrmlScene.GetNodeByID(self.label_node_id)
                with VolumeNodeObjectTransfer(self.job_local_path, self.label_node_id) as transfer:
                    transfer.save(label_node)

            self.cli_params = {
                "scalar": str(self.job_remote_path / f"{self.input_node_id}"),
                "cwd": str(self.job_remote_path),
                "divs": self.parallel_params["divs"],
            }
            if self.label_node_id:
                self.cli_params["label"] = str(self.job_remote_path / f"{self.label_node_id}")

            if self.parallel_params["slurm_jobs"] > 1:
                self.cli_params["slurm"] = ""
                self.cli_params["slurm_jobs"] = self.parallel_params["slurm_jobs"]
                self.cli_params["slurm_cores"] = self.parallel_params["slurm_cores"]
                self.cli_params["slurm_memory"] = self.parallel_params["slurm_memory"]

            details = {
                "input_node_id": self.input_node_id,
                "label_node_id": self.label_node_id,
                "visualization": self.visualization,
                "params": self.params,
                "parallel_params": self.parallel_params,
                "job_remote_path": str(self.job_remote_path),
                "job_local_path": str(self.job_local_path),
                "cli_params": self.cli_params,
            }
            caller.set_state(
                uid, JOB_STATE_DEPLOYING, 10, message="Configuration done. Starting job deployment.", details=details
            )
            caller.schedule(uid, JOB_EVENT_START)
        except errors.ChannelError as e:
            # The host dropped us mid-deploy: nothing is known about the
            # processing, so this must not become a terminal FAILED. Hand it to
            # the reconnection backoff, which flags NOT CONNECTED and retries.
            #
            # Clean up all the same. The export only survives a failure of the
            # copy stage below, which has its own finally; reaching here means
            # one of the mkdirs above lost the connection, and nothing re-enters
            # deploy afterwards -- disconnected() and resume() both schedule
            # PROGRESS -- so keeping the files would strand them until exit.
            self._cleanup_temp_export_dir()
            self.disconnected(caller, uid, client, error=e)
        except Exception:
            traceback.print_exc()
            caller.set_state(uid, "FAILED", 100, message=f"Failed to deploy job.")

    def start(self, caller: JobManager, uid: str, client: Any = None):
        ts_start = datetime.now().timestamp()
        try:
            storage = caller.jobs[uid].host.get_storage()
            script = " ".join(["PoreNetworkExtractorCLI.PoreNetworkExtractorCLI", argstring(self.cli_params)])
            host = caller.jobs[uid].host
            remote_version = host.get_remote_version()
            main_cmd = slurm_utils.get_python_cmd(
                cli_cmd_list=[script],
                remote_version=remote_version,
                containers_root=storage.remote_path("geoslicer_containers"),
            )
            full_cmd = slurm_utils.get_job_cmd(caller, uid, main_cmd, self.job_remote_path)

            output = client.run_command(full_cmd, verbose=True)

            match = self.JOB_ID_PATTERN.search(output["stdout"])
            if not match:
                caller.set_state(uid, JOB_STATE_FAILED, 100, message=f"Failed to match job id.")
                # Not persisted: no slurm job was created, so there is nothing
                # to follow across a restart. Writing it would bring the entry
                # back as a terminal FAILED with no job ids, which is how these
                # rows became unmanageable. The other handlers already return
                # here without persisting.
                return
            self.slurm_job_ids.append(match.group(1))

            details = {
                "slurm_job_ids": self.slurm_job_ids,
                "command": full_cmd,
            }
            caller.set_state(
                uid,
                JOB_STATE_PENDING,
                10,
                message=f"Job submitted for extraction.",
                start_time=ts_start,
                details=details,
            )
            caller.persist(uid)
            caller.schedule(uid, JOB_EVENT_PROGRESS)
        except errors.ChannelError as e:
            # The host dropped us mid-submission: nothing is known about the
            # processing, so this must not become a terminal FAILED. Hand it to
            # the reconnection backoff, which flags NOT CONNECTED and retries.
            self.disconnected(caller, uid, client, error=e)
        except Exception:
            traceback.print_exc()
            caller.set_state(
                uid,
                JOB_STATE_FAILED,
                100,
                start_time=ts_start,
                end_time=datetime.now().timestamp(),
                message="Execution failed to start jobs on cluster.",
            )
            caller.persist(uid)

    def _post_status_update(self, caller: JobManager, uid: str, client: Any, jobstatus: List[dict]):
        job_status = slurm_utils.sacct(client, self.slurm_job_ids)
        if slurm_utils.all_done(job_status):
            failed_jobs = []
            for job_id in self.slurm_job_ids:
                slurm_out = self.job_local_path / f"slurm-{job_id}.out"
                progress_pct = self.read_last_progress(slurm_out)
                if progress_pct < 100:
                    failed_jobs.append({"job_id": job_id, "last_progress": progress_pct, "slurm_out": str(slurm_out)})

            if failed_jobs:
                failed_ids = ", ".join([f["job_id"] for f in failed_jobs])
                caller.set_state(
                    uid,
                    JOB_STATE_FAILED,
                    100,
                    message=f"The following jobs did not complete: {failed_ids}.",
                    details={"failed_jobs": failed_jobs},
                    end_time=datetime.now().timestamp(),
                )
                caller.persist(uid)
                return

            caller.set_state(
                uid, JOB_STATE_COMPLETED, 100, message="All jobs completed.", end_time=datetime.now().timestamp()
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
            caller.set_state(uid, JOB_STATE_RUNNING, avg_progress)
            caller.schedule(uid, JOB_EVENT_PROGRESS)
        else:
            caller.set_state(uid, JOB_STATE_PENDING, 10)
            caller.schedule(uid, JOB_EVENT_PROGRESS)

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
            if local_path and local_path.exists():
                shutil.rmtree(local_path, ignore_errors=True)

    def collect(self, caller: JobManager, uid: str, client: Any = None):
        metadata = self.params["metadata"]

        watershed_output_array = None
        watershed_path = Path(self.job_local_path) / "watershed.npy"
        if watershed_path.exists():
            try:
                watershed_output_array = np.load(str(watershed_path)).astype(np.int32)
            except Exception:
                logging.exception(f"Failed to load watershed volume from {watershed_path}")

        extraction_nodes_creator = ExtractionNodesCreator(
            metadata,
            self.job_local_path,
            self.params["prefix"],
            self.visualization,
            watershed_output_array=watershed_output_array,
        )
        try:
            self.results = extraction_nodes_creator.create()
        except FileNotFoundError as e:
            error_message = str(e)
            logging.error(error_message)
            slicer.util.errorDisplay(f"Cannot create Pore Network.\n\n{error_message}", windowTitle="Missing Data")
        except Exception as e:
            logging.error(f"Unexpected error creating nodes: {str(e)}")
            slicer.util.errorDisplay(f"An error occurred: {str(e)}")
