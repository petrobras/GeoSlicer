from pathlib import Path, PurePosixPath

from ltrace.remote.connections import JobExecutor
from ltrace.remote.handlers.PoreNetworkRemoteWorkflowHandler import PoreNetworkRemoteWorkflowHandler


def pnmworkflow_loader(job: JobExecutor):
    details = job.details

    workflow_dir_name = details.get("workflow_dir_name")
    workflow_remote_path = details.get("workflow_remote_path")
    workflow_local_path = details.get("workflow_local_path")

    files_data = details.get("files_data")
    prefix = details.get("prefix")
    slurm_jobs = details.get("slurm_jobs")
    slurm_job_ids = details.get("slurm_job_ids")
    successful_job_ids = details.get("successful_job_ids")
    failed_files = details.get("failed_files")
    workflow_params = details.get("workflow_params")

    handler = PoreNetworkRemoteWorkflowHandler(files_data, prefix, workflow_params)

    handler.workflow_dir_name = workflow_dir_name
    handler.workflow_remote_path = PurePosixPath(workflow_remote_path)
    handler.workflow_local_path = Path(workflow_local_path)
    handler.slurm_jobs = slurm_jobs
    handler.slurm_job_ids = slurm_job_ids
    handler.successful_job_ids = successful_job_ids
    handler.failed_files = set(failed_files) if failed_files else set()

    job.task_handler = handler
    print(job, handler)
    return job
