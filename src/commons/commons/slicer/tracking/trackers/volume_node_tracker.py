from commons.slicer.node_observer import NodeObserver
from commons.slicer import helpers
from commons.slicer.tracking.tracker import Tracker

import vtk
import slicer


class VolumeNodeTracker(Tracker):
    def __init__(self) -> None:
        super().__init__()
        self.__nodeObservers = []
        self.__nodeAddedObserverHandler = None

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
            "data_type": (
                helpers.getScalarTypesAsString(node.GetImageData().GetScalarType())
                if node.GetImageData() is not None
                else None
            ),
        }

    def __onNodeModified(self, nodeObserver: NodeObserver, node: slicer.vtkMRMLNode):
        self.log(f"Volume node modified: {self.__getNodeData(node)}")

    def __onNodeRemoved(self, nodeObserver: NodeObserver, node: slicer.vtkMRMLNode):
        if nodeObserver not in self.__nodeObservers:
            return

        self.__nodeObservers.remove(nodeObserver)
        nodeObserver.deleteLater()
        self.log(f"Volume node removed: {self.__getNodeData(node)}")

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def __onNodeAdded(self, caller, eventId, node):
        if (
            isinstance(node, slicer.vtkMRMLLabelMapVolumeNode)
            or isinstance(node, slicer.vtkMRMLScalarVolumeNode)
            or isinstance(node, slicer.vtkMRMLVectorVolumeNode)
        ):
            observer = NodeObserver(node=node, parent=slicer.modules.AppContextInstance.mainWindow)
            observer.modifiedSignal.connect(self.__onNodeModified)
            observer.removedSignal.connect(self.__onNodeRemoved)

            self.__nodeObservers.append(observer)

            self.log(f"Volume node added: {self.__getNodeData(node)}")

    def install(self) -> None:
        self.__nodeAddedObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.NodeAddedEvent, self.__onNodeAdded
        )

    def uninstall(self) -> None:
        if not self.__nodeAddedObserverHandler:
            return

        self.__nodeAddedObserverHandler = slicer.mrmlScene.RemoveObserver(self.__nodeAddedObserverHandler)
        for nodeObserver in self.__nodeObservers[:]:
            self.__nodeObservers.remove(nodeObserver)
            nodeObserver.deleteLater()

        self.__nodeObservers.clear()
