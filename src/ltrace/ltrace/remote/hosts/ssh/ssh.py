from typing import ClassVar

import slicer
import traceback
from ltrace.remote.clients import ssh
from ltrace.remote import errors
from ltrace.remote.errors import AuthException
from dataclasses import dataclass
from ltrace.remote.hosts.base import Host
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
                raise AuthException(ValueError("Missing password and/or identity file."), self.address)

            password = password if isinstance(password, str) else None

            client = ssh.Client(self.address, key_filename=self.rsa_key, port=self.port)
            client.connect(self.username, password)

            if not client.is_active():
                raise AuthException(RuntimeError("Failed to connect to host."), self.address)

            return client
        except (
            errors.TimeoutException,
            errors.AuthException,
            errors.BadHostKeyException,
            errors.BadPermsScriptPath,
            errors.SSHException,
        ) as e:
            logging.warning(e.reason)
            raise
        except Exception as e:
            # TODO return for accounts instead of login
            logging.warning(e.reason)
            traceback.print_exc()
            raise

    def server_name(self):
        return self.address

    @staticmethod
    def createWidget() -> "qt.QWidget":
        from ltrace.remote.hosts.ssh.widget import SshConfigWidget

        return SshConfigWidget()
