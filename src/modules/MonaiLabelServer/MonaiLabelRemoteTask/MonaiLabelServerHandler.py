from datetime import datetime
import shutil
from typing import Any, Callable
import re
import time
from pathlib import Path, PurePosixPath
from ltrace.remote.errors import SSHException

from ltrace.remote.utils import argstring
from ltrace.remote.jobs import JobManager

NFS_MOUNTED_FOLDER = "//dfs.petrobras.biz/cientifico/cenpes/res/"
NFS_REMOTE_FOLDER = "/nethome/"
SCRIPT = "drp/smart-segmenter/laminas/run-notebook.sh"
LOCKFILE = "drp/smart-segmenter/laminas/monailabel.lock"


class MonaiLabelServerHandler:
    def __init__(self, **kwargs):
        self.node_ip = None
        self.app_folder = kwargs.get("app_folder")
        self.dataset_folder = kwargs.get("dataset_folder")

        self.__action_map = {
            "DEPLOY": self.deploy,
            "PROGRESS": self.progress,
            "CANCEL": self.cancel,
            "COLLECT": self.collect,
        }

    def __call__(self, caller: JobManager, uid: str, action: str, **kwargs):
        try:
            client = kwargs.get("client")
            self.__action_map[action](caller, uid, client)
        except KeyError:
            pass

    def deploy(self, caller: JobManager, uid: str, client: Any, **kwargs):
        self.app_folder = str(self.app_folder)
        self.app_folder = self.app_folder.replace("\\", "/")
        self.app_folder = self.app_folder.replace(NFS_MOUNTED_FOLDER, NFS_REMOTE_FOLDER)

        self.dataset_folder = str(self.dataset_folder)
        self.dataset_folder = self.dataset_folder.replace("\\", "/")
        self.dataset_folder = self.dataset_folder.replace(NFS_MOUNTED_FOLDER, NFS_REMOTE_FOLDER)

        out = client.run_command(f"sbatch {NFS_REMOTE_FOLDER}{SCRIPT} {self.app_folder} {self.dataset_folder}")

        caller.set_state(uid, "RUNNING", 100.0, message="Monai server is running.")
        caller.persist(uid)
        caller.schedule(uid, "PROGRESS")

    def progress(self, caller: JobManager, uid: str, client: Any, **kwargs):
        out = client.run_command("squeue -hu $USER")
        if out["stdout"].replace("\n", "") == "":
            caller.set_state(uid, "CANCELLED", 0.0)
            caller.persist(uid)
        else:
            if out["stdout"].replace("\n", "").split(" ")[26] == "R" and self.node_ip == None:
                lock_file = client.run_command(f"cat {NFS_REMOTE_FOLDER}{LOCKFILE}")
                self.node_ip = lock_file["stdout"].replace("\n", "")
                print(self.node_ip)

                details = {
                    "nodeIP": self.node_ip,
                    "appPath": self.app_folder,
                    "datasetPath": self.dataset_folder,
                }
                caller.set_state(uid, "RUNNING", 100.0, message="Monai server is running.", details=details)
                caller.persist(uid)

            caller.set_state(uid, "RUNNING", 100.0)
            caller.schedule(uid, "PROGRESS")

    def cancel(self, caller: JobManager, uid: str, client: Any, **kwargs):
        out = client.run_command("scancel -n monailabel")
        caller.set_state(uid, "CANCELLED", 0.0)
        caller.remove(uid)

    def collect(self, caller: JobManager, uid: str, client: Any, **kwargs):
        slicer.util.selectModule("MONAILabel")
