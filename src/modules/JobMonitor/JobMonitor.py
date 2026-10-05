import datetime
import json
import logging
import os

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Dict, Tuple

import qt
import slicer

from ltrace.remote.connections import ConnectionManager, JobExecutor
from ltrace.remote.constants import (
    JOB_DORMANT_STATES,
    JOB_EVENT_COLLECT,
    JOB_INACTIVE_STATES,
    JOB_STATE_COMPLETED,
    JOB_STATE_IDLE,
    JOB_STATE_NOTCONNECTED,
    JOB_STATE_RUNNING,
    JOB_TERMINAL_STATES,
)
from ltrace.remote.jobs import JobManager
from ltrace.slicer import ui
from ltrace.slicer.widget.elided_label import ElidedLabel
from ltrace.slicer.widget.remote import waiting
from ltrace.slicer.widget.search_filter_bar import SearchFilterBar
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.utils.custom_event_filter import CustomEventFilter
from ltrace.utils.log_once import LogOnce

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
# States where we no longer know what the remote side holds, so cancelling
# would risk losing the reference to the job's folder on the cluster.
CANCEL_DISABLED_STATES = JOB_DORMANT_STATES | {JOB_STATE_NOTCONNECTED}
# States a job can be pulled out of by reconnecting to its host. Equal to the
# set above today, but by coincidence rather than by definition: one is about
# what we may still do remotely, the other about what the user can restart.
RESUMABLE_STATES = JOB_DORMANT_STATES | {JOB_STATE_NOTCONNECTED}
# States in which the job is not following anything: the monitor delivers it no
# events (JOB_INACTIVE_STATES) or it is parked waiting to be reconnected. What
# they have in common is that nothing will revalidate the host's cached client
# on its own, so check_host's answer about such a job cannot be trusted.
NOT_POLLING_STATES = JOB_INACTIVE_STATES | {JOB_STATE_NOTCONNECTED}


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
    """Whether the full Cancel/Delete (scancel + remote cleanup) may run.

    Needs a live connection, since the whole point is to reach the cluster,
    and a state that still mirrors a known remote job.
    """
    return status not in CANCEL_DISABLED_STATES and host_connected


def should_allow_forget(status: str, host_connected: bool) -> bool:
    """Whether the local-only removal may run. Always.

    Shown in the menu as "Unlink from cluster". It is the one action that needs
    nothing from the cluster -- it only drops the local entry -- so there is no
    state in which refusing it helps, and every state in which refusing it
    traps the row.

    It used to be offered exactly when Cancel/Delete was not, on the reasoning
    that between them every row kept one working way out. That reasoning leaned
    on `host_connected` being true only when the cluster is actually reachable,
    and check_host does not promise that: it reports whether a client object is
    cached, not whether its transport is alive. A FAILED job is terminal, so
    the monitor delivers it no events, so nothing ever calls drop_client for
    it; with a dead client still cached, the row offered a Cancel/Delete that
    could not reach the host, and hid the Unlink that would have worked.

    The arguments are kept for the call site's symmetry with the other two.
    """
    return True


def partition_by_cancellable(jobs, host_connected) -> Tuple[list, list]:
    """Split jobs into those Cancel/Delete can act on and those it cannot.

    `host_connected` is a callable taking a host, so the caller decides how
    connectivity is judged and this stays testable without a ConnectionManager.
    """
    deletable, blocked = [], []
    for job in jobs:
        target = deletable if should_allow_cancel(job.status, host_connected(job.host)) else blocked
        target.append(job)
    return deletable, blocked


