import logging
import re
from collections import namedtuple
from pathlib import Path

import ctk
import numpy as np
import pandas as pd
import qt
import slicer

from ImageLogInstanceSegmenter import ImageLogInstanceSegmenter
from ltrace.file_utils import read_csv
from ltrace.slicer.helpers import (
    triggerNodeModified,
    highlight_error,
    labels_to_color_node,
    save_path,
    reset_style_on_valid_text,
    tryGetNode,
)
from ltrace.slicer.node_attributes import ImageLogDataSelectable
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer_utils import (
    is_tensorflow_gpu_enabled,
    dataFrameToTableNode,
)


class SidewallSampleWidget(qt.QWidget):
    SegmentParameters = namedtuple(
        "SegmentParameters",
        [
            "model",
            "amplitudeImageNode",
            "transitTimeImageNode",
            "nominalDepthsDataFrame",
            "depthThreshold",
            "outputPrefix",
            "initialDepth",
            "finalDepth",
        ],
    )

    def __init__(self, instanceSegmenterClass, instanceSegmenterWidget, identifier, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instanceSegmenterClass = instanceSegmenterClass
        self.instanceSegmenterWidget = instanceSegmenterWidget
        self.identifier = identifier
        self.setup()

    def getDepthThreshold(self):
        return ImageLogInstanceSegmenter.get_setting("depthThreshold", default=0.3)

    def setup(self):
        self.progressBar = LocalProgressBar()
        self.logic = SidewallSampleLogic(self.progressBar)

        formLayout = qt.QFormLayout(self)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        # Input section
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        formLayout.addRow(inputCollapsibleButton)

        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.amplitudeImageNodeComboBox = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode"], onChange=self.onAmplitudeImageNodeChanged
        )
        self.amplitudeImageNodeComboBox.setObjectName("sidewallSampleAmplitudeImageNodeComboBox" + self.identifier)
        self.amplitudeImageNodeComboBox.setToolTip("Select the amplitude image.")
        inputFormLayout.addRow("Amplitude image:", self.amplitudeImageNodeComboBox)
        self.amplitudeImageNodeComboBox.resetStyleOnValidNode()

        self.transitTimeImageNodeComboBox = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode"], onChange=self.onTransitTimeImageNodeChanged
        )
        self.transitTimeImageNodeComboBox.setObjectName("sidewallSampleTransitTimeImageNodeComboBox" + self.identifier)
        self.transitTimeImageNodeComboBox.setToolTip("Select the transit time image.")
        inputFormLayout.addRow("Transit time image:", self.transitTimeImageNodeComboBox)
        inputFormLayout.addRow(" ", None)
        self.transitTimeImageNodeComboBox.resetStyleOnValidNode()

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.nominalDepthsPathLineEdit = ctk.ctkPathLineEdit()
        self.nominalDepthsPathLineEdit.setObjectName("sidewallSampleNominalDepthsPathLineEdit" + self.identifier)
        self.nominalDepthsPathLineEdit.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Readable
        self.nominalDepthsPathLineEdit.nameFilters = ("CSV (*.csv)",)
        self.nominalDepthsPathLineEdit.setToolTip("Input CSV file with nominal depths.")
        self.nominalDepthsPathLineEdit.settingKey = "ImageLogInstanceSegmenter/NominalDepthsPath"
        self.nominalDepthsPathLineEdit.setCurrentPath("")
        nominalDepthsCombo = self.nominalDepthsPathLineEdit.children()[3]
        nominalDepthsCombo.currentTextChanged.connect(self.onNominalDepthsPathChanged)
        parametersFormLayout.addRow("       Nominal depths file (CSV):", self.nominalDepthsPathLineEdit)

        self.depthThresholdFrame = qt.QFrame()
        depthThresholdLayout = qt.QFormLayout(self.depthThresholdFrame)
        depthThresholdLayout.setLabelAlignment(qt.Qt.AlignRight)
        depthThresholdLayout.setContentsMargins(0, 0, 0, 0)
        self.depthThresholdSpinBox = qt.QDoubleSpinBox()
        self.depthThresholdSpinBox.setObjectName("sidewallSampleDepthThresholdSpinBox" + self.identifier)
        self.depthThresholdSpinBox.setRange(0.1, 10)
        self.depthThresholdSpinBox.setDecimals(1)
        self.depthThresholdSpinBox.setSingleStep(0.1)
        self.depthThresholdSpinBox.setValue(float(self.getDepthThreshold()))
        self.depthThresholdSpinBox.setToolTip("Threshold to associate a nominal depth with an instance real depth.")
        depthThresholdLayout.addRow("Nominal depths threshold (m):", self.depthThresholdSpinBox)
        self.depthThresholdFrame.setVisible(False)
        parametersFormLayout.addRow(self.depthThresholdFrame)
        parametersFormLayout.addRow(" ", None)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.outputPrefixLineEdit = qt.QLineEdit()
        self.outputPrefixLineEdit.setObjectName("sidewallSampleOutputPrefixLineEdit" + self.identifier)
        outputFormLayout.addRow("Output prefix:", self.outputPrefixLineEdit)
        outputFormLayout.addRow(" ", None)
        reset_style_on_valid_text(self.outputPrefixLineEdit)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setObjectName("sidewallSampleApplyButton" + self.identifier)
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

    def onAmplitudeImageNodeChanged(self, itemId):
        amplitudeImage = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(itemId)
        if amplitudeImage:
            outputPrefix = amplitudeImage.GetName()
            if any(s in outputPrefix.lower() for s in ["tt", "transit", "time"]):
                slicer.util.warningDisplay(
                    "This input image appears to be a transit time image. Please check if it is the correct input."
                )
        else:
            outputPrefix = ""
        self.outputPrefixLineEdit.setText(outputPrefix)

    def onTransitTimeImageNodeChanged(self, itemId):
        transitTimeImage = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(itemId)
        if transitTimeImage:
            if any(s in transitTimeImage.GetName().lower() for s in ["amp", "amplitude"]):
                slicer.util.warningDisplay(
                    "This input image appears to be an amplitude image. Please check if it is the correct input."
                )

    def onNominalDepthsPathChanged(self, path):
        self.depthThresholdFrame.setVisible(path.strip() != "")

    def onApplyButtonClicked(self):
        try:
            if self.amplitudeImageNodeComboBox.currentNode() is None:
                highlight_error(self.amplitudeImageNodeComboBox)
                return
            if self.transitTimeImageNodeComboBox.currentNode() is None:
                highlight_error(self.transitTimeImageNodeComboBox)
                return
            if self.outputPrefixLineEdit.text.strip() == "":
                highlight_error(self.outputPrefixLineEdit)
                return

            nominalDepthsDataFrame = self.logic.readNominalDepthsCSV(self.nominalDepthsPathLineEdit.currentPath)
            save_path(self.nominalDepthsPathLineEdit)
            self.instanceSegmenterClass.set_setting("model", self.instanceSegmenterWidget.modelComboBox.currentData)
            self.instanceSegmenterClass.set_setting("depthThreshold", self.depthThresholdSpinBox.value)

            segmentParameters = self.SegmentParameters(
                model=self.instanceSegmenterWidget.modelComboBox.currentData,
                amplitudeImageNode=self.amplitudeImageNodeComboBox.currentNode(),
                transitTimeImageNode=self.transitTimeImageNodeComboBox.currentNode(),
                nominalDepthsDataFrame=nominalDepthsDataFrame,
                depthThreshold=float(self.depthThresholdSpinBox.value),
                outputPrefix=self.outputPrefixLineEdit.text,
                initialDepth=-1,
                finalDepth=-1,
            )
            self.logic.apply(segmentParameters)
        except MaskRCNNInfo as e:
            slicer.util.infoDisplay(str(e))
            return

    def onCancelButtonClicked(self):
        self.logic.cancel()


