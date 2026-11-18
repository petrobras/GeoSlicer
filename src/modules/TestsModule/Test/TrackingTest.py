import slicer
import tempfile
import shutil
import numpy as np
import logging

from commons.slicer_utils import LTracePluginTest
from commons.slicer.tests.utils import wait, save_project, save_current_project, close_project
from commons.slicer import helpers
from commons.slicer.tracking.tracking_manager import TrackingManager
from pathlib import Path
from typing import List, TYPE_CHECKING
from unittest.mock import DEFAULT, patch

if TYPE_CHECKING:
    from commons.slicer.project_manager import ProjectManager


def getProjectManagerInstance() -> "ProjectManager":
    from commons.slicer.project_manager import ProjectManager

    return ProjectManager()


def readLog(log_file_path: Path) -> List[str]:
    with open(log_file_path, "r", encoding="utf-8") as log_file:
        return log_file.readlines()


def logExists(logs: List[str], logMessage: str, exactly: bool = False) -> bool:
    if exactly:
        return logMessage in logs

    for log in logs:
        if logMessage not in log:
            continue

        return True

    return False


def clearLog(logFile: Path) -> None:
    with open(logFile, "w"):
        pass


class TrackingTest(LTracePluginTest):
    def post_setup(self) -> None:
        # Create the temporary directory used to store the test files
        self.__tempProjectDirPath = Path(tempfile.mkdtemp()).resolve()
        self.__tempLogFilePath = self.__tempProjectDirPath / "tracking.log"

        # Add temporary file handler to the tracking logger
        self.__logger = logging.getLogger("tracking")
        self.__fileHandler = logging.FileHandler(self.__tempLogFilePath, mode="a")
        self.__logger.addHandler(self.__fileHandler)

    def tear_down(self) -> None:
        # Remove temporary file handler to the tracking logger
        self.__fileHandler.close()
        self.__logger.removeHandler(self.__fileHandler)

        # Remove the temporary directory used to store the test files
        if self.__tempProjectDirPath.exists():
            shutil.rmtree(self.__tempProjectDirPath, onexc=helpers.make_directory_writable)

    def test_module_tracker(self) -> None:
        moduleNames = ["Charts", "NetCDF"]
        for moduleName in moduleNames:
            slicer.util.selectModule(moduleName)
            wait(0.5)

        logLines = readLog(self.__tempLogFilePath)

        def check_module_change(text, logLines):
            linesWithText = [line for line in logLines if text in line]
            return len(linesWithText)

        assert check_module_change("Changed to module: Charts", logLines), f"Missing module change log:\n{logLines}"
        assert check_module_change("Changed to module: NetCDF", logLines), f"Missing module change log:\n{logLines}"
        assert len(logLines) == 2, f"Expected 2 log lines only, but it has {len(logLines)} lines"

    def test_volume_node_tracker_scalar_node(self) -> None:
        # Create a scalar volume node
        scalarVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")

        # Modify scalar volume node
        arr = np.zeros((3, 3))
        slicer.util.updateVolumeFromArray(scalarVolumeNode, arr)
        wait(1)

        # Remove scalar volume node from scene
        slicer.mrmlScene.RemoveNode(scalarVolumeNode)

        # Assert logs
        logLines = readLog(self.__tempLogFilePath)
        assert (
            total_lines := len([line for line in logLines if "[VolumeNodeTracker] Volume node added:" in line])
        ) == 1, f"Expected {1} log from node added, but got {total_lines}\nlogs:\n{logLines}"
        assert (
            total_lines := len([line for line in logLines if "[VolumeNodeTracker] Volume node modified:" in line])
        ) == 1, f"Expected {1} log from node modified, but got {total_lines}\nlogs:\n{logLines}"
        assert (
            total_lines := len([line for line in logLines if "[VolumeNodeTracker] Volume node removed:" in line])
        ) == 1, f"Expected {1} log from node removed, but got {total_lines}\nlogs:\n{logLines}"

    def test_volume_node_tracker_label_map_node(self) -> None:
        # Create a scalar volume node
        scalarVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")

        # Modify scalar volume node
        arr = np.zeros((3, 3))
        slicer.util.updateVolumeFromArray(scalarVolumeNode, arr)
        wait(1)

        # Remove scalar volume node from scene
        slicer.mrmlScene.RemoveNode(scalarVolumeNode)

        # Assert logs
        logLines = readLog(self.__tempLogFilePath)
        assert (
            total_lines := len([line for line in logLines if "[VolumeNodeTracker] Volume node added:" in line])
        ) == 1, f"Expected {1} log from node added, but got {total_lines}\nlogs:\n{logLines}"
        assert (
            total_lines := len([line for line in logLines if "[VolumeNodeTracker] Volume node modified:" in line])
        ) == 1, f"Expected {1} log from node modified, but got {total_lines}\nlogs:\n{logLines}"
        assert (
            total_lines := len([line for line in logLines if "[VolumeNodeTracker] Volume node removed:" in line])
        ) == 1, f"Expected {1} log from node removed, but got {total_lines}\nlogs:\n{logLines}"

    def test_volume_node_tracker_vector_node(self) -> None:
        # Create a scalar volume node
        scalarVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode")

        # Modify scalar volume node
        arr = np.zeros((3, 3))
        slicer.util.updateVolumeFromArray(scalarVolumeNode, arr)
        wait(1)

        # Remove scalar volume node from scene
        slicer.mrmlScene.RemoveNode(scalarVolumeNode)

        # Assert logs
        logLines = readLog(self.__tempLogFilePath)
        assert (
            total_lines := len([line for line in logLines if "[VolumeNodeTracker] Volume node added:" in line])
        ) == 1, f"Expected {1} log from node added, but got {total_lines}\nlogs:\n{logLines}"
        assert (
            total_lines := len([line for line in logLines if "[VolumeNodeTracker] Volume node modified:" in line])
        ) == 1, f"Expected {1} log from node modified, but got {total_lines}\nlogs:\n{logLines}"
        assert (
            total_lines := len([line for line in logLines if "[VolumeNodeTracker] Volume node removed:" in line])
        ) == 1, f"Expected {1} log from node removed, but got {total_lines}\nlogs:\n{logLines}"

    def test_scene_tracker(self) -> None:
        projectFilePath = self.__tempProjectDirPath / "test" / "test.mrml"

        # 'Save as' process
        assert save_project(projectFilePath), "Failed to save temporary project."

        logs = readLog(self.__tempLogFilePath)
        assert len(logs) > 0, "No logs were registered."

        assert logExists(logs, "Starting the save project process: ")
        assert logExists(logs, "Finished the save project process: ")
        assert logExists(logs, "Starting the load project process: ")
        assert logExists(logs, "Finished the load project process: ")
        assert not logExists(logs, "Starting the close project process: ")
        assert not logExists(logs, "Finished the close project process: ")

        # Clean logs
        clearLog(self.__tempLogFilePath)

        # Modify project to be able to save it
        slicer.mrmlScene.CreateNodeByClass("vtkMRMLLabelMapVolumeNode").UnRegister(None)

        # 'Save' process
        assert save_current_project(), "Failed to save temporary project."

        logs = readLog(self.__tempLogFilePath)
        assert len(logs) > 0, "No logs were registered."

        assert logExists(logs, "Starting the save project process: ")
        assert logExists(logs, "Finished the save project process: ")
        assert not logExists(logs, "Starting the load project process: ")
        assert not logExists(logs, "Finished the load project process: ")
        assert not logExists(logs, "Starting the close project process: ")
        assert not logExists(logs, "Finished the close project process: ")

    def test_volume_tracker_deleting_observers_when_node_is_removed(self):
        pm = getProjectManagerInstance()
        observers = pm._ProjectManager__nodeObservers

        currentObserversLen = len(observers)

        nodesId = []
        for i in range(3):
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode")
            nodesId.append(node.GetID())
        wait(1)

        observers = pm._ProjectManager__nodeObservers
        assert len(observers) == currentObserversLen + 3, (
            f"Expected {currentObserversLen + 3} observers, but got {len(observers)}"
        )

        close_project()

        for nodeId in nodesId:
            assert helpers.tryGetNode(nodeId) is None

        observers = pm._ProjectManager__nodeObservers

        assert len(observers) == currentObserversLen, (
            f"Expected {currentObserversLen} observers, but got {len(observers)}"
        )

    def test_log_in_temporary_path_set_after_creation(self):
        """On the first launch after an upgrade, AppContext creates the tracking manager before slicerrc moves the
        temporary folder out of the installation. The log must be written where the bug report looks for it."""
        oldTemporaryPath = self.__tempProjectDirPath / "old"
        newTemporaryPath = self.__tempProjectDirPath / "new"
        oldTemporaryPath.mkdir()
        newTemporaryPath.mkdir()
        handlers = list(self.__logger.handlers)
        trackers = {name: DEFAULT for name in ["WidgetTracker", "ModuleTracker", "VolumeNodeTracker", "SceneTracker"]}
        try:
            with patch.multiple("commons.slicer.tracking.tracking_manager", slicer=DEFAULT, **trackers) as mocks:
                mocks["slicer"].app.temporaryPath = str(oldTemporaryPath)
                mocks["slicer"].app.userSettings().value.return_value = None
                trackingManager = TrackingManager()

                mocks["slicer"].app.temporaryPath = str(newTemporaryPath)
                trackingManager.installTrackers()
                self.__logger.info("Tracked action")

                recentLogs = trackingManager.getRecentLogs()
        finally:
            for handler in self.__logger.handlers:
                handler.close()
            self.__logger.handlers = handlers

        assert len(recentLogs) == 1 and recentLogs[0].parent == newTemporaryPath, f"Unexpected logs: {recentLogs}"
        assert logExists(readLog(recentLogs[0]), "Tracked action")
        assert not list(oldTemporaryPath.iterdir())