def should_allow_reconnect(status: str, host_connected: bool) -> bool:
    """Whether reconnecting to the job's host is worth offering.

    Also true for finished jobs: reconnecting is what makes their remote
    cleanup available again.

    Offered for every job that is not actively polling, whatever check_host
    says about the host. That method reports whether a client object is cached,
    not whether its transport is alive, and it is honest about it: the staleness
    is meant to be corrected by the next poll, which goes through connect() and
    swaps a dead client out. A job in one of these states never polls again, so
    that correction never comes -- and a FAILED job whose host still had a dead
    client cached had Reconnect greyed out precisely when it was the one thing
    that would have helped.
    """
    return not host_connected or status in NOT_POLLING_STATES


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
    forgotten = qt.Signal(bool)
    inspected = qt.Signal(bool)
    loadResults = qt.Signal(bool)
    reconnected = qt.Signal(bool)
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
        self.allowLoadData = False
        self.allowRestart = False
        self.allowCancel = True
        self.allowForget = False
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
        menu.setToolTipsVisible(True)  # otherwise the actions' tooltips never show
        openAction = menu.addAction("Open")
        openAction.triggered.connect(self.loadResults)
        openAction.enabled = self.allowLoadData
        detailsAction = menu.addAction("Details")
        detailsAction.triggered.connect(self.inspected)
        menu.addSeparator()
        reconnAction = menu.addAction("Reconnect")
        reconnAction.triggered.connect(self.reconnected)
        reconnAction.enabled = self.allowRestart
        reconnAction.setToolTip("Connect to this job's host again, which also re-enables Cancel/Delete.")
        menu.addSeparator()
        cancelAction = menu.addAction("Cancel/Delete")
        cancelAction.triggered.connect(self.onDeleteResults)
        cancelAction.enabled = self.allowCancel
        cancelAction.setToolTip("Cancel the job and delete its data from the cluster.")
        menu.addSeparator()
        forgetAction = menu.addAction("Unlink from cluster")
        forgetAction.triggered.connect(self.onForgetJob)
        forgetAction.enabled = self.allowForget
        # Named for what it costs, not for what it tidies: "Remove from list"
        # read as the neat option and invited people to pick it over
        # Cancel/Delete, which is the one that actually frees the cluster.
        forgetAction.setToolTip(
            "Last resort: stop tracking this job. Its folder stays on the cluster and GeoSlicer "
            "can no longer reach it."
        )
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
        # Kept so the unlink dialog can name the job the user is abandoning.
        self._job = job
        self.jobNameLabel.setText(f"{job.name} (Host: {job.host.name})")
        self.statusLabel.setText(job.status)  # TGODO use human readable status
        self.progressBar.setValue(job.progress)
        self.elapsedTimeValueLabel.setText(str(JobExecutor.elapsed_time(job)))

        hostConnected = ConnectionManager.check_host(job.host)

        if job.status == JOB_STATE_COMPLETED:
            self.allowLoadData = True
        elif job.status == JOB_STATE_RUNNING and job.polling_enabled:
            self.allowLoadData = True
        else:
            self.allowLoadData = False

        self.allowRestart = should_allow_reconnect(job.status, hostConnected)
        self.allowCancel = should_allow_cancel(job.status, hostConnected)
        self.allowForget = should_allow_forget(job.status, hostConnected)

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

    def onForgetJob(self, clicked):
        """Confirm breaking the link between this entry and the cluster.

        Worth a blunt dialog: this is the only action that leaves data behind,
        and it is irreversible from inside GeoSlicer -- there is no way to
        re-attach an entry to a folder once the reference is gone.
        """
        job = getattr(self, "_job", None)
        where = f"{job.name} on {job.host.name}" if job is not None else "this job"

        msg = qt.QMessageBox()
        msg.setIcon(qt.QMessageBox.Warning)
        msg.setText(f"Unlink {where} from the cluster?")
        msg.setInformativeText(
            "This breaks the synchronization between GeoSlicer and the cluster. It does not cancel "
            "anything: if the job is still running it keeps running, and its folder stays on the "
            "cluster taking up space.\n\n"
            "GeoSlicer will no longer know where that folder is, and there is no way to link the job "
            "again afterwards; it would have to be found and deleted by hand.\n\n"
            "If you can reach the host, use 'Reconnect' and then 'Cancel/Delete' instead: that frees "
            "the space properly."
        )
        if job is not None:
            msg.setDetailedText(f"Job UID: {job.uid}\nHost: {job.host.name}\nStatus: {job.status}")
        msg.setWindowTitle("Unlink from cluster")
        msg.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
        msg.setDefaultButton(qt.QMessageBox.No)
        if msg.exec_() == qt.QMessageBox.Yes:
            self.forgotten.emit(True)


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
        self.visibilityFilter = None

        self.logic = JobMonitorLogic(self)

    def cleanup(self):
        super().cleanup()
        if self.visibilityFilter is not None:
            self.visibilityFilter.remove()
            self.visibilityFilter = None
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
        # A snapshot: the monitor thread removes jobs it has cancelled.
        for uid, job in list(JobManager.jobs.items()):
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
        self.searchFilterBar.deleteRequested.connect(self.deleteVisibleJobs)

        # Followed only while on screen, wherever that is. Not on enter() and
        # exit(): this widget also lives in the "Remote Jobs" tab of the right
        # drawer, where Slicer calls neither.
        self.visibilityFilter = CustomEventFilter(self._onVisibilityEvent, self.parent)
        self.visibilityFilter.install()
        if self.parent.isVisible():
            self.logic.start()

        self.update()

    def _onVisibilityEvent(self, obj, event):
        if event.type() == qt.QEvent.Show:
            self.logic.start()
        elif event.type() == qt.QEvent.Hide:
            self.logic.pause()

    def addJob(self, job: JobExecutor):
        item = qt.QListWidgetItem(self.jobListWidget)
        self.jobListWidget.addItem(item)

        itemWidget = JobListItemWidget(job)
        item.setSizeHint(itemWidget.sizeHint)
        self.jobListWidget.setItemWidget(item, itemWidget)

        itemWidget.inspected.connect(lambda _, job_=job: self.showJobDetails(job_))
        itemWidget.cancelled.connect(lambda _, item_=item, job_=job: self.removeJob(item_, job_))
        itemWidget.forgotten.connect(lambda _, job_=job: self.forceDelete(job_.uid))
        itemWidget.loadResults.connect(lambda _, item_=item, job_=job: self.loadResults(item_, job_))
        itemWidget.reconnected.connect(lambda _, job_=job: self.reconnectJob(job_))
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
        """Drop a job locally, without touching the cluster.

        The escape hatch for entries the normal Cancel/Delete cannot reach:
        the remote cleanup needs a live connection, so without this a job on an
        unreachable host (or one already flagged NOT CONNECTED / GHOST) had no
        way out of the list at all.
        """
        try:
            item, _ = self.listedJobs.pop(uid)
            self.jobListWidget.takeItem(self.jobListWidget.row(item))
        except KeyError:
            logging.warning(f"Job {uid} is not listed. Removing it from the manager anyway.")

        try:
            JobManager.remove(uid)
        except Exception as e:
            logging.error(f"Failed to remove job {uid}. Cause: {repr(e)}")

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
        # visibleJobs() is a snapshot: each reconnect waits behind a dialog,
        # and rows can come and go while it does.
        for job in self.visibleJobs():
            if job.status in (JOB_STATE_IDLE, JOB_STATE_NOTCONNECTED):
                self.logic.loadResults(job)

    def visibleJobs(self):
        """What the filter is currently showing.

        A snapshot rather than a live view: cancelling a job takes its row out
        of listedJobs, and iterating the dict while that happens would skip
        entries or raise.
        """
        return [job for _, (item, job) in list(self.listedJobs.items()) if not item.isHidden()]

    def deleteVisibleJobs(self):
        """Cancel/Delete every visible job, after one confirmation for the lot.

        Only the remote cancel: jobs it cannot reach are left listed rather
        than quietly unlinked, because unlinking leaves their data on the
        cluster forever and has to stay a deliberate, per-job decision.
        """
        jobs = self.visibleJobs()
        if not jobs:
            slicer.util.infoDisplay("No jobs are currently visible.")
            return

        deletable, blocked = partition_by_cancellable(jobs, ConnectionManager.check_host)

        if not deletable:
            slicer.util.warningDisplay(
                f"None of the {len(jobs)} visible job(s) can be cancelled right now.\n\n"
                "Cancel/Delete needs a live connection to the job's host. Use 'Reconnect' first, "
                "or 'Unlink from cluster' on a job you are willing to stop tracking."
            )
            return

        if not self.confirmDeleteVisible(deletable, blocked):
            return

        self.cancelJobs(deletable)

    def cancelJobs(self, jobs):
        """Cancel/Delete, then report the jobs it could not cancel. Returns at once."""

        def report(failed):
            if failed:
                names = "\n".join(f"- {job.name} ({job.host.name})" for job, _ in failed)
                slicer.util.errorDisplay(f"{len(failed)} of {len(jobs)} job(s) could not be cancelled:\n\n{names}")

        try:
            self.logic.cancelJobs(jobs, onFinished=report)
        except RuntimeError as e:
            # The job monitor is not running: nothing was sent.
            logging.error(f"Failed to cancel {len(jobs)} job(s). Cause: {repr(e)}")
            slicer.util.errorDisplay(f"Nothing was cancelled: {e}")

    @staticmethod
    def confirmDeleteVisible(deletable, blocked) -> bool:
        msg = qt.QMessageBox(slicer.modules.AppContextInstance.mainWindow)
        msg.setIcon(qt.QMessageBox.Warning)
        msg.setWindowTitle("Cancel/Delete visible jobs")
        msg.setText(f"Cancel and delete {len(deletable)} visible job(s)?")

        informative = (
            "Each one is cancelled on the cluster and every result it produced is deleted from the "
            "cluster filesystem. This cannot be undone."
        )
        if blocked:
            informative += (
                f"\n\n{len(blocked)} other visible job(s) will be left alone: Cancel/Delete needs a "
                "live connection to their host."
            )
        msg.setInformativeText(informative)
        msg.setDetailedText("\n".join(f"{job.name} ({job.status}) on {job.host.name}" for job in deletable))
        msg.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
        msg.setDefaultButton(qt.QMessageBox.No)
        return msg.exec_() == qt.QMessageBox.Yes

    def loadResults(self, item: qt.QListWidgetItem, job: JobExecutor):
        self.logic.loadResults(job)
        # TODO move isso para o handler slicer.util.selectModule("Data")

    def removeJob(self, item: qt.QListWidgetItem, job: JobExecutor):
        # The row leaves the list when the handler removes the job.
        self.cancelJobs([job])

    def reconnectJob(self, job: JobExecutor):
        self.logic.reconnect(job)
        # Refresh every row, not just this one: the connection is per host, so
        # a successful reconnect re-enables Cancel/Delete for its siblings too.
        # Jobs that no longer poll (FAILED, CANCELLED) emit no event of their
        # own, so without this their menu would stay stale.
        self.update()

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


