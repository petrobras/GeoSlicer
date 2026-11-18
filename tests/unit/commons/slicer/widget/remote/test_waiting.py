"""The dialog shown while the job monitor works for someone.

It never touches the work: it polls futures and says when they are all done,
or that the person stopped waiting, or that time ran out.
"""

import importlib.util
import sys
import types
from concurrent.futures import Future
from pathlib import Path

import pytest


class _Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in self.slots:
            slot(*args)


class _Widget:
    """Enough of a Qt widget for the dialog to build itself."""

    def __init__(self, *args, **kwargs):
        self.clicked = _Signal()
        self.timeout = _Signal()
        self.finished = _Signal()

    def __getattr__(self, name):
        # Everything else the dialog touches is layout and styling plumbing.
        return lambda *args, **kwargs: None


@pytest.fixture
def waiting(monkeypatch):
    """The real module, loaded against stubbed Qt."""
    import commons

    qt = types.ModuleType("qt")
    for name in ("QDialog", "QLabel", "QProgressBar", "QPushButton", "QVBoxLayout", "QHBoxLayout", "QTimer"):
        setattr(qt, name, type(name, (_Widget,), {}))
    qt.Qt = types.SimpleNamespace(ApplicationModal=2)
    # Deferred calls run at once here; what matters is that they are deferred.
    qt.QTimer.singleShot = staticmethod(lambda msec, callback: callback())
    monkeypatch.setitem(sys.modules, "qt", qt)

    source = Path(commons.__file__).parent / "slicer" / "widget" / "remote" / "waiting.py"
    spec = importlib.util.spec_from_file_location("waiting_under_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def close(outcome, code):
        def done(self):
            self.outcome = outcome
            self.finished.emit(code)

        return done

    module.WaitingDialog.accept = close("accepted", 1)
    module.WaitingDialog.reject = close("rejected", 0)
    return module


def dialog_for(waiting, futures, **kwargs):
    dialog = waiting.WaitingDialog("Title", "Working...", futures, **kwargs)
    dialog.outcome = None
    return dialog


def run(waiting, monkeypatch, futures, drive, **kwargs):
    """wait(), with `drive` standing in for the dialog's event loop."""
    monkeypatch.setattr(waiting.WaitingDialog, "exec_", drive, raising=False)
    return waiting.wait(futures, "Title", "Working...", **kwargs)


def done(result=None):
    future = Future()
    future.set_result(result)
    return future


def test_keeps_waiting_while_any_future_is_pending(waiting):
    dialog = dialog_for(waiting, [done(), Future()])

    dialog._poll()

    assert dialog.outcome is None


def test_closes_once_every_future_is_done(waiting):
    dialog = dialog_for(waiting, [done(), done()])

    dialog._poll()

    assert dialog.outcome == "accepted"


def test_waits_forever_without_a_timeout(waiting):
    # Cancelling a batch of jobs has no natural deadline; the button is the way out.
    dialog = dialog_for(waiting, [Future()])
    dialog._deadline = None

    dialog._poll()

    assert dialog.outcome is None
    assert not dialog.timedOut


def test_reports_everything_done(waiting, monkeypatch):
    futures = [done(), done()]

    assert run(waiting, monkeypatch, futures, lambda dialog: dialog._poll()) is True


def test_reports_that_the_person_stopped_waiting(waiting, monkeypatch):
    futures = [done(), Future()]

    assert run(waiting, monkeypatch, futures, lambda dialog: dialog.reject()) is False


def test_work_that_finishes_as_the_button_is_clicked_still_counts(waiting, monkeypatch):
    future = Future()

    def drive(dialog):
        future.set_result(None)
        dialog.reject()

    assert run(waiting, monkeypatch, [future], drive) is True


def test_raises_when_time_runs_out(waiting, monkeypatch):
    def drive(dialog):
        dialog._deadline = 0
        dialog._poll()

    with pytest.raises(TimeoutError):
        run(waiting, monkeypatch, [Future()], drive, timeoutSeconds=60)


def test_when_done_returns_before_the_work_is_done(waiting):
    """A Cancel/Delete asked from a job's row removes that very row. Waiting in
    a nested event loop meant returning into the deleted row and its menu,
    which took GeoSlicer down; whenDone leaves the caller's stack at once."""
    reported = []

    dialog = waiting.whenDone([Future()], reported.append, "Title", "Working...")

    assert reported == []
    dialog._poll()
    assert reported == []


def test_when_done_reports_once_everything_is_done(waiting):
    future = Future()
    reported = []
    dialog = waiting.whenDone([future], reported.append, "Title", "Working...")

    future.set_result(None)
    dialog._poll()

    assert dialog.outcome == "accepted"
    assert reported == [True]


def test_when_done_reports_that_the_person_stopped_waiting(waiting):
    reported = []
    dialog = waiting.whenDone([Future()], reported.append, "Title", "Working...")

    dialog.reject()

    assert reported == [False]


def test_clicking_the_button_stops_the_waiting(waiting):
    """clicked carries the button's checked flag, and reject() takes none:
    PythonQt refused the call, so "Continue in background" did nothing but
    raise."""
    reported = []
    dialog = waiting.whenDone([Future()], reported.append, "Title", "Working...", buttonText="Continue in background")

    dialog.button.clicked.emit(False)

    assert dialog.outcome == "rejected"
    assert reported == [False]
