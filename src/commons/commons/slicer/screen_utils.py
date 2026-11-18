import sys
import ctypes

import qt

import slicer.util


def getMainWindow():
    try:
        mainWindow = slicer.modules.AppContextInstance.mainWindow
    except AttributeError:
        mainWindow = slicer.util.mainWindow()

    return mainWindow


def getScaleFactorForDevice(deviceId: int) -> int:
    if sys.platform == "win32":
        return ctypes.windll.shcore.GetScaleFactorForDevice(deviceId) / 100.0
    elif sys.platform == "linux":
        mainWindow = getMainWindow()
        return mainWindow.devicePixelRatio()
    else:
        raise NotImplementedError("This function is not implemented for this OS.")


def getApplicationCurrentScreen() -> int:
    """
    Get the current screen number of the application.
    """
    mainWindow = getMainWindow()

    # Get the geometry of the main window
    windowGeometry = mainWindow.frameGeometry

    # Find the screen where the main window is located
    for i, screen in enumerate(qt.QGuiApplication.screens()):
        if screen.geometry.intersects(windowGeometry):
            return i

    return 1
