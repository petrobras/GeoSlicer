"""Submitting, polling and cancelling an LBPM run — the same way locally and on a cluster.

Everything a backend needs is expressed as *shell command strings* plus small parsers. Both backends then
run through one client abstraction (SSH for a cluster, subprocess for this machine) and one job handler, so
local runs inherit the whole remote-job machinery: persistence, resume after a restart, cancellation and the
Job Monitor UI.

The SLURM script is the one the reference cluster (Atena) is run with by hand, in its CPU and its GPU
shape: an ``sbatch`` header, environment modules, then ``mpirun`` over an Apptainer/Singularity image.
"""

import math
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, Optional, Sequence

from .binary import DEFAULT_SIMULATOR, LBPMBinary

STATE_PENDING = "PENDING"
STATE_RUNNING = "RUNNING"
STATE_COMPLETED = "COMPLETED"
STATE_FAILED = "FAILED"
STATE_CANCELLED = "CANCELLED"
STATE_UNKNOWN = "UNKNOWN"

SLURM_SUBMIT_PATTERN = re.compile(r"Submitted batch job (\d+)")
LOG_NAME = "lbpm.out"
PID_NAME = "lbpm.pid"
SCRIPT_NAME = "run_lbpm.sh"
STAGING_SUBFOLDER = "lbpm"
"""Where a cluster run's copy of its case is staged, under the staging root: ``<root>/lbpm/<job uid>``."""

MODULES_INIT = "/usr/share/Modules/init/bash"
"""Where Environment Modules defines ``module``. A batch job's shell is not a login shell, so it may not have it."""

CPU_CPUS_PER_TASK = 1
GPU_CPUS_PER_TASK = 2
"""A GPU rank drives its device from the host: it gets a second core, as on the reference cluster."""

GPU_CONTAINER_LIBRARY_PATH = "/usr/local/cuda/lib64"
"""Where the image keeps the CUDA libraries a GPU run loads."""


@dataclass
class LBPMJobSpec:
    """What to run. Paths are as seen by the machine that will run it."""

    case_dir: str
    config_file: str = "waterflow.db"
    simulator: str = DEFAULT_SIMULATOR
    ranks: int = 8
    gpu: bool = False
    walltime: Optional[str] = None
    partition: Optional[str] = None
    account: Optional[str] = None
    job_name: str = "lbpm"
    nodes: int = 1
    modules: Sequence[str] = field(default_factory=tuple)
    env: Dict[str, str] = field(default_factory=dict)
    opening_command: str = ""

    @property
    def directory(self) -> str:
        return PurePosixPath(str(self.case_dir)).as_posix()

    def to_dict(self) -> Dict:
        data = dict(self.__dict__)
        data["case_dir"] = str(self.case_dir)
        data["modules"] = list(self.modules)
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "LBPMJobSpec":
        known = {key: value for key, value in (data or {}).items() if key in cls.__dataclass_fields__}
        return cls(**known)


class Scheduler:
    """Command builder + output parser for one execution backend."""

    name = "abstract"

    def __init__(self, binary: LBPMBinary):
        self.binary = binary

    # -- submission -----------------------------------------------------------------------------------
    def script(self, spec: LBPMJobSpec) -> Optional[str]:
        """Content of the script to write next to the case, or ``None`` when the backend needs none."""
        return None

    def submit_command(self, spec: LBPMJobSpec) -> str:
        raise NotImplementedError

    def parse_submit(self, stdout: str) -> Optional[str]:
        raise NotImplementedError

    # -- monitoring -----------------------------------------------------------------------------------
    def status_command(self, job_id: str, spec: LBPMJobSpec = None) -> str:
        raise NotImplementedError

    def parse_status(self, stdout: str, stderr: str = "") -> str:
        raise NotImplementedError

    def cancel_command(self, job_id: str, spec: LBPMJobSpec = None) -> str:
        raise NotImplementedError

    # -- helpers --------------------------------------------------------------------------------------
    def _environment(self, spec: LBPMJobSpec) -> str:
        parts = [f"module load {name}" for name in spec.modules]
        parts += [f"export {key}={shlex.quote(str(value))}" for key, value in (spec.env or {}).items()]
        if spec.opening_command:
            parts.insert(0, spec.opening_command)
        return "\n".join(parts)

    def run_line(self, spec: LBPMJobSpec) -> str:
        return self.binary.command(spec.ranks, spec.config_file, gpu=spec.gpu)


