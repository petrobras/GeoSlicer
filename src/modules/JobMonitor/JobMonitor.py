from collections import OrderedDict
from dataclasses import dataclass
import datetime
from functools import partial
import json
import logging
import os

from pathlib import Path
from queue import Queue
from typing import Callable, List
from uuid import uuid4

import ctk


import qt
import slicer
import vtk

from ltrace.slicer.widget.elided_label import ElidedLabel
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic

from ltrace.remote.targets import TargetManager, Host
from ltrace.remote.connections import JobExecutor
from ltrace.remote.jobs import JobManager

from ltrace.slicer import ui


class EventHandler:
    def __call__(self, caller, event, *args, **kwargs):
        return


# class TaskExecutor:

#     def __init__(self,  account_callback: Callable, login_callback: Callable) -> None:
#         self.request_account = account_callback
#         self.request_login = login_callback

#     def run(self, task: Callable, *args, **kwargs):
#         host: TargetHost = self.request_account()
#         if host is None:
#             raise Exception("No host selected")  # TODO handle with custom exceptions

#         connection = self.connections.find(host)
#         if connection is None:
#             connection = connect(host, self.request_login)


# RemoteService.instance.cli(ssh.Client).run()


def prettydt(dtt: datetime):
    dt = dtt.date()
    today_dt = datetime.today().date()
    dt_fmt = "%H:%M"

    if dt < today_dt:
        dt_fmt = "%d %B, %Y" if dt.year != today_dt.year else "%d %B"

    return dtt.strftime(dt_fmt)


class ThreeWayQuestion(qt.QMessageBox):
    def __init__(self, jobname, parent=None):
        super().__init__(parent)

        self.setWindowTitle(f"Job {jobname} has finished")
        self.setText(
            "It has been more than 15 days since this task finished. Please, delete the data to free up space in the cluster."
        )
        self.addButton(qt.QPushButton("Download"), qt.QMessageBox.YesRole)
        self.addButton(qt.QPushButton("Delete"), qt.QMessageBox.NoRole)
        self.addButton(qt.QPushButton("Close"), qt.QMessageBox.RejectRole)


class JobListWidget(qt.QListWidget):
    def __init__(self, parent=None):
        qt.QListWidget.__init__(self, parent)

        qSize = qt.QSizePolicy()
        qSize.setHorizontalPolicy(qt.QSizePolicy.Preferred)
        qSize.setVerticalPolicy(qt.QSizePolicy.Expanding)
        self.setSizePolicy(qSize)

        self.setStyleSheet("QListWidget::item { border-bottom: 1px solid black; }")

    def sizeHint(self):
        return qt.QSize(300, 800)


