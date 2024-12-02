import ctk
import markdown2 as markdown
import qt
import slicer
import logging
import os

from ltrace.slicer import helpers, ui
from ltrace.slicer.helpers import highlight_error, reset_style_on_valid_node
from ltrace.slicer.helpers import reset_style_on_valid_text
from ltrace.slicer.node_attributes import ImageLogDataSelectable
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer_utils import (
    dataframeFromTable,
    dataFrameToTableNode,
    LTracePlugin,
    LTracePluginWidget,
    LTracePluginLogic,
)
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from typing import List
from vtk.util.numpy_support import vtk_to_numpy
from ImageLogsLib.KdsOptimizationTableWidget import KdsOptimizationWidget
from pathlib import Path

ERROR_CORRECTION_NODE_NAME = "ERROR_CORRECTION_TABLE_NODE"

try:
    from Test.PermeabilityModelingTest import PermeabilityModelingTest
except ImportError:
    PermeabilityModelingTest = None


class PermeabilityModeling(LTracePlugin):
    SETTING_KEY = "PermeabilityModeling"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Permeability Modeling"
        self.parent.categories = ["Tools", "ImageLog"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = PermeabilityModeling.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PermeabilityModelingWidget(LTracePluginWidget):
    def __init__(self, parent=None):
        LTracePluginWidget.__init__(self, parent)

        self.__kdsOptimizationTableId = None

        self.logic = PermeabilityModelingLogic(parent)
        self.onOutputNodeReady = lambda volumes: None
        self.logic.processFinished.connect(self._onProcessFinished)

    def setup(self):
        LTracePluginWidget.setup(self)

        self.progressBar = None
        self.ioFileInputLineEdit = None
        self.depthLogNameLineEdit = None
        self.porosityLogNameLineEdit = None
        self.ioPlugFileInputLineEdit = None
        self.missingValuePlaceholderInput = None

        self.subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        self.inputSection()
        self.paramsSection()
        self.measurementSection()
        self.kdsOptimizationSection()
        self.outputSection()

        self.applyButton = ui.ButtonWidget(text="Apply", onClick=self.onApply)
        self.applyButton.objectName = "Apply Button"

        self.applyButton.setStyleSheet("QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 4px}")
        self.applyButton.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Preferred)

        self.progressBar = LocalProgressBar()

        self.layout.addWidget(self.applyButton)
        self.layout.addWidget(self.progressBar)
        self.layout.addStretch(1)

    @classmethod
    def help(cls):
        htmlHelp = ""
        with open(cls.readme_path(), "r", encoding="utf-8") as docfile:
            md = markdown.Markdown(extras=["fenced-code-blocks"])
            htmlHelp = md.convert(docfile.read())
        return htmlHelp

    @classmethod
    def readme_path(cls):
        dir_path = os.path.dirname(os.path.realpath(__file__))
        return str(dir_path + "/" + "PermeabilityModeling.md")

    def cleanup(self):
        LTracePluginWidget.cleanup(self)
        # # TO-DO (PL-2580): Fix dangling callback references for hierarchyVolumeInput and numericInput widgets.
        # # Remove the code below after the fix is merged.

    def _onProcessFinished(self, status: str) -> None:
        if status == "Completed":
            self.onComplete()
        elif status == "Cancelled":
            self.onCancelled()
        else:
            self.onCompletedWithErrors()

    def enter(self) -> None:
        self.__checkUniqueErrorCorrectionNode()

    def __checkUniqueErrorCorrectionNode(self):
        try:
            nodes = slicer.util.getNodes(ERROR_CORRECTION_NODE_NAME, useLists=True)
            nodes: List = list(nodes.values()) if nodes else []
        except slicer.util.MRMLNodeNotFoundException:
            # No error correction node detected
            self.__updateKdsOptimizationTable()
            return

        if not nodes:
            # Safe check for empty node list
            self.__kdsOptimizationTableId = None
            self.__updateKdsOptimizationTable()
            return

        nodes = nodes[0]
        if len(nodes) == 1:
            # Unique node detected
            node = nodes[0]
            self.__kdsOptimizationTableId = node.GetID()
            self.__updateKdsOptimizationTable()
            return

        # If there are more than one related node, remove the last one and keep the first one in the list
        for node in nodes[:]:
            if node.GetID() != self.__kdsOptimizationTableId:
                continue

            nodes.remove(node)
            slicer.mrmlScene.RemoveNode(node)
            break

        for node in nodes[1:]:
            # Safe check for multiple nodes with same ID
            slicer.mrmlScene.RemoveNode(node)
            del node

        self.__kdsOptimizationTableId = nodes[0].GetID()
        self.__updateKdsOptimizationTable()

    def __updateKdsOptimizationTable(self):
        try:
            if not self.kdsOptimizationWidget:
                return

            if self.__kdsOptimizationTableId is None:
                self.kdsOptimizationWidget.setTableData(None)
                return

            node = helpers.tryGetNode(self.__kdsOptimizationTableId)
            if node is None:
                self.kdsOptimizationWidget.setTableData(None)
                return

            df = dataframeFromTable(node)
            self.kdsOptimizationWidget.setTableData(df)

        except Exception as e:
            logging.error(f"Failed to update Kds Optimization Table, cause: {repr(e)}")

    def inputSection(self):
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Input Images"
        self.layout.addWidget(parametersCollapsibleButton)

        # Layout within the dummy collapsible button
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

        self._porosityLogInput = hierarchyVolumeInput(
            onChange=self.__onPorosityTableChanged, nodeTypes=["vtkMRMLTableNode"]
        )
        self._porosityLogInput.objectName = "Well Logs Input"

        reset_style_on_valid_node(self._porosityLogInput)
        self._porosityLogComboBox = qt.QComboBox()
        self._porosityLogComboBox.objectName = "Porosity Log Combo Box"
        reset_style_on_valid_node(self._porosityLogComboBox)
        self.segmentedImageInput = hierarchyVolumeInput(
            onChange=self.onSegmentedImageSelected, nodeTypes=["vtkMRMLSegmentationNode", "vtkMRMLLabelMapVolumeNode"]
        )
        self.segmentedImageInput.objectName = "Segmented Image Input"
        reset_style_on_valid_node(self.segmentedImageInput)

        parametersFormLayout.addRow("Well logs (.las):", self._porosityLogInput)
        parametersFormLayout.addRow("Porosity Log:", self._porosityLogComboBox)
        parametersFormLayout.addRow("Segmented Image:", self.segmentedImageInput)

    def __onPorosityTableChanged(self, node_id):
        node = self.subjectHierarchyNode.GetItemDataNode(node_id)

        if node is None:
            return

        logs = [node.GetColumnName(index) for index in range(node.GetNumberOfColumns())]
        if "DEPTH" not in logs:
            message = (
                "The selected table doesn't have a column related to the 'Depth' data."
                "\nPlease select another table or load a log file."
            )
            slicer.util.errorDisplay(message, windowTitle="Error", parent=slicer.modules.AppContextInstance.mainWindow)
            return

        logs.remove("DEPTH")
        # populate porosity log combo box
        self._porosityLogComboBox.clear()
        self._porosityLogComboBox.addItems(logs)

        self.__checkUniqueErrorCorrectionNode()

    def paramsSection(self):
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Parameters"
        self.layout.addWidget(parametersCollapsibleButton)

        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

        self.modelSelector = qt.QComboBox()
        self.modelSelector.enabled = False
        self.modelSelector.connect("currentIndexChanged(int)", lambda v: self.onNumericChanged("class1", v))
        self.modelSelector.objectName = "Macro Pore Segment Combo Box"

        self.missingSelector = qt.QComboBox()
        self.missingSelector.enabled = False
        self.missingSelector.connect("currentIndexChanged(int)", lambda v: self.onNumericChanged("nullable", v))
        self.missingSelector.objectName = "Ignored/null Segment Combo Box"

        parametersFormLayout.addRow("Macro Pore Segment: ", self.modelSelector)
        parametersFormLayout.addRow("Ignored/null Segment: ", self.missingSelector)

    def measurementSection(self):
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Reference Permeability"
        self.layout.addWidget(parametersCollapsibleButton)

        # Layout within the dummy collapsible button
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

        self._plugsPermeabilityTableComboBox = hierarchyVolumeInput(
            onChange=lambda i: self.__onPlugsPermeabilityTableChanged(i),
            nodeTypes=["vtkMRMLTableNode"],
        )
        reset_style_on_valid_node(self._plugsPermeabilityTableComboBox)
        self._plugsPermeabilityTableComboBox.objectName = "Plugs Measurements Input"
        self._plugsPermeabilityLogComboBox = qt.QComboBox()
        self._plugsPermeabilityLogComboBox.objectName = "Plugs Permeability Log Combo Box"
        parametersFormLayout.addRow("Plugs measurements:", self._plugsPermeabilityTableComboBox)
        parametersFormLayout.addRow("Plugs Permeability Log:", self._plugsPermeabilityLogComboBox)

    def kdsOptimizationSection(self):
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Kds Optimization"
        self.layout.addWidget(parametersCollapsibleButton)

        # Layout within the dummy collapsible button
        parametersFormLayout = qt.QVBoxLayout(parametersCollapsibleButton)

        self.kdsOptimizationWidget = KdsOptimizationWidget()
        self.kdsOptimizationWidget.tableUpdated.connect(self.storeKdsOptimizationTable)
        self.kdsOptimizationWidget.objectName = "Kds Optimization Widget"
        self.kdsOptimizationWidget.table.objectName = "Kds Optimization Table"
        self.kdsOptimizationWidget.addButton.objectName = "Kds Optimization Add Button"
        self.kdsOptimizationWidget.removeButton.objectName = "Kds Optimization Remove Button"
        self.kdsOptimizationWidget.weightSpinBox.objectName = "Kds Optimization Weight Spin Box"
        parametersFormLayout.addWidget(self.kdsOptimizationWidget)

    def storeKdsOptimizationTable(self, df):
        node = helpers.tryGetNode(ERROR_CORRECTION_NODE_NAME)
        if node is None:
            node = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__, ERROR_CORRECTION_NODE_NAME)
            node.SetHideFromEditors(True)

        node.RemoveAllColumns()
        dataFrameToTableNode(df, node)
        node.Modified()
        self.__kdsOptimizationTableId = node.GetID()

    def __onPlugsPermeabilityTableChanged(self, node_id):
        node = self.subjectHierarchyNode.GetItemDataNode(node_id)

        if node is None:
            return

        logs = [node.GetColumnName(index) for index in range(node.GetNumberOfColumns())]
        if "DEPTH" not in logs:
            message = (
                "The selected table doesn't have a column related to the 'Depth' data."
                "\nPlease select another table or load a log file."
            )
            slicer.util.errorDisplay(message, windowTitle="Error", parent=slicer.modules.AppContextInstance.mainWindow)
            return

        logs.remove("DEPTH")
        # Populate porosity log combo box
        self._plugsPermeabilityLogComboBox.clear()
        self._plugsPermeabilityLogComboBox.addItems(logs)

    def outputSection(self):
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Output"
        self.layout.addWidget(parametersCollapsibleButton)

        self.outputNameLineEdit = qt.QLineEdit()
        reset_style_on_valid_text(self.outputNameLineEdit)
        self.outputNameLineEdit.setToolTip("Type the text to be used as the output node's name.")
        self.outputNameLineEdit.objectName = "Output Name Line Edit"

        # Layout within the dummy collapsible button
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.addRow("Output Name: ", self.outputNameLineEdit)

    def setDefaults(self, **kwargs):
        pass

    def onPLUGPathChanged(self, p):
        self.onTextChanged("file", p)

    def onApply(self):
        if self._porosityLogInput.currentNode() is None:
            highlight_error(self._porosityLogInput)
            return

        if self._porosityLogComboBox.currentText == "":
            highlight_error(self._porosityLogComboBox)
            return

        if self.segmentedImageInput.currentNode() is None:
            highlight_error(self.segmentedImageInput)
            return

        if self._plugsPermeabilityTableComboBox.currentNode() is None:
            highlight_error(self._plugsPermeabilityTableComboBox)
            return

        if self.outputNameLineEdit.text.strip() == "":
            highlight_error(self.outputNameLineEdit)
            return

        self.logic.model["outputVolumeName"] = self.outputNameLineEdit.text

        # Update model parameters

        kdsOptimizationTable = helpers.tryGetNode(ERROR_CORRECTION_NODE_NAME)

        porosityLogScalarNode = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLScalarVolumeNode, "POROSITY_LOG_TMP_NODE", hidden=True
        )
        porosityDepthScalarNode = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLScalarVolumeNode, "POROSITY_DEPTH_TMP_NODE", hidden=True
        )
        permeabilityPlugLogScalarNode = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLScalarVolumeNode, "PERMEABILITY_PLUG_TMP_NODE", hidden=True
        )
        permeabilityPlugDepthScalarNode = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLScalarVolumeNode, "PERMEABILITY_PLUG_DEPTH_TMP_NODE", hidden=True
        )
        permeabilityOutput = slicer.mrmlScene.AddNewNodeByClass(
            slicer.vtkMRMLTableNode.__name__, self.logic.model["outputVolumeName"]
        )
        permeabilityOutput.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)

        porosityLogTableNode = self.subjectHierarchyNode.GetItemDataNode(self._porosityLogInput.currentItem())
        porosityLogArray = vtk_to_numpy(
            porosityLogTableNode.GetTable().GetColumnByName(self._porosityLogComboBox.currentText)
        )
        porosityDepthArray = vtk_to_numpy(porosityLogTableNode.GetTable().GetColumnByName("DEPTH"))

        permeabilityPlugLogTableNode = self.subjectHierarchyNode.GetItemDataNode(
            self._plugsPermeabilityTableComboBox.currentItem()
        )
        permeabilityPlugLogArray = vtk_to_numpy(
            permeabilityPlugLogTableNode.GetTable().GetColumnByName(self._plugsPermeabilityLogComboBox.currentText)
        )
        permeabilityPlugDepthArray = vtk_to_numpy(permeabilityPlugLogTableNode.GetTable().GetColumnByName("DEPTH"))

        porosityLogArray = porosityLogArray.reshape(porosityLogArray.shape[0], 1, 1)
        porosityDepthArray = porosityDepthArray.reshape(porosityDepthArray.shape[0], 1, 1)
        permeabilityPlugLogArray = permeabilityPlugLogArray.reshape(permeabilityPlugLogArray.shape[0], 1, 1)
        permeabilityPlugDepthArray = permeabilityPlugDepthArray.reshape(permeabilityPlugDepthArray.shape[0], 1, 1)

        slicer.util.updateVolumeFromArray(porosityLogScalarNode, porosityLogArray)
        slicer.util.updateVolumeFromArray(porosityDepthScalarNode, porosityDepthArray)
        slicer.util.updateVolumeFromArray(permeabilityPlugLogScalarNode, permeabilityPlugLogArray)
        slicer.util.updateVolumeFromArray(permeabilityPlugDepthScalarNode, permeabilityPlugDepthArray)

        self.logic.model["log_por"] = porosityLogScalarNode.GetID()
        self.logic.model["depth_por"] = porosityDepthScalarNode.GetID()
        self.logic.model["perm_plugs"] = permeabilityPlugLogScalarNode.GetID()
        self.logic.model["depth_plugs"] = permeabilityPlugDepthScalarNode.GetID()
        self.logic.model["outputVolume"] = permeabilityOutput.GetID()
        self.logic.model["kdsOptimizationTable"] = (
            kdsOptimizationTable.GetID() if kdsOptimizationTable is not None else None
        )
        self.logic.model["kdsOptimizationWeight"] = self.kdsOptimizationWidget.weightSpinBox.value

        task = self.logic.run()
        if task:
            self.progressBar.setCommandLineModuleNode(task)

    def onCancel(self):
        self.logic.cancelCLI()

    def onSegmentedImageSelected(self, itemId):
        node = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        volumeNode = node.GetItemDataNode(itemId)

        if volumeNode is None or (
            not volumeNode.IsA(slicer.vtkMRMLLabelMapVolumeNode.__name__)
            and not volumeNode.IsA(slicer.vtkMRMLSegmentationNode.__name__)
        ):
            self.logic.model["inputVolume1"] = None
            self.modelSelector.enabled = False
            self.missingSelector.enabled = False
            self.__checkUniqueErrorCorrectionNode()
            return

        self.modelSelector.clear()
        self.missingSelector.clear()

        segmentsDict = helpers.extractLabels(volumeNode)

        for selector in [self.modelSelector, self.missingSelector]:
            selector.addItems(list(segmentsDict.values()))

        self.logic.model["inputVolume1"] = volumeNode.GetID()
        self.outputNameLineEdit.setText(f"{volumeNode.GetName()}_Permeability_Output")
        self.modelSelector.enabled = True
        self.missingSelector.enabled = True
        self.__checkUniqueErrorCorrectionNode()

    def onNumericChanged(self, key, value):
        self.logic.model[key] = value

    def onTextChanged(self, key, value):
        self.logic.model[key] = str(value)

    def onComplete(self):
        self.removeTemporaryNodes()

        outputNodeId = self.logic.model["outputVolume"]
        self.onOutputNodeReady([self.logic.model["outputVolume"]])

        outputNode = helpers.tryGetNode(outputNodeId)
        helpers.autoDetectColumnType(outputNode)

    def onCompletedWithErrors(self):
        self.removeTemporaryNodes()

    def onCancelled(self):
        self.removeTemporaryNodes()

    def removeTemporaryNodes(self):
        temp_nodes_name = [
            "POROSITY_LOG_TMP_NODE",
            "POROSITY_DEPTH_TMP_NODE",
            "PERMEABILITY_PLUG_TMP_NODE",
            "PERMEABILITY_PLUG_DEPTH_TMP_NODE",
        ]
        for node_name in temp_nodes_name:
            node = helpers.tryGetNode(node_name)
            if node is None:
                continue

            slicer.mrmlScene.RemoveNode(node)


