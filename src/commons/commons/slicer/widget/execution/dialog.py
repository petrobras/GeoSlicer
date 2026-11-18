"""The settings of one backend, in a dialog of their own.

What the execution section shows is what changes between two runs; what is here changes when you move to
another machine, so it is a click away instead of on screen. The dialog knows nothing about where the
values come from or go: it is handed a set of fields and their current values, and gives back what the
user left in them.
"""

import ctk
import qt
import slicer

from .options import BOOL, INT, LIST, MAP, PATH, Field, format_value, parse_value


class ExecutionSettingsDialog(qt.QDialog):
    def __init__(self, title: str, fields, values: dict, info: str = "", parent=None):
        super().__init__(parent or slicer.util.mainWindow())
        self.setWindowFlags(self.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.objectName = "Execution Settings Dialog"

        self._fields = tuple(fields)
        self._editors = {}

        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        if info:
            self.infoLabel = qt.QLabel(info)
            self.infoLabel.objectName = "Execution Settings Info"
            self.infoLabel.setWordWrap(True)
            self.infoLabel.setTextFormat(qt.Qt.PlainText)
            layout.addWidget(self.infoLabel)

        form = qt.QFormLayout()
        form.setVerticalSpacing(8)
        for item in self._fields:
            editor = self._buildEditor(item)
            editor.objectName = f"Execution Settings {item.key}"
            editor.setToolTip(item.tooltip)
            self._write(item, editor, (values or {}).get(item.key, item.default))
            self._editors[item.key] = editor
            form.addRow(f"{item.label}:", editor)
        layout.addLayout(form)

        layout.addStretch(1)

        buttons = qt.QHBoxLayout()
        buttons.setSpacing(8)

        self.defaultsButton = qt.QPushButton("Restore defaults")
        self.defaultsButton.objectName = "Execution Settings Defaults Button"
        self.defaultsButton.setToolTip("Empty every field above, so the defaults apply again.")
        self.defaultsButton.clicked.connect(self.restoreDefaults)
        buttons.addWidget(self.defaultsButton)
        buttons.addStretch(1)

        self.okButton = qt.QPushButton("OK")
        self.okButton.objectName = "Execution Settings Ok Button"
        self.okButton.clicked.connect(lambda checked=False: self.accept())
        buttons.addWidget(self.okButton)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.objectName = "Execution Settings Cancel Button"
        self.cancelButton.clicked.connect(lambda checked=False: self.reject())
        buttons.addWidget(self.cancelButton)

        layout.addLayout(buttons)

    # -- values -------------------------------------------------------------------------------------
    def values(self) -> dict:
        """What the fields hold now, whether or not the dialog was accepted."""
        return {item.key: self._read(item, self._editors[item.key]) for item in self._fields}

    def editor(self, key: str):
        """The editor showing one field, for a caller that wants to preselect or check it."""
        return self._editors.get(key)

    def restoreDefaults(self) -> None:
        for item in self._fields:
            self._write(item, self._editors[item.key], item.default)

    # -- editors ------------------------------------------------------------------------------------
    @staticmethod
    def _buildEditor(item: Field):
        if item.kind == BOOL:
            return qt.QCheckBox()

        if item.kind == INT:
            box = qt.QSpinBox()
            box.setRange(1, 4096)
            return box

        if item.kind == PATH:
            edit = ctk.ctkPathLineEdit()
            edit.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Executable
            return edit

        if item.kind == MAP:
            edit = qt.QPlainTextEdit()
            edit.setPlaceholderText(item.placeholder)
            edit.setMaximumHeight(72)
            return edit

        edit = qt.QLineEdit()
        edit.setPlaceholderText(item.placeholder)
        return edit

    @staticmethod
    def _write(item: Field, editor, value) -> None:
        if item.kind == BOOL:
            editor.setChecked(bool(value))
        elif item.kind == INT:
            editor.setValue(int(value or item.default or 1))
        elif item.kind == PATH:
            editor.currentPath = format_value(item.kind, value)
        elif item.kind == MAP:
            editor.setPlainText(format_value(item.kind, value))
        else:
            editor.setText(format_value(item.kind, value))

    @staticmethod
    def _read(item: Field, editor):
        if item.kind == BOOL:
            return bool(editor.checked)
        if item.kind == INT:
            return int(editor.value)
        if item.kind == PATH:
            return editor.currentPath.strip()
        if item.kind == MAP:
            return parse_value(MAP, editor.plainText)
        if item.kind == LIST:
            return parse_value(LIST, editor.text)
        return editor.text.strip()
