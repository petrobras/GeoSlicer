from functools import partial
from typing import List, Callable

import qt

from ltrace.remote.connections import ConnectionManager
from ltrace.remote.targets import Host

from ltrace.slicer.widget.remote.outdated import OutdatedHostsBanner, outdatedTag
from ltrace.slicer.widget.remote.register import RegisterDialog

SEND_COLOR = "#43a047"
DISCONNECT_STYLE = (
    "QPushButton { background-color: #c62828; color: white; border: 1px solid #8e0000;"
    " border-radius: 3px; padding: 3px 8px; }"
    " QPushButton:hover { background-color: #d32f2f; }"
    " QPushButton:pressed { background-color: #b71c1c; }"
)


def drawSendIcon(size=32) -> "qt.QIcon":
    """A green arrow pointing right: run the job on this account."""
    pixmap = qt.QPixmap(size, size)
    pixmap.fill(qt.Qt.transparent)
    painter = qt.QPainter(pixmap)
    painter.setRenderHint(qt.QPainter.Antialiasing)
    pen = qt.QPen(qt.QColor(SEND_COLOR))
    pen.setWidth(size // 6)
    pen.setCapStyle(qt.Qt.RoundCap)
    pen.setJoinStyle(qt.Qt.RoundJoin)
    painter.setPen(pen)

    middle = size // 2
    margin = size // 6
    tip = size - margin
    head = size // 3
    painter.drawLine(margin, middle, tip, middle)
    painter.drawLine(tip - head, middle - head, tip, middle)
    painter.drawLine(tip - head, middle + head, tip, middle)
    painter.end()
    return qt.QIcon(pixmap)


class AccountListItemWidget(qt.QWidget):
    signin = qt.Signal()
    # Not 'disconnect': that would shadow QObject.disconnect.
    signout = qt.Signal()
    send = qt.Signal()
    set_default = qt.Signal()
    edit = qt.Signal()
    remove = qt.Signal()

    OK = 1
    ERROR = 0

    def __init__(self, text, connected=False, defaultAccount=False, outdated=False, forJob=False, parent=None) -> None:
        super().__init__(parent)

        self.text = text
        self.defaultAccount = defaultAccount
        self.outdated = outdated
        self.forJob = forJob

        self._setupUI()

        # Note: keep after UI setup, this is a property
        self.status = self.ERROR if not connected else self.OK

    def _setupUI(self) -> None:
        self.statusLabel = qt.QLabel()

        self.hostLabel = qt.QLabel(self.text)

        self.outdatedLabel = outdatedTag()
        self.outdatedLabel.setVisible(self.outdated)

        # Only when the list is picking where a job runs. Connected or not:
        # sending connects first if needed.
        self.sendButton = qt.QPushButton()
        self.sendButton.setIcon(drawSendIcon())
        self.sendButton.setIconSize(qt.QSize(20, 20))
        self.sendButton.setToolTip("Run the job on this account, connecting to it first if needed.")
        self.sendButton.setVisible(self.forJob)

        # Its text and action follow the status: Disconnect while connected, Connect otherwise.
        self.connectionButton = qt.QPushButton()
        # Wide enough for either text, so the buttons line up across rows.
        self.connectionButton.setMinimumWidth(self.connectionButton.fontMetrics().horizontalAdvance("Disconnect") + 32)
        self.defaultButton = qt.QPushButton("Set as default")
        self.editButton = qt.QPushButton("Edit")
        self.removeButton = qt.QPushButton("Remove")

        self.defaultLabel = qt.QLabel("(default)")

        self.defaultOption()

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.setSpacing(8)
        buttonsLayout.addWidget(self.sendButton)
        buttonsLayout.addWidget(self.connectionButton)
        buttonsLayout.addWidget(self.defaultButton)
        buttonsLayout.addWidget(self.editButton)
        buttonsLayout.addWidget(self.removeButton)

        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self.statusLabel)
        layout.addWidget(self.hostLabel)
        layout.addWidget(self.outdatedLabel)
        layout.addStretch(1)
        layout.addWidget(self.defaultLabel)
        layout.addLayout(buttonsLayout)

        self.sendButton.clicked.connect(lambda: self.send.emit())
        self.connectionButton.clicked.connect(self._onConnectionClicked)
        self.defaultButton.clicked.connect(self.defaultClicked)
        self.editButton.clicked.connect(lambda: self.edit.emit())
        self.removeButton.clicked.connect(lambda: self.remove.emit())

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, status):
        self._status = status

        palette = qt.QPalette()
        if self._status == self.OK:
            palette.setColor(qt.QPalette.Foreground, qt.Qt.green)
            self.statusLabel.setPixmap(self.drawStatus(qt.Qt.green))
            self.connectionButton.setText("Disconnect")
            self.connectionButton.setStyleSheet(DISCONNECT_STYLE)
            self.connectionButton.setToolTip(
                "Close the connection. Jobs on this account pause until you connect again."
            )
        else:
            palette.setColor(qt.QPalette.Foreground, qt.Qt.red)
            self.statusLabel.setPixmap(self.drawStatus(qt.Qt.red))
            self.connectionButton.setText("Connect")
            self.connectionButton.setStyleSheet("")
            self.connectionButton.setToolTip("Connect to this account.")

        self.setPalette(palette)

    def _onConnectionClicked(self):
        if self._status == self.OK:
            self.signout.emit()
        else:
            self.signin.emit()

    def drawStatus(self, color):
        size = 11
        pixmap = qt.QPixmap(size, size)
        pixmap.fill(qt.Qt.transparent)
        painter = qt.QPainter(pixmap)
        painter.setRenderHint(qt.QPainter.Antialiasing)
        painter.setBrush(qt.QColor(color))
        painter.drawEllipse(0, 0, size, size)
        return pixmap

    def defaultClicked(self):
        self.set_default.emit()
        self.defaultButton.hide()
        self.defaultLabel.show()

    def defaultOption(self):
        self.defaultButton.show()
        self.defaultLabel.hide()


