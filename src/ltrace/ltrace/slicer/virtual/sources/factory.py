"""Source factory: turns a path or virtual URI into the backend that can read it partially.

Detection is by content first and extension second, because extensions lie in this domain: LBPM writes
plain HDF5 rank files with an ``.h5`` extension that ``xarray`` cannot open, and whitespace-separated logs
with a ``.csv`` extension.
"""

import logging
from pathlib import Path
from typing import List, Optional, Type

from ..uri import SCHEME_FILE, SCHEME_FOURD, VirtualURI
from .base import UnsupportedSourceError, VirtualSource
from .images import ImageSource, ImageStackSource
from .lbpm_h5 import LbpmH5Source
from .netcdf_h5 import NetCdfSource
from .raw import RawSource
from .tables import TableSource

BACKENDS: List[Type[VirtualSource]] = [
    LbpmH5Source,  # before NetCdfSource: LBPM rank files are .h5 but not NetCDF
    NetCdfSource,
    ImageSource,
    RawSource,
    TableSource,
    ImageStackSource,  # directories, tried last so file backends win for files
]


def backend_for_path(path: Path) -> Optional[Type[VirtualSource]]:
    for backend in BACKENDS:
        try:
            if backend.can_open(path):
                return backend
        except OSError as error:
            logging.debug(f"{backend.__name__} could not inspect {path}: {error}")
    return None


def resolve_target(path) -> Path:
    """The thing to actually open.

    A folder holding exactly one readable file is that file — the shape some tools use for a time
    sequence, one folder per frame with the frame inside it. Folders that are datasets in their own right
    (an image stack, a set of LBPM rank files) are matched by their own backend before this is reached.
    """
    path = Path(path)
    if not path.is_dir() or backend_for_path(path) is not None:
        return path

    try:
        candidates = [
            item
            for item in sorted(path.iterdir())
            if item.is_file() and not item.name.startswith(".") and backend_for_path(item) is not None
        ]
    except OSError:
        return path

    return candidates[0] if len(candidates) == 1 else path


def source_class_for(path) -> Type[VirtualSource]:
    path = Path(path)
    backend = backend_for_path(path)
    if backend is not None:
        return backend

    raise UnsupportedSourceError(f"No deferred reader available for {path}")


def open_source(target, variable: str = None, **options) -> VirtualSource:
    """Open ``target`` (a path, a ``file://`` URI or a ``VirtualURI``) with the right backend."""
    if isinstance(target, VirtualSource):
        return target

    uri = target if isinstance(target, VirtualURI) else None
    if uri is None and isinstance(target, str) and "://" in target:
        uri = VirtualURI.parse(target)

    if uri is not None:
        if uri.scheme == SCHEME_FOURD:
            raise UnsupportedSourceError(
                "4D datasets are opened through ltrace.slicer.virtual.fourd.dataset.FourDDataset, "
                f"not as a single source: {uri.format()}"
            )
        if uri.scheme != SCHEME_FILE:
            raise UnsupportedSourceError(f"Unsupported scheme {uri.scheme!r} in {uri.format()}")
        path = uri.path
        variable = variable or uri.variable
        options = {**{key: value for key, value in uri.params.items() if key != "var"}, **options}
    else:
        path = Path(target)

    if not path.exists():
        raise FileNotFoundError(f"Deferred source not found: {path}")

    path = resolve_target(path)
    backend = source_class_for(path)
    return backend(path, variable=variable, **_filter_options(backend, options))


def _filter_options(backend: Type[VirtualSource], options: dict) -> dict:
    """Drop URI query parameters that a backend does not understand, keeping URIs forward-compatible."""
    import inspect

    parameters = inspect.signature(backend.__init__).parameters
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return options
    return {key: value for key, value in options.items() if key in parameters}
