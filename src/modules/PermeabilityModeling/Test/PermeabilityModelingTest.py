import qt
import pandas as pd

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import (
    wait,
    wait_cli_to_finish,
    load_project,
    save_project,
    check_for_message_box,
    getPlatformProjectPath,
)
from commons.slicer.helpers import tryGetNode
from typing import Union
from pathlib import Path
from commons.slicer_utils import dataframeFromTable


TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
PERM_POCO_RAW_PROJECT_FILE = TEST_RESOURCES_DIR / "PERM_POCO_RAW" / "PERM_POCO_RAW.mrml"
PERM_POCO_PROJECT_FILE = TEST_RESOURCES_DIR / "PERM_POCO" / "PERM_POCO.mrml"
PERM_VOLUME_RAW_PROJECT_FILE = TEST_RESOURCES_DIR / "PERM_VOLUME_RAW" / "PERM_VOLUME_RAW.mrml"
PERM_VOLUME_PROJECT_FILE = TEST_RESOURCES_DIR / "PERM_VOLUME" / "PERM_VOLUME.mrml"


class PermeabilityModelingTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __addItemToTable(self, startDepth: int, stopDepth: int, kDst: int, kRo: int):
        def process():
            widgets = {
                "Add Kds Optimization Item Dialog": self.find_widget(
                    name="Add Kds Optimization Item Dialog",
                    only_visible=True,
                ),
                "Start Depth Spin Box": self.find_widget(
                    name="Start Depth Spin Box",
                    only_visible=True,
                ),
                "Stop Depth Spin Box": self.find_widget(
                    name="Stop Depth Spin Box",
                    only_visible=True,
                ),
                "Kdst Spin Box": self.find_widget(
                    name="Kdst Spin Box",
                    only_visible=True,
                ),
                "Kro Spin Box": self.find_widget(
                    name="Kro Spin Box",
                    only_visible=True,
                ),
                "Add Kds Optimization Item Add Button": self.find_widget(
                    name="Add Kds Optimization Item Add Button",
                    only_visible=True,
                ),
                "Add Kds Optimization Item Cancel Button": self.find_widget(
                    name="Add Kds Optimization Item Cancel Button",
                    only_visible=True,
                ),
            }
            # Input tab
            for objectName, widget in widgets.items():
                assert widget is not None, f"widget related to the objectName '{objectName}' is None!"

            # assert widgets["Add Kds Optimization Item Dialog"].visible
            widgets["Start Depth Spin Box"].value = startDepth
            widgets["Stop Depth Spin Box"].value = stopDepth
            widgets["Kdst Spin Box"].value = kDst
            widgets["Kro Spin Box"].value = kRo

            # Click on add button
            widgets["Add Kds Optimization Item Add Button"].click()
            wait(0.1)

        # Using a timer to trigger the method to be called after the modal dialog to be executed.
        qt.QTimer.singleShot(1000, process)

        # Click on add button to open the dialog
        self.__widgets["kdsOptimizationAddButton"].click()
        wait(0.1)

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self.__widgets = {
            # Input Section
            "wellLogsInput": self.find_widget("Well Logs Input"),
            "porosityLogComboBox": self.find_widget("Porosity Log Combo Box"),
            "segmentedImageInput": self.find_widget("Segmented Image Input"),
            # Parameters Section
            "macroPoreSegmentComboBox": self.find_widget("Macro Pore Segment Combo Box"),
            "ignoredNullSegmentComboBox": self.find_widget("Ignored/null Segment Combo Box"),
            # Measurement Section,
            "plugsMeasurementsInput": self.find_widget("Plugs Measurements Input"),
            "plugsPermeabilityLogComboBox": self.find_widget("Plugs Permeability Log Combo Box"),
            # Kds Optimization section,
            "kdsOptimizationWidget": self.find_widget("Kds Optimization Widget"),
            "kdsOptimizationTable": self.find_widget("Kds Optimization Table"),
            "kdsOptimizationAddButton": self.find_widget("Kds Optimization Add Button"),
            "kdsOptimizationRemoveButton": self.find_widget("Kds Optimization Remove Button"),
            "kdsOptimizationWeightSpinBox": self.find_widget("Kds Optimization Weight Spin Box"),
            # Output section
            "outputNameLineEdit": self.find_widget(name="Output Name Line Edit"),
            "applyButton": self.find_widget(name="Apply Button"),
            # Advanced settings section
            "fractionSmoothingWindowSizeSpinBox": self.find_widget("Fraction Smoothing Window Size Spin Box"),
            "excessKFractionThresholdSpinBox": self.find_widget("Excess-K Fraction Threshold Spin Box"),
            "useMatrixKPlugErrorTermCheckBox": self.find_widget("Use Matrix-K Plug Error Term Check Box"),
            "excessKPowerParamaterSpinBox": self.find_widget("Excess-K Power Paramater Spin Box"),
        }

        # Input tab
        for objectName, widget in self.__widgets.items():
            assert widget is not None, f"widget related to the objectName '{objectName}' is None!"

    def generate_template_project(self):
        # Load raw project with the necessary data to generate the templates
        load_project(project_file_path=PERM_POCO_RAW_PROJECT_FILE)
        self._module_widget.enter()  # Trigger Kds optimization table update

        # Tests process to generated template data
        self.test_process_default_input(generateDataOnly=True)
        self.test_process_default_input_with_kds_optimization(generateDataOnly=True)
        self.test_process_with_advanced_parameters_variation(generateDataOnly=True)
        platform_poco_project_file = getPlatformProjectPath(PERM_POCO_PROJECT_FILE, check_exists=False)
        assert save_project(project_path=platform_poco_project_file), "Failed to save generated data to project."

    def generate_template_project_perm_volume(self):
        load_project(project_file_path=PERM_VOLUME_RAW_PROJECT_FILE)
        self.test_process_new_input_with_labelmap_volume_node(generateDataOnly=True)
        self.test_process_new_input_with_segmentation_node(generateDataOnly=True)
        platform_volume_project_file = getPlatformProjectPath(PERM_VOLUME_PROJECT_FILE, check_exists=False)
        assert save_project(project_path=platform_volume_project_file), "Failed to save generated data to project."

    def test_process_default_input(self, generateDataOnly=False):
        self.__execute_sucessful_process(
            projectPath=PERM_POCO_PROJECT_FILE,
            generateDataOnly=generateDataOnly,
            wellLogsInput="Well_Logs",
            porosityLogInput="PHI_MATRIZ",
            segmentedImageInput="Well_Logs_Segmentation",
            macroPoreSegmentInput="Segment 1",
            ignoredSegmentInput="Segment 5",
            plugsMeasurementsInput="Plugs_Measurement_Table",
            plugsPermeabilityLog="Perm",
            outputName="Permeability_Output",
        )

    def test_process_new_input_with_segmentation_node(self, generateDataOnly=False):
        self.__execute_sucessful_process(
            projectPath=PERM_VOLUME_PROJECT_FILE,
            generateDataOnly=generateDataOnly,
            wellLogsInput="TCMR [m3/m3]",
            porosityLogInput="TCMR [m3/m3]",
            segmentedImageInput="Segmentation",
            macroPoreSegmentInput="V",
            ignoredSegmentInput="Art",
            plugsMeasurementsInput="KSDR_HR [mD]",
            plugsPermeabilityLog="KSDR_HR [mD]",
            outputName="Permeability_Output",
        )

    def test_process_new_input_with_labelmap_volume_node(self, generateDataOnly=False):
        self.__execute_sucessful_process(
            projectPath=PERM_VOLUME_PROJECT_FILE,
            generateDataOnly=generateDataOnly,
            wellLogsInput="TCMR [m3/m3]",
            porosityLogInput="TCMR [m3/m3]",
            segmentedImageInput="Segmentation-label",
            macroPoreSegmentInput="V",
            ignoredSegmentInput="Art",
            plugsMeasurementsInput="KSDR_HR [mD]",
            plugsPermeabilityLog="KSDR_HR [mD]",
            outputName="Permeability_Output_label",
        )

    def test_process_new_input_invalid_macropore_segment(self):
        load_project(project_file_path=getPlatformProjectPath(PERM_VOLUME_PROJECT_FILE))
        wellLogsInput = "TCMR [m3/m3]"
        porosityLogInput = "TCMR [m3/m3]"
        segmentedImageInput = "InvalidSegmentation"
        macroPoreSegmentInput = "V"
        ignoredSegmentInput = "Art"
        plugsMeasurementsInput = "KSDR_HR [mD]"
        plugsPermeabilityLog = "KSDR_HR [mD]"
        outputName = "Permeability_Output"

        # Input images section
        wellLogsInputNode = tryGetNode(wellLogsInput)
        segmentedImageInputNode = tryGetNode(segmentedImageInput)

        self.__widgets["wellLogsInput"].setCurrentNode(wellLogsInputNode)
        self.__widgets["porosityLogComboBox"].setCurrentText(porosityLogInput)
        self.__widgets["segmentedImageInput"].setCurrentNode(segmentedImageInputNode)

        # Parameters section
        self.__widgets["macroPoreSegmentComboBox"].setCurrentText(macroPoreSegmentInput)
        self.__widgets["ignoredNullSegmentComboBox"].setCurrentText(ignoredSegmentInput)

        # Reference permeability section
        plugsMeasurementsInputNode = tryGetNode(plugsMeasurementsInput)
        self.__widgets["plugsMeasurementsInput"].setCurrentNode(plugsMeasurementsInputNode)
        self.__widgets["plugsPermeabilityLogComboBox"].setCurrentText(plugsPermeabilityLog)

        # Output section
        self.__widgets["outputNameLineEdit"].setText(f"{outputName}")

        wait(0.1)

        with check_for_message_box(
            "Segment registered as 'Macropore' is empty. Please, check the segmentation or change the selected segment."
        ):
            # Simulate apply button clicked
            self.__widgets["applyButton"].clicked()

    def test_process_new_input_invalid_macropore_label(self):
        load_project(project_file_path=getPlatformProjectPath(PERM_VOLUME_PROJECT_FILE))
        wellLogsInput = "TCMR [m3/m3]"
        porosityLogInput = "TCMR [m3/m3]"
        segmentedImageInput = "InvalidSegmentation-label"
        macroPoreSegmentInput = "V"
        ignoredSegmentInput = "Art"
        plugsMeasurementsInput = "KSDR_HR [mD]"
        plugsPermeabilityLog = "KSDR_HR [mD]"
        outputName = "Permeability_Output"

        # Input images section
        wellLogsInputNode = tryGetNode(wellLogsInput)
        segmentedImageInputNode = tryGetNode(segmentedImageInput)

        self.__widgets["wellLogsInput"].setCurrentNode(wellLogsInputNode)
        self.__widgets["porosityLogComboBox"].setCurrentText(porosityLogInput)
        self.__widgets["segmentedImageInput"].setCurrentNode(segmentedImageInputNode)

        # Parameters section
        self.__widgets["macroPoreSegmentComboBox"].setCurrentText(macroPoreSegmentInput)
        self.__widgets["ignoredNullSegmentComboBox"].setCurrentText(ignoredSegmentInput)

        # Reference permeability section
        plugsMeasurementsInputNode = tryGetNode(plugsMeasurementsInput)
        self.__widgets["plugsMeasurementsInput"].setCurrentNode(plugsMeasurementsInputNode)
        self.__widgets["plugsPermeabilityLogComboBox"].setCurrentText(plugsPermeabilityLog)

        # Output section
        self.__widgets["outputNameLineEdit"].setText(f"{outputName}")

        wait(0.1)

        with check_for_message_box(
            "Segment registered as 'Macropore' is empty. Please, check the segmentation or change the selected segment."
        ):
            # Simulate apply button clicked
            self.__widgets["applyButton"].clicked()

    def test_process_default_input_with_kds_optimization(self, generateDataOnly=False):
        self.__execute_sucessful_process(
            projectPath=PERM_POCO_PROJECT_FILE,
            generateDataOnly=generateDataOnly,
            wellLogsInput="Well_Logs",
            porosityLogInput="PHI_MATRIZ",
            segmentedImageInput="Well_Logs_Segmentation",
            macroPoreSegmentInput="Segment 1",
            ignoredSegmentInput="Segment 5",
            plugsMeasurementsInput="Plugs_Measurement_Table",
            plugsPermeabilityLog="Perm",
            kDsOptimizationIntervals=[[5277.7, 5417.7, 464000.0, 0.75]],
            kDsOptimizationWeight=1.0,
            outputName="Permeability_with_kds_Output",
        )

    def test_interface_default_values_for_widgets(self):
        assert self.__widgets["wellLogsInput"].currentNode() is None
        assert self.__widgets["porosityLogComboBox"].currentText == ""
        assert self.__widgets["segmentedImageInput"].currentNode() is None
        assert self.__widgets["macroPoreSegmentComboBox"].currentText == ""
        assert self.__widgets["ignoredNullSegmentComboBox"].currentText == ""
        assert self.__widgets["plugsMeasurementsInput"].currentNode() is None
        assert self.__widgets["plugsPermeabilityLogComboBox"].currentText == ""
        assert self.__widgets["kdsOptimizationWidget"].visible
        assert self.__widgets["kdsOptimizationTable"].visible
        assert self.__widgets["kdsOptimizationTable"].rowCount == 0
        assert self.__widgets["outputNameLineEdit"].text == ""
        assert self.__widgets["fractionSmoothingWindowSizeSpinBox"].value == 10
        assert self.__widgets["excessKFractionThresholdSpinBox"].value == 1.0
        assert self.__widgets["useMatrixKPlugErrorTermCheckBox"].isChecked() is False
        assert self.__widgets["excessKPowerParamaterSpinBox"].value == 1.0

    def test_loading_kds_table_from_project(self):
        kdsTable = self.__widgets["kdsOptimizationTable"]
        assert kdsTable.rowCount == 0
        load_project(project_file_path=getPlatformProjectPath(PERM_POCO_PROJECT_FILE))
        self._module_widget.enter()  # Trigger Kds optimization table update

        assert kdsTable.rowCount == 1, f"Expected 1 row, got {kdsTable.rowCount}"
        assert kdsTable.item(0, 0).text() == "5277.7"
        assert kdsTable.item(0, 1).text() == "5417.7"
        assert kdsTable.item(0, 2).text() == "464000.0"
        assert kdsTable.item(0, 3).text() == "0.75"

    def test_removing_kds_item_from_table(self):
        kdsTable = self.__widgets["kdsOptimizationTable"]
        assert kdsTable.rowCount == 0
        load_project(project_file_path=getPlatformProjectPath(PERM_POCO_PROJECT_FILE))
        self._module_widget.enter()  # Trigger Kds optimization table update

        assert kdsTable.rowCount == 1, f"Expected 1 row, got {kdsTable.rowCount}"

        # Select first row
        kdsTable.selectRow(0)

        # Click on remove button
        self.__widgets["kdsOptimizationRemoveButton"].click()
        wait(0.1)

        assert kdsTable.rowCount == 0

    def test_removing_multiples_kds_item_from_table(self):
        kdsTable = self.__widgets["kdsOptimizationTable"]
        assert kdsTable.rowCount == 0

        self.__addItemToTable(startDepth=1, stopDepth=2, kDst=464000.0, kRo=0.75)
        self.__addItemToTable(startDepth=2, stopDepth=3, kDst=464000.0, kRo=0.75)
        self.__addItemToTable(startDepth=3, stopDepth=4, kDst=464000.0, kRo=0.75)
        self.__addItemToTable(startDepth=4, stopDepth=5, kDst=464000.0, kRo=0.75)
        assert kdsTable.rowCount == 4, f"Expected 4 rows, got {kdsTable.rowCount}"

        # Select all
        kdsTable.selectAll()

        # Click on remove button
        self.__widgets["kdsOptimizationRemoveButton"].click()
        wait(0.1)

        assert kdsTable.rowCount == 0

    def test_adding_kds_item_to_table(self):
        kdsTable = self.__widgets["kdsOptimizationTable"]
        assert kdsTable.rowCount == 0

        wait(0.1)

        self.__addItemToTable(startDepth=5277.7, stopDepth=5417.7, kDst=464000.0, kRo=0.75)
        assert kdsTable.rowCount == 1
        assert kdsTable.item(0, 0).text() == "5277.7"
        assert kdsTable.item(0, 1).text() == "5417.7"
        assert kdsTable.item(0, 2).text() == "464000.0"
        assert kdsTable.item(0, 3).text() == "0.75"

    def test_adding_kds_item_to_table_with_invalid_depths(self):
        kdsTable = self.__widgets["kdsOptimizationTable"]
        assert kdsTable.rowCount == 0

        self.__addItemToTable(startDepth=5277.7, stopDepth=5227.7, kDst=464000.0, kRo=0.75)
        assert kdsTable.rowCount == 1
        assert kdsTable.item(0, 0).text() == "5277.7"
        assert kdsTable.item(0, 1).text() == "5278.7"
        assert kdsTable.item(0, 2).text() == "464000.0"
        assert kdsTable.item(0, 3).text() == "0.75"

    def __execute_sucessful_process(
        self, projectPath: Union[str, Path], generateDataOnly=False, *args, **kwargs
    ) -> None:
        """Handle succesful interface interaction.

        Args:
            projectPath (Union[str, Path]): The template project path
            generateDataOnly (bool, optional): Save generated data in the project path instead of asserting values. Defaults to False.
        """

        if not generateDataOnly:
            load_project(project_file_path=getPlatformProjectPath(projectPath))

        wellLogsInput = kwargs.get("wellLogsInput")
        porosityLogInput = kwargs.get("porosityLogInput")
        segmentedImageInput = kwargs.get("segmentedImageInput")
        macroPoreSegmentInput = kwargs.get("macroPoreSegmentInput")
        ignoredSegmentInput = kwargs.get("ignoredSegmentInput")
        plugsMeasurementsInput = kwargs.get("plugsMeasurementsInput")
        plugsPermeabilityLog = kwargs.get("plugsPermeabilityLog")
        kDsOptimizationIntervals = kwargs.get("kDsOptimizationIntervals")
        kDsOptimizationWeight = kwargs.get("kDsOptimizationWeight", 1.0)
        outputName = kwargs.get("outputName")

        # Advanced settings parameters
        fractionSmoothingWindowSize = kwargs.get("fractionSmoothingWindowSize", 10)
        excessKFractionThreshold = kwargs.get("excessKFractionThreshold", 1.0)
        useMatrixKPlugErrorTerm = kwargs.get("useMatrixKPlugErrorTerm", False)
        excessKPowerParamater = kwargs.get("excessKPowerParamater", 1.0)

        # Input images section
        wellLogsInputNode = tryGetNode(wellLogsInput)
        segmentedImageInputNode = tryGetNode(segmentedImageInput)

        self.__widgets["wellLogsInput"].setCurrentNode(wellLogsInputNode)
        self.__widgets["porosityLogComboBox"].setCurrentText(porosityLogInput)
        self.__widgets["segmentedImageInput"].setCurrentNode(segmentedImageInputNode)

        # Parameters section
        self.__widgets["macroPoreSegmentComboBox"].setCurrentText(macroPoreSegmentInput)
        self.__widgets["ignoredNullSegmentComboBox"].setCurrentText(ignoredSegmentInput)

        # Advanced settings section
        self.__widgets["fractionSmoothingWindowSizeSpinBox"].setValue(fractionSmoothingWindowSize)
        self.__widgets["excessKFractionThresholdSpinBox"].setValue(excessKFractionThreshold)
        self.__widgets["useMatrixKPlugErrorTermCheckBox"].setChecked(useMatrixKPlugErrorTerm)
        self.__widgets["excessKPowerParamaterSpinBox"].setValue(excessKPowerParamater)

        # Reference permeability section
        plugsMeasurementsInputNode = tryGetNode(plugsMeasurementsInput)
        self.__widgets["plugsMeasurementsInput"].setCurrentNode(plugsMeasurementsInputNode)
        self.__widgets["plugsPermeabilityLogComboBox"].setCurrentText(plugsPermeabilityLog)

        # Kds optimization section
        # Remove all previous loaded kds items from table
        self.__widgets["kdsOptimizationTable"].selectAll()

        # Click on remove button
        self.__widgets["kdsOptimizationRemoveButton"].click()
        wait(0.1)
        if kDsOptimizationIntervals is not None:
            for kdsInterval in kDsOptimizationIntervals:
                self.__addItemToTable(*kdsInterval)
        self.__widgets["kdsOptimizationWeightSpinBox"].setValue(kDsOptimizationWeight)

        # Output section
        suffix = "_Template" if generateDataOnly else ""
        self.__widgets["outputNameLineEdit"].setText(f"{outputName}{suffix}")

        wait(0.1)

        # Simulate apply button clicked
        self.__widgets["applyButton"].clicked()

        # Process Qt event queue
        wait(1)

        cliNode = self._module_widget.logic.cliNode
        assert cliNode is not None
        wait_cli_to_finish(cli_entity=cliNode)

        if generateDataOnly:
            return

        # Assert nodes
        outputNode = tryGetNode(f"{outputName}")
        outputTemplateNode = tryGetNode(f"{outputName}_Template")

        assert outputNode is not None
        assert outputTemplateNode is not None

        outputDataFrame = dataframeFromTable(outputNode)
        outputTemplateDataFrame = dataframeFromTable(outputTemplateNode)

        pd.testing.assert_frame_equal(outputDataFrame, outputTemplateDataFrame, check_exact=False)

    def test_kds_table_cell_changed_updates_model(self):
        load_project(project_file_path=getPlatformProjectPath(PERM_POCO_PROJECT_FILE))
        self._module_widget.enter()

        kdsTable = self.__widgets["kdsOptimizationTable"]
        assert kdsTable.rowCount == 1

        item = kdsTable.item(0, 3)
        assert item is not None
        assert item.text() == "0.75"

        # Select the cell so that the handler's currentCell is set
        kdsTable.setCurrentCell(0, 3)

        # Track if the cellChanged signal was emitted
        # because checking the actual bug behavior require the implementation
        # of the table cell manipulation through QEvents
        signal_emitted = False

        def on_signal_emitted():
            nonlocal signal_emitted
            signal_emitted = True

        widget = self.__widgets["kdsOptimizationWidget"]
        widget._tableCellHandler.cellChanged.connect(on_signal_emitted)

        item.setText("0.85")
        wait(0.2)

        assert signal_emitted, "Signal cellChanged was not emitted!"

        node = tryGetNode("ERROR_CORRECTION_TABLE_NODE")
        assert node is not None
        df = dataframeFromTable(node)
        assert df is not None
        assert float(df.iloc[0, 3]) == 0.85

    def test_process_with_advanced_parameters_variation(self, generateDataOnly=False):
        # Update 'fraction smoothing window size'
        self.__execute_sucessful_process(
            projectPath=PERM_POCO_PROJECT_FILE,
            generateDataOnly=generateDataOnly,
            wellLogsInput="Well_Logs",
            porosityLogInput="PHI_MATRIZ",
            segmentedImageInput="Well_Logs_Segmentation",
            macroPoreSegmentInput="Segment 1",
            ignoredSegmentInput="Segment 5",
            plugsMeasurementsInput="Plugs_Measurement_Table",
            plugsPermeabilityLog="Perm",
            kDsOptimizationIntervals=[[5277.7, 5417.7, 464000.0, 0.75]],
            kDsOptimizationWeight=1.0,
            fractionSmoothingWindowSize=5,
            excessKFractionThreshold=1.0,
            useMatrixKPlugErrorTerm=False,
            excessKPowerParamater=1.0,
            outputName="Permeability_advanced_variation_Output",
        )

        # Update 'excess-K fraction threshold'
        self.__execute_sucessful_process(
            projectPath=PERM_POCO_PROJECT_FILE,
            generateDataOnly=generateDataOnly,
            wellLogsInput="Well_Logs",
            porosityLogInput="PHI_MATRIZ",
            segmentedImageInput="Well_Logs_Segmentation",
            macroPoreSegmentInput="Segment 1",
            ignoredSegmentInput="Segment 5",
            plugsMeasurementsInput="Plugs_Measurement_Table",
            plugsPermeabilityLog="Perm",
            kDsOptimizationIntervals=[[5277.7, 5417.7, 464000.0, 0.75]],
            kDsOptimizationWeight=1.0,
            fractionSmoothingWindowSize=10,
            excessKFractionThreshold=0.5,
            useMatrixKPlugErrorTerm=False,
            excessKPowerParamater=1.0,
            outputName="Permeability_advanced_variation_2_Output",
        )

        # Update 'use matrix-k plug error term only'
        self.__execute_sucessful_process(
            projectPath=PERM_POCO_PROJECT_FILE,
            generateDataOnly=generateDataOnly,
            wellLogsInput="Well_Logs",
            porosityLogInput="PHI_MATRIZ",
            segmentedImageInput="Well_Logs_Segmentation",
            macroPoreSegmentInput="Segment 1",
            ignoredSegmentInput="Segment 5",
            plugsMeasurementsInput="Plugs_Measurement_Table",
            plugsPermeabilityLog="Perm",
            kDsOptimizationIntervals=[[5277.7, 5417.7, 464000.0, 0.75]],
            kDsOptimizationWeight=1.0,
            fractionSmoothingWindowSize=10,
            excessKFractionThreshold=1.0,
            useMatrixKPlugErrorTerm=True,
            excessKPowerParamater=1.0,
            outputName="Permeability_advanced_variation_3_Output",
        )

        ## Update 'excess-k power parameter'
        self.__execute_sucessful_process(
            projectPath=PERM_POCO_PROJECT_FILE,
            generateDataOnly=generateDataOnly,
            wellLogsInput="Well_Logs",
            porosityLogInput="PHI_MATRIZ",
            segmentedImageInput="Well_Logs_Segmentation",
            macroPoreSegmentInput="Segment 1",
            ignoredSegmentInput="Segment 5",
            plugsMeasurementsInput="Plugs_Measurement_Table",
            plugsPermeabilityLog="Perm",
            kDsOptimizationIntervals=[[5277.7, 5417.7, 464000.0, 0.75]],
            kDsOptimizationWeight=1.0,
            fractionSmoothingWindowSize=10,
            excessKFractionThreshold=1.0,
            useMatrixKPlugErrorTerm=True,
            excessKPowerParamater=3.5,
            outputName="Permeability_advanced_variation_4_Output",
        )

        # Compare table with/without parameter changes
        if not generateDataOnly:
            outputNodeDefaultAdvancedParam = tryGetNode("Permeability_with_kds_Output_Template")
            outputNode1 = tryGetNode("Permeability_advanced_variation_Output")
            outputNode2 = tryGetNode("Permeability_advanced_variation_2_Output")
            outputNode3 = tryGetNode("Permeability_advanced_variation_3_Output")
            outputNode4 = tryGetNode("Permeability_advanced_variation_4_Output")

            assert outputNodeDefaultAdvancedParam is not None
            assert outputNode1 is not None
            assert outputNode2 is not None
            assert outputNode3 is not None
            assert outputNode4 is not None

            outputDataFrameDefaultParam = dataframeFromTable(outputNodeDefaultAdvancedParam)
            outputDataFrame1 = dataframeFromTable(outputNode1)
            outputDataFrame2 = dataframeFromTable(outputNode2)
            outputDataFrame3 = dataframeFromTable(outputNode3)
            outputDataFrame4 = dataframeFromTable(outputNode4)

            for idx, outputDataFrame in enumerate(
                [outputDataFrame1, outputDataFrame2, outputDataFrame3, outputDataFrame4]
            ):
                try:
                    pd.testing.assert_frame_equal(outputDataFrameDefaultParam, outputDataFrame, check_exact=False)
                except AssertionError:
                    pass  # Expected
                else:
                    raise AssertionError(
                        f"Expected 'outputDataFrame{idx + 1} to be different from 'outputDataFrameDefaultParam'"
                    )
