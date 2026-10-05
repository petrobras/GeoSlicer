from collections import defaultdict
from threading import Lock
from typing import Any, Callable, Dict, Set

import datetime
import logging
import time

from ltrace.remote import errors
from ltrace.remote.constants import JOB_STATE_NOTCONNECTED, JOB_STATE_PENDING, JOB_TERMINAL_STATES
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

    def flag_not_connected(self, tasker, title: str, reason: str):
        """Record a connection failure, without rewriting a finished job's state.

        A job that already reached a terminal state has nothing left to poll:
        overwriting it with NOT CONNECTED would both lose its outcome and move
        it into a state the monitor refuses to cancel, leaving an entry the
        user can no longer remove. The reason is still attached so 'Details'
        explains why the connection failed.
        """
        status = JOB_STATE_NOTCONNECTED
        if self.status in JOB_TERMINAL_STATES:
            status = self.status

        tasker.set_state(self.uid, status=status, traceback={title: reason})

    def process(self, event, tasker, connection_pool, **kwargs):
        client = None

        try:
            client = connection_pool.connect(self.host)  # TODO client should be optional
        except errors.UserDisconnectedError as e:
            # Not a failure: the user disconnected from this host. Park the job
            # without delivering the event (see below), so polling stops until
            # they connect again -- which resumes it.
            logging.info(repr(e))
            self.flag_not_connected(
                tasker,
                "[INFO] Disconnected",
                "Disconnected by the user. Use 'Reconnect' to resume.",
            )
            return
        except errors.MissingCredentialsError as e:
            # Permanent failure: no stored credential to use. Flag NOT CONNECTED
            # and return WITHOUT delivering the event, so the handler never runs
            # disconnected() and the polling loop stops here. A manual
            # 'Reconnect' restarts it.
            logging.warning(repr(e))
            self.flag_not_connected(
                tasker,
                "[ERROR] Credentials required",
                "No saved credentials. Please reconnect manually.",
            )
            return
        except errors.HostNotFoundError as e:
            # Permanent failure: the host address could not be resolved.
            # Retrying can't find it, so stop the loop (see above).
            logging.warning(repr(e))
            self.flag_not_connected(
                tasker,
                "[ERROR] Host not found",
                "Host address could not be resolved. Please reconnect manually.",
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
            self.flag_not_connected(tasker, "[ERROR] Authentication failed", reason)
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
    # Run after a connection someone asked for -- see announce_connected.
    _connected_listeners = []
    # Closes a client once it has left the cache -- see set_closer.
    _closer: Callable = None
    # Keys of the hosts the user disconnected from, refused to anyone but the
    # user until they connect again -- see disconnect. In memory only: a
    # restart starts from a clean slate.
    _disconnected: Set[str] = set()

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

    @staticmethod
    def _is_usable(client: Any) -> bool:
        """Whether a cached client can still be handed out.

        Clients without a liveness check are assumed usable: a wrong 'dead'
        here would drop a working connection on every poll.
        """
        checker = getattr(client, "is_alive", None)
        if checker is None:
            return True

        try:
            return bool(checker())
        except Exception as e:
            logging.warning(f"Failed to check client liveness: {repr(e)}")
            return False

    @classmethod
    def check_host(cls, host: Host) -> bool:
        """Whether this process holds a connection to the host.

        Deliberately does not probe the client. This runs on the UI thread,
        once per job row per second, while the client object belongs to the
        monitor thread -- which may be closing or replacing it at that very
        moment. The staleness is short-lived: the monitor thread evicts a
        closed connection within about a second (prune_closed), and connect()
        checks liveness before handing a client out.
        """
        return cls.connections.get(host.get_key(), None) is not None

    @classmethod
    def get_client(cls, host_key):
        return cls.connections.get(host_key, None)

    @classmethod
    def connect(cls, host: Host, user_initiated: bool = False):
        """Return a connected client for the host, reusing the cached one.

        user_initiated means the user asked for this connection (the Connect
        button, a login). Only such a connection lifts a Disconnect; everyone
        else -- the job monitor polling, a lazy load -- gets
        UserDisconnectedError until then.
        """
        host_key = host.get_key()

        with cls._lock_for(host_key):
            if user_initiated:
                cls._disconnected.discard(host_key)
            elif host_key in cls._disconnected:
                raise cls._disconnected_error(host)

            client = cls.connections.get(host_key, None)

            if client is not None and not cls._is_usable(client):
                # A cached client whose transport already died (laptop sleep,
                # VPN drop, server-side timeout) would fail on its very next
                # command and be reported as a fresh disconnection. Replace it
                # here instead, so a reachable host never shows NOT CONNECTED.
                logging.info(f"Cached client for {host.server_name()} is dead. Reconnecting.")
                del cls.connections[host_key]
                cls._close(host_key, client)
                client = None

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

                if not user_initiated and host_key in cls._disconnected:
                    # The user disconnected while this handshake ran. Caching
                    # the client would undo it, so throw it away instead.
                    cls._close(host_key, client)
                    raise cls._disconnected_error(host)

                logging.info(f"Storing host {host.server_name()}'s key {host_key}.")
                cls.connections[host_key] = client

            return client

    @classmethod
    def add_connected_listener(cls, listener: Callable):
        """Register a callable to run after a user-initiated connection.

        A registry rather than a direct call because jobs.py already imports
        this module; reaching back to JobManager from here would be a cycle.
        """
        if listener not in cls._connected_listeners:
            cls._connected_listeners.append(listener)

    @classmethod
    def announce_connected(cls, host: Host):
        """Tell the listeners that a host someone asked to connect to is up.

        Main thread only, after the monitor thread made the connection. A
        connection belongs to the host, not to whatever prompted it, so
        everything parked on that host can move again once it is up -- and the
        jobs stopped for want of a credential only ever get one this way:
        process() returns without delivering their event, so nothing else will
        ever restart them.

        Announced on a cache hit too. Clicking connect on a host that is
        already connected is exactly what someone does when a job looks stuck,
        and the listeners only act on jobs that are waiting for it.

        Never from the monitor thread, not even after its own reconnects: the
        listeners resume jobs, resuming mounts them, and mounting runs a job
        loader that touches MRML.
        """
        for listener in list(cls._connected_listeners):
            try:
                listener(host)
            except Exception as e:
                logging.error(f"Connection listener failed for {host.server_name()}. Cause: {repr(e)}")

    @classmethod
    def drop_client(cls, host: Host, stale_client: Any = None):
        """Discard the cached client for a host and have it closed.

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

        cls._close(host_key, cached)

    @classmethod
    def disconnect(cls, host: Host):
        """Close the connection to a host at the user's request, and keep it closed.

        Dropping the client alone would not last: the next poll of any job on
        the host reconnects with the stored credential, seconds later. So the
        host is also refused to every caller but the user (see connect) until
        they connect again. The credential is kept, so that needs no password.
        Jobs polling the host are parked NOT CONNECTED by their next poll, and
        the connection that lifts the Disconnect resumes them.
        """
        # Flag first: a poll landing between the two steps would otherwise
        # reconnect and cache a fresh client right after the drop.
        cls._disconnected.add(host.get_key())
        cls.drop_client(host)

    @staticmethod
    def _disconnected_error(host: Host) -> errors.UserDisconnectedError:
        return errors.UserDisconnectedError(
            RuntimeError(f"Disconnected from {host.server_name()} by the user."), host.server_name()
        )

    @classmethod
    def prune_closed(cls):
        """Evict every cached client whose connection has closed. Monitor thread only.

        connect() only swaps out the client of the host it is asked for, so a
        connection the server closed used to stay cached for as long as nothing
        connected to that host again -- forever, once its jobs stopped polling
        -- and check_host() kept reporting the host as connected.
        """
        for host_key, client in list(cls.connections.items()):
            if client is None or cls._is_usable(client):
                continue

            lock = cls._lock_for(host_key)
            if not lock.acquire(blocking=False):
                # A connect() for this host is running and does its own swap.
                # Waiting on it would stall the monitor behind a handshake.
                continue
            try:
                if cls.connections.get(host_key, None) is not client:
                    continue  # replaced meanwhile
                del cls.connections[host_key]
            finally:
                lock.release()

            logging.info(f"Connection {host_key} was closed. Removing it from the cache.")
            cls._close(host_key, client)

    @classmethod
    def set_closer(cls, closer: Callable = None):
        """Route every close through closer(host_key, client); None closes in place.

        The job monitor registers itself here so that only its thread ever
        closes a client. Taking one out of the cache is safe from any thread,
        but close() is a paramiko call, and the caller may be the UI thread.
        A registry rather than a direct call for the same reason as
        add_connected_listener.
        """
        cls._closer = closer

    @classmethod
    def _close(cls, host_key: str, client: Any):
        """Close a client that has already left the cache.

        With no monitor registered (unit tests, or after shutdown) no other
        thread owns the client, so it is closed right here.
        """
        closer = cls._closer or cls.close_now
        closer(host_key, client)

    @staticmethod
    def close_now(host_key: str, client: Any):
        """Close a client on the calling thread, which should be the monitor's."""
        try:
            client.close()
        except Exception as e:
            logging.warning(f"Failed to close client {host_key}: {repr(e)}")
