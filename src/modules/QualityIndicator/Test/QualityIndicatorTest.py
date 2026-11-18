from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, save_project, process_events, wait_cli_to_finish
from commons.slicer.helpers import tryGetNode
from commons.slicer.data_utils import tableNodeToDataFrame
from commons.slicer import metadata

from pathlib import Path
import slicer

from typing import Union

import pandas as pd
import numpy as np


RESOURCES_DIR = Path(__file__).parent / "Resources"
TEST_PROJECT_FILE = RESOURCES_DIR / "ubi_tt" / "ubi_tt.mrml"
TEST_RAW_PROJECT_FILE = RESOURCES_DIR / "raw_ubi_tt" / "raw_ubi_tt.mrml"


class QualityIndicatorTest(LTracePluginTest):
    def _assert_equal(self, node1: slicer.vtkMRMLNode, node2: slicer.vtkMRMLNode) -> None:
        if type(node1) is not type(node2):
            raise ValueError(f"Type mismatch: {type(node1)} != {type(node2)}")

        if isinstance(node1, slicer.vtkMRMLTableNode):
            node1Df = tableNodeToDataFrame(node1)
            node2Df = tableNodeToDataFrame(node2)
            pd.testing.assert_frame_equal(node1Df, node2Df, check_exact=False)
            return

        if isinstance(node1, slicer.vtkMRMLScalarVolumeNode):
            array1 = slicer.util.arrayFromVolume(node1)
            array2 = slicer.util.arrayFromVolume(node2)
            np.testing.assert_almost_equal(array1, array2, decimal=5)
            return

        raise NotImplementedError(f"Unsupported type: {type(node1)}")

    def _process(
        self,
        nodeName: str,
        windowSize: int,
        minimumWavelength: int,
        maximumWavelength: int,
        filteringFactor: float,
        stepLength: float,
        outputPrefix: str,
        outputAsImage: bool,
        generateTestData: bool,
        templateProject: Union[str, Path],
        templateNodeName: str = None,
    ) -> None:
        assert nodeName is not None, "Node cannot be None"

        if not generateTestData:
            load_project(templateProject)

        node = tryGetNode(nodeName)
        assert node, f"Node {nodeName} not found in the scene"

        self.widgets["Transit Time Combo Box"].setCurrentNode(node)
        self.widgets["Window Size Spin Box"].value = windowSize
        self.widgets["Minimum Wavelength Spin Box"].value = minimumWavelength
        self.widgets["Maximum Wavelength Spin Box"].value = maximumWavelength
        self.widgets["Filtering Factor Spin Box"].value = filteringFactor
        self.widgets["Band Spectrum Step Length Spin Box"].value = stepLength
        self.widgets["Output As Image Check Box"].setChecked(outputAsImage)
        self.widgets["Output Prefix Line Edit"].text = outputPrefix if not generateTestData else templateNodeName

        process_events()

        self.widgets["Apply Button"].click()

        process_events()

        cliNode = self._module_widget.logic.cliNode
        assert cliNode is not None

        wait_cli_to_finish(cliNode)

        if generateTestData:
            return

        generatedNode = tryGetNode(f"{outputPrefix}_Quality")
        assert generatedNode is not None, f"Node {outputPrefix} not found in the scene"

        templateNode = tryGetNode(f"{templateNodeName}_Quality")
        assert templateNode is not None, f"Node {templateNodeName} not found in the scene"

        self._assert_equal(generatedNode, templateNode)

        assert metadata.get_node_metadata(generatedNode) == metadata.get_node_metadata(node)

    def test_process_output_as_image(self, generateTestData=False) -> False:
        self._process(
            nodeName="UBI_TT [us]",
            windowSize=40,
            minimumWavelength=4,
            maximumWavelength=100,
            filteringFactor=1.00,
            stepLength=0.020,
            outputPrefix="UBI_TT [us] Image",
            outputAsImage=True,
            generateTestData=generateTestData,
            templateProject=TEST_PROJECT_FILE,
            templateNodeName="UBI_TT [us] Image_Template",
        )

    def test_process_output_as_table(self, generateTestData=False) -> False:
        self._process(
            nodeName="UBI_TT [us]",
            windowSize=40,
            minimumWavelength=4,
            maximumWavelength=100,
            filteringFactor=1.00,
            stepLength=0.020,
            outputPrefix="UBI_TT [us] Table",
            outputAsImage=False,
            generateTestData=generateTestData,
            templateProject=TEST_PROJECT_FILE,
            templateNodeName="UBI_TT [us] Table_Template",
        )

    def generate_test_data(self) -> None:
        load_project(TEST_RAW_PROJECT_FILE)

        self.test_process_output_as_image(generateTestData=True)
        self.test_process_output_as_table(generateTestData=True)

        save_project(project_path=TEST_PROJECT_FILE)
