from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import (
    wait,
    wait_cli_to_finish,
    process_events,
    load_project,
    save_project,
    check_for_message_box,
)
from commons.slicer.helpers import tryGetNode
from commons.slicer import metadata

from typing import Union
from pathlib import Path
import numpy as np
import slicer


TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
SPIRAL_RAW_PROJECT_FILE = TEST_RESOURCES_DIR / "SPIRAL_RAW" / "SPIRAL_RAW.mrml"
SPIRAL_PROJECT_FILE = TEST_RESOURCES_DIR / "SPIRAL" / "SPIRAL.mrml"


class SpiralTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def post_setup(self) -> None:
        """Test case setup handler, applied before reloding the widgets"""
        self.__widgets = dict()

        # Input tab
        self.__widgets["imageInput"] = self.find_widget(name="Image Input")

        # Parameters tab
        self.__widgets["minimumWaveLengthInput"] = self.find_widget(name="Minimum Wave Length Input")
        self.__widgets["maximumWaveLengthInput"] = self.find_widget(name="Maximum Wave Length Input")
        self.__widgets["filteringFactorInput"] = self.find_widget(name="Filtering Factor Input")
        self.__widgets["bandSpectrumStepLengthInput"] = self.find_widget(name="Band Spectrum Step Length Input")

        # Output tab
        self.__widgets["outputPrefixInput"] = self.find_widget(name="Output Prefix Input")

        # Buttons
        self.__widgets["applyButton"] = self.find_widget(name="Apply Button")
        self.__widgets["cancelButton"] = self.find_widget(name="Cancel Button")

        for objectName, widget in self.__widgets.items():
            assert widget is not None, f"widget related to the objectName '{objectName}' is None!"

    def generate_template_project(self) -> None:
        # Load raw project with the necessary data to generate the templates
        load_project(project_file_path=SPIRAL_RAW_PROJECT_FILE)

        # Tests process to generated template data
        self.test_process_default_input(generateDataOnly=True)
        self.test_process_min_filtering_factor(generateDataOnly=True)
        self.test_process_change_filtering_factor(generateDataOnly=True)
        self.test_process_max_band_spectrum_step_length(generateDataOnly=True)
        self.test_process_min_band_spectrum_step_length(generateDataOnly=True)
        self.test_process_change_min_max_wavelength_1(generateDataOnly=True)
        self.test_process_change_min_max_wavelength_2(generateDataOnly=True)
        self.test_process_change_min_max_wavelength_3(generateDataOnly=True)

        assert save_project(project_path=SPIRAL_PROJECT_FILE), "Failed to save generated data to project."

    def test_process_default_input(self, generateDataOnly=False) -> None:
        self.__execute_sucessful_process(
            projectPath=SPIRAL_PROJECT_FILE,
            imageInput="UBI_TT [us]",
            outputPrefixInput="Spiral_default",
            generateDataOnly=generateDataOnly,
        )

    def test_process_min_filtering_factor(self, generateDataOnly=False) -> None:
        self.__execute_sucessful_process(
            projectPath=SPIRAL_PROJECT_FILE,
            imageInput="UBI_TT [us]",
            outputPrefixInput="Spiral_min_filtering_factor",
            generateDataOnly=generateDataOnly,
            filteringFactorInput=0.00,
        )

    def test_process_change_filtering_factor(self, generateDataOnly=False) -> None:
        self.__execute_sucessful_process(
            projectPath=SPIRAL_PROJECT_FILE,
            imageInput="UBI_TT [us]",
            outputPrefixInput="Spiral_change_filtering_factor",
            generateDataOnly=generateDataOnly,
            filteringFactorInput=0.50,
        )

    def test_process_max_band_spectrum_step_length(self, generateDataOnly=False) -> None:
        self.__execute_sucessful_process(
            projectPath=SPIRAL_PROJECT_FILE,
            imageInput="UBI_TT [us]",
            outputPrefixInput="Spiral_max_band_spectrum_step_length",
            generateDataOnly=generateDataOnly,
            bandSpectrumStepLengthInput=0.1,
        )

    def test_process_min_band_spectrum_step_length(self, generateDataOnly=False) -> None:
        self.__execute_sucessful_process(
            projectPath=SPIRAL_PROJECT_FILE,
            imageInput="UBI_TT [us]",
            outputPrefixInput="Spiral_min_band_spectrum_step_length",
            generateDataOnly=generateDataOnly,
            bandSpectrumStepLengthInput=0.001,
        )

    def test_process_change_min_max_wavelength_1(self, generateDataOnly=False) -> None:
        self.__execute_sucessful_process(
            projectPath=SPIRAL_PROJECT_FILE,
            imageInput="UBI_TT [us]",
            outputPrefixInput="Spiral_change_min_max_wavelength_1",
            generateDataOnly=generateDataOnly,
            minimumWaveLengthInput=1,
            maximumWaveLengthInput=2,
        )

    def test_process_change_min_max_wavelength_2(self, generateDataOnly=False) -> None:
        self.__execute_sucessful_process(
            projectPath=SPIRAL_PROJECT_FILE,
            imageInput="UBI_TT [us]",
            outputPrefixInput="Spiral_change_min_max_wavelength_2",
            generateDataOnly=generateDataOnly,
            minimumWaveLengthInput=99,
            maximumWaveLengthInput=100,
        )

    def test_process_change_min_max_wavelength_3(self, generateDataOnly=False) -> None:
        self.__execute_sucessful_process(
            projectPath=SPIRAL_PROJECT_FILE,
            imageInput="UBI_TT [us]",
            outputPrefixInput="Spiral_change_min_max_wavelength_3",
            generateDataOnly=generateDataOnly,
            minimumWaveLengthInput=100,
            maximumWaveLengthInput=500,
        )

    def test_interface_default_values_for_widgets(self) -> None:
        defaultMinimumWaveLengthInput = float(self._module_widget.getMinimumWavelength())
        defaultMaximumWaveLengthInput = float(self._module_widget.getMaximumWavelength())
        defaultFilteringFactor = float(self._module_widget.getMultiplicationFactor())
        defaultBandSpectrumStepLength = float(self._module_widget.getSmoothstepFactor())

        assert self.__widgets["imageInput"].currentNode() is None
        assert np.isclose(self.__widgets["minimumWaveLengthInput"].value, defaultMinimumWaveLengthInput), (
            f"Expected: {defaultMinimumWaveLengthInput} - Actual: {self.__widgets['minimumWaveLengthInput'].value}"
        )
        assert np.isclose(self.__widgets["maximumWaveLengthInput"].value, defaultMaximumWaveLengthInput), (
            f"Expected: {defaultMaximumWaveLengthInput} - Actual: {self.__widgets['maximumWaveLengthInput'].value}"
        )
        assert np.isclose(self.__widgets["filteringFactorInput"].value, defaultFilteringFactor), (
            f"Expected: {defaultFilteringFactor} - Actual: {self.__widgets['filteringFactorInput'].value}"
        )
        assert np.isclose(self.__widgets["bandSpectrumStepLengthInput"].value, defaultBandSpectrumStepLength), (
            f"Expected: {defaultBandSpectrumStepLength} - Actual: {self.__widgets['bandSpectrumStepLengthInput'].value}"
        )
        assert self.__widgets["outputPrefixInput"].text == "", (
            f"Expected: {''} - Actual: {self.__widgets['outputPrefixInput'].text}"
        )
        assert not self.__widgets["applyButton"].enabled, (
            f"Expected: {False} - Actual: {self.__widgets['applyButton'].enabled}"
        )
        assert not self.__widgets["cancelButton"].enabled, (
            f"Expected: {False} - Actual: {self.__widgets['cancelButton'].enabled}"
        )

    def test_interface_input_rules_for_apply_button_enablement(self) -> None:
        # Get widgets
        applyButton = self.__widgets["applyButton"]
        imageInput = self.__widgets["imageInput"]

        load_project(project_file_path=SPIRAL_PROJECT_FILE)

        # Get nodes
        imageNode = tryGetNode("UBI_TT [us]")
        assert imageNode is not None

        # Assert default apply button enablement state
        assert not applyButton.enabled

        # Update image input to a valid node
        imageInput.setCurrentNode(imageNode)

        # Assert apply button enablement state
        assert applyButton.enabled

    def test_interface_output_prefix_update_rules(self) -> None:
        # Get widgets
        imageInput = self.__widgets["imageInput"]
        outputPrefixInput = self.__widgets["outputPrefixInput"]

        # Assert default value
        assert outputPrefixInput.text == ""

        load_project(project_file_path=SPIRAL_PROJECT_FILE)

        # Set input nodes
        imageNode = tryGetNode("UBI_TT [us]")
        assert imageNode is not None

        imageInput.setCurrentNode(imageNode)
        process_events()

        # Assert output prefix update when changing the amplitude node
        assert outputPrefixInput.text == f"{imageNode.GetName()}_Spiral", (
            f"Expected: {imageNode.GetName()}_Spiral - Actual: {outputPrefixInput.text}"
        )

        # Simulate erasing output prefix text to check if it updates to a valid text, with an valid amplitude node selected
        imageInput.setCurrentNode(imageNode)
        outputPrefixInput.setText("")
        process_events()
        assert outputPrefixInput.text == f"{imageNode.GetName()}_Spiral", (
            f"Expected: {imageNode.GetName()}_Spiral - Actual: {outputPrefixInput.text}"
        )

        # Simulate erasing output prefix text to check if it updates to a valid text, without an amplitude node selected
        imageInput.setCurrentNode(None)
        outputPrefixInput.setText("")
        process_events()
        assert outputPrefixInput.text == "Spiral", f"Expected: Spiral - Actual: {outputPrefixInput.text}"

    def test_interface_min_max_wavelength_input_rules(self) -> None:
        load_project(project_file_path=SPIRAL_PROJECT_FILE)
        imageNode = tryGetNode("UBI_TT [us]")

        # Input tab
        assert imageNode is not None
        self.__widgets["imageInput"].setCurrentNode(imageNode)

        # Get widgets
        applyButton = self.__widgets["applyButton"]
        minimumWaveLengthInput = self.__widgets["minimumWaveLengthInput"]
        maximumWaveLengthInput = self.__widgets["maximumWaveLengthInput"]

        assert applyButton.enabled

        # Test minimum and maximum values for each widget
        # Minimum wavelength widget
        minimumWaveLengthCurrentMinValue = minimumWaveLengthInput.minimum
        minimumWaveLengthInput.setValue(0)
        process_events()
        # Assert set value was not accepted due the current value being under the minimum value.
        assert minimumWaveLengthInput.value == minimumWaveLengthCurrentMinValue, (
            f"Expected: {minimumWaveLengthCurrentMinValue} - Actual {minimumWaveLengthInput.value}"
        )

        minimumWaveLengthCurrentMaxValue = minimumWaveLengthInput.maximum
        minimumWaveLengthInput.setValue(101)
        process_events()
        # Assert set value was not accepted due the current value being above the maximum value.
        assert minimumWaveLengthInput.value == minimumWaveLengthCurrentMaxValue, (
            f"Expected: {minimumWaveLengthCurrentMaxValue} - Actual {minimumWaveLengthInput.value}"
        )

        # Maximum wavelength widget
        maximumWaveLengthCurrentMinValue = maximumWaveLengthInput.minimum
        maximumWaveLengthInput.setValue(0)
        process_events()
        # Assert set value was not accepted due the current value being under the minimum value.
        assert maximumWaveLengthInput.value == maximumWaveLengthCurrentMinValue, (
            f"Expected: {maximumWaveLengthCurrentMinValue} - Actual {maximumWaveLengthInput.value}"
        )

        maximumWaveLengthCurrentMaxValue = maximumWaveLengthInput.maximum
        maximumWaveLengthInput.setValue(501)
        process_events()
        # Assert set value was not accepted due the current value being above the maximum value.
        assert maximumWaveLengthInput.value == maximumWaveLengthCurrentMaxValue, (
            f"Expected: {maximumWaveLengthCurrentMaxValue} - Actual {maximumWaveLengthInput.value}"
        )

        # Assert not being able to apply due the minimum wavelenght value be greater than the maximum wavelenght value
        minimumWaveLengthInput.setValue(50)
        maximumWaveLengthInput.setValue(10)

        with check_for_message_box("Maximum wavelength must be larger than minimum wavelength."):
            applyButton.clicked()

    def test_interface_filtering_factor_range_limit(self) -> None:
        # Get widget
        filteringFactor = self.__widgets["filteringFactorInput"]

        # Test minimum value
        defaultMinFactor = filteringFactor.minimum
        filteringFactor.setValue(-1)
        process_events()
        assert filteringFactor.value == defaultMinFactor, (
            f"Expected: {defaultMinFactor} - Actual {filteringFactor.value}"
        )

        # Test maximum value
        defaultMaxFactor = filteringFactor.maximum
        filteringFactor.setValue(1.1)
        process_events()
        assert filteringFactor.value == defaultMaxFactor, (
            f"Expected: {defaultMaxFactor} - Actual {filteringFactor.value}"
        )

    def test_interface_band_spectrum_step_length_range_limit(self) -> None:
        # Get widget
        bandSpectrumStepLengthInput = self.__widgets["bandSpectrumStepLengthInput"]

        # Test minimum value
        defaultMinLength = bandSpectrumStepLengthInput.minimum
        bandSpectrumStepLengthInput.setValue(0.000)
        process_events()
        assert bandSpectrumStepLengthInput.value == defaultMinLength, (
            f"Expected: {defaultMinLength} - Actual: {bandSpectrumStepLengthInput.value}"
        )

        # Test maximum value
        defaultMaxLength = bandSpectrumStepLengthInput.maximum
        bandSpectrumStepLengthInput.setValue(0.11)
        process_events()
        assert bandSpectrumStepLengthInput.value == defaultMaxLength, (
            f"Expected: {defaultMaxLength} - Actual: {bandSpectrumStepLengthInput.value}"
        )

    def test_cancelling_process(self) -> None:
        load_project(project_file_path=SPIRAL_PROJECT_FILE)

        imageNode = tryGetNode("UBI_TT [us]")

        # Input tab
        assert imageNode is not None
        self.__widgets["imageInput"].setCurrentNode(imageNode)

        # Check buttons enablement state
        assert self.__widgets["applyButton"].enabled is True
        assert self.__widgets["cancelButton"].enabled is False
        assert self.widgets["Indicators Widget"].visible is False

        # Simulate apply button clicked
        self.__widgets["applyButton"].clicked()

        # Process Qt event queue
        wait(0.3)

        cliNode = self._module_widget.logic.cliNode
        assert cliNode is not None

        # Simulate apply button clicked
        with check_for_message_box(message="Filtering cancelled.", timeout_sec=5):
            self.__widgets["cancelButton"].clicked()
            wait_cli_to_finish(cli_entity=cliNode)

        # Check buttons enablement state
        assert self.__widgets["applyButton"].enabled
        assert not self.__widgets["cancelButton"].enabled
        assert self.widgets["Indicators Widget"].visible is False

        # Assert nodes
        outputNode = tryGetNode("UBI_TT [us]_Spiral_Output")
        assert outputNode is None

    def test_interface_indicator(self) -> None:
        assert self.widgets["Indicators Widget"].visible is False
        self.test_process_default_input()
        assert self.widgets["Indicators Widget"].visible is True

    def __execute_sucessful_process(
        self, projectPath: Union[str, Path], generateDataOnly=False, *args, **kwargs
    ) -> None:
        """Handle succesful interface interaction.

        Args:
            projectPath (Union[str, Path]): The template project path
            generateDataOnly (bool, optional): Save generated data in the project path instead of asserting values. Defaults to False.
        """
        if not generateDataOnly:
            load_project(project_file_path=projectPath)

        imageNodeName = kwargs.get("imageInput", None)
        imageNode = tryGetNode(imageNodeName)
        minimumWaveLength = kwargs.get("minimumWaveLengthInput", 4)
        maximumWaveLength = kwargs.get("maximumWaveLengthInput", 100)
        filteringFactor = kwargs.get("filteringFactorInput", 1.00)
        bandSpectrumStepLength = kwargs.get("bandSpectrumStepLengthInput", 0.020)
        outputPrefix = kwargs.get("outputPrefixInput", "")

        # Input tab
        assert imageNode is not None
        self.__widgets["imageInput"].setCurrentNode(imageNode)

        # Parameters tab
        self.__widgets["minimumWaveLengthInput"].setValue(minimumWaveLength)
        self.__widgets["maximumWaveLengthInput"].setValue(maximumWaveLength)
        self.__widgets["filteringFactorInput"].setValue(filteringFactor)
        self.__widgets["bandSpectrumStepLengthInput"].setValue(bandSpectrumStepLength)

        # Output tab
        suffix = "_Template" if generateDataOnly else ""
        self.__widgets["outputPrefixInput"].setText(f"{outputPrefix}{suffix}")

        # Check buttons enablement state
        assert self.__widgets["applyButton"].enabled is True
        assert self.__widgets["cancelButton"].enabled is False

        # Simulate apply button clicked
        self.__widgets["applyButton"].clicked()

        # Process Qt event queue
        process_events()

        cliNode = self._module_widget.logic.cliNode
        assert cliNode is not None

        wait(2)

        # Check buttons enablement state
        assert self.widgets["Indicators Widget"].visible is False
        assert not self.__widgets["applyButton"].enabled
        assert self.__widgets["cancelButton"].enabled

        wait_cli_to_finish(cli_entity=cliNode)

        if generateDataOnly:
            return

        # Wait for method calls run after the CLI process finished
        wait(1)

        # Check buttons enablement state
        assert self.__widgets["applyButton"].enabled
        assert not self.__widgets["cancelButton"].enabled
        assert self.widgets["Indicators Widget"].visible is True

        # Assert nodes
        outputNode = tryGetNode(f"{outputPrefix}_Output")
        outputTemplateNode = tryGetNode(f"{outputPrefix}_Template_Output")
        assert outputNode is not None
        assert outputTemplateNode is not None

        # assert array
        outputNodeArray = slicer.util.arrayFromVolume(outputNode)
        outputTemplateNodeArray = slicer.util.arrayFromVolume(outputTemplateNode)
        assert np.allclose(outputNodeArray, outputTemplateNodeArray)

        # Assert metadata is propagated

        assert metadata.get_node_metadata(outputNode) == metadata.get_node_metadata(imageNode)

        # TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        input_itemID = subjectHierarchyNode.GetItemByDataNode(imageNode)  # the hierarchy item ID corresponding to node
        output_itemID = subjectHierarchyNode.GetItemByDataNode(outputNode)
        assert subjectHierarchyNode.GetItemAttributeNames(input_itemID) == subjectHierarchyNode.GetItemAttributeNames(
            output_itemID
        )

        assert imageNode.GetNumberOfNodeReferences("referenceImageGeometryRef") == outputNode.GetNumberOfNodeReferences(
            "referenceImageGeometryRef"
        )
        assert imageNode.GetNumberOfNodeReferences("referenceVolume") == outputNode.GetNumberOfNodeReferences(
            "referenceVolume"
        )
