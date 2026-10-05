"""What an execution section asks for, and where the answers are kept.

Split from the widget so the parts with no Qt in them — which backend was chosen, what a dispatcher is
told, and what is remembered between sessions — can be read and tested on their own.

Fields are *declared* (:data:`LOCAL_FIELDS`, :data:`REMOTE_FIELDS`) rather than built, because the dialog,
the storage and the options object all have to agree on them: a module wiring up its own tool adds an
entry to a tuple instead of editing three places.
"""

from dataclasses import dataclass, field, fields as dataclass_fields, replace
from typing import Dict, List, Optional, Sequence

import slicer

from ltrace.remote.backends import BACKEND_AUTO, BACKEND_LOCAL

TEXT = "text"
INT = "int"
BOOL = "bool"
PATH = "path"
LIST = "list"
MAP = "map"


@dataclass(frozen=True)
class Field:
    """One setting of a backend: how to show it, how to store it, what it means when left empty."""

    key: str
    label: str
    kind: str = TEXT
    tooltip: str = ""
    placeholder: str = ""
    default: object = None
    shared: bool = False
    """Kept once for the tool rather than once per backend — an installation path is not a run choice."""


# Shared by both backends: the same two questions, asked of whichever machine will run the command.
MODULES_FIELD = Field(
    key="modules",
    label="Environment modules",
    kind=LIST,
    tooltip="Modules to 'module load' before the run, in the order given. Empty loads none.",
    placeholder="comma separated, in the order they load",
)

ENVIRONMENT_FIELD = Field(
    key="env",
    label="Environment variables",
    kind=MAP,
    tooltip="Exported before the run. One NAME=value per line.",
    placeholder="NAME=value",
)

LOCAL_FIELDS = (
    Field(
        key="binary",
        label="Program",
        kind=PATH,
        tooltip=("Executable or container image to run. Only needed when it is not on this computer's PATH."),
        shared=True,
    ),
    MODULES_FIELD,
    ENVIRONMENT_FIELD,
)

REMOTE_FIELDS = (
    Field(
        key="nodes",
        label="Nodes",
        kind=INT,
        tooltip="How many machines to spread the processes over. The processes are divided equally.",
        default=1,
    ),
    Field(
        key="partition",
        label="Partition",
        tooltip="Queue to submit to. Empty uses the partition configured in the account, GPU or CPU.",
        placeholder="the account's own",
    ),
    Field(
        key="account",
        label="Account",
        tooltip="Project the allocation is charged to. Empty asks for none.",
    ),
    Field(
        key="walltime",
        label="Walltime",
        tooltip="Longest the job may run before the scheduler stops it. Empty lets the queue decide.",
        placeholder="e.g. 5-00:00:00",
    ),
    MODULES_FIELD,
    ENVIRONMENT_FIELD,
    Field(
        key="remote_root",
        label="Staging folder",
        tooltip=(
            "Folder the case is copied into, as the cluster sees it. Empty uses the GeoSlicer jobs folder "
            "of the account's cluster storage."
        ),
        placeholder="the account's jobs folder",
        shared=True,
    ),
)


def fields_for(kind: str, local=LOCAL_FIELDS, remote=REMOTE_FIELDS) -> Sequence[Field]:
    """The fields that apply to a backend of this kind."""
    return tuple(local if kind == BACKEND_LOCAL else remote)


def with_defaults(fields: Sequence[Field], defaults: Dict) -> Sequence[Field]:
    """The same fields, with the defaults one module wants instead of the ones they were declared with.

    A default is what the field falls back to until the backend has an answer of its own, so overriding it
    changes what an untouched installation does — not what a user already chose.
    """
    if not defaults:
        return tuple(fields)
    return tuple(replace(item, default=defaults[item.key]) if item.key in defaults else item for item in fields)


# -- values -------------------------------------------------------------------------------------------
def parse_value(kind: str, raw, default=None):
    """One stored string back into the value its field holds. Anything unset falls back to ``default``."""
    if raw is None or raw == "":
        if default is not None:
            return default
        return _empty(kind)

    if kind == BOOL:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")

    if kind == INT:
        try:
            return int(str(raw).strip())
        except ValueError:
            return int(default or 0)

    if kind == LIST:
        return [item.strip() for item in str(raw).split(",") if item.strip()]

    if kind == MAP:
        values = {}
        for line in str(raw).splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip():
                values[name.strip()] = value.strip()
        return values

    return str(raw)


