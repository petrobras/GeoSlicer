import hashlib
import numpy as np
import os
import slicer
import qt
import shutil
import tempfile

from commons.constants import SaveStatus
from commons.slicer import helpers
from commons.slicer_utils import LTracePluginTest
from commons.slicer.tests.utils import (
    close_project,
    check_for_message_box,
    process_events,
    loadEnvironmentByName,
    wait,
)
from commons.slicer.data_utils import dataFrameToTableNode
from commons.slicer.tests.mocks.mock_qt_widgets import mockFileDialog
from pathlib import Path
from typing import Union
from unittest.mock import MagicMock, patch
import pandas as pd

RESOURCES = Path(__file__).parent / "Resources"
MODULES_DIR = Path(__file__).parents[2]


def _getFileMenuAction(name: str) -> qt.QAction:
    fileMenu = slicer.util.mainWindow().findChild("QMenu", "FileMenu")
    actions = {action.text: action for action in fileMenu.actions()}
    return actions.get(name)


def _useSaveAction() -> None:
    saveAction = _getFileMenuAction("Save Scene")
    assert saveAction is not None, "Couldn't find 'Save Scene' action"
    saveAction.triggered()


def _useSaveAsAction() -> None:
    saveAsAction = _getFileMenuAction("Save Scene As")
    assert saveAsAction is not None, "Couldn't find 'Save Scene As' action"
    saveAsAction.triggered()


def _useCloseAction() -> None:
    closeAction = _getFileMenuAction("Close Scene")
    assert closeAction is not None, "Couldn't find 'Close Scene' action"
    closeAction.triggered()


def _useLoadAction() -> None:
    loadAction = _getFileMenuAction("Load Scene")
    assert loadAction is not None, "Couldn't find 'Load Scene' action"
    loadAction.triggered()


def _useRecentAction(recentProjectPath: Union[Path, str]) -> None:

    if isinstance(recentProjectPath, Path):
        recentProjectPath = recentProjectPath.as_posix()

    recentMenuActions = _getRecentProjectActions()
    recentProjectAction = recentMenuActions.get(recentProjectPath)
    assert recentProjectAction is not None, f"Unable to find recent project action for '{recentProjectPath}'"
    recentProjectAction.triggered()


def _getRecentProjectActions() -> dict[str, qt.QAction]:
    recentMenu = _getFileMenuAction("Recent").menu()
    return {action.text: action for action in recentMenu.actions()}


def _md5UpdateFromDir(directory: Path, hash: hashlib.md5) -> hashlib.md5:
    assert Path(directory).is_dir()
    for path in sorted(Path(directory).iterdir(), key=lambda p: str(p).lower()):
        hash.update(path.name.encode())
        if path.is_file():
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash.update(chunk)
        elif path.is_dir():
            hash = _md5UpdateFromDir(path, hash)
    return hash


def _md5Dir(directory: Path) -> str:
    return _md5UpdateFromDir(directory, hashlib.md5()).hexdigest()


def createTableNode(name="TestNode", df: pd.DataFrame = None) -> slicer.vtkMRMLTableNode:
    node = helpers.createTemporaryVolumeNode(
        slicer.vtkMRMLTableNode, name=name, environment="test", saveWithScene=True, hidden=False
    )

    df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6], "C": [7, 8, 9]})
    dataFrameToTableNode(df, node)

    node.Modified()

    return node


