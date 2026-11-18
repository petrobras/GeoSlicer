import slicer
import qt
import os
import json


from pathlib import Path
from commons.constants import PSDLib
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.helpers import tryGetNode
from collections import namedtuple
from commons.slicer.tests.utils import (
    load_project,
    wait,
    process_events,
    wait_cli_to_finish,
    check_for_message_box,
    close_project,
)
from commons.slicer.tests.mocks.mock_qt_widgets import mockFileDialog

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
PROJECT_FILE = TEST_RESOURCES_DIR / "PSD" / "PSD.mrml"
PRESETS_PATH = Path(slicer.app.temporaryPath).absolute() / "ImageLogPSDGenerationTestPresets.json"
EXPORT_PRESETS_PATH = Path(slicer.app.temporaryPath).absolute() / "ImageLogPSDGenerationExportTestPresets.json"
IMPORT_PRESETS_PATH = TEST_RESOURCES_DIR / "ImageLogPSDGenerationPresets.json"

PSDParameter = namedtuple("PSDParameter", ["label", "field", "defaultValue", "newValue", "getPresetValue", "required"])


class Opt:
    DEFAULT = "DEFAULT"
    NEW = "NEW"
    EMPTY = "EMPTY"
    PRESET = "PRESET"


class ImageLogPSDGenerationTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        if os.path.isfile(PRESETS_PATH):
            os.remove(PRESETS_PATH)

        if os.path.isfile(EXPORT_PRESETS_PATH):
            os.remove(EXPORT_PRESETS_PATH)

        self._module_widget.presetsFilePath = PRESETS_PATH
        self._module_widget.presets = self._module_widget.logic.getPresets(PRESETS_PATH)
        self._module_widget.presetWidget.loadData(self._module_widget.presets.values())
        self._module_widget.exportPresetsPath = EXPORT_PRESETS_PATH
        self._module_widget.importPresetsPath = IMPORT_PRESETS_PATH

        self._widgets = {
            "psdLibComboBox": self.find_widget("PSD Lib Combo Box"),
            "segmentationInput": self.find_widget("Segmentation ComboBox"),
            "soiInput": self.find_widget("SOI ComboBox"),
            "referenceInput": self.find_widget("Image Segments ComboBox"),
            "segmentList": self.find_widget("Segment List"),
            "dimensionLabelPx": self.find_widget("Dimensions Label (px)"),
            "dimensionLabelMm": self.find_widget("Dimensions Label (mm)"),
            "presetComboBox": self.find_widget("Preset Combo Box"),
            "presetDialog": self.find_widget("Preset Dialog"),
            "messageDialog": self.find_widget("Message Dialog"),
            "exportImportDialog": self.find_widget("Export Import Dialog"),
            "presetCreateBtn": self.find_widget("Create Preset Button"),
            "presetRenameBtn": self.find_widget("Rename Preset Button"),
            "presetSaveBtn": self.find_widget("Save Preset Button"),
            "presetDeleteBtn": self.find_widget("Delete Preset Button"),
            "exportPresetsBtn": self.find_widget("Export Preset Button"),
            "importPresetsBtn": self.find_widget("Import Preset Button"),
            "microtomSatRes": self.find_widget("Microtom Saturation Resolution"),
            "microtomRadRes": self.find_widget("Microrom Radius Resolution"),
            "porespySizes": self.find_widget("Porespy Sizes"),
            "porespySmooth": self.find_widget("Porespy Smooth"),
            "porespyMethod": self.find_widget("Porespy Method"),
            "resetPresetBtn": self.find_widget("Reset Parameters Preset"),
            "resetDefaultBtn": self.find_widget("Reset Parameters Default"),
            "outputPrefix": self.find_widget("Output Prefix Line Edit"),
            "manualOutputPrefixCkb": self.find_widget("Manual Output Prefix Check Box"),
            "applyBtn": self.find_widget("Apply Button"),
            "cancelBtn": self.find_widget("Cancel Button"),
        }

        # PSD libs parameters
        self._psdParametersFields = {
            PSDLib.MICROTOM: [
                PSDParameter(
                    self._module_widget.psdParameters[PSDLib.MICROTOM].satResLabel,
                    self._widgets["microtomSatRes"],
                    str(self._module_widget.psdParameters[PSDLib.MICROTOM].defaultSatRes),
                    "0.88",
                    lambda preset: preset.satResMicrotom,
                    True,
                ),
                PSDParameter(
                    self._module_widget.psdParameters[PSDLib.MICROTOM].radResLabel,
                    self._widgets["microtomRadRes"],
                    str(self._module_widget.psdParameters[PSDLib.MICROTOM].defaultRadRes),
                    "0.99",
                    lambda preset: preset.radResMicrotom,
                    True,
                ),
            ],
            PSDLib.PORESPY: [
                PSDParameter(
                    self._module_widget.psdParameters[PSDLib.PORESPY].sizesLabel,
                    self._widgets["porespySizes"],
                    self._module_widget.psdParameters[PSDLib.PORESPY]._toStrList(
                        self._module_widget.psdParameters[PSDLib.PORESPY].defaultSizes
                    ),
                    "1, 1",
                    lambda preset: preset.sizesPorespy,
                    False,
                ),
                PSDParameter(
                    self._module_widget.psdParameters[PSDLib.PORESPY].smoothLabel,
                    self._widgets["porespySmooth"],
                    self._module_widget.psdParameters[PSDLib.PORESPY].defaultSmooth,
                    False,
                    lambda preset: preset.smoothPorespy,
                    False,
                ),
                PSDParameter(
                    self._module_widget.psdParameters[PSDLib.PORESPY].methodLabel,
                    self._widgets["porespyMethod"],
                    self._module_widget.psdParameters[PSDLib.PORESPY].defaultMethod,
                    "bf",
                    lambda preset: preset.methodPorespy,
                    False,
                ),
            ],
        }

        for key, widget in self._widgets.items():
            assert widget is not None, f"Missing widget: {key}"

    def tear_down(self):
        if os.path.isfile(PRESETS_PATH):
            os.remove(PRESETS_PATH)

    # Utils
    def _get_inputs(self):
        segmentationInputNode = tryGetNode("Segmentation")
        soiInputNode = tryGetNode("Soi")
        referenceInputNode = tryGetNode("Imagelog")

        assert segmentationInputNode is not None, "Segmentation node not found"
        assert soiInputNode is not None, "Segment of Interest node not found"
        assert referenceInputNode is not None, "Reference node not found"

        return segmentationInputNode, soiInputNode, referenceInputNode

    def _msg_expected(self, expected, current):
        return f"Expected '{expected}' but got '{current}'"

    def _msg_cli(self, expected, cli):
        return (
            f"Expected CLI to finish status as '{expected}' but got '{cli.GetStatusString()}'. "
            f"Error: {cli.GetErrorText()}"
        )

    def _create_preset(self, presetName) -> None:
        presetCreateBtn = self._widgets["presetCreateBtn"]
        presetDialog = self._widgets["presetDialog"]

        def create_preset():
            assert presetDialog.windowTitle == "Create Preset"
            presetDialog.setOutputName(presetName)
            presetDialog.applyButtonClicked()

            # If the preset name is empty, a pop up will appear and the dialog will not be closed,
            # so we need to close it manually in the test
            if presetDialog.getOutputName().strip() == "":
                presetDialog.reject()

        qt.QTimer.singleShot(500, create_preset)
        presetCreateBtn.clicked()
        process_events()

    def _rename_preset(self, oldPresetName, newPresetName) -> None:
        presetRenameBtn = self._widgets["presetRenameBtn"]
        presetDialog = self._widgets["presetDialog"]

        def rename_preset():
            assert presetDialog.windowTitle == "Rename Preset"
            # When renaming a preset, the dialog should be pre-populated with the current preset name
            assert presetDialog.getOutputName() == oldPresetName, self._msg_expected(
                oldPresetName, presetDialog.getOutputName()
            )

            presetDialog.setOutputName(newPresetName)
            presetDialog.applyButtonClicked()

            # If the preset name is empty, a pop up will appear and the dialog will not be closed,
            # so we need to close it manually in the test
            if presetDialog.getOutputName().strip() == "":
                presetDialog.reject()

        qt.QTimer.singleShot(500, rename_preset)
        presetRenameBtn.clicked()
        process_events()

    def _change_parameters_to_value(self, psdLib, option=Opt.DEFAULT):
        for parameter in self._psdParametersFields[psdLib]:
            value = parameter.defaultValue

            if option == Opt.NEW:
                value = parameter.newValue
            if option == Opt.EMPTY:
                if isinstance(parameter.field, qt.QComboBox):
                    value = None
                elif isinstance(parameter.field, qt.QCheckBox):
                    value = False
                else:
                    value = ""

            if isinstance(parameter.field, qt.QComboBox):
                if parameter.field.findData(value) != -1:
                    parameter.field.setCurrentIndex(parameter.field.findData(value))
            elif isinstance(parameter.field, qt.QCheckBox):
                parameter.field.checked = value
            else:
                parameter.field.text = value

    def _assert_parameters(self, psdLib, option=Opt.DEFAULT):
        for parameter in self._psdParametersFields[psdLib]:
            value = parameter.defaultValue

            if option == Opt.NEW:
                value = parameter.newValue
            if option == Opt.EMPTY:
                if isinstance(parameter.field, qt.QComboBox):
                    value = None
                elif isinstance(parameter.field, qt.QCheckBox):
                    value = False
                else:
                    value = ""

            if isinstance(parameter.field, qt.QComboBox):
                if parameter.field.findData(value) != -1:
                    assert parameter.field.currentData == value
            elif isinstance(parameter.field, qt.QCheckBox):
                assert parameter.field.checked == value
            else:
                assert parameter.field.text == value

    def _assert_presets(self, psdLib, option=Opt.DEFAULT, preset=None):
        for parameter in self._psdParametersFields[psdLib]:
            value = parameter.defaultValue

            if option == Opt.NEW:
                value = parameter.newValue
            if option == Opt.EMPTY:
                if isinstance(parameter.field, qt.QComboBox):
                    value = None
                elif isinstance(parameter.field, qt.QCheckBox):
                    value = False
                else:
                    value = ""

            assert parameter.getPresetValue(preset) == value

    def _run_process(self, psdLib, hasSoi=False) -> None:
        load_project(PROJECT_FILE)

        psdLibInput = self._widgets["psdLibComboBox"]
        segmentationInput = self._widgets["segmentationInput"]
        soiInput = self._widgets["soiInput"]
        refInput = self._widgets["referenceInput"]
        segmentList = self._widgets["segmentList"]
        outputPrefx = self._widgets["outputPrefix"]
        applyBtn = self._widgets["applyBtn"]
        cancelBtn = self._widgets["cancelBtn"]

        segmentationInputNode, soiInputNode, refInputNode = self._get_inputs()

        psdLibInput.setCurrentIndex(psdLibInput.findData(psdLib))
        segmentationInput.setCurrentNode(segmentationInputNode)

        if hasSoi:
            soiInput.setCurrentNode(soiInputNode)

        assert segmentationInput.currentNode() == segmentationInputNode, self._msg_expected(
            segmentationInputNode, segmentationInput.currentNode()
        )

        if hasSoi:
            assert soiInput.currentNode() == soiInputNode, self._msg_expected(soiInputNode, soiInput.currentNode())
        else:
            assert soiInput.currentNode() is None, self._msg_expected("None", soiInput.currentNode())

        assert refInput.currentNode() == refInputNode, self._msg_expected(refInputNode, refInput.currentNode())
        assert outputPrefx.text == segmentationInputNode.GetName(), self._msg_expected(
            segmentationInputNode.GetName(), outputPrefx.text
        )

        # wait for the UI to update
        wait(0.1)

        segmentList.item(0).setCheckState(2)

        assert applyBtn.enabled, "Apply button should be enabled"
        assert not cancelBtn.enabled, "Cancel button should be disabled"

        with check_for_message_box(
            "Input segmentation has non-isotropic spacing. A new resampled node will be created with nearest "
            "neighbor interpolation to have an isotropic spacing to apply the PSD algorithm.",
            timeout_sec=1,
        ):
            applyBtn.clicked()
            process_events()

        wait(0.1)

        assert segmentationInput.currentNode().GetName() == segmentationInputNode.GetName() + "_Resampled", (
            self._msg_expected(
                segmentationInputNode.GetName() + "_Resampled", segmentationInput.currentNode().GetName()
            )
        )

        if hasSoi:
            assert soiInput.currentNode() == soiInputNode, self._msg_expected(soiInputNode, soiInput.currentNode())
        else:
            assert soiInput.currentNode() is None, self._msg_expected("None", soiInput.currentNode())

        assert refInput.currentNode() == refInputNode, self._msg_expected(refInputNode, refInput.currentNode())
        assert outputPrefx.text == segmentationInputNode.GetName() + "_Resampled", self._msg_expected(
            segmentationInputNode.GetName() + "_Resampled", outputPrefx.text
        )

        cliNode = self._module_widget.logic.cliNode

        assert cliNode is not None, "Cli node is None"
        assert not applyBtn.enabled, "Apply button shoud be disabled"
        assert cancelBtn.enabled, "Cancel button should be enabled"

        wait_cli_to_finish(cliNode)

        assert cliNode.GetStatusString() == "Completed", self._msg_cli("Completed", cliNode)
        assert applyBtn.enabled, "Apply button should be enabled"
        assert not cancelBtn.enabled, "Cancel button should be disabled"

        process_events()

        resultNode = tryGetNode(segmentationInputNode.GetName() + "_Resampled_PSD")

        assert resultNode is not None, "Execution did not generate result node"

        applyBtn.clicked()
        process_events()

        assert segmentationInput.currentNode().GetName() == segmentationInputNode.GetName() + "_Resampled", (
            self._msg_expected(
                segmentationInputNode.GetName() + "_Resampled", segmentationInput.currentNode().GetName()
            )
        )

        if hasSoi:
            assert soiInput.currentNode() == soiInputNode, self._msg_expected(soiInputNode, soiInput.currentNode())
        else:
            assert soiInput.currentNode() is None, self._msg_expected("None", soiInput.currentNode())

        assert refInput.currentNode() == refInputNode, self._msg_expected(refInputNode, refInput.currentNode())

        cliNode = self._module_widget.logic.cliNode

        assert cliNode is not None, "Cli node is None"
        assert not applyBtn.enabled, "Apply button shoud be disabled"
        assert cancelBtn.enabled, "Cancel button should be enabled"

        wait_cli_to_finish(cliNode)

        assert cliNode.GetStatusString() == "Completed", self._msg_cli("Completed", cliNode)
        assert applyBtn.enabled, "Apply button should be enabled"
        assert not cancelBtn.enabled, "Cancel button should be disabled"

        process_events()

        close_project()

    def _run_process_and_cancel(self, psdLib, hasSoi=False) -> None:
        load_project(PROJECT_FILE)

        psdLibInput = self._widgets["psdLibComboBox"]
        segmentationInput = self._widgets["segmentationInput"]
        soiInput = self._widgets["soiInput"]
        segmentList = self._widgets["segmentList"]
        applyBtn = self._widgets["applyBtn"]
        cancelBtn = self._widgets["cancelBtn"]

        segmentationInputNode, soiInputNode, _ = self._get_inputs()

        psdLibInput.setCurrentIndex(psdLibInput.findData(psdLib))
        segmentationInput.setCurrentNode(segmentationInputNode)

        if hasSoi:
            soiInput.setCurrentNode(soiInputNode)

        # wait for the UI to update
        wait(0.1)

        segmentList.item(0).setCheckState(2)

        assert applyBtn.enabled, "Apply button should be enabled"
        assert not cancelBtn.enabled, "Cancel button should be disabled"

        with check_for_message_box(
            "Input segmentation has non-isotropic spacing. A new resampled node will be created with nearest "
            "neighbor interpolation to have an isotropic spacing to apply the PSD algorithm.",
            timeout_sec=1,
        ):
            applyBtn.clicked()
            process_events()

        cliNode = self._module_widget.logic.cliNode

        assert cliNode is not None, "Cli node is None"
        assert not applyBtn.enabled, "Apply button shoud be disabled"
        assert cancelBtn.enabled, "Cancel button should be enabled"

        # wait for the UI to update
        wait(0.1)

        cancelBtn.clicked()
        process_events()

        wait_cli_to_finish(cliNode)

        assert cliNode.GetStatusString() == "Cancelled", self._msg_cli("Cancelled", cliNode)
        assert applyBtn.enabled, "Apply button should be enabled"
        assert not cancelBtn.enabled, "Cancel button should be disabled"

        process_events()

        resultNode = tryGetNode(segmentationInputNode.GetName() + "_Resampled_PSD")

        assert resultNode is None, "Execution generated result node"

        close_project()

    # Tests
    def test_default_interface_configuration(self):
        assert self._widgets["psdLibComboBox"].currentData == PSDLib.MICROTOM

        assert self._widgets["segmentationInput"].currentNode() is None
        assert self._widgets["soiInput"].currentNode() is None
        assert self._widgets["referenceInput"].currentNode() is None

        assert not self._widgets["dimensionLabelPx"].isVisible()
        assert not self._widgets["dimensionLabelMm"].isVisible()

        assert self._widgets["presetComboBox"].currentText == "None"
        assert self._widgets["presetCreateBtn"].enabled
        assert not self._widgets["presetRenameBtn"].enabled
        assert not self._widgets["presetSaveBtn"].enabled
        assert not self._widgets["presetDeleteBtn"].enabled
        assert self._widgets["exportPresetsBtn"].enabled
        assert self._widgets["importPresetsBtn"].enabled

        assert not self._widgets["resetPresetBtn"].enabled
        assert self._widgets["resetDefaultBtn"].enabled

        assert self._widgets["outputPrefix"].text == ""
        assert not self._widgets["manualOutputPrefixCkb"].isChecked()

        assert not self._widgets["applyBtn"].enabled
        assert not self._widgets["cancelBtn"].enabled

        self._assert_parameters(PSDLib.MICROTOM)
        self._assert_parameters(PSDLib.PORESPY)

    def test_attributes_appears_when_input_image_is_selected_and_output_prefix_name_changes(self) -> None:
        load_project(PROJECT_FILE)

        segmentationInput = self._widgets["segmentationInput"]
        soiInput = self._widgets["soiInput"]
        referenceInput = self._widgets["referenceInput"]
        segmentList = self._widgets["segmentList"]
        dimensionsLabelPx = self._widgets["dimensionLabelPx"]
        dimensionsLabelMm = self._widgets["dimensionLabelMm"]
        outputPrefx = self._widgets["outputPrefix"]

        segmentationInputNode, _, referenceInputNode = self._get_inputs()

        segmentationInput.setCurrentNode(segmentationInputNode)

        assert segmentationInput.currentNode() is segmentationInputNode, self._msg_expected(
            segmentationInputNode.GetName(), segmentationInput.currentNode()
        )

        # wait for the UI to update
        wait(0.1)

        assert soiInput.currentNode() is None, self._msg_expected("None", soiInput.currentNode())
        assert referenceInput.currentNode() is referenceInputNode, self._msg_expected(
            referenceInputNode.GetName(), referenceInput.currentNode()
        )

        assert segmentList.isVisible(), "Segment list should be visible"
        assert segmentList.count == 2, self._msg_expected("2", segmentList.count)
        assert segmentList.item(0).text() == "Segment_1", self._msg_expected("Segment_1", segmentList.item(0).text())
        assert segmentList.item(1).text() == "Segment_2", self._msg_expected("Segment_2", segmentList.item(1).text())

        assert dimensionsLabelPx.isVisible(), "Dimensions px label should be visible"
        assert dimensionsLabelPx.text == "180 x 1 x 251", self._msg_expected("180 x 1 x 251", dimensionsLabelPx.text)

        assert dimensionsLabelMm.isVisible(), "Dimensions mm label should be visible"
        assert dimensionsLabelMm.text == "678.2699 x 0.48 x 637.5365", self._msg_expected(
            "678.2699 x 0.48 x 637.5365", dimensionsLabelMm.text
        )
        assert outputPrefx.text == segmentationInputNode.GetName(), self._msg_expected(
            segmentationInputNode.GetName(), outputPrefx.text
        )

    def test_reset_parameters(self) -> None:
        psdLibInput = self._widgets["psdLibComboBox"]
        resetDefaultBtn = self._widgets["resetDefaultBtn"]

        # Change all parameter values
        self._change_parameters_to_value(PSDLib.MICROTOM, option=Opt.NEW)
        self._change_parameters_to_value(PSDLib.PORESPY, option=Opt.NEW)

        # Assert all the parameters have been changed
        self._assert_parameters(PSDLib.MICROTOM, option=Opt.NEW)
        self._assert_parameters(PSDLib.PORESPY, option=Opt.NEW)

        # Select Microtom lib backend
        psdLibInput.setCurrentIndex(psdLibInput.findData(PSDLib.MICROTOM))
        resetDefaultBtn.clicked()

        process_events()

        # Assert only Microtom parameters have been reset
        self._assert_parameters(PSDLib.MICROTOM, option=Opt.DEFAULT)
        self._assert_parameters(PSDLib.PORESPY, option=Opt.NEW)

        # Change Microtom parameters again
        self._change_parameters_to_value(PSDLib.MICROTOM, option=Opt.NEW)

        # Select PoreSpy lib backend
        psdLibInput.setCurrentIndex(psdLibInput.findData(PSDLib.PORESPY))
        resetDefaultBtn.clicked()

        process_events()

        # Assert only PoreSpy parameters have been reset
        self._assert_parameters(PSDLib.MICROTOM, option=Opt.NEW)
        self._assert_parameters(PSDLib.PORESPY, option=Opt.DEFAULT)

    def test_output_prefix_automatically_changes_when_manual_checkbox_is_not_checked(self) -> None:
        load_project(PROJECT_FILE)

        segmentationInput = self._widgets["segmentationInput"]
        outputPrefix = self._widgets["outputPrefix"]

        segmentationInputNode, *_ = self._get_inputs()

        assert outputPrefix.text == "", self._msg_expected("", outputPrefix.text)

        segmentationInput.setCurrentNode(segmentationInputNode)

        assert outputPrefix.text == segmentationInputNode.GetName(), self._msg_expected(
            segmentationInputNode.GetName(), outputPrefix.text
        )

        segmentationInput.setCurrentNode(None)

        assert outputPrefix.text == "", self._msg_expected("", outputPrefix.text)

    def test_output_prefix_should_not_change_when_manual_checkbox_is_checked(self) -> None:
        load_project(PROJECT_FILE)

        segmentationInput = self._widgets["segmentationInput"]
        outputPrefix = self._widgets["outputPrefix"]
        manualOutputPrefixCheckBox = self._widgets["manualOutputPrefixCkb"]

        outputPrefixValue = "Test_1"

        segmentationInputNode, *_ = self._get_inputs()

        assert outputPrefix.text == "", self._msg_expected("", outputPrefix.text)
        assert not outputPrefix.enabled, "Output prefix should be disabled"

        manualOutputPrefixCheckBox.setCheckState(2)

        process_events()

        assert outputPrefix.enabled, "Output prefix should be enabled"

        outputPrefix.text = outputPrefixValue

        assert outputPrefix.text == outputPrefixValue, self._msg_expected(outputPrefixValue, outputPrefixValue.text)

        segmentationInput.setCurrentNode(segmentationInputNode)

        assert outputPrefix.text == outputPrefixValue, self._msg_expected(outputPrefixValue, outputPrefix.text)

    def test_apply_must_be_enabled_when_all_inputs_are_set(self) -> None:
        load_project(PROJECT_FILE)

        segmentationInput = self._widgets["segmentationInput"]
        segmentList = self._widgets["segmentList"]
        applyBtn = self._widgets["applyBtn"]

        segmentationInputNode, *_ = self._get_inputs()

        segmentationInput.setCurrentNode(segmentationInputNode)

        # wait for the UI to update
        wait(0.1)

        segmentList.item(0).setCheckState(2)

        assert applyBtn.enabled, "Apply button should be enabled"

    def test_apply_must_be_enabled_after_close_popup_informing_no_segment_selected(self) -> None:
        load_project(PROJECT_FILE)

        segmentationInput = self._widgets["segmentationInput"]
        applyBtn = self._widgets["applyBtn"]

        segmentationInputNode, *_ = self._get_inputs()

        segmentationInput.setCurrentNode(segmentationInputNode)

        # wait for the UI to update
        wait(0.1)

        assert applyBtn.enabled, "Apply button should be enabled"

        with check_for_message_box("Please select at least one segment.", timeout_sec=1):
            applyBtn.clicked()
            process_events()

        assert applyBtn.enabled, "Apply button should be enabled"

    def test_apply_with_missing_required_fields(self) -> None:
        load_project(PROJECT_FILE)

        psdLibInput = self._widgets["psdLibComboBox"]
        segmentList = self._widgets["segmentList"]
        segmentationInput = self._widgets["segmentationInput"]
        applyBtn = self._widgets["applyBtn"]

        segmentationInputNode, *_ = self._get_inputs()

        segmentationInput.setCurrentNode(segmentationInputNode)

        # wait for the UI to update
        wait(0.1)

        self._change_parameters_to_value(psdLib=PSDLib.MICROTOM, option=Opt.EMPTY)
        self._change_parameters_to_value(psdLib=PSDLib.PORESPY, option=Opt.EMPTY)

        self._assert_parameters(psdLib=PSDLib.MICROTOM, option=Opt.EMPTY)
        self._assert_parameters(psdLib=PSDLib.PORESPY, option=Opt.EMPTY)

        message = "Expected background color to highlighted"

        for parameters in self._psdParametersFields.values():
            for parameter in parameters:
                if (
                    parameter.required
                    and not isinstance(parameter.field, qt.QComboBox)
                    and not isinstance(parameter.field, qt.QCheckBox)
                ):
                    assert "background-color:" in parameter.field.styleSheet, message

        assert applyBtn.enabled, "Apply button should be enabled"

        with check_for_message_box(
            "Please select at least one segment.\nSaturation Resolution is required.\nRadius Resolution is required.",
            timeout_sec=1,
        ):
            applyBtn.clicked()
            process_events()

        assert "background-color:" in segmentList.styleSheet, message
        assert applyBtn.enabled, "Apply button should be enabled"

        psdLibInput.setCurrentIndex(psdLibInput.findData(PSDLib.PORESPY))

        assert applyBtn.enabled, "Apply button should be enabled"

        with check_for_message_box(
            "Please select at least one segment.",
            timeout_sec=1,
        ):
            applyBtn.clicked()
            process_events()

        assert "background-color:" in segmentList.styleSheet, message
        assert applyBtn.enabled, "Apply button should be enabled"

    def test_presets_rename_save_delete_buttons_enabled_only_when_a_preset_is_selected(self) -> None:
        presetComboBox = self._widgets["presetComboBox"]
        presetCreateBtn = self._widgets["presetCreateBtn"]
        presetRenameBtn = self._widgets["presetRenameBtn"]
        presetSaveBtn = self._widgets["presetSaveBtn"]
        presetDeleteBtn = self._widgets["presetDeleteBtn"]

        def assert_none_preset_selected():
            assert presetComboBox.currentText == "None", self._msg_expected("None", presetComboBox.currentText)
            assert presetCreateBtn.enabled, "Create button should be enabled"
            assert not presetRenameBtn.enabled, "Rename button should be disabled"
            assert not presetSaveBtn.enabled, "Save button should be disabled"
            assert not presetDeleteBtn.enabled, "Delete button should be disabled"

        assert_none_preset_selected()

        presetName = "Preset 1"

        # When a preset is created, it should be automatically selected and the rename, save and delete buttons
        # should be enabled
        self._create_preset(presetName)

        # When a preset is created, it should be automatically selected
        assert presetComboBox.currentText == presetName, self._msg_expected(presetName, presetComboBox.currentText)

        assert presetCreateBtn.enabled, "Create button should be enabled"
        assert presetRenameBtn.enabled, "Rename button should be enabled"
        assert presetSaveBtn.enabled, "Save button should be enabled"
        assert presetDeleteBtn.enabled, "Delete button should be enabled"

        # When selecting the "None" option the rename, save and delete buttons should be disabled
        presetComboBox.setCurrentIndex(presetComboBox.findData(None))

        assert_none_preset_selected()

    def test_create_preset_with_empty_name_shows_popup(self) -> None:
        with check_for_message_box("Preset name cannot be empty", timeout_sec=1):
            self._create_preset("")

    def test_create_preset_with_valid_name(self) -> None:
        presetComboBox = self._widgets["presetComboBox"]

        presetName = "Preset 1"

        self._create_preset(presetName)

        # When a preset is created, it should be automatically selected
        assert presetComboBox.currentText == presetName, self._msg_expected(presetName, presetComboBox.currentText)

        presetList = self._module_widget.presets
        presetId = presetComboBox.currentData

        assert len(presetList) == 1, "There should be one preset in the preset list"
        assert presetId in presetList, "Preset ID of the created preset should be in the preset list presets"

        preset = presetList[presetId]

        self._assert_presets(PSDLib.MICROTOM, Opt.DEFAULT, preset)
        self._assert_presets(PSDLib.PORESPY, Opt.DEFAULT, preset)

    def test_rename_preset_with_empty_name_shows_popup(self) -> None:
        presetName = "Preset 1"

        self._create_preset(presetName)

        with check_for_message_box("Preset name cannot be empty", timeout_sec=1):
            self._rename_preset(presetName, "")

    def test_rename_preset_with_valid_name(self) -> None:
        presetComboBox = self._widgets["presetComboBox"]

        presetName = "Preset 1"
        newPresetName = "Preset 1 Renamed"

        self._create_preset(presetName)

        preset = self._module_widget.presets[presetComboBox.currentData]

        assert preset.name == presetName, self._msg_expected(presetName, preset.name)

        self._rename_preset(presetName, newPresetName)

        assert presetComboBox.currentText == newPresetName, self._msg_expected(
            newPresetName, presetComboBox.currentText
        )
        assert preset.name == newPresetName, self._msg_expected(newPresetName, preset.name)

    def test_save_preset_with_empty_parameters_shows_popup(self) -> None:
        presetSaveBtn = self._widgets["presetSaveBtn"]

        self._create_preset("Preset 1")

        # Clear parameters to simulate empty parameters
        self._change_parameters_to_value(psdLib=PSDLib.MICROTOM, option=Opt.EMPTY)
        self._change_parameters_to_value(psdLib=PSDLib.PORESPY, option=Opt.EMPTY)

        with check_for_message_box("Saturation Resolution is required.\nRadius Resolution is required.", timeout_sec=1):
            presetSaveBtn.clicked()
            process_events()

        self._widgets["psdLibComboBox"].setCurrentIndex(self._widgets["psdLibComboBox"].findData(PSDLib.PORESPY))

        presetSaveBtn.clicked()
        process_events()

    def test_save_preset(self) -> None:
        presetComboBox = self._widgets["presetComboBox"]
        presetSaveBtn = self._widgets["presetSaveBtn"]

        self._create_preset("Preset 1")

        # Change some parameter values
        self._change_parameters_to_value(psdLib=PSDLib.MICROTOM, option=Opt.NEW)
        self._change_parameters_to_value(psdLib=PSDLib.PORESPY, option=Opt.NEW)

        self._widgets["psdLibComboBox"].setCurrentIndex(self._widgets["psdLibComboBox"].findData(PSDLib.MICROTOM))

        presetSaveBtn.clicked()
        process_events()

        self._assert_presets(
            psdLib=PSDLib.MICROTOM, option=Opt.NEW, preset=self._module_widget.presets[presetComboBox.currentData]
        )
        self._assert_presets(
            psdLib=PSDLib.PORESPY, option=Opt.DEFAULT, preset=self._module_widget.presets[presetComboBox.currentData]
        )

        self._widgets["psdLibComboBox"].setCurrentIndex(self._widgets["psdLibComboBox"].findData(PSDLib.PORESPY))

        presetSaveBtn.clicked()
        process_events()

        self._assert_presets(
            psdLib=PSDLib.MICROTOM, option=Opt.NEW, preset=self._module_widget.presets[presetComboBox.currentData]
        )
        self._assert_presets(
            psdLib=PSDLib.PORESPY, option=Opt.NEW, preset=self._module_widget.presets[presetComboBox.currentData]
        )

    def test_delete_preset(self) -> None:
        presetComboBox = self._widgets["presetComboBox"]
        presetDeleteBtn = self._widgets["presetDeleteBtn"]
        messageDialog = self._widgets["messageDialog"]
        presetName = "Preset 1"

        self._create_preset(presetName)

        presetList = self._module_widget.presets

        assert len(presetList) == 1, "There should be one preset in the preset list"
        assert presetComboBox.currentData in presetList, "Preset should be in the preset list"

        def delete_preset():
            assert messageDialog.windowTitle == "Delete Preset"
            assert (
                messageDialog.message.text == f"The '<span style='color: yellow;'>{presetName}</span>' preset will be "
                "deleted. Are you sure?"
            ), self._msg_expected(
                f"The '<span style='color: yellow;'>{presetName}</span>' preset will be deleted. Are you sure?",
                messageDialog.message.text,
            )

            messageDialog.accept()

        qt.QTimer.singleShot(500, delete_preset)
        presetDeleteBtn.clicked()
        process_events()

        wait(0.5)

        presetList = self._module_widget.presets

        assert presetComboBox.currentText == "None", self._msg_expected("None", presetComboBox.currentText)
        assert len(presetList) == 0, "There should be no presets in the preset list"

    def test_parameter_changing_when_selecting_different_presets(self) -> None:
        presetComboBox = self._widgets["presetComboBox"]
        presetSaveBtn = self._widgets["presetSaveBtn"]

        presetName1 = "Preset 1"
        presetName2 = "Preset 2"

        self._create_preset(presetName1)
        self._create_preset(presetName2)

        # Change some parameter values
        self._change_parameters_to_value(psdLib=PSDLib.MICROTOM, option=Opt.NEW)
        self._change_parameters_to_value(psdLib=PSDLib.PORESPY, option=Opt.NEW)

        self._widgets["psdLibComboBox"].setCurrentIndex(self._widgets["psdLibComboBox"].findData(PSDLib.MICROTOM))

        presetSaveBtn.clicked()
        process_events()

        self._widgets["psdLibComboBox"].setCurrentIndex(self._widgets["psdLibComboBox"].findData(PSDLib.PORESPY))

        presetSaveBtn.clicked()
        process_events()

        presetComboBox.setCurrentIndex(presetComboBox.findText(presetName1))

        self._assert_parameters(psdLib=PSDLib.MICROTOM, option=Opt.DEFAULT)
        self._assert_parameters(psdLib=PSDLib.PORESPY, option=Opt.DEFAULT)

        presetComboBox.setCurrentIndex(presetComboBox.findText(presetName2))

        self._assert_parameters(psdLib=PSDLib.MICROTOM, option=Opt.NEW)
        self._assert_parameters(psdLib=PSDLib.PORESPY, option=Opt.NEW)

    def test_reset_preset_values(self) -> None:
        presetSaveBtn = self._widgets["presetSaveBtn"]
        resetPresetBtn = self._widgets["resetPresetBtn"]

        presetName1 = "Preset 1"

        self._create_preset(presetName1)

        # Change some parameter values
        self._change_parameters_to_value(psdLib=PSDLib.MICROTOM, option=Opt.NEW)
        self._change_parameters_to_value(psdLib=PSDLib.PORESPY, option=Opt.NEW)

        self._widgets["psdLibComboBox"].setCurrentIndex(self._widgets["psdLibComboBox"].findData(PSDLib.MICROTOM))

        presetSaveBtn.clicked()
        process_events()

        self._widgets["psdLibComboBox"].setCurrentIndex(self._widgets["psdLibComboBox"].findData(PSDLib.PORESPY))

        presetSaveBtn.clicked()
        process_events()

        self._assert_parameters(psdLib=PSDLib.MICROTOM, option=Opt.NEW)
        self._assert_parameters(psdLib=PSDLib.PORESPY, option=Opt.NEW)

        # Chage parameters to default value
        self._change_parameters_to_value(psdLib=PSDLib.MICROTOM, option=Opt.DEFAULT)
        self._change_parameters_to_value(psdLib=PSDLib.PORESPY, option=Opt.DEFAULT)

        self._assert_parameters(psdLib=PSDLib.MICROTOM, option=Opt.DEFAULT)
        self._assert_parameters(psdLib=PSDLib.PORESPY, option=Opt.DEFAULT)

        self._widgets["psdLibComboBox"].setCurrentIndex(self._widgets["psdLibComboBox"].findData(PSDLib.MICROTOM))

        resetPresetBtn.clicked()
        process_events()

        self._assert_parameters(psdLib=PSDLib.MICROTOM, option=Opt.NEW)
        self._assert_parameters(psdLib=PSDLib.PORESPY, option=Opt.DEFAULT)

        self._widgets["psdLibComboBox"].setCurrentIndex(self._widgets["psdLibComboBox"].findData(PSDLib.PORESPY))

        resetPresetBtn.clicked()
        process_events()

        self._assert_parameters(psdLib=PSDLib.MICROTOM, option=Opt.NEW)
        self._assert_parameters(psdLib=PSDLib.PORESPY, option=Opt.NEW)

    def test_export_presets(self) -> None:
        presetExportBtn = self._widgets["exportPresetsBtn"]
        exportImportDialog = self._widgets["exportImportDialog"]

        presetName1 = "Preset 1"
        presetName2 = "Preset 2"

        self._create_preset(presetName1)
        self._create_preset(presetName2)

        def select_export_presets():
            assert exportImportDialog.windowTitle == "Export Presets"
            assert exportImportDialog.selectAllCkb.checked
            assert exportImportDialog.table.rowCount == 2
            assert exportImportDialog.table.item(0, 0).checkState() == qt.Qt.Checked
            assert exportImportDialog.table.item(1, 0).checkState() == qt.Qt.Checked

            exportImportDialog.selectAllCkb.setCheckState(qt.Qt.Unchecked)
            process_events()
            wait(0.1)

            assert exportImportDialog.table.item(0, 0).checkState() == qt.Qt.Unchecked
            assert exportImportDialog.table.item(1, 0).checkState() == qt.Qt.Unchecked

            exportImportDialog.selectAllCkb.setCheckState(qt.Qt.Checked)
            process_events()
            wait(0.1)

            assert exportImportDialog.table.item(0, 0).checkState() == qt.Qt.Checked
            assert exportImportDialog.table.item(1, 0).checkState() == qt.Qt.Checked

            exportImportDialog.selectAllCkb.setCheckState(qt.Qt.Unchecked)
            process_events()
            wait(0.1)

            exportImportDialog.table.item(1, 0).setCheckState(qt.Qt.Checked)
            process_events()
            wait(0.1)

            exportImportDialog.accept()
            process_events()

        qt.QTimer.singleShot(500, select_export_presets)
        with mockFileDialog(selectedFiles=[EXPORT_PRESETS_PATH.as_posix()]):
            presetExportBtn.clicked()
            process_events()

        assert os.path.isfile(EXPORT_PRESETS_PATH)

        with open(EXPORT_PRESETS_PATH, "r") as f:
            presets = json.load(f)
            presets = presets["ImageLogPSDGeneration"]

        assert len(presets) == 1, self._msg_expected(1, len(presets))
        assert list(presets.values())[0]["name"] == "Preset 2", self._msg_expected(
            "Preset 2", list(presets.values())[0]["name"]
        )

        if os.path.isfile(EXPORT_PRESETS_PATH):
            os.remove(EXPORT_PRESETS_PATH)

    def test_import_presets(self) -> None:
        presetImportBtn = self._widgets["importPresetsBtn"]
        exportImportDialog = self._widgets["exportImportDialog"]

        def select_import_presets():
            assert exportImportDialog.windowTitle == "Import Presets"
            assert exportImportDialog.selectAllCkb.checked
            assert exportImportDialog.table.rowCount == 2
            assert exportImportDialog.table.item(0, 0).checkState() == qt.Qt.Checked
            assert exportImportDialog.table.item(1, 0).checkState() == qt.Qt.Checked

            exportImportDialog.selectAllCkb.setCheckState(qt.Qt.Unchecked)
            process_events()
            wait(0.1)

            assert exportImportDialog.table.item(0, 0).checkState() == qt.Qt.Unchecked
            assert exportImportDialog.table.item(1, 0).checkState() == qt.Qt.Unchecked

            exportImportDialog.selectAllCkb.setCheckState(qt.Qt.Checked)
            process_events()
            wait(0.1)

            assert exportImportDialog.table.item(0, 0).checkState() == qt.Qt.Checked
            assert exportImportDialog.table.item(1, 0).checkState() == qt.Qt.Checked

            exportImportDialog.selectAllCkb.setCheckState(qt.Qt.Unchecked)
            process_events()
            wait(0.1)

            exportImportDialog.table.item(1, 0).setCheckState(qt.Qt.Checked)
            process_events()
            wait(0.1)

            exportImportDialog.accept()

        qt.QTimer.singleShot(1000, select_import_presets)

        with mockFileDialog(selectedFiles=[IMPORT_PRESETS_PATH.as_posix()]):
            presetImportBtn.clicked()
            process_events()

        assert len(self._module_widget.presets) == 1, self._msg_expected(1, len(self._module_widget.presets))
        assert list(self._module_widget.presets.values())[0].name == "Preset 2", self._msg_expected(
            "Preset 2", list(self._module_widget.presets.values())[0].name
        )

    def test_import_presets_conflict(self) -> None:
        presetComboBox = self._widgets["presetComboBox"]
        presetImportBtn = self._widgets["importPresetsBtn"]
        exportImportDialog = self._widgets["exportImportDialog"]

        self._create_preset("Preset 1")

        assert len(self._module_widget.presets) == 1, self._msg_expected(1, len(self._module_widget.presets))

        # Update the created preset id with an existing preset id inside the file that will be imported
        presetId = presetComboBox.currentData
        newPresetId = "b3235dd9-6488-4786-b527-025d3e96a8f5"

        preset = self._module_widget.presets[presetId]
        del self._module_widget.presets[presetId]
        preset.id = newPresetId

        self._module_widget.presets[newPresetId] = preset
        self._module_widget.presetWidget.loadData(self._module_widget.presets.values())
        self._module_widget.logic.savePresets(PRESETS_PATH, self._module_widget.presets)

        self._assert_presets(PSDLib.MICROTOM, option=Opt.DEFAULT, preset=preset)
        self._assert_presets(PSDLib.PORESPY, option=Opt.DEFAULT, preset=preset)

        def conflicts_import_presets():
            assert exportImportDialog.windowTitle == "Import Presets"
            assert exportImportDialog.selectAllCkb.checked
            assert exportImportDialog.table.rowCount == 1
            assert exportImportDialog.table.item(0, 0).checkState() == qt.Qt.Checked

            exportImportDialog.accept()

        def select_import_presets():
            assert exportImportDialog.windowTitle == "Import Presets"
            assert exportImportDialog.selectAllCkb.checked
            assert exportImportDialog.table.rowCount == 2
            assert exportImportDialog.table.item(0, 0).checkState() == qt.Qt.Checked
            assert exportImportDialog.table.item(1, 0).checkState() == qt.Qt.Checked

            qt.QTimer.singleShot(500, conflicts_import_presets)
            exportImportDialog.accept()

        qt.QTimer.singleShot(500, select_import_presets)

        with mockFileDialog(selectedFiles=[IMPORT_PRESETS_PATH.as_posix()]):
            presetImportBtn.clicked()
            process_events()

        assert len(self._module_widget.presets) == 2, self._msg_expected(2, len(self._module_widget.presets))
        assert list(self._module_widget.presets.values())[0].name == "Preset 1", self._msg_expected(
            "Preset 1", list(self._module_widget.presets.values())[0].name
        )
        assert list(self._module_widget.presets.values())[1].name == "Preset 2", self._msg_expected(
            "Preset 2", list(self._module_widget.presets.values())[1].name
        )

        self._assert_presets(PSDLib.MICROTOM, option=Opt.NEW, preset=self._module_widget.presets[newPresetId])
        self._assert_presets(PSDLib.PORESPY, option=Opt.NEW, preset=self._module_widget.presets[newPresetId])

    def test_run_for_microtom_lib(self) -> None:
        self._run_process(PSDLib.MICROTOM)

    def test_run_with_soi_for_microtom_lib(self) -> None:
        self._run_process(PSDLib.MICROTOM, hasSoi=True)

    def test_run_and_cancel_for_microtom_lib(self) -> None:
        self._run_process_and_cancel(PSDLib.MICROTOM)

    def test_run_and_cancel_with_soi_for_microtom_lib(self) -> None:
        self._run_process_and_cancel(PSDLib.MICROTOM, hasSoi=True)

    def test_run_for_porespy_lib(self) -> None:
        self._run_process(PSDLib.PORESPY)

    def test_run_with_soi_for_porespy_lib(self) -> None:
        self._run_process(PSDLib.PORESPY, hasSoi=True)

    def test_run_and_cancel_for_porespy_lib(self) -> None:
        self._run_process_and_cancel(PSDLib.PORESPY)

    def test_run_and_cancel_with_soi_for_porespy_lib(self) -> None:
        self._run_process_and_cancel(PSDLib.PORESPY, hasSoi=True)
