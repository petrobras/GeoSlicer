import time
import typing
from collections import OrderedDict
import logging
from queue import PriorityQueue, Empty

import json
from pathlib import Path

from typing import Callable, Dict, List
from threading import Lock, Thread

from ltrace.remote.connections import ConnectionManager, JobExecutor
from ltrace.remote.constants import (
    JOB_EVENT_PROGRESS,
    JOB_EVENT_SHUTDOWN,
    JOB_POLL_INTERVAL_SECONDS,
    JOB_STATE_FAILED,
    JOB_STATE_NOTCONNECTED,
    JOB_STATE_PENDING,
    JOB_STATE_CANCELLED,
    JOB_STATE_IDLE,
    JOB_STATE_DONE,
)


class JobManager:
    jobs: OrderedDict[str, JobExecutor] = OrderedDict()
    storage: Path = None
    connections: ConnectionManager = None
    observers: List[Callable] = []
    agenda = PriorityQueue()  # entries are (due_time, uid, event, epoch)
    worker: Thread = None
    endstates = set((JOB_STATE_FAILED, JOB_STATE_CANCELLED, JOB_STATE_IDLE, JOB_STATE_DONE))
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
    def locked_send(cls, uid, event, epoch=None, **kwargs):
        with cls.read_lock:
            try:
                job = cls.jobs.get(uid, None)
                if job is None or (job.status in cls.endstates):
                    return

                if event == JOB_EVENT_PROGRESS:
                    if epoch is not None and epoch != job.progress_epoch:
                        # Stale entry from a superseded polling chain
                        # (e.g. a parked backoff retry after a manual
                        # reconnect). Drop it.
                        return
                    # Turnstile: consuming the epoch on every accepted
                    # delivery guarantees at most one live PROGRESS chain
                    # per job, even if duplicates were ever scheduled.
                    job.progress_epoch += 1

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
    def schedule(cls, uid: str, event: str, delay: float = None):
        """Queue an event for delivery by the monitor thread, optionally delayed.

        PROGRESS events default to JOB_POLL_INTERVAL_SECONDS so that polling
        handlers rescheduling themselves cannot busy-loop the monitor thread.
        """
        if delay is None:
            delay = JOB_POLL_INTERVAL_SECONDS if event == JOB_EVENT_PROGRESS else 0.0

        job = cls.jobs.get(uid, None)
        epoch = job.progress_epoch if job is not None else 0

        cls.agenda.put((time.monotonic() + delay, uid, event, epoch))

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
        """Mount the job and restart its polling.

        The SSH connection is NOT opened here: this method runs on the Qt main
        thread and a handshake would block the UI. JobExecutor.process opens
        (or reuses) the connection on the monitor thread when the scheduled
        event is delivered, and flags the job NOT CONNECTED if that fails.
        """
        if job is None or not isinstance(job, JobExecutor):
            return

        uid = job.uid

        try:
            mounted_job = cls.mount(job)

            cls.manage(mounted_job)

            if mounted_job.status in (JOB_STATE_IDLE, JOB_STATE_NOTCONNECTED):
                cls.set_state(uid, status=JOB_STATE_PENDING, message="Resuming job...")

            # Invalidate any parked PROGRESS entry (e.g. a long backoff
            # retry) so this resume becomes the only live polling chain.
            mounted_job.progress_epoch += 1

            cls.schedule(uid, JOB_EVENT_PROGRESS)
            return True
        except Exception as e:
            import traceback

            cls.set_state(uid, status=JOB_STATE_IDLE, traceback={"[ERROR] Unable to resume": traceback.format_exc()})

            return False

    @classmethod
    def resume_all(cls):
        for _, job in cls.jobs.items():
            cls.resume(job)

    @classmethod
    def resume_host(cls, host):
        for _, job in cls.jobs.items():
            if host.get_key() == job.host.get_key():
                if not cls.resume(job):
                    job.status = JOB_STATE_IDLE

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
                f"Error loading previous jobs. Current file has a invalid JSON format.\nDetails: {repr(je)}. File: {jobfile}"
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
                try:
                    item = JobManager.agenda.get(timeout=1.0)
                except Empty:
                    continue

                due, uid, event, epoch = item

                if event == JOB_EVENT_SHUTDOWN:
                    break

                remaining = due - time.monotonic()
                if remaining > 0:
                    # Not due yet: wait a bounded slice and requeue, so
                    # newly scheduled events (including SHUTDOWN) still get
                    # picked up promptly.
                    time.sleep(min(remaining, 1.0))
                    JobManager.agenda.put(item)
                    continue

                JobManager.locked_send(uid, event, epoch=epoch)
            except Exception:
                logging.exception("Job monitor iteration failed.")

    t = Thread(target=monitor, daemon=False)
    t.start()

    return t
