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

import ltrace.slicer.netcdf as netcdf

try:
    from Test.BoundaryRemovalBigImageTest import BoundaryRemovalBigImageTest
except ImportError:
    BoundaryRemovalBigImageTest = None  # tests not deployed to final version or closed source


from dataclasses import dataclass


@dataclass
class BoundaryRemovalParameters:
    volumeNode: slicer.vtkMRMLNode = None
    segmentationNode: slicer.vtkMRMLNode = None
    thresholdMinimumValue: int = None
    thresholdMaximumValue: int = None
    exportPath: str = None


class BoundaryRemovalBigImage(LTracePlugin):
    SETTING_KEY = "BoundaryRemovalBigImage"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Boundary Removal for Big Image"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = BoundaryRemovalBigImage.help()
        self.setHelpUrl("Volumes/BigImage/BoundaryRemoval.html")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class BoundaryRemovalBigImageWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = None
        self.title = "Boundary Removal Big Image"

    def setup(self):
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.__inputSelector = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode", "vtkMRMLTextNode"],
            tooltip="Select the image within the NetCDF dataset to filter.",
        )
        self.__inputSelector.objectName = "Input Selector"

        self.__segmentationSelector = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLSegmentationNode", "vtkMRMLTextNode"],
            tooltip="Select the segmentation node related to the dataset.",
        )
        self.__segmentationSelector.objectName = "Segmentation Selector"

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Input Image:", self.__inputSelector)
        inputLayout.addRow("Segmentation:", self.__segmentationSelector)

        # Parameters section
        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False
        parametersSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        self.__thresholdSlider = ctk.ctkRangeWidget()
        self.__thresholdSlider.singleStep = 0.01
        self.__thresholdSlider.setRange(sys.float_info.min, sys.float_info.max)
        self.__thresholdSlider.setMinimumValue(0.0)
        self.__thresholdSlider.setMaximumValue(0.0)
        self.__thresholdSlider.setToolTip("Define the threshold range")
        self.__thresholdSlider.objectName = "Threshold Slider"

        parametersLayout = qt.QFormLayout(parametersSection)
        parametersLayout.addRow("Threshold adjustment:", self.__thresholdSlider)

        # Output section
        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.__exportPathEdit = CustomPathLineEdit()
        self.__exportPathEdit.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Writable
        self.__exportPathEdit.nameFilters = ["*.nc"]
        self.__exportPathEdit.settingKey = "BoundaryRemovalBigImage/OutputPath"
        self.__exportPathEdit.setToolTip("Select the output path for the resulting .nc image")
        self.__exportPathEdit.objectName = "Output Path Line Edit"

        outputFormLayout = qt.QFormLayout(outputSection)
        outputFormLayout.addRow("Output Path:", self.__exportPathEdit)

        # Apply button
        self.__applyButton = ui.ApplyButton(
            onClick=self.__onApplyButtonClicked, tooltip="Apply changes", enabled=True, object_name="Apply Button"
        )

        # CLI progress bar
        self.__cliProgressBar = LocalProgressBar()

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addWidget(self.__applyButton)
        self.layout.addWidget(self.__cliProgressBar)
        self.layout.addStretch(1)

    def setParameters(self, **kwargs):
        params = BoundaryRemovalParameters(**kwargs)

        if params.volumeNode:
            self.__inputSelector.setCurrentNode(params.volumeNode)

        if params.segmentationNode:
            self.__segmentationSelector.setCurrentNode(params.segmentationNode)

        if params.thresholdMaximumValue:
            self.__thresholdSlider.setMaximumValue(params.thresholdMaximumValue)

        if params.thresholdMinimumValue:
            self.__thresholdSlider.setMinimumValue(params.thresholdMinimumValue)

        if params.exportPath:
            self.__exportPathEdit.setCurrentPath(params.exportPath)

    def __onApplyButtonClicked(self, state):
        if self.__inputSelector.currentNode() is None:
            slicer.util.errorDisplay("Please select an input node.", self.title)
            return

        if self.__segmentationSelector.currentNode() is None:
            slicer.util.errorDisplay("Please select a segmentation node.", self.title)
            return

        if not self.__exportPathEdit.currentPath:
            slicer.util.errorDisplay("Please select an output path.", self.title)
            return

        data = {
            "inputNodeId": self.__inputSelector.currentNode().GetID(),
            "segmentationNodeId": self.__segmentationSelector.currentNode().GetID(),
            "exportPath": self.__exportPathEdit.currentPath,
            "thresholdMinimumValue": self.__thresholdSlider.minimumValue,
            "thresholdMaximumValue": self.__thresholdSlider.maximumValue,
            "geoslicerVersion": getApplicationVersion(),
        }

        self.logic = BoundaryRemovalBigImageLogic()
        self.logic.signalProcessRuntimeError.connect(self.onProcessError)
        self.logic.signalProcessSucceed.connect(self.onProcessSucceed)

        try:
            self.logic.apply(data=data, progressBar=self.__cliProgressBar)
        except Exception as error:
            self.onProcessError(error)

        helpers.save_path(self.__exportPathEdit)

    def onProcessError(self, error):
        logging.error(f"{error}.\n{traceback.format_exc()}")
        slicer.util.errorDisplay(
            "An error was found during the process. Please, check the application logs for more details.", self.title
        )

    def onProcessSucceed(self, nodeName):
        slicer.util.infoDisplay(f"Process finished successfully.\nPlease check the node '{nodeName}'.", self.title)

    def cleanup(self):
        super().cleanup()
        if self.logic:
            self.logic.signalProcessRuntimeError.disconnect()
            self.logic.signalProcessSucceed.disconnect()


