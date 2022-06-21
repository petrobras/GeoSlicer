import gc
import slicer
import random
import traceback
import qt
from types import MappingProxyType

from ltrace.slicer.tests.constants import TestState
from ltrace.slicer.tests.test_case import TestCase
from ltrace.slicer.tests.utils import (
    log,
    find_widget_by_object_name,
    close_project,
    process_events,
)
from ltrace.slicer.tests.widgets_identification import guess_widget_by_name, widgetsIdentificationModule
from ltrace.utils.string_comparison import StringComparison
from slicer import ScriptedLoadableModule


class LTracePluginTestMeta(type(qt.QObject), type(ScriptedLoadableModule.ScriptedLoadableModuleTest)):
    pass


class LTracePluginTest(qt.QObject, ScriptedLoadableModule.ScriptedLoadableModuleTest, metaclass=LTracePluginTestMeta):
    """Class to enhance ScriptedLoadableModuleTest for LTrace purpose."""

    test_case_finished = qt.Signal(str, object)
    tests_cancelled = qt.Signal()

    def __init__(
        self,
        module_name=None,
        suite_list=None,
        shuffle=True,
        break_on_failure=False,
        after_clear=True,
        test_case_filter=[],
        show_overview=False,
        *args,
        **kwargs,
    ):
        super(qt.QObject, self).__init__()
        super(ScriptedLoadableModule.ScriptedLoadableModuleTest, self).__init__(*args, **kwargs)
        self._module_name = (
            module_name or self.__class__.__name__[:-4]
            if self.__class__.__name__.endswith("Test")
            else self.__class__.__name__
        )
        self.__suite_list = suite_list
        self.__shuffle = shuffle
        self.__break_on_failure = break_on_failure
        self.__after_clear = after_clear

        test_case_method_list = self.get_test_case_methods()
        self.__test_cases = self.__get_methods(test_case_method_list, test_case_filter)

        generate_method_list = self.get_generate_methods()
        self.__generate_methods = self.__get_methods(generate_method_list, test_case_filter)

        self.__test_state = TestState.NOT_INITIALIZED
        self.__show_overview = show_overview
        self.__warnings = []
        self.__widgets = {}

    @property
    def widgets(self):
        return MappingProxyType(self.__widgets)

    @property
    def status(self):
        return self.__test_state

    @property
    def test_cases(self):
        return self.__test_cases

    @property
    def generate_methods(self):
        return self.__generate_methods

    @property
    def warnings(self):
        return self.__warnings

    @classmethod
    def get_test_case_methods(cls):
        methods = list()
        for attribute in dir(cls):
            attr = getattr(cls, attribute)
            if hasattr(attr, "__name__") and attr.__name__.startswith("test_"):
                methods.append(attr)
        return methods

    @classmethod
    def get_generate_methods(cls):
        methods = list()
        for attribute in dir(cls):
            attr = getattr(cls, attribute)
            if hasattr(attr, "__name__") and attr.__name__.startswith("generate_"):
                methods.append(attr)
        return methods

    def reloadModuleWidget(self):
        """Wrapper for widget reload"""
        self._module_widget.onReload()

    def setUp(self):
        """ScriptedLoadableModuleTest method overload, called before starting the testing case."""
        self.__close_project()

        try:
            self._pre_setup()
        except Exception as error:
            self.warnings.append(error)

        self._module_widget = slicer.util.getNewModuleWidget(self._module_name)
        self._module_widget.parent.setWindowModality(qt.Qt.ApplicationModal)
        self._module_widget.parent.show()
        self._module_widget.enter()
        process_events()

        try:
            self._post_setup()
        except Exception as error:
            self.warnings.append(error)

    def tearDown(self):
        try:
            self.tear_down()
        except Exception as error:
            message = "Test suite tear down failed! Please review the 'tear_down' method from the test class!"
            message += f"\nError: {error}\n{traceback.format_exc()}"
            self.warnings.append(message)

        if self._module_widget is not None:
            self._module_widget.cleanup()
            self._module_widget.parent.close()
            del self._module_widget
            self._module_widget = None

        if self.__after_clear:
            self.__close_project()
        gc.collect()

    def cancel(self):
        if not self.__test_state == TestState.RUNNING:
            return

        self.__test_state = TestState.CANCELLED

    def runTest(self):
        """ScriptedLoadableModuleTest method overload, called when starting the testing process."""
        self.__test_state = TestState.RUNNING

        log(
            f"Starting test session from {self.__class__.__name__} suite...",
            show_window=False,
        )

        test_cases = self.test_cases + self.generate_methods
        if self.__shuffle:
            random.shuffle(test_cases)

        valid_test_count = 0
        for idx, test in enumerate(test_cases):
            if self.__test_state == TestState.CANCELLED and idx != len(test_cases) - 1:
                break

            self.setUp()

            log(
                " " * 4 + f"Running test case: {test.name}... ",
                end="",
                show_window=False,
            )
            test()
            self.tearDown()
            if test.status == TestState.SUCCEED:
                valid_test_count += 1
                log(f"OK! [{test.elapsed_time_sec:.6f} sec]")
                self.test_case_finished.emit(test.function.__name__, TestState.SUCCEED)
            else:
                log(f"FAILED! [{test.elapsed_time_sec:.6f} sec]")
                self.test_case_finished.emit(test.function.__name__, TestState.FAILED)
                if self.__break_on_failure:
                    break

        if self.__test_state == TestState.CANCELLED and idx != len(test_cases) - 1:
            self.__on_test_cancelled()
            return

        if valid_test_count == len(test_cases):
            log(
                f"\nTest session from {self.__class__.__name__} finished succesfully! "
                + f"Total test cases: {valid_test_count}\n"
            )
            self.__test_state = TestState.SUCCEED
        else:
            self.__test_state = TestState.FAILED
            log(
                f"\nTest session from {self.__class__.__name__} finished with errors! "
                + f"Total valid test cases: {valid_test_count} from {len(test_cases)}\n"
            )

        if self.__show_overview:
            self.show_overview()

    def __on_test_cancelled(self):
        log("Aborting tests. The tests were cancelled by the user.")
        self.tests_cancelled.emit()

    def pre_setup(self):
        """Abstract method.
        Use for custom setup before module initialization at the LTracePluginTest derived class (test suite).
        """
        pass

    def post_setup(self):
        """Abstract method.
        Use for custom setup after module initialization at the LTracePluginTest derived class (test suite).
        """
        pass

    def _pre_setup(self):
        """
        Method responsible to handle setup before module initialization
        """
        try:
            self.pre_setup()
        except Exception as error:
            message = "Test suite pre-setup failed! Please review the 'pre_setup' class method!"
            message += f"\nError: {error}\n{traceback.format_exc()}"
            raise Exception(message)

    def _post_setup(self):
        """
        Method responsible to handle setup after module initialization
        """
        try:
            self.__widgets = widgetsIdentificationModule(self._module_widget).widgets
            for key, widget in self.__widgets.items():
                assert widget is not None, f"widget related to the identifier '{key}' is None!"
        except Exception as error:
            message = (
                "Automatic recognition of widgets failed! Please review the 'widgetsIdentificationModule' class method!"
            )
            message += f"\nError: {error}\n{traceback.format_exc()}"
            raise Exception(message)

        try:
            self.post_setup()
        except Exception as error:
            message = "Test suite post-setup failed! Please review the 'post_setup' class method!"
            message += f"\nError: {error}\n{traceback.format_exc()}"
            raise Exception(message)

    def tear_down(self):
        """Abstract method.
        Use for custom tear down at the LTracePluginTest derived class (test suite).
        """
        pass

    def __close_project(self):
        process_events()
        close_project()
        process_events()

    def find_widget(
        self,
        name: str,
        obj=None,
        type="QWidget",
        comparison_type=StringComparison.EXACTLY,
    ):
        """Search for the QWidget that contains the desired object's name attribute.

        Args:
            name (str): The expected QWidget's object name.

        Raises:
            RuntimeError: Raises if module's widget is not configured.

        Returns:
            qt.QWidget/None: the related widget object. If no widget with the information is found, returns None.
        """
        if obj is None:
            if self._module_widget is None:
                raise RuntimeError("No module was defined.")

            obj = self._module_widget.parent

        return find_widget_by_object_name(obj, name, type, comparison_type) or guess_widget_by_name(
            self.__widgets, name
        )

    def __get_methods(self, methods_list: list, methods_filter: list):
        """Retrieve test or generate methods from the LTracePluginTest object.

        Args:
            methods_list (list): list of functions to retrieve
            methods_filter (list): list of functions to filter

        Returns:
            list: A list of TestCase objects
        """
        cases = list()
        for method in methods_list:
            if len(methods_filter) > 0 and method.__name__ not in methods_filter:
                continue

            method_case = TestCase(method, self)
            cases.append(method_case)

        return cases

    def show_overview(self):
        if warning_text := self.get_warnings_text():
            log(warning_text)

        if failure_text := self.get_failure_overview_text():
            log(failure_text)

    def get_failure_overview_text(self) -> str:
        if len(self.test_cases + self.generate_methods) <= 0:
            return None

        failed_test_cases = [
            test_case for test_case in self.test_cases + self.generate_methods if test_case.status == TestState.FAILED
        ]
        if not failed_test_cases:
            return None

        text = f"Errors from {self._module_name} test suite:"
        for test in failed_test_cases:
            text += "\n" + "=" * 66
            text += f"\n{str(test)}"
        text += "\n" + "=" * 66 + "\n"

        return text

    def get_warnings_text(self) -> str:
        if not self.warnings:
            return ""

        text = f"Warnings from {self._module_name} test suite:"
        for warning in self.warnings:
            text += "\n" + "=" * 66
            text += f"\n{warning}"
        text += "\n" + "=" * 66 + "\n"

        return text
