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

from ltrace.slicer.widget.remote import login, accounts
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

        self.cli = RemoteServiceLogic()

    def setupRemoteService(self):
        TargetManager.load_targets()

        register_job_loaders()

        JobManager.load_jobs()

        JobManager.worker = start_monitor()
        ApplicationObservables().aboutToQuit.connect(self.__joinJobManageWorker)
        logging.info("Remote Service setup complete " + str(len(JobManager.jobs)))
        JobManager.resume_all()

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
        widget = login.LoginDialog(host=host)
        widget.exec_()
        return widget.output

    @staticmethod
    def showAccounts(hosts: List[Host], select, templates: List[Host] = None):
        if select is None:
            raise ValueError("select callback is required")

        dialog = accounts.AccountsDialog(backend=TargetManager, templates=templates, onAccept=select)
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

    def showSelectTargetDialog(self, targets: List[tuple[bool, Host]]):
        target: Host = None

        def select(choice: Host):
            nonlocal target
            target = choice

        templates = self.load_templates()

        if not RemoteServiceWidget.showAccounts(targets, select, templates=templates):
            target = None

        return target

    def initiateConnectionDialog(self, host: Host = None, keepDialogOpen=False):

        target = host or TargetManager.default

        client = None

        while keepDialogOpen or client is None:
            if keepDialogOpen:
                """Clear target so that the dialog is shown again"""
                target = None

            if not isinstance(target, Host):
                hosts = [(ConnectionManager.check_host(h), h) for h in TargetManager.targets.values()]
                target = self.showSelectTargetDialog(hosts)

            if target is None:
                """If no target is selected, means the user cancelled the dialog. We are done here."""
                return None, None
            try:
                try:
                    if not target.get_password():
                        RemoteServiceWidget.showLoginDialog(target)

                    client = ConnectionManager.connect(target)

                    if client is not None and keepDialogOpen is False:
                        return target, client

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

        return target, client

    def run(self, task_handler: Callable, name: str = None, job_type: str = None):
        try:
            target, client_connected = self.initiateConnectionDialog()

            if not client_connected:
                return None

            uid = str(uuidlib.uuid4())

            JobManager.manage(JobExecutor(uid, task_handler, target, name=name, job_type=job_type))

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
