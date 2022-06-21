import pyqtgraph as pg
from pyqtgraph.Qt import QtGui, QtCore
from ltrace.slicer.graph_data import TEXT_SYMBOLS, LINE_STYLES, SCATTER_PLOT_TYPE, LINE_PLOT_TYPE
from ltrace.slicer.widget.style_editor_widget import StyleEditorWidget


class CustomColorButton(pg.ColorButton):
    """Enhances pg.ColorButton dialog to our purposes"""

    sigStyleChanged = QtCore.Signal(object, str, int, str, int)

    def __init__(
        self,
        parent=None,
        color=(128, 128, 128),
        symbol=list(TEXT_SYMBOLS.keys())[0],
        symbol_size=10,
        line_style=list(LINE_STYLES.keys())[0],
        line_size=1,
        plot_type=LINE_PLOT_TYPE,
    ):
        super().__init__(parent=parent, color=color)
        self.setupCustomUi(symbol, symbol_size, line_style, line_size, plot_type)
        self.sigColorChanged.connect(self.__onStyleChanged)

    def setupCustomUi(self, symbol, symbol_size, line_style, line_size, plot_type):
        """Adds custom widgets to the original layout

        Args:
            symbol (str): the current symbol's description
            symbol_size (int): the current symbols size
            line_style (str): The current line style
            line_size (int): The current line width
            plot_type (str): The type of the plot data
        """
        dialogLayout = self.colorDialog.layout()
        if not dialogLayout:
            return

        formLayout = QtGui.QFormLayout()

        self.styleEditor = StyleEditorWidget(
            self,
            symbol=TEXT_SYMBOLS if plot_type == SCATTER_PLOT_TYPE else None,
            lineStyle=LINE_STYLES if line_style is not None else None,
            extraOption=None,
        )

        if plot_type == SCATTER_PLOT_TYPE:
            self.styleEditor.symbolComboBox.setCurrentText(symbol)
            self.styleEditor.symbolSizeSpinBox.setValue(symbol_size)

        if line_style is not None:
            self.styleEditor.lineStyleComboBox.setCurrentText(line_style)
            self.styleEditor.lineSizeSpinBox.setValue(line_size)

        formLayout.addWidget(self.styleEditor)

        dialogLayout.insertLayout(0, formLayout)

    def __onStyleChanged(self, *args, **kwargs):
        """Handles original color change signal to emit the custom informations as well."""
        color = self.color()
        symbol = (
            list(TEXT_SYMBOLS.keys())[0]
            if not hasattr(self.styleEditor, "symbolComboBox")
            else self.styleEditor.symbolComboBox.currentText()
        )
        symbolSize = (
            10 if not hasattr(self.styleEditor, "symbolSizeSpinBox") else self.styleEditor.symbolSizeSpinBox.value()
        )
        lineStyle = (
            list(LINE_STYLES.keys())[0]
            if not hasattr(self.styleEditor, "lineStyleComboBox")
            else self.styleEditor.lineStyleComboBox.currentText()
        )
        lineSize = 1 if not hasattr(self.styleEditor, "lineSizeSpinBox") else self.styleEditor.lineSizeSpinBox.value()
        self.sigStyleChanged.emit(color, symbol, symbolSize, lineStyle, lineSize)
