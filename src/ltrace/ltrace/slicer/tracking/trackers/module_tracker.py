from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.slicer.tracking.tracker import Tracker


class ModuleTracker(Tracker):
    def install(self) -> None:
        ApplicationObservables().moduleWidgetEnter.connect(self.__onLog)

    def uninstall(self) -> None:
        ApplicationObservables().moduleWidgetEnter.disconnect(self.__onLog)

    def __onLog(self, moduleObject):
        self.log(f"Changed to module: {moduleObject.moduleName}")
