import qt
import slicer


class CustomEventFilter(qt.QObject):
    def __init__(self, filter_callback, target=None):
        super().__init__()
        self.filter_callback = filter_callback
        self.target = target or slicer.modules.AppContextInstance.mainWindow

    def install(self):
        self.target.installEventFilter(self)

    def remove(self):
        self.target.removeEventFilter(self)

    def eventFilter(self, object, event):
        self.filter_callback(object, event)
