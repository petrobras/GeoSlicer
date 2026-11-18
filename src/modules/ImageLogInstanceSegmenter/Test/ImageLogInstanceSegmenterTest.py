import os
import numpy as np
import pandas as pd
import slicer

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import check_for_message_box, load_project, wait_cli_to_finish, save_project, wait
from commons.slicer import helpers
from pathlib import Path
from typing import Union, Optional

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"

WELL_LOG_TT_AMP_PROJECT_FILE = TEST_RESOURCES_DIR / "WellLog_TT_AMP" / "WellLog_TT_AMP.mrml"
ELLIPSES_RAW_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "Ellipses_RAW", "Ellipses_RAW.mrml")
ELLIPSES_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "Ellipses", "Ellipses.mrml")


def setComboBoxIndexByData(comboBox, data):
    for i in range(comboBox.count):
        comboBox.setCurrentIndex(i)
        if comboBox.currentData == data:
            return


def instancesReportAssertClose(currentDf, expectedDf, column, absDifference):
    value1 = currentDf[column][0]
    value2 = expectedDf[column][0]
    assert abs(value1 - value2) <= absDifference, f"Expected: {absDifference} <= {abs(value1 - value2)}"


def populate_widgets(cls):
    """Initialize dictionary with module's interface widgets reference."""

    widgets = {
        "modelComboBox": cls.find_widget("modelComboBox"),
        "sidewallModelSelector": cls.find_widget("sidewallModelSelectorComboBox"),
        "amplitudeImageNodeComboBox": cls.find_widget("sidewallSampleAmplitudeImageNodeComboBox"),
        "transitTimeImageNodeComboBox": cls.find_widget("sidewallSampleTransitTimeImageNodeComboBox"),
        "nominalDepthsPathLineEdit": cls.find_widget("sidewallSampleNominalDepthsPathLineEdit"),
        "depthThresholdSpinBox": cls.find_widget("sidewallSampleDepthThresholdSpinBox"),
        "depthColumnSelectorComboBox": cls.find_widget("depthColumnSelectorComboBox"),
        "outputPrefixLineEdit": cls.find_widget("sidewallSampleOutputPrefixLineEdit"),
        "applyButton": cls.find_widget("sidewallSampleApplyButton"),
        "cancelButton": cls.find_widget("Sidewall Sample Cancel Button"),
        "Islands Preprocessing": cls.find_widget("Islands Preprocessing CheckBox"),
        "Islands Input": cls.find_widget("Islands Segmentation ComboBox"),
        "Islands Minimum Threshold Size": cls.find_widget("Islands Minimum Threshold Size"),
        "Islands Output Prefix Line Edit": cls.find_widget("Islands Output Prefix Line Edit"),
        "Islands Apply Button": cls.find_widget("Islands Apply Button"),
        "Islands Cancel Button": cls.find_widget("Islands Cancel Button"),
        "Snow Preprocessing": cls.find_widget("Snow Preprocessing CheckBox"),
        "Snow Input": cls.find_widget("Snow Segmentation ComboBox"),
        "Snow Smooth Factor": cls.find_widget("Snow Smooth Factor"),
        "Snow Minimum Distance Filter": cls.find_widget("Snow Minimum Distance Filter"),
        "Snow Size Minimum Threshold": cls.find_widget("Snow Size Minimum Threshold"),
        "Snow Output Prefix Line Edit": cls.find_widget("Snow Output Prefix Line Edit"),
        "Snow Apply Button": cls.find_widget("Snow Apply Button"),
        "Snow Cancel Button": cls.find_widget("Snow Cancel Button"),
    }

    for objectName, widget in widgets.items():
        assert widget is not None, f"Failed to find '{objectName}' related widget."

    return widgets


