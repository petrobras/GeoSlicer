import qt

from ltrace.slicer_utils import getResourcePath


class RenameDialog(qt.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("Rename Volume")

        self.newPlotWidgetLineEdit = qt.QLineEdit()

        okButton = qt.QPushButton("OK")
        okButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Apply.png"))
        okButton.setIconSize(qt.QSize(12, 14))

        cancelButton = qt.QPushButton("Cancel")
        cancelButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Cancel.png"))
        cancelButton.setIconSize(qt.QSize(12, 14))

        okButton.clicked.connect(lambda checked: self.okButtonClicked())
        cancelButton.clicked.connect(lambda checked: self.reject())

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(okButton)
        buttonsLayout.addWidget(cancelButton)

        formLayout = qt.QFormLayout()
        formLayout.addRow("New name:", self.newPlotWidgetLineEdit)
        formLayout.addRow(buttonsLayout)
        formLayout.setVerticalSpacing(10)

        self.setLayout(formLayout)

    def showPopup(self, message):
        qt.QMessageBox.warning(self, "Error", message)

    def okButtonClicked(self):
        newPlotLabel = self.newPlotWidgetLineEdit.text

        if newPlotLabel == "":
            self.showPopup("Volume name cannot be empty")
            return

        self.accept()

    def getOutputName(self):
        return self.newPlotWidgetLineEdit.text

    def setOutputName(self, name):
        self.newPlotWidgetLineEdit.text = name
