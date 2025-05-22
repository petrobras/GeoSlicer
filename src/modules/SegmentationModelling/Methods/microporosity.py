from collections import defaultdict
import ctk
import json
import qt
import slicer

import numpy as np

from ltrace.algorithms.measurements import GetMicroporosityUpperAndLowerLimits
from ltrace.algorithms.partition import ResultInfo
from ltrace.slicer import helpers, ui, widgets
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widget.histogram_frame import MicroPorosityHistogramFrame
from Methods.output_info import OutputInfo
from Methods.common import LitePorosityOutputWidget, processSegmentation, processVolume


class MicroPorosity(widgets.BaseSettingsWidget):
    signal_quality_control_changed = qt.Signal()
    METHOD = "microporosity"
    DISPLAY_NAME = "Porosity Map from Segmentation"

    SEGMENT_TYPES = ("High Attenuation", "Reference Solid", "Macroporosity", "Microporosity")

    def __init__(self, controller=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.controller = controller

        self.totalPorosityAcquired = False
        self.outputInfo = OutputInfo()
        self.outputInfo.name = "Total porosity:"
        self.outputInfo.tooltip = "Total porosity (micro + macro)"
        self.inputWidget = widgets.SingleShotInputWidget()
        self.inputWidget.objectName = f"{self.DISPLAY_NAME} Single Shot Input Widget"
        self.progress_bar = LocalProgressBar()

        self.poreDistSelector = []

        layout = qt.QVBoxLayout(self)
        layout.addWidget(self.inputWidget)

        self.backgroundPorosityNumberInput = ui.numberParam((0.0, 1.0), value=0, step=0.01, decimals=2)
        self.backgroundPorosityNumberInput.setToolTip('"Solid" phase in fact corresponds to some background porosity.')
        self.backgroundPorosityNumberInput.objectName = "Microporosity Input Number"
        # layout.addRow('Solid background Porosity: ', self.backgroundPorosityNumberInput)
        self.backgroundPorosityNumberInput.visible = False  # instead, hide it

        self.comboBoard = qt.QVBoxLayout()
        self.comboBoard.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.comboBoard)

        self.plotSection = ctk.ctkCollapsibleButton()
        self.plotSection.text = "Quality Control"
        self.plotSection.flat = True
        self.plotSection.collapsed = True

        plotFormLayout = qt.QVBoxLayout(self.plotSection)
        plotFormLayout.setContentsMargins(0, 0, 0, 0)

        self.microporosityPlot = PorosityPlotControllerWidget()
        self.microporosityPlot.signal_quality_control_clicked.connect(self._onQualityControlClicked)
        self.microporosityPlot.signal_quality_control_changed.connect(self._onQualityControlChanged)
        plotFormLayout.addWidget(self.microporosityPlot)

        extraConfigLayout = qt.QVBoxLayout()
        self.onlyComputePorosity = qt.QCheckBox("Only compute total porosity (No porosity map)")
        extraConfigLayout.addWidget(self.onlyComputePorosity)

        plotFormLayout.addLayout(extraConfigLayout)

        layout.addWidget(self.plotSection)

    def clearPlotData(self):
        self.microporosityPlot.clear_data()

    def apply(self, outputPrefix: str):
        returnVolume: bool = not self.onlyComputePorosity.isChecked()
        return self.compute(outputPrefix, returnVolume)

    def compute(self, outputPrefix, returnVolume=True):

        segmentationNode = self.inputWidget.mainInput.currentNode()
        referenceNode = self.inputWidget.referenceInput.currentNode()
        soiNode = self.inputWidget.soiInput.currentNode()

        procLabelsNode, _ = processSegmentation(segmentationNode, referenceNode, soiNode)
        procrRefNode = processVolume(referenceNode, soiNode)

        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        itemTreeId = folderTree.GetItemByDataNode(segmentationNode)
        parentItemId = folderTree.GetItemParent(itemTreeId)
        outputDir = folderTree.GetItemChildWithName(parentItemId, "Modelling Results")
        if outputDir == 0 and returnVolume:
            outputDir = folderTree.CreateFolderItem(parentItemId, helpers.generateName(folderTree, "Modelling Results"))

        # Define parameters
        common_params = {
            "parent": self,
            "referenceNodeId": procrRefNode.GetID(),
            "labelMapNodeId": procLabelsNode.GetID(),
            "outputPrefix": outputPrefix,
            "params": self.toJson(),
            "currentDir": outputDir,
        }

        common_params["params"]["returnVolume"] = returnVolume

        logic = MicroPorosityLogic(**common_params)

        self.total_porosity_acquired = False
        logic.signalTotalPorosityComputed.connect(self.__update_output_info)

        return logic

    def getLabelsDict(self):
        labels = defaultdict(list)
        for i, combo in enumerate(self.poreDistSelector, start=1):
            prop = combo.currentText
            labels[prop].append(i)
        return labels

    def toJson(self):
        bgPorosity = self.backgroundPorosityNumberInput.value
        labels = self.getLabelsDict()
        microporosityLowerLimit = None
        microporosityUpperLimit = None

        if self.microporosityPlot.has_loaded_data():
            microporosityLowerLimit, microporosityUpperLimit = self.microporosityPlot.get_attenuation_factors()

        return dict(
            labels=labels,
            intrinsic_porosity=bgPorosity,
            method=self.METHOD,
            microporosityLowerLimit=microporosityLowerLimit,
            microporosityUpperLimit=microporosityUpperLimit,
        )

    def select(self):
        self.plotSection.collapsed = False
        super().select()

    def shrink(self):
        self.plotSection.collapsed = True

    def onInputChanged(self):
        pass

    def onReferenceChanged(self, node, selected):
        self.clearPlotData()
        self._checkQualityControlEnabled()
        self.onInputChanged()

    def onSoiChanged(self, node):
        self.onInputChanged()

    def onSegmentationChanged(self, inputNode):
        if inputNode is None or not (
            inputNode.IsA("vtkMRMLSegmentationNode") or inputNode.IsA("vtkMRMLLabelMapVolumeNode")
        ):
            self._checkQualityControlEnabled()
            self.clearSegmentInputs()
            return
        self._checkQualityControlEnabled()
        self.onInputChanged()
        self.CreateSegmentsInputsTypes()

    def CreateSegmentsInputsTypes(self):
        self.clearSegmentInputs()
        self.clearPlotData()

        segmentationNode = self.inputWidget.mainInput.currentNode()
        referenceNode = self.inputWidget.referenceInput.currentNode()
        soiNode = self.inputWidget.soiInput.currentNode()
        segmentsDict = helpers.getSegmentList(node=segmentationNode, roiNode=soiNode, refNode=referenceNode)
        segments = [segment["name"] for segment in segmentsDict.values()]

        formLayout = qt.QFormLayout()
        for segment in segments:
            combobox = qt.QComboBox()
            combobox.addItems(self.SEGMENT_TYPES)
            combobox.setCurrentIndex(len(self.SEGMENT_TYPES) - 1)
            self.poreDistSelector.append(combobox)
            formLayout.addRow(segment + "  ", combobox)
            combobox.objectName = f"{segment} Segment Porosity Map Parameter ComboBox"

        self.comboBoard.addLayout(formLayout)

    def clearSegmentInputs(self):
        # hide the comboboxes
        # renew the references, to avoid being found before being deleted (because deleteLater is asynchronous)
        for segmentInput in self.poreDistSelector:
            segmentInput.hide()
            segmentInput.objectName = "Deleted Segment ComboBox"

        # expect to force delete this references
        del self.poreDistSelector
        self.poreDistSelector = []
        helpers.clear_layout(self.comboBoard)

    def validatePrerequisites(self):
        segmentationNode = self.inputWidget.mainInput.currentNode()
        referenceNode = self.inputWidget.referenceInput.currentNode()
        if referenceNode is None or segmentationNode is None:
            slicer.util.errorDisplay("Please, select a valid segmentation and reference volume.")
            return False
        return self._checkPorosityTypesSelected(self.getLabelsDict())

    def getOutputInfo(self):
        if self.totalPorosityAcquired:
            return [self.outputInfo]
        else:
            return []

    def _onQualityControlClicked(self):
        if not self.validatePrerequisites():
            return
        self.signal_quality_control_changed.emit()
        labelsDictionary = self.getLabelsDict()
        if self._checkPorosityTypesSelected(labelsDictionary):

            segmentationNode = self.inputWidget.mainInput.currentNode()
            referenceNode = self.inputWidget.referenceInput.currentNode()
            soiNode = self.inputWidget.soiInput.currentNode()

            procLabelsNode, reverseMapping = processSegmentation(segmentationNode, referenceNode, soiNode)
            procRefNode = processVolume(referenceNode, soiNode)

            self.microporosityPlot.set_data(procRefNode, procLabelsNode, labelsDictionary, reverseMapping)

    def _onQualityControlChanged(self):
        self.signal_quality_control_changed.emit()

    # def _onComputeButtonClicked(self):
    #     if not self.validatePrerequisites():
    #         return
    #     self.signal_quality_control_changed.emit()
    #     self.only_compute_microporosity = True
    #     self.computeOutputWidget.setRunningState()
    #     self.apply("compute").apply(self.progress_bar)

    def _checkQualityControlEnabled(self):
        segmentationNode = self.inputWidget.mainInput.currentNode()
        referenceNode = self.inputWidget.referenceInput.currentNode()
        self.microporosityPlot.attenuation_factors.enable_quality_control(segmentationNode and referenceNode)

    def _checkPorosityTypesSelected(self, labelsDictionary):
        # Checks if every required porosity type was selected
        if (
            "Reference Solid" not in labelsDictionary
            or "Microporosity" not in labelsDictionary
            or "Macroporosity" not in labelsDictionary
        ):
            slicer.util.errorDisplay(
                'The user must define the input segments as "Reference Solid", "Microporosity" and "Macroporosity".'
            )
            return False
        return True

    def __update_output_info(self, value):
        self.totalPorosityAcquired = True
        self.outputInfo.value = f"{value:.2f}%"


