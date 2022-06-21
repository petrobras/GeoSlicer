import json
import logging
from collections import namedtuple

import ctk
import numpy as np
import pandas as pd
import qt
import slicer
import traceback

from ImageLogInstanceSegmenter import ImageLogInstanceSegmenter
from ltrace.algorithms.measurements import instancesPropertiesDataFrame
from ltrace.slicer.helpers import (
    makeNodeTemporary,
    triggerNodeModified,
    highlight_error,
    labels_to_color_node,
    reset_style_on_valid_text,
    tryGetNode,
)
from ltrace.slicer.node_attributes import ImageLogDataSelectable, NodeTemporarity
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widgets import PixelLabel, SingleShotInputWidget
from ltrace.slicer_utils import dataFrameToTableNode

CLONED_COLUMNS = 40


class IslandsWidget(qt.QWidget):
    SegmentParameters = namedtuple(
        "SegmentParameters",
        [
            "model",
            "segmentationNode",
            "sizeMinThreshold",
            "outputPrefix",
        ],
    )

    def __init__(self, instanceSegmenterClass, instanceSegmenterWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instanceSegmenterClass = instanceSegmenterClass
        self.instanceSegmenterWidget = instanceSegmenterWidget
        self.setup()

    def getSizeMinThreshold(self):
        return ImageLogInstanceSegmenter.get_setting("sizeMinThreshold", default=0.0)

    def setup(self):
        self.progressBar = LocalProgressBar()
        self.logic = IslandsLogic(self.progressBar)

        formLayout = qt.QFormLayout(self)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        # Input section
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        formLayout.addRow(inputCollapsibleButton)

        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        SingleShotInputWidget
        self.segmentationNodeComboBox = SingleShotInputWidget(
            hideImage=True,
            hideSoi=True,
            hideCalcProp=True,
            mainName="Binary segmentation image",
            objectNamePrefix="Islands",
        )
        self.segmentationNodeComboBox.onMainSelected = self.onSegmentationNodeChanged
        self.segmentationNodeComboBox.setToolTip("Select the binary segmentation image.")
        inputFormLayout.addRow(self.segmentationNodeComboBox)
        inputFormLayout.addRow(" ", None)

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.sizeMinThreshold = qt.QDoubleSpinBox()
        self.sizeMinThreshold.setRange(0, 10)
        self.sizeMinThreshold.setDecimals(1)
        self.sizeMinThreshold.setSingleStep(0.1)
        self.sizeMinThreshold.setValue(float(self.getSizeMinThreshold()))
        self.sizeMinThreshold.setToolTip("Parameter to set the minimum size of a partition.")
        self.sizeMinThreshold.objectName = "Islands Minimum Threshold Size"
        thresholdBoxLayout = qt.QHBoxLayout()
        thresholdBoxLayout.addWidget(self.sizeMinThreshold)
        pixel_label = PixelLabel(value_input=self.sizeMinThreshold, node_input=self.segmentationNodeComboBox)
        pixel_label.setSizePolicy(qt.QSizePolicy.Maximum, qt.QSizePolicy.Fixed)
        thresholdBoxLayout.addWidget(pixel_label)
        parametersFormLayout.addRow("Size minimum threshold (mm):", thresholdBoxLayout)
        parametersFormLayout.addRow(" ", None)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.outputPrefixLineEdit = qt.QLineEdit()
        self.outputPrefixLineEdit.objectName = "Islands Output Prefix Line Edit"
        outputFormLayout.addRow("Output prefix:", self.outputPrefixLineEdit)
        outputFormLayout.addRow(" ", None)
        reset_style_on_valid_text(self.outputPrefixLineEdit)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setObjectName("Islands Apply Button")
        self.applyButton.setFixedHeight(40)
        self.applyButton.clicked.connect(self.onApplyButtonClicked)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.applyButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        formLayout.addRow(buttonsHBoxLayout)

        formLayout.addRow(self.progressBar)

    def onSegmentationNodeChanged(self, node):
        self.outputPrefixLineEdit.text = node.GetName() if node is not None else ""

    def onApplyButtonClicked(self):
        try:
            if self.segmentationNodeComboBox.mainInput.currentNode() is None:
                highlight_error(self.segmentationNodeComboBox)
                return
            if self.outputPrefixLineEdit.text.strip() == "":
                highlight_error(self.outputPrefixLineEdit)
                return

            node = self.segmentationNodeComboBox.mainInput.currentNode()
            is_labelmap = isinstance(node, slicer.vtkMRMLLabelMapVolumeNode)
            if is_labelmap:
                segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
                slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                    node,
                    segmentationNode,
                )
                node = segmentationNode

            segments = [
                node.GetSegmentation().GetNthSegmentID(n) for n in self.segmentationNodeComboBox.getSelectedSegments()
            ]
            labelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                node, segments, labelMapNode, None, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY, None
            )
            if is_labelmap:
                slicer.mrmlScene.RemoveNode(node)
            labelMapNode.SetName("tempLabelMap")
            makeNodeTemporary(labelMapNode, hide=True)
            node = labelMapNode

            self.instanceSegmenterClass.set_setting("model", self.instanceSegmenterWidget.modelComboBox.currentData)
            self.instanceSegmenterClass.set_setting("sizeMinThreshold", self.sizeMinThreshold.value)

            segmentParameters = self.SegmentParameters(
                model=self.instanceSegmenterWidget.modelComboBox.currentData,
                segmentationNode=node,
                sizeMinThreshold=float(self.sizeMinThreshold.value),
                outputPrefix=self.outputPrefixLineEdit.text,
            )
            self.logic.apply(segmentParameters)
        except IslandsInfo as e:
            slicer.util.infoDisplay(str(e))
            if labelMapNode:
                slicer.mrmlScene.RemoveNode(labelMapNode)
            return

    def onCancelButtonClicked(self):
        self.logic.cancel()


