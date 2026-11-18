from pathlib import Path

import numpy as np
import slicer

from commons.slicer.helpers import tryGetNode
from commons.slicer.node_attributes import NodeEnvironment
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project
from commons.slicer import metadata

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
TEST_PROJECT_FILE = TEST_RESOURCES_DIR / "TestProject" / "TestProject.mrml"


def mock_module_environment():
    return NodeEnvironment.MICRO_CT.value


class VolumeCalculatorTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def test_compare(self):
        load_project(TEST_PROJECT_FILE)

        # Generating the compare data

        resampleCube1 = tryGetNode("resample_cube_1")
        assert resampleCube1 is not None
        resampleCube2 = tryGetNode("resample_cube_2")
        assert resampleCube2 is not None
        resampleCube3 = tryGetNode("resample_cube_3")
        assert resampleCube3 is not None
        clipCube1 = tryGetNode("clip_cube_1")
        assert clipCube1 is not None
        clipCube2 = tryGetNode("clip_cube_2")
        assert clipCube2 is not None
        clipCube3Clipping = tryGetNode("clip_cube_3_clipping")
        assert clipCube3Clipping is not None
        clipCube3Padding = tryGetNode("clip_cube_3_padding")
        assert clipCube3Padding is not None
        clipCube3ClippingMnemonic = tryGetNode("clip_cube_3_clipping_mnemonic")
        assert clipCube3ClippingMnemonic is not None
        mnemonicTable = tryGetNode("Mnemonic Table")
        assert mnemonicTable is not None

        # Testing calculation with resampling
        self.widgets["formulaLineEdit"].setText("{resample_cube_1}-{resample_cube_2}")
        self.widgets["outputVolumeLineEdit"].setText("resample_cube_3_test")
        calculatePushButton = self.widgets["calculatePushButton"]
        calculatePushButton.clicked()

        resampleCube3Test = tryGetNode("resample_cube_3_test")
        resampleCube3TestArray = slicer.util.arrayFromVolume(resampleCube3Test)
        resampleCube3Array = slicer.util.arrayFromVolume(resampleCube3)
        assert np.array_equal(resampleCube3TestArray, resampleCube3Array)

        # Testing calculation with clipping and padding

        # Clipping

        self.widgets["formulaLineEdit"].setText("{clip_cube_1}-{clip_cube_2}")
        self.widgets["outputVolumeLineEdit"].setText("clip_cube_3_clipping_test")
        calculatePushButton.clicked()

        clipCube3ClippingTest = tryGetNode("clip_cube_3_clipping_test")
        clipCube3ClippingTestArray = slicer.util.arrayFromVolume(clipCube3ClippingTest)
        clipCube3ClippingArray = slicer.util.arrayFromVolume(clipCube3Clipping)
        assert np.array_equal(clipCube3ClippingTestArray, clipCube3ClippingArray)

        # Padding

        self.widgets["formulaLineEdit"].setText("{clip_cube_2}-{clip_cube_1}")
        self.widgets["outputVolumeLineEdit"].setText("clip_cube_3_padding_test")
        calculatePushButton.clicked()

        clipCube3PaddingTest = tryGetNode("clip_cube_3_padding_test")
        clipCube3PaddingTestArray = slicer.util.arrayFromVolume(clipCube3PaddingTest)
        clipCube3PaddingArray = slicer.util.arrayFromVolume(clipCube3Padding)
        assert np.array_equal(clipCube3PaddingTestArray, clipCube3PaddingArray)

        # Testing mnemonics
        self.widgets["mnemonicSelector"].setCurrentNode(mnemonicTable)
        self.widgets["formulaLineEdit"].setText("{cc1}-{cc2}")  # Use of mnemonics
        self.widgets["outputVolumeLineEdit"].setText("clip_cube_3_clipping_mnemonic_test")
        calculatePushButton.clicked()

        clipCube3ClippingMnemonicTest = tryGetNode("clip_cube_3_clipping_mnemonic_test")
        clipCube3ClippingMnemonicTestArray = slicer.util.arrayFromVolume(clipCube3ClippingMnemonicTest)
        clipCube3ClippingMnemonicArray = slicer.util.arrayFromVolume(clipCube3ClippingMnemonic)
        assert np.array_equal(clipCube3ClippingMnemonicTestArray, clipCube3ClippingMnemonicArray)

        # Assert metadata is propagated

        assert metadata.get_node_metadata(resampleCube3Test) == metadata.get_node_metadata(resampleCube3)
        assert metadata.get_node_metadata(clipCube3ClippingTest) == metadata.get_node_metadata(clipCube3Clipping)
        assert metadata.get_node_metadata(clipCube3ClippingMnemonic) == metadata.get_node_metadata(
            clipCube3ClippingMnemonicTest
        )

        # TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        input_itemID = subjectHierarchyNode.GetItemByDataNode(
            resampleCube3
        )  # the hierarchy item ID corresponding to node
        output_itemID = subjectHierarchyNode.GetItemByDataNode(resampleCube3Test)
        assert subjectHierarchyNode.GetItemAttributeNames(input_itemID) == subjectHierarchyNode.GetItemAttributeNames(
            output_itemID
        )
        input_itemID = subjectHierarchyNode.GetItemByDataNode(
            clipCube3Clipping
        )  # the hierarchy item ID corresponding to node
        output_itemID = subjectHierarchyNode.GetItemByDataNode(clipCube3ClippingTest)
        assert subjectHierarchyNode.GetItemAttributeNames(input_itemID) == subjectHierarchyNode.GetItemAttributeNames(
            output_itemID
        )
        input_itemID = subjectHierarchyNode.GetItemByDataNode(
            clipCube3ClippingMnemonic
        )  # the hierarchy item ID corresponding to node
        output_itemID = subjectHierarchyNode.GetItemByDataNode(clipCube3ClippingMnemonicTest)
        assert subjectHierarchyNode.GetItemAttributeNames(input_itemID) == subjectHierarchyNode.GetItemAttributeNames(
            output_itemID
        )