def getMicroporosityData(referenceNode, segmentationNode, labelDict):
    inputVoxelArray = slicer.util.arrayFromVolume(referenceNode)
    labelmapVoxelArray = slicer.util.arrayFromVolume(segmentationNode)

    microporosityData = GetMicroporosityUpperAndLowerLimits(inputVoxelArray, labelmapVoxelArray, labelDict)
    return microporosityData


class PorosityPlotControllerWidget(qt.QFrame):
    signal_quality_control_clicked = qt.Signal()
    signal_quality_control_changed = qt.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = qt.QFormLayout(self)

        self.attenuation_factors = AttenuationFactorsWidget(parent=self)
        self.attenuation_factors.enable_quality_control(False)
        self.microporosity_histogram = MicroPorosityHistogramFrame(parent=self, region_widget=self.attenuation_factors)
        self.attenuation_factors.signal_quality_control_clicked.connect(self._onQualityControlClicked)
        self.attenuation_factors.signal_quality_control_changed.connect(self._onQualityControlChanged)
        self.attenuation_factors.signal_clear_plot.connect(self.clear_data)

        layout.addRow(self.attenuation_factors)
        layout.addRow(self.microporosity_histogram)

    def set_data(self, referenceNode, segmentation_node, labels_dictionary, invmap=None):
        self.clear_data()
        microporosityData = getMicroporosityData(referenceNode, segmentation_node, labels_dictionary)
        masks = [
            microporosityData.macroporosity_mask,
            microporosityData.microporosity_mask,
            microporosityData.solid_mask,
        ]
        colors = [
            self._get_color_from_invmap(invmap, labels_dictionary, "Macroporosity"),
            self._get_color_from_invmap(invmap, labels_dictionary, "Microporosity"),
            self._get_color_from_invmap(invmap, labels_dictionary, "Reference Solid"),
        ]

        self.microporosity_histogram.set_data(
            referenceNode, array_masks=masks, plot_colors=colors, update_plot_auto_zoom=True
        )
        self.microporosity_histogram.set_region(microporosityData.lower_limit, microporosityData.upper_limit)
        self.attenuation_factors.enable_input(True)

    def get_attenuation_factors(self):
        return self.attenuation_factors.min_attenuation_factor(), self.attenuation_factors.max_attenuation_factor()

    def has_loaded_data(self):
        if self.microporosity_histogram is None:
            return False
        else:
            return self.microporosity_histogram.has_loaded_data()

    def clear_data(self):
        self.microporosity_histogram.clear_loaded_data()
        self.attenuation_factors.set_min_attenuation_factor(0)
        self.attenuation_factors.set_max_attenuation_factor(0)
        self.attenuation_factors.set_factors_value_range(0, 0)
        self.attenuation_factors.enable_input(False)

    def _onQualityControlClicked(self):
        self.signal_quality_control_clicked.emit()
        self.signal_quality_control_changed.emit()

    def _onQualityControlChanged(self):
        self.signal_quality_control_changed.emit()

    def _get_color_from_invmap(self, invmap, label_dict, label_name):
        invmap_index = np.min(label_dict[label_name])
        inv = invmap[invmap_index - 1]
        return tuple(np.array(inv[2]) * 255)


