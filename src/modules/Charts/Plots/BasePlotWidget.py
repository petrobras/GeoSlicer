from abc import abstractclassmethod

from pyqtgraph.Qt import QtGui, QtCore, QtWidgets
import pyqtgraph as pg
from pathlib import Path

RESOURCES_PATH = Path(__file__).absolute().with_name("Resources")
WINDOWN_ICON = RESOURCES_PATH / "Charts.png"


class BasePlotWidget(QtWidgets.QDialog):
    """Base class to  custom plot types of Charts module.
       Provides the setup behavior and the interface methods to be customized in the derived class.
       Check out the methods 'setupUi' and 'appendData'

    Args:
        QtGui ([type]): [description]
    """

    def __init__(self, plotType="", plotLabel="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowModality(QtCore.Qt.WindowModality.NonModal)
        self.setWindowTitle(f"{plotType}: {plotLabel}")
        self.setWindowIcon(QtGui.QIcon(str(WINDOWN_ICON)))
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)

        self.__type = plotType
        self.__label = plotLabel

    def show(self):
        self.setupUi()
        super().show()

    def exec(self):
        self.setupUi()
        super().exec_()

    @property
    def type(self):
        return self.__type

    @property
    def label(self):
        return self.__label

    @abstractclassmethod
    def setupUi(self):
        """Handles the dialog's layout setup.
        Use this method to initialize all the dialogs necessary widgets
        """
        pass

    @abstractclassmethod
    def appendData(self, dataNode):
        """Handles data insertion to the plot's widget.

        Args:
            dataNode (dataNode): The node with the data to be inserted at the widget.
        """
        pass
