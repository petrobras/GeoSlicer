"""Agent-friendly API for GeoSlicer test execution and debugging.

Provides simple functions callable via the Web Server exec endpoint (gs_exec.py)
for running integration tests and enabling crash diagnostics.

"""

import dataclasses
import logging
import sys
import traceback

import slicer

from pathlib import Path

from ltrace.slicer.tests.ltrace_tests_model import LTraceTestsModel, TestsSource
from ltrace.slicer.tests.utils import loadAllModules, TESTS_LOGGER


@dataclasses.dataclass
class _State:
    model: object = None
    error: str | None = None
    faulthandler_file: object = None
    is_running: bool = False
    result: str | None = None
    output_buffer: list = dataclasses.field(default_factory=list)
    log_file_path: str | None = None


_state = _State()


# Side-channel log file. Mirrored from stdout/stderr during run_tests so that
# output is recoverable even when the HTTP response never arrives (e.g. a test
# hangs on the main thread and the WebServer never gets to write the response).
RUN_TESTS_LOG_PATH = Path(slicer.app.temporaryPath) / "agent_run_tests.log"


class _TeeStream:
    """Writes to multiple streams simultaneously, ignoring stream-level errors."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for s in self.streams:
            try:
                s.write(text)
            except Exception:
                pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass


class _BufferStream:
    """Append-only stream that stores writes in a list."""

    def __init__(self, buffer):
        self._buffer = buffer

    def write(self, text):
        if text:
            self._buffer.append(text)

    def flush(self):
        pass

    def isatty(self):
        return False


class _DuplicateFilterStream:
    """Buffers text into lines and suppresses lines that repeat too many times."""

    def __init__(self, target_stream, max_occurrences=3):
        self.target = target_stream
        self.max_occurrences = max_occurrences
        self.line_counts = {}
        self._buffer = ""

    def write(self, text):
        if not text:
            return

        self._buffer += text
        # Process complete lines as soon as a newline arrives
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._process_line(line)

    def _process_line(self, line):
        stripped = line.strip()
        # Do not filter empty lines
        if not stripped:
            self.target.write(line + "\n")
            return

        count = self.line_counts.get(stripped, 0) + 1
        self.line_counts[stripped] = count

        if count < self.max_occurrences:
            self.target.write(line + "\n")
        elif count == self.max_occurrences:
            self.target.write(line + " [...]\n")

    def flush(self):
        # Dump any remaining partial text when stream is flushed
        if self._buffer:
            self._process_line(self._buffer)
            self._buffer = ""
        self.target.flush()

    def isatty(self):
        return False


class _CLIOutputCapture:
    """Capture stdout/stderr from CLI module nodes and print to stdout.

    Patches slicer.cli.run during test runs so every CLI node gets a
    ModifiedEvent observer attached before the subprocess has any chance to
    complete. Active only during agent-driven test runs. Has no effect on the
    rest of the codebase.
    """

    _DONE = (
        slicer.vtkMRMLCommandLineModuleNode.Completed,
        slicer.vtkMRMLCommandLineModuleNode.CompletedWithErrors,
    )

    def __init__(self):
        self._original_run = None
        self._node_tags = {}  # node_id -> observer tag

    def start(self):
        self._original_run = slicer.cli.run
        capture = self

        def _patched_run(module, node=None, parameters=None, *args, **kwargs):
            result_node = capture._original_run(module, node, parameters, *args, **kwargs)
            if result_node is not None:
                if result_node.GetStatus() in capture._DONE:
                    capture._emit(result_node)
                else:
                    tag = result_node.AddObserver("ModifiedEvent", capture._on_node_modified)
                    capture._node_tags[result_node.GetID()] = tag
            return result_node

        slicer.cli.run = _patched_run

    def stop(self):
        if self._original_run is not None:
            slicer.cli.run = self._original_run
            self._original_run = None
        self._node_tags.clear()

    def _on_node_modified(self, node, event):
        if node is None or node.GetStatus() not in self._DONE:
            return
        tag = self._node_tags.pop(node.GetID(), None)
        if tag is None:
            return  # already logged
        node.RemoveObserver(tag)
        self._emit(node)

    def _emit(self, node):
        name = node.GetName()
        for label, text in (("stdout", node.GetOutputText()), ("stderr", node.GetErrorText())):
            if text and text.strip():
                print(f"[CLI:{name}] {label}:\n{text.strip()}", flush=True)


def list_tests():
    """Return all available test suites and their test cases.

    Returns:
        dict: ``{"suites": [{"name": str, "cases": [str]}]}``
    """
    loadAllModules()
    model = LTraceTestsModel(parent=slicer.util.mainWindow(), test_source=TestsSource.GEOSLICER)
    suites = []
    for suite in model.test_suite_list:
        cases = [case.name for case in suite.test_case_data_list]
        suites.append({"name": suite.name, "cases": cases})
    model.deleteLater()
    return {"suites": suites}


def run_tests(filters=None):
    """Run tests synchronously. Logs stream to stdout, the in-memory buffer,
    and a side-channel file (RUN_TESTS_LOG_PATH).

    The side channels exist so that output is recoverable when the HTTP
    response never arrives (e.g. a test hangs on the main thread). Use
    ``get_run_status()`` to fetch the buffer and ``cancel_run_tests()`` to
    request cancellation in that case.

    Args:
        filters: List of filter strings, e.g. ``["SuiteName:test1,test2", "OtherSuite"]``.
                 ``None`` or empty list runs all tests.

    Returns:
        dict: ``{"result": str}``
              ``result`` is ``"SUCCEED"``, ``"FAILED"``, or ``"ERROR"``.
    """
    global _state

    if _state.is_running:
        return {
            "result": "ERROR",
            "error": "A test run is already in progress. Use cancel_run_tests() first.",
        }

    log_path = RUN_TESTS_LOG_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_file = open(log_path, "w", buffering=1, encoding="utf-8", errors="replace")
    except Exception as e:
        return {"result": "ERROR", "error": f"Could not open log file {log_path}: {e}"}

    _state = _State(
        is_running=True,
        output_buffer=[],
        log_file_path=str(log_path),
    )

    log_formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")

    buffer_stream = _BufferStream(_state.output_buffer)
    old_stdout, old_stderr = sys.stdout, sys.stderr

    # Combine destinations
    raw_stdout = _TeeStream(old_stdout, buffer_stream, log_file)
    raw_stderr = _TeeStream(old_stderr, buffer_stream, log_file)

    # Wrap destinations with the real-time deduplicator filter
    capture_stdout = _DuplicateFilterStream(raw_stdout, max_occurrences=3)
    capture_stderr = _DuplicateFilterStream(raw_stderr, max_occurrences=3)

    tests_handler = logging.StreamHandler(capture_stdout)
    tests_handler.setLevel(logging.DEBUG)
    tests_handler.setFormatter(log_formatter)

    root_handler = logging.StreamHandler(capture_stdout)
    root_handler.setLevel(logging.WARNING)
    root_handler.setFormatter(log_formatter)

    cli_capture = _CLIOutputCapture()

    try:
        sys.stdout = capture_stdout
        sys.stderr = capture_stderr
        TESTS_LOGGER.addHandler(tests_handler)
        logging.getLogger().addHandler(root_handler)
        cli_capture.start()

        loadAllModules()
        _state.model = LTraceTestsModel(parent=slicer.util.mainWindow(), test_source=TestsSource.GEOSLICER)

        _apply_filters(_state.model, filters)

        _state.model.run_tests(
            suite_list=_state.model.test_suite_list,
            shuffle=False,
            break_on_failure=False,
        )

        for suite in _state.model.test_suite_list:
            if suite.warning_log_text:
                TESTS_LOGGER.debug(suite.warning_log_text)
            if suite.failure_log_text:
                TESTS_LOGGER.debug(suite.failure_log_text)

        _state.model.create_test_status_file()

    except Exception as e:
        _state.error = f"{e}\n{traceback.format_exc()}"
        logging.error(f"Agent test API error: {_state.error}")
    finally:
        capture_stdout.flush()  # Ensure any trailing partial lines are written
        capture_stderr.flush()
        sys.stdout, sys.stderr = old_stdout, old_stderr
        cli_capture.stop()
        TESTS_LOGGER.removeHandler(tests_handler)
        logging.getLogger().removeHandler(root_handler)
        try:
            log_file.flush()
            log_file.close()
        except Exception:
            pass

        result_name = "ERROR" if _state.error else (_state.model.result().name if _state.model else "UNKNOWN")
        _state.result = result_name
        _state.is_running = False

    return {"result": _state.result}


def get_run_status():
    """Return the current state of the most recent (or in-flight) test run.

    Use this when the HTTP call to ``run_tests`` times out or is interrupted.
    The output buffer contains everything written to stdout/stderr since the
    run started.

    Returns:
        dict: ``{"running": bool, "result": str|None, "output": str,
                 "error": str|None, "log_file": str|None}``
    """
    return {
        "running": _state.is_running,
        "result": _state.result,
        "output": "".join(_state.output_buffer),
        "error": _state.error,
        "log_file": _state.log_file_path,
    }


def cancel_run_tests():
    """Best-effort request to cancel an in-flight test run.

    Calls ``cancel()`` on the underlying test model. Tests that are stuck in a
    Python loop that does not check for cancellation will not stop until that
    loop exits.

    Returns:
        dict: ``{"cancel_requested": bool, "running": bool}``
    """
    requested = False
    if _state.is_running and _state.model is not None:
        try:
            _state.model.cancel()
            requested = True
        except Exception as e:
            logging.error(f"cancel_run_tests failed: {e}")
    return {"cancel_requested": requested, "running": _state.is_running}


def _apply_filters(model, filters):
    """Enable specific suites/cases based on filter strings.

    Mirrors the logic from ``tools/pipeline/run_modules_tests.py:filter_tests()``.

    Filter format:
        - ``"SuiteName"`` — run all cases in that suite
        - ``"SuiteName:test1,test2"`` — run specific cases
    """
    if not filters:
        for suite in model.test_suite_list:
            suite.enabled = True
        return

    for filter_str in filters:
        if ":" in filter_str:
            suite_name, case_names_str = filter_str.split(":", 1)
        else:
            suite_name = filter_str
            case_names_str = None

        matched_suite = None
        for suite in model.test_suite_list:
            if suite.name.lower() != suite_name.lower():
                continue
            matched_suite = suite

            if case_names_str is None:
                suite.enabled = True
            else:
                for case_name in case_names_str.split(","):
                    case_name = case_name.strip()
                    if not any(case.name.lower() == case_name.lower() for case in suite.test_case_data_list):
                        print(f"[WARNING] Filter '{filter_str}': no test case '{case_name}' in suite '{suite.name}'")
                        continue
                    for case in suite.test_case_data_list:
                        if case.name.lower() == case_name.lower():
                            case.enabled = True

        if matched_suite is None:
            print(f"[WARNING] Filter '{filter_str}': no suite named '{suite_name}' found")


def enable_faulthandler(output_path=None):
    """Enable Python's faulthandler to capture crash tracebacks.

    Writes crash information to a file so it can be inspected after a hard crash.
    Off by default because faulthandler makes GeoSlicer slower.

    Args:
        output_path: Absolute path to the output file.
                     Defaults to ``<slicer_temp>/faulthandler.log``.

    Returns:
        dict: ``{"enabled": True, "file": str}``
    """
    import faulthandler

    if output_path is None:
        output_path = Path(slicer.app.temporaryPath) / "faulthandler.log"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if _state.faulthandler_file is not None:
        _state.faulthandler_file.close()

    _state.faulthandler_file = open(output_path, "w")
    faulthandler.enable(file=_state.faulthandler_file)

    return {"enabled": True, "file": str(output_path)}
