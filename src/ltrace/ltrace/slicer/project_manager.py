import qt
import slicer
import vtk
import os
import logging
import re
import shutil
import traceback
import psutil
import pandas as pd
import subprocess

from dataclasses import dataclass
from ltrace.constants import SaveStatus
from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.slicer.helpers import singleton
from ltrace.slicer.node_custom_behavior.node_custom_behavior_manager import NodeCustomBehaviorManager
from ltrace.slicer.node_custom_behavior.defs import TriggerEvent
from ltrace.slicer.node_observer import NodeObserver
from pathlib import Path
from pathvalidate import is_valid_filename
from typing import List, Union
from humanize import naturalsize

DEFAULT_PROPERTIES = {"useCompression": 0}
FILE_SIZE_EXTRA_MARGIN = 1.1


@dataclass
class SliceViewConfiguration:
    background: str = None
    foreground: str = None
    label: str = None
    foregroundOpacity: float = None
    labelOpacity: float = None


def handleCopySuffixOnClonedNodes(storageNode: slicer.vtkMRMLStorageNode) -> str:
    """Handle the extra copy at the end of the file name.
    This is a bug fix for the method AddDefaultStorageNode, that probably generate the wrong name internally

    Args:
        filename (str): the file name to be fixed.

    Returns:
        str: the fixed file name.
    """
    filename = storageNode.GetFileName()
    if not filename:
        return ""

    patters = [r" Copy", r".nrrd Copy.nrrd"]
    func = lambda fn: max([len(p) if fn.endswith(p) else 0 for p in patters])

    found = func(filename)

    if found > 0:
        filepath = Path(filename[:-found])
        filename = str(filepath.with_name(f"{filepath.stem} Copy{filepath.suffix}"))
        storageNode.SetFileName(filename)

    return filename


