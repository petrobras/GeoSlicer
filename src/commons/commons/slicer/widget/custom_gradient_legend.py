import pyqtgraph as pg
from pyqtgraph.Qt import QtGui, QtCore


class CustomGradientLegend(pg.GradientLegend):
    """
    Patchs pg.GradientLegend for the current pyqtgraph version available for python 3.6
    """

    def __init__(self, size, offset):
        super().__init__(size, offset)
        self.textPen = QtGui.QPen(QtGui.QColor(0, 0, 0))
        self.setZValue(100)  # draw on top of ordinary plots

    def paint(self, p, opt, widget):
        pg.UIGraphicsItem.paint(self, p, opt, widget)

        view = self.getViewBox()
        if view is None:
            return
        p.save()  # save painter state before we change transformation
        trans = view.sceneTransform()
        p.setTransform(trans)  # draw in ViewBox pixel coordinates
        rect = view.rect()

        ## determine max width of all labels
        labelWidth = 0
        labelHeight = 0
        for k in self.labels:
            b = p.boundingRect(
                QtCore.QRectF(0, 0, 0, 0),
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                str(k),
            )
            labelWidth = max(labelWidth, b.width())
            labelHeight = max(labelHeight, b.height())

        textPadding = 2  # in px

        xR = rect.right()
        xL = rect.left()
        yT = rect.top()
        yB = rect.bottom()

        # coordinates describe edges of text and bar, additional margins will be added for background
        if self.offset[0] < 0:
            x3 = xR + self.offset[0]  # right edge from right edge of view, offset is negative!
            x2 = x3 - labelWidth - 2 * textPadding  # right side of color bar
            x1 = x2 - self.size[0]  # left side of color bar
        else:
            x1 = xL + self.offset[0]  # left edge from left edge of view
            x2 = x1 + self.size[0]
            x3 = x2 + labelWidth + 2 * textPadding  # leave room for 2x textpadding between bar and text
        if self.offset[1] < 0:
            y2 = yB + self.offset[1]  # bottom edge from bottom of view, offset is negative!
            y1 = y2 - self.size[1]
        else:
            y1 = yT + self.offset[1]  # top edge from top of view
            y2 = y1 + self.size[1]
        self.b = [x1, x2, x3, y1, y2, labelWidth]

        ## Draw background
        p.setPen(self.pen)
        p.setBrush(self.brush)  # background color
        rect = QtCore.QRectF(
            QtCore.QPointF(x1 - textPadding, y1 - labelHeight / 2 - textPadding),  # extra left/top padding
            QtCore.QPointF(x3 + textPadding, y2 + labelHeight / 2 + textPadding),  # extra bottom/right padding
        )
        p.drawRect(rect)

        ## Draw color bar
        self.gradient.setStart(0, y2)
        self.gradient.setFinalStop(0, y1)
        p.setBrush(self.gradient)
        rect = QtCore.QRectF(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))
        p.drawRect(rect)

        ## draw labels
        p.setPen(self.textPen)
        tx = x2 + 2 * textPadding  # margin between bar and text
        lh = labelHeight
        lw = labelWidth
        for k in self.labels:
            y = y2 - self.labels[k] * (y2 - y1)
            p.drawText(
                QtCore.QRectF(tx, y - lh / 2, lw, lh),
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                str(k),
            )

        p.restore()  # restore QPainter transform to original state
