"""The local machine as a job host.

Modelling "run it here" as a :class:`~ltrace.remote.hosts.base.Host` means a local job is an ordinary
managed job: it is persisted, resumed after a restart, polled by the same monitor thread, cancelled the same
way, and shown by the Job Monitor next to cluster jobs. No credentials are involved, so the password hooks
are no-ops.
"""

import platform
from dataclasses import dataclass
from typing import ClassVar

from ltrace.remote.clients import local as local_client
from ltrace.remote.hosts.base import Host

LOCAL_HOST_NAME = "This computer"


@dataclass
class LocalHost(Host):
    username: str = ""
    name: str = LOCAL_HOST_NAME
    opening_command: str = ""
    protocol: ClassVar[str] = "local"
    protocol_name: ClassVar[str] = "Local execution"

    def get_key(self) -> str:
        return "local://localhost"

    def get_password(self):
        return None

    def set_password(self, password) -> None:
        return

    def delete_password(self) -> None:
        return

    def connect(self):
        client = local_client.Client()
        client.connect()
        return client

    def server_name(self) -> str:
        return platform.node() or "localhost"

    def get_mounted_path(self):
        """Local jobs read and write the case folder directly, so there is no share to map."""
        return None

    @staticmethod
    def createWidget() -> "qt.QWidget":
        return None
