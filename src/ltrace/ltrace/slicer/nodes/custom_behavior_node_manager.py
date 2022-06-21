import slicer
from .custom_behavior_node_factory import CustomBehaviorNodeFactory
from .custom_behavior_node_base import CustomBehaviorNodeBase
from .defs import TriggerEvent


class CustomBehaviorNodeManager:
    """Class to handle custom behavior node initialization and runtime operation."""

    def __init__(self) -> None:
        self.__triggerEvent: TriggerEvent = TriggerEvent.NONE
        self.__customBehaviorNodeObservers = []
        self.__installCustomBehaviorNodeObservers()

    def __del__(self) -> None:
        self.__uninstallCustomBehaviorNodeObservers()

    @property
    def triggerEvent(self) -> TriggerEvent:
        return self.__triggerEvent

    @triggerEvent.setter
    def triggerEvent(self, triggerEvent: TriggerEvent):
        if self.__triggerEvent == triggerEvent:
            return

        self.__triggerEvent = triggerEvent

    def reset(self) -> None:
        self.__triggerEvent = TriggerEvent.NONE

    def __installCustomBehaviorNodeObservers(self) -> None:
        if len(self.__customBehaviorNodeObservers) > 0:
            self.__uninstallCustomBehaviorNodeObservers()

        self.__customBehaviorNodeObservers.extend(
            [
                slicer.mrmlScene.AddObserver(
                    slicer.mrmlScene.EndImportEvent, lambda x, y: self.behaviorCallback(method="afterLoad")
                ),
                slicer.mrmlScene.AddObserver(
                    slicer.mrmlScene.StartSaveEvent, lambda x, y: self.behaviorCallback(method="beforeSave")
                ),
                slicer.mrmlScene.AddObserver(
                    slicer.mrmlScene.EndSaveEvent, lambda x, y: self.behaviorCallback(method="afterSave")
                ),
            ]
        )

    def __uninstallCustomBehaviorNodeObservers(self) -> None:
        for observer in self.__customBehaviorNodeObservers:
            slicer.mrmlScene.RemoveObserver(observer)

        self.__customBehaviorNodeObservers.clear()

    def behaviorCallback(self, method: str) -> None:
        for node in self._getCustomBehaviorNodes():
            if hasattr(node, method):
                callback = getattr(node, method)
                callback()

        self.reset()

    def _getCustomBehaviorNodes(self) -> CustomBehaviorNodeBase:
        for _, node in slicer.util.getNodes().items():
            try:
                CustomBehaviorNode = CustomBehaviorNodeFactory.factory(node, event=self.__triggerEvent)
            except ValueError:
                continue

            yield CustomBehaviorNode
