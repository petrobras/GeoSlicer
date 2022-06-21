from collections import defaultdict
import ctk
import json
import numpy as np
import qt
import slicer

from ltrace.algorithms.partition import ResultInfo
from ltrace.slicer import helpers, ui, widgets
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widget.histogram_frame import SegmentationModellingHistogramFrame
from Methods.output_info import OutputInfo
from Methods.common import LitePorosityOutputWidget, processVolume


class SaturatedPorosity(widgets.BaseSettingsWidget):
    signal_quality_control_changed = qt.Signal()
    METHOD = "Saturated porosity"
    DISPLAY_NAME = "Porosity Map from Saturated Image"

    def __init__(self, controller=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.controller = controller

        self.outputInfo = OutputInfo()
        self.outputInfo.name = "Total porosity:"
        self.outputInfo.tooltip = "Total porosity (micro + macro)"

        self.inputWidget = widgets.SingleShotInputWidget(
            allowedInputNodes=["vtkMRMLScalarVolumeNode", "vtkMRMLVectorVolumeNode"],
            mainName="Dry",
            referenceName="Saturated",
        )
        self.inputWidget.objectName = f"{self.DISPLAY_NAME} Single Shot Input Widget"

        self.progress_bar = LocalProgressBar()

        layout = qt.QVBoxLayout(self)
        layout.addWidget(self.inputWidget)

        self.comboBoard = qt.QVBoxLayout()
        self.comboBoard.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.comboBoard)

        self.plotSection = ctk.ctkCollapsibleButton()
        self.plotSection.text = "Quality Control"
        self.plotSection.flat = True
        self.plotSection.collapsed = True

        plotFormLayout = qt.QVBoxLayout(self.plotSection)
        plotFormLayout.setContentsMargins(0, 0, 0, 0)

        self.qualityControlButton = qt.QPushButton("Initialize")
        self.qualityControlButton.clicked.connect(self._onQualityControlClicked)
        self.qualityControlButton.objectName = f"saturated_porosity.SaturatedPorosity[Quality Control Button]"
        plotFormLayout.addWidget(self.qualityControlButton)

        self.satDryPorosityPlot = SatDryPlotControllerWidget()
        self.satDryPorosityPlot.objectName = "SaturatedPorosity[QC Plot Controller Widget]"
        self.satDryPorosityPlot.signal_quality_control_changed.connect(self._onQualityControlChanged)
        plotFormLayout.addWidget(self.satDryPorosityPlot)

        extraConfigLayout = qt.QVBoxLayout()
        self.onlyComputePorosity = qt.QCheckBox("Only compute total porosity (No porosity map)")
        self.onlyComputePorosity.objectName = "saturated_porosity.SaturatedPorosity[Only Compute Porosity]"
        extraConfigLayout.addWidget(self.onlyComputePorosity)

        plotFormLayout.addLayout(extraConfigLayout)

        # self.computeOutputWidget = LitePorosityOutputWidget(parent=self)
        # self.computeOutputWidget.clicked.connect(self._onComputeButtonClicked)
        # plotFormLayout.addWidget(self.computeOutputWidget)

        layout.addWidget(self.plotSection)

    def clearPlotData(self):
        self.satDryPorosityPlot.clear_data()

    def apply(self, outputPrefix: str):
        returnVolume: bool = not self.onlyComputePorosity.isChecked()
        return self.compute(outputPrefix, returnVolume)

    def compute(self, outputPrefix, returnVolume=True):
        dryNode = self.inputWidget.mainInput.currentNode()
        satNode = self.inputWidget.referenceInput.currentNode()

        if satNode is None or dryNode is None:
            raise ValueError("Please, select a valid dry and saturated volume.")

        soiNode = self.inputWidget.soiInput.currentNode()
        dryMaskNode = processVolume(dryNode, soiNode)
        saturatedMaskNode = processVolume(satNode, soiNode)

        dryNode = helpers.tryGetNode(self.dryNodeId)
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemTreeId = folderTree.GetItemByDataNode(dryNode)
        parentItemId = folderTree.GetItemParent(itemTreeId)
        outputDir = folderTree.GetItemChildWithName(parentItemId, "Modelling Results")
        if outputDir == 0 and returnVolume:
            outputDir = folderTree.CreateFolderItem(parentItemId, helpers.generateName(folderTree, "Modelling Results"))

        self.totalPorosityAcquired = False

        params = self.toJson()
        if params["airValueDry"] == params["calciteValueDry"]:
            raise ValueError("Air and calcite attenuation factors must be different.")

        # Define parameters
        common_params = {
            "dryNodeId": dryMaskNode.GetID(),
            "saturatedNodeId": saturatedMaskNode.GetID(),
            "outputPrefix": outputPrefix,
            "params": params,
            "currentDir": outputDir,
        }

        common_params["params"]["returnVolume"] = returnVolume

        logic = SaturatedPorosityLogic(**common_params)
        self.total_porosity_acquired = False
        logic.signalTotalPorosityComputed.connect(self.__updateOutputInfo)
        return logic

    def toJson(self):
        bgPorosity = 0
        airValueDry = None
        calciteValueDry = None
        airValueSaturated = None
        calciteValueSaturated = None

        if self.satDryPorosityPlot.has_loaded_data():
            airValueDry, calciteValueDry = self.satDryPorosityPlot.get_attenuation_factors()

        return dict(
            intrinsic_porosity=bgPorosity,
            method=self.METHOD,
            airValueDry=airValueDry,
            calciteValueDry=calciteValueDry,
            airValueSaturated=airValueSaturated,
            calciteValueSaturated=calciteValueSaturated,
        )

    def validateQC(self):
        return self.satDryPorosityPlot.has_loaded_data()

    def onSelect(self):
        self.plotSection.collapsed = False

    def shrink(self):
        self.plotSection.collapsed = True

    def onInputChanged(self):
        pass
        # self.computeOutputWidget.clearState()

    def onSaturatedChanged(self, node, selected):
        self.clearPlotData()
        self._checkQualityControlEnabled()
        self.onInputChanged()

        if node is None or not (node.IsA("vtkMRMLScalarVolumeNode") or node.IsA("vtkMRMLVectorVolumeNode")):
            self.saturatedNodeId = None
        else:
            self.saturatedNodeId = node.GetID()

    def onSoiChanged(self, node):
        self.soiNodeId = node.GetID() if node is not None else None
        self.onInputChanged()

    def onDryChanged(self, inputNode):
        self.dryNodeId = inputNode.GetID() if inputNode is not None else None
        self.satDryPorosityPlot.clear_data()
        self._checkQualityControlEnabled()
        self.onInputChanged()

    def onSegmentationChanged(self, node):
        self.onDryChanged(node)

    def onReferenceChanged(self, node, selected):
        self.onSaturatedChanged(node, selected)

    def validatePrerequisites(self):
        dryNode = self.inputWidget.mainInput.currentNode()
        saturatedNode = self.inputWidget.referenceInput.currentNode()

        if dryNode is None or saturatedNode is None:
            slicer.util.errorDisplay("Please, select a valid dry and saturated volume.")
            return False

        if not self.equal(dryNode, saturatedNode):
            confirmedRedirect = slicer.util.confirmOkCancelDisplay(
                "The size or dimensions of the inputs are different." "\nDo you agree to go to registration module?",
                "Redirect to Registration",
            )
            if confirmedRedirect:
                slicer.util.selectModule("CTAutoRegistration")
                return False

            if not confirmedRedirect:
                return False

        return True

    def equal(self, A, B):
        return np.equal(A.GetImageData().GetDimensions(), B.GetImageData().GetDimensions()).all()

    def getOutputInfo(self):
        if self.totalPorosityAcquired:
            return [self.outputInfo]
        else:
            return []

    def _onQualityControlClicked(self):
        if not self.validatePrerequisites():
            return

        dryNode = self.inputWidget.mainInput.currentNode()
        saturatedNode = self.inputWidget.referenceInput.currentNode()

        soiNode = self.inputWidget.soiInput.currentNode()
        if soiNode is not None:
            dryNode = processVolume(dryNode, soiNode)
            saturatedNode = processVolume(saturatedNode, soiNode)

        self.signal_quality_control_changed.emit()
        self.satDryPorosityPlot.set_data(dryNode, saturatedNode)

    def _onQualityControlChanged(self):
        self.signal_quality_control_changed.emit()

    # def _onComputeButtonClicked(self):
    #     self.signal_quality_control_changed.emit()
    #     if not self.validatePrerequisites():
    #         return
    #     #self.computeOutputWidget.setRunningState()
    #     self.apply("compute", returnVolume=False).apply(progress_bar=self.progress_bar)

    def _checkQualityControlEnabled(self):
        saturatedNode = self.inputWidget.referenceInput.currentNode()
        dryNode = self.inputWidget.mainInput.currentNode()
        validInputs = dryNode is not None and saturatedNode is not None
        self.satDryPorosityPlot.attenuation_factors.enable_quality_control(validInputs)

    def __updateOutputInfo(self, value):
        self.totalPorosityAcquired = True
        self.outputInfo.value = f"{value:.2f}%"