class MainWindowTest(LTracePluginTest):
    """Test suite to assert slicer default widgets existence."""

    def post_setup(self) -> None:
        """Setup method for test case."""
        self.tempDirectory = Path(tempfile.TemporaryDirectory().name)
        self.tempDirectory.mkdir(parents=True, exist_ok=True)

    def tear_down(self) -> None:
        """Tear down method for test case."""
        if self.tempDirectory.exists():
            shutil.rmtree(self.tempDirectory, onexc=helpers.make_directory_writable)

        # Wait some signals to be processed and handled
        wait(0.5)

    def test_save_new_project(self) -> None:
        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / "project").as_posix()):
                _useSaveAction()

        wait(0.5)
        assert (self.tempDirectory / "project").exists()
        assert (self.tempDirectory / "project" / "project.mrml").exists()
        assert slicer.mrmlScene.GetURL() == (self.tempDirectory / "project" / "project.mrml").as_posix()

    def test_save_current_project(self) -> None:
        self.test_save_new_project()
        wait(1)
        assert slicer.util.mainWindow().windowModified is False

        createTableNode()
        wait(1)

        assert slicer.util.mainWindow().windowModified is True

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            _useSaveAction()

        wait(0.5)

        assert slicer.util.mainWindow().windowModified is False

    def test_save_current_project_in_a_new_directory(self) -> None:
        self.test_save_new_project()

        assert slicer.util.mainWindow().windowModified is False

        hashProject1 = _md5Dir(self.tempDirectory / "project")

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / "project2").as_posix()):
                _useSaveAsAction()

        wait(0.5)
        assert (self.tempDirectory / "project").exists()
        assert (self.tempDirectory / "project" / "project.mrml").exists()
        assert (self.tempDirectory / "project2").exists()
        assert (self.tempDirectory / "project2" / "project2.mrml").exists()
        assert slicer.mrmlScene.GetURL() == (self.tempDirectory / "project2" / "project2.mrml").as_posix()
        assert slicer.util.mainWindow().windowModified is False
        assert _md5Dir(self.tempDirectory / "project") == hashProject1

    def test_save_current_project_in_a_new_directory_making_changes(self) -> None:
        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        labelmapNode.CreateDefaultDisplayNodes()
        labelmapArray = np.random.randint(3, size=(16, 16, 16))
        slicer.util.updateVolumeFromArray(labelmapNode, labelmapArray.astype(np.int32))
        wait(1)
        assert slicer.util.mainWindow().windowModified is True

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / "project").as_posix()):
                _useSaveAction()

        wait(0.5)
        assert slicer.util.mainWindow().windowModified is False
        assert (self.tempDirectory / "project").exists()
        assert (self.tempDirectory / "project" / "project.mrml").exists()
        assert slicer.mrmlScene.GetURL() == (self.tempDirectory / "project" / "project.mrml").as_posix()
        hashProject1 = _md5Dir(self.tempDirectory / "project")

        # Use save as to change project directory
        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / "project2").as_posix()):
                _useSaveAsAction()

        wait(0.5)
        assert (self.tempDirectory / "project2").exists()
        assert (self.tempDirectory / "project2" / "project2.mrml").exists()
        assert slicer.mrmlScene.GetURL() == (self.tempDirectory / "project2" / "project2.mrml").as_posix()

        # Change labelmap data
        labelmapNode = helpers.tryGetNode(labelmapNode.GetID())
        assert labelmapNode is not None
        labelmapArray = np.random.randint(3, size=(24, 24, 24))
        slicer.util.updateVolumeFromArray(labelmapNode, labelmapArray.astype(np.int32))
        labelmapNode.Modified()
        wait(0.5)

        assert slicer.util.mainWindow().windowModified is True

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            # There is no expectation for a dialog to appear
            _useSaveAction()

        wait(0.5)

        assert slicer.util.mainWindow().windowModified is False
        assert _md5Dir(self.tempDirectory / "project") == hashProject1
        assert _md5Dir(self.tempDirectory / "project2") != hashProject1

    @patch("slicer.util.saveScene", lambda x: False)
    def test_save_as_failed_slicer_save_scene(self) -> None:
        assert slicer.util.mainWindow().windowModified is False
        with check_for_message_box(
            message="An error occurred while saving the project. Please check the following:", timeout_sec=10
        ):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / "project").as_posix()):
                _useSaveAsAction()

        wait(0.5)
        assert slicer.util.mainWindow().windowModified is False

    @patch("slicer.util.saveScene", lambda x: False)
    def test_save_as_failed_slicer_save_modified_scene(self) -> None:
        slicer.util.mainWindow().setWindowModified(True)
        process_events()

        assert slicer.util.mainWindow().windowModified is True

        with check_for_message_box(
            message="An error occurred while saving the project. Please check the following:", timeout_sec=10
        ):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / "project").as_posix()):
                _useSaveAsAction()

        wait(0.5)
        assert slicer.util.mainWindow().windowModified is True

    def test_save_failed_slicer_save_scene(self) -> None:
        self.test_save_new_project()
        wait(0.2)
        assert slicer.util.mainWindow().windowModified is False

        createTableNode(name="NewTable2")

        wait(1)

        assert slicer.util.mainWindow().windowModified is True

        with patch("slicer.util.saveScene") as mockSaveNode:
            mockSaveNode.return_value = False
            with check_for_message_box(
                message="An error occurred while saving the project. Please check the following:", timeout_sec=10
            ):
                _useSaveAction()

            wait(0.5)
            assert mockSaveNode.call_count > 0
            assert slicer.util.mainWindow().windowModified is True

    def test_save_failed_slicer_save_node(self) -> None:
        self.test_save_new_project()
        wait(1)
        assert slicer.util.mainWindow().windowModified is False

        createTableNode(name="NewTable2")

        wait(1)
        assert slicer.util.mainWindow().windowModified is True

        with patch("slicer.util.saveNode") as mockSaveNode:
            mockSaveNode.return_value = False
            with check_for_message_box(
                message="An error occurred while saving the project. Please check the following:", timeout_sec=10
            ):
                _useSaveAction()

            wait(0.5)
            assert mockSaveNode.call_count > 0
            assert slicer.util.mainWindow().windowModified is True

        wait(1)

    def test_close_project_without_modification(self) -> None:
        self.test_save_new_project()

        wait(0.2)
        assert slicer.util.mainWindow().windowModified is False

        try:
            with check_for_message_box(
                message="Save the changes before closing the scene?", timeout_sec=5, buttonTextToClick="&Cancel"
            ):
                _useCloseAction()
        except AttributeError:
            pass
        else:
            raise RuntimeError("Expected 'check_for_message_box' to trigger an exception, but it didn't")

    @patch("slicer.util.saveNode")
    @patch("slicer.util.saveScene")
    def test_close_project_with_modification_cancel(self, mockSaveScene: MagicMock, mockSaveNode: MagicMock) -> None:
        assert slicer.util.mainWindow().windowModified is False

        createTableNode()

        wait(1)
        assert slicer.util.mainWindow().windowModified is True

        with check_for_message_box(
            message="Save the changes before closing the scene?", timeout_sec=50, buttonTextToClick="&Cancel"
        ):
            _useCloseAction()

        assert mockSaveScene.call_count == 0
        assert mockSaveNode.call_count == 0

    @patch("slicer.util.saveNode")
    @patch("slicer.util.saveScene")
    def test_close_project_with_modification_close_without_saving(
        self, mockSaveScene: MagicMock, mockSaveNode: MagicMock
    ) -> None:
        assert slicer.util.mainWindow().windowModified is False

        createTableNode()

        wait(1)
        assert slicer.util.mainWindow().windowModified is True

        with check_for_message_box(
            message="Save the changes before closing the scene?",
            timeout_sec=5,
            buttonTextToClick="Close &without Saving",
        ):
            _useCloseAction()

        assert mockSaveScene.call_count == 0
        assert mockSaveNode.call_count == 0

    def test_close_project_with_modification_and_saving(self) -> None:
        assert slicer.util.mainWindow().windowModified is False

        createTableNode()

        wait(1)
        assert slicer.util.mainWindow().windowModified is True

        with check_for_message_box(
            message="Save the changes before closing the scene?", timeout_sec=5, buttonTextToClick="&Save and Close"
        ):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / "project").as_posix()):
                _useCloseAction()

        wait(1)
        assert (self.tempDirectory / "project").exists()
        assert (self.tempDirectory / "project" / "project.mrml").exists()
        assert slicer.mrmlScene.GetURL() == ""
        assert slicer.util.mainWindow().windowModified is False

    @patch("slicer.util.saveScene", lambda x: False)
    def test_close_project_with_modification_close_failed_to_save(self) -> None:
        assert slicer.util.mainWindow().windowModified is False

        createTableNode()

        wait(1)
        assert slicer.util.mainWindow().windowModified is True

        with check_for_message_box(
            message="An error occurred while saving the project. Please check the following:",
            timeout_sec=10,
            closeOthers=False,
        ):
            with check_for_message_box(
                message="Save the changes before closing the scene?",
                timeout_sec=10,
                buttonTextToClick="&Save and Close",
            ):
                with mockFileDialog(getSaveFileName=(self.tempDirectory / "project").as_posix()):
                    _useCloseAction()

        assert slicer.util.mainWindow().windowModified is True

    def test_close_current_project_with_modification_close_failed_to_save_scene(self) -> None:
        self.test_save_new_project()

        wait(1)
        assert slicer.util.mainWindow().windowModified is False

        createTableNode()

        wait(1)
        assert slicer.util.mainWindow().windowModified is True

        with check_for_message_box(
            message="An error occurred while saving the project. Please check the following:",
            timeout_sec=10,
            closeOthers=False,
        ):
            with check_for_message_box(
                message="Save the changes before closing the scene?",
                timeout_sec=10,
                buttonTextToClick="&Save and Close",
            ):
                with patch("slicer.util.saveScene", lambda x: False):
                    _useCloseAction()

        assert slicer.util.mainWindow().windowModified is True

    def test_close_current_project_with_modification_close_failed_to_save_node(self) -> None:
        self.test_save_new_project()

        wait(1)
        assert slicer.util.mainWindow().windowModified is False

        createTableNode()

        wait(1)
        assert slicer.util.mainWindow().windowModified is True

        with check_for_message_box(
            message="An error occurred while saving the project. Please check the following:",
            timeout_sec=15,
            closeOthers=False,
        ):
            with check_for_message_box(
                message="Save the changes before closing the scene?",
                timeout_sec=15,
                buttonTextToClick="&Save and Close",
            ):
                with patch("slicer.util.saveNode", lambda x, y: False):
                    _useCloseAction()

        assert slicer.util.mainWindow().windowModified is True

    def test_load_project(self) -> None:
        self.test_save_new_project()

        close_project()

        assert slicer.util.mainWindow().windowModified is False
        assert slicer.mrmlScene.GetURL() == ""

        projectPath = self.tempDirectory / "project"
        projectFilePath = projectPath / "project.mrml"

        assert projectPath.exists() and projectPath.is_dir()
        assert projectFilePath.exists() and projectFilePath.is_file()

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndImportEvent, timeout_ms=60000):
            with mockFileDialog(selectedFiles=[(projectFilePath).as_posix()]):
                _useLoadAction()

        assert slicer.util.mainWindow().windowModified is False
        assert slicer.mrmlScene.GetURL() == projectFilePath.as_posix()

    def test_load_project_cancelled_during_file_dialog(self) -> None:
        self.test_save_new_project()

        close_project()

        assert slicer.util.mainWindow().windowModified is False
        assert slicer.mrmlScene.GetURL() == ""

        try:
            with helpers.WatchSignal(signal=slicer.mrmlScene.EndImportEvent, timeout_ms=5000):
                with mockFileDialog(cancel=True):
                    _useLoadAction()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Expected 'slicer.mrmlScene.EndImportEvent' to not trigger, but it did.")

        assert slicer.util.mainWindow().windowModified is False
        assert slicer.mrmlScene.GetURL() == ""

    def test_load_project_failed(self) -> None:
        self.test_save_new_project()

        close_project()

        projectPath = self.tempDirectory / "project"
        projectFilePath = projectPath / "project.mrml"

        assert slicer.util.mainWindow().windowModified is False
        assert slicer.mrmlScene.GetURL() == ""
        assert projectPath.exists() and projectPath.is_dir()
        assert projectFilePath.exists() and projectFilePath.is_file()

        with patch("slicer.util.loadScene") as mockLoadScene:
            mockLoadScene.return_value = False

            try:
                with helpers.WatchSignal(signal=slicer.mrmlScene.EndImportEvent, timeout_ms=5000):
                    with mockFileDialog(selectedFiles=[projectFilePath.as_posix()]):
                        _useLoadAction()
            except RuntimeError:
                pass
            else:
                raise RuntimeError("Expected 'slicer.mrmlScene.EndImportEvent' to not trigger, but it did.")

        assert slicer.util.mainWindow().windowModified is False
        assert slicer.mrmlScene.GetURL() == ""

    def test_load_recent_project(self) -> None:
        self.test_save_new_project()

        close_project()

        projectPath = self.tempDirectory / "project"
        projectFilePath = projectPath / "project.mrml"

        assert slicer.util.mainWindow().windowModified is False
        assert slicer.mrmlScene.GetURL() == ""
        assert projectPath.exists() and projectPath.is_dir()
        assert projectFilePath.exists() and projectFilePath.is_file()

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndImportEvent, timeout_ms=10000):
            _useRecentAction(projectFilePath)

        assert slicer.util.mainWindow().windowModified is False
        assert slicer.mrmlScene.GetURL() == projectFilePath.as_posix()

    def test_load_recent_project_clear_history(self) -> None:
        self.test_save_new_project()

        close_project()

        projectPath = self.tempDirectory / "project"
        projectFilePath = projectPath / "project.mrml"

        assert slicer.util.mainWindow().windowModified is False
        assert slicer.mrmlScene.GetURL() == ""
        assert projectPath.exists() and projectPath.is_dir()
        assert projectFilePath.exists() and projectFilePath.is_file()

        _useRecentAction("Clear History")

        wait(0.4)

        recentAction = _getFileMenuAction("Recent")
        assert recentAction.enabled is False

    def test_load_recent_project_deleted_project(self) -> None:
        self.test_save_new_project()

        close_project()

        wait(0.2)

        projectPath = self.tempDirectory / "project"
        projectFilePath = projectPath / "project.mrml"

        shutil.move(projectPath, self.tempDirectory / "deleted")

        wait(1)

        assert slicer.util.mainWindow().windowModified is False
        assert slicer.mrmlScene.GetURL() == ""
        assert not projectPath.exists(), f"The directory {projectPath.as_posix()} still exists"
        assert not projectFilePath.exists(), f"The file {projectFilePath.as_posix()} still exists"

        expectedMessage = f"Cannot load project from '{projectFilePath.as_posix()}'. File does not exist."
        with check_for_message_box(message=expectedMessage, timeout_sec=5):
            _useRecentAction(projectFilePath)

        assert slicer.util.mainWindow().windowModified is False
        assert slicer.mrmlScene.GetURL() == ""

    def test_help_menu_visible_actions(self):
        helpMenu = slicer.modules.AppContextInstance.mainWindow.findChild("QMenu", "HelpMenu")
        assert helpMenu is not None

        hideActionsFromHelpMenu = [
            "Browse tutorials",
            "Slicer Publications",
            "Visual Blog",
            "Report a bug",
            "Interface Documentation",
        ]

        for action in helpMenu.actions():
            if action.text in hideActionsFromHelpMenu and action.isVisible():
                raise Exception(f"{action.text} should not be visible.")

    def test_help_menu_custom_about(self):
        helpMenu = slicer.modules.AppContextInstance.mainWindow.findChild("QMenu", "HelpMenu")
        assert helpMenu is not None
        actions = {action.text: action for action in helpMenu.actions()}
        aboutAction = actions.get("About GeoSlicer")

        assert aboutAction is not None
        aboutAction.trigger()

        dialogs = slicer.modules.AppContextInstance.mainWindow.findChildren("QDialog", "GeoSlicer About Dialog")
        assert len(dialogs) == 1, f"Expected 1 dialog, got {len(dialogs)}"

        dialog = dialogs[0]
        assert dialog is not None
        process_events()

        if dialog is not None:
            visible = dialog.visible
            dialog.close()
            dialog.delete()
            process_events()
            assert visible

    def test_close_project_with_scene_modifications_saving_but_internal_failing_to_do_it(self) -> None:
        node = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__)
        nodeName = node.GetName()
        assert helpers.tryGetNode(nodeName) is not None, f"{nodeName} not found."

        wait(1)

        assert slicer.util.mainWindow().windowModified is True

        with patch("AppContext.ProjectEventsLogic.saveScene") as saveSceneMock:
            saveSceneMock.return_value = SaveStatus.FAILED
            with check_for_message_box(
                "Save the changes before closing the scene?", timeout_sec=4, buttonTextToClick="&Save and Close"
            ):
                _useCloseAction()
            saveSceneMock.assert_called_once()

    def test_close_project_with_scene_modifications_saving_but_internal_failing_to_do_it_due_to_file_existence(
        self,
    ) -> None:
        node = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__)
        nodeName = node.GetName()
        assert helpers.tryGetNode(nodeName) is not None, f"{nodeName} not found."

        wait(1)

        assert slicer.util.mainWindow().windowModified is True

        with patch("AppContext.ProjectEventsLogic.saveScene") as saveSceneMock:
            saveSceneMock.return_value = SaveStatus.FAILED_FILE_ALREADY_EXISTS
            with check_for_message_box(
                "Save the changes before closing the scene?", timeout_sec=4, buttonTextToClick="&Save and Close"
            ):
                _useCloseAction()
            saveSceneMock.assert_called_once()

        assert slicer.util.mainWindow().windowModified is True

    def test_image_log_view_when_switching_envs(self):
        loadEnvironmentByName("Well Logs")
        wait(2)
        self.assertGreaterEqual(slicer.app.layoutManager().layout, 15000)

        loadEnvironmentByName("Thin Section")
        wait(2)
        self.assertEqual(slicer.app.layoutManager().layout, slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)

        loadEnvironmentByName("Well Logs")
        wait(2)
        self.assertGreaterEqual(slicer.app.layoutManager().layout, 15000)

        loadEnvironmentByName("Thin Section")
        wait(2)
        self.assertEqual(slicer.app.layoutManager().layout, slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)

    def test_save_project_failed_due_not_available_disk_size(self):
        self.test_save_new_project()
        from commons.slicer.project_manager import ProjectManager

        node = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__, "TableNode")

        with check_for_message_box(
            message="An error occurred while saving the project. Please check the following:", timeout_sec=10
        ):
            with patch.object(ProjectManager(), "getWritableStorageInfo") as mockHDSize:
                mockHDSize.return_value = 0

                _useSaveAction()

            wait(0.5)
        assert not (self.tempDirectory / "project" / "Data" / f"{node.GetName()}.nrrd").is_file(), (
            "Expected file to not exist"
        )

    def test_load_recent_project_multiple_times_in_sequence(self):
        projectNames = ["project1", "project2", "project3"]
        for projectName in projectNames:
            with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
                with mockFileDialog(getSaveFileName=(self.tempDirectory / f"{projectName}").as_posix()):
                    _useSaveAsAction()

            wait(0.5)
            assert (self.tempDirectory / f"{projectName}").exists()
            assert (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").exists()
            assert (
                slicer.mrmlScene.GetURL() == (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").as_posix()
            )
            close_project()
            wait(0.5)
            assert slicer.mrmlScene.GetURL() == "", f"Expected empty URL. Got {slicer.mrmlScene.GetURL()}"

        wait(0.5)
        assert slicer.util.mainWindow().windowModified is False

        from commons.slicer.project_manager import ProjectManager

        with patch.object(ProjectManager(), "load") as mockLoad:
            mockLoad.return_value = (True, "")
            for projectName in projectNames:
                _useRecentAction(self.tempDirectory / f"{projectName}" / f"{projectName}.mrml")

            wait(0.5)
            assert mockLoad.call_count == 3, f"Expected 3 calls to ProjectManager.load(), got {mockLoad.call_count}"

    def test_load_different_file_extensions_and_not_save_as_recent(self):
        if _getFileMenuAction("Recent").enabled:
            _useRecentAction("Clear History")

        nodeFilePath = (
            RESOURCES / "ThinSections" / "PoreSegs" / "Data" / "sample_1234,56m_c1_Segmentation_LabelMap.nrrd"
        )
        slicer.util.loadVolume(str(nodeFilePath), properties={"singleFile": True})

        imageFilePath = RESOURCES / "ThinSections" / "sample_1234,56m_c1.jpg"
        slicer.util.loadVolume(str(imageFilePath), properties={"singleFile": True})

        tableFilePath = RESOURCES / "save_table_test" / "Data" / "duplicate name.tsv"
        slicer.util.loadTable(str(tableFilePath))

        wait(1)

        recentFilePaths = [Path(filePath) for filePath in _getRecentProjectActions().keys()]
        assert nodeFilePath not in recentFilePaths, (
            f"Expected {nodeFilePath} to not be in the recent project files list"
        )
        assert imageFilePath not in recentFilePaths, (
            f"Expected {imageFilePath} to not be in the recent project files list"
        )
        assert tableFilePath not in recentFilePaths, (
            f"Expected {tableFilePath} to not be in the recent project files list"
        )
        assert _getFileMenuAction("Recent").enabled is False

    def test_load_recent_project_multiple_times_in_sequence_after_modifying(self):
        projectNames = ["project1", "project2", "project3"]

        for projectName in projectNames:
            with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
                with mockFileDialog(getSaveFileName=(self.tempDirectory / f"{projectName}").as_posix()):
                    _useSaveAsAction()

            wait(0.5)
            assert (self.tempDirectory / f"{projectName}").exists()
            assert (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").exists()
            assert (
                slicer.mrmlScene.GetURL() == (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").as_posix()
            )

            close_project()
            wait(0.5)

        from commons.slicer.project_manager import ProjectManager

        with patch.object(ProjectManager(), "load") as mockLoad:
            mockLoad.return_value = (True, "")
            for projectName in projectNames:
                with check_for_message_box(
                    "Save the changes before closing the scene?",
                    buttonTextToClick="Close &without Saving",
                    timeout_sec=5,
                ):
                    slicer.modules.AppContextInstance.mainWindow.setWindowModified(True)
                    process_events()
                    _useRecentAction(self.tempDirectory / f"{projectName}" / f"{projectName}.mrml")

                wait(1)

            assert mockLoad.call_count == 3, f"Expected 3 calls to ProjectManager.load(), got {mockLoad.call_count}"

    def test_load_recent_project_in_a_modified_scene_and_cancel_closing(self):
        projectName = "project1"

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / f"{projectName}").as_posix()):
                _useSaveAsAction()

        wait(0.5)
        assert (self.tempDirectory / f"{projectName}").exists()
        assert (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").exists()
        assert slicer.mrmlScene.GetURL() == (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").as_posix()
        close_project()
        wait(0.5)

        assert slicer.mrmlScene.GetURL() == ""

        from commons.slicer.project_manager import ProjectManager

        with patch.object(ProjectManager(), "load") as mockLoad:
            with check_for_message_box(
                "Save the changes before closing the scene?",
                buttonTextToClick="&Cancel",
                timeout_sec=5,
            ):
                slicer.modules.AppContextInstance.mainWindow.setWindowModified(True)
                process_events()
                _useRecentAction(self.tempDirectory / f"{projectName}" / f"{projectName}.mrml")

            wait(1)
            assert mockLoad.call_count == 0, f"Expected 0 calls to ProjectManager.load(), got {mockLoad.call_count}"

    def test_load_recent_project_in_a_modified_scene_and_save_current_project(self):
        projectName = "project1"

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / f"{projectName}").as_posix()):
                _useSaveAsAction()

        wait(0.5)
        projectFilePath = self.tempDirectory / f"{projectName}" / f"{projectName}.mrml"
        assert (self.tempDirectory / f"{projectName}").exists()
        assert projectFilePath.exists()
        assert slicer.mrmlScene.GetURL() == projectFilePath.as_posix()
        close_project()
        wait(0.5)

        from commons.slicer.project_manager import ProjectManager

        with patch.object(ProjectManager(), "load") as mockLoad:
            mockLoad.return_value = (True, "")
            with patch("AppContext.ProjectEventsLogic.saveScene") as saveSceneMock:
                saveSceneMock.return_value = SaveStatus.SUCCEED
                with check_for_message_box(
                    "Save the changes before closing the scene?",
                    buttonTextToClick="&Save and Close",
                    timeout_sec=5,
                ):
                    slicer.modules.AppContextInstance.mainWindow.setWindowModified(True)
                    process_events()
                    _useRecentAction(self.tempDirectory / f"{projectName}" / f"{projectName}.mrml")

                wait(1)

            assert mockLoad.call_count == 1, f"Expected 1 calls to ProjectManager.load(), got {mockLoad.call_count}"

    def test_load_same_project_as_current_from_recent(self):
        projectName = "project1"

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / f"{projectName}").as_posix()):
                _useSaveAsAction()

        wait(0.5)
        projectFilePath = self.tempDirectory / f"{projectName}" / f"{projectName}.mrml"
        assert (self.tempDirectory / f"{projectName}").exists()
        assert (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").exists()
        assert Path(slicer.mrmlScene.GetURL()) == projectFilePath, (
            f"Expected {projectFilePath.as_posix()}. Got {slicer.mrmlScene.GetURL()}"
        )
        wait(0.5)

        with patch("slicer.util.loadScene") as mockLoadScene:
            _useRecentAction(self.tempDirectory / f"{projectName}" / f"{projectName}.mrml")
            wait(0.5)
            assert mockLoadScene.call_count == 0, f"Expected 0 calls to loadScene(), got {mockLoadScene.call_count}"

        assert Path(slicer.mrmlScene.GetURL()) == projectFilePath, (
            f"Expected {projectFilePath.as_posix()}. Got {slicer.mrmlScene.GetURL()}"
        )

    def test_load_same_recent_project_as_current_after_saving_modified_scene_as_the_same_project(self):
        projectName = "project1"

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / f"{projectName}").as_posix()):
                _useSaveAsAction()

        wait(0.5)
        projectFilePath = self.tempDirectory / f"{projectName}" / f"{projectName}.mrml"
        assert (self.tempDirectory / f"{projectName}").exists()
        assert (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").exists()
        assert Path(slicer.mrmlScene.GetURL()) == projectFilePath, (
            f"Expected {projectFilePath.as_posix()}. Got {slicer.mrmlScene.GetURL()}"
        )
        wait(0.5)

        with patch("slicer.util.loadScene") as mockLoadScene:
            projectFilePathToLoad = projectFilePath
            projectFilePathToSaveOnClose = projectFilePath.parent
            with mockFileDialog(
                selectedFiles=[(projectFilePathToLoad).as_posix()],
                getSaveFileName=(projectFilePathToSaveOnClose).as_posix(),
            ):
                slicer.modules.AppContextInstance.mainWindow.setWindowModified(True)
                process_events()
                _useLoadAction()
                wait(1)

            assert mockLoadScene.call_count == 0, f"Expected 0 calls to loadScene(), got {mockLoadScene.call_count}"

        assert Path(slicer.mrmlScene.GetURL()) == projectFilePath, (
            f"Expected {projectFilePath.as_posix()}. Got {slicer.mrmlScene.GetURL()}"
        )

    def test_load_project_multiple_times_in_sequence_after_modifying(self):
        projectNames = ["project1", "project2", "project3"]

        for projectName in projectNames:
            with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
                with mockFileDialog(getSaveFileName=(self.tempDirectory / f"{projectName}").as_posix()):
                    _useSaveAsAction()

            wait(0.5)
            assert (self.tempDirectory / f"{projectName}").exists()
            assert (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").exists()
            assert (
                slicer.mrmlScene.GetURL() == (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").as_posix()
            )
            close_project()
            wait(1)

        from commons.slicer.project_manager import ProjectManager

        with patch.object(ProjectManager(), "load") as mockLoad:
            mockLoad.return_value = (True, "")
            for projectName in projectNames:
                projectFilePath = self.tempDirectory / f"{projectName}" / f"{projectName}.mrml"
                with check_for_message_box(
                    "Save the changes before closing the scene?",
                    buttonTextToClick="Close &without Saving",
                    timeout_sec=5,
                ):
                    with mockFileDialog(selectedFiles=[(projectFilePath).as_posix()]):
                        slicer.modules.AppContextInstance.mainWindow.setWindowModified(True)
                        process_events()
                        _useLoadAction()

                wait(1)

            assert mockLoad.call_count == 3, f"Expected 3 calls to ProjectManager.load(), got {mockLoad.call_count}"

    def test_load_project_in_a_modified_scene_and_cancel_closing(self):
        projectName = "project1"

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / f"{projectName}").as_posix()):
                _useSaveAsAction()

        wait(0.5)
        assert (self.tempDirectory / f"{projectName}").exists()
        assert (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").exists()
        assert slicer.mrmlScene.GetURL() == (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").as_posix()
        close_project()
        wait(0.5)

        assert slicer.mrmlScene.GetURL() == ""

        from commons.slicer.project_manager import ProjectManager

        with patch.object(ProjectManager(), "load") as mockLoad:
            projectFilePath = self.tempDirectory / f"{projectName}" / f"{projectName}.mrml"
            with check_for_message_box(
                "Save the changes before closing the scene?",
                buttonTextToClick="&Cancel",
                timeout_sec=5,
            ):
                with mockFileDialog(selectedFiles=[(projectFilePath).as_posix()]):
                    slicer.modules.AppContextInstance.mainWindow.setWindowModified(True)
                    process_events()
                    _useLoadAction()

            wait(1)
            assert mockLoad.call_count == 0, f"Expected 0 calls to ProjectManager.load(), got {mockLoad.call_count}"

    def test_load_project_in_a_modified_scene_and_save_current_project(self):
        projectName = "project"

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / f"{projectName}").as_posix()):
                _useSaveAsAction()

        wait(0.5)
        assert (self.tempDirectory / f"{projectName}").exists()
        assert (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").exists()
        assert slicer.mrmlScene.GetURL() == (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").as_posix()
        close_project()
        wait(0.5)

        assert slicer.mrmlScene.GetURL() == ""

        from commons.slicer.project_manager import ProjectManager

        with patch.object(ProjectManager(), "load") as mockLoad:
            mockLoad.return_value = (True, "")
            projectFilePathToLoad = self.tempDirectory / f"{projectName}" / f"{projectName}.mrml"
            projectFilePathToSaveOnClose = self.tempDirectory / f"{projectName}B"
            with check_for_message_box(
                "Save the changes before closing the scene?",
                buttonTextToClick="&Save and Close",
                timeout_sec=5,
            ):
                with mockFileDialog(
                    selectedFiles=[(projectFilePathToLoad).as_posix()],
                    getSaveFileName=(projectFilePathToSaveOnClose).as_posix(),
                ):
                    slicer.modules.AppContextInstance.mainWindow.setWindowModified(True)
                    process_events()
                    _useLoadAction()

                wait(1)

            assert mockLoad.call_count == 1, f"Expected 1 calls to ProjectManager.load(), got {mockLoad.call_count}"

    def test_load_same_project_as_current(self):
        projectName = "project1"

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / f"{projectName}").as_posix()):
                _useSaveAsAction()

        wait(0.5)
        projectFilePath = self.tempDirectory / f"{projectName}" / f"{projectName}.mrml"
        assert (self.tempDirectory / f"{projectName}").exists()
        assert (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").exists()
        assert Path(slicer.mrmlScene.GetURL()) == projectFilePath, (
            f"Expected {projectFilePath.as_posix()}. Got {slicer.mrmlScene.GetURL()}"
        )
        wait(0.5)

        with patch("slicer.util.loadScene") as mockLoadScene:
            with mockFileDialog(selectedFiles=[(projectFilePath).as_posix()]):
                slicer.modules.AppContextInstance.mainWindow.setWindowModified(True)
                process_events()
                _useLoadAction()
                wait(1)

            assert mockLoadScene.call_count == 0, f"Expected 0 calls to loadScene(), got {mockLoadScene.call_count}"

        assert Path(slicer.mrmlScene.GetURL()) == projectFilePath, (
            f"Expected {projectFilePath.as_posix()}. Got {slicer.mrmlScene.GetURL()}"
        )

    def test_load_same_project_as_current_after_saving_modified_scene_as_existent_project(self):
        projectName = "project1"

        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / f"{projectName}").as_posix()):
                _useSaveAsAction()

        wait(0.5)
        projectFilePath = self.tempDirectory / f"{projectName}" / f"{projectName}.mrml"
        assert (self.tempDirectory / f"{projectName}").exists()
        assert (self.tempDirectory / f"{projectName}" / f"{projectName}.mrml").exists()
        assert Path(slicer.mrmlScene.GetURL()) == projectFilePath, (
            f"Expected {projectFilePath.as_posix()}. Got {slicer.mrmlScene.GetURL()}"
        )
        wait(1)

        with patch("slicer.util.loadScene") as mockLoadScene:
            projectFilePathToLoad = projectFilePath
            projectFilePathToSaveOnClose = projectFilePath.parent
            with mockFileDialog(
                selectedFiles=[(projectFilePathToLoad).as_posix()],
                getSaveFileName=(projectFilePathToSaveOnClose).as_posix(),
            ):
                slicer.modules.AppContextInstance.mainWindow.setWindowModified(True)
                process_events()
                _useLoadAction()
                wait(1)

            assert mockLoadScene.call_count == 0, f"Expected 0 calls to loadScene(), got {mockLoadScene.call_count}"

        assert Path(slicer.mrmlScene.GetURL()) == projectFilePath, (
            f"Expected {projectFilePath.as_posix()}. Got {slicer.mrmlScene.GetURL()}"
        )

    def test_save_does_not_create_data_folder_in_working_directory(self) -> None:
        """Saving a project must not create a 'Data' folder in the current working
        directory, nor change it. Node files belong under the scene root directory."""

        # Save an empty project first to establish the scene URL
        with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
            with mockFileDialog(getSaveFileName=(self.tempDirectory / "project").as_posix()):
                _useSaveAction()
        wait(0.5)

        # Add a node with data — this triggers individual file saving on the next save
        createTableNode()
        wait(1)

        # Use a directory distinct from the project root as the working directory
        cwdDir = self.tempDirectory / "cwd"
        cwdDir.mkdir(parents=True, exist_ok=True)
        originalCwd = os.getcwd()
        os.chdir(cwdDir)
        try:
            with helpers.WatchSignal(signal=slicer.mrmlScene.EndSaveEvent, timeout_ms=10000):
                _useSaveAction()
            wait(0.5)

            assert os.getcwd() == str(cwdDir), (
                f"Working directory changed during save: expected {cwdDir}, got {os.getcwd()}"
            )
            assert not (cwdDir / "Data").exists(), (
                f"'Data' folder was created in the working directory ({cwdDir}) instead of the project directory."
            )
        finally:
            os.chdir(originalCwd)
