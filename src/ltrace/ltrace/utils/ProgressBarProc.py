from multiprocessing.shared_memory import SharedMemory

import time
import json
import sys
import subprocess
import qt
import slicer
import logging

if sys.platform.startswith("win32"):
    import win32gui
    import win32con
    import pywintypes

from . import ProgressBarWidget


from ..slicer_utils import base_version


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
        bg_color = palette.color(qt.QPalette.Background).name()
        fg_color = palette.color(qt.QPalette.WindowText).name()

        si = None
        if sys.platform.startswith("win32"):
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE

        # Due to a Python bug it's not possible to unlink() shared memory
        # on Windows so we create the file once and reuse it when needed.
        # https://bugs.python.org/issue40882
        try:
            self.sharedMem = SharedMemory(name="ProgressBar", create=True, size=1024)
        except Exception as error:
            logging.debug(
                f"Failed to create shared memory. Trying to open existent resource if available. Error: {error}"
            )
            self.sharedMem = SharedMemory(name="ProgressBar", create=False)

        self.sharedDict = {}
        self.progress = None

        progressbar_icon_file = "GeoSlicer-ProgressBar.ico"
        icon_path = f"lib/{base_version()}/qt-scripted-modules/Resources/{progressbar_icon_file}"

        self.setTitle("Processing")
        self.setMessage("Processing, please wait...")

        self.proc = subprocess.Popen(
            [
                sys.executable,
                ProgressBarWidget.__file__,
                slicer.app.toSlicerHomeAbsolutePath(icon_path),
                bg_color,
                fg_color,
            ],
            startupinfo=si,
        )
        try:
            if sys.platform.startswith("win32"):
                # time to find the process
                time.sleep(1)
                window_title = self.title
                hwnd = win32gui.FindWindow(None, window_title)

                # If the window handle is found, bring it to the foreground
                if hwnd:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(hwnd)
        except pywintypes.error as e:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.sharedMem.buf[:] = b"\x00" * self.sharedMem.size

        self.__releaseProcess()

    def __del__(self):
        self.__releaseProcess()

    def __releaseProcess(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)  # Wait up to 5 seconds for the subprocess to terminate
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()

            del self.proc
            self.proc = None

        if self.sharedMem is not None:
            try:
                self.sharedMem.close()
                self.sharedMem.unlink()
            except:
                pass

            del self.sharedMem
            self.sharedMem = None

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
        dataBytes = json.dumps(self.sharedDict).encode()
        self.sharedMem.buf[:] = b"\x00" * self.sharedMem.size
        self.sharedMem.buf[: len(dataBytes)] = dataBytes