class SatDryPlotControllerWidget(qt.QFrame):
    signal_quality_control_changed = qt.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = qt.QFormLayout(self)

        self.attenuation_factors = AttenuationFactorsWidget(parent=self, controller=self)
        self.attenuation_factors.enable_quality_control(False)
        self.porosity_histogram = SegmentationModellingHistogramFrame(
            parent=self, region_widget=self.attenuation_factors
        )
        self.porosity_histogram.number_of_arrays = 2
        self.porosity_histogram.region_leeway = 0.1  # 10%
        self.attenuation_factors.signal_clear_plot.connect(self.clear_data)

        layout.addRow(self.attenuation_factors)
        layout.addRow(self.porosity_histogram)

    def __process(self, dry_node, sat_node):
        dry_array = slicer.util.arrayFromVolume(dry_node).ravel()
        sat_array = slicer.util.arrayFromVolume(sat_node).ravel()
        reference_array = np.concatenate((dry_array, sat_array))

        thrsh = len(dry_array)

        dry_mask_array = np.zeros_like(reference_array, dtype=bool)
        dry_mask_array[:thrsh] = True

        sat_mask_array = np.zeros_like(reference_array, dtype=bool)
        sat_mask_array[thrsh:] = True

        indexing = reference_array != 0
        reference_array = reference_array[indexing]
        dry_mask_array = dry_mask_array[indexing]
        sat_mask_array = sat_mask_array[indexing]

        return reference_array, dry_mask_array, sat_mask_array

    def set_data(self, dry_node, sat_node):
        self.clear_data()
        if dry_node is None or sat_node is None:
            return

        reference_array, dry_mask_array, sat_mask_array = self.__process(dry_node, sat_node)

        # blue color in rgb is (0, 0, 255)
        self.porosity_histogram.set_data(
            reference_data=reference_array,
            array_masks=[dry_mask_array, sat_mask_array],
            plot_colors=[(127.0, 127.0, 127.0), (0, 0, 255)],
            update_plot_auto_zoom="minmax",
        )

        initial_air_value = 0.528
        initial_water_value = 1.195
        if np.any(reference_array > 10):
            # If the reference array has values greater than 10, it is likely that it is non-normalized
            median = np.median(reference_array)
            radius = np.std(reference_array) * 1.5
            initial_air_value = max(0, median - radius)
            initial_water_value = min(reference_array.max(), median + radius)

        self.porosity_histogram.set_region(initial_air_value, initial_water_value)
        self.attenuation_factors.enable_input(True)

    def get_attenuation_factors(self):
        return self.attenuation_factors.min_attenuation_factor(), self.attenuation_factors.max_attenuation_factor()

    def has_loaded_data(self):
        if self.porosity_histogram is None:
            return False
        else:
            return self.porosity_histogram.has_loaded_data()

    def clear_data(self):
        self.porosity_histogram.clear_loaded_data()
        self.attenuation_factors.set_min_attenuation_factor(0)
        self.attenuation_factors.set_max_attenuation_factor(0)
        self.attenuation_factors.set_factors_value_range(0, 0)
        self.attenuation_factors.enable_input(False)

    def _onQualityControlClicked(self):
        self.clear_data()


