import slicer
import pandas as pd
from commons.slicer.helpers import tryGetNode
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import wait, load_project, save_project, check_for_message_box
from commons.slicer.data_utils import tableNodeToDataFrame
from pathlib import Path

RESOURCES = Path(__file__).parent / "Resources"
HIST_TEMPLATE_PROJECT_FILE = RESOURCES / "HIST_TEMPLATE_PROJECT" / "HIST_TEMPLATE_PROJECT.mrml"
MEAN_TEMPLATE_PROJECT_FILE = RESOURCES / "MEAN_TEMPLATE_PROJECT" / "MEAN_TEMPLATE_PROJECT.mrml"
BASIC_PETROPHYSICS_TEMPLATE_PROJECT_FILE = (
    RESOURCES / "BASIC_PETROPHYSICS_TEMPLATE_PROJECT" / "BASIC_PETROPHYSICS_TEMPLATE_PROJECT.mrml"
)

RELATIVE_TOLERANCE = 1e-03
ABSOLUT_TOLERANCE = 1e-06


class MultipleImageAnalysisTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _histogram_in_depth_process(
        self,
        multipleProjectPathName: str,
        bins: bool = 20,
        parameterLabel: str = "max_feret",
        weightLabel: str = "area",
        normalized: bool = True,
        height: int = 1,
        normalizationLabel: str = "Number of elements",
        templateProjectPath: Path = None,
        templateReportNodeName: str = None,
        generateTestData: bool = False,
    ) -> None:

        if not generateTestData:
            load_project(templateProjectPath)

        analysisTypeComboBox = self.widgets["Analysis Type Combo Box"]
        directoryInputPathLineEdit = self.widgets["Directory Input Path Line Edit"]
        saveButton = self.widgets["Save Button"]
        parameterLabelComboBox = self.widgets["Histogram in Depth Parameter Combo Box"]
        weightLabelComboBox = self.widgets["Histogram in Depth Weight Combo Box"]
        histogramBinSpinBox = self.widgets["Histogram in Depth Bins Spin Box"]
        histogramHeightSpinBox = self.widgets["Histogram in Depth Height Spin Box"]
        normalizationComboBox = self.widgets["Histogram in Depth Normalization Combo Box"]
        normalizeCheckBox = self.widgets["Histogram in Depth Normalize Check Box"]

        analysisTypeComboBox.setCurrentText("Histogram in Depth Analysis")
        histogramBinSpinBox.setValue(bins)
        parameterLabelComboBox.setCurrentText(parameterLabel)
        weightLabelComboBox.setCurrentText(weightLabel or "None")

        if normalized:
            normalizationComboBox.setCurrentText(normalizationLabel)
        else:
            normalizeCheckBox.setChecked(False)
            wait(0.1)
            histogramHeightSpinBox.setValue(height)

        # Trigger analysis generation method
        directoryInputPathLineEdit.setCurrentPath(RESOURCES / multipleProjectPathName)
        wait(0.5)

        saveButton.click()

        wait(0.5)

        name = f"{multipleProjectPathName} {parameterLabel} Histogram in Depth"
        if weightLabel is not None and weightLabel != "None":
            name += f" Weighted by {weightLabel}"

        generatedReportNode = slicer.util.getNode(name)

        if generateTestData and templateReportNodeName:
            generatedReportNode.SetName(templateReportNodeName)
            return

        templateReportNode = slicer.util.getNode(templateReportNodeName)

        generatedReportDf = tableNodeToDataFrame(generatedReportNode)
        templateReportDf = tableNodeToDataFrame(templateReportNode)

        pd.testing.assert_frame_equal(
            generatedReportDf,
            templateReportDf,
            check_exact=False,
            rtol=RELATIVE_TOLERANCE,
            atol=ABSOLUT_TOLERANCE,
        )

    def _mean_in_depth_process(
        self,
        multipleProjectPathName: str,
        parameterLabel: str = "max_feret",
        weightLabel: str = "area",
        templateProjectPath: Path = None,
        templateReportNodeName: str = None,
        generateTestData: bool = False,
    ) -> None:

        if not generateTestData:
            load_project(templateProjectPath)

        analysisTypeComboBox = self.widgets["Analysis Type Combo Box"]
        directoryInputPathLineEdit = self.widgets["Directory Input Path Line Edit"]
        saveButton = self.widgets["Save Button"]
        parameterLabelComboBox = self.widgets["Mean in Depth Parameter Combo Box"]
        weightLabelComboBox = self.widgets["Mean in Depth Weight Combo Box"]

        analysisTypeComboBox.setCurrentText("Mean in Depth Analysis")
        parameterLabelComboBox.setCurrentText(parameterLabel)
        weightLabelComboBox.setCurrentText(weightLabel or "None")

        # Trigger analysis generation method
        directoryInputPathLineEdit.setCurrentPath(RESOURCES / multipleProjectPathName)
        wait(0.5)
        saveButton.click()

        wait(0.5)

        name = f"{multipleProjectPathName} {parameterLabel} Mean in Depth"
        if weightLabel is not None and weightLabel != "None":
            name += f" Weighted by {weightLabel}"

        generatedReportNode = slicer.util.getNode(name)

        if generateTestData and templateReportNodeName:
            generatedReportNode.SetName(templateReportNodeName)
            return

        templateReportNode = slicer.util.getNode(templateReportNodeName)

        generatedReportDf = tableNodeToDataFrame(generatedReportNode)
        templateReportDf = tableNodeToDataFrame(templateReportNode)
        pd.testing.assert_frame_equal(
            generatedReportDf,
            templateReportDf,
            check_exact=False,
            rtol=RELATIVE_TOLERANCE,
            atol=ABSOLUT_TOLERANCE,
        )

    def _basic_petrophysics_process(
        self,
        multipleProjectPathName: str,
        templateProjectPath: Path = None,
        templateReportNodeName: str = None,
        generateTestData: bool = False,
    ) -> None:

        if not generateTestData:
            load_project(templateProjectPath)

        analysisTypeComboBox = self.widgets["Analysis Type Combo Box"]
        directoryInputPathLineEdit = self.widgets["Directory Input Path Line Edit"]
        saveButton = self.widgets["Save Button"]

        analysisTypeComboBox.setCurrentText("Basic Petrophysics Analysis")

        # Trigger analysis generation method
        directoryInputPathLineEdit.setCurrentPath(RESOURCES / multipleProjectPathName)
        wait(0.5)
        saveButton.click()

        wait(0.5)

        name = f"{multipleProjectPathName} Basic Petrophysics"
        generatedReportNode = slicer.util.getNode(name)

        if generateTestData and templateReportNodeName:
            generatedReportNode.SetName(templateReportNodeName)
            return

        templateReportNode = slicer.util.getNode(templateReportNodeName)

        generatedReportDf = tableNodeToDataFrame(generatedReportNode)
        templateReportDf = tableNodeToDataFrame(templateReportNode)

        pd.testing.assert_frame_equal(
            generatedReportDf,
            templateReportDf,
            check_exact=False,
            rtol=RELATIVE_TOLERANCE,
            atol=ABSOLUT_TOLERANCE,
        )

    def test_mean_in_depth(self, generateTestData: bool = False) -> None:
        self._mean_in_depth_process(
            multipleProjectPathName="BUZ",
            parameterLabel="max_feret",
            weightLabel="None",
            templateProjectPath=MEAN_TEMPLATE_PROJECT_FILE,
            templateReportNodeName="Mean_In_Depth_Template",
            generateTestData=generateTestData,
        )

    def test_mean_in_depth_weighted(self, generateTestData: bool = False) -> None:
        self._mean_in_depth_process(
            multipleProjectPathName="BUZ",
            parameterLabel="max_feret",
            weightLabel="area",
            templateProjectPath=MEAN_TEMPLATE_PROJECT_FILE,
            templateReportNodeName="Mean_In_Depth_Weighted_Template",
            generateTestData=generateTestData,
        )

    def test_mean_in_depth_all_columns(self, generateTestData: bool = False) -> None:
        self._mean_in_depth_process(
            multipleProjectPathName="BUZ",
            parameterLabel="All",
            weightLabel="None",
            templateProjectPath=MEAN_TEMPLATE_PROJECT_FILE,
            templateReportNodeName="Mean_In_Depth_All_Columns_Template",
            generateTestData=generateTestData,
        )

    def test_mean_in_depth_all_columns_weighted(self, generateTestData: bool = False) -> None:
        self._mean_in_depth_process(
            multipleProjectPathName="BUZ",
            parameterLabel="All",
            weightLabel="area",
            templateProjectPath=MEAN_TEMPLATE_PROJECT_FILE,
            templateReportNodeName="Mean_In_Depth_All_Columns_Weighted_Template",
            generateTestData=generateTestData,
        )

    def test_mean_with_depth_missing_report_file(self, generateTestData: bool = False) -> None:
        self._mean_in_depth_process(
            multipleProjectPathName="BUZ_WITH_INVALID_DEPTH_PROJECT",
            parameterLabel="max_feret",
            templateProjectPath=MEAN_TEMPLATE_PROJECT_FILE,
            templateReportNodeName="Mean_In_Depth_With_Depth_Missing_Report_File_Template",
            generateTestData=generateTestData,
        )

    def test_histogram_in_depth_default_parameters(self, generateTestData: bool = False) -> None:
        self._histogram_in_depth_process(
            multipleProjectPathName="BUZ",
            templateProjectPath=HIST_TEMPLATE_PROJECT_FILE,
            templateReportNodeName="Histogram_in_Depth_Default_Parameters_Template",
            generateTestData=generateTestData,
        )

    def test_histogram_in_depth_with_depth_missing_report_file(self, generateTestData: bool = False) -> None:
        self._histogram_in_depth_process(
            multipleProjectPathName="BUZ_WITH_INVALID_DEPTH_PROJECT",
            templateProjectPath=HIST_TEMPLATE_PROJECT_FILE,
            templateReportNodeName="Histogram_in_Depth_With_Depth_Missing_Report_File_Template",
            generateTestData=generateTestData,
        )

    def test_histogram_in_depth_custom_parameters(self, generateTestData: bool = False) -> None:
        self._histogram_in_depth_process(
            multipleProjectPathName="BUZ",
            bins=100,
            parameterLabel="angle",
            weightLabel="None",
            templateProjectPath=HIST_TEMPLATE_PROJECT_FILE,
            templateReportNodeName="Histogram_in_Depth_Custom_Parameters_Template",
            generateTestData=generateTestData,
        )

    def test_histogram_in_depth_pore_size_class(self, generateTestData: bool = False) -> None:
        self._histogram_in_depth_process(
            multipleProjectPathName="BUZ",
            parameterLabel="pore_size_class",
            weightLabel="None",
            templateProjectPath=HIST_TEMPLATE_PROJECT_FILE,
            templateReportNodeName="Histogram_in_Depth_Pore_Size_Class_Template",
            generateTestData=generateTestData,
        )

    def test_histogram_in_depth_with_height(self, generateTestData: bool = False) -> None:
        self._histogram_in_depth_process(
            multipleProjectPathName="BUZ",
            normalized=False,
            height=3,
            templateProjectPath=HIST_TEMPLATE_PROJECT_FILE,
            templateReportNodeName="Histogram_in_Depth_With_Height_Template",
            generateTestData=generateTestData,
        )

    def test_inserting_invalid_path_then_analysing(self) -> None:
        analysisTypeComboBox = self.widgets["Analysis Type Combo Box"]
        directoryInputPathLineEdit = self.widgets["Directory Input Path Line Edit"]
        analysisTypeComboBox.setCurrentText("Histogram in Depth Analysis")

        with check_for_message_box("The selected path is invalid. Please select a directory."):
            directoryInputPathLineEdit.setCurrentPath(" ")

        self.test_histogram_in_depth_default_parameters()

    def test_inserting_invalid_project_then_analysing(self) -> None:
        analysisTypeComboBox = self.widgets["Analysis Type Combo Box"]
        directoryInputPathLineEdit = self.widgets["Directory Input Path Line Edit"]
        saveButton = self.widgets["Save Button"]

        analysisTypeComboBox.setCurrentText("Histogram in Depth Analysis")
        directoryInputPathLineEdit.setCurrentPath(RESOURCES / "BasicPetrophysics")

        wait(0.3)

        assert not saveButton.visible, "Save button shouldn't be displayed"

        self.test_histogram_in_depth_default_parameters()

    def test_histogram_in_depth_visualization_parameters(self) -> None:
        analysisTypeComboBox = self.widgets["Analysis Type Combo Box"]
        histogramHeightSpinBox = self.widgets["Histogram in Depth Height Spin Box"]
        normalizeCheckBox = self.widgets["Histogram in Depth Normalize Check Box"]

        analysisTypeComboBox.setCurrentText("Histogram in Depth Analysis")

        # Check 'Normalize' option checked by default
        assert normalizeCheckBox.isChecked(), "Normalize option should be checked by default, but it isn't"

        # Check that 'Histogram Height' option is disabled because of 'Normalize' option
        assert not histogramHeightSpinBox.isEnabled(), (
            "Histogram Height option should be disabled because of 'Normalize' option"
        )

        # Force uncheck from 'Normalize' option to change 'Histogram Height' enablement
        normalizeCheckBox.setChecked(False)
        wait(0.2)
        assert histogramHeightSpinBox.isEnabled(), (
            "Histogram Height option should be enabled because of 'Normalize' option"
        )

    def test_basic_petrophysics(self, generateTestData: bool = False) -> None:
        self._basic_petrophysics_process(
            multipleProjectPathName="BasicPetrophysics",
            templateProjectPath=BASIC_PETROPHYSICS_TEMPLATE_PROJECT_FILE,
            templateReportNodeName="Basic_Petrophysics_Template",
            generateTestData=generateTestData,
        )

    def test_basic_petrophysics_with_depth_missing_report_file(self, generateTestData: bool = False) -> None:
        self._basic_petrophysics_process(
            multipleProjectPathName="BasicPetrophysics_WITH_INVALID_DEPTH_PROJECT",
            templateProjectPath=BASIC_PETROPHYSICS_TEMPLATE_PROJECT_FILE,
            templateReportNodeName="Basic_petrophysics_With_Depth_Missing_Report_File_Template",
            generateTestData=generateTestData,
        )

    def test_multiples_analysis_in_sequence(self) -> None:
        self.test_histogram_in_depth_custom_parameters()
        self.test_mean_in_depth_all_columns()
        self.test_basic_petrophysics()

    def test_cancelling_report_after_changing_path(self) -> None:
        analysisTypeComboBox = self.widgets["Analysis Type Combo Box"]
        directoryInputPathLineEdit = self.widgets["Directory Input Path Line Edit"]
        saveButton = self.widgets["Save Button"]

        analysisTypeComboBox.setCurrentText("Mean in Depth Analysis")

        wait(0.5)

        parameterLabelComboBox = self.widgets["Mean in Depth Parameter Combo Box"]
        weightLabelComboBox = self.widgets["Mean in Depth Weight Combo Box"]
        parameterLabelComboBox.setCurrentText("max_feret")
        weightLabelComboBox.setCurrentText("area")

        # Trigger analysis generation method
        directoryInputPathLineEdit.setCurrentPath(RESOURCES / "BUZ")

        wait(0.5)
        # Check temporary node existance
        assert tryGetNode("Multiple Image Analysis Preview") is not None, "Temporary node should exist"

        assert saveButton.visible, "Save button should be visible"

        # Change path
        with check_for_message_box("The selected path is invalid. Please select a directory."):
            directoryInputPathLineEdit.setCurrentPath(" ")

        wait(0.5)
        # Check temporary node doesn't exist
        assert tryGetNode("Multiple Image Analysis Preview") is None, "Temporary node shouldn't exist"
        assert saveButton.visible is False, "Save button shouldn't be visible"

    def test_cancelling_report_after_changing_module(self) -> None:
        analysisTypeComboBox = self.widgets["Analysis Type Combo Box"]
        directoryInputPathLineEdit = self.widgets["Directory Input Path Line Edit"]
        saveButton = self.widgets["Save Button"]
        parameterLabelComboBox = self.widgets["Histogram in Depth Parameter Combo Box"]
        weightLabelComboBox = self.widgets["Histogram in Depth Weight Combo Box"]

        analysisTypeComboBox.setCurrentText("Histogram in Depth Analysis")
        parameterLabelComboBox.setCurrentText("angle")
        weightLabelComboBox.setCurrentText(None)

        # Trigger analysis generation method
        directoryInputPathLineEdit.setCurrentPath(RESOURCES / "BUZ")

        wait(0.5)
        # Check temporary node existance
        assert tryGetNode("Multiple Image Analysis Preview") is not None, "Temporary node should exist"
        assert saveButton.visible, "Save button should be visible"

        # Simulate module change
        slicer.util.selectModule("")
        self._module_widget.exit()

        wait(0.5)
        # Check temporary node doesn't exist
        assert tryGetNode("Multiple Image Analysis Preview") is None, "Temporary node shouldn't exist"
        assert saveButton.visible is False, "Save button shouldn't be visible"

    def generate_histogram_test_data(self) -> None:
        self.test_histogram_in_depth_default_parameters(generateTestData=True)
        self.test_histogram_in_depth_custom_parameters(generateTestData=True)
        self.test_histogram_in_depth_pore_size_class(generateTestData=True)
        self.test_histogram_in_depth_with_height(generateTestData=True)
        self.test_histogram_in_depth_with_depth_missing_report_file(generateTestData=True)

        wait(0.5)

        assert save_project(project_path=HIST_TEMPLATE_PROJECT_FILE, timeout_ms=15000), (
            "Failed to save generated data to project."
        )

    def generate_mean_test_data(self) -> None:
        self.test_mean_in_depth(generateTestData=True)
        self.test_mean_in_depth_weighted(generateTestData=True)
        self.test_mean_in_depth_all_columns(generateTestData=True)
        self.test_mean_in_depth_all_columns_weighted(generateTestData=True)
        self.test_mean_with_depth_missing_report_file(generateTestData=True)

        wait(0.5)

        assert save_project(project_path=MEAN_TEMPLATE_PROJECT_FILE, timeout_ms=15000), (
            "Failed to save generated data to project."
        )

    def generate_basic_petrophysics_test_data(self) -> None:
        self.test_basic_petrophysics(generateTestData=True)
        self.test_basic_petrophysics_with_depth_missing_report_file(generateTestData=True)

        wait(0.5)

        assert save_project(project_path=BASIC_PETROPHYSICS_TEMPLATE_PROJECT_FILE, timeout_ms=15000), (
            "Failed to save generated data to project."
        )
