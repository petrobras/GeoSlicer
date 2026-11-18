"""Both execution backends are only command strings and parsers; they are unit-testable as such."""

from pathlib import Path, PurePosixPath

from commons.lbpm.binary import LBPMBinary
from commons.lbpm.config import WaterflowConfig
from commons.lbpm.scheduler import (
    STATE_CANCELLED,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_PENDING,
    STATE_RUNNING,
    STATE_UNKNOWN,
    LBPMJobSpec,
    LocalScheduler,
    SlurmScheduler,
    expected_frames,
    parse_progress,
    progress_command,
)


def make_spec(**kwargs) -> LBPMJobSpec:
    return LBPMJobSpec(**{"case_dir": "/data/case/sim001", "ranks": 8, **kwargs})


# How LBPM is run by hand on the reference cluster: atena_lbpm_cpu.sh and atena_lbpm_gpu.sh.
ATENA_IMAGE = "/nethome/drp2/servicos/Luciano/lbpm/lbpm-ufsc/lbpm-ufsc.sif"
ATENA_LIBS = "/usr/lib/gcc/x86_64-redhat-linux/8/:/usr/lib/gcc/"
ATENA_OPENMPI = "openmpi/4.1.4_ucx1.13.1_cuda_11.3_gcc"


def atena(**kwargs):
    scheduler = SlurmScheduler(LBPMBinary(container=PurePosixPath(ATENA_IMAGE), binds=(ATENA_LIBS,)))
    spec = make_spec(
        **{
            "case_dir": "/nethome/drp/lbpm/case",
            "partition": "gpu",
            "account": "tcr_ext",
            "walltime": "5-00:00:00",
            "modules": [ATENA_OPENMPI],
            **kwargs,
        }
    )
    return scheduler, spec


def test_a_cpu_job_is_the_script_run_by_hand_on_the_cluster():
    scheduler, spec = atena(job_name="lbpm_bentheimer_cpu_ltrace", ranks=40)

    assert scheduler.script(spec) == (
        "#!/bin/bash\n"
        "#SBATCH --partition gpu\n"
        "#SBATCH -A tcr_ext\n"
        "#SBATCH -J lbpm_bentheimer_cpu_ltrace\n"
        "#SBATCH --ntasks=40\n"
        "#SBATCH --nodes=1\n"
        "#SBATCH --cpus-per-task=1\n"
        "#SBATCH --time=5-00:00:00\n"
        "#SBATCH --output=lbpm.out\n"
        "\n"
        "source /usr/share/Modules/init/bash\n"
        f"module load {ATENA_OPENMPI}\n"
        "cd /nethome/drp/lbpm/case\n"
        f"time mpirun -n 40 singularity exec -B {ATENA_LIBS} -B .:/sim -W /sim {ATENA_IMAGE} "
        "lbpm_color_simulator waterflow.db\n"
    )


def test_a_gpu_job_is_the_script_run_by_hand_on_the_cluster():
    scheduler, spec = atena(job_name="lbpm_bentheimer", ranks=8, gpu=True)

    assert scheduler.script(spec) == (
        "#!/bin/bash\n"
        "#SBATCH --partition gpu\n"
        "#SBATCH -A tcr_ext\n"
        "#SBATCH -J lbpm_bentheimer\n"
        "#SBATCH --ntasks=8\n"
        "#SBATCH --nodes=1\n"
        "#SBATCH --cpus-per-task=2\n"
        "#SBATCH --gres=gpu:8\n"
        "#SBATCH --exclusive\n"
        "#SBATCH --time=5-00:00:00\n"
        "#SBATCH --output=lbpm.out\n"
        "\n"
        "source /usr/share/Modules/init/bash\n"
        f"module load {ATENA_OPENMPI}\n"
        "export APPTAINERENV_LD_LIBRARY_PATH=/usr/local/cuda/lib64\n"
        "cd /nethome/drp/lbpm/case\n"
        "time mpirun -n 8 --map-by ppr:8:node --bind-to core "
        f"singularity exec --nv -B {ATENA_LIBS} -B .:/sim -W /sim {ATENA_IMAGE} lbpm_color_simulator waterflow.db\n"
    )


def test_a_gpu_job_asks_each_node_for_one_gpu_per_rank():
    scheduler, spec = atena(ranks=16, nodes=2, gpu=True)
    script = scheduler.script(spec)

    assert "#SBATCH --ntasks=16" in script and "#SBATCH --nodes=2" in script
    assert "#SBATCH --gres=gpu:8" in script
    assert "mpirun -n 16 --map-by ppr:8:node --bind-to core" in script


def test_a_cpu_job_shares_its_nodes():
    """Only a GPU job takes whole nodes, as on the cluster; a CPU job asks for cores, not devices."""
    scheduler, spec = atena(ranks=40)
    script = scheduler.script(spec)

    assert "--exclusive" not in script
    assert "--gres" not in script
    assert "--nv" not in script and "APPTAINERENV_LD_LIBRARY_PATH" not in script


