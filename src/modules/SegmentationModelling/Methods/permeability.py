import json
import numpy as np
import qt
import slicer

from ltrace.slicer import helpers, ui, widgets
from Methods.common import processVolume, processSegmentation


def createEquationInput(objectName, callback):
    equation_input = ui.hierarchyVolumeInput(nodeTypes=["vtkMRMLTableNode"])
    equation_input.objectName = objectName
    equation_input.addNodeAttributeIncludeFilter("table_type", "equation")
    equation_input.currentItemChanged.connect(callback(equation_input))
    return equation_input


class Permeability(widgets.BaseSettingsWidget):
    METHOD = "permeability"
    DISPLAY_NAME = "Permeability Map"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.segmentEquationDict = {}
        self.inputWidget = widgets.SingleShotInputWidget(
            mainName="Segmentation (optional)",
            referenceName="Porosity Map",
            dependentInputs=None,
            autoReferenceFetch=False,
            checkable=False,
        )
        self.inputWidget.objectName = f"{self.DISPLAY_NAME} Single Shot Input Widget"
        self.segments_layout = qt.QFormLayout()

        layout = qt.QVBoxLayout(self)
        layout.addWidget(self.inputWidget)
        layout.addLayout(self.segments_layout)

    def onSelect(self):
        return

    def shrink(self):
        return

    def clearPlotData(self):
        """Maintain interface with the other method"""
        pass

    def onSegmentationChanged(self, node):
        self.updateEquationInputs()

        referenceNode = self.inputWidget.referenceInput.currentNode()
        if referenceNode is None:
            helpers.highlight_error(self.inputWidget.referenceInput, widget_name="QComboBox")

    def onSoiChanged(self, node):
        pass

    def onReferenceChanged(self, node, status):
        if len(self.segmentEquationDict) == 0:
            self.updateEquationInputs()

    def updateEquationInputs(self):
        self.cleanEquationInputs()

        segmentationNode = self.inputWidget.mainInput.currentNode()

        if segmentationNode is None:
            # create global equation input
            equation_input = createEquationInput(
                f"{self.DISPLAY_NAME} Global Equation ComboBox", self.__createEquationInputChangedCallback
            )
            self.segmentEquationDict["global-ltrace-eq"] = equation_input
            self.segments_layout.addRow("Global Equation: ", equation_input)
        else:
            referenceNode = self.inputWidget.referenceInput.currentNode()
            soiNode = self.inputWidget.soiInput.currentNode()

            segmentsDict = helpers.getSegmentList(node=segmentationNode, roiNode=soiNode, refNode=referenceNode)
            segmentNames = [segment["name"] for segment in segmentsDict.values()]

            for segment_name in segmentNames:
                equation_input = createEquationInput(
                    f"{self.DISPLAY_NAME} {segment_name} Equation ComboBox",
                    self.__createEquationInputChangedCallback,
                )
                self.segmentEquationDict[segment_name] = equation_input
                self.segments_layout.addRow(segment_name + ": ", equation_input)

    def cleanEquationInputs(self):
        # Disengage the signal to avoid triggering the onSegmentationChanged method
        # hide the comboboxes
        # renew the references, to avoid being found before being deleted (because deleteLater is asynchronous)
        for segmentName, equationInput in self.segmentEquationDict.items():
            equationInput.currentItemChanged.disconnect()
            equationInput.hide()
            equationInput.objectName = "Deleted Equation ComboBox"

        self.segmentEquationDict = {}
        helpers.clear_layout(self.segments_layout)

    def validatePrerequisites(self):

        if self.inputWidget.referenceInput.currentNode() is None:
            slicer.util.errorDisplay("Please select a Porosity Map")
            return False

        missingEquation = False
        for segmentName, equationInput in self.segmentEquationDict.items():
            if equationInput.currentNode() is None:
                self.__setEquationInputState(equationInput, widgets.InputState.MISSING)
                missingEquation = True
                print(f"Missing equation for segment {segmentName} on {equationInput} ({equationInput.objectName})")

        return not missingEquation

    def apply(self, outputPrefix):
        referenceNode = self.inputWidget.referenceInput.currentNode()
        segmentationNode = self.inputWidget.mainInput.currentNode()
        soiNode = self.inputWidget.soiInput.currentNode()

        procrRefNode = processVolume(referenceNode, soiNode)

        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemTreeId = folderTree.GetItemByDataNode(referenceNode)
        parentItemId = folderTree.GetItemParent(itemTreeId)
        outputDir = folderTree.GetItemChildWithName(parentItemId, "Modelling Results")
        if outputDir == 0:
            outputDir = folderTree.CreateFolderItem(parentItemId, helpers.generateName(folderTree, "Modelling Results"))
        common_params = {
            "parent": self,
            "output_prefix": outputPrefix,
            "output_dir": outputDir,
        }
        if segmentationNode is not None:
            procLabelsNode, reverseMapping = processSegmentation(segmentationNode, referenceNode, soiNode)

            logicSegmentEquationDict = {}
            for segmentName, equationInput in self.segmentEquationDict.items():
                segmentId = self.__getSegmentIdFromName(segmentName, reverseMapping)
                logicSegmentEquationDict[segmentId] = slicer.util.dataframeFromTable(
                    equationInput.currentNode()
                ).to_json()

            common_params["inputNodeId"] = procrRefNode.GetID()
            common_params["labelMapNodeId"] = procLabelsNode.GetID()
            common_params["segmentEquationDict"] = logicSegmentEquationDict
            common_params["soiNodeId"] = soiNode.GetID() if soiNode else None

        else:  # no segmentation node, use one global equation
            procLabelsNode = helpers.createTemporaryVolumeNode(
                slicer.vtkMRMLLabelMapVolumeNode, "temp_", content=procrRefNode
            )

            segmentId = 1
            arr = slicer.util.arrayFromVolume(procLabelsNode)
            arr[:] = segmentId
            slicer.util.updateVolumeFromArray(procLabelsNode, arr)

            logicSegmentEquationDict = {
                segmentId: slicer.util.dataframeFromTable(
                    self.segmentEquationDict["global-ltrace-eq"].currentNode()
                ).to_json()
            }

            common_params["inputNodeId"] = procrRefNode.GetID()
            common_params["labelMapNodeId"] = procLabelsNode.GetID()
            common_params["segmentEquationDict"] = logicSegmentEquationDict
            common_params["soiNodeId"] = soiNode.GetID() if soiNode else None

        return PermeabilityLogic(**common_params)

    @staticmethod
    def __getSegmentIdFromName(segmentName, invmap):
        for id, name, color in invmap:
            if name == segmentName:
                return id
        return None

    @staticmethod
    def __setEquationInputState(equationInput, state):
        color = widgets.get_input_widget_color(state)
        equationInput.blockSignals(True)
        if color:
            equationInput.setStyleSheet("QComboBox { background-color: " + color + "; }")
            equationInput.clearSelection()
        else:
            equationInput.setStyleSheet("")
        equationInput.blockSignals(False)

    @staticmethod
    def __createEquationInputChangedCallback(equationInput):
        def callback(text):
            Permeability.__setEquationInputState(equationInput, widgets.InputState.OK)

        return callback


