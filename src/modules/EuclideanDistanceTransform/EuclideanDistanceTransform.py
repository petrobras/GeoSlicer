import os
import typing
from pathlib import Path

import ctk
import qt
import slicer

from ltrace.slicer import helpers, ui
from ltrace.slicer.widget.combined_inputs import CheckableSegmentListBoard
from ltrace.slicer_utils import *
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.node_attributes import NodeEnvironment


class EuclideanDistanceTransform(LTracePlugin):
    SETTING_KEY = "EuclideanDistanceTransform"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Euclidean Distance Transform"
        self.parent.categories = ["Tools", "MicroCT", "Multiscale", "Thin Section"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = "Computes the Euclidean Distance Transform of a binary image."
        self.parent.acknowledgementText = ""
        self.setHelpUrl("Volumes/Filter/Filter.html#euclidean-distance-transform")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class EuclideanDistanceTransformWidget(LTracePluginWidget):
    OUTPUT_SUFFIX = "_EDT"

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = EuclideanDistanceTransformLogic(self.progressBar)

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        # Input section
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        formLayout.addRow(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.inputVolumeComboBox = slicer.qMRMLNodeComboBox()
        self.inputVolumeComboBox.nodeTypes = [
            "vtkMRMLLabelMapVolumeNode",
            "vtkMRMLScalarVolumeNode",
            "vtkMRMLSegmentationNode",
        ]
        self.inputVolumeComboBox.selectNodeUponCreation = True
        self.inputVolumeComboBox.addEnabled = False
        self.inputVolumeComboBox.removeEnabled = False
        self.inputVolumeComboBox.noneEnabled = True
        self.inputVolumeComboBox.showHidden = False
        self.inputVolumeComboBox.showChildNodeTypes = False
        self.inputVolumeComboBox.setMRMLScene(slicer.mrmlScene)
        self.inputVolumeComboBox.setToolTip("Select the input binary image.")
        self.inputVolumeComboBox.currentNodeChanged.connect(self.onInputChanged)
        inputFormLayout.addRow("Input image:", self.inputVolumeComboBox)
        inputFormLayout.addRow(" ", None)

        # # Use CheckableSegmentListBoard to present a list of segments for selection
        self.segmentsBoard = CheckableSegmentListBoard(defaultState=qt.Qt.Unchecked)
        self.segmentsBoard.showBoard()
        self.segmentsBoard.setVisible(False)
        inputFormLayout.addRow(self.segmentsBoard)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.outputVolumeNameLineEdit = qt.QLineEdit()
        outputFormLayout.addRow("Output image name:", self.outputVolumeNameLineEdit)
        outputFormLayout.addRow(" ", None)

        # self.applyButton = qt.QPushButton("Apply")
        # self.applyButton.setFixedHeight(40)
        # self.applyButton.clicked.connect(self.onApplyButtonClicked)
        #
        # self.cancelButton = qt.QPushButton("Cancel")
        # self.cancelButton.setFixedHeight(40)
        # self.cancelButton.clicked.connect(self.onCancelButtonClicked)
        #
        # buttonsHBoxLayout = qt.QHBoxLayout()
        # buttonsHBoxLayout.addWidget(self.applyButton)
        # buttonsHBoxLayout.addWidget(self.cancelButton)

        buttonsHBox = ui.ApplyCancelButtons(
            onApplyClick=self.onApplyButtonClicked,
            onCancelClick=self.onCancelButtonClicked,
        )

        formLayout.addRow(buttonsHBox)

        self.layout.addStretch()
        self.layout.addWidget(self.progressBar)

    def onApplyButtonClicked(self):
        try:
            if not self.inputVolumeComboBox.currentNode():
                raise EDTInfo("Input image is required.")
            if not self.outputVolumeNameLineEdit.text:
                raise EDTInfo("Output image name is required.")

            self.logic.apply(
                self.inputVolumeComboBox.currentNode(),
                self.outputVolumeNameLineEdit.text,
                self.segmentsBoard.getCheckedIndexes(),
            )
        except EDTInfo as e:
            slicer.util.infoDisplay(str(e))
            return

    def onCancelButtonClicked(self):
        self.logic.cancel()

    def onInputChanged(self, inputNode):
        self.segmentsBoard.setVisible(False)

        if inputNode is None:
            self.outputVolumeNameLineEdit.setText("")
            self.segmentsBoard.setData(None)
            return

        newOutputName = inputNode.GetName() + self.OUTPUT_SUFFIX if inputNode else ""
        self.outputVolumeNameLineEdit.setText(newOutputName)

        if not inputNode.IsA("vtkMRMLSegmentationNode") and not inputNode.IsA("vtkMRMLLabelMapVolumeNode"):
            self.segmentsBoard.setData(None)
            return

        self.segmentsBoard.setData(inputNode)

        if self.segmentsBoard.segmentList.count > 1:
            self.segmentsBoard.setVisible(True)

        self.segmentsBoard.check(0)


def convertToLabelMap(segmentationNode):
    import slicer.util

    labelMapNode = helpers.createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, "LabelMapFromSegmentation_TMP")

    slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
        segmentationNode, labelMapNode, helpers.tryGetNode(helpers.getReferenceNode(segmentationNode))
    )

    return labelMapNode


