import logging

import qt
import slicer

from commons.slicer.custom_modules.logic import customModules
from commons.slicer.helpers import svgToQIcon
from commons.slicer_utils import getResourcePath


def editModuleSource(moduleName: str) -> None:
    """Open a module's source file, honoring the Python editor set in the application settings."""
    widget = slicer.util.getModuleWidget(moduleName)
    if hasattr(widget, "onEditSource"):
        widget.onEditSource()
        return

    filePath = slicer.util.modulePath(moduleName)
    if not qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(filePath)):
        logging.error(f"Failed to open {filePath}")


class CustomModuleDevTools(qt.QWidget):
    """Reload and edit buttons for the module header. Shown for custom modules only, so users can work on their code
    without developer mode."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.objectName = "Module Header Dev Tools"
        self.visible = False
        self.moduleName = None

        # One bordered box around the label and its buttons, so they read as a group
        frame = qt.QFrame()
        frame.objectName = "moduleHeaderDevFrame"
        frame.toolTip = "Tools for developing this custom module"
        frame.setStyleSheet("QFrame#moduleHeaderDevFrame { border: 1px solid #7a7a7a; border-radius: 3px; }")

        label = qt.QLabel("DEV")
        label.setStyleSheet("QLabel { color: #b8b8b8; font-size: 7pt; font-weight: bold; }")

        self.reloadButton = self.__toolButton("Reload Module Header Button", "Refresh", "Reload this module's code")
        self.reloadButton.clicked.connect(lambda: slicer.util.reloadScriptedModule(self.moduleName))

        self.editButton = self.__toolButton(
            "Edit Module Header Button",
            "SquarePen",
            "Open this module's code in an editor",
        )
        self.editButton.clicked.connect(lambda: editModuleSource(self.moduleName))

        frameLayout = qt.QHBoxLayout(frame)
        frameLayout.setContentsMargins(5, 0, 2, 0)
        frameLayout.setSpacing(3)
        frameLayout.addWidget(label)
        frameLayout.addSpacing(2)
        frameLayout.addWidget(self.reloadButton)
        frameLayout.addWidget(self.editButton)

        layout = qt.QHBoxLayout(self)
        # Keeps the dev tools apart from the help button
        layout.setContentsMargins(0, 0, 12, 0)
        layout.addWidget(frame)

    def setModule(self, moduleName) -> None:
        """Point the buttons at a module, showing them only if it is a custom module."""
        self.moduleName = moduleName
        self.visible = moduleName is not None and customModules().isCustomModule(moduleName)

    @staticmethod
    def __toolButton(objectName, iconName, toolTip):
        button = qt.QToolButton()
        button.objectName = objectName
        button.setIcon(svgToQIcon(getResourcePath("Icons") / "svg" / f"{iconName}.svg"))
        button.setToolTip(toolTip)
        button.setAutoRaise(True)
        button.setFixedSize(21, 21)
        return button
