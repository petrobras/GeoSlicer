import json
import importlib
import inspect
import logging
import gc
import qt
import random
import slicer
import traceback
import os
import json

from enum import Enum
from ltrace.slicer.tests.caveat import Caveat
from ltrace.slicer.tests.constants import TestState, CaseType
from ltrace.slicer.tests.ltrace_plugin_test import LTracePluginTest
from ltrace.slicer.tests.utils import log, wait
from pathlib import Path
from typing import List

TEST_STATUS_FILE_PATH = Path(slicer.app.temporaryPath) / "test_status.json"


class TestsSource(Enum):
    """Enumerate to indicate which environment the related test is within."""

    ANY = 0
    SLICER = 1
    GEOSLICER = 2


class TestSuiteData(qt.QObject):
    enablement_changed = qt.Signal(bool)
    test_case_enablement_changed = qt.Signal(bool)

    def __init__(
        self,
        test_class: object = None,
        test_case_data_list: List["TestCaseData"] = None,
        enabled: bool = False,
        module_name=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.test_class = test_class
        self.name = self.test_class.__name__
        self.__test_case_data_list = None
        self.test_case_data_list = test_case_data_list  # property setter
        self.__enabled = False
        self.enabled = enabled  # property setter
        self.__test_status = TestState.NOT_INITIALIZED
        self.module_name = module_name
        self.__failure_log_text: str = ""
        self.__warning_log_text: str = ""

    @property
    def test_status(self):
        return self.__test_status

    @test_status.setter
    def test_status(self, mode: TestState):
        self.__test_status = mode

    @property
    def enabled(self):
        return self.__enabled

    @enabled.setter
    def enabled(self, mode):
        if isinstance(mode, tuple):
            state, propagate = mode
        else:
            state = mode
            propagate = True

        if self.__enabled == state:
            return

        if self.__test_case_data_list is not None and propagate:
            for test_case_data in self.__test_case_data_list:
                test_case_data.enabled = state

        self.__enabled = state
        self.enablement_changed.emit(state)

    @property
    def test_case_data_list(self):
        return self.__test_case_data_list or []

    @test_case_data_list.setter
    def test_case_data_list(self, test_case_data_list):
        if self.__test_case_data_list is not None and len(self.__test_case_data_list) > 0:
            for test_case_data in self.__test_case_data_list:
                test_case_data.enablement_changed.disconnect(self.__on_child_test_case_enablement_changed)
            self.__test_case_data_list.clear()

        if self.__test_case_data_list is None:
            self.__test_case_data_list = []

        for test_case_data in test_case_data_list:
            test_case_data.enablement_changed.connect(self.__on_child_test_case_enablement_changed)
            self.__test_case_data_list.append(test_case_data)

    @property
    def failure_log_text(self) -> str:
        return self.__failure_log_text

    @failure_log_text.setter
    def failure_log_text(self, log: str):
        self.__failure_log_text = log

    @property
    def warning_log_text(self) -> str:
        return self.__warning_log_text

    @warning_log_text.setter
    def warning_log_text(self, log: str):
        self.__warning_log_text = log

    def __on_child_test_case_enablement_changed(self, state):
        if self.__test_case_data_list is None:
            return

        self.test_case_enablement_changed.emit(state)
        child_enabled = [test_case_data.enabled for test_case_data in self.__test_case_data_list]
        if len(child_enabled) <= 0:
            return

        if not any(child_enabled):
            self.enabled = (False, False)  # state, propagate
        else:
            self.enabled = (True, False)  # state, propagate

    def reset_state(self):
        for test_case_data in self.test_case_data_list:
            test_case_data.reset_state()

        self.test_status = TestState.NOT_INITIALIZED
        self.__failure_log_text = ""
        self.__warning_log_text = ""


class TestCaseData(qt.QObject):
    """Class to manage test case data."""

    enablement_changed = qt.Signal(bool)

    def __init__(
        self,
        test_case_method: object = None,
        enabled: bool = False,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.test_case_method = test_case_method
        self.name = self.test_case_method.__name__
        self.__enabled = False
        self.enabled = enabled
        self.__test_status = TestState.NOT_INITIALIZED

    @property
    def test_status(self):
        return self.__test_status

    @test_status.setter
    def test_status(self, mode: TestState):
        self.__test_status = mode

    @property
    def enabled(self):
        return self.__enabled

    @enabled.setter
    def enabled(self, mode: bool):
        if self.__enabled == mode:
            return

        self.__enabled = mode
        self.enablement_changed.emit(mode)

    def reset_state(self):
        self.test_status = TestState.NOT_INITIALIZED


class LTraceTestsModel(qt.QObject):
    """Class to handle the modules test run through code execution.
    It searchs the existent test classes in the GeoSlicer environment,
    allows test filtering and enable feedback when tests process are running or is finished.
    """

    test_case_finished = qt.Signal(object, object)
    tests_cancelled = qt.Signal()

    def __init__(self, parent=None, test_source=TestsSource.ANY, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.__test_source = test_source
        self.__test_suite_list, self.__generate_suite_list = self.__get_all_suites(test_source=self.__test_source)
        self.__is_running = False
        self.__running_test_class = None
        self.__cancelling = False

    @property
    def is_running(self):
        return self.__is_running

    @property
    def test_suite_list(self) -> List["TestSuiteData"]:
        return self.__test_suite_list

    @property
    def generate_suite_list(self) -> List["TestSuiteData"]:
        return self.__generate_suite_list

    @property
    def test_source(self):
        return self.__test_source

    @test_source.setter
    def test_source(self, test_source: TestsSource):
        if self.__test_source == test_source:
            return

        self.__test_source = test_source
        for test_suite_data in self.__test_suite_list[:]:
            del test_suite_data

        for generate_suite_data in self.__generate_suite_list[:]:
            del generate_suite_data

        self.__test_suite_list.clear()
        self.__generate_suite_list.clear()

        self.__test_suite_list, self.__generate_suite_list = self.__get_all_suites(test_source=self.__test_source)

    def cancel(self):
        if not self.__is_running or self.__running_test_class is None or self.__cancelling:
            return

        self.__running_test_class.cancel()
        self.__cancelling = True

    def result(self):
        def check_suite(suite_list: List[TestSuiteData]) -> TestState:
            for test_suite in suite_list:
                if not test_suite.enabled:
                    continue

                enabled_test_cases = [case for case in test_suite.test_case_data_list if case.enabled is True]

                for case in enabled_test_cases:
                    if case.test_status != TestState.SUCCEED:
                        return TestState.FAILED

            return TestState.SUCCEED

        return check_suite(self.test_suite_list + self.generate_suite_list)

    def __get_all_suites(self, test_source=TestsSource.ANY):
        test_suite_list = []
        generate_suite_list = []
        for method in slicer.selfTests.values():
            if not hasattr(method, "__self__"):
                continue

            module_name = method.__self__.__module__

            try:
                module = importlib.import_module(module_name)
            except ModuleNotFoundError as error:
                logging.info(f"{error}.\n{traceback.format_exc()}")
                continue

            test_class_names = []
            for test_class_name, obj in module.__dict__.items():
                if not test_class_name.endswith("Test"):
                    continue

                if obj is LTracePluginTest:
                    continue

                test_class_names.append(test_class_name)

            for test_class_name in test_class_names:
                test_class = getattr(module, test_class_name)

                if test_class is None or not inspect.isclass(test_class):
                    continue

                if not self.__match_test_source(test_class, test_source):
                    continue

                test_case_data_list = self.__get_test_cases_data(test_class)
                if test_case_data_list:
                    test_suite_list.append(
                        TestSuiteData(
                            test_class=test_class,
                            test_case_data_list=test_case_data_list,
                            module_name=module_name,
                        )
                    )

                generate_case_data_list = self.__get_generate_methods_data(test_class)
                if generate_case_data_list:
                    generate_suite_list.append(
                        TestSuiteData(
                            test_class=test_class,
                            test_case_data_list=generate_case_data_list,
                            module_name=module_name,
                        )
                    )

        # Order list by test class name alphabetical asceding order
        test_suite_list.sort(key=lambda x: x.test_class.__name__, reverse=False)
        generate_suite_list.sort(key=lambda x: x.test_class.__name__, reverse=False)

        return test_suite_list, generate_suite_list

    def __match_test_source(self, test_class, test_source):
        if test_class is LTracePluginTest:
            return False
        if issubclass(test_class, LTracePluginTest) and test_source in (
            TestsSource.ANY,
            TestsSource.GEOSLICER,
        ):
            return True
        if not issubclass(test_class, LTracePluginTest) and test_source in (
            TestsSource.ANY,
            TestsSource.SLICER,
        ):
            return True

        return False

    def __get_test_cases_data(self, test_class):
        if not issubclass(test_class, LTracePluginTest):  # Original slicer test class
            return [TestCaseData(test_case_method=test_class().runTest)]

        return [
            TestCaseData(test_case_method=test_case_method)
            for test_case_method in test_class.get_case_methods(CaseType.TEST)
        ]

    def __get_generate_methods_data(self, test_class):
        if not issubclass(test_class, LTracePluginTest):  # Original slicer test class
            return None

        return [
            TestCaseData(test_case_method=test_case_method)
            for test_case_method in test_class.get_case_methods(CaseType.TEMPLATE_GENERATOR)
        ]

    def run_tests(self, **kwargs):
        self.__is_running = True
        shuffle = kwargs.get("shuffle", False)
        useCaveat = kwargs.get("use_caveat", False)
        if "use_caveat" in kwargs.keys():
            del kwargs["use_caveat"]
        shutdownAfterTest = kwargs.get("shutdown_after_test", False)
        if "shutdown_after_test" in kwargs.keys():
            del kwargs["shutdown_after_test"]

        test_suite_list: List[TestSuiteData] = kwargs.get("suite_list")

        if not isinstance(test_suite_list, list) or test_suite_list is None:
            self.__cancelling = False
            self.__is_running = False
            raise ValueError("Invalid suite_list argument.")

        if shuffle:
            random.shuffle(test_suite_list)

        for test_suite in test_suite_list:
            test_suite.reset_state()

            if not test_suite.enabled:
                continue

            if self.__cancelling:
                break

            test_suite.test_status = TestState.RUNNING
            try:
                if not issubclass(test_suite.test_class, LTracePluginTest):  # Original slicer test class
                    self.__run_slicer_test_suite(test_suite)
                    continue

                self.__run_geoslicer_test_suite(test_suite, **kwargs)
            except Exception as error:
                logging.info(f"{error}.\n{traceback.format_exc()}")
                test_suite.test_status = TestState.FAILED
                continue

        self.create_test_status_file(useCaveat=useCaveat)

        if shutdownAfterTest:
            log("Shutting down application...")
            wait(5)
            slicer.app.exit()

        self.__cancelling = False
        self.__is_running = False

    def __run_geoslicer_test_suite(self, test_suite: TestSuiteData, **kwargs):
        if not test_suite.enabled:
            return

        # Filter test cases
        test_case_name_filter_list = [
            test_case_data.name for test_case_data in test_suite.test_case_data_list if test_case_data.enabled
        ]
        test_class = test_suite.test_class(
            module_name=test_suite.module_name,
            test_case_filter=test_case_name_filter_list,
            show_overview=False,
            **kwargs,
        )

        if len(test_class.test_cases) + len(test_class.generate_methods) <= 0:
            return

        # Connect signals
        test_class.test_case_finished.connect(
            lambda test_case_name, test_state: self.__on_test_case_finished(test_suite, test_case_name, test_state)
        )
        test_class.tests_cancelled.connect(self.tests_cancelled)

        # Run tests
        self.__running_test_class = test_class
        test_class.runTest()
        test_suite.test_status = test_class.status

        # Disconnect signals
        test_class.test_case_finished.disconnect()
        test_class.tests_cancelled.disconnect()

        # Store test suite logs
        test_suite.warning_log_text = test_class.get_warnings_text()
        test_suite.failure_log_text = test_class.get_failure_overview_text()

        # Reset objects
        del test_class
        del self.__running_test_class
        self.__running_test_class = None
        gc.collect()

    def __on_test_case_finished(self, test_suite_data: TestSuiteData, test_case_name: str, test_state: TestState):
        current_test_case_data = None
        for test_case in test_suite_data.test_case_data_list:
            if test_case.name == test_case_name:
                current_test_case_data = test_case
                break

        if current_test_case_data is None:
            raise RuntimeError(f"The finished test case {test_case_name} doesn't belong to {test_suite_data.name} ")

        current_test_case_data.test_status = test_state
        self.test_case_finished.emit(test_suite_data, current_test_case_data)

    def __run_slicer_test_suite(self, test_suite: TestSuiteData):
        raise NotImplementedError("Slicer test runner not implemented yet.")

    def create_test_status_file(self, useCaveat: bool = False, file_path: Path = TEST_STATUS_FILE_PATH) -> None:
        state = self.result()
        failed_test_suites = {}
        for test_suite_data in self.test_suite_list:
            if test_suite_data.test_status == TestState.SUCCEED:
                continue

            failed_test_cases = [
                case.name for case in test_suite_data.test_case_data_list if case.test_status == TestState.FAILED
            ]

            if len(failed_test_cases) == 0:
                continue

            failed_test_suites[test_suite_data.name] = failed_test_cases

        caveat = None
        if useCaveat and state == TestState.FAILED:
            caveat = Caveat()
            log("Test failure detected. Checking caveat...")
            should_bypass = True
            for test_suite_name, failed_test_cases in failed_test_suites.items():
                set_failed_test_cases = set(failed_test_cases)
                set_expected_to_fail_test_cases = set(caveat.failing_test_cases(test_suite_name))
                difference = set_failed_test_cases - set_expected_to_fail_test_cases
                should_bypass &= len(difference) == 0

                if not should_bypass:
                    log(f"The test suite '{test_suite_name}' has failed cases that are not expected to fail.")
                    break

            if should_bypass:
                log("All the current failed test cases are expected to fail, bypassing test failure...")
                state = TestState.SUCCEED

        data = {"status": state.value}
        data = {**data, "failing_tests": {**failed_test_suites}}

        if useCaveat and caveat is not None:
            data = {**data, "expected_failing_tests": caveat.failing_tests}

        if file_path.exists():
            file_path.unlink()

        with open(file_path, "x") as f:
            json.dump(data, f, indent=4)
