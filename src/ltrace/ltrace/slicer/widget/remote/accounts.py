from functools import partial
from typing import List, Callable

import qt

from ltrace.remote.targets import Host

from ltrace.slicer.widget.remote.register import RegisterDialog


class AccountListItemWidget(qt.QWidget):
    signin = qt.Signal()
    set_default = qt.Signal()
    edit = qt.Signal()
    remove = qt.Signal()

    OK = 1
    ERROR = 0

    def __init__(self, text, connected=False, defaultAccount=False, parent=None) -> None:
        super().__init__(parent)

        self.text = text
        self.defaultAccount = defaultAccount

        self._setupUI()

        # Note: keep after UI setup, this is a property
        self.status = self.ERROR if not connected else self.OK

    def _setupUI(self) -> None:
        self.statusLabel = qt.QLabel()

        self.hostLabel = qt.QLabel(self.text)

        self.connectButton = qt.QPushButton("Connect")
        self.defaultButton = qt.QPushButton("Set as default")
        self.editButton = qt.QPushButton("Edit")
        self.removeButton = qt.QPushButton("Remove")

        self.defaultLabel = qt.QLabel("(default)")

        self.defaultOption()

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.setSpacing(8)
        buttonsLayout.addWidget(self.connectButton)
        buttonsLayout.addWidget(self.defaultButton)
        buttonsLayout.addWidget(self.editButton)
        buttonsLayout.addWidget(self.removeButton)

        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self.statusLabel)
        layout.addWidget(self.hostLabel)
        layout.addStretch(1)
        layout.addWidget(self.defaultLabel)
        layout.addLayout(buttonsLayout)

        self.connectButton.clicked.connect(lambda: self.signin.emit())
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
        else:
            palette.setColor(qt.QPalette.Foreground, qt.Qt.red)
            self.statusLabel.setPixmap(self.drawStatus(qt.Qt.red))

        self.setPalette(palette)

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
    def __init__(self, backend, selector, templates=None, parent=None) -> None:
        super().__init__(parent)

        self.setMinimumWidth(720)
        self.setMinimumHeight(256)

        self.backend = backend
        self.selector = selector
        self.templates = templates

        self._setupUI()

    def _setupUI(self) -> None:
        self.accountsListWidget = self._setupAccountsList()

        self.addButton = qt.QPushButton("+ Add new account")

        layout = qt.QVBoxLayout(self)
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

        widget = AccountListItemWidget(host.name, connected=status)
        item.setSizeHint(widget.sizeHint)
        self.accountsListWidget.setItemWidget(item, widget)

        widget.signin.connect(partial(self._onSignin, item))
        widget.set_default.connect(partial(self._onSetDefault, item))
        widget.edit.connect(partial(self._onEdit, item))
        widget.remove.connect(partial(self._onRemove, item))

    def fillList(self, hosts: List[tuple[bool, Host]]) -> None:
        self.accountsListWidget.clear()
        for connected, host in hosts:
            self.addItem(host, status=connected)

    def _onSignin(self, item: qt.QListWidgetItem):
        data: Host = item.data(qt.Qt.UserRole)
        self.selector(data)

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

        self.backend.del_target(old_host_config)
        self.backend.set_target(host)
        self.backend.save_targets()

        oldWidget = self.accountsListWidget.itemWidget(item)

        newWidget = AccountListItemWidget(host.name)

        item.setSizeHint(newWidget.sizeHint)
        item.setData(qt.Qt.UserRole, host)
        self.accountsListWidget.setItemWidget(item, newWidget)

        del oldWidget

        newWidget.signin.connect(partial(self._onSignin, item))
        newWidget.edit.connect(partial(self._onEdit, item))
        newWidget.remove.connect(partial(self._onRemove, item))

    def _onRemove(self, item: qt.QListWidgetItem):
        self.accountsListWidget.takeItem(self.accountsListWidget.row(item))
        self.backend.del_target(item.data(qt.Qt.UserRole))
        self.backend.save_targets()

    def _onAdd(self):
        host = RegisterDialog.creating(templates=self.templates, parent=self)
        if host is None:
            return

        print("Created", host)
        self.backend.add_target(host)
        self.backend.save_targets()
        self.addItem(host)


class AccountsDialog(qt.QDialog):
    def __init__(self, backend, templates=None, onAccept=None, onReject=None, parent=None) -> None:
        super().__init__(parent)

        def selector(host: Host):
            onAccept(host)
            self.accept()

        self.widget = AccountsWidget(backend, selector, templates, self)

        self.setWindowTitle("Accounts")
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.widget)
