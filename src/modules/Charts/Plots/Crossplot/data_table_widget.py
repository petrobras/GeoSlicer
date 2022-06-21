import os

from pyqtgraph.Qt import QtCore, QtGui

from ltrace.slicer.graph_data import TEXT_SYMBOLS, LINE_STYLES, SYMBOL_TEXT, LINE_STYLES_TEXT
from ltrace.slicer.widget.custom_color_button import CustomColorButton
from ltrace.slicer.widget.style_editor_widget import StyleEditorWidget

RESOURCES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Resources")
ICONS_DIR_PATH = os.path.join(RESOURCES_PATH, "Icons")
REMOVE_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "CancelIcon.png")
VISIBLE_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "eye.svg")
NOT_VISIBLE_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "eye-off.svg")
EDIT_ALL_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "edit-all.svg")
ALL_VISIBILITY_ON_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "toggle-left.svg")
ALL_VISIBILITY_OFF_ICON_FILE_PATH = os.path.join(ICONS_DIR_PATH, "toggle-right.svg")


class DataTableWidget(QtGui.QTreeWidget):
    signal_style_changed = QtCore.Signal()
    signal_data_removed = QtCore.Signal(str)
    signal_all_style_changed = QtCore.Signal(str, int, str, int)
    signal_all_visible_changed = QtCore.Signal(bool)

    ALL_VISIBILITY_STATE = True

    INPUT_DATA_TYPE = 0
    FIT_DATA_TYPE = 1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setColumnCount(2)
        self.setHeaderLabels(["Data", "Options"])
        self.header().setResizeMode(0, QtGui.QHeaderView.Stretch)
        self.header().setStretchLastSection(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(self.SelectRows)
        self.setSelectionMode(self.SingleSelection)

        self.input_data_item = QtGui.QTreeWidgetItem(["Input data"])
        self.input_data_item.setFlags(self.input_data_item.flags() & ~QtCore.Qt.ItemIsEditable)
        self.addTopLevelItem(self.input_data_item)

        self.fitted_curves_item = QtGui.QTreeWidgetItem(["Curves"])
        self.fitted_curves_item.setFlags(self.fitted_curves_item.flags() & ~QtCore.Qt.ItemIsEditable)
        self.addTopLevelItem(self.fitted_curves_item)

        self.editAllStyleDialog = StyleEditorWidget(useButtons=True)

        visibilityButton = QtGui.QPushButton(QtGui.QIcon(str(ALL_VISIBILITY_ON_ICON_FILE_PATH)), "")
        visibilityButton.setFixedSize(26, 26)
        visibilityButton.setIconSize(QtCore.QSize(20, 20))
        visibilityButton.setAutoDefault(False)
        visibilityButton.setDefault(False)
        visibilityButton.setToolTip("Turn on/off all input data")

        editButton = QtGui.QPushButton(QtGui.QIcon(str(EDIT_ALL_ICON_FILE_PATH)), "")
        editButton.setFixedSize(26, 26)
        editButton.setIconSize(QtCore.QSize(20, 20))
        editButton.setAutoDefault(False)
        editButton.setDefault(False)
        editButton.setToolTip("Edit the style for all input data")

        optionsLayout = QtGui.QHBoxLayout()
        optionsLayout.setSizeConstraint(QtGui.QLayout.SetMinimumSize)
        optionsLayout.setSpacing(5)
        optionsLayout.addWidget(visibilityButton)
        optionsLayout.addWidget(editButton)

        # connections
        visibilityButton.clicked.connect(lambda: self.__on_all_visibility_button_clicked(visibilityButton))
        editButton.clicked.connect(lambda: self.editAllStyleDialog.show())
        self.editAllStyleDialog.sigAllStyleChange.connect(
            lambda symbol, symbol_size, line_style, line_size: self.signal_all_style_changed.emit(
                symbol, symbol_size, line_style, line_size
            )
        )

        optionsWidget = QtGui.QWidget()
        optionsWidget.setLayout(optionsLayout)
        optionsWidget.setFixedSize(26, 26)
        self.setItemWidget(self.input_data_item, 1, optionsWidget)

        # Create dummy widgets to assure a proper height to the top level items
        fit_dummy_widget = QtGui.QWidget()
        fit_dummy_widget.setFixedSize(26, 26)
        self.setItemWidget(self.fitted_curves_item, 1, fit_dummy_widget)

    def add_data(self, graphData, data_type):
        """Creates objects and widgets related to the GraphData inserted."""
        # Options widget
        optionsWidget = QtGui.QWidget()

        # Visible toggle button
        visibleButton = QtGui.QPushButton("")
        self.__updateTableVisibleButton(visibleButton, graphData)
        visibleButton.setFixedSize(26, 26)
        visibleButton.setIconSize(QtCore.QSize(20, 20))
        visibleButton.setAutoDefault(False)
        visibleButton.setDefault(False)

        # Customize style button
        editButton = CustomColorButton(
            color=graphData.style.color,
            symbol=SYMBOL_TEXT[graphData.style.symbol],
            symbol_size=graphData.style.size,
            line_style=LINE_STYLES_TEXT[graphData.style.line_style],
            line_size=graphData.style.line_size,
            plot_type=graphData.style.plot_type,
        )
        editButton.setFixedSize(26, 26)
        editButton.setAutoDefault(False)
        editButton.setDefault(False)

        # Remove button
        removeButton = QtGui.QPushButton(QtGui.QIcon(str(REMOVE_ICON_FILE_PATH)), "")
        removeButton.setFixedSize(26, 26)
        removeButton.setIconSize(QtCore.QSize(20, 20))
        removeButton.setAutoDefault(False)
        removeButton.setDefault(False)

        # Options widget layout
        optionsLayout = QtGui.QHBoxLayout()
        optionsLayout.setSizeConstraint(QtGui.QLayout.SetMinimumSize)
        optionsLayout.setSpacing(5)
        optionsLayout.addWidget(visibleButton)
        optionsLayout.addWidget(editButton)
        optionsLayout.addWidget(removeButton)
        optionsWidget.setLayout(optionsLayout)

        # Buttons connections
        visibleButton.clicked.connect(lambda state: self.__toggleGraphVisible(visibleButton, graphData))
        removeButton.clicked.connect(lambda state: self.__on_remove_button_clicked(graphData))
        editButton.sigStyleChanged.connect(
            lambda color, symbol, size, lineStyle, lineSize: self.__onPlotStyleChanged(
                graphData, color, symbol, size, lineStyle, lineSize
            )
        )

        nameItem = QtGui.QTreeWidgetItem([graphData.name])
        nameItem.setFlags(nameItem.flags() & ~QtCore.Qt.ItemIsEditable)
        if data_type == self.INPUT_DATA_TYPE:
            self.input_data_item.addChild(nameItem)
        else:
            self.fitted_curves_item.addChild(nameItem)
        self.setItemWidget(nameItem, 1, optionsWidget)

    def clear(self):
        self.input_data_item.takeChildren()
        self.fitted_curves_item.takeChildren()

    def __onPlotStyleChanged(self, graphData, color, symbol_text, size, line_style, line_size):
        """Handles plot style update

        Args:
            graphData (GraphData): the related GraphData object
            color (tuple): the RGB tuple chosed
            symbol_text (str): the symbol description chosed
            size (int): the symbol pen size chosed
            line_style (str): the chosen line description
            line_size (int): the chosen line pen size
        """
        graphData.style.color = (color.red(), color.green(), color.blue())
        graphData.style.symbol = TEXT_SYMBOLS[symbol_text]
        graphData.style.size = size
        graphData.style.line_style = LINE_STYLES[line_style]
        graphData.style.line_size = line_size
        self.signal_style_changed.emit()

    def __updateTableVisibleButton(self, button: QtGui.QPushButton, graphData):
        """Updates icon of the related visible button (from the table widget)."""
        if graphData.visible is True:
            button.setIcon(QtGui.QIcon(str(VISIBLE_ICON_FILE_PATH)))
        else:
            button.setIcon(QtGui.QIcon(str(NOT_VISIBLE_ICON_FILE_PATH)))

    def __toggleGraphVisible(self, button: QtGui.QPushButton, graphData):
        """Updates visible state from GraphData object."""
        graphData.visible = not graphData.visible
        self.__updateTableVisibleButton(button, graphData)

    def __on_remove_button_clicked(self, graph_data):
        self.signal_data_removed.emit(graph_data.name)

    def __update_all_visibility_button_icon(self, button, state):
        """Update the icon of the all visibility button"""
        if state:
            button.setIcon(QtGui.QIcon(str(ALL_VISIBILITY_ON_ICON_FILE_PATH)))
        else:
            button.setIcon(QtGui.QIcon(str(ALL_VISIBILITY_OFF_ICON_FILE_PATH)))

    def __on_all_visibility_button_clicked(self, button):
        self.ALL_VISIBILITY_STATE = not self.ALL_VISIBILITY_STATE
        self.__update_all_visibility_button_icon(button, self.ALL_VISIBILITY_STATE)
        self.signal_all_visible_changed.emit(self.ALL_VISIBILITY_STATE)
