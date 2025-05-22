import os
import subprocess
import sys
from pathlib import Path

import drd
import qt
import slicer
import xarray as xr
import time

from Libs.drd_wrapper import Source, DATASET_METADATA
from ltrace.slicer import netcdf
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, getResourcePath

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
        self.parent.categories = ["Tools", "OpenRockData", "MicroCT", "Thin Section", "Image Log", "Core", "Multiscale"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = f"file:///{(getResourcePath('manual') / 'Modules/Volumes/OpenRockData.html').as_posix()}"

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class OpenRockDataWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.is_downloading = False

    def setup(self):
        LTracePluginWidget.setup(self)

        helpLayout = qt.QFormLayout()
        helpButton = HelpButton(
            message="""
This module uses the <a href="https://github.com/LukasMosser/digital_rocks_data">drd</a>
library by Lukas-Mosser to access microtomography data from various sources.

<h2>Data Sources</h2>
<ul>
<li>
    <a href="https://www.digitalrocksportal.org/">Digital Rocks Portal</a>:
    <a href="https://www.digitalrocksportal.org/projects/317">Eleven Sandstones</a>
</li>
<li>
    <a href="https://www.imperial.ac.uk/earth-science/research/research-groups/pore-scale-modelling/micro-ct-images-and-networks/">Imperial College London</a>:
    <a href="https://figshare.com/projects/micro-CT_Images_-_2009/2275">ICL Sandstone Carbonates 2009</a>
</li>
"""
        )
        helpLayout.addRow("Data Sources && References:", helpButton)
        self.treeView = qt.QTreeView()

        self.tree = qt.QTreeWidget()
        self.tree.setHeaderLabels(["Datasets"])
        self.tree.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
        self.tree.setColumnCount(1)

        root = self.tree.invisibleRootItem()

        datasetItem = qt.QTreeWidgetItem(root, [Source.ELEVEN])
        datasetItem.setExpanded(True)
        metadata = DATASET_METADATA
        for key, value in metadata.items():
            childItem = qt.QTreeWidgetItem(datasetItem, [key])
            for key in value:
                subchildItem = qt.QTreeWidgetItem(childItem, [key])

        datasetItem = qt.QTreeWidgetItem(root, [Source.ICL_2009])
        datasetItem.setExpanded(True)
        metadata = drd.datasets.icl_sandstones_carbonates_2009.DATASET_METADATA
        for key in metadata:
            if key == "LV60B":
                # LV60B comes with bad metadata
                # Says it's 450x450x450, but it's actually 450x450x425
                # Skipping for now
                continue
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

        self.layout.addLayout(helpLayout)
        self.layout.addWidget(self.tree, 5)
        self.layout.addWidget(self.downloadButton)
        self.layout.addWidget(self.stdoutTextArea, 1)

        self.timer = qt.QTimer()
        self.timer.setInterval(100)

    def onSelectionChanged(self):
        self.updateDownloadButton()

    def updateDownloadButton(self):
        if self.is_downloading:
            self.downloadButton.enabled = False
            return

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
        output_name = str(int(time.time() * 1000)) + ".nc"

        popen_args = [
            sys.executable,
            "-X",
            "utf8",
            str(OpenRockData.MODULE_DIR / "Libs" / "drd_wrapper.py"),
            "/".join(hierarchy),
            str(data_home),
            output_name,
        ]
        popen_kwargs = {
            "stdout": stdout_file,
            "stderr": stderr_file,
        }

        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        self.loadProcess = subprocess.Popen(popen_args, **popen_kwargs)

        self.outputPath = data_home / "output_nc" / output_name
        self.outputNodeName = hierarchy[-1]
        self.data_home = data_home
        self.timer.timeout.connect(self.checkProcess)
        self.timer.start()
        self.is_downloading = True
        self.updateDownloadButton()

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
            self.is_downloading = False
            self.updateDownloadButton()
            self.onDownloadFinished()

    def onDownloadFinished(self):
        try:
            with xr.open_dataarray(self.outputPath) as array:
                node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", self.outputNodeName)
                netcdf._array_to_node(array, node)
        except (FileNotFoundError, ValueError):
            slicer.util.errorDisplay("Error: Dataset could not be loaded")
            return
        self.outputPath.unlink()
        spacing = node.GetSpacing()
        node.SetSpacing(spacing[0] * 1000, spacing[1] * 1000, spacing[2] * 1000)
        slicer.util.setSliceViewerLayers(background=node, fit=True)
