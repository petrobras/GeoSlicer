from functools import wraps
from commons.slicer_utils import LTracePluginTest
from commons.slicer.tests.utils import process_events
from commons.slicer.app import MANUAL_BASE_URL
from pathlib import Path
from unittest.mock import patch

import slicer
import qt
import tempfile
import importlib.util
import os
import sys


def getSlicerRCModule():
    """Load the .slicerrc.py script as a module for testing."""
    slicerrcFilePath = Path(slicer.app.slicerHome) / ".slicerrc.py"
    spec = importlib.util.spec_from_file_location("slicerrc_test", slicerrcFilePath)
    slicerrc = importlib.util.module_from_spec(spec)
    sys.modules["slicerrc_test"] = slicerrc
    spec.loader.exec_module(slicerrc)
    return slicerrc


slicerrc = getSlicerRCModule()


def mocked_test_case(f):
    """Decorator for tests of slicerrc functions: mocks slicer, qt and logging and provides a temporary directory."""

    @patch("slicerrc_test.logging")
    @patch("slicerrc_test.qt")
    @patch("slicerrc_test.slicer")
    @wraps(f)
    def wrapper(self, mockSlicer, mockQt, mockLogging):
        with tempfile.TemporaryDirectory() as tmpdir:
            return f(self, Path(tmpdir), mockSlicer, mockQt, mockLogging)

    return wrapper


