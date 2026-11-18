import slicer
import numpy as np

from commons.slicer.throat_analysis.throat_analysis import ThroatAnalysis
from commons.slicer.throat_analysis.throat_analysis_generator import ThroatAnalysisGenerator
from commons.slicer_utils import LTracePluginTest
from commons.slicer.tests.utils import wait_cli_to_finish


class ThroatAnalysisTest(LTracePluginTest):
    def create_synthetic_label_map(self, name="TestLabelMap"):
        """Creates a 2D label map with two pores (labels 1 and 2) sharing a boundary."""
        imageSize = (1, 100, 100)
        imageData = np.zeros(imageSize, dtype=np.uint8)

        # Pore 1
        imageData[0, 20:80, 20:50] = 1
        # Pore 2
        imageData[0, 20:80, 50:80] = 2

        labelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", name)
        slicer.util.updateVolumeFromArray(labelMapNode, imageData)

        # Set some spacing
        labelMapNode.SetSpacing(0.1, 0.1, 0.1)

        return labelMapNode

    def test_throat_analysis_logic_single_throat(self):
        """Verifies that ThroatAnalysis correctly identifies a single throat between two pores."""
        labelMapNode = self.create_synthetic_label_map()
        params = {"spacing": labelMapNode.GetSpacing()}

        throatAnalysis = ThroatAnalysis(labelVolume=labelMapNode, params=params, cpu_count=1)

        reportDf = throatAnalysis.throat_report_df
        boundaryArray = throatAnalysis.boundary_labeled_array

        # Verify report
        self.assertIsNotNone(reportDf)
        self.assertEqual(len(reportDf), 1)
        self.assertEqual(reportDf.iloc[0]["ID"], "1-2")

        # Verify boundary array
        self.assertIsNotNone(boundaryArray)
        self.assertEqual(boundaryArray.shape, (1, 100, 100))
        self.assertTrue(np.any(boundaryArray > 0))

        # Check that the boundary is located where pores 1 and 2 meet (column 48-52 approx)
        transitionZone = boundaryArray[0, 20:80, 48:52]
        self.assertTrue(np.any(transitionZone > 0))

    def test_throat_analysis_logic_multiple_throats(self):
        """Verifies that ThroatAnalysis handles multiple throats and duplicated IDs."""
        imageSize = (1, 100, 100)
        imageData = np.zeros(imageSize, dtype=np.uint8)

        # Throat 1: between 1 and 2
        imageData[0, 10:30, 10:40] = 1
        imageData[0, 10:30, 40:70] = 2

        # Throat 2: between 1 and 3
        imageData[0, 40:60, 10:40] = 1
        imageData[0, 40:60, 40:70] = 3

        # Throat 3: another one between 1 and 2 (duplicated ID case)
        imageData[0, 70:90, 10:40] = 1
        imageData[0, 70:90, 40:70] = 2

        labelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "MultiThroatMap")
        slicer.util.updateVolumeFromArray(labelMapNode, imageData)

        params = {"spacing": labelMapNode.GetSpacing()}
        throatAnalysis = ThroatAnalysis(labelVolume=labelMapNode, params=params, cpu_count=1)

        reportDf = throatAnalysis.throat_report_df
        self.assertEqual(len(reportDf), 3)

        ids = reportDf["ID"].tolist()
        self.assertIn("1-3", ids)

        # Verify we have two variations of 1-2 (renamed to 1-2a, 1-2b)
        one_two_ids = [tid for tid in ids if "1-2" in tid]
        self.assertEqual(len(one_two_ids), 2)
        self.assertTrue(any(tid == "1-2a" for tid in one_two_ids))
        self.assertTrue(any(tid == "1-2b" for tid in one_two_ids))

    def test_throat_analysis_generator_integration(self):
        """Tests ThroatAnalysisGenerator and its ability to create and populate Slicer nodes."""
        labelMapNode = self.create_synthetic_label_map("GeneratorTestInput")

        generator = ThroatAnalysisGenerator(
            input_node_id=labelMapNode.GetID(),
            base_name="GeneratorTest",
            hierarchy_folder=0,
            direction=None,
        )

        generator.generate()
        cliNode = generator._ThroatAnalysisGenerator__cli_node
        self.assertIsNotNone(cliNode)
        wait_cli_to_finish(cliNode)

        # Check if nodes were created
        self.assertIsNotNone(generator.throat_table_node_id)
        self.assertIsNotNone(generator.throat_label_map_node_id)

        tableNode = slicer.util.getNode(generator.throat_table_node_id)
        labelMapOutput = slicer.util.getNode(generator.throat_label_map_node_id)

        self.assertIsNotNone(tableNode)
        self.assertIsNotNone(labelMapOutput)

        # Verify table content
        self.assertGreater(tableNode.GetNumberOfRows(), 0)

        # dataFrameToTableNode might name columns differently or keep them.
        # Let's check the column "ID"
        idCol = tableNode.GetTable().GetColumnByName("ID")
        self.assertIsNotNone(idCol)
        self.assertEqual(idCol.GetValue(0), "1-2")

        # Verify label map output
        outputArray = slicer.util.arrayFromVolume(labelMapOutput)
        self.assertTrue(np.any(outputArray > 0))
        self.assertEqual(outputArray.shape, (1, 100, 100))

    def test_throat_analysis_invalid_input(self):
        """Verifies that ThroatAnalysis handles invalid inputs gracefully."""
        # 3D image (more than 1 slice)
        imageSize = (2, 10, 10)
        imageData = np.zeros(imageSize, dtype=np.uint8)
        labelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "3DInput")
        slicer.util.updateVolumeFromArray(labelMapNode, imageData)

        with self.assertRaises(NotImplementedError):
            ThroatAnalysis(labelVolume=labelMapNode, params={}, cpu_count=1)

    def test_throat_analysis_generator_cli(self):
        """Tests ThroatAnalysisGenerator using CLI mode."""
        labelMapNode = self.create_synthetic_label_map("GeneratorCLITestInput")

        generator = ThroatAnalysisGenerator(
            input_node_id=labelMapNode.GetID(),
            base_name="GeneratorCLITest",
            hierarchy_folder=0,
            direction=None,
        )

        generator.generate()

        # Access private member via name mangling as the user asked
        cliNode = generator._ThroatAnalysisGenerator__cli_node
        self.assertIsNotNone(cliNode)

        wait_cli_to_finish(cliNode)

        # After CLI finishes, generator handles the results via observer
        tableNodeId = generator.throat_table_node_id
        tableNode = slicer.util.getNode(tableNodeId)

        self.assertIsNotNone(tableNode)
        self.assertGreater(tableNode.GetNumberOfRows(), 0)

        idCol = tableNode.GetTable().GetColumnByName("ID")
        self.assertIsNotNone(idCol)
        self.assertEqual(idCol.GetValue(0), "1-2")
