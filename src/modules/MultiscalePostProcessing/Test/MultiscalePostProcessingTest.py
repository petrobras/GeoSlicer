from pathlib import Path

import numpy as np
import qt
import slicer
from commons.slicer.helpers import tryGetNode
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, process_events

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
MULTISCALE_PROJECT_FILE = TEST_RESOURCES_DIR / "MULTISCALEPOSTPROCESSING" / "MULTISCALEPOSTPROCESSING.mrml"


class MultiscalePostProcessingTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = {
            "method_combo_box": self.find_widget("methodComboBox"),
            ## Frequency
            # input
            "realization_node_combo_box": self.find_widget("realizationNodeComboBox"),
            "training_image_combo_box": self.find_widget("trainingImageComboBox"),
            # parameters
            "porosity_value_spin_box": self.find_widget("porosityValueSpinBox"),
            "segment_list": self.find_widget("Segment List"),
            ## PSD
            # input
            "psd_table_combo_box": self.find_widget("psdTableComboBox"),
            "psd_ti_table_combo_box": self.find_widget("psdTiTableComboBox"),
            # Output
            "output_prefix": self.find_widget("outputPrefix"),
            "apply_button": self.find_widget("applyButton"),
        }

    def tear_down(self):
        pass

    def test_interface_default_values(self):
        assert self._widgets["method_combo_box"].currentText == "Multiscale porosity per realization"
        assert self._widgets["realization_node_combo_box"].currentNode() is None
        assert self._widgets["training_image_combo_box"].currentNode() is None
        assert self._widgets["porosity_value_spin_box"].value == 0
        assert self._widgets["psd_table_combo_box"].currentNode() is None
        assert self._widgets["psd_ti_table_combo_box"].currentNode() is None
        assert self._widgets["output_prefix"].text == ""
        assert self._widgets["apply_button"].enabled is False

    def test_porosity_per_realization_scalar(self):
        realizationNodeComboBox = self._widgets["realization_node_combo_box"]
        trainingImageComboBox = self._widgets["training_image_combo_box"]
        porosityValueSpinBox = self._widgets["porosity_value_spin_box"]
        outputPrefix = self._widgets["output_prefix"]
        applyButton = self._widgets["apply_button"]

        load_project(project_file_path=MULTISCALE_PROJECT_FILE)

        proxyNode = tryGetNode("hard data - 32_multiscale_proxy")
        assert proxyNode is not None
        trainingImageNode = tryGetNode("training image - 32")
        assert trainingImageNode is not None

        realizationNodeComboBox.setCurrentNode(proxyNode)
        trainingImageComboBox.setCurrentNode(trainingImageNode)
        porosityValueSpinBox.value = 1
        outputPrefix.text = "test"

        applyButton.clicked()
        process_events()

        tableNode = tryGetNode(outputPrefix.text)
        assert tableNode is not None

        tiTableNode = tryGetNode(f"{outputPrefix.text}_TI")
        assert tiTableNode is not None

    def test_porosity_per_realization_labelmap(self):
        realizationNodeComboBox = self._widgets["realization_node_combo_box"]
        trainingImageComboBox = self._widgets["training_image_combo_box"]
        segmentList = self._widgets["segment_list"]
        outputPrefix = self._widgets["output_prefix"]
        applyButton = self._widgets["apply_button"]

        # Create sequence of labelmaps for input
        n = 5
        SequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "sequence example")
        for i in range(n):
            labelmapArray = np.random.randint(4, size=(20, 1, 100))
            labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", f"label_{i}")
            slicer.util.updateVolumeFromArray(labelmapNode, labelmapArray.astype(np.int32))
            labelmapNode.SetOrigin(0, 0, -1000000)
            labelmapNode.SetIJKToRASDirections(-1, 0, 0, 0, -1, 0, 0, 0, -1)

            SequenceNode.SetDataNodeAtValue(labelmapNode, str(i))

        browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "browser example")
        browserNode.SetAndObserveMasterSequenceNodeID(SequenceNode.GetID())

        # Create mock training image input
        tiArray = np.random.randint(4, size=(20, 1, 100))
        tiNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", f"label_{i}")
        slicer.util.updateVolumeFromArray(tiNode, tiArray.astype(np.int32))
        tiNode.SetOrigin(0, 0, -1000050)
        tiNode.SetIJKToRASDirections(-1, 0, 0, 0, -1, 0, 0, 0, -1)

        proxyNode = tryGetNode("sequence example")
        assert proxyNode is not None

        realizationNodeComboBox.setCurrentNode(proxyNode)
        assert segmentList.count == 3
        segmentList.item(0).setCheckState(qt.Qt.Checked)

        trainingImageComboBox.setCurrentNode(tiNode)

        outputPrefix.text = "test"

        applyButton.clicked()
        process_events()

        resultTable = tryGetNode(outputPrefix.text)
        assert resultTable is not None
        tiTable = tryGetNode(f"{outputPrefix.text}_TI")
        assert tiTable is not None

        assert resultTable.GetNodeReference("TrainingImagePorosityTable") == tiTable, (
            f"Expected result table to have ti table {tiTable.GetName()} as reference, but has {resultTable.GetNodeReference('TrainingImagePorosityTable').GetName()} instead"
        )

        df = slicer.util.dataframeFromTable(resultTable)
        assert df.shape[1] == n + 1, f"Expected {n + 1} columns, but result table has {df.shape[1]} columns"
        depthList = list(df["DEPTH"])
        assert len(depthList) == proxyNode.GetImageData().GetDimensions()[2], (
            f"Expected {proxyNode.GetImageData().GetDimensions()[2]}, got {len(depthList)}"
        )
        assert depthList[0] == -proxyNode.GetOrigin()[2], (
            f"Expected start depth {-proxyNode.GetOrigin()[2]}, got {depthList[0]} instead"
        )

        expectedEndDepth = (
            -proxyNode.GetOrigin()[2] + (proxyNode.GetImageData().GetDimensions()[2] - 1) * proxyNode.GetSpacing()[2]
        )
        assert depthList[-1] == expectedEndDepth, f"Expected end depth {expectedEndDepth}, got {depthList[-1]} instead"

    def test_porosity_per_realization_labelmap_inverted(self):
        realizationNodeComboBox = self._widgets["realization_node_combo_box"]
        segmentList = self._widgets["segment_list"]
        outputPrefix = self._widgets["output_prefix"]
        applyButton = self._widgets["apply_button"]

        n = 5
        SequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "sequence example")
        for i in range(n):
            labelmapArray = np.random.randint(4, size=(100, 1, 20))
            labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", f"label_{i}")
            slicer.util.updateVolumeFromArray(labelmapNode, labelmapArray.astype(np.int32))
            labelmapNode.SetOrigin(0, 0, -1000000)

            SequenceNode.SetDataNodeAtValue(labelmapNode, str(i))

        browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "browser example")
        browserNode.SetAndObserveMasterSequenceNodeID(SequenceNode.GetID())

        proxyNode = tryGetNode("sequence example")
        assert proxyNode is not None

        realizationNodeComboBox.setCurrentNode(proxyNode)
        assert segmentList.count == 3
        segmentList.item(0).setCheckState(qt.Qt.Checked)

        outputPrefix.text = "test"

        applyButton.clicked()
        process_events()

        tableNode = tryGetNode(outputPrefix.text)
        assert tableNode is not None

        df = slicer.util.dataframeFromTable(tableNode)
        depthList = list(df["DEPTH"])
        assert len(depthList) == proxyNode.GetImageData().GetDimensions()[2], (
            f"Expected {proxyNode.GetImageData().GetDimensions()[2]}, got {len(depthList)}"
        )

        expectedStartDepth = (
            -proxyNode.GetOrigin()[2] - (proxyNode.GetImageData().GetDimensions()[2] - 1) * proxyNode.GetSpacing()[2]
        )
        assert depthList[0] == expectedStartDepth, (
            f"Expected start depth {expectedStartDepth}, got {depthList[0]} instead"
        )
        expectedEndDepth = -proxyNode.GetOrigin()[2]
        assert depthList[-1] == expectedEndDepth, f"Expected end depth {expectedEndDepth}, got {depthList[-1]} instead"

    def test_pore_size_distribution(self):
        method_combo_box = self._widgets["method_combo_box"]
        psd_table_combo_box = self._widgets["psd_table_combo_box"]
        output_prefix = self._widgets["output_prefix"]
        apply_button = self._widgets["apply_button"]

        load_project(project_file_path=MULTISCALE_PROJECT_FILE)

        proxy_node = tryGetNode("PSD_proxy")
        assert proxy_node is not None

        method_combo_box.setCurrentText("Pore size distribution")

        psd_table_combo_box.setCurrentNode(proxy_node)
        output_prefix.text = "test_output"

        apply_button.clicked()
        process_events()

        table_node = tryGetNode(f"{output_prefix.text}_proxy")
        assert table_node is not None
        browser_node = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(table_node)
        assert browser_node is not None
        sequence_node = browser_node.GetSequenceNode(table_node)
        assert sequence_node is not None
        assert sequence_node.GetNumberOfDataNodes() == 5
