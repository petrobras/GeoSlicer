import humanize
import slicer
import vtk
import numpy as np
import pandas as pd
import shutil
import re
import tempfile
import xml.etree.ElementTree as ET

from humanize import naturalsize
from commons.slicer.tests.utils import (
    wait,
    save_project,
    save_current_project,
    load_project,
    close_project,
    process_events,
)
from commons.slicer_utils import LTracePluginTest
from commons.slicer.data_utils import tableNodeToDataFrame, dataFrameToTableNode
from pathlib import Path
from commons.slicer import helpers
from unittest.mock import patch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from commons.slicer.project_manager import ProjectManager

RESOURCES = Path(__file__).parent / "Resources"
MODULES_DIR = Path(__file__).parents[2]


def getProjectManagerInstance() -> "ProjectManager":
    from commons.slicer.project_manager import ProjectManager

    return ProjectManager()


class ProjectManagerTest(LTracePluginTest):
    """Test suite to assert slicer default widgets existence."""

    def post_setup(self) -> None:
        """Setup method for test case."""
        self.tempDirectory = Path(tempfile.TemporaryDirectory().name)
        self.tempDirectory.mkdir(parents=True, exist_ok=True)

    def tear_down(self) -> None:
        """Tear down method for test case."""
        shutil.rmtree(self.tempDirectory, onexc=helpers.make_directory_writable)

    def _modify_node_array(self, node, value=255):
        """Modify the node array to trigger its modified event

        Args:
            node (slicer.vtkMRMLNode): the node to be modified
        """
        arr = slicer.util.arrayFromVolume(node)
        unique = np.unique(arr)
        arr[arr == unique[-1]] = value
        slicer.util.updateVolumeFromArray(node, arr)
        node.SetOrigin(1, 1, 1)
        node.Modified()

    def _create_dummy_node(self, nodeType: slicer.vtkMRMLNode, name="TestNode") -> slicer.vtkMRMLNode:
        """Build a dummy node and add it to the scene, with a random 2D image array

        Args:
            nodeType (slicer.vtkMRMLNode): the type of node to be created

        Returns:
            slicer.vtkMRMLNode: The dummy node object.
        """
        nodeCls = nodeType if nodeType != slicer.vtkMRMLSegmentationNode else slicer.vtkMRMLLabelMapVolumeNode
        node = helpers.createTemporaryVolumeNode(
            nodeCls, name=name, environment="test", saveWithScene=True, hidden=False
        )
        if nodeType == slicer.vtkMRMLSegmentationNode:
            array = np.random.randint(0, 3, size=(3, 5000, 5000))
        else:
            array = np.random.randint(0, 255, size=(3, 5000, 5000))

        slicer.util.updateVolumeFromArray(node, array.astype(np.int32))
        node.SetOrigin(0, 0, 0)
        node.SetSpacing(1, 1, 1)

        if nodeType == slicer.vtkMRMLSegmentationNode:
            segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(node, segmentationNode)
            slicer.mrmlScene.RemoveNode(node)
            del node
            segmentationNode.SetName(name)
            node = segmentationNode

        node.Modified()
        return node

    def _save_project_process(self, projectFilePath: Path, useCompression: bool) -> None:
        """Wrapper for 'save as' project process.

        Args:
            projectFilePath (Path): the path of the project file.
            useCompression (bool): use compression method or not.
        """
        properties = {"useCompression": 1 if useCompression else 0}
        assert save_project(projectFilePath, properties=properties), "Failed to save the project"

    def _resave_project_process(self, useCompression):
        """Wrapper for 'save' project process.

        Args:
            useCompression (bool, optional): use compression method or not.
        """
        properties = {"useCompression": 1 if useCompression else 0}
        assert save_current_project(properties=properties), "Failed to resave the project"

    def _assert_file_size(self, path: Path, expectedSize: int, tolerancePercent=0.10):
        """Assert that the file size is close to the expected size

        Args:
            path (Path): the path of the file
            expectedSize (int): the expected size in bytes.
            tolerancePercent (float, optional): the tolerance percentage. Defaults to 0.10.
        """
        fileSize = path.stat().st_size

        assert fileSize >= (expectedSize * (1 - tolerancePercent)) and fileSize <= (
            expectedSize * (1 + tolerancePercent)
        ), (
            f"Expected file size to be close to {humanize.naturalsize(expectedSize)}, within a tolerance of {tolerancePercent * 100}%. Current size is {humanize.naturalsize(fileSize)}."
        )

    def test_save_project_with_scalar_volume_and_compression(self):
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        node = self._create_dummy_node(slicer.vtkMRMLScalarVolumeNode)
        self._save_project_process(projectFilePath, useCompression=True)
        nodeFilePath = projectFilePath.parent / "Data" / f"{node.GetID()}.nrrd"
        self._assert_file_size(nodeFilePath, 118429927)

    def test_save_project_with_scalar_volume_without_compression(self):
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        node = self._create_dummy_node(slicer.vtkMRMLScalarVolumeNode)
        self._save_project_process(projectFilePath, useCompression=False)
        nodeFilePath = projectFilePath.parent / "Data" / f"{node.GetID()}.nrrd"
        self._assert_file_size(nodeFilePath, 300000299)

    def test_resave_project_with_scalar_volume(self):
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        node = self._create_dummy_node(slicer.vtkMRMLScalarVolumeNode)

        # Save first time project with compression
        self._save_project_process(projectFilePath, useCompression=True)
        nodeFilePath = projectFilePath.parent / "Data" / f"{node.GetID()}.nrrd"
        self._assert_file_size(nodeFilePath, 118429927)

        # Update node reference
        node = slicer.util.getNode("TestNode")
        # Save project without compression, but node will not be resaved as it has not been modified
        self._resave_project_process(useCompression=False)
        self._assert_file_size(nodeFilePath, 118429927)

        # Update node reference
        node = slicer.util.getNode("TestNode")
        # Save project without compression, but now node will be saved again
        self._modify_node_array(node, value=250)
        self._resave_project_process(useCompression=False)
        self._assert_file_size(nodeFilePath, 300000299)

        # Update node reference
        node = slicer.util.getNode("TestNode")
        # Save project with compression
        self._modify_node_array(node)
        self._resave_project_process(useCompression=True)
        nodeFilePath = projectFilePath.parent / "Data" / f"{node.GetID()}.nrrd"
        self._assert_file_size(nodeFilePath, 118429927)

    def test_save_project_with_label_map_volume_and_compression(self):
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        node = self._create_dummy_node(slicer.vtkMRMLLabelMapVolumeNode)
        self._save_project_process(projectFilePath, useCompression=True)
        nodeFilePath = projectFilePath.parent / "Data" / f"{node.GetID()}.nrrd"
        self._assert_file_size(nodeFilePath, 118429927)

    def test_save_project_with_label_map_volume_without_compression(self):
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        node = self._create_dummy_node(slicer.vtkMRMLLabelMapVolumeNode)
        self._save_project_process(projectFilePath, useCompression=False)
        nodeFilePath = projectFilePath.parent / "Data" / f"{node.GetID()}.nrrd"
        self._assert_file_size(nodeFilePath, 300000299)

    def test_save_project_with_segmentation_node_and_compression(self):
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        node = self._create_dummy_node(slicer.vtkMRMLSegmentationNode)
        self._save_project_process(projectFilePath, useCompression=True)
        nodeFilePath = projectFilePath.parent / "Data" / f"{node.GetID()}.seg.nrrd"
        self._assert_file_size(nodeFilePath, 27360198)

    def test_save_project_with_segmentation_node_without_compression(self):
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        node = self._create_dummy_node(slicer.vtkMRMLSegmentationNode)
        self._save_project_process(projectFilePath, useCompression=False)
        nodeFilePath = projectFilePath.parent / "Data" / f"{node.GetID()}.seg.nrrd"
        self._assert_file_size(nodeFilePath, 300000299)

    def test_save_project_default_compression_mode_is_0(self):
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        node = self._create_dummy_node(slicer.vtkMRMLScalarVolumeNode)

        # Save first time project with compression
        save_project(projectFilePath)
        nodeFilePath = projectFilePath.parent / "Data" / f"{node.GetID()}.nrrd"
        self._assert_file_size(nodeFilePath, 300000299)

        # Update node reference
        node = slicer.util.getNode("TestNode")
        # Save project without compression, but now node will be saved again
        self._modify_node_array(node)
        self._resave_project_process(useCompression=False)
        nodeFilePath = projectFilePath.parent / "Data" / f"{node.GetID()}.nrrd"
        self._assert_file_size(nodeFilePath, 300000299)

    def test_save_project_with_tables(self):
        projectDirPath = RESOURCES / "save_table_test"

        with tempfile.TemporaryDirectory() as tempDir:
            tempDir = Path(tempDir)
            shutil.copytree(projectDirPath, tempDir / projectDirPath.name)
            projectDirPath = tempDir / projectDirPath.name
            projectFilePath = projectDirPath / f"{projectDirPath.name}.mrml"

            assert load_project(projectFilePath), f"Failed to load project '{projectFilePath}'"

            tableNames = ["Table. Test", "Table.Test [Hello]", "This is a table...", "duplicate name", "duplicate name"]
            for i, name in enumerate(tableNames):
                table = slicer.mrmlScene.GetNodeByID(f"vtkMRMLTableNode{i + 1}")
                self.assertEqual(table.GetName(), name)

            save_current_project()

            dataDir = projectDirPath / "Data"
            tableFileStems = [
                "Table. Test",
                "Table.Test [Hello]",
                "This is a table...",
                "duplicate name",
                "duplicate name_1",
            ]
            expectedFileNames = sorted(
                [f"{name}.tsv" for name in tableFileStems] + [f"{name}.schema.tsv" for name in tableFileStems]
            )
            fileNames = sorted([f.name for f in dataDir.iterdir()])

            self.assertEqual(fileNames, expectedFileNames)

    def test_general_memory_leak(self):
        projectPath = MODULES_DIR / "SegmentInspector" / "Test" / "Resources" / "QEMSCAN" / "QEMSCAN.mrml"

        memory_before = helpers.get_memory_usage()
        for _ in range(10):
            assert load_project(projectPath), f"Failed to load project '{projectPath}'"
            process_events()
            close_project()
            process_events()
        memory_after = helpers.get_memory_usage()

        diff_memory_use = memory_after - memory_before
        MEM_DIFF_TOL = 400 * 1024 * 1024  # 400 MB
        assert diff_memory_use <= MEM_DIFF_TOL, (
            f"Memory leak detected! Memory usage:\n  Before: ({naturalsize(memory_before)})\n  After: ({naturalsize(memory_after)})\n  Diff: ({naturalsize(diff_memory_use)})"
        )

    def test_check_default_node_observers_for_clean_project(self):
        pm = getProjectManagerInstance()

        # Close project to trigger default scenes nodes after ProjectManager initialization.
        # Even though ProjectManager is a singleton, it is initialized after thefirst scene
        for _ in range(3):
            close_project()
            wait(0.5)
            observers = pm._ProjectManager__nodeObservers

            assert len(observers) == 0, f"Expected 0 observers, got {len(observers)}"
            wait(0.5)

    def test_creating_node_observer_for_new_nodes(self):
        pm = getProjectManagerInstance()

        close_project()  # Close project to trigger default scenes nodes

        observers_list = pm._ProjectManager__nodeObservers

        def assert_observer_list_length(expected_length: int) -> None:
            nodes = [obs.node for obs in observers_list]
            names = [node.GetName() for node in nodes]
            assert len(observers_list) == expected_length, (
                f"Expected {expected_length} observers, got {len(observers_list)}. Current observed nodes: {names}"
            )

        assert_observer_list_length(0)

        slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__, "TableNode")
        process_events()
        assert_observer_list_length(1)

        slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLSegmentationNode.__name__, "SegmentationNode")
        process_events()
        assert_observer_list_length(2)

        slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLScalarVolumeNode.__name__, "VolumeNode")
        process_events()
        assert_observer_list_length(3)

        slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLLabelMapVolumeNode.__name__, "LabelMapNode")
        process_events()
        assert_observer_list_length(4)

        slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLMarkupsROINode.__name__, "MarkupsROINode")
        process_events()
        assert_observer_list_length(6)  # vtkMRMLMarkupsROINode creates a vtkMRMLMarkupsROINodeDisplayNode by default

        slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLVectorVolumeNode.__name__, "VectorVolumeNode")
        process_events()
        assert_observer_list_length(7)

        slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTextNode.__name__, "TextNode")
        process_events()
        assert_observer_list_length(8)

        ignored_classes = [
            slicer.vtkMRMLModelNode,
            slicer.vtkMRMLColorTableNode,
            slicer.vtkMRMLTransformNode,
            slicer.vtkMRMLSliceDisplayNode,
        ]
        # vtkMRMLSubjectHierarchyNode cannot be created by this way

        for cls in ignored_classes:
            slicer.mrmlScene.AddNewNodeByClass(cls.__name__)
            process_events()
            assert_observer_list_length(8)

        close_project()
        assert_observer_list_length(0)

    def test_estimate_new_nodes_sizes(self):
        from commons.slicer.project_manager import ProjectManager

        pm = ProjectManager()
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"

        scalarNode = self._create_dummy_node(slicer.vtkMRMLScalarVolumeNode, "scalar")
        labelmapNode = self._create_dummy_node(slicer.vtkMRMLLabelMapVolumeNode, "labelmap")
        segmentationNode = self._create_dummy_node(slicer.vtkMRMLSegmentationNode, "segmentation")

        tableArray = np.random.rand(5000, 500)
        tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "table")
        slicer.util.updateTableFromArray(tableNode, tableArray)

        self._save_project_process(projectFilePath, useCompression=False)

        nodesToTest = [
            (f"{scalarNode.GetID()}.nrrd", scalarNode),
            (f"{labelmapNode.GetID()}.nrrd", labelmapNode),
            (f"{segmentationNode.GetID()}.seg.nrrd", segmentationNode),
            (f"{tableNode.GetID()}.tsv", tableNode),
        ]
        wait(0.4)

        for file, node in nodesToTest:
            nodeFilePath = projectFilePath.parent / "Data" / file
            estimateSize = pm.estimateNodeSize(node)
            self._assert_file_size(nodeFilePath, estimateSize)

    def test_estimate_storable_nodes_sizes(self):
        from commons.slicer.project_manager import ProjectManager

        pm = ProjectManager()
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"

        scalarNode = self._create_dummy_node(slicer.vtkMRMLScalarVolumeNode, "scalar")
        labelmapNode = self._create_dummy_node(slicer.vtkMRMLLabelMapVolumeNode, "labelmap")
        segmentationNode = self._create_dummy_node(slicer.vtkMRMLSegmentationNode, "segmentation")

        self._save_project_process(projectFilePath, useCompression=False)

        nodesToTest = [
            (f"{scalarNode.GetID()}.nrrd", scalarNode),
            (f"{labelmapNode.GetID()}.nrrd", labelmapNode),
            (f"{segmentationNode.GetID()}.seg.nrrd", segmentationNode),
        ]

        for file, node in nodesToTest:
            updatedNode = helpers.tryGetNode(node.GetName())
            nodeFilePath = projectFilePath.parent / "Data" / file
            assert updatedNode.GetStorageNode() is not None, f"Expected {updatedNode.GetName()} to have a storable node"
            estimate = pm.getNodeSize(updatedNode, projectFilePath)
            self._assert_file_size(nodeFilePath, estimate)

    def test_estimate_fail_available_storage(self):
        from commons.slicer.project_manager import ProjectManager

        pm = ProjectManager()

        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        save_project(projectFilePath, timeout_ms=30000)

        self._create_dummy_node(slicer.vtkMRMLScalarVolumeNode, "scalar")

        with patch.object(pm, "getWritableStorageInfo") as mockHDSize:
            mockHDSize.return_value = 50 * 1024

            assert not save_current_project(), "Expected save project to fail"

        assert not (projectFilePath.parent / "Data" / "scalar.nrrd").is_file(), "Expected file to not exist"

    def test_load_project(self) -> None:
        pm = getProjectManagerInstance()
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        self._save_project_process(projectFilePath, useCompression=False)

        process_events()
        close_project()

        assert pm.load(projectFilePath)[0], f"Failed to load project '{projectFilePath}'"

    def test_load_project_twice(self) -> None:
        pm = getProjectManagerInstance()
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        self._save_project_process(projectFilePath, useCompression=False)

        process_events()
        close_project()

        assert pm.load(projectFilePath)[0], f"Failed to load project '{projectFilePath}'"

        process_events()

        assert pm.load(projectFilePath)[0], f"Failed to load project '{projectFilePath}' a second time"

    def test_load_project_inexistent_file(self) -> None:
        pm = getProjectManagerInstance()
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"

        assert not pm.load(projectFilePath)[0], f"Unexpected success to load inexistent project '{projectFilePath}'"
        assert (
            pm.load(projectFilePath)[1]
            == f"Cannot load project from '{projectFilePath.as_posix()}'. File does not exist."
        )

    def test_save_project_with_cloned_node(self) -> None:
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        scalarNode = self._create_dummy_node(slicer.vtkMRMLScalarVolumeNode, "scalar")

        def cloneNode(node) -> slicer.vtkMRMLNode:
            subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            itemIDToClone = subjectHierarchyNode.GetItemByDataNode(node)
            clonedItemID = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(
                subjectHierarchyNode, itemIDToClone
            )
            clonedNode = subjectHierarchyNode.GetItemDataNode(clonedItemID)
            process_events()

            return clonedNode

        clonedScalarNode = cloneNode(scalarNode)
        assert clonedScalarNode.GetName() == f"{scalarNode.GetName()} Copy"

        self._save_project_process(projectFilePath, useCompression=False)

        assert (projectFilePath.parent / "Data" / f"{scalarNode.GetID()}.nrrd").exists()
        assert (projectFilePath.parent / "Data" / f"{clonedScalarNode.GetID()}.nrrd").exists()

        # Saving project again, but in a new directory
        oldScalarNodeID = scalarNode.GetID()
        oldClonedScalarNodeID = clonedScalarNode.GetID()
        scalarNode.SetName("scalar2")
        clonedScalarNode.SetName("clonedScalar2")

        newProjectFilePath = self.tempDirectory / "dummy_project_2" / "dummy_project_2.mrml"
        self._save_project_process(newProjectFilePath, useCompression=False)

        assert (newProjectFilePath.parent / "Data" / f"{scalarNode.GetID()}.nrrd").exists()
        assert (newProjectFilePath.parent / "Data" / f"{clonedScalarNode.GetID()}.nrrd").exists()

        # Check previous project file still exists with the old names
        assert (projectFilePath.parent / "Data" / f"{oldScalarNodeID}.nrrd").exists()
        assert (projectFilePath.parent / "Data" / f"{oldClonedScalarNodeID}.nrrd").exists()

    def test_save_project_table_nodes_with_the_same_name(self) -> None:
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        node1 = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__)
        node2 = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__)

        node1.SetName("TableNode")
        node2.SetName("TableNode")

        self._save_project_process(projectFilePath, useCompression=False)

        assert (projectFilePath.parent / "Data" / f"{node1.GetID()}.tsv").exists()
        assert (projectFilePath.parent / "Data" / f"{node2.GetID()}.tsv").exists()

        assert node1.GetStorageNode().GetFileName() != node2.GetStorageNode().GetFileName()
        assert (
            Path(node1.GetStorageNode().GetFileName()).resolve()
            == (projectFilePath.parent / "Data" / f"{node1.GetID()}.tsv").resolve()
        )
        assert (
            Path(node2.GetStorageNode().GetFileName()).resolve()
            == (projectFilePath.parent / "Data" / f"{node2.GetID()}.tsv").resolve()
        )

    def test_save_project_scalar_nodes_with_the_same_name(self) -> None:
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        node1 = self._create_dummy_node(slicer.vtkMRMLScalarVolumeNode)
        node2 = self._create_dummy_node(slicer.vtkMRMLScalarVolumeNode)

        node1.SetName("ScalarNode")
        node2.SetName("ScalarNode")

        self._save_project_process(projectFilePath, useCompression=False)

        assert (projectFilePath.parent / "Data" / f"{node1.GetID()}.nrrd").exists()
        assert (projectFilePath.parent / "Data" / f"{node2.GetID()}.nrrd").exists()

        assert node1.GetStorageNode().GetFileName() != node2.GetStorageNode().GetFileName()
        assert (
            Path(node1.GetStorageNode().GetFileName()).resolve()
            == (projectFilePath.parent / "Data" / f"{node1.GetID()}.nrrd").resolve()
        )
        assert (
            Path(node2.GetStorageNode().GetFileName()).resolve()
            == (projectFilePath.parent / "Data" / f"{node2.GetID()}.nrrd").resolve()
        )

    def test_save_project_volume_is_updated(self) -> None:
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        # Save empty project
        self._save_project_process(projectFilePath, useCompression=False)

        close_project()
        load_project(projectFilePath)

        node = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLLabelMapVolumeNode, name="TestNode", environment="test", saveWithScene=True, hidden=False
        )

        array = np.random.randint(0, 255, size=(3, 1000, 1000))
        slicer.util.updateVolumeFromArray(node, array.astype(np.int32))
        node.Modified()

        self._resave_project_process(useCompression=False)

        close_project()
        load_project(projectFilePath)

        node = helpers.tryGetNode("TestNode")
        assert node is not None, "Node not found."

        np.testing.assert_array_almost_equal(array, slicer.util.arrayFromVolume(node))

        # Modify array and save again
        array = np.zeros((3, 1000, 1000))
        slicer.util.updateVolumeFromArray(node, array.astype(np.int32))
        node.Modified()

        self._resave_project_process(useCompression=False)

        close_project()
        load_project(projectFilePath)

        node = helpers.tryGetNode("TestNode")
        assert node is not None, "Node not found."

        np.testing.assert_array_almost_equal(array, slicer.util.arrayFromVolume(node))
        assert (projectFilePath.parent / "Data" / f"{node.GetID()}.nrrd").exists(), (
            f"File not found: {projectFilePath.parent / 'Data' / f'{node.GetID()}.nrrd'}"
        )

    def test_save_project_table_is_updated(self) -> None:
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"

        # Save empty project
        self._save_project_process(projectFilePath, useCompression=False)

        close_project()
        load_project(projectFilePath)

        node = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLTableNode, name="TestNode", environment="test", saveWithScene=True, hidden=False
        )

        df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6], "C": [7, 8, 9]})
        dataFrameToTableNode(df, node)

        self._resave_project_process(useCompression=False)

        close_project()
        load_project(projectFilePath)

        node = helpers.tryGetNode("TestNode")
        assert node is not None, "Node not found."

        pd.testing.assert_frame_equal(df, tableNodeToDataFrame(node))

        # Modify table and save again
        df = pd.DataFrame({"A": [0, 0, 0, 0], "B": [0, 0, 0, 0], "C": [0, 0, 0, 0]})
        dataFrameToTableNode(df, node)

        self._resave_project_process(useCompression=False)

        close_project()
        load_project(projectFilePath)

        node = helpers.tryGetNode("TestNode")
        assert node is not None, "Node not found."

        pd.testing.assert_frame_equal(df, tableNodeToDataFrame(node))
        assert (projectFilePath.parent / "Data" / f"{node.GetID()}.tsv").exists(), (
            f"File not found: {projectFilePath.parent / 'Data' / f'{node.GetID()}.tsv'}"
        )
        assert (projectFilePath.parent / "Data" / f"{node.GetID()}.schema.tsv").exists(), (
            f"File not found: {projectFilePath.parent / 'Data' / f'{node.GetID()}.schema.tsv'}"
        )

    def test_project_mrml_store_data_filenames_as_relative_path(self):
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"

        # Create table node
        node = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLTableNode, name="TableNode", environment="test", saveWithScene=True, hidden=False
        )

        df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6], "C": [7, 8, 9]})
        dataFrameToTableNode(df, node)

        # Create scalar volume node
        node = self._create_dummy_node(slicer.vtkMRMLScalarVolumeNode)

        # Save empty project
        self._save_project_process(projectFilePath, useCompression=False)

        close_project()

        # Regular expression for matching "fileListMemberX" attribute, where X is a number
        fileListMemberPattern = re.compile(r"fileListMember\d+")

        # Function to retrieve relevant attributes
        def retrieveFileAttributes(element):
            results = {}
            for attrib, value in element.attrib.items():
                if attrib == "fileName" or fileListMemberPattern.match(attrib):
                    results[attrib] = value
            return results

        mrmlFileData = projectFilePath.read_text()
        root = ET.fromstring(mrmlFileData)

        # Iterate through each element and retrieve relevant attributes
        for elem in root.iter():
            fileAttributes = retrieveFileAttributes(elem)
            if not fileAttributes:
                continue

            for attrib, path in fileAttributes.items():
                assert path.startswith("Data"), (
                    f"Path {path} from '{elem}' {attrib} isn't relative from the Data folder"
                )

    def test_subject_hierarchy_widget_sort_filter_not_looping_forever(self):
        """Reproduce the application's crash behavior from PL-2417:
        Load a project with empty items in the subject hierarchy (without a related node), that would cause a recursion loop in the subject hierarchy widgets
        when the widget's attribute 'showEmptyHierarchyItems' is False.
        This test case should crash the application when running it with an outdated GeoSlicer version without the fix from PL-2418.
        """
        node = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLSegmentationNode.__name__, "Segmentation")
        node.CreateDefaultDisplayNodes()
        node.SaveWithSceneOff()
        node.GetSegmentation().AddEmptySegment("segment_1", "segment_1")

        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"
        save_project(projectFilePath)

        close_project()

        # Create widget to ensure sort filter execution, matching the bug's conditions.
        inputSelector = slicer.qMRMLSubjectHierarchyComboBox()
        inputSelector.showEmptyHierarchyItems = False
        inputSelector.setMRMLScene(slicer.mrmlScene)

        load_project(projectFilePath)

        assert helpers.tryGetNode("Segmentation") is None

    def test_not_deleting_file_if_still_used_by_new_node(self):
        """Test a case where we create a table node that store a schema.tsv file as well, and force a behavior of generating a new table node with the same ID. This test should check if the new scheme.tsv file its not deleted by being marked as a non-used old file."""
        projectFilePath = self.tempDirectory / "project1" / "project1.mrml"

        # Create first table node
        tableNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__)
        table = tableNode.GetTable()
        columnArray = vtk.vtkDoubleArray()
        columnArray.SetName("Column 1")
        columnArray.InsertNextValue(2)
        table.AddColumn(columnArray)
        table.Modified()
        tableNodeId = tableNode.GetID()

        tableNode = None

        # Save project and reopen it
        save_project(projectFilePath)
        close_project()
        load_project(projectFilePath)

        # Retrieve previous table node, remove it and create a new one
        tableNode = slicer.util.getNode(tableNodeId)
        slicer.mrmlScene.RemoveNode(tableNode)
        tableNode = None
        wait(0.5)
        tableNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__)
        table = tableNode.GetTable()
        assert tableNode.GetID() == tableNodeId

        columnArray = vtk.vtkDoubleArray()
        columnArray.SetName("Column 3")
        columnArray.InsertNextValue(4)
        table.AddColumn(columnArray)
        table.Modified()
        tableNode = None

        # Save project and reopen it
        save_current_project()
        close_project()
        load_project(projectFilePath)

        # Assert loaded table node is valid
        tableNode = slicer.util.getNode(tableNodeId)
        assert tableNode.GetID() == tableNodeId
        assert tableNode.GetColumnType("Column 3") == vtk.VTK_DOUBLE
        assert (projectFilePath.parent / "Data" / f"{tableNodeId}.tsv").exists()
        assert (projectFilePath.parent / "Data" / f"{tableNodeId}.schema.tsv").exists()

    def test_save_and_load_long_text_node(self):
        projectFilePath = self.tempDirectory / "dummy_project" / "dummy_project.mrml"

        # Create a text node with a thousand characters.
        text_node = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTextNode.__name__, "LongTextNode")
        long_text = "a" * 1000
        text_node.SetText(long_text)

        # Save the project.
        self._save_project_process(projectFilePath, useCompression=False)

        # Load the project.
        close_project()
        assert load_project(projectFilePath), f"Failed to load project '{projectFilePath}'"

        # Assert that the text content is preserved.
        loaded_text_node = slicer.util.getNode("LongTextNode")
        self.assertIsNotNone(loaded_text_node)
        self.assertEqual(loaded_text_node.GetText(), long_text)

    def test_slice_edges_3d_visibility_disabled_after_closing_the_scene(self):
        # Set all slices edge 3D as visible
        for sliceName in ["Red", "Yellow", "Green"]:
            sliceWidget = slicer.app.layoutManager().sliceWidget(sliceName)
            slicerController = sliceWidget.sliceController()
            slicerController.setSliceEdgeVisibility3D(True)

        # Load any project
        PROJECT_URL = RESOURCES / "SCREENSHOT" / "SCREENSHOT.mrml"
        load_project(PROJECT_URL)
        close_project()

        # Assert
        for sliceName in ["Red", "Yellow", "Green"]:
            sliceWidget = slicer.app.layoutManager().sliceWidget(sliceName)
            sliceController = sliceWidget.sliceController()
            assert sliceController.sliceLogic().GetSliceNode().GetSliceEdgeVisibility3D() is False, (
                f"Expected '{sliceName}' slice view to have its slice edge 3D visibility disabled"
            )

    def test_slice_edges_3d_visibility_disabled_after_loading_project(self):
        # Set all slices edge 3D as visible
        for sliceName in ["Red", "Yellow", "Green"]:
            sliceWidget = slicer.app.layoutManager().sliceWidget(sliceName)
            slicerController = sliceWidget.sliceController()
            slicerController.setSliceEdgeVisibility3D(True)

        # Load any project
        PROJECT_URL = RESOURCES / "SCREENSHOT" / "SCREENSHOT.mrml"
        load_project(PROJECT_URL)

        # Assert
        for sliceName in ["Red", "Yellow", "Green"]:
            sliceWidget = slicer.app.layoutManager().sliceWidget(sliceName)
            sliceController = sliceWidget.sliceController()
            assert sliceController.sliceLogic().GetSliceNode().GetSliceEdgeVisibility3D() is False, (
                f"Expected '{sliceName}' slice view to have its slice edge 3D visibility disabled"
            )

    def test_save_records_environment_for_recent_badge(self):
        """A freshly saved project must be stamped with the current environment
        so the onboarding RECENT list shows the correct badge immediately,
        without needing the project to be reopened first (see PL-3147)."""
        from commons.slicer.app import onboard, onboard_view

        projectFilePath = self.tempDirectory / "env_badge_project" / "env_badge_project.mrml"
        slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__, "EnvBadgeTable")

        settingsKey = onboard_view.PATH_ENV_SETTINGS_KEY
        originalSetting = slicer.app.userSettings().value(settingsKey, "")
        originalLastEnv = onboard.getLastEnvironment()
        try:
            # Isolate the recents→env map and pretend the user is in Volumes.
            slicer.app.userSettings().setValue(settingsKey, "")
            onboard._lastEnvironment = onboard.LOADERS["Volumes"]

            assert save_project(projectFilePath), "Failed to save the project"
            process_events()

            # Recorded at save time — no reopen required.
            assert onboard_view.getEnvironmentForPath(projectFilePath.as_posix()) == "Volumes"
        finally:
            onboard._lastEnvironment = originalLastEnv
            slicer.app.userSettings().setValue(settingsKey, originalSetting)
