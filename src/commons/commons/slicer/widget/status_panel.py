import qt


class StatusPanel(qt.QGroupBox):
    def __init__(self, panel_name, defaultStatus=""):
        super().__init__(panel_name)

        self.defaultStatus = defaultStatus

        statusFrame = qt.QFrame()
        statusForm = qt.QVBoxLayout(statusFrame)
        self.statusLabel = qt.QLabel()
        self.unset_instruction()
        self.statusLabel.setAlignment(qt.Qt.AlignCenter)
        statusForm.addWidget(self.statusLabel)
        self.setLayout(statusForm)

    def unset_instruction(self):
        self.set_instruction(self.defaultStatus)

    def set_instruction(self, message=None, important=False):
        if important:
            style = "font-size: 14pt; font-weight: bold; color: red"
        else:
            style = "font-size: 14pt; font-weight: bold"
        self.statusLabel.setStyleSheet(style)
        self.statusLabel.setText(message)
