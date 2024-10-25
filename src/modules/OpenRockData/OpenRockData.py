import os
import qt
import slicer
import xarray as xr
import drd
import sys
import subprocess

from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget
from ltrace.slicer import netcdf
from pathlib import Path
from Libs.drd_wrapper import Source

try:
    from Test.OpenRockDataTest import OpenRockDataTest
except ImportError:
    OpenRockDataTest = None  # tests not deployed to final version or closed source


class OpenRockData(LTracePlugin):
    SETTING_KEY = "OpenRockData"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Digital Rocks Portal"
        self.parent.categories = ["LTrace Tools"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = OpenRockData.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class OpenRockDataWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        self.treeView = qt.QTreeView()

        self.tree = qt.QTreeWidget()
        self.tree.setHeaderLabels(["Datasets"])
        self.tree.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
        self.tree.setColumnCount(1)

        root = self.tree.invisibleRootItem()

        datasetItem = qt.QTreeWidgetItem(root, [Source.ELEVEN])
        datasetItem.setExpanded(True)
        metadata = drd.datasets.eleven_sandstones.DATASET_METADATA
        for key, value in metadata.items():
            childItem = qt.QTreeWidgetItem(datasetItem, [key])
            for key in value:
                subchildItem = qt.QTreeWidgetItem(childItem, [key])

        datasetItem = qt.QTreeWidgetItem(root, [Source.ICL_2009])
        datasetItem.setExpanded(True)
        metadata = drd.datasets.icl_sandstones_carbonates_2009.DATASET_METADATA
        for key in metadata:
            childItem = qt.QTreeWidgetItem(datasetItem, [key])

        """gdrive not working
        datasetItem = qt.QTreeWidgetItem(root, [Source.ICL_2015])
        metadata = ["Bentheimer", "Doddington", "Estaillades", "Ketton"]
        for name in metadata:
            childItem = qt.QTreeWidgetItem(datasetItem, [name])
        """

        self.tree.addTopLevelItem(root)
        self.tree.itemSelectionChanged.connect(self.onSelectionChanged)

        self.downloadButton = qt.QPushButton("Download")
        self.downloadButton.clicked.connect(self.onDownload)
        self.downloadButton.setFixedHeight(40)

        self.stdoutTextArea = qt.QTextEdit()
        self.stdoutTextArea.setReadOnly(True)

        self.onSelectionChanged()

        self.layout.addWidget(self.tree, 5)
        self.layout.addWidget(self.downloadButton)
        self.layout.addWidget(self.stdoutTextArea, 1)

        self.timer = qt.QTimer()
        self.timer.setInterval(100)

    def onSelectionChanged(self):
        selected = self.tree.currentItem()
        if selected is None:
            enabled = False
        else:
            enabled = selected.childCount() == 0
        self.downloadButton.enabled = enabled

    def onDownload(self):
        selected = self.tree.currentItem()

        hierarchy = []
        while selected is not None:
            hierarchy.insert(0, selected.text(0))
            selected = selected.parent()

        data_home = Path(slicer.app.temporaryPath) / "OpenRockData"
        data_home.mkdir(parents=True, exist_ok=True)
        stdout_file = open(data_home / "stdout.txt", "wb")
        stderr_file = open(data_home / "stderr.txt", "wb")

        popen_args = [
            sys.executable,
            "-X",
            "utf8",
            str(OpenRockData.MODULE_DIR / "Libs" / "drd_wrapper.py"),
            "/".join(hierarchy),
            str(data_home),
        ]
        popen_kwargs = {
            "stdout": stdout_file,
            "stderr": stderr_file,
        }

        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        self.loadProcess = subprocess.Popen(popen_args, **popen_kwargs)

        self.outputPath = data_home / "output_nc" / "output.nc"
        self.outputNodeName = hierarchy[-1]
        self.data_home = data_home
        self.timer.timeout.connect(self.checkProcess)
        self.timer.start()

    def checkProcess(self):
        if self.loadProcess.poll() is None:
            with open(self.data_home / "stdout.txt", "rb") as out, open(self.data_home / "stderr.txt", "rb") as err:
                err_text = err.read().decode("utf-8", errors="ignore")
                err_lines = err_text.split("\n")
                err_lines = [line[line.rfind("\r") + 1 :] for line in err_lines]
                err_text = "\n".join(err_lines)
                self.stdoutTextArea.setText(
                    "Please wait...\n\n" + out.read().decode("utf-8", errors="ignore") + "\n\n" + err_text
                )
            self.stdoutTextArea.verticalScrollBar().setValue(self.stdoutTextArea.verticalScrollBar().maximum)
        else:
            self.timer.stop()
            self.timer.timeout.disconnect()
            self.onDownloadFinished()

    def onDownloadFinished(self):
        try:
            array = xr.open_dataarray(self.outputPath)
        except (FileNotFoundError, ValueError):
            slicer.util.errorDisplay("Error: Dataset could not be loaded")
            return
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", self.outputNodeName)
        netcdf._array_to_node(array, node)
        spacing = node.GetSpacing()
        node.SetSpacing(spacing[0] * 1000, spacing[1] * 1000, spacing[2] * 1000)
        slicer.util.setSliceViewerLayers(background=node, fit=True)
