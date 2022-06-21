from typing import List, Callable

import qt
import logging

from ltrace.slicer.widget import PasswordEdit
from ltrace.remote.connections import ConnectionManager
from ltrace.remote.targets import Host

from ltrace.remote.errors import *


class LoginDialog(qt.QDialog):
    WRONG_PASSWORD = 1

    def __init__(self, host: Host, parent=None) -> None:
        super().__init__(parent)

        self.host = host
        self.output = None

        self.msgtext = "Please, enter your password to login"

        self.setMinimumWidth(400)
        # self.setMaximumHeight(128)

        self.setWindowTitle(f"Connect to {host.name}")
        self._setupUI()

    def _setupUI(self) -> None:
        self.message = qt.QLabel(self.msgtext)
        self.message.setWordWrap(True)

        self.displayField = qt.QLabel(self.host.server_name())

        self.usernameField = qt.QLabel(self.host.username)

        self.passwordField = PasswordEdit()
        self.passwordField.setPlaceholderText("**********")

        password = self.host.get_password()
        if password:
            self.passwordField.setText(password)
        del password

        formLayout = qt.QFormLayout()
        formLayout.addRow("Server: ", self.displayField)
        formLayout.addRow("Username: ", self.usernameField)
        formLayout.addRow("Password: ", self.passwordField)

        layout = qt.QVBoxLayout(self)
        layout.addWidget(self.message)
        layout.addLayout(formLayout)
        layout.addLayout(self._setupButons())

    def _setupButons(self) -> None:
        layout = qt.QHBoxLayout()
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addStretch(1)

        self.acceptButton = qt.QPushButton("Connect")
        self.acceptButton.clicked.connect(self._enterPassword)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.clicked.connect(self._cancel)

        # TODO switch based on OS
        layout.addWidget(self.acceptButton)
        layout.addWidget(self.cancelButton)

        return layout

    def reset(self):
        self.msgtext = "Wrong password, please try again or check your credentials."
        self.passwordField.text = ""
        self.message.setText(self.msgtext)
        self.message.setStyleSheet("QLabel { color: red; }")

    def _cancel(self):
        self.reject()

    def _enterPassword(self):
        self.host.set_password(self.passwordField.text)
        try:
            output = ConnectionManager.connect(self.host)
            self.output = output
            self.accept()
        except AuthException:
            self.mode = self.WRONG_PASSWORD
            self.reset()
        except Exception as e:
            logging.warning(f"Could not handle this error {repr(e)}.")
            raise
