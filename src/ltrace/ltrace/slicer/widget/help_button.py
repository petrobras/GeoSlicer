import logging
import typing
from pathlib import Path
import markdown
import qt
from ltrace.slicer.helpers import get_scripted_modules_path, svgToQIcon
from ltrace.slicer_utils import getResourcePath
import re


def is_url(url: str) -> bool:
    if url is None:
        return False

    return re.match(r"^(?:https|file)s?://", url) is not None


class HelpButton(qt.QToolButton):

    DEFAULT_URL = (getResourcePath("manual") / "index.html").as_posix()

    def __init__(
        self,
        message: str = None,
        url: str = None,
        replacer: typing.Union[None, typing.Callable] = None,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)

        if not is_url(url):
            url = None

        self.md_message = message
        self.url = url
        self.setStyleSheet("border : none;")
        self.setIcon(svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "CircleHelp.svg"))
        self.setIconSize(qt.QSize(18, 18))
        self.clicked.connect(self.handleClick)
        self.replacer = replacer

    def handleClick(self):
        if self.md_message:
            self.showFloatingMessage(self.md_message)
        else:
            self.handleLinkClick(self.url)

    def updateLink(self, helpURL: str) -> None:
        # check if it is a valid URI/URL
        if not is_url(helpURL):
            helpURL = self.DEFAULT_URL

        self.url = helpURL

    def showFloatingMessage(self, message: str) -> None:

        message = self.replacer(message) if self.replacer else message
        message = markdown.markdown(message)

        pos = qt.QCursor.pos() - qt.QPoint(10, 10)

        text_browser = qt.QTextBrowser(self)
        text_browser.setWindowFlags(qt.Qt.ToolTip)
        text_browser.setHtml(message)
        text_browser.setOpenExternalLinks(False)  # Disable automatic link handling
        text_browser.anchorClicked.connect(self.handleLinkClick)
        text_browser.setStyleSheet(
            """
            padding: 20px;
            border: 1px;
            border-style: outset;
            font-size: 12px;
            """
        )
        text_browser.setWordWrapMode(qt.QTextOption.WordWrap)
        text_browser.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        text_browser.setVerticalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)

        # Adjust size to fit content
        document = text_browser.document
        document.setTextWidth(400)  # Set a maximum width
        size = document.size.toSize()
        padding = 70
        text_browser.setFixedSize(qt.QSize(size.width() + padding, size.height() + padding))

        text_browser.move(pos)
        text_browser.show()

        text_browser.installEventFilter(self)

        text_browser.move(pos)
        text_browser.show()

        text_browser.installEventFilter(self)
        self.text_browser = text_browser

    # IMPORTANT: this method
    def handleLinkClick(self, url: typing.Union[str, qt.QUrl]) -> None:
        try:
            if isinstance(url, qt.QUrl) and url.isValid():
                qt.QDesktopServices.openUrl(url)
                return

            if isinstance(url, str) and is_url(url) and url.lower().endswith(".html"):
                if qt.QDesktopServices.openUrl(qt.QUrl(url)):
                    return

            manualPath = (getResourcePath("manual") / "index.html").as_posix()
            qt.QDesktopServices.openUrl(qt.QUrl(f"file:///{manualPath}"))
        finally:
            if hasattr(self, "text_browser"):
                self.text_browser.hide()

    def eventFilter(self, obj, event) -> None:
        if event.type() == qt.QEvent.Leave or event.type() == qt.QEvent.MouseButtonRelease:
            obj.hide()
