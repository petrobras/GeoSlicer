import qt
import slicer
import logging
from ImageLogDataLib.viewdata.ViewData import SliceViewData, GraphicViewData, EmptyViewData


class IdentifyViewMouseEventFilter(qt.QObject):
    def __init__(self, logic):
        self.dataLogic = logic
        self.dragViewManager = None
        super().__init__(logic)

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

    # When user dragged a view, stayed with the mouse over the label of a view (HoverEnter event in its label),
    # and moved the mouse to a log while the reordering was taking place. This made the HoverLeave of the label
    # not being called.
    def preventMouseCursorShapeStuck(self, event):
        if not self.dragViewManager.dragging and self.dataLogic.overElidedLabel(qt.QCursor().pos()) == -1:
            qt.QApplication.restoreOverrideCursor()

    def eventFilter(self, widget, event):
        posMouse = qt.QCursor().pos()

        self.dragViewManager = self.dataLogic.dragViewManager

        if not (
            isinstance(event, qt.QHoverEvent)
            or isinstance(event, qt.QWheelEvent)
            or isinstance(event, qt.QMouseEvent)
            or isinstance(event, qt.QDragMoveEvent)
        ):
            return

        # Showing information of the view at mouse position
        identifier = self.dataLogic.getIdentifierAt(event.pos().x(), event.pos().y())
        if identifier >= 0:
            self.preventMouseCursorShapeStuck(event)

            imageLogView = self.dataLogic.imageLogViewList[identifier]

            try:
                viewWidget = self.dataLogic.viewWidgets[identifier]
            except IndexError as error:
                logging.debug(error)
                return False

            viewData = imageLogView.viewData
            if (
                type(viewData) is SliceViewData
                or type(viewData) is GraphicViewData
                and (viewData.primaryTableNodeColumn != "" or viewData.secondaryTableNodeColumn != "")
            ):
                if viewData.primaryNodeId == None:
                    return False

                logGeometry = slicer.util.getModuleWidget("ImageLogData").getGeometry(viewWidget)

                relativePosMouseY = posMouse.y() - logGeometry.y()
                relativePosMouseX = posMouse.x() - logGeometry.x()
                physicalPos = self.getCursorPhysicalPosition(
                    viewWidget, imageLogView, relativePosMouseX, relativePosMouseY
                )
                value = self.getValue(imageLogView, *physicalPos)
                self.writeCoordinates(identifier, *physicalPos, value)
        return False
