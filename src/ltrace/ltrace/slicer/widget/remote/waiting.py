import time

import qt


class WaitingDialog(qt.QDialog):
    """A busy bar and one button, shown while the job monitor works for someone.

    Only waits: the futures are polled from this dialog's own event loop, so
    the interface stays responsive and nothing here touches the work itself.
    Closes on its own once every future is done. The button, like Esc, stops
    the waiting; what that means for the work is the caller's to say.
    """

    POLL_INTERVAL_MS = 100

    def __init__(self, title, text, futures, buttonText="Cancel", timeoutSeconds=None, parent=None) -> None:
        super().__init__(parent)

        self.futures = list(futures)
        self.timedOut = False
        self._deadline = None if timeoutSeconds is None else time.monotonic() + timeoutSeconds

        self.setWindowTitle(title)
        self.setMinimumWidth(320)

        busy = qt.QProgressBar()
        busy.setRange(0, 0)  # indeterminate
        busy.setTextVisible(False)

        self.button = qt.QPushButton(buttonText)
        # Not connected directly: PythonQt would hand reject() the checked flag.
        self.button.clicked.connect(lambda checked: self.reject())

        buttons = qt.QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.button)

        layout = qt.QVBoxLayout(self)
        layout.addWidget(qt.QLabel(text))
        layout.addWidget(busy)
        layout.addLayout(buttons)

        self.timer = qt.QTimer(self)
        self.timer.setInterval(self.POLL_INTERVAL_MS)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def _poll(self) -> None:
        if all(future.done() for future in self.futures):
            self.accept()
        elif self._deadline is not None and time.monotonic() > self._deadline:
            self.timedOut = True
            self.reject()


def wait(futures, title, text, buttonText="Cancel", timeoutSeconds=None, parent=None) -> bool:
    """Show a WaitingDialog until every future is done.

    Returns True once they all are, and False if the person stopped waiting
    first. Raises TimeoutError when timeoutSeconds ran out.
    """
    futures = list(futures)

    dialog = WaitingDialog(title, text, futures, buttonText=buttonText, timeoutSeconds=timeoutSeconds, parent=parent)
    try:
        dialog.exec_()
        timedOut = dialog.timedOut
    finally:
        dialog.timer.stop()
        dialog.deleteLater()

    if all(future.done() for future in futures):
        return True

    if timedOut:
        raise TimeoutError(f"Still waiting after {timeoutSeconds} s.")

    return False


def whenDone(futures, onDone, title, text, buttonText="Cancel", parent=None) -> WaitingDialog:
    """Like wait(), but returns at once and calls onDone(finished) when the waiting ends.

    For a slot whose own widget the work may delete. wait() runs a nested
    event loop, and a Cancel/Delete asked from a job's row removes that very
    row while the loop runs -- returning into the deleted row and its menu
    took GeoSlicer down. `finished` is True if every future is done, False if
    the person stopped waiting.
    """
    futures = list(futures)

    dialog = WaitingDialog(title, text, futures, buttonText=buttonText, parent=parent)
    # As modal as exec_() would make it, without exec_()'s nested event loop.
    dialog.setWindowModality(qt.Qt.ApplicationModal)

    def finish(_result):
        dialog.timer.stop()
        dialog.deleteLater()
        allDone = all(future.done() for future in futures)
        # Not from here: onDone may open a message box, and its event loop
        # would run with this dialog's own slot still on the stack.
        qt.QTimer.singleShot(0, lambda: onDone(allDone))

    dialog.finished.connect(finish)
    dialog.show()
    return dialog
