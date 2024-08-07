import ctk
import json
import os
import qt
import slicer
import logging

from ltrace.assets_utils import get_trained_models_with_metadata, get_metadata
from ltrace.remote.connections import JobExecutor
from ltrace.remote.jobs import JobManager
from ltrace.slicer import ui, helpers, widgets
from ltrace.slicer.helpers import (
    clearPattern,
    generateName,
    rgb2label,
    maskInputWithROI,
    separateLabelmapVolumeIntoSlices,
)
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, dataFrameToTableNode
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer.node_attributes import NodeEnvironment

import csv
import numpy as np
from pathlib import Path
import vtk
import pandas as pd

try:
    from Test.ThinSectionInstanceSegmenterTest import ThinSectionInstanceSegmenterTest
except ImportError:
    ThinSectionInstanceSegmenterTest = None  # tests not deployed to final version or closed source


def getVolumeMinSpacing(volumeNode):
    return min(volumeNode.GetSpacing())


def compareVolumeSpacings(volumeNode, referenceNode):
    volumeSpacing = getVolumeMinSpacing(volumeNode)
    referenceSpacing = getVolumeMinSpacing(referenceNode)
    sameMinSpacing = volumeSpacing == referenceSpacing
    delta = volumeSpacing - referenceSpacing
    relativeError = abs(delta / referenceSpacing)
    return sameMinSpacing, relativeError


