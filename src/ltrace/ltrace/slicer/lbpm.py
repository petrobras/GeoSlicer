"""Dispatching an LBPM simulation from GeoSlicer, locally or on a cluster, through one API.

Any module can call :meth:`LBPMDispatcher.submit` with a case folder and get back a managed job id; where
it runs is decided by what is available, and both paths report progress the same way (Job Monitor included).

    uid = LBPMDispatcher.submit(case_dir, backend="auto", ranks=8)

The pure logic — configuration, backends, result parsing — lives in :mod:`ltrace.lbpm`; this module is the
part that needs the application: hosts, credentials, the job manager and MRML nodes.
"""

import logging
import shutil
import uuid
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import slicer

from ltrace.lbpm import binary as lbpm_binary
from ltrace.lbpm.config import WaterflowConfig
from ltrace.lbpm.results import LBPMResults
from ltrace.lbpm.scheduler import STAGING_SUBFOLDER, LBPMJobSpec, LocalScheduler, SlurmScheduler, expected_frames
from ltrace.remote.backends import BACKEND_AUTO, BACKEND_LOCAL, BACKEND_REMOTE
from ltrace.remote.connections import JobExecutor
from ltrace.remote.handlers.LBPMSimulationHandler import JOB_TYPE, LBPMSimulationHandler
from ltrace.remote.hosts.local.local import LocalHost
from ltrace.remote.jobs import JobManager
from ltrace.remote.paths import ClusterStorage, storage_for
from ltrace.remote.targets import TargetManager
from ltrace.slicer.widget.execution.options import LIST, REMOTE_FIELDS, TEXT, Field, with_defaults

SETTING_BINARY = "LBPM/BinaryPath"
SETTING_MODULES = "LBPM/EnvironmentModules"
SETTING_REMOTE_ROOT = "LBPM/RemoteRoot"

STAGING_DIR = "geoslicer_jobs"
"""The cluster storage directory cases are staged under, unless the staging folder setting names another."""
RESULTS_FOLDER_NAME = "LBPM Results"
RESULTS_SOURCE_ATTRIBUTE = "LBPM.ResultsSource"
"""On a results table: the folder whose logs it was made from, so making it again updates it."""
RESULTS_TABLE_ATTRIBUTE = "LBPM.ResultsTable"
"""On a results table: which log it holds, ``timelog`` or ``subphase``."""
LBPM_MODULE = "PoreScaleModelling"
"""The module that shows LBPM runs, which the Job Monitor's *Open* goes to."""

CLUSTER_DEFAULTS = {
    "partition": "gpu",
    "account": "tcr_ext",
    "walltime": "5-00:00:00",
    "modules": ["openmpi/4.1.4_ucx1.13.1_cuda_11.3_gcc"],
    "container": "/nethome/drp2/servicos/Luciano/lbpm/lbpm-ufsc/lbpm-ufsc.sif",
    "binds": ["/usr/lib/gcc/x86_64-redhat-linux/8/:/usr/lib/gcc/"],
}
"""What LBPM is run with by hand on the reference cluster (Atena), CPU and GPU alike. These are defaults of the
per-cluster settings, so another cluster only needs its own answers there."""

REMOTE_FIELDS_LBPM = with_defaults(
    REMOTE_FIELDS
    + (
        Field(
            key="container",
            label="Container image",
            kind=TEXT,
            tooltip=(
                "Apptainer/Singularity image LBPM runs from, as the cluster sees it. Empty runs "
                "lbpm_color_simulator from the environment modules instead."
            ),
            placeholder="/path/on/the/cluster/lbpm.sif",
        ),
        Field(
            key="binds",
            label="Container binds",
            kind=LIST,
            tooltip=(
                "Host folders the image needs, each as 'singularity -B' takes it: source[:destination]. "
                "The simulation folder is always bound."
            ),
            placeholder="comma separated",
        ),
    ),
    CLUSTER_DEFAULTS,
)
"""The cluster settings of an LBPM run: the common ones, plus the image it runs from. Applied to clusters only —
a module to load or an image path on the cluster means nothing on this computer."""


class NoBackendAvailable(RuntimeError):
    """Neither a local installation nor a configured cluster can run the simulator."""


class StagingUnavailable(RuntimeError):
    """A cluster is configured but there is no shared folder to place the case in."""


@dataclass
class Backend:
    kind: str
    name: str
    available: bool
    reason: str = ""
    host: object = None
    binary: Optional[lbpm_binary.LBPMBinary] = None

    def describe(self) -> str:
        detail = self.binary.describe() if self.binary is not None else self.reason
        return f"{self.name} ({detail})" if detail else self.name