class SlicerRCTest(LTracePluginTest):
    def post_setup(self):
        """Save the initial DICOM database directory base value before tests."""
        self.dicomDatabaseDirectoryBaseValue = slicer.app.userSettings().value("DICOM/DatabaseDirectoryBase")

    def tear_down(self):
        """Restore the initial DICOM database directory base value after tests."""
        slicer.app.userSettings().setValue("DICOM/DatabaseDirectoryBase", self.dicomDatabaseDirectoryBaseValue)

    def test_module_change_to_3dslicer_module(self):
        """Verify that the help URL changes correctly when switching between modules."""

        def getModuleHeader():
            modulePanelDockWidget = slicer.util.mainWindow().findChildren("QDockWidget", "PanelDockWidget")[0]
            assert modulePanelDockWidget.titleBarWidget() is not None
            headerWidget = modulePanelDockWidget.titleBarWidget().findChild("QWidget", "ModuleHeader")
            return headerWidget

        slicer.util.selectModule("SegmentEditor")
        process_events()
        assert getModuleHeader().moduleHelp.url == MANUAL_BASE_URL, (
            f"Expected: {MANUAL_BASE_URL}, Actual: {getModuleHeader().moduleHelp.url}"
        )

        # Change to GeoSlicer module
        slicer.util.selectModule("CTAutoRegistration")
        process_events()
        expectedRegisterHtml = MANUAL_BASE_URL + "Volumes/Register/Register.html"
        assert getModuleHeader().moduleHelp.url.strip() == expectedRegisterHtml.strip(), (
            f"Expected: {expectedRegisterHtml}, Actual: {getModuleHeader().moduleHelp.url}"
        )

        slicer.util.selectModule("ModuleManager")
        process_events()
        expectedModuleHtml = MANUAL_BASE_URL + "GettingStarted/ModuleManager.html"
        assert getModuleHeader().moduleHelp.url.strip() == expectedModuleHtml.strip(), (
            f"Expected: {expectedModuleHtml}, Actual: {getModuleHeader().moduleHelp.url}"
        )

    def test_default_slice_edges_3d_visibility(self):
        for sliceName in ["Red", "Yellow", "Green"]:
            sliceWidget = slicer.app.layoutManager().sliceWidget(sliceName)
            sliceController = sliceWidget.sliceController()
            assert sliceController.sliceLogic().GetSliceNode().GetSliceEdgeVisibility3D() is False, (
                f"Expected '{sliceName}' slice view to have its slice edge 3D visibility disabled"
            )

    @mocked_test_case
    def test_update_DICOM_database_path_same_path(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Test that no changes are made if the path is already the desired one."""
        mockSlicer.app.DICOMDatabaseDirectoryBasePath.return_value = str(tmpDir)
        mockQt.QStandardPaths.writableLocation.return_value = str(tmpDir)

        slicerrc.updateDICOMDatabasePath()

        mockSlicer.app.userSettings().setValue.assert_not_called()

    @mocked_test_case
    def test_update_DICOM_database_path_invalid_current_path(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Test that no files are moved from an invalid (non-standard) current path."""
        currentPath = tmpDir / "invalid"
        desiredPath = tmpDir / "appdata"
        currentPath.mkdir()
        desiredPath.mkdir()

        mockSlicer.app.DICOMDatabaseDirectoryBasePath.return_value = str(currentPath)
        mockSlicer.app.slicerHome = "some/other/path"

        def writableLocationSideEffect(locationType):
            if locationType == mockQt.QStandardPaths.AppLocalDataLocation:
                return str(desiredPath)
            if locationType == mockQt.QStandardPaths.DocumentsLocation:
                return str(tmpDir / "docs")  # A different path
            return ""

        mockQt.QStandardPaths.writableLocation.side_effect = writableLocationSideEffect

        (currentPath / "a_DICOM_file.dcm").touch()

        slicerrc.updateDICOMDatabasePath()

        self.assertTrue((currentPath / "a_DICOM_file.dcm").exists())
        self.assertFalse((desiredPath / "a_DICOM_file.dcm").exists())

    @mocked_test_case
    def test_update_DICOM_database_path_from_documents(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Test moving DICOM files and folders from the Documents directory."""
        currentPath = tmpDir / "docs"
        desiredPath = tmpDir / "appdata"
        currentPath.mkdir()
        desiredPath.mkdir()

        mockSlicer.app.DICOMDatabaseDirectoryBasePath.return_value = str(currentPath)
        mockSlicer.app.slicerHome = "some/other/path"

        def writableLocationSideEffect(locationType):
            if locationType == mockQt.QStandardPaths.AppLocalDataLocation:
                return str(desiredPath)
            if locationType == mockQt.QStandardPaths.DocumentsLocation:
                return str(currentPath)
            return ""

        mockQt.QStandardPaths.writableLocation.side_effect = writableLocationSideEffect

        (currentPath / "a_DICOM_file.dcm").touch()
        (currentPath / "a_dicom_folder").mkdir()
        (currentPath / "sub").mkdir()
        (currentPath / "sub" / "another_DICOM_file.dcm").touch()
        (currentPath / "sub" / "not_a_d-i-c-o-m_file.txt").touch()
        (currentPath / "not_a_d-i-c-o-m_file.txt").touch()

        slicerrc.updateDICOMDatabasePath()

        mockSlicer.app.userSettings().setValue.assert_called_once_with("DICOM/DatabaseDirectoryBase", str(desiredPath))

        self.assertFalse((currentPath / "a_DICOM_file.dcm").exists())
        self.assertFalse((currentPath / "a_dicom_folder").exists())
        self.assertFalse((currentPath / "sub" / "another_DICOM_file.dcm").exists())
        self.assertTrue((currentPath / "not_a_d-i-c-o-m_file.txt").exists())
        self.assertTrue((currentPath / "sub" / "not_a_d-i-c-o-m_file.txt").exists())

        self.assertTrue((desiredPath / "a_DICOM_file.dcm").exists())
        self.assertTrue((desiredPath / "a_dicom_folder").exists())
        self.assertTrue((desiredPath / "sub" / "another_DICOM_file.dcm").exists())
        self.assertFalse((desiredPath / "not_a_d-i-c-o-m_file.txt").exists())
        self.assertFalse((desiredPath / "sub" / "not_a_d-i-c-o-m_file.txt").exists())

    @mocked_test_case
    def test_update_DICOM_database_path_from_app_home(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Test moving DICOM files from the application's home directory."""
        app_home_path = tmpDir / "slicer_home"
        currentPath = app_home_path / "dicom_db"
        desiredPath = tmpDir / "appdata"
        app_home_path.mkdir()
        currentPath.mkdir()
        desiredPath.mkdir()

        mockSlicer.app.DICOMDatabaseDirectoryBasePath.return_value = str(currentPath)
        mockSlicer.app.slicerHome = str(app_home_path)

        def writableLocationSideEffect(locationType):
            if locationType == mockQt.QStandardPaths.AppLocalDataLocation:
                return str(desiredPath)
            if locationType == mockQt.QStandardPaths.DocumentsLocation:
                return "some/other/docs"
            return ""

        mockQt.QStandardPaths.writableLocation.side_effect = writableLocationSideEffect

        (currentPath / "my_DICOM.zip").touch()

        slicerrc.updateDICOMDatabasePath()

        self.assertTrue((desiredPath / "my_DICOM.zip").exists())
        self.assertFalse((currentPath / "my_DICOM.zip").exists())

    @mocked_test_case
    def test_update_DICOM_database_path_case_insensitivity(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Test that file moving is case-insensitive."""
        currentPath = tmpDir / "docs"
        desiredPath = tmpDir / "appdata"
        currentPath.mkdir()
        desiredPath.mkdir()

        mockSlicer.app.DICOMDatabaseDirectoryBasePath.return_value = str(currentPath)
        mockSlicer.app.slicerHome = "some/other/path"

        def writableLocationSideEffect(locationType):
            if locationType == mockQt.QStandardPaths.AppLocalDataLocation:
                return str(desiredPath)
            if locationType == mockQt.QStandardPaths.DocumentsLocation:
                return str(currentPath)
            return ""

        mockQt.QStandardPaths.writableLocation.side_effect = writableLocationSideEffect

        (currentPath / "file_dicom.txt").touch()
        (currentPath / "file_DICOM.txt").touch()
        (currentPath / "file_Dicom.txt").touch()

        slicerrc.updateDICOMDatabasePath()

        self.assertTrue((desiredPath / "file_dicom.txt").exists())
        self.assertTrue((desiredPath / "file_DICOM.txt").exists())
        self.assertTrue((desiredPath / "file_Dicom.txt").exists())

    @mocked_test_case
    def test_update_DICOM_database_path_no_dicom_files(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Test that non-DICOM files are not moved."""
        currentPath = tmpDir / "docs"
        desiredPath = tmpDir / "appdata"
        currentPath.mkdir()
        desiredPath.mkdir()

        mockSlicer.app.DICOMDatabaseDirectoryBasePath.return_value = str(currentPath)
        mockSlicer.app.slicerHome = "some/other/path"

        def writableLocationSideEffect(locationType):
            if locationType == mockQt.QStandardPaths.AppLocalDataLocation:
                return str(desiredPath)
            if locationType == mockQt.QStandardPaths.DocumentsLocation:
                return str(currentPath)
            return ""

        mockQt.QStandardPaths.writableLocation.side_effect = writableLocationSideEffect

        (currentPath / "not_a_d-i-c-o-m_file.txt").touch()

        slicerrc.updateDICOMDatabasePath()

        self.assertTrue((currentPath / "not_a_d-i-c-o-m_file.txt").exists())
        self.assertFalse((desiredPath / "not_a_d-i-c-o-m_file.txt").exists())

    @mocked_test_case
    def test_update_DICOM_database_path_current_is_none(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Test behavior when the current path is None."""
        currentPath = None
        desiredPath = tmpDir / "appdata"
        desiredPath.mkdir()

        mockSlicer.app.DICOMDatabaseDirectoryBasePath.return_value = currentPath
        mockSlicer.app.slicerHome = "some/other/path"

        def writableLocationSideEffect(locationType):
            if locationType == mockQt.QStandardPaths.AppLocalDataLocation:
                return str(desiredPath)
            return ""

        mockQt.QStandardPaths.writableLocation.side_effect = writableLocationSideEffect
        slicerrc.updateDICOMDatabasePath()

        mockSlicer.app.userSettings().setValue.assert_called_once_with("DICOM/DatabaseDirectoryBase", str(desiredPath))

    @mocked_test_case
    def test_update_DICOM_database_path_current_is_empty(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Test behavior when the current path is an empty string."""
        currentPath = ""
        desiredPath = tmpDir / "appdata"
        desiredPath.mkdir()

        mockSlicer.app.DICOMDatabaseDirectoryBasePath.return_value = currentPath
        mockSlicer.app.slicerHome = "some/other/path"

        def writableLocationSideEffect(locationType):
            if locationType == mockQt.QStandardPaths.AppLocalDataLocation:
                return str(desiredPath)
            return ""

        mockQt.QStandardPaths.writableLocation.side_effect = writableLocationSideEffect
        slicerrc.updateDICOMDatabasePath()

        mockSlicer.app.userSettings().setValue.assert_called_once_with("DICOM/DatabaseDirectoryBase", str(desiredPath))

    @mocked_test_case
    def test_update_DICOM_database_path_current_doesnt_exist(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Test behavior when the current path doesnt exist."""
        currentPath = tmpDir / "inexistent"
        desiredPath = tmpDir / "appdata"
        desiredPath.mkdir()

        mockSlicer.app.DICOMDatabaseDirectoryBasePath.return_value = str(currentPath)
        mockSlicer.app.slicerHome = "some/other/path"

        def writableLocationSideEffect(locationType):
            if locationType == mockQt.QStandardPaths.AppLocalDataLocation:
                return str(desiredPath)
            return ""

        mockQt.QStandardPaths.writableLocation.side_effect = writableLocationSideEffect
        slicerrc.updateDICOMDatabasePath()

        mockSlicer.app.userSettings().setValue.assert_called_once_with("DICOM/DatabaseDirectoryBase", str(desiredPath))
        self.assertIn(
            f"The current DICOM Database directory base path '{str(currentPath)}' does not exist",
            mockLogging.info.call_args[0][0],
        )

    @mocked_test_case
    def test_update_DICOM_database_path_move_error(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Test that an error during file moving is logged."""
        currentPath = tmpDir / "docs"
        desiredPath = tmpDir / "appdata"
        currentPath.mkdir()
        desiredPath.mkdir()

        mockSlicer.app.DICOMDatabaseDirectoryBasePath.return_value = str(currentPath)

        def writableLocationSideEffect(locationType):
            if locationType == mockQt.QStandardPaths.AppLocalDataLocation:
                return str(desiredPath)
            if locationType == mockQt.QStandardPaths.DocumentsLocation:
                return str(currentPath)
            return ""

        mockQt.QStandardPaths.writableLocation.side_effect = writableLocationSideEffect

        (currentPath / "a_dicom_file.txt").touch()

        with patch("slicerrc_test.shutil.move", side_effect=OSError("Test error")):
            slicerrc.updateDICOMDatabasePath()

        mockLogging.warning.assert_called_once()
        self.assertIn("Failed to update DICOM Database file", mockLogging.warning.call_args[0][0])

    def mockUserPaths(self, tmpDir, mockSlicer, mockQt, settings):
        """Point the user settings, the system temporary folder and the standard locations inside tmpDir. Returns the
        AppData and Documents paths, which don't exist yet."""
        appData = tmpDir / "appdata"
        documents = tmpDir / "documents"
        mockSlicer.app.applicationName = "GeoSlicer"
        mockSlicer.app.temporaryPath = "unchanged"
        mockSlicer.app.defaultScenePath = "unchanged"
        mockSlicer.app.userSettings().value.side_effect = settings.get
        mockQt.QDir.tempPath.return_value = str(tmpDir / "systemtemp")
        locations = {
            mockQt.QStandardPaths.AppLocalDataLocation: str(appData),
            mockQt.QStandardPaths.DocumentsLocation: str(documents),
        }
        mockQt.QStandardPaths.writableLocation.side_effect = locations.get
        return appData, documents

    @mocked_test_case
    def test_set_user_paths_legacy_relative_paths(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Paths relative to an installation, which earlier versions saved to the shared settings, are replaced."""
        appData, _ = self.mockUserPaths(
            tmpDir, mockSlicer, mockQt, {"TemporaryPath": "LTrace/temp", "DefaultScenePath": "LTrace/saved_scenes"}
        )

        slicerrc.setUserPaths()

        self.assertEqual(mockSlicer.app.temporaryPath, (appData / "temp").as_posix())
        self.assertEqual(mockSlicer.app.defaultScenePath, Path.home().as_posix())

    @mocked_test_case
    def test_set_user_paths_slicer_fallback(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Slicer's fallback temporary folder, saved when the legacy one wasn't writable, is replaced."""
        slicerTemporaryPath = (
            tmpDir / "systemtemp" / ("GeoSlicer" if os.name == "nt" else f"GeoSlicer-{os.environ.get('USER', '')}")
        )
        appData, documents = self.mockUserPaths(tmpDir, mockSlicer, mockQt, {"TemporaryPath": str(slicerTemporaryPath)})

        slicerrc.setUserPaths()

        self.assertEqual(mockSlicer.app.temporaryPath, (appData / "temp").as_posix())

    @mocked_test_case
    def test_set_user_paths_user_chosen_paths(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Absolute paths the user chose are kept."""
        settings = {"TemporaryPath": str(tmpDir / "my_temp"), "DefaultScenePath": str(tmpDir / "my_scenes")}
        self.mockUserPaths(tmpDir, mockSlicer, mockQt, settings)

        slicerrc.setUserPaths()

        self.assertEqual(mockSlicer.app.temporaryPath, "unchanged")
        self.assertEqual(mockSlicer.app.defaultScenePath, "unchanged")

    @mocked_test_case
    def test_set_user_paths_slicer_default_scene_path(self, tmpDir, mockSlicer, mockQt, mockLogging):
        """Slicer's default scene folder, Documents, which OneDrive often syncs, is replaced by the home folder."""
        _, documents = self.mockUserPaths(tmpDir, mockSlicer, mockQt, {})
        mockSlicer.app.userSettings().value.side_effect = {"DefaultScenePath": str(documents)}.get
        documents.mkdir()

        slicerrc.setUserPaths()

        self.assertEqual(mockSlicer.app.defaultScenePath, Path.home().as_posix())

    def test_dicom_database_directory_base_path(self):
        """Verify that the DICOM database directory base path is correctly set."""
        self.assertEqual(
            self.dicomDatabaseDirectoryBaseValue,
            str(Path(qt.QStandardPaths.writableLocation(qt.QStandardPaths.AppLocalDataLocation))),
        )
