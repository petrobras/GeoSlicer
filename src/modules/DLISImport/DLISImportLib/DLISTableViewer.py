import qt

from .DLISImportLogic import ChannelMetadata
from ltrace.slicer import ui


def buildCheckBoxCell(checked):
    checkBoxWidget = qt.QWidget()
    checkBox = qt.QCheckBox()
    checkBox.setStyleSheet("QCheckBox::indicator {width:20px; height: 20px;}")
    checkBox.setChecked(checked)
    layoutCheckBox = qt.QHBoxLayout(checkBoxWidget)  # create a layer with reference to the widget
    layoutCheckBox.addWidget(checkBox)  # Set the checkbox in the layer
    layoutCheckBox.setAlignment(qt.Qt.AlignCenter)  # Center the checkbox
    layoutCheckBox.setContentsMargins(0, 0, 0, 0)  # Set the zero padding
    return checkBoxWidget


class DLISTableViewer(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.loadClicked = lambda *a: None

        self.db = []

        self.selected_rows = 0

        self.columns = ["Load", "Id", "Name", "Unit", "Frame", "Logical file", "LabelMap", "As Table"]
        self.ID_COLUMN = self.columns.index("Id")
        self.NAME_COLUMN = self.columns.index("Name")

        filterLayout = qt.QHBoxLayout()
        self.filterLineEdit = qt.QLineEdit()
        self.filterLineEdit.setObjectName("Filter Input")
        self.filterLineEdit.setPlaceholderText("Filter by Id or Name")
        self.filterLineEdit.textChanged.connect(self._on_filter_changed)
        self.clearFilterButton = qt.QPushButton("Clear filter")
        self.clearFilterButton.clicked.connect(self.clearFilter)
        self.selectButton = qt.QPushButton("Select all")
        self.selectButton.setObjectName("Select All Button")
        self.selectButton.clicked.connect(lambda: self._select_all(True))
        self.deselectButton = qt.QPushButton("Deselect all")
        self.deselectButton.clicked.connect(lambda: self._select_all(False))
        filterLayout.addWidget(self.filterLineEdit)
        filterLayout.addWidget(self.clearFilterButton)
        filterLayout.addWidget(self.selectButton)
        filterLayout.addWidget(self.deselectButton)

        self.tableWidget = qt.QTableWidget()
        self.tableWidget.setObjectName("Table Widget")
        self.tableWidget.verticalHeader().setVisible(False)
        self.tableWidget.setColumnCount(len(self.columns))
        self.tableWidget.setHorizontalHeaderLabels(self.columns)
        self.tableWidget.horizontalHeader().setStyleSheet(
            "QHeaderView::section {padding-left: 10px; padding-right: 10px;}"
        )
        self.tableWidget.horizontalHeader().sectionDoubleClicked.connect(self._on_header_clicked)
        self.tableWidget.horizontalHeader().setSectionResizeMode(1, qt.QHeaderView.Stretch)
        self.tableWidget.horizontalHeader().setSectionResizeMode(2, qt.QHeaderView.Stretch)
        self.tableWidget.setShowGrid(False)
        self.tableWidget.setAlternatingRowColors(True)
        self.tableWidget.setSelectionBehavior(self.tableWidget.SelectRows)
        self.tableWidget.setSelectionMode(self.tableWidget.ExtendedSelection)
        self.tableWidget.selectionModel().selectionChanged.connect(self._on_table_selection_changed)
        self.tableWidget.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Expanding)

        self.loadButton = qt.QPushButton()
        self.loadButton.setObjectName("Load Button")
        self.loadButton.clicked.connect(self._on_load_clicked)
        self.loadButton.setFixedHeight(40)
        self.loadButton.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Preferred)

        self.statusLabel = ui.TemporaryStatusLabel()

        layout = qt.QVBoxLayout()
        self.setLayout(layout)
        layout.addLayout(filterLayout)
        layout.addWidget(self.tableWidget)
        layout.addWidget(self.loadButton)
        layout.addWidget(self.statusLabel)

        self._on_loaded_checkbox_changed()

    def clearFilter(self):
        self.filterLineEdit.text = ""

    def set_database(self, db):
        self.db = db
        current_filter = self.filterLineEdit.text
        self.filterLineEdit.text = ""
        self.tableWidget.clearContents()
        self.tableWidget.setRowCount(len(self.db))

        for i in range(len(self.db)):
            loadItem = buildCheckBoxCell(False)
            loadItem.findChild(qt.QCheckBox).stateChanged.connect(self._on_loaded_checkbox_changed)
            self.tableWidget.setCellWidget(i, 0, loadItem)
            entry = self.db[i]
            for j in range(1, len(self.columns)):
                if isinstance(entry[j - 1], bool):  # j - 1 because entry is 1 shorter than self.columns
                    item = buildCheckBoxCell(entry[j - 1])
                    if j == self.columns.index("LabelMap"):
                        item.findChild(qt.QCheckBox).stateChanged.connect(self._on_checkbox_label_clicked)
                    elif j == self.columns.index("As Table"):
                        item.findChild(qt.QCheckBox).stateChanged.connect(self._on_checkbox_table_clicked)
                    self.tableWidget.setCellWidget(i, j, item)
                else:
                    item = qt.QTableWidgetItem(entry[j - 1])
                    flags = ~qt.Qt.ItemIsEditable
                    original_flags = item.flags()
                    item.setFlags(qt.Qt.ItemFlag(original_flags and flags))
                    self.tableWidget.setItem(i, j, item)

        self.tableWidget.sortByColumn(0, qt.Qt.AscendingOrder)
        self.tableWidget.resizeColumnsToContents()
        self.filterLineEdit.text = current_filter

        self._on_loaded_checkbox_changed()

    def _on_filter_changed(self, current_text):
        current_text = current_text.casefold().split()
        for i in range(self.tableWidget.rowCount):
            entry = (
                self.tableWidget.item(i, self.ID_COLUMN).text()
                + " "
                + self.tableWidget.item(i, self.NAME_COLUMN).text()
            )
            entry = entry.casefold()

            should_hide = not (any(word in entry for word in current_text) or current_text == [])
            self.tableWidget.setRowHidden(i, should_hide)

    def _on_header_clicked(self, column_clicked):
        self.tableWidget.sortByColumn(column_clicked, qt.Qt.AscendingOrder)

    def _on_loaded_checkbox_changed(self, *args):
        selected_rows = self.rows_to_load()

        self.tableWidget.setSelectionMode(self.tableWidget.MultiSelection)

        self.tableWidget.clearSelection()

        for r in selected_rows:
            self.tableWidget.selectRow(r)

        self.tableWidget.setSelectionMode(self.tableWidget.ExtendedSelection)

        self._on_selection_changed()

    def _on_table_selection_changed(self, *args):
        load_column = self.columns.index("Load")

        selection = self.tableWidget.selectionModel()

        for i in range(self.tableWidget.rowCount):
            widget = self.tableWidget.cellWidget(i, load_column)
            if widget:
                item = widget.layout().itemAt(0).widget()
                item.blockSignals(True)
                item.setChecked(selection.isRowSelected(i))
                item.blockSignals(False)

        self._on_selection_changed()

    def _select_all(self, select):
        load_column = self.columns.index("Load")
        for i in range(self.tableWidget.rowCount):
            rowHidden = self.tableWidget.isRowHidden(i)
            widget = self.tableWidget.cellWidget(i, load_column)
            if widget and not rowHidden:
                item = widget.layout().itemAt(0).widget()
                item.blockSignals(True)
                item.setChecked(select)
                item.blockSignals(False)

        self._on_loaded_checkbox_changed()

    def _on_selection_changed(self, *args):
        filteredSelected = []

        self.selected_rows = self.rows_to_load()

        aslabelmap_column = self.columns.index("LabelMap")
        astable_column = self.columns.index("As Table")
        for i in range(self.tableWidget.rowCount):
            widget = self.tableWidget.cellWidget(i, aslabelmap_column)
            widget1 = self.tableWidget.cellWidget(i, astable_column)
            try:
                item = widget.layout().itemAt(0).widget()
                item.setVisible(i in self.selected_rows)
                item1 = widget1.layout().itemAt(0).widget()
                item1.setVisible(i in self.selected_rows)
            except AttributeError:  # no "Labelmap"
                pass

            rowHidden = self.tableWidget.isRowHidden(i)
            if not rowHidden:
                selected = self.tableWidget.selectionModel().isRowSelected(i)
                filteredSelected.append(selected)

        if len(self.selected_rows) == 0:
            self.loadButton.setText("No selected curves to load")
            self.loadButton.setEnabled(False)
        elif len(self.selected_rows) == 1:
            self.loadButton.setText("Load selected curve")
            self.loadButton.setEnabled(True)
        else:
            self.loadButton.setText("Load {} selected curves".format(len(self.selected_rows)))
            self.loadButton.setEnabled(True)

        self.statusLabel.setVisible(False)

    def _on_checkbox_table_clicked(self, state):
        self._on_checkbox_clicked_common(state, "As Table", "LabelMap")

    def _on_checkbox_label_clicked(self, state):
        self._on_checkbox_clicked_common(state, "LabelMap", "As Table")

    def _on_checkbox_clicked_common(self, state, target_column, other_column):
        target_index = self.columns.index(target_column)
        other_index = self.columns.index(other_column)
        for i in self.selected_rows:
            row_hidden = self.tableWidget.isRowHidden(i)
            target_widget = self.tableWidget.cellWidget(i, target_index)
            other_widget = self.tableWidget.cellWidget(i, other_index)
            if target_widget and not row_hidden:
                target_item = target_widget.layout().itemAt(0).widget()
                target_item.setChecked(state == qt.Qt.Checked)
            if state == qt.Qt.Checked:
                if other_widget and not row_hidden:
                    other_item = other_widget.layout().itemAt(0).widget()
                    other_item.setChecked(state == qt.Qt.Unchecked)

    def rows_to_load(self):
        rows = []
        load_column = self.columns.index("Load")
        for i in range(self.tableWidget.rowCount):
            widget = self.tableWidget.cellWidget(i, load_column)
            try:
                item = widget.layout().itemAt(0).widget()
                if item.isChecked():
                    rows.append(i)
            except AttributeError:  # no "Labelmap"
                pass
        return rows

    def _on_load_clicked(self):
        selected_mnemonic_and_files = []

        for row in self.rows_to_load():
            row_args = []
            for i in range(len(self.columns)):
                try:
                    item = self.tableWidget.item(row, i)
                    row_args.append(item.text())
                except AttributeError:
                    widget = self.tableWidget.cellWidget(row, i)
                    item = widget.layout().itemAt(0).widget()
                    if self.columns[i] == "LabelMap":
                        row_args.append(item.isChecked())
                    if self.columns[i] == "As Table":
                        row_args.append(item.isChecked())

            channel = ChannelMetadata(*row_args)
            selected_mnemonic_and_files.append(channel)

        self.loadClicked(selected_mnemonic_and_files)
