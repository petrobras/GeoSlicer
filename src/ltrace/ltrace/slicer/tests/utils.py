import contextlib
import slicer
import logging
import qt
import shutil
import time

from ltrace.constants import SaveStatus
from ltrace.slicer.project_manager import ProjectManager
from ltrace.slicer.helpers import make_directory_writable, WatchSignal
from ltrace.utils.string_comparison import StringComparison
from pathlib import Path
from stopit import TimeoutException
from typing import Union

TEST_LOG_FILE_PATH = Path(slicer.app.temporaryPath) / "tests.log"


def process_events():
    """Qt processEvent method wrapper."""
    slicer.app.processEvents(qt.QEventLoop.AllEvents, 5000)


def create_logger(level=logging.DEBUG, log_file_path=TEST_LOG_FILE_PATH):
    logger = logging.getLogger("tests_logger")
    logger.setLevel(level)

    formatter = logging.Formatter(
        "[%(levelname)s] %(asctime)s - %(name)s: %(message)s",
        datefmt="%d/%m/%Y %I:%M:%S%p",
    )

    # File handler
    log_file_path.parent.mkdir(exist_ok=True)
    fileHandler = logging.FileHandler(log_file_path, mode="a")
    fileHandler.setLevel(level)
    fileHandler.setFormatter(formatter)
    logger.addHandler(fileHandler)

    return logger


TESTS_LOGGER = create_logger()


def wait(seconds: float) -> None:
    """Sleep method wrapper that calls QApplication 'processEvents' method

    Args:
        seconds (float): the total time to wait in seconds.
    """
    start = time.perf_counter()

    try:
        while True:
            time.sleep(0.1)
            process_events()

            if time.perf_counter() - start >= seconds:
                break
    except TimeoutException:
        raise TimeoutError("Test timeout reached!")


def wait_cli_to_finish(cli_node, timeout_sec: int = 3600) -> None:
    """Lock thread until respective CLI node is not busy anymore.

    Args:
        cli_node (vtkMRMLCommandLineModuleNode): the CLI node object,
        timeout_sec (int, optional): the timeout in seconds. Defaults to 3600 seconds.
    """
    if cli_node is None:
        return

    start = time.perf_counter()
    try:
        while cli_node.IsBusy():
            time.sleep(0.200)
            process_events()

            if time.perf_counter() - start >= timeout_sec:
                cli_node.Cancel()
                raise TimeoutError("CLI timeout reached!")
    except TimeoutException:
        cli_node.Cancel()
        raise TimeoutError("Test timeout reached!")


def log(message, show_window=False, end="\n"):
    """Logging wrapper for test run scenario.

    Args:
        message (str): The message to log
        show_window (bool, optional): Open a message box with the related message. Defaults to False.
        end (str, optional): Print statement paremeter. Defaults to "\n".
    """
    TESTS_LOGGER.debug(message, extra={"end": end})
    if show_window:
        slicer.util.delayDisplay(message, autoCloseMsec=2000)


def find_widget_by_object_name(
    obj, name: str, _type="QWidget", comparison_type=StringComparison.EXACTLY, only_visible=False
):
    """Finds widgets inside qt objects. Please write a test when using this function"""
    if not obj:
        return None

    widgets = obj.findChildren(_type)

    if not widgets:
        return None

    for widget in widgets:
        if only_visible and not widget.visible:
            continue

        if widget and widget.objectName == name:
            return widget

    return None


def load_project(project_file_path, timeout_ms=300000):
    path = Path(project_file_path)
    if not path.exists():
        raise ValueError("Project file not found!")

    with WatchSignal(signal=slicer.mrmlScene.EndImportEvent, timeout_ms=timeout_ms):
        try:
            slicer.util.loadScene(path.as_posix())
        except Exception:
            raise RuntimeError(f"Timeout! Failed to load {path.as_posix()} project file!")


