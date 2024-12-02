from pathlib import Path
import markdown
import qt
from ltrace.slicer.helpers import get_scripted_modules_path, svgToQIcon
from ltrace.slicer_utils import getResourcePath


class HelpButton(qt.QToolButton):
    def __init__(self, message: str = None, url: str = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.message = message
        self.url = url
        self.setStyleSheet("border : none;")
        self.setIcon(svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "CircleHelp.svg"))
        self.setIconSize(qt.QSize(18, 18))
        self.clicked.connect(self.handleClick)

    def handleClick(self):
        self.updateMessage(self.message)
        if self.url:
            self.handleLinkClick(self.url)
        else:
            self.showFloatingMessage(self.html_message)

    def updateMessage(self, message: str) -> None:
        self.message = message
        if self.message:
            self.html_message = markdown.markdown(message)

    def updateLink(self, helpURL: str) -> None:
        self.url = helpURL

    def showFloatingMessage(self, message: str = None) -> None:
        if message:
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

    def handleLinkClick(self, url):
        if isinstance(url, qt.QUrl) and url.isValid():
            qt.QDesktopServices.openUrl(url)
            if hasattr(self, "text_browser"):
                self.text_browser.hide()
            return
        if isinstance(url, str) and url.lower().endswith(".html"):
            fileUrl = qt.QUrl(url)
            qt.QDesktopServices.openUrl(fileUrl)
        else:
            manualPath = (getResourcePath("manual") / "Welcome" / "welcome.html").as_posix()
            qt.QDesktopServices.openUrl(qt.QUrl(f"file:///{manualPath}"))

        if hasattr(self, "text_browser"):
            self.text_browser.hide()

    def eventFilter(self, obj, event) -> None:
        if event.type() == qt.QEvent.Leave or event.type() == qt.QEvent.MouseButtonRelease:
            obj.hide()
