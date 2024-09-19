import qt
import slicer

from ltrace.slicer.application_observables import ApplicationObservables


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
        appObservables = ApplicationObservables()
        mainWindow = slicer.util.mainWindow()
        if event.type() == qt.QEvent.Close:
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
                    if result is True:
                        event.accept()
                        appObservables.aboutToQuit.emit()
                        return False
                    else:
                        # Save process was cancelled or an error occurred
                        qt.QMessageBox(qt.QMessageBox.Warning, "Error saving", "Try to save your data manually")
                        appObservables.aboutToQuit.emit()
                        return False
            elif messageBox.clickedButton() == exitButton:
                event.accept()
                appObservables.aboutToQuit.emit()
                return False
            else:
                event.ignore()
                return True

        return False
