import logging
from pathlib import Path, PurePosixPath

from ltrace.remote.connections import JobExecutor
from ltrace.remote.handlers.PoreNetworkRemoteWorkflowHandler import PoreNetworkRemoteWorkflowHandler


def pnmworkflow_loader(job: JobExecutor):
    details = job.details or {}

    workflow_dir_name = details.get("workflow_dir_name")
    workflow_remote_path = details.get("workflow_remote_path")
    workflow_local_path = details.get("workflow_local_path")

    # The handler indexes item["name"] over this, so anything that is not a
    # list of dicts has to be dropped here rather than blow up in __init__.
    files_data = details.get("files_data") or []
    if not isinstance(files_data, list) or not all(isinstance(item, dict) and "name" in item for item in files_data):
        logging.warning(f"Job {job.uid} carries unusable files_data. Rebuilding the handler without it.")
        files_data = []

    prefix = details.get("prefix")
    slurm_jobs = details.get("slurm_jobs")
    slurm_job_ids = details.get("slurm_job_ids")
    successful_job_ids = details.get("successful_job_ids")
    failed_files = details.get("failed_files")
    workflow_params = details.get("workflow_params")

    handler = PoreNetworkRemoteWorkflowHandler(files_data, prefix, workflow_params)

    handler.workflow_dir_name = workflow_dir_name
    if workflow_remote_path:
        handler.workflow_remote_path = PurePosixPath(workflow_remote_path)
    if workflow_local_path:
        handler.workflow_local_path = Path(workflow_local_path)
    handler.slurm_jobs = slurm_jobs or {}
    handler.slurm_job_ids = slurm_job_ids or []
    handler.successful_job_ids = successful_job_ids or []
    handler.failed_files = set(failed_files) if failed_files else set()

    job.task_handler = handler
    logging.debug(f"Mounted pnmworkflow job {job.uid}.")
    return job
