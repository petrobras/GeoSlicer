# from ltrace.remote.connections import JobExecutor
#
#
# def pucnet_loader(job: JobExecutor):
#     from ImageLogCustomSegmenterRemoteTask.PUCModelExecutionHandler import PUCModelExecutionHandler
#
#     details = job.details
#     output_name = details.get("output_name", "output")
#     class_of_interest = details.get("class_of_interest", 0)
#     depth_interval = details.get("depth_interval", (0, 0))
#     inputNodeId = details.get("input_volume_node_id", None)
#     script_path = details.get("script_path", "")
#     bin_path = details.get("bin_path", "")
#
#     handler = ResultHandler()
#
#     task_handler = PUCModelExecutionHandler(
#         handler,
#         output_name,
#         bin_path=bin_path,
#         script_path=script_path,
#         image_log_node_id=inputNodeId,
#         class_of_interest=class_of_interest,
#         depth_interval=depth_interval,
#         opening_cmd="",
#     )
#
#     task_handler.jobid = str(job.details["job_id"][0])
#     job.task_handler = task_handler
#     print("JOB ok:", job)
#     return job
