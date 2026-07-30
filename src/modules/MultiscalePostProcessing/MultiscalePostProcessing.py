import os
from pathlib import Path
import ctk
import qt
import slicer
from pathlib import Path
from typing import Union

import pandas as pd
import numpy as np
from ltrace.slicer import ui, helpers, widgets
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.data_utils import dataFrameToTableNode
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
        self.setHelpUrl("Multiscale/MultiscalePostProcessing/MultiscalePostProcessing.html", NodeEnvironment.MULTISCALE)
        self.setHelpUrl("Volumes/Multiscale/Multiscale.html#post-processing", NodeEnvironment.MICRO_CT)

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

        self.warningLabel = qt.QLabel("Input segmentation has no reference. Set custom depth.")
        self.warningLabel.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        self.warningLabel.hide()

        porosityInputLayout = qt.QFormLayout(self.porosityInputSection)
        porosityInputLayout.addRow("Realization volume:", self.realizationNodeComboBox)
        porosityInputLayout.addRow(None, self.warningLabel)
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

        self.topSpinBox = qt.QDoubleSpinBox()
        self.topSpinBox.setSuffix(" m")
        self.topSpinBox.setDecimals(6)
        self.topSpinBox.objectName = "Top depth spinbox"
        self.topSpinBox.setRange(-99999999, 999999999)
        self.topSpinBox.valueChanged.connect(self.checkRunButtonState)
        self.topLabel = qt.QLabel("Top depth:")

        self.bottomSpinBox = qt.QDoubleSpinBox()
        self.bottomSpinBox.setSuffix(" m")
        self.bottomSpinBox.setDecimals(6)
        self.bottomSpinBox.objectName = "bottom depth spinbox"
        self.bottomSpinBox.setRange(-99999999, 999999999)
        self.bottomSpinBox.valueChanged.connect(self.checkRunButtonState)
        self.bottomLabel = qt.QLabel("Bottom depth:")

        parametersLayout = qt.QFormLayout(self.parametersSection)
        parametersLayout.addRow(self.poreValueLabel, self.porosityValueSpinBox)
        parametersLayout.addRow(self.poreSegmentLabel, self.singleShotWidget.segmentListGroup[1])
        parametersLayout.addRow(self.topLabel, self.topSpinBox)
        parametersLayout.addRow(self.bottomLabel, self.bottomSpinBox)

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
            (
                np.array(self.singleShotWidget.getSelectedSegments()) + 1
                if self.isSegment
                else [self.porosityValueSpinBox.value]
            ),
            self.topSpinBox.value * 1000,
            self.bottomSpinBox.value * 1000,
            self.outputPrefix.text,
            TINode,
        )

    def runFrequencyLogic(self):
        node = self.psdTableComboBox.currentNode()

        self.logic.psdFrequency(node, self.outputPrefix.text, self.psdTiTableComboBox.currentNode())

    def checkFrequencyApply(self) -> bool:
        return True if self.psdTableComboBox.currentNode() is not None else False

    def checkPorosityApply(self) -> bool:
        node = self.realizationNodeComboBox.currentNode()
        if node is not None:
            if (
                isinstance(node, (slicer.vtkMRMLLabelMapVolumeNode, slicer.vtkMRMLSegmentationNode))
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

        validDepths = self.checkDepthValid()

        self.applyButton.enabled = isValid and self.outputPrefix.text.replace(" ", "") != "" and validDepths

    def checkDepthValid(self) -> bool:
        if self.topSpinBox.value >= self.bottomSpinBox.value:
            helpers.highlight_error(self.topSpinBox)
            helpers.highlight_error(self.bottomSpinBox)
            return False
        else:
            self.topSpinBox.setStyleSheet("")
            self.bottomSpinBox.setStyleSheet("")
            return True

    def changeInputError(self, state) -> None:
        if state:
            self.warningLabel.setStyleSheet("")
            self.warningLabel.hide()
        else:
            helpers.highlight_warning(self.warningLabel)
            self.warningLabel.show()

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

            try:
                top, bottom = self.logic.getReferenceDepths(node)

            except ValueError:
                self.changeInputError(False)
                self.topSpinBox.setValue(0)
                self.bottomSpinBox.setValue(0)

            else:
                self.topSpinBox.setValue(top)
                self.bottomSpinBox.setValue(bottom)
                self.changeInputError(True)

            finally:
                self.outputPrefix.text = "Porosity_per_realization_table"

        else:
            self.singleShotWidget.mainInput.setCurrentNode(None)
            self.changePoreValueSelector(True)
            self.outputPrefix.text = ""
            self.changeInputError(True)

        self.checkRunButtonState()

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

    def generatePorosityPerRealization(
        self,
        inputNode: Union[slicer.vtkMRMLScalarVolumeNode, slicer.vtkMRMLLabelMapVolumeNode],
        poreValues: list,
        topDepth: float,
        bottomDepth: float,
        outputPrefix: str,
        trainingImageNode=None,
    ) -> slicer.vtkMRMLTableNode:
        browser_node = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(inputNode)
        if browser_node:
            sequence_node = browser_node.GetSequenceNode(inputNode)

        height = slicer.util.arrayFromVolume(inputNode).shape[0]
        width = sequence_node.GetNumberOfDataNodes() if browser_node else 1

        headers = ["realization_" + str(x) for x in range(-1, width)]
        headers[0] = "DEPTH"

        poreTable = np.empty((height, width + 1))
        poreTable[:] = np.nan
        poreTable[:, 0] = np.linspace(topDepth, bottomDepth, height)

        if browser_node:
            for image in range(sequence_node.GetNumberOfDataNodes()):
                poreArray = slicer.util.arrayFromVolume(sequence_node.GetNthDataNode(image))
                poreTable[: poreArray.shape[0], image + 1] = ((np.isin(poreArray, poreValues)).sum(axis=(1, 2))) / (
                    poreArray.shape[1] * poreArray.shape[2]
                )
        else:
            poreArray = slicer.util.arrayFromVolume(inputNode)
            poreTable[: poreArray.shape[0], 1] = ((np.isin(poreArray, poreValues)).sum(axis=(1, 2))) / (
                poreArray.shape[1] * poreArray.shape[2]
            )

        df = pd.DataFrame(poreTable, columns=headers)

        result = dataFrameToTableNode(df)
        result.SetName(slicer.mrmlScene.GenerateUniqueName(outputPrefix))
        result.SetAttribute(TableType.name(), TableType.POROSITY_PER_REALIZATION.value)
        result.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)

        if trainingImageNode:
            tiTop, tiBottom = self.getReferenceDepths(trainingImageNode)

            tiTableNode = self.generatePorosityPerRealization(
                trainingImageNode, poreValues, tiTop * 1000, tiBottom * 1000, outputPrefix=f"{outputPrefix}_TI"
            )

            result.AddNodeReferenceID("TrainingImagePorosityTable", tiTableNode.GetID())

        self.__AddNodeToHierarchy(result, METHODS["Porosity"])

        helpers.removeTemporaryNodes()

        return result

    def getReferenceDepths(
        self,
        node: Union[slicer.vtkMRMLScalarVolumeNode, slicer.vtkMRMLLabelMapVolumeNode, slicer.vtkMRMLSegmentationNode],
    ) -> tuple[float, float]:
        if isinstance(node, slicer.vtkMRMLSegmentationNode):
            referenceNode = helpers.getSourceVolume(node)
            if referenceNode is None:
                raise ValueError(f"No reference found for {node.GetName()}")
            return self.getNodeDepths(referenceNode)

        return self.getNodeDepths(node)

    def getNodeDepths(
        self, node: Union[slicer.vtkMRMLScalarVolumeNode, slicer.vtkMRMLLabelMapVolumeNode]
    ) -> tuple[float, float]:
        origin = node.GetOrigin()
        height = node.GetImageData().GetDimensions()[2] - 1
        verticalSpacing = node.GetSpacing()[2]

        ijkMatrix = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        node.GetIJKToRASDirections(ijkMatrix)
        if ijkMatrix[2][2] == -1:
            top = -origin[2] / 1000
            bottom = (-origin[2] + height * verticalSpacing) / 1000
        else:
            bottom = (-origin[2]) / 1000
            top = (-origin[2] - height * verticalSpacing) / 1000

        return top, bottom
