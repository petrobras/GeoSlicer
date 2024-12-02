import qt
import slicer

from ltrace.slicer.module_info import ModuleInfo
from ltrace.slicer_utils import getResourcePath


class ModuleIndicator(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(2)

        self.moduleBtn = qt.QToolButton(self)
        self.moduleBtn.setToolButtonStyle(qt.Qt.ToolButtonTextBesideIcon)
        self.moduleBtn.setAutoRaise(True)

        # TODO check if it worth it to have a bookmark
        # self.bookmarkBtn = self.checkableButton(
        #     lambda checked: print("Bookmark checked" if checked else "Bookmark unchecked"),
        #     svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "BookmarkCheck.svg"),
        #     svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "Bookmark.svg"),
        #     checked=False
        # )
        # self.bookmarkBtn.setToolButtonStyle(qt.Qt.ToolButtonIconOnly)
        # self.bookmarkBtn.setAutoRaise(True)

        self.docBtn = qt.QToolButton(self)
        self.docBtn.setIcon(
            svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "CircleHelp.svg"),
        )
        self.docBtn.setToolButtonStyle(qt.Qt.ToolButtonIconOnly)
        self.docBtn.setAutoRaise(True)

        layout.addWidget(self.moduleBtn)
        # layout.addWidget(self.bookmarkBtn)
        layout.addWidget(self.docBtn)

    def setModule(self, moduleInfo: ModuleInfo):
        module = getattr(slicer.modules, moduleInfo.key.lower())
        self.moduleBtn.setIcon(module.icon)
        self.moduleBtn.setText(module.title)

    @staticmethod
    def checkableButton(func, checkedIcon, uncheckedIcon, checked=False):
        button = qt.QToolButton()
        button.setCheckable(True)
        button.setChecked(checked)
        button.setIcon(checkedIcon if checked else uncheckedIcon)

        # Connect the toggled signal to change the icon
        def update_icon(checked_):
            if checked_:
                button.setIcon(checkedIcon)
            else:
                button.setIcon(uncheckedIcon)

            func(checked_)

        button.toggled.connect(update_icon)

        return button
