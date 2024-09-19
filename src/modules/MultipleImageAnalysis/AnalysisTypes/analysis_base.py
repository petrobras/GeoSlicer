from abc import abstractmethod
from dataclasses import dataclass
from typing import Union, List

import qt
import slicer


FILE_NOT_FOUND = "FILE NOT FOUND"


@dataclass
class AnalysisReport:
    name: str
    data: object
    config: dict


class AnalysisWidgetBase(qt.QWidget):
    outputNameChangedSignal = qt.Signal()
    configModified = qt.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setupModifiedDebounceTimer()
        self.setup()

    def setupModifiedDebounceTimer(self) -> None:
        """Create timer to avoid multiple sequential triggers of the 'configModified' signal."""
        self.modifiedBounceTimer = qt.QTimer(self)
        self.modifiedBounceTimer.setSingleShot(True)
        self.modifiedBounceTimer.timeout.connect(self.configModified)
        self.modifiedBounceTimer.setInterval(500)

    @classmethod
    @abstractmethod
    def setup(self) -> None:
        pass

    @classmethod
    @abstractmethod
    def updateReportParameters(self, parameters: List) -> None:
        pass

    def modified(self) -> None:
        """Wrapper for 'configModified' signal. Use it when you need to emit the 'configModified' signal."""
        if self.modifiedBounceTimer.isActive():
            self.modifiedBounceTimer.stop()

        self.modifiedBounceTimer.start()

    @classmethod
    @abstractmethod
    def resetConfiguration(self) -> None:
        pass


class AnalysisBase(qt.QObject):
    configModified = qt.Signal()

    def __init__(self, parent: Union[qt.QObject, qt.QWidget], name: str, configWidget: AnalysisWidgetBase):
        super().__init__(parent)
        self._name = name
        self._config_widget = configWidget
        self._config_widget.configModified.connect(self.configModified)
        self._reports = list()

    @property
    def name(self) -> str:
        return self._name

    @property
    def configWidget(self) -> AnalysisWidgetBase:
        return self._config_widget

    @classmethod
    @abstractmethod
    def run(self, path: str, name: str) -> AnalysisReport:
        pass

    @classmethod
    @abstractmethod
    def getSuggestedOutputName(self) -> str:
        pass

    @classmethod
    @abstractmethod
    def refreshInputReportfiles(self, folder: str) -> "pd.DataFrame":
        pass

    def resetConfiguration(self) -> None:
        self.configWidget.resetConfiguration()