class SlurmScheduler(Scheduler):
    """Submits through ``sbatch`` the script the reference cluster is run with by hand.

    A CPU job is one task per core. A GPU job is one task per GPU, on nodes of its own, with two cores per
    task and every rank pinned to its node by ``mpirun``.
    """

    name = "slurm"

    def script(self, spec: LBPMJobSpec) -> str:
        header = ["#!/bin/bash"]
        if spec.partition:
            header.append(f"#SBATCH --partition {spec.partition}")
        if spec.account:
            header.append(f"#SBATCH -A {spec.account}")
        header += [
            f"#SBATCH -J {spec.job_name}",
            f"#SBATCH --ntasks={_ranks(spec)}",
            f"#SBATCH --nodes={_nodes(spec)}",
            f"#SBATCH --cpus-per-task={GPU_CPUS_PER_TASK if spec.gpu else CPU_CPUS_PER_TASK}",
        ]
        if spec.gpu:
            header += [f"#SBATCH --gres=gpu:{_ranks_per_node(spec)}", "#SBATCH --exclusive"]
        if spec.walltime:
            header.append(f"#SBATCH --time={spec.walltime}")
        header.append(f"#SBATCH --output={LOG_NAME}")

        body = [self._environment(spec), f"cd {spec.directory}", self.run_line(spec)]
        return "\n".join(header + [""] + [line for line in body if line]) + "\n"

    def _environment(self, spec: LBPMJobSpec) -> str:
        parts = [spec.opening_command] if spec.opening_command else []
        if spec.modules:
            parts.append(f"source {MODULES_INIT}")
        parts += [f"module load {name}" for name in spec.modules]
        if spec.gpu and self.binary.container is not None:
            # Before the user's own variables, so one of theirs with the same name still wins.
            parts.append(f"export APPTAINERENV_LD_LIBRARY_PATH={GPU_CONTAINER_LIBRARY_PATH}")
        parts += [f"export {key}={shlex.quote(str(value))}" for key, value in (spec.env or {}).items()]
        return "\n".join(parts)

    def run_line(self, spec: LBPMJobSpec) -> str:
        options = ("--map-by", f"ppr:{_ranks_per_node(spec)}:node", "--bind-to", "core") if spec.gpu else ()
        command = self.binary.command(spec.ranks, spec.config_file, gpu=spec.gpu, launcher_options=options)
        # The job's log then ends with how long the simulation took.
        return f"time {command}"

    def submit_command(self, spec: LBPMJobSpec) -> str:
        return f"cd {spec.directory} && sbatch {SCRIPT_NAME}"

    def parse_submit(self, stdout: str) -> Optional[str]:
        match = SLURM_SUBMIT_PATTERN.search(stdout or "")
        return match.group(1) if match else None

    def status_command(self, job_id: str, spec: LBPMJobSpec = None) -> str:
        return f"sacct -P -n -ojobid,state -j {job_id}"

    def parse_status(self, stdout: str, stderr: str = "") -> str:
        """First line of ``sacct`` output decides: it is the job itself, later lines are its steps."""
        for line in (stdout or "").strip().splitlines():
            fields = line.split("|")
            if len(fields) < 2:
                continue
            state = fields[1].strip().upper()
            if state.startswith("CANCELLED"):
                return STATE_CANCELLED
            if state in (STATE_COMPLETED, STATE_RUNNING, STATE_FAILED, STATE_PENDING):
                return state
            if state in ("TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY", "BOOT_FAIL", "DEADLINE"):
                return STATE_FAILED
            if state in ("REQUEUED", "RESIZING", "SUSPENDED", "CONFIGURING"):
                return STATE_PENDING
        return STATE_UNKNOWN

    def cancel_command(self, job_id: str, spec: LBPMJobSpec = None) -> str:
        return f"scancel {job_id}"


