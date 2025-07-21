import qt
from vtk import VTK_ENCODING_NONE


class TextWidget(qt.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.matches = []
        self.currentMatchIndex = -1
        self.setup()

    def setup(self):
        self.fmtClear = qt.QTextCharFormat()
        self.fmtClear.setBackground(qt.QBrush(qt.Qt.NoBrush))

        self.fmtHighlightYellow = qt.QTextCharFormat()
        self.fmtHighlightYellow.setForeground(qt.QColor("black"))
        self.fmtHighlightYellow.setBackground(qt.QColor("yellow"))

        self.fmtHighlightOrange = qt.QTextCharFormat()
        self.fmtHighlightOrange.setForeground(qt.QColor("black"))
        self.fmtHighlightOrange.setBackground(qt.QColor("orange"))

        self.textEdit = qt.QPlainTextEdit(self)
        self.textEdit.setReadOnly(True)
        self.textEdit.setMinimumHeight(600)
        font = qt.QFont()
        font.setFamily("Courier New")
        self.textEdit.setFont(font)

        self.searchField = qt.QLineEdit(self)
        self.searchField.setPlaceholderText("Search...")

        self.downButton = qt.QPushButton("↓")
        self.downButton.setFixedWidth(30)
        self.upButton = qt.QPushButton("↑")
        self.upButton.setFixedWidth(30)

        searchLayout = qt.QHBoxLayout()
        searchLayout.addWidget(self.searchField)
        searchLayout.addWidget(self.downButton)
        searchLayout.addWidget(self.upButton)

        layout = qt.QVBoxLayout(self)
        layout.addLayout(searchLayout)
        layout.addWidget(self.textEdit)

        self.searchField.textChanged.connect(self.highlightMatches)
        self.searchField.returnPressed.connect(lambda: self.scrollToMatch(1))
        self.upButton.clicked.connect(lambda: self.scrollToMatch(-1))
        self.downButton.clicked.connect(lambda: self.scrollToMatch(1))

    def setNode(self, node):
        if node.GetEncoding() == VTK_ENCODING_NONE:
            self.textEdit.setPlainText(f"Binary content not displayed ({len(node.GetText())} bytes)")
        else:
            self.textEdit.setPlainText(node.GetText())
        self.highlightMatches()

    def _applyFormatToMatch(self, matchIndex, charFormat):
        if matchIndex < 0 or matchIndex >= len(self.matches):
            return

        startPos = self.matches[matchIndex]

        cursor = self.textEdit.textCursor()
        cursor.beginEditBlock()
        cursor.setPosition(startPos)
        cursor.movePosition(qt.QTextCursor.Right, qt.QTextCursor.KeepAnchor, len(self.searchField.text))
        cursor.mergeCharFormat(charFormat)
        cursor.endEditBlock()

    def highlightMatches(self):
        cursor = self.textEdit.textCursor()

        cursor.beginEditBlock()
        cursor.setPosition(0)
        cursor.movePosition(qt.QTextCursor.End, qt.QTextCursor.KeepAnchor)
        cursor.setCharFormat(self.fmtClear)
        cursor.endEditBlock()

        pattern = self.searchField.text
        self.matches = []
        self.currentMatchIndex = -1

        flags = qt.QTextDocument.FindFlags()

        cursor.beginEditBlock()
        cursor.setPosition(0)
        findCursor = self.textEdit.document().find(pattern, 0, flags)  # Start search from beginning

        while not findCursor.isNull():
            self.matches.append(findCursor.selectionStart())
            findCursor.mergeCharFormat(self.fmtHighlightYellow)
            # Find next occurrence using the same findCursor
            findCursor = self.textEdit.document().find(pattern, findCursor, flags)

        cursor.endEditBlock()  # This block was for yellow highlights.

    def scrollToMatch(self, direction):
        if not self.matches:
            return

        if self.currentMatchIndex != -1:
            self._applyFormatToMatch(self.currentMatchIndex, self.fmtHighlightYellow)

        if self.currentMatchIndex == -1:
            self.currentMatchIndex = 0 if direction == 1 else len(self.matches) - 1
        else:
            self.currentMatchIndex = (self.currentMatchIndex + direction + len(self.matches)) % len(self.matches)

        self._applyFormatToMatch(self.currentMatchIndex, self.fmtHighlightOrange)

        cursor = self.textEdit.textCursor()
        cursor.setPosition(self.matches[self.currentMatchIndex])
        self.textEdit.setTextCursor(cursor)
        self.textEdit.centerCursor()
