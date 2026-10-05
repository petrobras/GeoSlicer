import itertools
import time
import typing
from collections import OrderedDict
from concurrent.futures import Future
import logging
from queue import PriorityQueue, Empty

import json
from pathlib import Path

from typing import Callable, Dict, List
from threading import Lock, Thread

from ltrace.remote.connections import ConnectionManager, JobExecutor
from ltrace.remote.constants import (
    JOB_DORMANT_STATES,
    JOB_EVENT_CANCEL,
    JOB_EVENT_CLOSE,
    JOB_EVENT_CONNECT,
    JOB_EVENT_PROGRESS,
    JOB_EVENT_SHUTDOWN,
    JOB_INACTIVE_STATES,
    JOB_POLL_INTERVAL_SECONDS,
    JOB_STATE_IDLE,
    JOB_STATE_NOTCONNECTED,
    JOB_STATE_PENDING,
    JOB_TERMINAL_STATES,
)


class JobManager:
    jobs: OrderedDict[str, JobExecutor] = OrderedDict()
    storage: Path = None
    connections: ConnectionManager = None
    observers: List[Callable] = []
    agenda = PriorityQueue()  # entries are (due_time, uid, event, epoch)
    worker: Thread = None
    compilers = {}
    keep_working: bool = True

    read_lock = Lock()

    # Requests riding the agenda -- see request_connect, request_close and
    # request_cancel. The entry's uid slot carries the request id and the
    # payload waits here, so the agenda keeps its (due, uid, event, epoch)
    # shape and ordering.
    pending_requests: Dict[str, tuple] = {}
    _request_ids = itertools.count()

    @staticmethod
    def dirname(job: JobExecutor):
        return f"{job.host.username}-{job.job_type}-{job.uid}"

    @classmethod
    def mount(cls, job: JobExecutor) -> JobExecutor:
        """Attach the job's task handler, and return the job to work with.

        Callers must use the returned object rather than the one they passed in.

        Raises KeyError if the job is not managed. Mounting exists to leave
        cls.jobs holding a mounted object, so a job that is not in there cannot
        be mounted meaningfully: arriving here with one is a programming error,
        not a state to absorb.
        """
        if job.uid not in cls.jobs:
            raise KeyError(f"Job {job.uid} is not managed. Register it with manage() before mounting.")

        compiler = cls.compilers.get(job.job_type)
        if compiler is None:
            # Not an error here -- mount has nothing to do -- but the job comes
            # back with no task_handler, and a job in that state can never poll.
            # Say so once, rather than leaving it to be inferred from silence.
            logging.warning(f"No job loader registered for '{job.job_type}'. Job {job.uid} will be left unmounted.")
            return job

        try:
            mounted = compiler(job)
        except Exception as e:
            logging.error(f"Failed to mount job {job.uid}. Cause: {repr(e)}")
            raise

        if mounted is None:
            # A compiler that mutated in place but forgot to return: keep the
            # object we already have instead of losing the job to None.
            logging.warning(f"Compiler for '{job.job_type}' returned None. Assuming it mounted job {job.uid} in place.")
            return job

        if mounted is not job:
            logging.info(f"Job constructor for '{job.job_type}' replaced job {job.uid}. Updating the registry.")
            cls.jobs[job.uid] = mounted

        return mounted

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
                if job is None or (job.status in JOB_INACTIVE_STATES):
                    # Not a caller error. The event was valid when queued and
                    # the job went inactive while it sat in the agenda -- up to
                    # DISCONNECT_BACKOFF_MAX_SECONDS for a parked retry, or a
                    # user Cancel, which is served by serve_cancel and never
                    # passes through here. Drop it quietly;
                    # schedule() is where a genuine caller mistake is reported.
                    return

                if event == JOB_EVENT_PROGRESS:
                    if epoch is not None and epoch != job.progress_epoch:
                        # Stale entry from a superseded polling chain
                        # (e.g. a parked backoff retry after a manual
                        # reconnect). Drop it.
                        return

                    job.progress_epoch += 1

                job.process(event, cls, cls.connections, **kwargs)
            except Exception as e:
                logging.error(f"Failed to deliver event {event} to job {uid}. Cause: {repr(e)}")

    @classmethod
    def add_observer(cls, observer: Callable):
        if observer in cls.observers:
            # Registering the same observer twice (a module reload re-runs the
            # logic's constructor) only doubles the work it does.
            return

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

        A job that is already inactive is refused here rather than dropped on
        delivery: nothing has raced yet at this point, so the caller is wrong.
        """
        if delay is None:
            delay = JOB_POLL_INTERVAL_SECONDS if event == JOB_EVENT_PROGRESS else 0.0

        job = cls.jobs.get(uid, None)

        # job is None for control events -- SHUTDOWN carries an empty uid and
        # belongs to the monitor loop rather than to any job.
        if job is not None and job.status in JOB_INACTIVE_STATES:
            # A terminal branch that fell through to a reschedule, or a resume
            # that forgot to reactivate the job first. stack_info names the
            # call site; it only costs anything when the guard actually fires.
            logging.warning(
                f"Refusing to schedule {event} for job {uid}: it is {job.status}.",
                stack_info=True,
            )
            return

        epoch = job.progress_epoch if job is not None else 0

        cls.agenda.put((time.monotonic() + delay, uid, event, epoch))

    @classmethod
    def _add_request(cls, event: str, *payload) -> str:
        # Zero-padded so that requests due at the same time keep FIFO order.
        request_id = f"{event}-{next(cls._request_ids):010d}"
        cls.pending_requests[request_id] = (event, *payload)
        return request_id

    @classmethod
    def request_connect(cls, host) -> Future:
        """Have the monitor thread connect to host. Never blocks.

        The future resolves to whether the host is connected -- deliberately
        not to the client, which stays with the monitor thread -- or raises
        what the connection attempt raised. Cancelling it before the monitor
        gets to it skips the attempt.
        """
        if cls.worker is None or not cls.worker.is_alive():
            raise RuntimeError("The job monitor is not running, so nothing can connect.")

        future = Future()
        request_id = cls._add_request(JOB_EVENT_CONNECT, host, future)
        # Due at 0 sorts ahead of every poll: someone is watching a dialog.
        cls.agenda.put((0.0, request_id, JOB_EVENT_CONNECT, 0))
        return future

    @classmethod
    def request_close(cls, host_key: str, client):
        """Have the monitor thread close a client that already left the cache.

        start_monitor registers this with ConnectionManager.set_closer. Posted
        even from the monitor thread itself, so that every close takes the
        same path; it then runs right after the event being delivered.
        """
        request_id = cls._add_request(JOB_EVENT_CLOSE, host_key, client)
        cls.agenda.put((time.monotonic(), request_id, JOB_EVENT_CLOSE, 0))

    @classmethod
    def request_cancel(cls, uid: str) -> Future:
        """Have the monitor thread deliver CANCEL to a job. Never blocks.

        Delivered whatever state the job is in: Cancel/Delete is also the
        remote cleanup of a finished job, the very kind of job schedule() and
        locked_send() refuse. The future raises what the handler raised and
        resolves to None otherwise -- most handlers report a cancel that did
        not go through in the job's state rather than by raising.
        """
        if cls.worker is None or not cls.worker.is_alive():
            raise RuntimeError("The job monitor is not running, so nothing can be cancelled.")

        future = Future()
        request_id = cls._add_request(JOB_EVENT_CANCEL, uid, future)
        # Due at 0, like CONNECT: someone asked for it and is waiting.
        cls.agenda.put((0.0, request_id, JOB_EVENT_CANCEL, 0))
        return future

    @classmethod
    def serve_connect(cls, request_id: str):
        """Monitor thread: make the connection a request asked for."""
        request = cls.pending_requests.pop(request_id, None)
        if request is None:
            return  # already settled by settle_requests

        _, host, future = request
        if not future.set_running_or_notify_cancel():
            return  # the person stopped waiting before it started

        try:
            # Someone is watching a dialog, so this is the user's own
            # connection: it lifts a Disconnect of this host.
            future.set_result(bool(cls.connections.connect(host, user_initiated=True)))
        except Exception as e:
            future.set_exception(e)

    @classmethod
    def serve_close(cls, request_id: str):
        """Monitor thread: close the client a request handed over."""
        request = cls.pending_requests.pop(request_id, None)
        if request is None:
            return  # already settled by settle_requests

        _, host_key, client = request
        cls.connections.close_now(host_key, client)

    @classmethod
    def serve_cancel(cls, request_id: str):
        """Monitor thread: deliver the CANCEL a request asked for."""
        request = cls.pending_requests.pop(request_id, None)
        if request is None:
            return  # already settled by settle_requests

        _, uid, future = request
        if not future.set_running_or_notify_cancel():
            return

        try:
            with cls.read_lock:
                job = cls.jobs.get(uid, None)
                # A job removed meanwhile has nothing left to cancel.
                if job is not None:
                    job.process(JOB_EVENT_CANCEL, cls, cls.connections)
        except Exception as e:
            logging.error(f"Failed to cancel job {uid}. Cause: {repr(e)}")
            future.set_exception(e)
        else:
            future.set_result(None)

    @classmethod
    def settle_requests(cls):
        """Monitor thread, on its way out: nothing will serve these any more.

        Closes the clients still waiting to be closed, and fails the other
        requests, so no dialog waits on them for nothing.
        """
        for request_id in list(cls.pending_requests):
            request = cls.pending_requests.pop(request_id, None)
            if request is None:
                continue

            event = request[0]
            if event == JOB_EVENT_CLOSE:
                _, host_key, client = request
                cls.connections.close_now(host_key, client)
                continue

            future = request[-1]
            if future.set_running_or_notify_cancel():
                future.set_exception(RuntimeError(f"The job monitor stopped before serving {event}."))

    @classmethod
    def prune_connections(cls):
        """Monitor thread: drop the cached connections that closed on their own.

        Its own try, so that a failure here can never starve the job events.
        """
        if cls.connections is None:
            return

        try:
            cls.connections.prune_closed()
        except Exception as e:
            logging.warning(f"Failed to prune closed connections. Cause: {repr(e)}")

    @classmethod
    def remove(cls, uid):
        cls.delete_on_disk(uid)

        job = cls.jobs.pop(uid, None)
        if job is None:
            return

        for observer in cls.observers:
            try:
                observer(job, "JOB_DELETED")
            except Exception as e:
                # One failing observer must not leave the job half-removed:
                # it is already gone from the registry and from disk.
                logging.error(f"Observer failed on removal of job {uid}. Cause: {repr(e)}")

        del job

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

        Returns True when polling was scheduled, False otherwise -- callers
        surface that to the user, so it must not claim success it did not have.

        The SSH connection is NOT opened here: this method runs on the Qt main
        thread and a handshake would block the UI. JobExecutor.process opens
        (or reuses) the connection on the monitor thread when the scheduled
        event is delivered, and flags the job NOT CONNECTED if that fails.
        """
        if job is None or not isinstance(job, JobExecutor):
            return False

        uid = job.uid

        try:
            job = cls.mount(job)

            if job.status in JOB_TERMINAL_STATES:
                # Nothing left to follow. Reconnecting to the host is still
                # useful (it re-enables the remote cleanup) but that is the
                # caller's job, not a polling chain.
                logging.info(f"Job {uid} already finished ({job.status}). Nothing to resume.")
                return False

            if job.task_handler is None:
                # Scheduling this would hand the monitor thread an event with
                # nothing to deliver it to: process() skips a null handler, so
                # the job would burn a connection and then sit in PENDING for
                # good, with nothing on screen saying why. IDLE with a message
                # is the honest outcome.
                logging.error(
                    f"Job {uid} has no task handler: no loader is registered for '{job.job_type}'. Cannot resume."
                )
                cls.set_state(
                    uid,
                    status=JOB_STATE_IDLE,
                    message=f"No loader available for job type '{job.job_type}'.",
                )
                return False

            if job.status in JOB_DORMANT_STATES or job.status == JOB_STATE_NOTCONNECTED:
                # Before schedule(), not after: a job left dormant would have
                # its own resume refused by the guard there. NOT CONNECTED is
                # not dormant -- it is already retrying -- but gets the same
                # reset so the list stops showing a stale failure.
                cls.set_state(uid, status=JOB_STATE_PENDING, message="Resuming job...")

            # Invalidate any parked PROGRESS entry (e.g. a long backoff
            # retry) so this resume becomes the only live polling chain.
            job.progress_epoch += 1

            cls.schedule(uid, JOB_EVENT_PROGRESS)

            return True

        except Exception:
            import traceback

            # Logged as well as recorded: set_state silently drops the traceback
            # when the job is not in the registry, and an unmanaged job is
            # precisely what mount refuses.
            logging.exception(f"Failed to resume job {uid}.")
            cls.set_state(uid, status=JOB_STATE_IDLE, traceback={"[ERROR] Unable to resume": traceback.format_exc()})
            return False

    @staticmethod
    def has_credentials(host) -> bool:
        """Whether a connection to this host could be attempted unattended.

        A stored password or an identity file is enough. Without either, the
        connection can only fail, and failing on the monitor thread is worse
        than not trying: it cannot ask for a password, so the job lands in
        NOT CONNECTED with nothing telling the user what to do about it.
        """
        try:
            return bool(host.get_password())
        except Exception as e:
            logging.warning(f"Could not check credentials for {host.name}. Cause: {repr(e)}")
            return False

    @classmethod
    def resume_all(cls):
        """Restart polling for the jobs that still have something to poll.

        Runs at startup, before any login dialog. Two kinds of job are left
        alone:

          * finished ones -- there is nothing to poll, and resuming them would
            flag them NOT CONNECTED for no reason, a state the monitor refuses
            to cancel;
          * ones whose host has no stored credential -- the connection cannot
            succeed, and the monitor thread has no way to ask for one.

        Returns the hosts of that second group, so the caller can offer the
        user a login instead of leaving them to work out why nothing polls.
        """
        pending = OrderedDict()

        for _, job in list(cls.jobs.items()):
            # Read defensively: the log line for a job broken enough to fail
            # here must not fail as well.
            uid = getattr(job, "uid", "<unknown>")

            try:
                if job.status in JOB_TERMINAL_STATES:
                    logging.info(f"Job {uid} already finished ({job.status}). Skipping resume.")
                    continue

                if not cls.has_credentials(job.host):
                    logging.info(f"No stored credential for {job.host.name}. Job {uid} awaits a sign in.")
                    cls.set_state(
                        uid,
                        status=JOB_STATE_NOTCONNECTED,
                        message=f"Sign in to {job.host.name} to resume this job.",
                    )
                    pending.setdefault(job.host.get_key(), job.host)
                    continue

                cls.resume(job)

            except Exception:
                # One unreadable job must not cost the others their resume, nor
                # take the application's startup with it: this runs from
                # setupRemoteService, and nothing on the slicerrc path guards it.
                logging.exception(f"Could not resume job {uid}. Skipping it.")

        return list(pending.values())

    @classmethod
    def jobs_awaiting_connection(cls, host) -> List[JobExecutor]:
        """The host's jobs that a connection would actually revive.

        Deliberately not the finished ones: resuming those puts them back
        through PENDING, so a completed job flickers a progress stage for no
        reason.
        """
        waiting = []
        for job in list(cls.jobs.values()):
            try:
                if job.host.get_key() == host.get_key() and job.status in (JOB_STATE_IDLE, JOB_STATE_NOTCONNECTED):
                    waiting.append(job)
            except Exception:
                logging.exception(f"Could not read job {getattr(job, 'uid', '<unknown>')}. Leaving it out.")

        return waiting

    @classmethod
    def resume_host(cls, host) -> int:
        """Resume the jobs of one host that are waiting on a connection.

        Returns how many were restarted.
        """
        resumed = 0
        for job in cls.jobs_awaiting_connection(host):
            uid = getattr(job, "uid", "<unknown>")
            try:
                if cls.resume(job):
                    resumed += 1
                else:
                    # Through set_state, not a bare assignment: the monitor only
                    # learns about a change when the observers fire.
                    cls.set_state(uid, status=JOB_STATE_IDLE)
            except Exception:
                logging.exception(f"Could not resume job {uid}. Skipping it.")
        return resumed

    @classmethod
    def load_jobs(cls):
        try:
            jobfile = cls.storage
            djobs = cls.loadjson(jobfile)
            for uid, djob in djobs.items():
                try:
                    job = JobExecutor.fromJson(djob)
                    cls.manage(job)
                except Exception:
                    # Per entry, not per file: fromJson indexes its keys hard
                    # and looks the host protocol up in a table, so one job
                    # written by an older version used to cost every job that
                    # came after it in the file.
                    logging.exception(f"Could not load job {uid} from {jobfile}. Skipping it.")

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
        # From here on every client is closed on this thread, whoever drops it.
        if JobManager.connections is not None:
            JobManager.connections.set_closer(JobManager.request_close)

        try:
            while JobManager.keepWorking():
                JobManager.prune_connections()

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

                    if event == JOB_EVENT_CONNECT:
                        JobManager.serve_connect(uid)
                    elif event == JOB_EVENT_CLOSE:
                        JobManager.serve_close(uid)
                    elif event == JOB_EVENT_CANCEL:
                        JobManager.serve_cancel(uid)
                    else:
                        JobManager.locked_send(uid, event, epoch=epoch)
                except Exception:
                    logging.exception("Job monitor iteration failed.")
        finally:
            if JobManager.connections is not None:
                JobManager.connections.set_closer(None)
            JobManager.settle_requests()

    t = Thread(target=monitor, daemon=False)
    t.start()

    return t
