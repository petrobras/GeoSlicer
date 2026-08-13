from functools import partial

import qt

from ltrace.slicer import ui


class SearchFilterBar(qt.QWidget):
    searchChanged = qt.Signal(str)
    sortChanged = qt.Signal()
    resumeRequested = qt.Signal()

    SORT_NAME_ASC = "name_asc"
    SORT_NAME_DESC = "name_desc"
    SORT_STATUS = "status"
    SORT_NEWEST = "newest"
    SORT_OLDEST = "oldest"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._sortMode = self.SORT_NEWEST
        self._debounceTimer = qt.QTimer(self)
        self._debounceTimer.setSingleShot(True)
        self._debounceTimer.setInterval(250)  # 250 ms debounce interval
        self._debounceTimer.timeout.connect(self._emitSearch)

        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.searchField = qt.QLineEdit()
        self.searchField.setMinimumHeight(32)
        self.searchField.setStyleSheet("QLineEdit { padding: 4px 8px; }")
        self.searchField.setPlaceholderText("e.g. @host atena @status running")
        self.searchField.setToolTip(
            "<p>Filter jobs using <b>@flag value</b> pairs. Multiple flags are combined with AND logic.</p>"
            "<table>"
            "<tr><td><b>@host</b></td><td>Host name</td></tr>"
            "<tr><td><b>@name</b></td><td>Job name</td></tr>"
            "<tr><td><b>@status</b></td><td>Current status</td></tr>"
            "<tr><td><b>@address</b></td><td>Host address</td></tr>"
            "<tr><td><b>@protocol</b></td><td>Connection protocol</td></tr>"
            "<tr><td><b>@uid</b></td><td>Job unique identifier</td></tr>"
            "<tr><td><b>@type</b></td><td>Job type</td></tr>"
            "</table>"
            "<p>Text without a flag matches against the job label.</p>"
        )
        self.searchField.textChanged.connect(self._onTextChanged)
        layout.addWidget(self.searchField)

        self.filterBtn = ui.ClickableLabel.flatSvgIconButton(
            "ListFilterPlus", tooltip="Filter flags", onClick=self._showFilterMenu
        )
        layout.addWidget(self.filterBtn)

        self.sortBtn = ui.ClickableLabel.flatSvgIconButton(
            "SortDownUp", tooltip="Sort jobs", onClick=self._showSortMenu
        )
        layout.addWidget(self.sortBtn)

        self.actionsBtn = ui.ClickableLabel.flatSvgIconButton(
            "Ellipsis", tooltip="Actions", onClick=self._showActionsMenu
        )
        layout.addWidget(self.actionsBtn)

    def text(self):
        return self.searchField.text

    @property
    def sortMode(self):
        return self._sortMode

    def _onTextChanged(self, text):
        self._debounceTimer.start()

    def _emitSearch(self):
        self.searchChanged.emit(self.searchField.text)

    def _showFilterMenu(self):
        menu = qt.QMenu(self)
        for flag in ("@host ", "@name ", "@status ", "@address ", "@protocol ", "@uid ", "@type "):
            action = menu.addAction(flag.strip())
            action.triggered.connect(partial(self._insertFlag, flag))
        menu.exec_(self.filterBtn.mapToGlobal(self.filterBtn.rect.bottomLeft()))

    def _insertFlag(self, flag, *args):
        current = self.searchField.text
        separator = " " if current and not current.endswith(" ") else ""
        self.searchField.setText(current + separator + flag)
        self.searchField.setFocus()

    def _showSortMenu(self):
        menu = qt.QMenu(self)
        group = qt.QActionGroup(menu)
        group.setExclusive(True)

        sort_options = [
            ("Name (A-Z)", self.SORT_NAME_ASC),
            ("Name (Z-A)", self.SORT_NAME_DESC),
            ("Status", self.SORT_STATUS),
            ("Newest first", self.SORT_NEWEST),
            ("Oldest first", self.SORT_OLDEST),
        ]

        for label, mode in sort_options:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(mode == self._sortMode)
            group.addAction(action)
            action.triggered.connect(partial(self._setSortMode, mode))

        menu.exec_(self.sortBtn.mapToGlobal(self.sortBtn.rect.bottomLeft()))

    def _setSortMode(self, mode, *args):
        self._sortMode = mode
        self.sortChanged.emit()

    def _showActionsMenu(self):
        menu = qt.QMenu(self)
        resumeAction = menu.addAction("Reconnect Visible")
        resumeAction.triggered.connect(lambda *args: self.resumeRequested.emit())
        menu.exec_(self.actionsBtn.mapToGlobal(self.actionsBtn.rect.bottomLeft()))
