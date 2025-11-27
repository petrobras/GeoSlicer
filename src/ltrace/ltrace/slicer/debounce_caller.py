from PySide2.QtCore import QObject as PS2_QObject
from PySide2.QtCore import QTimer as PS2_QTimer
from PySide2.QtCore import Signal as PS2_Signal
from PySide2.QtWidgets import QWidget as PS2_QWidget
from typing import Union

import qt


class ADebounceCaller:
    """
    Wrapper for qt.Signal emits and method calls with debouncing effect,
    emiting the signal/calling the method only one time after a given interval.
    """

    def __init__(
        self,
        qtTimer,
        intervalMs: int = 500,
    ) -> None:
        self.timer = qtTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(intervalMs)
        self.timer.timeout.connect(self.__onTimeout)
        self.timer.stop()
        self.__args = []
        self.__kwargs = {}
        self.destroyed.connect(self.__del__)

    def __del__(self):
        self.stop()
        try:
            self.timer.deleteLater()
        except (AttributeError, ValueError):  # Timer has been deleted
            pass

        self.timer = None
        self.__args = []
        self.__kwargs = {}

    def emitSignal(self, *args, **kwargs) -> None:
        self.__args = args
        self.__kwargs = kwargs

        try:
            if self.timer.isActive():
                self.timer.stop()

            self.timer.start()
        except ValueError:  # timer or parent has been deleted
            pass

    def __call__(self, *args, **kwargs):
        self.emitSignal(*args, **kwargs)

    def __onTimeout(self) -> None:
        if self.__args or self.__kwargs:
            self.triggered.emit(*self.__args, **self.__kwargs)
        else:
            self.triggered.emit(None, None)

        self.__args = []
        self.__kwargs = {}

    def stop(self):
        try:
            if self.timer.isActive():
                self.timer.stop()
        except (AttributeError, ValueError):  # timer or parent has been deleted
            pass


class DebounceCallerMetaPythonQT(type(qt.QObject), type(ADebounceCaller)):
    pass


class DebounceCaller(qt.QObject, ADebounceCaller, metaclass=DebounceCallerMetaPythonQT):
    triggered = qt.Signal(object, object)

    def __init__(self, parent: Union[qt.QWidget, qt.QObject], intervalMs: int = 500):
        qt.QObject.__init__(self, parent)
        ADebounceCaller.__init__(self, qtTimer=qt.QTimer, intervalMs=intervalMs)


class DebounceCallerMetaPS2(type(PS2_QObject), type(ADebounceCaller)):
    pass


class DebounceCallerPS2(PS2_QObject, ADebounceCaller, metaclass=DebounceCallerMetaPS2):
    triggered = PS2_Signal(object, object)

    def __init__(self, parent: Union[PS2_QWidget, PS2_QObject], intervalMs: int = 500):
        PS2_QObject.__init__(self, parent)
        ADebounceCaller.__init__(self, qtTimer=PS2_QTimer, intervalMs=intervalMs)
