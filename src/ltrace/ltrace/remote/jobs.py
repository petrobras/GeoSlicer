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
        except Exception as e:
            logging.error(f"Failed to mount job {job.uid}. Cause: {repr(e)}")

        return job

    @classmethod
    def register(cls, key: str, compiler: Callable):
        cls.compilers[key] = compiler

    @classmethod
    def manage(cls, job: JobExecutor):
        if job.uid not in cls.jobs:
            cls.jobs[job.uid] = job

            for observer in cls.observers:
                observer(job, "JOB_MANAGED")

    @classmethod
    def broadcast(cls, event, **kwargs):
        raise NotImplementedError("Broadcasting not implemented yet")

    @classmethod
    def send(cls, uid, event, **kwargs):
        try:
            job = cls.jobs.get(uid)
            client = cls.connections.connect(job.host)  # TODO client should be optional
            if job.task_handler:
                job.task_handler(cls, uid, event, client=client, **kwargs)
        except Exception as e:
            logging.error(f"Failed to send event {event} to job {uid}. Cause: {repr(e)}")

    @classmethod
    def communicate(cls, uid, event, **kwargs):
        with cls.read_lock:
            try:
                job = cls.jobs.get(uid, None)
                if job and (job.status not in cls.endstates):
                    cls.send(uid, event, **kwargs)
            except errors.SSHException as e:
                print("communicate function failed ON CONNECTION: ", repr(e))
                cls.agenda.put((uid, event))
            except Exception as e:
                print("communicate function failed: ", repr(e))
            finally:
                pass

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
        traceback=None,
        start_time=None,
        end_time=None,
        details: Dict = None,
    ):
        try:
            job = cls.jobs.get(uid)
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
        except AttributeError:
            logging.info("Job not existing anymore, skipping set_state")
            import traceback

            traceback.print_exc()
            logging.info("---------------")
        except Exception as e:
            import traceback

            traceback.print_exc()
            logging.error(f"on jobs.JobManager.set_state = {repr(e)}")
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
        try:
            client = ConnectionManager.connect(job.host)

            job = cls.mount(job)

            cls.manage(job)

            if client and job and job.status == "IDLE":
                cls.set_state(job.uid, status="RUNNING")

            cls.schedule(job.uid, "PROGRESS")
            return True
        except errors.AuthException as e:
            logging.warning(repr(e))
            if job.host.rsa_key:
                cls.set_state(
                    job.uid,
                    status="IDLE",
                    traceback={
                        "[ERROR] Authentication failed": "Please check your credentials (Identity file) and reconnect manually."
                    },
                )
            else:
                cls.set_state(
                    job.uid,
                    status="IDLE",
                    traceback={"[ERROR] Authentication failed": "Password required, please reconnect manually."},
                )
            return False
        except errors.BadHostKeyException as e:
            logging.warning(repr(e))
            cls.set_state(
                job.uid,
                status="IDLE",
                traceback={
                    "[ERROR] Authentication failed": "Please check your credentials (Identity file) and reconnect manually."
                },
            )
            return False
        except Exception as e:
            # TODO return for accounts instead of login
            import traceback

            cls.set_state(job.uid, status="IDLE", traceback={"[ERROR] Unable to connect": traceback.format_exc()})

            return False

    @classmethod
    def resume_all(cls):
        for _, job in cls.jobs.items():
            if not cls.resume(job):
                job.status = "IDLE"

    @classmethod
    def load(cls):
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
    def jobspy():
        while True:
            try:
                uid, event = JobManager.agenda.get()
                JobManager.communicate(uid, event)
            except:
                pass

    t = Thread(target=jobspy, daemon=False)
    t.start()

    return t

    # @classmethod
    # def _persist(cls):
    #     if cls.storage is None:
    #         raise ValueError("No storage path set.")

    #     data = []
    #     for job in cls.jobs.values():
    #         blob = pickle.dumps(cls.jobs).encode('utf-8')

    #         djob = {
    #             "host": asdict(job.host),
    #             "uid": job.uid,
    #             "handler": blob,
    #             "status": job.status,
    #             "progress": job.progress,
    #             "message": job.message,
    #             "traceback": job.traceback
    #         }

    #         data.append(djob)

    #     content = {"jobs": data}

    #     cls.targets_storage.parent.mkdir(parents=True, exist_ok=True)

    #     with open(cls.targets_storage, "w") as file:
    #         json.dump(content, file, indent=2)

    # @classmethod
    # def load_from_remote(cls):
    #     if cls.targets_storage is None:
    #         raise ValueError("No storage path set.")

    #     if not cls.targets_storage.exists():
    #         logging.warning(f"Target storage {cls.targets_storage} does not exist. Starting with empty targets.")
    #         cls.targets = {}
    #         return

    #     try:
    #         with open(cls.targets_storage, "r") as file:
    #             content = json.load(file)
    #             cls.targets = {host["name"]: Host(**host) for host in content["hosts"]}
    #     except Exception as e:
    #         logging.error(f"Error loading targets: {e}")
    #         cls.targets = {}

    # @classmethod
    # def load(cls):
    #     pass
