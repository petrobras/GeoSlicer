import slicer
import qt

from ltrace.slicer.helpers import svgToQIcon
from ltrace.slicer_utils import getResourcePath


class ExpandDataDrawer(qt.QObject):

    APP_NAME = slicer.app.applicationName
    DEFAULT_WIDTH = 383
    MINIMUM_WIDTH_TO_REMEMBER = 100

    def __init__(self, drawer: qt.QWidget):
        super().__init__(drawer)
        self.closeIcon = svgToQIcon(getResourcePath("Icons") / "svg" / "PanelRightClose.svg")
        self.openIcon = svgToQIcon(getResourcePath("Icons") / "svg" / "PanelRightOpen.svg")
        self.__actionButton = None
        self.__drawer = drawer

        self.__drawer.setFeatures(qt.QDockWidget.DockWidgetFloatable | qt.QDockWidget.DockWidgetMovable)
        self.__drawer.installEventFilter(self)
        self.__dockVisible = slicer.util.toBool(
            slicer.app.userSettings().value(f"{ExpandDataDrawer.APP_NAME}/RighDrawerVisible", True)
        )
        self.__oldWidth = self.DEFAULT_WIDTH

    def widget(self):
        return self.__drawer

    def setAction(self, action):
        self.__actionButton = action

    def show(self, index=0):
        if self.__drawer.width < self.DEFAULT_WIDTH:
            if self.__oldWidth > self.MINIMUM_WIDTH_TO_REMEMBER:
                width = self.__oldWidth
            else:
                width = self.DEFAULT_WIDTH
            self.__resizeDock(width)
        self.__setOpen()
        self.__drawer.setCurrentWidget(index)

    def hide(self):
        self.__resizeDock(1)
        self.__setClosed()
        self.__oldWidth = self.__drawer.width

    def eventFilter(self, obj, event):
        if event.type() == qt.QEvent.Resize:
            newWidth = event.size().width()
            oldWidth = event.oldSize().width()
            if not self.__dockVisible and newWidth > oldWidth and newWidth != 1:
                self.__setOpen()
        elif event.type() == qt.QEvent.Move:
            if self.__dockVisible and (event.pos().x() < 0 or event.pos().y() < 0):
                self.__oldWidth = 1
                self.__setClosed()
        return False

    def __resizeDock(self, size):
        self.__drawer.blockSignals(True)
        slicer.util.mainWindow().resizeDocks([self.__drawer], [size], qt.Qt.Horizontal)
        self.__drawer.blockSignals(False)

    def __setOpen(self):
        self.__actionButton.setIcon(self.closeIcon)
        self.__actionButton.setToolTip("Collapse Data")
        slicer.app.userSettings().setValue(f"{ExpandDataDrawer.APP_NAME}/RighDrawerVisible", True)
        self.__dockVisible = True

    def __setClosed(self):
        self.__actionButton.setIcon(self.openIcon)
        self.__actionButton.setToolTip("Expand Data")
        slicer.app.userSettings().setValue(f"{ExpandDataDrawer.APP_NAME}/RighDrawerVisible", False)
        self.__dockVisible = False

    def __call__(self, *args, **kargs):
        if self.__dockVisible:
            self.hide()
        else:
            self.show()
