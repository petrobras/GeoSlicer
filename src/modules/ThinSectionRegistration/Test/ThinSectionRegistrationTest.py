from commons.slicer import helpers
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events, wait, check_for_message_box, load_project, close_project
from pathlib import Path

import slicer


RESOURCE_DIR = Path(__file__).parent / "Resources"
TEST_PROJECT = RESOURCE_DIR / "test_project" / "test_project.mrml"


class ThinSectionRegistrationTest(LTracePluginTest):
    def test_attempt_to_register_without_available_images(self) -> None:
        selectVolumesButton = self.find_widget("Select Volumes Button")

        assert selectVolumesButton is not None

        with check_for_message_box("You need at least two different images to register."):
            selectVolumesButton.click()

    def test_attempt_to_register_with_one_image(self) -> None:
        selectVolumesButton = self.find_widget("Select Volumes Button")

        # Create dummy node
        slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "volume")

        assert selectVolumesButton is not None
        with check_for_message_box("You need at least two different images to register."):
            selectVolumesButton.click()

    def test_attempt_to_register_using_the_same_image(self) -> None:
        load_project(TEST_PROJECT)

        fixedVolumeNode = slicer.util.getNode("Fixed")
        selectVolumesButton = self.find_widget("Select Volumes Button")

        with check_for_message_box(
            "You selected the same image for both fixed and moving images. Please select different images."
        ):
            selectVolumesButton.click()
            wait(0.3)
            self._handleInnerDialog(fixedVolumeNode=fixedVolumeNode, movingVolumeNode=fixedVolumeNode)

    def test_register_finished(self) -> None:
        load_project(TEST_PROJECT)

        fixedVolumeNode = slicer.util.getNode("Fixed")
        movingVolumeNode = slicer.util.getNode("Moving")

        self._setConfiguration(fixedVolumeNode, movingVolumeNode)

        finishRegistrationButton = self.find_widget("Finish Registration Button")
        finishRegistrationButton.click()
        process_events()

        assert helpers.tryGetNode("Moving - Transformed") is not None
        assert helpers.tryGetNode("Transform") is None

    def test_register_canceled(self) -> None:
        load_project(TEST_PROJECT)

        fixedVolumeNode = slicer.util.getNode("Fixed")
        movingVolumeNode = slicer.util.getNode("Moving")
        self._setConfiguration(fixedVolumeNode, movingVolumeNode)

        cancelRegistrationButton = self.find_widget("Cancel Registration Button")
        cancelRegistrationButton.click()
        process_events()

        assert helpers.tryGetNode("Moving - Transformed") is None
        assert helpers.tryGetNode("Transform") is None

    def test_register_canceled_by_close_scene(self) -> None:
        load_project(TEST_PROJECT)

        fixedVolumeNode = slicer.util.getNode("Fixed")
        movingVolumeNode = slicer.util.getNode("Moving")
        self._setConfiguration(fixedVolumeNode, movingVolumeNode)

        close_project()
        process_events()

        selectVolumesButton = self.find_widget("Select Volumes Button")
        finishRegistrationButton = self.find_widget("Finish Registration Button")
        cancelRegistrationButton = self.find_widget("Cancel Registration Button")

        assert selectVolumesButton is not None
        assert finishRegistrationButton is not None
        assert cancelRegistrationButton is not None
        assert selectVolumesButton.visible
        assert not finishRegistrationButton.visible
        assert not cancelRegistrationButton.visible

    def test_register_canceled_by_removing_fixed_volume_node(self) -> None:
        load_project(TEST_PROJECT)

        fixedVolumeNode = slicer.util.getNode("Fixed")
        movingVolumeNode = slicer.util.getNode("Moving")
        self._setConfiguration(fixedVolumeNode, movingVolumeNode)

        slicer.mrmlScene.RemoveNode(fixedVolumeNode)
        process_events()

        selectVolumesButton = self.find_widget("Select Volumes Button")
        finishRegistrationButton = self.find_widget("Finish Registration Button")
        cancelRegistrationButton = self.find_widget("Cancel Registration Button")

        assert selectVolumesButton is not None
        assert finishRegistrationButton is not None
        assert cancelRegistrationButton is not None
        assert selectVolumesButton.visible
        assert not finishRegistrationButton.visible
        assert not cancelRegistrationButton.visible

    def test_register_canceled_by_removing_moving_volume_node(self) -> None:
        load_project(TEST_PROJECT)

        fixedVolumeNode = slicer.util.getNode("Fixed")
        movingVolumeNode = slicer.util.getNode("Moving")
        self._setConfiguration(fixedVolumeNode, movingVolumeNode)

        slicer.mrmlScene.RemoveNode(movingVolumeNode)
        process_events()

        selectVolumesButton = self.find_widget("Select Volumes Button")
        finishRegistrationButton = self.find_widget("Finish Registration Button")
        cancelRegistrationButton = self.find_widget("Cancel Registration Button")

        assert selectVolumesButton is not None
        assert finishRegistrationButton is not None
        assert cancelRegistrationButton is not None
        assert selectVolumesButton.visible
        assert not finishRegistrationButton.visible
        assert not cancelRegistrationButton.visible

    def test_register_canceled_by_removing_transform_node(self) -> None:
        load_project(TEST_PROJECT)

        fixedVolumeNode = slicer.util.getNode("Fixed")
        movingVolumeNode = slicer.util.getNode("Moving")
        self._setConfiguration(fixedVolumeNode, movingVolumeNode)

        transformVolumeNode = slicer.util.getNode("Transform")
        slicer.mrmlScene.RemoveNode(transformVolumeNode)
        process_events()

        selectVolumesButton = self.find_widget("Select Volumes Button")
        finishRegistrationButton = self.find_widget("Finish Registration Button")
        cancelRegistrationButton = self.find_widget("Cancel Registration Button")

        assert selectVolumesButton is not None
        assert finishRegistrationButton is not None
        assert cancelRegistrationButton is not None
        assert selectVolumesButton.visible
        assert not finishRegistrationButton.visible
        assert not cancelRegistrationButton.visible

    def test_register_canceled_by_removing_moving_transformed_volume_node(self) -> None:
        load_project(TEST_PROJECT)

        fixedVolumeNode = slicer.util.getNode("Fixed")
        movingVolumeNode = slicer.util.getNode("Moving")
        self._setConfiguration(fixedVolumeNode, movingVolumeNode)

        movingTransformedVolumeNode = slicer.util.getNode("Moving - Transformed")
        slicer.mrmlScene.RemoveNode(movingTransformedVolumeNode)
        process_events()

        selectVolumesButton = self.find_widget("Select Volumes Button")
        finishRegistrationButton = self.find_widget("Finish Registration Button")
        cancelRegistrationButton = self.find_widget("Cancel Registration Button")

        assert selectVolumesButton is not None
        assert finishRegistrationButton is not None
        assert cancelRegistrationButton is not None
        assert selectVolumesButton.visible
        assert not finishRegistrationButton.visible
        assert not cancelRegistrationButton.visible

    def test_registering_markup_cursor(self) -> None:
        load_project(TEST_PROJECT)

        fixedVolumeNode = slicer.util.getNode("Fixed")
        movingVolumeNode = slicer.util.getNode("Moving")
        self._setConfiguration(fixedVolumeNode, movingVolumeNode)

        addLandmarkButton = self.find_widget("Landmark Add Button")
        assert addLandmarkButton is not None
        assert addLandmarkButton.visible

        addLandmarkButton.click()
        process_events()

        # Force markup interactor to process and create markup node
        layoutManager = slicer.app.layoutManager()
        sliceWidget = layoutManager.sliceWidget("Fixed")
        sliceView = sliceWidget.sliceView()
        interactor = sliceView.interactorStyle().GetInteractor()
        interactor.MouseMoveEvent()

        wait(0.5)
        markupsNode = helpers.tryGetNode("F")
        assert markupsNode is not None, f"Available nodes: {slicer.util.getNodes().keys()}"

        markupsDisplayNode = markupsNode.GetDisplayNode()
        assert markupsDisplayNode.GetGlyphTypeAsString() == "StarBurst2D"

        cancelRegistrationButton = self.find_widget("Cancel Registration Button")
        cancelRegistrationButton.click()

    def _setConfiguration(
        self, fixedVolumeNode: slicer.vtkMRMLScalarVolumeNode, movingVolumeNode: slicer.vtkMRMLScalarVolumeNode
    ) -> None:
        selectVolumesButton = self.find_widget("Select Volumes Button")
        selectVolumesButton.click()
        process_events()

        self._handleInnerDialog(fixedVolumeNode=fixedVolumeNode, movingVolumeNode=movingVolumeNode)
        wait(1)

        movingtransformNode = helpers.tryGetNode("Moving - Transformed")
        transformNode = helpers.tryGetNode("Transform")

        assert movingtransformNode is not None
        assert transformNode is not None

        finishRegistrationButton = self.find_widget("Finish Registration Button")
        cancelRegistrationButton = self.find_widget("Cancel Registration Button")

        assert finishRegistrationButton is not None
        assert cancelRegistrationButton is not None
        assert finishRegistrationButton.visible and cancelRegistrationButton.visible
        assert not selectVolumesButton.visible

    def _handleInnerDialog(
        self,
        fixedVolumeNode: slicer.vtkMRMLScalarVolumeNode,
        movingVolumeNode: slicer.vtkMRMLScalarVolumeNode,
        apply=True,
    ) -> None:
        """Handle dialog interface configuration

        Args:
            fixedVolumeNode (slicer.vtkMRMLScalarVolumeNode): Node to use as fixed image.
            movingVolumeNode (slicer.vtkMRMLScalarVolumeNode): Node to use as moving image.
            apply (bool, optional): If True, apply button will be clicked, otherwise the cancel button will be clicked. Defaults to True.
        """
        volumeSelectDialog = self.find_widget("Thin Section Registration Volume Select")
        assert volumeSelectDialog is not None

        applyDialogButton = self.find_widget("Volume Dialog Apply", obj=volumeSelectDialog)
        cancelDialogButton = self.find_widget("Volume Dialog Cancel", obj=volumeSelectDialog)
        fixedImageComboBox = self.find_widget("Fixed Volume Node Combo Box", obj=volumeSelectDialog)
        movingImageComboBox = self.find_widget("Moving Volume Node Combo Box", obj=volumeSelectDialog)

        assert applyDialogButton is not None
        assert cancelDialogButton is not None
        assert fixedImageComboBox is not None
        assert movingImageComboBox is not None

        self._setNodeComboBoxNode(fixedImageComboBox, fixedVolumeNode)
        self._setNodeComboBoxNode(movingImageComboBox, movingVolumeNode)

        process_events()

        if apply:
            applyDialogButton.click()
        else:
            cancelDialogButton.click()

    def _setNodeComboBoxNode(self, comboBox: slicer.qMRMLNodeComboBox, node: slicer.vtkMRMLNode) -> None:
        """Wrapper for slicer node combo box selection set.
            The combobox from this module widget is not working correctly with 'setCurrentNode' and 'setCurrentNodeId', only with 'setCurrentNodeIndex'

        Args:
            comboBox (slicer.qMRMLNodeComboBox): The combo box widget.
            node (slicer.vtkMRMLNode): the node to be selected.
        """
        if node is None:
            comboBox.setCurrentNode(None)
            return

        for i in range(comboBox.nodeCount()):
            if comboBox.nodeFromIndex(i) != node:
                continue

            comboBox.setCurrentNodeIndex(i)
            break

    def test_node_observer_lifetime(self):
        """Checks the node observer handlers lifetime handling."""
        load_project(TEST_PROJECT)

        fixedVolumeNode = slicer.util.getNode("Fixed")
        movingVolumeNode = slicer.util.getNode("Moving")
        self._setConfiguration(fixedVolumeNode, movingVolumeNode)

        widget = self._module_widget
        observers = widget.landmarksWidget.observerTags
        assert len(observers) == 0, f"Expected a total of '0' observer. Actual: {len(observers)}"

        fiducialNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "TestFiducials")
        widget.landmarksWidget.addLandmark()
        wait(0.5)
        assert len(observers) == 4, f"Expected a total of '4' observer. Actual: {len(observers)}"

        widget.logic.addLandmark([fixedVolumeNode, movingVolumeNode])
        widget.landmarksWidget.updateLandmarkArray()
        wait(0.5)
        assert len(observers) == 12, f"Expected a total of '12' observer. Actual: {len(observers)}"

        for fiducialNode in slicer.util.getNodes("vtkMRMLMarkupsFiducialNode*").values():
            slicer.mrmlScene.RemoveNode(fiducialNode)

        wait(1)
        assert len(observers) == 0, f"Expected a total of '0' observer. Actual: {len(observers)}"