class SidewallSampleLogic:
    def __init__(self, progressBar):
        self.cliNode = None
        self.progressBar = progressBar
        self.outputLabelMapNodeId = None

    def readNominalDepthsCSV(self, csvFilePath):
        if csvFilePath.strip() == "":
            return None

        try:
            nominalDepthsDataFrame = read_csv(csvFilePath)
        except:
            raise MaskRCNNInfo("Invalid nominal depths file.")

        # stripping newlines from header
        nominalDepthsDataFrame.rename(columns=lambda x: re.sub("\n", "", x), inplace=True)
        # renaming prof
        nominalDepthsDataFrame.rename(columns=lambda x: re.sub("[P|p]rof(\s*\(m\))?", "n depth (m)", x), inplace=True)
        # renaming descida|corrida to desc
        nominalDepthsDataFrame.rename(columns=lambda x: re.sub("([D|d]escida)|([C|c]orrida)", "desc", x), inplace=True)
        # renaming condicao to cond
        nominalDepthsDataFrame.rename(columns=lambda x: re.sub("[C|c]ondicao", "cond", x), inplace=True)

        if "desc" not in nominalDepthsDataFrame:
            nominalDepthsDataFrame["desc"] = 0

        if "cond" not in nominalDepthsDataFrame:
            nominalDepthsDataFrame["cond"] = ""

        if "n depth (m)" not in nominalDepthsDataFrame.columns:
            raise MaskRCNNInfo("Invalid nominal depths file: depth column not found.")

        return nominalDepthsDataFrame

    def apply(self, p):
        amplitudeImageNode = p.amplitudeImageNode
        transitTimeImageNode = p.transitTimeImageNode
        initialDepth = p.initialDepth
        finalDepth = p.finalDepth
        self.model = p.model

        shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        self.itemParent = shNode.GetItemParent(shNode.GetItemByDataNode(amplitudeImageNode))

        outputLabelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        outputLabelMapNode.SetName(p.outputPrefix + "_Instances")
        outputLabelMapNode.SetAttribute("InstanceSegmenter", self.model)
        outputLabelMapNode.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
        outputLabelMapNode.HideFromEditorsOn()
        triggerNodeModified(outputLabelMapNode)
        self.outputLabelMapNodeId = outputLabelMapNode.GetID()

        shNode.SetItemParent(shNode.GetItemByDataNode(outputLabelMapNode), self.itemParent)

        self.outputParametersFile = Path(slicer.util.tempDirectory(key="instance-segmenter-cli")) / "output-parameters"

        self.nominalDepthsDataFrame = p.nominalDepthsDataFrame
        self.depthThreshold = p.depthThreshold
        self.outputPrefix = p.outputPrefix

        cliParams = {
            "model": p.model,
            "redChannelImage": amplitudeImageNode.GetID(),
            "greenChannelImage": transitTimeImageNode.GetID(),
            "outputLabelMapNode": self.outputLabelMapNodeId,
            "outputParametersFile": str(self.outputParametersFile),
            "gpuEnabled": is_tensorflow_gpu_enabled(),
        }

        self.cliNode = slicer.cli.run(slicer.modules.instancesegmentercli, None, cliParams)
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.instanceSegmenterCLICallback)

    def instanceSegmenterCLICallback(self, caller, event):
        if caller is None:
            self.cliNode = None
            return
        if self.cliNode is None:
            return
        status = caller.GetStatusString()
        if "Completed" in status or status == "Cancelled":
            logging.info(status)
            del self.cliNode
            self.cliNode = None
            outputLabelMapNode = tryGetNode(self.outputLabelMapNodeId)
            propertiesTableNode = None
            if status == "Completed":
                try:
                    array = slicer.util.arrayFromVolume(outputLabelMapNode)
                    # tripling the number of available colors on the color table, to account for adding/editing extra labels later
                    colorTable = labels_to_color_node(
                        3 * int(np.max(array)), outputLabelMapNode.GetName() + "_color_table"
                    )
                    outputLabelMapNode.GetDisplayNode().SetAndObserveColorNodeID(colorTable.GetID())

                    propertiesDataFrame = pd.read_pickle(str(self.outputParametersFile))
                    self.outputParametersFile.unlink(missing_ok=True)

                    if len(propertiesDataFrame.index) == 0:
                        slicer.mrmlScene.RemoveNode(outputLabelMapNode)
                        slicer.util.infoDisplay("No instances were detected.")
                        self.outputLabelMapNodeId = None
                        return

                    outputLabelMapNode.HideFromEditorsOff()
                    triggerNodeModified(outputLabelMapNode)

                    propertiesDataFrame = self.aggregateNominalToRealDepthsInformation(
                        self.nominalDepthsDataFrame, propertiesDataFrame, self.depthThreshold
                    )

                    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
                    propertiesTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
                    propertiesTableNode.SetName(self.outputPrefix + "_Instances_Report")
                    propertiesTableNode.SetAttribute("InstanceSegmenter", self.model)
                    propertiesTableNode.AddNodeReferenceID("InstanceSegmenterLabelMap", self.outputLabelMapNodeId)
                    shNode.SetItemParent(shNode.GetItemByDataNode(propertiesTableNode), self.itemParent)
                    dataFrameToTableNode(propertiesDataFrame, tableNode=propertiesTableNode)
                except Exception as error:
                    if outputLabelMapNode:
                        slicer.mrmlScene.RemoveNode(outputLabelMapNode)
                    if propertiesTableNode:
                        slicer.mrmlScene.RemoveNode(propertiesTableNode)
                    self.outputLabelMapNodeId = None
                    slicer.util.errorDisplay(
                        "A problem has occurred during the segmentation. Please check your input files."
                    )
                    logging.info(str(error))

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

    def aggregateNominalToRealDepthsInformation(self, nominalDepthsDataFrame, propertiesDataFrame, depthThreshold):
        if self.nominalDepthsDataFrame is not None:
            nominalToRealDepthsDataFrame = propertiesDataFrame

            # first reset_index and rename
            df_A = nominalDepthsDataFrame.reset_index().rename(columns={"index": "index_A"})
            df_B = nominalToRealDepthsDataFrame.reset_index().rename(columns={"index": "index_B"})

            delta = depthThreshold
            df_A["list_B"] = df_A["n depth (m)"].apply(
                lambda nominalDepth: df_B.index_B[
                    (nominalDepth - delta <= df_B["depth (m)"]) & (nominalDepth + delta >= df_B["depth (m)"])
                ].tolist()
            )

            # now use pd.Series and stack, with reset_index drop and rename, for finally merge
            df_C = (
                df_A.set_index(["index_A", "n depth (m)", "desc", "cond"])["list_B"]
                .apply(pd.Series, dtype="float64")
                .stack()
                .astype(int)
                .reset_index()
                .drop(columns="level_4")
                .rename(columns={0: "index_B"})
                .merge(df_B)
                .sort_values("index_A")
            )

            # Create the columns difference
            df_C["difference (m)"] = (df_C["n depth (m)"] - df_C["depth (m)"]).round(2)
            df_C["difference (m)"] = df_C["difference (m)"].abs()

            # add the info from df_A and df_B without corresponding in the other df
            df_C = pd.concat(
                [
                    pd.concat([df_C, df_A[~df_A["n depth (m)"].isin(df_C["n depth (m)"])].drop(columns="list_B")]),
                    df_B[~df_B["depth (m)"].isin(df_C["depth (m)"])],
                ]
            ).fillna(0)
            df_C["cond"].replace(0, "", inplace=True)

            df_C.drop(columns=["index_A", "index_B", "difference (m)"], inplace=True)
            df_C.reset_index(drop=True, inplace=True)
            df_C["desc"] = df_C["desc"].apply(lambda x: str(int(float(x))))
            df_C["label"] = df_C["label"].apply(lambda x: int(float(x)))

            zeroLabelsSeries = df_C.loc[df_C["label"] == 0, "label"]
            nextLabelValue = df_C["label"].max() + 1
            df_C.loc[df_C["label"] == 0, "label"] = list(range(nextLabelValue, nextLabelValue + len(zeroLabelsSeries)))
        else:
            df_C = propertiesDataFrame
            df_C["n depth (m)"] = 0.0
            df_C["desc"] = str(0)
            df_C["cond"] = ""

        df_C = df_C[
            ["depth (m)", "n depth (m)", "desc", "cond", "diam (cm)", "circularity", "solidity", "azimuth (°)", "label"]
        ]

        df_C.sort_values(by=["depth (m)", "n depth (m)"], inplace=True, ascending=True)
        df_C.reset_index(drop=True, inplace=True)

        return df_C

    def cancel(self):
        if self.cliNode is None:
            return
        self.cliNode.Cancel()


class MaskRCNNInfo(RuntimeError):
    pass