@dataclass
class SubmissionResult:
    uid: str
    backend: Backend
    case_dir: str
    """Folder as the machine running the simulation sees it (a remote path for a cluster run)."""
    spec: LBPMJobSpec
    local_dir: str = ""
    """Where the run writes its frames and logs, as this machine sees it: the case folder for a local run, its
    staged copy on the shared folder for a cluster run."""
    details: Dict = field(default_factory=dict)


class LBPMDispatcher:
    """Entry point for running LBPM. Stateless: all state lives in the job manager."""

    # -- discovery ------------------------------------------------------------------------------------
    @staticmethod
    def binary_hint() -> Optional[str]:
        return slicer.app.userSettings().value(SETTING_BINARY, None)

    @staticmethod
    def set_binary_hint(path) -> None:
        settings = slicer.app.userSettings()
        settings.setValue(SETTING_BINARY, str(path) if path else "")
        settings.sync()

    @staticmethod
    def environment_modules() -> List[str]:
        raw = slicer.app.userSettings().value(SETTING_MODULES, "") or ""
        return [name.strip() for name in raw.split(",") if name.strip()]

    @classmethod
    def local_backend(cls) -> Backend:
        found = lbpm_binary.find_local(hint=cls.binary_hint())
        return Backend(
            kind=BACKEND_LOCAL,
            name=LocalHost().name,
            available=found.available,
            reason="" if found.available else lbpm_binary.missing_reason(found),
            host=LocalHost(),
            binary=found,
        )

    @staticmethod
    def remote_backends() -> List[Backend]:
        """Configured SSH targets. Availability is optimistic: whether the cluster provides LBPM is only
        known once connected, and asking for credentials just to populate a combo box is hostile."""
        backends = []
        for name, host in (TargetManager.targets or {}).items():
            if getattr(host, "protocol", "") != "ssh":
                continue
            backends.append(
                Backend(
                    kind=BACKEND_REMOTE,
                    name=name,
                    available=True,
                    reason="",
                    host=host,
                    binary=lbpm_binary.LBPMBinary(origin="cluster"),
                )
            )
        return backends

    @classmethod
    def available_backends(cls) -> List[Backend]:
        """Remote first: that is the order they should be offered in, and the default that ``auto`` picks."""
        return cls.remote_backends() + [cls.local_backend()]

    @classmethod
    def resolve_backend(cls, backend: str = BACKEND_AUTO, target_name: str = None) -> Backend:
        if backend == BACKEND_LOCAL:
            resolved = cls.local_backend()
            if not resolved.available:
                raise NoBackendAvailable(resolved.reason)
            return resolved

        remotes = cls.remote_backends()

        if backend == BACKEND_REMOTE or target_name:
            for candidate in remotes:
                if target_name is None or candidate.name == target_name:
                    return candidate
            raise NoBackendAvailable(
                "No cluster is configured. Add one in the remote accounts dialog, or run the simulation locally."
            )

        if remotes:
            return remotes[0]

        local = cls.local_backend()
        if local.available:
            return local

        raise NoBackendAvailable(local.reason)

    # -- submission -----------------------------------------------------------------------------------
    @classmethod
    def submit(
        cls,
        case_dir,
        backend: str = BACKEND_AUTO,
        target_name: str = None,
        config_file: str = "waterflow.db",
        ranks: int = None,
        gpu: bool = False,
        walltime: str = None,
        partition: str = None,
        account: str = None,
        nodes: int = 1,
        modules: Sequence[str] = None,
        env: Dict[str, str] = None,
        job_name: str = None,
        collector: Callable[[Dict], None] = None,
        name: str = None,
        container: str = None,
        binds: Sequence[str] = None,
    ) -> SubmissionResult:
        """Run the case in ``case_dir``. Returns the managed job's identity, or raises with a reason.

        ``container`` and ``binds`` say how a cluster runs LBPM — see :data:`REMOTE_FIELDS_LBPM`. A local
        run finds its program itself and ignores them. ``collector`` is what the Job Monitor's *Open* calls
        with the job's details; by default, :func:`open_run`.
        """
        case_dir = Path(case_dir)
        config_path = case_dir / config_file
        if not config_path.is_file():
            raise FileNotFoundError(f"{config_file} not found in {case_dir}")

        config = WaterflowConfig.from_file(config_path)
        problems = config.validate()
        if problems:
            raise ValueError("This configuration cannot run: " + " ".join(problems))

        chosen = cls.resolve_backend(backend, target_name=target_name)
        uid = str(uuid.uuid4())
        job_name = job_name or f"lbpm-{case_dir.name}"
        # Modules are settled per backend by whoever is submitting; the global setting is what is left
        # for a caller that has no such UI.
        modules = list(modules) if modules is not None else cls.environment_modules()
        env = dict(env or {})

        # Where the run writes its frames and logs, as this computer reads them.
        output_dir = case_dir

        if chosen.kind == BACKEND_LOCAL:
            spec = LBPMJobSpec(
                case_dir=case_dir.as_posix(),
                config_file=config_file,
                ranks=ranks or config.rank_count(),
                gpu=gpu,
                job_name=job_name,
                modules=modules,
                env=env,
            )
            scheduler = LocalScheduler(chosen.binary)
        else:
            remote_dir, output_dir = cls._stage_remote_case(case_dir, chosen.host, uid)
            spec = LBPMJobSpec(
                case_dir=remote_dir,
                config_file=config_file,
                ranks=ranks or config.rank_count(),
                gpu=gpu,
                walltime=walltime,
                partition=partition or getattr(chosen.host, "gpu_partition" if gpu else "cpu_partition", None),
                account=account,
                nodes=max(1, int(nodes or 1)),
                job_name=job_name,
                modules=modules,
                env=env,
                opening_command=getattr(chosen.host, "opening_command", "") or "",
            )
            scheduler = SlurmScheduler(cls._remote_binary(container, binds))

        handler = LBPMSimulationHandler(
            spec=spec,
            scheduler=scheduler,
            collector=collector or open_run,
            expected_frames=expected_frames(config),
            source_dir=case_dir.as_posix(),
            output_dir=output_dir.as_posix(),
        )

        if chosen.kind == BACKEND_LOCAL:
            JobManager.manage(
                JobExecutor(uid, handler, chosen.host, name=name or job_name, job_type=JOB_TYPE, polling_enabled=True)
            )
            JobManager.schedule(uid, "DEPLOY")
        else:
            # The job takes the uid its inputs were staged under, so the id Job Monitor shows names the folder.
            started = None
            try:
                started = slicer.modules.RemoteServiceInstance.cli.run(
                    handler, name=name or job_name, job_type=JOB_TYPE, polling_enabled=True, uid=uid
                )
            finally:
                if not started:
                    # No job will ever run from the staged copy, so it does not stay on the share.
                    shutil.rmtree(output_dir, ignore_errors=True)
            if not started:
                raise NoBackendAvailable("The cluster connection was cancelled.")

        return SubmissionResult(
            uid=uid, backend=chosen, case_dir=spec.directory, spec=spec, local_dir=output_dir.as_posix()
        )

    @staticmethod
    def cancel(uid: str) -> Future:
        """Cancel/Delete the job, as the Job Monitor does: the run stops, the job leaves the list and what it
        wrote on a cluster is deleted. Returns at once; raises when the job monitor is not running.

        Through the request queue: a scheduled CANCEL would be taken for a request id that was never made,
        and dropped.
        """
        return JobManager.request_cancel(uid)

    # -- staging --------------------------------------------------------------------------------------
    @classmethod
    def _stage_remote_case(cls, case_dir: Path, host, uid: str) -> Tuple[str, Path]:
        """Copy the case into the share the cluster reads.

        Returns the copy's path twice: as the cluster sees it, where the run is started, and as this computer
        sees it, where the run's output appears. Same arrangement the other cluster jobs use: a network share
        mounted on both sides, so no file transfer protocol is involved and large images are not pushed
        through the SSH channel. Both come from one cluster path translated by the host's storage layout, so
        they cannot name different folders. The copy is named ``uid``, the uid the job is then started under.
        """
        storage = storage_for(host)
        root = cls._staging_root(storage)
        local_root = storage.to_local(root)
        if not local_root.is_dir():
            raise StagingUnavailable(
                f"The cluster's shared folder {root.as_posix()} is not reachable from this computer at "
                f"{local_root}, so the simulation case cannot be handed to it. Check the cluster storage in the "
                "account settings, or the staging folder in the LBPM settings."
            )

        remote_dir = root / STAGING_SUBFOLDER / uid
        destination = storage.to_local(remote_dir)
        destination.mkdir(parents=True, exist_ok=True)

        for item in case_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, destination / item.name)

        return remote_dir.as_posix(), destination

    @staticmethod
    def _staging_root(storage: ClusterStorage) -> PurePosixPath:
        """The folder cases are staged under, as the cluster sees it.

        The staging folder setting may be written from either side of the share: a path this computer reaches
        is translated, and a relative one is taken from the cluster's root.
        """
        configured = str(slicer.app.userSettings().value(SETTING_REMOTE_ROOT, None) or "").strip()
        if not configured:
            return storage.remote_dir(STAGING_DIR)

        root = storage.to_remote(configured)
        return root if root.is_absolute() else storage.cluster_root / root

    @staticmethod
    def _remote_binary(container: str = None, binds: Sequence[str] = None) -> lbpm_binary.LBPMBinary:
        """How the cluster invokes LBPM: from a container image when one is named, else the module build."""
        return lbpm_binary.LBPMBinary(
            # A path on the cluster, which is POSIX whatever this computer is.
            container=PurePosixPath(container) if container else None,
            binds=tuple(binds or ()),
            origin="cluster",
        )


