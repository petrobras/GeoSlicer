import ctk
import os
import qt
import slicer
import json

from ltrace.slicer.app import getApplicationVersion
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer import helpers
from ltrace.slicer.lazy import lazy
from ltrace.slicer.ui import hierarchyVolumeInput
from pathlib import Path


class MultipleThresholdBigImage(LTracePlugin):
    SETTING_KEY = "MultipleThresholdBigImage"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Multiple Threshold for Big Image"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = MultipleThresholdBigImage.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MultipleThresholdBigImageWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = MultipleThresholdBigImageLogic()

    def setup(self):
        LTracePluginWidget.setup(self)

        formLayout = qt.QFormLayout()

        self.volumeSelector = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLTextNode"],
            tooltip="Select the image within the NetCDF dataset to preview.",
        )
        self.volumeSelector.selectorWidget.addNodeAttributeFilter("LazyNode", "1")

        self.exportPathEdit = ctk.ctkPathLineEdit()
        self.exportPathEdit.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Writable
        self.exportPathEdit.nameFilters = ["*.nc"]
        self.exportPathEdit.settingKey = "MultipleThresholdBigImage/OutputPath"
        self.exportPathEdit.setToolTip("Select the output path for the resulting .nc image")

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.toolTip = "Run the algorithm on the whole image"
        self.applyButton.clicked.connect(self.onApplyButtonClicked)
        self.cliProgressBar = LocalProgressBar()
        self.cliProgressBar.visible = False

        formLayout.addRow("Input Image:", self.volumeSelector)
        formLayout.addRow("Output Path:", self.exportPathEdit)
        self.layout.addLayout(formLayout)
        self.layout.addWidget(self.applyButton)
        self.layout.addWidget(self.cliProgressBar)
        self.layout.addStretch(1)

    def onApplyButtonClicked(self):
        lazyData = lazy.data(self.volumeSelector.currentNode())

        self.logic.apply(lazyData, self.exportPathEdit.currentPath, progress_bar=self.cliProgressBar)
        helpers.save_path(self.exportPathEdit)

    def setParams(self, inputLazyNode, thresholds, colors, names):
        self.volumeSelector.setCurrentNode(inputLazyNode)
        self.logic.setParams(thresholds, colors, names)


class MultipleThresholdBigImageLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.__cli_node = None
        self.__cli_node_modified_observer = None

        self.setParams([], [], [])

    def setParams(self, thresholds, colors, names):
        self.thresholds = thresholds
        self.colors = colors
        self.names = names

    def apply(self, lazyData, outputPath, progress_bar=None):
        lazyDataNodeProtocol = lazyData.get_protocol()
        lazyDataNodeHost = lazyDataNodeProtocol.host()
        params = {
            "input_url": lazyData.url,
            "input_var": lazyData.var,
            "output_url": outputPath,
            "threshs": self.thresholds,
            "colors": self.colors,
            "names": self.names,
            "geoslicerVersion": getApplicationVersion(),
            "lazyDataNodeHost": lazyDataNodeHost.to_dict(),
        }
        cli_config = {
            "params": json.dumps(params),
        }
        self.outputLazyData = lazy.LazyNodeData("file://" + params["output_url"], params["input_var"] + "_segmented")

        progress_bar.visible = True

        self.__cli_node = slicer.cli.run(
            slicer.modules.multiplethresholdbigimagecli,
            None,
            cli_config,
            wait_for_completion=False,
        )
        self.__cli_node_modified_observer = self.__cli_node.AddObserver(
            "ModifiedEvent", lambda c, ev, info=cli_config: self.__on_cli_modified_event(c, ev, info)
        )

        if progress_bar is not None:
            progress_bar.setCommandLineModuleNode(self.__cli_node)

    def __on_cli_modified_event(self, caller, event, info):
        if caller is None:
            self.__cli_node = None
            return

        if caller.IsBusy():
            return

        if caller.GetStatusString() == "Completed":
            self.outputLazyData.to_node()

        if self.__cli_node_modified_observer is not None:
            self.__cli_node.RemoveObserver(self.__cli_node_modified_observer)
            self.__cli_node_modified_observer = None

        self.__cli_node = None
