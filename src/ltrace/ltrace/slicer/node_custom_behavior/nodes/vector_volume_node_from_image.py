import slicer
import cv2
import logging
import numpy as np
import shutil
import tempfile

from ltrace.slicer.node_custom_behavior.node_custom_behavior_base import (
    NodeCustomBehaviorBase,
    CustomBehaviorRequirements,
)
from ltrace.slicer.node_custom_behavior.defs import TriggerEvent
from ltrace.slicer.node_attributes import LosslessAttribute
from ltrace.slicer.helpers import isImageFile
from ltrace.slicer import export
from pathvalidate import sanitize_filepath
from pathlib import Path
from typing import Union


TAG_TEMPORARY_DIRECTORY = "LTraceImageNode"
SOURCE_IMAGE_ATTRIBUTE_LABEL = "SourceImage"


class VectorVolumeNodeFromImageCustomBehavior(NodeCustomBehaviorBase):
    """Custom behavior for volumes loaded from a image file (.jpg, .png, etc...).
    It stores the original image file in the project data directory to be loaded every time the node is loaded.
    This behavior prevents slicer conversion (from image to nrrd) from greatly increase the node project file size.
    """

    REQUIREMENTS = CustomBehaviorRequirements(
        nodeTypes=[slicer.vtkMRMLVectorVolumeNode], attributes={LosslessAttribute.name(): LosslessAttribute.FALSE.value}
    )

    def __init__(self, node: slicer.vtkMRMLNode, event: TriggerEvent) -> None:
        super().__init__(node=node, event=event)

    def _afterLoad(self) -> None:
        if self._event == TriggerEvent.NONE:
            return

        self._loadDataFromImageFile()

    def _afterSave(self) -> None:
        """Store image file used when the data was loaded for the first time."""
        storageNode = self._node.GetStorageNode()
        if storageNode is None:
            logging.error(f"Skipping custom behavior for node {self._node.GetName()} due missing its storage node.")
            return

        sourceImageFilePath = self._node.GetAttribute(SOURCE_IMAGE_ATTRIBUTE_LABEL)
        if sourceImageFilePath is None:
            logging.error(
                f"Skipping custom behavior for node {self._node.GetName()} due missing its source image file path information."
            )
            return

        # Creater directory if its 'Data' folder is missing for any reason
        currentNodeProjectDataDirectory = Path(slicer.mrmlScene.GetRootDirectory()) / "Data"
        if not currentNodeProjectDataDirectory.is_dir():
            currentNodeProjectDataDirectory.mkdir(parents=True, exist_ok=True)

        sourceImageFilePath = Path(sourceImageFilePath)
        # Check if the source image file is stored in a temporary directory.
        # If so, then make a copy in the project data directory.
        if self.__isTemporaryDirectory(sourceImageFilePath) or not self.__isPathFromProjectDirectory(
            sourceImageFilePath
        ):
            destinationSourceImageFilePath = Path(shutil.copy(sourceImageFilePath, currentNodeProjectDataDirectory))
            assert (
                destinationSourceImageFilePath.is_file()
            ), "Source image file doesn't exists in the project directory."

            # Update attribute
            self._node.SetAttribute(SOURCE_IMAGE_ATTRIBUTE_LABEL, destinationSourceImageFilePath.as_posix())

        # Reload data from the image to maintaing node's data updated. Only if its was triggered by a 'save' event.
        if self._event != TriggerEvent.SAVE_AS:
            self._loadDataFromImageFile()

        if self.__isTemporaryDirectory(sourceImageFilePath):
            shutil.rmtree(sourceImageFilePath.parent)

    def _beforeSave(self) -> None:
        """Save image file to a temporary directory and reset array from the node."""
        storageNode = self._node.GetStorageNode()
        sourceFilePath = Path(storageNode.GetFileName()) if storageNode is not None else ""
        # Check if it is the first time saving the 'lossy' image node
        # When its the first time saving
        sourceImageFilePath = self._node.GetAttribute(SOURCE_IMAGE_ATTRIBUTE_LABEL)
        if not sourceImageFilePath and isImageFile(
            sourceFilePath
        ):  # First-time saving an usual volume node with lossy attributes
            destinationPath = self.__createTemporaryDirectory()
            sourceImageFilePath = destinationPath / sourceFilePath.name
            self._node.SetAttribute(SOURCE_IMAGE_ATTRIBUTE_LABEL, sourceImageFilePath.as_posix())
        elif (
            sourceImageFilePath
            and sourceFilePath
            and not isImageFile(sourceFilePath)
            and self._event == TriggerEvent.SAVE_AS
        ):  # Old lossy node during 'save as' event
            destinationPath = self.__createTemporaryDirectory()
            sourceImageFilePath = destinationPath / Path(sourceImageFilePath).name
            self._node.SetAttribute(SOURCE_IMAGE_ATTRIBUTE_LABEL, sourceImageFilePath.as_posix())
        elif (
            storageNode is None
        ):  # and not sourceImageFilePath:  # Saving cloned volume node with lossless attribute but without source image attribute
            destinationPath = self.__createTemporaryDirectory()
            extension = Path(sourceImageFilePath).suffix if sourceImageFilePath else ".jpg"  # use jpg as default format
            fileName = sanitize_filepath(f"{self._node.GetName()}{extension}")
            sourceImageFilePath = destinationPath / fileName
            self._node.SetAttribute(SOURCE_IMAGE_ATTRIBUTE_LABEL, sourceImageFilePath.as_posix())
        elif (
            storageNode is not None and not sourceImageFilePath and not isImageFile(sourceFilePath)
        ):  # No data available to create a lossy image node
            logging.error("Invalid node data. The source image file path attribute is missing.")
            return

        # Export current array to image file
        self._exportImageWrapper(node=self._node, destinationImageFile=sourceImageFilePath)

        # Clear node's data to reduce nrrd file size.
        array = slicer.util.arrayFromVolume(self._node)
        shape_tuple = (1,) * (array.ndim - 1) + (array.ndim - 1,)
        empty_array = np.empty(shape_tuple, dtype=array.dtype)
        slicer.util.updateVolumeFromArray(self._node, empty_array)
        self._node.Modified()

    def _exportImageWrapper(self, node: slicer.vtkMRMLNode, destinationImageFile: Union[str, Path]) -> None:
        if isinstance(destinationImageFile, str):
            destinationImageFile = Path(destinationImageFile)

        array = slicer.util.arrayFromVolume(node)
        imageArray = cv2.cvtColor(array[0, :, :, :], cv2.COLOR_BGR2RGB)

        export.exportNodeAsImage(
            nodeName=destinationImageFile.stem,
            dataArray=imageArray,
            imageFormat=destinationImageFile.suffix,
            rootPath=destinationImageFile.parents[1],
            nodePath=destinationImageFile.parents[0].name,
        )

    def _loadDataFromImageFile(self) -> None:
        self.updateNodeReference()
        imageFilePath = self._node.GetAttribute(SOURCE_IMAGE_ATTRIBUTE_LABEL)
        if imageFilePath is None:
            logging.error(
                f"Skipping custom behavior for node {self._node.GetName()} due missing its source image file path information."
            )
            return

        storageNode = self._node.GetStorageNode()
        if storageNode is None:
            logging.error(f"Skipping custom behavior for node {self._node.GetName()} due missing its storage node.")
            return

        # Check if current source image information is stored in a temporary directory.
        # If so, updates the node attribute to the image file in project data directory.
        imageFilePath = Path(imageFilePath)
        if self.__isTemporaryDirectory(imageFilePath) or not self.__isPathFromProjectDirectory(imageFilePath):
            imageFileInProjectPath = Path(storageNode.GetFileName()).parent / imageFilePath.name
            if not imageFileInProjectPath.is_file():
                logging.error(
                    f"Failed to load '{self._node.GetName()}' node. The image's file is missing: {imageFileInProjectPath.as_posix()}"
                )
                return

            imageFilePath = imageFileInProjectPath
            self._node.SetAttribute(SOURCE_IMAGE_ATTRIBUTE_LABEL, imageFilePath.as_posix())

        if not imageFilePath.is_file():
            logging.error(
                f"Failed to load '{self._node.GetName()}' node. The image's file is missing: {imageFilePath.as_posix()}"
            )
            return

        # Create temporary node to load the image array
        tempVolumeNode = slicer.util.loadVolume(imageFilePath.as_posix(), properties={"show": False})
        tempVolumeNode.SetHideFromEditors(True)

        array = slicer.util.arrayFromVolume(tempVolumeNode)
        slicer.util.updateVolumeFromArray(self._node, array)
        displayNode = self._node.GetDisplayNode()
        if displayNode is None:
            self._node.CreateDefaultDisplayNodes()

        self._node.GetDisplayNode().Copy(tempVolumeNode.GetDisplayNode())

        # Add image file to StorageNode to avoid problems with the future to remove unused project files.
        storageNode.AddFileName(imageFilePath.as_posix())

        self._node.Modified()

        # Remove temporary node
        slicer.mrmlScene.RemoveNode(tempVolumeNode)

    def __isTemporaryDirectory(self, path: Union[str, Path]) -> bool:
        if isinstance(path, str):
            path = Path(path)

        dirName = path.name if path.is_dir() else path.parent.name
        return Path(tempfile.gettempdir()) in path.parents and dirName == TAG_TEMPORARY_DIRECTORY

    def __isPathFromProjectDirectory(self, path: Union[str, Path]) -> bool:
        if isinstance(path, str):
            path = Path(path)

        currentProjectDirectoryPath = Path(slicer.mrmlScene.GetRootDirectory())
        return currentProjectDirectoryPath in path.parents

    def __createTemporaryDirectory(self) -> Path:
        destinationPath = Path(tempfile.mkdtemp()) / TAG_TEMPORARY_DIRECTORY
        destinationPath.mkdir(parents=True, exist_ok=True)
        return destinationPath
