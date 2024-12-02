import qt
import slicer

from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.constants import SaveStatus


class CustomizerEventFilter(qt.QWidget):
    """Class to handle Geoslicer main window event filter.
    Use the key arguments to pass references to objects or information needed for each custom's event handler
    """

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.__kwarg = kwargs

    def eventFilter(self, object, event):
        """Qt eventFilter method overload.
        Please read reference for more information: https://doc.qt.io/archives/qt-4.8/eventsandfilters.html
        """

        if event.type() == qt.QEvent.Close:
            appObservables = ApplicationObservables()
            mainWindow = slicer.modules.AppContextInstance.mainWindow
            isModified = mainWindow.isWindowModified()

            if isModified is False:
                event.accept()
                appObservables.aboutToQuit.emit()
                return False

            messageBox = qt.QMessageBox(mainWindow)
            messageBox.setWindowTitle("Exit")
            messageBox.setIcon(qt.QMessageBox.Warning)
            messageBox.setText("Save the changes before exiting?")
            saveExitButton = messageBox.addButton("&Save and Exit", qt.QMessageBox.ActionRole)
            exitButton = messageBox.addButton("&Exit without Saving", qt.QMessageBox.ActionRole)
            cancelButton = messageBox.addButton("&Cancel Exit", qt.QMessageBox.ActionRole)

            messageBox.exec_()

            if messageBox.clickedButton() == saveExitButton:
                saveCallback = self.__kwarg.get("saveSceneCallback", None)
                if saveCallback:
                    result = saveCallback()
                    if result == SaveStatus.SUCCEED:
                        event.accept()
                        appObservables.aboutToQuit.emit()
                        return False
                    elif result == SaveStatus.CANCELLED:
                        event.ignore()
                        return True
                    else:  # SaveStatus.FAILED options and SaveStatus.IN_PROGRESS
                        event.ignore()
                        return True
            elif messageBox.clickedButton() == exitButton:
                event.accept()
                appObservables.aboutToQuit.emit()
                return False
            else:
                event.ignore()
                return True

        return False
