from ltrace.remote.jobs import JobManager

from .microtom import microtom_job_loader
from .monai import monai_job_loader
from .instseg import instseg_loader
from .pnmsimulation import pnmsimulation_loader


def register_job_loaders():
    JobManager.register("microtom", microtom_job_loader)
    JobManager.register("monai", monai_job_loader)
    JobManager.register("instseg", instseg_loader)
    JobManager.register("pnmsimulation", pnmsimulation_loader)
