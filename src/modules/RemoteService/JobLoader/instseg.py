from ltrace.remote.connections import JobExecutor
from ltrace.remote.handlers.InstanceSegmenterHandler import ThinSectionInstanceSegmenterExecutionHandler, ResultHandler


def instseg_loader(job: JobExecutor):

    details = job.details
    output_name = details.get("output_name", "output")
    referenceNodeID = details.get("input_volume_node_id", None)
    tmpReferenceNodeID = details.get("tmp_reference_node_id", None)
    soiNodeID = details.get("soi_node_id", None)
    params = (details.get("params", []),)
    classes = details.get("classes", [])
    segmentation = details.get("segmentation", False)
    script_path = details.get("script_path", "")
    bin_path = details.get("bin_path", "")

    handler = ResultHandler()

    task_handler = ThinSectionInstanceSegmenterExecutionHandler(
        handler,
        output_name,
        bin_path=bin_path,
        script_path=script_path,
        model_path=model,
        reference_node_id=referenceNodeID,
        tmp_reference_node_id=tmpReferenceNodeID,
        soi_node_id=soiNodeID,
        params=params,
        classes=classes,
        opening_cmd='bash -c "source /etc/bashrc" && source /nethome/drp/microtom/init.sh',
        segmentation=segmentation,
    )

    task_handler.jobid = str(job.details["job_id"][0])
    job.task_handler = task_handler
    print("JOB ok:", job)
    return job


