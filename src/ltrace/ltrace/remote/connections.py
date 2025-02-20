from collections import defaultdict
from typing import Any, Callable, Dict

import datetime
import logging
import time

from ltrace.remote import errors
from ltrace.remote.hosts.base import Host
from ltrace.remote.hosts import PROTOCOL_HANDLERS


class TooManyAuthAttempts(Exception):
    pass


class JobExecutor:
    def __init__(self, uid: str, task_handler: Callable, host: Host, name: str = None, job_type: str = None):
        self.uid = uid
        self.job_type = job_type
        self.task_handler = task_handler
        self.host = host
        self.name = name or uid
        self.progress = 0.0
        self.status = "PENDING"
        self.start_time: float = None
        self.end_time: float = None
        self.message = None
        self.traceback = None
        self.details: Dict = None

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

        retry = kwargs.get("retry", False)

        try:
            client = connection_pool.connect(self.host)  # TODO client should be optional
            if self.task_handler:
                self.task_handler(tasker, self.uid, event, client=client, **kwargs)
        except errors.SSHException as e:
            logging.warning(f"Failed to send event {event} to job {self.uid}. Cause: {repr(e)}")
            if retry:
                time.sleep(1)  # avoid flooding the queue
                tasker.agenda.put((self.uid, event))  # pass retry here
        except Exception as e:
            logging.error(f"Failed to send event {event} to job {self.uid}. Cause: {repr(e)}")
            raise


class ConnectionManager:
    connections: Dict[str, Any] = defaultdict(lambda: None)

    @classmethod
    def check_host(cls, host: Host) -> bool:
        host_key = host.get_key()
        return cls.connections.get(host_key, None) is not None

    @classmethod
    def connect(cls, host: Host):
        host_key = host.get_key()
        client = cls.connections.get(host_key, None)

        if client is None:
            try:
                client = host.connect()
            except Exception:
                logging.error(f"Failed to connect to {host.server_name()}. Cleaning password.")
                host.delete_password()
                raise

            if not client:
                return client

            logging.error(f"Storing host {host.server_name()}'s key {host_key}.")
            cls.connections[host_key] = client

        return client

    @classmethod
    def drop_client(cls, host: Host):
        host_key = cls.generate_key(host)
        if host_key in cls.connections:
            del cls.connections[host_key]