# -- results ------------------------------------------------------------------------------------------
def load_results(case_dir) -> LBPMResults:
    return LBPMResults.load(case_dir)


def build_result_nodes(case_dir, prefix: str = None, parent_item: int = None) -> Dict[str, object]:
    """Turn a finished (or running) case's logs into table nodes, grouped in the subject hierarchy."""
    from ltrace.slicer.data_utils import dataFrameToTableNode
    from ltrace.slicer.helpers import autoDetectColumnType

    case_dir = Path(case_dir)
    prefix = prefix or case_dir.name
    results = load_results(case_dir)

    folder_tree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    folder = (
        parent_item
        or folder_tree.GetItemByName(RESULTS_FOLDER_NAME)
        or folder_tree.CreateFolderItem(folder_tree.GetSceneItemID(), RESULTS_FOLDER_NAME)
    )

    nodes = {}
    for key, frame in (("timelog", results.timelog), ("subphase", results.subphase)):
        if frame is None:
            continue

        # A run opened again, or still running, gets its tables brought up to date rather than doubled.
        node = _result_table(case_dir, key)
        if node is None:
            node = dataFrameToTableNode(frame)
            node.SetName(slicer.mrmlScene.GenerateUniqueName(f"{prefix} {key}"))
            node.SetAttribute(RESULTS_SOURCE_ATTRIBUTE, case_dir.as_posix())
            node.SetAttribute(RESULTS_TABLE_ATTRIBUTE, key)
            folder_tree.CreateItem(folder, node)
        else:
            dataFrameToTableNode(frame, tableNode=node, replace=True)
        autoDetectColumnType(node)
        nodes[key] = node

    return {"results": results, "nodes": nodes, "folder": folder}