class JobListItemWidget(qt.QWidget):
    cancelled = qt.Signal(bool)
    inspected = qt.Signal(bool)
    loadResults = qt.Signal(bool)
    errorClick = qt.Signal(bool)

    def __init__(self, job, parent=None):
        qt.QWidget.__init__(self, parent)

        self.setMinimumWidth(312)
        self.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Preferred)

        self.jobNameLabel = ElidedLabel(f"{job.name} (Host: {job.host.name})")
        self.jobNameLabel.setStyleSheet("QLabel {font-size: 14px; font-weight: bold;}")
        self.jobNameLabel.setToolTip(f"{job.name} (Host: {job.host.name})")
        self.jobNameLabel.setMaximumWidth(274)
        progressWidget = self.createProgressInfo()
        infoWidget = self.createInfoWidget(job.status)

        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # self.iconBtn = self.actionButton("erro", onClick=self.showMessageAboutJobAging)
        self.iconBtn = qt.QPushButton("")
        self.iconBtn.clicked.connect(self.showMessageAboutJobAging)
        self.iconBtn.setIcon(qt.QIcon(qt.QPixmap(str(JobMonitor.RES_DIR / "Icons" / "erro.png"))))
        self.iconBtn.setIconSize(qt.QSize(24, 24))
        self.iconBtn.setStyleSheet("QPushButton {padding: 2px}")
        self.iconBtn.visible = False

        iconBlock = qt.QVBoxLayout()
        iconBlock.setContentsMargins(6, 6, 6, 6)
        iconBlock.setSpacing(6)
        iconBlock.addWidget(self.iconBtn)

        frontBlock = qt.QVBoxLayout()
        frontBlock.setContentsMargins(0, 0, 0, 0)
        frontBlock.addWidget(self.jobNameLabel)
        frontBlock.addWidget(progressWidget)
        frontBlock.addWidget(infoWidget)

        self.menuBtn = self.actionButton("menu", onClick=self.showContextMenuOnClick)

        menuBlock = qt.QVBoxLayout()
        menuBlock.setContentsMargins(6, 6, 6, 6)
        menuBlock.setSpacing(6)
        menuBlock.addWidget(self.menuBtn)

        menuBlock.addStretch(1)

        layout.addLayout(iconBlock)
        layout.addLayout(frontBlock)
        layout.addLayout(menuBlock)
        self.update(job)

    # def getIcon(self):
    #     itemIcon = qt.QLabel()
    #     # itemIcon.setStyleSheet("QLabel {padding-top: 4px; padding-left: 16px; padding-right: 16px; padding-bottom: 4px; margin: 0px}")
    #     icon = qt.QIcon(qt.QPixmap(str(JobMonitor.RES_DIR / "Icons" / "job.png"))).pixmap(qt.QSize(24, 24))
    #     itemIcon.setPixmap(icon)
    #     itemIcon.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)
    #     return itemIcon

    def actionButton(self, name, hide=False, onClick=None, parent=None):
        icon = qt.QIcon(qt.QPixmap(str(JobMonitor.RES_DIR / "Icons" / f"{name}.png"))).pixmap(qt.QSize(16, 16))
        button = ui.ClickableLabel(parent)
        button.setPixmap(icon)
        # button = qt.QPushButton("", parent)
        # button.setIcon(qt.QIcon(str(JobMonitor.RES_DIR / "Icons" / f"{name}.png")))
        # button.setIconSize(qt.QSize(16, 16))
        button.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)
        button.setVisible(not hide)
        button.clicked.connect(onClick)
        return button

    def createProgressInfo(self):
        widget = qt.QWidget()
        layout = qt.QHBoxLayout(widget)
        layout.setContentsMargins(0, 6, 0, 0)
        self.progressBar = qt.QProgressBar()
        self.progressBar.setMinimumWidth(300)
        layout.addWidget(self.progressBar)
        return widget

    def createInfoWidget(self, status: str):
        widget = qt.QWidget()
        widget.setMinimumWidth(300)
        layout = qt.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.statusLabel = qt.QLabel(status)
        self.statusLabel.setStyleSheet("QLabel {font-size: 10px; color: 'grey'}")
        layout.addWidget(self.statusLabel)
        layout.addStretch(1)
        self.elapsedTimeValueLabel = qt.QLabel("")
        self.elapsedTimeValueLabel.setStyleSheet("QLabel {font-size: 10px; color: 'grey'}")
        layout.addWidget(self.elapsedTimeValueLabel)
        return widget

    def setContextMenu(self, location: qt.QPoint):
        menu = qt.QMenu(self)
        openAction = menu.addAction("Open")
        openAction.triggered.connect(self.loadResults)
        openAction.enabled = self.allowLoadData
        detailsAction = menu.addAction("Details")
        detailsAction.triggered.connect(self.inspected)
        menu.addSeparator()
        reconnAction = menu.addAction("Reconnect")
        reconnAction.triggered.connect(self.loadResults)
        reconnAction.enabled = self.allowRestart
        menu.addSeparator()
        cancelAction = menu.addAction("Cancel/Delete")
        cancelAction.triggered.connect(self.onDeleteResults)
        menu.exec_(location)

    def showMessageAboutJobAging(self):
        dialog = ThreeWayQuestion(self.jobNameLabel.text)
        clicked = dialog.exec_()

        if clicked == qt.QMessageBox.AcceptRole:
            self.loadResults.emit(True)
        elif clicked == qt.QMessageBox.RejectRole:
            self.onDeleteResults(True)

    def showContextMenuOnClick(self):
        self.setContextMenu(location=self.menuBtn.mapToGlobal(self.menuBtn.rect.topRight()))

    def contextMenuEvent(self, event):
        self.setContextMenu(location=self.mapToGlobal(event.pos()))

    def update(self, job: JobExecutor):
        self.jobNameLabel.setText(f"{job.name} (Host: {job.host.name})")
        self.statusLabel.setText(job.status)  # TGODO use human readable status
        self.progressBar.setValue(job.progress)
        self.elapsedTimeValueLabel.setText(str(JobExecutor.elapsed_time(job)))

        if job.status == "COMPLETED":
            self.allowLoadData = True
            self.allowRestart = not self.allowLoadData
        elif job.status == "IDLE":
            self.allowLoadData = False
            self.allowRestart = not self.allowLoadData
        else:
            self.allowLoadData = False
            self.allowRestart = False

        if JobMonitorLogic.mustIndicateAging(job):
            self.iconBtn.visible = True

    def onDeleteResults(self, clicked):
        """this function open a dialog to confirm and if yes, emit the signal to delete the results"""
        msg = qt.QMessageBox()
        msg.setIcon(qt.QMessageBox.Warning)
        msg.setText(
            "Are you sure you want to cancel/delete this job? This action will delete any result associated with this job on the cluster filesystem."
        )
        msg.setWindowTitle("Warning")
        msg.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
        msg.setDefaultButton(qt.QMessageBox.No)
        if msg.exec_() == qt.QMessageBox.Yes:
            self.cancelled.emit(True)


