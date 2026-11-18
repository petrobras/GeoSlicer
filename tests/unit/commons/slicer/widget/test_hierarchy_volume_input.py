import sys
from unittest.mock import MagicMock, patch


class TestHierarchyVolumeInput:
    def setup_class(self):
        sys.modules["slicer"].qMRMLSubjectHierarchyComboBox = MagicMock()

    def teardown_class(self):
        sys.modules["slicer"] = MagicMock()

    def setup_method(self):
        with patch("commons.utils.custom_event_filter.CustomEventFilter"):
            from commons.slicer.widget.hierarchy_volume_input import HierarchyVolumeInput

        self.hierarchy_volume_input = HierarchyVolumeInput()

    def test_add_attribute_filter(self):
        self.hierarchy_volume_input.addNodeAttributeIncludeFilter("attr_name", "attrb_value")
        assert self.hierarchy_volume_input.node_attribute_filter_list == [("attr_name", "attrb_value")]
        self.hierarchy_volume_input.selectorWidget.addNodeAttributeFilter.assert_called_with("attr_name", "attrb_value")

    def test_remove_attribute_filter(self):
        self.hierarchy_volume_input.addNodeAttributeIncludeFilter("attr_name", "attrb_value")
        self.hierarchy_volume_input.removeNodeAttributeIncludeFilter("attr_name", "attrb_value")
        assert self.hierarchy_volume_input.node_attribute_filter_list == []
        self.hierarchy_volume_input.selectorWidget.removeNodeAttributeFilter.assert_called_with(
            "attr_name", "attrb_value"
        )

    def test_remove_all_of_one_attribute_filter(self):
        self.hierarchy_volume_input.addNodeAttributeIncludeFilter("attr_name", "attrb_value_0")
        self.hierarchy_volume_input.addNodeAttributeIncludeFilter("attr_name", "attrb_value_1")
        self.hierarchy_volume_input.addNodeAttributeIncludeFilter("attr_name_0", "attrb_value_0")
        self.hierarchy_volume_input.removeNodeAttributeIncludeFilter("attr_name")
        assert self.hierarchy_volume_input.node_attribute_filter_list == [("attr_name_0", "attrb_value_0")]
        self.hierarchy_volume_input.selectorWidget.removeNodeAttributeFilter.assert_called_with("attr_name", True)
