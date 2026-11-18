import numpy as np
import slicer

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, process_events, wait, check_for_message_box
from commons.slicer import helpers
from pathlib import Path

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
VECTOR_VOLUME_PROJECT_FILE = TEST_RESOURCES_DIR / "VectorVolume" / "VectorVolume.mrml"


class ImageToolsTest(LTracePluginTest):
    def __get_widget(self, objectName: str):
        return self._LTracePluginTest__widgets[objectName]

    def test_brightness_contrast_undo_redo(self):
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Brightness/Contrast")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        assert self.__get_widget("Brightness Slider").visible
        assert self.__get_widget("Contrast Slider").visible
        assert self.__get_widget("Brightness Slider").value == 0.0
        assert self.__get_widget("Contrast Slider").value == 0.0

        arrayPhase0 = slicer.util.arrayFromVolume(currentWorkingNode).copy()

        # Phase 1: Change brightness and contrast
        self.__get_widget("Brightness Slider").setValue(33)
        self.__get_widget("Contrast Slider").setValue(-33)
        self.__get_widget("Apply").click()
        process_events()

        assert self.__get_widget("Undo").enabled is True
        assert self.__get_widget("Redo").enabled is False

        arrayPhase1 = slicer.util.arrayFromVolume(currentWorkingNode).copy()

        assert np.array_equal(arrayPhase0, arrayPhase1) is False

        # Phase 2: Change brightness and contrast
        self.__get_widget("Brightness Slider").setValue(33)
        self.__get_widget("Contrast Slider").setValue(66)
        self.__get_widget("Apply").click()
        process_events()

        assert self.__get_widget("Undo").enabled is True
        assert self.__get_widget("Redo").enabled is False

        arrayPhase2 = slicer.util.arrayFromVolume(currentWorkingNode).copy()

        assert np.array_equal(arrayPhase0, arrayPhase2) is False
        assert np.array_equal(arrayPhase1, arrayPhase2) is False

        # Phase 3: Undo all changes
        self.__get_widget("Undo").click()
        process_events()

        assert self.__get_widget("Undo").enabled is True
        assert self.__get_widget("Redo").enabled is True

        currentArray = slicer.util.arrayFromVolume(currentWorkingNode).copy()
        assert np.array_equal(arrayPhase1, currentArray) is True

        self.__get_widget("Undo").click()
        process_events()

        assert self.__get_widget("Undo").enabled is False
        assert self.__get_widget("Redo").enabled is True

        currentArray = slicer.util.arrayFromVolume(currentWorkingNode).copy()
        assert np.array_equal(arrayPhase0, currentArray) is True

        # Phase 4: Redo all changes
        self.__get_widget("Redo").click()
        process_events()

        assert self.__get_widget("Undo").enabled is True
        assert self.__get_widget("Redo").enabled is True

        currentArray = slicer.util.arrayFromVolume(currentWorkingNode).copy()
        assert np.array_equal(arrayPhase1, currentArray) is True

        self.__get_widget("Redo").click()
        process_events()

        assert self.__get_widget("Undo").enabled is True
        assert self.__get_widget("Redo").enabled is False

        currentArray = slicer.util.arrayFromVolume(currentWorkingNode).copy()
        assert np.array_equal(arrayPhase2, currentArray) is True
        assert helpers.isTemporaryNode(currentWorkingNode) is True

        # Save
        self.__get_widget("Save").click()
        process_events()

        assert self._module_widget.currentNode is None

        outputNodeArray = slicer.util.arrayFromVolume(currentWorkingNode).copy()
        assert np.array_equal(arrayPhase2, outputNodeArray) is True
        assert helpers.isTemporaryNode(currentWorkingNode) is False
        assert bool(currentWorkingNode.GetHideFromEditors()) is False

    def test_saturation(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Saturation")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        assert self.__get_widget("Saturation Slider").visible
        assert self.__get_widget("Saturation Slider").value == 0.0

        arrayPhase0 = slicer.util.arrayFromVolume(currentWorkingNode).copy()

        # Phase 1: Change saturation
        self.__get_widget("Saturation Slider").setValue(33)
        self.__get_widget("Apply").click()
        process_events()

        assert self.__get_widget("Undo").enabled is True
        assert self.__get_widget("Redo").enabled is False

        arrayPhase1 = slicer.util.arrayFromVolume(currentWorkingNode).copy()

        assert np.array_equal(arrayPhase0, arrayPhase1) is False

        # Phase 2: Change saturation
        self.__get_widget("Saturation Slider").setValue(-66)
        self.__get_widget("Apply").click()
        process_events()

        assert self.__get_widget("Undo").enabled is True
        assert self.__get_widget("Redo").enabled is False

        arrayPhase2 = slicer.util.arrayFromVolume(currentWorkingNode).copy()

        assert np.array_equal(arrayPhase0, arrayPhase2) is False
        assert np.array_equal(arrayPhase1, arrayPhase2) is False

        # Save
        self.__get_widget("Save").click()
        process_events()

        assert self._module_widget.currentNode is None
        assert bool(currentWorkingNode.GetHideFromEditors()) is False

    def test_histogram_equalization(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        # This tools apply changes as it is selected
        arrayPhase0 = slicer.util.arrayFromVolume(volumeNode).copy()

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Histogram Equalization")
        process_events()

        currentWorkingNode = self._module_widget.currentNode

        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        # Phase 1: Equalize
        self.__get_widget("Apply").click()
        process_events()

        assert self.__get_widget("Undo").enabled is True
        assert self.__get_widget("Redo").enabled is False

        arrayPhase1 = slicer.util.arrayFromVolume(currentWorkingNode).copy()

        assert np.array_equal(arrayPhase0, arrayPhase1) is False

        # Save
        self.__get_widget("Save").click()
        process_events()

        assert self._module_widget.currentNode is None
        assert bool(currentWorkingNode.GetHideFromEditors()) is False

    def test_shading_correction(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        # This tools apply changes as it is selected
        arrayPhase0 = slicer.util.arrayFromVolume(volumeNode).copy()

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        # Phase 1: Equalize
        self.__get_widget("Apply").click()
        process_events()

        assert self.__get_widget("Undo").enabled is True
        assert self.__get_widget("Redo").enabled is False

        arrayPhase1 = slicer.util.arrayFromVolume(currentWorkingNode).copy()

        assert np.array_equal(arrayPhase0, arrayPhase1) is False

        # Save
        self.__get_widget("Save").click()
        process_events()

        assert self._module_widget.currentNode is None
        assert bool(currentWorkingNode.GetHideFromEditors()) is False

    def test_cancel(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        # This tools apply changes as it is selected
        arrayPhase0 = slicer.util.arrayFromVolume(volumeNode).copy()

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True
        assert helpers.isTemporaryNode(currentWorkingNode) is True

        # Cancel
        assert self.__get_widget("Cancel").enabled is True
        self.__get_widget("Cancel").click()
        process_events()

        arrayPhase1 = slicer.util.arrayFromVolume(currentWorkingNode).copy()
        assert np.array_equal(arrayPhase0, arrayPhase1)
        assert helpers.isTemporaryNode(currentWorkingNode) is True

    def test_remove_working_node_while_using_tool(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        # Phase 1: Equalize
        self.__get_widget("Apply").click()
        process_events()

        # Force node removal
        slicer.mrmlScene.RemoveNode(currentWorkingNode)
        wait(1)

        assert self.__get_widget("Tool Combo Box").currentText == "Select a tool"
        assert self.__get_widget("Apply").enabled is False
        assert self.__get_widget("Cancel").enabled is False
        assert self.__get_widget("Undo").enabled is False
        assert self.__get_widget("Redo").enabled is False
        assert self.__get_widget("Save").enabled is False
        assert self.__get_widget("Reset").enabled is False
        assert self._module_widget.currentNode is None
        assert self.__get_widget("Image Combo Box").currentNode() is None

    def test_remove_reference_node_while_using_tool(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        # Phase 1: Equalize
        self.__get_widget("Apply").click()
        process_events()

        # Force node removal
        with check_for_message_box("Save the changes to the image before exiting?", buttonTextToClick="&No"):
            slicer.mrmlScene.RemoveNode(volumeNode)
            wait(1)

        assert self.__get_widget("Tool Combo Box").currentText == "Select a tool"
        assert self.__get_widget("Apply").enabled is False
        assert self.__get_widget("Cancel").enabled is False
        assert self.__get_widget("Undo").enabled is False
        assert self.__get_widget("Redo").enabled is False
        assert self.__get_widget("Save").enabled is False
        assert self.__get_widget("Reset").enabled is False
        assert self._module_widget.currentNode is None, f"current node: {self._module_widget.currentNode}"
        assert self.__get_widget("Image Combo Box").currentNode() is None

    def test_change_image_before_saving_and_save(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        # Phase 1: Equalize
        self.__get_widget("Apply").click()
        process_events()

        # Change image
        with check_for_message_box("Save the changes to the image before exiting?", buttonTextToClick="&Yes"):
            self.__get_widget("Image Combo Box").setCurrentNode(None)
            process_events()

        assert self.__get_widget("Tool Combo Box").currentText == "Select a tool"
        assert self._module_widget.currentNode is None
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is False
        assert helpers.isTemporaryNode(currentWorkingNode) is False

    def test_change_image_before_saving_and_not_save(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        # Phase 1: Equalize
        self.__get_widget("Apply").click()
        process_events()

        # Change image
        with check_for_message_box("Save the changes to the image before exiting?", buttonTextToClick="&No"):
            self.__get_widget("Image Combo Box").setCurrentNode(None)
            process_events()

        assert self.__get_widget("Tool Combo Box").currentText == "Select a tool"
        assert self._module_widget.currentNode is None
        assert helpers.tryGetNode(currentWorkingNode.GetID()) is None

    def test_change_image_before_saving_and_cancel(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        # Phase 1: Equalize
        self.__get_widget("Apply").click()
        process_events()

        # Change image
        with check_for_message_box("Save the changes to the image before exiting?", buttonTextToClick="Cancel"):
            self.__get_widget("Image Combo Box").setCurrentNode(None)
            process_events()

        assert self.__get_widget("Image Combo Box").currentNode() is volumeNode, "current node: " + str(
            self.__get_widget("Image Combo Box").currentNode()
        )
        assert self._module_widget.currentNode is currentWorkingNode
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

    def test_change_image_before_applying_and_not_exiting(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        # Change image
        with check_for_message_box(
            "The current tool changes to the image were not applied and will be lost. Are you sure you want to exit the current tool?",
            buttonTextToClick="&No",
        ):
            self.__get_widget("Image Combo Box").setCurrentNode(None)
            process_events()

        assert self.__get_widget("Image Combo Box").currentNode() is volumeNode
        assert self._module_widget.currentNode is currentWorkingNode
        assert helpers.isTemporaryNode(currentWorkingNode) is True
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

    def test_change_image_before_applying_and_exiting(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        # Change image
        with check_for_message_box(
            "The current tool changes to the image were not applied and will be lost. Are you sure you want to exit the current tool?",
            buttonTextToClick="&Yes",
        ):
            self.__get_widget("Image Combo Box").setCurrentNode(None)
            process_events()

        assert self.__get_widget("Image Combo Box").currentNode() is None
        assert self._module_widget.currentNode is None

    def test_exit_module_before_saving_and_not_save(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        # Phase 1: Equalize
        self.__get_widget("Apply").click()
        process_events()

        with check_for_message_box("Save the changes to the image before exiting?", buttonTextToClick="&No"):
            self._module_widget.exit()
            process_events()

        assert self.__get_widget("Image Combo Box").currentNode() is None
        assert self.__get_widget("Tool Combo Box").currentText == "Select a tool"
        assert self.__get_widget("Apply").enabled is False
        assert self.__get_widget("Cancel").enabled is False
        assert self.__get_widget("Undo").enabled is False
        assert self.__get_widget("Redo").enabled is False
        assert self.__get_widget("Save").enabled is False
        assert self.__get_widget("Reset").enabled is False
        assert self._module_widget.currentNode is None
        assert helpers.isTemporaryNode(currentWorkingNode) is True
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

    def test_exit_module_before_saving_and_save(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        # Phase 1: Equalize
        self.__get_widget("Apply").click()
        process_events()

        with check_for_message_box("Save the changes to the image before exiting?", buttonTextToClick="&Yes"):
            self._module_widget.exit()
            process_events()

        assert self.__get_widget("Image Combo Box").currentNode() is None
        assert self.__get_widget("Tool Combo Box").currentText == "Select a tool"
        assert self.__get_widget("Apply").enabled is False
        assert self.__get_widget("Cancel").enabled is False
        assert self.__get_widget("Undo").enabled is False
        assert self.__get_widget("Redo").enabled is False
        assert self.__get_widget("Save").enabled is False
        assert self.__get_widget("Reset").enabled is False
        assert self._module_widget.currentNode is None
        assert helpers.isTemporaryNode(currentWorkingNode) is False
        assert bool(currentWorkingNode.GetHideFromEditors()) is False

    def test_exit_module_without_apply_not_save(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        with check_for_message_box(
            "The current changes in the image were not applied and will be lost. Do you want to save the changes?",
            buttonTextToClick="&No",
        ):
            self._module_widget.exit()
            process_events()

        assert self.__get_widget("Image Combo Box").currentNode() is None
        assert self.__get_widget("Tool Combo Box").currentText == "Select a tool"
        assert self.__get_widget("Apply").enabled is False
        assert self.__get_widget("Cancel").enabled is False
        assert self.__get_widget("Undo").enabled is False
        assert self.__get_widget("Redo").enabled is False
        assert self.__get_widget("Save").enabled is False
        assert self.__get_widget("Reset").enabled is False
        assert self._module_widget.currentNode is None
        assert helpers.isTemporaryNode(currentWorkingNode) is True
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

    def test_exit_module_without_applying_and_save(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True

        with check_for_message_box(
            "The current changes in the image were not applied and will be lost. Do you want to save the changes?",
            buttonTextToClick="&Yes",
        ):
            self._module_widget.exit()
            process_events()

        assert self.__get_widget("Image Combo Box").currentNode() is None
        assert self.__get_widget("Tool Combo Box").currentText == "Select a tool"
        assert self.__get_widget("Apply").enabled is False
        assert self.__get_widget("Cancel").enabled is False
        assert self.__get_widget("Undo").enabled is False
        assert self.__get_widget("Redo").enabled is False
        assert self.__get_widget("Save").enabled is False
        assert self.__get_widget("Reset").enabled is False
        assert self._module_widget.currentNode is None
        assert helpers.isTemporaryNode(currentWorkingNode) is False
        assert bool(currentWorkingNode.GetHideFromEditors()) is False

    def test_reset(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        # This tools apply changes as it is selected
        arrayPhase0 = slicer.util.arrayFromVolume(volumeNode).copy()

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        currentWorkingNode = self._module_widget.currentNode
        assert currentWorkingNode is not None
        assert bool(currentWorkingNode.GetHideFromEditors()) is True
        assert helpers.isTemporaryNode(currentWorkingNode) is True

        assert self.__get_widget("Apply").enabled is True
        self.__get_widget("Apply").click()
        process_events()

        arrayPhase1 = slicer.util.arrayFromVolume(currentWorkingNode).copy()

        # Reset
        assert self.__get_widget("Reset").enabled is True
        self.__get_widget("Reset").click()
        process_events()

        arrayPhase2 = slicer.util.arrayFromVolume(currentWorkingNode).copy()
        assert np.array_equal(arrayPhase0, arrayPhase2) is True
        assert np.array_equal(arrayPhase1, arrayPhase2) is False
        assert helpers.isTemporaryNode(currentWorkingNode) is True
        assert self.__get_widget("Apply").enabled is False
        assert self.__get_widget("Cancel").enabled is False
        assert self.__get_widget("Undo").enabled is False
        assert self.__get_widget("Redo").enabled is False
        assert self.__get_widget("Save").enabled is False
        assert self.__get_widget("Reset").enabled is False

    def test_observers_being_cleared_after_reset(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        process_events()

        assert self._module_widget.currentNode is not None
        assert self._module_widget._ImageToolsWidget__currentNodeObserver is not None
        assert self._module_widget._ImageToolsWidget__referenceNodeObserver is not None

        # Deselect the image. '_resetNodeObserver' disconnects/deleteLater's the node
        # observers here, but if the bug is present, the references to
        # them are never cleared.
        self.__get_widget("Image Combo Box").setCurrentNode(None)
        process_events()

        assert self._module_widget.currentNode is None
        assert self._module_widget._ImageToolsWidget__currentNodeObserver is None, (
            "The node observer reference was not cleared after being reset"
        )
        assert self._module_widget._ImageToolsWidget__referenceNodeObserver is None, (
            "The reference node observer reference was not cleared after being reset"
        )

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        process_events()

        assert self.__get_widget("Tool Combo Box").visible
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        assert self.__get_widget("Apply").enabled

    def test_observers_being_cleared_after_exit(self) -> None:
        load_project(VECTOR_VOLUME_PROJECT_FILE)

        volumeNode = slicer.util.getNode("A_PP")
        assert volumeNode is not None

        self.__get_widget("Image Combo Box").setCurrentNode(volumeNode)
        process_events()
        self.__get_widget("Tool Combo Box").setCurrentText("Shading Correction")
        process_events()

        assert self._module_widget._ImageToolsWidget__currentNodeObserver is not None
        assert self._module_widget._ImageToolsWidget__referenceNodeObserver is not None

        # Exit without applying the pending change, so it calls 'clearWorkingNode' on its own.
        with check_for_message_box(
            "The current changes in the image were not applied and will be lost. Do you want to save the changes?",
            buttonTextToClick="&No",
        ):
            self._module_widget.exit()
            process_events()

        assert self._module_widget._ImageToolsWidget__currentNodeObserver is None, (
            "The node observer reference was not cleared by 'exit' after being reset"
        )
        assert self._module_widget._ImageToolsWidget__referenceNodeObserver is None, (
            "The reference node observer reference was not cleared by 'exit' after being reset"
        )
