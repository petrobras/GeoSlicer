import qt


class PasswordEdit(qt.QLineEdit):
    def __init__(self, show_visibility=True, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.visibleIcon = qt.QIcon("./eye.svg")
        self.hiddenIcon = qt.QIcon("./hidden.svg")

        self.setEchoMode(qt.QLineEdit.Password)

        if show_visibility:
            # Add the password hide/shown toggle at the end of the edit box.
            self.togglepasswordAction = self.addAction(self.visibleIcon, qt.QLineEdit.TrailingPosition)
            self.togglepasswordAction.triggered.connect(self.on_toggle_password_Action)

        self.password_shown = False

    def on_toggle_password_Action(self):
        if not self.password_shown:
            self.setEchoMode(qt.QLineEdit.Normal)
            self.password_shown = True
            self.togglepasswordAction.setIcon(self.hiddenIcon)
        else:
            self.setEchoMode(qt.QLineEdit.Password)
            self.password_shown = False
            self.togglepasswordAction.setIcon(self.visibleIcon)