@contextlib.contextmanager
def check_for_message_box(message, should_accept=True, timeout_sec=2, buttonTextToClick=None):
    """Context manager to handle the displaying of a QMessageBox during a test scenario

    Args:
        message (str): the expected QMessageBox text
        should_accept (bool, optional): Accept if True, otherwise Reject the message box action. Defaults to True.
        timeout_sec (int, optional): Timeout to wait for the message box to appear, in seconds. Defaults to 2.
        buttonTextToClick (_type_, optional): The button text to click. Defaults to None.

    Raises:
        AttributeError: When the QMessageBox isn't identified.
    """
    result = [False]
    start_time = time.perf_counter()
    timer = qt.QTimer()
    timer.setSingleShot(True)
    timer.setInterval(1000)

    def check():
        if result[0] is True:
            return

        mw = slicer.util.mainWindow()
        message_boxes = mw.findChildren(qt.QMessageBox)
        the_message_box = None

        related_message_boxes = [
            msg_box for msg_box in message_boxes if msg_box.visible == True and message in msg_box.text
        ]

        if len(related_message_boxes) <= 0:
            # Find possible visible QMessageBox and close it to avoid freezing the test process
            other_message_boxes = [msg_box for msg_box in message_boxes if msg_box.visible == True]
            for message_box in other_message_boxes:
                message_box.close()

            if time.perf_counter() - start_time < timeout_sec:
                timer.start()
            return

        the_message_box = related_message_boxes[0]

        if not buttonTextToClick:
            if should_accept:
                the_message_box.accept()
            else:
                the_message_box.reject()
        else:
            the_button = None
            for button in the_message_box.buttons():
                if button.text != buttonTextToClick:
                    continue

                the_button = button

            if the_button is None:
                the_message_box.reject()
            else:
                the_button.click()

        result[0] = True

    timer.timeout.connect(check)
    timer.start()

    yield

    while result[0] is False:
        if time.perf_counter() - start_time >= timeout_sec:
            break

        wait(0.1)
        check()

    timer.stop()
    timer = None

    if result[0] is False:
        raise AttributeError("The desired message box doesn't exist in the current context.")


def save_project(project_path: Union[str, Path], timeout_ms=300000, properties=None) -> bool:
    """Handles the 'save as' project method.

    Args:
        project_path (Union[str, Path]): the desired project folder .mrml file.

    Returns:
        bool: True if save process was successful, otherwise False
    """
    if properties is None or not isinstance(properties, dict):
        properties = {}

    if not isinstance(project_path, Path):
        project_path = Path(project_path)

    if project_path.is_file():
        shutil.rmtree(project_path.parent, onerror=make_directory_writable)
    elif project_path.is_dir():
        shutil.rmtree(project_path, onerror=make_directory_writable)

    project_manager = ProjectManager(folder_icon_path="")

    with WatchSignal(signal=slicer.mrmlScene.EndImportEvent, timeout_ms=timeout_ms):
        return project_manager.save_as(project_path.parent, properties=properties) == SaveStatus.SUCCEED


def save_current_project(timeout_ms=300000, properties=None) -> bool:
    """Handles the 'save' project method.

    Args:
        project_path (Union[str, Path]): the desired project folder .mrml file.

    Returns:
        bool: True if save process was successful, otherwise False
    """
    url = slicer.mrmlScene.GetURL()
    if url == "":
        raise AttributeError("There is no project loaded")

    if properties is None or not isinstance(properties, dict):
        properties = {}

    project_manager = ProjectManager(folder_icon_path="")

    with WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=timeout_ms):
        return project_manager.save(url, properties=properties) == SaveStatus.SUCCEED


def close_project(timeout_ms: int = 300000) -> None:
    with WatchSignal(signal=slicer.mrmlScene.EndCloseEvent, timeout_ms=timeout_ms):
        slicer.mrmlScene.Clear(0)

    slicer.mrmlScene.EndState(slicer.mrmlScene.CloseState)
    process_events()


def compare_ignore_line_endings(file1, file2):
    with open(file1, "r") as f1:
        with open(file2, "r") as f2:
            return f1.read().replace("\r\n", "\n") == f2.read().replace("\r\n", "\n")
