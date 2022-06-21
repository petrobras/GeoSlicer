import slicer
import qt
from itertools import chain as iter_chain


class SubjectHierarchyTreeViewFilter(qt.QObject):
    """Event filter handler to catch ChildRemoved events to detect a drag and drop action from the subject hierarchy tree to the view area"""

    def __init__(self, dataWidget, parent=None):
        super().__init__(parent)
        self.dataWidget = dataWidget

    def anyUnderMouse(self, widgetGeometries):
        posMouse = qt.QGraphicsView().mapFromGlobal(qt.QCursor().pos())
        for rect in widgetGeometries:
            if rect.contains(posMouse):
                return True
        return False

    def viewPortRectWithOffset(self):
        mw = slicer.util.mainWindow()
        vp = self.dataWidget.logic.layoutManagerViewPort
        d = mw.findChild(qt.QDockWidget, "PanelDockWidget")
        if d.isVisible() and not d.isFloating():
            topLeftAdjusted = mw.geometry.topLeft() + d.geometry.topRight() + vp.geometry.topLeft()
            bottomRightAdjusted = mw.geometry.topLeft() + d.geometry.topRight() + vp.geometry.bottomRight()
            rect = qt.QRect(topLeftAdjusted, bottomRightAdjusted)
        else:
            topLeftAdjusted = mw.geometry.topLeft() + vp.geometry.topLeft()
            bottomRightAdjusted = mw.geometry.topLeft() + vp.geometry.bottomRight()
            rect = qt.QRect(topLeftAdjusted, bottomRightAdjusted)

        return rect

    def widgetRectsWithOffset(self):
        rects = []
        mw = slicer.util.mainWindow()
        d = mw.findChild(qt.QDockWidget, "PanelDockWidget")
        for w in self.dataWidget.logic.viewWidgets:
            if d.isVisible() and not d.isFloating():
                topLeftAdjusted = mw.geometry.topLeft() + d.geometry.topRight() + w.geometry.topLeft()
                bottomRightAdjusted = mw.geometry.topLeft() + d.geometry.topRight() + w.geometry.bottomRight()
                rect = qt.QRect(topLeftAdjusted, bottomRightAdjusted)
            else:
                topLeftAdjusted = mw.geometry.topLeft() + w.geometry.topLeft()
                bottomRightAdjusted = mw.geometry.topLeft() + w.geometry.bottomRight()
                rect = qt.QRect(topLeftAdjusted, bottomRightAdjusted)
            rects.append(rect)
        return rects

    def eventFilter(self, widget, event):
        if event.type() == qt.QEvent.ChildRemoved:
            # Checks if it's the correct node type
            selectedNodeIdInTree = self.dataWidget.subjectHierarchyTreeView.currentItem()
            subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

            selectedNode = subjectHierarchyNode.GetItemDataNode(selectedNodeIdInTree)
            isVolumeNode = isinstance(selectedNode, slicer.vtkMRMLVolumeNode)
            isSegmentationNode = isinstance(selectedNode, slicer.vtkMRMLSegmentationNode)
            isTableNode = isinstance(selectedNode, slicer.vtkMRMLTableNode)
            if not (isVolumeNode or isSegmentationNode or isTableNode):
                return

            # Checks if it's under the view area
            widgets = iter_chain(
                (self.viewPortRectWithOffset(),),  # central widget - will capture almost all cases
                # [w.geometry for w in self.dataWidget.logic.containerWidgets.values()],  # removed because it enabled dropping over the left panel
                self.widgetRectsWithOffset(),  # capture when a view is open - fallback case
            )

            if self.anyUnderMouse(widgets):
                self.dataWidget.addView()
