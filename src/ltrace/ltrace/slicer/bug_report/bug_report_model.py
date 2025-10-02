import logging
import slicer
import shutil

from datetime import datetime
from pathlib import Path


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
