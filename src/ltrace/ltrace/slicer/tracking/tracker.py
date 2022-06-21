import logging

from abc import ABC, abstractclassmethod


class Tracker(ABC):
    def __init__(self) -> None:
        super().__init__()
        self.logger = logging.getLogger("tracking")

    def log(self, message: str) -> None:
        if not message:
            return

        self.logger.info(f"[{self.__class__.__name__}] {message}")

    @abstractclassmethod
    def install(self) -> None:
        pass

    @abstractclassmethod
    def uninstall(self) -> None:
        pass