class AttenuationFactorsWidget(qt.QFrame):
    signal_quality_control_clicked = qt.Signal()
    signal_quality_control_changed = qt.Signal()
    signal_editing_finished = qt.Signal(int, int)
    signal_clear_plot = qt.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.controller = parent
        self.data_widget = None

        layout = qt.QVBoxLayout(self)

        input_layout = qt.QFormLayout()

        self.quality_control_button = qt.QPushButton("Initialize")
        self.quality_control_button.clicked.connect(self._on_quality_control_clicked)
        self.quality_control_button.objectName = f"{MicroPorosity.DISPLAY_NAME} Quality Control Button"

        layout.addWidget(self.quality_control_button)

        self.air_attenuation_factor_input = ui.FloatInput()
        self.air_attenuation_factor_input.enabled = False
        self.air_attenuation_factor_input.textChanged.connect(self._on_attenuation_input_changed)
        self.air_attenuation_factor_input.editingFinished.connect(self._on_attenuation_changed)
        self.air_attenuation_factor_input.objectName = "microporosity.AttenuationFactorsWidget[Air Input]"
        input_layout.addRow(qt.QLabel("Air: "), self.air_attenuation_factor_input)

        self.solid_attenuation_factor_input = ui.FloatInput()
        self.solid_attenuation_factor_input.enabled = False
        self.solid_attenuation_factor_input.textChanged.connect(self._on_attenuation_input_changed)
        self.solid_attenuation_factor_input.editingFinished.connect(self._on_attenuation_changed)
        self.solid_attenuation_factor_input.objectName = "microporosity.AttenuationFactorsWidget[Solid Input]"
        input_layout.addRow(qt.QLabel("Solid: "), self.solid_attenuation_factor_input)

        layout.addLayout(input_layout)

        layout.addStretch(1)

    def enable_input(self, enable):
        self.air_attenuation_factor_input.enabled = enable
        self.solid_attenuation_factor_input.enabled = enable

    def enable_quality_control(self, enable):
        if not enable:
            self.signal_clear_plot.emit()
            self.air_attenuation_factor_input.enabled = False
            self.solid_attenuation_factor_input.enabled = False

    def min_attenuation_factor(self):
        return self.air_attenuation_factor_input.value

    def max_attenuation_factor(self):
        return self.solid_attenuation_factor_input.value

    def set_min_attenuation_factor(self, value):
        self.blockSignals(True)
        self.air_attenuation_factor_input.setValue(value)
        self.blockSignals(False)

    def set_max_attenuation_factor(self, value):
        self.blockSignals(True)
        self.solid_attenuation_factor_input.setValue(value)
        self.blockSignals(False)

    def set_factors_value_range(self, min_, max_):
        self.air_attenuation_factor_input.setRange(min_, max_)
        self.solid_attenuation_factor_input.setRange(min_, max_)

    def _on_attenuation_changed(self):
        self.signal_editing_finished.emit(
            self.air_attenuation_factor_input.value, self.solid_attenuation_factor_input.value
        )

    def _on_attenuation_input_changed(self):
        self.controller.signal_quality_control_changed.emit()

    def _on_quality_control_clicked(self):
        self.signal_quality_control_clicked.emit()