@singleton
class ProjectManager(qt.QObject):
    """Class to handle the 'project concept' from  Geoslicer.
    Specialize loading, saving and related slicer's process
    """

    projectChangedSignal = qt.Signal(None)

    def __init__(self, folderIconPath, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__nodeObservers = list()
        self.__folderIconPath = folderIconPath
        self.__customBehaviorNodeManager = None
        self.__configStorageNodeDefaults()
        self.__startCloseSceneObserverHandler = None
        self.__endCloseSceneObserverHandler = None
        self.__modifiedEventObserverHandler = None
        self.__endLoadEventObserverHandler = None
        self.__startLoadEventObserverHandler = None
        self.__projectModifiedSignalPaused = True
        self.__startSaveEventObserver = None
        self.__endSaveEventObserver = None
        ApplicationObservables().applicationLoadFinished.connect(self.__setup)
        self.destroyed.connect(self.__del__)

    def __del__(self):
        ApplicationObservables().applicationLoadFinished.disconnect(self.__setup)

    def __setup(self):
        self.__customBehaviorNodeManager = NodeCustomBehaviorManager()
        self.__endCloseSceneObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndCloseEvent, self.__onEndCloseScene
        )
        self.__modifiedEventObserverHandler = slicer.mrmlScene.AddObserver("ModifiedEvent", self.__onSceneModified)
        self.__nodeAddedObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.NodeAddedEvent, self.__onNodeAdded
        )
        self.__endLoadEventObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndImportEvent, self.__onEndLoadScene
        )

        self.__startLoadEventObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.StartImportEvent, self.__onStartLoadScene
        )

        ApplicationObservables().applicationLoadFinished.disconnect(self.__setup)
        self.__resumeModifiedObserver()

    def save(self, projectUrl, internalCall=False, *args, **kwargs):
        """Handles project' saving process. It saves the nodes that has modifications and
           are related to the current scene, and then, saves the scene.

        Args:
            projectUrl (str): the scene filepath (.mrml).

        Returns:
            bool: True if save process was successful, otherwise False.
        """
        projectModified = slicer.modules.AppContextInstance.mainWindow.windowModified
        if not internalCall:
            self.__customBehaviorNodeManager.triggerEvent = TriggerEvent.SAVE
            self.__pauseModifiedObserver()
            slicer.mrmlScene.StartState(slicer.mrmlScene.SaveState)

        status = SaveStatus.IN_PROGRESS

        if not self.__validateProjectIsWritable(projectUrl):
            slicer.mrmlScene.EndState(slicer.mrmlScene.SaveState)
            return SaveStatus.FAILED

        rootDirBeforeSave = slicer.mrmlScene.GetRootDirectory()
        self.__configStorageNodeDefaults(*args, **kwargs)
        projectUrl = Path(projectUrl).resolve()
        projectRootUrl = projectUrl.parent if projectUrl.is_file() else projectUrl
        slicer.mrmlScene.SetRootDirectory(projectRootUrl.as_posix())
        firstSave = not projectUrl.exists()

        # Save Scene
        if not self.__saveNodes(firstSave=firstSave, *args, **kwargs) or not self.__saveScene(
            projectUrl, *args, **kwargs
        ):
            slicer.mrmlScene.SetRootDirectory(rootDirBeforeSave)
            status = SaveStatus.FAILED

        projectFile = self.__findProjectFile(projectRootUrl.as_posix())
        if not projectFile:
            slicer.mrmlScene.SetRootDirectory(rootDirBeforeSave)
            status = SaveStatus.FAILED

        if status != SaveStatus.IN_PROGRESS:  # status is FAILED or FAILED_FILE_ALREADY_EXISTS
            if not internalCall:
                slicer.mrmlScene.EndState(slicer.mrmlScene.SaveState)
                self.__resumeModifiedObserver(projectModified)
            return status

        fileProjectPath = (projectRootUrl / projectFile).resolve()

        parameters = {
            "fileType": "SceneFile",
            "fileName": fileProjectPath.as_posix(),
        }
        slicer.app.coreIOManager().emitFileSaved(parameters)

        slicer.app.processEvents(qt.QEventLoop.AllEvents, 1000)

        if not internalCall:
            slicer.mrmlScene.EndState(slicer.mrmlScene.SaveState)
            self.__resumeModifiedObserver(False)

        return SaveStatus.SUCCEED

    def __getSliceViewConfiguration(self) -> SliceViewConfiguration:
        config = SliceViewConfiguration()
        num = slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSliceCompositeNode")
        for i in range(num):
            sliceViewer = slicer.mrmlScene.GetNthNodeByClass(i, "vtkMRMLSliceCompositeNode")
            config.background = config.background or sliceViewer.GetBackgroundVolumeID()
            config.foreground = config.foreground or sliceViewer.GetForegroundVolumeID()
            config.label = config.label or sliceViewer.GetLabelVolumeID()
            config.foregroundOpacity = config.foregroundOpacity or sliceViewer.GetForegroundOpacity()
            config.labelOpacity = config.labelOpacity or sliceViewer.GetLabelOpacity()

        return config

    def __setSliceViewConfiguration(self, config: SliceViewConfiguration) -> None:
        slicer.util.setSliceViewerLayers(
            background=config.background,
            foreground=config.foreground,
            label=config.label,
            foregroundOpacity=config.foregroundOpacity,
            labelOpacity=config.labelOpacity,
        )

    def saveAs(self, scenePath, *args, **kwargs):
        """Handle custom save scene as operation."""
        self.__customBehaviorNodeManager.triggerEvent = TriggerEvent.SAVE_AS
        sliceViewConfig = self.__getSliceViewConfiguration()
        self.__pauseModifiedObserver()
        slicer.mrmlScene.StartState(slicer.mrmlScene.SaveState)
        status = SaveStatus.IN_PROGRESS
        projectModified = slicer.modules.AppContextInstance.mainWindow.windowModified

        scenePath = Path(scenePath)

        if scenePath.is_file():
            slicer.util.errorDisplay(f'Cannot create project directory at "{scenePath}" because it is a file.')
            slicer.mrmlScene.EndState(slicer.mrmlScene.SaveState)
            self.__resumeModifiedObserver(projectModified)
            self.__setSliceViewConfiguration(sliceViewConfig)
            return SaveStatus.FAILED_FILE_ALREADY_EXISTS

        status = self.save(str(scenePath), internalCall=True, *args, **kwargs)

        if status != SaveStatus.SUCCEED and status != SaveStatus.IN_PROGRESS:  # CANCELLED or FAILED options
            slicer.mrmlScene.EndState(slicer.mrmlScene.SaveState)
            self.__resumeModifiedObserver(projectModified)
            self.__setSliceViewConfiguration(sliceViewConfig)
            return status

        self.__configureProjectFolder(str(scenePath))
        projectFile = self.__findProjectFile(str(scenePath))

        if projectFile is None:
            self.__resumeModifiedObserver(projectModified)
            slicer.mrmlScene.EndState(slicer.mrmlScene.SaveState)
            self.__setSliceViewConfiguration(sliceViewConfig)
            return SaveStatus.FAILED

        # Maintain event behavior from previous version
        slicer.mrmlScene.StartState(slicer.mrmlScene.ImportState)

        fileProjectPath = (scenePath / projectFile).resolve()
        slicer.mrmlScene.SetURL(fileProjectPath.as_posix())
        status = SaveStatus.SUCCEED

        slicer.mrmlScene.EndState(slicer.mrmlScene.ImportState)

        self.projectChangedSignal.emit()
        self.__setSliceViewConfiguration(sliceViewConfig)
        slicer.mrmlScene.EndState(slicer.mrmlScene.SaveState)
        self.__resumeModifiedObserver(False)

        return status

    def __getFileSize(self, filePath: str) -> int:
        """Returns the size of a file in bytes if it exists.
        If the file does not exist, checks if the path is a directory and returns the total size of all files in that directory.
        """
        filePath = Path(filePath)
        if filePath.is_file():
            return filePath.stat().st_size
        elif filePath.is_dir():
            totalSize = 0
            for item in list(filePath.iterdir()):
                if item.is_file():
                    totalSize += item.stat().st_size
            return totalSize
        else:
            if filePath.parent.is_dir():
                totalSize = 0
                for item in list(filePath.parent.iterdir()):
                    if item.is_file():
                        totalSize += item.stat().st_size

                return totalSize

            logging.error(f"File or directory not found: {filePath}")
            return 0

    def __estimateImageDataSize(self, imageData: vtk.vtkImageData) -> int:
        """returns expected file size of a volume node Image Data"""
        try:
            dimensions = imageData.GetDimensions()
            dataTypeSize = imageData.GetScalarSize()
            size = dimensions[0] * dimensions[1] * dimensions[2] * dataTypeSize
        except AttributeError:
            logging.error("Attempt to estimate size of empty image data failed.")
            size = 0

        return size

    def estimateNodeSize(self, node: slicer.vtkMRMLNode) -> int:
        """returns the expected file size in bytes of a node"""
        if isinstance(node, slicer.vtkMRMLScalarVolumeNode):
            if node.GetImageData() is None:
                estimate = 0
            else:
                estimate = self.__estimateImageDataSize(node.GetImageData())

        elif isinstance(node, slicer.vtkMRMLSegmentationNode):
            try:
                binaryLabelMap = node.GetSegmentation().GetNthSegment(0).GetRepresentation("Binary labelmap")
            except AttributeError:  # Invalid segment or representation
                logging.error("Attempt to estimate size of empty segmentation node failed.")
                estimate = 0
            else:
                estimate = self.__estimateImageDataSize(binaryLabelMap)

        elif isinstance(node, slicer.vtkMRMLTableNode):
            tableDF = slicer.util.dataframeFromTable(node)
            tableDF: pd.DataFrame = tableDF.round(6)
            headerCounts = pd.Series(tableDF.columns.astype(str).str.len())
            numRows, numColumns = tableDF.shape
            characterCounts = tableDF.astype(str).apply(lambda x: x.astype(str).str.len())
            estimate = characterCounts.sum().sum() + numRows * numColumns + headerCounts.sum()

        elif isinstance(node, slicer.vtkMRMLModelNode):
            try:
                estimate = node.GetPolyData().GetActualMemorySize() * 1024
            except AttributeError:
                estimate = 0

        elif isinstance(node, slicer.vtkMRMLSequenceNode):
            estimate = 0
            for item in range(node.GetNumberOfDataNodes()):
                estimate += self.estimateNodeSize(node.GetNthDataNode(item))

        else:
            estimate = 0

        return estimate * FILE_SIZE_EXTRA_MARGIN

    def getNodeSize(self, node: slicer.vtkMRMLNode, scenePath: str) -> int:
        """Returns the size of a node's associated file if it exists and is in scene path,
        the expected estimate size or 0 if it doesn't exist or type has considerable size."""
        storageNode = node.GetStorageNode()
        filePath = None
        if storageNode:
            filePath = storageNode.GetFullNameFromFileName()
            if not Path(filePath).is_relative_to(Path(scenePath).parent):
                filePath = None

        if filePath:
            return self.__getFileSize(filePath)
        else:
            estimate = self.estimateNodeSize(node)
            return estimate

    def __listAllStorableNodes(self, scenePath: str) -> int:
        """Lists all storable nodes and their sizes."""
        totalSize = 0
        for node in self.__getNodesToSave():
            nodeSize = self.getNodeSize(node, scenePath)
            totalSize += nodeSize

        return totalSize

    def __hasWriteAccess(self, path: Path) -> bool:
        """Check if the user has write access to the given path."""

        try:
            testFile = path / "test_write.tmp"
            with open(testFile, "w") as f:
                f.write("test")
            testFile.unlink(missing_ok=True)
            return True
        except (PermissionError, IOError):
            return False

    def getWritableStorageInfo(self, storageDestination: Path) -> int:
        """Get writable storage information for the user home directory."""

        if self.__hasWriteAccess(storageDestination):
            usage = psutil.disk_usage(storageDestination.as_posix())
            return usage.free
        else:
            logging.error(f"Warning: No write access to {storageDestination}!")
            return 0

    def __validateProjectIsWritable(self, scenePath: str) -> bool:
        """Checks if project can be written and if has enough space for expected files sizes"""
        try:
            hdSize = self.getWritableStorageInfo(Path(scenePath).parent)
            sceneSize = self.__listAllStorableNodes(scenePath)
            logging.debug(f"hdSize: {hdSize}, sceneSize: {sceneSize}, scenePath: {scenePath}")
            if hdSize <= sceneSize:
                logging.error(
                    f"Not enough space in drive ({naturalsize(hdSize)}) for scene ({naturalsize(sceneSize)})."
                )
                return False

        except Exception as e:
            logging.error(f"Failed to validate project path access: {e}\n{traceback.format_exc()}")
            return False

        return True

    def load(self, projectFilePath: Union[str, Path], internalCall: bool = False) -> bool:
        """Handle custom load scene operation."""
        if isinstance(projectFilePath, str):
            projectFilePath = Path(projectFilePath)

        projectFilePath = projectFilePath.resolve()

        if projectFilePath.as_posix() == Path(slicer.mrmlScene.GetURL()).as_posix():
            return True

        if not projectFilePath.exists():
            logging.error(f"Cannot load project from '{projectFilePath.as_posix()}'. File does not exist.")
            return False

        if not internalCall:
            self.__customBehaviorNodeManager.triggerEvent = TriggerEvent.LOAD
            self.__pauseModifiedObserver()

        self.__clearNodeObservers()
        # Close scene before load a new one
        self.close()

        status = True
        try:
            slicer.util.loadScene(projectFilePath.as_posix())
        except Exception as error:
            logging.error(f"A problem occured during the 'Load Scene' process: {error}\n{traceback.format_exc()}")
            status = False

        if not internalCall:
            self.__resumeModifiedObserver(False)

        self.__setProjectModified(False)

        return status

    def close(self) -> None:
        """Wrapper method to close the project."""
        slicer.mrmlScene.Clear(0)
        slicer.mrmlScene.SetURL("")
        self.__setProjectModified(False)

    def __onEndCloseScene(self, *args) -> None:
        """Handle slicer' end close scene event."""
        slicer.app.processEvents(qt.QEventLoop.AllEvents, 1000)
        self.__setProjectModified(False)
        self.projectChangedSignal.emit()

    def __onStartLoadScene(self, *args, **kwargs) -> None:
        """Handle slicer' start load scene event."""
        self.__pauseModifiedObserver()

    def __onEndLoadScene(self, *args, **kwargs) -> None:
        """Handle slicer' end load scene event."""
        self.projectChangedSignal.emit()

        # Hide axis labels for legacy projects which may have them.
        # This can probably be removed in the future, as it is also done
        # when GeoSlicer starts.
        viewNode = slicer.app.layoutManager().threeDWidget(0).mrmlViewNode()
        viewNode.SetAxisLabelsVisible(False)

        self.__clearMaskSettingsOnAllSegmentEditors()
        self.__setProjectModified(False)

    def __onSceneModified(self, *args, **kwargs):
        """Handle slicer' scene modified event."""
        self.__setProjectModified(True)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def __onNodeAdded(self, caller, eventId, callData):
        """Handle slicer' node added to scene event."""
        if issubclass(
            type(callData),
            (
                slicer.vtkMRMLModelNode,
                slicer.vtkMRMLColorTableNode,
                slicer.vtkMRMLSubjectHierarchyNode,
                slicer.vtkMRMLTransformNode,
                slicer.vtkMRMLSliceDisplayNode,
                slicer.vtkMRMLTableViewNode,
                slicer.vtkMRMLSegmentEditorNode,
            ),
        ):
            return

        if isinstance(callData, slicer.vtkMRMLTableNode) and callData.GetName() == "Default mineral colors":
            return

        observer = NodeObserver(node=callData, parent=self)
        observer.modifiedSignal.connect(self.__onSceneModified)
        observer.removedSignal.connect(self.__onObservedNodeRemoved)

        self.__nodeObservers.append(observer)

    def __onObservedNodeRemoved(self, node_observer: NodeObserver, node: slicer.vtkMRMLNode) -> None:
        """Handle when a node being observed is removed from the scene."""
        if node_observer not in self.__nodeObservers:
            return

        self.__nodeObservers.remove(node_observer)
        del node_observer

    def __clearNodeObservers(self) -> None:
        """Clear the node observer's list and remove the observer handlers from each one."""
        for node_observer in self.__nodeObservers[:]:
            node_observer.clear()
            del node_observer

        self.__nodeObservers.clear()

    def __configureProjectFolder(self, projectPath: str) -> None:
        """Applies folder's custom configuration

        Args:
            projectPath (str): the folder path
        """
        platform = os.name
        if platform == "nt":  # Windows:
            self.__createProjectFolderConfigurationFile(
                projectPath=projectPath,
                ConfirmFileOp=1,
                NoSharing=0,
                IconFile=self.__folderIconPath,
                IconIndex=0,
                InfoTip="This is a Geoslicer project folder",
            )
        elif platform == "posix":  # Linux:
            self.__createProjectFolderConfigurationFile(projectPath=projectPath, Icon=self.__folderIconPath)
        else:
            pass

    def __createProjectFolderConfigurationFile(self, projectPath: str, *args, **kwargs) -> None:
        """Wrapper for creating the file that configures the folder attributes.
        Works with the following OS: Windows, Linux

        Args:
            projectPath (str): the folder path to be configured

        Raises:
            Exception: Not supported OS.
            Exception: Not valid icon file.
        """
        platform = os.name

        if platform == "nt":  # Windows
            iconParameterLabel = "IconFile"
            configFileName = "desktop.ini"
            header = "[.ShellClassInfo]"

            def run_cmd(cmd):
                return subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW)

            def post_setup(configFile):
                # Add attributes to the config file (Mandatory)
                run_cmd(["attrib", "+h", "+s", configFile])

                # Add attributes to the directory (Mandatory)
                run_cmd(["attrib", "+r", os.path.dirname(configFile)])

        elif platform == "posix":  # Linux
            iconParameterLabel = "Icon"
            configFileName = ".directory"
            header = "[Desktop Entry]"

            def post_setup(configFile):
                # TODO: test if this works consistently in different Linux systems
                command = f'gio set -t string "{projectPath}"'
                command += f' metadata::custom-icon "file://{projectPath}/ProjectIcon.ico"'
                command += f' && touch "{projectPath}"'
                os.system(command)

        else:
            raise Exception("Current OS is not supported by this function.")

        if iconParameterLabel in kwargs.keys():
            iconFile = kwargs[iconParameterLabel]
            if os.path.isfile(iconFile):
                shutil.copy2(iconFile, projectPath)
                kwargs[iconParameterLabel] = os.path.basename(iconFile)

        data = header + "\n"
        for k, v in kwargs.items():
            data += "{}={}\n".format(k, v)

        configFile = os.path.join(projectPath, configFileName)

        # Create folder configuration file
        with open(configFile, "w", encoding="utf-8") as file:
            file.write(data)

        # Apply post configurations
        post_setup(configFile)

    def __findProjectFile(self, projectPath: str, extension=".mrml") -> str:
        """Search for project file inside path.

        Args:
            projectPath (str): The directory to search for the project file
            extension (str, optional): The project file extension. Defaults to ".mrml".

        Returns:
            str: The project file path if it was found. Otherwise, None
        """
        projectFile = None
        for _, _, files in os.walk(projectPath):
            for file in files:
                if file.endswith(extension):
                    projectFile = file
                    break

        return projectFile

    def __setProjectModified(self, mode: bool) -> None:
        """Handle project modification's events."""
        if self.__projectModifiedSignalPaused:
            return

        slicer.modules.AppContextInstance.mainWindow.setWindowModified(mode)

    def __configStorageNodeDefaults(self, *args, **kwargs) -> None:
        properties = DEFAULT_PROPERTIES.copy()
        customProperties = kwargs.get("properties")
        if customProperties is not None and isinstance(customProperties, dict):
            properties.update(customProperties)

        useCompression = properties.get("useCompression", 0)

        # Add default storage nodes for volume node types
        defaultVolumeStorageNode = slicer.vtkMRMLVolumeArchetypeStorageNode()
        defaultVolumeStorageNode.SetUseCompression(useCompression)

        if hasattr(defaultVolumeStorageNode, "SetForceRightHandedIJKCoordinateSystem"):
            defaultVolumeStorageNode.SetForceRightHandedIJKCoordinateSystem(False)

        slicer.mrmlScene.AddDefaultNode(defaultVolumeStorageNode)

        # Add default storage nodes for segmentation node types
        defaultSegStorageNode = slicer.vtkMRMLSegmentationStorageNode()
        defaultSegStorageNode.SetUseCompression(useCompression)
        slicer.mrmlScene.AddDefaultNode(defaultSegStorageNode)

    def __getNodesToSave(self) -> List[slicer.vtkMRMLNode]:
        nodesCollection = slicer.mrmlScene.GetNodesByClass("vtkMRMLStorableNode")
        nodesCount = nodesCollection.GetNumberOfItems()
        for idx in range(nodesCount):
            node = nodesCollection.GetItemAsObject(idx)
            hide = bool(node.GetHideFromEditors())
            saveWithScene = bool(node.GetSaveWithScene())

            if not saveWithScene:
                continue

            yield node

    def __saveNodes(self, firstSave: bool, *args, **kwargs) -> bool:
        """Handle the nodes saving process.

        Returns:
            bool: True if worked succesfully, otherwise returns False.
        """
        status = True

        rootPath = Path(slicer.mrmlScene.GetRootDirectory())
        dataFolder = (rootPath / "Data").resolve()
        if dataFolder.exists():
            filesToDelete = {path for path in dataFolder.iterdir()}
        else:
            filesToDelete = set()

        try:
            for node in self.__getNodesToSave():
                if not self.__handle_storable_node(node, *args, **kwargs):
                    continue

                storageNode = node.GetStorageNode()
                filePath = Path(storageNode.GetFileName()).resolve()
                filePaths = {filePath}

                # File name list. Typically used to store a table schema.
                for i in range(storageNode.GetNumberOfFileNames()):
                    path = Path(storageNode.GetNthFileName(i)).resolve()
                    filePaths.add(path)
                filesToDelete -= filePaths

                fileAlreadyExists = all(path.exists() for path in filePaths)
                if node.GetModifiedSinceRead() is False and fileAlreadyExists:
                    continue

                if filePath.exists() or not firstSave:
                    relativeNodeFilePath = filePath.relative_to(rootPath).as_posix()
                    status = slicer.util.saveNode(node, relativeNodeFilePath)
                    if not status:
                        logging.error(
                            "Failed to save {} node's file at the location: {}\n{}".format(
                                node.GetName(), filePath, traceback.format_exc()
                            )
                        )
                        return False
                    else:
                        # Retrieve new associate file paths to ensure they are not deleted
                        # in case it has the same path as files marked to delete
                        for i in range(storageNode.GetNumberOfFileNames()):
                            path = Path(storageNode.GetNthFileName(i)).resolve()
                            filesToDelete -= {path}
                        logging.debug("Node {} was saved succesfully at {}".format(node.GetName(), filePath))

            for filePath in filesToDelete:
                if filePath.is_dir():
                    shutil.rmtree(filePath)
                else:
                    filePath.unlink()
                logging.debug(f"{filePath} was deleted as it is no longer associated to any node.")

        except Exception as error:
            logging.error(f"A problem has occured during the nodes' save process: {error}\n{traceback.format_exc()}")
            return False

        return status

    def __getLocalizedStorageNode(
        self, node: slicer.vtkMRMLStorableNode, localStorageDir: Path
    ) -> slicer.vtkMRMLStorageNode:
        storageNode = node.GetStorageNode()

        # All files should be stored in the Data directory.
        # If the node's file name is in another directory, create a new default storage node.
        if storageNode and storageNode.GetFileName():
            filePath = Path(storageNode.GetFileName()).resolve()
            if filePath.parent != localStorageDir:
                slicer.mrmlScene.RemoveNode(storageNode)
                node.AddDefaultStorageNode()
        else:
            node.AddDefaultStorageNode()

        return node.GetStorageNode()

    def __handle_storable_node(self, node: slicer.vtkMRMLStorableNode, *args, **kwargs) -> bool:
        """Function that checks if storable node has a valid storage node or if it could be created.
            In case of creating a new storage node, it will define its filename.
            Otherwise, if it wouldn't be possible to create a new storage node,
            then it will mean that its not necessary to save this node individually.
            (Probably the scene file's writer will handle it)

        Args:
            node (slicer.vtkMRMLStorableNode): the storable node object.

        Returns:
            bool: True if node has a valid storage node, otherwise returns False.
        """
        if not hasattr(node, "GetStorageNode"):
            return False

        dataFolder = (Path(slicer.mrmlScene.GetRootDirectory()) / "Data").resolve()

        storageNode = self.__getLocalizedStorageNode(node, dataFolder)
        if not storageNode:
            return False

        filepath = Path(handleCopySuffixOnClonedNodes(storageNode))

        if not (filepath and is_valid_filename(filepath.name)):
            tempFileName = storageNode.GetTempFileName()
            if tempFileName and Path(tempFileName).is_relative_to(dataFolder):
                storageNode.SetFileName(tempFileName)
            else:
                ext = storageNode.GetDefaultWriteFileExtension()
                filePath = f"{(dataFolder / node.GetID()).as_posix()}.{ext}"
                storageNode.SetFileName(filePath)

        # Define compression mode
        properties = DEFAULT_PROPERTIES.copy()
        customProperties = kwargs.get("properties")
        if customProperties is not None and isinstance(customProperties, dict):
            properties.update(customProperties)

        useCompression = properties.get("useCompression", 0)
        storageNode.SetUseCompression(useCompression)

        return True

    def __saveScene(self, projectUrl: Union[str, Path], *args, **kwargs) -> bool:
        """Handle the nodes saving process.

        Args:
            projectUrl (str): the scene URL string.

        Returns:
            bool: True if worked succesfully, otherwise returns False.
        """
        status = True

        if isinstance(projectUrl, str):
            projectUrl = Path(projectUrl).resolve()

        try:
            status = slicer.util.saveScene(projectUrl.as_posix())
        except Exception as error:
            status = False
            logging.error(
                "A problem has occured during the save scene's process: {}\n{}".format(error, traceback.format_exc())
            )

        # Don't need to log in case of status being False because slicer.util.saveScene does that
        if status:
            logging.debug("Scene was saved succesfully!")

        return status

    def __clearMaskSettingsOnAllSegmentEditors(self) -> None:
        nodes = slicer.util.getNodesByClass("vtkMRMLSegmentEditorNode")
        for node in nodes:
            node.SourceVolumeIntensityMaskOff()

    def __pauseModifiedObserver(self) -> None:
        self.__projectModifiedSignalPaused = True

    def __resumeModifiedObserver(self, mode: bool = None) -> None:
        def process():
            self.__projectModifiedSignalPaused = False
            if mode is not None:
                self.__setProjectModified(mode)

        qt.QTimer.singleShot(100, process)


