"""Virtual nodes: ordinary MRML nodes holding a *sample* of data that stays on disk.

A virtual node is a real node of the right class — table, scalar volume, label map or vector volume — whose
content is the first rows, or a downsampled read, of a much larger source. That makes it immediately
viewable in slice views, table views and charts, and usable as input to existing modules, at a cost that
does not grow with the size of the source.

The source is remembered in node attributes (see :mod:`ltrace.slicer.virtual.attributes`), so any code can
ask for more: :func:`refresh` re-reads the sample when the file changes, :func:`load_full` streams the full
resolution (or an arbitrary window) into a new node, and :func:`promote` turns the node itself into a
regular, fully loaded one.

Contrast with :mod:`ltrace.slicer.lazy`, which is kept untouched: a lazy node is a text node holding a URI
and needs a dedicated previewer; a virtual node *is* the data, at a lower fidelity.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import slicer

from . import attributes as attrs
from .nodes import backend_for, backend_for_class
from .sources.base import DEFAULT_SAMPLE_ROWS, KIND_TABLE, KIND_VOLUME, SourceInfo, VirtualSource
from .sources.factory import open_source
from .uri import VirtualURI, file_uri

PARENT_ATTRIBUTE = "ParentVirtualNode"
"""Set on nodes produced by :func:`load_full`, pointing back at the virtual node they came from."""


@dataclass
class VirtualNodeSpec:
    """Machine-readable description of what a virtual node holds and where it came from."""

    uri: str
    node_class: str
    kind: str = KIND_VOLUME
    variable: Optional[str] = None
    factor: int = 1
    rows: int = 0
    full_shape: Optional[Tuple[int, ...]] = None
    full_rows: Optional[int] = None
    dtype: Optional[str] = None
    columns: Tuple[str, ...] = field(default_factory=tuple)
    stamp: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> "VirtualNodeSpec":
        data = json.loads(text)
        for key in ("full_shape", "columns"):
            if data.get(key) is not None:
                data[key] = tuple(data[key])
        known = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        return cls(**known)

    @property
    def path(self) -> Path:
        return VirtualURI.parse(self.uri).path

    @property
    def is_volume(self) -> bool:
        return self.kind == KIND_VOLUME


# -- inspection ---------------------------------------------------------------------------------------
def is_virtual_node(node) -> bool:
    return attrs.is_true(node, attrs.VIRTUAL_NODE)


def spec(node) -> Optional[VirtualNodeSpec]:
    """The node's :class:`VirtualNodeSpec`, or ``None`` if it is not a virtual node."""
    if node is None:
        return None
    text = node.GetAttribute(attrs.SPEC)
    if not text:
        return None
    try:
        return VirtualNodeSpec.from_json(text)
    except (ValueError, TypeError) as error:
        logging.warning(f"Unreadable virtual node spec on {node.GetName()}: {error}")
        return None


def write_spec(node, node_spec: VirtualNodeSpec) -> None:
    """Store ``node_spec`` on the node, plus the human/filterable attributes that mirror it."""
    node.SetAttribute(attrs.VIRTUAL_NODE, attrs.TRUE)
    node.SetAttribute(attrs.SPEC, node_spec.to_json())
    node.SetAttribute(attrs.URI, node_spec.uri)

    if node_spec.variable:
        node.SetAttribute(attrs.VARIABLE, node_spec.variable)
    if node_spec.dtype:
        node.SetAttribute(attrs.DTYPE, node_spec.dtype)
    if node_spec.full_shape:
        node.SetAttribute(attrs.FULL_SHAPE, ",".join(str(size) for size in node_spec.full_shape))
    if node_spec.full_rows is not None:
        node.SetAttribute(attrs.FULL_ROWS, str(node_spec.full_rows))
    if node_spec.stamp:
        node.SetAttribute(attrs.SOURCE_STAMP, node_spec.stamp)

    if node_spec.is_volume:
        node.SetAttribute(attrs.DOWNSAMPLING, str(node_spec.factor))
    else:
        node.SetAttribute(attrs.SAMPLE_ROWS, str(node_spec.rows))


def mark_stale(node, stale: bool = True, reason: str = None) -> None:
    """Flag that the source could not be read. Virtual nodes are never deleted automatically: a missing
    file is usually an unmounted share, not a request to destroy the user's scene."""
    attrs.set_bool(node, attrs.STALE, stale)
    if stale and reason:
        logging.info(f"Virtual node {node.GetName()} is stale: {reason}")


def is_stale(node) -> bool:
    return attrs.is_true(node, attrs.STALE)


def open_node_source(node, **options) -> VirtualSource:
    """Open the source behind ``node``. Caller owns the returned source (use it as a context manager)."""
    node_spec = spec(node)
    if node_spec is None:
        raise ValueError(f"{node.GetName() if node else node} is not a virtual node")
    return open_source(node_spec.uri, variable=node_spec.variable, **options)


def describe(node, **options) -> SourceInfo:
    with open_node_source(node, **options) as source:
        return source.describe()


