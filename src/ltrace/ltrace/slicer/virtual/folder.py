"""Virtual folders: a directory listed as nodes without being loaded.

Selecting a folder with *deferred* loading enabled creates one virtual node per dataset found inside it
(:mod:`ltrace.slicer.virtual.virtual_node`), grouped under a subject-hierarchy folder. With monitoring
enabled the listing is kept in sync through :class:`~ltrace.slicer.virtual.monitor.FolderMonitorService`,
so datasets that appear while a simulation runs show up on their own.

What counts as "one dataset" is deliberately coarse: a directory of image planes is one volume, not 46
nodes; an LBPM ``vis`` folder of per-rank HDF5 files is one volume per field. Anything unrecognized is
reported as skipped rather than silently dropped, so the UI can explain what it ignored.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import qt
import slicer

from . import attributes as attrs
from . import virtual_node
from .monitor import FolderMonitorService
from .sources.images import is_image_candidate
from .sources.raw import RAW_EXTENSIONS
from .sources.netcdf_h5 import NETCDF_EXTENSIONS

SCAN_TABLE_EXTENSIONS = (".csv", ".tsv")
"""Table extensions trusted during a folder scan. ``.txt``/``.dat`` are supported when the user points at
one explicitly, but a folder full of settings files must not become a folder full of table nodes."""

ITEM_TABLE = "table"
ITEM_VOLUME = "volume"
ITEM_STACK = "stack"

DEFAULT_DEPTH = 1
"""How far below the selected folder to look for datasets. One level covers the shapes seen in practice
(a folder of reconstruction folders, a simulation folder of frame folders) without walking a whole tree."""

REGISTRY_NODE_NAME = "VirtualFolderRegistry"

TRAILING_DIGITS = re.compile(r"^(?P<prefix>.*?)(?P<digits>\d+)$")


# -- scanning -----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ScanItem:
    key: str
    path: Path
    kind: str
    label: str
    options: Dict = field(default_factory=dict)


DEFAULT_MAX_ITEMS = 200
"""Cap on the datasets a single scan turns into nodes. Numbered families beyond this are better handled as
a time sequence — which is what :func:`suggest_patterns` proposes."""


@dataclass
class ScanResult:
    items: List[ScanItem] = field(default_factory=list)
    frames: List[Path] = field(default_factory=list)
    skipped: List[Path] = field(default_factory=list)
    truncated: int = 0


def scan(root, pattern: str = None, depth: int = DEFAULT_DEPTH, max_items: int = DEFAULT_MAX_ITEMS) -> ScanResult:
    """Find the datasets inside ``root``.

    Entries whose name matches ``pattern`` are collected as :attr:`ScanResult.frames` instead of items:
    they belong to a time sequence, which is surfaced as a single 4D node rather than one node per frame.
    ``pattern`` is a plain regular expression, so several families can be selected at once with ``|``.
    """
    result = ScanResult()
    _scan_directory(Path(root), Path(root), pattern, depth, result)
    result.items.sort(key=lambda item: item.key)
    result.frames.sort(key=frame_sort_key)

    if max_items and len(result.items) > max_items:
        result.truncated = len(result.items) - max_items
        result.items = result.items[:max_items]

    return result


def _scan_directory(current: Path, root: Path, pattern: Optional[str], depth: int, result: ScanResult) -> None:
    from natsort import natsorted

    try:
        entries = natsorted(current.iterdir(), key=lambda path: path.name)
    except OSError as error:
        logging.warning(f"Unable to list {current}: {error}")
        return

    compiled = re.compile(pattern) if pattern else None
    has_images = False

    for entry in entries:
        if entry.name.startswith("."):
            continue

        if compiled is not None and compiled.fullmatch(entry.name):
            result.frames.append(entry)
            continue

        if entry.is_dir():
            if depth > 0:
                _scan_directory(entry, root, pattern, depth - 1, result)
            else:
                result.skipped.append(entry)
            continue

        if is_image_candidate(entry):
            has_images = True
            continue

        item = _file_item(entry, root)
        if item is None:
            result.skipped.append(entry)
        else:
            result.items.append(item)

    if has_images:
        result.items.append(
            ScanItem(
                key=_key(current, root) or ".",
                path=current,
                kind=ITEM_STACK,
                label=current.name,
            )
        )


def _file_item(path: Path, root: Path) -> Optional[ScanItem]:
    suffix = path.suffix.lower()

    if suffix in SCAN_TABLE_EXTENSIONS:
        return ScanItem(key=_key(path, root), path=path, kind=ITEM_TABLE, label=path.stem)

    if suffix in RAW_EXTENSIONS or suffix in NETCDF_EXTENSIONS:
        return ScanItem(key=_key(path, root), path=path, kind=ITEM_VOLUME, label=path.stem)

    return None


def _key(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
    return "" if relative == "." else relative


def frame_sort_key(path) -> Tuple:
    """Sort frames by the number in their name, never lexicographically.

    LBPM names its output ``vis10000``, ``vis100000``, ``vis110000``: sorted as text, the simulation plays
    out of order. Names without a number keep alphabetical order after the numbered ones.
    """
    match = TRAILING_DIGITS.match(Path(path).name)
    if match is None:
        return (1, Path(path).name, 0)
    return (0, match.group("prefix"), int(match.group("digits")))


def suggest_patterns(root, depth: int = 1, minimum: int = 2) -> List[Tuple[str, int, List[str]]]:
    """Frame patterns worth offering for a folder, as ``(pattern, count, examples)``.

    Groups entries by "name without its trailing number", which is how simulation and reconstruction
    output is named in practice (``vis10000``, ``recon_0``, ``frame_0001.tif``).
    """
    root = Path(root)
    families: Dict[str, List[str]] = {}

    try:
        entries = list(root.iterdir())
    except OSError as error:
        logging.warning(f"Unable to list {root}: {error}")
        return []

    for entry in entries:
        if entry.name.startswith("."):
            continue
        stem = entry.name if entry.is_dir() else entry.stem
        match = TRAILING_DIGITS.match(stem)
        if match is None:
            continue
        families.setdefault(match.group("prefix"), []).append(entry.name)

    suggestions = []
    for prefix, names in families.items():
        if len(names) < minimum:
            continue
        is_directory = (root / names[0]).is_dir()
        pattern = f"{re.escape(prefix)}\\d+" + ("" if is_directory else r"\.\w+")
        suggestions.append((pattern, len(names), sorted(names, key=frame_sort_key)[:3]))

    return sorted(suggestions, key=lambda item: item[1], reverse=True)


# -- virtual folders ----------------------------------------------------------------------------------
@dataclass
class SyncReport:
    added: List[str] = field(default_factory=list)
    refreshed: List[str] = field(default_factory=list)
    stale: List[str] = field(default_factory=list)
    errors: List[Tuple[str, str]] = field(default_factory=list)
    frames: int = 0
    truncated: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.added or self.refreshed or self.stale)

    def summary(self) -> str:
        parts = []
        if self.added:
            parts.append(f"{len(self.added)} added")
        if self.refreshed:
            parts.append(f"{len(self.refreshed)} updated")
        if self.stale:
            parts.append(f"{len(self.stale)} missing")
        if self.errors:
            parts.append(f"{len(self.errors)} failed")
        if self.truncated:
            parts.append(f"{self.truncated} not listed")
        return ", ".join(parts) if parts else "no changes"


@dataclass
class VirtualFolder:
    """A folder surfaced as nodes, optionally kept in sync with what is on disk."""

    root: Path
    deferred: bool = True
    monitored: bool = True
    pattern: Optional[str] = None
    depth: int = DEFAULT_DEPTH
    max_items: int = DEFAULT_MAX_ITEMS
    folder_item: int = 0
    nodes: Dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return Path(self.root).as_posix()

    def to_dict(self) -> Dict:
        return {
            "root": self.key,
            "deferred": self.deferred,
            "monitored": self.monitored,
            "pattern": self.pattern,
            "depth": self.depth,
            "max_items": self.max_items,
            "nodes": dict(self.nodes),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "VirtualFolder":
        return cls(
            root=Path(data["root"]),
            deferred=bool(data.get("deferred", True)),
            monitored=bool(data.get("monitored", True)),
            pattern=data.get("pattern"),
            depth=int(data.get("depth", DEFAULT_DEPTH)),
            max_items=int(data.get("max_items", DEFAULT_MAX_ITEMS)),
            nodes=dict(data.get("nodes", {})),
        )

    # -- hierarchy ----------------------------------------------------------------------------------
    def ensure_folder_item(self) -> int:
        folder_tree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        if self.folder_item and folder_tree.GetItemName(self.folder_item):
            return self.folder_item

        existing = folder_tree.GetItemByName(Path(self.root).name)
        self.folder_item = existing or folder_tree.CreateFolderItem(folder_tree.GetSceneItemID(), Path(self.root).name)
        return self.folder_item

    # -- syncing ------------------------------------------------------------------------------------
    def sync(self) -> SyncReport:
        """Bring the scene in line with the folder. Never deletes nodes: missing sources are marked stale."""
        report = SyncReport()
        result = scan(self.root, pattern=self.pattern, depth=self.depth, max_items=self.max_items)
        report.frames = len(result.frames)
        report.truncated = result.truncated

        folder_item = self.ensure_folder_item()
        seen = set()

        for item in result.items:
            seen.add(item.key)
            node = self._node_for(item.key)

            if node is None:
                try:
                    node = virtual_node.create(
                        item.path,
                        name=item.label,
                        parent_item=folder_item,
                        folder_root=self.root,
                        source_options=item.options or None,
                    )
                    if not self.deferred:
                        virtual_node.promote(node)
                    self.nodes[item.key] = node.GetID()
                    report.added.append(item.key)
                except Exception as error:
                    logging.info(f"Skipping {item.path}: {error}")
                    report.errors.append((item.key, str(error)))
                continue

            try:
                if virtual_node.is_virtual_node(node) and virtual_node.refresh(node):
                    report.refreshed.append(item.key)
            except Exception as error:
                report.errors.append((item.key, str(error)))

        for key, node_id in list(self.nodes.items()):
            if key in seen:
                continue
            node = slicer.mrmlScene.GetNodeByID(node_id)
            if node is None:
                self.nodes.pop(key, None)
                continue
            virtual_node.mark_stale(node, True, reason=f"{key} is no longer in {self.key}")
            report.stale.append(key)

        return report

    def _node_for(self, key: str):
        node_id = self.nodes.get(key)
        return slicer.mrmlScene.GetNodeByID(node_id) if node_id else None

    def node_list(self) -> List:
        return [node for node in (self._node_for(key) for key in self.nodes) if node is not None]

    def remove_nodes(self) -> None:
        for node in self.node_list():
            slicer.mrmlScene.RemoveNode(node)
        self.nodes.clear()


# -- registry + manager -------------------------------------------------------------------------------
class VirtualFolderManager(qt.QObject):
    """Owns the registered virtual folders, their persistence and their monitoring subscriptions."""

    folderSynced = qt.Signal(str)
    folderRegistered = qt.Signal(str)
    folderUnregistered = qt.Signal(str)

    __instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folders: Dict[str, VirtualFolder] = {}
        self._monitor = FolderMonitorService.instance()
        self._monitor.folderChanged.connect(self._onFolderChanged)
        self._endImportObserver = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndImportEvent, lambda *args: self.restore()
        )
        self._endCloseObserver = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndCloseEvent, lambda *args: self._folders.clear()
        )

    @classmethod
    def instance(cls) -> "VirtualFolderManager":
        if cls.__instance is None:
            cls.__instance = cls()
        return cls.__instance

    # -- registration -------------------------------------------------------------------------------
    def folders(self) -> List[VirtualFolder]:
        return list(self._folders.values())

    def get(self, root) -> Optional[VirtualFolder]:
        return self._folders.get(Path(root).as_posix())

    def register(self, folder: VirtualFolder, sync: bool = True) -> SyncReport:
        self._folders[folder.key] = folder
        report = folder.sync() if sync else SyncReport()

        if folder.monitored:
            self._monitor.watch(folder.root, token=f"folder:{folder.key}")
        else:
            self._monitor.unwatch(folder.root, token=f"folder:{folder.key}")

        self.save()
        self.folderRegistered.emit(folder.key)
        return report

    def unregister(self, root, remove_nodes: bool = False) -> None:
        key = Path(root).as_posix()
        folder = self._folders.pop(key, None)
        if folder is None:
            return

        self._monitor.unwatch(folder.root, token=f"folder:{key}")
        if remove_nodes:
            folder.remove_nodes()

        self.save()
        self.folderUnregistered.emit(key)

    def sync(self, root) -> SyncReport:
        folder = self.get(root)
        if folder is None:
            return SyncReport()

        report = folder.sync()
        if report.changed:
            self.save()
        self.folderSynced.emit(folder.key)
        return report

    def syncAll(self) -> None:
        for key in list(self._folders):
            self.sync(key)

    def _onFolderChanged(self, root: str) -> None:
        if root in self._folders:
            self.sync(root)

    # -- persistence --------------------------------------------------------------------------------
    def save(self) -> None:
        """Persist the registry in the scene, so monitored folders survive save/load."""
        node = self._registryNode(create=True)
        node.SetText(json.dumps({"folders": [folder.to_dict() for folder in self._folders.values()]}, indent=2))

    def restore(self) -> None:
        """Re-register the folders described by the scene, reconnecting monitors and node ids."""
        node = self._registryNode(create=False)
        if node is None:
            return

        try:
            data = json.loads(node.GetText() or "{}")
        except ValueError as error:
            logging.warning(f"Unreadable virtual folder registry: {error}")
            return

        for entry in data.get("folders", []):
            try:
                folder = VirtualFolder.from_dict(entry)
            except (KeyError, TypeError) as error:
                logging.warning(f"Skipping an unreadable virtual folder entry: {error}")
                continue

            self._folders[folder.key] = folder
            if folder.monitored:
                self._monitor.watch(folder.root, token=f"folder:{folder.key}")
            self.folderRegistered.emit(folder.key)

    @staticmethod
    def _registryNode(create: bool = False):
        nodes = slicer.util.getNodes(REGISTRY_NODE_NAME, useLists=True).get(REGISTRY_NODE_NAME, [])
        if nodes:
            return nodes[0]

        if not create:
            return None

        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTextNode", REGISTRY_NODE_NAME)
        node.SetAttribute(attrs.VIRTUAL_NODE, attrs.FALSE)
        node.SetHideFromEditors(True)
        node.SetForceCreateStorageNode(True)
        return node


def manager() -> VirtualFolderManager:
    return VirtualFolderManager.instance()
