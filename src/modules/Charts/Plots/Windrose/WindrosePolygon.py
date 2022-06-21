from pyqtgraph.Qt import QtCore, QtGui
import math


class WindrosePolygonItem(QtGui.QGraphicsPolygonItem):
    """QtGui.QGraphicsPolygonItem specialization to create a windrose bar polygon item"""

    def __init__(self, radius, alpha, *args, **kwargs):
        self.__radius = radius
        self.__alpha = alpha
        polygon = self.draw()
        super().__init__(polygon, *args, **kwargs)

    def draw(self):
        """Handles polygon's drawing.
           Need to enhance the curved line.

        Returns:
            QPolygonF: a floating point polygon object.
        """
        x0 = y0 = 0.0
        x1 = math.cos(math.radians(90 - self.__alpha / 2)) * self.__radius
        y1 = math.sin(math.radians(90 - self.__alpha / 2)) * self.__radius
        x2 = math.cos(math.radians(90 + self.__alpha / 2)) * self.__radius
        y2 = math.sin(math.radians(90 + self.__alpha / 2)) * self.__radius

        rect = QtCore.QRectF(x2, y1 - abs(self.__radius - y1) / 2, abs(x2 - x1), abs(self.__radius - y1))

        path = QtGui.QPainterPath()
        path.moveTo(x0, y0)
        path.lineTo(x1, y1)
        path.arcTo(rect, 0.0, -180.0)
        path.lineTo(x2, y2)
        path.lineTo(x0, y0)
        path.closeSubpath()

        return path.toFillPolygon()
