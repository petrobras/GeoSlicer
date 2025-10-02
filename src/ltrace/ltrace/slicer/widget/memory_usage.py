import qt
import psutil

from ltrace.slicer_utils import getResourcePath
from ltrace.slicer.helpers import svgToQIcon


class MemoryUsageWidget(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = qt.QHBoxLayout()
        layout.setContentsMargins(8, 0, 16, 0)
        layout.setSpacing(3)

        icon = svgToQIcon((getResourcePath("Icons") / "svg" / "Memory.svg").as_posix())
        self.labelIcon = qt.QLabel()
        self.labelIcon.setPixmap(icon.pixmap(16, 16))
        self.memoryCounter = qt.QLabel("")
        self.memoryUsedTimer = qt.QTimer()

        layout.addWidget(self.labelIcon)
        layout.addWidget(self.memoryCounter)
        self.setLayout(layout)

        self.setStyleSheet(
            "QLabel {\
                font-size: 12px;\
            }"
        )
        self.toolTip = "Memory Usage"

    def update(self, value, total):
        percent = int((value / total) * 100)
        text = f"{value} / {total}GB  ({percent}%)"
        if text != self.memoryCounter.text:
            self.memoryCounter.setText(text)

    def start(self):
        self.memoryUsedTimer.setInterval(1000)
        self.memoryUsedTimer.timeout.connect(self.__poller)
        self.memoryUsedTimer.start()

    def __poller(self):
        used_gb = int(round(psutil.virtual_memory().used / (1024**3)))
        total_gb = int(round(psutil.virtual_memory().total / (1024**3)))
        self.update(used_gb, total_gb)
