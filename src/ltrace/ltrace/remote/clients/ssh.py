import socket
import paramiko
import logging

from pathlib import Path

from .base import AbstractClient
from ..errors import *

_1s = 1


class Client(AbstractClient):
    def __init__(self, host, key_filename=None, port=22) -> None:

        self.__credentials = dict(hostname=host, port=port)

        # Clean input
        pkey_ = key_filename.strip() if key_filename else None

        if pkey_:
            pkeyPath = Path(pkey_)
            if not pkeyPath.exists():
                raise ValueError(
                    f"SSH Client 'pkey' argument must be a valid path. The value provided '{pkey_}' does not exist"
                )
            if not pkeyPath.is_file():
                raise ValueError(f"SSH Client 'pkey' argument must be a file. The value provide is '{pkey_}'.")

            self.__credentials["key_filename"] = pkey_

        self.__ssh = paramiko.SSHClient()
        self.__ssh.load_system_host_keys()
        self.__ssh.set_missing_host_key_policy(
            paramiko.MissingHostKeyPolicy()
        )  # TODO this enables MitM attacks, but currently it is only used inside private networks

    def connect(self, user, password=None):
        if user is None:
            raise ValueError(f"SSH Client 'user' argument type is 'NoneType'")

        # Force lower case (Is this a petrobras case?) and clean input
        user_ = user.lower().strip()

        if password:
            password = password.strip()

        kwargs = {}
        if password and "key_filename" not in self.__credentials:
            kwargs["look_for_keys"] = False
            kwargs["allow_agent"] = False

        kwargs["timeout"] = 7 * _1s
        kwargs["auth_timeout"] = 3 * _1s

        credentials = {**self.__credentials, "username": user_, "password": password}

        try:
            self.__ssh.connect(**credentials, **kwargs)
        except socket.timeout as e:
            raise TimeoutException(e, self.__credentials["hostname"])
        except socket.error as e:
            raise SSHException(e, self.__credentials["hostname"])
        except paramiko.BadHostKeyException as e:
            raise BadHostKeyException(e, self.__credentials["hostname"])
        except paramiko.AuthenticationException as e:
            raise AuthException(e, self.__credentials["hostname"])
        except paramiko.SSHException as e:
            raise SSHException(e, self.__credentials["hostname"])
        except Exception as e:
            raise SSHException(e, self.__credentials["hostname"])

    def is_active(self):
        """
        This will check if the connection is still availlable.

        Return (bool) : True if it's still alive, False otherwise.
        """
        try:
            self.__ssh.exec_command("cd .", timeout=5)
            return True
        except Exception as e:
            print("Connection lost, cause: ", repr(e))

        return False

    def which_os(self):
        try:
            output = self.run_command("uname -a")
            if len(output["stderr"]) > 0:
                return "windows"

            if len(output["stdout"]) > 0 and "Linux" in output["stdout"]:
                return "linux"

            return "unknown"
        except Exception as e:
            print("Connection lost, cause: ", repr(e))

    def run_command(self, cmd: str, wait_exit=True, verbose=False):
        try:
            _, stdout_, stderr_ = self.__ssh.exec_command(cmd)
        except paramiko.SSHException as e:
            raise BadScriptPath(e, self.__credentials["hostname"])
        except Exception as e:
            raise SSHException(e, self.__credentials["hostname"])
        finally:
            if verbose:
                print(cmd)

        if wait_exit:
            stdout_.channel.recv_exit_status()

            return dict(
                stdout=stdout_.read().decode("utf-8").strip(),
                stderr=stderr_.read().decode("utf-8").strip(),
            )

        return None

    def close(self):
        try:
            self.__ssh.close()
        except Exception as e:
            logging.exception(e)
