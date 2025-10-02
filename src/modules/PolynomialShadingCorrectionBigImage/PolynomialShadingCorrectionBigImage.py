import ctk
import json
import os
import qt
import slicer
import logging
import sys
import ltrace.slicer.helpers as helpers
import traceback

from ltrace.slicer.app import getApplicationVersion
from ltrace.slicer.lazy import lazy
from ltrace.slicer import ui
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.widget.custom_path_line_edit import CustomPathLineEdit
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from pathlib import Path
from pathvalidate import sanitize_filepath
from ltrace.slicer import netcdf

from PolynomialShadingCorrection import PolynomialShadingCorrection

try:
    from Test.PolynomialShadingCorrectionBigImageTest import PolynomialShadingCorrectionBigImageTest
except ImportError:
    PolynomialShadingCorrectionBigImageTest = None  # tests not deployed to final version or closed source


from dataclasses import dataclass

SLICE_GROUP_SIZE = "sliceGroupSize"
NUMBER_FITTING_POINTS = "numberFittingPoints"


@dataclass
class PolynomialShadingCorrectionParameters:
    inputNode: slicer.vtkMRMLNode = None
    inputMaskNode: slicer.vtkMRMLNode = None
    inputShadingMaskNode: slicer.vtkMRMLNode = None
    sliceGroupSize: int = None
    numberFittingPoints: int = None
    exportPath: str = None


class PolynomialShadingCorrectionBigImage(LTracePlugin):
    SETTING_KEY = "PolynomialShadingCorrectionBigImage"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent: qt.QWidget) -> None:
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Polynomial Shading Correction for Big Images"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = PolynomialShadingCorrectionBigImage.help()
        self.setHelpUrl("Volumes/BigImage/PolynomialShadingCorrection.html")

    @classmethod
    def readme_path(cls: LTracePlugin) -> None:
        return str(cls.MODULE_DIR / "README.md")