def _result_table(case_dir: Path, key: str):
    """The table made from the ``key`` log of ``case_dir``, while it is still in the scene."""
    for node in slicer.util.getNodesByClass("vtkMRMLTableNode"):
        if (
            node.GetAttribute(RESULTS_SOURCE_ATTRIBUTE) == case_dir.as_posix()
            and node.GetAttribute(RESULTS_TABLE_ATTRIBUTE) == key
        ):
            return node
    return None


# -- opening a run ------------------------------------------------------------------------------------
def open_run(details: Dict) -> None:
    """Collector of LBPM jobs: show the run in the LBPM module, with its case, its frames as a time sequence,
    its report and tables, and have the module follow its job again.

    What the Job Monitor's *Open* ends in, also for a job restored after GeoSlicer restarted. ``details``
    are the job's, as :meth:`LBPMSimulationHandler.collect` hands them over.
    """
    source = details.get("source_dir")
    output = details.get("output_dir")
    if not source and not output:
        slicer.util.errorDisplay("This job does not say where its results are, so it cannot be opened.")
        return

    widget = _lbpm_module_widget()
    if widget is None:
        slicer.util.errorDisplay("The LBPM module is not available, so the run cannot be opened.")
        return

    slicer.util.selectModule(LBPM_MODULE)
    widget.openRun(source, output, uid=details.get("uid"))


def _lbpm_module_widget():
    """The LBPM module's widget, loading the module first when this environment has not."""
    if not hasattr(slicer.modules, LBPM_MODULE.lower()):
        try:
            from ltrace.slicer.module_utils import loadModule

            loadModule(slicer.modules.AppContextInstance.modules.availableModules[LBPM_MODULE])
        except Exception as error:
            logging.error(f"Could not load the {LBPM_MODULE} module: {error!r}")
            return None

    return slicer.util.getModuleWidget(LBPM_MODULE)
