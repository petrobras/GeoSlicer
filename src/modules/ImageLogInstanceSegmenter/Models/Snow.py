import json
import logging
from collections import namedtuple

import ctk
import numpy as np
import pandas as pd
import qt
import slicer
import traceback

from ltrace.algorithms.measurements import instancesPropertiesDataFrame, GENERIC_PROPERTIES
from ltrace.slicer.helpers import (
    makeNodeTemporary,
    triggerNodeModified,
    highlight_error,
    remove_highlight,
    labels_to_color_node,
    reset_style_on_valid_text,
    themeIsDark,
)
from ltrace.slicer.node_attributes import ImageLogDataSelectable, NodeTemporarity
from ltrace.slicer.ui import fixedRangeNumberParam
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widgets import PixelLabel, SingleShotInputWidget
from ltrace.slicer_utils import dataFrameToTableNode
from .model import ModelLogic, ModelWidget

CLONED_COLUMNS = 40


class SnowWidget(ModelWidget):
    SegmentParameters = namedtuple(
        "SegmentParameters",
        [
            "model",
            "segmentationNode",
            "sigma",
            "minDistanceFilter",
            "sizeMinThreshold",
            "outputPrefix",
            "selectedMeasurements",
        ],
    )

    def __init__(self, instanceSegmenterClass, instanceSegmenterWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instanceSegmenterClass = instanceSegmenterClass
        self.instanceSegmenterWidget = instanceSegmenterWidget
        self.setup()

    def getSigma(self):
        return slicer.app.settings().value(f"ImageLogInstanceSegmenter/sigma", 0.0)

    def getMinDistanceFilter(self):
        return slicer.app.settings().value(f"ImageLogInstanceSegmenter/minDistanceFilter", 5)

    def getSizeMinThreshold(self):
        return slicer.app.settings().value(f"ImageLogInstanceSegmenter/sizeMinThreshold", 0.0)

    def setup(self):
        self.progressBar = LocalProgressBar()
        self.logic = SnowLogic(self, self.progressBar)
        self.logic.processFinished.connect(lambda: self.updateButtonsEnablement(False))

        formLayout = qt.QFormLayout(self)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        # Input section
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        formLayout.addRow(inputCollapsibleButton)

        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.segmentationNodeComboBox = SingleShotInputWidget(
            hideImage=True,
            hideSoi=True,
            hideCalcProp=True,
            mainName="Binary segmentation image",
            objectNamePrefix="Snow",
        )
        self.segmentationNodeComboBox.onMainSelectedSignal.connect(self.onSegmentationNodeChanged)
        self.segmentationNodeComboBox.setToolTip("Select the binary segmentation image.")
        inputFormLayout.addRow(self.segmentationNodeComboBox)
        inputFormLayout.addRow(" ", None)

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignLeft)

        self.smooth_factor = qt.QDoubleSpinBox()
        self.smooth_factor.setRange(0, 10)
        self.smooth_factor.setDecimals(1)
        self.smooth_factor.setSingleStep(0.1)
        self.smooth_factor.setValue(float(self.getSigma()))
        self.smooth_factor.setToolTip("Gaussian blur window size.")
        self.smooth_factor.objectName = "Snow Smooth Factor"
        sigmaBoxLayout = qt.QHBoxLayout()
        sigmaBoxLayout.addWidget(self.smooth_factor)
        pixel_label = PixelLabel(value_input=self.smooth_factor, node_input=self.segmentationNodeComboBox)
        pixel_label.setSizePolicy(qt.QSizePolicy.Maximum, qt.QSizePolicy.Fixed)
        sigmaBoxLayout.addWidget(pixel_label)
        parametersFormLayout.addRow("Smooth factor (mm):", sigmaBoxLayout)

        minDistBox = qt.QHBoxLayout()
        self.minDistanceFilter = fixedRangeNumberParam(2, 30, value=5)
        self.minDistanceFilter.setToolTip(
            "Minimum distance separating peaks in a region of 2 * min_distance + 1 "
            "(i.e. peaks are separated by at least min_distance). To find the maximum number of partitions, "
            "use min_distance = 0."
        )
        self.minDistanceFilter.objectName = "Snow Minimum Distance Filter"
        self.minDistPixelLabel = qt.QLabel("  0 px")
        minDistBox.addWidget(self.minDistanceFilter)
        minDistBox.addWidget(self.minDistPixelLabel)
        self.minDistanceFilter.valueChanged.connect(
            lambda v, w=self.minDistPixelLabel: self._onMinDistanceFilterChanged(v, w)
        )
        parametersFormLayout.addRow("Minimum distance filter:", minDistBox)

        self.sizeMinThreshold = qt.QDoubleSpinBox()
        self.sizeMinThreshold.setRange(0, 10)
        self.sizeMinThreshold.setDecimals(1)
        self.sizeMinThreshold.setSingleStep(0.1)
        self.sizeMinThreshold.setValue(float(self.getSizeMinThreshold()))
        self.sizeMinThreshold.setToolTip("Parameter to set the minimum size of a partition.")
        self.sizeMinThreshold.objectName = "Snow Size Minimum Threshold"
        thresholdBoxLayout = qt.QHBoxLayout()
        thresholdBoxLayout.addWidget(self.sizeMinThreshold)
        pixel_label = PixelLabel(value_input=self.sizeMinThreshold, node_input=self.segmentationNodeComboBox)
        pixel_label.setSizePolicy(qt.QSizePolicy.Maximum, qt.QSizePolicy.Fixed)
        thresholdBoxLayout.addWidget(pixel_label)
        parametersFormLayout.addRow("Size minimum threshold (mm):", thresholdBoxLayout)

        self.measurementsList = qt.QListWidget()
        self.measurementsList.setSizePolicy(qt.QSizePolicy.Expanding, qt.QAbstractScrollArea.AdjustToContents)
        self.measurementsList.objectName = "Snow measurement list widget"
        for measurement in GENERIC_PROPERTIES:
            item = qt.QListWidgetItem(measurement)
            item.setFlags(item.flags() | qt.Qt.ItemIsUserCheckable)
            item.setCheckState(qt.Qt.Checked)
            self.measurementsList.addItem(item)

        selectAllButton = qt.QPushButton("Select all")
        selectAllButton.clicked.connect(lambda: self.changeMeasurementsSelection(True))
        unselectAllButton = qt.QPushButton("Unselect all")
        unselectAllButton.clicked.connect(lambda: self.changeMeasurementsSelection(False))
        selectionButtonsLayout = qt.QHBoxLayout()
        selectionButtonsLayout.addWidget(selectAllButton)
        selectionButtonsLayout.addWidget(unselectAllButton)

        parametersFormLayout.addRow("Select measurements:", self.measurementsList)
        parametersFormLayout.addRow("", selectionButtonsLayout)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.outputPrefixLineEdit = qt.QLineEdit()
        self.outputPrefixLineEdit.objectName = "Snow Output Prefix Line Edit"
        outputFormLayout.addRow("Output prefix:", self.outputPrefixLineEdit)
        outputFormLayout.addRow(" ", None)
        reset_style_on_valid_text(self.outputPrefixLineEdit)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.objectName = "Snow Apply Button"
        self.applyButton.setFixedHeight(40)
        self.applyButton.clicked.connect(self.onApplyButtonClicked)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.objectName = "Snow Cancel Button"
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.applyButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        formLayout.addRow(buttonsHBoxLayout)

        formLayout.addRow(self.progressBar)
        self.updateButtonsEnablement(running=False)

    def _onMinDistanceFilterChanged(self, value, labelWidget):
        node = self.segmentationNodeComboBox.mainInput.currentNode()
        refNode = node.GetNodeReference("referenceImageGeometryRef") if node else None
        voxelSize = min([x for x in refNode.GetSpacing()]) if refNode else 0
        unpx = np.round(value * voxelSize, decimals=5)
        labelWidget.setText(f" {int(value)} px ({unpx} mm)")

        if value <= 6:
            color = "white" if themeIsDark() else "black"
            labelWidget.setStyleSheet(f"QLabel {{color: {color};}}")
        elif 6 < value < 8:
            color = "yellow" if themeIsDark() else "orange"
            labelWidget.setStyleSheet(f"QLabel {{color: {color};}}")
        else:
            labelWidget.setStyleSheet("QLabel {color: red;}")

    def onSegmentationNodeChanged(self, node):
        self.outputPrefixLineEdit.text = node.GetName() if node else ""
        self._onMinDistanceFilterChanged(self.minDistanceFilter.value, self.minDistPixelLabel)

    def onApplyButtonClicked(self):
        labelmapnode = None

        try:
            if self.segmentationNodeComboBox.mainInput.currentNode() is None:
                highlight_error(self.segmentationNodeComboBox)
                return
            if self.outputPrefixLineEdit.text.strip() == "":
                highlight_error(self.outputPrefixLineEdit)
                return

            remove_highlight(self.segmentationNodeComboBox)
            remove_highlight(self.outputPrefixLineEdit)

            node = self.segmentationNodeComboBox.mainInput.currentNode()
            is_labelmap = isinstance(node, slicer.vtkMRMLLabelMapVolumeNode)
            if is_labelmap:
                segmentationnode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
                slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                    node,
                    segmentationnode,
                )
                node = segmentationnode
            segments = [
                node.GetSegmentation().GetNthSegmentID(n) for n in self.segmentationNodeComboBox.getSelectedSegments()
            ]

            if len(segments) == 0:
                self.segmentationNodeComboBox.checkSelection()
                raise SnowInfo("Please, select at least one segment by checking the segment box on the segment list.")

            labelmapnode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                node, segments, labelmapnode, None, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY, None
            )
            if is_labelmap:
                slicer.mrmlScene.RemoveNode(node)
            labelmapnode.SetName("tempLabelMap")
            makeNodeTemporary(labelmapnode, hide=True)
            node = labelmapnode

            self.instanceSegmenterClass.set_setting("model", self.instanceSegmenterWidget.modelComboBox.currentData)
            self.instanceSegmenterClass.set_setting("sigma", self.smooth_factor.value)
            self.instanceSegmenterClass.set_setting("minDistanceFilter", self.minDistanceFilter.value)
            self.instanceSegmenterClass.set_setting("sizeMinThreshold", self.sizeMinThreshold.value)

            segmentParameters = self.SegmentParameters(
                model=self.instanceSegmenterWidget.modelComboBox.currentData,
                segmentationNode=node,
                sigma=float(self.smooth_factor.value),
                minDistanceFilter=int(self.minDistanceFilter.value),
                sizeMinThreshold=float(self.sizeMinThreshold.value),
                outputPrefix=self.outputPrefixLineEdit.text,
                selectedMeasurements=self.getSelectedMeasurements(),
            )
            self.updateButtonsEnablement(running=True)
            self.logic.apply(segmentParameters)
        except SnowInfo as e:
            slicer.util.infoDisplay(str(e))
            if labelmapnode:
                slicer.mrmlScene.RemoveNode(labelmapnode)
        except Exception as e:
            logging.error(f"Error: {e}\n{traceback.print_exc()}")
            slicer.util.errorDisplay("An error has occurred during the segmentation.")

    def onCancelButtonClicked(self):
        self.logic.cancel()

    def updateButtonsEnablement(self, running: bool) -> None:
        self.applyButton.setEnabled(not running)
        self.cancelButton.setEnabled(running)

    def getSelectedMeasurements(self):
        selectedMeasurements = []
        for item in range(self.measurementsList.count):
            itemSelected = self.measurementsList.item(item).checkState() == qt.Qt.Checked
            selectedMeasurements.append(1 if itemSelected else 0)

        return selectedMeasurements

    def changeMeasurementsSelection(self, selected):
        for item in range(self.measurementsList.count):
            self.measurementsList.item(item).setCheckState(qt.Qt.Checked if selected else qt.Qt.Unchecked)


