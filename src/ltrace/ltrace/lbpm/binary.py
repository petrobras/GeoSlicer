"""Finding an LBPM executable.

LBPM is deployed in very different shapes: a binary on ``PATH``, a module-loaded build on a cluster, or an
Apptainer/Singularity image (which is how the reference cluster runs it — see ``run_atena.sh`` in the
sample data). Discovery therefore returns *how* to invoke the simulator, not just a path, and says why it
failed so the UI can ask the user for the missing piece instead of guessing.
"""

import os
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

DEFAULT_SIMULATOR = "lbpm_color_simulator"

CONTAINER_SUFFIXES = (".sif", ".simg")

COMMON_DIRECTORIES = (
    "/opt/lbpm/bin",
    "/usr/local/lbpm/bin",
    "/usr/local/bin",
    "/opt/apps/lbpm/bin",
)
"""Places worth a look before giving up. Deliberately short: guessing wrong is worse than asking."""


@dataclass
class LBPMBinary:
    """How to run the simulator: either a plain executable or a container image."""

    simulator: str = DEFAULT_SIMULATOR
    executable: Optional[Path] = None
    container: Optional[Path] = None
    launcher: str = "mpirun"
    modules: Sequence[str] = field(default_factory=tuple)
    origin: str = ""
    binds: Sequence[str] = field(default_factory=tuple)
    """Host folders the container needs besides the case, as ``singularity -B`` takes them."""

    @property
    def available(self) -> bool:
        return self.executable is not None or self.container is not None

    def command(
        self, ranks: int, config_file: str, gpu: bool = False, bind: str = ".", launcher_options: Sequence[str] = ()
    ) -> str:
        """Shell command running the simulator on ``config_file`` with ``ranks`` processes.

        ``launcher_options`` go to ``mpirun`` after the process count — placement, binding — and are dropped
        with it when a single process needs no launcher.
        """
        launcher = ""
        if self.launcher and ranks and ranks > 1:
            launcher = " ".join([self.launcher, "-n", str(max(1, int(ranks))), *launcher_options])

        if self.container is not None:
            flags = ["--nv"] if gpu else []
            flags += [f"-B {shlex.quote(str(item))}" for item in self.binds]
            flags += [f"-B {bind}:/sim", "-W /sim"]
            inner = " ".join(["singularity exec", *flags, shlex.quote(self.container.as_posix()), self.simulator])
        else:
            inner = self.executable.as_posix() if self.executable else self.simulator

        return " ".join(part for part in (launcher, inner, config_file) if part)

    def describe(self) -> str:
        if self.container is not None:
            return f"container image {self.container.name}"
        if self.executable is not None:
            return f"executable {self.executable.as_posix()}"
        return "not found"


def find_local(simulator: str = DEFAULT_SIMULATOR, hint: str = None, launcher: str = None) -> LBPMBinary:
    """Look for a local LBPM installation.

    ``hint`` is whatever the user configured (an executable, a container image, or a directory holding
    either); it always wins, so a configured path is never second-guessed. The MPI launcher is only used if
    one is actually installed — a single-rank run does not need it, and inventing a command that does not
    exist turns a working setup into a failure.
    """
    if launcher is None:
        launcher = "mpirun" if shutil.which("mpirun") else ""
    if hint:
        candidate = Path(hint).expanduser()
        resolved = _from_hint(candidate, simulator)
        if resolved is not None:
            return LBPMBinary(simulator=simulator, launcher=launcher, origin="configured path", **resolved)

    on_path = shutil.which(simulator)
    if on_path:
        return LBPMBinary(simulator=simulator, executable=Path(on_path), launcher=launcher, origin="PATH")

    for directory in COMMON_DIRECTORIES:
        candidate = Path(directory) / simulator
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return LBPMBinary(
                simulator=simulator, executable=candidate, launcher=launcher, origin=f"found in {directory}"
            )

    return LBPMBinary(simulator=simulator, launcher=launcher, origin="")


def _from_hint(candidate: Path, simulator: str) -> Optional[dict]:
    if candidate.is_dir():
        for name in (simulator, f"bin/{simulator}"):
            executable = candidate / name
            if executable.is_file():
                return {"executable": executable}
        for suffix in CONTAINER_SUFFIXES:
            images = sorted(candidate.glob(f"*{suffix}"))
            if images:
                return {"container": images[0]}
        return None

    if candidate.suffix.lower() in CONTAINER_SUFFIXES and candidate.is_file():
        return {"container": candidate}

    if candidate.is_file():
        return {"executable": candidate}

    return None


def missing_reason(binary: LBPMBinary) -> str:
    """One sentence a UI can show when nothing was found."""
    return (
        f"'{binary.simulator}' was not found on this machine. Point the module at the LBPM executable or at "
        "its Apptainer/Singularity image (*.sif) to run simulations locally, or connect to a cluster that "
        "provides it."
    )


def remote_probe_command(simulator: str = DEFAULT_SIMULATOR, modules: Sequence[str] = ()) -> str:
    """Command that prints where a remote host has the simulator, if anywhere.

    Kept as a plain command string so it can be sent through the same client abstraction used for
    submitting and polling jobs — no separate remote-inspection channel.
    """
    prelude = " && ".join(f"module load {name}" for name in modules)
    lookup = f"command -v {simulator} || ls -1 /opt/**/{simulator} 2>/dev/null | head -1"
    return f"bash -lc '{prelude + ' && ' if prelude else ''}{lookup}'"
