import json
import sys

from PySide2.QtCore import Qt, QTimer
from PySide2.QtGui import QIcon
from PySide2.QtWidgets import QApplication, QLabel, QProgressBar, QVBoxLayout, QWidget
from multiprocessing.shared_memory import SharedMemory


class ProgressBarWidget(QWidget):
    def __init__(self):
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

        self.sharedMem = SharedMemory(name="ProgressBar", create=False)

        timer = QTimer(self)
        timer.timeout.connect(self.updateFromSharedMem)
        timer.start(100)

    def updateFromSharedMem(self):
        data = bytes(self.sharedMem.buf)
        data = data[: data.index(b"\x00")]
        if not data:
            self.deleteLater()
            return
        data = json.loads(data)

        self.setWindowTitle(data["title"])
        self.label.setText(data["message"])
        if "progress" in data:
            self.progressBar.show()
            self.progressBar.setValue(data["progress"])


def main(iconPath, bgColor, fgColor):
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(iconPath))
    widget = ProgressBarWidget()
    widget.setStyleSheet("QWidget {background-color: %s; color: %s;}" % (bgColor, fgColor))
    widget.show()
    app.exec_()


if __name__ == "__main__":
    main(*sys.argv[1:4])
