"""Offer to sign in to the hosts whose jobs could not be resumed at startup.

GeoSlicer restores its job list when it starts, but the connections behind
those jobs are not restored with it: resuming runs on the monitor thread, which
cannot ask for a password. A host with nothing in the keyring therefore leaves
its jobs sitting in NOT CONNECTED with no indication that a sign in is all they
need.

This dialog is shown once, after startup finishes, listing only those hosts.
Signing in to one resumes that host's waiting jobs and leaves every other job
alone -- in particular the finished ones, which would otherwise flicker back
through a progress stage for nothing.
"""

from typing import Callable, List

import qt

from ltrace.slicer.widget.remote.outdated import OutdatedHostsBanner, outdatedTag


class _HostRow(qt.QFrame):
    """One host: its name, how many jobs are waiting, and a way to sign in."""

    connectRequested = qt.Signal(object)  # emits the host

    def __init__(self, host, jobCount: int, outdated: bool = False, parent=None):
        super().__init__(parent)
        self.__host = host

        self.setObjectName("ReconnectHostRow")
        self.setStyleSheet(
            """
            QFrame#ReconnectHostRow {
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 3px;
            }
            """
        )

        self.nameLabel = qt.QLabel(host.name)
        self.nameLabel.setStyleSheet("font-weight: 600;")

        self.outdatedLabel = outdatedTag()
        self.outdatedLabel.setVisible(outdated)

        jobs = "job" if jobCount == 1 else "jobs"
        self.detailLabel = qt.QLabel(f"{jobCount} {jobs} waiting")
        self.detailLabel.setStyleSheet("color: #999;")

        self.connectButton = qt.QPushButton("Sign in")
        self.connectButton.setToolTip(f"Connect to {host.name} and resume its jobs.")
        self.connectButton.clicked.connect(lambda: self.connectRequested.emit(self.__host))

        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        layout.addWidget(self.nameLabel)
        layout.addWidget(self.outdatedLabel)
        layout.addStretch(1)
        layout.addWidget(self.detailLabel)
        layout.addWidget(self.connectButton)

    def setResult(self, message: str, done: bool) -> None:
        self.detailLabel.setText(message)
        self.connectButton.setEnabled(not done)
        if done:
            self.connectButton.setText("Connected")


class ReconnectDialog(qt.QDialog):
    """Lists the hosts that need a sign in before their jobs can resume."""

    def __init__(
        self,
        hosts: List[object],
        jobCounter: Callable,
        onConnect: Callable,
        isOutdated: Callable = None,
        parent=None,
    ):
        """
        Args:
            hosts: the hosts whose jobs could not be resumed.
            jobCounter: host -> how many of its jobs are waiting.
            onConnect: host -> number of jobs resumed. Raises nothing; a
                failure is reported by returning 0 after the user cancels or
                the connection is refused.
            isOutdated: host -> whether its account was configured in an
                older version, which gets it a warning. None warns about none.
        """
        super().__init__(parent)
        self.__jobCounter = jobCounter
        self.__onConnect = onConnect
        self.__rows = {}

        self.setWindowTitle("Reconnect to continue")
        self.setMinimumWidth(460)

        layout = qt.QVBoxLayout(self)
        layout.setSpacing(10)

        intro = qt.QLabel(
            "Jobs from your last session are waiting on a connection. "
            "Sign in to pick them up again; anything already finished is left as it is."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        outdated = [host.name for host in hosts if isOutdated is not None and isOutdated(host)]
        self.outdatedBanner = OutdatedHostsBanner(self)
        self.outdatedBanner.setHosts(outdated)
        layout.addWidget(self.outdatedBanner)

        for host in hosts:
            row = _HostRow(host, jobCounter(host), outdated=host.name in outdated, parent=self)
            row.connectRequested.connect(self.__onRowConnect)
            self.__rows[host.get_key()] = row
            layout.addWidget(row)

        layout.addStretch(1)

        buttons = qt.QDialogButtonBox(qt.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def __onRowConnect(self, host) -> None:
        row = self.__rows.get(host.get_key())
        if row is None:
            return

        resumed = self.__onConnect(host)

        if resumed:
            jobs = "job" if resumed == 1 else "jobs"
            row.setResult(f"{resumed} {jobs} resumed", done=True)
        elif self.__jobCounter(host) == 0:
            # Connected, but the jobs went away meanwhile (cancelled from the
            # monitor, say). Nothing left to do for this host either way.
            row.setResult("nothing left to resume", done=True)
        else:
            # The user cancelled the login, or it was refused.
            row.setResult("not connected", done=False)

        if all(not r.connectButton.isEnabled() for r in self.__rows.values()):
            self.accept()