class PolynomialShadingCorrectionBigImageWidget(LTracePluginWidget):
    def __init__(self, parent: qt.QWidget) -> None:
        LTracePluginWidget.__init__(self, parent)
        self.logic = None
        self.title = "Polynomial Shading Correction Big Image"

    def getSliceGroupSize(self) -> int:
        return int(PolynomialShadingCorrection.get_setting(SLICE_GROUP_SIZE, default="7"))

    def getNumberFittingPoints(self) -> int:
        return int(PolynomialShadingCorrection.get_setting(NUMBER_FITTING_POINTS, default="1000"))

    def setup(self) -> None:
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.__inputSelector = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode", "vtkMRMLTextNode"],
            tooltip="Select the image within the NetCDF dataset to filter.",
        )
        self.__inputSelector.objectName = "Input Image Selector"

        self.__inputMaskSelector = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLLabelMapVolumeNode", "vtkMRMLSegmentationNode", "vtkMRMLTextNode"],
            tooltip="Select the input mask.",
        )
        self.__inputMaskSelector.objectName = "Input Mask Selector"

        self.__inputShadingMaskSelector = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLLabelMapVolumeNode", "vtkMRMLSegmentationNode", "vtkMRMLTextNode"],
            tooltip="Select the input mask.",
        )
        self.__inputShadingMaskSelector.objectName = "Input Shading Mask Selector"

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Input image:", self.__inputSelector)
        inputLayout.addRow("Input mask:", self.__inputMaskSelector)
        inputLayout.addRow("Input shading mask:", self.__inputShadingMaskSelector)

        # Parameters section
        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False
        parametersSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        self.__sliceGroupSize = qt.QSpinBox()
        self.__sliceGroupSize.objectName = "Slice Group Size"
        self.__sliceGroupSize.setRange(1, 9)
        self.__sliceGroupSize.setSingleStep(2)
        self.__sliceGroupSize.setValue(self.getSliceGroupSize())
        self.__sliceGroupSize.setToolTip(
            "This parameter will cause the polynomial function to be fitted for the central slice in the group of slices. All the other "
            "slices of the group will use the same fitted function."
        )

        self.__numberFittingPoints = qt.QSpinBox()
        self.__numberFittingPoints.objectName = "Number Fitting Points"
        self.__numberFittingPoints.setRange(100, 999999)
        self.__numberFittingPoints.setValue(self.getNumberFittingPoints())
        self.__numberFittingPoints.setToolTip("Number of points used in the function fitting process.")

        parametersLayout = qt.QFormLayout(parametersSection)
        parametersLayout.addRow("Slice group size:", self.__sliceGroupSize)
        parametersLayout.addRow("Number of fitting points:", self.__numberFittingPoints)

        # Output section
        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.__exportPathEdit = CustomPathLineEdit()
        self.__exportPathEdit.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Writable
        self.__exportPathEdit.nameFilters = ["*.nc"]
        self.__exportPathEdit.settingKey = "PolynomialShadingCorrectionBigImage/OutputPath"
        self.__exportPathEdit.setToolTip("Select the output path for the .nc image file output")
        self.__exportPathEdit.objectName = "Output Path Line Edit"

        outputFormLayout = qt.QFormLayout(outputSection)
        outputFormLayout.addRow("Output Path:", self.__exportPathEdit)

        # Apply button
        self.__applyButton = ui.ApplyButton(
            onClick=self.__onApplyButtonClicked, tooltip="Apply changes", enabled=True, object_name="Apply Button"
        )

        self.__cancelButton = qt.QPushButton("Cancel")
        self.__cancelButton.setEnabled(False)
        self.__cancelButton.clicked.connect(self.__onCancelButtonClicked)
        self.__cancelButton.objectName = "Cancel Button"

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.__applyButton)
        buttonsHBoxLayout.addWidget(self.__cancelButton)

        # CLI progress bar
        self.__cliProgressBar = LocalProgressBar()

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addLayout(buttonsHBoxLayout)
        self.layout.addWidget(self.__cliProgressBar)
        self.layout.addStretch(1)

    def setParameters(self, **kwargs) -> None:
        params = PolynomialShadingCorrectionParameters(**kwargs)

        if params.inputNode:
            self.__inputSelector.setCurrentNode(params.inputNode)

        if params.inputMaskNode:
            self.__inputMaskSelector.setCurrentNode(params.inputMaskNode)

        if params.inputShadingMaskNode:
            self.__inputShadingMaskSelector.setCurrentNode(params.inputShadingMaskNode)

        if params.sliceGroupSize:
            self.__sliceGroupSize.setValue(params.sliceGroupSize)

        if params.numberFittingPoints:
            self.__numberFittingPoints.setValue(params.numberFittingPoints)

        if params.exportPath:
            self.__exportPathEdit.setCurrentPath(params.exportPath)

    def __onApplyButtonClicked(self, state: bool) -> None:
        if self.__inputSelector.currentNode() is None:
            slicer.util.errorDisplay("Please select a volume node as the input.", self.title)
            return

        if self.__inputMaskSelector.currentNode() is None:
            slicer.util.errorDisplay("Please select a node as the input mask.", self.title)
            return

        if self.__inputShadingMaskSelector.currentNode() is None:
            slicer.util.errorDisplay("Please select a node as the input shading mask.", self.title)
            return

        if not self.__exportPathEdit.currentPath:
            slicer.util.errorDisplay("Please select an output path.", self.title)
            return

        data = {
            "inputNodeId": self.__inputSelector.currentNode().GetID(),
            "inputMaskNodeId": self.__inputMaskSelector.currentNode().GetID(),
            "inputShadingMaskNodeId": self.__inputShadingMaskSelector.currentNode().GetID(),
            "sliceGroupSize": self.__sliceGroupSize.value,
            "numberFittingPoints": self.__numberFittingPoints.value,
            "exportPath": self.__exportPathEdit.currentPath,
            "geoslicerVersion": getApplicationVersion(),
            "nullValue": 0,
        }

        self.logic = PolynomialShadingCorrectionBigImageLogic(parent=self.parent)
        self.logic.signalProcessRuntimeError.connect(self.onProcessError)
        self.logic.signalProcessSucceed.connect(self.onProcessSucceed)
        self.logic.signalProcessCancelled.connect(self.onProcessCancelled)

        try:
            self.logic.apply(data=data, progressBar=self.__cliProgressBar)
        except Exception as error:
            self.onProcessError(error)

        self.__updateButtonsEnablement(running=True)

        helpers.save_path(self.__exportPathEdit)
        PolynomialShadingCorrection.set_setting(SLICE_GROUP_SIZE, self.__sliceGroupSize.value)
        PolynomialShadingCorrection.set_setting(NUMBER_FITTING_POINTS, self.__numberFittingPoints.value)

    def __updateButtonsEnablement(self, running: bool) -> None:
        self.__cancelButton.setEnabled(running)
        self.__applyButton.setEnabled(not running)

    def __onCancelButtonClicked(self) -> None:
        if not self.logic:
            return

        self.logic.cancel()

    def onProcessError(self, error: str) -> None:
        logging.error(f"{error}.\n{traceback.format_exc()}")
        slicer.util.errorDisplay(
            "An error was found during the process. Please, check the application logs for more details.", self.title
        )
        self.__updateButtonsEnablement(running=False)

    def onProcessSucceed(self, nodeName: str) -> None:
        slicer.util.infoDisplay(f"Process finished successfully.\nPlease check the node '{nodeName}'.", self.title)
        self.__updateButtonsEnablement(running=False)

    def onProcessCancelled(self) -> None:
        logging.debug(f"Process cancelled by the user.")
        self.__updateButtonsEnablement(running=False)


