import datetime
import json
import logging
import os

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import qt
import slicer

from ltrace.remote.connections import ConnectionManager, JobExecutor
from ltrace.remote.constants import (
    JOB_EVENT_COLLECT,
    JOB_STATE_COMPLETED,
    JOB_STATE_IDLE,
    JOB_STATE_NOTCONNECTED,
    JOB_STATE_RUNNING,
)
from ltrace.remote.jobs import JobManager
from ltrace.slicer import ui
from ltrace.slicer.widget.elided_label import ElidedLabel
from ltrace.slicer.widget.search_filter_bar import SearchFilterBar
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic

# Checks if closed source code is available
try:
    from Test.JobMonitorTest import JobMonitorTest
except ImportError:
    JobMonitorTest = None


def prettydt(dtt: datetime):
    dt = dtt.date()
    today_dt = datetime.today().date()
    dt_fmt = "%H:%M"

    if dt < today_dt:
        dt_fmt = "%d %B, %Y" if dt.year != today_dt.year else "%d %B"

    return dtt.strftime(dt_fmt)


KNOWN_FLAGS = {"@host", "@name", "@status", "@address", "@protocol", "@uid", "@type"}
CANCEL_DISABLED_STATES = {JOB_STATE_IDLE, JOB_STATE_NOTCONNECTED, "GHOST"}


@dataclass
class JobSearchQuery:
    host_filter: str = None
    name_filter: str = None
    status_filter: str = None
    address_filter: str = None
    protocol_filter: str = None
    uid_filter: str = None
    type_filter: str = None
    free_text: str = ""

    @classmethod
    def parse(cls, text: str) -> "JobSearchQuery":
        tokens = text.split()
        filters = {
            "@host": None,
            "@name": None,
            "@status": None,
            "@address": None,
            "@protocol": None,
            "@uid": None,
            "@type": None,
        }
        free_parts = []

        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token.lower() in KNOWN_FLAGS and i + 1 < len(tokens):
                filters[token.lower()] = tokens[i + 1]
                i += 2
            else:
                free_parts.append(token)
                i += 1

        return cls(
            host_filter=filters["@host"],
            name_filter=filters["@name"],
            status_filter=filters["@status"],
            address_filter=filters["@address"],
            protocol_filter=filters["@protocol"],
            uid_filter=filters["@uid"],
            type_filter=filters["@type"],
            free_text=" ".join(free_parts),
        )

    @staticmethod
    def _contains(needle, haystack):
        if needle is None:
            return True
        if haystack is None:
            return False
        return needle.lower() in str(haystack).lower()

    def matches(self, job: JobExecutor) -> bool:
        if not self._contains(self.host_filter, job.host.name):
            return False
        if not self._contains(self.name_filter, job.name):
            return False
        if not self._contains(self.status_filter, job.status):
            return False
        if self.address_filter is not None:
            if not self._contains(self.address_filter, getattr(job.host, "address", None)):
                return False
        if self.protocol_filter is not None:
            if not self._contains(self.protocol_filter, getattr(job.host, "protocol", None)):
                return False
        if not self._contains(self.uid_filter, job.uid):
            return False
        if not self._contains(self.type_filter, getattr(job, "job_type", None)):
            return False
        if self.free_text:
            label = f"{job.name} (Host: {job.host.name})".lower()
            if self.free_text.lower() not in label:
                return False
        return True


def should_allow_cancel(status: str, host_connected: bool) -> bool:
    return status not in CANCEL_DISABLED_STATES and host_connected


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
        self.allowCancel = True
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
        cancelAction.enabled = self.allowCancel
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
        elif job.status == "RUNNING" and job.polling_enabled:
            self.allowLoadData = True
            self.allowRestart = not self.allowLoadData
        elif job.status == "IDLE" or job.status == "NOT CONNECTED" or job.status == "GHOST":
            self.allowLoadData = False
            self.allowRestart = not self.allowLoadData
        else:
            self.allowLoadData = False
            self.allowRestart = False

        self.allowCancel = should_allow_cancel(job.status, ConnectionManager.check_host(job.host))

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


class JobMonitor(LTracePlugin):
    # Plugin info
    SETTING_KEY = "JobMonitor"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Job Monitor"
        self.parent.categories = ["Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.acknowledgementText = ""
        self.setHelpUrl("GettingStarted/RemoteComputing.html")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


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

        self.setWindowTitle(f"Job Details - {job.name}")
        self.setMinimumSize(400, 300)
        self.resize(800, 600)
        self.setWindowFlags(qt.Qt.Window | qt.Qt.WindowMaximizeButtonHint | qt.Qt.WindowCloseButtonHint)

        # Enable the easy-to-grab corner for resizing
        self.setSizeGripEnabled(True)

        layout = qt.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = DetailsWidget()
        self.view.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)

        layout.addWidget(self.view, 0, 0)

        self.view.update(job)

    @staticmethod
    def show():
        d = DetailsDialog(parent=slicer.modules.AppContextInstance.mainWindow)
        return d.exec_() == 1


class JobMonitorWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

        self.hostSelector = None
        self.jobListWidget = None
        self.listedJobs = {}

        self.logic = JobMonitorLogic(self)

    def cleanup(self):
        super().cleanup()
        if self.logic is not None:
            self.logic.stop()
            self.logic.deleteLater()

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

        self.searchFilterBar = SearchFilterBar()
        self.layout.addWidget(self.searchFilterBar)

        self.jobListWidget = JobListWidget()
        self.layout.addWidget(self.jobListWidget)
        self.layout.addStretch(1)

        self.jobListWidget.itemDoubleClicked.connect(self.someMethod)
        self.searchFilterBar.searchChanged.connect(self.applyFilter)
        self.searchFilterBar.sortChanged.connect(self.applySorting)
        self.searchFilterBar.resumeRequested.connect(self.resumeVisibleJobs)

        self.update()

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

        self.listedJobs[job.uid] = (item, job)
        self._applyFilterToItem(item, job)

    def updateJob(self, job: JobExecutor):
        if job.uid in self.listedJobs:
            item, _ = self.listedJobs[job.uid]
            self.listedJobs[job.uid] = (item, job)
            itemWidget = self.jobListWidget.itemWidget(item)
            itemWidget.update(job)
            self._applyFilterToItem(item, job)
        else:
            self.addJob(job)

    def clearJob(self, job: JobExecutor):
        try:
            if job and job.uid in self.listedJobs:
                item, _ = self.listedJobs[job.uid]
                self.jobListWidget.takeItem(self.jobListWidget.row(item))
                del self.listedJobs[job.uid]
        except Exception as e:
            logging.error(repr(e))

    def forceDelete(self, uid: str):
        try:
            item, _ = self.listedJobs[uid]
            self.jobListWidget.takeItem(self.jobListWidget.row(item))
            del self.listedJobs[uid]
            JobManager.remove(uid)
        except KeyError:
            logging.error(f"Job {uid} does not exist")

    def _currentQuery(self):
        return JobSearchQuery.parse(self.searchFilterBar.text())

    def _applyFilterToItem(self, item, job):
        item.setHidden(not self._currentQuery().matches(job))

    def applyFilter(self, text):
        query = JobSearchQuery.parse(text)
        for uid, (item, job) in self.listedJobs.items():
            item.setHidden(not query.matches(job))

    def _sortedJobs(self):
        jobs = [job for uid, (item, job) in self.listedJobs.items()]
        sort_mode = self.searchFilterBar.sortMode
        if sort_mode == SearchFilterBar.SORT_NAME_ASC:
            jobs.sort(key=lambda j: j.name.lower())
        elif sort_mode == SearchFilterBar.SORT_NAME_DESC:
            jobs.sort(key=lambda j: j.name.lower(), reverse=True)
        elif sort_mode == SearchFilterBar.SORT_STATUS:
            jobs.sort(key=lambda j: j.status.lower())
        elif sort_mode == SearchFilterBar.SORT_NEWEST:
            jobs.sort(key=lambda j: j.start_time or 0, reverse=True)
        elif sort_mode == SearchFilterBar.SORT_OLDEST:
            jobs.sort(key=lambda j: j.start_time or 0)
        return jobs

    def applySorting(self):
        jobs = self._sortedJobs()
        self.listedJobs = {}
        self.jobListWidget.clear()
        for job in jobs:
            self.addJob(job)

    def resumeVisibleJobs(self):
        for uid, (item, job) in self.listedJobs.items():
            if not item.isHidden() and job.status in (JOB_STATE_IDLE, JOB_STATE_NOTCONNECTED):
                self.logic.loadResults(job)

    def loadResults(self, item: qt.QListWidgetItem, job: JobExecutor):
        self.logic.loadResults(job)
        # TODO move isso para o handler slicer.util.selectModule("Data")

    def removeJob(self, item: qt.QListWidgetItem, job: JobExecutor):
        # self.jobListWidget.takeItem(self.jobListWidget.row(item))
        self.logic.cancelJob(job)

    def showJobDetails(self, job: JobExecutor):
        d = DetailsDialog(job, parent=slicer.modules.AppContextInstance.mainWindow)
        self.logic.currentDetail = (job.uid, d.view.update)
        d.exec_()
        self.logic.currentDetail = None

    def errorOnClick(self, job: JobExecutor):
        slicer.util.errorDisplay(f"Error on job {job.name}: {job.message}")

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


def _listener(job, event):
    logic = slicer.modules.jobmonitor.widgetRepresentation().self().logic
    logic._updates[job.uid] = (job, event)


class JobMonitorLogic(LTracePluginLogic):
    def __init__(self, widget):
        super().__init__(parent=widget.parent)
        self.widget = widget

        self.currentDetail = None

        self._updates = {}

        JobManager.add_observer(_listener)

        self.timer = qt.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.updater)
        self.timer.start()

    def stop(self):
        if self.timer is not None:
            self.timer.stop()
        self.widget = None

    def updater(self):
        self.timer.stop()
        try:
            for key in list(self._updates.keys()):
                job, event = self._updates.pop(key)
                self.eventHandler(job, event)

                if self.currentDetail and self.currentDetail[0] == job.uid:
                    self.currentDetail[1](job)

        except Exception as e:
            logging.error(repr(e))
            # but keep running

        self.timer.start()

    def eventHandler(self, job, event):
        if event == "JOB_DELETED":
            self.widget.clearJob(job)
        else:
            self.widget.updateJob(job)

    def cancelJob(self, job):
        job.process("CANCEL", JobManager, JobManager.connections)

    def loadResults(self, job):
        if job.status == JOB_STATE_COMPLETED:
            job.process(JOB_EVENT_COLLECT, JobManager, JobManager.connections)
        elif job.status == JOB_STATE_RUNNING and job.polling_enabled:
            job.process(JOB_EVENT_COLLECT, JobManager, JobManager.connections)
        elif job.status == JOB_STATE_IDLE or job.status == JOB_STATE_NOTCONNECTED:
            slicer.modules.RemoteServiceInstance.cli.resume(job)

    @staticmethod
    def mustIndicateAging(job: JobExecutor):
        return JobExecutor.elapsed_time(job) > datetime.timedelta(days=15)
