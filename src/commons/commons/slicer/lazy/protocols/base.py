from abc import ABC, abstractclassmethod

import xarray as xr

from commons.remote.hosts.base import Host


class BaseProtocol(ABC):
    PROTOCOL = ""

    def __init__(self, url) -> None:
        super().__init__()
        self.__url = url

    def __init_subclass__(cls):
        attrName = "PROTOCOL"
        if attrName not in cls.__dict__ or getattr(cls, attrName).replace(" ", "") == "":
            raise NotImplementedError(f"Missing defition of '{attrName}' in the class '{cls.__name__}'")

    @property
    def url(self):
        return self.__url

    @abstractclassmethod
    def load(self, *args, **kwargs) -> "xr.Dataset":
        pass

    @staticmethod
    def host(*args, **kwargs) -> Host:
        return Host("", "")