def test_the_environment_comes_before_the_run_in_the_order_it_is_needed():
    scheduler, spec = atena(
        gpu=True,
        opening_command="echo ready",
        env={"APPTAINERENV_LD_LIBRARY_PATH": "/opt/cuda/lib64", "OMP_NUM_THREADS": "2"},
    )
    lines = scheduler.script(spec).splitlines()
    body = lines[lines.index("") + 1 :]

    assert body[:3] == ["echo ready", "source /usr/share/Modules/init/bash", f"module load {ATENA_OPENMPI}"]
    # A variable the user set for the image wins over the one the GPU run sets by default.
    assert body.index("export APPTAINERENV_LD_LIBRARY_PATH=/usr/local/cuda/lib64") < body.index(
        "export APPTAINERENV_LD_LIBRARY_PATH=/opt/cuda/lib64"
    )
    assert body[-2] == "cd /nethome/drp/lbpm/case"
    assert body[-1].startswith("time mpirun")


def test_a_job_without_modules_does_not_initialise_them():
    scheduler, spec = atena(modules=[])
    assert "Modules/init" not in scheduler.script(spec)


def test_a_cluster_without_an_image_runs_the_module_build():
    scheduler = SlurmScheduler(LBPMBinary())
    script = scheduler.script(make_spec(gpu=True, modules=["lbpm/gpu"]))

    assert "time mpirun -n 8 --map-by ppr:8:node --bind-to core lbpm_color_simulator waterflow.db" in script
    assert "singularity" not in script and "APPTAINERENV" not in script


def test_the_container_command_quotes_what_the_shell_would_split():
    binary = LBPMBinary(container=PurePosixPath("/images/my lbpm.sif"), binds=("/data/with space:/data",))
    command = binary.command(4, "waterflow.db")

    assert "-B '/data/with space:/data' -B .:/sim -W /sim '/images/my lbpm.sif' lbpm_color_simulator" in command


def test_launcher_options_go_away_with_the_launcher():
    binary = LBPMBinary(executable=Path("/opt/lbpm/bin/lbpm_color_simulator"))
    options = ("--bind-to", "core")

    assert binary.command(4, "waterflow.db", launcher_options=options).startswith("mpirun -n 4 --bind-to core ")
    assert binary.command(1, "waterflow.db", launcher_options=options) == (
        "/opt/lbpm/bin/lbpm_color_simulator waterflow.db"
    )


def test_slurm_submission_and_states():
    scheduler = SlurmScheduler(LBPMBinary(executable=Path("/usr/bin/lbpm_color_simulator")))

    assert scheduler.submit_command(make_spec()).endswith("sbatch run_lbpm.sh")
    assert scheduler.parse_submit("Submitted batch job 6854163") == "6854163"
    assert scheduler.parse_submit("something went wrong") is None

    assert scheduler.parse_status("6854163|RUNNING\n6854163.0|RUNNING") == STATE_RUNNING
    assert scheduler.parse_status("6854163|COMPLETED") == STATE_COMPLETED
    assert scheduler.parse_status("6854163|CANCELLED by 1000") == STATE_CANCELLED
    assert scheduler.parse_status("6854163|TIMEOUT") == STATE_FAILED
    assert scheduler.parse_status("6854163|CONFIGURING") == STATE_PENDING
    assert scheduler.parse_status("") == STATE_UNKNOWN
    assert scheduler.cancel_command("6854163") == "scancel 6854163"


def test_local_run_is_detached_and_polled_by_pid():
    scheduler = LocalScheduler(LBPMBinary(executable=Path("/opt/lbpm/bin/lbpm_color_simulator"), launcher="mpirun"))
    spec = make_spec()

    script = scheduler.script(spec)
    assert "mpirun -n 8 /opt/lbpm/bin/lbpm_color_simulator waterflow.db" in script

    submit = scheduler.submit_command(spec)
    assert "setsid nohup ./run_lbpm.sh" in submit and "lbpm.pid" in submit
    assert scheduler.parse_submit("25104\n") == "25104"

    status = scheduler.status_command("25104", spec)
    assert "kill -0 25104" in status
    assert scheduler.parse_status("RUNNING") == STATE_RUNNING
    assert scheduler.parse_status("COMPLETED") == STATE_COMPLETED
    assert scheduler.parse_status("FAILED") == STATE_FAILED

    # The run is its own session leader, so the whole MPI process group is signalled.
    assert scheduler.cancel_command("25104", spec).startswith("kill -TERM -25104")


def test_single_rank_runs_without_a_launcher():
    scheduler = LocalScheduler(LBPMBinary(executable=Path("/opt/lbpm/bin/lbpm_color_simulator"), launcher="mpirun"))
    assert "mpirun" not in scheduler.run_line(make_spec(ranks=1))


def test_progress_is_read_from_the_case_folder():
    command = progress_command(make_spec())
    assert "vis*" in command and "timelog.csv" in command

    counters = parse_progress("frames=42\ntimelog=43\nsubphase=43\n")
    assert counters == {"frames": 42, "timelog": 43, "subphase": 43}


def test_expected_frame_count_comes_from_the_configuration():
    config = WaterflowConfig.default()
    config.set("Analysis", "visualization_interval", 10000)
    config.set("Color", "timestepMax", 100000)
    assert expected_frames(config) == 10

    config.set("Analysis", "visualization_interval", 0)
    assert expected_frames(config) is None