def adjustSpacingAndCrop(volumeNode, outputPrefix, soiNode=None, referenceNode=None):
    if volumeNode is None:
        return None

    adjustSpacing = False
    if referenceNode is not None:
        sameMinSpacing, relativeError = compareVolumeSpacings(volumeNode, referenceNode)
        if not sameMinSpacing:
            adjustSpacing = True

    # copy original array
    if soiNode or adjustSpacing:
        volumeNode = helpers.createTemporaryVolumeNode(
            volumeNode.__class__,
            outputPrefix.replace("{type}", "TMP_REFNODE"),
            hidden=True,
            content=volumeNode,
        )

        if referenceNode:
            referenceSpacing = referenceNode.GetSpacing()
            volumeNode.SetSpacing(referenceSpacing)
            volumeOrigin = np.array(volumeNode.GetOrigin())
            volumeNode.SetOrigin((volumeOrigin // referenceSpacing) * referenceSpacing)

    # crop with SOI
    if soiNode:
        volumeNode = maskInputWithROI(volumeNode, soiNode, mask=True)

    return volumeNode


def makeColorsSlices(volumeNode, outputPrefix, deleteOriginal=False):
    """
    the strategy of making color channels slices is hacky,
    works only for 2D data and thus should be avoided
    """
    originalNode = volumeNode
    volumeNode = rgb2label(originalNode, outputPrefix.replace("{type}", "TMP_REFNODECM"))
    if deleteOriginal:
        slicer.mrmlScene.RemoveNode(originalNode)
    return volumeNode


def prepareTemporaryInputs(inputNodes, outputPrefix, soiNode=None, referenceNode=None, colorsToSlices=False):
    ctypes = []
    tmpInputNodes = []
    tmpReferenceNode = None
    tmpReferenceNodeDims = None

    for n, node in enumerate(inputNodes):
        if node is None:
            continue

        tmpNode = adjustSpacingAndCrop(
            node, outputPrefix, soiNode=soiNode
        )  # without spacing to avoid problems with null image

        if n == 0:
            tmpReferenceNode = tmpNode
            tmpReferenceNodeDims = tmpReferenceNode.GetImageData().GetDimensions()
        else:
            tmpNodeDims = tmpNode.GetImageData().GetDimensions()
            sameDimensions = all(d1 == d2 for d1, d2 in zip(tmpNodeDims, tmpReferenceNodeDims))
            if not sameDimensions:
                msg = (
                    "Volume arrays inside SOI have different shapes "
                    f"({tmpNodeDims} found while {tmpReferenceNodeDims} was expected)"
                )
                # remove already created tmpInputNodes before cancellation
                for node, tmpNode in zip(inputNodes, tmpInputNodes):
                    if tmpNode != node and node is not None and tmpNode is not None:
                        slicer.mrmlScene.RemoveNode(tmpNode)
                raise Exception(msg)

        ctype = "rgb" if node.IsA("vtkMRMLVectorVolumeNode") else "value"
        ctypes.append(ctype)

        # the strategy of making color channels slices is hacky,
        # works only for 2D data and thus should be avoided
        if colorsToSlices and ctype == "rgb":
            tmpNodeIsCopy = tmpNode != node
            tmpNode = makeColorsSlices(tmpNode, outputPrefix=outputPrefix, deleteOriginal=tmpNodeIsCopy)

        tmpInputNodes.append(tmpNode)
    return tmpInputNodes, ctypes


def revertColorTable(invMap, destinationNode):
    segmentation = destinationNode.GetSegmentation()
    for j in range(segmentation.GetNumberOfSegments()):
        segment = segmentation.GetNthSegment(j)
        try:
            index, name, color = invMap[segment.GetLabelValue() - 1]
            segment.SetName(name)
            segment.SetColor(color[:3])
            # segment.SetLabelValue(index)
        except Exception as e:
            logging.warning(
                f"Failed during segment {j} [id: {segmentation.GetNthSegmentID(j)}, name: {segment.GetName()}, label: {segment.GetLabelValue()}]"
            )


def setupResultInScene(segmentationNode, referenceNode, imageLogMode, soiNode=None, croppedReferenceNode=None):
    folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    itemTreeId = folderTree.GetItemByDataNode(referenceNode)
    parentItemId = folderTree.GetItemParent(itemTreeId)
    nodeTreeId = folderTree.CreateItem(parentItemId, segmentationNode)

    if imageLogMode:
        segmentationNode.SetAttribute("ImageLogSegmentation", "True")
    else:
        segmentationNode.GetDisplayNode().SetVisibility(True)
        folderTree.SetItemDisplayVisibility(nodeTreeId, True)

        if soiNode:
            slicer.util.setSliceViewerLayers(background=croppedReferenceNode, fit=True)
            slicer.util.setSliceViewerLayers(background=referenceNode, fit=False)
        else:
            slicer.util.setSliceViewerLayers(background=referenceNode, fit=True)


def paddingImageUntilReference(node, reference):
    ref_origin = np.array(reference.GetOrigin())
    ref_spacing = np.array(reference.GetSpacing())
    label_origin = np.array(node.GetOrigin())
    disl = (ref_origin - label_origin) / ref_spacing

    dims = reference.GetImageData().GetDimensions()
    image_data = node.GetImageData()
    extend = reference.GetImageData().GetExtent()

    constant_pad = vtk.vtkImageConstantPad()
    constant_pad.SetOutputWholeExtent(
        np.round(extend[0] - disl[0]).astype(int),
        np.round(extend[1] - disl[0]).astype(int),
        np.round(extend[2] - disl[1]).astype(int),
        np.round(extend[3] - disl[1]).astype(int),
        0,
        0,
    )
    constant_pad.SetConstant(0.0)
    constant_pad.SetInputData(image_data)
    constant_pad.Update()

    new_image_data = constant_pad.GetOutput()
    new_image_data.SetExtent(extend)
    node.SetAndObserveImageData(new_image_data)
    node.SetOrigin(reference.GetOrigin())
    node.Modified()


class ThinSectionInstanceSegmenter(LTracePlugin):
    SETTING_KEY = "ThinSectionInstanceSegmenter"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "ThinSection Instance Segmenter"
        self.parent.categories = ["LTrace Tools"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = ThinSectionInstanceSegmenter.help()
        self.parent.dependencies = []
        self.parent.acknowledgementText = ""

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ThinSectionInstanceSegmenterWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

        self.logic: ThinSectionInstanceSegmenterLogic = None

        self.cliNode = None

    def setup(self):
        LTracePluginWidget.setup(self)

        self.layout.addWidget(self._setupLocalRemoteSection())
        self.layout.addWidget(self._setupInputsSection())
        self.layout.addWidget(self._setupSettingsSection())
        self.layout.addWidget(self._setupOutputSection())
        self.layout.addWidget(self._setupApplySection())

        self.layout.addStretch(1)

        self._addPretrainedModelsIfAvailable()

    def _setupLocalRemoteSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Resources"

        self.localRadioButton = qt.QRadioButton("Local")
        self.localRadioButton.setToolTip("Select to run inference with local resources")
        self.localRadioButton.objectName = "Local Resources RadioButton"
        self.remoteRadioButton = qt.QRadioButton("Remote")
        self.remoteRadioButton.setToolTip("Select to run inference with remote resources")
        self.remoteRadioButton.objectName = "Remote Resources RadioButton"

        hbox = qt.QHBoxLayout(widget)
        hbox.addWidget(self.localRadioButton)
        hbox.addWidget(self.remoteRadioButton)

        self.localRadioButton.setChecked(True)

        return widget

    def _setupInputsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Model selection"
        layout = qt.QVBoxLayout(widget)

        self.inferenceType = qt.QComboBox()
        self.inferenceType.objectName = "Inference ComboBox"
        self.inferenceType.addItem("Native (Direct)", "native_direct")
        self.inferenceType.addItem("Native (Chunked)", "native_sliced")
        self.inferenceType.addItem("Third-Party (Direct)", "lib_direct")
        self.inferenceType.addItem("Third-Party (Chunked)", "lib_sliced")
        self.inferenceType.setToolTip("Select inference type")
        self.inferenceType.currentIndexChanged.connect(self._onInferenceSelected)

        scripted_modules_path = helpers.get_scripted_modules_path()
        inferenceTypeHelpButton = HelpButton(
            f"### Instance Segmentation Inference\n\nDifferent algorithms are available to perform an inference with a given model.\n\nThe native ones are codes implemented by us using the mmdet framework. Third parties use the [sahi](https://github.com/obss/sahi) library. In addition we also provide two types of inference:\n\n - Direct: Default method for running inference on the entire image. It's faster, but provides fewer results.\n\n - Chunked: Run inference on fragments or tiles of the full image. It can be very slow, but provides more complete results.\n\n-----\n More information available at [Geoslicer Manual]({scripted_modules_path}/Resources/manual/Segmenter/Semiauto/semiauto.html)"
        )

        self.modelInput = qt.QComboBox()
        self.modelInput.objectName = "Model ComboBox"
        self.modelInput.setToolTip("Select pre-trained model for instance segmentation")

        modelInputHelpButton = HelpButton(
            f"### Instance Segmentation Inference\n\n The frameworks provided here can support different types of models. Select one of then from the list.\n\n-----\n More information available at [Geoslicer Manual]({scripted_modules_path}/Resources/manual/Segmenter/Semiauto/semiauto.html)"
        )

        self.inputsSelector = widgets.SingleShotInputWidget(
            rowTitles={"main": "Annotations", "soi": "Region (SOI)", "reference": "Volume (PX)"},
            checkable=False,
            setDefaultMargins=False,
        )
        self.inputsSelector.setParent(widget)
        self.inputsSelector.onReferenceSelectedSignal.connect(self._onReferenceSelected)
        self.inputsSelector.segmentationLabel.visible = False
        self.inputsSelector.mainInput.visible = False
        self.inputsSelector.segmentsContainerWidget.visible = False
        self.inputsSelector.mainInput.setCurrentNode(None)
        self.inputsSelector.soiInput.enabled = True
        self.inputsSelector.soiInput.objectName = "SOI ComboBox"
        self.inputsSelector.referenceInput.enabled = True
        self.inputsSelector.referenceInput.objectName = "Input Volume ComboBox"
        self.inputsSelector.referenceInput.setNodeTypes(["vtkMRMLVectorVolumeNode"])

        hbox = qt.QHBoxLayout(widget)
        inferenceTypeLabel = qt.QLabel("Inference:")
        inferenceTypeLabel.setFixedWidth(80)
        hbox.addWidget(inferenceTypeLabel)
        hbox.addWidget(self.inferenceType)
        hbox.addWidget(inferenceTypeHelpButton)
        layout.addLayout(hbox)

        hbox = qt.QHBoxLayout(widget)
        modelInputLabel = qt.QLabel("Model:")
        modelInputLabel.setFixedWidth(80)
        hbox.addWidget(modelInputLabel)
        hbox.addWidget(self.modelInput)
        hbox.addWidget(modelInputHelpButton)
        layout.addLayout(hbox)

        hbox = qt.QHBoxLayout(widget)
        self.inputsSelector.soiLabel.setFixedWidth(80)
        hbox.addWidget(self.inputsSelector.soiLabel)
        hbox.addWidget(self.inputsSelector.soiInput)
        layout.addLayout(hbox)

        hbox = qt.QHBoxLayout(widget)
        self.inputsSelector.referenceLabel.setFixedWidth(80)
        hbox.addWidget(self.inputsSelector.referenceLabel)
        hbox.addWidget(self.inputsSelector.referenceInput)
        layout.addLayout(hbox)

        return widget

    def _setupSettingsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Settings"

        layout = qt.QFormLayout(widget)

        self.conf_spinbox = qt.QSpinBox()
        self.conf_spinbox.objectName = "Confidence Threshold SpinBox"
        self.conf_spinbox.setRange(0, 100)
        self.conf_spinbox.setValue(20)
        self.conf_spinbox.setToolTip(
            "Confidence threshold used to filter results. Larger values ​​provide better quality results, small values ​​provide more predictions."
        )

        self.nms_spinbox = qt.QSpinBox()
        self.nms_spinbox.objectName = "NMS Threshold SpinBox"
        self.nms_spinbox.setRange(0, 100)
        self.nms_spinbox.setValue(10)
        self.nms_spinbox.setToolTip(
            "Non-maximum suppression limit: Remove boxes with IoU greater than the value. Larger values ​​give closer results, small values ​​give sparser results."
        )

        self.resize_spinbox = qt.QDoubleSpinBox()
        self.resize_spinbox.objectName = "Resize SpinBox"
        self.resize_spinbox.setRange(0, 1)
        self.resize_spinbox.setValue(0.25)
        self.resize_spinbox.setToolTip(
            "Scale used to resize the image before inference. 1/4 is cost-effective, larger values may take longer to process."
        )

        self.chunk_size_spinbox = qt.QSpinBox()
        self.chunk_size_spinbox.objectName = "Chunk Size SpinBox"
        self.chunk_size_spinbox.setRange(0, 20000)
        self.chunk_size_spinbox.setValue(3200)
        self.chunk_size_spinbox.setToolTip(
            "Size of the chunks on which inference is performed. Small values may take longer to process."
        )
        self.chunk_size_label = qt.QLabel("Chunk size (px):")

        self.overlap_spinbox = qt.QSpinBox()
        self.overlap_spinbox.objectName = "Chunk Overlap SpinBox"
        self.overlap_spinbox.setRange(0, 100)
        self.overlap_spinbox.setValue(50)
        self.overlap_spinbox.setToolTip("Overlap between chunks.")
        self.overlap_label = qt.QLabel("Chunk overlap (%):")

        layout.addRow("Confidence threshold (%):", self.conf_spinbox)
        layout.addRow("NMS threshold (%):", self.nms_spinbox)
        layout.addRow("Resize ratio:", self.resize_spinbox)
        layout.addRow(self.chunk_size_label, self.chunk_size_spinbox)
        layout.addRow(self.overlap_label, self.overlap_spinbox)

        self._onInferenceSelected(0)

        return widget

    def _setupOutputSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Output"

        self.calculateStatisticsCheckbox = qt.QCheckBox("Calculate statistics on segments")
        self.calculateStatisticsCheckbox.objectName = "Statistics CheckBox"
        self.calculateStatisticsCheckbox.setChecked(True)
        self.calculateStatisticsCheckbox.setToolTip(
            "Calculate geometric properties of each instance (Required for use in the instance editor)."
        )

        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.objectName = "Output Prefix LineEdit"

        formLayout = qt.QFormLayout(widget)
        formLayout.addRow(self.calculateStatisticsCheckbox)
        formLayout.addRow("Output Prefix: ", self.outputPrefix)

        return widget

    def _setupApplySection(self):
        widget = qt.QWidget()
        vlayout = qt.QVBoxLayout(widget)

        self.applyButton = ui.ButtonWidget(
            text="Apply", tooltip="Run segmenter on input data limited by ROI", onClick=self._onApplyClicked
        )
        self.applyButton.objectName = "Apply Button"

        self.applyButton.setStyleSheet("QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 0px}")
        self.applyButton.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)

        self.applyButton.enabled = False

        self.progressBar = LocalProgressBar()

        hlayout = qt.QHBoxLayout()
        hlayout.addWidget(self.applyButton)
        hlayout.setContentsMargins(0, 8, 0, 8)

        vlayout.addLayout(hlayout)
        vlayout.addWidget(self.progressBar)

        return widget

    def _onInferenceSelected(self, index):
        if self.inferenceType.itemData(index).endswith("_direct"):
            self.chunk_size_spinbox.visible = False
            self.chunk_size_label.visible = False
            self.overlap_spinbox.visible = False
            self.overlap_label.visible = False
        else:
            self.chunk_size_spinbox.visible = True
            self.chunk_size_label.visible = True
            self.overlap_spinbox.visible = True
            self.overlap_label.visible = True
        return

    def _onReferenceSelected(self, node):
        self.refNode = node
        self._checkRequirementsForApply()
        if self.refNode is None:
            return

        self.outputPrefix.setText(self.refNode.GetName())

        max_size = max(self.refNode.GetImageData().GetDimensions())
        self.chunk_size_spinbox.setMaximum(max_size)

    def _checkRequirementsForApply(self):
        if self.cliNode == None or not self.cliNode.IsBusy():
            self.applyButton.enabled = self.refNode is not None

    def _onApplyClicked(self):
        if self.outputPrefix.text.strip() == "":
            slicer.util.errorDisplay("Please type an output prefix.")
            return

        if self.inputsSelector.referenceInput.currentNode() is None:
            slicer.util.errorDisplay("Please select an input node.")
            return

        self.applyButton.enabled = False

        prefix = self.outputPrefix.text + "_{type}"

        try:
            model_dir = self.modelInput.currentData
            refNode = self.inputsSelector.referenceInput.currentNode()
            soiNode = self.inputsSelector.soiInput.currentNode()

            params = dict(
                conf_thresh=self.conf_spinbox.value,
                nms_thresh=self.nms_spinbox.value,
                resize_ratio=self.resize_spinbox.value,
                chunk_size=self.chunk_size_spinbox.value if self.chunk_size_spinbox.visible else None,
                chunk_overlap=self.overlap_spinbox.value if self.overlap_spinbox.visible else None,
                calculate_statistics=self.calculateStatisticsCheckbox.checked,
                inference=self.inferenceType.currentData,
            )

            logic = ThinSectionInstanceSegmenterLogic(onFinish=self.resetUI)
            classes = get_metadata(model_dir)["classes"]

            model_dir = model_dir.as_posix()
            if self.remoteRadioButton.checked:
                self.cliNode = logic.dispatch(model_dir, refNode, soiNode, prefix, params, classes)
                self.applyButton.enabled = True
            else:
                self.cliNode = logic.run(model_dir, refNode, soiNode, prefix, params, classes)
                if self.cliNode:
                    self.progressBar.setCommandLineModuleNode(self.cliNode)

            if self.cliNode is None:
                self.resetUI()

        except Exception as e:
            slicer.util.errorDisplay(f"Failed to complete execution. {e}")
            tmpPrefix = prefix.replace("{type}", "TMP_*")
            clearPattern(tmpPrefix)
            self.applyButton.enabled = True
            raise

    def resetUI(self):
        self._checkRequirementsForApply()
        self.cliNode = None

    def enter(self) -> None:
        super().enter()
        # Add pretrained models
        self._addPretrainedModelsIfAvailable()

    def _addPretrainedModelsIfAvailable(self):
        env = slicer.util.selectedModule()
        envs = tuple(map(lambda x: x.value, NodeEnvironment))

        if env not in envs:
            return

        if self.modelInput.count == 0:
            try:
                model_dirs = get_trained_models_with_metadata(env)
                for model_dir in model_dirs:
                    metadata = get_metadata(model_dir)
                    try:
                        if metadata["is_instance_seg_model"]:
                            self.modelInput.addItem(metadata["title"], model_dir)
                    except KeyError:
                        pass
            except RuntimeError as error:
                logging.error(error)


def hex2rgb(hex):
    hex = hex.lstrip("#")
    lv = len(hex)
    rgb = tuple(int(hex[i : i + lv // 3], 16) / 255.0 for i in range(0, lv, lv // 3))
    return rgb


def import_colors_from_csv(path):
    with open(path, mode="r") as f:
        reader = csv.reader(f)
        color_dict = {}
        for rows in reader:
            k = rows[1]
            v = rows[0]
            color_dict[k] = hex2rgb(v)
    return color_dict


def setTableUnits(tableNode):
    tableUnits = {
        "label": "null",
        "width": "mm",
        "height": "mm",
        "confidence": "%",
        "area": "mm^2",
        "max_feret": "mm",
        "min_feret": "mm",
        "aspect_ratio": "null",
        "elongation": "null",
        "eccentricity": "null",
        "perimeter": "mm",
    }

    for col in range(tableNode.GetNumberOfColumns()):
        name = tableNode.GetColumnName(col)
        tableNode.SetColumnUnitLabel(name, tableUnits[name])
        if tableUnits[name] != "null":
            tableNode.RenameColumn(col, f"{name} ({tableUnits[name]})")


class ThinSectionInstanceSegmenterLogic(LTracePluginLogic):
    def __init__(self, onFinish=None):
        LTracePluginLogic.__init__(self)

        self.onFinish = onFinish or (lambda: None)
        self.progressUpdate = lambda value: print(value * 100, "%")

        self.config = None

    def loadConfig(self):
        moduleDir = Path(os.path.dirname(os.path.realpath(__file__)))
        sampleFilePath = moduleDir / "Resources" / "ThinSectionInstanceSegmenterConfig.json"

        with open(sampleFilePath, "r") as f:
            config = json.load(f)
            self.config = config["atena02"]
            return self.config

    def run(
        self,
        model,
        referenceNode,
        soiNode,
        outputPrefix,
        params,
        classes,
        segmentation=False,
    ):
        tmpOutNode = helpers.createNode(slicer.vtkMRMLLabelMapVolumeNode, outputPrefix.replace("{type}", "TMP_OUTNODE"))
        slicer.mrmlScene.AddNode(tmpOutNode)

        inputNodes = [referenceNode]

        tmpInputNodes, ctypes = prepareTemporaryInputs(
            inputNodes,
            outputPrefix=outputPrefix,
            soiNode=soiNode,
            referenceNode=referenceNode,
            colorsToSlices=True,
        )

        tmpReferenceNode, *tmpExtraNodes = tmpInputNodes

        if params["inference"].endswith("sliced"):
            refDims = np.array(tmpReferenceNode.GetImageData().GetDimensions())
            refMinSize = min(refDims[1:])
            if params["chunk_size"] > refMinSize:
                slicer.util.warningDisplay(
                    "The size of the chosen chunk is larger than selected region of interest.\nConsider using Direct inference in this case or reducing the chunk size."
                )
                return

        cliConf = dict(
            input_model=model,
            input_volume=tmpReferenceNode.GetID(),
            output_volume=tmpOutNode.GetID(),
            output_table=str(Path(slicer.app.temporaryPath) / "instances_report"),
            ctypes=",".join(ctypes),
        )

        cliConf["xargs"] = json.dumps(params)

        if ctypes[0] == "rgb":
            cliNode = slicer.cli.run(
                slicer.modules.thinsectioninstancesegmentercli,
                None,
                cliConf,
                wait_for_completion=False,
            )
        else:
            slicer.util.warningDisplay(
                "You need to pass a rgb image.\nGo to Thin Section environment for more details."
            )
            return

        def onSuccess(caller):
            try:
                volumeIJKToRASMatrix = vtk.vtkMatrix4x4()
                tmpReferenceNode.GetIJKToRASMatrix(volumeIJKToRASMatrix)
                tmpOutNode.SetIJKToRASMatrix(volumeIJKToRASMatrix)
                referenceSpacing = tmpReferenceNode.GetSpacing()
                tmpOutNode.SetSpacing(referenceSpacing)
                volumeOrigin = tmpReferenceNode.GetOrigin()
                tmpOutNode.SetOrigin(volumeOrigin)

                folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
                itemTreeId = folderTree.GetItemByDataNode(referenceNode)
                parentItemId = folderTree.GetItemParent(itemTreeId)
                outputDir = folderTree.CreateFolderItem(
                    parentItemId, generateName(folderTree, f"{outputPrefix.replace('_{type}', '')} Results")
                )

                tableNodes = []
                sliceNodes = separateLabelmapVolumeIntoSlices(tmpOutNode, axis=0, verifyContent=True, dtype=np.int32)

                if len(sliceNodes) == 0:
                    slicer.util.warningDisplay("The model didn't find any instance.\n")
                    folderTree.RemoveItem(outputDir, True, True)

                    slicer.util.setSliceViewerLayers(
                        background=referenceNode,
                        fit=True,
                    )
                else:
                    if params["calculate_statistics"] and cliConf["output_table"]:
                        try:
                            output_report = pd.read_pickle(cliConf["output_table"])
                            os.remove(cliConf["output_table"])
                        except OSError as e:
                            slicer.util.warningDisplay(
                                "Without data on table.\nCan't calculate statistics on predicted labels.\n"
                            )

                    for i, node in sliceNodes:
                        node.SetIJKToRASMatrix(volumeIJKToRASMatrix)
                        node.SetSpacing(referenceSpacing)
                        node.SetOrigin(volumeOrigin)
                        if soiNode:
                            node = maskInputWithROI(node, soiNode, mask=True)

                        paddingImageUntilReference(node, referenceNode)

                        if segmentation:
                            array = slicer.util.arrayFromVolume(node)
                            instances = np.unique(array)

                            outNode = helpers.createNode(slicer.vtkMRMLSegmentationNode, f"{classes[i]}")
                            outNode.SetHideFromEditors(False)
                            slicer.mrmlScene.AddNode(outNode)
                            outNode.SetReferenceImageGeometryParameterFromVolumeNode(
                                referenceNode
                            )  # use orignal volume

                            invmap = [
                                [j, f"Segment_{j}", self.color_dict[classes[i]]] for j in range(len(instances[1:]))
                            ]

                            helpers.updateSegmentationFromLabelMap(outNode, labelmapVolumeNode=node)
                            revertColorTable(invmap, outNode)

                            setupResultInScene(outNode, referenceNode, None, croppedReferenceNode=tmpReferenceNode)
                            outNode.GetDisplayNode().SetVisibility(True)

                            slicer.mrmlScene.RemoveNode(node)
                        else:
                            nodeTreeId = folderTree.CreateItem(parentItemId, node)
                            helpers.moveNodeTo(outputDir, node, dirTree=folderTree)
                            folderTree.SetItemDisplayVisibility(nodeTreeId, True)
                            node.SetName(classes[i])

                            if params["calculate_statistics"]:
                                tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
                                nodeTreeId = folderTree.CreateItem(parentItemId, tableNode)

                                tableNode.SetName(classes[i] + "_Report")
                                class_report = output_report.loc[output_report["class"] == classes[i]]
                                class_report = class_report.drop("class", axis=1)
                                dataFrameToTableNode(class_report, tableNode=tableNode)
                                setTableUnits(tableNode)

                                del class_report

                                tableNode.SetAttribute("InstanceEditor", classes[i])
                                tableNode.SetAttribute("ReferenceVolumeNode", node.GetID())
                                tableNode.AddNodeReferenceID("InstanceEditorLabelMap", node.GetID())
                                tableNode.AddNodeReferenceID("referenceNode", referenceNode.GetID())
                                tableNodes.append(tableNode)
                                node.SetAttribute("ThinSectionInstanceTableNode", tableNode.GetID())

                            colorNode = slicer.util.loadColorTable(
                                str(
                                    Path(os.path.dirname(os.path.realpath(__file__)))
                                    / "Resources"
                                    / f"{classes[i]}.ctbl"
                                )
                            )
                            node.GetDisplayNode().SetAndObserveColorNodeID(colorNode.GetID())

                    if node:
                        slicer.util.setSliceViewerLayers(
                            background=referenceNode,
                            label=node,
                            fit=True,
                        )
                    else:
                        slicer.util.setSliceViewerLayers(
                            background=referenceNode,
                            fit=True,
                        )

                    if len(tableNodes) != 0:
                        for tableNode in tableNodes:
                            helpers.moveNodeTo(outputDir, tableNode, dirTree=folderTree)

            except Exception as e:
                print("Handle errors on state: %s" % caller.GetStatusString())
                tmpPrefix = outputPrefix.replace("{type}", "TMP_*")
                clearPattern(tmpPrefix)
                self.progressUpdate(0)
                raise

        def onFinish(caller):
            print("ExecCmd CLI %s" % caller.GetStatusString())
            tmpPrefix = outputPrefix.replace("{type}", "TMP_*")
            clearPattern(tmpPrefix)
            self.progressUpdate(1.0)
            self.onFinish()
            cliNode.RemoveObserver(self.observerTag)

        ehandler = CLIEventHandler()
        ehandler.onSuccessEvent = onSuccess
        ehandler.onFinish = onFinish

        self.observerTag = cliNode.AddObserver("ModifiedEvent", ehandler)

        return cliNode

    def dispatch(
        self,
        model,
        referenceNode,
        soiNode,
        outputPrefix,
        params,
        classes,
        segmentation=False,
    ):
        from ThinSectionInstanceSegmenterRemoteTask.ThinSectionInstanceSegmenterExecutionHandler import (
            ThinSectionInstanceSegmenterExecutionHandler,
        )

        handler = ResultHandler()

        tmpOutNode = helpers.createNode(slicer.vtkMRMLLabelMapVolumeNode, outputPrefix.replace("{type}", "TMP_OUTNODE"))
        slicer.mrmlScene.AddNode(tmpOutNode)

        inputNodes = [referenceNode]

        tmpInputNodes, ctypes = prepareTemporaryInputs(
            inputNodes,
            outputPrefix=outputPrefix,
            soiNode=soiNode,
            referenceNode=referenceNode,
            colorsToSlices=True,
        )

        tmpReferenceNode, *tmpExtraNodes = tmpInputNodes

        cmd_handler = ThinSectionInstanceSegmenterExecutionHandler(
            handler,
            outputPrefix.replace("{type}", "LabelMap.nrrd"),
            bin_path=self.config["pythonInterpreter"],
            script_path=self.config["script"],
            model_path=model,
            reference_node_id=referenceNode.GetID(),
            tmp_reference_node_id=tmpReferenceNode.GetID(),
            soi_node_id=soiNode.GetID() if soiNode else None,
            ctypes=ctypes,
            params=params,
            classes=classes,
            segmentation=False,
            opening_cmd='bash -c "source /etc/bashrc" && source /nethome/drp/microtom/init.sh',
        )

        job_name = f"Inst. Seg.: {outputPrefix.replace('_{type}', '')} ({os.path.basename(model)})"

        slicer.modules.RemoteServiceInstance.cli.run(cmd_handler, name=job_name, job_type="instseg")


def instseg_loader(job: JobExecutor):
    from ThinSectionInstanceSegmenterRemoteTask.ThinSectionInstanceSegmenterExecutionHandler import (
        ThinSectionInstanceSegmenterExecutionHandler,
    )

    details = job.details
    output_name = details.get("output_name", "output")
    referenceNodeID = details.get("input_volume_node_id", None)
    tmpReferenceNodeID = details.get("tmp_reference_node_id", None)
    soiNodeID = details.get("soi_node_id", None)
    params = (details.get("params", []),)
    classes = detail.get("classes", [])
    segmentation = detail.get("segmentation", False)
    script_path = details.get("script_path", "")
    bin_path = details.get("bin_path", "")

    handler = ResultHandler()

    task_handler = ThinSectionInstanceSegmenterExecutionHandler(
        handler,
        output_name,
        bin_path=bin_path,
        script_path=script_path,
        model_path=model,
        reference_node_id=referenceNodeID,
        tmp_reference_node_id=tmpReferenceNodeID,
        soi_node_id=soiNodeID,
        params=params,
        classes=classes,
        opening_cmd='bash -c "source /etc/bashrc" && source /nethome/drp/microtom/init.sh',
        segmentation=segmentation,
    )

    task_handler.jobid = str(job.details["job_id"][0])
    job.task_handler = task_handler
    print("JOB ok:", job)
    return job


if "instseg" not in JobManager.compilers:
    JobManager.register("instseg", instseg_loader)


class ResultHandler:
    def __call__(self, results):
        segmentation = False

        ref_node_id = results.get("reference_node_id", None)
        tmp_ref_node_id = results.get("tmp_reference_node_id", None)
        soi_node_id = results.get("soi_node_id", None)
        outputs = results.get("results", [])
        classes = results.get("classes", [])
        outputPrefix = results.get("output_prefix", None)

        referenceNode = slicer.util.getNode(ref_node_id)
        tmpReferenceNode = slicer.util.getNode(tmp_ref_node_id)

        soi_node_id = json.loads(soi_node_id)
        soiNode = slicer.util.getNode(soi_node_id) if soi_node_id else None

        tmpOutNode = slicer.util.loadVolume(
            outputs[0], properties={"name": f"{outputPrefix}_TMP_OUTNODE", "labelmap": True}
        )

        try:
            volumeIJKToRASMatrix = vtk.vtkMatrix4x4()
            tmpReferenceNode.GetIJKToRASMatrix(volumeIJKToRASMatrix)
            tmpOutNode.SetIJKToRASMatrix(volumeIJKToRASMatrix)
            referenceSpacing = tmpReferenceNode.GetSpacing()
            tmpOutNode.SetSpacing(referenceSpacing)
            volumeOrigin = tmpReferenceNode.GetOrigin()
            tmpOutNode.SetOrigin(volumeOrigin)

            folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            itemTreeId = folderTree.GetItemByDataNode(referenceNode)
            parentItemId = folderTree.GetItemParent(itemTreeId)
            outputDir = folderTree.CreateFolderItem(
                parentItemId, generateName(folderTree, f"{outputPrefix.replace('_LabelMap.nrrd', '')} Results")
            )

            tableNodes = []
            sliceNodes = separateLabelmapVolumeIntoSlices(tmpOutNode, axis=0, verifyContent=True, dtype=np.int32)

            if len(outputs) == 2:
                try:
                    output_report = pd.read_pickle(outputs[1])
                    os.remove(outputs[1])
                except OSError as e:
                    slicer.util.warningDisplay("Without data on table.\n")

            if len(sliceNodes) == 0:
                slicer.util.warningDisplay("The model didn't find any instance.\n")
                folderTree.RemoveItem(outputDir, True, True)
            else:
                for i, node in sliceNodes:
                    node.SetIJKToRASMatrix(volumeIJKToRASMatrix)
                    node.SetSpacing(referenceSpacing)
                    node.SetOrigin(volumeOrigin)
                    if soiNode:
                        node = maskInputWithROI(node, soiNode, mask=True)

                    if segmentation:
                        array = slicer.util.arrayFromVolume(node)
                        instances = np.unique(array)

                        outNode = helpers.createNode(slicer.vtkMRMLSegmentationNode, f"{classes[i]}")
                        outNode.SetHideFromEditors(False)
                        slicer.mrmlScene.AddNode(outNode)
                        outNode.SetReferenceImageGeometryParameterFromVolumeNode(referenceNode)  # use orignal volume

                        invmap = [[j, f"Segment_{j}", self.color_dict[classes[i]]] for j in range(len(instances[1:]))]

                        helpers.updateSegmentationFromLabelMap(outNode, labelmapVolumeNode=node)
                        revertColorTable(invmap, outNode)

                        setupResultInScene(outNode, referenceNode, None, croppedReferenceNode=tmpReferenceNode)
                        outNode.GetDisplayNode().SetVisibility(True)

                        slicer.mrmlScene.RemoveNode(node)
                    else:
                        nodeTreeId = folderTree.CreateItem(parentItemId, node)
                        helpers.moveNodeTo(outputDir, node, dirTree=folderTree)
                        folderTree.SetItemDisplayVisibility(nodeTreeId, True)
                        node.SetName(classes[i])

                        if len(outputs) == 2:
                            tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
                            nodeTreeId = folderTree.CreateItem(parentItemId, tableNode)

                            tableNode.SetName(classes[i] + "_Report")
                            class_report = output_report.loc[output_report["class"] == classes[i]]
                            class_report = class_report.drop("class", axis=1)
                            dataFrameToTableNode(class_report, tableNode=tableNode)
                            setTableUnits(tableNode)
                            del class_report

                            tableNode.SetAttribute("InstanceEditor", classes[i])
                            tableNode.SetAttribute("ReferenceVolumeNode", node.GetID())
                            tableNode.AddNodeReferenceID("InstanceEditorLabelMap", node.GetID())
                            tableNode.AddNodeReferenceID("referenceNode", referenceNode.GetID())
                            tableNodes.append(tableNode)
                            node.SetAttribute("ThinSectionInstanceTableNode", tableNode.GetID())

                        colorNode = slicer.util.loadColorTable(
                            str(Path(os.path.dirname(os.path.realpath(__file__))) / "Resources" / f"{classes[i]}.ctbl")
                        )
                        node.GetDisplayNode().SetAndObserveColorNodeID(colorNode.GetID())

                if node:
                    slicer.util.setSliceViewerLayers(
                        background=referenceNode,
                        label=node,
                        fit=True,
                    )
                else:
                    slicer.util.setSliceViewerLayers(
                        background=referenceNode,
                        fit=True,
                    )

                if len(tableNodes) != 0:
                    for tableNode in tableNodes:
                        helpers.moveNodeTo(outputDir, tableNode, dirTree=folderTree)

            tmpPrefix = outputPrefix.replace("LabelMap.nrrd", "LabelMap.nrrd_TMP_*")
            clearPattern(tmpPrefix)

        except Exception as e:
            print("Handle errors on state: %s" % caller.GetStatusString())
            tmpPrefix = outputPrefix.replace("LabelMap.nrrd", "TMP_*")
            clearPattern(tmpPrefix)
            raise


class CLIEventHandler:
    COMPlETED = "completed"
    CANCELLED = "cancelled"

    def __init__(self):
        self.onSuccessEvent = lambda cliNode: print("Completed")
        self.onErrorEvent = lambda cliNode: print("Completed with Errors")
        self.onCancelEvent = lambda cliNode: print("Cancelled")
        self.onFinish = lambda cliNode: None

        self.shouldProcess = True

    def getStatus(self, caller):
        return caller.GetStatusString().lower()

    def __call__(self, cliNode, event):
        if cliNode is None or not self.shouldProcess:
            return

        status = self.getStatus(cliNode)

        if status == self.COMPlETED:
            self.onSuccessEvent(cliNode)

        elif "error" in status:
            self.onErrorEvent(cliNode)

        elif status == self.CANCELLED:
            self.onCancelEvent(cliNode)

        if not cliNode.IsBusy():
            self.onFinish(cliNode)
            self.shouldProcess = False