class AttenuationFactorsWidget(qt.QFrame):
    signal_editing_finished = qt.Signal(float, float)
    signal_clear_plot = qt.Signal()

    def __init__(self, parent=None, controller=None):
        super().__init__(parent)
        self.controller = controller
        self.data_widget = None

        layout = qt.QVBoxLayout(self)

        input_layout = qt.QFormLayout()

        self.air_input = ui.numberParam(vrange=(0, 2**16), value=0.0, step=0.001, decimals=3)
        self.air_input.enabled = False
        self.air_input.textChanged.connect(self._clear_porosity_data)
        self.air_input.editingFinished.connect(self._on_input_changed)
        self.air_input.objectName = "saturated_porosity.AttenuationFactorsWidget[Air Input]"
        input_layout.addRow(qt.QLabel("Air: "), self.air_input)

        self.water_input = ui.numberParam(vrange=(0, 2**16), value=0.0, step=0.001, decimals=3)
        self.water_input.enabled = False
        self.water_input.editingFinished.connect(self._on_input_changed)
        self.water_input.textChanged.connect(self._clear_porosity_data)
        self.water_input.objectName = "saturated_porosity.AttenuationFactorsWidget[Water Input]"
        input_layout.addRow(qt.QLabel("Water: "), self.water_input)

        layout.addLayout(input_layout)

        layout.addStretch(1)

    def enable_input(self, enable):
        self.air_input.enabled = enable
        self.water_input.enabled = enable

    def enable_quality_control(self, enable):
        if not enable:
            self.signal_clear_plot.emit()
            self.air_input.enabled = False
            self.water_input.enabled = False

    def min_attenuation_factor(self):
        return self.air_input.value

    def max_attenuation_factor(self):
        return self.water_input.value

    def set_min_attenuation_factor(self, value):
        self.blockSignals(True)
        self.air_input.setValue(value)
        self.blockSignals(False)

    def set_max_attenuation_factor(self, value):
        self.blockSignals(True)
        self.water_input.setValue(value)
        self.blockSignals(False)

    def set_factors_value_range(self, min_, max_):
        self.air_input.setRange(min_, max_)
        self.water_input.setRange(min_, max_)

    def _on_input_changed(self):
        self.signal_editing_finished.emit(self.air_input.value, self.water_input.value)

    def _clear_porosity_data(self):
        self.controller.signal_quality_control_changed.emit()
        self.signal_editing_finished.emit(self.air_input.value, self.water_input.value)


