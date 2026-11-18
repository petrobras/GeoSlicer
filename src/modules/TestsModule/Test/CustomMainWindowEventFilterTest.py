from unittest.mock import MagicMock
from commons.slicer_utils import LTracePluginTest
from pathlib import Path
from commons.slicer.tests.utils import (
    process_events,
    check_for_message_box,
)
import slicer
import qt
from commons.slicer.custom_main_window_event_filter import CustomizerEventFilter
from commons.slicer.application_observables import ApplicationObservables
from commons.constants import SaveStatus

RESOURCES_DIR = Path(__file__).parent / "Resources"


class CustomMainWindowEventFilterTest(LTracePluginTest):
    def _createDummyWidget(self):
        self._mockSaveSceneCallback = MagicMock()
        self._customEventFilter = CustomizerEventFilter(saveSceneCallback=self._mockSaveSceneCallback)
        self._module_widget.parent.installEventFilter(self._customEventFilter)

    def _installSignalSpy(self):
        self._mockSignalAboutToQuit = MagicMock()
        ApplicationObservables().aboutToQuit.connect(self._mockSignalAboutToQuit)

    def _triggerCloseEvent(self, widget) -> None:
        event = qt.QCloseEvent()
        slicer.app.sendEvent(widget, event)
        process_events()

    def _setWindowModified(self, state) -> None:
        slicer.modules.AppContextInstance.mainWindow.setWindowModified(state)

    def post_setup(self) -> None:
        self._createDummyWidget()
        self._installSignalSpy()

        self._cacheWindowModified = slicer.modules.AppContextInstance.mainWindow.isWindowModified

    def tear_down(self) -> None:
        self._setWindowModified(self._cacheWindowModified)
        self._module_widget.parent.removeEventFilter(self._customEventFilter)

    def test_close_modified_application_and_cancel(self):
        self._setWindowModified(True)
        assert self._mockSignalAboutToQuit.call_count == 0

        with check_for_message_box(
            message="Save the changes before exiting", timeout_sec=10, buttonTextToClick="&Cancel Exit"
        ):
            self._triggerCloseEvent(self._module_widget.parent)

        assert self._mockSignalAboutToQuit.call_count == 0
        assert self._mockSaveSceneCallback.call_count == 0

    def test_close_modified_application_without_saving(self):
        self._setWindowModified(True)
        assert self._mockSignalAboutToQuit.call_count == 0

        with check_for_message_box(
            message="Save the changes before exiting", timeout_sec=10, buttonTextToClick="&Exit without Saving"
        ):
            self._triggerCloseEvent(self._module_widget.parent)

        assert self._mockSignalAboutToQuit.call_count == 1
        assert self._mockSaveSceneCallback.call_count == 0

    def test_close_modified_application_and_succeed_to_saved(self):
        self._setWindowModified(True)
        assert self._mockSignalAboutToQuit.call_count == 0

        self._mockSaveSceneCallback.return_value = SaveStatus.SUCCEED
        with check_for_message_box(
            message="Save the changes before exiting", timeout_sec=10, buttonTextToClick="&Save and Exit"
        ):
            self._triggerCloseEvent(self._module_widget.parent)

        assert self._mockSignalAboutToQuit.call_count == 1
        assert self._mockSaveSceneCallback.call_count == 1

    def test_close_modified_application_and_failed_to_save(self):
        self._setWindowModified(True)
        assert self._mockSignalAboutToQuit.call_count == 0

        self._mockSaveSceneCallback.return_value = SaveStatus.FAILED
        with check_for_message_box(
            message="Save the changes before exiting", timeout_sec=10, buttonTextToClick="&Save and Exit"
        ):
            self._triggerCloseEvent(self._module_widget.parent)

        assert self._mockSignalAboutToQuit.call_count == 0
        assert self._mockSaveSceneCallback.call_count == 1

    def test_close_modified_application_and_failed_to_save_due_to_file_already_exist(self):
        self._setWindowModified(True)
        assert self._mockSignalAboutToQuit.call_count == 0

        self._mockSaveSceneCallback.return_value = SaveStatus.FAILED_FILE_ALREADY_EXISTS
        with check_for_message_box(
            message="Save the changes before exiting", timeout_sec=10, buttonTextToClick="&Save and Exit"
        ):
            self._triggerCloseEvent(self._module_widget.parent)

        assert self._mockSignalAboutToQuit.call_count == 0
        assert self._mockSaveSceneCallback.call_count == 1

    def test_close_modified_application_but_canceled_during_file_selection(self):
        self._setWindowModified(True)
        assert self._mockSignalAboutToQuit.call_count == 0

        self._mockSaveSceneCallback.return_value = SaveStatus.CANCELLED
        with check_for_message_box(
            message="Save the changes before exiting", timeout_sec=10, buttonTextToClick="&Save and Exit"
        ):
            self._triggerCloseEvent(self._module_widget.parent)

        assert self._mockSignalAboutToQuit.call_count == 0
        assert self._mockSaveSceneCallback.call_count == 1

    def test_close_not_modified_application(self):
        self._setWindowModified(False)
        assert self._mockSignalAboutToQuit.call_count == 0

        self._triggerCloseEvent(self._module_widget.parent)

        assert self._mockSignalAboutToQuit.call_count == 1
        assert self._mockSaveSceneCallback.call_count == 0
