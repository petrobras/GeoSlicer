from pathlib import Path

import slicer

from commons.slicer.helpers import tryGetNode
from commons.slicer.node_attributes import NodeEnvironment
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, wait

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
TEST_PROJECT_FILE = TEST_RESOURCES_DIR / "TestProject" / "TestProject.mrml"


def mock_module_environment():
    return NodeEnvironment.MICRO_CT.value


class PoreNetworkCompareTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def test_compare(self):
        load_project(TEST_PROJECT_FILE)
        shn = slicer.mrmlScene.GetSubjectHierarchyNode()

        # Generating the compare data

        poreTable = tryGetNode(
            "Dry_reference_scan_segmented_inverted_Inspector_0.025_0.0035_0.0164_LabelMap_pore_table"
        )
        assert poreTable is not None
        poreLabelMap = tryGetNode("Dry_reference_scan_segmented_inverted")
        assert poreLabelMap is not None
        watershedPoreLabelMap = tryGetNode(
            "Dry_reference_scan_segmented_inverted_Inspector_0.025_0.0035_0.0164_LabelMap"
        )
        assert watershedPoreLabelMap is not None
        simulationModelNode = tryGetNode("cycle_node")
        assert simulationModelNode is not None
        drainageLabelmapsFolderItem = shn.GetItemByName("Drainage Oil Segmented")
        assert drainageLabelmapsFolderItem
        imbibitionLabelmapsFolderItem = shn.GetItemByName("Imbibition Oil Segmented")
        assert imbibitionLabelmapsFolderItem

        self.widgets["inputPoreTable"].setCurrentNode(poreTable)
        self.widgets["inputPoreLabelMap"].setCurrentNode(poreLabelMap)
        self.widgets["inputWatershedPoreLabelMap"].setCurrentNode(watershedPoreLabelMap)
        self.widgets["inputCycleNodeModel"].setCurrentNode(simulationModelNode)
        self.widgets["inputDrainageOilLabelmapsFolder"].setCurrentItem(drainageLabelmapsFolderItem)
        self.widgets["inputImbibitionOilLabelmapsFolder"].setCurrentItem(imbibitionLabelmapsFolderItem)
        self.widgets["downsamplingFactorSpinBox"].setValue(0.2)
        self.widgets["numNearestNeighborsSpinBox"].setValue(3)
        self.widgets["outputFolderNameLineEdit"].setText("Test")

        applyButton = self.widgets["applyButton"]
        assert applyButton.enabled
        applyButton.clicked()

        # Visualizing the compare data

        compareResultsFolderItem = shn.GetItemByName("Test")
        assert compareResultsFolderItem

        self.widgets["resultsFolder"].setCurrentItem(compareResultsFolderItem)

        compareButton = self.widgets["compareButton"]
        assert compareButton.enabled
        compareButton.clicked()

        wait(1)

        # Assert if the Pore Network Compare layout is activated
        # layout = slicer.app.layoutManager().layout
        # assert layout >= 10**8, f"Expected layout >= 10**8 but got {layout}"

        # Verifying if the comparison node exist and the layout slice views are populated with it
        sliceWidgets = self._module_widget.logic.getSliceWidgets()

        def checkComparisonNode(nodeName):
            for sliceWidget in sliceWidgets:
                sliceCompositeNode = sliceWidget.sliceLogic().GetSliceCompositeNode()
                comparisonNode = tryGetNode(sliceCompositeNode.GetBackgroundVolumeID())
                assert comparisonNode is not None
                assert comparisonNode.GetName() == nodeName

        # Checking if the node is correct
        checkComparisonNode("0 - Drainage_oil_segmented_001")

        # Going to the last comparison node
        stepSlider = self.widgets["stepSlider"]
        stepSlider.value = stepSlider.maximum

        # Checking if the node is correct
        checkComparisonNode("4 - Imbibition_oil_segmented_416")

        # Verifying if the 3D models exist and are being shown
        realModel = tryGetNode("cycle_node - Real")
        assert realModel is not None
        realViewNodeIds = realModel.GetDisplayNode().GetViewNodeIDs()
        assert len(realViewNodeIds) == 1
        assert realViewNodeIds[0] == "vtkMRMLViewNodePoreNetworkCompare1"
        syntheticModel = tryGetNode("cycle_node - Synthetic")
        assert syntheticModel is not None
        syntheticViewNodeIds = syntheticModel.GetDisplayNode().GetViewNodeIDs()
        assert len(syntheticViewNodeIds) == 1
        assert syntheticViewNodeIds[0] == "vtkMRMLViewNodePoreNetworkCompare2"
