import slicer
import qt

from ltrace.slicer.helpers import svgToQIcon
from ltrace.slicer_utils import getResourcePath


class ExpandDataDrawer:

    APP_NAME = slicer.app.applicationName

    def __init__(self, drawer: qt.QWidget):

        self.closeIcon = svgToQIcon(getResourcePath("Icons") / "svg" / "PanelRightClose.svg")
        self.openIcon = svgToQIcon(getResourcePath("Icons") / "svg" / "PanelRightOpen.svg")
        self.__actionButton = None
        self.__drawer = drawer

        self.__drawer.setFeatures(qt.QDockWidget.DockWidgetFloatable | qt.QDockWidget.DockWidgetMovable)

    def widget(self):
        return self.__drawer

    def setAction(self, action):
        self.__actionButton = action

    def show(self, index=0):
        self.__actionButton.setIcon(self.closeIcon)
        self.__actionButton.setToolTip("Collapse Data")
        self.__drawer.setCurrentWidget(index)
        self.__drawer.visible = True
        slicer.app.userSettings().setValue(f"{ExpandDataDrawer.APP_NAME}/RighDrawerVisible", True)

    def hide(self):
        self.__actionButton.setIcon(self.openIcon)
        self.__actionButton.setToolTip("Expand Data")
        self.__drawer.visible = False
        slicer.app.userSettings().setValue(f"{ExpandDataDrawer.APP_NAME}/RighDrawerVisible", False)

    def __call__(self, *args, **kargs):
        if self.__drawer.visible:
            self.hide()
        else:
            self.show()
