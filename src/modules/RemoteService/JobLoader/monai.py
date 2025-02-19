from ltrace.remote.connections import JobExecutor


def monai_job_loader(job: JobExecutor):
    details = job.details
    IP = details.get("nodeIP", "")
    appPath = details.get("appPath", "")
    datasetPath = details.get("datasetPath", "")
    job.task_handler = MonaiLabelServerHandler(app_folder=appPath, dataset_folder=datasetPath)

    return job
