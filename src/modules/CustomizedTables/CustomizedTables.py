import os
import string
from pathlib import Path

import ctk
import numexpr as ne
import numpy as np
import qt
import slicer

from ltrace.slicer.helpers import svgToQIcon
from ltrace.slicer_utils import *
from ltrace.slicer_utils import getResourcePath
from ltrace.slicer.node_attributes import NodeEnvironment

RESOURCES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Resources", "Icons")
CHARTS_ICON_PATH = os.path.join(RESOURCES_PATH, "Charts.png")


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
        self.setHelpUrl("Volumes/MoreTools/Tables.html", NodeEnvironment.MICRO_CT)
        self.setHelpUrl("Multiscale/MoreTools/Tables.html", NodeEnvironment.MULTISCALE)
        self.setHelpUrl("ImageLog/MoreTools/Tables.html", NodeEnvironment.IMAGE_LOG)

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

        newPropertiesDataTypeBox = newPropertiesWidget.findChild(qt.QComboBox, "DataTypeComboBox")
        newPropertiesDataTypeBox.removeItem(0)
        tableNodeSelector = self.tablesWidget.findChild(slicer.qMRMLNodeComboBox, "TableNodeSelector")

        # This function exists because removing the "string" type would cause
        # the initial selected data type when a node is created to appear blank
        def fixInitialDataType(node):
            currentNode = tableNodeSelector.currentNode()
            self.tablesWidget.setCurrentTableNode(node)
            newPropertiesDataTypeBox.setCurrentIndex(0)
            self.tablesWidget.setCurrentTableNode(currentNode)

        tableNodeSelector.nodeAdded.connect(fixInitialDataType)

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
    COLUMN_LETTERS = [char for char in string.ascii_uppercase]
    COLUMN_INDEXES = [i for i in range(len(COLUMN_LETTERS))]
    COLUMN_LETTERS_TO_INDEXES_DICT = dict(zip(COLUMN_LETTERS, COLUMN_INDEXES))
    COLUMN_INDEXES_TO_LETTERS_DICT = dict(zip(COLUMN_INDEXES, COLUMN_LETTERS))

    def __init__(self):
        LTracePluginLogic.__init__(self)

    def calculate(self, tableNode, formulaString, outputColumnLetter):
        # Checking if output column exists
        if outputColumnLetter == "":
            raise CustomizedTableError("Output column name is required.")

        try:
            outputColumnIndex = self.COLUMN_LETTERS_TO_INDEXES_DICT[outputColumnLetter]
        except KeyError as e:
            raise CustomizedTableError("Invalid output column name: " + outputColumnLetter + ".")

        if outputColumnIndex > tableNode.GetNumberOfColumns() - 1:
            raise CustomizedTableError("Invalid output column name: " + outputColumnLetter + ".")

        for c in self.COLUMN_LETTERS:
            # If letter exists in formula
            if c in formulaString:
                # If letter exists in table
                if self.COLUMN_LETTERS_TO_INDEXES_DICT[c] <= tableNode.GetNumberOfColumns() - 1:
                    columnArray = self.getColumnAsArray(tableNode, c)
                    exec(c + "=columnArray", locals())
                else:
                    raise CustomizedTableError("Invalid output column name: " + c + ".")

        try:
            outputArray = ne.evaluate(formulaString)
            self.setColumnFromArray(tableNode, outputColumnLetter, outputArray)
        except:
            raise CustomizedTableError("Invalid formula.")

    def getColumnAsArray(self, tableNode, columnLetter):
        columnIndex = self.COLUMN_LETTERS_TO_INDEXES_DICT[columnLetter]
        numberOfRows = tableNode.GetTable().GetNumberOfRows()
        rows = []
        for i in range(numberOfRows):
            rows.append(float(tableNode.GetCellText(i, columnIndex)))
        return np.array(rows)

    def setColumnFromArray(self, tableNode, columnLetter, array):
        columnIndex = self.COLUMN_LETTERS_TO_INDEXES_DICT[columnLetter]

        # convert column to double first
        columnName = tableNode.GetColumnName(columnIndex)
        tableNode.SetColumnType(columnName, 0)

        table = tableNode.GetTable()
        numberOfRows = table.GetNumberOfRows()
        for i in range(numberOfRows):
            table.SetValue(i, columnIndex, array[i])
        tableNode.Modified()


class CustomizedTableError(RuntimeError):
    pass