class PolynomialShadingCorrectionBigImageLogic(LTracePluginLogic):

    signalProcessRuntimeError = qt.Signal(str)
    signalProcessSucceed = qt.Signal(str)
    signalProcessCancelled = qt.Signal()

    def __init__(self, parent) -> None:
        LTracePluginLogic.__init__(self, parent)
        self._cliNode = None
        self.__cliNodeModifiedObserver = None

    def _getLazyData(self, node: slicer.vtkMRMLNode) -> None:
        if lazy.is_lazy_node(node):
            return lazy.data(node)

        path = Path(slicer.app.temporaryPath).absolute() / f"{node.GetName().lower()}.nc"
        path = sanitize_filepath(file_path=path, platform="auto")
        netcdf.exportNetcdf(path, [node])

        assert path.exists(), f"Failed to export node {node.GetName()} as NetCDF"

        return lazy.LazyNodeData(url=f"file://{path.as_posix()}", var=f"{node.GetName()}")

    def _removeProxyNodeFile(self, node: slicer.vtkMRMLNode, url: str) -> None:
        if lazy.is_lazy_node(node):
            return

        proxyFilePath = Path(url)
        if not proxyFilePath.exists():
            return

        logging.debug(f"Deleting file: {proxyFilePath.as_posix()}")
        proxyFilePath.unlink()

    def apply(self, data: dict, progressBar: LocalProgressBar = None) -> None:
        inputNode = helpers.tryGetNode(data["inputNodeId"])
        inputMaskNode = helpers.tryGetNode(data["inputMaskNodeId"])
        inputShadingMaskNode = helpers.tryGetNode(data["inputShadingMaskNodeId"])

        if not inputNode:
            raise ValueError("The node selected as input is invalid.")

        if not inputMaskNode:
            raise ValueError("The node selected as input mask is invalid.")

        if not inputShadingMaskNode:
            raise ValueError("The node selected as input shading mask is invalid.")

        inputLazyData = self._getLazyData(inputNode)
        inputMaskLazyData = self._getLazyData(inputMaskNode)
        inputShadingMaskLazyData = self._getLazyData(inputShadingMaskNode)

        inputLazyNodeProtocol = inputLazyData.get_protocol()
        inputLazyNodeHost = inputLazyNodeProtocol.host()
        inputMaskLazyNodeProtocol = inputMaskLazyData.get_protocol()
        inputMaskLazyNodeHost = inputMaskLazyNodeProtocol.host()
        inputShadingMaskLazyNodeProtocol = inputShadingMaskLazyData.get_protocol()
        inputShadingMaskLazyNodeHost = inputShadingMaskLazyNodeProtocol.host()

        data = {
            **data,
            "inputLazyNodeUrl": inputLazyData.url,
            "inputLazyNodeVar": inputLazyData.var,
            "inputMaskLazyNodeUrl": inputMaskLazyData.url,
            "inputMaskLazyNodeVar": inputMaskLazyData.var,
            "inputShadingMaskLazyNodeUrl": inputShadingMaskLazyData.url,
            "inputShadingMaskLazyNodeVar": inputShadingMaskLazyData.var,
            "inputLazyNodeHost": inputLazyNodeHost.to_dict(),
            "inputMaskLazyNodeHost": inputMaskLazyNodeHost.to_dict(),
            "inputShadingMaskLazyNodeHost": inputShadingMaskLazyNodeHost.to_dict(),
        }

        cliConfig = {
            "params": json.dumps(data),
        }

        if progressBar is not None:
            progressBar.visible = True

        self._cliNode = slicer.cli.run(
            slicer.modules.polynomialshadingcorrectionbigimagecli,
            None,
            cliConfig,
            wait_for_completion=False,
        )
        self.__cliNodeModifiedObserver = self._cliNode.AddObserver(
            "ModifiedEvent", lambda c, ev, info=cliConfig: self.__onCliModifiedEvent(c, ev, info)
        )

        if progressBar is not None:
            progressBar.setCommandLineModuleNode(self._cliNode)

    def __onCliModifiedEvent(self, caller, event, info) -> None:
        if self._cliNode is None:
            return

        if caller is None:
            del self._cliNode
            self._cliNode = None
            return

        if caller.IsBusy():
            return

        params = json.loads(info["params"])
        if caller.GetStatusString() == "Completed":
            lazyNodeData = lazy.LazyNodeData(
                url="file://" + params["exportPath"], var=params["inputLazyNodeVar"] + "_filtered"
            )
            lazyNodeData.to_node()
            self.signalProcessSucceed.emit(lazyNodeData.var)
        elif caller.GetStatusString() != "Cancelled":
            self.signalProcessRuntimeError.emit(caller.GetErrorText())
        else:  # Cancelled
            self.signalProcessCancelled.emit()

        inputNode = helpers.tryGetNode(params["inputNodeId"])
        inputMaskNode = helpers.tryGetNode(params["inputMaskNodeId"])
        inputShadingMaskNode = helpers.tryGetNode(params["inputShadingMaskNodeId"])
        self._removeProxyNodeFile(inputNode, params["inputLazyNodeUrl"])
        self._removeProxyNodeFile(inputMaskNode, params["inputMaskLazyNodeUrl"])
        self._removeProxyNodeFile(inputShadingMaskNode, params["inputShadingMaskLazyNodeUrl"])

        if self.__cliNodeModifiedObserver is not None:
            self._cliNode.RemoveObserver(self.__cliNodeModifiedObserver)
            self.__cliNodeModifiedObserver = None

        del self._cliNode
        self._cliNode = None

    def cancel(self) -> None:
        if not self._cliNode:
            return

        self._cliNode.Cancel()
