from typing import Any

import qt
import slicer
import os
import uuid

from ltrace.slicer import ui
from ltrace.slicer_utils import getResourcePath
from ltrace.slicer.widget.help_button import HelpButton
from typing import Callable
from copy import deepcopy


# Base class of presets
class Preset:
    def __init__(self, id=None, name=None):
        if id is None:
            id = str(uuid.uuid4())

        if name is None or not name.strip():
            name = slicer.mrmlScene.GenerateUniqueName("Preset")

        self.id = id
        self.name = name


class InputDialog(qt.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("Preset")

        self.presetName = qt.QLineEdit()

        applyButton = qt.QPushButton("Apply")
        applyButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Apply.png"))

        cancelButton = qt.QPushButton("Cancel")
        cancelButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Cancel.png"))

        applyButton.clicked.connect(lambda event: self.applyButtonClicked())
        cancelButton.clicked.connect(lambda event: self.reject())

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(applyButton)
        buttonsLayout.addWidget(cancelButton)

        formLayout = qt.QFormLayout()
        formLayout.addRow("Preset Name:", self.presetName)
        formLayout.addRow(buttonsLayout)
        formLayout.setVerticalSpacing(10)
        formLayout.setHorizontalSpacing(10)

        self.setLayout(formLayout)

    def showPopup(self, message):
        slicer.util.errorDisplay(message, "Missing Data")

    def applyButtonClicked(self):
        if self.presetName.text.strip() == "":
            self.showPopup("Preset name cannot be empty")
            return

        self.accept()

    def getOutputName(self):
        return self.presetName.text.strip()

    def setOutputName(self, name):
        self.presetName.text = name


class MessageDialog(qt.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("Message")

        self.message = qt.QLabel("Confirm")
        self.message.setAlignment(qt.Qt.AlignCenter)
        self.message.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)

        yesButton = qt.QPushButton("Yes")
        yesButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Apply.png"))

        noButton = qt.QPushButton("No")
        noButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Cancel.png"))

        yesButton.clicked.connect(lambda event: self.accept())
        noButton.clicked.connect(lambda event: self.reject())

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(yesButton)
        buttonsLayout.addWidget(noButton)

        formLayout = qt.QFormLayout()
        formLayout.addRow(self.message)
        formLayout.addRow(buttonsLayout)
        formLayout.setVerticalSpacing(10)
        formLayout.setHorizontalSpacing(10)

        self.setLayout(formLayout)

    def setMessage(self, message):
        self.message.text = message


class ExportImportDialog(qt.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.__checkedItemCount = 0

        formLayout = qt.QFormLayout()
        self.setLayout(formLayout)

        self.setWindowFlags(self.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("Selector")

        self.messageLabel = qt.QLabel()

        self.selectAllLabel = qt.QLabel("Select All: ")
        self.selectAllCkb = ui.CheckBoxWidget("Select all presets.", self._onSelectAllCkbChecked, checked=True)

        self.table = qt.QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["", "Name", "Data"])
        self.table.setFocusPolicy(qt.Qt.NoFocus)
        self.table.horizontalHeader().setSectionResizeMode(0, qt.QHeaderView.Fixed)
        self.table.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollMode(qt.QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(qt.QAbstractItemView.ScrollPerPixel)
        self.table.itemChanged.connect(self._onItemChanged)

        confirmButton = qt.QPushButton("Confirm")
        confirmButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Apply.png"))

        cancelButton = qt.QPushButton("Cancel")
        cancelButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Cancel.png"))

        confirmButton.clicked.connect(lambda event: self.accept())
        cancelButton.clicked.connect(lambda evnet: self.reject())

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(confirmButton)
        buttonsLayout.addWidget(cancelButton)

        formLayout.addRow(self.messageLabel)
        formLayout.addRow(self.selectAllLabel, self.selectAllCkb)
        formLayout.addRow(self.table)
        formLayout.addRow(buttonsLayout)
        formLayout.setVerticalSpacing(10)
        formLayout.setHorizontalSpacing(10)

    def resize(self, width, height):
        qt.QDialog.resize(self, width, height)
        slicer.app.processEvents()
        self._adjustTableSize()

    def resizeEvent(self, event):
        qt.QDialog.resizeEvent(self, event)
        slicer.app.processEvents()
        qt.QTimer.singleShot(10, self._adjustTableSize)

    def _adjustTableSize(self):
        self.table.resizeColumnsToContents()
        dialogWidth = self.table.viewport().width
        lastColumnWidth = self.table.horizontalHeader().sectionSize(self.table.columnCount - 1)

        # Sum of widths of all columns except the last one
        precedingColumnWidths = sum(
            self.table.horizontalHeader().sectionSize(i) for i in range(self.table.columnCount - 1)
        )

        # Set last column to fill remaining space or to fit all contents
        self.table.horizontalHeader().resizeSection(
            self.table.columnCount - 1, max(lastColumnWidth, dialogWidth - precedingColumnWidths)
        )

    def _onSelectAllCkbChecked(self, checkbox, event):
        state = qt.Qt.Unchecked
        self.__checkedItemCount = 0

        if self.selectAllCkb.isChecked():
            state = qt.Qt.Checked
            self.__checkedItemCount = self.table.rowCount

        # Prevent calling item changed while modifying the item state
        self.table.blockSignals(True)

        for i in range(self.table.rowCount):
            self.table.item(i, 0).setCheckState(state)

        self.table.blockSignals(False)

    def _onItemChanged(self, item):
        if item.checkState() == qt.Qt.Checked:
            self.__checkedItemCount = min(self.__checkedItemCount + 1, self.table.rowCount)
        else:
            self.__checkedItemCount = max(self.__checkedItemCount - 1, 0)

        # We just want to update the ckeckbox state, not run its state changing callback
        self.selectAllCkb.blockSignals(True)

        if self.__checkedItemCount >= self.table.rowCount:
            self.selectAllCkb.checked = True
        else:
            self.selectAllCkb.checked = False

        self.selectAllCkb.blockSignals(False)

    def reset(self):
        self.messageLabel.setText("")
        self.table.setRowCount(0)
        self.table.horizontalScrollBar().setValue(self.table.horizontalScrollBar().minimum)
        self.selectAllCkb.checked = True
        self.__checkedItemCount = 0

    def setMessageText(self, text=""):
        self.messageLabel.setText(text)

    def loadData(self, dataList: list[Preset]):
        dataList = sorted(dataList, key=lambda data: data.name.lower())
        self.table.setRowCount(len(dataList))
        self.__checkedItemCount = self.table.rowCount

        # When filling the table, prevent calling the item changed function, because it will run for every changing,
        # not only for the checkbox items
        self.table.blockSignals(True)

        for row, data in enumerate(dataList):
            displayInfo = deepcopy(vars(data))

            del displayInfo["id"]
            del displayInfo["name"]

            checkItem = qt.QTableWidgetItem(" ")
            checkItem.setData(qt.Qt.UserRole, data.id)
            checkItem.setFlags(
                (checkItem.flags() | qt.Qt.ItemIsUserCheckable) & ~qt.Qt.ItemIsSelectable & ~qt.Qt.ItemIsEditable
            )
            checkItem.setCheckState(qt.Qt.Checked)

            nameItem = qt.QTableWidgetItem(data.name)
            nameItem.setFlags(nameItem.flags() & ~qt.Qt.ItemIsSelectable & ~qt.Qt.ItemIsEditable)

            dataItem = qt.QTableWidgetItem(displayInfo)
            dataItem.setFlags(dataItem.flags() & ~qt.Qt.ItemIsSelectable & ~qt.Qt.ItemIsEditable)

            self.table.setItem(row, 0, checkItem)
            self.table.setItem(row, 1, nameItem)
            self.table.setItem(row, 2, dataItem)

        self.table.blockSignals(False)

    def getSelectedItems(self):
        data = []

        for i in range(self.table.rowCount):
            if self.table.item(i, 0).checkState() == qt.Qt.Checked:
                data.append(self.table.item(i, 0).data(qt.Qt.UserRole))

        return data


class PresetWidget(qt.QWidget):
    def __init__(
        self,
        onPresetSelected: Callable[[int], None] = None,
        onCreatePresetClicked: Callable[[Any], None] = None,
        onRenamePresetClicked: Callable[[Any], None] = None,
        onSavePresetClicked: Callable[[Any], None] = None,
        onDeletePresetClicked: Callable[[Any], None] = None,
        onExportPresetClicked: Callable[[Any], None] = None,
        onImportPresetClicked: Callable[[Any], None] = None,
        helpText: str = "",
        styledBox: bool = False,
        parent=None,
    ):
        super().__init__(parent)

        # Layout
        qt.QFormLayout(self)

        # Preset dialogs
        self.presetDialog = InputDialog(self.layout().parentWidget())
        self.presetDialog.objectName = "Preset Dialog"

        self.messageDialog = MessageDialog(self.layout().parentWidget())
        self.messageDialog.objectName = "Message Dialog"

        self.exportImportDialog = ExportImportDialog(self.layout().parentWidget())
        self.exportImportDialog.objectName = "Export Import Dialog"

        # Preset input
        self.presetComboBox = ui.SearchableCombobox(
            toolTip="Select a preset.", objectName="Preset Combo Box", parent=self.layout().parentWidget()
        )
        self.presetComboBox.currentIndexChanged.connect(self._onPresetSelected)

        if callable(onPresetSelected):
            self.presetComboBox.currentIndexChanged.connect(onPresetSelected)

        # Preset buttons
        self.createPresetBtn = ui.IconButtonWidget(
            onClick=onCreatePresetClicked,
            icon=qt.QIcon(getResourcePath("Icons") / "png" / "Add.png"),
            iconSize=(14, 14),
            tooltip="Create a preset.",
            objectName="Create Preset Button",
        )

        self.renamePresetBtn = ui.IconButtonWidget(
            onClick=onRenamePresetClicked,
            icon=qt.QIcon(getResourcePath("Icons") / "png" / "Edit.png"),
            iconSize=(14, 14),
            tooltip="Rename a preset.",
            objectName="Rename Preset Button",
        )

        self.savePresetBtn = ui.IconButtonWidget(
            onClick=onSavePresetClicked,
            icon=qt.QIcon(getResourcePath("Icons") / "png" / "Save.png"),
            iconSize=(14, 14),
            tooltip="Save the current parameters to the selected preset",
            objectName="Save Preset Button",
        )

        self.deletePresetBtn = ui.IconButtonWidget(
            onClick=onDeletePresetClicked,
            icon=qt.QIcon(getResourcePath("Icons") / "png" / "Delete.png"),
            iconSize=(14, 14),
            tooltip="Delete a preset.",
            objectName="Delete Preset Button",
        )

        presetHelpBtn = HelpButton(helpText)

        self.exportPresetBtn = ui.ButtonWidget(
            onClick=onExportPresetClicked,
            text="Export Preset List",
            tooltip="Export all presets.",
            object_name="Export Preset Button",
        )

        self.importPresetBtn = ui.ButtonWidget(
            onClick=onImportPresetClicked,
            text="Import Preset List",
            tooltip="Import a list of presets.",
            object_name="Import Preset Button",
        )

        # Preset widgets
        presetSection = ui.collapsibleButton("Presets", True, True)

        presetInputWidget = qt.QWidget()
        presetInputLayout = qt.QHBoxLayout(presetInputWidget)
        presetInputLayout.setContentsMargins(0, 0, 0, 0)
        presetInputLayout.addWidget(qt.QLabel("Preset: "))
        presetInputLayout.addWidget(self.presetComboBox)
        presetInputLayout.addWidget(self.createPresetBtn)
        presetInputLayout.addWidget(self.renamePresetBtn)
        presetInputLayout.addWidget(self.savePresetBtn)
        presetInputLayout.addWidget(self.deletePresetBtn)

        if helpText:
            presetInputLayout.addWidget(presetHelpBtn)

        presetImportExportWidget = qt.QWidget()
        presetImportExportLayout = qt.QHBoxLayout(presetImportExportWidget)
        presetImportExportLayout.setContentsMargins(0, 4, 0, 0)
        presetImportExportLayout.addWidget(self.exportPresetBtn)
        presetImportExportLayout.addWidget(self.importPresetBtn)

        if styledBox:
            presetBoxWidget = qt.QGroupBox()
            presetBoxWidget.setStyleSheet(
                """
                QGroupBox {
                    border: 1px solid #555555;
                    border-radius: 3px;
                    margin-top: 3px;
                    padding: 3px 0px 3px 0px;
                    font-size: 13px;
                }
                """
            )
        else:
            presetBoxWidget = qt.QWidget()

        presetBoxLayout = qt.QFormLayout(presetBoxWidget)
        presetBoxLayout.addRow(presetInputWidget)
        presetBoxLayout.addRow(presetImportExportWidget)

        presetSectionLayout = qt.QFormLayout(presetSection)
        presetSectionLayout.setContentsMargins(3, 0, 3, 6)
        presetSectionLayout.addRow(presetBoxWidget)

        # Update layout
        self.layout().setContentsMargins(12, 0, 12, 0)
        self.layout().addRow(presetSection)

    def _onPresetSelected(self):
        if self.presetComboBox.currentData is None:
            self.renamePresetBtn.enabled = False
            self.savePresetBtn.enabled = False
            self.deletePresetBtn.enabled = False
        else:
            self.renamePresetBtn.enabled = True
            self.savePresetBtn.enabled = True
            self.deletePresetBtn.enabled = True

    def _showInputDialog(self, title, initialPresetName, size):
        self.presetDialog.setWindowTitle(title)
        self.presetDialog.resize(size[0], size[1])
        self.presetDialog.setOutputName(initialPresetName)

        result = self.presetDialog.exec_()

        if result == qt.QDialog.Accepted:
            return self.presetDialog.getOutputName()

        return None

    def _showImportExportDialog(self, title, size, data, message):
        self.exportImportDialog.setWindowTitle(title)
        self.exportImportDialog.reset()
        self.exportImportDialog.loadData(data)
        self.exportImportDialog.setMessageText(message)
        self.exportImportDialog.resize(size[0], size[1])

        result = self.exportImportDialog.exec_()

        if result == qt.QDialog.Accepted:
            return self.exportImportDialog.getSelectedItems()

        return None

    def execCreateDialog(self, title="Create Preset", initialPresetName="", size=(400, 80)):
        return self._showInputDialog(title, initialPresetName, size)

    def execRenameDialog(self, title="Rename Preset", size=(400, 80)):
        return self._showInputDialog(title, self.presetComboBox.currentText, size)

    def execDeleteDialog(self, title="Delete Preset"):
        self.messageDialog.setWindowTitle(title)
        self.messageDialog.setMessage(
            f"The '<span style='color: yellow;'>{self.presetComboBox.currentText}</span>' preset will be "
            "deleted. Are you sure?"
        )

        result = self.messageDialog.exec_()

        return result == qt.QDialog.Accepted

    def execExportDialog(self, title="Export Presets", size=(700, 400), data=[], message=""):
        return self._showImportExportDialog(title, size, data, message)

    def execImportDialog(self, title="Import Presets", size=(700, 400), data=[], message=""):
        return self._showImportExportDialog(title, size, data, message)

    def execConflictDialog(self, title="Conflict Presets", size=(700, 400), data=[], message=""):
        return self._showImportExportDialog(title, size, data, message)

    def execGetSaveFileDialog(
        self,
        title="Export Presets",
        directory=os.path.join(slicer.mrmlScene.GetRootDirectory(), "Presets.json"),
        type="JSON files (*.json)",
    ):
        fileDialog = qt.QFileDialog(self.layout().parentWidget(), title, directory, type)
        fileDialog.setFileMode(qt.QFileDialog.AnyFile)
        fileDialog.setAcceptMode(qt.QFileDialog.AcceptSave)
        fileDialog.objectName = "Preset File Dialog"

        result = fileDialog.exec_()

        if result == qt.QDialog.Accepted:
            files = fileDialog.selectedFiles()
            if files:
                return files[0]

        return None

    def execGetOpenFileDialog(
        self,
        title="Import Presets",
        directory=slicer.mrmlScene.GetRootDirectory(),
        type="JSON files (*.json)",
    ):
        fileDialog = qt.QFileDialog(self.layout().parentWidget(), title, directory, type)
        fileDialog.setFileMode(qt.QFileDialog.ExistingFile)
        fileDialog.setAcceptMode(qt.QFileDialog.AcceptOpen)
        fileDialog.objectName = "Preset File Dialog"

        result = fileDialog.exec_()

        if result == qt.QDialog.Accepted:
            files = fileDialog.selectedFiles()
            if files:
                return files[0]

        return None

    def loadData(self, data: list[Preset]):
        self.presetComboBox.clear()
        self.presetComboBox.addItem("None", None)

        for item in data:
            self.presetComboBox.addItem(item.name, item.id)

    def addItem(self, data: Preset) -> None:
        self.presetComboBox.addItem(data.name, data.id)
        self.presetComboBox.setCurrentIndex(self.presetComboBox.findData(data.id))

    def removeItem(self, data: Preset) -> None:
        self.presetComboBox.removeItem(self.presetComboBox.findData(data.id))
        self.presetComboBox.setCurrentIndex(0)

    def updateItem(self, data: Preset) -> None:
        self.presetComboBox.setItemText(self.presetComboBox.findData(data.id), data.name)

    def getCurrentText(self) -> str:
        return self.presetComboBox.currentText

    def getCurrentData(self) -> Any:
        return self.presetComboBox.currentData

    def setCurrentText(self, text: str) -> None:
        self.presetComboBox.setCurrentText(text)

    def setCurrentData(self, data: Any) -> None:
        self.presetComboBox.setCurrentIndex(self.presetComboBox.findData(data))

    def setCurrentIndex(self, index: int) -> None:
        self.presetComboBox.setCurrentIndex(index)
