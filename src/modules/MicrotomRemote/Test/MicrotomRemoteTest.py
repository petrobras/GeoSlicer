from pathlib import Path

import slicer

import numpy as np

from commons.slicer.helpers import tryGetNode
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import (
    load_project,
    wait,
    process_events,
    wait_cli_to_finish,
    check_for_message_box,
    close_project,
)

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
PROJECT_FILE = TEST_RESOURCES_DIR / "SAMPLE" / "SAMPLE.mrml"
CONNECTIVITY_PROJECT_FILE = TEST_RESOURCES_DIR / "CONNECTIVITY" / "CONNECTIVITY.mrml"


class MicrotomRemoteTest(LTracePluginTest):
    def post_setup(self) -> None:
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = dict()
        self._populate_widgets()

    def tear_down(self) -> None:
        pass

    def _populate_widgets(self) -> None:
        """Initialize dictionary with module's interface widgets reference."""

        self._widgets = {
            "dimensionLabelPx": self.find_widget("Dimensions Label (px)"),
            "dimensionLabelMm": self.find_widget("Dimensions Label (mm)"),
            "segmentationInput": self.find_widget("Segmentation ComboBox"),
            "soiInput": self.find_widget("SOI ComboBox"),
            "referenceInput": self.find_widget("Image Segments ComboBox"),
            "segmentList": self.find_widget("Segment List"),
            "applyButton": self.find_widget("Apply PushButton"),
            "cancelButton": self.find_widget("CancelButton"),
            "SingleShotInputWidget": self.find_widget("SingleShotInputWidget"),
            "SimulationComboBox": self.find_widget("SimulationComboBox"),
            "SingleShotRadioButton": self.find_widget("Single Shot Mode Radio Button"),
        }

        for key, widget in self._widgets.items():
            assert widget is not None, f"Missing widget: {key}"

    def test_dimensions_label_doesnt_appear_without_input_image(self) -> None:
        assert not self._widgets["dimensionLabelPx"].isVisible()
        assert not self._widgets["dimensionLabelMm"].isVisible()

    def test_dimensions_label_appears_when_input_image_is_selected(self) -> None:
        load_project(PROJECT_FILE)

        # widgets
        segmentationInput = self._widgets["segmentationInput"]
        soiInput = self._widgets["soiInput"]
        referenceInput = self._widgets["referenceInput"]
        dimensionsLabelPx = self._widgets["dimensionLabelPx"]
        dimensionsLabelMm = self._widgets["dimensionLabelMm"]
        simulationComboBox = self._widgets["SimulationComboBox"]
        simulationComboBox.setCurrentText("Pore Size Distribution")
        process_events()

        # project nodes
        segmentationInputNode = tryGetNode("Segmentation")
        referenceInputNode = tryGetNode("Image")

        assert segmentationInputNode is not None, "Segmentation node not found"
        assert referenceInputNode is not None, "Reference node not found"

        segmentationInput.setCurrentNode(segmentationInputNode)

        assert segmentationInput.currentNode() is segmentationInputNode, (
            f"Expected '{segmentationInputNode.GetName()}' but got '{segmentationInput.currentNode()}'"
        )

        # wait for the UI to update
        wait(0.1)
        assert soiInput.currentNode() is None, f"Expected 'None' but got '{soiInput.currentNode()}'"
        assert referenceInput.currentNode() is referenceInputNode, (
            f"Expected '{referenceInputNode.GetName()}' but got '{referenceInput.currentNode()}'"
        )

        assert dimensionsLabelPx.isVisible()
        assert dimensionsLabelPx.text == "200 x 200 x 200", (
            f"Expected '200 x 200 x 200' but got '{dimensionsLabelPx.text}'"
        )

        assert dimensionsLabelMm.isVisible()
        assert dimensionsLabelMm.text == "2.0 x 2.0 x 2.0", (
            f"Expected '2.0 x 2.0 x 2.0' but got '{dimensionsLabelMm.text}'"
        )

    def test_run_sequence_input(self) -> None:
        simulation = "Pore Size Distribution"
        simulationComboBox = self._widgets["SimulationComboBox"]
        simulationComboBox.setCurrentText(simulation)
        self.assertTrue(simulationComboBox.currentText, simulation)

        segmentationInput = self._widgets["segmentationInput"]
        segmentList = self._widgets["segmentList"]
        applyButton = self._widgets["applyButton"]

        n = 2

        SequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "sequence example")

        for i in range(n):
            labelmapArray = np.random.randint(3, size=(16, 16, 16))
            labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", f"labelmap_{i}")
            labelmapNode.CreateDefaultDisplayNodes()
            slicer.util.updateVolumeFromArray(labelmapNode, labelmapArray.astype(np.int32))
            SequenceNode.SetDataNodeAtValue(labelmapNode, str(i))

        browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "browser example")
        browserNode.SetAndObserveMasterSequenceNodeID(SequenceNode.GetID())

        proxyNode = browserNode.GetProxyNode(SequenceNode)
        proxyNode.SetName("test_proxy")

        segmentationInput.setCurrentNode(proxyNode)

        wait(3)

        segmentList.item(1).setCheckState(2)

        assert applyButton.enabled is True, "Apply button should be enabled"
        cliNode = self._module_widget.logic.cliNode
        assert cliNode is None
        applyButton.clicked()

        process_events()
        cliNode = self._module_widget.logic.cliNode
        assert cliNode is not None

        wait_cli_to_finish(cliNode)

        assert cliNode.GetStatusString() == "Completed", (
            f"Expected CLI to finish status as 'Completed' but got '{cliNode.GetStatusString()}'. Error: {cliNode.GetErrorText()}"
        )

        process_events()
        outputProxy = tryGetNode("test_proxy_PSD_Output_Proxy")
        assert outputProxy is not None
        outputSequence = tryGetNode("test_proxy_PSD_Output_Sequence")
        assert outputSequence is not None
        assert outputSequence.GetNumberOfDataNodes() == n

        dataProxy = tryGetNode("test_proxy_PSD_Output_Proxy")
        assert dataProxy is not None
        dataSequence = tryGetNode("test_proxy_PSD_Output_Sequence")
        assert dataSequence is not None
        assert dataSequence.GetNumberOfDataNodes() == n

        runTimeProxy = tryGetNode("test_proxy_PSD_Output_Proxy")
        assert runTimeProxy is not None
        runTimeSequence = tryGetNode("test_proxy_PSD_Output_Sequence")
        assert runTimeSequence is not None
        assert runTimeSequence.GetNumberOfDataNodes() == n

        browserNode = tryGetNode("test_proxy_PSD_Output_Browser")
        assert browserNode is not None
        assert browserNode.GetNumberOfItems() == n
        assert browserNode.GetNumberOfSynchronizedSequenceNodes(True) == 3, (
            f"Expected 3 nodes but got {browserNode.GetNumberOfSynchronizedSequenceNodes(True)}"
        )

    def test_run_local_simulations(self) -> None:
        simOptions = [
            "Pore Size Distribution",
            "Hierarquical Pore Size Distribution",
            "Mercury Injection Capillary Pressure",
            "Incompressible Drainage Capillary Pressure",
            "Imbibition Capillary Pressure",
            "Incompressible Imbibition Capillary Pressure",
        ]

        for option in simOptions:
            self._run_process(PROJECT_FILE, "Segmentation", "Image", None, option)
            process_events()
            close_project()

    def test_apply_must_be_enabled_when_all_inputs_are_set(self) -> None:
        load_project(PROJECT_FILE)

        # widgets
        segmentationInput = self._widgets["segmentationInput"]
        soiInput = self._widgets["soiInput"]
        referenceInput = self._widgets["referenceInput"]
        segmentList = self._widgets["segmentList"]
        applyButton = self._widgets["applyButton"]
        simulationComboBox = self._widgets["SimulationComboBox"]

        simulationComboBox.setCurrentText("Pore Size Distribution")

        self._widgets["SingleShotRadioButton"].setChecked(True)

        # project nodes
        segmentationInputNode = tryGetNode("Segmentation")
        referenceInputNode = tryGetNode("Image")

        assert segmentationInputNode is not None, "Segmentation node not found"
        assert referenceInputNode is not None, "Reference node not found"

        assert not applyButton.enabled, "Apply button should be disabled"

        segmentationInput.setCurrentNode(segmentationInputNode)

        assert segmentationInput.currentNode() is segmentationInputNode, (
            f"Expected '{segmentationInputNode.GetName()}' but got '{segmentationInput.currentNode()}'"
        )

        # wait for the UI to update
        wait(0.1)
        assert soiInput.currentNode() is None, f"Expected 'None' but got '{soiInput.currentNode()}'"
        assert referenceInput.currentNode() is referenceInputNode, (
            f"Expected '{referenceInputNode.GetName()}' but got '{referenceInput.currentNode()}'"
        )

        segmentList.item(0).setCheckState(2)
        assert applyButton.enabled, "Apply button should be enabled"

    def test_apply_must_be_enabled_after_close_popup_informing_no_segment_selected(self) -> None:
        load_project(PROJECT_FILE)

        # widgets
        segmentationInput = self._widgets["segmentationInput"]
        soiInput = self._widgets["soiInput"]
        referenceInput = self._widgets["referenceInput"]
        applyButton = self._widgets["applyButton"]
        simulationComboBox = self._widgets["SimulationComboBox"]

        self._widgets["SingleShotRadioButton"].setChecked(True)

        simulationComboBox.setCurrentText("Pore Size Distribution")

        # project nodes
        segmentationInputNode = tryGetNode("Segmentation")
        referenceInputNode = tryGetNode("Image")

        assert segmentationInputNode is not None, "Segmentation node not found"
        assert referenceInputNode is not None, "Reference node not found"

        assert not applyButton.enabled, "Apply button should be disabled"

        segmentationInput.setCurrentNode(segmentationInputNode)
        assert segmentationInput.currentNode() is segmentationInputNode, (
            f"Expected '{segmentationInputNode.GetName()}' but got '{segmentationInput.currentNode()}'"
        )

        # wait for the UI to update
        wait(0.1)
        assert soiInput.currentNode() is None, f"Expected 'None' but got '{soiInput.currentNode()}'"
        assert referenceInput.currentNode() is referenceInputNode, (
            f"Expected '{referenceInputNode.GetName()}' but got '{referenceInput.currentNode()}'"
        )

        assert applyButton.enabled, "Apply button should be enabled"

        with check_for_message_box(
            "Please, select at least one segment by checking the segment box on the segment list. "
            "The selected segment will be considered as the pore space.",
            timeout_sec=2,
        ):
            applyButton.clicked()
            process_events()

        assert applyButton.enabled, "Apply button should be enabled"

    def test_apply_must_be_enabled_after_executing_segmentation(self) -> None:
        load_project(PROJECT_FILE)

        # widgets
        segmentationInput = self._widgets["segmentationInput"]
        soiInput = self._widgets["soiInput"]
        referenceInput = self._widgets["referenceInput"]
        segmentList = self._widgets["segmentList"]
        applyButton = self._widgets["applyButton"]
        simulationComboBox = self._widgets["SimulationComboBox"]

        self._widgets["SingleShotRadioButton"].setChecked(True)

        simulationComboBox.setCurrentText("Pore Size Distribution")
        # project nodes
        segmentationInputNode = tryGetNode("Segmentation")
        referenceInputNode = tryGetNode("Image")

        assert segmentationInputNode is not None, "Segmentation node not found"
        assert referenceInputNode is not None, "Reference node not found"

        segmentationInput.setCurrentNode(segmentationInputNode)
        assert segmentationInput.currentNode() is segmentationInputNode, (
            f"Expected '{segmentationInputNode.GetName()}' but got '{segmentationInput.currentNode()}'"
        )

        # wait for the UI to update
        wait(0.1)
        assert soiInput.currentNode() is None, f"Expected 'None' but got '{soiInput.currentNode()}'"
        assert referenceInput.currentNode() is referenceInputNode, (
            f"Expected '{referenceInputNode.GetName()}' but got '{referenceInput.currentNode()}'"
        )

        segmentList.item(0).setCheckState(2)

        assert applyButton.enabled, "Apply button should be enabled"

        applyButton.clicked()
        process_events()

        cliNode = self._module_widget.logic.cliNode
        assert cliNode is not None

        wait_cli_to_finish(cliNode)

        assert cliNode.GetStatusString() == "Completed", (
            f"Expected CLI to finish status as 'Completed' but got '{cliNode.GetStatusString()}'. Error: {cliNode.GetErrorText()}"
        )

        assert applyButton.enabled, "Apply button should be enabled"

    def _run_process(
        self,
        projectFilePath: Path,
        segmentationInputNodeName: str,
        referenceInputNodeName: str,
        soiInputNodeName: str,
        simulationOption: str,
    ) -> None:
        load_project(projectFilePath)

        # widgets
        segmentationInput = self._widgets["segmentationInput"]
        soiInput = self._widgets["soiInput"]
        referenceInput = self._widgets["referenceInput"]
        segmentList = self._widgets["segmentList"]
        applyButton = self._widgets["applyButton"]
        simulationComboBox = self._widgets["SimulationComboBox"]

        self._widgets["SingleShotRadioButton"].setChecked(True)

        # project nodes
        segmentationInputNode = tryGetNode(segmentationInputNodeName)
        referenceInputNode = tryGetNode(referenceInputNodeName)

        simulationComboBox.setCurrentText(simulationOption)
        segmentationInput.setCurrentNode(segmentationInputNode)
        soiInput.setCurrentNode(soiInputNodeName)

        process_events()

        assert segmentationInputNode is not None, "Segmentation node not found"
        assert referenceInputNode is not None, "Reference node not found"
        assert simulationComboBox.currentText == simulationOption, (
            f"Expected '{simulationOption}' but got '{simulationComboBox.currentText}'"
        )
        assert segmentationInput.currentNode() is segmentationInputNode, (
            f"Expected '{segmentationInputNode.GetName()}' but got '{segmentationInput.currentNode()}'"
        )

        assert soiInput.currentNode() is None, f"Expected 'None' but got '{soiInput.currentNode()}'"
        assert referenceInput.currentNode() is referenceInputNode, (
            f"Expected '{referenceInputNode.GetName()}' but got '{referenceInput.currentNode()}'"
        )

        segmentList.item(0).setCheckState(2)

        cliNode = self._module_widget.logic.cliNode
        assert cliNode is None
        assert applyButton.enabled is True, "Apply button should be enabled"
        applyButton.clicked()

        process_events()
        cliNode = self._module_widget.logic.cliNode
        assert cliNode is not None

        wait_cli_to_finish(cliNode)

        assert cliNode.GetStatusString() == "Completed", (
            f"Expected CLI to finish status as 'Completed' but got '{cliNode.GetStatusString()}'. Error: {cliNode.GetErrorText()}"
        )

    def test_error_on_unconnected(self) -> None:
        load_project(CONNECTIVITY_PROJECT_FILE)

        for method in (
            "Absolute Permeability",
            "Absolute Permeability - Representative Elementary Volume",
            "Relative Permeability",
        ):
            self._widgets["SimulationComboBox"].currentText = method
            self._widgets["segmentationInput"].setCurrentNode(tryGetNode("Unconnected"))
            with check_for_message_box(
                "Cannot run simulation: pore space is not connected.\n"
                "Make sure the selected segments connect the opposite faces over the 'z' axis."
            ):
                self._widgets["applyButton"].click()
                process_events()

    def test_cancel_button_behavior(self):
        load_project(PROJECT_FILE)

        cancelButton = self._widgets["cancelButton"]
        self.assertTrue(cancelButton.isVisible())
        self.assertFalse(cancelButton.isEnabled())

        simulationComboBox = self._widgets["SimulationComboBox"]
        simulationComboBox.setCurrentText("Pore Size Distribution")

        segmentationInputNode = tryGetNode("Segmentation")
        segmentationInput = self._widgets["segmentationInput"]
        segmentationInput.setCurrentNode(segmentationInputNode)

        segmentList = self._widgets["segmentList"]
        segmentList.item(0).setCheckState(2)

        applyButton = self._widgets["applyButton"]
        self.assertTrue(applyButton.isEnabled())

        applyButton.clicked()
        process_events()

        self.assertTrue(cancelButton.isEnabled())

        cliNode = self._module_widget.logic.cliNode
        self.assertIsNotNone(cliNode)
        self.assertTrue(cliNode.IsBusy())

        cancelButton.clicked()
        process_events()

        wait_cli_to_finish(cliNode)
        self.assertEqual(cliNode.GetStatusString(), "Cancelled")
        self.assertFalse(cancelButton.isEnabled())
        self.assertTrue(applyButton.isEnabled())
