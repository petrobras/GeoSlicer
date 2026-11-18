import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import slicer
from commons.screenshot.Screenshot import ScreenshotWidget
from commons.slicer.helpers import tryGetNode
from commons.slicer_utils import LTracePluginTest
from commons.slicer.tests.utils import load_project, wait, process_events, loadEnvironmentByName
from commons.slicer import helpers

SCREENSHOT_PROJECT_FILE = Path(__file__).parent / "Resources" / "SCREENSHOT" / "SCREENSHOT.mrml"


class ScreenshotTest(LTracePluginTest):
    def run_screenshot(self, option: str) -> None:
        screenshotWidget = ScreenshotWidget()
        viewComboBox = screenshotWidget.viewCombobox
        viewComboBox.setCurrentIndex(0)
        viewComboBox.setCurrentText(option)
        process_events()

        fileName = option.replace(" ", "_")
        filePath = self.tempDirectory / f"{fileName}.png"
        with patch("qt.QFileDialog.getSaveFileName") as mockTempPath:
            mockTempPath.return_value = filePath.as_posix()
            with patch("commons.screenshot.Screenshot.ScreenshotWidget.accept") as mockAccept:
                mockAccept.return_value = None
                screenshotWidget.onSaveAs()

        process_events()
        assert filePath.exists(), f"Expected {filePath} to exist, but was not found"

    def post_setup(self) -> None:
        self.tempDirectory = Path(tempfile.TemporaryDirectory().name)
        self.tempDirectory.mkdir(parents=True, exist_ok=True)

    def tear_down(self) -> None:
        shutil.rmtree(self.tempDirectory, onexc=helpers.make_directory_writable)

    def test_views_options(self):
        """
        Tests widget expected behavior, asserting counts of available option and widget enabled options update
        """
        loadEnvironmentByName("Well Logs")

        # Load a project with a view
        load_project(project_file_path=SCREENSHOT_PROJECT_FILE)
        wait(1)  # Wait imagelog load views with volume

        table = tryGetNode("TEST_TABLE")

        ImageLogDataWidget = slicer.modules.ImageLogDataWidget
        ImageLogDataWidget.addView()
        ImageLogDataWidget.logic.primaryNodeChanged(1, table)  # Add graphic to imagelog view
        ImageLogDataWidget.logic.refreshViews()
        wait(1)  # Wait for view to load change

        screenshotWidget = ScreenshotWidget()
        viewComboBox = screenshotWidget.viewCombobox
        viewComboBox.setCurrentIndex(0)
        viewComboBox.setCurrentText(table.GetName())
        process_events()

        assert viewComboBox.count == 6, f"Expected 6 itens, but got {viewComboBox.count}"

        screenshotOptions = (
            [screenshotWidget.THREED_VIEW_OPTION] + screenshotWidget.VIEW_OPTION + ["TEST_VOLUME", "TEST_TABLE"]
        )

        for index in range(0, viewComboBox.count):
            assert viewComboBox.itemText(index) in screenshotOptions, (
                f"Expected {viewComboBox.itemText(index)} to be in {screenshotOptions}"
            )

        assert screenshotWidget.annotationsOptionsWidget.enabled is False, (
            f"Expected to be False, but got {screenshotWidget.annotationsOptionsWidget.enabled}"
        )

    def test_export_graphic_view(self):
        """
        Tests ImageLog Graphic View Screenshot Export
        """
        loadEnvironmentByName("Well Logs")

        load_project(project_file_path=SCREENSHOT_PROJECT_FILE)
        wait(1)

        table = tryGetNode("TEST_TABLE")

        ImageLogDataWidget = slicer.modules.ImageLogDataWidget
        ImageLogDataWidget.logic.primaryNodeChanged(0, table)
        ImageLogDataWidget.logic.refreshViews()
        wait(1)

        self.run_screenshot(table.GetName())

    def test_export_slice_view(self):
        """
        Tests ImageLog Slice View Screenshot Export
        """
        loadEnvironmentByName("Well Logs")

        load_project(project_file_path=SCREENSHOT_PROJECT_FILE)
        wait(1)

        self.run_screenshot("TEST_VOLUME")

    def test_export_3D_view(self):
        """
        Tests Slicer 3D View Screenshot Export
        """
        load_project(project_file_path=SCREENSHOT_PROJECT_FILE)
        wait(1)

        self.run_screenshot("3D View")