# Filled by the JobManager monitor thread, drained by a QTimer on the main
# thread. Deliberately a plain module-level buffer: the observer used to reach
# the logic through slicer.modules.jobmonitor.widgetRepresentation(), which
# calls into Slicer's module manager -- and therefore into Qt -- from the
# monitor thread. Racing that against the main thread (switching modules, say)
# corrupted X state and took the application down with a BadWindow abort and
# no Python traceback.
_pendingUpdates: Dict[str, Tuple[JobExecutor, str]] = {}
_pendingUpdatesLock = Lock()


def _listener(job, event):
    """Record a job change. Runs on the monitor thread: no Slicer, no Qt."""
    with _pendingUpdatesLock:
        _pendingUpdates[job.uid] = (job, event)


def _drainPendingUpdates():
    """Take everything buffered so far. Main thread only."""
    with _pendingUpdatesLock:
        updates = list(_pendingUpdates.values())
        _pendingUpdates.clear()
    return updates


class JobMonitorLogic(LTracePluginLogic):
    def __init__(self, widget):
        super().__init__(parent=widget.parent)
        self.widget = widget

        self.currentDetail = None

        JobManager.add_observer(_listener)

        # Runs while the monitor is on screen -- see start() and pause().
        self.timer = qt.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.updater)
        self.following = False

        # updater() runs every second, so an error that keeps happening would
        # keep being logged, idle computer or not.
        self.logError = LogOnce(logging.error)

    def start(self):
        """Follow job changes: catch up on what changed meanwhile, then every second."""
        if self.widget is None:
            return

        self.following = True
        self.updater()  # starts the timer on its way out

    def pause(self):
        """Stop following. Changes keep buffering until the next start()."""
        self.following = False
        self.timer.stop()

    def stop(self):
        self.pause()
        self.widget = None

    def updater(self):
        self.timer.stop()
        try:
            for job, event in _drainPendingUpdates():
                self.eventHandler(job, event)

                if self.currentDetail and self.currentDetail[0] == job.uid:
                    self.currentDetail[1](job)

        except Exception as e:
            self.logError(repr(e))
            # but keep running
        finally:
            # Not restarted if the monitor went off screen meanwhile.
            if self.following:
                self.timer.start()

    def eventHandler(self, job, event):
        if event == "JOB_DELETED":
            self.widget.clearJob(job)
        else:
            self.widget.updateJob(job)

    def cancelJobs(self, jobs, onFinished):
        """Cancel/Delete jobs on the job monitor's thread, showing it happening.

        Returns at once. The remote cancel runs where the connection lives,
        and the waiting must not happen in a nested event loop here: the row
        that asked is removed by the very cancel it asked for, while its menu
        is still on the stack. The button stops the waiting, not the
        cancelling; a failure that comes after that is only logged, by the
        monitor.

        onFinished gets (job, error) for each job whose cancel raised. Most
        handlers never raise -- one that cannot reach the cluster flags the
        job instead, and the row shows it.
        """
        requests = [(job, JobManager.request_cancel(job.uid)) for job in jobs]

        def finished(_allDone):
            onFinished([(job, future.exception()) for job, future in requests if future.done() and future.exception()])

        text = f"Cancelling {jobs[0].name}..." if len(jobs) == 1 else f"Cancelling {len(jobs)} jobs..."
        waiting.whenDone(
            [future for _, future in requests],
            finished,
            title="Cancel/Delete",
            text=text,
            buttonText="Continue in background",
            parent=slicer.modules.AppContextInstance.mainWindow,
        )

    def reconnect(self, job):
        """Open the connection to the job's host again.

        For a job that still has work to follow this also restarts its polling.
        For a finished one there is nothing left to poll, so it only restores
        the connection -- which is what re-enables the remote Cancel/Delete.
        """
        service = getattr(slicer.modules, "RemoteServiceInstance", None)
        if service is None:
            logging.error("Remote service is not available. Cannot reconnect.")
            return

        try:
            if job.status in JOB_TERMINAL_STATES:
                service.cli.initiateConnectionDialog(job.host)
            else:
                service.cli.resume(job)
        except Exception as e:
            logging.error(f"Failed to reconnect job {job.uid}. Cause: {repr(e)}")

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
