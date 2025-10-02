import qt
import slicer
import vtk
import logging
import traceback
from ltrace.slicer import helpers
from ltrace.slicer.debounce_caller import DebounceCaller


class NodeObserver(qt.QObject):
    """Class responsible to emit signals (Qt.Signal) from events related to the related node."""

    modifiedSignal = qt.Signal(object, object)
    removedSignal = qt.Signal(object, object)

    def __init__(self, node: slicer.vtkMRMLNode, parent=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        if node is None:
            raise ValueError("Invalid node reference to observe.")

        self.__nodeId = node.GetID()
        self.__observerHandlers = list()
        self.__observerHandlers.append(
            (
                node,
                node.AddObserver("ModifiedEvent", self.__on_node_modified),
            )
        )
        self.__observerHandlers.append(
            (
                slicer.mrmlScene,
                slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeRemovedEvent, self.__on_node_removed),
            )
        )
        if node.IsA("vtkMRMLSegmentationNode"):
            for eventType in (
                slicer.vtkSegmentation.RepresentationModified,
                slicer.vtkSegmentation.SegmentModified,
            ):
                self.__observerHandlers.append(
                    (
                        node,
                        node.AddObserver(eventType, self.__on_node_modified),
                    )
                )
        self.__signalModifiedDebouncer = DebounceCaller(
            parent=self, callback=self.onModifiedSignalToBeTriggered, intervalMs=100
        )
        self.destroyed.connect(self.__del__)

    def __del__(self):
        self.clear()

    @property
    def node(self):
        return helpers.tryGetNode(self.__nodeId)

    def __on_node_modified(self, caller, event):
        """Handles node's modification."""
        self.__signalModifiedDebouncer.emit(self, caller)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def __on_node_removed(self, caller, event, node):
        """Handles node's removal."""
        if node is None or node.GetID() != self.__nodeId:
            return
        try:
            self.removedSignal.emit(self, node)
            self.clear()
        except Exception as error:
            logging.debug(
                f"Bypassing error from node observer related to node {node.GetName()} ({node.GetID()}): {error}. Traceback:\n{traceback.format_exc()}"
            )

    def clear(self):
        """Clears current object's data."""
        try:
            self.children()
            self.modifiedSignal.disconnect()
            self.removedSignal.disconnect()
        except ValueError:
            # Object has been deleted
            pass

        for obj, tag in self.__observerHandlers:
            obj.RemoveObserver(tag)

        self.__observerHandlers.clear()
        self.__nodeId = None

    def onModifiedSignalToBeTriggered(self, *args, **kwargs):
        # TODO this code does not look right
        if len(args) + len(kwargs) == 0:
            self.modifiedSignal.emit(None, None)

        self.modifiedSignal.emit(*args, **kwargs)
