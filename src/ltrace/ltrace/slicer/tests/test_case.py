import sys
import traceback

from ltrace.slicer.helpers import ElapsedTime
from ltrace.slicer.tests.constants import TestState
from unittest.mock import patch
from typing import Callable

# Hack to catch exceptions triggered by Qt signals
sys._excepthook = sys.excepthook


class TestCase:
    """Class to handle information about a single test case."""

    def __init__(self, function: Callable, cls: "LTracePluginTest") -> None:
        self.name = self.__generate_name(function)
        self.function = function
        self.status: TestState = TestState.NOT_INITIALIZED
        self.reason = ""
        self.elapsed_time_sec = 0
        self.test_module_class = cls
        self.__exception_hook_patch = patch("sys.excepthook", self.__exception_hook_handler)

    def __generate_name(self, function: Callable) -> None:
        return function.__name__.replace("test_", "").replace("_", " ")

    def __call__(self, *args, **kwargs) -> None:
        self.run()

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
