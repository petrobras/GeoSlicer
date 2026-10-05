import logging
from pathlib import Path, PurePosixPath

from ltrace.remote.connections import JobExecutor
from ltrace.remote.handlers.PoreNetworkSimulationHandler import PoreNetworkSimulationHandler


def pnmsimulation_loader(job: JobExecutor):
    details = job.details or {}

    pore_table_node_id = details.get("pore_table_node_id")
    params = details.get("params")
    prefix = details.get("prefix")
    job_remote_path = details.get("job_remote_path")
    job_local_path = details.get("job_local_path")
    slurm_job_ids = details.get("slurm_job_ids")

    handler = PoreNetworkSimulationHandler(pore_table_node_id, params, prefix)
    if job_remote_path:
        handler.job_remote_path = PurePosixPath(job_remote_path)
    if job_local_path:
        handler.job_local_path = Path(job_local_path)
    handler.slurm_job_ids = slurm_job_ids or []
    job.task_handler = handler
    logging.debug(f"Mounted pnmsimulation job {job.uid}.")
    return job
