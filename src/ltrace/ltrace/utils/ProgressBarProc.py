import json
import logging
import mmap
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import qt
import slicer

from ltrace.utils import ProgressBarWidget

if sys.platform.startswith("win32"):
    import win32gui
    import win32con
    import pywintypes


_SHM_SIZE = 1024
_ICON_RELATIVE_PATH = "LTrace/Resources/Icons/ico/GeoSlicer.ico"

# Published to in-process consumers (currently the patched h5pyd download loop in
# tools/deploy/Patches/h5pyd/0001-Progress-Bar.patch) so they can mmap the same
# region and push live status into the widget without going through the parent.
_SHM_PATH_ENV_VAR = "GEOSLICER_PROGRESS_SHM_PATH"


class ProgressBarProc:
    """Creates a progress bar window in a new process.

    Usage:
    >>> from ltrace.utils.ProgressBarProc import ProgressBarProc
    >>> with ProgressBarProc() as pb:
    >>>     pb.setMessage("Doing something...")
    >>>     pb.setProgress(50)
    >>>     # Or:
    >>>     pb.nextStep(50, "Doing something...")
    """

    def __init__(self):
        palette = slicer.app.palette()
        bgColor = palette.color(qt.QPalette.Background).name()
        fgColor = palette.color(qt.QPalette.WindowText).name()

        iconPath = slicer.app.toSlicerHomeAbsolutePath(_ICON_RELATIVE_PATH)
        if not Path(iconPath).exists():
            raise FileNotFoundError(f"Icon file '{iconPath}' does not exist")

        mainWindow = slicer.util.mainWindow()
        screenIndex = qt.QApplication.desktop().screenNumber(mainWindow) if mainWindow else 0

        fd, self._shmPath = tempfile.mkstemp(prefix="geoslicer-pb-", suffix=".shm")
        os.write(fd, b"\x00" * _SHM_SIZE)
        os.close(fd)
        self._shmFile = open(self._shmPath, "r+b")
        self.sharedMem = mmap.mmap(self._shmFile.fileno(), _SHM_SIZE)
        self.sharedDict = {}
        os.environ[_SHM_PATH_ENV_VAR] = self._shmPath

        self.setTitle("Processing")
        self.setMessage("Processing, please wait...")

        si = None
        if sys.platform.startswith("win32"):
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE

        self.proc = subprocess.Popen(
            [
                sys.executable,
                ProgressBarWidget.__file__,
                self._shmPath,
                iconPath,
                bgColor,
                fgColor,
                str(screenIndex),
            ],
            startupinfo=si,
        )

        if sys.platform.startswith("win32"):
            self._bringWindowToForeground()

    def _bringWindowToForeground(self):
        try:
            deadline = time.monotonic() + 2.0
            hwnd = 0
            while time.monotonic() < deadline:
                hwnd = win32gui.FindWindow(None, self.title)
                if hwnd:
                    break
                time.sleep(0.05)
            if hwnd:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
        except pywintypes.error:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._release()

    def __del__(self):
        self._release()

    def _release(self):
        if self.proc is not None:
            # Graceful shutdown: zero the shared buffer. The widget polls and
            # quits when it reads an empty payload. This is the only reliable
            # shutdown signal on Windows, where sys.executable is a wrapper
            # that spawns the real interpreter as a grandchild — terminate()
            # kills only the wrapper and leaves the window running.
            if self.sharedMem is not None:
                self.sharedMem[:] = b"\x00" * _SHM_SIZE
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._killProcessTree()
            self.proc = None

        if self.sharedMem is not None:
            os.environ.pop(_SHM_PATH_ENV_VAR, None)
            self.sharedMem.close()
            self._shmFile.close()
            self.sharedMem = None
            self._shmFile = None
            try:
                os.unlink(self._shmPath)
            except OSError as e:
                logging.debug(f"Could not remove {self._shmPath}: {e}")

    def _killProcessTree(self):
        if sys.platform.startswith("win32"):
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            self.proc.kill()
        self.proc.wait()

    def setTitle(self, title: str):
        self.title = title
        self.sharedDict["title"] = title
        self._updateSharedMem()

    def setMessage(self, message: str):
        self.sharedDict["message"] = message
        self._updateSharedMem()

    def setProgress(self, progress: int):
        self.sharedDict["progress"] = progress
        self._updateSharedMem()

    def nextStep(self, progress: int, message: str):
        self.setProgress(progress)
        self.setMessage(message)

    def _updateSharedMem(self):
        data = json.dumps(self.sharedDict).encode()
        self.sharedMem[:] = data + b"\x00" * (_SHM_SIZE - len(data))
