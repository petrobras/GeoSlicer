"""URI parsing/formatting for deferred data sources.

The format follows the one already used by ``ltrace.slicer.lazy`` (``<scheme>://<path>``) and adds an
optional query string so a single URI can point at one variable of a multi-variable file, or at a 4D
dataset defined by a folder plus a frame pattern::

    file:///data/tomo.nc?var=microtom
    file:///data/recon_0                       (a directory read as an image stack)
    4d:///data/LBPM?pattern=vis%5Cd%2B&var=phase

Kept free of ``slicer``/``qt`` imports so it can be unit-tested headlessly.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict
from urllib.parse import urlencode, parse_qsl

SCHEME_FILE = "file"
SCHEME_FOURD = "4d"


class InvalidURIError(ValueError):
    pass


@dataclass(frozen=True)
class VirtualURI:
    scheme: str
    path: Path
    params: Dict[str, str] = field(default_factory=dict)

    @staticmethod
    def parse(text: str) -> "VirtualURI":
        if not text or "://" not in text:
            raise InvalidURIError(f"Not a virtual URI: {text!r}")

        scheme, _, remainder = text.partition("://")
        location, _, query = remainder.partition("?")

        if not location:
            raise InvalidURIError(f"URI without a path: {text!r}")

        return VirtualURI(scheme=scheme.lower(), path=Path(location), params=dict(parse_qsl(query)))

    def format(self) -> str:
        text = f"{self.scheme}://{self.path.as_posix()}"
        if self.params:
            text = f"{text}?{urlencode(self.params)}"
        return text

    def with_params(self, **params) -> "VirtualURI":
        merged = {**self.params, **{key: str(value) for key, value in params.items() if value is not None}}
        return VirtualURI(scheme=self.scheme, path=self.path, params=merged)

    @property
    def variable(self):
        return self.params.get("var")

    @property
    def pattern(self):
        return self.params.get("pattern")

    def __str__(self) -> str:
        return self.format()


def file_uri(path, variable: str = None, **params) -> str:
    """URI for a local file or directory."""
    return VirtualURI(scheme=SCHEME_FILE, path=Path(path)).with_params(var=variable, **params).format()


def fourd_uri(folder, pattern: str, variable: str = None, **params) -> str:
    """URI for a 4D dataset: a folder plus the pattern that defines its frames."""
    return (
        VirtualURI(scheme=SCHEME_FOURD, path=Path(folder)).with_params(pattern=pattern, var=variable, **params).format()
    )
