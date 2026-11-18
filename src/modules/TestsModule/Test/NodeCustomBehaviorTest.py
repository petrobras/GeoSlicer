from commons.slicer_utils import LTracePluginTest
from commons.slicer.node_custom_behavior.defs import TriggerEvent
from commons.slicer.node_custom_behavior.nodes.vector_volume_node_from_image import LosslessAttribute
from commons.slicer.node_custom_behavior.node_custom_behavior_manager import NodeCustomBehaviorFactory
from commons.slicer.node_custom_behavior.nodes.vector_volume_node_from_image import (
    VectorVolumeNodeFromImageCustomBehavior,
)
from commons.slicer.node_custom_behavior.nodes.directory_node_behavior import DirectoryNodeCustomBehavior
from commons.slicer.node_custom_behavior.nodes.volume_node import VolumeNodeCustomBehavior
from commons.slicer.node_custom_behavior.nodes.segmentation_display_node import SegmentationDisplayNodeCustomBehavior
from commons.slicer.node_custom_behavior.nodes.volume_rendering_display_node import (
    VolumeRenderingDisplayNodeCustomBehavior,
)
from commons.slicer.node_custom_behavior.nodes.table_node import TableNodeCustomBehavior
from commons.slicer.nodes.directory_node import DirectoryNode
from pathlib import Path
from commons.slicer.tests.utils import (
    process_events,
    wait,
    load_project,
    save_project,
    close_project,
    save_current_project,
)
from commons.slicer.helpers import tryGetNode, make_directory_writable

import math
import slicer
import shutil
import tempfile
import vtk

RESOURCES_DIR = Path(__file__).parent / "Resources"


