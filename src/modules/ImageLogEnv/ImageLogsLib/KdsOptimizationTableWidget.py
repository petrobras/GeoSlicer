import slicer
import qt
import sys
import pandas as pd
from ltrace.slicer import ui
from ltrace.slicer_utils import tableWidgetToDataFrame


class KdsOptimizationItemModel:
    def __init__(self) -> None:
        self.__kRo = None
        self.__kDst = None
        self.__initialDepth = None
        self.__endDepth = None

    @property
    def kRo(self):
        return self.__kRo

    @kRo.setter
    def kRo(self, value):
        self.__kRo = value

    @property
    def kDst(self):
        return self.__kDst

    @kDst.setter
    def kDst(self, value):
        self.__kDst = value

    @property
    def initialDepth(self):
        return self.__initialDepth

    @initialDepth.setter
    def initialDepth(self, value):
        self.__initialDepth = value

    @property
    def endDepth(self):
        return self.__endDepth

    @endDepth.setter
    def endDepth(self, value):
        self.__endDepth = value


class AddKdsOptimizationItemDialog(qt.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = KdsOptimizationItemModel()
        self.setup()

    def setup(self):
        layout = qt.QVBoxLayout()
        self.setLayout(layout)

        self.__initialDepthSpinBox = ui.numberParam(
            vrange=(0, sys.float_info.max),
            value=0.0,
        )
        self.__endDepthSpinBox = ui.numberParam(vrange=(0, sys.float_info.max), value=1.0)
        self.__kDstSpinBox = ui.numberParam(vrange=(0, sys.float_info.max), value=1.0)
        self.__kRoSpinBox = ui.numberParam(vrange=(0, sys.float_info.max), value=1.0, decimals=3)

        self.__initialDepthSpinBox.setKeyboardTracking(False)
        self.__endDepthSpinBox.setKeyboardTracking(False)
        self.__kDstSpinBox.setKeyboardTracking(False)
        self.__kRoSpinBox.setKeyboardTracking(False)

        self.__initialDepthSpinBox.valueChanged.connect(self.__onValuesChanged)
        self.__endDepthSpinBox.valueChanged.connect(self.__onValuesChanged)
        self.__kDstSpinBox.valueChanged.connect(self.__onValuesChanged)
        self.__kRoSpinBox.valueChanged.connect(self.__onValuesChanged)

        formLayout = qt.QFormLayout()
        formLayout.addRow("Initial Depth", self.__initialDepthSpinBox)
        formLayout.addRow("End Depth", self.__endDepthSpinBox)
        formLayout.addRow("K_dst", self.__kDstSpinBox)
        formLayout.addRow("K_ro", self.__kRoSpinBox)

        buttonLayout = qt.QHBoxLayout()
        okButton = qt.QPushButton("OK")
        okButton.clicked.connect(self.__onOkButtonClicked)

        cancelButton = qt.QPushButton("Cancel")
        cancelButton.clicked.connect(lambda x: self.reject())

        buttonLayout.addWidget(okButton)
        buttonLayout.addWidget(cancelButton)

        layout.addLayout(formLayout)
        layout.addLayout(buttonLayout)

        self.__initialDepthSpinBox.objectName = "Start Depth Spin Box"
        self.__endDepthSpinBox.objectName = "Stop Depth Spin Box"
        self.__kDstSpinBox.objectName = "Kdst Spin Box"
        self.__kRoSpinBox.objectName = "Kro Spin Box"
        okButton.objectName = "Add Kds Optimization Item Add Button"
        cancelButton.objectName = "Add Kds Optimization Item Cancel Button"

    def __onValuesChanged(self, _):
        if self.__endDepthSpinBox.value < self.__initialDepthSpinBox.value:
            self.__endDepthSpinBox.value = self.__initialDepthSpinBox.value + 1

        if self.__initialDepthSpinBox.value > self.__endDepthSpinBox.value:
            self.__initialDepthSpinBox.value = self.__endDepthSpinBox.value - 1

    def __onOkButtonClicked(self, checked):
        self.model.kRo = self.__kRoSpinBox.value
        self.model.kDst = self.__kDstSpinBox.value
        self.model.initialDepth = self.__initialDepthSpinBox.value
        self.model.endDepth = self.__endDepthSpinBox.value

        self.accept()


class KdsOptimizationWidget(qt.QWidget):
    tableUpdated = qt.Signal(object)
    HEADER = ["Start Depth [m]", "Stop Depth [m]", "K_dst [m.MD]", "K_ro [frac]"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup()

    def setup(self):
        layout = qt.QVBoxLayout()
        self.setLayout(layout)

        # 'flow capacity definitions per depth' Table
        self.table = qt.QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(self.HEADER)
        self.table.horizontalHeader().setSectionResizeMode(qt.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(False)
        self._tableCellHandler = KdsOptimizationTableCellHandler(self.table)

        # Define the same size for all columns
        for i in range(self.table.columnCount):
            self.table.horizontalHeader().setSectionResizeMode(i, qt.QHeaderView.Stretch)

        self.table.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)

        self.addButton = qt.QPushButton("Add")
        self.addButton.clicked.connect(self.__onAddButtonClicked)
        self.removeButton = qt.QPushButton("Remove")
        self.removeButton.clicked.connect(self.__onRemoveButtonClicked)

        # Weight value
        self.weightSpinBox = ui.numberParam(vrange=(0, sys.float_info.max), value=1.0)
        formLayout = qt.QFormLayout()
        formLayout.addRow("Weight", self.weightSpinBox)

        # Layout
        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addStretch()
        buttonsLayout.addWidget(self.addButton)
        buttonsLayout.addWidget(self.removeButton)

        layout.addWidget(self.table)
        layout.addLayout(buttonsLayout)
        layout.addLayout(formLayout)

    def __onAddButtonClicked(self, checked):
        dialog = AddKdsOptimizationItemDialog(self)
        dialog.objectName = "Add Kds Optimization Item Dialog"
        result = dialog.exec_()
        if result == qt.QDialog.Accepted:
            state = self.table.blockSignals(True)
            self.table.insertRow(self.table.rowCount)
            self.table.setItem(self.table.rowCount - 1, 0, qt.QTableWidgetItem(str(dialog.model.initialDepth)))
            self.table.setItem(self.table.rowCount - 1, 1, qt.QTableWidgetItem(str(dialog.model.endDepth)))
            self.table.setItem(self.table.rowCount - 1, 2, qt.QTableWidgetItem(str(dialog.model.kDst)))
            self.table.setItem(self.table.rowCount - 1, 3, qt.QTableWidgetItem(str(dialog.model.kRo)))
            self.table.blockSignals(state)

        df = tableWidgetToDataFrame(self.table)
        self.tableUpdated.emit(df)

    def __onRemoveButtonClicked(self, checked):
        selectedIndexes = self.table.selectedIndexes()

        rowSet = set()
        for index in selectedIndexes:
            rowSet.add(index.row())

        if len(rowSet) <= 0:
            return

        rowSet = sorted(rowSet, reverse=True)

        for row in rowSet:
            self.table.removeRow(row)

        df = tableWidgetToDataFrame(self.table)
        self.tableUpdated.emit(df)
        self.table.setCurrentCell(-1, -1)

    def setTableData(self, df: pd.DataFrame = None):
        self.table.clearContents()

        if df is None:
            return

        self.table.setRowCount(0)
        for _, row in df.iterrows():
            self.table.insertRow(self.table.rowCount)
            self.table.setItem(self.table.rowCount - 1, 0, qt.QTableWidgetItem(str(row.iloc[0])))
            self.table.setItem(self.table.rowCount - 1, 1, qt.QTableWidgetItem(str(row.iloc[1])))
            self.table.setItem(self.table.rowCount - 1, 2, qt.QTableWidgetItem(str(row.iloc[2])))
            self.table.setItem(self.table.rowCount - 1, 3, qt.QTableWidgetItem(str(row.iloc[3])))


class KdsOptimizationTableCellHandler:
    """Class to handle Kds Optimization Table cells user's iteraction"""

    START_DEPTH_COLUMN = 0
    STOP_DEPTH_COLUMN = 1

    def __init__(self, table: qt.QTableWidget) -> None:
        self.currentCell = None
        self.previousValue = None
        self.table = table
        self.table.cellChanged.connect(self.__onCellChanged)
        self.table.currentCellChanged.connect(self.__onCurrentCellChanged)

    def restore(self) -> None:
        """Restore the previous value"""
        state = self.table.blockSignals(True)
        self.currentCell.setText(self.previousValue)
        self.table.blockSignals(state)

    def validateCell(self) -> bool:
        """Validate the current cell

        Returns:
            bool: True if the cell is valid, otherwise False
        """
        if not self.currentCell or not self.currentCell.text():
            return False

        try:
            currentValue = float(self.currentCell.text())
        except ValueError:  # not a number
            return False

        row = self.currentCell.row()
        column = self.currentCell.column()

        if column not in [self.START_DEPTH_COLUMN, self.STOP_DEPTH_COLUMN]:
            return True  # No validation needed for other columns

        if column == 0:  # related to 'Start Depth'
            stopDepthItem = self.table.item(row, self.STOP_DEPTH_COLUMN)
            return currentValue < float(stopDepthItem.text())

        if column == 1:  # related to 'Stop Depth'
            startDepthItem = self.table.item(row, self.START_DEPTH_COLUMN)
            return currentValue > float(startDepthItem.text())

        return True

    def __onCellChanged(self, row: int, column: int):
        """Handle cell changed event.

        Args:
            row (int): the current row.
            column (int): the current column.
        """
        if self.currentCell is None or self.currentCell.row() != row or self.currentCell.column() != column:
            return

        if not self.validateCell():
            self.restore()
            return

        self.previousValue = self.currentCell.text()

    def __onCurrentCellChanged(self, currentRow: int, currentColumn: int, previousRow: int, previousColumn: int):
        """Handle current cell changed event. Used to store the reference from the selected cell item object.

        Args:
            currentRow (int): the current row selected.
            currentColumn (int): the current column selected.
            previousRow (int): the previous row selected.
            previousColumn (int): the previous column selected.
        """
        self.currentCell = self.table.item(currentRow, currentColumn)
        self.previousValue = self.currentCell.text() if self.currentCell else None
