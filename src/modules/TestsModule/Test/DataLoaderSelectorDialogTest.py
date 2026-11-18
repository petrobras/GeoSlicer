import qt
import slicer

from commons.slicer.app.onboard import ui_DataLoaderSelectorDialog
from commons.slicer.app.onboard import LoaderInfo
from commons.slicer.app.onboard import ui_IntroToolButton
from commons.slicer.tests.utils import wait
from commons.slicer_utils import LTracePluginTest
from unittest.mock import patch, MagicMock
from commons.slicer.app import MANUAL_BASE_URL


class DataLoaderSelectorDialogTest(LTracePluginTest):
    def post_setup(self) -> None:
        self.modules = [
            LoaderInfo("Module 1", "Module1", "icon1", "Load Module 1 data"),
            LoaderInfo("Module 2", "Module2", "icon2", "Load Module 2 data"),
        ]
        self.dialog = ui_DataLoaderSelectorDialog(self.modules, parent=self._module_widget.parent)
        self.dialog.show()

    def test_data_loader_selector_dialog_init(self) -> None:
        self.assertEqual(self.dialog.windowTitle, "Open Image")
        self.assertTrue(self.dialog.projectOptionFrame.visible)

    def test_data_loader_selector_dialog_show_only_data_types(self) -> None:
        self.dialog.showOnlyDataTypes()
        self.assertFalse(self.dialog.projectOptionFrame.visible)

    def test_data_loader_selector_dialog_signal_emit(self) -> None:
        emittedModule = None

        def handleSignal(module: LoaderInfo) -> None:
            nonlocal emittedModule
            emittedModule = module

        self.dialog.signalEnvironmentClicked.connect(handleSignal)

        buttons = self.dialog.findChildren(ui_IntroToolButton)
        for button in buttons:
            if button.text == "Module 1":
                button.click()
                break

        self.assertIsNotNone(emittedModule)
        self.assertEqual(emittedModule.displayName, "Module 1")

    def test_data_loader_selector_dialog_event_filter(self) -> None:
        buttons = self.dialog.findChildren(ui_IntroToolButton)
        button = buttons[0]
        self.assertEqual(self.dialog.helpBoxTextEdit.toPlainText(), "")

        # Simulate mouse enter event
        eventEnter = qt.QEvent(qt.QEvent.Enter)
        self.dialog.eventFilter(button, eventEnter)
        self.assertEqual(self.dialog.helpBoxTextEdit.toPlainText(), "Load Module 1 data")

        # Simulate mouse leave event
        eventLeave = qt.QEvent(qt.QEvent.Leave)
        self.dialog.eventFilter(button, eventLeave)
        self.assertEqual(self.dialog.helpBoxTextEdit.toPlainText(), "")

    def test_open_netcdf_project(self) -> None:
        openNCButton = self.find_widget("Open NetCDF Project Button", self.dialog)
        assert openNCButton is not None

        netCDFWidget = slicer.modules.netcdf.widgetRepresentation().self()
        netCDFLoaderWidget = netCDFWidget.importModule.self()
        with patch.object(netCDFLoaderWidget, "file_selector", new_callable=MagicMock) as mockFileSelector:
            openNCButton.clicked()
            wait(1)
            self.assertTrue(slicer.util.selectedModule() == "NetCDF")
            mockFileSelector.browse.assert_called_once()

    @patch("commons.slicer.app.onboard.qt.QDesktopServices.openUrl")
    def test_documentation_button_opens_url(self, mockOpenUrl) -> None:
        docButton = self.dialog.findChild(qt.QToolButton, "Documentation Tool Button")
        self.assertIsNotNone(docButton)

        docButton.click()

        expectedUrl = qt.QUrl(MANUAL_BASE_URL)
        mockOpenUrl.assert_called_once_with(expectedUrl)
