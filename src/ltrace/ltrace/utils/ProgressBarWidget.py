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

        try:
            self.sharedMem = SharedMemory(name="ProgressBar", create=False)
        except Exception as error:
            self.sharedMem = None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.updateFromSharedMem)
        self.timer.start(100)

        self.errorCount = 0
        self.destroyed.connect(self.__del__)

    def updateFromSharedMem(self):
        try:
            self.sharedMem = SharedMemory(name="ProgressBar", create=False)
        except Exception:
            self.errorCount += 1

            if self.errorCount >= 30:
                self.timer.stop()
                self.timer = None
                self.deleteLater()

            return

        data = bytes(self.sharedMem.buf)
        data = data[: data.index(b"\x00")]
        if not data:
            self.deleteLater()
            return
        data = json.loads(data)

        self.setWindowTitle(data["title"])
        self.label.setText(data["message"])
        if "progress" in data:
            progress = data["progress"]
            self.progressBar.show()
            self.progressBar.setValue(progress)

    def __del__(self):
        self.__releaseProcess()

    def __releaseProcess(self):
        if self.sharedMem is not None:
            try:
                self.sharedMem.close()
                self.sharedMem.unlink()
            except:
                pass

            del self.sharedMem
            self.sharedMem = None


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