class LocalScheduler(Scheduler):
    """Runs the simulator on this machine, detached, and polls it by pid.

    Detaching (rather than waiting) is what lets a local run behave like a cluster job: the application can
    be closed and reopened, the job resumed, its progress polled and its output collected the same way.
    """

    name = "local"

    def script(self, spec: LBPMJobSpec) -> str:
        body = [
            "#!/bin/bash",
            self._environment(spec),
            f"cd {spec.directory}",
            f"exec {self.run_line(spec)}",
        ]
        return "\n".join(line for line in body if line) + "\n"

    def submit_command(self, spec: LBPMJobSpec) -> str:
        return (
            f"cd {spec.directory} && chmod +x {SCRIPT_NAME} && "
            f"(setsid nohup ./{SCRIPT_NAME} > {LOG_NAME} 2>&1 < /dev/null & echo $! > {PID_NAME}) && "
            f"cat {PID_NAME}"
        )

    def parse_submit(self, stdout: str) -> Optional[str]:
        for token in reversed((stdout or "").split()):
            if token.isdigit():
                return token
        return None

    def status_command(self, job_id: str, spec: LBPMJobSpec = None) -> str:
        directory = spec.directory if spec else "."
        # "alive" while the pid is still there; otherwise the exit status is recovered from the log's tail.
        return (
            f"if kill -0 {job_id} 2>/dev/null; then echo RUNNING; "
            f"elif grep -qiE 'error|traceback|aborted' {directory}/{LOG_NAME} 2>/dev/null; then echo FAILED; "
            f"else echo COMPLETED; fi"
        )

    def parse_status(self, stdout: str, stderr: str = "") -> str:
        text = (stdout or "").strip().upper()
        if STATE_RUNNING in text:
            return STATE_RUNNING
        if STATE_FAILED in text:
            return STATE_FAILED
        if STATE_COMPLETED in text:
            return STATE_COMPLETED
        return STATE_UNKNOWN

    def cancel_command(self, job_id: str, spec: LBPMJobSpec = None) -> str:
        # The run is its own session leader (setsid), so the whole MPI process group goes down with it.
        return f"kill -TERM -{job_id} 2>/dev/null || kill -TERM {job_id}"


def _ranks(spec: LBPMJobSpec) -> int:
    return max(1, int(spec.ranks or 1))


def _nodes(spec: LBPMJobSpec) -> int:
    return max(1, int(spec.nodes or 1))


def _ranks_per_node(spec: LBPMJobSpec) -> int:
    return math.ceil(_ranks(spec) / _nodes(spec))


def progress_command(spec: LBPMJobSpec, pattern: str = "vis*") -> str:
    """Command reporting how far a run has got: frames written and analysis rows logged."""
    directory = spec.directory
    return (
        f"echo frames=$(ls -d {directory}/{pattern} 2>/dev/null | wc -l); "
        f"echo timelog=$(wc -l < {directory}/timelog.csv 2>/dev/null || echo 0); "
        f"echo subphase=$(wc -l < {directory}/subphase.csv 2>/dev/null || echo 0)"
    )


def parse_progress(stdout: str) -> Dict[str, int]:
    values = {}
    for line in (stdout or "").splitlines():
        key, _, value = line.partition("=")
        try:
            values[key.strip()] = int(value.strip())
        except ValueError:
            continue
    return values


def expected_frames(config) -> Optional[int]:
    """How many visualization frames a finished run should produce, from its configuration."""
    interval = config.get_int("Analysis", "visualization_interval")
    total = config.get_int("Color", "timestepMax")
    if not interval or not total:
        return None
    return max(1, total // interval)
