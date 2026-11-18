import vtk
import slicer
import numpy as np

from commons.slicer.helpers import (
    createLabelmapInput,
    createTemporaryNode,
    removeTemporaryNodes,
    getNodesWithAttribute,
    createTemporaryVolumeNode,
    makeTemporaryNodePermanent,
    tryGetNode,
    tryGetNodes,
    get_scripted_modules_path,
    disableSlice3DEdges,
    isSegmentIdEmpty,
    isLabelMapValueEmpty,
)
from commons.slicer.node_attributes import ColorMapSelectable, NodeEnvironment, NodeTemporarity
from commons.slicer_utils import LTracePluginTest
from commons.slicer.tests.utils import wait, process_events, load_project
from pathlib import Path


RESOURCES_DIR = Path(__file__).parent / "Resources"
SEGMENTATION_PROJECT_FILE_PATH = RESOURCES_DIR / "Segmentation" / "Segmentation.mrml"


class HelpersTest(LTracePluginTest):
    def test_create_and_remove_temporary_volume_nodes(self):
        """
        Tests creation and removal of temporary volume nodes by environment.
        """

        # remove all initial temporary nodes
        removeTemporaryNodes()

        # create some image log volume nodes
        tempNodesStart = getNodesWithAttribute(NodeTemporarity.TRUE.value)
        for i in range(3):
            createTemporaryVolumeNode(
                slicer.vtkMRMLScalarVolumeNode, f"node_{i}", environment=NodeEnvironment.IMAGE_LOG.value
            )
        tempNodesCreated = getNodesWithAttribute(NodeTemporarity.TRUE.value)

        # removing nodes inside environment that has no nodes
        removeTemporaryNodes(NodeEnvironment.MICRO_CT.value)
        tempNodesAfterRemoval = getNodesWithAttribute(NodeTemporarity.TRUE.value)
        test1 = len(tempNodesAfterRemoval) == len(tempNodesCreated)
        assert test1

        # removing nodes inside environment that has all the nodes
        removeTemporaryNodes(NodeEnvironment.IMAGE_LOG.value)
        tempNodesAfterRemoval = getNodesWithAttribute(NodeTemporarity.TRUE.value)
        test2 = len(tempNodesAfterRemoval) == len(tempNodesStart)
        assert test2

    def test_create_and_remove_temporary_label_map(self):
        tag = "Test"
        segmentation_node = createTemporaryNode(
            slicer.vtkMRMLSegmentationNode,
            name="TMP-Segmentation",
            environment=tag,
            hidden=False,
            saveWithScene=False,
            uniqueName=True,
        )
        label_map_volume_node, _ = createLabelmapInput(
            segmentationNode=segmentation_node,
            name="TMP-LabelMap",
            segments="all",
            tag=tag,
            referenceNode=None,
            soiNode=None,
            uniqueName=True,
        )

        assert label_map_volume_node is not None
        assert segmentation_node is not None
        assert tryGetNode("TMP-Segmentation") is not None
        assert tryGetNode("TMP-LabelMap") is not None
        removeTemporaryNodes(tag)
        assert tryGetNode("TMP-Segmentation") is None
        assert tryGetNode("TMP-LabelMap") is None

    def test_make_temporary_node_permanent_and_attempt_remove(self):
        environment = NodeEnvironment.IMAGE_LOG.value
        node_name = "TMP-PERMANENT-NODE"

        node = createTemporaryVolumeNode(
            slicer.vtkMRMLScalarVolumeNode,
            node_name,
            environment=environment,
            saveWithScene=False,
            uniqueName=False,
        )

        assert node is not None
        assert node.GetAttribute(NodeTemporarity.name()) == NodeTemporarity.TRUE.value
        makeTemporaryNodePermanent(node)
        assert node.GetAttribute(NodeTemporarity.name()) == NodeTemporarity.FALSE.value
        removeTemporaryNodes(environment)
        assert tryGetNode(node_name) is not None

    def test_get_scripted_modules_path(self):
        path = Path(get_scripted_modules_path())
        self.assertEqual(path.name, "qt-scripted-modules")
        self.assertTrue(path.parent.name.startswith("GeoSlicer-"))
        self.assertTrue(path.is_dir())

    def test_remove_temporary_node_doesnt_delete_color_node_from_lookup_table(self):
        array = np.random.rand(200, 200, 200) * 1000
        volumeNode = createTemporaryNode(slicer.vtkMRMLScalarVolumeNode, "ScalarNode", uniqueName=False)
        volumeNode.CreateDefaultDisplayNodes()

        slicer.util.updateVolumeFromArray(volumeNode, array)
        wait(1)

        # Get display node ID to check its existence after removal
        displayNode = volumeNode.GetDisplayNode()
        displayNodeId = displayNode.GetID()

        # Get color node ID to check its existence after removal (should not be deleted, because it is a lookup table)
        colorNode = displayNode.GetColorNode()
        colorNodeId = colorNode.GetID()
        assert colorNode.GetAttribute(ColorMapSelectable.name()) is not None, "Color node is not a lookup table"

        displayNode = colorNode = None
        slicer.util.setSliceViewerLayers(background=volumeNode, fit=True)
        wait(1)

        removeTemporaryNodes()
        wait(1)

        assert tryGetNode(displayNodeId) is None, "Display node was deleted"
        assert tryGetNode(colorNodeId) is not None, "Color node was deleted"

    def test_tryGetNode_with_same_name_for_folder_and_volume(self):
        """
        Ensure tryGetNode returns the correct node when both a vtkMRMLFolderDisplayNode
        and a volume share the same name.
        """
        name = "SameName"

        # Create a volume node
        volume_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", name)
        imageData = vtk.vtkImageData()
        imageData.SetDimensions(1, 1, 1)
        imageData.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        volume_node.SetAndObserveImageData(imageData)
        assert volume_node is not None
        assert hasattr(volume_node, "GetImageData") and volume_node.GetImageData()

        # Create the folder item
        sh_node = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        folder_item_id = sh_node.CreateFolderItem(sh_node.GetSceneItemID(), name)
        folder_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLFolderDisplayNode", name)
        sh_node.SetItemUID(folder_item_id, "vtkMRMLNodeID", folder_node.GetID())
        assert folder_node is not None

        # test tryGetNode()
        result = tryGetNode(name)
        assert result is folder_node, f"Expected folder node, got {type(result)}"

        result = tryGetNode(name, hasImageData=True)
        assert result is volume_node, f"Expected volume node with image data, got {type(result)}"

        # test tryGetNodes()
        results, count = tryGetNodes(name)
        assert count == 2, "Expected folder and volume nodes to be in return value of tryGetNodes()"

        results, count = tryGetNodes(name, hasImageData=True)
        assert count == 1, "Expected just volume nodes to be in return value of tryGetNodes(, hasImageData)"

        # Cleanup
        slicer.mrmlScene.RemoveNode(volume_node)
        slicer.mrmlScene.RemoveNode(folder_node)

    def test_disable_slice_view_3d_edge(self):
        # Set all slices edge 3D as visible
        for sliceName in ["Red", "Yellow", "Green"]:
            sliceWidget = slicer.app.layoutManager().sliceWidget(sliceName)
            slicerController = sliceWidget.sliceController()
            slicerController.setSliceEdgeVisibility3D(True)

        process_events()
        disableSlice3DEdges()

        # Check each slice view configuration
        for sliceName in ["Red", "Yellow", "Green"]:
            sliceWidget = slicer.app.layoutManager().sliceWidget(sliceName)
            sliceController = sliceWidget.sliceController()
            assert sliceController.sliceLogic().GetSliceNode().GetSliceEdgeVisibility3D() is False, (
                f"Expected '{sliceName}' slice view to have its slice edge 3D visibility disabled"
            )

    def test_is_labelmap_value_empty_method(self):
        load_project(SEGMENTATION_PROJECT_FILE_PATH)
        node = tryGetNode("Segmentation-label")
        assert node is not None, "Node not found"
        assert isLabelMapValueEmpty(node, labelName="V") is True
        assert isLabelMapValueEmpty(node, labelName="Alta") is False
        assert isLabelMapValueEmpty(node, labelName="Media") is False
        assert isLabelMapValueEmpty(node, labelName="Baixa") is False
        assert isLabelMapValueEmpty(node, labelName="Art") is False

    def test_is_segment_id_empty_method(self):
        load_project(SEGMENTATION_PROJECT_FILE_PATH)
        node = tryGetNode("Segmentation")
        assert node is not None, "Node not found"

        # By segment name
        assert isSegmentIdEmpty(node, segmentName="V") is True
        assert isSegmentIdEmpty(node, segmentName="Alta") is False
        assert isSegmentIdEmpty(node, segmentName="Media") is False
        assert isSegmentIdEmpty(node, segmentName="Baixa") is False
        assert isSegmentIdEmpty(node, segmentName="Art") is False

        # By segment id
        segmentation = node.GetSegmentation()

        def getId(segmentName):
            return segmentation.GetSegmentIdBySegmentName(segmentName)

        assert isSegmentIdEmpty(node, segmentId=getId("V")) is True
        assert isSegmentIdEmpty(node, segmentId=getId("Alta")) is False
        assert isSegmentIdEmpty(node, segmentId=getId("Media")) is False
        assert isSegmentIdEmpty(node, segmentId=getId("Baixa")) is False
        assert isSegmentIdEmpty(node, segmentId=getId("Art")) is False

    def test_is_segment_id_empty_exceptions(self):
        # Case: segmentationNode is None
        with self.assertRaises(ValueError) as context:
            isSegmentIdEmpty(None)
        self.assertEqual(str(context.exception), "A valid vtkMRMLSegmentationNode must be provided.")

        # Case: segmentId and segmentName are None
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        with self.assertRaises(ValueError) as context:
            isSegmentIdEmpty(segmentationNode)
        self.assertEqual(str(context.exception), "segmentId or segmentName must be provided")

    def test_is_labelmap_value_empty_exceptions(self):
        # Case: labelmapNode is None
        with self.assertRaises(ValueError) as context:
            isLabelMapValueEmpty(None, labelName="Test")
        self.assertEqual(str(context.exception), "A valid vtkMRMLLabelMapVolumeNode must be provided.")

        # Case: labelName is empty
        labelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        with self.assertRaises(ValueError) as context:
            isLabelMapValueEmpty(labelMapNode, labelName="")
        self.assertEqual(str(context.exception), "A valid 'labelName' must be provided.")

        # Case: Labelmap does not have a Display Node
        with self.assertRaises(RuntimeError) as context:
            isLabelMapValueEmpty(labelMapNode, labelName="Test")
        self.assertEqual(str(context.exception), "Labelmap does not have a Display Node to look up names.")

        # Case: Labelmap Display Node does not have an associated Color Node
        labelMapNode.CreateDefaultDisplayNodes()
        displayNode = labelMapNode.GetDisplayNode()
        displayNode.SetAndObserveColorNodeID("")
        with self.assertRaises(RuntimeError) as context:
            isLabelMapValueEmpty(labelMapNode, labelName="Test")
        self.assertEqual(str(context.exception), "Labelmap Display Node does not have an associated Color Node.")

        # Case: Label name was not found in the color table
        colorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLColorTableNode")
        displayNode.SetAndObserveColorNodeID(colorNode.GetID())
        with self.assertRaises(ValueError) as context:
            isLabelMapValueEmpty(labelMapNode, labelName="NonExistent")
        self.assertEqual(str(context.exception), "Label name 'NonExistent' was not found in the color table.")
