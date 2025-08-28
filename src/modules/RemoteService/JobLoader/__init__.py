from ltrace.remote.jobs import JobManager

from .instseg import instseg_loader
from .microtom import microtom_job_loader
from .monai import monai_job_loader
from .pnmextractor import pnmextractor_loader
from .pnmsimulation import pnmsimulation_loader


def register_job_loaders():
    JobManager.register("microtom", microtom_job_loader)
    JobManager.register("monai", monai_job_loader)
    JobManager.register("instseg", instseg_loader)
    JobManager.register("pnmsimulation", pnmsimulation_loader)
    JobManager.register("pnmextractor", pnmextractor_loader)
