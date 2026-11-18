import slicer
import qt
import time

from commons.slicer_utils import LTracePluginTest
from commons.slicer.tests.constants import TestState
from commons.slicer.tests.test_case import TestCase
from commons.slicer.tests.utils import wait, check_for_message_box, wait_cli_to_finish
from unittest.mock import patch, MagicMock


class LTracePluginTestTest(LTracePluginTest):
    GLOBAL_TIMEOUT_MS = 45000

    def test_timeout_from_test_case(self) -> None:
        """Create a test environment to test the case in which a message box freezes and the fallback system fails the test case"""

        def test_case_function(cls: LTracePluginTest, timeout_ms: int = 1000) -> None:
            # Testing test case timeout_ms logic
            msg_box = qt.QMessageBox(slicer.modules.AppContextInstance.mainWindow)
            msg_box.setText("Test")
            msg_box.exec_()

        fake_test_case = TestCase(function=test_case_function, cls=None)
        mock_get_methods = MagicMock()

        mock_get_methods.side_effect = [
            [fake_test_case],
            [],
        ]  # first is for the test cases, second is for the generate methods

        @patch("commons.slicer.tests.ltrace_plugin_test.log", MagicMock())
        @patch("slicer.util.getNewModuleWidget", lambda x: MagicMock())
        @patch(
            "commons.slicer.tests.ltrace_plugin_test.LTracePluginTest._LTracePluginTest__get_methods", mock_get_methods
        )
        @patch("commons.slicer.tests.ltrace_plugin_test.LTracePluginTest.GLOBAL_TIMEOUT_MS", 10000)
        def fake_test_environment():
            fake_plugin_test = LTracePluginTest()
            fake_test_case.test_module_class = fake_plugin_test
            fake_plugin_test.runTest()

        start = time.perf_counter()
        fake_test_environment()
        end = time.perf_counter()

        assert fake_test_case.status == TestState.FAILED
        assert "Test case timeout reached! Please check the test case logic" in fake_test_case.reason, (
            f"Expected the expected message box's exception to be triggered. Got: {fake_test_case.reason}"
        )
        assert end - start < 30, "Expected the message box to freeze the operation for less than 30 seconds"

    def test_timeout_from_test_suite(self) -> None:
        """Create a test environment to test the case in which a message box freezes and the fallback system fails the test case"""

        def test_case_function(cls: LTracePluginTest) -> None:
            # Testing test case without timeout_ms logic
            msg_box = qt.QMessageBox(slicer.modules.AppContextInstance.mainWindow)
            msg_box.setText("Test2")
            msg_box.exec_()

        fake_test_case = TestCase(function=test_case_function, cls=None)
        mock_get_methods = MagicMock()

        mock_get_methods.side_effect = [
            [fake_test_case],
            [],
        ]  # first is for the test cases, second is for the generate methods

        @patch("commons.slicer.tests.ltrace_plugin_test.log", MagicMock())
        @patch("slicer.util.getNewModuleWidget", lambda x: MagicMock())
        @patch(
            "commons.slicer.tests.ltrace_plugin_test.LTracePluginTest._LTracePluginTest__get_methods", mock_get_methods
        )
        @patch("commons.slicer.tests.ltrace_plugin_test.LTracePluginTest.GLOBAL_TIMEOUT_MS", 2000)
        def fake_test_environment() -> None:
            fake_plugin_test = LTracePluginTest()
            fake_test_case.test_module_class = fake_plugin_test
            fake_plugin_test.runTest()

        start = time.perf_counter()
        fake_test_environment()
        end = time.perf_counter()

        assert fake_test_case.status == TestState.FAILED
        assert "Test case timeout reached! Please check the test case logic" in fake_test_case.reason, (
            f"Expected the expected message box's exception to be triggered. Got: {fake_test_case.reason}"
        )
        assert end - start < 30, "Expected the message box to freeze the operation for less than 30 seconds"

    def test_handling_expected_message_box(self) -> None:
        with check_for_message_box("Test Message Box", timeout_sec=5):
            msg_box = qt.QMessageBox(slicer.modules.AppContextInstance.mainWindow)
            msg_box.setText("Test Message Box")
            msg_box.exec_()

    def test_not_finding_expected_message_box(self) -> None:
        try:
            with check_for_message_box("Test Message Box", timeout_sec=2):
                wait(3)

        except AttributeError:
            pass
        else:
            raise Exception("Expected the expected message box's exception to be triggered")

    def test_timeout_from_wait_cli_to_finish(self) -> None:
        """Create a test environment to test the case in which a CLI is running until its timeout."""

        mock_cli_node = MagicMock()
        mock_cli_node.IsBusy.return_value = True

        def test_case_function(cls: LTracePluginTest) -> None:
            # Testing test case without timeout_ms logic
            wait_cli_to_finish(cli_entity=mock_cli_node, timeout_sec=2)

        fake_test_case = TestCase(function=test_case_function, cls=None)
        mock_get_methods = MagicMock()

        mock_get_methods.side_effect = [
            [fake_test_case],
            [],
        ]  # first is for the test cases, second is for the generate methods

        @patch("commons.slicer.tests.ltrace_plugin_test.log", MagicMock())
        @patch("slicer.util.getNewModuleWidget", lambda x: MagicMock())
        @patch(
            "commons.slicer.tests.ltrace_plugin_test.LTracePluginTest._LTracePluginTest__get_methods", mock_get_methods
        )
        @patch("commons.slicer.tests.ltrace_plugin_test.LTracePluginTest.GLOBAL_TIMEOUT_MS", 30000)
        def fake_test_environment() -> None:
            fake_plugin_test = LTracePluginTest()
            fake_test_case.test_module_class = fake_plugin_test
            fake_plugin_test.runTest()

        fake_test_environment()

        assert fake_test_case.status == TestState.FAILED
        assert "CLI timeout reached!" in fake_test_case.reason
        assert mock_cli_node.Cancel.call_count == 1
        # assert end - start < 30, f"The process took {end - start} seconds, expected less than 30 seconds"

    def test_global_timeout_priority_over_wait_cli_to_finish(self) -> None:
        """Create a test environment to test the case in which a CLI is running until its timeout,
        even though the test suite/case timeout had already triggered."""

        mock_cli_node = MagicMock()
        mock_cli_node.IsBusy.return_value = True

        def test_case_function(cls: LTracePluginTest) -> None:
            # Testing test case without timeout_ms logic
            wait_cli_to_finish(cli_entity=mock_cli_node, timeout_sec=8)

        fake_test_case = TestCase(function=test_case_function, cls=None)
        mock_get_methods = MagicMock()

        mock_get_methods.side_effect = [
            [fake_test_case],
            [],
        ]  # first is for the test cases, second is for the generate methods

        @patch("commons.slicer.tests.ltrace_plugin_test.log", MagicMock())
        @patch("slicer.util.getNewModuleWidget", lambda x: MagicMock())
        @patch(
            "commons.slicer.tests.ltrace_plugin_test.LTracePluginTest._LTracePluginTest__get_methods", mock_get_methods
        )
        @patch("commons.slicer.tests.ltrace_plugin_test.LTracePluginTest.GLOBAL_TIMEOUT_MS", 2000)
        def fake_test_environment() -> None:
            fake_plugin_test = LTracePluginTest()
            fake_test_case.test_module_class = fake_plugin_test
            fake_plugin_test.runTest()

        fake_test_environment()

        assert fake_test_case.status == TestState.FAILED
        assert "Test timeout reached!" in fake_test_case.reason, (
            f"Expected the reason to be 'Test timeout reached!'. Got: {fake_test_case.reason}"
        )
        assert mock_cli_node.Cancel.call_count == 1, (
            f"Expected the Cancel method from CLI Node to be called once, but it got called {mock_cli_node.Cancel.call_count} times"
        )
        # assert end - start < 8, f"The process took {end - start} seconds, expected less than 10 seconds"

    def test_timeout_during_wait(self) -> None:
        """Create a test environment to test the case in which a wait statement runs until the test timeout"""

        def test_case_function(cls: LTracePluginTest) -> None:
            # Testing test case without timeout_ms logic
            wait(8)

        fake_test_case = TestCase(function=test_case_function, cls=None)
        mock_get_methods = MagicMock()

        mock_get_methods.side_effect = [
            [fake_test_case],
            [],
        ]  # first is for the test cases, second is for the generate methods

        @patch("commons.slicer.tests.ltrace_plugin_test.log", MagicMock())
        @patch("slicer.util.getNewModuleWidget", lambda x: MagicMock())
        @patch(
            "commons.slicer.tests.ltrace_plugin_test.LTracePluginTest._LTracePluginTest__get_methods", mock_get_methods
        )
        @patch("commons.slicer.tests.ltrace_plugin_test.LTracePluginTest.GLOBAL_TIMEOUT_MS", 2000)
        def fake_test_environment() -> None:
            fake_plugin_test = LTracePluginTest()
            fake_test_case.test_module_class = fake_plugin_test
            fake_plugin_test.runTest()

        fake_test_environment()

        assert fake_test_case.status == TestState.FAILED
        assert "Test timeout reached!" in fake_test_case.reason, (
            f"Expected the reason to be 'Test timeout reached!'. Got: {fake_test_case.reason}"
        )
        # assert end - start < 8, f"The process took {end - start} seconds, expected less than 10 seconds"

    def test_suite_hooks_run_once_around_all_test_cases(self) -> None:
        """Suite hooks must run once, before the first and after the last test case, while the per-case hooks run
        for each test case."""

        calls = []

        def make_case(name: str) -> TestCase:
            def test_case_function(cls: LTracePluginTest) -> None:
                calls.append(name)

            return TestCase(function=test_case_function, cls=None)

        fake_test_cases = [make_case("case_1"), make_case("case_2")]
        mock_get_methods = MagicMock()
        mock_get_methods.side_effect = [fake_test_cases, []]

        class HooksTest(LTracePluginTest):
            def suite_setup(self) -> None:
                calls.append("suite_setup")

            def suite_tear_down(self) -> None:
                calls.append("suite_tear_down")

            def pre_setup(self) -> None:
                calls.append("pre_setup")

            def post_setup(self) -> None:
                calls.append("post_setup")

            def tear_down(self) -> None:
                calls.append("tear_down")

        @patch("commons.slicer.tests.ltrace_plugin_test.log", MagicMock())
        @patch("commons.slicer.tests.ltrace_plugin_test.widgetsIdentificationModule", MagicMock())
        @patch("slicer.util.getNewModuleWidget", lambda x: MagicMock())
        @patch(
            "commons.slicer.tests.ltrace_plugin_test.LTracePluginTest._LTracePluginTest__get_methods", mock_get_methods
        )
        def fake_test_environment() -> None:
            fake_plugin_test = HooksTest()
            for fake_test_case in fake_test_cases:
                fake_test_case.test_module_class = fake_plugin_test
            fake_plugin_test.runTest()

        fake_test_environment()

        assert calls.count("suite_setup") == 1, f"Expected suite_setup to run once. Got: {calls}"
        assert calls.count("suite_tear_down") == 1, f"Expected suite_tear_down to run once. Got: {calls}"
        assert calls[0] == "suite_setup", f"Expected suite_setup to run first. Got: {calls}"
        assert calls[-1] == "suite_tear_down", f"Expected suite_tear_down to run last. Got: {calls}"
        assert calls.count("pre_setup") == 2, f"Expected pre_setup to run for each test case. Got: {calls}"
        assert calls.count("post_setup") == 2, f"Expected post_setup to run for each test case. Got: {calls}"
        assert calls.count("tear_down") == 2, f"Expected tear_down to run for each test case. Got: {calls}"
        per_case_calls = calls[1:-1]
        for start in range(0, len(per_case_calls), 4):
            pre_setup, post_setup, case, tear_down = per_case_calls[start : start + 4]
            assert (pre_setup, post_setup, tear_down) == ("pre_setup", "post_setup", "tear_down")
            assert case.startswith("case_"), f"Expected the test case between post_setup and tear_down. Got: {calls}"
        assert sorted(name for name in calls if name.startswith("case_")) == ["case_1", "case_2"]

    def test_suite_hooks_failure_does_not_abort_suite(self) -> None:
        """A failing suite hook must be reported as a warning, and must not prevent the suite tear down."""

        calls = []

        def test_case_function(cls: LTracePluginTest) -> None:
            calls.append("case")

        fake_test_case = TestCase(function=test_case_function, cls=None)
        mock_get_methods = MagicMock()
        mock_get_methods.side_effect = [[fake_test_case], []]

        class FailingHooksTest(LTracePluginTest):
            def suite_setup(self) -> None:
                raise RuntimeError("suite setup boom")

            def suite_tear_down(self) -> None:
                calls.append("suite_tear_down")
                raise RuntimeError("suite tear down boom")

        holder = {}

        @patch("commons.slicer.tests.ltrace_plugin_test.log", MagicMock())
        @patch("slicer.util.getNewModuleWidget", lambda x: MagicMock())
        @patch(
            "commons.slicer.tests.ltrace_plugin_test.LTracePluginTest._LTracePluginTest__get_methods", mock_get_methods
        )
        def fake_test_environment() -> None:
            fake_plugin_test = FailingHooksTest()
            fake_test_case.test_module_class = fake_plugin_test
            holder["suite"] = fake_plugin_test
            fake_plugin_test.runTest()

        fake_test_environment()

        assert calls == ["case", "suite_tear_down"], f"Expected the test case and the suite tear down. Got: {calls}"
        warnings_text = "\n".join(str(warning) for warning in holder["suite"].warnings)
        assert "suite setup boom" in warnings_text, f"Missing suite_setup warning. Got: {warnings_text}"
        assert "suite tear down boom" in warnings_text, f"Missing suite_tear_down warning. Got: {warnings_text}"

    def test_generate_cases_failing(self) -> None:
        def test_case_function(cls: LTracePluginTest) -> None:
            raise RuntimeError("Should fail")

        fake_generate_case = TestCase(function=test_case_function, cls=None)
        mock_get_methods = MagicMock()

        mock_get_methods.side_effect = [
            [],
            [fake_generate_case],
        ]  # first is for the test cases, second is for the generate methods

        mock_log = MagicMock()

        @patch("commons.slicer.tests.ltrace_plugin_test.log", mock_log)
        @patch("slicer.util.getNewModuleWidget", lambda x: MagicMock())
        @patch(
            "commons.slicer.tests.ltrace_plugin_test.LTracePluginTest._LTracePluginTest__get_methods", mock_get_methods
        )
        def fake_test_environment() -> None:
            class GenerateTest(LTracePluginTest):
                pass

            fake_plugin_test = GenerateTest(show_overview=True)
            fake_generate_case.test_module_class = fake_plugin_test
            fake_plugin_test.runTest()

        fake_test_environment()
        assert fake_generate_case.status == TestState.FAILED
        assert ("Errors from GenerateTest test suite:") in mock_log.call_args_list[5][0][0], (
            f"Log not available in: {mock_log.call_args_list}'."
        )
