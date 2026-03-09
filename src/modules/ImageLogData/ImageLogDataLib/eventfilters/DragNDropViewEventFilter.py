import qt
import re


class DragNDropViewEventFilter(qt.QObject):
    def __init__(self, logic):
        self.dataLogic = logic
        super().__init__(logic)

    def eventFilter(self, obj, event):
        posMouse = qt.QCursor().pos()

        if event.type() == qt.QEvent.DragEnter:
            if event.mimeData().hasText():
                self.dataLogic.dragViewManager.dragging = True
                event.acceptProposedAction()
                return False

        elif event.type() == qt.QEvent.DragMove:
            self.dataLogic.dragViewManager.moveLogViewScreenshot(posMouse)
            event.acceptProposedAction()
            return True

        elif event.type() == qt.QEvent.Drop:

            dragViewManager = self.dataLogic.dragViewManager
            match = re.search(rf"{dragViewManager.dragMimeTextPrefix}(\d+)$", event.mimeData().text())

            qt.QApplication.restoreOverrideCursor()

            if not match:
                return False
            if int(match.group(1)) != dragViewManager.viewsIdentifiersFromTo[0]:
                return False

            if dragViewManager.dragging == True:
                dragViewManager.dragging = False

            globalPos = obj.mapToGlobal(event.pos())

            dragViewManager.updateViewsIdentifiersFromTo1(globalPos)

            view_from = dragViewManager.viewsIdentifiersFromTo[0]
            view_to = dragViewManager.viewsIdentifiersFromTo[1]

            if dragViewManager.viewsIdentifiersFromTo[1] >= 0:
                if view_to >= 0 and view_to != view_from:
                    self.dataLogic.reorderLayout(view_from, view_to)
                    self.dataLogic.refreshViews("loadViewFromList")
            dragViewManager.logViewScreenshot.hide()
            return True

        return False
