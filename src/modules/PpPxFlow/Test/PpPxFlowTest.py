from pathlib import Path
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import wait_cli_to_finish

import slicer

RESOURCES_DIR = Path(__file__).parent / "Resources"
PP_IMAGE_PATH = RESOURCES_DIR / "sample_pp.jpg"
PX_IMAGE_PATH = RESOURCES_DIR / "sample_px.jpg"


class PpPxFlowTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def post_setup(self) -> None:
        self._flowWidget = self._module_widget.flowWidget

    def _get_current_step(self):
        return self._flowWidget.steps[self._flowWidget.currentStepIndex]

    def _move_to_smartseg(self):
        loadStep = self._get_current_step()
        loadStep.ppFileSelector.setCurrentPath(PP_IMAGE_PATH)
        loadStep.pxFileSelector.setCurrentPath(PX_IMAGE_PATH)

        self._flowWidget.navWidget.nextButton.click()
        self._flowWidget.navWidget.skipButton.click()
        self._flowWidget.navWidget.skipButton.click()
        self._flowWidget.navWidget.skipButton.click()

    def test_smartseg_running(self):
        self._move_to_smartseg()

        smartSegStep = self._get_current_step()
        smartSegStep.modelComboBox.setCurrentIndex(1)

        self._flowWidget.navWidget.nextButton.click()
        wait_cli_to_finish(smartSegStep.cliQueue)

        outputNode = slicer.util.getNode(PP_IMAGE_PATH.stem + "_Segmentation")
        assert outputNode is not None, "No output was generated!"
        assert self._get_current_step().TITLE == "Manual Seg", "The flow did not advance to the next step!"

    def test_cleaning_section_visibility(self):
        self._move_to_smartseg()
        smartSegStep = self._get_current_step()
        for i in range(smartSegStep.modelComboBox.count):
            smartSegStep.modelComboBox.setCurrentIndex(i)
            assert not smartSegStep.cleaningSection.isVisible(), (
                f'Pore cleaning enable for the "{smartSegStep.modelComboBox.currentText}" model (index {smartSegStep.modelComboBox.currentIndex})'
            )
