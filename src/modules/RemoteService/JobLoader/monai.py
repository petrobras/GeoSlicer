import logging

from ltrace.remote.connections import JobExecutor
from ltrace.remote.handlers import MonaiLabelServerHandler


def monai_job_loader(job: JobExecutor):
    details = job.details or {}
    appPath = details.get("appPath", "")
    datasetPath = details.get("datasetPath", "")

    job.task_handler = MonaiLabelServerHandler(app_folder=appPath, dataset_folder=datasetPath)
    logging.debug(f"Mounted monai job {job.uid}.")

    return job
