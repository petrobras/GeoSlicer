import slicer
from commons.slicer.helpers import createTemporaryVolumeNode, tryGetNode
from commons.slicer_utils import LTracePluginTest
from commons.slicer.tests.utils import process_events
import SubjectHierarchyPlugins
import numpy as np
import vtk


class CenterSubjectHierarchyPluginTest(LTracePluginTest):
    def test_create_sequence_from_folder_then_unpack_sequence(self):
        scriptedPlugin = slicer.qSlicerSubjectHierarchyScriptedPlugin(None)
        scriptedPlugin.setPythonSource(SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin.filePath)
        centerPlugin = SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin(scriptedPlugin)

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        parentItemId = subjectHierarchyNode.GetSceneItemID()
        folderLabel = "Test folder"
        testDir = subjectHierarchyNode.CreateFolderItem(parentItemId, folderLabel)

        numberOfNodes = 3
        for i in range(numberOfNodes):
            node = createTemporaryVolumeNode(slicer.vtkMRMLScalarVolumeNode, f"node_{i}")
            subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(node), testDir)

        centerPlugin.create_sequence_from_folder(testDir)

        outputName = f"{folderLabel}_{node.GetClassName()}".replace("vtkMRML", "").replace("Node", "")

        proxyNode = tryGetNode(f"{outputName}_proxy")
        sequenceNode = tryGetNode(f"{outputName}_sequence")

        assert proxyNode is not None
        assert sequenceNode is not None
        assert sequenceNode.GetNumberOfDataNodes() == numberOfNodes
        assert tryGetNode(f"{outputName}_browser") is not None

        centerPlugin.extract_volumes_from_sequence(proxyNode)

        for i in range(numberOfNodes):
            assert tryGetNode(f"{proxyNode.GetName()}_1_r{i}") is not None

    def test_find_and_create_labelmap_from_segmentation(self):
        scriptedPlugin = slicer.qSlicerSubjectHierarchyScriptedPlugin(None)
        scriptedPlugin.setPythonSource(SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin.filePath)
        centerPlugin = SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin(scriptedPlugin)

        # Create a segmentation from a random-filled label map
        volumeArray = np.random.random_integers(0, 255, (20, 1, 20)).astype(np.uint16)
        testLabelMap = slicer.util.addVolumeFromArray(
            volumeArray, name="TestLabelMapNode", nodeClassName="vtkMRMLLabelMapVolumeNode"
        )
        testSegmentationName = "TestSegmentationNode"
        testSegmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", testSegmentationName)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(testLabelMap, testSegmentation)
        newSegment_segmentID = testSegmentation.GetSegmentation().AddEmptySegment(
            "newSegment_segmentID", "NewSegmentName"
        )  # note: it's a segment ID (not a hierarchy ID)
        process_events()

        pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler().instance()
        subjectHierarchyNode = pluginHandlerSingleton.subjectHierarchyNode()

        # Creating label map from selecting the segmentation:

        segmentationItemID = subjectHierarchyNode.GetItemByDataNode(testSegmentation)
        pluginHandlerSingleton.setCurrentItem(segmentationItemID)  # selected node

        centerPlugin.find_and_create_labelmap_from_items()

        createdLabelMap = tryGetNode(testSegmentationName + "-label")
        assert createdLabelMap is not None
        assert createdLabelMap.GetNodeReferenceID("referenceImageGeometryRef") == testSegmentation.GetID()

        # Creating label map from selecting a segment:

        """
        print(f"testSegmentation.GetSegmentation().GetSegmentIdBySegmentName({newSegmentName}): {testSegmentation.GetSegmentation().GetSegmentIdBySegmentName(newSegmentName)}")
        pluginHandlerSingleton.setCurrentItem(
            subjectHierarchyNode.GetItemChildWithName(segmentationItemID, newSegmentName) #, newSegment_segmentID?
        ) 
        Not sure why the approach above didn't work. Below, iterating through children instead."""

        children = vtk.vtkIdList()
        subjectHierarchyNode.GetItemChildren(segmentationItemID, children)
        segmentHierarchyID = 0
        for i in range(children.GetNumberOfIds()):
            childID = children.GetId(i)
            # Check the "segmentID" attribute specifically
            if subjectHierarchyNode.GetItemAttribute(childID, "segmentID") == newSegment_segmentID:
                segmentHierarchyID = childID
                break
        pluginHandlerSingleton.setCurrentItem(segmentHierarchyID)  # selected node

        centerPlugin.find_and_create_labelmap_from_items()

        createdLabelMap = tryGetNode(testSegmentationName + "-label")
        assert createdLabelMap is not None
        assert createdLabelMap.GetNodeReferenceID("referenceImageGeometryRef") == testSegmentation.GetID()
