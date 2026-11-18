"""Mocks for the Slicer modules that are not available in the unit test environment.

The root conftest installs them in the pytest process. This directory is also put on sys.path, so a child
process started with "spawn" (the default on Windows), which does not run the conftest, gets the same mocks
when it imports one of the stub packages next to this file (slicer, ctk, qt, SegmentEditorEffects).
"""

import sys
import tempfile
from unittest.mock import MagicMock, PropertyMock

_installed = False


def mock_package(name):
    m = MagicMock()
    m.__path__ = []
    m.__spec__ = None
    sys.modules[name] = m
    return m


# Classes needed for mocking qt.QWidget and qt.QObject
class QWidgetMock(object):
    setLayout = MagicMock()
    destroyed = MagicMock()

    def __init__(self, *args, **kwargs):
        pass


class QObjectMeta(type):
    pass


class QObjectMock(metaclass=QObjectMeta):
    def __init__(self, *args, **kwargs):
        pass


def install():
    global _installed
    if _installed:
        return
    _installed = True

    slicerMock = mock_package("slicer")
    slicerMock.app.temporaryPath = tempfile.TemporaryDirectory().name

    # Setup ScriptedLoadableModule mocks
    ScriptedLoadableModuleMock = MagicMock()
    ScriptedLoadableModuleTestMock = type("ScriptedLoadableModuleTest", (object,), {})
    ScriptedLoadableModuleMock.ScriptedLoadableModuleTest = ScriptedLoadableModuleTestMock
    ScriptedLoadableModuleLogicMock = type("ScriptedLoadableModuleLogic", (object,), {})
    ScriptedLoadableModuleMock.ScriptedLoadableModuleLogic = ScriptedLoadableModuleLogicMock
    slicerMock.ScriptedLoadableModule = ScriptedLoadableModuleMock

    # Other mandatory mocks
    mock_package("ctk")
    mock_package("qt")
    mock_package("SegmentEditorEffects")

    # Mock submodules that are imported as 'import slicer.util' etc.
    sys.modules["slicer.util"] = slicerMock.util

    sys.modules["qt"].QWidget = QWidgetMock
    sys.modules["qt"].QObject = QObjectMock

    # For some reason, cProfile is not available in the installed Python from slicerltrace-windows docker image
    sys.modules["cProfile"] = MagicMock()

    # Mock commons.slicer.tests.ltrace_tests_widget before any import that might trigger its loading
    aTreeViewItemMock = MagicMock()
    aTreeViewItemMock.testData = PropertyMock()
    ltraceTestsWidgetMock = MagicMock()
    ltraceTestsWidgetMock.ATreeViewItem = aTreeViewItemMock
    sys.modules["commons.slicer.tests.ltrace_tests_widget"] = ltraceTestsWidgetMock
