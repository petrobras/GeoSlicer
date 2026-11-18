import slicer
import tempfile
import shutil

from pathlib import Path
from unittest.mock import patch
from commons.slicer_utils import LTracePluginTest
from commons.slicer.tests.utils import wait, check_for_message_box
from commons.slicer.bug_report.bug_report_widget import BugReportDialog


class BugReportTest(LTracePluginTest):
    def post_setup(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.dateTimeSuffix = "16_07_25-16_07_35"
        self.datetimeStrPatcher = patch(
            "commons.slicer.bug_report.bug_report_widget.BugReportModel._getTimeNowAsString",
            return_value=self.dateTimeSuffix,
        )
        self.datetimeStrPatcher.start()

    def tear_down(self):
        self.datetimeStrPatcher.stop()
        shutil.rmtree(self.tmpdir)

    def test_generate_bug_report_usual_logs(self):
        logFile = self.tmpdir / "test.log"
        logFile.touch()

        reportZipFilePath = self.tmpdir / f"GeoSlicerBugReport-{self.dateTimeSuffix}.zip"
        with patch(
            "commons.slicer.bug_report.bug_report_widget.BugReportModel._getRecentLogs", return_value=[str(logFile)]
        ):
            with patch("commons.slicer.bug_report.bug_report_widget.BugReportModel._getTrackingLogs", return_value=[]):
                with check_for_message_box(
                    message=f"Bug report was generated in <b>{str(reportZipFilePath)}</b>", timeout_sec=5
                ):
                    dialog = BugReportDialog(slicer.modules.AppContextInstance.mainWindow)
                    dialog.reportDirectoryButton.directory = str(self.tmpdir)
                    dialog.errorDescriptionTextEdit.setPlainText("Test error")
                    dialog._onGenerateButtonClicked()

        wait(1)
        self.assertTrue(reportZipFilePath.exists())

        shutil.unpack_archive(str(reportZipFilePath), str(self.tmpdir / "output"))

        self.assertTrue((self.tmpdir / "output" / "test.log").exists())
        self.assertEqual((self.tmpdir / "output" / "bug_description.txt").read_text(), "Test error")

    def test_generate_bug_report_tracking_logs(self):
        logFile = self.tmpdir / "test.log"
        logFile.touch()

        reportZipFilePath = self.tmpdir / f"GeoSlicerBugReport-{self.dateTimeSuffix}.zip"
        with patch("commons.slicer.bug_report.bug_report_widget.BugReportModel._getRecentLogs", return_value=[]):
            with patch(
                "commons.slicer.bug_report.bug_report_widget.BugReportModel._getTrackingLogs",
                return_value=[str(logFile)],
            ):
                with check_for_message_box(
                    message=f"Bug report was generated in <b>{reportZipFilePath}</b>", timeout_sec=5
                ):
                    dialog = BugReportDialog(slicer.modules.AppContextInstance.mainWindow)
                    dialog.reportDirectoryButton.directory = str(self.tmpdir)
                    dialog._onGenerateButtonClicked()

        wait(1)
        self.assertTrue(reportZipFilePath.exists())

        shutil.unpack_archive(str(reportZipFilePath), str(self.tmpdir / "output"))

        self.assertTrue((self.tmpdir / "output" / "test.log").exists())
        self.assertEqual((self.tmpdir / "output" / "bug_description.txt").read_text(), "")

    def test_generate_bug_report_no_logs(self):
        reportZipFilePath = self.tmpdir / f"GeoSlicerBugReport-{self.dateTimeSuffix}.zip"
        with patch("commons.slicer.bug_report.bug_report_widget.BugReportModel._getRecentLogs", return_value=[]):
            with patch(
                "commons.slicer.bug_report.bug_report_widget.BugReportModel._getTrackingLogs",
                return_value=[],
            ):
                with check_for_message_box(
                    message=f"Bug report was generated in <b>{reportZipFilePath}</b>", timeout_sec=5
                ):
                    dialog = BugReportDialog(slicer.modules.AppContextInstance.mainWindow)
                    dialog.reportDirectoryButton.directory = str(self.tmpdir)
                    dialog.errorDescriptionTextEdit.setPlainText("Test error")
                    dialog._onGenerateButtonClicked()

        wait(1)
        self.assertTrue(reportZipFilePath.exists())

        shutil.unpack_archive(str(reportZipFilePath), str(self.tmpdir / "output"))

        self.assertFalse((self.tmpdir / "output" / "test.log").exists())
        self.assertEqual((self.tmpdir / "output" / "bug_description.txt").read_text(), "Test error")

    def test_generate_bug_report_file_not_found(self):
        logFile = self.tmpdir / "test.log"

        reportZipFilePath = self.tmpdir / f"GeoSlicerBugReport-{self.dateTimeSuffix}.zip"
        with patch(
            "commons.slicer.bug_report.bug_report_widget.BugReportModel._getRecentLogs", return_value=[str(logFile)]
        ):
            with patch("commons.slicer.bug_report.bug_report_widget.BugReportModel._getTrackingLogs", return_value=[]):
                with check_for_message_box(
                    message=f"Bug report was generated in <b>{reportZipFilePath}</b>", timeout_sec=5
                ):
                    dialog = BugReportDialog(slicer.modules.AppContextInstance.mainWindow)
                    dialog.reportDirectoryButton.directory = str(self.tmpdir)
                    dialog.errorDescriptionTextEdit.setPlainText("Test error")
                    dialog._onGenerateButtonClicked()

        wait(1)
        self.assertTrue(reportZipFilePath.exists())

        shutil.unpack_archive(str(reportZipFilePath), str(self.tmpdir / "output"))

        self.assertFalse((self.tmpdir / "output" / "test.log").exists())
        self.assertEqual((self.tmpdir / "output" / "bug_description.txt").read_text(), "Test error")
