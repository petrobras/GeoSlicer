"""The 'where does this run' section of a module, and the settings behind it."""

from ltrace.remote.backends import BACKEND_AUTO, BACKEND_LOCAL, BACKEND_REMOTE

from .dialog import ExecutionSettingsDialog
from .options import (
    BOOL,
    INT,
    LIST,
    MAP,
    PATH,
    TEXT,
    LOCAL_FIELDS,
    REMOTE_FIELDS,
    ExecutionOptions,
    ExecutionSettings,
    Field,
    fields_for,
    with_defaults,
)
from .widget import ExecutionWidget

__all__ = [
    "BACKEND_AUTO",
    "BACKEND_LOCAL",
    "BACKEND_REMOTE",
    "BOOL",
    "INT",
    "LIST",
    "MAP",
    "PATH",
    "TEXT",
    "LOCAL_FIELDS",
    "REMOTE_FIELDS",
    "ExecutionOptions",
    "ExecutionSettings",
    "ExecutionSettingsDialog",
    "ExecutionWidget",
    "Field",
    "fields_for",
    "with_defaults",
]