class BoundaryRemovalBigImageLogic(LTracePluginLogic):

    signalProcessRuntimeError = qt.Signal(str)
    signalProcessSucceed = qt.Signal(str)

    def __init__(self):
        LTracePluginLogic.__init__(self)
        self._cliNode = None
        self.__cliNodeModifiedObserver = None

    def _getLazyData(self, node):
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
        segmentationNode = helpers.tryGetNode(data["segmentationNodeId"])

        if not inputNode:
            raise ValueError("The node selected as input is invalid.")

        if not segmentationNode:
            raise ValueError("The node selected as segmentat is invalid.")

        inputLazyData = self._getLazyData(inputNode)
        segmentationLazyData = self._getLazyData(segmentationNode)

        inputLazyDataProtocol = inputLazyData.get_protocol()
        inputLazyDataHost = inputLazyDataProtocol.host()
        segmentationLazyDataProtocol = segmentationLazyData.get_protocol()
        segmentationLazyDataHost = segmentationLazyDataProtocol.host()

        data = {
            **data,
            "inputLazyNodeUrl": inputLazyData.url,
            "inputLazyNodeVar": inputLazyData.var,
            "inputLazyNodeHost": inputLazyDataHost.to_dict(),
            "segmentationLazyNodeUrl": segmentationLazyData.url,
            "segmentationLazyNodeVar": segmentationLazyData.var,
            "segmentationLazyNodeHost": segmentationLazyDataHost.to_dict(),
        }

        cliConfig = {
            "params": json.dumps(data),
        }

        if progressBar is not None:
            progressBar.visible = True

        self._cliNode = slicer.cli.run(
            slicer.modules.boundaryremovalbigimagecli,
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
            del self._cliNode
            self._cliNode = None
            return

        if caller.IsBusy():
            return

        params = json.loads(info["params"])
        if caller.GetStatusString() == "Completed":
            lazyNodeData = lazy.LazyNodeData(
                url="file://" + params["exportPath"], var=params["segmentationLazyNodeVar"] + "_filtered"
            )
            lazyNodeData.to_node()
            self.signalProcessSucceed.emit(lazyNodeData.var)
        else:
            self.signalProcessRuntimeError.emit(caller.GetErrorText())

        inputNode = helpers.tryGetNode(params["inputNodeId"])
        segmentationNode = helpers.tryGetNode(params["segmentationNodeId"])
        self._removeProxyNodeFile(inputNode, params["inputLazyNodeUrl"])
        self._removeProxyNodeFile(segmentationNode, params["segmentationLazyNodeUrl"])

        if self.__cliNodeModifiedObserver is not None:
            self._cliNode.RemoveObserver(self.__cliNodeModifiedObserver)
            self.__cliNodeModifiedObserver = None

        del self._cliNode
        self._cliNode = None
