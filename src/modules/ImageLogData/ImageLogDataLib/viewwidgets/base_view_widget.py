import qt

from abc import abstractmethod
from typing import Tuple


class BaseViewWidget(qt.QObject):
    signalUpdated = qt.Signal()

    @classmethod
    @abstractmethod
    def clear(self):
        pass

    @classmethod
    @abstractmethod
    def getBounds(self) -> Tuple:
        pass

    @classmethod
    @abstractmethod
    def getValue(self, x, y):
        pass

    @classmethod
    @abstractmethod
    def getGraphX(self, view_x, width):
        pass

    @classmethod
    @abstractmethod
    def set_range(self, current_range):
        pass

    @classmethod
    @abstractmethod
    def getPlot(self):
        pass
