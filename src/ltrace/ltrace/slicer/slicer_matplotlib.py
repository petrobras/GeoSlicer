from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide2 import QtCore, QtGui, QtWidgets
import shiboken2


class MatplotlibCanvasWidget(FigureCanvasQTAgg):
    def __init__(self, parent=None, minWidth=None, minHeight=None):
        fig = Figure()
        FigureCanvasQTAgg.__init__(self, fig)

        self.setParent(parent)

        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.updateGeometry()
        self._update_figure_size()
        self.pyqtlayout = None

        if minWidth:
            self.figure.set_figwidth(minWidth)

        if minHeight:
            self.figure.set_figheight(minHeight)

    def add_subplot(self, *args, **kwargs):
        self.axes = self.figure.add_subplot(*args, **kwargs)

    def _update_figure_size(self):
        s = self.size()
        width_pixels = s.width()
        height_pixels = s.height()

        self.figure.set_size_inches(width_pixels / self.figure.dpi, height_pixels / self.figure.dpi)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_figure_size()

    def getPythonQtWidget(self):
        from PySide2.QtWidgets import QVBoxLayout
        import PythonQt

        if self.pyqtlayout is None:
            self.pyqtlayout = PythonQt.Qt.QVBoxLayout()
            self.pysideLayout = shiboken2.wrapInstance(hash(self.pyqtlayout), QVBoxLayout)
            self.pysideLayout.addWidget(self)
            self.pysideLayout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)

        return self.pyqtlayout.itemAt(0).widget()
