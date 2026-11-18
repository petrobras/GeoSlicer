from pathlib import Path
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest

RESOURCES_DIR = Path(__file__).parent / "Resources"
SAMPLE_IMAGE_PATH = RESOURCES_DIR / "sample.jpg"


class PpFlowTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def post_setup(self) -> None:
        self._flowWidget = self._module_widget.flowWidget

    def _get_current_step(self):
        return self._flowWidget.steps[self._flowWidget.currentStepIndex]

    def _move_to_smartseg(self):
        loadStep = self._get_current_step()
        loadStep.ppFileSelector.setCurrentPath(SAMPLE_IMAGE_PATH)

        self._flowWidget.navWidget.nextButton.click()
        self._flowWidget.navWidget.skipButton.click()
        self._flowWidget.navWidget.skipButton.click()

    def test_models_presence(self):
        self._move_to_smartseg()
        smartSegStep = self._get_current_step()
        assert smartSegStep.modelComboBox.count > 1

    def test_cleaning_section_visibility(self):
        self._move_to_smartseg()
        smartSegStep = self._get_current_step()
        assert not smartSegStep.cleaningSection.isVisible()
        for i in range(1, smartSegStep.modelComboBox.count):
            smartSegStep.modelComboBox.setCurrentIndex(i)
            assert smartSegStep.cleaningSection.isVisible(), (
                f'Pore cleaning not enable for the "{smartSegStep.modelComboBox.currentText}" model (index {smartSegStep.modelComboBox.currentIndex})'
            )
