#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import argparse
import gc
import json
import logging
import os
import random
import sys
import traceback
from pathlib import Path

import dask
from dask.distributed import Client, as_completed
from dask_jobqueue import SLURMCluster

from ltrace.remote.slurm import MAX_WORKERS
from ltrace.slicer.cli_utils import progressUpdate
from .workstep.crop_sample import CropSampleWorkstep
from .workstep.extractor import ExtractorWorkstep
from .workstep.load_data import LoadDataWorkstep
from .workstep.one_phase_simulation import OnePhaseSimulationWorkstep
from .workstep.porosity_map import PorosityMapWorkstep
from .workstep.shading_correction import ShadingCorrectionWorkstep
from .workstep.two_phase_simulation import TwoPhaseSimulationWorkstep
from .workstep.workstep import WorkflowContext

# Extended Dask configuration for severe GIL stalls and heavy synchronous processing
dask.config.set(
    {
        # Suppress "Event loop was unresponsive" warnings until the stall exceeds 5 minutes
        "distributed.admin.tick.limit": "300s",
        # Time the scheduler waits without a heartbeat before declaring a worker dead (10 minutes)
        "distributed.scheduler.worker-ttl": "600s",
        # Network socket connection timeout (5 minutes)
        "distributed.comm.timeouts.connect": "300s",
        # Network TCP read/write timeout (5 minutes)
        "distributed.comm.timeouts.tcp": "300s",
        # Time to wait before giving up on an unresponsive worker step (10 minutes)
        "distributed.deploy.lost-worker-timeout": "600s",
    }
)


def process_sample(working_dir_str, netcdf_file_path_str, sample_params):
    """Worker function executed across SLURM cluster to process a single sample."""

    # Configure standard logging for this specific Dask worker process
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
        datefmt="%d/%m/%Y %H:%M:%S",
        stream=sys.stdout,
    )
    logger = logging.getLogger("RemoteWorkFlowCLI")

    working_dir = Path(working_dir_str)
    working_dir.mkdir(parents=True, exist_ok=True)
    netcdf_file_path = Path(netcdf_file_path_str)

    header_text = f"PROCESSING SAMPLE: {working_dir_str}"
    border = "=" * len(header_text)
    logger.info(border)
    logger.info(header_text)
    logger.info(border)

    # Initialize the global context for this run
    context = WorkflowContext(working_dir=working_dir, workflow_params=sample_params, netcdf_file_path=netcdf_file_path)

    LoadDataWorkstep(context).execute()

    if not context.workflow_params.get("visualize", False):
        if context.workflow_params.get("crop_sample"):
            CropSampleWorkstep(context).execute()

        if context.workflow_params.get("shading_correction"):
            ShadingCorrectionWorkstep(context).execute()

        PorosityMapWorkstep(context).execute()

        if context.workflow_params.get("extractor"):
            ExtractorWorkstep(context).execute()
            if context.workflow_params.get("one_phase_simulation"):
                OnePhaseSimulationWorkstep(context).execute()
            if context.workflow_params.get("two_phase_simulation"):
                TwoPhaseSimulationWorkstep(context).execute()

    # Mark individual sample workflow as finalized and dump updated params
    context.workflow_params["workflow_done"] = True
    context.save_params()

    logger.info(f"Completed job for directory: {working_dir_str}")

    # Memory cleanup
    del context
    gc.collect()

    return str(working_dir.name)


def _record_failure(task, exception, failed_tasks_list=None):
    """Unified helper to format exception output and record task failure immediately."""
    job_working_dir_str, netcdf_file_path_str, sample_params = task
    err_msg = str(exception)
    tb_msg = traceback.format_exc()

    sample_name = sample_params.get("name", "")

    print(f"\n--- Task Failed: {sample_name} (DS={sample_params.get('downsampling_factor')}) ---")
    print(f"Error: {err_msg}")

    failure_data = {
        "sample_name": sample_name,
        "downsampling_factor": sample_params.get("downsampling_factor"),
        "working_dir": job_working_dir_str,
        "netcdf_file_path": netcdf_file_path_str,
        "error": err_msg,
        "traceback": tb_msg,
    }

    if failed_tasks_list is not None:
        failed_tasks_list.append(failure_data)

    job_working_dir = Path(job_working_dir_str)
    main_workflow_dir = job_working_dir.parent
    main_workflow_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write individual task failure JSON in the main workflow dir
    failure_file_name = f"failed_task_{job_working_dir.name}.json"
    failure_file_path = main_workflow_dir / failure_file_name

    try:
        with open(failure_file_path, "w") as f:
            json.dump(failure_data, f, indent=4)
        print(f"Failure log written to: {failure_file_path}")
    except Exception as e:
        print(f"Failed to write failure file to {failure_file_path}: {e}")

    # 2. Immediately update global JSON list containing unique failed sample names
    global_failed_samples_path = main_workflow_dir / "failed_samples.json"
    try:
        failed_samples = set()
        if global_failed_samples_path.exists():
            with open(global_failed_samples_path, "r") as f:
                failed_samples = set(json.load(f))

        if sample_name:
            failed_samples.add(sample_name)

        with open(global_failed_samples_path, "w") as f:
            json.dump(sorted(list(failed_samples)), f, indent=4)
        print(f"Updated global failed samples file: {global_failed_samples_path}")
    except Exception as e:
        print(f"Failed to update global failure samples file: {e}")


