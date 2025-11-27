import qt
import slicer


class CustomEventFilter(qt.QObject):
    def __init__(self, filter_callback, target=None):
        self.target = target or slicer.modules.AppContextInstance.mainWindow
        super().__init__(target)
        self.filter_callback = filter_callback
        self.destroyed.connect(self.__del__)

    def __del__(self):
        self.filter_callback = None
        if self.target:
            self.remove()
            self.target = None

    def install(self):
        self.target.installEventFilter(self)

    def remove(self):
        self.target.removeEventFilter(self)

    def eventFilter(self, object, event):
        self.filter_callback(object, event)