class PermeabilityModelingLogic(LTracePluginLogic):
    processFinished = qt.Signal(object)

    def __init__(self, parent):
        LTracePluginLogic.__init__(self, parent)
        self.model = PermeabilityModelingModel()
        self.cliNode = None

    def cancelCLI(self):
        if self.cliNode:
            self.cliNode.Cancel()
            self.cliNode = None

    def eventHandler(self, caller, event):
        if self.cliNode is None:
            return

        status = caller.GetStatusString()
        try:
            if status == "Completed":
                self.cliNode = None
                self.processFinished.emit(status)
            elif "Completed" in status:
                self.cliNode = None
                self.processFinished.emit(status)
            elif status == "Cancelled":
                self.cliNode = None
                self.processFinished.emit(status)
        except Exception as e:
            logging.info(f'Exception on Event Handler: {repr(e)} with status "{status}"')
            self.processFinished.emit("Completed with Errors")

    def run(self):
        self.cliNode = slicer.cli.run(
            slicer.modules.permeabilitymodelingcli,
            None,
            {k: v for k, v in self.model.items()},
            wait_for_completion=False,
        )

        self.cliNode.AddObserver("ModifiedEvent", lambda c, e: self.eventHandler(c, e))
        return self.cliNode


def PermeabilityModelingModel():
    return dict(
        log_por=None,
        depth_por=None,
        inputVolume1=None,
        class1=1,
        depth_plugs=None,
        perm_plugs=None,
        outputVolume=None,
        nullable=0,
        outputVolumeName=None,
        kdsOptimizationTable=None,
        kdsOptimizationWeight=None,
    )
