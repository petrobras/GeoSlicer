import qt


class ElidedLabel(qt.QLabel):
    def paintEvent(self, event):
        self.setToolTip(self.text)
        painter = qt.QPainter(self)

        metrics = qt.QFontMetrics(self.font)
        newWidth = self.width if self.parent() is None else self.parent().width
        elided = metrics.elidedText(self.text, qt.Qt.ElideRight, newWidth - 8)

        rect = self.rect
        rect.setWidth(newWidth)

        painter.drawText(rect, self.alignment, elided)
