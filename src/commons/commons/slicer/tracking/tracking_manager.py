import logging
import slicer

from datetime import datetime
from commons.slicer.tracking.trackers.widget_tracker import WidgetTracker
from commons.slicer.tracking.trackers.module_tracker import ModuleTracker
from commons.slicer.tracking.trackers.volume_node_tracker import VolumeNodeTracker
from commons.slicer.tracking.trackers.scene_tracker import SceneTracker
from commons.slicer import helpers
from typing import List
from pathlib import Path


class TrackingManager:
    def __init__(self) -> None:
        self.__trackers = [WidgetTracker(), ModuleTracker(), VolumeNodeTracker(), SceneTracker()]

    def _createLogger(self) -> None:
        """Create logger for the tracking feature."""
        logger = logging.getLogger("tracking")

        # Remove any previous handler
        for handler in logger.handlers:
            logger.removeHandler(handler)

        logger.propagate = False

        # Create and add the file handler
        formatter = logging.Formatter(
            "[%(levelname)s] %(asctime)s - %(name)s: %(message)s",
            datefmt="%d/%m/%Y %I:%M:%S%p",
        )

        now = datetime.now()
        datetimeString = now.strftime("%Y%m%d_%H%M%S_%f")
        suffix = "tracking"
        logFilePath = Path(slicer.app.temporaryPath) / f"{suffix}_{datetimeString}.log"

        helpers.limitLogFiles(logFilePath.parent, f"{suffix}_", 20)

        fileHandler = logging.FileHandler(logFilePath, mode="a", delay=True)
        fileHandler.setLevel(logging.INFO)
        fileHandler.setFormatter(formatter)
        logger.addHandler(fileHandler)

    def installTrackers(self) -> None:
        """Install all trackers."""
        # Created here rather than on construction, which happens before slicerrc moves the temporary folder out of
        # the installation. The bug report looks for the logs in the current temporary folder
        self._createLogger()
        for tracker in self.__trackers:
            tracker.install()

    def uninstallTrackers(self) -> None:
        """Uninstall all trackers."""
        for tracker in self.__trackers:
            tracker.uninstall()

    def getRecentLogs(self) -> List[Path]:
        """Retrieve the most recent logs

        Returns:
            List[Path]: The list of Path object related to the recent logs.
        """
        userSettings = slicer.app.userSettings()
        filesNumber = userSettings.value("LogFiles/NumberOfFilesToKeep")
        filesList = list(Path(slicer.app.temporaryPath).glob("tracking_*.log"))
        filesList.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        return filesList[: int(filesNumber)] if filesNumber is not None else filesList