class MicroPorosityLogic(qt.QObject):
    signalTotalPorosityComputed = qt.Signal(float)
    signalProcessEnded = qt.Signal()

    def __init__(
        self,
        parent,
        referenceNodeId,
        labelMapNodeId,
        outputPrefix,
        params,
        currentDir,
    ):
        super().__init__(parent)

        self.__referenceNodeId = referenceNodeId
        self.__labelMapNodeId = labelMapNodeId
        self.__outputPrefix = outputPrefix
        self.__params = params
        self.__currentDir = currentDir

        self._cliNode = None
        self.__cliNodeModifiedObserver = None

    def apply(self, progressBar=None):
        referenceNode = helpers.tryGetNode(self.__referenceNodeId)
        labelMapNode = helpers.tryGetNode(self.__labelMapNodeId)

        cliNode, resultInfo = self.__run_microporosity(
            referenceNode,
            labelMapNode,
            self.__outputPrefix + "_{type}",
            self.__params,
            currentDir=self.__currentDir,
            tag="PorosityMap",
        )

        self._cliNode = cliNode
        self.__cliNodeModifiedObserver = self._cliNode.AddObserver(
            "ModifiedEvent", lambda c, ev, info=resultInfo: self.__onCliModifiedEvent(c, ev, info)
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

            doReturnVolume = self.__params.get("returnVolume", True)

            outputVolumeNode = helpers.tryGetNode(info.outputVolume)
            outputReportNode = helpers.tryGetNode(info.outputReport)
            if outputReportNode is not None:
                outputReportNode.SetAttribute("ReferenceVolumeNode", info.outputVolume)
                table = outputReportNode.GetTable()
                nRows = table.GetNumberOfRows()
                totalPorosity = None
                for row in range(nRows):
                    if table.GetValue(row, 0).ToString().startswith("Total Porosity"):
                        totalPorosity = table.GetValue(row, 1).ToDouble()
                        break

                if totalPorosity:
                    self.signalTotalPorosityComputed.emit(totalPorosity)

            if doReturnVolume:
                helpers.makeTemporaryNodePermanent(outputVolumeNode, show=True)
                helpers.makeTemporaryNodePermanent(outputReportNode, show=True)
            else:
                slicer.util.setSliceViewerLayers(background=info.inputNode, fit=True)

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

    @staticmethod
    def __run_microporosity(referenceNode, labelMapNode, outputPrefix, params, currentDir=None, tag=None):
        outNode = helpers.createOutput(
            prefix=outputPrefix,
            where=currentDir,
            ntype="PorosityMap",
            builder=lambda n, hidden=True: helpers.createTemporaryVolumeNode(
                slicer.vtkMRMLScalarVolumeNode, n, environment=tag, hidden=hidden
            ),
        )

        reportNode = helpers.createOutput(
            prefix=outputPrefix,
            where=currentDir,
            ntype="Variables",
            builder=lambda n, hidden=True: helpers.createTemporaryNode(
                slicer.vtkMRMLTableNode, n, environment=tag, hidden=hidden
            ),
        )
        cliConf = {
            "params": json.dumps(params),
            "inputVolume": referenceNode.GetID(),
            "labelVolume": labelMapNode.GetID(),
            "outputReport": reportNode.GetID(),
            "outputVolume": outNode.GetID(),
        }

        cliNode = slicer.cli.run(slicer.modules.microporositycli, None, cliConf, wait_for_completion=False)

        resultInfo = ResultInfo(
            sourceLabelMapNode=None,
            outputVolume=outNode.GetID(),
            outputReport=reportNode.GetID(),
            reportNode=None,
            outputPrefix=outputPrefix,
            allLabels=None,
            targetLabels=None,
            saveOutput=None,
            referenceNode=None,
            params=params,
            currentDir=currentDir,
            inputNode=labelMapNode,
            roiNode=None,
        )

        return cliNode, resultInfo
