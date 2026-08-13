import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
from ltrace.slicer.graph_data import TEXT_SYMBOLS, LINE_STYLES, SCATTER_PLOT_TYPE, LINE_PLOT_TYPE

NO_CHANGE = "No change"


class StyleEditorWidget(QtWidgets.QWidget):
    """
    Widget to edit pyqtgraph symbol and line styles
    """

    sigAllStyleChange = QtCore.Signal(str, int, str, int)

    def __init__(
        self,
        parent=None,
        symbol: object = TEXT_SYMBOLS,
        lineStyle: object = LINE_STYLES,
        extraOption: str = NO_CHANGE,
        useButtons: bool = False,
    ):
        super().__init__(parent=parent)
        self.setup(symbol, lineStyle, extraOption, useButtons)

    def setup(self, symbol: object, lineStyle: object, extraOption: str, useButtons: bool):
        """A custom widget to edit pyqtgraph styling. Can be used as if it were a dialog.

        Args:
            symbol (object): List of available symbol options
            lineStyle (str): List of available line style options
            useButtons (bool): Enable or disable basic buttons. Use True when using as dialog
            extraOption (str): Adds an extra options at the beggining of the comboBoxes.
        """
        self.setWindowTitle("Edit style for all data")
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint)

        formLayout = QtWidgets.QFormLayout()

        if symbol is not None:
            self.symbolComboBox = QtWidgets.QComboBox()
            if extraOption:
                self.symbolComboBox.addItem(extraOption)
            self.symbolComboBox.addItems(symbol.keys())
            self.symbolComboBox.setToolTip("Select a symbol style to be applied")

            self.symbolSizeSpinBox = QtWidgets.QSpinBox()
            self.symbolSizeSpinBox.setRange(0, 50)
            self.symbolSizeSpinBox.setValue(0)
            self.symbolSizeSpinBox.setToolTip("Set the size of the symbol")

            formLayout.addRow("Symbol", self.symbolComboBox)
            formLayout.addRow("Symbol size", self.symbolSizeSpinBox)

        if lineStyle is not None:
            self.lineStyleComboBox = QtWidgets.QComboBox()
            if extraOption:
                self.lineStyleComboBox.addItem(extraOption)
            self.lineStyleComboBox.addItems(lineStyle.keys())
            self.lineStyleComboBox.setToolTip(
                "Select a line style to be applied. Select None to remove the line from the plot"
            )

            self.lineSizeSpinBox = QtWidgets.QSpinBox()
            self.lineSizeSpinBox.setRange(0, 50)
            self.lineSizeSpinBox.setValue(0)
            self.lineSizeSpinBox.setToolTip("Set the width of the line")

            formLayout.addRow("Line style", self.lineStyleComboBox)
            formLayout.addRow("Line size", self.lineSizeSpinBox)

        if useButtons:
            applyButton = QtWidgets.QPushButton("Apply")
            cancelButton = QtWidgets.QPushButton("Cancel")

            applyButton.clicked.connect(lambda: self.__applyClicked())
            cancelButton.clicked.connect(lambda: self.close())

            buttonsLayout = QtWidgets.QHBoxLayout()
            buttonsLayout.addWidget(applyButton)
            buttonsLayout.addWidget(cancelButton)
            formLayout.addRow(buttonsLayout)

        self.setLayout(formLayout)

    def __applyClicked(self):
        """Handles the emission of the signal with the choosen options"""
        self.sigAllStyleChange.emit(
            self.symbolComboBox.currentText(),
            self.symbolSizeSpinBox.value(),
            self.lineStyleComboBox.currentText(),
            self.lineSizeSpinBox.value(),
        )
        self.close()
