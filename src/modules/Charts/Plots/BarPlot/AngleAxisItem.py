from pyqtgraph import AxisItem
import math

__all__ = ["AngleAxisItem"]


class AngleAxisItem(AxisItem):
    def __init__(self, angle=0, *args, **kwargs):
        AxisItem.__init__(self, *args, **kwargs)
        self._angle = angle
        self._height_updated = False

    def setTicksAngle(self, angle):
        self._angle = angle

    def drawPicture(self, p, axisSpec, tickSpecs, textSpecs):
        max_width = 0
        p.setRenderHint(p.Antialiasing, False)
        p.setRenderHint(p.TextAntialiasing, True)
        pen, p1, p2 = axisSpec
        p.setPen(pen)
        p.drawLine(p1, p2)
        p.translate(0.5, 0)  ## resolves some damn pixel ambiguitys
        for pen, p1, p2 in tickSpecs:
            p.setPen(pen)
            p.drawLine(p1, p2)

        for rect, flags, text in textSpecs:
            p.save()  # save the painter state

            p.translate(rect.center())  # move coordinate system to center of text rect
            p.rotate(self._angle)  # rotate text
            p.translate(-rect.center())  # revert coordinate system

            x_offset = math.ceil(math.fabs(math.sin(math.radians(self._angle)) * rect.width()))
            if self._angle < 0:
                x_offset = -x_offset
            p.translate(x_offset / 1.5, 0)  # Move the coordinate system (relatively) downwards

            p.drawText(rect, flags, text)
            p.restore()  # restore the painter state
            offset = math.fabs(x_offset)
            max_width = offset if max_width < offset else max_width

        #  Adjust the height
        if not self._height_updated:
            self.setHeight(self.height() + max_width)
            self._height_updated = True
