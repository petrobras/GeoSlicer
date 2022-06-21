import json
import logging
from typing import Callable

from abc import ABC, abstractmethod
from functools import partial

import time


class AbstractTask(ABC):
    @staticmethod
    @abstractmethod
    def get_name():
        pass

    def __init__(self):

        self.logger = logging.getLogger("tasks.core.%s" % self.get_name())

        self.started = None
        self.elapsed = None

    def service(self):
        """
        Called to execute the task.
        Subclasses must implement :meth:`_do_service`
        """
        try:
            self.started = time.time()

            try:
                self._do_service()
            except Exception as e:
                self.logger.exception(e)

        finally:
            self.elapsed = time.time() - self.started

    @abstractmethod
    def execute(self):
        self.service()

    @abstractmethod
    def cancel(self) -> None:
        pass

    @abstractmethod
    def _do_service(self):
        raise NotImplementedError()

    @staticmethod
    @abstractmethod
    def from_json(js: str):
        raise NotImplementedError()

    @abstractmethod
    def to_dict(self):
        raise NotImplementedError()

    @abstractmethod
    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class AsyncTask(AbstractTask):

    DONE = 0
    RUNNING = 1
    DONE_WITH_ERROR = 2
    CANCELLED = 3
    IDLE = 4

    def __init__(self) -> None:
        super().__init__()

        self._id = ""
        self.current_state = None

    @property
    def id(self) -> str:
        return self._id

    def execute(self):
        while True:
            self.service()
            if self.current_state != self.RUNNING:
                return
