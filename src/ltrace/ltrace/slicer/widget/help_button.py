import markdown
import qt


class HelpButton(qt.QToolButton):
    def __init__(self, message: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.message = message
        self.html_message = markdown.markdown(message)
        self.setStyleSheet("border : none;")
        self.setIcon(qt.QApplication.style().standardIcon(qt.QStyle.SP_MessageBoxQuestion))
        self.setIconSize(qt.QSize(20, 20))
        self.setEnabled(True)
        self.clicked.connect(lambda: self.showFloatingMessage(self.html_message))

    def updateMessage(self, message: str) -> None:
        self.message = message
        self.html_message = markdown.markdown(message)

    def showFloatingMessage(self, message: str = "") -> None:
        pos = qt.QCursor.pos() - qt.QPoint(10, 10)

        label = qt.QLabel(self)
        label.setWindowFlags(qt.Qt.ToolTip)
        label.setTextFormat(qt.Qt.RichText)
        label.setTextInteractionFlags(qt.Qt.TextBrowserInteraction)
        label.setOpenExternalLinks(True)
        label.setStyleSheet(
            """
            padding: 20px;
            border: 1px;
            border-style: outset;
            -qt-block-indent: 0;
            font-size: 12px;
            """
        )
        label.setText(message)
        label.setWordWrap(True)
        label.setMaximumWidth(500)
        label.move(pos)
        label.show()

        label.installEventFilter(self)

    def eventFilter(self, object, event) -> None:
        if event.type() == qt.QEvent.Leave or event.type() == qt.QEvent.MouseButtonRelease:
            object.hide()
