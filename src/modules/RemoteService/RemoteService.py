import logging
import os
import uuid as uuidlib
from typing import Callable, Dict, List

from pathlib import Path


import slicer

from ltrace.slicer_utils import *
from ltrace.remote.connections import ConnectionManager, JobExecutor
from ltrace.remote.jobs import JobManager, start_monitor
from ltrace.remote.targets import TargetManager, Host
from ltrace.remote import errors

from ltrace.slicer.widget.remote import login, accounts, connecting
from ltrace.slicer.widget.remote.reconnect import ReconnectDialog
from ltrace.slicer.application_observables import ApplicationObservables

from JobLoader import register_job_loaders


class RemoteService(LTracePlugin):
    SETTING_KEY = "RemoteService"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Remote Queue Watcher Service"
        self.parent.categories = ["Backends"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]  # replace with "Firstname Lastname (Organization)"
        self.parent.hidden = True
        self.parent.helpText = ""
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = ""

        self.hosts_file = Path(slicer.app.userSettings().fileName()).parent / "remote" / "config.json"

        self.job_file = Path(slicer.app.userSettings().fileName()).parent / "remote" / "jobs.json"

        moduleDir = Path(os.path.dirname(os.path.realpath(__file__)))
        self.templates_dir = moduleDir / "Resources" / "templates"

        JobManager.storage = self.job_file
        JobManager.connections = ConnectionManager  # TODO direct access not good

        TargetManager.set_storage(self.hosts_file)
        TargetManager.set_templates_dir(self.templates_dir)

        self.cli = RemoteServiceLogic()
        # Hosts whose jobs could not be resumed for want of a credential,
        # handed to __promptReconnect once the application is up.
        self.__pendingReconnectHosts = []

    def setupRemoteService(self):
        # paramiko logs each step of every connection at DEBUG and INFO -- the
        # handshake, the auth, every channel -- and the job polls open channels
        # every few seconds. Only its errors are worth a line in the log. Set on
        # the parent logger: paramiko.transport and the rest inherit it.
        logging.getLogger("paramiko").setLevel(logging.ERROR)

        TargetManager.load_targets()

        register_job_loaders()

        # A connection someone asked for revives every job parked on that host,
        # not just the one that prompted it. Registered here rather than called
        # from each connect site so the Accounts dialog, which connects on its
        # own, is covered too.
        ConnectionManager.add_connected_listener(self.__resumeJobsWaitingOn)

        JobManager.load_jobs()

        JobManager.worker = start_monitor()
        ApplicationObservables().aboutToQuit.connect(self.__joinJobManageWorker)
        logging.info("Remote Service setup complete " + str(len(JobManager.jobs)))

        # Jobs whose host has no stored credential are not resumed here: this
        # runs on the way up, where nothing can ask for a password. Offer the
        # user a sign in once the application is on screen instead.
        pending = JobManager.resume_all()
        if pending:
            self.__pendingReconnectHosts = pending
            ApplicationObservables().applicationLoadFinished.connect(self.__promptReconnect)

    def __resumeJobsWaitingOn(self, host):
        """Restart the jobs that were only waiting for this host to come back.

        The ones flagged NOT CONNECTED for want of a credential never retry on
        their own -- process() returns without delivering their event -- so a
        successful login is the only thing that can move them.
        """
        resumed = JobManager.resume_host(host)
        if resumed:
            logging.info(f"Resumed {resumed} job(s) waiting on {host.name}.")

    def __promptReconnect(self):
        """Ask the user to sign in to the hosts whose jobs are waiting.

        Fires once, after startup: connecting is a modal conversation and has
        no business happening while the application is still assembling itself.
        """
        try:
            ApplicationObservables().applicationLoadFinished.disconnect(self.__promptReconnect)
        except Exception:  # pragma: no cover - already disconnected
            pass

        hosts = [host for host in self.__pendingReconnectHosts if JobManager.jobs_awaiting_connection(host)]
        self.__pendingReconnectHosts = []
        if not hosts:
            return

        def connect(host):
            # Sign in, then revive only the jobs that were waiting on it.
            self.cli.initiateConnectionDialog(host)
            if not ConnectionManager.check_host(host):
                return 0
            return JobManager.resume_host(host)

        dialog = ReconnectDialog(
            hosts,
            jobCounter=lambda host: len(JobManager.jobs_awaiting_connection(host)),
            onConnect=connect,
            isOutdated=TargetManager.is_outdated,
            parent=slicer.modules.AppContextInstance.mainWindow,
        )
        dialog.exec_()
        dialog.deleteLater()

    def __joinJobManageWorker(self):
        JobManager.keep_working = False
        JobManager.schedule("", "SHUTDOWN")
        JobManager.worker = None


