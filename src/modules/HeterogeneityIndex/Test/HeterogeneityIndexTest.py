import slicer
import pandas as pd
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, process_events
from commons.slicer.data_utils import tableNodeToDataFrame
from commons.slicer import metadata
from pathlib import Path


RESOURCES = Path(__file__).parent / "Resources"
PROJECT_FILE = RESOURCES / "HI_Test" / "HI_Test.mrml"


class HeterogeneityIndexTest(LTracePluginTest):
    MODULE_NAME = "HeterogeneityIndex"

    def test_heterogeneity_index(self):
        load_project(PROJECT_FILE)

        applyButton = self.widgets["applyButton"]
        self.assertFalse(applyButton.enabled)

        inputSelector = self.widgets["inputSelector"]
        outputPrefixLineEdit = self.widgets["outputPrefixLineEdit"]

        input_node = slicer.mrmlScene.GetFirstNodeByName("Amplitude")
        self.assertIsNotNone(input_node, "Input node 'Amplitude' not found in the project.")

        inputSelector.setCurrentNode(input_node)
        process_events()
        self.assertTrue(applyButton.enabled)

        outputPrefixLineEdit.setText("TestGenerated")

        applyButton.click()

        # Get generated output table
        generated_output_node = slicer.mrmlScene.GetFirstNodeByName("TestGenerated_HI")
        self.assertIsNotNone(generated_output_node, "Generated output node 'TestGenerated_HI' was not created.")
        generated_df = tableNodeToDataFrame(generated_output_node)

        # Get reference table node
        reference_output_node = slicer.mrmlScene.GetFirstNodeByName("Amplitude_HI")
        self.assertIsNotNone(reference_output_node, "Reference output node 'Amplitude_HI' not found in the project.")
        reference_df = tableNodeToDataFrame(reference_output_node)

        # Compare the results
        pd.testing.assert_frame_equal(generated_df, reference_df, check_dtype=True, atol=1e-4)

        # Verify metadata propagation

        assert metadata.get_node_metadata(generated_output_node) == metadata.get_node_metadata(input_node)

        # TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        input_itemID = subjectHierarchyNode.GetItemByDataNode(input_node)  # the hierarchy item ID corresponding to node
        output_itemID = subjectHierarchyNode.GetItemByDataNode(generated_output_node)
        assert subjectHierarchyNode.GetItemAttributeNames(input_itemID) == subjectHierarchyNode.GetItemAttributeNames(
            output_itemID
        )

        assert input_node.GetNumberOfNodeReferences(
            "referenceImageGeometryRef"
        ) == generated_output_node.GetNumberOfNodeReferences("referenceImageGeometryRef")
        assert input_node.GetNumberOfNodeReferences(
            "referenceVolume"
        ) == generated_output_node.GetNumberOfNodeReferences("referenceVolume")
