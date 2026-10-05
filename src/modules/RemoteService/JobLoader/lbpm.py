"""Rehydrate an LBPM job after the application restarts.

A job persisted by :class:`~ltrace.remote.jobs.JobManager` keeps only its details dictionary, so the handler
— scheduler, spec, expected frame count, the folders it is opened from — is rebuilt from it here.
"""

from ltrace.lbpm.binary import LBPMBinary
from ltrace.lbpm.scheduler import LBPMJobSpec, LocalScheduler, SlurmScheduler
from ltrace.remote.connections import JobExecutor
from ltrace.remote.handlers.LBPMSimulationHandler import LBPMSimulationHandler
from ltrace.slicer.lbpm import open_run


def lbpm_job_loader(job: JobExecutor) -> JobExecutor:
    details = job.details or {}
    spec = LBPMJobSpec.from_dict(details.get("spec", {"case_dir": details.get("case_dir", ".")}))

    scheduler_name = details.get("scheduler", "local")
    binary = LBPMBinary(simulator=spec.simulator, origin="restored")
    scheduler = LocalScheduler(binary) if scheduler_name == "local" else SlurmScheduler(binary)

    handler = LBPMSimulationHandler(
        spec=spec,
        scheduler=scheduler,
        # A collector is not persisted, so a restored job gets the one any LBPM job opens with.
        collector=open_run,
        expected_frames=details.get("expected_frames"),
        source_dir=details.get("source_dir"),
        output_dir=details.get("output_dir"),
    )
    handler.job_id = str(details.get("job_id")) if details.get("job_id") else None
    handler.slurm_job_ids = [handler.job_id] if handler.job_id else []

    job.task_handler = handler
    return job
