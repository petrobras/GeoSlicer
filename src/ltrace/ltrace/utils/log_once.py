from collections import OrderedDict
from typing import Callable


class LogOnce:
    """Log each distinct message once, remembering at most `capacity` of them.

    For code that runs on a timer: without it, an error that recurs on every
    tick fills the log for as long as the application sits idle. Once full,
    the oldest remembered message is forgotten, so a message can be logged
    again after `capacity` other ones.
    """

    def __init__(self, log: Callable[[str], None], capacity: int = 32) -> None:
        self._log = log
        self._capacity = capacity
        # An ordered set: the values are unused.
        self._logged = OrderedDict()

    def __call__(self, message: str) -> bool:
        """Log the message unless it already was. Returns whether it was logged."""
        if message in self._logged:
            return False

        self._logged[message] = None
        if len(self._logged) > self._capacity:
            self._logged.popitem(last=False)

        self._log(message)
        return True
