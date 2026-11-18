import json
import logging
import tempfile

from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

from commons.slicer.tests.constants import TestState
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.ltrace_tests_model import LTraceTestsModel, TestSuiteData
from commons.slicer.tests.utils import TemporaryFolderLogHandler


class LTraceModelTestTest(LTracePluginTest):
    def test_check_missing_test_suites_logic(self):
        """Verifies that check_missing_test_suites correctly identifies missing suites and logs a warning."""
        with patch("logging.warning") as mock_warning:
            with patch.object(Path, "exists", return_value=True):
                with patch.object(Path, "glob") as mock_glob:
                    mock_file_existing = MagicMock(spec=Path)
                    mock_file_existing.stem = "ExistingTest"
                    mock_file_missing = MagicMock(spec=Path)
                    mock_file_missing.stem = "MissingTest"
                    mock_glob.return_value = [mock_file_existing, mock_file_missing]

                    with patch.object(LTraceTestsModel, "_LTraceTestsModel__get_all_suites", return_value=([], [])):
                        model = LTraceTestsModel()
                        mock_warning.reset_mock()
                        mock_suite = MagicMock(spec=TestSuiteData)
                        mock_suite.name = "ExistingTest"

                        with patch.object(LTraceTestsModel, "test_suite_list", new_callable=PropertyMock) as mock_list:
                            mock_list.return_value = [mock_suite]

                            model.check_missing_test_suites()

                            # Verify warning was logged with the missing suite name
                            mock_warning.assert_called_once()
                            warning_msg = mock_warning.call_args[0][0]
                            self.assertIn("MissingTest", warning_msg)
                            self.assertNotIn("ExistingTest", warning_msg)

    def test_check_missing_test_suites_all_present(self):
        """Verifies that no warning is logged if all test suites on disk are successfully imported."""
        with patch("logging.warning") as mock_warning:
            with patch.object(Path, "exists", return_value=True):
                with patch.object(Path, "glob") as mock_glob:
                    mock_file = MagicMock(spec=Path)
                    mock_file.stem = "SomeTest"
                    mock_glob.return_value = [mock_file]

                    with patch.object(LTraceTestsModel, "_LTraceTestsModel__get_all_suites", return_value=([], [])):
                        model = LTraceTestsModel()
                        mock_warning.reset_mock()

                        mock_suite = MagicMock(spec=TestSuiteData)
                        mock_suite.name = "SomeTest"

                        with patch.object(LTraceTestsModel, "test_suite_list", new_callable=PropertyMock) as mock_list:
                            mock_list.return_value = [mock_suite]
                            model.check_missing_test_suites()
                            mock_warning.assert_not_called()

    def test_tests_log_in_temporary_path_set_after_creation(self):
        """The tests logger is created on import, before slicerrc moves the temporary folder out of the installation.
        The log must be written to the temporary folder current when the tests run."""
        tmpDir = Path(tempfile.mkdtemp())
        oldTemporaryPath = tmpDir / "old"
        newTemporaryPath = tmpDir / "new"
        oldTemporaryPath.mkdir()
        logger = logging.getLogger("test_tests_log_in_temporary_path_set_after_creation")
        logger.propagate = False

        with patch("commons.slicer.tests.utils.slicer") as mockSlicer:
            mockSlicer.app.temporaryPath = str(oldTemporaryPath)
            handler = TemporaryFolderLogHandler()
            logger.addHandler(handler)
            try:
                mockSlicer.app.temporaryPath = str(newTemporaryPath)
                logger.warning("Tested")
            finally:
                logger.removeHandler(handler)
                handler.close()

        logs = list(newTemporaryPath.glob("tests_*.log"))
        assert len(logs) == 1 and "Tested" in logs[0].read_text(), f"Unexpected logs: {logs}"
        assert not list(oldTemporaryPath.iterdir())

    def test_status_file_in_temporary_path_set_after_import(self):
        """The tests model is imported before slicerrc moves the temporary folder out of the installation. The status
        file must be written to the temporary folder current when the tests finish."""
        temporaryPath = Path(tempfile.mkdtemp())
        model = MagicMock(spec=LTraceTestsModel)
        model.result.return_value = TestState.SUCCEED
        model.test_suite_list = []

        with patch("commons.slicer.tests.ltrace_tests_model.slicer") as mockSlicer:
            mockSlicer.app.temporaryPath = str(temporaryPath)
            LTraceTestsModel.create_test_status_file(model)

        status = json.loads((temporaryPath / "test_status.json").read_text())
        assert status["status"] == TestState.SUCCEED.value, f"Unexpected status: {status}"
