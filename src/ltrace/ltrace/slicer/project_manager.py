import qt
import slicer
import vtk
import os
import logging
import re
import shutil
import traceback

from ltrace.slicer.helpers import bounds2size, singleton
from ltrace.slicer.nodes.custom_behavior_node_manager import CustomBehaviorNodeManager
from ltrace.slicer.nodes.defs import TriggerEvent
from ltrace.slicer.node_observer import NodeObserver
from pathlib import Path
from pathvalidate import sanitize_filepath, is_valid_filename
from typing import List

DEFAULT_PROPERTIES = {"useCompression": 0}


class HierarchyVisibilityManager:
    """Makes hierarchy folders above node visible when it becomes visible.
    Slicer has no visibility changed event (the modified event is triggered
    when a parent folder visibility is changed), so this class keeps track
    of the last visibility state of the node as a workaround.
    """

    def __init__(self, display_node: slicer.vtkMRMLDisplayNode, get_displayable_node: callable):
        # Set to false to trigger visibility change on first update
        self.__last_visibility = False
        self.__get_displayable_node = get_displayable_node
        display_node.AddObserver("ModifiedEvent", self.__on_node_modified)

    @staticmethod
    def __make_all_ancestors_visible(node):
        if node is None:
            return False
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        id_ = sh.GetItemByDataNode(node)
        if id_ == 0:
            return False
        plugin_handler = slicer.qSlicerSubjectHierarchyPluginHandler().instance()
        folder_plugin = plugin_handler.pluginByName("Folder")
        scene_id = sh.GetSceneItemID()
        while (id_ := sh.GetItemParent(id_)) != scene_id:
            node = sh.GetItemDataNode(id_)
            if isinstance(node, slicer.vtkMRMLFolderDisplayNode):
                folder_plugin.setDisplayVisibility(id_, 1)
            sh.SetItemDisplayVisibility(id_, True)
        return True

    def __on_node_modified(self, caller, event):
        if self.__last_visibility:
            self.__last_visibility = caller.GetVisibility()
        elif caller.GetVisibility():
            status = self.__make_all_ancestors_visible(self.__get_displayable_node(caller))
            # First few calls for volume rendering are before it's set up, we
            # should skip these so the callback is triggered again later
            if status:
                self.__last_visibility = caller.GetVisibility()


