import qt
import logging

from .viewdata.ViewData import SliceViewData, GraphicViewData


class MouseEventFilter(qt.QObject):
    def __init__(self, logic):
        self.dataLogic = logic
        super().__init__(logic)

    def getGeometry(self, viewWidget):
        if self.dataLogic is None or not hasattr(self.dataLogic, "axisItem"):
            return qt.QRect(0, 0, 0, 0)

        logGeometry = viewWidget.geometry

        oldWidth = logGeometry.width()
        oldHeight = logGeometry.height()
        axisGeometry = self.dataLogic.axisItem.geometry()

        logGeometryXY = viewWidget.mapToGlobal(qt.QPoint(0, axisGeometry.y()))

        logGeometry = qt.QRect(logGeometryXY.x(), logGeometryXY.y(), oldWidth, oldHeight)

        return logGeometry

    def getCursorPhysicalPosition(self, viewWidget, imageLogView, x, y):
        width = viewWidget.geometry.width()

        if imageLogView.widget == None:
            # This avoids raising unnecessary errors,
            # but might also avoid unknown necessary ones, too
            return -1, -1

        xDepth = imageLogView.widget.getGraphX(x, width)

        axisItem = self.dataLogic.axisItem
        height = axisItem.geometry().height()

        vDif = axisItem.range[0] - axisItem.range[1]
        if vDif == 0:
            yScale = 1
            yOffset = 0
        else:
            yScale = height / vDif
            yOffset = axisItem.range[1] * yScale

        yDepth = (y + yOffset) / yScale

        return xDepth, yDepth

    def getValue(self, imageLogView, x, y):
        value = None
        if imageLogView.widget:
            value = imageLogView.widget.getValue(x, y)
        return value

    def writeCoordinates(self, identifier, x, y, value):
        text = f"View #{identifier} ({x:.2f}, {y:.2f})"
        text = text + f" {value:.2f}" if isinstance(value, float) else text + f" {value}"
        toolBarWidget = self.dataLogic.containerWidgets["toolBarWidget"]
        mousePhysicalCoordinates = toolBarWidget.findChild(qt.QLabel, "MousePhysicalCoordinates")
        mousePhysicalCoordinates.setText(text)

    def eventFilter(self, widget, event):
        if not (isinstance(event, qt.QHoverEvent) or isinstance(event, qt.QWheelEvent)):
            return
        for identifier in self.dataLogic.getViewDataListIdentifiers():
            imageLogView = self.dataLogic.imageLogViewList[identifier]
            if imageLogView is None:
                continue

            try:
                viewWidget = self.dataLogic.viewWidgets[identifier]
            except IndexError as error:
                logging.debug(error)
                continue

            if viewWidget is None:
                continue

            viewData = imageLogView.viewData
            if viewData.primaryNodeId == None:
                continue
            if (
                type(viewData) is SliceViewData
                or type(viewData) is GraphicViewData
                and (viewData.primaryTableNodeColumn != "" or viewData.secondaryTableNodeColumn != "")
            ):
                posMouse = qt.QCursor().pos()
                logGeometry = self.getGeometry(viewWidget)
                if not logGeometry.contains(posMouse):
                    continue
                relativePosMouseY = posMouse.y() - logGeometry.y()
                relativePosMouseX = posMouse.x() - logGeometry.x()
                physicalPos = self.getCursorPhysicalPosition(
                    viewWidget, imageLogView, relativePosMouseX, relativePosMouseY
                )
                value = self.getValue(imageLogView, *physicalPos)
                self.writeCoordinates(identifier, *physicalPos, value)
                break
