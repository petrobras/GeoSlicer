import ctk
import qt
import slicer

from pathlib import Path


class CustomPathLineEditFilter(qt.QWidget):
    """Class to handle Geoslicer main window event filter.
    Use the key arguments to pass references to objects or information needed for each custom's event handler
    """

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.__focusOutCallback = kwargs.get("focusOut", lambda x: None)
        self.__enterKeyPressCallback = kwargs.get("enterKeyPress", lambda x: None)

    def eventFilter(self, object, event):
        """Qt eventFilter method overload.
        Please read reference for more information: https://doc.qt.io/archives/qt-4.8/eventsandfilters.html
        """
        if event.type() == qt.QEvent.FocusOut:
            self.__focusOutCallback()
            return True

        elif event.type() == qt.QEvent.KeyPress:
            if event.key() == qt.Qt.Key_Enter - 1:  # 1677721
                self.__enterKeyPressCallback()
                return True

        return False


class CustomPathLineEdit(ctk.ctkPathLineEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(self, *args, **kwargs)
        self.validInputChanged.connect(lambda x: self.__onExportPathChanged())
        self.__pathEventFilter = CustomPathLineEditFilter(
            focusOut=self.__onExportPathChanged, enterKeyPress=self.__onExportPathChanged
        )
        self.comboBox().installEventFilter(self.__pathEventFilter)

    def defaultSuffix(self):
        return self.nameFilters[0].split(".")[-1]

    def __onExportPathChanged(self):
        if self.hasFocus():
            return

        path = self.currentPath

        if not path.replace(" ", ""):
            return

        file_path = Path(path)

        if not file_path.parent.exists():
            slicer.util.errorDisplay("Please select a valid export's file path.")

            blockState = self.blockSignals(True)
            self.setCurrentPath("")
            self.blockSignals(blockState)
            return

        if file_path.suffix == f".{self.defaultSuffix()}":
            return

        if not file_path.stem or file_path.stem == self.defaultSuffix():
            file_name = f"output.{self.defaultSuffix()}"
        else:
            file_name = f"{file_path.stem}.{self.defaultSuffix()}"

        new_path = file_path.parent / file_name
        blockState = self.blockSignals(True)
        self.setCurrentPath(new_path.as_posix())
        self.blockSignals(blockState)