class IslandsLogic:
    def __init__(self, progressBar):
        self.cliNode = None
        self.progressBar = progressBar
        self.outputLabelMapNodeId = None
        self.segmentationNodeId = None

    def apply(self, p):
        self.model = p.model
        segmentationNode = p.segmentationNode
        self.segmentationNodeId = segmentationNode.GetID()
        self.sizeMinThreshold = p.sizeMinThreshold
        self.outputPrefix = p.outputPrefix
        shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        self.itemParent = shNode.GetItemParent(shNode.GetItemByDataNode(segmentationNode))

        outputLabelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        outputLabelMapNode.SetName(p.outputPrefix + "_Instances")
        outputLabelMapNode.SetAttribute("InstanceSegmenter", p.model)
        outputLabelMapNode.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
        outputLabelMapNode.HideFromEditorsOn()
        self.outputLabelMapNodeId = outputLabelMapNode.GetID()
        triggerNodeModified(outputLabelMapNode)
        shNode.SetItemParent(shNode.GetItemByDataNode(outputLabelMapNode), self.itemParent)

        params = {
            "method": "islands",
            "size_min_threshold": self.sizeMinThreshold,
            "direction": None,
        }

        self.cloneColumns(segmentationNode)

        cliConf = dict(
            params=json.dumps(params),
            products="partitions",
            labelVolume=self.segmentationNodeId,
            outputVolume=self.outputLabelMapNodeId,
            outputReport=None,
            throatOutputVolume=None,
        )

        self.cliNode = slicer.cli.run(slicer.modules.segmentinspectorcli, None, cliConf, wait_for_completion=False)
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.segmentationCLICallback)

    def cloneColumns(self, node):
        array = slicer.util.arrayFromVolume(node)
        array = np.concatenate((array[:, :, -CLONED_COLUMNS:], array, array, array[:, :, :CLONED_COLUMNS]), axis=2)
        slicer.util.updateVolumeFromArray(node, array)

    def decloneColumns(self, node, link_border_segments=False):
        array = slicer.util.arrayFromVolume(node)
        width = array.shape[2]
        main_slice = array[:, :, CLONED_COLUMNS : int(width / 2)]
        if link_border_segments:
            linking_slice = array[:, :, int(width / 2) : -CLONED_COLUMNS]
            segments_values = np.unique(main_slice[main_slice != 0])
            for value in segments_values:
                main_slice[linking_slice == value] = value
        slicer.util.updateVolumeFromArray(node, main_slice)
        node.Modified()

    def segmentationCLICallback(self, caller, event):
        if caller is None:
            del self.cliNode
            self.cliNode = None
            return
        if self.cliNode is None:
            return
        status = caller.GetStatusString()
        if "Completed" in status or status == "Cancelled":
            logging.info(status)
            del self.cliNode
            self.cliNode = None
            propertiesTableNode = None
            outputLabelMapNode = tryGetNode(self.outputLabelMapNodeId)
            segmentationNode = tryGetNode(self.segmentationNodeId)
            if status == "Completed":
                try:
                    array = slicer.util.arrayFromVolume(outputLabelMapNode)
                    # tripling the number of available colors on the color table, to account for adding/editing extra labels later
                    colorTable = labels_to_color_node(
                        3 * int(np.max(array)), outputLabelMapNode.GetName() + "_color_table"
                    )
                    outputLabelMapNode.GetDisplayNode().SetAndObserveColorNodeID(colorTable.GetID())

                    self.decloneColumns(outputLabelMapNode, link_border_segments=True)
                    self.decloneColumns(segmentationNode)

                    propertiesDataFrame = instancesPropertiesDataFrame(outputLabelMapNode)
                    if len(propertiesDataFrame.index) == 0:
                        slicer.mrmlScene.RemoveNode(outputLabelMapNode)
                        self.outputLabelMapNodeId = None
                        slicer.util.infoDisplay("No instances were detected.")
                        return

                    outputLabelMapNode.HideFromEditorsOff()
                    triggerNodeModified(outputLabelMapNode)

                    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
                    propertiesTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
                    propertiesTableNode.SetName(self.outputPrefix + "_Instances_Report")
                    propertiesTableNode.SetAttribute("InstanceSegmenter", self.model)
                    propertiesTableNode.AddNodeReferenceID("InstanceSegmenterLabelMap", outputLabelMapNode.GetID())
                    shNode.SetItemParent(shNode.GetItemByDataNode(propertiesTableNode), self.itemParent)
                    dataFrameToTableNode(propertiesDataFrame, tableNode=propertiesTableNode)
                except Exception as err:
                    logging.info(f"{err}\n{traceback.print_exc()}")
                    if outputLabelMapNode:
                        slicer.mrmlScene.RemoveNode(outputLabelMapNode)
                    if propertiesTableNode:
                        slicer.mrmlScene.RemoveNode(propertiesTableNode)
                    slicer.util.errorDisplay(
                        "A problem has occurred during the segmentation. Please check your input files."
                    )
                    self.outputLabelMapNodeId = None

            elif status == "Cancelled":
                if outputLabelMapNode:
                    slicer.mrmlScene.RemoveNode(outputLabelMapNode)
                if propertiesTableNode:
                    slicer.mrmlScene.RemoveNode(propertiesTableNode)
                self.outputLabelMapNodeId = None
            else:
                if outputLabelMapNode:
                    slicer.mrmlScene.RemoveNode(outputLabelMapNode)
                if propertiesTableNode:
                    slicer.mrmlScene.RemoveNode(propertiesTableNode)
                self.outputLabelMapNodeId = None

            if segmentationNode and segmentationNode.GetAttribute(NodeTemporarity.name()) == NodeTemporarity.TRUE.value:
                slicer.mrmlScene.RemoveNode(segmentationNode)
                self.segmentationNodeId = None

    def cancel(self):
        if self.cliNode is None:
            return
        self.cliNode.Cancel()


class IslandsInfo(RuntimeError):
    pass
