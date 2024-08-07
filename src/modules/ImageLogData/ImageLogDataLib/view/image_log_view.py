import slicer

from ImageLogDataLib.viewwidgets.graphic_view_widget import GraphicViewWidget
from ImageLogDataLib.viewwidgets.histogram_in_depth_view_widget import HistogramInDepthViewWidget
from ImageLogDataLib.viewwidgets.slice_view_widget import SliceViewWidget
from ImageLogDataLib.viewwidgets.porosity_per_realization_widget import PorosityPerRealizationViewWidget
from ImageLogDataLib.viewdata.ViewData import EmptyViewData
from ImageLogDataLib.viewdata.ViewData import GraphicViewData
from ImageLogDataLib.viewdata.ViewData import SliceViewData
from ltrace.slicer.node_attributes import TableType
from ltrace.slicer_utils import tableNodeToDict
from ltrace.utils.CorrelatedLabelMapVolume import ProportionLabelMapVolume
from ltrace.slicer.helpers import triggerNodeModified
import vtk


class ProportionNodesLoader:
    def __init__(self):
        self.proportionsNodesIds = {}

    def getProportionsLabelMapNode(self, segmentationNode):
        if segmentationNode is None:
            return None
        # Try to get from the dictionary
        proportionsNode = self.getNodeById(self.proportionsNodesIds.get(segmentationNode.GetID(), None))
        # Build a new node if it is not found
        if proportionsNode is None:
            proportionLabelMapVolumeName = segmentationNode.GetName() + "_Proportions"
            plmv = ProportionLabelMapVolume(segmentationNode, proportionLabelMapVolumeName)
            proportionsNode = plmv.labelMapVolumeNode
            if proportionsNode is not None:
                proportionsNode.HideFromEditorsOn()
                proportionsNode.SetAttribute("ShowInFilteredNodeComboBox", "False")
                triggerNodeModified(proportionsNode)  # Trigger node modification to apply the hide from editors
                subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
                itemParent = subjectHierarchyNode.GetItemParent(
                    subjectHierarchyNode.GetItemByDataNode(segmentationNode)
                )
                subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(proportionsNode), itemParent)
                self.proportionsNodesIds[segmentationNode.GetID()] = proportionsNode.GetID()
        return proportionsNode

    def getNodeById(self, nodeId):
        if nodeId is not None:
            return slicer.mrmlScene.GetNodeByID(nodeId)
        return None


