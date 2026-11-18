from commons.slicer.helpers import make_directory_writable, tryGetNode
from commons.slicer.nodes.directory_node import DirectoryNode
from commons.slicer.tests.utils import (
    close_project,
    load_project,
    process_events,
    save_current_project,
    save_project,
)
from commons.slicer_utils import LTracePluginTest
from pathlib import Path

import shutil
import slicer
import tempfile


DUMMY_FILE_NAME = "dummy.txt"


class DirectoryNodeTest(LTracePluginTest):
    """Test suite for the directory node's custom behavior during the project's save process."""

    def post_setup(self) -> None:
        self.__temp_dir_path = Path(tempfile.mkdtemp()).resolve()

    def tear_down(self) -> None:
        shutil.rmtree(self.__temp_dir_path, onexc=make_directory_writable)

    def test_save(self) -> None:
        """Assert the directory a directory node points to is stored inside the project's 'Data'
        directory when the project is saved, that it is kept there by the following saves, and
        that it is deleted when its node is removed from the scene.
        """
        project_file_path = self.__temp_dir_path / "project" / "project.mrml"
        project_data_dir_path = project_file_path.parent / "Data"

        # Test if directory node created before the first save is moved to project
        first_source_dir_path = self.__create_source_dir("first")
        first_node_id = DirectoryNode(first_source_dir_path, "first directory").getNode().GetID()

        assert save_project(project_file_path), "Failed to save the project."
        process_events()

        self.__assert_directory_in_project(project_data_dir_path, first_node_id, "first")

        assert not first_source_dir_path.exists(), (
            f"Failed to move '{first_source_dir_path.as_posix()}' to the project."
        )

        # Test if directory node created after the first save is kept in the project dir after a second save
        second_source_dir_path = self.__create_source_dir("second")
        second_node_id = DirectoryNode(second_source_dir_path, "second directory").getNode().GetID()

        assert save_current_project(), "Failed to save the current project. [0]"
        process_events()

        self.__assert_directory_in_project(project_data_dir_path, second_node_id, "second")
        self.__assert_directory_in_project(project_data_dir_path, first_node_id, "first")

        # Test directory deleted at node removal
        slicer.mrmlScene.RemoveNode(tryGetNode(first_node_id))
        process_events()

        assert save_current_project(), "Failed to save the current project. [1]"
        process_events()

        removed_node_dir_path = project_data_dir_path / first_node_id
        assert not removed_node_dir_path.exists(), (
            f"'{removed_node_dir_path.as_posix()}' was not deleted from the project."
        )
        self.__assert_directory_in_project(project_data_dir_path, second_node_id, "second")

    def test_duplicated_name(self) -> None:
        """Check if two directory nodes with same name can be successfully saved."""
        project_file_path = self.__temp_dir_path / "project" / "project.mrml"
        project_data_dir_path = project_file_path.parent / "Data"

        first_source_dir_path = self.__create_source_dir("first")
        first_node_id = DirectoryNode(first_source_dir_path, "node_duplicated_name").getNode().GetID()
        second_source_dir_path = self.__create_source_dir("second")
        second_node_id = DirectoryNode(second_source_dir_path, "node_duplicated_name").getNode().GetID()

        assert save_project(project_file_path), "Failed to save the project."
        process_events()

        self.__assert_directory_in_project(project_data_dir_path, second_node_id, "second")
        self.__assert_directory_in_project(project_data_dir_path, first_node_id, "first")

    def test_reload(self) -> None:
        """Assert a directory node still points to the directory stored inside the project's 'Data'
        directory after the project is closed and loaded again.
        """
        project_file_path = self.__temp_dir_path / "project" / "project.mrml"
        project_data_dir_path = project_file_path.parent / "Data"

        source_dir_path = self.__create_source_dir("reloaded")
        node_id = DirectoryNode(source_dir_path, "reloaded directory").getNode().GetID()

        assert save_project(project_file_path), "Failed to save the project."
        process_events()

        self.__assert_directory_in_project(project_data_dir_path, node_id, "reloaded")

        close_project()
        load_project(project_file_path)
        process_events()

        assert Path(slicer.mrmlScene.GetURL()) == project_file_path, (
            f"Failed to load the project '{project_file_path.as_posix()}'."
        )

        # The node must keep pointing to the directory inside the project
        self.__assert_directory_in_project(project_data_dir_path, node_id, "reloaded")

    def test_move_project_dir(self) -> None:
        """Assert a directory node still points to the directory stored inside the project's 'Data'
        directory even if the entire project directory was moved in the file system.
        """
        project_file_path = self.__temp_dir_path / "project" / "project.mrml"

        source_dir_path = self.__create_source_dir("moved")
        node_id = DirectoryNode(source_dir_path, "moved directory").getNode().GetID()

        assert save_project(project_file_path), "Failed to save the project."
        process_events()

        self.__assert_directory_in_project(project_file_path.parent / "Data", node_id, "moved")

        close_project()

        # Move the project directory
        moved_project_file_path = self.__temp_dir_path / "movedProject Name" / project_file_path.name
        project_file_path.parent.rename(moved_project_file_path.parent)

        # Load the project from the moved directory
        load_project(moved_project_file_path)
        process_events()

        assert Path(slicer.mrmlScene.GetURL()) == moved_project_file_path, (
            f"Failed to load the project '{moved_project_file_path.as_posix()}'."
        )

        # The node must point to the directory inside the moved project
        self.__assert_directory_in_project(moved_project_file_path.parent / "Data", node_id, "moved")

    def test_clone_before_save(self) -> None:
        """Assert a directory node and its clone, both created before the project's first save,
        get their own directory inside the project's 'Data' directory.
        """
        project_file_path = self.__temp_dir_path / "project" / "project.mrml"
        project_data_dir_path = project_file_path.parent / "Data"

        source_dir_path = self.__create_source_dir("cloned")
        node_id = DirectoryNode(source_dir_path, "cloned directory").getNode().GetID()
        cloned_node_id = self.__clone_node(tryGetNode(node_id)).GetID()

        assert save_project(project_file_path), "Failed to save the project."
        process_events()

        assert not source_dir_path.exists(), f"Failed to move '{source_dir_path.as_posix()}' to the project."

        # Each node must have its own directory in the project
        self.__assert_directory_in_project(project_data_dir_path, node_id, "cloned")
        self.__assert_directory_in_project(project_data_dir_path, cloned_node_id, "cloned")

    def test_clone_after_save(self) -> None:
        """Assert a directory node cloned after the project's first save gets its own directory
        inside the project's 'Data' directory, keeping the cloned node's one.
        """
        project_file_path = self.__temp_dir_path / "project" / "project.mrml"
        project_data_dir_path = project_file_path.parent / "Data"

        source_dir_path = self.__create_source_dir("cloned")
        node_id = DirectoryNode(source_dir_path, "cloned directory").getNode().GetID()

        assert save_project(project_file_path), "Failed to save the project."
        process_events()

        self.__assert_directory_in_project(project_data_dir_path, node_id, "cloned")

        cloned_node_id = self.__clone_node(tryGetNode(node_id)).GetID()

        assert save_current_project(), "Failed to save the current project."
        process_events()

        # Each node must have its own directory in the project
        self.__assert_directory_in_project(project_data_dir_path, node_id, "cloned")
        self.__assert_directory_in_project(project_data_dir_path, cloned_node_id, "cloned")

    def test_constructor(self) -> None:
        """Assert a directory node is created from a directory's path, and that only a node marked
        as a directory node can be wrapped by 'DirectoryNode'.
        """
        source_dir_path = self.__create_source_dir("constructed")

        # A directory node is created in the scene, pointing to the given directory
        directory_node = DirectoryNode(source_dir_path, "constructed directory")
        node = directory_node.getNode()

        assert node is not None, "The directory node wasn't created."
        assert tryGetNode(node.GetID()) is not None, f"The node '{node.GetID()}' isn't in the scene."
        assert node.GetName() == "constructed directory", f"Unexpected node's name: '{node.GetName()}'."
        assert node.IsA(DirectoryNode.getNodeType().__name__), (
            f"Expected a '{DirectoryNode.getNodeType().__name__}' node. Got a '{node.GetClassName()}' node."
        )
        assert node.GetStorageNode() is not None, f"The node '{node.GetID()}' has no storage node."
        assert DirectoryNode.isDirectoryNode(node), f"The node '{node.GetID()}' isn't marked as a directory node."
        assert directory_node.getDirPath() == source_dir_path, (
            f"Expected the node to point to '{source_dir_path.as_posix()}'. It points to '{str(directory_node.getDirPath())}'."
        )

        # A directory node can be wrapped again from its node
        wrapped_directory_node = DirectoryNode(node)
        assert wrapped_directory_node.getNode().GetID() == node.GetID(), (
            f"Expected to wrap the node '{node.GetID()}'. Got '{wrapped_directory_node.getNode().GetID()}'."
        )
        assert wrapped_directory_node.getDirPath() == source_dir_path

        # A node of the same type, but not marked as a directory node, can't be wrapped
        other_node = slicer.mrmlScene.AddNewNodeByClass(DirectoryNode.getNodeType().__name__, "not a directory")
        assert not DirectoryNode.isDirectoryNode(other_node), (
            f"The node '{other_node.GetID()}' shouldn't be a directory node."
        )
        with self.assertRaises(ValueError):
            DirectoryNode(other_node)

        # Neither can a node of another type
        table_node = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__, "table")
        assert not DirectoryNode.isDirectoryNode(table_node), (
            f"The node '{table_node.GetID()}' shouldn't be a directory node."
        )
        with self.assertRaises(ValueError):
            DirectoryNode(table_node)

    def __clone_node(self, node: slicer.vtkMRMLNode) -> slicer.vtkMRMLNode:
        """Clone a node through the subject hierarchy, as the user does.

        Args:
            node (slicer.vtkMRMLNode): the node to be cloned.

        Returns:
            slicer.vtkMRMLNode: the cloned node.
        """
        subject_hierarchy_node = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        item_id = subject_hierarchy_node.GetItemByDataNode(node)
        cloned_item_id = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(
            subject_hierarchy_node, item_id
        )
        cloned_node = subject_hierarchy_node.GetItemDataNode(cloned_item_id)
        process_events()

        assert cloned_node is not None, f"Failed to clone the node '{node.GetName()}'."

        return cloned_node

    def __create_source_dir(self, label: str) -> Path:
        """Create a directory containing a dummy file, outside of any project directory.

        Args:
            label (str): the directory's name, also used as the dummy file's content.

        Returns:
            Path: the created directory's path.
        """
        source_dir_path = self.__temp_dir_path / "sources" / label
        source_dir_path.mkdir(parents=True, exist_ok=True)
        (source_dir_path / DUMMY_FILE_NAME).write_text(label)

        return source_dir_path

    def __assert_directory_in_project(self, project_data_dir_path: Path, node_id: str, label: str) -> None:
        """Assert the directory related to the node, and its dummy file, are inside the project's 'Data' directory.

        Args:
            project_data_dir_path (Path): the project's 'Data' directory path.
            node_id (str): the directory node's ID.
            label (str): the expected dummy file's content.
        """
        node_dir_path = project_data_dir_path / node_id
        dummy_file_path = node_dir_path / DUMMY_FILE_NAME

        assert node_dir_path.is_dir(), f"The directory '{node_dir_path.as_posix()}' is missing from the project."
        assert dummy_file_path.is_file(), f"The file '{dummy_file_path.as_posix()}' is missing from the project."

        dummy_file_content = dummy_file_path.read_text()
        assert dummy_file_content == label, (
            f"Expected the content of '{dummy_file_path.as_posix()}' to be '{label}'. Actual content is '{dummy_file_content}'."
        )

        node = tryGetNode(node_id)
        assert node is not None, f"The node '{node_id}' is missing from the scene."

        node_dir_path_attribute = DirectoryNode(node).getDirPath()
        assert node_dir_path_attribute == node_dir_path, (
            f"Expected the node '{node_id}' to point to '{node_dir_path.as_posix()}'. It points to '{node_dir_path_attribute.as_posix()}'."
        )
