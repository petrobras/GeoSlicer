import qt

from commons.slicer.custom_modules.dev_tools import CustomModuleDevTools
from commons.slicer.helpers import svgToQIcon
from commons.slicer_utils import getResourcePath
from commons.slicer.widget.help_button import HelpButton


class ModuleHeader(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Initialize layout
        self.objectName = "ModuleHeader"
        self.headerLayout = qt.QHBoxLayout(self)
        self.headerLayout.setContentsMargins(6, 6, 6, 6)
        self.headerLayout.setSpacing(3)
        self.headerLayout.setAlignment(qt.Qt.AlignLeft)

        self.baseIcon = svgToQIcon(getResourcePath("Icons") / "svg" / "ChevronRight.svg")
        self.baseLabel = qt.QLabel()
        self.baseLabel.setPixmap(self.baseIcon.pixmap(qt.QSize(16, 16)))
        self.moduleTitle = qt.QLabel("")
        self.moduleHelp = HelpButton()
        self.moduleHelp.setFixedSize(21, 21)

        self.devTools = CustomModuleDevTools()

        self.headerLayout.setAlignment(qt.Qt.AlignLeft)
        self.headerLayout.addWidget(self.baseLabel)
        self.headerLayout.addWidget(self.moduleTitle)
        self.headerLayout.addStretch(1)
        self.headerLayout.addWidget(self.devTools)
        self.headerLayout.addWidget(self.moduleHelp)

    def update(self, title, helpURL, moduleName=None):
        self.moduleTitle.setText(title.upper())
        self.moduleHelp.updateLink(helpURL)
        self.devTools.setModule(moduleName)
