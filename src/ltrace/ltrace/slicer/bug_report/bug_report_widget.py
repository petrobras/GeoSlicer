import logging
import ctk
import qt
import slicer
import shutil

from datetime import datetime
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
        cancelButton.clicked.connect(self.close)

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

        htmlMessage = f"Bug report was generated in <b>{generatedFilePath}</b>.<br>Please send this file to <a href='mailto:contact@ltrace.com.br'>contact@ltrace.com.br</a>."

        messageBox = qt.QMessageBox(self)
        messageBox.setWindowTitle("Bug report generated")
        messageBox.setIcon(qt.QMessageBox.Information)
        messageBox.setText(htmlMessage)
        openFolderButton = messageBox.addButton("&Open report folder", qt.QMessageBox.ActionRole)
        closeButton = messageBox.addButton("&Close", qt.QMessageBox.AcceptRole)
        messageBox.exec_()
        if messageBox.clickedButton() == openFolderButton:
            folder = Path(generatedFilePath).parent
            qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(folder))

        self.errorDescriptionTextEdit.setPlainText("")
        self.close()


class BugReportModel:
    def __init__(self) -> None:
        pass

    @staticmethod
    def _getTrackingLogs() -> list[Path]:
        trackingManager = slicer.modules.AppContextInstance.getTracker()
        return trackingManager.getRecentLogs() if trackingManager else []

    @staticmethod
    def _getRecentLogs() -> list[Path]:
        logFilePaths = [Path(file) for file in list(slicer.app.recentLogFiles())]
        files = [file for file in logFilePaths if file.exists()]
        return files

    @staticmethod
    def _getTimeNowAsString() -> str:
        return datetime.now().strftime("%m_%d_%Y-%H_%M_%S")

    @staticmethod
    def generateBugReport(outputPath: Path, errorDescription: str) -> str:
        """Generate a bug report

        Args:
            outputPath (Path): the path to save the bug report
            errorDescription (str): the error description

        Returns:
            str: the generated filepath
        """
        outputPath.mkdir(parents=True, exist_ok=True)
        geoslicerLogFiles = BugReportModel._getRecentLogs()
        trackingLogFiles = BugReportModel._getTrackingLogs()

        nowString = BugReportModel._getTimeNowAsString()
        compresseFilePath = outputPath.parent / f"{outputPath.stem}-{nowString}"
        for file in geoslicerLogFiles + trackingLogFiles:
            try:
                shutil.copy2(file, str(outputPath))
            except FileNotFoundError:
                logging.debug(f"Unable to copy the file '{file}'. File not found.")

        Path(outputPath / "bug_description.txt").write_text(errorDescription)
        generatedFilePath = shutil.make_archive(compresseFilePath, "zip", outputPath)

        try:
            shutil.rmtree(str(outputPath))
        except OSError as e:
            # If for some reason can't delete the directory
            pass

        return generatedFilePath