@dataclass
class JobListFilter:
    hostname: str = None
    status: str = None
    name: str = None
    jobid: str = None


class JobMonitor(LTracePlugin):
    # Plugin info
    SETTING_KEY = "JobMonitor"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Job Monitor"
        self.parent.categories = ["LTrace Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = JobMonitor.help()
        self.parent.acknowledgementText = ""

        self.filter = JobListFilter()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")

    # def setFilter(self, filter: JobListFilter):
    #     self.filter = filter
    #     self.updateList()

    # def filterItem(self, item: JobListItemWidget):
    #     data = item.data(qt.Qt.UserRole)
    #     if self.filter.hostname and self.filter.hostname not in data.host.name:
    #         return True
    #     if self.filter.status and self.filter.status == data.status:
    #         return True
    #     if self.filter.name and self.filter.name not in data.name:
    #         return True
    #     if self.filter.jobid and self.filter.jobid not in data.id:
    #         return True
    #     return False

    # def updateList(self):
    #     for nth in range(self.count):
    #         item = self.item(nth)
    #         item.setHidden(self.filterItem(item))


def jobInfo(job) -> str:
    out = OrderedDict()
    out["Name"] = job.name
    out["UID"] = job.uid
    out["Status"] = job.status
    out["Started at"] = job.start_time
    out["Finished at"] = job.end_time or "Not finished yet"
    out["Last update"] = job.message or "No updates yet"
    if job.details:
        out["Details"] = job.details

    return json.dumps(out, indent=4)


def hostInfo(job) -> str:
    return json.dumps(
        {
            "Address": job.host.address,
            "Port": job.host.port,
            "Username": job.host.username,
            "Identity File": job.host.rsa_key or "Not defined",
        },
        indent=4,
    )


def tracebackInfo(job) -> str:
    if job.traceback:
        return json.dumps(job.traceback, indent=4)
    return "No traceback available"


class DetailsWidget(qt.QWidget):
    # TODO incrementar os resultados aqui
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        layout = qt.QVBoxLayout(self)

        tabwidget = qt.QTabWidget()

        self.infoTab = self.getTextSpace()
        tabwidget.addTab(self.infoTab, "Job")

        self.hostTab = self.getTextSpace()
        tabwidget.addTab(self.hostTab, "Host")

        self.logsTab = self.getTextSpace()
        tabwidget.addTab(self.logsTab, "Logs")

        layout.addWidget(tabwidget)

    @staticmethod
    def getTextSpace():
        textEdit = qt.QPlainTextEdit()
        textEdit.viewport().setAutoFillBackground(False)
        # textEdit.setFrameStyle(qt.QFrame.NoFrame)
        textEdit.setReadOnly(True)
        textEdit.setPlainText("")
        return textEdit

    def update(self, job: JobExecutor):
        self.infoTab.setPlainText(jobInfo(job))
        self.hostTab.setPlainText(hostInfo(job))
        self.logsTab.setPlainText(tracebackInfo(job))


class DetailsDialog(qt.QDialog):
    def __init__(self, job: JobExecutor, parent=None) -> None:
        super().__init__(parent)

        layout = qt.QGridLayout(self)
        layout.setMargin(0)

        self.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        self.view = DetailsWidget()
        layout.addWidget(self.view, 0, 0)

        self.view.update(job)

    @staticmethod
    def show():
        d = DetailsDialog(parent=slicer.util.mainWindow())
        return d.exec_() == 1


class JobMonitorWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

        self.hostSelector = None
        self.jobListWidget = None
        self.listedJobs = {}

        self.logic = JobMonitorLogic(self)

    def onReload(self) -> None:
        # import importlib
        # importlib.reload(register)
        # importlib.reload(login)
        # importlib.reload(accounts)
        try:
            self.listedJobs = {}
            if self.jobListWidget:
                self.jobListWidget.clear()
            del self.jobListWidget
        finally:
            super().onReload()

    def enter(self) -> None:
        super().enter()
        self.update()

    def update(self):
        for uid, job in JobManager.jobs.items():
            if uid not in self.listedJobs:
                self.addJob(job)
            else:
                self.updateJob(job)

    def setup(self):
        LTracePluginWidget.setup(self)

        # self.layout.addWidget(self.buildHeader())

        self.jobListWidget = JobListWidget()
        self.layout.addWidget(self.jobListWidget)
        self.layout.addStretch(1)

        self.jobListWidget.itemDoubleClicked.connect(self.someMethod)

        self.update()

        # self.hostSelector.addItem("All", None)

    def buildHeader(self):
        widget = qt.QWidget()
        layout = qt.QHBoxLayout(widget)
        layout.addWidget(qt.QLabel("Host:"))
        self.hostSelector = qt.QComboBox()
        self.hostSelector.setMinimumWidth(128)
        layout.addWidget(self.hostSelector)
        self.searchBar = qt.QLineEdit()
        self.searchBar.setPlaceholderText("Search by ID, job name, or host")
        layout.addWidget(self.searchBar)
        return widget

    def addJob(self, job: JobExecutor):
        item = qt.QListWidgetItem(self.jobListWidget)
        self.jobListWidget.addItem(item)

        itemWidget = JobListItemWidget(job)
        item.setSizeHint(itemWidget.sizeHint)
        self.jobListWidget.setItemWidget(item, itemWidget)

        itemWidget.inspected.connect(lambda _, job_=job: self.showJobDetails(job_))
        itemWidget.cancelled.connect(lambda _, item_=item, job_=job: self.removeJob(item_, job_))
        itemWidget.loadResults.connect(lambda _, item_=item, job_=job: self.loadResults(item_, job_))
        itemWidget.errorClick.connect(lambda _, job_=job: self.errorOnClick(job_))

        self.listedJobs[job.uid] = item

    def updateJob(self, job: JobExecutor):
        if job.uid in self.listedJobs:
            item = self.listedJobs[job.uid]
            itemWidget = self.jobListWidget.itemWidget(item)
            itemWidget.update(job)
        else:
            self.addJob(job)

    def clearJob(self, job: JobExecutor):
        if job.uid in self.listedJobs:
            item = self.listedJobs[job.uid]
            self.jobListWidget.takeItem(self.jobListWidget.row(item))
            del self.listedJobs[job.uid]

    def loadResults(self, item: qt.QListWidgetItem, job: JobExecutor):
        self.logic.loadResults(job)
        # TODO move isso para o handler slicer.util.selectModule("Data")

    def removeJob(self, item: qt.QListWidgetItem, job: JobExecutor):
        # self.jobListWidget.takeItem(self.jobListWidget.row(item))
        self.logic.cancelJob(job)

    def showJobDetails(self, job: JobExecutor):
        d = DetailsDialog(job, parent=slicer.util.mainWindow())
        self.logic.currentDetail = (job.uid, d.view.update)
        d.exec_()
        self.logic.currentDetail = None

    def errorOnClick(self, job: JobExecutor):
        slicer.util.errorDisplay(f"Error on job {job.name}: {job.message}")

    def addHost(self, host: Host):
        self.hostSelector.addItem(host.name, host)

    def someMethod(self, item):
        pass

        # widget = register.RegisterWidget(templates=[('LOCALHOST', register.Host("localhost", "marcio", "1234"))])
        # widget.setWindowModality(qt.Qt.WindowModal)
        # widget.show()

        # def wrongPassword():
        #     print("wrong password")
        #     raise Exception("wrong password")

        # widget = login.LoginWidget(host=login.Host("localhost", "marcio", "1234"), validate_password=lambda x: wrongPassword())
        # widget.exec_()

        # dialog = accounts.AccountsDialog()
        # dialog.widget.fillList([
        #     register.Host("localhost     SSH(22)", "marcio", "1234"),
        #     register.Host("ATENA 02    SSH(22)", "e85h", "atena02")
        # ])
        # dialog.exec_()


class JobMonitorLogic(LTracePluginLogic):
    def __init__(self, widget):
        self.widget = widget

        self.currentDetail = None

        self._updates = {}

        def listener(job, event):
            self._updates[job.uid] = (job, event)

        JobManager.add_observer(partial(listener))

        JobMonitorLogic.updater(self)

    @staticmethod
    def updater(logic):
        try:
            for key in list(logic._updates.keys()):
                job, event = logic._updates.pop(key)
                logic.eventHandler(job, event)

                if logic.currentDetail and logic.currentDetail[0] == job.uid:
                    logic.currentDetail[1](job)

        except Exception as e:
            logging.error(repr(e))
            # but keep running

        qt.QTimer.singleShot(1000, partial(JobMonitorLogic.updater, logic))

    def eventHandler(self, job, event):
        if event == "JOB_DELETED":
            self.widget.clearJob(job)
        else:
            self.widget.updateJob(job)

    def cancelJob(self, job):
        JobManager.send(job.uid, "CANCEL")

    def loadResults(self, job):
        if job.status == "COMPLETED":
            JobManager.send(job.uid, "COLLECT")
        elif job.status == "IDLE":
            slicer.modules.RemoteServiceInstance.cli.resume(job)

    @staticmethod
    def mustIndicateAging(job: JobExecutor):
        return JobExecutor.elapsed_time(job) > datetime.timedelta(days=15)
