from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest


class ThinSectionSegmentInspectorTest(LTracePluginTest):
    def test_has_no_median_surface(self):
        combobox = self._module_widget.methodSelector.selector
        method_names = {combobox.itemText(i) for i in range(combobox.count)}
        self.assertIn("Over-Segmented Watershed", method_names)
        self.assertNotIn("Medial surface segmentation", method_names)