def filterLabelmap(labelMapNode, selection: typing.List[int] = None):
    array = slicer.util.arrayFromVolume(labelMapNode)
    # use numexpr to filter the selection indexes if provided from array
    if selection:
        import numexpr as ne

        selection_condition = " & ".join([f"(array != {idx})" for idx in selection])
        mask = ne.evaluate(selection_condition)
        array[mask] = 0

    slicer.util.updateVolumeFromArray(labelMapNode, array)

    return labelMapNode


class EuclideanDistanceTransformLogic(LTracePluginLogic):
    def __init__(self, progressBar):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar

    def __handleInputTypes(self, inputVolume, selection: typing.List[int] = None):
        if selection:
            if inputVolume.IsA("vtkMRMLSegmentationNode"):
                inputVolume = convertToLabelMap(inputVolume)
                selection = [i + 1 for i in selection]
            elif inputVolume.IsA("vtkMRMLLabelMapVolumeNode"):
                inputVolume = helpers.createTemporaryVolumeNode(
                    slicer.vtkMRMLLabelMapVolumeNode, name=inputVolume.GetName() + "_Filtered_TMP", content=inputVolume
                )

            filterLabelmap(inputVolume, selection)
        else:
            if inputVolume.IsA("vtkMRMLSegmentationNode"):
                inputVolume = convertToLabelMap(inputVolume)

        return inputVolume

    def apply(self, inputVolume, outputVolumeName, selection: typing.List[int] = None):
        # Removing old cli node if it exists
        if self.cliNode:
            slicer.mrmlScene.RemoveNode(self.cliNode)

        try:
            # Output volume
            outputVolume = helpers.createTemporaryVolumeNode(slicer.vtkMRMLScalarVolumeNode, name=outputVolumeName)

            # TODO change to class variables
            self._params = {
                "inputVolume": inputVolume.GetID(),
                "outputVolume": outputVolume.GetID(),
            }

            processedInputVolume = self.__handleInputTypes(inputVolume, selection)

            cliParams = {
                "inputVolume": processedInputVolume.GetID(),
                "outputVolume": outputVolume.GetID(),
            }

            self.cliNode = slicer.cli.run(
                slicer.modules.euclideandistancetransformcli, None, cliParams, wait_for_completion=False
            )
            self.progressBar.setCommandLineModuleNode(self.cliNode)
            self.cliNode.AddObserver("ModifiedEvent", self.onCLIModified)

        except Exception as e:
            if self.cliNode:
                slicer.mrmlScene.RemoveNode(self.cliNode)
                self.cliNode = None

            helpers.removeTemporaryNodes()
            raise e

    def onCLIModified(self, caller, event):
        status = caller.GetStatusString()
        if "Completed" in status or status == "Cancelled":
            self.cliNode.RemoveAllObservers()
            self.cliNode = None

            if status == "Completed":
                inputVolume = helpers.tryGetNode(self._params["inputVolume"])
                outputVolume = helpers.tryGetNode(self._params["outputVolume"])

                slicer.util.setSliceViewerLayers(background=outputVolume, fit=True)

                subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
                inputVolumeItemParent = subjectHierarchyNode.GetItemParent(
                    subjectHierarchyNode.GetItemByDataNode(inputVolume)
                )
                subjectHierarchyNode.SetItemParent(
                    subjectHierarchyNode.GetItemByDataNode(outputVolume), inputVolumeItemParent
                )

                helpers.makeTemporaryNodePermanent(outputVolume, show=True)

            else:  # Cancelled or error
                outputVolume = helpers.tryGetNode(self._params["outputVolume"])
                slicer.mrmlScene.RemoveNode(outputVolume)
                if status != "Cancelled":
                    slicer.util.errorDisplay("EDT computation failed.")

            helpers.removeTemporaryNodes()

    def cancel(self):
        if self.cliNode:
            self.cliNode.Cancel()


class EDTInfo(RuntimeError):
    pass
