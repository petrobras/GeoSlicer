from pathlib import Path

import slicer

from ltrace.remote.connections import JobExecutor
from ltrace.remote.jobs import JobManager
from ltrace.remote.handlers import OneResultSlurmHandler
from ltrace.readers.microtom import KrelCompiler, PorosimetryCompiler, StokesKabsCompiler


def microtom_job_loader(job: JobExecutor):
    print("Job received", job)
    details = job.details
    simulator = details.get("simulator", "psd")
    outputPrefix = details.get("output_prefix", "output")
    direction = details.get("direction", "z")
    tag = details.get("geoslicer_tag", "")
    referenceNodeId = details.get("reference_volume_node_id", None)

    try:
        if referenceNodeId:
            node = slicer.util.getNode(referenceNodeId)
            if node is None:
                raise ValueError("Reference node not found")
    except Exception:
        referenceNodeId = None

    shared_path = Path(r"geoslicer/remote/jobs")

    # TODO make this conditions shared with dispatch code
    if simulator == "krel":
        collector = KrelCompiler()
        task_handler = OneResultSlurmHandler(
            simulator,
            collector,
            None,
            shared_path,
            "",
            "cpu",
            {"direction": direction},
            outputPrefix,
            referenceNodeId,
            tag,
            post_args=dict(diameters=details.get("diameters", None), direction=direction),
        )

    elif "kabs" in simulator:
        collector = StokesKabsCompiler()
        task_handler = OneResultSlurmHandler(
            simulator,
            collector,
            None,
            shared_path,
            "",
            "cpu",
            {"direction": direction},
            outputPrefix,
            referenceNodeId,
            tag,
            post_args=dict(load_volumes=details.get("load_volumes", None), direction=direction),
        )

    else:
        collector = PorosimetryCompiler()

        task_handler = OneResultSlurmHandler(
            simulator,
            collector,
            None,
            shared_path,
            "",
            "cpu",
            {"direction": direction},
            outputPrefix,
            referenceNodeId,
            tag,
            post_args=dict(vfrac=details.get("vfrac", None), direction=direction),
        )
    task_handler.jobid = str(job.details["job_id"][0])
    task_handler.jobs = [str(j) for j in job.details["job_id"]]
    job.task_handler = task_handler
    print(job, task_handler)
    return job