class NodeCustomBehaviorTest(LTracePluginTest):
    def post_setup(self) -> None:
        # Create the temporary directory used to store the test files
        self.__temp_project_dir_path = Path(tempfile.mkdtemp()).resolve()

    def tear_down(self) -> None:
        # Delete the temporary directory
        shutil.rmtree(self.__temp_project_dir_path, onexc=make_directory_writable)

    def test_lossy_image_node_loading_from_image_file(self):
        image_file_path = RESOURCES_DIR / "example.jpg"
        node = slicer.util.loadVolume(image_file_path.as_posix())
        assert node is not None
        assert isinstance(node, slicer.vtkMRMLVectorVolumeNode)

        # Set attributes
        node.SetAttribute(LosslessAttribute.name(), LosslessAttribute.FALSE.value)

        # Create temporary directory to save the project
        temp_project_file = self.__temp_project_dir_path / "test" / "test.mrml"

        assert save_project(temp_project_file), "Failed to save temporary project."

        process_events()
        # Update node reference after save
        node = tryGetNode(node.GetID())

        # Assert node attributes
        storage_node = node.GetStorageNode()
        node_project_file_path = Path(storage_node.GetFileName())
        node_project_file_size = node_project_file_path.stat().st_size
        expected_image_project_file_path = temp_project_file.parent / "Data" / image_file_path.name
        expected_image_project_file_size = expected_image_project_file_path.stat().st_size
        lossless_attribute = node.GetAttribute("Lossless")
        source_image_attribute = node.GetAttribute("SourceImage")

        assert node_project_file_path.suffix == ".nrrd"
        assert storage_node.GetNumberOfFileNames() == 1, (
            f"Expected 1 file name. Actual number of file names is {storage_node.GetNumberOfFileNames()}"
        )
        assert lossless_attribute == LosslessAttribute.FALSE.value, (
            f"'Lossless' attribute is set as '{lossless_attribute}'. Expected False"
        )
        assert expected_image_project_file_path.samefile(Path(source_image_attribute)), (
            f"'SourceImage' attribute is set as '{source_image_attribute}'. Expected to be related to {expected_image_project_file_path.as_posix()}"
        )
        assert node_project_file_size <= 10000, (
            f"Expected the node .nrrd file to be 10kB at most. Actual size is {node_project_file_size} bytes"
        )
        assert expected_image_project_file_size <= (image_file_path.stat().st_size) * 2.5, (
            f"Expected the project image file size to be 2 times greater than the original image file size at most. Actual size is {expected_image_project_file_size} bytes"
        )

    def test_lossy_image_node_loading_from_cloned_volume_node(self):
        image_file_path = RESOURCES_DIR / "example.jpg"
        node = slicer.util.loadVolume(image_file_path.as_posix())
        assert node is not None
        assert isinstance(node, slicer.vtkMRMLVectorVolumeNode)

        # Set attributes
        node.SetAttribute(LosslessAttribute.name(), LosslessAttribute.FALSE.value)

        # Create new node based on the old node array
        clonned_node = slicer.mrmlScene.AddNewNodeByClass(node.GetClassName(), f"{node.GetName()} Clone")
        assert clonned_node.GetStorageNode() is None
        clonned_node.CopyOrientation(node)

        for attribute_name in node.GetAttributeNames():
            clonned_node.SetAttribute(attribute_name, node.GetAttribute(attribute_name))

        array = slicer.util.arrayFromVolume(node)
        slicer.util.updateVolumeFromArray(clonned_node, array)

        # Create temporary directory to save the project
        temp_project_file = self.__temp_project_dir_path / "test" / "test.mrml"

        assert save_project(temp_project_file), "Failed to save temporary project."

        process_events()
        # Update node reference after save
        node = tryGetNode(node.GetID())
        clonned_node = tryGetNode(clonned_node.GetID())

        # Assert node attributes
        def assert_lossy_node(node):
            storage_node = node.GetStorageNode()
            node_project_file_path = Path(storage_node.GetFileName())
            node_project_file_size = node_project_file_path.stat().st_size
            expected_image_project_file_path = (
                temp_project_file.parent / "Data" / f"{node.GetName()}{image_file_path.suffix}"
            )
            expected_image_project_file_size = expected_image_project_file_path.stat().st_size
            lossless_attribute = node.GetAttribute("Lossless")
            source_image_attribute = node.GetAttribute("SourceImage")

            assert node_project_file_path.suffix == ".nrrd"
            assert storage_node.GetNumberOfFileNames() == 1, (
                f"Expected 1 file name. Actual number of file names is {storage_node.GetNumberOfFileNames()}."
            )
            assert lossless_attribute == LosslessAttribute.FALSE.value, (
                f"'Lossless' attribute is set as '{lossless_attribute}'. Expected False"
            )
            assert expected_image_project_file_path.samefile(Path(source_image_attribute)), (
                f"'SourceImage' attribute is set as '{source_image_attribute}'. Expected to be related to {expected_image_project_file_path.as_posix()}"
            )
            assert node_project_file_size <= 10000, (
                f"Expected the node .nrrd file to be 10kB at most. Actual size is {node_project_file_size} bytes"
            )
            assert expected_image_project_file_size <= (image_file_path.stat().st_size) * 2.5, (
                f"Expected the project image file size to be 2 times greater than the original image file size at most. Actual size is {expected_image_project_file_size} bytes"
            )

        assert_lossy_node(node=node)
        assert_lossy_node(node=clonned_node)

        source_image_attribute = node.GetAttribute("SourceImage")
        clonned_source_image_attribute = clonned_node.GetAttribute("SourceImage")
        assert source_image_attribute != clonned_source_image_attribute

    def test_lossy_image_node_loading_visibility(self):
        """Test 2 behaviors:
        1) saving lossy image node being shown in the slice viewers, and keep showing after loading
        2) saving lossy image node not being shown in the slice viewers, and doesn't show after loading
        """
        image_file_path = RESOURCES_DIR / "example.jpg"
        node = slicer.util.loadVolume(image_file_path.as_posix())
        assert node is not None
        assert isinstance(node, slicer.vtkMRMLVectorVolumeNode)

        # Set attributes
        node.SetAttribute(LosslessAttribute.name(), LosslessAttribute.FALSE.value)

        # Behavior 1: saving lossy image node being shown in the slice viewers, and keep showing after loading

        # Create temporary directory to save the project
        temp_project_file = self.__temp_project_dir_path / "project1" / "project1.mrml"

        # Set node as visible in slice viewers(eye icon opened)
        slicer.util.setSliceViewerLayers(background=node)
        # Assert node is visible
        assert self.__is_node_visible_in_slicer_viewers(node)

        assert save_project(temp_project_file), "Failed to save temporary project."

        process_events()
        # Update node reference after save
        node = tryGetNode(node.GetID())

        # Assert node attributes
        assert self.__is_node_visible_in_slicer_viewers(node)

        # Behavior 2: saving lossy image node not being shown in the slice viewers, and doesn't show after loading
        temp_project_file = self.__temp_project_dir_path / "project2" / "project2.mrml"

        # Set node as visible in slice viewers(eye icon opened)
        slicer.util.setSliceViewerLayers(background=None)
        # Assert node is not visible
        assert not self.__is_node_visible_in_slicer_viewers(node)

        assert save_project(temp_project_file), "Failed to save temporary project."

        process_events()
        # Update node reference after save
        node = tryGetNode(node.GetID())

        # Assert node attributes
        assert not self.__is_node_visible_in_slicer_viewers(node)

    def test_crop_lossy_image_node_from_old_project_not_overwritting_previous_image_file_reference(self):
        """Test case for previous bug behavior where the user saves a new project based on an old project with lossy image and the old project lossy node files were modified."""
        # Create lossy image node
        image_file_path = RESOURCES_DIR / "example.jpg"
        node = slicer.util.loadVolume(image_file_path.as_posix())
        assert node is not None
        assert isinstance(node, slicer.vtkMRMLVectorVolumeNode)

        # Set lossy attribute
        node.SetAttribute(LosslessAttribute.name(), LosslessAttribute.FALSE.value)

        # Save the first project
        temp_project_file = self.__temp_project_dir_path / "project1" / "project1.mrml"
        assert save_project(temp_project_file), "Failed to save temporary project."

        # Update node reference after save
        node = tryGetNode(node.GetID())
        assert node is not None

        # Assert node attributes
        project_1_source_image_attribute = node.GetAttribute("SourceImage")
        project_1_image_file_first_modified_time = Path(project_1_source_image_attribute).stat().st_mtime

        # Use crop feature to create a cloned volume based on the reference node
        ijk_size = [1696, 1419, 1]
        crop_module = slicer.modules.customizedcropvolume.createNewWidgetRepresentation()
        crop_module.self().enter()  # Apply a few logics from entering the module's window
        crop_logic = crop_module.self().logic
        crop_logic.initializeVolume(node)
        crop_logic.setRoiSizeIjk(node, ijk_size)
        crop_logic.crop(node, ijk_size)
        crop_module.deleteLater()

        cropped_node = slicer.util.getNode(f"{node.GetName()} - Cropped")
        assert cropped_node is not None

        cropped_node_source_image_attribute = cropped_node.GetAttribute("SourceImage")
        assert project_1_source_image_attribute == cropped_node_source_image_attribute

        # Wait a few seconds before saving the second project
        wait(1)

        # Save a second project
        temp_project_file = self.__temp_project_dir_path / "project2" / "project2.mrml"
        assert save_project(temp_project_file), "Failed to save temporary project."

        # Update node reference after save
        node = tryGetNode(node.GetID())
        cropped_node = tryGetNode(cropped_node.GetID())

        project_2_source_image_attribute = node.GetAttribute("SourceImage")
        project_2_cropped_source_image_attribute = cropped_node.GetAttribute("SourceImage")

        # Files modified time variables
        project_1_image_file_second_modified_time = Path(project_1_source_image_attribute).stat().st_mtime
        project_2_image_file_modified_time = Path(project_2_source_image_attribute).stat().st_mtime
        project_2_cropped_image_file_modified_time = Path(project_2_cropped_source_image_attribute).stat().st_mtime

        # File size variables
        project_1_source_image_file_size = Path(project_1_source_image_attribute).stat().st_size
        project_2_source_image_file_size = Path(project_2_source_image_attribute).stat().st_size
        project_2_cropped_source_image_file_size = Path(project_2_cropped_source_image_attribute).stat().st_size

        # Check source image attribute
        assert project_1_source_image_attribute != project_2_source_image_attribute
        assert project_1_source_image_attribute != project_2_cropped_source_image_attribute
        assert project_2_source_image_attribute != project_2_cropped_source_image_attribute

        # Check modified time from source image files
        assert project_1_image_file_first_modified_time == project_1_image_file_second_modified_time
        assert project_1_image_file_second_modified_time != project_2_image_file_modified_time
        assert project_1_image_file_second_modified_time != project_2_cropped_image_file_modified_time

        # Check file size between source image files (Expected cropped file to be lighter)
        assert math.isclose(
            project_1_source_image_file_size, project_2_source_image_file_size, abs_tol=5000
        )  # 5kb tolerance
        assert project_1_source_image_file_size > project_2_cropped_source_image_file_size
        assert project_2_source_image_file_size > project_2_cropped_source_image_file_size

    def test_lossy_image_loading_when_user_changes_project_dir_offline(self):
        """Test case for test loading lossy image node project file even if the entire project directory was moved in the file system"""
        # Create lossy image node
        image_file_path = RESOURCES_DIR / "example.jpg"
        node = slicer.util.loadVolume(image_file_path.as_posix())
        assert node is not None
        assert isinstance(node, slicer.vtkMRMLVectorVolumeNode)

        # Set lossy attribute
        node.SetAttribute(LosslessAttribute.name(), LosslessAttribute.FALSE.value)

        # Save the first project
        temp_project_file = self.__temp_project_dir_path / "project1" / "project1.mrml"

        assert save_project(temp_project_file), "Failed to save temporary project."

        # Close project in GeoSlicer
        close_project()

        # Move project directory
        new_project_file = self.__temp_project_dir_path / "newProject Name" / "project1.mrml"
        temp_project_file.parent.rename(new_project_file.parent)

        # Load project from renamed directory
        load_project(new_project_file)

        # Update node reference
        node = tryGetNode(node.GetID())
        assert node is not None

        # Assert node attributes
        source_image_attribute = node.GetAttribute("SourceImage")
        source_image_path = Path(source_image_attribute)
        lossless_attribute = node.GetAttribute(LosslessAttribute.name())

        assert source_image_attribute
        assert source_image_path.exists()
        assert source_image_path.is_relative_to(
            new_project_file.parent
        )  # check if source image is within the new project directory
        assert lossless_attribute == LosslessAttribute.FALSE.value

    def __is_node_visible_in_slicer_viewers(self, node: slicer.vtkMRMLNode) -> bool:
        num = slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSliceCompositeNode")
        if num <= 0:
            return False

        for i in range(num):
            sliceViewer = slicer.mrmlScene.GetNthNodeByClass(i, "vtkMRMLSliceCompositeNode")
            if sliceViewer.GetBackgroundVolumeID() != node.GetID():
                return False

        return True

    def test_table_node_custom_behavior(self):
        projectFilePath = self.__temp_project_dir_path / "project1" / "project1.mrml"
        tableNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__)
        table = tableNode.GetTable()
        columnArray = vtk.vtkStringArray()
        columnArray.SetName("Column 1")
        columnArray.InsertNextValue("2")
        table.AddColumn(columnArray)
        table.Modified()

        save_project(projectFilePath)
        wait(0.5)

        tableNode = slicer.util.getNode(tableNode.GetID())
        tableNode.SetColumnType("Column 1", vtk.VTK_DOUBLE)

        save_current_project()
        wait(0.5)

        close_project()

        load_project(projectFilePath)
        tableNode = slicer.util.getNode(tableNode.GetID())
        assert tableNode.GetColumnType("Column 1") == vtk.VTK_DOUBLE
        assert (projectFilePath.parent / "Data" / f"{tableNode.GetID()}.tsv").exists()
        assert (projectFilePath.parent / "Data" / f"{tableNode.GetID()}.schema.tsv").exists()

    def test_save_project_with_pore_network_tables(self):
        projectFilePath = self.__temp_project_dir_path / "pnm_project" / "pnm_project.mrml"
        dataDir = projectFilePath.parent / "Data"

        # Create Pore Network tables (simulating a network)
        poreTableNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__, "PoreNetwork_pore_table")
        poreTableNode.SetAttribute("table_type", "pore_table")

        # Add some data to pore table
        poreTable = poreTableNode.GetTable()
        poreRadius = vtk.vtkFloatArray()
        poreRadius.SetName("pore.radius")
        poreRadius.InsertNextValue(1.0)
        poreRadius.InsertNextValue(2.0)
        poreTable.AddColumn(poreRadius)
        poreTableNode.Modified()

        throatTableNode = slicer.mrmlScene.AddNewNodeByClass(
            slicer.vtkMRMLTableNode.__name__, "PoreNetwork_throat_table"
        )
        throatTableNode.SetAttribute("table_type", "throat_table")

        # Add some data to throat table
        throatTable = throatTableNode.GetTable()
        throatRadius = vtk.vtkFloatArray()
        throatRadius.SetName("throat.radius")
        throatRadius.InsertNextValue(0.5)
        throatTable.AddColumn(throatRadius)
        throatTableNode.Modified()

        initialPoreNodeId = poreTableNode.GetID()
        initialThroatNodeId = throatTableNode.GetID()

        # 1. "Save as" the project
        save_project(projectFilePath, properties={"useCompression": 0})

        # Verify initial files exist
        self.assertTrue(
            (dataDir / f"{initialPoreNodeId}.tsv").exists(),
            f"Pore table TSV file not found: {dataDir / f'{initialPoreNodeId}.tsv'}",
        )
        self.assertTrue(
            (dataDir / f"{initialPoreNodeId}.schema.tsv").exists(),
            f"Pore table schema file not found: {dataDir / f'{initialPoreNodeId}.schema.tsv'}",
        )
        self.assertTrue(
            (dataDir / f"{initialThroatNodeId}.tsv").exists(),
            f"Throat table TSV file not found: {dataDir / f'{initialThroatNodeId}.tsv'}",
        )
        self.assertTrue(
            (dataDir / f"{initialThroatNodeId}.schema.tsv").exists(),
            f"Throat table schema file not found: {dataDir / f'{initialThroatNodeId}.schema.tsv'}",
        )

        # 2. Make any alteration (e.g. modify the pore table)
        # Retrieve the node by ID to ensure we're modifying the correct object in the current scene
        currentPoreNode = slicer.mrmlScene.GetNodeByID(initialPoreNodeId)
        self.assertIsNotNone(currentPoreNode, "Pore table node not found in scene for modification.")
        currentPoreNode.GetTable().GetColumnByName("pore.radius").SetValue(0, 1.5)  # Change value
        currentPoreNode.Modified()

        # 3. "Save" (overwrite)
        save_current_project(properties={"useCompression": 0})

        # Verify if changes were saved and files still exist after overwrite
        close_project()

        # Re-verify files existence after loading the project
        assert load_project(projectFilePath), f"Failed to load project '{projectFilePath}'"

        loadedPoreTableNode = tryGetNode("PoreNetwork_pore_table")
        self.assertIsNotNone(loadedPoreTableNode, "Loaded PoreNetwork_pore_table node is None.")
        self.assertAlmostEqual(loadedPoreTableNode.GetTable().GetColumnByName("pore.radius").GetValue(0), 1.5)

        self.assertTrue(
            (dataDir / f"{loadedPoreTableNode.GetID()}.tsv").exists(),
            f"Loaded Pore table TSV file not found: {dataDir / f'{loadedPoreTableNode.GetID()}.tsv'}",
        )
        self.assertTrue(
            (dataDir / f"{loadedPoreTableNode.GetID()}.schema.tsv").exists(),
            f"Loaded Pore table schema file not found: {dataDir / f'{loadedPoreTableNode.GetID()}.schema.tsv'}",
        )

        loadedThroatTableNode = tryGetNode("PoreNetwork_throat_table")
        self.assertIsNotNone(loadedThroatTableNode, "Loaded PoreNetwork_throat_table node is None.")
        self.assertTrue(
            (dataDir / f"{loadedThroatTableNode.GetID()}.tsv").exists(),
            f"Loaded Throat table TSV file not found: {dataDir / f'{loadedThroatTableNode.GetID()}.tsv'}",
        )
        self.assertTrue(
            (dataDir / f"{loadedThroatTableNode.GetID()}.schema.tsv").exists(),
            f"Loaded Throat table schema file not found: {dataDir / f'{loadedThroatTableNode.GetID()}.schema.tsv'}",
        )


