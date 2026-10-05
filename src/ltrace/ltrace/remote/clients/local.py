"""A client that runs commands on this machine, with the same interface as the SSH client.

This is what lets a local simulation travel through the remote-job machinery — ``JobManager``, its polling
thread, job persistence, resume-after-restart and the Job Monitor UI — instead of needing a second,
parallel implementation for local runs.
"""

import logging
import subprocess

from .base import AbstractClient

DEFAULT_TIMEOUT_SECONDS = 60


class Client(AbstractClient):
    def __init__(self, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.timeout = timeout
        self.__closed = False

    def connect(self, user=None, password=None):  # noqa: D401 - part of the client contract
        """Nothing to connect to; kept so callers do not special-case the local backend."""
        self.__closed = False

    def is_active(self) -> bool:
        return not self.__closed

    def which_os(self) -> str:
        import platform

        system = platform.system().lower()
        return "windows" if system.startswith("win") else "linux"

    def run_command(self, cmd: str, wait_exit: bool = True, verbose: bool = False):
        if verbose:
            logging.info(f"local command: {cmd}")

        try:
            completed = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as error:
            return dict(stdout="", stderr=f"Command timed out after {self.timeout}s: {error}")
        except OSError as error:
            return dict(stdout="", stderr=str(error))

        if not wait_exit:
            return None

        return dict(stdout=(completed.stdout or "").strip(), stderr=(completed.stderr or "").strip())

    def close(self) -> None:
        self.__closed = True
