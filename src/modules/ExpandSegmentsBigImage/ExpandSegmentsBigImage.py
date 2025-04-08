import ctk
import json
import os
import qt
import slicer
import logging
import sys
import ltrace.slicer.helpers as helpers

from ltrace.slicer.app import getApplicationVersion
from ltrace.slicer.lazy import lazy
from ltrace.slicer import ui
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from pathlib import Path
from pathvalidate import sanitize_filepath

import ltrace.slicer.netcdf as netcdf

try:
    from Test.ExpandSegmentsBigImageTest import ExpandSegmentsBigImageTest
except ImportError:
    ExpandSegmentsBigImageTest = None  # tests not deployed to final version or closed source

from dataclasses import dataclass


@dataclass
class ExpandSegmentsParameters:
    segmentationNode: slicer.vtkMRMLNode = None
    exportPath: str = None


class ExpandSegmentsBigImage(LTracePlugin):
    SETTING_KEY = "ExpandSegmentsBigImage"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Expand Segments for Big Images"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = ExpandSegmentsBigImage.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ExpandSegmentsBigImageWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = None
        self.title = "Expand Segments Big Image"

    def setup(self):
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.__segmentationSelector = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLSegmentationNode", "vtkMRMLTextNode"],
            tooltip="Select the segmentation node related to the dataset.",
        )
        self.__segmentationSelector.objectName = "Segmentation Selector"

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Segmentation:", self.__segmentationSelector)

        # Output section
        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.__exportPathEdit = ctk.ctkPathLineEdit()
        self.__exportPathEdit.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Writable
        self.__exportPathEdit.nameFilters = ["*.nc"]
        self.__exportPathEdit.settingKey = "ExpandSegmentsBigImage/OutputPath"
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
        self.layout.addWidget(outputSection)
        self.layout.addWidget(self.__applyButton)
        self.layout.addWidget(self.__cliProgressBar)
        self.layout.addStretch(1)

    def setParameters(self, **kwargs):
        params = ExpandSegmentsParameters(**kwargs)

        if params.segmentationNode:
            self.__segmentationSelector.setCurrentNode(params.segmentationNode)

        if params.exportPath:
            self.__exportPathEdit.setCurrentPath(params.exportPath)

    def __onApplyButtonClicked(self, state):
        if self.__segmentationSelector.currentNode() is None:
            slicer.util.errorDisplay("Please select a segmentation node.", self.title)
            return

        if not self.__exportPathEdit.currentPath:
            slicer.util.errorDisplay("Please select an output path.", self.title)
            return

        data = {
            "segmentationNodeId": self.__segmentationSelector.currentNode().GetID(),
            "exportPath": self.__exportPathEdit.currentPath,
            "geoslicerVersion": getApplicationVersion(),
        }

        self.logic = ExpandSegmentsBigImageLogic()
        self.logic.signalProcessRuntimeError.connect(self.onProcessError)
        self.logic.signalProcessSucceed.connect(self.onProcessSucceed)

        try:
            self.logic.apply(data=data, progressBar=self.__cliProgressBar)
        except Exception as error:
            self.onProcessError(error)

        helpers.save_path(self.__exportPathEdit)

    def onProcessError(self, error):
        logging.error(error)
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


class ExpandSegmentsBigImageLogic(LTracePluginLogic):
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
        segmentationNode = helpers.tryGetNode(data["segmentationNodeId"])

        if not segmentationNode:
            raise ValueError("The node selected as segmentat is invalid.")

        segmentationLazyData = self._getLazyData(segmentationNode)
        protocol = segmentationLazyData.get_protocol()
        host = protocol.host()

        data = {
            **data,
            "segmentationLazyNodeUrl": segmentationLazyData.url,
            "segmentationLazyNodeVar": segmentationLazyData.var,
            "segmentationLazyNodeHost": host.to_dict(),
        }

        cliConfig = {
            "params": json.dumps(data),
        }

        if progressBar is not None:
            progressBar.visible = True

        self._cliNode = slicer.cli.run(
            slicer.modules.expandsegmentsbigimagecli,
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
                url="file://" + params["exportPath"], var=params["segmentationLazyNodeVar"] + "_expanded"
            )
            lazyNodeData.to_node()
            self.signalProcessSucceed.emit(lazyNodeData.var)
        else:
            self.signalProcessRuntimeError.emit(caller.GetErrorText())

        segmentationNode = helpers.tryGetNode(params["segmentationNodeId"])
        self._removeProxyNodeFile(segmentationNode, params["segmentationLazyNodeUrl"])

        if self.__cliNodeModifiedObserver is not None:
            self._cliNode.RemoveObserver(self.__cliNodeModifiedObserver)
            self.__cliNodeModifiedObserver = None

        del self._cliNode
        self._cliNode = None