class ImageLogInstanceSegmenterTest(LTracePluginTest):
    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = populate_widgets(self)

    def test_instance_segmenter_outputs_csv(self):
        self.run_instance_segmenter_sidewall("WellLog_nominal_depths.csv")

    def test_instance_segmenter_outputs_xlsx(self):
        self.run_instance_segmenter_sidewall("WellLog_nominal_depths.xlsx")

    def run_instance_segmenter_sidewall(self, fileName):
        """
        Here we are primarily asserting if there are any detections. A bad sign if none is detected, but since the predictive models will be
        upgraded with time, it is no big deal if the number of detections change.
        """
        nodeNamingPrefix = "WellLog"

        load_project(WELL_LOG_TT_AMP_PROJECT_FILE)

        sidewallModelSelector = self._widgets["sidewallModelSelector"]
        sidewallModelSelector.setCurrentText("Petrobras Sidewall Sample Mask RCNN 1")

        ampNode = slicer.util.getNode("AMP")
        self.assertIsNotNone(ampNode)

        ttNode = slicer.util.getNode("TT")
        self.assertIsNotNone(ttNode)

        amplitudeImageNodeComboBox = self._widgets["amplitudeImageNodeComboBox"]
        amplitudeImageNodeComboBox.setCurrentNode(ampNode)

        transitTimeImageNodeComboBox = self._widgets["transitTimeImageNodeComboBox"]
        transitTimeImageNodeComboBox.setCurrentNode(ttNode)

        nominalDepthsPathLineEdit = self._widgets["nominalDepthsPathLineEdit"]
        nominalDepthsFilePath = os.path.join(WELL_LOG_TT_AMP_PROJECT_FILE.parent, fileName)
        nominalDepthsPathLineEdit.setCurrentPath(nominalDepthsFilePath)

        depthSelectorComboBox = self._widgets["depthColumnSelectorComboBox"]
        depthSelectorComboBox.setCurrentText("prof")

        depthThresholdSpinBox = self._widgets["depthThresholdSpinBox"]
        depthThresholdSpinBox.setValue(1)

        outputPrefixLineEdit = self._widgets["outputPrefixLineEdit"]
        outputPrefixLineEdit.setText(nodeNamingPrefix)

        applyButton = self._widgets["applyButton"]
        cancelButton = self._widgets["cancelButton"]

        assert applyButton.enabled is True
        assert cancelButton.enabled is False

        applyButton.clicked()
        wait(0.1)

        assert applyButton.enabled is False
        assert cancelButton.enabled is True

        cli_node = self._module_widget.stackedWidgets.currentWidget().logic.cliNode
        self.assertIsNotNone(cli_node)

        wait_cli_to_finish(cli_node)
        self.assertTrue(cli_node.GetStatusString() == "Completed")

        instancesNode = slicer.util.getNode(nodeNamingPrefix + "_Instances")
        self.assertIsNotNone(instancesNode)
        instancesNodeArray = slicer.util.arrayFromVolume(instancesNode)

        numberOfDetectedInstances = len(np.unique(instancesNodeArray)) - 1  # -1 is to exclude background
        self.assertTrue(numberOfDetectedInstances > 0)

        instancesReportNode = slicer.util.getNode(nodeNamingPrefix + "_Instances_Report")
        self.assertIsNotNone(instancesReportNode)

        expectedInstancesReportNode = slicer.util.getNode(nodeNamingPrefix + "_Instances_Report_Expected")
        self.assertIsNotNone(expectedInstancesReportNode)

        instancesReportDataFrame = slicer.util.dataframeFromTable(instancesReportNode)
        expectedInstancesReportDataFrame = slicer.util.dataframeFromTable(expectedInstancesReportNode)

        for column, absDifference in [
            ["depth (m)", 1],
            ["n depth (m)", 0],
            ["diam (cm)", 0.05],
            ["circularity", 0.05],
            ["azimuth (°)", 1],
            ["label", 0],
        ]:
            instancesReportAssertClose(
                currentDf=instancesReportDataFrame,
                expectedDf=expectedInstancesReportDataFrame,
                column=column,
                absDifference=absDifference,
            )

        assert applyButton.enabled is True
        assert cancelButton.enabled is False

    def _islands_instance_segmentation_process(
        self, projectPath: Union[str, Path], segmentationNode: str, outputPrefix: str, minThresholdSize: float
    ):
        load_project(projectPath)

        modelComboBox = self._widgets["modelComboBox"]
        setComboBoxIndexByData(modelComboBox, "ImageLogIslands")

        inputNode = slicer.util.getNode(segmentationNode)
        assert inputNode is not None

        inputNodeComboBox = self._widgets["Islands Input"]
        inputNodeComboBox.setCurrentNode(inputNode)

        depthThresholdSpinBox = self._widgets["Islands Minimum Threshold Size"]
        depthThresholdSpinBox.setValue(minThresholdSize)

        preprocessingCheckbox = self._widgets["Snow Preprocessing"]
        assert preprocessingCheckbox.isChecked() is True

        outputPrefixLineEdit = self._widgets["Islands Output Prefix Line Edit"]
        outputPrefixLineEdit.setText(outputPrefix)

        applyButton = self._widgets["Islands Apply Button"]
        cancelButton = self._widgets["Islands Cancel Button"]

        assert applyButton.enabled is True
        assert cancelButton.enabled is False
        applyButton.clicked()

        cliNode = self._module_widget.stackedWidgets.currentWidget().logic.cliNode
        assert cliNode is not None

        wait(0.1)
        assert applyButton.enabled is False
        assert cancelButton.enabled is True

        wait_cli_to_finish(cliNode)
        assert cliNode.GetStatusString() == "Completed", f"CLI error: {cliNode.GetErrorText()}"

        instancesNode = slicer.util.getNode(f"{outputPrefix}_Instances")
        assert instancesNode is not None

        instancesNodeArray = slicer.util.arrayFromVolume(instancesNode)

        numberOfDetectedInstances = len(np.unique(instancesNodeArray)) - 1  # -1 is to exclude background
        assert numberOfDetectedInstances > 0

        assert applyButton.enabled is True
        assert cancelButton.enabled is False

    def _snow_instance_segmentation_process(
        self,
        projectPath: Union[str, Path],
        segmentationNode: str,
        outputPrefix: str,
        smoothFactor: float,
        minDistanceFilter: float,
        minThresholdSize: float,
        message: Optional[str] = None,
    ):
        load_project(projectPath)

        modelComboBox = self._widgets["modelComboBox"]
        setComboBoxIndexByData(modelComboBox, "ImageLogSnow")

        inputNode = slicer.util.getNode(segmentationNode)
        assert inputNode is not None

        inputNodeComboBox = self._widgets["Snow Input"]
        inputNodeComboBox.setCurrentNode(inputNode)

        depthThresholdSpinBox = self._widgets["Snow Smooth Factor"]
        depthThresholdSpinBox.setValue(smoothFactor)

        preprocessingCheckbox = self._widgets["Snow Preprocessing"]
        assert preprocessingCheckbox.isChecked() is True

        depthThresholdSpinBox = self._widgets["Snow Minimum Distance Filter"]
        depthThresholdSpinBox.setValue(minDistanceFilter)

        depthThresholdSpinBox = self._widgets["Snow Size Minimum Threshold"]
        depthThresholdSpinBox.setValue(minThresholdSize)

        outputPrefixLineEdit = self._widgets["Snow Output Prefix Line Edit"]
        outputPrefixLineEdit.setText(outputPrefix)

        applyButton = self._widgets["Snow Apply Button"]
        cancelButton = self._widgets["Snow Cancel Button"]
        assert applyButton.enabled is True
        assert cancelButton.enabled is False

        if message:
            with check_for_message_box(message, timeout_sec=120):
                applyButton.clicked()
                cliNode = self._module_widget.stackedWidgets.currentWidget().logic.cliNode
                wait(0.1)
                assert applyButton.enabled is False
                assert cancelButton.enabled is True
                wait_cli_to_finish(cliNode)

        else:
            applyButton.clicked()

            cliNode = self._module_widget.stackedWidgets.currentWidget().logic.cliNode
            assert cliNode is not None

            wait(0.1)
            assert applyButton.enabled is False
            assert cancelButton.enabled is True

            wait_cli_to_finish(cliNode)
            assert cliNode.GetStatusString() == "Completed", f"CLI error: {cliNode.GetErrorText()}"

            instancesNode = slicer.util.getNode(f"{outputPrefix}_Instances")
            assert instancesNode is not None

            instancesNodeArray = slicer.util.arrayFromVolume(instancesNode)

            numberOfDetectedInstances = len(np.unique(instancesNodeArray)) - 1  # -1 is to exclude background
            assert numberOfDetectedInstances > 0

        assert applyButton.enabled is True
        assert cancelButton.enabled is False

    def generate_ellipses_project(self):
        self._islands_instance_segmentation_process(
            projectPath=ELLIPSES_RAW_PROJECT_FILE,
            segmentationNode="Segmentation",
            outputPrefix="Output_Template_Island",
            minThresholdSize=5.00,
        )

        self._snow_instance_segmentation_process(
            projectPath=ELLIPSES_RAW_PROJECT_FILE,
            segmentationNode="Segmentation",
            outputPrefix="Output_Template_Snow",
            smoothFactor=0.00,
            minDistanceFilter=5,
            minThresholdSize=1.0,
        )
        assert save_project(project_path=ELLIPSES_PROJECT_FILE), "Failed to save generated data to project."

    def test_islands_segmentation_ellipses(self):
        segmentationNode = "Segmentation"
        outputPrefix = "Output"

        self._islands_instance_segmentation_process(
            projectPath=ELLIPSES_PROJECT_FILE,
            segmentationNode=segmentationNode,
            outputPrefix=outputPrefix,
            minThresholdSize=5.00,
        )
        currentReportNode = slicer.util.getNode(outputPrefix + "_Instances_Report")
        assert currentReportNode is not None

        templateReportNode = slicer.util.getNode(outputPrefix + "_Template_Island_Instances_Report")
        assert templateReportNode is not None

        currentRepportDataFrame = slicer.util.dataframeFromTable(currentReportNode)
        templateReportDataFrame = slicer.util.dataframeFromTable(templateReportNode)

        pd.testing.assert_frame_equal(currentRepportDataFrame, templateReportDataFrame, check_exact=False)

    def test_snow_segmentation_ellipses(self):
        segmentationNode = "Segmentation"
        outputPrefix = "Output"

        self._snow_instance_segmentation_process(
            projectPath=ELLIPSES_PROJECT_FILE,
            segmentationNode=segmentationNode,
            outputPrefix=outputPrefix,
            smoothFactor=0.00,
            minDistanceFilter=5,
            minThresholdSize=1.0,
        )
        currentReportNode = slicer.util.getNode(outputPrefix + "_Instances_Report")
        assert currentReportNode is not None

        templateReportNode = slicer.util.getNode(outputPrefix + "_Template_Snow_Instances_Report")
        assert templateReportNode is not None

        currentRepportDataFrame = slicer.util.dataframeFromTable(currentReportNode)
        templateReportDataFrame = slicer.util.dataframeFromTable(templateReportNode)

        pd.testing.assert_frame_equal(currentRepportDataFrame, templateReportDataFrame, check_exact=False)

    def test_snow_segmentation_ellipses_message_without_correct_parameters(self):
        segmentationNode = "Segmentation"
        outputPrefix = "Output"

        self._snow_instance_segmentation_process(
            projectPath=ELLIPSES_PROJECT_FILE,
            segmentationNode=segmentationNode,
            outputPrefix=outputPrefix,
            smoothFactor=1.00,
            minDistanceFilter=5,
            minThresholdSize=1.0,
            message="No instances were detected.",
        )

        assert helpers.tryGetNode(outputPrefix + "_Instances_Report") is None
