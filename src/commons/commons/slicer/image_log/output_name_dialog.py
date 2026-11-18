import qt


class OutputNameDialog(qt.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("DLIS output name")
        self.setFixedSize(200, 60)

        formLayout = qt.QFormLayout()
        self.newPlotWidgetLineEdit = qt.QLineEdit()
        formLayout.addRow("File name", self.newPlotWidgetLineEdit)

        okButton = qt.QPushButton("OK")
        cancelButton = qt.QPushButton("Cancel")

        okButton.clicked.connect(lambda checked: self.okButtonClicked())
        cancelButton.clicked.connect(lambda checked: self.reject())

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(okButton)
        buttonsLayout.addWidget(cancelButton)
        formLayout.addRow(buttonsLayout)
        formLayout.setVerticalSpacing(10)

        self.setLayout(formLayout)

    def showPopup(self, message):
        qt.QMessageBox.warning(self, "Error", message)

    def okButtonClicked(self):
        newPlotLabel = self.newPlotWidgetLineEdit.text
        if newPlotLabel == "":
            self.showPopup("File name cannot be empty")
            return

        self.accept()

    def getOutputName(self):
        return self.newPlotWidgetLineEdit.text
