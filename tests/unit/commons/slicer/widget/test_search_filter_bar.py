"""The Actions menu of the job search bar.

QAction.triggered carries a `checked` flag. Connected straight to one of the
bar's argument-less signals, PythonQt called the signal with it and refused --
"Called deleteRequested() -> void with wrong number of arguments: (False,)" --
so Cancel/Delete Visible and Reconnect Visible did nothing.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class _Signal:
    """A PythonQt signal: calling it directly checks the arguments, like emit."""

    def __init__(self, *argumentTypes):
        self.arity = len(argumentTypes)
        self.slots = []
        self.emitted = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        if len(args) != self.arity:
            raise ValueError(f"Called signal with wrong number of arguments: {args}")
        self.emitted.append(args)

    def __call__(self, *args):
        self.emit(*args)


class _Action:
    def __init__(self):
        self.triggered = _Signal(bool)

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture
def bar(monkeypatch):
    """A SearchFilterBar from the real module, loaded against stubbed Qt."""
    import commons
    import commons.slicer

    menus = []

    class Menu:
        def __init__(self, parent=None):
            self.actions = {}
            menus.append(self)

        def addAction(self, text):
            self.actions[text] = _Action()
            return self.actions[text]

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    qt = types.ModuleType("qt")
    qt.QWidget = type("QWidget", (), {})
    qt.QMenu = Menu
    qt.Signal = _Signal
    monkeypatch.setitem(sys.modules, "qt", qt)
    monkeypatch.setattr(commons.slicer, "ui", types.ModuleType("commons.slicer.ui"), raising=False)

    source = Path(commons.__file__).parent / "slicer" / "widget" / "search_filter_bar.py"
    spec = importlib.util.spec_from_file_location("search_filter_bar_under_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Only the menu is under test; the rest of the bar is layout.
    instance = module.SearchFilterBar.__new__(module.SearchFilterBar)
    instance.actionsBtn = MagicMock()
    instance.menus = menus
    return instance


@pytest.mark.parametrize(
    "text, signal",
    [("Cancel/Delete Visible", "deleteRequested"), ("Reconnect Visible", "resumeRequested")],
)
def test_an_actions_menu_entry_emits_its_request(bar, text, signal):
    bar._showActionsMenu()
    action = bar.menus[-1].actions[text]

    for slot in action.triggered.slots:
        slot(False)  # what PythonQt passes along: triggered(bool checked)

    assert getattr(bar, signal).emitted == [()]