def format_value(kind: str, value) -> str:
    """The value as one string, which is all a settings file can hold."""
    if value is None:
        return ""
    if kind == BOOL:
        return "true" if value else "false"
    if kind == LIST:
        return ", ".join(str(item) for item in value)
    if kind == MAP:
        return "\n".join(f"{name}={item}" for name, item in dict(value).items())
    return str(value)


def _empty(kind: str):
    if kind == LIST:
        return []
    if kind == MAP:
        return {}
    if kind == INT:
        return 0
    if kind == BOOL:
        return False
    return ""


@dataclass
class ExecutionOptions:
    """One run's answer to "where, how big, and under which settings"."""

    kind: str = BACKEND_AUTO
    target: Optional[str] = None
    """Name of the chosen backend, when one was chosen rather than left to ``auto``."""
    ranks: int = 1
    gpu: bool = False
    nodes: int = 1
    walltime: Optional[str] = None
    partition: Optional[str] = None
    account: Optional[str] = None
    modules: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    binary: Optional[str] = None
    remote_root: Optional[str] = None

    @classmethod
    def compose(cls, kind: str, target: Optional[str], ranks: int, gpu: bool, values: Dict) -> "ExecutionOptions":
        """Fold a backend's stored settings into the choices made in the section itself.

        Values a tool added for its own fields are ignored here — they reach the tool through
        :meth:`ExecutionWidget.settingsValues`, not through this object.
        """
        known = {item.name for item in dataclass_fields(cls)}
        extra = {key: value for key, value in (values or {}).items() if key in known}
        extra.pop("kind", None)
        extra.pop("target", None)
        return cls(kind=kind, target=target, ranks=int(ranks), gpu=bool(gpu), **extra)

    def asKwargs(self) -> Dict:
        """The vocabulary the dispatchers take, as in ``submit(case_dir, **options.asKwargs())``.

        Empty becomes ``None``: everywhere below, "not given" has a meaning of its own — use the account's
        partition, let the queue choose the walltime — and an empty string would override it with nothing.

        ``binary`` and ``remote_root`` are left out. They describe an installation rather than a run, and
        the dispatcher reads them from the settings this widget writes them to.
        """
        return {
            "backend": self.kind,
            "target_name": self.target,
            "ranks": int(self.ranks),
            "gpu": bool(self.gpu),
            "nodes": max(1, int(self.nodes or 1)),
            "walltime": self.walltime or None,
            "partition": self.partition or None,
            "account": self.account or None,
            "modules": list(self.modules or []),
            "env": dict(self.env or {}),
        }


class ExecutionSettings:
    """Remembers a field per backend, or once for the tool when the field is shared.

    Scoped by backend name because the answers are about a machine, not about the tool: the partition of
    one cluster means nothing on another, and the modules a cluster needs are not the ones this computer
    has. ``aliases`` maps a shared field onto a settings key that already exists, so a tool whose
    installation path is read from somewhere keeps being read from there.
    """

    def __init__(self, prefix: str, aliases: Dict[str, str] = None, settings=None):
        self.prefix = (prefix or "").strip("/")
        self.aliases = dict(aliases or {})
        self._settings = settings

    @property
    def settings(self):
        if self._settings is None:
            self._settings = slicer.app.userSettings()
        return self._settings

    def key(self, backend: Optional[str], item: Field) -> str:
        if item.shared:
            return self.aliases.get(item.key) or f"{self.prefix}/{item.key}"
        scope = (backend or BACKEND_AUTO).replace("/", "_")
        return f"{self.prefix}/Execution/{scope}/{item.key}"

    def value(self, backend: Optional[str], item: Field):
        return parse_value(item.kind, self.settings.value(self.key(backend, item), None), item.default)

    def setValue(self, backend: Optional[str], item: Field, value) -> None:
        self.settings.setValue(self.key(backend, item), format_value(item.kind, value))

    def values(self, backend: Optional[str], fields: Sequence[Field]) -> Dict:
        return {item.key: self.value(backend, item) for item in fields}

    def update(self, backend: Optional[str], fields: Sequence[Field], values: Dict) -> None:
        for item in fields:
            if item.key in (values or {}):
                self.setValue(backend, item, values[item.key])

        sync = getattr(self.settings, "sync", None)
        if callable(sync):
            sync()