class PermeabilityLogic(qt.QObject):
    signalProcessEnded = qt.Signal()

    def __init__(
        self, parent, inputNodeId, labelMapNodeId, segmentEquationDict, output_prefix, output_dir, soiNodeId=None
    ):
        super().__init__(parent)

        self.__inputNodeId = inputNodeId
        self.__labelMapNodeId = labelMapNodeId
        self.__segmentEquationDict = segmentEquationDict
        self.__outputPrefix = output_prefix
        self.__outputDir = output_dir
        self.__soiNodeId = soiNodeId

        self._cliNode = None
        self.__cliNodeModifiedObserver = None

    def apply(self, progressBar=None):
        outputVolume = helpers.createOutput(
            prefix=self.__outputPrefix + "_{type}",
            where=self.__outputDir,
            ntype="PermeabilityMap",
            builder=lambda n: helpers.createTemporaryNode(
                cls=slicer.vtkMRMLScalarVolumeNode,
                name=n,
                environment=self.__class__.__name__,
                hidden=True,
            ),
        )
        cliConfig = {
            "input_volume": self.__inputNodeId,
            "segmentation_volume": self.__labelMapNodeId,
            "segment_equation_dict": json.dumps(self.__segmentEquationDict),
            "output_volume": outputVolume.GetID(),
        }
        self._cliNode = slicer.cli.run(
            slicer.modules.permeabilitycli,
            None,
            cliConfig,
            wait_for_completion=False,
        )
        self.__cliNodeModifiedObserver = self._cliNode.AddObserver(
            "ModifiedEvent", lambda c, ev, info=cliConfig: self.__onCliModifiedEvent(c, ev, info)
        )

        if progressBar is not None:
            progressBar.setCommandLineModuleNode(self._cliNode)

    def __onCliModifiedEvent(self, caller, event, info):
        if self._cliNode is None:
            return

        if caller is None:
            self.__resetCliNodes()
            return

        if caller.IsBusy():
            return

        if caller.GetStatusString() == "Completed":
            outputVolumeNode = helpers.tryGetNode(info["output_volume"])
            if self.__soiNodeId:
                soiNode = helpers.tryGetNode(self.__soiNodeId)
                outputVolumeNode = helpers.maskInputWithROI(outputVolumeNode, soiNode)

            helpers.makeTemporaryNodePermanent(outputVolumeNode, show=True)
        else:
            helpers.removeTemporaryNodes(environment=self.__class__.__name__)

        self.__resetCliNodes()
        self.signalProcessEnded.emit()

    def __resetCliNodes(self):
        if self._cliNode is None:
            return

        if self.__cliNodeModifiedObserver is not None:
            self._cliNode.RemoveObserver(self.__cliNodeModifiedObserver)
            del self.__cliNodeModifiedObserver
            self.__cliNodeModifiedObserver = None

        del self._cliNode
        self._cliNode = None
        self.signalProcessEnded.emit()
