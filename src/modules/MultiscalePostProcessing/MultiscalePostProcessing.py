import os
from pathlib import Path
import ctk
import qt
import slicer

import pandas as pd
import numpy as np
from ltrace.slicer import ui, helpers, widgets
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, dataFrameToTableNode
from ltrace.utils.ProgressBarProc import ProgressBarProc
from ltrace.slicer.node_attributes import ImageLogDataSelectable, TableType

try:
    from Test.MultiscalePostProcessingTest import MultiscalePostProcessingTest
except ImportError:
    MultiscalePostProcessingTest = None  # tests not deployed to final version or closed source

METHODS = {"Porosity": "Multiscale porosity per realization", "Frequency": "Pore size distribution"}


class MultiscalePostProcessing(LTracePlugin):
    SETTING_KEY = "MultiscalePostProcessing"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Multiscale Post-Processing"
        self.parent.categories = ["MicroCT", "Multiscale"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = MultiscalePostProcessing.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MultiscalePostProcessingWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

        self.subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        self.logic = None
        self.isSegment = False

    def setup(self):
        LTracePluginWidget.setup(self)

        self.logic = MultiscalePostProcessingLogic()

        ## Method section
        methodSection = ctk.ctkCollapsibleButton()
        methodSection.collapsed = False
        methodSection.text = "Method"

        self.methodComboBox = qt.QComboBox()
        for method in METHODS.values():
            self.methodComboBox.addItem(method)
        self.methodComboBox.objectName = "methodComboBox"

        self.methodComboBox.currentIndexChanged.connect(self.onMethodChange)

        methodLayout = qt.QFormLayout(methodSection)
        methodLayout.addRow("Method:", self.methodComboBox)

        ## Input section porosity
        self.porosityInputSection = ctk.ctkCollapsibleButton()
        self.porosityInputSection.collapsed = False
        self.porosityInputSection.text = "Input"

        self.realizationNodeComboBox = ui.hierarchyVolumeInput(
            onChange=self.onRealizationNodeChange,
            nodeTypes=[
                "vtkMRMLScalarVolumeNode",
                "vtkMRMLLabelMapVolumeNode",
                "vtkMRMLSegmentationNode",
            ],
            hasNone=True,
        )
        self.realizationNodeComboBox.objectName = "realizationNodeComboBox"
        self.realizationNodeComboBox.setToolTip(
            "Select the realization volume node to calculate the porosity table. If its a sequence node from 'Image generation', it will calculate for all realizations"
        )

        self.trainingImageComboBox = ui.hierarchyVolumeInput(
            onChange=self.onTrainingImageChange,
            nodeTypes=[
                "vtkMRMLScalarVolumeNode",
                "vtkMRMLLabelMapVolumeNode",
                "vtkMRMLSegmentationNode",
            ],
            hasNone=True,
        )
        self.trainingImageComboBox.objectName = "trainingImageComboBox"
        self.trainingImageComboBox.setToolTip(
            "Select the training image to be added to the porosity per realization table"
        )

        porosityInputLayout = qt.QFormLayout(self.porosityInputSection)
        porosityInputLayout.addRow("Realization volume:", self.realizationNodeComboBox)
        porosityInputLayout.addRow("Training image:", self.trainingImageComboBox)

        ## Input section frequency
        self.frequencyInputSection = ctk.ctkCollapsibleButton()
        self.frequencyInputSection.collapsed = False
        self.frequencyInputSection.text = "Input"
        self.frequencyInputSection.hide()

        self.psdTableComboBox = ui.hierarchyVolumeInput(
            onChange=self.onPsdTableChange,
            nodeTypes=[
                "vtkMRMLTableNode",
            ],
            hasNone=True,
        )
        self.psdTableComboBox.objectName = "psdTableComboBox"
        self.psdTableComboBox.setToolTip(
            "Select pore size distribution results table. Accepts the sequence result table from microtom"
        )

        self.psdTiTableComboBox = ui.hierarchyVolumeInput(
            # onChange=self.onTrainingImageChange,
            nodeTypes=[
                "vtkMRMLTableNode",
            ],
            hasNone=True,
        )
        self.psdTiTableComboBox.objectName = "psdTiTableComboBox"
        self.psdTiTableComboBox.setToolTip("Select the training image pore size distribution results table")

        inputLayout = qt.QFormLayout(self.frequencyInputSection)
        inputLayout.addRow("PSD Sequence Table:", self.psdTableComboBox)
        inputLayout.addRow("TI PSD Table:", self.psdTiTableComboBox)

        ## Porosity Parameters section
        self.parametersSection = ctk.ctkCollapsibleButton()
        self.parametersSection.text = "Parameters"
        self.parametersSection.collapsed = False
        self.parametersSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        self.porosityValueSpinBox = qt.QDoubleSpinBox()
        self.porosityValueSpinBox.setRange(0, 1000)
        self.porosityValueSpinBox.objectName = "porosityValueSpinBox"
        self.porosityValueSpinBox.setToolTip("Set the value of the segment classified as pore in the image.")

        self.singleShotWidget = widgets.SingleShotInputWidget(
            hideImage=True,
            hideSoi=True,
            hideCalcProp=False,
            allowedInputNodes=["vtkMRMLLabelMapVolumeNode", "vtkMRMLSegmentationNode"],
        )
        self.singleShotWidget.segmentListGroup[1].itemChanged.connect(self.checkRunButtonState)

        self.poreValueLabel = qt.QLabel("Pore segment value:")
        self.poreSegmentLabel = qt.QLabel("Pore segment:")
        self.poreSegmentLabel.hide()

        parametersLayout = qt.QFormLayout(self.parametersSection)
        parametersLayout.addRow(self.poreValueLabel, self.porosityValueSpinBox)
        parametersLayout.addRow(self.poreSegmentLabel, self.singleShotWidget.segmentListGroup[1])

        # Output section
        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.objectName = "outputPrefix"
        self.outputPrefix.textChanged.connect(self.checkRunButtonState)
        outputFormLayout = qt.QFormLayout(outputSection)
        outputFormLayout.addRow("Output prefix:", self.outputPrefix)

        # Apply button
        self.applyButton = ui.ApplyButton(
            onClick=self.onApplyClicked, tooltip="Generate the selected method result table", enabled=False
        )
        self.applyButton.objectName = "applyButton"

        # Update layout
        self.layout.addWidget(methodSection)
        self.layout.addWidget(self.porosityInputSection)
        self.layout.addWidget(self.frequencyInputSection)
        self.layout.addWidget(self.parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addWidget(self.applyButton)
        self.layout.addStretch(1)

    def onApplyClicked(self):
        with ProgressBarProc() as progressBar:
            if self.methodComboBox.currentText == METHODS["Porosity"]:
                self.runPorosityLogic()
            else:
                self.runFrequencyLogic()

    def runPorosityLogic(self):
        mainNode = self.realizationNodeComboBox.currentNode()
        TINode = (
            self.trainingImageComboBox.currentNode() if self.trainingImageComboBox.currentNode() is not None else None
        )

        if mainNode is not None and isinstance(mainNode, slicer.vtkMRMLSegmentationNode):
            mainNode, _ = helpers.createLabelmapInput(mainNode, "temporary_Main")

        if TINode is not None and isinstance(TINode, slicer.vtkMRMLSegmentationNode):
            TINode, _ = helpers.createLabelmapInput(TINode, "temporary_TI")

        self.logic.generatePorosityPerRealization(
            mainNode,
            np.array(self.singleShotWidget.getSelectedSegments()) + 1
            if self.isSegment
            else [self.porosityValueSpinBox.value],
            self.outputPrefix.text,
            TINode,
        )

    def runFrequencyLogic(self):
        node = self.psdTableComboBox.currentNode()

        self.logic.psdFrequency(node, self.outputPrefix.text, self.psdTiTableComboBox.currentNode())

    def checkFrequencyApply(self) -> bool:
        return True if self.psdTableComboBox.currentNode() is not None else False

    def checkPorosityApply(self) -> bool:
        if self.realizationNodeComboBox.currentNode() is not None:
            if (
                isinstance(self.realizationNodeComboBox.currentNode(), slicer.vtkMRMLLabelMapVolumeNode)
                and not self.singleShotWidget.getSelectedSegments()
            ):
                return False
            return True
        return False

    def checkRunButtonState(self) -> None:
        if self.methodComboBox.currentText == METHODS["Porosity"]:
            isValid = self.checkPorosityApply()
        elif self.methodComboBox.currentText == METHODS["Frequency"]:
            isValid = self.checkFrequencyApply()

        self.applyButton.enabled = isValid and self.outputPrefix.text.replace(" ", "") != ""

    def onRealizationNodeChange(self, itemId):
        node = self.subjectHierarchyNode.GetItemDataNode(itemId)
        if node:
            if type(node) is slicer.vtkMRMLScalarVolumeNode:
                self.changePoreValueSelector(False)
                self.singleShotWidget.mainInput.setCurrentNode(None)
            else:
                self.singleShotWidget.updateSegmentList(
                    helpers.getSegmentList(
                        node,
                    )
                )
                self.changePoreValueSelector(True)

            self.outputPrefix.text = "Porosity_per_realization_table"
        else:
            self.singleShotWidget.mainInput.setCurrentNode(None)
            self.changePoreValueSelector(False)
            self.outputPrefix.text = ""

    def onTrainingImageChange(self, itemId):
        node = self.subjectHierarchyNode.GetItemDataNode(itemId)
        if self.realizationNodeComboBox.currentNode() is not None and node:
            self.checkRunButtonState()

    def changePoreValueSelector(self, isSegment):
        self.isSegment = isSegment
        if isSegment:
            self.poreSegmentLabel.show()
            self.singleShotWidget.segmentListGroup[1].show()
            self.porosityValueSpinBox.hide()
            self.poreValueLabel.hide()
        else:
            self.poreSegmentLabel.hide()
            self.singleShotWidget.segmentListGroup[1].hide()
            self.porosityValueSpinBox.show()
            self.poreValueLabel.show()

    def onPsdTableChange(self, itemId):
        node = self.subjectHierarchyNode.GetItemDataNode(itemId)
        if node:
            self.outputPrefix.text = f"{node.GetName()}_frequency_table"
        else:
            self.outputPrefix.text = ""

    def onMethodChange(self, index):
        if index == 0:
            self.porosityInputSection.show()
            self.parametersSection.show()
            self.frequencyInputSection.hide()

        else:
            self.porosityInputSection.hide()
            self.parametersSection.hide()
            self.frequencyInputSection.show()

        self.checkRunButtonState()


class MultiscalePostProcessingLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def __AddNodeToHierarchy(self, tableNode: slicer.vtkMRMLTableNode, folder: str) -> None:
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        parentItemId = folderTree.GetSceneItemID()
        dirLabel = "Multiscale Post-processing"
        mainDir = folderTree.GetItemByName(dirLabel)
        if not mainDir:
            mainDir = folderTree.CreateFolderItem(parentItemId, dirLabel)

        folderDir = folderTree.GetItemByName(folder)
        if not folderDir:
            folderDir = folderTree.CreateFolderItem(mainDir, folder)

        folderTree.SetItemParent(folderTree.GetItemByDataNode(tableNode), folderDir)

    def __frequencyArrayFromDataframe(self, dataFrame: pd.DataFrame) -> np.ndarray:
        try:
            fractions = np.array(dataFrame["Sw (frac)"])
            frequency = np.zeros((len(fractions), 2))
            frequency[:, 0] = np.array(dataFrame["radii (voxel)"])
            frequency[1:, 1] = (fractions[1:] - fractions[:-1]) * 100
            return frequency
        except Exception as error:
            slicer.util.errorDisplay(f"Invalid data selected as input.\nNo column with header {error}")
            raise error

    def psdFrequency(self, psdInputNode, outputPrefix: str, tiTableNode: slicer.vtkMRMLTableNode = None) -> None:
        nodesDataFrames = []
        isSingleReturn = True
        isLastTI = False

        browser_node = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(psdInputNode)
        if browser_node:
            sequence_node = browser_node.GetSequenceNode(psdInputNode)
            for image in range(sequence_node.GetNumberOfDataNodes()):
                nodesDataFrames.append(slicer.util.dataframeFromTable(sequence_node.GetNthDataNode(image)))
        else:
            nodesDataFrames.append(slicer.util.dataframeFromTable(psdInputNode))

        if tiTableNode is not None:
            isLastTI = True
            nodesDataFrames.append(slicer.util.dataframeFromTable(tiTableNode))

        if len(nodesDataFrames) > 1:
            isSingleReturn = False
            frequencySequenceNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSequenceNode", slicer.mrmlScene.GenerateUniqueName(f"{outputPrefix}_sequence")
            )
            frequencySequenceNode.SetIndexUnit("")
            frequencySequenceNode.SetIndexName("Realization")

        headers = ["radius (voxel)", "frequency (%)"]
        index = 0
        for df in nodesDataFrames:
            frequency = self.__frequencyArrayFromDataframe(df)
            dfFrequency = pd.DataFrame(frequency, columns=headers)
            tableNode = dataFrameToTableNode(dfFrequency)

            if isSingleReturn:
                tableNode.SetName(slicer.mrmlScene.GenerateUniqueName(outputPrefix))
                self.__AddNodeToHierarchy(tableNode, METHODS["Frequency"])
                return
            else:
                tableNode.SetName("TI" if (isLastTI and index == len(nodesDataFrames) - 1) else f"Realization_{index}")
                frequencySequenceNode.SetDataNodeAtValue(tableNode, str(index))

            if index < len(nodesDataFrames) - 1:
                slicer.mrmlScene.RemoveNode(tableNode)

            index = index + 1

        self.__AddNodeToHierarchy(tableNode, METHODS["Frequency"])
        tableNode.SetName(slicer.mrmlScene.GenerateUniqueName(f"{outputPrefix}_proxy"))
        browserNode = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSequenceBrowserNode", slicer.mrmlScene.GenerateUniqueName(f"{outputPrefix}_browser")
        )
        browserNode.AddProxyNode(tableNode, frequencySequenceNode, False)
        browserNode.SetAndObserveMasterSequenceNodeID(frequencySequenceNode.GetID())
        browserNode.SetIndexDisplayFormat("%.0f")

    def generatePorosityPerRealization(self, input_node, poreValues, outputPrefix, trainingImageNode=None):
        browser_node = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(input_node)
        if browser_node:
            sequence_node = browser_node.GetSequenceNode(input_node)

        height = slicer.util.arrayFromVolume(input_node).shape[0]
        width = sequence_node.GetNumberOfDataNodes() if browser_node else 1
        spacing = (input_node).GetSpacing()

        if trainingImageNode is not None:
            trainingImageArray = slicer.util.arrayFromVolume(trainingImageNode)
            tiHeight = trainingImageArray.shape[0]
            if tiHeight > height:
                height = tiHeight

        headers = ["realization_" + str(x) for x in range(-1, width)]
        headers[0] = "DEPTH"

        poreTable = np.empty((height, width + 1))
        poreTable[:] = np.nan
        poreTable[:, 0] = np.arange(height) * spacing[2]

        if browser_node:
            for image in range(sequence_node.GetNumberOfDataNodes()):
                poreArray = slicer.util.arrayFromVolume(sequence_node.GetNthDataNode(image))
                poreTable[: poreArray.shape[0], image + 1] = ((np.isin(poreArray, poreValues)).sum(axis=(1, 2))) / (
                    poreArray.shape[1] * poreArray.shape[2]
                )
        else:
            poreArray = slicer.util.arrayFromVolume(input_node)
            poreTable[: poreArray.shape[0], 1] = ((np.isin(poreArray, poreValues)).sum(axis=(1, 2))) / (
                poreArray.shape[1] * poreArray.shape[2]
            )

        if trainingImageNode is not None:
            trainingImagePorosity = np.empty(height)
            trainingImagePorosity[:] = np.nan
            trainingImagePorosity[:tiHeight] = ((np.isin(trainingImageArray, poreValues)).sum(axis=(1, 2))) / (
                trainingImageArray.shape[1] * trainingImageArray.shape[2]
            )

            poreTable = np.c_[poreTable, trainingImagePorosity]
            headers.append("TI")

        df = pd.DataFrame(poreTable, columns=headers)

        result = dataFrameToTableNode(df)
        result.SetName(slicer.mrmlScene.GenerateUniqueName(outputPrefix))
        result.SetAttribute(TableType.name(), TableType.POROSITY_PER_REALIZATION.value)
        result.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)

        self.__AddNodeToHierarchy(result, METHODS["Porosity"])

        helpers.removeTemporaryNodes()
