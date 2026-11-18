"""An LBPM job restored after GeoSlicer restarts opens like one that was just submitted."""

from types import SimpleNamespace

from commons.lbpm.scheduler import LBPMJobSpec, SlurmScheduler
from commons.slicer.lbpm import open_run
from modules.RemoteService.JobLoader import lbpm as loader


def test_a_restored_job_is_opened_like_a_new_one():
    job = SimpleNamespace(
        details={
            "spec": LBPMJobSpec(case_dir="/nethome/drp/servicos/LTRACE/GEOSLICER/jobs/lbpm/uid-1").to_dict(),
            "scheduler": "slurm",
            "job_id": "6854163",
            "expected_frames": 5,
            "source_dir": "/cases/rock/sim001",
            "output_dir": "/share/drp/servicos/LTRACE/GEOSLICER/jobs/lbpm/uid-1",
        },
        task_handler=None,
    )

    handler = loader.lbpm_job_loader(job).task_handler

    assert handler.collector is open_run, "the Job Monitor's Open would do nothing for it"
    assert handler.source_dir == "/cases/rock/sim001"
    assert handler.output_dir == "/share/drp/servicos/LTRACE/GEOSLICER/jobs/lbpm/uid-1"
    assert isinstance(handler.scheduler, SlurmScheduler) and handler.job_id == "6854163"


def test_a_job_restored_from_before_its_folders_were_kept_still_gets_opened():
    job = SimpleNamespace(details={"spec": {"case_dir": "/cases/rock/sim001"}, "scheduler": "local"}, task_handler=None)

    handler = loader.lbpm_job_loader(job).task_handler

    assert handler.collector is open_run
    assert handler.source_dir is None and handler.output_dir is None