class NodeCustomBehaviorFactoryTest(LTracePluginTest):
    def _create_custom_node(self, cls: slicer.vtkMRMLNode, attributes: dict):
        node = slicer.mrmlScene.AddNewNodeByClass(cls.__name__)
        for attr, value in attributes.items():
            node.SetAttribute(attr, value)

        return node

    def test_factory(self) -> None:
        parametrized_dict = [
            {
                "class": slicer.vtkMRMLVectorVolumeNode,
                "attributes": {LosslessAttribute.name(): LosslessAttribute.TRUE.value},
                "test_id": "image_node_lossless_attribute",
                "expected_custom_behavior_classes": [VolumeNodeCustomBehavior],
            },
            {
                "class": slicer.vtkMRMLVectorVolumeNode,
                "attributes": {LosslessAttribute.name(): LosslessAttribute.FALSE.value},
                "test_id": "image_node_valid_lossy_attribute",
                "expected_custom_behavior_classes": [VectorVolumeNodeFromImageCustomBehavior, VolumeNodeCustomBehavior],
            },
            {
                "class": slicer.vtkMRMLScalarVolumeNode,
                "attributes": {LosslessAttribute.name(): LosslessAttribute.TRUE.value},
                "test_id": "invalid_type_image_node_lossy_attribute",
                "expected_custom_behavior_classes": [VolumeNodeCustomBehavior],
            },
            {
                "class": slicer.vtkMRMLTableNode,
                "attributes": {},
                "test_id": "table_node_any",
                "expected_custom_behavior_classes": [TableNodeCustomBehavior],
            },
            {
                "class": slicer.vtkMRMLSegmentationDisplayNode,
                "attributes": {},
                "test_id": "segmentation_display_node_any",
                "expected_custom_behavior_classes": [SegmentationDisplayNodeCustomBehavior],
            },
            {
                "class": slicer.vtkMRMLLabelMapVolumeNode,
                "attributes": {},
                "test_id": "volume_node_any",
                "expected_custom_behavior_classes": [VolumeNodeCustomBehavior],
            },
            {
                "class": slicer.vtkMRMLMultiVolumeRenderingDisplayNode,
                "attributes": {},
                "test_id": "volume_rendering_display_node_any",
                "expected_custom_behavior_classes": [VolumeRenderingDisplayNodeCustomBehavior],
            },
            {
                "class": slicer.vtkMRMLTextNode,
                "attributes": {},
                "test_id": "text_node_any",
                "expected_custom_behavior_classes": [],
            },
            {
                "class": DirectoryNode.getNodeType(),
                "attributes": {DirectoryNode.getNodeAttribute()[0]: DirectoryNode.getNodeAttribute()[1]},
                "test_id": "directory_node",
                "expected_custom_behavior_classes": [DirectoryNodeCustomBehavior],
            },
        ]

        for param in parametrized_dict:
            cls = param["class"]
            attributes = param["attributes"]
            testId = param["test_id"]
            expectedCustomBehaviorClasses = param["expected_custom_behavior_classes"]
            expectedCustomBehaviorClassesNames = [cls.__name__ for cls in expectedCustomBehaviorClasses]

            node = self._create_custom_node(cls=cls, attributes=attributes)
            customBehaviors = NodeCustomBehaviorFactory.factory(node=node, event=TriggerEvent.NONE, eventArgs={})
            customBehaviorsNames = [customBehavior.__class__.__name__ for customBehavior in customBehaviors]
            assert customBehaviorsNames == expectedCustomBehaviorClassesNames, (
                f"Assert fail for '{testId}'.Expected: {expectedCustomBehaviorClassesNames}. Actual: {customBehaviorsNames}"
            )
            assert len(customBehaviors) == len(expectedCustomBehaviorClasses), (
                f"Assert fail for '{testId}'.Expected: {len(expectedCustomBehaviorClasses)}. Actual: {len(customBehaviors)}"
            )
