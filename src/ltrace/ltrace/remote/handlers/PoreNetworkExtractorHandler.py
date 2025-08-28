import json
import logging
import re
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

import pandas as pd
import slicer

from ltrace.remote import utils as slurm_utils
from ltrace.remote.jobs import JobManager
from ltrace.remote.utils import argstring
from ltrace.slicer.data_utils import dataFrameToTableNode


class PoreNetworkExtractorHandler:
    JOBS_REMOTE_PATH = PurePosixPath(r"/nethome/drp/servicos/LTRACE/GEOSLICER/jobs")
    JOBS_LOCAL_PATH = Path("\\\\dfs.petrobras.biz\\cientifico\\cenpes\\res\\drp\\servicos\\LTRACE\\GEOSLICER\\jobs")
    JOB_ID_PATTERN = re.compile("job_id = ([a-zA-Z0-9]+)")

    def __init__(self, input_node_id, label_node_id, params) -> None:
        self.input_node_id = input_node_id
        self.label_node_id = label_node_id
        self.params = params
        self.slurm_job_ids = []

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

            with (self.job_local_path / "params_dict.json").open("w") as file:
                json.dump(self.params, file)

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
            main_cmd = f"RPS_DIR='/atena/users/g575/containers/geoslicer'; sh $RPS_DIR/scripts/rps.sh --sif $RPS_DIR/images/geoslicer-cli.sif --gpu 1 --cli -- '{script}'"
            full_cmd = " && ".join([opening_command, rf"cd {self.job_remote_path}", main_cmd])

            output = client.run_command(full_cmd, verbose=True)

            match = self.JOB_ID_PATTERN.search(output["stdout"])
            if not match:
                caller.set_state(uid, "FAILED", 100, message=f"Failed to match job id.")
                return
            self.slurm_job_ids.append(match.group(1))

            details = {
                "input_node_id": self.input_node_id,
                "label_node_id": self.label_node_id,
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

    def progress(self, caller: JobManager, uid: str, client: Any = None):
        try:
            job_status = slurm_utils.sacct(client, self.slurm_job_ids)
            if slurm_utils.all_done(job_status):
                caller.set_state(
                    uid,
                    "COMPLETED",
                    100,
                    message="All jobs completed.",
                    end_time=datetime.now().timestamp(),
                )
            else:
                # Aggregate progress from each job output file
                total_progress = 0
                for job_id in self.slurm_job_ids:
                    slurm_out = self.job_local_path / f"slurm-{job_id}.out"
                    total_progress += self.read_last_progress(slurm_out)
                avg_progress = max(total_progress / len(self.slurm_job_ids), 10)

                caller.set_state(uid, "RUNNING", avg_progress)
                caller.schedule(uid, "PROGRESS")
        except Exception as e:
            traceback.print_exc()
            logging.debug(f"Error in progress: {repr(e)}")

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
        def _create_table(table_type):
            table = slicer.mrmlScene.CreateNodeByClass("vtkMRMLTableNode")
            table.AddNodeReferenceID("PoresLabelMap", self.input_node_id)
            table.SetName(slicer.mrmlScene.GenerateUniqueName(f"{self.params['prefix']}_{table_type}_table"))
            table.SetAttribute("table_type", f"{table_type}_table")
            table.SetAttribute("is_multiscale", "false")  # TODO check if needed, case positive, set it correctly
            slicer.mrmlScene.AddNode(table)
            return table

        def _create_tables(algorithm_name):
            poreOutputTable = _create_table("pore")
            throatOutputTable = _create_table("throat")
            networkOutputTable = _create_table("network")
            poreOutputTable.SetAttribute("extraction_algorithm", algorithm_name)
            edge_throats = "none" if (algorithm_name == "porespy") else "x"
            poreOutputTable.SetAttribute("edge_throats", edge_throats)
            return throatOutputTable, poreOutputTable, networkOutputTable

        inputNode = slicer.mrmlScene.GetNodeByID(self.input_node_id)

        if inputNode:
            df_pores = pd.read_pickle(str(self.job_local_path / "pores.pd"))
            df_throats = pd.read_pickle(str(self.job_local_path / "throats.pd"))
            df_network = pd.read_pickle(str(self.job_local_path / "network.pd"))

            throatOutputTable, poreOutputTable, networkOutputTable = _create_tables("porespy")

            dataFrameToTableNode(df_pores, poreOutputTable)
            dataFrameToTableNode(df_throats, throatOutputTable)
            dataFrameToTableNode(df_network, networkOutputTable)

            ### Include size infomation ###
            bounds = [0, 0, 0, 0, 0, 0]
            inputNode.GetBounds(bounds)  # In millimeters
            poreOutputTable.SetAttribute("x_size", str(bounds[1] - bounds[0]))
            poreOutputTable.SetAttribute("y_size", str(bounds[3] - bounds[2]))
            poreOutputTable.SetAttribute("z_size", str(bounds[5] - bounds[4]))
            poreOutputTable.SetAttribute("origin", f"{bounds[0]};{bounds[2]};{bounds[4]}")

            ### Move table nodes to hierarchy nodes ###
            folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            itemTreeId = folderTree.GetItemByDataNode(inputNode)
            parentItemId = folderTree.GetItemParent(itemTreeId)
            currentDir = folderTree.CreateFolderItem(parentItemId, f"{self.params['prefix']}_Pore_Network")

            folderTree.CreateItem(currentDir, poreOutputTable)
            folderTree.CreateItem(currentDir, throatOutputTable)
            folderTree.CreateItem(currentDir, networkOutputTable)
        else:
            slicer.util.infoDisplay(
                f"Could not find the reference node with ID '{self.input_node_id}'. Load the scene that contains that node before collecting the job result."
            )

    def read_last_progress(self, slurm_out_file_path):
        last_progress = 0.1
        try:
            with slurm_out_file_path.open("r") as f:
                for line in f:
                    match = re.search(r"<filter-progress>(0(?:\.\d+)?|1(?:\.0+)?)</filter-progress>", line)
                    if match:
                        last_progress = float(match.group(1))
        except FileNotFoundError:
            return 0.1

        return last_progress * 100
