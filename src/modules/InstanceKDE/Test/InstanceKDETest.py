import numpy as np
import slicer
from pathlib import Path

from commons.slicer import helpers
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import check_for_message_box, load_project, process_events

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
TEST_PROJECT_FILE = TEST_RESOURCES_DIR / "WellLog_TT_AMP" / "WellLog_TT_AMP.mrml"


class InstanceKDETest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = {
            "instance_report_table_selector": self.find_widget("Instance Report Table Selector"),
            "property_combo_box": self.find_widget("Property Combo Box"),
            "depth_spin_box": self.find_widget("Depth Spin Box"),
            "bandwith_spin_box": self.find_widget("Bandwith Spin Box"),
            "apply_button": self.find_widget("Apply Button"),
            "output_prefix_line_edit": self.find_widget("Output Prefix Line Edit"),
        }

    def tear_down(self):
        pass

    def test_default_interface_configuration(self):
        instanceReportTableSelector = self._widgets["instance_report_table_selector"]
        propertyComboBox = self._widgets["property_combo_box"]
        depthSpinBox = self._widgets["depth_spin_box"]
        bandwithSpinBox = self._widgets["bandwith_spin_box"]
        applyButton = self._widgets["apply_button"]
        outputPrefixLineEdit = self._widgets["output_prefix_line_edit"]

        assert instanceReportTableSelector.currentNode() is None
        assert propertyComboBox.count == 0
        assert depthSpinBox.value == 0.1
        assert bandwithSpinBox.value == 0.2
        assert not applyButton.enabled
        assert outputPrefixLineEdit.enabled
        assert outputPrefixLineEdit.text == ""

    def test_generate_kde_table(self):
        instanceReportTableSelector = self._widgets["instance_report_table_selector"]
        propertyComboBox = self._widgets["property_combo_box"]
        depthSpinBox = self._widgets["depth_spin_box"]
        bandwithSpinBox = self._widgets["bandwith_spin_box"]
        applyButton = self._widgets["apply_button"]
        outputPrefixLineEdit = self._widgets["output_prefix_line_edit"]

        instanceProject = TEST_PROJECT_FILE
        load_project(instanceProject)

        def groupValues(depths, depthRange=0.1):
            groups = []
            currentDepth = min(depths)
            while currentDepth <= max(depths):
                if np.any((depths >= currentDepth) & (depths <= currentDepth + depthRange)):
                    groups.append(currentDepth + depthRange)

                currentDepth += depthRange
            return np.round(np.array(groups), 2)

        reportNode = slicer.util.getNode("WellLog_Instances_Report_Expected")
        depths = slicer.util.arrayFromTableColumn(reportNode, "depth (m)")
        groupedDepths = groupValues(depths, depthSpinBox.value)

        instanceReportTableSelector.setCurrentNode(reportNode)

        outputExpectedName = (
            f"{reportNode.GetName()}_KDE_{propertyComboBox.currentText}_{depthSpinBox.value}_{bandwithSpinBox.value}"
        )
        assert outputPrefixLineEdit.text == outputExpectedName, (
            f"Expected {outputExpectedName}, got {outputPrefixLineEdit.text}"
        )

        applyButton.clicked()

        kdeTable = helpers.tryGetNode(outputExpectedName)
        assert kdeTable is not None, f"Expected table node {outputExpectedName} to exist"

        kdeDF = slicer.util.dataframeFromTable(kdeTable)
        kdeDepths = np.round(kdeDF["DEPTH(m)"].to_numpy() / 1000, 2)

        assert np.array_equal(groupedDepths, kdeDepths), f"report depths:{groupedDepths}, KDE depths:{kdeDepths}"

    def test_invalid_report_table(self):
        instanceReportTableSelector = self._widgets["instance_report_table_selector"]
        propertyComboBox = self._widgets["property_combo_box"]
        applyButton = self._widgets["apply_button"]

        instanceProject = TEST_PROJECT_FILE
        load_project(instanceProject)

        oneLineReportNode = slicer.util.getNode("WellLog_Instances_Report_Expected_Invalid")
        instanceReportTableSelector.setCurrentNode(oneLineReportNode)
        process_events()

        propertyComboBox.setCurrentText("insc diam (mm)")

        with check_for_message_box(
            f"An issue occurred during execution. Check if '{oneLineReportNode.GetName()}' table has enough data and if its correct.",
            timeout_sec=10,
        ):
            applyButton.clicked()
