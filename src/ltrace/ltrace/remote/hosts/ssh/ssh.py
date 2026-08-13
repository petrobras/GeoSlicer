from typing import ClassVar
from pathlib import Path
import platform

import slicer
import traceback
from ltrace.remote.clients import ssh
from ltrace.remote import errors
from dataclasses import dataclass
from ltrace.remote.hosts.base import Host
from ltrace.remote.utils import get_posix_friendly_version
import logging

PASSWORD_NOT_REQUIRED = -1


@dataclass
class SshHost(Host):
    address: str
    rsa_key: str = None
    port: int = 22
    opening_command: str = None
    remote_mount: str = ""
    gpu_partition: str = "gpu"
    cpu_partition: str = "cpu"
    protocol: ClassVar[str] = "ssh"
    protocol_name: ClassVar[str] = "SSH+NFS (Remote Execution)"
    mounted_path: str = ""
    remote_version: str = ""

    def get_key(self):  # TODO create a short memory cache
        return f"{self.protocol}://{self.username}@{self.address}:{self.port}"

    def get_password(self):
        if self.rsa_key is not None:
            return PASSWORD_NOT_REQUIRED
        return super().get_password()

    def connect(self):
        try:
            password = self.get_password()

            if password is None and self.rsa_key is None:
                # No credential stored: this is NOT an authentication failure,
                # so raise a distinct error. AuthException here would wrongly
                # delete a (non-existent) password and mask the real state
                # (e.g. an unavailable server the connect never got to reach).
                raise errors.MissingCredentialsError(
                    ValueError("Missing password and/or identity file."), self.address
                )

            password = password if isinstance(password, str) else None

            client = ssh.Client(self.address, key_filename=self.rsa_key, port=self.port)
            client.connect(self.username, password)

            if not client.is_active():
                # Connectivity problem, not an authentication one: raising
                # AuthException here would wrongly delete the stored password
                # and demand a manual reconnect.
                client.close()
                raise errors.SSHException(RuntimeError("Failed to connect to host."), self.address)

            return client
        except (
            errors.TimeoutException,
            errors.AuthException,
            errors.MissingCredentialsError,
            errors.HostNotFoundError,
            errors.BadHostKeyException,
            errors.BadPermsScriptPath,
            errors.SSHException,
        ) as e:
            logging.warning(e.reason)
            raise
        except Exception as e:
            # TODO return for accounts instead of login
            logging.warning(repr(e))
            traceback.print_exc()
            raise

    def server_name(self):
        return self.address

    def get_mounted_path(self):
        if self.mounted_path:
            return Path(self.mounted_path)
        elif platform.system() == "Windows":
            return Path(r"\\dfs.petrobras.biz\cientifico\cenpes\res\drp\servicos\LTRACE\GEOSLICER\jobs")
        else:
            return Path("/nethome/drp/servicos/LTRACE/GEOSLICER/jobs")

    def get_remote_version(self):
        if self.remote_version:
            return self.remote_version
        else:
            return get_posix_friendly_version()

    @staticmethod
    def createWidget() -> "qt.QWidget":
        from ltrace.remote.hosts.ssh.widget import SshConfigWidget

        return SshConfigWidget()
