from dataclasses import dataclass, field
from typing import ClassVar, Dict
from pathlib import Path

import slicer
import traceback
from ltrace.remote.clients import ssh
from ltrace.remote import errors
from ltrace.remote.hosts.base import Host
from ltrace.remote.paths import storage_for
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
    # Filesystem layout of this cluster: the exported root as the cluster and
    # each kind of workstation see it, plus the directories under it. Shipped
    # in the account template; anything omitted falls back to the defaults in
    # ltrace.remote.paths.
    storage: Dict = field(default_factory=dict)
    # Absolute paths that exist only on the cluster, with no local counterpart.
    remote_paths: Dict = field(default_factory=dict)

    def get_key(self):  # TODO create a short memory cache
        return f"{self.protocol}://{self.username}@{self.address}:{self.port}"

    def get_password(self):
        # Truthiness, not "is not None": the account templates ship
        # "rsa_key": "", and an empty string was counted as an identity file.
        # That made this claim no password was needed, so a stored one was
        # never looked up and the connection failed as an auth error -- which
        # ConnectionManager punishes by deleting the very password it skipped.
        if self.rsa_key:
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
                raise errors.MissingCredentialsError(ValueError(
                    "Missing password and/or identity file."), self.address)

            password = password if isinstance(password, str) else None

            client = ssh.Client(self.address, key_filename=self.rsa_key, port=self.port)
            try:
                client.connect(self.username, password)
                if not client.is_active():
                    # Connectivity problem, not an authentication one: raising
                    # AuthException here would wrongly delete the stored
                    # password and demand a manual reconnect.
                    raise errors.SSHException(RuntimeError("Failed to connect to host."), self.address)

            except Exception:
                # A half-open attempt -- TCP accepted, no banner, which is what
                # a cluster still coming back up looks like -- leaves paramiko
                # holding a socket and a transport thread.
                client.close()
                raise

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
            logging.warning(repr(e))
            raise
        except Exception as e:
            # TODO return for accounts instead of login
            logging.warning(repr(e))
            traceback.print_exc()
            raise

    def server_name(self):
        return self.address

    def get_mounted_path(self):
        # mounted_path stays supported as a direct override of this one
        # directory, which is what it has always meant.
        if self.mounted_path:
            return Path(self.mounted_path)
        return storage_for(self).local_dir("geoslicer_jobs")

    def get_storage(self):
        """This cluster's filesystem layout."""
        return storage_for(self)

    def get_remote_version(self):
        if self.remote_version:
            return self.remote_version
        else:
            return get_posix_friendly_version()

    @staticmethod
    def createWidget() -> "qt.QWidget":
        from ltrace.remote.hosts.ssh.widget import SshConfigWidget

        return SshConfigWidget()