class AccountsWidget(qt.QWidget):
    def __init__(self, backend, selector, templates=None, parent=None, forJob=False) -> None:
        """
        Args:
            selector: host, send -> None. Called with send=True from the send
                arrow and without it from Connect.
            forJob: whether the list is picking the account a job runs on,
                which gives each row the send arrow.
        """
        super().__init__(parent)

        self.setMinimumWidth(720)
        self.setMinimumHeight(256)

        self.backend = backend
        self.selector = selector
        self.templates = templates
        self.forJob = forJob

        self._setupUI()

    def _setupUI(self) -> None:
        self.outdatedBanner = OutdatedHostsBanner()
        self.accountsListWidget = self._setupAccountsList()

        self.addButton = qt.QPushButton("+ Add new account")

        layout = qt.QVBoxLayout(self)
        layout.addWidget(self.outdatedBanner)
        layout.addWidget(self.accountsListWidget)
        layout.addWidget(self.addButton)

        self.addButton.clicked.connect(self._onAdd)

    def _setupAccountsList(self) -> qt.QListWidget:
        hostListWidget = qt.QListWidget()
        hostListWidget.setSpacing(8)
        return hostListWidget

    def addItem(self, host: Host, status=False) -> None:
        item = qt.QListWidgetItem(self.accountsListWidget)
        item.setData(qt.Qt.UserRole, host)

        widget = AccountListItemWidget(host.name, connected=status, outdated=self._isOutdated(host), forJob=self.forJob)
        item.setSizeHint(widget.sizeHint)
        self.accountsListWidget.setItemWidget(item, widget)

        self._connectItemSignals(item, widget)
        self._refreshOutdatedBanner()

    def _isOutdated(self, host: Host) -> bool:
        return bool(self.backend.is_outdated(host))

    def _refreshOutdatedBanner(self) -> None:
        hosts = [self.accountsListWidget.item(i).data(qt.Qt.UserRole) for i in range(self.accountsListWidget.count)]
        self.outdatedBanner.setHosts([host.name for host in hosts if self._isOutdated(host)])

    def _connectItemSignals(self, item: qt.QListWidgetItem, widget: AccountListItemWidget) -> None:
        widget.signin.connect(partial(self._onSignin, item))
        widget.signout.connect(partial(self._onDisconnect, item))
        widget.send.connect(partial(self._onSend, item))
        widget.set_default.connect(partial(self._onSetDefault, item))
        widget.edit.connect(partial(self._onEdit, item))
        widget.remove.connect(partial(self._onRemove, item))

    def fillList(self, hosts: List[tuple[bool, Host]]) -> None:
        self.accountsListWidget.clear()
        for connected, host in hosts:
            self.addItem(host, status=connected)
        self._refreshOutdatedBanner()

    def _onSignin(self, item: qt.QListWidgetItem):
        data: Host = item.data(qt.Qt.UserRole)
        self.selector(data)

    def _onSend(self, item: qt.QListWidgetItem):
        data: Host = item.data(qt.Qt.UserRole)
        self.selector(data, send=True)

    def _onDisconnect(self, item: qt.QListWidgetItem):
        host: Host = item.data(qt.Qt.UserRole)
        ConnectionManager.disconnect(host)

        widget = self.accountsListWidget.itemWidget(item)
        widget.status = AccountListItemWidget.ERROR

    def _onSetDefault(self, item: qt.QListWidgetItem):
        data: Host = item.data(qt.Qt.UserRole)
        self.backend.default = data
        self.backend.save_targets()

        for i in range(self.accountsListWidget.count):
            item = self.accountsListWidget.item(i)
            widget = self.accountsListWidget.itemWidget(item)
            if widget.defaultAccount:
                widget.defaultOption()
                break

        # dialog = LoginDialog(data, mode=LoginDialog.FIRST_TIME, check_password=self.store, parent=self)
        # if dialog.exec_() == 0:
        #     print('Not Connected')
        #     return

        # print('Successfully Connected')

    def _onEdit(self, item: qt.QListWidgetItem):
        old_host_config: Host = item.data(qt.Qt.UserRole)
        host = RegisterDialog.editing(old_host_config, self)
        if host is None:
            return

        outdated = self._isOutdated(old_host_config)
        self.backend.del_target(old_host_config)
        self.backend.set_target(host)
        if outdated:
            # Editing fills in the new settings from the form, not from the
            # template, so the account still has to be created again.
            self.backend.mark_outdated(host)
        self.backend.save_targets()

        oldWidget = self.accountsListWidget.itemWidget(item)

        newWidget = AccountListItemWidget(
            host.name, connected=ConnectionManager.check_host(host), outdated=outdated, forJob=self.forJob
        )

        item.setSizeHint(newWidget.sizeHint)
        item.setData(qt.Qt.UserRole, host)
        self.accountsListWidget.setItemWidget(item, newWidget)

        del oldWidget

        self._connectItemSignals(item, newWidget)
        self._refreshOutdatedBanner()

    def _onRemove(self, item: qt.QListWidgetItem):
        self.accountsListWidget.takeItem(self.accountsListWidget.row(item))
        self.backend.del_target(item.data(qt.Qt.UserRole))
        self.backend.save_targets()
        self._refreshOutdatedBanner()

    def _onAdd(self):
        host = RegisterDialog.creating(templates=self.templates, parent=self)
        if host is None:
            return

        print("Created", host)
        self.backend.add_target(host)
        self.backend.save_targets()
        self.addItem(host)


class AccountsDialog(qt.QDialog):
    def __init__(self, backend, templates=None, onAccept=None, onReject=None, parent=None, forJob=False) -> None:
        super().__init__(parent)

        def selector(host: Host, send: bool = False):
            onAccept(host, send)
            self.accept()

        self.widget = AccountsWidget(backend, selector, templates, self, forJob=forJob)

        self.setWindowTitle("Choose the account to run the job on" if forJob else "Accounts")
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.widget)
