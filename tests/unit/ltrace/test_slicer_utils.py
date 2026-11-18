"""Opening a configuration file in a text editor, on each platform GeoSlicer runs on."""

import ctypes
import sys
from unittest.mock import MagicMock

import pytest

import slicer
from commons import slicer_utils
from commons.slicer_utils import openInTextEditor


@pytest.fixture
def popen(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(slicer_utils.subprocess, "Popen", fake)
    return fake


@pytest.fixture
def windows(monkeypatch):
    """A Windows ``shell32`` whose ``ShellExecuteExW`` succeeds unless told otherwise."""
    monkeypatch.setattr(sys, "platform", "win32")
    windll = MagicMock()
    windll.shell32.ShellExecuteExW.return_value = 1
    monkeypatch.setattr(ctypes, "windll", windll, raising=False)
    monkeypatch.setattr(ctypes, "GetLastError", lambda: 1155, raising=False)
    return windll.shell32


def test_windows_opens_the_file_with_the_program_for_txt_files(windows, popen, tmp_path):
    """A ``.db`` extension would pick a database browser, or nothing at all: the ``.txt`` handler is asked."""
    path = tmp_path / "waterflow.db"

    assert openInTextEditor(path) is True

    windows.ShellExecuteExW.assert_called_once()
    info = windows.ShellExecuteExW.call_args.args[0]._obj
    assert info.lpFile == str(path)
    assert info.lpClass == ".txt"
    assert info.lpVerb == "open"
    assert info.fMask & 0x1, "SEE_MASK_CLASSNAME makes lpClass override the file's own association"
    popen.assert_not_called()


def test_windows_falls_back_to_notepad(windows, popen, tmp_path):
    windows.ShellExecuteExW.return_value = 0
    path = tmp_path / "waterflow.db"

    assert openInTextEditor(path) is True

    popen.assert_called_once_with(["notepad.exe", str(path)])


def test_windows_reports_when_no_editor_could_start(windows, popen, tmp_path):
    windows.ShellExecuteExW.return_value = 0
    popen.side_effect = FileNotFoundError("notepad.exe")

    assert openInTextEditor(tmp_path / "waterflow.db") is False


def test_linux_opens_the_file_outside_the_launcher_environment(monkeypatch, popen, tmp_path):
    """The editor must not inherit the library paths GeoSlicer's launcher set for itself."""
    monkeypatch.setattr(sys, "platform", "linux")
    path = tmp_path / "waterflow.db"

    assert openInTextEditor(path) is True

    popen.assert_called_once()
    assert popen.call_args.args[0] == ["xdg-open", str(path)]
    assert popen.call_args.kwargs["env"] is slicer.util.startupEnvironment.return_value
    assert popen.call_args.kwargs["start_new_session"] is True


def test_linux_without_xdg_open_asks_qt(monkeypatch, popen, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    popen.side_effect = FileNotFoundError("xdg-open")
    openUrl = MagicMock(return_value=False)
    monkeypatch.setattr(slicer_utils.qt.QDesktopServices, "openUrl", openUrl)

    assert openInTextEditor(tmp_path / "waterflow.db") is False

    openUrl.assert_called_once()
