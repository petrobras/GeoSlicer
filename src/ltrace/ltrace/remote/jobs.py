import time
import typing
from collections import OrderedDict
import logging
from queue import Queue

import json
from pathlib import Path

from typing import Callable, Dict, List
from threading import Lock, Thread

from ltrace.remote import errors
from ltrace.remote.connections import ConnectionManager, JobExecutor


class JobManager:
    jobs: OrderedDict[str, JobExecutor] = OrderedDict()
    storage: Path = None
    connections: ConnectionManager = None
    observers: List[Callable] = []
    agenda = Queue()
    worker: Thread = None
    endstates = set(("FAILED", "CANCELLED", "IDLE", "DONE"))
    compilers = {}
    keep_working: bool = True

    read_lock = Lock()

    @staticmethod
    def dirname(job: JobExecutor):
        return f"{job.host.username}-{job.job_type}-{job.uid}"

    @classmethod
    def mount(cls, job: JobExecutor):
        try:
            if job.job_type not in cls.compilers:
                return job

            job = cls.compilers[job.job_type](job)
            return job

        except Exception as e:
            logging.error(f"Failed to mount job {job.uid}. Cause: {repr(e)}")
            raise

    @staticmethod
    def keepWorking():
        return JobManager.keep_working

    @classmethod
    def register(cls, key: str, compiler: Callable):
        cls.compilers[key] = compiler

    @classmethod
    def manage(cls, job: JobExecutor):
        try:
            if job.uid not in cls.jobs:
                cls.jobs[job.uid] = job
                logging.info("Managing the job: " + str(job.uid))
                for observer in cls.observers:
                    observer(job, "JOB_MANAGED")
        except Exception as e:
            import traceback

            logging.error(f"Failed to manage job {job.uid}. Cause: {repr(e)}")
            logging.error(traceback.format_exc())

    @classmethod
    def broadcast(cls, event, **kwargs):
        raise NotImplementedError("Broadcasting not implemented yet")

    # @classmethod
    # def send(cls, uid, event, retry=False, **kwargs):
    #     try:
    #         job = cls.jobs.get(uid)
    #         client = cls.connections.connect(job.host)  # TODO client should be optional
    #         if job.task_handler:
    #             job.task_handler(cls, uid, event, client=client, **kwargs)
    #     except errors.SSHException as e:
    #         logging.warning(f"Failed to send event {event} to job {uid}. Cause: {repr(e)}")
    #         if retry:
    #             time.sleep(1)  # avoid flooding the queue
    #             cls.agenda.put((uid, event))  # pass retry here
    #     except Exception as e:
    #         logging.error(f"Failed to send event {event} to job {uid}. Cause: {repr(e)}")
    #         raise

    @classmethod
    def locked_send(cls, uid, event, **kwargs):
        with cls.read_lock:
            try:
                job = cls.jobs.get(uid, None)
                if job and (job.status not in cls.endstates):
                    job.process(event, cls, cls.connections, **kwargs)
            except Exception as e:
                print(f"Failed to deliver event {event} to job {uid}. Cause: {repr(e)}")

    @classmethod
    def add_observer(cls, observer: Callable):
        # TODO make different observers for send and broadcast
        cls.observers.append(observer)

    @classmethod
    def set_state(
        cls,
        uid,
        status,
        progress=None,
        message=None,
        traceback: typing.Union[str, Dict, None] = None,
        start_time=None,
        end_time=None,
        details: Dict = None,
    ):
        job = cls.jobs.get(uid)

        if job is None:
            logging.info(f"Job {uid} removed. Skipping this state change.")
            return

        try:
            job.status = status
            job.progress = progress or job.progress
            job.message = message or job.message

            if traceback is not None:
                if isinstance(traceback, str):
                    traceback = {"stderr": traceback}

                if job.traceback:
                    job.traceback.update(traceback)
                else:
                    job.traceback = traceback

            if details is not None:
                if job.details:
                    job.details.update(details)
                else:
                    job.details = details

            if start_time and job.start_time is None:
                job.start_time = start_time

            if end_time and job.end_time is None:
                job.end_time = end_time

            for observer in cls.observers:
                observer(job, "JOB_MODIFIED")
        except Exception as e:
            import traceback

            traceback.print_exc()
            logging.error(f"Failed to set state for job {uid}. Cause: {repr(e)}")
        finally:
            pass

    @classmethod
    def schedule(cls, uid: str, event: str):
        cls.agenda.put((uid, event))

    @classmethod
    def remove(cls, uid):
        try:
            cls.delete_on_disk(uid)

            job = cls.jobs.pop(uid)

            for observer in cls.observers:
                observer(job, "JOB_DELETED")

            del job
        finally:
            pass

    @classmethod
    def persist(cls, uid):
        try:
            jobfile = cls.storage
            djobs = cls.loadjson(jobfile)
            this_job = cls.jobs.get(uid)
            djobs[uid] = this_job.to_dict()
            with open(jobfile, "w") as f:
                json.dump(djobs, f)
        except json.JSONDecodeError as je:
            logging.error(f"Error decoding jobfile: File '{jobfile}' has an invalid JSON format. Details: {repr(je)}")
        except Exception as e:
            logging.error(f"Error persisting job: {e}")

    @classmethod
    def resume(cls, job):

        if job is None or not isinstance(job, JobExecutor):
            return

        uid = job.uid

        try:
            client = ConnectionManager.connect(job.host)
            mounted_job = cls.mount(job)

            cls.manage(mounted_job)

            if client and mounted_job and mounted_job.status == "IDLE":
                cls.set_state(uid, status="RUNNING")

            cls.schedule(uid, "PROGRESS")
            return True
        except errors.AuthException as e:
            logging.warning(repr(e))
            if mounted_job.host.rsa_key:
                cls.set_state(
                    uid,
                    status="IDLE",
                    traceback={
                        "[ERROR] Authentication failed": "Please check your credentials (Identity file) and reconnect manually."
                    },
                )
            else:
                cls.set_state(
                    uid,
                    status="IDLE",
                    traceback={"[ERROR] Authentication failed": "Password required, please reconnect manually."},
                )
            return False
        except errors.BadHostKeyException as e:
            logging.warning(repr(e))
            cls.set_state(
                uid,
                status="IDLE",
                traceback={
                    "[ERROR] Authentication failed": "Please check your credentials (Identity file) and reconnect manually."
                },
            )
            return False
        except Exception as e:
            # TODO return for accounts instead of login
            import traceback

            cls.set_state(uid, status="IDLE", traceback={"[ERROR] Unable to connect": traceback.format_exc()})

            return False

    @classmethod
    def resume_all(cls):
        for _, job in cls.jobs.items():
            if not cls.resume(job):
                job.status = "IDLE"

    @classmethod
    def load_jobs(cls):
        try:
            jobfile = cls.storage
            djobs = cls.loadjson(jobfile)
            for _, djob in djobs.items():
                job = JobExecutor.fromJson(djob)
                cls.manage(job)

        except FileNotFoundError:
            pass
        except json.JSONDecodeError as je:
            logging.error(
                f"Error loading previous jobs. Current file has a invalid JSON format.\nDetails: {repr(e)}. File: {jobfile}"
            )
        except Exception as e:
            import traceback

            logging.error(traceback.format_exc())

    @classmethod
    def delete_on_disk(cls, uid):
        try:
            jobfile = cls.storage
            djobs = cls.loadjson(jobfile)
            djobs.pop(uid)
            with open(jobfile, "w") as f:
                json.dump(djobs, f)
        except KeyError:
            pass
        except Exception as e:
            logging.warning(f"Error deleting job: {e}")

    @staticmethod
    def loadjson(path: Path):
        if not path.exists():
            return {}

        try:
            with open(path, "r") as f:
                text = f.read().strip()
                if not text:
                    return {}

                return json.loads(text)

        except Exception as e:
            logging.warning(f"Error loading json file: {e}")
            return {}


def start_monitor():
    def monitor():
        while JobManager.keepWorking():
            try:
                uid, event = JobManager.agenda.get()
                if event == "SHUTDOWN":
                    break

                JobManager.locked_send(uid, event)
            except:
                pass

    t = Thread(target=monitor, daemon=False)
    t.start()

    return t
