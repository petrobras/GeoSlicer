import slicer

from pathlib import Path
from typing import Union, overload

from ltrace.slicer.node_attributes import CustomNodeType


DIR_PATH_ATTRIBUTE_LABEL = "DirPath"
TEMP_DIR_ATTRIBUTE_LABEL = "TempDir"


class DirectoryNode:
    @staticmethod
    def getNodeType():
        return slicer.vtkMRMLTransformNode

    @staticmethod
    def getNodeAttribute():
        return CustomNodeType.name(), CustomNodeType.DIRECTORY.value

    @staticmethod
    def isDirectoryNode(node: slicer.vtkMRMLNode) -> bool:
        nodeAttibute = DirectoryNode.getNodeAttribute()
        return node.GetAttribute(nodeAttibute[0]) == nodeAttibute[1]

    @overload
    def __init__(self, dirPath: str | Path, name: str = "Directory"):
        pass

    @overload
    def __init__(self, node: slicer.vtkMRMLNode):
        pass

    def __init__(self, *args):
        self.directoryNode = None

        if len(args) == 1 and isinstance(args[0], slicer.vtkMRMLNode):
            self.__init_from_node(args[0])
        elif len(args) == 1:
            self.__init_from_path(args[0])
        elif len(args) == 2:
            self.__init_from_path(args[0], args[1])
        else:
            raise TypeError("Invalid arguments")

    def __init_from_node(self, node: slicer.vtkMRMLNode):
        if not DirectoryNode.isDirectoryNode(node):
            raise ValueError(f"'{node.GetName()}' node isn't a directory node.")
        self.directoryNode = node

    def __init_from_path(self, dirPath: Union[str, Path], name: str = "Directory"):
        nodeAttibute = DirectoryNode.getNodeAttribute()
        self.directoryNode = slicer.mrmlScene.AddNewNodeByClass(DirectoryNode.getNodeType().__name__, name)
        self.directoryNode.SetAttribute(nodeAttibute[0], nodeAttibute[1])
        self.directoryNode.AddDefaultStorageNode()
        self.setDirPath(dirPath)

    def getNode(self) -> slicer.vtkMRMLNode:
        return self.directoryNode

    def setDirPath(self, dirPath: Union[str, Path]) -> None:
        """Update the directory the node points to.
        Args:
            dirPath (Union[str, Path]): the absolute path of the directory to which the node points to.
        Raises:
            ValueError: if the directory's path isn't absolute.
        """
        dirPath = Path(dirPath)
        if not dirPath.is_absolute():
            raise ValueError(f"'{dirPath.as_posix()}' isn't an absolute path.")
        self.setRawDirPath(dirPath)

    def getDirPath(self) -> Path:
        """Retrieve the absolute path of the directory the node points to. A path stored relatively
           is completed with the current project's root directory.
        Returns:
            Union[Path, None]: the directory's absolute path, or None when it isn't available.
        """
        dirPath = Path(self.directoryNode.GetAttribute(DIR_PATH_ATTRIBUTE_LABEL))
        if dirPath.is_absolute():
            return dirPath
        return Path(slicer.mrmlScene.GetRootDirectory()) / dirPath

    def setRawDirPath(self, dirPath: Union[str, Path]) -> None:
        dirPathPosix = Path(dirPath).as_posix()
        self.directoryNode.SetAttribute(DIR_PATH_ATTRIBUTE_LABEL, dirPathPosix)

    def setTempDir(self, dirPath: Union[str, Path]) -> None:
        """Set the temporary path where the directory is in.
           Used during save, when DirPath path points to the future saved path,
           and TempDir points to the current path
        Args:
            dirPath (Union[str, Path]): the temporary path where the directory is in.
        """
        dirPathPosix = Path(dirPath).as_posix()
        self.directoryNode.SetAttribute(TEMP_DIR_ATTRIBUTE_LABEL, dirPathPosix)

    def getTempDir(self) -> Union[Path, None]:
        return self.directoryNode.GetAttribute(TEMP_DIR_ATTRIBUTE_LABEL)

    def markDirToNotBeDeletedAtSave(self):
        """Keep the directory's path in the storage node's file name list, so the project's save
        process doesn't delete it from the project.
        """
        storageNode = self.directoryNode.GetStorageNode()
        storageNode.ResetFileNameList()
        storageNode.AddFileName(self.getDirPath().as_posix())
