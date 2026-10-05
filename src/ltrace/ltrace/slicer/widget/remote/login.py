from typing import List, Callable

import qt
import logging

from ltrace.slicer.widget import PasswordEdit
from ltrace.slicer.widget.remote import connecting
from ltrace.slicer.widget.remote.outdated import OutdatedHostsBanner
from ltrace.remote.targets import Host, TargetManager

from ltrace.remote.errors import *


class LoginDialog(qt.QDialog):
    WRONG_PASSWORD = 1

    def __init__(self, host: Host, parent=None) -> None:
        super().__init__(parent)

        self.host = host
        self.output = None
        # A connection failure this dialog cannot fix, kept for the caller to
        # report. None means either success or a plain cancel.
        self.error = None

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

        self.outdatedBanner = OutdatedHostsBanner()
        self.outdatedBanner.setHosts([self.host.name] if TargetManager.is_outdated(self.host) else [])

        layout = qt.QVBoxLayout(self)
        layout.addWidget(self.outdatedBanner)
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
        self.passwordField.text = ""
        self.__warn("Wrong password, please try again or check your credentials.")

    def __warn(self, text: str) -> None:
        self.msgtext = text
        self.message.setText(text)
        self.message.setStyleSheet("QLabel { color: red; }")

    def _cancel(self):
        self.reject()

    def _enterPassword(self):
        try:
            if not self.passwordField.text:
                self.__warn("Please, enter your password to login.")
                return

            previous = self.host.get_password()
            self.host.set_password(self.passwordField.text)

            connected = connecting.connect(self.host, parent=self)
            if connected is None:
                # Cancelled while connecting: back to the password, with the
                # credential as it was before this attempt.
                self.__forgetPassword(previous)
                return

            self.output = connected
            self.accept()

        except AuthException:
            # dont close the dialog yet. let the user try a new password
            self.reset()
        except Exception as error:
            logging.warning(f"Could not connect to {self.host.server_name()}. Cause: {repr(error)}")
            self.__forgetPassword(previous)
            self.error = error
            self.reject()

    def __forgetPassword(self, previous) -> None:
        """Undo the keyring write made for an attempt that never connected.

        connect() reads the credential from the keyring, so a typed password
        has to be stored before it can be tried. One the server never confirmed
        must not be left behind as if it had been.
        """
        try:
            # A non-string is the "no password needed, an identity file is
            # configured" sentinel: nothing was stored to put back.
            if isinstance(previous, str) and previous:
                self.host.set_password(previous)
            else:
                self.host.delete_password()
        except Exception as error:
            logging.warning(f"Failed to restore the credential for {self.host.server_name()}. Cause: {repr(error)}")
