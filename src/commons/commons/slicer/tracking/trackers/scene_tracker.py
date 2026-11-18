import psutil
import slicer

from humanize import naturalsize
from commons.slicer import helpers
from commons.slicer.tracking.tracker import Tracker
from pathlib import Path
from typing import List, Tuple


class SceneTracker(Tracker):
    def __init__(self) -> None:
        super().__init__()
        self.__observers: List[Tuple[object, object]] = []

    def __getSceneData(self) -> dict:
        memoryRamUsageBytes = naturalsize(helpers.get_memory_usage())
        memoryRamUsagePercent = helpers.get_memory_usage(mode="percent")
        totalMemoryRam = naturalsize(psutil.virtual_memory().total)

        currentUrl = slicer.mrmlScene.GetURL()
        currenUrlDirectoryPath = Path(currentUrl).parent
        if currenUrlDirectoryPath.exists():
            diskUsage = psutil.disk_usage(Path(currentUrl).parent.as_posix())
            urlDiskSizeUsageBytes = naturalsize(diskUsage.used)
            urlDiskSizeUsagePercent = diskUsage.percent
            availableDiskSpace = naturalsize(diskUsage.free)
        else:
            urlDiskSizeUsageBytes = "N/A"
            urlDiskSizeUsagePercent = "N/A"
            availableDiskSpace = "N/A"

        return {
            "currentUrl": Path(currentUrl).as_posix(),
            "memoryRAMUsageBytes": memoryRamUsageBytes,
            "memoryRAMUsagePercent": memoryRamUsagePercent,
            "totalMemoryRAM": totalMemoryRam,
            "availableDiskSize": availableDiskSpace,
            "urlDiskSizeUsageBytes": urlDiskSizeUsageBytes,
            "urlDiskSizeUsagePercent": urlDiskSizeUsagePercent,
        }

    def install(self) -> None:
        self.__observers.append(
            (slicer.mrmlScene, slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartSaveEvent, self.__onStartSaveEvent))
        )
        self.__observers.append(
            (slicer.mrmlScene, slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndSaveEvent, self.__onEndSaveEvent))
        )

        self.__observers.append(
            (
                slicer.mrmlScene,
                slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartImportEvent, self.__onStartImportEvent),
            )
        )
        self.__observers.append(
            (slicer.mrmlScene, slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndImportEvent, self.__onEndImportEvent))
        )

        self.__observers.append(
            (slicer.mrmlScene, slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartCloseEvent, self.__onStartCloseEvent))
        )
        self.__observers.append(
            (slicer.mrmlScene, slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndCloseEvent, self.__onEndCloseEvent))
        )

    def __onStartSaveEvent(self, *args, **kwargs) -> None:
        self.log(f"Starting the save project process: {self.__getSceneData()}")

    def __onEndSaveEvent(self, *args, **kwargs) -> None:
        self.log(f"Finished the save project process: {self.__getSceneData()}")

    def __onStartImportEvent(self, *args, **kwargs) -> None:
        self.log(f"Starting the load project process: {self.__getSceneData()}")

    def __onEndImportEvent(self, *args, **kwargs) -> None:
        self.log(f"Finished the load project process: {self.__getSceneData()}")

    def __onStartCloseEvent(self, *args, **kwargs) -> None:
        self.log(f"Starting the close project process: {self.__getSceneData()}")

    def __onEndCloseEvent(self, *args, **kwargs) -> None:
        self.log(f"Finished the close project process: {self.__getSceneData()}")

    def uninstall(self) -> None:
        for obj, handler in self.__observers:
            obj.RemoveObserver(handler)

        self.__observers.clear()
