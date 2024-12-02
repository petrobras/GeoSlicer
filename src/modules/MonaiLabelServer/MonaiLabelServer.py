from pathlib import Path

import itertools
import json
import logging
import os
import qt, ctk, slicer
import signal
import subprocess

from ltrace.slicer import widgets
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from slicer.ScriptedLoadableModule import *

from MonaiLabelRemoteTask.MonaiLabelServerHandler import MonaiLabelServerHandler
from ltrace.remote.connections import JobExecutor
from ltrace.remote.jobs import JobManager

LOCK_FILE = "monailabelserver.lock"


class MonaiLabelServer(LTracePlugin):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
    """

    # Plugin info
    SETTING_KEY = "MonaiLabelServer"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "MONAILabel Server"
        self.parent.categories = ["Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MonaiLabelServerWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)

        self.layout.addWidget(self._setupServerSection())
        self.layout.addStretch(1)

    def _setupServerSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "MONAI Label Server Manager"

        self.localRadioButton = qt.QRadioButton("Local server")
        self.localRadioButton.toggled.connect(self._onLocalToggled)
        self.remoteRadioButton = qt.QRadioButton("Remote server")
        self.remoteRadioButton.toggled.connect(self._onRemoteToggled)

        layout = qt.QFormLayout(widget)
        hbox = qt.QHBoxLayout()
        hbox.addWidget(self.localRadioButton)
        hbox.addWidget(self.remoteRadioButton)
        layout.addRow(hbox)

        self.statusIndicator = qt.QLabel()

        self.appLineEdit = qt.QLineEdit(
            "//dfs.petrobras.biz/cientifico/cenpes/res/drp/smart-segmenter/laminas/ElementosConstrutores/app_test"
        )
        self.appLineEdit.setPlaceholderText("Selecione o app a ser usado pelo MONAI Label")
        self.appLineEdit.textChanged.connect(self.isFieldFilled)
        self.appBrowseButton = qt.QPushButton("Browse")
        self.appBrowseButton.clicked.connect(self.browseApp)

        self.datasetLineEdit = qt.QLineEdit(
            "//dfs.petrobras.biz/cientifico/cenpes/res/drp/smart-segmenter/laminas/ElementosConstrutores/dataset_test"
        )
        self.datasetLineEdit.setPlaceholderText("Selecione o dataset a ser usado pelo MONAI Label")
        self.datasetLineEdit.textChanged.connect(self.isFieldFilled)
        self.datasetBrowseButton = qt.QPushButton("Browse")
        self.datasetBrowseButton.clicked.connect(self.browseDataset)

        self.checkboxLog = qt.QCheckBox("Show logs in the terminal")

        self.startServerButton = qt.QPushButton()
        self.startServerButton.text = "Start MONAI Label Server"

        self.stopServerButton = qt.QPushButton()
        self.stopServerButton.text = "Stop MONAI Label Server"
        self.stopServerButton.setEnabled(False)

        self.logic = MonaiLabelServerLogic(self)
        self.startServerButton.clicked.connect(self.onStartServer)
        self.stopServerButton.clicked.connect(self.onStopServer)

        hbox = qt.QHBoxLayout()
        hbox.addWidget(qt.QLabel("App:       "))
        hbox.addWidget(self.appLineEdit)
        hbox.addWidget(self.appBrowseButton)
        layout.addRow(hbox)

        hbox = qt.QHBoxLayout()
        hbox.addWidget(qt.QLabel("Dataset: "))
        hbox.addWidget(self.datasetLineEdit)
        hbox.addWidget(self.datasetBrowseButton)
        layout.addRow(hbox)

        hbox = qt.QHBoxLayout()
        hbox.addWidget(self.checkboxLog)
        layout.addRow(hbox)

        hbox = qt.QHBoxLayout()
        hbox.addWidget(self.startServerButton)
        hbox.addWidget(self.stopServerButton)
        layout.addRow(hbox)

        layout.addRow(self.statusIndicator)

        self.localRadioButton.setChecked(True)
        self.remoteRadioButton.setChecked(False)

        return widget

    def onStartServer(self):
        if self.localRadioButton.checked:
            self.logic.onStartLocalServer()
        elif self.remoteRadioButton.checked:
            self.logic.onStartRemoteServer()

    def onStopServer(self):
        if self.localRadioButton.checked:
            self.logic.onStopLocalServer()
        elif self.remoteRadioButton.checked:
            self.logic.onStopRemoteServer()

    def isFieldFilled(self, text):
        if not text:
            self.startServerButton.setEnabled(False)
        elif not self.logic.process:
            self.startServerButton.setEnabled(True)

    def browseApp(self):
        dialog = qt.QFileDialog()
        dialog.setFileMode(qt.QFileDialog.Directory)
        dialog.setOption(qt.QFileDialog.ShowDirsOnly)
        directory = dialog.getExistingDirectory(slicer.modules.AppContextInstance.mainWindow, "Choose App Directory")
        self.appLineEdit.setText(directory)
        dialog.delete()

    def browseDataset(self):
        dialog = qt.QFileDialog()
        dialog.setFileMode(qt.QFileDialog.Directory)
        dialog.setOption(qt.QFileDialog.ShowDirsOnly)
        directory = dialog.getExistingDirectory(
            slicer.modules.AppContextInstance.mainWindow, "Choose Dataset Directory"
        )
        self.datasetLineEdit.setText(directory)
        dialog.delete()

    def _onLocalToggled(self):
        self.remoteRadioButton.setChecked(False)
        self.checkboxLog.visible = True

    def _onRemoteToggled(self):
        self.localRadioButton.setChecked(False)
        self.checkboxLog.visible = False


class MonaiLabelServerLogic(LTracePluginLogic):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget = parent
        self.process = None
        self.PID = None
        self.UID = None

        if Path(LOCK_FILE).exists():
            try:
                lock_file = open(Path(LOCK_FILE), "r")
                line = lock_file.readline()
                self.PID = int(line.split("=")[1])
                lock_file.close()

                self.timer = qt.QTimer()
                self.timer.timeout.connect(self.CheckIfServerIsRunning)
                self.timer.start(5000)

                self.widget.statusIndicator.setText(f"Server running with PID={self.PID}")
                self.widget.startServerButton.setEnabled(False)
                self.widget.stopServerButton.setEnabled(True)
                self.widget.localRadioButton.setChecked(True)
            except:
                os.remove(Path(LOCK_FILE))

        for job in JobManager.jobs:
            if JobManager.jobs[job].job_type == "monai" and JobManager.jobs[job].status == "RUNNING":
                self.UID = job
                self.widget.statusIndicator.setText(
                    f"Server already running on host {JobManager.jobs[self.UID].host.name}"
                )
                self.widget.startServerButton.setEnabled(False)
                self.widget.stopServerButton.setEnabled(True)
                self.widget.remoteRadioButton.setChecked(True)

    def onStartRemoteServer(self):
        if not self.UID:
            appStr = self.widget.appLineEdit.text
            datasetStr = self.widget.datasetLineEdit.text

            if appStr == "":
                slicer.util.errorDisplay(f"Choose a properly app folder.")
                return

            if datasetStr == "":
                slicer.util.errorDisplay(f"Choose a properly dataset folder.")
                return

            appPath = Path(appStr)
            if not appPath.exists():
                slicer.util.errorDisplay(f"The app path {appStr} does not exists.")
                return

            datasetPath = Path(datasetStr)
            if not datasetPath.exists():
                slicer.util.errorDisplay(f"The dataset path {datasetStr} does not exists.")
                return

            # set a timer to check if the process is still running
            self.timer = qt.QTimer()
            self.timer.timeout.connect(self.CheckIfServerIsRunning)
            self.timer.start(5000)
            managed_cmd = MonaiLabelServerHandler(app_folder=appPath, dataset_folder=datasetPath)

            self.UID = slicer.modules.RemoteServiceInstance.cli.run(managed_cmd, name="Monai Server", job_type="monai")
            self.widget.statusIndicator.setText(f"Server running on host {JobManager.jobs[self.UID].host.name}")
            self.widget.startServerButton.setEnabled(False)
            self.widget.stopServerButton.setEnabled(True)

    def onStartLocalServer(self):
        if not self.PID or not self.process:
            appStr = self.widget.appLineEdit.text
            datasetStr = self.widget.datasetLineEdit.text

            if appStr == "":
                slicer.util.errorDisplay(f"Choose a properly app folder.")
                return

            if datasetStr == "":
                slicer.util.errorDisplay(f"Choose a properly dataset folder.")
                return

            appPath = Path(appStr)
            if not appPath.exists():
                slicer.util.errorDisplay(f"The app path {appStr} does not exists.")
                return

            datasetPath = Path(datasetStr)
            if not datasetPath.exists():
                slicer.util.errorDisplay(f"The dataset path {datasetStr} does not exists.")
                return

            command = [
                "PythonSlicer",
                "-m",
                "monailabel.main",
                "start_server",
                "--app",
                str(appPath),
                "--studies",
                str(datasetPath),
                "--conf",
                "models",
                "deepedit",
            ]

            if os.name == "posix":
                if self.widget.checkboxLog.isChecked():
                    command = ["xterm", "-e"] + command

                self.process = subprocess.Popen(
                    command, preexec_fn=os.setsid, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
            else:
                if self.widget.checkboxLog.isChecked():
                    self.process = subprocess.Popen(command, encoding="utf-8")
                else:
                    self.process = subprocess.Popen(
                        command, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW
                    )
            self.PID = self.process.pid
            print(f"Starting {self.PID}...\n")

            # create the lock file
            lock_file = open(Path(LOCK_FILE), "w")
            lock_file.write(f"PID={self.PID}")
            lock_file.close()

            # set a timer to check if the process is still running
            self.timer = qt.QTimer()
            self.timer.timeout.connect(self.CheckIfServerIsRunning)
            self.timer.start(5000)

            self.widget.statusIndicator.setText(f"Server running with PID={self.PID}")
            self.widget.startServerButton.setEnabled(False)
            self.widget.stopServerButton.setEnabled(True)

    def CheckIfServerIsRunning(self):
        if self.widget.localRadioButton.checked:
            if self.process.poll() is not None:
                print(f"The MONAI Label server that was running with PID={self.PID} terminated unexpectedly.\n")
                self.PID = None
                self.onStopLocalServer()
        elif self.widget.remoteRadioButton.checked:
            if self.UID in JobManager.jobs and JobManager.jobs[self.UID].status == "CANCELLED":
                print(
                    f"The MONAI Label server that was running with UID={self.UID} on host {JobManager.jobs[self.UID].host.name} terminated unexpectedly.\n"
                )
                self.UID = None
                self.onStopLocalServer()

    def onStopRemoteServer(self):
        self.widget.statusIndicator.setText(f"Server stopped")
        self.widget.startServerButton.setEnabled(True)
        self.widget.stopServerButton.setEnabled(False)

        if JobManager.jobs[self.UID].status == "RUNNING":
            JobManager.send(self.UID, "CANCEL")
            self.UID = None

    def onStopLocalServer(self):
        self.timer.stop()
        self.widget.statusIndicator.setText(f"Server stopped")
        self.widget.startServerButton.setEnabled(True)
        self.widget.stopServerButton.setEnabled(False)

        if self.PID:
            if os.name == "posix":
                os.killpg(os.getpgid(self.PID), signal.SIGTERM)
            else:
                subprocess.Popen(
                    "TASKKILL /F /PID {pid} /T".format(pid=self.PID), creationflags=subprocess.CREATE_NO_WINDOW
                )
            print(f"Killing {self.PID} and child processes...\n")

            os.remove(Path(LOCK_FILE))

        self.PID = None
        self.process = None


def monai_job_compiler(job: JobExecutor):
    details = job.details
    IP = details.get("nodeIP", "")
    appPath = details.get("appPath", "")
    datasetPath = details.get("datasetPath", "")
    job.task_handler = MonaiLabelServerHandler(app_folder=appPath, dataset_folder=datasetPath)

    return job


JobManager.register("monai", monai_job_compiler)