class ImageLogView:
    PROPORTION_NODES_LOADER = ProportionNodesLoader()

    TABLE_TYPE_IMAGE_LOG = 0
    TABLE_TYPE_HISTOGRAM_IN_DEPTH = 1
    TABLE_TYPE_POROSITY_PER_REALIZATION = 2

    def __init__(self, primaryNode, segmentation_node=None):
        self.primaryNode = primaryNode
        self.segmentation_node = segmentation_node
        self.widget = None
        """ if viewData:
            self.viewData = viewData """

        self.viewData, self.table_type = self.__add_node(self.primaryNode, self.segmentation_node)

    def setup_widget(self, parent):
        if isinstance(self.viewData, SliceViewData):
            self.widget = SliceViewWidget(parent, self.viewData, self.primaryNode)
            self.primary_table_dict = None
        elif isinstance(self.viewData, GraphicViewData):
            if self.table_type == self.TABLE_TYPE_IMAGE_LOG:
                self.widget = GraphicViewWidget(parent, self.viewData, self.primaryNode)
                self.primary_table_dict = tableNodeToDict(self.primaryNode)
            elif self.table_type == self.TABLE_TYPE_HISTOGRAM_IN_DEPTH:
                self.widget = HistogramInDepthViewWidget(parent, self.viewData, self.primaryNode)
                self.primary_table_dict = None
            elif self.table_type == self.TABLE_TYPE_POROSITY_PER_REALIZATION:
                self.widget = PorosityPerRealizationViewWidget(parent, self.viewData, self.primaryNode)
                self.primary_table_dict = None

    def set_new_segmentation_node(self, segmentationNode):
        if segmentationNode is not None:
            self.viewData.segmentationNodeId = segmentationNode.GetID()
            if type(segmentationNode) is slicer.vtkMRMLSegmentationNode:
                if segmentationNode.GetSegmentation().GetNumberOfSegments() <= 10:
                    proportionNode = self.PROPORTION_NODES_LOADER.getProportionsLabelMapNode(segmentationNode)
                    self.viewData.proportionsNodeId = proportionNode.GetID() if proportionNode is not None else None
            elif type(segmentationNode) is slicer.vtkMRMLLabelMapVolumeNode:
                if segmentationNode.GetImageData().GetScalarRange()[1] <= 10:
                    proportionNode = self.PROPORTION_NODES_LOADER.getProportionsLabelMapNode(segmentationNode)
                    self.viewData.proportionsNodeId = proportionNode.GetID() if proportionNode is not None else None
        else:
            self.viewData.segmentationNodeId = None
            self.viewData.proportionsNodeId = None

    def set_new_secondary_node(self, node):
        if node is not None:
            self.viewData.secondaryTableNodeId = node.GetID()
            table_type = self.__get_table_type(node)
            if table_type == self.TABLE_TYPE_IMAGE_LOG:
                columns = self.__getParametersForGraphicViewData(node)
            elif table_type == self.TABLE_TYPE_HISTOGRAM_IN_DEPTH:
                columns = self.__getParametersHistogramInDepth(node)
                self.viewData.secondaryTableHistogram = True
            self.viewData.secondaryTableNodeColumn = columns[0]
            self.viewData.secondaryTableNodeColumnList = columns
        else:
            self.viewData.secondaryTableNodeId = None
            self.viewData.secondaryTableNodeColumn = ""

    def __add_node(self, node, segmentation):
        if segmentation is None:
            return self.__new_view_data_for_node(node)
        else:
            return self.__new_view_data_for_node_and_segment(node, segmentation)

    def __new_view_data_for_node(self, node):
        if (
            type(node) is slicer.vtkMRMLScalarVolumeNode
            or type(node) is slicer.vtkMRMLLabelMapVolumeNode
            or type(node) is slicer.vtkMRMLVectorVolumeNode
        ):
            sliceViewData = SliceViewData()
            sliceViewData.primaryNodeId = node.GetID()
            return sliceViewData, None
        elif type(node) is slicer.vtkMRMLTableNode:
            table_type = self.__get_table_type(node)
            graphicViewData = GraphicViewData()
            graphicViewData.primaryNodeId = node.GetID()
            if table_type == self.TABLE_TYPE_IMAGE_LOG:
                columns = self.__getParametersForGraphicViewData(node)
                graphicViewData.primaryTableNodeColumn = columns[0]
                graphicViewData.primaryTableNodeColumnList = columns
                return graphicViewData, table_type
            elif table_type == self.TABLE_TYPE_HISTOGRAM_IN_DEPTH:
                columns = self.__getParametersHistogramInDepth(node)
                graphicViewData.primaryTableNodeColumn = columns[0]
                graphicViewData.primaryTableNodeColumnList = columns
                graphicViewData.primaryTableHistogram = True
                graphicViewData.primaryTableScaleHistogram = 1.0
                return graphicViewData, table_type
            elif table_type == self.TABLE_TYPE_POROSITY_PER_REALIZATION:
                columns = self.__getParametersForGraphicViewData(node)
                graphicViewData.primaryTableNodeColumn = columns[-1]
                graphicViewData.primaryTableNodeColumnList = columns
                return graphicViewData, table_type

        return EmptyViewData(), None

    def __new_view_data_for_node_and_segment(self, sourceVolumeNode, segmentationNode):
        sliceViewData = SliceViewData()
        sliceViewData.primaryNodeId = sourceVolumeNode.GetID()
        sliceViewData.segmentationNodeId = segmentationNode.GetID()
        proportionNode = self.PROPORTION_NODES_LOADER.getProportionsLabelMapNode(segmentationNode)
        sliceViewData.proportionsNodeId = proportionNode.GetID() if proportionNode is not None else None
        return sliceViewData, None

    def __getParametersForGraphicViewData(self, node):
        if node is None:
            return [""]

        parameters = [node.GetColumnName(index) for index in range(node.GetNumberOfColumns())]
        if "DEPTH" in parameters:
            parameters.remove("DEPTH")

        return parameters

    def __getParametersHistogramInDepth(self, node):
        if node is None:
            return [""]
        samples = 10
        parameters = [str(index) for index in range(1, samples + 1)]

        return parameters

    def __get_table_type(self, table_node):
        table_type_attribute = table_node.GetAttribute(TableType.name())
        if table_type_attribute == TableType.IMAGE_LOG.value:
            return self.TABLE_TYPE_IMAGE_LOG
        elif table_type_attribute == TableType.HISTOGRAM_IN_DEPTH.value:
            return self.TABLE_TYPE_HISTOGRAM_IN_DEPTH
        elif table_type_attribute == TableType.POROSITY_PER_REALIZATION.value:
            return self.TABLE_TYPE_POROSITY_PER_REALIZATION

        if table_node.GetColumnName(0) == "DEPTH":
            return self.TABLE_TYPE_IMAGE_LOG
        elif table_node.GetTable().GetRow(0).GetValue(0) == "X":
            return self.TABLE_TYPE_HISTOGRAM_IN_DEPTH

        return self.TABLE_TYPE_IMAGE_LOG
