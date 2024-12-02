from dataclasses import dataclass
from pandas.api.types import is_float_dtype, is_integer_dtype

import collections
import pandas as pd
import qt
import slicer

from .Base import TableWidget


class FilterableTableWidget(TableWidget):
    def __init__(self, logic):
        super().__init__(logic)
        super().setup()

    def setupFilters(self, filters):
        self.filterWidgets = {}
        self.filterProps = filters

        for key, props in filters.items():
            filterWidget = slicer.qMRMLRangeWidget()
            filterWidget.singleStep = 0.01 if props.type_ is float else 1
            filterWidget.tracking = False
            filterWidget.valuesChanged.connect(self.filterValuesChanged)
            self.layout().addRow(props.label, filterWidget)
            self.filterWidgets[key] = filterWidget

    def createExcludingDataFrame(self):
        dataFrame = self.tableView.model()._data
        condition = dataFrame["label"] != dataFrame["label"]

        for key, filterWidget in self.filterWidgets.items():
            epsilon = 0 if filterWidget.singleStep == 1 else 0.01
            condition |= dataFrame[key] < filterWidget.minimumValue - epsilon
            condition |= dataFrame[key] > filterWidget.maximumValue + epsilon
        excludingDataFrame = dataFrame[condition]
        return excludingDataFrame

    def setTableNode(self, tableNode):
        tableNodeDataFrame = slicer.util.dataframeFromTable(tableNode)
        self.pandasTableModel = PandasTableModel(tableNodeDataFrame)
        self.tableView.setModel(self.pandasTableModel)
        self.tableView.selectionModel().selectionChanged.connect(self.tableViewSelectionChanged)
        self.setAllRangeWidgetValues()

    def setAllRangeWidgetValues(self, resetValues=True):
        model = self.tableView.model()
        dataFrame = model._data
        for key, filterWidget in self.filterWidgets.items():
            props = self.filterProps[key]
            self.setRangeWidgetValues(
                dataFrame, filterWidget, key, resetValues, minVal=props.minVal, maxVal=props.maxVal
            )
        model.setFilteredLabels([])


@dataclass
class FilterProps:
    label: str
    type_: type
    minVal: float = None
    maxVal: float = None


class SidewallSampleTableWidget(FilterableTableWidget):
    def __init__(self, logic):
        super().__init__(logic)
        self.setupFilters(
            {
                "diam (cm)": FilterProps("Diameter (cm):", float),
                "circularity": FilterProps("Circularity:", float),
                "solidity": FilterProps("Solidity:", float),
                "azimuth (°)": FilterProps("Azimuth (°):", int, 0, 360),
                "depth (m)": FilterProps("Depth (m):", int),
            }
        )


class StopsTableWidget(FilterableTableWidget):
    def __init__(self, logic):
        super().__init__(logic)
        self.setupFilters(
            {
                "area": FilterProps("Area:", float),
                "linearity": FilterProps("Linearity:", float),
                "steepness (°)": FilterProps("Steepness (°):", int),
                "depth (m)": FilterProps("Depth (m):", int),
            }
        )


class GenericTableWidget(FilterableTableWidget):
    def __init__(self, logic):
        super().__init__(logic)
        df = slicer.util.dataframeFromTable(logic.tableNode)
        columnsToFilter = {}
        for col in df.columns:
            series = df[col]
            if not is_float_dtype(series) and not is_integer_dtype(series):
                continue

            dtype = float if is_float_dtype(series) else int
            formattedColumnName = col[0].upper() + col[1:]
            columnsToFilter[col] = FilterProps(formattedColumnName, dtype)

        self.setupFilters(columnsToFilter)


class PandasTableModel(qt.QAbstractTableModel):
    def __init__(self, data, parent=None):
        qt.QAbstractTableModel.__init__(self, parent)
        self._data = data
        self.filteredLabels = []
        self.sortingColumn = [0, False]
        self.calculateConflictedLabels()

    def calculateConflictedLabels(self):
        labelsList = list(self._data["label"])
        self.conflictedLabels = [item for item, count in collections.Counter(labelsList).items() if count > 1]

    def removeRows(self, row, count, parent=None):
        self.beginRemoveRows(parent, row, row + count - 1)
        self._data = self._data.drop(index=[i for i in range(row, row + count)])
        self._data = self._data.reset_index(drop=True)
        self.calculateConflictedLabels()
        self.endRemoveRows()
        return True

    def editRow(self, row, rowData):
        rowDataFrame = pd.DataFrame([rowData])
        cols = list(rowDataFrame.columns)
        self._data.loc[row, cols] = rowDataFrame.loc[0, cols]
        self.calculateConflictedLabels()
        self.dataChanged.emit(qt.QModelIndex(), qt.QModelIndex())

    def addRow(self, rowData):
        position = self.rowCount()
        count = 1
        self.beginInsertRows(qt.QModelIndex(), position, position + count - 1)
        rowDataFrame = pd.DataFrame([rowData])
        self._data = pd.concat([self._data, rowDataFrame], ignore_index=True)
        self.calculateConflictedLabels()
        self.endInsertRows()
        return position

    def getRowByLabel(self, label):
        return self._data.index[self._data["label"] == label].to_list()[0]

    def labelIndex(self):
        return self._data.columns.get_loc("label")

    def getLabelByRow(self, row):
        label = self.index(row, self.labelIndex()).data()
        return int(label)

    def sort(self, column, descending):
        self._data = self._data.sort_values(by=self._data.columns[column], ascending=not descending)
        self._data = self._data.reset_index(drop=True)
        self.sortingColumn = [column, descending]
        self.dataChanged.emit(qt.QModelIndex(), qt.QModelIndex())

    def sortDefault(self):
        self.sort(self.sortingColumn[0], self.sortingColumn[1])

    def sortByMultipleColumns(self, columnIds, ascending=True):
        self._data = self._data.sort_values(by=columnIds, ascending=ascending)
        self._data = self._data.reset_index(drop=True)
        self.dataChanged.emit(qt.QModelIndex(), qt.QModelIndex())

    def setFilteredLabels(self, filteredLabels):
        self.filteredLabels = filteredLabels
        self.dataChanged.emit(qt.QModelIndex(), qt.QModelIndex())

    def rowCount(self, parent=None):
        return len(self._data.values)

    def columnCount(self, parent=None):
        return self._data.columns.size

    def headerData(self, x, orientation, role):
        if orientation == qt.Qt.Horizontal and role == qt.Qt.DisplayRole:
            return self._data.columns[x]
        if orientation == qt.Qt.Vertical and role == qt.Qt.DisplayRole:
            return self._data.index[x]
        return None

    def data(self, index, role):
        if not index.isValid():
            return None

        label = self._data.iloc[index.row(), self.labelIndex()]

        if role == qt.Qt.DisplayRole:
            value = self._data.iloc[index.row(), index.column()]
            # if the value is integer, then convert to string. necessary to allow it to appear on the table view.
            try:
                if int(value) == value:
                    value = str(value)
            except ValueError:
                pass
            return value

        if role == qt.Qt.ForegroundRole:
            if label in self.conflictedLabels:
                return qt.QBrush(qt.QColor(255, 216, 0))

        if role == qt.Qt.BackgroundRole:
            if label in self.filteredLabels:
                return qt.QBrush(qt.QColor(100, 30, 30))

        return None
