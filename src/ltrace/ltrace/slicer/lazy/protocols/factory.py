import importlib
import logging
import re

from ltrace.slicer.lazy.protocols.base import BaseProtocol
from pathlib import Path
from typing import Union, List


class ProtocolFactory:
    PROTOCOLS_DIR = Path(__file__).parent

    @staticmethod
    def build(url: str) -> BaseProtocol:
        try:
            protocol, path = url.split("://")
        except ValueError:
            raise ValueError("Invalid url pattern.")

        formatedProtocol = ProtocolFactory._parse_protocol_string(protocol)
        protocols = ProtocolFactory._get_protocol_subclasses()

        for protoCls in protocols:
            if protoCls.PROTOCOL != formatedProtocol:
                continue

            return protoCls(url=url)

        raise ValueError(f"Unable to find valid protocol that matches the {formatedProtocol} specification.")

    @staticmethod
    def _parse_protocol_string(protocol: str) -> str:
        return re.sub("[^a-zA-Z0-9 \n]", "", protocol).replace(" ", "")

    @staticmethod
    def _get_protocol_subclasses_from_module(module: "module") -> List[BaseProtocol]:
        classes = []
        for attribute in dir(module):
            attr = getattr(module, attribute)
            try:
                if issubclass(attr, BaseProtocol) and attr != BaseProtocol:
                    logging.debug(f"{attr.__name__} is a subclass of 'BaseProtocol'")
                    classes.append(attr)
            except Exception:
                continue

        return classes

    @staticmethod
    def _get_module_from_path(path: Path) -> Union["module", None]:
        try:
            spec = importlib.util.spec_from_file_location(path.stem, path.as_posix())
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except FileNotFoundError:
            logging.error(f"File not found at path: {path}")
            return None
        except Exception as e:
            logging.error(f"Error loading module from {path.as_posix()}: {e}")
            return None

    @staticmethod
    def _get_modules() -> List[Path]:
        modules = []
        for file in ProtocolFactory.PROTOCOLS_DIR.rglob("*.py"):
            module = ProtocolFactory._get_module_from_path(file)
            if module:
                modules.append(module)
        return modules

    @staticmethod
    def _get_protocol_subclasses() -> List[BaseProtocol]:
        modules = ProtocolFactory._get_modules()
        subclasses = []
        for module in modules:
            subcls = ProtocolFactory._get_protocol_subclasses_from_module(module)
            subclasses.extend(subcls)

            if not subcls:
                del module

        return subclasses
