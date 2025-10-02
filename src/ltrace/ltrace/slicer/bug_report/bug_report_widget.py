import logging
import ctk
import qt

from ltrace.slicer.bug_report.bug_report_model import BugReportModel
from pathlib import Path


class BugReportDialog(qt.QDialog):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setWindowTitle("Generate a bug report")
        self.setMinimumSize(600, 400)

        self.errorDescriptionTextEdit = qt.QPlainTextEdit()

        self.reportDirectoryButton = ctk.ctkDirectoryButton()
        self.reportDirectoryButton.caption = "Select a directory to save the report"

        generateButton = qt.QPushButton("Generate report")
        generateButton.setFixedHeight(40)

        cancelButton = qt.QPushButton("Cancel")
        cancelButton.setFixedHeight(40)

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(generateButton)
        buttonsLayout.addWidget(cancelButton)

        layout = qt.QFormLayout(self)
        layout.setLabelAlignment(qt.Qt.AlignRight)
        layout.addRow("Please describe the problem in the area bellow:", None)
        layout.addRow(self.errorDescriptionTextEdit)
        layout.addRow(" ", None)
        layout.addRow("Report destination directory:", None)
        layout.addRow(self.reportDirectoryButton)
        layout.addRow(" ", None)
        layout.addRow(buttonsLayout)

        generateButton.clicked.connect(self._onGenerateButtonClicked)
        cancelButton.clicked.connect(self._onCloseButtonClicked)

    def _onGenerateButtonClicked(self) -> None:
        reportPath = Path(self.reportDirectoryButton.directory).absolute() / "GeoSlicerBugReport"
        errorDescription = self.errorDescriptionTextEdit.toPlainText()
        generatedFilePath = ""
        try:
            generatedFilePath = BugReportModel.generateBugReport(
                outputPath=reportPath, errorDescription=errorDescription
            )
        except Exception as error:
            logging.error(f"Failed to generate bug report: {error}.")

        htmlMessage = f"Bug report was generated in <b>{generatedFilePath}</b>.<br>Please create a issue in our <a href='https://github.com/petrobras/GeoSlicer/issues/new'>GitHub repository</a> and attach the report file."

        messageBox = qt.QMessageBox(self)
        messageBox.setWindowTitle("Bug report generated")
        messageBox.setIcon(qt.QMessageBox.Information)
        messageBox.setText(htmlMessage)
        openFolderButton = messageBox.addButton("&Open report folder", qt.QMessageBox.ActionRole)
        closeButton = messageBox.addButton("&Close", qt.QMessageBox.RejectRole)
        messageBox.exec_()
        if messageBox.clickedButton() == openFolderButton:
            folder = Path(generatedFilePath).parent
            qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(folder))

        self.errorDescriptionTextEdit.setPlainText("")
        self.close()

    def _onCloseButtonClicked(self) -> None:
        self.close()
