import numpy as np
import qt
import re
import slicer

from .base_view_widget import BaseViewWidget


class SliceViewWidget(BaseViewWidget):
    def __init__(self, viewWidget, viewData, primaryNode):
        super().__init__()

        self.viewWidget = viewWidget
        self.primaryNode = primaryNode

        sliceCompositeNode = self.viewWidget.sliceLogic().GetSliceCompositeNode()
        sliceCompositeNode.SetBackgroundVolumeID(primaryNode.GetID())
        sliceCompositeNode.SetBackgroundOpacity(not viewData.primaryNodeHidden)
        if viewData.primaryNodeHidden is False:
            self.viewWidget.sliceController().fitSliceToBackground()
            if (
                type(primaryNode) is slicer.vtkMRMLScalarVolumeNode
                and primaryNode.GetAttribute("ColorTableNodeConfigured") != "True"
            ):
                colorNode = slicer.util.getFirstNodeByName("AFMHot")
                primaryNode.GetDisplayNode().SetAndObserveColorNodeID(colorNode.GetID())
                primaryNode.SetAttribute("ColorTableNodeConfigured", "True")

        sliceCompositeNode.SetLabelVolumeID(None)

        segmentationNode = self.__get_node_by_id(viewData.segmentationNodeId)
        if (
            segmentationNode is not None
            and viewData.segmentationNodeHidden == False
            and type(segmentationNode) is slicer.vtkMRMLLabelMapVolumeNode
        ):
            sliceCompositeNode.SetLabelVolumeID(viewData.segmentationNodeId)

        proportionsNodeId = viewData.proportionsNodeId
        if proportionsNodeId is not None and viewData.proportionsNodeHidden is False:
            sliceCompositeNode.SetLabelVolumeID(proportionsNodeId)

    def set_range(self, current_range):
        bounds = np.zeros(6)
        self.primaryNode.GetBounds(bounds)
        volumeMidpoint = (bounds[4] + bounds[5]) / 2
        rangeMidpoint = (current_range[0] + current_range[1]) / 2
        fieldOfView = [abs(bounds[0] - bounds[1]), current_range[0] - current_range[1], 1]
        origin = [0, -1 * (rangeMidpoint + volumeMidpoint), 0]
        sliceNode = self.viewWidget.sliceLogic().GetSliceNode()
        sliceNode.SetFieldOfView(*fieldOfView)
        sliceNode.SetSliceOrigin(*origin)

    def getGraphX(self, view_x, width):
        origin = self.primaryNode.GetOrigin()
        circumference = origin[0] * 2

        if circumference == 0:
            xScale = 1
        else:
            xScale = width / circumference

        xDepth = view_x / xScale
        return xDepth

    def getBounds(self):
        bounds = np.zeros(6)
        self.primaryNode.GetBounds(bounds)
        return bounds[4], bounds[5]

    def getValue(self, x, y):
        value = None

        # Gets the last piece of the B string on the Data Probe and
        # takes the first number from it, which should be the only one
        infoWidget = slicer.modules.DataProbeInstance.infoWidget
        valueStr = infoWidget.layerValues["B"].text
        if valueStr:
            valueStr.split()[-1]
            values = re.findall(r"[-+]?(?:\d*\.\d+|\d+)", valueStr)
            if len(values):
                value = float(values[0])
        return value

    def __get_node_by_id(self, nodeId):
        if nodeId is not None:
            return slicer.mrmlScene.GetNodeByID(nodeId)
        return None