class SnowLogic(ModelLogic):
    def __init__(self, parent, progressBar) -> None:
        super().__init__(parent)
        self.cliNode = None
        self.progressBar = progressBar
        self.outputLabelMapNode = None
        self.propertiesTableNode = None
        self.selectedMeasurements = []

    def apply(self, p):
        self.model = p.model
        self.segmentationNode = p.segmentationNode
        self.sigma = p.sigma
        self.minDistanceFilter = p.minDistanceFilter
        self.sizeMinThreshold = p.sizeMinThreshold
        self.selectedMeasurements = p.selectedMeasurements
        self.outputPrefix = p.outputPrefix
        shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        self.itemParent = shNode.GetItemParent(shNode.GetItemByDataNode(self.segmentationNode))

        self.outputLabelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        self.outputLabelMapNode.SetName(slicer.mrmlScene.GenerateUniqueName(p.outputPrefix + "_Instances"))
        self.outputLabelMapNode.SetAttribute("InstanceSegmenter", p.model)
        self.outputLabelMapNode.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
        self.outputLabelMapNode.HideFromEditorsOn()
        triggerNodeModified(self.outputLabelMapNode)
        shNode.SetItemParent(shNode.GetItemByDataNode(self.outputLabelMapNode), self.itemParent)

        params = {
            "method": "snow",
            "sigma": self.sigma,
            "d_min_filter": self.minDistanceFilter,
            "size_min_threshold": self.sizeMinThreshold,
            "direction": None,
            "generate_throat_analysis": False,
            "voxel_size": None,
        }

        self.cloneColumns(self.segmentationNode)

        cliConf = dict(
            params=json.dumps(params),
            products="partitions",
            labelVolume=self.segmentationNode.GetID(),
            outputVolume=self.outputLabelMapNode.GetID(),
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
            self.cliNode = None
            return
        if self.cliNode is None:
            return
        errors = caller.GetParameterAsString("errors")
        status = caller.GetStatusString()
        if "Completed" in status or status == "Cancelled":
            self.processFinished.emit()
            logging.info(status)
            self.cliNode = None
            if errors:
                slicer.util.errorDisplay(
                    "Check the method parameters. Please try it with smaller values and incrementally increase them as needed."
                )
                return
            if status == "Completed":
                try:
                    array = slicer.util.arrayFromVolume(self.outputLabelMapNode)
                    # tripling the number of available colors on the color table, to account for adding/editing extra labels later
                    colorTable = labels_to_color_node(
                        3 * int(np.max(array)), self.outputLabelMapNode.GetName() + "_color_table"
                    )
                    self.outputLabelMapNode.GetDisplayNode().SetAndObserveColorNodeID(colorTable.GetID())

                    self.decloneColumns(self.outputLabelMapNode, link_border_segments=True)
                    self.decloneColumns(self.segmentationNode)

                    propertiesDataFrame = instancesPropertiesDataFrame(
                        self.outputLabelMapNode, self.selectedMeasurements
                    )
                    if len(propertiesDataFrame.index) == 0:
                        slicer.mrmlScene.RemoveNode(self.outputLabelMapNode)
                        slicer.util.infoDisplay("No instances were detected.")
                        return

                    self.outputLabelMapNode.HideFromEditorsOff()
                    triggerNodeModified(self.outputLabelMapNode)

                    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
                    self.propertiesTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
                    self.propertiesTableNode.SetName(
                        slicer.mrmlScene.GenerateUniqueName(self.outputPrefix + "_Instances_Report")
                    )
                    self.propertiesTableNode.SetAttribute("InstanceSegmenter", self.model)
                    self.propertiesTableNode.AddNodeReferenceID(
                        "InstanceSegmenterLabelMap", self.outputLabelMapNode.GetID()
                    )
                    shNode.SetItemParent(shNode.GetItemByDataNode(self.propertiesTableNode), self.itemParent)
                    dataFrameToTableNode(propertiesDataFrame, tableNode=self.propertiesTableNode)
                except Exception as e:
                    logging.error(f"Error: {e}\n{traceback.print_exc()}")
                    slicer.mrmlScene.RemoveNode(self.outputLabelMapNode)
                    slicer.mrmlScene.RemoveNode(self.propertiesTableNode)
                    slicer.util.errorDisplay(
                        "A problem has occurred during the segmentation. Please check your input files."
                    )
                self.selectedMeasurements = []

            elif status == "Cancelled":
                slicer.mrmlScene.RemoveNode(self.outputLabelMapNode)
                slicer.mrmlScene.RemoveNode(self.propertiesTableNode)
                self.selectedMeasurements = []
            else:
                slicer.mrmlScene.RemoveNode(self.outputLabelMapNode)
                slicer.mrmlScene.RemoveNode(self.propertiesTableNode)
                self.selectedMeasurements = []

            if self.segmentationNode.GetAttribute(NodeTemporarity.name()) == NodeTemporarity.TRUE.value:
                slicer.mrmlScene.RemoveNode(self.segmentationNode)

    def cancel(self):
        if self.cliNode is None:
            return
        self.cliNode.Cancel()


class SnowInfo(RuntimeError):
    pass
