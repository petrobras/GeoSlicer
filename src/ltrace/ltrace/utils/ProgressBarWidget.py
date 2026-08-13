import json
import mmap
import sys
from pathlib import Path

from PySide2.QtCore import Qt, QTimer
from PySide2.QtGui import QIcon
from PySide2.QtWidgets import QApplication, QLabel, QProgressBar, QVBoxLayout, QWidget


_STYLESHEET = """
QWidget {
    background-color: %s;
    color: %s;
    font-family: "Inter", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", sans-serif;
    font-weight: 600;
    font-size: 9pt;
}

QProgressBar {
    background-color: #535353;
    border-radius: 4px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #26C252;
    border-radius: 4px;
}
"""


class ProgressBarWidget(QWidget):
    def __init__(self, shmPath: str):
        super().__init__()
        self.label = QLabel()

        self.progressBar = QProgressBar()
        self.progressBar.hide()

        self.busyIndicator = QProgressBar()
        self.busyIndicator.setMinimum(0)
        self.busyIndicator.setMaximum(0)
        self.busyIndicator.setValue(0)

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.progressBar)
        layout.addWidget(self.busyIndicator)

        self.setLayout(layout)
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.CustomizeWindowHint
            | Qt.MSWindowsFixedSizeDialogHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowMinimizeButtonHint
        )
        self.setMinimumWidth(400)

        self._shmFile = open(shmPath, "r+b")
        self._shm = mmap.mmap(self._shmFile.fileno(), 0)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.updateFromSharedMem)
        self.timer.start(100)

    def updateFromSharedMem(self):
        raw = bytes(self._shm[:])
        head = raw.split(b"\x00", 1)[0]
        if not head:
            # Parent zeroed the buffer as a shutdown signal.
            QApplication.quit()
            return
        data = json.loads(head)
        self.setWindowTitle(data["title"])
        self.label.setText(data["message"])
        if "progress" in data:
            self.progressBar.show()
            self.progressBar.setValue(data["progress"])


def main(shmPath: str, iconPath: str, bgColor: str = "#323232", fgColor: str = "#FFFFFF", screenIndex: str = "0"):
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(iconPath))
    widget = ProgressBarWidget(shmPath)
    widget.setStyleSheet(_STYLESHEET % (bgColor, fgColor))

    logPath = Path(__file__).parent / "ProgressBarWidget.debug.log"
    logFile = open(logPath, "w", encoding="utf-8")

    screens = app.screens()
    for i, s in enumerate(screens):
        g = s.geometry()
        ag = s.availableGeometry()
    primary = app.primaryScreen()
    pg = primary.geometry()

    try:
        index = int(screenIndex)
    except ValueError:
        index = 0

    if index < len(screens):
        screen = screens[index]
    else:
        screen = app.primaryScreen()
    geometry = screen.geometry()

    widget.adjustSize()
    raw_w = widget.width()
    raw_h = widget.height()
    hint_w = widget.sizeHint().width()
    hint_h = widget.sizeHint().height()
    width = raw_w if raw_w > 0 else hint_w
    height = raw_h if raw_h > 0 else hint_h

    dx = (geometry.width() - width) // 2
    dy = (geometry.height() - height) // 2
    x = geometry.x() + dx
    y = geometry.y() + dy
    widget.move(x, y)

    widget.show()
    current_screen = widget.screen() if hasattr(widget, "screen") else None
    if current_screen is not None:
        cg = current_screen.geometry()

    # On Windows, move() positions the outer frame (title bar + borders) at (x, y), so the
    # first move() left the content below center by ~title_bar_height. Re-center by frame.
    # On Linux, move() positions the client area, so no correction is needed. Guarding by
    # platform avoids a mis-centering race on X11/Wayland-SSD where processEvents() could
    # pull in WM frame extents and make frameGeometry() larger than geometry().
    if sys.platform == "win32":
        QApplication.processEvents()
        fg = widget.frameGeometry()
        x2 = geometry.x() + (geometry.width() - fg.width()) // 2
        y2 = geometry.y() + (geometry.height() - fg.height()) // 2
        widget.move(x2, y2)
    app.exec_()
    logFile.close()


if __name__ == "__main__":
    main(*sys.argv[1:6])
