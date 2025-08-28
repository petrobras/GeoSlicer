from pathlib import Path, PurePosixPath

from ltrace.remote.connections import JobExecutor
from ltrace.remote.handlers.PoreNetworkExtractorHandler import PoreNetworkExtractorHandler


def pnmextractor_loader(job: JobExecutor):
    details = job.details

    input_node_id = details.get("input_node_id")
    label_node_id = details.get("label_node_id")
    params = details.get("params")
    job_remote_path = details.get("job_remote_path")
    job_local_path = details.get("job_local_path")
    slurm_job_ids = details.get("slurm_job_ids")

    handler = PoreNetworkExtractorHandler(input_node_id, label_node_id, params)
    handler.job_remote_path = PurePosixPath(job_remote_path)
    handler.job_local_path = Path(job_local_path)
    handler.slurm_job_ids = slurm_job_ids
    job.task_handler = handler
    print(job, handler)
    return job
