import contextlib
import slicer
import logging
import qt
import shutil
import time
import sys

from datetime import datetime
from commons.constants import SaveStatus
from commons.slicer.project_manager import ProjectManager
from commons.slicer.helpers import make_directory_writable, WatchSignal, limitLogFiles
from commons.slicer.module_utils import loadModules
from commons.utils.string_comparison import StringComparison
from pathlib import Path
from stopit import TimeoutException
from typing import Callable, Union


def process_events():
    """Qt processEvent method wrapper."""
    slicer.app.processEvents(qt.QEventLoop.AllEvents, 5000)


def newTestsLogFilePath() -> Path:
    datetimeString = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return Path(slicer.app.temporaryPath) / f"tests_{datetimeString}.log"


class TemporaryFolderLogHandler(logging.FileHandler):
    """Writes the tests log to the temporary folder, choosing the file when the first message is logged instead of
    when the handler is created. The handler is created on import, before slicerrc moves the temporary folder out of
    the installation, so a path chosen then would point at the old folder."""

    def __init__(self):
        # Placeholder: FileHandler requires a filename, but emit() replaces it before the file is first opened
        super().__init__(newTestsLogFilePath(), mode="a", delay=True)

    def emit(self, record):
        if self.stream is None:
            logFilePath = newTestsLogFilePath()
            logFilePath.parent.mkdir(parents=True, exist_ok=True)
            limitLogFiles(logFilePath.parent, "tests_", 20)
            self.baseFilename = str(logFilePath)
        super().emit(record)


def create_logger(level=logging.DEBUG):
    logger = logging.getLogger("tests_logger")
    logger.setLevel(level)

    formatter = logging.Formatter(
        "[%(levelname)s] %(asctime)s - %(name)s: %(message)s",
        datefmt="%d/%m/%Y %I:%M:%S%p",
    )

    fileHandler = TemporaryFolderLogHandler()
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


def wait_cli_to_finish(cli_entity, timeout_sec: int = 3600) -> None:
    """Lock thread until respective CLI node or queue is not busy anymore.

    Args:
        cli_entity (slicer.vtkMRMLCommandLineModuleNode or commons.slicer.CliQueue): the CLI entity object,
        timeout_sec (int, optional): the timeout in seconds. Defaults to 3600 seconds.
    """
    if cli_entity is None:
        return

    start = time.perf_counter()
    try:
        while cli_entity.IsBusy():
            time.sleep(0.200)
            process_events()

            if time.perf_counter() - start >= timeout_sec:
                cli_entity.Cancel()
                raise TimeoutError("CLI timeout reached!")
    except TimeoutException:
        cli_entity.Cancel()
        raise TimeoutError("Test timeout reached!")

    # IsBusy() becoming False does not guarantee the ModifiedEvent callback has
    # been dispatched yet in the new Slicer base. The CLI polling timer fires
    # asynchronously, so sleep briefly between flushes to give it time to queue
    # the ModifiedEvent before each process_events() call.
    for _ in range(5):
        time.sleep(0.200)
        process_events()


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

    if path == Path(slicer.mrmlScene.GetURL()):
        return True

    status = False
    with WatchSignal(signal=slicer.mrmlScene.EndImportEvent, timeout_ms=timeout_ms):
        status = ProjectManager().load(path)

    return status


