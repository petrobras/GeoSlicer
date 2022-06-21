import logging
import os
import re
from pathlib import Path

import ctk
import numexpr as ne
import numpy as np
import qt
import slicer

from ltrace.slicer.helpers import tryGetNode, reset_style_on_valid_text, highlight_error
from ltrace.slicer_utils import *
from ltrace.transforms import resample_if_needed

# Checks if closed source code is available
try:
    from Test.VolumeCalculatorTest import VolumeCalculatorTest
except ImportError:
    VolumeCalculatorTest = None  # tests not deployed to final version or closed source


class VolumeCalculator(LTracePlugin):
    SETTING_KEY = "VolumeCalculator"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Volume Calculator"
        self.parent.categories = ["LTrace Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = VolumeCalculator.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class VolumeCalculatorWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = VolumeCalculatorLogic()

        import SubjectHierarchyPlugins

        scriptedPlugin = slicer.qSlicerSubjectHierarchyScriptedPlugin(None)
        scriptedPlugin.setPythonSource(SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin.filePath)

        dataWidget = slicer.modules.data.createNewWidgetRepresentation()

        qFrame = qt.QFrame()
        qFormLayout = qt.QFormLayout(qFrame)
        qFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout.addWidget(qFrame)

        # Filter
        filberLabel = dataWidget.findChild(qt.QObject, "FilterLabel")
        filterLineEdit = dataWidget.findChild(qt.QObject, "FilterLineEdit")
        hBoxLayout = qt.QHBoxLayout()
        hBoxLayout.setContentsMargins(3, 0, 0, 0)
        hBoxLayout.addWidget(filberLabel)
        hBoxLayout.addWidget(filterLineEdit)
        frame = qt.QFrame()
        frame.setLayout(hBoxLayout)
        qFormLayout.addRow(frame)

        # Show transforms set to False
        qtTabwidgetStackedwidget = dataWidget.findChild(qt.QObject, "qt_tabwidget_stackedwidget")
        subjectHierarchyDisplayTransformsCheckBox = qtTabwidgetStackedwidget.findChild(
            qt.QObject, "SubjectHierarchyDisplayTransformsCheckBox"
        )
        subjectHierarchyDisplayTransformsCheckBox.checked = False

        self.subjectHierarchyTreeView = dataWidget.findChild(qt.QObject, "SubjectHierarchyTreeView")
        self.subjectHierarchyTreeView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.subjectHierarchyTreeView.hideColumn(3)
        qFormLayout.addRow(self.subjectHierarchyTreeView)
        qFormLayout.addRow(" ", None)
        self.subjectHierarchyTreeView.doubleClicked.connect(self.doubleClicked)

        mnemonicsCollapsibleButton = ctk.ctkCollapsibleButton()
        mnemonicsCollapsibleButton.text = "Mnemonics"
        mnemonicsCollapsibleButton.collapsed = True
        qFormLayout.addRow(mnemonicsCollapsibleButton)
        mnemonicsFormLayout = qt.QFormLayout(mnemonicsCollapsibleButton)

        self.mnemonicSelector = slicer.qMRMLNodeComboBox()
        self.mnemonicSelector.setObjectName("mnemonicSelector")
        self.mnemonicSelector.nodeTypes = ["vtkMRMLTableNode"]
        self.mnemonicSelector.setNodeTypeLabel("Mnemonic Table", "vtkMRMLTableNode")
        self.mnemonicSelector.noneEnabled = True
        self.mnemonicSelector.renameEnabled = True
        self.mnemonicSelector.showHidden = False
        self.mnemonicSelector.showChildNodeTypes = False
        self.mnemonicSelector.setMRMLScene(slicer.mrmlScene)
        self.mnemonicSelector.setToolTip("Pick a mnemonic table to use in the calculations")
        self.mnemonicSelector.currentNodeChanged.connect(self.mnemonicChanged)
        self.mnemonicSelector.currentNodeRenamed.connect(self.configureTableView)
        mnemonicsFormLayout.addRow("Mnemonic Table:", self.mnemonicSelector)

        self.mnemonicTableView = slicer.qMRMLTableView()
        self.mnemonicTableView.setMRMLScene(slicer.mrmlScene)
        self.mnemonicTableView.tableModel().itemChanged.connect(self.configureTableViewHeader)
        self.configureTableView()
        mnemonicsFormLayout.addRow(self.mnemonicTableView)

        self.addMnemonicButton = qt.QPushButton("Add mnemonic")
        self.addMnemonicButton.setFixedHeight(40)
        self.addMnemonicButton.clicked.connect(self.onAddMnemonicButtonClicked)
        self.removeMnemonicButton = qt.QPushButton("Remove selected mnemonics")
        self.removeMnemonicButton.setFixedHeight(40)
        self.removeMnemonicButton.clicked.connect(self.onRemoveMnemonicButtonClicked)
        mnemonicButtonsHBoxLayout = qt.QHBoxLayout()
        mnemonicButtonsHBoxLayout.addWidget(self.addMnemonicButton)
        mnemonicButtonsHBoxLayout.addWidget(self.removeMnemonicButton)
        mnemonicsFormLayout.addRow(mnemonicButtonsHBoxLayout)
        mnemonicsFormLayout.addRow(" ", None)

        self.formulaLineEdit = qt.QLineEdit()
        self.formulaLineEdit.setObjectName("formulaLineEdit")
        self.formulaLineEdit.setToolTip(
            "Formula input. The volumes names must be between underscores (e.g. Volume_1 must be inserted as _Volume_1_"
            "). Double clicking the volume in the selection area will do this automatically."
        )
        reset_style_on_valid_text(self.formulaLineEdit)
        qFormLayout.addRow("Formula:", self.formulaLineEdit)

        self.outputVolumeLineEdit = qt.QLineEdit()
        self.outputVolumeLineEdit.setObjectName("outputVolumeLineEdit")
        self.outputVolumeLineEdit.setToolTip("Volume name to save the calculation results")
        reset_style_on_valid_text(self.outputVolumeLineEdit)
        qFormLayout.addRow("Output volume name:", self.outputVolumeLineEdit)

        self.calculatePushButton = qt.QPushButton("Calculate")
        self.calculatePushButton.setObjectName("calculatePushButton")
        self.calculatePushButton.setFixedHeight(40)
        qFormLayout.addRow(" ", None)
        qFormLayout.addRow(self.calculatePushButton)

        self.statusLabel = qt.QLabel()
        self.statusLabel.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        self.statusLabel.hide()
        qFormLayout.addRow(self.statusLabel)

        self.calculatePushButton.clicked.connect(self.onCalculatePushButtonClicked)
        self.formulaLineEdit.returnPressed.connect(self.onCalculatePushButtonClicked)
        self.outputVolumeLineEdit.returnPressed.connect(self.onCalculatePushButtonClicked)

    def configureTableViewHeader(self):
        # This is needed because of a bug resetting the header columns names
        self.mnemonicTableView.tableModel().setHorizontalHeaderLabels(["Volume name", "Mnemonic"])

    def onAddMnemonicButtonClicked(self):
        self.mnemonicTableView.insertRow()
        self.configureTableView()

    def onRemoveMnemonicButtonClicked(self):
        self.mnemonicTableView.deleteRow()
        self.configureTableView()

    def mnemonicChanged(self, node):
        self.mnemonicTableView.setMRMLTableNode(node)
        if node is not None and node.GetNumberOfColumns() == 0:  # New mnemonic table being created
            self.configureNodeMetadata(node)
            self.mnemonicTableView.insertColumn()
            self.mnemonicTableView.insertColumn()
            self.mnemonicTableView.insertRow()
        self.configureTableView()

    def configureNodeMetadata(self, node):
        node.SetName("Mnemonic " + node.GetName())
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        rootDirID = subjectHierarchyNode.GetItemByName("Volume Calculator Mnemonics")
        if rootDirID == 0:
            rootDirID = subjectHierarchyNode.CreateFolderItem(
                subjectHierarchyNode.GetSceneItemID(), "Volume Calculator Mnemonics"
            )
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(node),
            rootDirID,
        )

    def configureTableView(self):
        self.mnemonicTableView.setFirstRowLocked(True)
        self.mnemonicTableView.tableModel().setHorizontalHeaderLabels(["Volume name", "Mnemonic"])
        self.mnemonicTableView.setColumnWidth(1, 160)
        self.mnemonicTableView.horizontalHeader().setSectionResizeMode(0, qt.QHeaderView.Stretch)
        self.mnemonicTableView.setFocusPolicy(qt.Qt.NoFocus)
        self.mnemonicTableView.setSelectionBehavior(self.mnemonicTableView.SelectRows)

    def doubleClicked(self):
        itemID = self.subjectHierarchyTreeView.currentItem()
        node = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene).GetItemDataNode(itemID)
        mnemonicsDict = self.logic.getMnemonicsDictFromMnemonicsTableNode(self.mnemonicSelector.currentNode())
        if (
            type(node) is slicer.vtkMRMLScalarVolumeNode
            or type(node) is slicer.vtkMRMLVectorVolumeNode
            or type(node) is slicer.vtkMRMLLabelMapVolumeNode
        ):
            try:
                self.formulaLineEdit.insert("{" + mnemonicsDict[node.GetName()] + "}")
            except KeyError:
                # If there is no matching mnemonic, insert the node name
                self.formulaLineEdit.insert("{" + node.GetName() + "}")

    def onCalculatePushButtonClicked(self):
        self.statusLabel.setText("Status: Running")
        self.statusLabel.show()
        slicer.app.processEvents()
        formulaString = self.formulaLineEdit.text
        outputVolumeName = self.outputVolumeLineEdit.text
        try:
            error = False

            if self.formulaLineEdit.text.strip() == "":
                highlight_error(self.formulaLineEdit)
                error = True

            if self.outputVolumeLineEdit.text.strip() == "":
                highlight_error(self.outputVolumeLineEdit)
                error = True

            if error:
                return

            self.logic.calculate(formulaString, outputVolumeName, self.mnemonicSelector.currentNode())
            self.statusLabel.setText("Status: Completed")
            logging.info("Calculation completed.")
        except CalculateInfo as e:
            self.statusLabel.setText("Status: Completed")
            logging.warning(str(e))
        except CalculateError as e:
            self.statusLabel.setText("Status: Error")
            logging.error(str(e))
        except slicer.util.MRMLNodeNotFoundException as e:
            self.statusLabel.setText("Status: Error")
            logging.error("Invalid volume name: " + str(e) + ".")
        except KeyError as e:
            self.statusLabel.setText("Status: Error")
            logging.error("Invalid formula.")


class VolumeCalculatorLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def calculate(self, formulaString, outputVolumeName, mnemonicsTableNode):
        variablesNamesList = re.findall(r"\{(.*?)\}", formulaString)
        mnemonicsDict = self.getMnemonicsDictFromMnemonicsTableNode(mnemonicsTableNode)
        nodeNamesList = self.getNodeNamesFromVariablesNames(variablesNamesList, mnemonicsDict)

        if nodeNamesList:
            resampleNeeded = False

            # The reference node (the first node in the formula), where the resample/clipping will be based if applied
            baseNode = tryGetNode(nodeNamesList[0])

            # Doing resample if necessary
            for i, nodeName in enumerate(nodeNamesList):
                node = tryGetNode(nodeName)

                if node is None:
                    raise CalculateError(f"Invalid node name: {nodeName}")

                resampledVolume = None
                if i > 0:  # skipping resample of the base node on itself
                    resampledVolume = slicer.mrmlScene.AddNewNodeByClass(node.GetClassName())
                    resamplePerformed = resample_if_needed(
                        input_volume=node, reference_volume=baseNode, output_volume=resampledVolume
                    )
                    if resamplePerformed:
                        node = resampledVolume

                array = slicer.util.arrayFromVolume(node)
                exec(node.GetID() + "=array", locals())

                slicer.mrmlScene.RemoveNode(resampledVolume)

                # Replace both cases: if the user used the node name as variable, or if he used its mnemonic
                formulaString = formulaString.replace("{" + nodeName + "}", node.GetID())
                formulaString = formulaString.replace(
                    "{" + self.getVariableNameFromNodeName(nodeName, mnemonicsDict) + "}", node.GetID()
                )
            try:
                outputArray = ne.evaluate(formulaString) * 1
            except (TypeError, SyntaxError) as e:
                raise CalculateError("Invalid formula.")

            outputVolume = tryGetNode(outputVolumeName)
            if outputVolume is None:
                firstFormulaInputVolume = tryGetNode(nodeNamesList[0])
                outputVolume = self.cloneVolumeProperties(firstFormulaInputVolume, outputVolumeName)
                subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
                itemParent = subjectHierarchyNode.GetItemParent(
                    subjectHierarchyNode.GetItemByDataNode(firstFormulaInputVolume)
                )
                subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(outputVolume), itemParent)
            slicer.util.updateVolumeFromArray(outputVolume, outputArray)
            slicer.util.setSliceViewerLayers(background=outputVolume)
            slicer.util.resetSliceViews()

            if resampleNeeded:
                raise CalculateInfo(
                    "Calculation completed. Temporary resample was used in some volumes to match the first one in the formula."
                )
        else:
            raise CalculateError("No volumes were detected in the formula.")

    def resample(self, volume, resampledVolume, referenceVolume):
        parameters = {
            "inputVolume": volume.GetID(),
            "outputVolume": resampledVolume.GetID(),
            "referenceVolume": referenceVolume.GetID(),
        }
        slicer.cli.runSync(slicer.modules.resamplescalarvectordwivolume, None, parameters)

    def clipArray(self, array, minimumArrayShape):
        clippedArray = array[: minimumArrayShape[0], : minimumArrayShape[1], : minimumArrayShape[2]]
        return clippedArray

    def cloneVolumeProperties(self, volume, newVolumeName):
        newVolume = slicer.mrmlScene.AddNewNodeByClass(volume.GetClassName(), newVolumeName)
        newVolume.SetOrigin(volume.GetOrigin())
        newVolume.SetSpacing(volume.GetSpacing())
        directions = np.eye(3)
        volume.GetIJKToRASDirections(directions)
        newVolume.SetIJKToRASDirections(directions)

        displayNode = volume.GetDisplayNode()
        newVolume.CreateDefaultDisplayNodes()
        newVolume.CreateDefaultStorageNode()
        if issubclass(type(displayNode), slicer.vtkMRMLScalarVolumeDisplayNode):
            newVolumeDisplayNode = newVolume.GetDisplayNode()
            newVolumeDisplayNode.AutoWindowLevelOff()
            newVolumeDisplayNode.SetWindowLevel(displayNode.GetWindow(), displayNode.GetLevel())
        return newVolume

    def getMnemonicsDictFromMnemonicsTableNode(self, mnemonicsTableNode):
        mnemonicsDict = {}
        if mnemonicsTableNode is not None:
            for i in range(mnemonicsTableNode.GetNumberOfRows()):
                mnemonicsDict[mnemonicsTableNode.GetCellText(i, 0)] = mnemonicsTableNode.GetCellText(i, 1)
        return mnemonicsDict

    def getNodeNamesFromVariablesNames(self, variablesNames, mnemonicsDict):
        nodeNamesDict = {v: k for k, v in mnemonicsDict.items()}
        nodeNames = []
        for variableName in variablesNames:
            try:
                nodeName = nodeNamesDict[variableName]
            except KeyError:
                nodeName = variableName
            nodeNames.append(nodeName)
        return nodeNames

    def getVariableNameFromNodeName(self, nodeName, mnemonicsDict):
        try:
            variableName = mnemonicsDict[nodeName]
        except KeyError:
            variableName = nodeName
        return variableName


class CalculateInfo(RuntimeError):
    pass


class CalculateError(RuntimeError):
    pass