def getAvailableFilename(name: str, dirpath: Path):
    files = [file for file in dirpath.iterdir() if file.is_file()]
    fileNames = [file.name for file in files]
    if name not in fileNames:
        return name

    def check(base_name, filename):
        pattern = rf"^({re.escape(base_name)})?\s?(\(\d+\))?$"
        return re.fullmatch(pattern, filename)

    name, ext = os.path.splitext(name)
    count = 0
    suffixCount = 0
    currentNameHasSuffix = False

    sch = re.search(rf"^(\w+)?\s+?(\(\d+\))?", name)
    if sch and len(sch.groups()) >= 2:
        name = sch.group(1)
        currentNameHasSuffix = True
        number = int(re.sub(r"[()]", "", sch.group(2)))
        suffixCount = max(suffixCount, int(number))

    for file in files:
        fileStem = os.path.splitext(file.name)[0]
        match = check(name, fileStem)
        if not match:
            continue

        pattern = rf"^({re.escape(name)})?\s?(\(\d+\))?$"
        if sch := re.search(pattern, fileStem):
            if len(sch.groups()) < 2:
                continue

            if sch.group(2):
                number = int(re.sub(r"[()]", "", sch.group(2)))
                suffixCount = max(suffixCount, int(number))

        count += 1

    if count == 0 and suffixCount == 0 and currentNameHasSuffix is False:
        unique_name = name + ext
    else:
        unique_name = f"{name} ({suffixCount+1}){ext}"

    return unique_name
