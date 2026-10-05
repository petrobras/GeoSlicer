import slicer
import logging
import shutil
import tempfile

from ltrace.slicer.node_custom_behavior.node_custom_behavior_base import (
    NodeCustomBehaviorBase,
    CustomBehaviorRequirements,
)
from ltrace.slicer.node_custom_behavior.defs import TriggerEvent
from ltrace.slicer.nodes.directory_node import DirectoryNode
from pathlib import Path
from typing import Union


TAG_TEMPORARY_DIRECTORY = "LTraceDirectoryNode"


class DirectoryNodeCustomBehavior(NodeCustomBehaviorBase):
    """Custom behavior for nodes that only point to a directory through their storage node's
    file name. It keeps the referenced directory inside the project data directory, so it
    follows the project when it is saved somewhere else. No data is loaded from the directory.
    """

    REQUIREMENTS = CustomBehaviorRequirements(
        nodeTypes=[DirectoryNode.getNodeType()],
        attributes={DirectoryNode.getNodeAttribute()[0]: DirectoryNode.getNodeAttribute()[1]},
    )

    def __init__(self, node: slicer.vtkMRMLNode, event: TriggerEvent, eventArgs: dict) -> None:
        super().__init__(node=node, event=event, eventArgs=eventArgs)
        if self._event == TriggerEvent.SAVE_AS or self._event == TriggerEvent.SAVE:
            self.targetSaveDir = self._eventArgs["targetSaveDir"]
        else:
            self.targetSaveDir = None
        self._directoryNode = DirectoryNode(self._node)

    def _beforeSave(self) -> None:
        """Move the source directory to a temporary directory when it can't be used as it is."""
        sourceDir = Path(self._directoryNode.getDirPath())
        destinationDir = Path(self.targetSaveDir) / "Data" / self._node.GetID()
        if sourceDir == destinationDir:
            self._directoryNode.setTempDir(sourceDir)
            self._directoryNode.markDirToNotBeDeletedAtSave()
            return

        if not sourceDir.is_dir():
            logging.error(
                f"Skipping custom behavior for node {self._node.GetName()} due its source directory is missing: {str(sourceDir)}"
            )
            return

        # During a 'save as' event the directory stored in the current project must be kept there,
        # then a copy is made in a temporary directory to be moved to the new project directory later.
        if self._event == TriggerEvent.SAVE_AS and self.__isPathFromProjectDir(sourceDir):
            temporarySourceDir = self.__createTemporaryDir() / sourceDir.name
            shutil.copytree(str(sourceDir), temporarySourceDir, dirs_exist_ok=True)
            self._directoryNode.setTempDir(temporarySourceDir)
        else:
            self._directoryNode.setTempDir(sourceDir)

        # Set project relative destination dir so the right property will be saved with the node
        self._directoryNode.setRawDirPath(Path("Data") / self._node.GetID())
        self._directoryNode.markDirToNotBeDeletedAtSave()

    def _afterSave(self) -> None:
        """Store the source directory in the project data directory."""
        sourceDir = Path(self._directoryNode.getTempDir())
        destinationDir = Path(self._directoryNode.getDirPath())
        if sourceDir == destinationDir:
            return

        if not sourceDir.is_dir():
            logging.error(
                f"Skipping custom behavior for node {self._node.GetName()} due its source directory is missing: {str(sourceDir)}"
            )
            return

        # Create directory if its 'Data' folder is missing for any reason
        if not destinationDir.parent.is_dir():
            destinationDir.parent.mkdir(parents=True, exist_ok=True)

        # Check if directory is held by another DirectoryNode
        dirIsExclusive = True
        nodes = slicer.util.getNodesByClass(DirectoryNode.getNodeType().__name__)
        for node in nodes:
            if (node.GetID() == self._node.GetID()) or not DirectoryNode.isDirectoryNode(node):
                continue

            if Path(DirectoryNode(node).getTempDir()) == sourceDir:
                dirIsExclusive = False

        # If directory is exclusive of this node move it, otherwise copy it
        if dirIsExclusive:
            try:
                shutil.move(sourceDir, destinationDir)
            except PermissionError as e:
                logging.warning(f'Couldn\'t move files from "{node.GetName()}" node: {repr(e)}. Copying instead.')
                shutil.copytree(sourceDir, destinationDir, dirs_exist_ok=True)
        else:
            shutil.copytree(sourceDir, destinationDir, dirs_exist_ok=True)
        self._directoryNode.setTempDir("")

        assert destinationDir.is_dir(), f"{str(destinationDir)} couldn't be created in the project directory."

        if self.__isTemporaryDir(sourceDir.parent) and self.__isEmptyDir(sourceDir.parent):
            try:
                shutil.rmtree(sourceDir.parent, ignore_errors=True)
            except PermissionError as e:
                logging.warning(f'Couldn\'t remove files from "{node.GetName()}" node: {repr(e)}')

    def __isTemporaryDir(self, path: Path) -> bool:
        if Path(slicer.app.temporaryPath) in path.parents:
            return True

        return Path(tempfile.gettempdir()) in path.parents and path.parent.name == TAG_TEMPORARY_DIRECTORY

    def __isEmptyDir(self, directory: Path):
        return not any(directory.iterdir())

    def __isPathFromProjectDir(self, path: Path) -> bool:
        currentProjectDirectoryPath = Path(slicer.mrmlScene.GetRootDirectory())
        return currentProjectDirectoryPath in path.parents

    def __createTemporaryDir(self) -> Path:
        destinationPath = Path(tempfile.mkdtemp()) / TAG_TEMPORARY_DIRECTORY
        destinationPath.mkdir(parents=True, exist_ok=True)
        return destinationPath