class SaturatedPorosityLogic(qt.QObject):
    signalTotalPorosityComputed = qt.Signal(float)
    signalProcessEnded = qt.Signal()

    def __init__(
        self,
        dryNodeId,
        saturatedNodeId,
        outputPrefix,
        params,
        currentDir,
    ):
        super().__init__()

        self.__dryNodeId = dryNodeId
        self.__saturatedNodeId = saturatedNodeId
        self.__outputPrefix = outputPrefix
        self.__params = params
        self.__currentDir = currentDir

        self._cliNode = None
        self.__cliNodeModifiedObserver = None

    def apply(self, progress_bar=None):

        cli_node, result_info = self.__runSaturatedPorosity(
            self.__dryNodeId,
            self.__saturatedNodeId,
            self.__outputPrefix + "_{type}",
            self.__params,
            currentDir=self.__currentDir,
            tag=self.__class__.__name__,
        )

        self._cliNode = cli_node
        self.__cliNodeModifiedObserver = self._cliNode.AddObserver(
            "ModifiedEvent", lambda c, ev, info=result_info: self.__onCliModifiedEvent(c, ev, info)
        )

        if progress_bar is not None:
            progress_bar.setCommandLineModuleNode(self._cliNode)

    def __onCliModifiedEvent(self, caller, event, info):
        if self._cliNode is None:
            return

        if caller is None:
            self.__resetCliNodes()
            del info
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

        del info

        self.signalProcessEnded.emit()

    def __runSaturatedPorosity(
        self,
        dryNodeId,
        saturatedNodeId,
        outputPrefix,
        params,
        currentDir=None,
        tag=None,
    ):
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
            "dryInputVolume": dryNodeId,
            "saturatedInputVolume": saturatedNodeId,
            "outputReport": reportNode.GetID(),
            "outputVolume": outNode.GetID(),
        }

        cliNode = slicer.cli.run(slicer.modules.saturatedporositycli, None, cliConf, wait_for_completion=False)
        dryNode = helpers.tryGetNode(dryNodeId)
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
            inputNode=dryNode,
            roiNode=None,
        )

        return cliNode, resultInfo

    def __resetCliNodes(self):
        if self._cliNode is None:
            return

        if self.__cliNodeModifiedObserver is not None:
            self._cliNode.RemoveObserver(self.__cliNodeModifiedObserver)
            del self.__cliNodeModifiedObserver
            self.__cliNodeModifiedObserver = None

        del self._cliNode
        self._cliNode = None
