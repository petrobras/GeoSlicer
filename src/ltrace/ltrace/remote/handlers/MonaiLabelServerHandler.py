from typing import Any
import logging

from ltrace.remote.constants import (
    JOB_EVENT_CANCEL,
    JOB_EVENT_COLLECT,
    JOB_EVENT_DEPLOY,
    JOB_EVENT_PROGRESS,
    JOB_STATE_RUNNING,
    JOB_STATE_CANCELLED,
)
from ltrace.remote.jobs import JobManager
from ltrace.remote.paths import storage_for, to_remote

SCRIPT = "run-notebook.sh"
LOCKFILE = "monailabel.lock"


class MonaiLabelServerHandler:
    def __init__(self, **kwargs):
        self.node_ip = None
        # Rebound from the host in __call__; the defaults stand in until then.
        self._storage = storage_for(None)
        self.app_folder = kwargs.get("app_folder")
        self.dataset_folder = kwargs.get("dataset_folder")

        self.__action_map = {
            JOB_EVENT_DEPLOY: self.deploy,
            JOB_EVENT_PROGRESS: self.progress,
            JOB_EVENT_CANCEL: self.cancel,
            JOB_EVENT_COLLECT: self.collect,
        }

    def __call__(self, caller: JobManager, uid: str, action: str, **kwargs):
        # Bind to the host's storage layout before dispatching: the handler is
        # constructed before it knows which account it belongs to.
        job = caller.jobs.get(uid)
        if job is not None:
            self._storage = storage_for(job.host)

        try:
            client = kwargs.get("client")
            self.__action_map[action](caller, uid, client)
        except KeyError:
            pass

    def deploy(self, caller: JobManager, uid: str, client: Any, **kwargs):
        # Typed by hand, so either separator style and either prefix may arrive.
        self.app_folder = str(to_remote(self.app_folder))
        self.dataset_folder = str(to_remote(self.dataset_folder))

        out = client.run_command(f"sbatch {self._storage.remote_dir('monailabel') / SCRIPT} {self.app_folder} {self.dataset_folder}")

        caller.set_state(uid, JOB_STATE_RUNNING, 100.0, message="Monai server is running.")
        caller.persist(uid)
        caller.schedule(uid, JOB_EVENT_PROGRESS)

    def progress(self, caller: JobManager, uid: str, client: Any, **kwargs):
        out = client.run_command("squeue -hu $USER")
        if out["stdout"].replace("\n", "") == "":
            caller.set_state(uid, JOB_STATE_CANCELLED, 0.0)
            caller.persist(uid)
        else:
            if out["stdout"].replace("\n", "").split(" ")[26] == "R" and self.node_ip == None:
                lock_file = client.run_command(f"cat {self._storage.remote_dir('monailabel') / LOCKFILE}")
                self.node_ip = lock_file["stdout"].replace("\n", "")
                logging.debug(f"Monai server node IP: {self.node_ip}")

                details = {
                    "nodeIP": self.node_ip,
                    "appPath": self.app_folder,
                    "datasetPath": self.dataset_folder,
                }
                caller.set_state(uid, JOB_STATE_RUNNING, 100.0, message="Monai server is running.", details=details)
                caller.persist(uid)

            caller.set_state(uid, JOB_STATE_RUNNING, 100.0)
            caller.schedule(uid, JOB_EVENT_PROGRESS)

    def cancel(self, caller: JobManager, uid: str, client: Any, **kwargs):
        out = client.run_command("scancel -n monailabel")
        caller.set_state(uid, JOB_STATE_CANCELLED, 0.0)
        caller.remove(uid)

    def collect(self, caller: JobManager, uid: str, client: Any, **kwargs):
        slicer.util.selectModule("MONAILabel")
