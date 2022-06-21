from pathlib import Path
from typing import List
from dataclasses import dataclass

import qt, ctk, slicer

from ltrace.remote.hosts import PROTOCOL_HANDLERS
from ltrace.remote.hosts.base import Host


INDEX = {name: i for i, name in enumerate(PROTOCOL_HANDLERS)}


class ElidedLabel(qt.QLabel):
    def paintEvent(self, event):
        self.setToolTip(self.text)
        painter = qt.QPainter(self)

        metrics = qt.QFontMetrics(self.font)
        newWidth = self.width if self.parent() is None else self.parent().width
        elided = metrics.elidedText(self.text, qt.Qt.ElideRight, newWidth - 8)

        rect = self.rect
        rect.setWidth(newWidth)

        painter.drawText(rect, self.alignment, elided)


@dataclass
class HostInfo:
    name: str
    cls: Host
    widget: qt.QWidget = None


class RegisterWidget(qt.QWidget):
    saved = qt.Signal(Host)
    canceled = qt.Signal()

    def __init__(self, templates: List[Host] = None, parent=None) -> None:
        super().__init__(parent)

        self.setMinimumWidth(512)
        self.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Minimum)

        self.templates = templates
        self.rsa_key: Path = None
        self.hostInfo: List[HostInfo] = []

        self._loadHosts()
        self._setupUI()
        self._fillUI()

    def _loadHosts(self) -> None:
        for name, cls in PROTOCOL_HANDLERS.items():
            info = HostInfo(name=name, cls=cls)
            self.hostInfo.append(info)

    def _fillUI(self) -> None:
        self.templateComboBox.setCurrentIndex(0)
        self.protocolComboBox.setCurrentIndex(0)

    def _setupUI(self) -> None:
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        advancedLayout = qt.QFormLayout()
        self._setupTemplateOptions(advancedLayout)
        self._setupProtocolFields(advancedLayout)
        layout.addLayout(advancedLayout)

        self.stackedSettings = qt.QStackedWidget()

        for info in self.hostInfo:
            widget = info.cls.createWidget()
            groupBox = qt.QGroupBox(f"{info.name.upper()} connection details")
            widgetLayout = qt.QVBoxLayout(groupBox)
            widgetLayout.setContentsMargins(0, 0, 0, 0)
            widgetLayout.addWidget(widget)

            info.widget = widget
            self.stackedSettings.addWidget(groupBox)

        layout.addWidget(self.stackedSettings)
        self._setupButtons(layout)
        layout.addStretch(1)

        self.protocolComboBox.currentIndexChanged.emit(self.protocolComboBox.currentIndex)

    def _setupTemplateOptions(self, layout) -> None:
        self.templateComboBox = qt.QComboBox(self)
        self.templateComboBox.addItem("Custom", None)
        if self.templates:
            for name, data in self.templates:
                self.templateComboBox.addItem(name, data)
        else:
            self.templateComboBox.setEnabled(False)
        self.templateComboBox.currentIndexChanged.connect(self._onTemplateChanged)
        self.templateComboBox.setToolTip("Select a template to fill in the fields below")

        layout.addRow("Template: ", self.templateComboBox)

    def _setupProtocolFields(self, layout) -> None:
        self.protocolComboBox = qt.QComboBox(self)
        self.protocolComboBox.setToolTip("Protocol to use for connection")

        for info in self.hostInfo:
            print(info)
            self.protocolComboBox.addItem(info.cls.protocol_name, info.cls)

        self.protocolComboBox.model().sort(0)
        self.protocolComboBox.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Preferred)
        self.protocolComboBox.currentIndexChanged.connect(self._onProtocolChanged)
        layout.addRow("Connect to: ", self.protocolComboBox)

    def _setupButtons(self, layout) -> None:
        self.saveButton = qt.QPushButton("Save", self)
        self.saveButton.setAutoDefault(True)
        self.saveButton.clicked.connect(self._onSaveClicked)

        self.cancelButton = qt.QPushButton("Cancel", self)
        self.cancelButton.clicked.connect(self._onCancelClicked)

        buttonLayout = qt.QHBoxLayout()
        buttonLayout.addStretch(1)
        buttonLayout.addWidget(self.saveButton)
        buttonLayout.addWidget(self.cancelButton)

        layout.addLayout(buttonLayout)

    def _onCancelClicked(self) -> None:
        self.close()
        self.canceled.emit()

    def _onSaveClicked(self) -> None:
        self.saved.emit(self.getData())

    def _onTemplateChanged(self, index: int) -> None:
        data: Host = self.templateComboBox.itemData(index)
        if data is not None:
            self.stackedSettings.setCurrentIndex(INDEX[data.protocol])
            self.setData(data)

    def _onProtocolChanged(self, index: int) -> None:
        data: Host = self.protocolComboBox.itemData(index)
        self.stackedSettings.setCurrentIndex(INDEX[data.protocol])

    def setData(self, data: Host) -> None:
        index = INDEX[data.protocol]
        host = self.hostInfo[index]
        host.widget.setData(data)
        self.protocolComboBox.setCurrentIndex(index)

    def getData(self) -> Host:
        data: Host = self.protocolComboBox.currentData
        try:
            handler = self.hostInfo[INDEX[data.protocol]]
            return handler.widget.getData()
        except KeyError as ke:
            raise KeyError(f"'{data.protocol.upper()}' host has not been implemented.")


class RegisterDialog(qt.QDialog):
    def __init__(self, templates=None, parent=None) -> None:
        super().__init__(parent)

        self.widget = RegisterWidget(templates, self)
        self.widget.saved.connect(self.success)
        self.widget.canceled.connect(self.cancel)

        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.widget)

    def success(self) -> None:
        self.accept()

    def cancel(self) -> None:
        self.reject()

    @staticmethod
    def editing(host: Host, parent=None) -> Host:
        dialog = RegisterDialog(parent=parent)
        dialog.setWindowTitle("Edit Connection")
        dialog.widget.setData(host)
        if dialog.exec_():
            return dialog.widget.getData()
        return None

    @staticmethod
    def creating(templates=None, parent=None) -> Host:
        dialog = RegisterDialog(templates=templates, parent=parent)
        dialog.setWindowTitle("New Connection")
        if dialog.exec_():
            return dialog.widget.getData()
        return None
