import logging
import os
import re
import string
from pathlib import Path

import ctk
import numexpr as ne
import numpy as np
import qt
import slicer
from vtk.util.numpy_support import vtk_to_numpy

from ltrace.slicer.helpers import svgToQIcon
from ltrace.slicer_utils import *
from ltrace.slicer_utils import getResourcePath
from ltrace.slicer.node_attributes import NodeEnvironment

RESOURCES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Resources", "Icons")
CHARTS_ICON_PATH = os.path.join(RESOURCES_PATH, "Charts.png")


# Checks if closed source code is available
try:
    from Test.CustomizedTablesTest import CustomizedTablesTest
except ImportError:
    CustomizedTablesTest = None  # tests not deployed to final version or closed source


class CustomizedTables(LTracePlugin):
    SETTING_KEY = "CustomizedTables"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Tables"
        self.parent.categories = ["Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = CustomizedTables.help()
        self.setHelpUrl("Volumes/MoreTools/MoreTools.html#tables", NodeEnvironment.MICRO_CT)
        self.setHelpUrl("Multiscale/MoreTools/MoreTools.html#tables", NodeEnvironment.MULTISCALE)
        self.setHelpUrl("ImageLog/MoreTools/MoreTools.html#tables", NodeEnvironment.IMAGE_LOG)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CustomizedTablesWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = CustomizedTablesLogic()

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        self.tablesWidget = slicer.modules.tables.createNewWidgetRepresentation()
        displayEditCollapsibleButton = self.tablesWidget.findChild(
            ctk.ctkCollapsibleButton, "DisplayEditCollapsibleWidget"
        )
        displayEditLayout = displayEditCollapsibleButton.children()[0]
        menuExtraOptionsLayout = displayEditCollapsibleButton.children()[3].layout()

        newPropertiesCollapisbleButton = displayEditCollapsibleButton.findChild(
            ctk.ctkCollapsibleButton, "NewColumnPropertiesCollapsibleButton"
        )
        newPropertiesWidget = newPropertiesCollapisbleButton.findChild(slicer.qSlicerTableColumnPropertiesWidget)
        newPropertiesNullValueEdit = newPropertiesWidget.findChild(qt.QLineEdit, "NullValueLineEdit")
        newPropertiesNullValidator = qt.QDoubleValidator(newPropertiesNullValueEdit)
        newPropertiesNullLocale = qt.QLocale()
        newPropertiesNullLocale.setNumberOptions(qt.QLocale.RejectGroupSeparator)
        newPropertiesNullValidator.setLocale(newPropertiesNullLocale)
        newPropertiesNullValueEdit.setValidator(newPropertiesNullValidator)

        # Set old plot button as invisible
        plotLayoutItem = menuExtraOptionsLayout.itemAt(0)
        plotButton = plotLayoutItem.widget()
        plotButton.setVisible(False)

        icon = svgToQIcon(getResourcePath("Icons") / "svg" / "Charts.svg")
        self.chartsButton = qt.QToolButton()
        self.chartsButton.text = "Charts"
        self.chartsButton.icon = icon
        self.chartsButton.setToolTip("Open Charts module with current table selected.")
        self.chartsButton.clicked.connect(self.__onChartsButtonClicked)
        menuExtraOptionsLayout.insertWidget(0, self.chartsButton)

        calculatorCollapsibleButton = ctk.ctkCollapsibleButton()
        calculatorCollapsibleButton.setText("Calculator")
        calculatorCollapsibleButton.collapsed = True
        displayEditLayout.addWidget(calculatorCollapsibleButton)

        calculatorQFormLayout = qt.QFormLayout(calculatorCollapsibleButton)
        calculatorQFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.formulaLineEdit = qt.QLineEdit()
        self.formulaLineEdit.setToolTip("Formula to apply on the columns (e.g. A + B)")
        calculatorQFormLayout.addRow("Formula:", self.formulaLineEdit)

        self.outputColumnLineEdit = qt.QLineEdit()
        self.outputColumnLineEdit.setToolTip(
            "Column to output the calculation results (the column must exist on the table)"
        )
        calculatorQFormLayout.addRow("Output column:", self.outputColumnLineEdit)

        calculatePushButton = qt.QPushButton("Calculate")
        calculatePushButton.setFixedHeight(40)
        calculatorQFormLayout.addRow(" ", None)
        calculatorQFormLayout.addRow(None, calculatePushButton)

        calculatePushButton.clicked.connect(self.onCalculatePushButtonClicked)
        self.formulaLineEdit.returnPressed.connect(self.onCalculatePushButtonClicked)
        self.outputColumnLineEdit.returnPressed.connect(self.onCalculatePushButtonClicked)

        formLayout.addWidget(self.tablesWidget)

        csvImportCollapsible = ctk.ctkCollapsibleButton()
        csvImportCollapsible.setText("Load CSV")
        csvImportCollapsible.collapsed = True
        formLayout.addWidget(csvImportCollapsible)

        csvImportLayout = qt.QFormLayout(csvImportCollapsible)

        self.csvPathEdit = ctk.ctkPathLineEdit()
        self.csvPathEdit.nameFilters = ["CSV files (*.csv)"]
        self.csvPathEdit.setToolTip("Select a CSV file to import as a table")
        csvImportLayout.addRow("CSV File:", self.csvPathEdit)

        self.csvDelimiterCombo = qt.QComboBox()
        self.csvDelimiterCombo.addItems(["Auto-detect", "Comma (,)", "Semicolon (;)", "Tab (\\t)"])
        csvImportLayout.addRow("Delimiter:", self.csvDelimiterCombo)

        csvLoadButton = qt.QPushButton("Load")
        csvLoadButton.setFixedHeight(40)
        csvImportLayout.addRow(None, csvLoadButton)
        csvLoadButton.clicked.connect(self.onLoadCSVClicked)

    def onLoadCSVClicked(self):
        from ltrace.file_utils import read_csv
        from ltrace.slicer.data_utils import dataFrameToTableNode

        path = self.csvPathEdit.currentPath
        if not path:
            slicer.util.warningDisplay("Please select a CSV file.")
            return

        delimiter_map = {
            "Auto-detect": None,
            "Comma (,)": ",",
            "Semicolon (;)": ";",
            "Tab (\\t)": "\t",
        }
        whitelist_map = {
            "Auto-detect": [",", ";", "\t"],
            "Comma (,)": [","],
            "Semicolon (;)": [";"],
            "Tab (\\t)": ["\t"],
        }
        selected = self.csvDelimiterCombo.currentText

        try:
            if delimiter_map[selected] is not None:
                df = read_csv(Path(path), delimiter=delimiter_map[selected])
            else:
                df = read_csv(Path(path), whitelist=whitelist_map[selected])

            tableNode = dataFrameToTableNode(df)
            tableNode.SetName(Path(path).stem)
            tableSelector = self.tablesWidget.findChild(slicer.qMRMLNodeComboBox, "TableNodeSelector")
            tableSelector.setCurrentNode(tableNode)
            logging.info(f"Loaded '{Path(path).name}' with {len(df)} rows and {len(df.columns)} columns.")
        except Exception as e:
            slicer.util.errorDisplay(f"Failed to load CSV: {e}")

    def onCalculatePushButtonClicked(self):
        tableNode = self.tablesWidget.findChild(slicer.qMRMLNodeComboBox, "TableNodeSelector").currentNode()
        formulaString = self.formulaLineEdit.text
        outputColumnLetter = self.outputColumnLineEdit.text
        try:
            self.logic.calculate(tableNode, formulaString, outputColumnLetter)
        except CustomizedTableError as e:
            slicer.util.infoDisplay(str(e))

        # To fix a bug where the table view is not updated after calculation
        tableView = self.tablesWidget.findChild(slicer.qMRMLTableView, "TableView")
        tableView.setFocus(True)

    def __onChartsButtonClicked(self, action):
        module = "Charts"

        # Get module's widget
        widget = slicer.util.getModuleWidget(module)

        # Find the selected node
        tableNode = self.tablesWidget.findChild(slicer.qMRMLNodeComboBox, "TableNodeSelector").currentNode()

        # Apply node selection in the module's widget
        widget.setSelectedNode(tableNode)

        # Change module
        slicer.util.selectModule(module)


class CustomizedTablesLogic(LTracePluginLogic):
    # Matches Excel-style column names: A, B, ..., Z, AA, AB, ..., ZZ, AAA, ...
    COLUMN_LETTER_PATTERN = re.compile(r"\b[A-Z]+\b")

    def __init__(self):
        LTracePluginLogic.__init__(self)

    @staticmethod
    def columnLetterToIndex(columnLetter):
        # Converts an Excel-style column name (A, B, ..., Z, AA, AB, ...) to a 0-based index
        if not columnLetter:
            raise ValueError("Column name is empty.")

        index = 0
        for char in columnLetter:
            if char not in string.ascii_uppercase:
                raise ValueError(f"Invalid column letter: {columnLetter}")
            index = index * 26 + (ord(char) - ord("A") + 1)
        return index - 1

    def calculate(self, tableNode, formulaString, outputColumnLetter):
        if tableNode is None:
            raise CustomizedTableError("Please select a table.")

        if formulaString.strip() == "":
            raise CustomizedTableError("Formula is required.")

        # Checking if output column exists
        if outputColumnLetter == "":
            raise CustomizedTableError("Output column name is required.")

        try:
            outputColumnIndex = self.columnLetterToIndex(outputColumnLetter)
        except ValueError:
            raise CustomizedTableError("Invalid output column name: " + outputColumnLetter + ".")

        if outputColumnIndex > tableNode.GetNumberOfColumns() - 1:
            raise CustomizedTableError("Invalid output column name: " + outputColumnLetter + ".")

        # numexpr resolves names from the caller's frame only when local_dict is omitted, and it clears
        # that frame's locals dict as a side effect, so the columns must be passed in explicitly.
        formulaVariables = {}
        for c in sorted(set(self.COLUMN_LETTER_PATTERN.findall(formulaString))):
            # If the column name exists in the table
            if self.columnLetterToIndex(c) <= tableNode.GetNumberOfColumns() - 1:
                formulaVariables[c] = self.getColumnAsArray(tableNode, c)
            else:
                raise CustomizedTableError("Invalid column name in formula: " + c + ".")

        try:
            outputArray = ne.evaluate(formulaString, local_dict=formulaVariables, global_dict={})
        except Exception as e:
            raise CustomizedTableError("Invalid formula: " + str(e))

        # A formula with no column references evaluates to a scalar, which fills the whole column.
        # Any other result already has one value per row, since every variable came from this table.
        if outputArray.ndim == 0:
            numberOfRows = tableNode.GetTable().GetNumberOfRows()
            outputArray = np.broadcast_to(outputArray, (numberOfRows,))

        self.setColumnFromArray(tableNode, outputColumnLetter, outputArray)

    def getColumnAsArray(self, tableNode, columnLetter):
        columnIndex = self.columnLetterToIndex(columnLetter)
        column = tableNode.GetTable().GetColumn(columnIndex)

        # Numeric columns are read from the VTK array itself. GetCellText is a display API -
        # it formats through vtkVariant::ToString at default stream precision - so reading a
        # double column through it would round every value to six significant digits. astype
        # also copies, which keeps the data valid when this is the output column as well.
        if column.IsNumeric():
            return vtk_to_numpy(column).astype(np.float64)

        # Text columns have no numeric array to read, so they are parsed cell by cell.
        numberOfRows = tableNode.GetTable().GetNumberOfRows()
        rows = []
        for i in range(numberOfRows):
            cellText = tableNode.GetCellText(i, columnIndex)
            try:
                rows.append(float(cellText))
            except ValueError:
                raise CustomizedTableError(
                    f"Column {columnLetter} contains a non-numeric value at row {i + 1}: '{cellText}'."
                )
        return np.array(rows)

    def setColumnFromArray(self, tableNode, columnLetter, array):
        columnIndex = self.columnLetterToIndex(columnLetter)

        # convert column to double first
        columnName = tableNode.GetColumnName(columnIndex)
        tableNode.SetColumnType(columnName, 0)

        # SetColumnType above replaced this column with a vtkDoubleArray holding one value per
        # row, so the results can be written in one assignment instead of boxing every row into
        # a vtkVariant. A shape mismatch raises here rather than corrupting part of the column.
        column = tableNode.GetTable().GetColumn(columnIndex)
        vtk_to_numpy(column)[:] = array
        column.Modified()
        tableNode.Modified()


class CustomizedTableError(RuntimeError):
    pass
