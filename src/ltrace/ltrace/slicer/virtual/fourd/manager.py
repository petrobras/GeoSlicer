"""Registry tying 4D proxy nodes to live players.

A proxy node persists in the project; a player (timers, preview cache, builder thread) does not. This
manager creates players, hands them out by node, rebuilds them from a node's attributes when a saved
project is reopened, and disposes of them when the node or the scene goes away.

It is also where 4D playback meets folder monitoring: a change reported for a dataset's folder becomes a
frame rescan, which is what makes *follow* mode track a running simulation.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import qt
import slicer
import vtk

from .. import attributes as attrs
from ..monitor import FolderMonitorService
from ..uri import VirtualURI
from . import proxy
from .cache import PreviewCache, purge_expired
from .dataset import FourDDataset
from .player import FourDPlayer


class FourDManager(qt.QObject):
    playerCreated = qt.Signal(str)
    playerClosed = qt.Signal(str)

    __instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._players: Dict[str, FourDPlayer] = {}
        self._monitor = FolderMonitorService.instance()
        self._monitor.folderChanged.connect(self._onFolderChanged)
        self._monitor.folderPolled.connect(self._onFolderPolled)

        self._nodeRemovedObserver = slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeRemovedEvent, self._onNodeRemoved)
        self._sceneCloseObserver = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.StartCloseEvent, lambda *args: self.closeAll()
        )

        purge_expired()

    @classmethod
    def instance(cls) -> "FourDManager":
        if cls.__instance is None:
            cls.__instance = cls()
        return cls.__instance

    # -- creation -------------------------------------------------------------------------------------
    def create(
        self,
        root,
        pattern: str,
        variable: str = None,
        name: str = None,
        follow: bool = False,
        parent_item: int = None,
        preview_target: int = None,
        monitored: bool = True,
        start: bool = True,
    ) -> Tuple["slicer.vtkMRMLNode", FourDPlayer]:
        """Create a 4D dataset, its proxy node and its player."""
        dataset = FourDDataset(root, pattern=pattern, variable=variable)
        if not dataset.frame_count:
            raise ValueError(f"No frame matching '{pattern}' inside {root}")

        factor = dataset.preview_factor(preview_target) if preview_target else dataset.preview_factor()
        node = proxy.create(dataset, name=name, parent_item=parent_item, preview_factor=factor)
        player = self._register(node, dataset, PreviewCache(dataset, factor=factor), monitored=monitored)

        player.setFollow(follow)
        if start:
            player.start()
            proxy.show(node)

        return node, player

    def attach(self, node) -> Optional[FourDPlayer]:
        """Player for ``node``, rebuilding it from the node's attributes when needed (project reopened)."""
        if node is None or not proxy.is_proxy(node):
            return None

        existing = self._players.get(node.GetID())
        if existing is not None:
            return existing

        uri = proxy.dataset_uri(node)
        if not uri:
            return None

        try:
            dataset = FourDDataset.from_uri(uri)
        except Exception as error:
            logging.warning(f"Unable to reopen the 4D dataset of {node.GetName()}: {error}")
            return None

        if not dataset.frame_count:
            logging.warning(f"The 4D folder of {node.GetName()} has no frame matching its pattern any more.")
            return None

        factor = attrs.get_int(node, attrs.FOURD_PREVIEW_FACTOR, 0) or dataset.preview_factor()
        player = self._register(node, dataset, PreviewCache(dataset, factor=factor))
        player.seek(proxy.frame_index(node), force=True)
        player.builder.start(priority=player.index)
        return player

    def find(self, root, pattern: str, variable: str = None) -> Optional[FourDPlayer]:
        """The player already showing this folder, pattern and variable, if there is one.

        A 4D node is a *view* of a folder, not a snapshot of it: a folder that gains frames is still the
        same sequence, so asking for it again has to return what is already on screen instead of adding a
        second node beside it. The variable is part of that identity, so ``phase`` and ``Pressure`` of one
        run stay two separate nodes.
        """
        target = Path(root)
        for node_id, player in self._players.items():
            dataset = player.dataset
            if (
                dataset.root == target
                and dataset.pattern == pattern
                and (dataset.variable or None) == (variable or None)
                and slicer.mrmlScene.GetNodeByID(node_id) is not None
            ):
                return player
        return None

    def nodes(self, root, pattern: str = None, variable: str = None) -> List["slicer.vtkMRMLNode"]:
        """The 4D nodes in the scene that show ``root``, whether a player is attached to them yet or not.

        A node restored with a project has no player until it is shown (see :meth:`attach`), so it is
        invisible to :meth:`find` and :meth:`players`. ``pattern`` and ``variable`` narrow the match when
        given, the way they identify a sequence in :meth:`find`.
        """
        target = Path(root)
        found = []
        for node in slicer.util.getNodesByClass("vtkMRMLNode"):
            uri = proxy.dataset_uri(node) if proxy.is_proxy(node) else None
            if not uri:
                continue
            try:
                parsed = VirtualURI.parse(uri)
            except Exception:
                continue
            if Path(parsed.path) != target:
                continue
            if pattern is not None and parsed.pattern != pattern:
                continue
            if variable is not None and (parsed.variable or None) != (variable or None):
                continue
            found.append(node)
        return found

    def player(self, node) -> Optional[FourDPlayer]:
        return self._players.get(node.GetID()) if node is not None else None

    def players(self) -> Dict[str, FourDPlayer]:
        return dict(self._players)

    # -- disposal -------------------------------------------------------------------------------------
    def close(self, node) -> None:
        node_id = node.GetID() if hasattr(node, "GetID") else str(node)
        self._closeById(node_id)

    def closeAll(self) -> None:
        for node_id in list(self._players):
            self._closeById(node_id)

    def _closeById(self, node_id: str) -> None:
        player = self._players.pop(node_id, None)
        if player is None:
            return

        try:
            self._monitor.unwatch(player.dataset.root, token=f"fourd:{node_id}")
            player.close()
        except Exception as error:
            logging.debug(f"Error while closing a 4D player: {error}")

        self.playerClosed.emit(node_id)

    # -- internals ------------------------------------------------------------------------------------
    def _register(self, node, dataset: FourDDataset, cache: PreviewCache, monitored: bool = True) -> FourDPlayer:
        player = FourDPlayer(dataset, node, cache=cache, parent=self)
        self._players[node.GetID()] = player

        if monitored:
            self._monitor.watch(dataset.root, token=f"fourd:{node.GetID()}")

        self.playerCreated.emit(node.GetID())
        return player

    def _onFolderChanged(self, root: str) -> None:
        target = Path(root)
        for player in list(self._players.values()):
            if player.dataset.root == target:
                try:
                    player.refreshFrames()
                except Exception as error:
                    logging.warning(f"Unable to refresh the frames of {player.dataset.root.name}: {error}")

    def _onFolderPolled(self, root: str) -> None:
        """Cheap per-poll check for frames rewritten in place (see FolderMonitorService.folderPolled)."""
        target = Path(root)
        for player in list(self._players.values()):
            if player.dataset.root == target:
                try:
                    player.refreshTail()
                except Exception as error:
                    logging.debug(f"Tail refresh failed for {player.dataset.root.name}: {error}")

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onNodeRemoved(self, caller, event, callData) -> None:
        if callData is None or not hasattr(callData, "GetID"):
            return
        if callData.GetID() in self._players:
            self._closeById(callData.GetID())


def get_manager() -> FourDManager:
    """The process-wide manager. Named to avoid shadowing this module in ``from ... import manager``."""
    return FourDManager.instance()