@singleton
class ProjectManager(qt.QObject):
    """Class to handle the 'project concept' from  Geoslicer.
    Specialize loading, saving and related slicer's process
    """

    projectChangedSignal = qt.Signal(None)

    def __init__(self, folder_icon_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__node_observers = list()
        self.__folder_icon_path = folder_icon_path
        self.__slices_shown = False
        self.custom_behavior_node_manager = CustomBehaviorNodeManager()
        self.__config_compression_mode()

    def save(self, project_url, internal_call=False, *args, **kwargs):
        """Handles project' saving process. It saves the nodes that has modifications and
           are related to the current scene, and then, saves the scene.

        Args:
            project_url (str): the scene filepath (.mrml).

        Returns:
            bool: True if save process was successful, otherwise False.
        """
        if not internal_call:
            self.custom_behavior_node_manager.triggerEvent = TriggerEvent.SAVE
            slicer.mrmlScene.StartState(slicer.mrmlScene.SaveState)
        status = True
        root_dir_before_save = slicer.mrmlScene.GetRootDirectory()
        self.__config_compression_mode(*args, **kwargs)
        if os.path.isdir(project_url):
            slicer.mrmlScene.SetRootDirectory(project_url)

            # Save Scene
            if not self.__save_scene(project_url, *args, **kwargs):
                slicer.mrmlScene.SetRootDirectory(root_dir_before_save)
                status = False
        else:
            slicer.mrmlScene.SetRootDirectory(os.path.dirname(project_url))

            # Save nodes
            status &= self.__save_nodes(*args, **kwargs)

            # Save Scene
            if not self.__save_scene(project_url, *args, **kwargs):
                slicer.mrmlScene.SetRootDirectory(root_dir_before_save)
                status = False

        if not internal_call:
            slicer.mrmlScene.EndState(slicer.mrmlScene.SaveState)

        if status:
            self.__set_project_modified(False)
        return status

    def save_as(self, scene_path, *args, **kwargs):
        """Handle custom save scene as operation."""
        self.custom_behavior_node_manager.triggerEvent = TriggerEvent.SAVE_AS
        slicer.mrmlScene.StartState(slicer.mrmlScene.SaveState)

        scene_path = Path(scene_path)

        if scene_path.is_file():
            slicer.util.errorDisplay(f'Cannot create project directory at "{scene_path}" because it is a file.')
            return False

        scene_path.mkdir(parents=True, exist_ok=True)
        self.save(str(scene_path), internal_call=True, *args, **kwargs)
        self.__configure_project_folder(str(scene_path))
        project_file = self.__find_project_file(str(scene_path))

        if project_file is None:
            return False

        slicer.mrmlScene.EndState(slicer.mrmlScene.SaveState)

        status = False
        file_project_path = os.path.join(str(scene_path), project_file)
        try:
            self.load(file_project_path)
        except Exception as error:
            status = False
            logging.error(
                "A problem occured during the 'Save As Scene' process: {}\n{}".format(error, traceback.format_exc())
            )
        else:
            status = True
            self.__set_project_modified(False)
            self.projectChangedSignal.emit()

        return status

    def load(self, project_file_path, internal_call=False):
        """Handle custom load scene operation."""
        if project_file_path == slicer.mrmlScene.GetURL():
            return

        if not internal_call:
            self.custom_behavior_node_manager.triggerEvent = TriggerEvent.LOAD

        self.__clear_node_observers()
        # Close scene before load a new one
        slicer.mrmlScene.Clear(0)
        slicer.util.loadScene(project_file_path)

        self.__set_project_modified(False)

    def setup(self):
        """Initialize project's event handlers"""
        self.end_close_scene_observer_handler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndCloseEvent, self.__on_end_close_scene
        )
        self.modified_event_observer_handler = slicer.mrmlScene.AddObserver("ModifiedEvent", self.__on_scene_modified)
        self.node_added_observer_handler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.NodeAddedEvent, self.__on_node_added
        )
        self.end_load_event_observer_handler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndImportEvent, self.__on_end_load_scene
        )

        self.start_load_event_observer_handler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.StartImportEvent, self.__on_start_load_scene
        )

    def __on_start_load_scene(self, *args, **kwargs):
        """Handle slicer' start load scene event."""
        slicer.mrmlScene.RemoveObserver(self.modified_event_observer_handler)

    def __on_end_close_scene(self, *args):
        """Handle slicer' end close scene event."""

        self.__slices_shown = False

        def process():
            self.__set_project_modified(False)
            self.projectChangedSignal.emit()

        # Add 'process' method to the end of the Qt's events queue.
        qt.QTimer.singleShot(0, process)

    def __on_end_load_scene(self, *args, **kwargs):
        """Handle slicer' end load scene event."""
        slicer.util.mainWindow().setWindowModified(False)
        self.projectChangedSignal.emit()
        self.modified_event_observer_handler = slicer.mrmlScene.AddObserver("ModifiedEvent", self.__on_scene_modified)

        # Hide axis labels for legacy projects which may have them.
        # This can probably be removed in the future, as it is also done
        # when GeoSlicer starts.
        viewNode = slicer.app.layoutManager().threeDWidget(0).mrmlViewNode()
        viewNode.SetAxisLabelsVisible(False)

        # Without this the Image Log segmenter doesn't correctly restore the selected segmentation node
        image_log_data_logic = slicer.modules.imagelogdata.widgetRepresentation().self().logic
        image_log_data_logic.imageLogSegmenterWidget.self().initializeSavedNodes()

        # Image Log number of views restoration
        if slicer.app.layoutManager().layout >= 15000:
            image_log_data_logic.configurationsNode = None
            image_log_data_logic.loadConfiguration()

        self.__clear_mask_settings_on_all_segment_editors()

    def __on_scene_modified(self, *args, **kwargs):
        """Handle slicer' scene modified event."""
        self.__set_project_modified(True)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def __on_node_added(self, caller, eventId, callData):
        """Handle slicer' node added to scene event."""
        observer = NodeObserver(node=callData, parent=self)
        observer.modifiedSignal.connect(self.__on_scene_modified)
        observer.removedSignal.connect(self.__on_observed_node_removed)

        self.__node_observers.append(observer)

        if isinstance(callData, slicer.vtkMRMLVolumeNode):

            def onVolumeModified(node_observer: NodeObserver, node: slicer.vtkMRMLNode) -> None:
                if node is None:
                    return

                # Wait for the volume to load
                qt.QTimer.singleShot(0, lambda: self.__on_volume_modified(node))

            observer.modifiedSignal.connect(onVolumeModified)
        elif isinstance(callData, slicer.vtkMRMLVolumeRenderingDisplayNode):
            volume_rendering = callData
            volume_rendering.SetFollowVolumeDisplayNode(True)
            HierarchyVisibilityManager(volume_rendering, lambda node: node.GetVolumeNode())
        elif isinstance(callData, slicer.vtkMRMLSegmentationDisplayNode):
            segmentation_display = callData
            HierarchyVisibilityManager(segmentation_display, lambda node: node.GetDisplayableNode())

    def __on_observed_node_removed(self, node_observer: NodeObserver, node: slicer.vtkMRMLNode) -> None:
        """Handle when a node being observed is removed from the scene."""
        if node_observer not in self.__node_observers:
            return

        self.__node_observers.remove(node_observer)

    def __clear_node_observers(self):
        """Clear the node observer's list and remove the observer handlers from each one."""
        for node_observer in self.__node_observers:
            node_observer.clear()

        self.__node_observers.clear()

    def __configure_project_folder(self, project_path):
        """Applies folder's custom configuration

        Args:
            project_path (str): the folder path
        """
        platform = os.name
        if platform == "nt":  # Windows:
            self.__create_project_folder_configuration_file(
                project_path=project_path,
                ConfirmFileOp=1,
                NoSharing=0,
                IconFile=self.__folder_icon_path,
                IconIndex=0,
                InfoTip="This is a Geoslicer project folder",
            )
        elif platform == "posix":  # Linux:
            self.__create_project_folder_configuration_file(project_path=project_path, Icon=self.__folder_icon_path)
        else:
            pass

    def __create_project_folder_configuration_file(self, project_path, *args, **kwargs):
        """Wrapper for creating the file that configures the folder attributes.
        Works with the following OS: Windows, Linux

        Args:
            project_path (str): the folder path to be configured

        Raises:
            Exception: Not supported OS.
            Exception: Not valid icon file.
        """
        platform = os.name

        if platform == "nt":  # Windows
            icon_parameter_label = "IconFile"
            config_file_name = "desktop.ini"
            header = "[.ShellClassInfo]"

            def post_setup(config_file):
                # Add attributes to the config file (Mandatory)
                os.system('attrib +h +s "{}"'.format(config_file))

                # Add attributes to the directory (Mandatory)
                os.system('attrib +r "{}"'.format(os.path.dirname(config_file)))

        elif platform == "posix":  # Linux
            icon_parameter_label = "Icon"
            config_file_name = ".directory"
            header = "[Desktop Entry]"

            def post_setup(config_file):
                # TODO: test if this works consistently in different Linux systems
                command = f'gio set -t string "{project_path}"'
                command += f' metadata::custom-icon "file://{project_path}/ProjectIcon.ico"'
                command += f' && touch "{project_path}"'
                os.system(command)

        else:
            raise Exception("Current OS is not supported by this function.")

        if icon_parameter_label in kwargs.keys():
            icon_file = kwargs[icon_parameter_label]
            if os.path.isfile(icon_file):
                shutil.copy2(icon_file, project_path)
                kwargs[icon_parameter_label] = os.path.basename(icon_file)

        data = header + "\n"
        for k, v in kwargs.items():
            data += "{}={}\n".format(k, v)

        config_file = os.path.join(project_path, config_file_name)

        # Create folder configuration file
        with open(config_file, "w", encoding="utf-8") as file:
            file.write(data)

        # Apply post configurations
        post_setup(config_file)

    def __find_project_file(self, project_path: str, extension=".mrml"):
        """Search for project file inside path.

        Args:
            project_path (str): The directory to search for the project file
            extension (str, optional): The project file extension. Defaults to ".mrml".

        Returns:
            str: The project file path if it was found. Otherwise, None
        """
        project_file = None
        for _, _, files in os.walk(project_path):
            for file in files:
                if file.endswith(extension):
                    project_file = file
                    break

        return project_file

    def __set_project_modified(self, mode: bool):
        """Handle project modification's events."""
        slicer.util.mainWindow().setWindowModified(mode)

    def __config_compression_mode(self, *args, **kwargs):
        properties = DEFAULT_PROPERTIES.copy()
        custom_properties = kwargs.get("properties")
        if custom_properties is not None and isinstance(custom_properties, dict):
            properties.update(custom_properties)

        use_compression = properties.get("useCompression", 0)

        # Add default storage nodes for volume node types
        default_volume_storage_node = slicer.vtkMRMLVolumeArchetypeStorageNode()
        default_volume_storage_node.SetUseCompression(use_compression)
        slicer.mrmlScene.AddDefaultNode(default_volume_storage_node)

        # Add default storage nodes for segmentation node types
        default_seg_storage_node = slicer.vtkMRMLSegmentationStorageNode()
        default_seg_storage_node.SetUseCompression(use_compression)
        slicer.mrmlScene.AddDefaultNode(default_seg_storage_node)

    def __get_nodes_to_save(self) -> List[slicer.vtkMRMLNode]:
        nodes_collection = slicer.mrmlScene.GetNodesByClass("vtkMRMLStorableNode")
        nodesCount = nodes_collection.GetNumberOfItems()
        for idx in range(nodesCount):
            node = nodes_collection.GetItemAsObject(idx)
            hide = bool(node.GetHideFromEditors())
            save_with_scene = bool(node.GetSaveWithScene())

            if not save_with_scene:
                continue

            yield node

    def __save_nodes(self, *args, **kwargs):
        """Handle the nodes saving process.

        Returns:
            bool: True if worked succesfully, otherwise returns False.
        """
        status = True

        data_folder = Path(slicer.mrmlScene.GetRootDirectory()) / "Data"
        files_to_delete = set(data_folder.iterdir())

        for node in self.__get_nodes_to_save():
            if not self.__handle_storable_node(node, *args, **kwargs):
                continue

            storage_node = node.GetStorageNode()
            file_path = Path(storage_node.GetFileName()).resolve()
            file_paths = {file_path}

            # File name list. Typically used to store a table schema.
            for i in range(storage_node.GetNumberOfFileNames()):
                path = Path(storage_node.GetNthFileName(i)).resolve()
                file_paths.add(path)
            files_to_delete -= file_paths

            file_already_exists = all(path.exists() for path in file_paths)
            if node.GetModifiedSinceRead() is False and file_already_exists:
                continue

            file_path = str(file_path)
            node_status = slicer.util.saveNode(node, file_path)
            if not node_status:
                logging.error(
                    "Failed to save {} node's file at the location: {}\n{}".format(
                        node.GetName(), file_path, traceback.format_exc()
                    )
                )
            else:
                logging.debug("Node {} was saved succesfully at {}".format(node.GetName(), file_path))
            status &= node_status

        for file_path in files_to_delete:
            file_path.unlink()
            logging.debug(f"File {file_path} was deleted as it is no longer associated to any node.")

        return status

    def __handle_storable_node(self, node, *args, **kwargs):
        """Function that checks if storable node has a valid storage node or if it could be created.
            In case of creating a new storage node, it will define its filename.
            Otherwise, if it wouldn't be possible to create a new storage node,
            then it will mean that its not necessary to save this node individually.
            (Probably the scene file's writer will handle it)

        Args:
            node (vtk.vtkMRMLStorableNode): the storable node object.

        Returns:
            bool: True if node has a valid storage node, otherwise returns False.
        """
        data_folder = Path(slicer.mrmlScene.GetRootDirectory()) / "Data"

        if not hasattr(node, "GetStorageNode"):
            return False

        storage_node = node.GetStorageNode()

        # All files should be stored in the Data directory.
        # If the node's file name is in another directory, create a new default storage node.
        if storage_node and storage_node.GetFileName():
            file_path = Path(storage_node.GetFileName()).resolve()
            if file_path.parent != data_folder:
                slicer.mrmlScene.RemoveNode(storage_node)

        storage_node = node.GetStorageNode()
        if storage_node is None:
            if not node.AddDefaultStorageNode():
                # If storable node doesn't have a storage node and isn't possible to create one,
                # it means that scene will handle its saving.
                # ref: https://github.com/Slicer/Slicer/blob/78f426ec6abc5ec6b0513542556b2016c1f54852/Base/QTGUI/qSlicerSaveDataDialog.cxx#L528
                return False

        # Retrieve storage node again,
        # in case of method 'AddDefaultStorageNode' call happened
        storage_node = node.GetStorageNode()
        if storage_node is None:
            return False

        file_path = storage_node.GetFileName()
        if file_path == "" or file_path is None or is_valid_filename(os.path.basename(file_path)) is False:
            # Define node's filepath

            file_path = self.__create_node_file_name(str(data_folder), node)
            if file_path is None:
                return False

            storage_node.SetFileName(file_path)

        # Define compression mode
        properties = DEFAULT_PROPERTIES.copy()
        custom_properties = kwargs.get("properties")
        if custom_properties is not None and isinstance(custom_properties, dict):
            properties.update(custom_properties)

        use_compression = properties.get("useCompression", 0)
        storage_node.SetUseCompression(use_compression)

        return True

    def __create_node_file_name(self, file_folder, node):
        """Handles node's filename creation.

        Args:
            file_folder (str): the folder where file will be created.
            node (vtk.vtkMRMLStorableNode): the node object.

        Returns:
            str/None: the node's filename. None if node's doesn't have a storage node.
        """
        storage_node = node.GetStorageNode()
        if storage_node is None:
            return None

        file_extension = storage_node.GetDefaultWriteFileExtension()
        index = 0
        while True:
            if index == 0:
                file_name = f"{node.GetName()}.{file_extension}"
            else:
                file_name = f"{node.GetName()} ({index}).{file_extension}"

            file_path = os.path.join(file_folder, file_name)
            file_path = sanitize_filepath(file_path=file_path, platform="auto")

            if os.path.exists(file_path) is False:
                break

            index += 1
            if index >= 1000:
                logging.error(
                    "A problem has occured during node's filename creation. Stopping process to avoid infinite loop."
                )
                break

        return file_path

    def __save_scene(self, project_url, *args, **kwargs):
        """Handle the nodes saving process.

        Args:
            project_url (str): the scene URL string.

        Returns:
            bool: True if worked succesfully, otherwise returns False.
        """
        status = True

        try:
            slicer.util.saveScene(project_url)
        except Exception as error:
            status = False
            raise RuntimeError(
                "A problem has occured during the save scene's process: {}\n{}".format(error, traceback.format_exc())
            )
        else:
            status = True
            self.__set_project_modified(False)
            logging.debug("Scene was saved succesfully!")

        return status

    def __on_volume_modified(self, volume: slicer.vtkMRMLNode) -> None:
        if volume is None:
            return

        autoFrameOff = volume.GetAttribute("AutoFrameOff")
        autoSliceVisibleOff = volume.GetAttribute("AutoSliceVisibleOff")
        if volume.GetImageData():
            if not self.__slices_shown and not slicer.mrmlScene.GetURL() and autoSliceVisibleOff != "true":
                # Open slice eyes once for a new project
                self.__show_slices_in_3d()
                self.__slices_shown = True
            if autoFrameOff != "true":
                self.__frame_volume(volume)

    def __show_slices_in_3d(self):
        if slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLScalarVolumeNode") == 0:
            return
        layoutManager = slicer.app.layoutManager()
        for sliceViewName in layoutManager.sliceViewNames():
            controller = layoutManager.sliceWidget(sliceViewName).sliceController()
            controller.setSliceVisible(True)

    def __frame_volume(self, volume):
        """Reposition camera so it points to the center of the volume and
        position it so the volume is reasonably visible.
        """
        bounds = [0] * 6
        volume.GetBounds(bounds)
        size = bounds2size(bounds)
        leastCorner = tuple(min(bounds[i * 2], bounds[i * 2 + 1]) for i in range(3))
        center = tuple(leastCorner[i] + size[i] / 2 for i in range(3))
        diagonalSize = sum((side**2 for side in size)) ** 0.5

        camNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLCameraNode")
        cam = camNode.GetCamera()
        cam.SetFocalPoint(center)
        pos = tuple(coord + diagonalSize for coord in center)
        cam.SetPosition(pos)
        camNode.ResetClippingRange()

    def __clear_mask_settings_on_all_segment_editors(self):
        nodes = slicer.util.getNodesByClass("vtkMRMLSegmentEditorNode")
        for node in nodes:
            node.SourceVolumeIntensityMaskOff()
