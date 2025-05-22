import slicer
import qt

from ltrace.slicer.node_custom_behavior.node_custom_behavior_base import (
    NodeCustomBehaviorBase,
    CustomBehaviorRequirements,
)
from ltrace.slicer.node_custom_behavior.defs import TriggerEvent
from ltrace.slicer.helpers import bounds2size


class VolumeNodeCustomBehavior(NodeCustomBehaviorBase):
    """Custom behavior for volumes vtkMRMLVolumeNode"""

    REQUIREMENTS = CustomBehaviorRequirements(nodeTypes=[slicer.vtkMRMLVolumeNode], attributes={})

    def __init__(self, node: slicer.vtkMRMLNode, event: TriggerEvent) -> None:
        super().__init__(node=node, event=event)

    def _onNodeAdded(self, node: slicer.vtkMRMLNode) -> None:
        node.AddObserver("ModifiedEvent", self.__onNodeModified)

    def _onNodeRemoved(self, node: slicer.vtkMRMLNode) -> None:
        node.RemoveAllObservers()

    def __onNodeModified(self, node: slicer.vtkMRMLNode, event) -> None:
        if node is None:
            return

        timer = qt.QTimer()

        def onTimeout():
            self._onVolumeModified(node)
            timer.timeout.disconnect(onTimeout)

        timer.setSingleShot(True)
        timer.timeout.connect(onTimeout)
        timer.start(0)

    def _showSlicesIn3D(self) -> None:
        if slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLScalarVolumeNode") == 0:
            return

        layoutManager = slicer.app.layoutManager()
        for sliceViewName in layoutManager.sliceViewNames():
            controller = layoutManager.sliceWidget(sliceViewName).sliceController()
            controller.setSliceVisible(True)

    def _frameVolume(self, volume) -> None:
        """Reposition camera so it points to the center of the volume and
        position it so the volume is reasonably visible.
        """
        bounds = [0] * 6
        volume.GetBounds(bounds)
        size = bounds2size(bounds)
        leastCorner = tuple(min(bounds[i * 2], bounds[i * 2 + 1]) for i in range(3))
        center = tuple(leastCorner[i] + size[i] / 2 for i in range(3))
        diagonalSize = sum((side**2 for side in size)) ** 0.5

        camNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLCameraNode")
        cam = camNode.GetCamera()
        cam.SetFocalPoint(center)
        pos = tuple(coord + diagonalSize for coord in center)
        cam.SetPosition(pos)
        camNode.ResetClippingRange()

    def _onVolumeModified(self, volume: slicer.vtkMRMLNode) -> None:
        if volume is None:
            return

        autoFrameOff = volume.GetAttribute("AutoFrameOff")
        autoSliceVisibleOff = volume.GetAttribute("AutoSliceVisibleOff")
        if volume.GetImageData():
            if (
                not slicer.modules.AppContextInstance.slicesShown
                and not slicer.mrmlScene.GetURL()
                and autoSliceVisibleOff != "true"
            ):
                # Open slice eyes once for a new project
                self._showSlicesIn3D()
                slicer.modules.AppContextInstance.slicesShown = True
            if autoFrameOff != "true":
                self._frameVolume(volume)
