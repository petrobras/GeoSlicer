from enum import Enum

import qt

from commons.slicer.helpers import svgToQIcon
from commons.slicer_utils import getResourcePath


class MessageLevel(Enum):
    SUCCESS = "success"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# level -> (icon, accent, background). SUCCESS uses the GeoSlicer accent
_STYLE = {
    MessageLevel.SUCCESS: ("CircleCheck", "#26c252", "#16301f"),
    MessageLevel.INFO: ("Info", "#64b5f6", "#1a2c40"),
    MessageLevel.WARNING: ("TriangleAlert", "#f0b429", "#3a2f15"),
    MessageLevel.ERROR: ("AlertCircle", "#ef5350", "#3f1f21"),
}


def levelColor(level: MessageLevel) -> str:
    """Accent color of a message level."""
    return _STYLE[level][1]


# Zero-width space: lets word wrap break long paths after their separators instead of clipping them
_BREAK_OPPORTUNITY = chr(0x200B)


def _wrappable(text: str) -> str:
    return text.replace("\\", "\\" + _BREAK_OPPORTUNITY).replace("/", "/" + _BREAK_OPPORTUNITY)


class MessageBanner(qt.QFrame):
    """Colored banner that reports the outcome of an action, with an icon.

    Hidden until a message is shown, then keeps the last message. Each new message fades in, so repeating the same
    message is still noticed.
    """

    FADE_MS = 250

    def __init__(self, parent=None):
        super().__init__(parent)
        self.objectName = "Message Banner"
        # Style sheet hook: a plain QFrame selector would also match the QLabel children
        self.setProperty("messageBanner", True)
        self.level = None
        self.__text = ""

        self.iconLabel = qt.QLabel()
        self.iconLabel.setFixedSize(18, 18)

        self.textLabel = qt.QLabel()
        self.textLabel.objectName = "Message Banner Text"
        self.textLabel.setWordWrap(True)
        self.textLabel.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)

        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        layout.addWidget(self.iconLabel, 0, qt.Qt.AlignTop)
        layout.addWidget(self.textLabel, 1)

        self.__opacity = qt.QGraphicsOpacityEffect(self)
        self.__opacity.setOpacity(1.0)
        self.setGraphicsEffect(self.__opacity)
        self.__fade = qt.QPropertyAnimation(self.__opacity, "opacity", self)
        self.__fade.setDuration(self.FADE_MS)
        self.__fade.setStartValue(0.0)
        self.__fade.setEndValue(1.0)

        self.visible = False

    @property
    def text(self) -> str:
        return self.__text

    def showMessage(self, text: str, level: MessageLevel = MessageLevel.INFO) -> None:
        if not text:
            self.clear()
            return

        self.level = level
        iconName, accent, background = _STYLE[level]
        icon = svgToQIcon(getResourcePath("Icons") / "svg" / f"{iconName}.svg", color=accent)
        self.iconLabel.setPixmap(icon.pixmap(qt.QSize(18, 18)))
        self.setStyleSheet(
            f"QFrame[messageBanner=true] {{ background-color: {background}; border: 1px solid {accent}; "
            "border-radius: 4px; }"
        )
        self.__text = text
        self.textLabel.setText(_wrappable(text))
        self.visible = True

        self.__fade.stop()
        self.__fade.start()

    def clear(self) -> None:
        self.__fade.stop()
        self.level = None
        self.__text = ""
        self.textLabel.setText("")
        self.visible = False