# Not Implemented
class RemoteServiceWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)

    @staticmethod
    def showMonitor():
        pass

    @staticmethod
    def showLoginDialog(host):
        """Sign in to a host. Returns None if the user cancelled.

        A failure that is not about the password is re-raised rather than
        shown here, so the caller reports it with the same dialog it uses for
        a connection that needed no login step.
        """
        widget = login.LoginDialog(host=host)
        widget.exec_()
        if widget.error is not None:
            raise widget.error
        return widget.output

    @staticmethod
    def showAccounts(hosts: List[Host], select, templates: List[Host] = None, forJob: bool = False):
        if select is None:
            raise ValueError("select callback is required")

        dialog = accounts.AccountsDialog(backend=TargetManager, templates=templates, onAccept=select, forJob=forJob)
        dialog.widget.fillList(hosts)
        return dialog.exec_() == 1


class RemoteServiceLogic:
    template_dir = Path(os.path.dirname(os.path.realpath(__file__))) / "Resources" / "templates"

    def load_templates(self):
        templates = []
        for template in self.template_dir.glob("*.json"):
            host = TargetManager.load_host(template)
            templates.append((host.name, host))
        return templates

    def showSelectTargetDialog(self, targets: List[tuple[bool, Host]], forJob: bool = False):
        """The account picked in the list, and whether it was picked only to connect to it.

        Picking the account a job runs on, Connect and the send arrow are
        different choices: Connect only connects, then the list comes back to
        send the job from.
        """
        target: Host = None
        connectOnly = False

        def select(choice: Host, send: bool = False):
            nonlocal target, connectOnly
            target = choice
            connectOnly = forJob and not send

        templates = self.load_templates()

        if not RemoteServiceWidget.showAccounts(targets, select, templates=templates, forJob=forJob):
            target = None

        return target, connectOnly

    def initiateConnectionDialog(self, host: Host = None, keepDialogOpen=False, forJob=False):
        """Connect to a host, asking which one when none is given.

        forJob means the host is where a job will run: the account list, if it
        is shown, offers to send the job to an account besides connecting it.
        """

        target = host or TargetManager.default
        if host is None and TargetManager.is_outdated(target):
            # Connecting to it silently would hide that it has to be created
            # again: go through the account list, which says so.
            target = None

        connected = None
        connectOnly = False

        while keepDialogOpen or connected is None:
            if keepDialogOpen:
                """Clear target so that the dialog is shown again"""
                target = None

            if not isinstance(target, Host):
                hosts = [(ConnectionManager.check_host(h), h) for h in TargetManager.targets.values()]
                target, connectOnly = self.showSelectTargetDialog(hosts, forJob=forJob)

            if target is None:
                """If no target is selected, means the user cancelled the dialog. We are done here."""
                return None, None
            try:
                try:
                    # Either way the job monitor makes the connection; these
                    # only show it happening.
                    if target.get_password():
                        connected = connecting.connect(target, parent=slicer.modules.AppContextInstance.mainWindow)
                    else:
                        connected = RemoteServiceWidget.showLoginDialog(target)

                    if connected is None:
                        # Cancelled, at the password prompt or while
                        # connecting. Back to the account list.
                        target = None
                        continue

                    if connected:
                        ConnectionManager.announce_connected(target)
                        if connectOnly:
                            # Connected from the list, not sent there: back
                            # to it, to pick the account the job runs on.
                            target, connected = None, None
                            continue
                        if keepDialogOpen is False:
                            return target, connected

                except errors.TimeoutException as e:
                    slicer.util.errorDisplay(
                        "Connection timed out. Check your network connection and host address, then try again."
                    )
                    raise
                except Exception as e:
                    # TODO return for accounts instead of login
                    slicer.util.errorDisplay(
                        "Connection failed. Check your network connection and host address, then try again."
                    )
                    raise
            except:
                target = None

        return target, connected

    def run(
        self,
        task_handler: Callable,
        name: str = None,
        job_type: str = None,
        polling_enabled: bool = False,
        uid: str = None,
    ):
        """Connect to a cluster and start the job there. Returns the job's uid, or None when it did not start.

        ``uid`` is for a caller that already named something after the job, such as the folder it staged the
        job's inputs in; without one, a new uid is made.
        """
        try:
            target, client_connected = self.initiateConnectionDialog(forJob=True)

            if not client_connected:
                return None

            uid = uid or str(uuidlib.uuid4())

            JobManager.manage(
                JobExecutor(uid, task_handler, target, name=name, job_type=job_type, polling_enabled=polling_enabled)
            )

            JobManager.schedule(uid, "DEPLOY")

            return uid
        except:
            import traceback

            traceback.print_exc()
            # TODO informe o usuario

        return None

    def resume(self, job: JobExecutor):
        try:
            self.initiateConnectionDialog(job.host)

            started = JobManager.resume(job)
            if not started:
                slicer.util.errorDisplay("Failed to automatically resume job. Please try to reconnect manually.")
        except:
            import traceback

            traceback.print_exc()
            # TODO informe the user
