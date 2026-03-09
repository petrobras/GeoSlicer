import numpy as np
import pyqtgraph as pg
import vtk
from vtk.util.numpy_support import vtk_to_numpy

from PySide2.QtCore import Qt
from PySide2.QtGui import QImage, QPixmap, QCursor
from PySide2.QtWidgets import QLabel, QWidget


class DragViewManager:
    class FramelessWindow(QWidget):
        def __init__(self, logic):
            self.dataLogic = logic
            super().__init__()
            self.setWindowFlags(Qt.FramelessWindowHint)
            self.label = QLabel("", self)
            self.label.setAlignment(Qt.AlignCenter)
            self.label.setStyleSheet("border: 2px dashed gray;")
            self.setAcceptDrops(True)

        # Prevents this own window from blocking the drag when mouse moves too fast and enters it
        def dragEnterEvent(self, event):
            g = self.geometry()
            self.setGeometry(event.pos().x() + g.width(), event.pos().y() + g.height(), g.width(), g.height())
            event.ignore()

    def __init__(self, logic):
        self.dataLogic = logic
        self.dragMimeTextPrefix = "draggingView"
        self.viewsIdentifiersFromTo = [0, 0]
        self.dragging = False
        self.logViewScreenshot = DragViewManager.FramelessWindow(
            logic
        )  # without setting parent to not mix qt and PySide
        self.logViewScreenshot.setAttribute(Qt.WA_TranslucentBackground, True)

    def __del__(self):
        self.logViewScreenshot.deleteLater()

    def moveLogViewScreenshot(self, posMouse):
        g = self.logViewScreenshot.geometry()
        self.logViewScreenshot.setGeometry(posMouse.x() + 10, posMouse.y() + 10, g.width(), g.height())

    def updateViewsIdentifiersFromTo1(self, globalPos):
        self.viewsIdentifiersFromTo[1] = self.dataLogic.getIdentifierAt(globalPos.x(), globalPos.y())

    def captureVtkAndDisplay(self, imageLogViewRenderWindow):
        windowToImage = vtk.vtkWindowToImageFilter()
        windowToImage.SetInputBufferTypeToRGBA()
        windowToImage.SetInput(imageLogViewRenderWindow)
        windowToImage.Update()

        vtkImage = windowToImage.GetOutput()
        dims = vtkImage.GetDimensions()
        scalars = vtkImage.GetPointData().GetScalars()

        npArray = vtk_to_numpy(scalars)

        # Applying some transparency
        npArrayFloat = npArray.astype(np.float32)
        npArrayFloat[:, 3] *= 0.4
        npArray = np.clip(npArrayFloat, 0, 255).astype(np.uint8)

        # Adequating the vtk array to what QImage expects
        npArrayC = np.ascontiguousarray(npArray)

        image = QImage(npArrayC, dims[0], dims[1], QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(image)

        self.logViewScreenshot.label.setPixmap(pixmap.scaled(self.logViewScreenshot.size(), Qt.KeepAspectRatio))
        self.logViewScreenshot.label.setGeometry(0, 0, self.logViewScreenshot.width(), self.logViewScreenshot.height())
        self.logViewScreenshot.label.show()

    def capturePyqtgraphAndDisplay(self, plotItem, width, height, dataLogic):
        image = QImage(plotItem.size().width(), plotItem.size().height(), QImage.Format_ARGB32)
        image.fill(Qt.transparent)

        painter = pg.QtGui.QPainter(image)
        plotItem.scene().render(
            painter,
            pg.Qt.QtCore.QRectF(0, 0, width, height),
            pg.Qt.QtCore.QRectF(0, 0, plotItem.size().width(), plotItem.size().height()),
        )
        painter.end()

        pixmap = QPixmap.fromImage(image)

        self.logViewScreenshot.label.setPixmap(pixmap.scaled(self.logViewScreenshot.size(), Qt.KeepAspectRatio))
        self.logViewScreenshot.label.setGeometry(0, 0, self.logViewScreenshot.width(), self.logViewScreenshot.height())
        self.logViewScreenshot.label.show()

    def displayEmpty(self):
        dims = [1, 1]
        npArray = np.zeros(shape=(2, 4), dtype=np.uint8)
        npArray = np.array([0, 0, 0, 102])  # one black pixel with transparency
        npArrayC = np.ascontiguousarray(npArray)
        image = QImage(npArrayC, dims[0], dims[1], QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(image)
        self.logViewScreenshot.label.setPixmap(pixmap.scaled(self.logViewScreenshot.size(), Qt.KeepAspectRatio))
        self.logViewScreenshot.label.setGeometry(0, 0, self.logViewScreenshot.width(), self.logViewScreenshot.height())
        self.logViewScreenshot.label.show()