def run_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--slurm_jobs", type=int, default=4, required=False)
    args = parser.parse_args()

    print(f"Current Working Directory: {os.getcwd()}")
    progressUpdate(value=0.0)

    working_dir = Path(args.cwd).resolve()

    with open(working_dir / "workflow_params_dict.json", "r") as file:
        workflow_params = json.load(file)

    files_data = workflow_params.get("files_data", [])
    factors = workflow_params.get("downsampling_factors", [1])

    # Read transmitted runtime and hardware configuration
    walltime = workflow_params.get("walltime", "72:00:00")
    use_gpu = workflow_params.get("use_gpu", True)

    base_netcdf_dir = Path("/atena/tcr/ia-drp/banco_de_dados/")

    tasks = []
    for item in files_data:
        file_name = item["name"]
        sample_phi = item.get("sample_phi")
        for run_idx, ds_factor in enumerate(factors):
            job_dir_name = f"{Path(file_name).stem}_DS{ds_factor}_R{run_idx}"
            job_working_dir = working_dir / job_dir_name
            netcdf_file_path = base_netcdf_dir / file_name

            sample_params = workflow_params.copy()
            sample_params["name"] = file_name
            sample_params["sample_phi"] = sample_phi
            sample_params["downsampling_factor"] = ds_factor

            tasks.append((str(job_working_dir), str(netcdf_file_path), sample_params))

    random.shuffle(tasks)
    failed_tasks = []

    # Dynamically build SLURM worker directives based on GPU request
    job_extra_directives = ["--cpus-per-task=16"]

    # Export Application Layer thread limits so OpenMP, MKL, OpenBLAS, and NumExpr
    # utilize all 16 allocated CPUs for the single active sample task.
    job_script_prologue = [
        "export OMP_NUM_THREADS=16",
        "export MKL_NUM_THREADS=16",
        "export OPENBLAS_NUM_THREADS=16",
        "export NUMEXPR_NUM_THREADS=16",
        "export VECLIB_MAXIMUM_THREADS=16",
    ]

    if use_gpu:
        job_extra_directives.extend(["--partition=gpu", "--gres=gpu:1"])
        job_script_prologue.append("export APPTAINER_USE_NVIDIA=true")

    geoslicer_base_path = os.getenv("GEOSLICER_BASE_PATH")
    cluster = SLURMCluster(
        cores=1,  # 1 task per SLURM job
        memory="256GB",
        job_extra_directives=job_extra_directives,
        job_script_prologue=job_script_prologue,
        interface="bond0",
        scheduler_options={"interface": "bond0"},
        job_name=f"pnm_worker_{working_dir.name}",
        python=f"{geoslicer_base_path}/scripts/run_apptainer.sh" if geoslicer_base_path else "python",
        account="tcr_ext",
        log_directory=str(working_dir),
        processes=1,
        death_timeout=3600,
        walltime=walltime,
    )

    target_jobs = min(args.slurm_jobs, len(tasks), MAX_WORKERS)
    print(f"Enabling adaptive scaling up to {target_jobs} jobs...")

    cluster.adapt(
        minimum=0,
        maximum=target_jobs,
        target_duration="5m",
        interval="10s",
        wait_count=3,
    )

    client = Client(cluster)

    future_to_task = {client.submit(process_sample, *task): task for task in tasks}

    for i, future in enumerate(as_completed(future_to_task)):
        task = future_to_task[future]
        try:
            future.result()
        except Exception as e:
            _record_failure(task, e, failed_tasks)
        finally:
            progressUpdate(value=0.1 + (0.9 * ((i + 1) / len(tasks))))

    client.close()
    cluster.close()

    if failed_tasks:
        print("\n" + "=" * 60)
        print(f"SUMMARY: {len(failed_tasks)} / {len(tasks)} TASKS FAILED")
        print("=" * 60)
        for fail in failed_tasks:
            print(f"• Sample: {fail['sample_name']} (DS {fail['downsampling_factor']})")
            print(f"  Directory: {fail['working_dir']}")
            print(f"  Error: {fail['error']}\n")
    else:
        print("\nAll tasks completed successfully!")

    progressUpdate(value=1.0)
    print("Done")


if __name__ == "__main__":
    run_cli()
