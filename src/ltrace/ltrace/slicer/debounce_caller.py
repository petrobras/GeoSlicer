import logging
import qt

from typing import Union


class DebounceCaller:
    """
    Wrapper for qt.Signal emits and method calls with debouncing effect,
    emiting the signal/calling the method only one time after a given interval.
    """

    def __init__(
        self,
        parent: Union[qt.QWidget, qt.QObject],
        signal: qt.Signal = None,
        callback=None,
        intervalMs: int = 500,
        qtTimer=qt.QTimer,
    ) -> None:
        assert signal is not None or callback is not None, "Use either signal or callback."
        assert parent is not None, "Invalid parent reference."

        self.__signal = signal
        self.__callback = callback
        self.__useSignal = signal is not None
        self.timer = qtTimer(parent)
        self.timer.setSingleShot(True)
        self.timer.setInterval(intervalMs)
        self.timer.timeout.connect(self.__onTimeout)
        self.timer.stop()
        self.__args = None
        self.__kwargs = None

    def emit(self, *args, **kwargs) -> None:
        self.__args = args
        self.__kwargs = kwargs

        try:
            if self.timer.isActive():
                self.timer.stop()

            self.timer.start()
        except ValueError:  # timer or parent has been deleted
            pass

    def __call__(self, *args, **kwargs):
        self.emit(*args, **kwargs)

    def __onTimeout(self) -> None:
        try:
            if self.__useSignal:
                self.__signal.emit(*self.__args, **self.__kwargs)
            else:
                if self.__args is None and self.__kwargs is None:
                    self.__callback()
                elif self.__kwargs is None:
                    self.__callback(*self.__args)
                elif self.__args is None:
                    self.__callback(**self.__kwargs)
                else:
                    self.__callback(*self.__args, **self.__kwargs)
        except Exception as error:
            logging.info(f"Failed to execute the call: {error}")

        self.__args = None
        self.__kwargs = None

    def stop(self):
        try:
            if self.timer.isActive():
                self.timer.stop()
        except ValueError:  # timer or parent has been deleted
            pass