@contextlib.contextmanager
def check_for_message_box(
    message, should_accept: bool = True, timeout_sec: int = 2, buttonTextToClick: str = None, closeOthers: bool = True
):
    """Context manager to handle the displaying of a QMessageBox during a test scenario

    Args:
        message (str): the expected QMessageBox text
        should_accept (bool, optional): Click the box's Accept-role button (e.g. Yes/Ok) if True,
                                       otherwise its Reject-role button (e.g. No/Cancel). Ignored
                                       when buttonTextToClick is given. Defaults to True.
        timeout_sec (int, optional): Timeout to wait for the message box to appear, in seconds. Defaults to 2.
        buttonTextToClick (str, optional): The button text to click. Defaults to None.
        closeOthers (:bool, optional): Close other visible message boxes.
                                       It might help to disable it when chaining multiple contexts to check
                                       for a message box. Defaults to True.

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

        mw = slicer.modules.AppContextInstance.mainWindow
        message_boxes = mw.findChildren(qt.QMessageBox)
        the_message_box = None

        related_message_boxes = [msg_box for msg_box in message_boxes if msg_box.visible and message in msg_box.text]
        logging.debug(f"Found {len(related_message_boxes)} message boxes with the text: '{message}'")

        if len(related_message_boxes) <= 0:
            # Find possible visible QMessageBox and close it to avoid freezing the test process
            other_message_boxes = [msg_box for msg_box in message_boxes if msg_box.visible]
            for message_box in other_message_boxes:
                logging.info(f"A different message box had appeared with the text: '{message_box.text}'")
                if closeOthers:
                    message_box.reject()

            if time.perf_counter() - start_time < timeout_sec:
                timer.start()
            return

        the_message_box = related_message_boxes[0]

        if not buttonTextToClick:
            roles = (
                (qt.QMessageBox.AcceptRole, qt.QMessageBox.YesRole)
                if should_accept
                else (qt.QMessageBox.RejectRole, qt.QMessageBox.NoRole)
            )
            the_button = next(
                (button for button in the_message_box.buttons() if the_message_box.buttonRole(button) in roles),
                None,
            )

            if the_button is not None:
                logging.debug(
                    f"Clicking the '{'accept' if should_accept else 'reject'}'-role button on the message box with the text: '{the_message_box.text}'"
                )
                the_button.click()
            elif should_accept:
                logging.debug(f"Accepting the message box with the text: '{the_message_box.text}'")
                the_message_box.accept()
            else:
                logging.debug(f"Rejecting the message box with the text: '{the_message_box.text}'")
                the_message_box.reject()
        else:
            the_button = None
            for button in the_message_box.buttons():
                if button.text != buttonTextToClick:
                    continue

                the_button = button

            if the_button is None:
                logging.error(f"The message box button {buttonTextToClick} doesn't exist in the current context.")
                the_message_box.reject()
            else:
                logging.debug(f"Clicking on the message box button with the text: '{the_button.text}'")
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
    timer.deleteLater()
    timer = None

    if result[0] is False:
        logging.error(
            f"Timed out waiting for the message box with the text: '{message}'. Please check if the the message box instance and its parents has a valid parent."
        )
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
        shutil.rmtree(project_path.parent, onexc=make_directory_writable)
    elif project_path.is_dir():
        shutil.rmtree(project_path, onexc=make_directory_writable)
    else:
        if project_path.parent.is_dir() and project_path.suffix == ".mrml":
            shutil.rmtree(project_path.parent, onexc=make_directory_writable)

    status = False
    with WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=timeout_ms):
        status = ProjectManager().saveAs(project_path.parent, properties=properties) == SaveStatus.SUCCEED

    return status


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

    status = False
    with WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=timeout_ms):
        status = ProjectManager().save(url, properties=properties) == SaveStatus.SUCCEED

    return status


def close_project(timeout_ms: int = 300000) -> None:
    with WatchSignal(signal=slicer.mrmlScene.EndCloseEvent, timeout_ms=timeout_ms):
        ProjectManager().close()

    process_events()


def compare_ignore_line_endings(file1, file2):
    with open(file1, "r") as f1:
        with open(file2, "r") as f2:
            return f1.read().replace("\r\n", "\n") == f2.read().replace("\r\n", "\n")


def handleFileDialog(accept: bool = True, directory: Path = None, projectName: str = None) -> None:
    fileDialog = None

    existentFileDialogs = [widget for widget in slicer.app.topLevelWidgets() if isinstance(widget, qt.QFileDialog)]
    if len(existentFileDialogs) == 0:
        raise RuntimeError("File dialog wasn't detected.")
    elif len(existentFileDialogs) > 1:
        logging.warning(f"Found {len(existentFileDialogs)} file dialogs. Check if this is the expected behavior.")

    visibleFileDialogs = [widget for widget in existentFileDialogs if widget.visible is True]

    if len(visibleFileDialogs) == 0:
        raise RuntimeError("A file dialog is instancied but wasn't visible.")

    fileDialog = visibleFileDialogs[0]

    if not accept:
        fileDialog.reject()
        return

    wait(1)
    fileDialog.setDirectory(qt.QDir(directory.as_posix()))
    fileNameEdit = fileDialog.findChild("QLineEdit")
    fileNameEdit.setText(projectName)
    wait(0.2)
    fileDialog.accept()
    wait(0.2)


def loadEnvironmentByName(displayName):
    slicer.modules.AppContextInstance.modules.loadEnvironmentByName(
        slicer.util.mainWindow().findChild("QToolBar", "ModuleToolBar"), displayName
    )


def loadAllModules():
    groups = slicer.modules.AppContextInstance.modules.groups
    modules = {obj.key: obj for sublist in groups.values() for obj in sublist}
    modules = list(modules.values())
    loadModules(modules)

    moduleManager = slicer.modules.AppContextInstance.modules
    if moduleManager.currentWorkingDataType is None:
        moduleManager.setEnvironment(("Thin Section", "ThinSectionEnv"))


def waitCondition(condition: Callable, timeoutSec: int = 5) -> None:
    """Sleeps until a condition is met.

    Args:
        condition (Callable): A function that returns True when the process is finished, otherwise it should returns False
        timeoutSec (int): The time limit to wait for the condition to happen.
    """
    start = time.perf_counter()
    while time.perf_counter() - start < timeoutSec and not condition():
        time.sleep(0.2)
        process_events()


def showTableInLayout(tableNode: slicer.vtkMRMLTableNode, layout: int) -> "slicer.qMRMLTableView":
    """Switch to a layout that has a table view, show the table in it and return the view.

    Args:
        tableNode (slicer.vtkMRMLTableNode): the table to show.
        layout (int): a layout with a table view, e.g. slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpTableView.
    """
    layoutManager = slicer.app.layoutManager()
    layoutManager.setLayout(layout)
    slicer.app.applicationLogic().GetSelectionNode().SetActiveTableID(tableNode.GetID())
    slicer.app.applicationLogic().PropagateTableSelection()
    process_events()
    return layoutManager.tableWidget(0).tableView()


def clickSubjectHierarchyVisibility(treeView: slicer.qMRMLSubjectHierarchyTreeView, node: slicer.vtkMRMLNode) -> None:
    """Left-clicks the visibility (eye) icon of the node's row, as the user would."""
    itemID = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemByDataNode(node)
    index = treeView.sortFilterProxyModel().indexFromSubjectHierarchyItem(itemID, treeView.model().visibilityColumn)
    treeView.scrollTo(index)
    rect = treeView.visualRect(index)
    # The eye icon is square and left-aligned in its cell
    position = qt.QPointF(rect.left() + rect.height() / 2, rect.center().y())
    for eventType, buttons in (
        (qt.QEvent.MouseButtonPress, qt.Qt.LeftButton),
        (qt.QEvent.MouseButtonRelease, qt.Qt.NoButton),
    ):
        event = qt.QMouseEvent(eventType, position, qt.Qt.LeftButton, buttons, qt.Qt.NoModifier)
        qt.QApplication.sendEvent(treeView.viewport(), event)
    process_events()


def getNodeName(node: slicer.vtkMRMLNode) -> str:
    if node is None:
        return "None"

    return node.GetName()


def getPlatformProjectPath(base_project_path: Union[str, Path], check_exists=True) -> Path:
    path = Path(base_project_path)
    parent_dir = path.parent
    platform = "LINUX" if sys.platform.startswith("linux") else "WIN"
    new_dir_name = f"{parent_dir.name}_{platform}"
    new_file_name = f"{path.stem}_{platform}{path.suffix}"
    platform_path = path.parent.parent / new_dir_name / new_file_name
    if check_exists and not platform_path.exists():
        return path
    return platform_path
