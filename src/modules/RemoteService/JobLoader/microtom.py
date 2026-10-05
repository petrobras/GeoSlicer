import logging
from pathlib import Path

import slicer

from ltrace.remote.connections import JobExecutor
from ltrace.remote.jobs import JobManager
from ltrace.remote.handlers import OneResultSlurmHandler
from ltrace.readers.microtom import KrelCompiler, PorosimetryCompiler, StokesKabsCompiler


def microtom_job_loader(job: JobExecutor):
    details = job.details or {}
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

    # TODO make this conditions shared with dispatch code
    if simulator == "krel":
        collector = KrelCompiler()
        task_handler = OneResultSlurmHandler(
            simulator,
            collector,
            None,
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
            "",
            "cpu",
            {"direction": direction},
            outputPrefix,
            referenceNodeId,
            tag,
            post_args=dict(vfrac=details.get("vfrac", None), direction=direction),
        )

    # Persisted as a list, but a job written by an older version may carry a
    # bare scalar. Either way the handler's own defaults (None / []) stand when
    # the key never made it to disk.
    job_ids = details.get("job_id") or []
    if isinstance(job_ids, (str, int)):
        job_ids = [job_ids]

    if job_ids:
        task_handler.jobid = str(job_ids[0])
    task_handler.slurm_job_ids = [str(j) for j in job_ids]

    job.task_handler = task_handler
    logging.debug(f"Mounted microtom job {job.uid} ({simulator}).")
    return job
