from ltrace.slicer.node_observer import NodeObserver
from ltrace.slicer import helpers
from ltrace.slicer.tracking.tracker import Tracker

import vtk
import slicer
from typing import Dict


class VolumeNodeTracker(Tracker):
    def __init__(self) -> None:
        super().__init__()
        self.__node_observers = []

    def __getNodeData(self, node: slicer.vtkMRMLNode) -> dict:
        if node is None:
            return {}

        return {
            "name": node.GetName(),
            "id": node.GetID(),
            "type": node.GetClassName(),
            "shape": node.GetImageData().GetDimensions() if node.GetImageData() is not None else None,
            "spacing": node.GetImageData().GetSpacing() if node.GetImageData() is not None else None,
            "origin": node.GetImageData().GetOrigin() if node.GetImageData() is not None else None,
            "data_type": helpers.getScalarTypesAsString(node.GetImageData().GetScalarType())
            if node.GetImageData() is not None
            else None,
        }

    def __onNodeModified(self, node_observer: NodeObserver, node: slicer.vtkMRMLNode):
        self.log(f"Volume node modified: {self.__getNodeData(node)}")

    def __onNodeRemoved(self, node_observer: NodeObserver, node: slicer.vtkMRMLNode):
        if node_observer not in self.__node_observers:
            return

        self.__node_observers.remove(node_observer)
        self.log(f"Volume node removed: {self.__getNodeData(node)}")

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def __on_node_added(self, caller, eventId, node):
        if (
            isinstance(node, slicer.vtkMRMLLabelMapVolumeNode)
            or isinstance(node, slicer.vtkMRMLScalarVolumeNode)
            or isinstance(node, slicer.vtkMRMLVectorVolumeNode)
        ):
            observer = NodeObserver(node=node, parent=slicer.util.mainWindow())
            observer.modifiedSignal.connect(self.__onNodeModified)
            observer.removedSignal.connect(self.__onNodeRemoved)

            self.__node_observers.append(observer)

            self.log(f"Volume node added: {self.__getNodeData(node)}")

    def install(self) -> None:
        self.nodeAddedObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.NodeAddedEvent, self.__on_node_added
        )

    def uninstall(self) -> None:
        if not self.nodeAddedObserverHandler:
            return

        self.nodeAddedObserverHandler = slicer.mrmlScene.RemoveObserver(self.nodeAddedObserverHandler)
        for node_observer in self.__node_observers[:]:
            node_observer.clear()
            self.__node_observers.remove(node_observer)

        self.__node_observers.clear()
