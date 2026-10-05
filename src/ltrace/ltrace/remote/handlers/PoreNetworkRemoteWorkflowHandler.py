import json
import logging
import re
import shutil
import traceback
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, List

import numpy as np
import pandas as pd
import slicer
import vtk

from ltrace.pore_networks.functions_extract import ExtractionNodesCreator
from ltrace.pore_networks.remote_workflow.remote_workflow_report import generate_remote_workflow_report
from ltrace.pore_networks.simulation_parameters_node import PNM_PARAMETER_TYPE_ATTR, REMOTE_WORKFLOW_TYPE
from ltrace.remote import errors
from ltrace.remote import utils as slurm_utils
from ltrace.remote.handlers.PoreNetworkSimulationHandler import collect_two_phase_simulation
from ltrace.remote.jobs import JobManager
from ltrace.remote.object_transfer import JsonObjectTransfer
from ltrace.remote.utils import argstring, SlurmJobStatusMixin
from ltrace.slicer.data_utils import dataFrameToTableNode
from ltrace.slicer.lazy import lazy

_1hour = 3600  # seconds


class PoreNetworkRemoteWorkflowHandler(SlurmJobStatusMixin):

    JOB_ID_PATTERN = re.compile(r"job_id = ([a-zA-Z0-9]+)")

    def __init__(
        self,
        files_data,
        prefix,
        workflow_params,
    ):
        super().__init__(timeout_seconds=_1hour)

        self.files_data = files_data  # list of dicts: [{'name': 'file.nc', 'phi': 0.15}, ...]
        self.files = [item["name"] for item in files_data]
        self.prefix = prefix
        self.workflow_params = workflow_params

        self.slurm_jobs = {}
        self.slurm_job_ids = []
        self.failed_files = set()

        self.workflow_dir_name = None
        self.workflow_remote_path = None
        self.workflow_local_path = None

        self.__action_map = {
            "DEPLOY": self.deploy,
            "DISCONNECTED": self.disconnected,
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
            logging.error(f"Invalid action: {action}")

    def deploy(self, caller: JobManager, uid: str, client: Any = None):
        try:
            caller.set_state(uid, "DEPLOYING", 0, message="Job main directory created.")
            job_executor = caller.jobs[uid]
            storage = job_executor.host.get_storage()
            self.workflow_dir_name = JobManager.dirname(job_executor)
            self.workflow_remote_path = storage.remote_dir("geoslicer_jobs") / self.workflow_dir_name
            self.workflow_local_path = storage.local_dir("geoslicer_jobs") / self.workflow_dir_name
            client.run_command(f"mkdir -p {self.workflow_remote_path} && chmod -R 777 {self.workflow_remote_path}")
            caller.schedule(uid, "START")
        except errors.ChannelError as e:
            # The host dropped us mid-deploy: nothing is known about the
            # processing, so this must not become a terminal FAILED. Hand it to
            # the reconnection backoff, which flags NOT CONNECTED and retries.
            self.disconnected(caller, uid, client, error=e)
        except Exception:
            traceback.print_exc()
            caller.set_state(uid, "FAILED", 100, message="Deployment failed.")
            caller.persist(uid)

    def start(self, caller: JobManager, uid: str, client: Any = None):
        ts_start = datetime.now().timestamp()
        caller.set_state(uid, "SENDING JOBS", 5, message="Submitting master workflow job.")

        try:
            storage = caller.jobs[uid].host.get_storage()

            # Extract wall time and GPU settings from workflow_params
            walltime = self.workflow_params.get("walltime", "72:00:00")
            use_gpu = self.workflow_params.get("use_gpu", True)

            # Package parameters for the CLI
            workflow_params = self.workflow_params.copy()
            workflow_params["files_data"] = self.files_data
            workflow_params["walltime"] = walltime
            workflow_params["use_gpu"] = use_gpu

            with JsonObjectTransfer(self.workflow_local_path, "workflow_params_dict.json") as transfer:
                transfer.save(workflow_params)

            # Determine the maximum amount of Dask nodes to deploy
            factors = workflow_params.get("downsampling_factors", [1])
            total_tasks = len(self.files_data) * len(factors)

            # Read max workers from UI workflow parameters (defaulting to 9)
            workers = workflow_params.get("workers", 9)
            max_slurm_jobs = min(workers, total_tasks)

            cli_params = {"cwd": str(self.workflow_remote_path), "slurm_jobs": max_slurm_jobs}

            # Manually append the --slurm flag so argstring doesn't convert it to "--slurm True"
            cli_cmd_str = " ".join(
                ["PoreNetworkRemoteWorkFlowCLI.PoreNetworkRemoteWorkFlowCLI", argstring(cli_params)]
            )

            main_cmd = slurm_utils.get_python_cmd(
                cli_cmd_list=[cli_cmd_str],
                time=walltime,
                use_gpu=use_gpu,
            )

            full_cmd = slurm_utils.get_job_cmd(caller, uid, main_cmd, self.workflow_remote_path)

            output = client.run_command(full_cmd, verbose=True)
            match = self.JOB_ID_PATTERN.search(output["stdout"])

            if not match:
                raise RuntimeError("Failed to match job ID for master CLI job.")

            master_job_id = match.group(1)

            # Track only the master job
            self.slurm_jobs[master_job_id] = {
                "remote_path": str(self.workflow_remote_path),
                "local_path": str(self.workflow_local_path),
                "start_time": datetime.now().timestamp(),
            }
            self.slurm_job_ids = [master_job_id]

            details = {
                "workflow_dir_name": self.workflow_dir_name,
                "workflow_remote_path": str(self.workflow_remote_path),
                "workflow_local_path": str(self.workflow_local_path),
                "files_data": self.files_data,
                "prefix": self.prefix,
                "slurm_jobs": self.slurm_jobs,
                "slurm_job_ids": self.slurm_job_ids,
                "workflow_params": self.workflow_params,
            }

            caller.set_state(
                uid,
                "RUNNING",
                10,
                message="Master workflow job submitted to cluster.",
                start_time=ts_start,
                details=details,
            )
            caller.persist(uid)
            caller.schedule(uid, "PROGRESS")

        except errors.ChannelError as e:
            # The host dropped us mid-submission: nothing is known about the
            # processing, so this must not become a terminal FAILED. Hand it to
            # the reconnection backoff, which flags NOT CONNECTED and retries.
            self.disconnected(caller, uid, client, error=e)
        except Exception:
            traceback.print_exc()
            caller.set_state(uid, "FAILED", 100, message="Failed to start master job.")
            caller.persist(uid)

    def _post_status_update(self, caller: JobManager, uid: str, client: Any, job_status: List[dict]):
        """Track the master job and read execution progress from its SLURM output file."""
        try:
            if slurm_utils.all_done(job_status):
                # Ensure the master job actually finished with COMPLETED state
                master_completed = any(job.get("state") == "COMPLETED" for job in job_status)

                if master_completed:
                    # Provide successful_job_ids to keep the collect() method's validation happy
                    details = {"successful_job_ids": self.slurm_job_ids}
                    caller.set_state(
                        uid,
                        "COMPLETED",
                        100,
                        message="Master job completed successfully.",
                        end_time=datetime.now().timestamp(),
                        details=details,
                    )
                else:
                    caller.set_state(
                        uid,
                        "FAILED",
                        100,
                        message="Master job failed or was cancelled.",
                        end_time=datetime.now().timestamp(),
                    )
                caller.persist(uid)
                return

            # Read progress from the master job's slurm output file
            total_progress = 0
            count = 0
            for job_id in self.slurm_job_ids:
                slurm_out = self.workflow_local_path / f"slurm-{job_id}.out"
                total_progress += self.read_last_progress(slurm_out)
                count += 1

            avg_progress = max(total_progress / count, 10) if count > 0 else 10

            caller.set_state(uid, "RUNNING", avg_progress, details={"successful_job_ids": self.slurm_job_ids})
            caller.schedule(uid, "PROGRESS")

        except errors.ChannelError:
            # Let it out to SlurmJobStatusMixin.progress, whose own handler
            # routes it to disconnected(). Catching it here is what used to
            # turn a dropped connection into a terminal FAILED, defeating the
            # reconnection backoff that already exists one frame up.
            raise
        except Exception as e:
            traceback.print_exc()
            caller.set_state(
                uid,
                "FAILED",
                100,
                message=f"Exception in progress: {repr(e)}",
                end_time=datetime.now().timestamp(),
            )
            caller.persist(uid)

    def read_last_progress(self, slurm_out_file_path):
        """Parses the SLURM .out file for standard Slicer progress XML tags."""
        last_progress = 0.1
        try:
            with slurm_out_file_path.open("r") as f:
                for line in f:
                    match = re.search(r"<filter-progress>(0(?:\.\d+)?|1(?:\.0+)?)</filter-progress>", line)
                    if match:
                        last_progress = float(match.group(1))
        except FileNotFoundError:
            # File might not be created on the cluster immediately
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
        # Cancel the master SLURM job
        if self.slurm_jobs:
            job_ids = ",".join(job_id for job_id in self.slurm_jobs.keys())
            try:
                output = client.run_command(f"scancel {job_ids}")
                if len(output["stderr"]) > 0:
                    raise Exception(output["stderr"])
            except Exception:
                traceback.print_exc()

        # Cancel Dask workers targeting this run's unique job name
        if client and self.workflow_dir_name:
            try:
                client.run_command(f"scancel --name=pnm_worker_{self.workflow_dir_name}")
            except Exception:
                traceback.print_exc()

        try:
            caller.remove(uid)
            if not (client and self.workflow_remote_path):
                raise RuntimeError("No remote client/path available for cleanup")
            # Delayed removal running asynchronously in the background on the remote host
            cmd = f"nohup bash -c 'sleep 60 && rm -rf \"{self.workflow_remote_path}\"' > /dev/null 2>&1 &"
            client.run_command(cmd)
        except Exception:
            local_path = self.workflow_local_path
            if local_path and local_path.exists():
                shutil.rmtree(local_path, ignore_errors=True)

    @staticmethod
    def _process_krel_cycle_dataframes(dataframes):
        """Helper matrix transformation engine for cycle results parsing."""
        base_df = dataframes[0][["cycle", "Sw"]].copy()
        group_columns = []
        index_counter = 0
        renamed_dfs = []

        for df in dataframes:
            df = df[[col for col in df.columns if not col.endswith("_middle")]]
            group_indices = sorted(
                set(
                    int(col.split("_")[-1])
                    for col in df.columns
                    if any(col.startswith(p) for p in ["cycle_", "Pc_", "Krw_", "Kro_"])
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

        result_df = pd.concat([base_df] + renamed_dfs, axis=1)
        pc_cols = [f"Pc_{i}" for i in group_columns]
        krw_cols = [f"Krw_{i}" for i in group_columns]
        kro_cols = [f"Kro_{i}" for i in group_columns]

        result_df["Pc_middle"] = result_df[pc_cols].mean(axis=1)
        result_df["Krw_middle"] = result_df[krw_cols].mean(axis=1)
        result_df["Kro_middle"] = result_df[kro_cols].mean(axis=1)

        float_cols = [col for col in result_df.columns if col not in ["cycle", "Sw"]]
        result_df[float_cols] = result_df[float_cols].values.astype(np.float32)

        return result_df

    def _aggregate_two_phase_results(
        self,
        is_visualization: bool,
        sample_workflow_params: dict,
        file_ds_map: dict,
        workflow_folder_item: Any,
    ):
        """Aggregates two-phase simulation results directly from remote run folders instead of local disk cache."""
        shn = slicer.mrmlScene.GetSubjectHierarchyNode()

        if not is_visualization and sample_workflow_params.get("two_phase_simulation"):
            for file_name_stem, ds_runs in file_ds_map.items():
                if len(ds_runs) > 1:
                    sample_folder_item = shn.GetItemChildWithName(workflow_folder_item, file_name_stem)
                    agg_folder_item = shn.GetItemChildWithName(sample_folder_item, "Aggregated_Two_Phase_Results")

                    # --- Remove old aggregation nodes and folder branch entirely if they exist ---
                    if agg_folder_item != 0:
                        child_items = vtk.vtkIdList()
                        shn.GetItemChildren(agg_folder_item, child_items, True)  # Recursive fetch
                        for i in range(child_items.GetNumberOfIds()):
                            child_id = child_items.GetId(i)
                            child_node = shn.GetItemDataNode(child_id)
                            if child_node:
                                slicer.mrmlScene.RemoveNode(child_node)
                        shn.RemoveItem(agg_folder_item)

                    # Fresh initialization every time
                    agg_folder_item = shn.CreateFolderItem(sample_folder_item, "Aggregated_Two_Phase_Results")
                    shn.SetItemExpanded(agg_folder_item, False)
                    table_dir = shn.CreateFolderItem(agg_folder_item, "Tables")
                    shn.SetItemExpanded(table_dir, False)
                    # --------------------------------------------------------------------------------------

                    # 1. Aggregate Krel Results (reading directly from original staging pickle files)
                    krel_dfs = []
                    for ds, run_idx in sorted(ds_runs):
                        job_suffix = f"DS{ds}_R{run_idx}"
                        job_dir_name = f"{file_name_stem}_{job_suffix}"
                        job_local_path = self.workflow_local_path / job_dir_name

                        pattern = "krelResults*"
                        files = list(job_local_path.glob(pattern))
                        if files:
                            dataframes = [pd.read_pickle(str(f)) for f in sorted(files)]
                            df = pd.concat(dataframes, ignore_index=True)
                            df["DS_factor"] = ds
                            krel_dfs.append(df)

                    if krel_dfs:
                        agg_krel_df = pd.concat(krel_dfs, ignore_index=True)

                        cols_to_drop = []
                        for col in agg_krel_df.columns:
                            valid_items = agg_krel_df[col].dropna()
                            if not valid_items.empty:
                                val = str(valid_items.iloc[0]).strip()
                                if val.startswith("{") and val.endswith("}"):
                                    cols_to_drop.append(col)
                                elif val.startswith("[") and val.endswith("]"):
                                    cols_to_drop.append(col)

                        if cols_to_drop:
                            agg_krel_df.drop(columns=cols_to_drop, inplace=True)

                        # Average over all runs for the same DS_factor (grouped by Sw if available)
                        if "Sw" in agg_krel_df.columns:
                            agg_krel_df = agg_krel_df.groupby(["DS_factor", "Sw"], as_index=False).mean(
                                numeric_only=True
                            )
                        else:
                            agg_krel_df = agg_krel_df.groupby(["DS_factor"], as_index=False).mean(numeric_only=True)

                        krel_table_node = dataFrameToTableNode(agg_krel_df)
                        krel_table_node.SetName(
                            slicer.mrmlScene.GenerateUniqueName(f"{file_name_stem}_Aggregated_Krel_results")
                        )
                        krel_table_node.SetAttribute("table_type", "krel_simulation_results")
                        shn.CreateItem(agg_folder_item, krel_table_node)

                    # 2. Aggregate Cycles using mean curves mapped properly by DS factor
                    for cycle in range(1, 4):
                        cycle_dfs = []
                        for ds, run_idx in sorted(ds_runs):
                            job_suffix = f"DS{ds}_R{run_idx}"
                            job_dir_name = f"{file_name_stem}_{job_suffix}"
                            job_local_path = self.workflow_local_path / job_dir_name

                            cycle_pattern = f"krelCycle{cycle}*"
                            cycle_files = list(job_local_path.glob(cycle_pattern))
                            if cycle_files:
                                dataframes = [pd.read_pickle(str(f)) for f in sorted(cycle_files)]
                                cycle_df = self._process_krel_cycle_dataframes(dataframes)
                                cycle_dfs.append((ds, cycle_df))

                        if cycle_dfs:
                            agg_cycle_df = self.aggregate_middle_krel_cycle_dfs(cycle_dfs)

                            cycle_table_node = dataFrameToTableNode(agg_cycle_df)
                            cycle_table_node.SetName(
                                slicer.mrmlScene.GenerateUniqueName(
                                    f"{file_name_stem}_Aggregated_krel_table_cycle{cycle}"
                                )
                            )
                            cycle_table_node.SetAttribute("table_type", "relative_permeability")
                            if krel_dfs:
                                krel_table_node.SetAttribute(f"cycle_table_{cycle}_id", cycle_table_node.GetID())
                            shn.CreateItem(table_dir, cycle_table_node)

    @staticmethod
    def aggregate_middle_krel_cycle_dfs(ds_df_tuples):
        """
        Extracts only the _middle columns for each DS factor,
        averages them across all runs of the same DS factor,
        and returns the aggregated mean curves per DS factor.
        """
        base_df = ds_df_tuples[0][1][["cycle", "Sw"]].copy()

        # Group dataframes by DS factor
        ds_groups = {}
        for ds, df in ds_df_tuples:
            if ds not in ds_groups:
                ds_groups[ds] = []
            ds_groups[ds].append(df)

        renamed_dfs = []

        for ds, dfs in ds_groups.items():
            # Extract only the middle results to compute the mean curve for this DS factor
            pc_cols = [df["Pc_middle"] for df in dfs if "Pc_middle" in df.columns]
            krw_cols = [df["Krw_middle"] for df in dfs if "Krw_middle" in df.columns]
            kro_cols = [df["Kro_middle"] for df in dfs if "Kro_middle" in df.columns]

            ds_df = pd.DataFrame()
            if pc_cols:
                ds_df[f"Pc_DS{ds}"] = pd.concat(pc_cols, axis=1).mean(axis=1)
            if krw_cols:
                ds_df[f"Krw_DS{ds}"] = pd.concat(krw_cols, axis=1).mean(axis=1)
            if kro_cols:
                ds_df[f"Kro_DS{ds}"] = pd.concat(kro_cols, axis=1).mean(axis=1)

            if not ds_df.empty:
                renamed_dfs.append(ds_df)

        # Concatenate horizontally
        result_df = pd.concat([base_df] + renamed_dfs, axis=1)

        # Cast back to float32
        float_cols = [col for col in result_df.columns if col not in ["cycle", "Sw"]]
        result_df[float_cols] = result_df[float_cols].values.astype(np.float32)

        return result_df

    def collect(self, caller: JobManager, uid: str, client: Any = None):
        storage = caller.jobs[uid].host.get_storage()

        # Retrieve the list of successful job IDs from the persisted details
        details = caller.jobs[uid].details or {}
        successful_job_ids = set(details.get("successful_job_ids", []))

        shn = slicer.mrmlScene.GetSubjectHierarchyNode()
        scene_item_id = shn.GetSceneItemID()
        workflow_folder_name = f"{self.prefix}_{self.workflow_dir_name}" if self.prefix else self.workflow_dir_name
        workflow_folder_item = shn.GetItemByName(workflow_folder_name)

        if not successful_job_ids:
            slicer.util.infoDisplay("No results yet to be collected. Wait some more time before trying again.")
            return

        if not workflow_folder_item:
            workflow_folder_item = shn.CreateFolderItem(scene_item_id, workflow_folder_name)
            shn.SetItemExpanded(workflow_folder_item, False)

        is_visualization = self.workflow_params.get("visualize", False)

        factors = self.workflow_params.get("downsampling_factors", [1])
        file_ds_map = {}
        sample_workflow_params = {}

        for item in self.files_data:
            file_name = item["name"]
            file_name_stem = f"{Path(file_name).stem}"

            for run_idx, ds_factor in enumerate(factors):
                job_suffix = f"DS{ds_factor}_R{run_idx}"
                folder_suffix = f"DS_{ds_factor}_R{run_idx}"
                job_dir_name = f"{file_name_stem}_{job_suffix}"

                job_local_path = self.workflow_local_path / job_dir_name

                # Skip mapping if job folder was not generated by cluster
                if not job_local_path.exists():
                    logging.warning(f"Skipping collection for {job_dir_name}, results folder was not generated.")
                    continue

                # Load the job-specific workflow parameters from the json file
                param_file = job_local_path / "workflow_params_dict.json"

                # Verify that the parameter file exists before continuing with collection
                if not param_file.exists():
                    logging.warning(f"Skipping collection for {job_dir_name}, workflow parameter file not found.")
                    continue

                with open(param_file, "r") as f:
                    sample_workflow_params = json.load(f)

                # --- Skip collection if the workflow execution is not complete ---
                if not sample_workflow_params.get("workflow_done", False):
                    logging.warning(f"Skipping collection for {job_dir_name}, workflow is not fully complete.")
                    continue

                # Map successful runs for aggregation
                file_ds_map.setdefault(file_name_stem, []).append((ds_factor, run_idx))

                if is_visualization:
                    target_folder_item = workflow_folder_item
                    ds_folder_item = shn.GetItemChildWithName(target_folder_item, folder_suffix)
                    if ds_folder_item == 0:
                        ds_folder_item = shn.CreateFolderItem(target_folder_item, folder_suffix)
                        shn.SetItemExpanded(ds_folder_item, False)
                else:
                    # Main sample folder
                    target_folder_item = shn.GetItemChildWithName(workflow_folder_item, file_name_stem)
                    if target_folder_item == 0:
                        target_folder_item = shn.CreateFolderItem(workflow_folder_item, file_name_stem)
                        shn.SetItemExpanded(target_folder_item, False)

                    # DS Subfolder below sample
                    ds_folder_item = shn.GetItemChildWithName(target_folder_item, folder_suffix)
                    if ds_folder_item != 0:
                        logging.info(
                            f"Skipping collection for '{file_name_stem}_{job_suffix}' as it was already collected earlier."
                        )
                        continue
                    ds_folder_item = shn.CreateFolderItem(target_folder_item, folder_suffix)
                    shn.SetItemExpanded(ds_folder_item, False)

                sample_workflow_params_node = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLTextNode", f"workflow_params_{job_suffix}"
                )
                sample_workflow_params_node.SetText(json.dumps(sample_workflow_params, indent=4))
                sample_workflow_params_node.SetAttribute(PNM_PARAMETER_TYPE_ATTR, REMOTE_WORKFLOW_TYPE)
                shn.SetItemParent(shn.GetItemByDataNode(sample_workflow_params_node), ds_folder_item)

                # --- Extract Experimental KREL Data ---
                self.collect_experimental_krel_data(
                    storage.local_dir("krel_dataset"),
                    file_name_stem=file_name_stem,
                    job_suffix=job_suffix,
                    ds_folder_item=ds_folder_item,
                )

                # Images collect
                try:
                    self.collect_images(
                        job_local_path, ds_folder_item, file_name_stem, job_suffix, sample_workflow_params
                    )
                except Exception as e:
                    logging.error(f"Failed to collect images for {file_name_stem}: {e}")

                # Extractor collect
                if sample_workflow_params.get("ExtractorWorkstep_done"):
                    try:
                        self.collect_extractor_data(
                            job_local_path, ds_folder_item, file_name_stem, job_suffix, sample_workflow_params
                        )
                    except Exception as e:
                        logging.error(f"Failed to collect extractor data for {file_name_stem}: {e}")

                # One phase simulation collect
                if sample_workflow_params.get("OnePhaseSimulationWorkstep_done"):
                    try:
                        self.collect_one_phase_simulation(
                            job_local_path, ds_folder_item, file_name_stem, job_suffix, sample_workflow_params
                        )
                    except Exception as e:
                        logging.error(f"Failed to collect one phase simulation for {file_name_stem}: {e}")

                # Two phase simulation collect
                if sample_workflow_params.get("TwoPhaseSimulationWorkstep_done"):
                    try:
                        collect_two_phase_simulation(job_local_path, ds_folder_item, f"{file_name_stem}_{job_suffix}")
                    except FileNotFoundError as e:
                        logging.warning(
                            f"Skipping two-phase simulation collection for {file_name_stem} (invalid network or missing results). Details: {e}"
                        )
                    except Exception as e:
                        logging.error(f"Failed to collect two-phase simulation for {file_name_stem}: {e}")

        # --- Aggregate Two-Phase Results Across Multiple Runs ---
        self._aggregate_two_phase_results(
            is_visualization=is_visualization,
            sample_workflow_params=sample_workflow_params,
            file_ds_map=file_ds_map,
            workflow_folder_item=workflow_folder_item,
        )

        # --- Consolidated Workflow Report ---
        try:
            generate_remote_workflow_report(workflow_folder_item)
        except Exception as e:
            logging.error(f"Failed to generate remote workflow report: {e}")

    def collect_experimental_krel_data(self, krel_dataset_obj: Path, file_name_stem: str, job_suffix: str, ds_folder_item: Any):
        """Extracts and parses experimental KREL data into Slicer."""
        shn = slicer.mrmlScene.GetSubjectHierarchyNode()
        stem_parts = file_name_stem.split("_")
        first_two_words = "_".join(stem_parts[:2])
        target_krel_filename = f"{first_two_words}_krel_ao.csv"
        krel_file_path = krel_path_obj / target_krel_filename

        if krel_file_path.exists():
            try:
                krel_df = pd.read_csv(str(krel_file_path), sep=None, engine="python")
                krel_df.rename(columns={"sw_perc": "Sw", "krw_perc": "Krw", "kro_perc": "Kro"}, inplace=True)
                krel_df["Sw"] /= 100
                krel_df["Krw"] /= 100
                krel_df["Kro"] /= 100

                krel_table_node = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLTableNode", f"{target_krel_filename}_{job_suffix}"
                )
                dataFrameToTableNode(krel_df, krel_table_node)
                shn.SetItemParent(shn.GetItemByDataNode(krel_table_node), ds_folder_item)
                logging.info(f"Loaded experimental KREL data from {krel_file_path.name}")
            except Exception as e:
                logging.error(f"Failed to load experimental KREL data for {file_name_stem} from {krel_file_path}: {e}")
        else:
            logging.info(f"No experimental KREL file found matching '{target_krel_filename}' in {krel_path_obj}")

    def collect_images(self, job_local_path, ds_folder_item, file_name_stem, job_suffix, workflow_params):
        def load_nc(file_name, node_suffix):
            shn = slicer.mrmlScene.GetSubjectHierarchyNode()
            node = lazy.create_nodes(f"{file_name_stem}_{job_suffix}", f"file://{str(job_local_path / file_name)}")[0]
            item_id = shn.GetItemByDataNode(node)
            original_parent_id = shn.GetItemParent(item_id)
            node.SetName(f"{file_name_stem}_{node_suffix}_{job_suffix}")
            node.SetAttribute("pnmremoteworkflow", "True")
            shn.SetItemParent(item_id, ds_folder_item)
            shn.RemoveItem(original_parent_id)

        if workflow_params.get("visualize") or workflow_params.get("save_workstep_image_data"):
            if workflow_params.get("LoadDataWorkstep_done"):
                load_nc("sample.nc", "Sample")

            if not workflow_params.get("visualize"):
                if workflow_params.get("CropSampleWorkstep_done"):
                    load_nc("cropped_sample_mask.nc", "Cropped_Sample_Mask")
                    load_nc("cropped_sample.nc", "Cropped_Sample")

                if workflow_params.get("ShadingCorrectionWorkstep_done"):
                    load_nc("shading_mask.nc", "Shading_Mask")
                    load_nc("shading_correction.nc", "Shading_Correction")

                if workflow_params.get("PorosityMapWorkstep_done"):
                    porosity_map_params = workflow_params.get("porosity_map_params")
                    if porosity_map_params.get("gradient_anisotropic_diffusion"):
                        load_nc("gad_pre_porosity_map.nc", "GAD_Pre_Porosity_Map")
                    load_nc("porosity_map.nc", "Porosity_Map")

    def collect_extractor_data(self, job_local_path, ds_folder_item, file_name_stem, job_suffix, workflow_params):
        extractor_params = workflow_params["extractor_params"]
        metadata = extractor_params["metadata"]
        generate_visualization = extractor_params["generate_visualization"]
        extraction_nodes_creator = ExtractionNodesCreator(
            metadata, job_local_path, f"{file_name_stem}_{job_suffix}", visualization=generate_visualization
        )
        extraction_nodes_creator.create(parent_folder=ds_folder_item)

    def collect_one_phase_simulation(
        self, job_local_path, destination_folder_item, file_name_stem, job_suffix, workflow_params
    ):
        shn = slicer.mrmlScene.GetSubjectHierarchyNode()
        prefix = f"{file_name_stem}_{job_suffix}"

        def create_table_nodes(root_dir):
            flow_rate_table_name = slicer.mrmlScene.GenerateUniqueName(f"{prefix}_flow_rate")
            flow_rate_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", flow_rate_table_name)
            flow_rate_table.SetAttribute("table_type", "flow_rate_tensor")
            flow_rate_df = pd.read_pickle(str(job_local_path / "flow.pd"))
            dataFrameToTableNode(flow_rate_df, flow_rate_table)
            shn.CreateItem(root_dir, flow_rate_table)

            permeability_table_name = slicer.mrmlScene.GenerateUniqueName(f"{prefix}_permeability")
            permeability_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", permeability_table_name)
            permeability_table.SetAttribute("table_type", "permeability_tensor")
            permeability_df = pd.read_pickle(str(job_local_path / "permeability.pd"))
            dataFrameToTableNode(permeability_df, permeability_table)
            shn.CreateItem(root_dir, permeability_table)

        one_phase_simulation_params_dict = workflow_params["one_phase_simulation_params"]

        if one_phase_simulation_params_dict.get("simulation type") == "Single orientation":
            root_dir = shn.CreateFolderItem(destination_folder_item, f"{prefix}_Single_Phase_PN_Simulation")
            create_table_nodes(root_dir)
        elif one_phase_simulation_params_dict.get("simulation type") == "Multiple orientations":
            return
        else:
            return
