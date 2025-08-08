import json
import logging
import re
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


import numpy as np
import pandas as pd
import slicer
from ltrace.pore_networks.functions import geo2pnf
from ltrace.pore_networks.functions import is_multiscale_geo
from ltrace.remote import utils as slurm_utils
from ltrace.remote.jobs import JobManager
from ltrace.remote.utils import argstring
from ltrace.slicer.data_utils import dataFrameToTableNode


class PoreNetworkSimulationHandler:
    JOBS_REMOTE_PATH = PurePosixPath(r"/nethome/drp/servicos/LTRACE/GEOSLICER/jobs")
    JOBS_LOCAL_PATH = Path("\\\\dfs.petrobras.biz\\cientifico\\cenpes\\res\\drp\\servicos\\LTRACE\\GEOSLICER\\jobs")
    JOB_ID_PATTERN = re.compile("job_id = ([a-zA-Z0-9]+)")

    def __init__(self, pore_table_node_id, params, prefix) -> None:
        self.pore_table_node_id = pore_table_node_id
        self.params = params
        self.prefix = prefix
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

            subresolution_function = self.params["subresolution function"]
            del self.params["subresolution function"]
            del self.params["subresolution function call"]

            pore_table_node = slicer.mrmlScene.GetNodeByID(self.pore_table_node_id)

            statoil_dict = geo2pnf(
                pore_table_node,
                subresolution_function,
                subres_shape_factor=self.params["subres_shape_factor"],
                subres_porositymodifier=self.params["subres_porositymodifier"],
            )

            with (self.job_local_path / "statoil_dict.json").open("w") as file:
                json.dump(statoil_dict, file)

            with (self.job_local_path / "params_dict.json").open("w") as file:
                json.dump(self.params, file)

            self.cli_params = {
                "model": "TwoPhaseSensibilityTest",
                "cwd": str(self.job_remote_path),
                "tempDir": str(self.temp_path),
                "isMultiScale": int(is_multiscale_geo(pore_table_node)),
                "returnparameterfile": str(self.temp_path / "returnparameterfile.txt"),
            }

            caller.set_state(uid, "DEPLOYING", 10, message="Configuration done. Starting job deployment.")
            caller.schedule(uid, "START")
        except Exception:
            traceback.print_exc()

    def start(self, caller: JobManager, uid: str, client: Any = None):
        ts_start = datetime.now().timestamp()
        try:
            n_sims = self.get_number_of_simulations()
            n_jobs = self.params["n_jobs"]
            n_jobs = max(1, min(n_jobs, n_sims))
            simulations_per_job = n_sims // n_jobs
            remainder = n_sims % n_jobs

            for i in range(n_jobs):
                start_sim = i * simulations_per_job + min(i, remainder)
                end_sim = (i + 1) * simulations_per_job + min(i + 1, remainder) - 1
                cli_params = self.cli_params.copy()
                cli_params["simInterval"] = f"{start_sim}:{end_sim}"

                script = " ".join(["PoreNetworkSimulationCLI.PoreNetworkSimulationCLI", argstring(cli_params)])
                opening_command = caller.jobs[uid].host.opening_command
                main_cmd = f"RPS_DIR='/atena/users/g575/containers/geoslicer'; sh $RPS_DIR/scripts/rps.sh --sif $RPS_DIR/images/geoslicer-cli.sif --gpu 1 --cli -- '{script}'"
                full_cmd = " && ".join([opening_command, rf"cd {self.job_remote_path}", main_cmd])

                output = client.run_command(full_cmd, verbose=True)

                match = self.JOB_ID_PATTERN.search(output["stdout"])
                if not match:
                    caller.set_state(
                        uid, "FAILED", 100, message=f"Failed to match job id for interval [{start_sim}, {end_sim}]"
                    )
                    return
                self.slurm_job_ids.append(match.group(1))

            details = {
                "pore_table_node_id": self.pore_table_node_id,
                "params": self.params,
                "prefix": self.prefix,
                "job_remote_path": str(self.job_remote_path),
                "job_local_path": str(self.job_local_path),
                "slurm_job_ids": self.slurm_job_ids,
                "n_sims": n_sims,
                "n_jobs": n_jobs,
                "command": full_cmd,
                "cli_params": self.cli_params,
            }
            caller.set_state(
                uid,
                "PENDING",
                10,
                message=f"{n_jobs} jobs submitted for {n_sims} simulations.",
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
        pore_table_node = slicer.mrmlScene.GetNodeByID(self.pore_table_node_id)
        folder_tree = slicer.mrmlScene.GetSubjectHierarchyNode()
        if pore_table_node:
            item_tree_id = folder_tree.GetItemByDataNode(pore_table_node)
            parent_item_id = folder_tree.GetItemParent(folder_tree.GetItemParent(item_tree_id))
        else:
            parent_item_id = folder_tree.GetSceneItemID()
        root_dir = folder_tree.CreateFolderItem(parent_item_id, f"{self.prefix}_Two_Phase_PN_Simulation")
        table_dir = folder_tree.CreateFolderItem(root_dir, "Tables")
        folder_tree.SetItemExpanded(root_dir, False)
        folder_tree.SetItemExpanded(table_dir, False)

        def load_and_concat(pattern):
            files = list(self.job_local_path.glob(pattern))
            if not files:
                raise FileNotFoundError(f"No files found matching pattern: {pattern}")
            dataframes = [pd.read_pickle(str(f)) for f in sorted(files)]
            return pd.concat(dataframes, ignore_index=True)

        def aggregate_cycle_data(dataframes):
            base_df = dataframes[0][["cycle", "Sw"]].copy()

            group_columns = []  # Store the new globally reindexed group columns
            index_counter = 0

            renamed_dfs = []

            for df in dataframes:
                # Drop _middle columns
                df = df[[col for col in df.columns if not col.endswith("_middle")]]

                # Detect the per-group columns by their suffix index
                group_indices = sorted(
                    set(
                        int(col.split("_")[-1])
                        for col in df.columns
                        if any(col.startswith(prefix) for prefix in ["cycle_", "Pc_", "Krw_", "Kro_"])
                    )
                )

                renamed = {}
                for group_idx in group_indices:
                    renamed[f"cycle_{group_idx}"] = f"cycle_{index_counter}"
                    renamed[f"Pc_{group_idx}"] = f"Pc_{index_counter}"
                    renamed[f"Krw_{group_idx}"] = f"Krw_{index_counter}"
                    renamed[f"Kro_{group_idx}"] = f"Kro_{index_counter}"

                    group_columns.append(index_counter)
                    index_counter += 1

                renamed_df = df.rename(columns=renamed).drop(columns=["cycle", "Sw"], errors="ignore")
                renamed_dfs.append(renamed_df)

            # Concatenate horizontally
            result_df = pd.concat([base_df] + renamed_dfs, axis=1)

            # Sanity check: no duplicate columns
            duplicates = result_df.columns[result_df.columns.duplicated()].tolist()
            assert not duplicates, f"Duplicate columns detected: {duplicates}"

            # Compute _middle columns
            pc_cols = [f"Pc_{i}" for i in group_columns]
            krw_cols = [f"Krw_{i}" for i in group_columns]
            kro_cols = [f"Kro_{i}" for i in group_columns]

            result_df["Pc_middle"] = result_df[pc_cols].mean(axis=1)
            result_df["Krw_middle"] = result_df[krw_cols].mean(axis=1)
            result_df["Kro_middle"] = result_df[kro_cols].mean(axis=1)

            # Cast to float32 (except 'cycle' and 'Sw')
            float_cols = [col for col in result_df.columns if col not in ["cycle", "Sw"]]
            result_df[float_cols] = result_df[float_cols].values.astype(np.float32)

            return result_df

        # Aggregate krelResults
        krel_df = load_and_concat("krelResults*")
        krel_table_node = dataFrameToTableNode(krel_df)
        krel_table_node.SetName(slicer.mrmlScene.GenerateUniqueName("Krel_results"))
        krel_table_node.SetAttribute("table_type", "krel_simulation_results")
        folder_tree.CreateItem(root_dir, krel_table_node)

        # Aggregate cycles
        for cycle in range(1, 4):
            pattern = f"krelCycle{cycle}*"
            files = list(self.job_local_path.glob(pattern))
            if not files:
                raise FileNotFoundError(f"No files found matching pattern: {pattern}")
            dataframes = [pd.read_pickle(str(f)) for f in sorted(files)]

            # Aggregate horizontally with reindexing and middle calculation
            cycle_df = aggregate_cycle_data(dataframes)
            cycle_table_node = dataFrameToTableNode(cycle_df)
            cycle_table_node.SetName(slicer.mrmlScene.GenerateUniqueName(f"krel_table_cycle{cycle}"))
            cycle_table_node.SetAttribute(f"table_type", "relative_permeability")
            krel_table_node.SetAttribute(f"cycle_table_{cycle}_id", cycle_table_node.GetID())
            folder_tree.CreateItem(table_dir, cycle_table_node)

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

    def get_number_of_simulations(self):
        num_tests = 1
        for key, value in self.params.items():
            if type(value) == list or type(value) == tuple:
                num_tests *= len(value)
        return num_tests
