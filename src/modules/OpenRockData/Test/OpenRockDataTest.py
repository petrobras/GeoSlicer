import slicer
import time

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import wait, process_events, check_for_message_box


class OpenRockDataTest(LTracePluginTest):
    def DISABLE_test_load_s1(self):
        tree = self._module_widget.tree
        item = tree.invisibleRootItem().child(1).child(3)  # ICL Sandstone Carbonate 2009 > S1
        tree.setCurrentItem(item)
        self._module_widget.downloadButton.click()
        process_events()

        assert self._module_widget.is_downloading, "Download did not start as expected"

        timeoutSeconds = 60

        startTime = time.perf_counter()
        try:
            with check_for_message_box(
                "Error: Dataset could not be loaded",
                timeout_sec=timeoutSeconds + 5,
                should_accept=True,
            ):
                while self._module_widget.is_downloading:
                    if time.perf_counter() - startTime > timeoutSeconds:
                        raise AssertionError("Download timed out")
                    wait(1)
        except AttributeError:
            pass  # No error dialog appeared — download completed without error

        node = slicer.mrmlScene.GetFirstNodeByName("S1")
        assert node is not None, "S1 volume node was not loaded (download may have failed)"
        array = slicer.util.arrayFromVolume(node)
        self.assertEqual(array.sum(), 23184825)
