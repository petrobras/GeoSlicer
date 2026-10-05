import logging
from pathlib import Path, PurePosixPath

from ltrace.remote.connections import JobExecutor
from ltrace.remote.handlers.PoreNetworkExtractorHandler import PoreNetworkExtractorHandler


def pnmextractor_loader(job: JobExecutor):
    details = job.details or {}

    input_node_id = details.get("input_node_id")
    label_node_id = details.get("label_node_id")
    visualization = details.get("visualization")
    params = details.get("params")
    parallel_params = details.get("parallel_params")
    job_remote_path = details.get("job_remote_path")
    job_local_path = details.get("job_local_path")
    slurm_job_ids = details.get("slurm_job_ids")

    handler = PoreNetworkExtractorHandler(input_node_id, label_node_id, visualization, params, parallel_params)
    # Only override the handler's own defaults (None) when the job actually
    # carries a path: PurePosixPath(None) raises TypeError.
    if job_remote_path:
        handler.job_remote_path = PurePosixPath(job_remote_path)
    if job_local_path:
        handler.job_local_path = Path(job_local_path)
    handler.slurm_job_ids = slurm_job_ids or []
    job.task_handler = handler
    logging.debug(f"Mounted pnmextractor job {job.uid}.")
    return job
