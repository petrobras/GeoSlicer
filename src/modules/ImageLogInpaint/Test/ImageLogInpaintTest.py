import vtk
import slicer
import numpy as np
import slicer.util
import shutil
import tempfile
import qt

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import save_project, load_project, process_events, save_current_project, wait
from commons.constants import ImageLogInpaintConst
from commons.slicer.helpers import tryGetNode, make_directory_writable
from commons.slicer import metadata
from pathlib import Path

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
PROJECT_FILE = TEST_RESOURCES_DIR / "INPAINT" / "INPAINT.mrml"
NUMBER_OF_VIEWS = 2


class ImageLogInpaintTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = {
            "segmentationComboBox": self.find_widget("segmentationNodeComboBox"),
            "sourceVolumeComboBox": self.find_widget("sourceVolumeNodeComboBox"),
            "undo": self.find_widget("undoButtonInpaint"),
            "redo": self.find_widget("redoButtonInpaint"),
            "clone": self.find_widget("cloneVolumeButton"),
            "rename": self.find_widget("renameVolumeButton"),
        }

        slicer.util.selectModule("ImageLogEnv")
        imageLogData = slicer.modules.imagelogdata.widgetRepresentation()
        self._module_widget.logic.imageLogDataLogic = imageLogData.self().logic
        process_events()

    def tear_down(self):
        self._module_widget.exit()
        process_events()

    def test_default_interface_configuration(self):
        assert self._widgets["segmentationComboBox"] is not None
        assert not self._widgets["segmentationComboBox"].visible
        assert self._widgets["segmentationComboBox"].currentNode() is not None

        segmentationNode = self._widgets["segmentationComboBox"].currentNode()

        assert segmentationNode.GetSegmentation().GetNumberOfSegments() == 1
        assert segmentationNode.GetSegmentation().GetNthSegmentID(0) == ImageLogInpaintConst.SEGMENT_ID

        assert self._widgets["sourceVolumeComboBox"] is not None
        assert self._widgets["sourceVolumeComboBox"].currentNode() is None

        assert self._widgets["undo"] is not None
        assert not self._widgets["undo"].enabled

        assert self._widgets["redo"] is not None
        assert not self._widgets["redo"].enabled

        assert self._widgets["clone"] is not None
        assert not self._widgets["clone"].enabled

        assert self._widgets["rename"] is not None
        assert not self._widgets["rename"].enabled

    def test_source_volume_combo_box_selection(self):
        imageLog = slicer.util.addVolumeFromArray(
            np.random.random((1200, 1, 360)), name="TestImageLog1", nodeClassName="vtkMRMLScalarVolumeNode"
        )

        assert not self._widgets["clone"].enabled
        assert not self._widgets["rename"].enabled

        assert len(self._module_widget.logic.imageLogDataLogic.imageLogViewList) == 0

        self._widgets["sourceVolumeComboBox"].setCurrentNode(imageLog)

        assert self._widgets["clone"].enabled
        assert self._widgets["rename"].enabled

        imageLogSegmentation = tryGetNode(imageLog.GetName() + "_Segmentation")

        assert imageLogSegmentation is not None
        assert imageLogSegmentation.GetSegmentation().GetNumberOfSegments() == 1
        assert imageLogSegmentation.GetSegmentation().GetNthSegmentID(0) == ImageLogInpaintConst.SEGMENT_ID

        assert len(self._module_widget.logic.imageLogDataLogic.imageLogViewList) == NUMBER_OF_VIEWS

    def test_clone_volume(self):
        imageLog = slicer.util.addVolumeFromArray(
            np.random.random((1200, 1, 360)), name="TestImageLog1", nodeClassName="vtkMRMLScalarVolumeNode"
        )

        metadata.Metadata(imageLog)["DummyMetadataTest"] = "test_value"

        self._widgets["sourceVolumeComboBox"].setCurrentNode(imageLog)
        self._widgets["clone"].clicked()
        process_events()

        imageLogClone = self._widgets["sourceVolumeComboBox"].currentNode()

        assert imageLogClone is not None
        assert (slicer.util.arrayFromVolume(imageLogClone) == slicer.util.arrayFromVolume(imageLog)).all()
        assert imageLogClone.GetName() == imageLog.GetName() + "_Inpaint"

        # Assert metadata is propagated

        assert metadata.Metadata(imageLogClone)["DummyMetadataTest"] == "test_value"
        # TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        input_itemID = subjectHierarchyNode.GetItemByDataNode(imageLog)
        output_itemID = subjectHierarchyNode.GetItemByDataNode(imageLogClone)
        assert subjectHierarchyNode.GetItemAttributeNames(input_itemID) == subjectHierarchyNode.GetItemAttributeNames(
            output_itemID
        )
        assert imageLog.GetNumberOfNodeReferences(
            "referenceImageGeometryRef"
        ) == imageLogClone.GetNumberOfNodeReferences("referenceImageGeometryRef")
        assert imageLog.GetNumberOfNodeReferences("referenceVolume") == imageLogClone.GetNumberOfNodeReferences(
            "referenceVolume"
        )

    def test_rename_volume_ok(self):
        newName = "NewTestImageLogName1"
        self._rename_volume("TestImageLog1", newName, lambda: self._find_rename_widget_and_rename(newName))

    def test_rename_volume_ok_with_name_unchanged(self):
        self._rename_volume("TestImageLog1", "TestImageLog1", self._find_rename_widget_and_accept)

    def test_rename_volume_ok_with_existing_name(self):
        slicer.util.addVolumeFromArray(
            np.random.random((1200, 1, 360)), name="TestImageLog1", nodeClassName="vtkMRMLScalarVolumeNode"
        )
        self._rename_volume(
            "TestImageLog2", "TestImageLog1_1", lambda: self._find_rename_widget_and_rename("TestImageLog1")
        )

    def test_rename_volume_cancel(self):
        self._rename_volume("TestImageLog1", "TestImageLog1", self._find_rename_widget_and_reject)

    def test_inpaint_image_log(self):
        initialVolume = np.random.random((1200, 1, 360))
        imageLog = slicer.util.addVolumeFromArray(
            initialVolume, name="TestImageLog1", nodeClassName="vtkMRMLScalarVolumeNode"
        )

        self._inpaint_volume(initialVolume, imageLog)

    def test_undo_and_redo_inpaint(self):
        initialVolume = np.random.random((1200, 1, 360))
        imageLog = slicer.util.addVolumeFromArray(
            initialVolume, name="TestImageLog1", nodeClassName="vtkMRMLScalarVolumeNode"
        )

        inpaintedVolume = self._inpaint_volume(initialVolume, imageLog)

        assert self._widgets["undo"].enabled
        assert not self._widgets["redo"].enabled

        self._widgets["undo"].clicked()
        process_events()
        undoVolume = slicer.util.arrayFromVolume(imageLog)

        assert (initialVolume == undoVolume).all()
        assert not self._widgets["undo"].enabled
        assert self._widgets["redo"].enabled

        self._widgets["redo"].clicked()
        process_events()
        redoVolume = slicer.util.arrayFromVolume(imageLog)

        assert (inpaintedVolume == redoVolume).all()
        assert self._widgets["undo"].enabled
        assert not self._widgets["redo"].enabled

    def test_undo_and_redo_inpaint_history(self):
        initialVolume = np.random.random((1200, 1, 360))
        imageLog = slicer.util.addVolumeFromArray(
            initialVolume, name="TestImageLog1", nodeClassName="vtkMRMLScalarVolumeNode"
        )

        self._inpaint_volume(initialVolume, imageLog)
        self._inpaint_volume(initialVolume, imageLog)
        self._inpaint_volume(initialVolume, imageLog)

        assert self._widgets["undo"].enabled
        assert not self._widgets["redo"].enabled

        self._widgets["undo"].clicked()
        process_events()

        assert self._widgets["undo"].enabled
        assert self._widgets["redo"].enabled

        self._widgets["undo"].clicked()
        process_events()

        assert self._widgets["undo"].enabled
        assert self._widgets["redo"].enabled

        self._inpaint_volume(initialVolume, imageLog)

        assert self._widgets["undo"].enabled
        assert not self._widgets["redo"].enabled

    def test_save_project(self):
        tempDirectory = Path(tempfile.TemporaryDirectory().name)
        tempDirectory.mkdir(parents=True, exist_ok=True)

        initialVolume = np.random.random((1200, 1, 360))
        imageLog = slicer.util.addVolumeFromArray(
            initialVolume, name="TestImageLog1", nodeClassName="vtkMRMLScalarVolumeNode"
        )

        self._inpaint_volume(initialVolume, imageLog)

        assert self._widgets["undo"].enabled
        assert not self._widgets["redo"].enabled

        segmentationCombBox = self._widgets["segmentationComboBox"]
        sourceVolumeComboBox = self._widgets["sourceVolumeComboBox"]

        projectFilePath = tempDirectory / "test_project" / "test_project.mrml"

        assert save_project(projectFilePath)

        assert segmentationCombBox.currentNode() is not None
        assert sourceVolumeComboBox.currentNode().GetID() == imageLog.GetID()
        assert not self._widgets["undo"].enabled
        assert not self._widgets["redo"].enabled
        assert len(self._module_widget.logic.imageLogDataLogic.imageLogViewList) == NUMBER_OF_VIEWS

        assert save_current_project()

        assert segmentationCombBox.currentNode() is not None
        assert sourceVolumeComboBox.currentNode().GetID() == imageLog.GetID()
        assert not self._widgets["undo"].enabled
        assert not self._widgets["redo"].enabled
        assert len(self._module_widget.logic.imageLogDataLogic.imageLogViewList) == NUMBER_OF_VIEWS

        shutil.rmtree(tempDirectory, onexc=make_directory_writable)

    def test_load_project(self):
        load_project(PROJECT_FILE)

        segmentationCombBox = self._widgets["segmentationComboBox"]
        sourceVolumeComboBox = self._widgets["sourceVolumeComboBox"]

        assert segmentationCombBox.currentNode() is not None
        assert sourceVolumeComboBox.currentNode() is not None
        assert sourceVolumeComboBox.currentNode().GetName() == "TestImageLog1"
        assert self._module_widget.parameterNode is not None
        assert len(self._module_widget.parameterNode.segmentations) == 1
        assert sourceVolumeComboBox.currentNode() in self._module_widget.parameterNode.segmentations
        assert len(self._module_widget.logic.imageLogDataLogic.imageLogViewList) == NUMBER_OF_VIEWS
        assert tryGetNode("TestImageLog1_Inpaint") is not None

    def test_inpaint_with_segmentation_out_of_volume_scope(self):
        initialVolume = np.random.random((1200, 1, 360))
        imageLog = slicer.util.addVolumeFromArray(
            initialVolume, name="TestImageLog1", nodeClassName="vtkMRMLScalarVolumeNode"
        )

        segment = np.zeros_like(initialVolume, dtype=np.uint8)
        labelMap = slicer.util.addVolumeFromArray(
            segment, name="inpaintLabelMap", nodeClassName="vtkMRMLLabelMapVolumeNode"
        )

        segmentationCombBox = self._widgets["segmentationComboBox"]
        sourceVolumeComboBox = self._widgets["sourceVolumeComboBox"]

        sourceVolumeComboBox.setCurrentNode(imageLog)
        inpaintSegmentation = segmentationCombBox.currentNode()

        ids = vtk.vtkStringArray()
        ids.InsertNextValue(ImageLogInpaintConst.SEGMENT_ID)

        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelMap, inpaintSegmentation, ids)
        process_events()

        inpaintedVolume = slicer.util.arrayFromVolume(imageLog)

        assert (initialVolume == inpaintedVolume).all()

        imageLogSegmentation = tryGetNode(imageLog.GetName() + "_Segmentation")

        assert imageLogSegmentation is not None
        assert imageLogSegmentation.GetSegmentation().GetNumberOfSegments() == 1
        assert imageLogSegmentation.GetSegmentation().GetNthSegmentID(0) == ImageLogInpaintConst.SEGMENT_ID

        imageLogSegmentationArray = slicer.util.arrayFromSegmentBinaryLabelmap(
            imageLogSegmentation, ImageLogInpaintConst.SEGMENT_ID
        )

        assert (imageLogSegmentationArray == segment).all()
        assert not self._widgets["undo"].enabled
        assert not self._widgets["redo"].enabled

    def test_clear_views_when_node_is_none(self):
        imageLog = slicer.util.addVolumeFromArray(
            np.random.random((1200, 1, 360)), name="TestImageLog1", nodeClassName="vtkMRMLScalarVolumeNode"
        )

        sourceVolumeComboBox = self._widgets["sourceVolumeComboBox"]
        sourceVolumeComboBox.setCurrentNode(imageLog)

        viewsNumber = len(self._module_widget.logic.imageLogDataLogic.imageLogViewList)
        assert viewsNumber == NUMBER_OF_VIEWS, f"Expected number of views: {NUMBER_OF_VIEWS}. Actual: {viewsNumber}"

        sourceVolumeComboBox.setCurrentNode(None)

        viewsNumber = len(self._module_widget.logic.imageLogDataLogic.imageLogViewList)
        assert viewsNumber == 0, f"Expected number of views: 0. Actual: {viewsNumber}"

    def test_observers_handling(self) -> None:
        """Test the observers reference life-time handling."""
        observers = self._module_widget._observerTags
        tempSegmentationNodeId = self._module_widget._tempSegmentation.GetID()
        assert len(observers[slicer.mrmlScene]) == 4, (
            f"Expected a total of '4' observers for mrmlScene. Actual: {len(observers[slicer.mrmlScene])}."
        )
        assert observers[tempSegmentationNodeId] is not None, (
            f"Expected a total of '1' observers for tempSegmentation. Actual: {observers[tempSegmentationNodeId]}."
        )

        self._module_widget.exit()
        wait(0.5)
        assert len(observers.get(slicer.mrmlScene, [])) == 0, (
            f"Expected a total of '0' observers for mrmlScene. Actual: {len(observers[slicer.mrmlScene])}."
        )
        assert self._module_widget._tempSegmentation is None
        assert observers.get(tempSegmentationNodeId) is None, (
            f"Expected a total of '0' observers for tempSegmentation. Actual: {observers[tempSegmentationNodeId]}"
        )

        self._module_widget.enter()
        wait(0.5)
        tempSegmentationNodeId = self._module_widget._tempSegmentation.GetID()
        assert len(observers[slicer.mrmlScene]) == 4, (
            f"Expected a total of '4' observers for mrmlScene. Actual: {len(observers[slicer.mrmlScene])}."
        )
        assert observers[tempSegmentationNodeId] is not None, (
            f"Expected a total of '1' observers for tempSegmentation. Actual: {observers[tempSegmentationNodeId]}."
        )

    def _inpaint_volume(self, initialVolume, imageLog):
        endZ = 40
        initX = 300
        endX = 350

        segment = np.zeros_like(initialVolume, dtype=np.uint8)
        segment[:endZ, :, initX:endX] = 1
        labelMap = slicer.util.addVolumeFromArray(
            segment, name="inpaintLabelMap", nodeClassName="vtkMRMLLabelMapVolumeNode"
        )

        segmentationCombBox = self._widgets["segmentationComboBox"]
        sourceVolumeComboBox = self._widgets["sourceVolumeComboBox"]

        sourceVolumeComboBox.setCurrentNode(imageLog)
        inpaintSegmentation = segmentationCombBox.currentNode()

        assert len(self._module_widget.logic.imageLogDataLogic.imageLogViewList) == NUMBER_OF_VIEWS

        ids = vtk.vtkStringArray()
        ids.InsertNextValue(ImageLogInpaintConst.SEGMENT_ID)

        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelMap, inpaintSegmentation, ids)
        process_events()

        inpaintedVolume = slicer.util.arrayFromVolume(imageLog)

        assert not (initialVolume[:endZ, :, initX:endX] == inpaintedVolume[:endZ, :, initX:endX]).all()
        assert (initialVolume[:endZ, :, :initX] == inpaintedVolume[:endZ, :, :initX]).all()
        assert (initialVolume[:endZ, :, endX:] == inpaintedVolume[:endZ, :, endX:]).all()
        assert (initialVolume[endZ:, :, :] == inpaintedVolume[endZ:, :, :]).all()

        imageLogSegmentation = tryGetNode(imageLog.GetName() + "_Segmentation")

        assert imageLogSegmentation is not None
        assert imageLogSegmentation.GetSegmentation().GetNumberOfSegments() == 1
        assert imageLogSegmentation.GetSegmentation().GetNthSegmentID(0) == ImageLogInpaintConst.SEGMENT_ID

        imageLogSegmentationArray = slicer.util.arrayFromSegmentBinaryLabelmap(
            imageLogSegmentation, ImageLogInpaintConst.SEGMENT_ID
        )

        assert (imageLogSegmentationArray == segment).all()

        return inpaintedVolume

    def _rename_volume(self, initialName, newName, func):
        imageLog = slicer.util.addVolumeFromArray(
            np.random.random((1200, 1, 360)), name=initialName, nodeClassName="vtkMRMLScalarVolumeNode"
        )

        self._widgets["sourceVolumeComboBox"].setCurrentNode(imageLog)
        segmentation = tryGetNode(initialName + "_Segmentation")

        assert segmentation is not None

        qt.QTimer.singleShot(2000, func)
        self._widgets["rename"].clicked()
        process_events()

        receivedNewName = self._widgets["sourceVolumeComboBox"].currentNode().GetName()

        assert receivedNewName == newName, f"Expected newName to be {newName}, got {receivedNewName} instead"
        assert segmentation.GetName() == newName + "_Segmentation"

    def _find_rename_widget_and_reject(self):
        parent = slicer.modules.AppContextInstance.mainWindow
        renameDialog = parent.findChild(qt.QDialog, "renameDialog")

        renameDialog.reject()
        renameDialog.deleteLater()

    def _find_rename_widget_and_accept(self):
        parent = slicer.modules.AppContextInstance.mainWindow
        renameDialog = parent.findChild(qt.QDialog, "renameDialog")

        renameDialog.accept()
        renameDialog.deleteLater()

    def _find_rename_widget_and_rename(self, newName):
        parent = slicer.modules.AppContextInstance.mainWindow
        renameDialog = parent.findChild(qt.QDialog, "renameDialog")
        renameDialog.setOutputName(newName)
        renameDialog.accept()
        renameDialog.deleteLater()
