import sys
import traceback

from inspect import signature
from ltrace.slicer.helpers import ElapsedTime
from ltrace.slicer.tests.constants import TestState
from typing import Callable, Union
from unittest.mock import patch

# Hack to catch exceptions triggered by Qt signals
sys._excepthook = sys.excepthook


class TestCase:
    """Class to handle information about a single test case."""

    def __init__(self, function: Callable, cls: "LTracePluginTest") -> None:
        assert function is not None, "Test case function is None!"
        self.name = self.__generate_name(function)
        self.function = function
        self.status: TestState = TestState.NOT_INITIALIZED
        self.reason = ""
        self.elapsed_time_sec = 0
        self.test_module_class = cls
        self.timeout_ms = self.__get_timeout()
        self.__exception_hook_patch = patch("sys.excepthook", self.__exception_hook_handler)

    def __get_timeout(self) -> Union[int, None]:
        """Get timeout in milliseconds. It will get the 'timeout_ms' parameter from the test case method if it is available.
           Otherwise, it will use the default value from 'TestCase.DEFAULT_TIMEOUT_MS'.

        Returns:
            int: the timeout in milliseconds.
        """
        func_signature = signature(self.function)
        timeout_ms_param = func_signature.parameters.get("timeout_ms")
        return timeout_ms_param.default if timeout_ms_param is not None else None

    def __generate_name(self, function: Callable) -> None:
        return function.__name__.replace("test_", "").replace("_", " ")

    def __call__(self, *args, **kwargs) -> None:
        self.run()

    def reset(self):
        self.status = TestState.NOT_INITIALIZED
        self.reason = ""
        self.elapsed_time_sec = 0

    def run(self) -> None:
        self.status = TestState.RUNNING
        with self.__exception_hook_patch:
            with ElapsedTime(print=False) as elapsed_time:
                try:
                    self.function(self.test_module_class)
                    if self.status == TestState.RUNNING:
                        self.status = TestState.SUCCEED
                except Exception as error:
                    trace_back = traceback.format_exc()
                    self.reason = trace_back if trace_back else str(error)
                    self.status = TestState.FAILED

            self.elapsed_time_sec = elapsed_time.time

    def __exception_hook_handler(self, exc_type: type, exc_value: TypeError, exc_traceback: traceback) -> None:
        """Handler for exception hook.
           Enhance behavior to set the test case run as failed when
           an internal exception happens (mostly caused by slots triggered by Qt signals).
        Args:
            exc_type (type): the exception class.
            exc_value (TypeError): the exception instance.
            exc_traceback (traceback): the traceback object.
        """
        sys._excepthook(exc_type, exc_value, exc_traceback)
        trace_back = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        self.status = TestState.FAILED
        self.reason = trace_back

    def __repr__(self) -> str:
        text = f"Test case: {self.name}"
        status = TestState.to_str(self.status)
        text += f"\nState: {status}"
        if self.status == TestState.FAILED:
            text += f"\nError:\n{self.reason}"

        return text
