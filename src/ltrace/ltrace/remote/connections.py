from collections import defaultdict
from threading import Lock
from typing import Any, Callable, Dict

import datetime
import logging
import time

from ltrace.remote import errors
from ltrace.remote.constants import JOB_STATE_NOTCONNECTED, JOB_STATE_PENDING
from ltrace.remote.hosts.base import Host
from ltrace.remote.hosts import PROTOCOL_HANDLERS


class TooManyAuthAttempts(Exception):
    pass


class JobExecutor:
    def __init__(
        self,
        uid: str,
        task_handler: Callable,
        host: Host,
        name: str = None,
        job_type: str = None,
        polling_enabled: bool = False,
    ):
        self.uid = uid
        self.job_type = job_type
        self.task_handler = task_handler
        self.host = host
        self.name = name or uid
        self.polling_enabled = polling_enabled
        self.progress = 0.0
        self.status = JOB_STATE_PENDING
        self.start_time: float = None
        self.end_time: float = None
        self.message = None
        self.traceback = None
        self.details: Dict = None
        # Turnstile token for PROGRESS deliveries: stale entries in the agenda
        # are dropped when their stamped epoch no longer matches. Not persisted.
        self.progress_epoch = 0

    @staticmethod
    def elapsed_time(job: "JobExecutor") -> datetime.timedelta:
        if job.start_time is None:
            return datetime.timedelta(0)
        if job.end_time is None:
            return datetime.datetime.now() - datetime.datetime.fromtimestamp(job.start_time)
        return datetime.datetime.fromtimestamp(job.end_time) - datetime.datetime.fromtimestamp(job.start_time)

    @staticmethod
    def fromJson(data: Dict[str, Any]):
        protocol = data["host"]["protocol"]
        host = PROTOCOL_HANDLERS[protocol].from_dict(data["host"])
        job = JobExecutor(data["uid"], None, host, name=data["name"], job_type=data["job_type"])
        job.polling_enabled = data.get("polling_enabled", True)  # Using get for older versions compatibility
        job.progress = data["progress"]
        job.status = data["status"]
        job.start_time = data["start_time"]
        job.end_time = data["end_time"]
        job.message = data["message"]
        job.traceback = data["traceback"]
        job.details = data["details"]
        return job

    def to_dict(self):
        return {
            "uid": self.uid,
            "job_type": self.job_type,
            "name": self.name,
            "polling_enabled": self.polling_enabled,
            "host": self.host.to_dict(),
            "progress": self.progress,
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "message": self.message,
            "traceback": self.traceback,
            "details": self.details,
        }

    def process(self, event, tasker, connection_pool, **kwargs):
        client = None

        try:
            client = connection_pool.connect(self.host)  # TODO client should be optional
        except errors.MissingCredentialsError as e:
            # Permanent failure: no stored credential to use. Flag NOT CONNECTED
            # and return WITHOUT delivering the event, so the handler never runs
            # disconnected() and the polling loop stops here. A manual
            # 'Reconnect' restarts it.
            logging.warning(repr(e))
            tasker.set_state(
                self.uid,
                status=JOB_STATE_NOTCONNECTED,
                traceback={"[ERROR] Credentials required": "No saved credentials. Please reconnect manually."},
            )
            return
        except errors.HostNotFoundError as e:
            # Permanent failure: the host address could not be resolved.
            # Retrying can't find it, so stop the loop (see above).
            logging.warning(repr(e))
            tasker.set_state(
                self.uid,
                status=JOB_STATE_NOTCONNECTED,
                traceback={"[ERROR] Host not found": "Host address could not be resolved. Please reconnect manually."},
            )
            return
        except (errors.AuthException, errors.BadHostKeyException) as e:
            # Permanent failure: rejected/invalid credential or a changed host
            # key. Retrying the same inputs can't succeed, so stop the loop
            # (see above).
            logging.warning(repr(e))
            if getattr(self.host, "rsa_key", None):
                reason = "Please check your credentials (Identity file) and reconnect manually."
            else:
                reason = "Password required, please reconnect manually."
            tasker.set_state(
                self.uid,
                status=JOB_STATE_NOTCONNECTED,
                traceback={"[ERROR] Authentication failed": reason},
            )
            return
        except errors.SSHException as e:
            # Transient connectivity failure over a resolvable host: fall through
            # to deliver the event with client=None so the handler's reconnect
            # backoff retries.
            logging.warning(f"SSH connection failed when sending event {event} to job {self.uid}. Cause: {repr(e)}")
        except Exception as e:
            logging.error(f"Connection failed when sending event {event} to job {self.uid}. Cause: {repr(e)}")
        try:
            if self.task_handler:
                self.task_handler(tasker, self.uid, event, client=client, **kwargs)
        except Exception as e:
            logging.error(f"Failed to send event {event} to job {self.uid}. Cause: {repr(e)}")
            raise


class ConnectionManager:
    connections: Dict[str, Any] = defaultdict(lambda: None)

    # Serializes connection attempts per host so that concurrent callers
    # (e.g. the monitor thread and the Qt thread) cannot run duplicate
    # handshakes and leak clients.
    _host_locks: Dict[str, Lock] = {}
    _host_locks_guard = Lock()

    @classmethod
    def _lock_for(cls, host_key: str) -> Lock:
        with cls._host_locks_guard:
            lock = cls._host_locks.get(host_key)
            if lock is None:
                lock = Lock()
                cls._host_locks[host_key] = lock
            return lock

    @classmethod
    def check_host(cls, host: Host) -> bool:
        host_key = host.get_key()
        return cls.connections.get(host_key, None) is not None

    @classmethod
    def get_client(cls, host_key):
        return cls.connections.get(host_key, None)

    @classmethod
    def connect(cls, host: Host):
        host_key = host.get_key()

        with cls._lock_for(host_key):
            client = cls.connections.get(host_key, None)

            if client is None:
                try:
                    client = host.connect()
                except errors.MissingCredentialsError:
                    # Nothing stored to invalidate: surface as-is so the caller
                    # can prompt for login, instead of deleting a non-existent
                    # password or reporting it as a rejected credential.
                    logging.warning(f"No stored credentials for {host.server_name()}.")
                    raise
                except errors.AuthException:
                    # Only bad credentials invalidate the stored password;
                    # transient failures must not, or auto-reconnect can
                    # never succeed after a network blip.
                    logging.error(f"Failed to authenticate to {host.server_name()}. Cleaning password.")
                    host.delete_password()
                    raise
                except Exception:
                    logging.error(f"Failed to connect to {host.server_name()}.")
                    raise

                if not client:
                    return client

                logging.info(f"Storing host {host.server_name()}'s key {host_key}.")
                cls.connections[host_key] = client

            return client

    @classmethod
    def drop_client(cls, host: Host, stale_client: Any = None):
        """Discard the cached client for a host and close it.

        When stale_client is given, only drop the cache entry if it still is
        that exact client — another thread may have reconnected meanwhile,
        and its fresh client must not be discarded.
        """
        host_key = host.get_key()

        with cls._lock_for(host_key):
            cached = cls.connections.get(host_key, None)
            if cached is None or (stale_client is not None and cached is not stale_client):
                return
            del cls.connections[host_key]

        try:
            cached.close()
        except Exception as e:
            logging.warning(f"Failed to close stale client for {host.server_name()}: {repr(e)}")