# -- creation -----------------------------------------------------------------------------------------
def create(
    target,
    variable: str = None,
    name: str = None,
    inplane_target: int = None,
    sample_rows: int = None,
    parent_item: int = None,
    folder_root=None,
    source_options: Dict = None,
    hide_from_editors: bool = False,
):
    """Create a virtual node for ``target`` (a path, a ``file://`` URI or an open source).

    Returns the new node, already added to the scene (and to ``parent_item`` in the subject hierarchy).
    """
    source = open_source(target, variable=variable, **(source_options or {}))
    try:
        info = source.describe()
        backend = backend_for(info)
        node_name = name or _default_name(source, info)

        node = backend.create(slicer.mrmlScene.GenerateUniqueName(node_name), info)
        fill_options = {"inplane_target": inplane_target}
        if sample_rows is not None:
            fill_options["rows"] = sample_rows
        written = backend.fill(node, source, info, **fill_options)

        node_spec = VirtualNodeSpec(
            uri=_uri_for(target, source, info),
            node_class=info.node_class,
            kind=info.kind,
            variable=info.variable,
            factor=int(written.get("factor", 1)),
            rows=int(written.get("rows", 0)),
            full_shape=info.shape_zyx,
            full_rows=info.rows,
            dtype=info.dtype,
            columns=tuple(written.get("columns", info.columns)),
            stamp=source.stamp(),
        )
        write_spec(node, node_spec)

        if folder_root is not None:
            node.SetAttribute(attrs.FOLDER_ROOT, Path(folder_root).as_posix())
        if hide_from_editors:
            node.SetHideFromEditors(True)
        if parent_item:
            _move_to_item(node, parent_item)

        return node
    finally:
        source.close()


def _default_name(source: VirtualSource, info: SourceInfo) -> str:
    stem = source.path.stem if source.path.is_file() else source.path.name
    if info.variable and info.variable not in (stem, source.path.name):
        return f"{stem} {info.variable}"
    return stem


def _uri_for(target, source: VirtualSource, info: SourceInfo) -> str:
    if isinstance(target, str) and "://" in target:
        return VirtualURI.parse(target).with_params(var=info.variable).format()
    return file_uri(source.path, info.variable)


def _move_to_item(node, parent_item: int) -> None:
    folder_tree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    item = folder_tree.GetItemByDataNode(node)
    if item:
        folder_tree.SetItemParent(item, parent_item)


# -- refreshing ---------------------------------------------------------------------------------------
def refresh(node, force: bool = False) -> bool:
    """Re-read the sample if the source changed. Returns whether the node was rewritten."""
    node_spec = spec(node)
    if node_spec is None:
        return False

    try:
        with open_source(node_spec.uri, variable=node_spec.variable) as source:
            stamp = source.stamp()
            if not force and stamp == node_spec.stamp:
                mark_stale(node, False)
                return False

            info = source.describe()
            backend = backend_for_class(node_spec.node_class)
            written = backend.fill(
                node,
                source,
                info,
                factor=node_spec.factor if node_spec.is_volume else None,
                rows=node_spec.rows or DEFAULT_SAMPLE_ROWS,
            )

            node_spec.stamp = stamp
            node_spec.full_shape = info.shape_zyx
            node_spec.full_rows = info.rows
            node_spec.dtype = info.dtype
            node_spec.factor = int(written.get("factor", node_spec.factor))
            node_spec.rows = int(written.get("rows", node_spec.rows))
            write_spec(node, node_spec)
            mark_stale(node, False)
            return True
    except (OSError, ValueError, RuntimeError) as error:
        mark_stale(node, True, reason=repr(error))
        return False


# -- materialization --------------------------------------------------------------------------------
def load_full(
    node,
    origin_zyx: Sequence[int] = (0, 0, 0),
    size_zyx: Sequence[int] = None,
    factor: int = 1,
    rows: int = None,
    name: str = None,
    into=None,
):
    """Stream the source into a node at full (or ``factor``) resolution.

    With ``into=None`` a new, regular node is created next to the virtual one and linked back to it through
    the ``ParentVirtualNode`` attribute (the same convention Big Image uses for reduced images). Passing
    ``into`` writes into an existing node instead, which is how the 4D player repaints its proxy node.
    """
    node_spec = spec(node)
    if node_spec is None:
        raise ValueError("load_full requires a virtual node")

    with open_source(node_spec.uri, variable=node_spec.variable) as source:
        info = source.describe()
        backend = backend_for_class(node_spec.node_class)

        target = into
        if target is None:
            suffix = "full" if factor == 1 else f"1:{factor}"
            target = backend.create(slicer.mrmlScene.GenerateUniqueName(name or f"{node.GetName()} ({suffix})"), info)
            target.SetAttribute(PARENT_ATTRIBUTE, node.GetID())
            _copy_parent_item(node, target)

        if node_spec.kind == KIND_TABLE:
            backend.fill(target, source, info, rows=rows)
        else:
            backend.fill(target, source, info, factor=factor, origin_zyx=origin_zyx, size_zyx=size_zyx)

        return target


def promote(node, rows: int = None):
    """Replace the sample in place with the full data and stop treating the node as virtual."""
    load_full(node, into=node, factor=1, rows=rows)

    for attribute in (
        attrs.VIRTUAL_NODE,
        attrs.SPEC,
        attrs.DOWNSAMPLING,
        attrs.SAMPLE_ROWS,
        attrs.STALE,
        attrs.SOURCE_STAMP,
    ):
        node.SetAttribute(attribute, None)

    return node


def resolve(node, **options):
    """The node a consumer should compute on: the full-resolution data behind a virtual node.

    Modules that must not silently operate on a sample call this instead of using the node directly.
    """
    return load_full(node, **options) if is_virtual_node(node) else node


def _copy_parent_item(source_node, target_node) -> None:
    folder_tree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    source_item = folder_tree.GetItemByDataNode(source_node)
    target_item = folder_tree.GetItemByDataNode(target_node)
    if source_item and target_item:
        folder_tree.SetItemParent(target_item, folder_tree.GetItemParent(source_item))
