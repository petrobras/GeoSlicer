import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

import qt, ctk, slicer
from Customizer import Customizer
from ltrace.slicer import ui
from ltrace.utils.ProgressBarProc import ProgressBarProc


GEOLOG_SCRIPT_ERRORS = {
    -1: "Unknown error occurred. Please check if connection parameters are correct",
    1: "Could not initialize project",
    2: "Script execution failed when trying to open WELL",
    3: "Script execution failed when trying to open SET",
    4: "Script execution failed when trying to open LOG",
    5: "Failed when trying to write attributes file when reading project data",
    6: "Failed when trying to read attributes file when importing data",
    7: "Failed when trying to write log data binary files",
    8: "Failed when trying to read  log data binary files",
    9: "Failed to read logs attributes during export.",
    11: "Failed to read geolog data when connecting",
    12: "Failed to find json attributes connection file. File must not have been created properly",
    13: "Failed to find temorary folder with connecting data.",
    21: "Selected items are not valid due to different spacing or types",
    22: "Selected 3D items are not exportable.",
    23: "Some items were skipped from export due to incompatible type.",
    24: "A SET was found with the given name and overwrite was not allowed",
    31: "Finished with errors. Some logs binary files could not be read and were skipped during export",
    32: "Finished with errors. Some logs could not be opened and were skiped during export",
    33: "Finished with errors. Could not add attributes to log and were skipped during export",
    34: "Script execution failed due to all logs being skipped.",
    35: "Failed to write log data into geolog. Script execution was aborted",
    41: "Finished with error. Some wells could not be opened and were skipped.",
    42: "Finished with error. Some sets could not be opened and were skipped.",
    43: "Finished with error. Some logs could not be opened and were skipped.",
}


class GeologConnectWidget(qt.QWidget):
    NO_PROJECT = "No project found in this directory"
    signalGeologData = qt.Signal(object)
    signalScriptError = qt.Signal(int, str)

    def __init__(self, parent=None, prefix=""):
        """
        Handles connection to Geolog, using path and host to find and retrieve Geologs project well data.

        Args:
            prefix (str): prefix text to be added to widgets object names to facilitate searching.
        """

        super().__init__(parent)

        self.geologData = None
        self.setup(prefix)

        self.loadClicked = lambda *a: None

    def setup(self, prefix):
        if sys.platform == "win32":
            geologUsualPath = "'C:/Program Files/Paradigm/Geolog22.0' for Windows systems"
            projectUsualPath = "'C:/programData/Paradigm/projects' for Windows systems (the programData folder may be hidden by default)"
        else:
            geologUsualPath = "'/home/USER/Paradigm/Geolog22.0' for Linux systems"
            projectUsualPath = "'/home/USER/Paradigm/projects/' for Linux systems"

        self.geologInstalation = ctk.ctkDirectoryButton()
        self.geologInstalation.caption = "Geolog instalation folder"
        self.geologInstalation.objectName = f"{prefix} Geolog Directory Browser"
        self.geologInstalation.directoryChanged.connect(self.checkSearchButtonState)
        self.geologInstalation.setToolTip(
            f"Select the path to Geolog folder. Default installation is usually in {geologUsualPath}. (Example path)"
        )

        self.geologProjectsFolder = ctk.ctkDirectoryButton()
        self.geologProjectsFolder.caption = "Geolog project parent folder"
        self.geologProjectsFolder.directoryChanged.connect(self.onProjectPathSelected)
        self.geologProjectsFolder.objectName = f"{prefix} Geolog Projects Directory Browser"
        self.geologProjectsFolder.setToolTip(
            f"Select the path to Geolog project directory. Usually is {projectUsualPath}"
        )

        self.projectComboBox = qt.QComboBox()
        self.projectComboBox.currentIndexChanged.connect(self.checkSearchButtonState)
        self.projectComboBox.objectName = f"{prefix} Geolog Project Selector ComboBox"
        self.projectComboBox.setToolTip("Projects available in Geolog projects folder")

        self.refreshButton = qt.QPushButton()
        self.refreshButton.clicked.connect(self.onProjectPathSelected)
        self.refreshButton.setIcon(qt.QIcon(str(Customizer.RESET_ICON_PATH)))
        self.refreshButton.setFixedWidth(30)
        self.refreshButton.setToolTip("Refresh the directory to check for newly created projects")

        projectLayout = qt.QHBoxLayout()
        projectLayout.addWidget(self.projectComboBox)
        projectLayout.addWidget(self.refreshButton)
        projectLayout.setContentsMargins(0, 0, 0, 0)

        projectSelectorWidget = qt.QWidget()
        projectSelectorWidget.setLayout(projectLayout)

        self.searchButton = ui.ApplyButton(
            onClick=self.searchButtonClicked,
            tooltip="Search for well, sets and logs in the given project",
            enabled=True,
        )
        self.searchButton.setText("Read project")
        self.searchButton.enabled = False
        self.searchButton.objectName = f"{prefix} Geolog Connect Button"

        self.status = qt.QLabel("Status: Idle")
        self.status.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        self.status.setWordWrap(True)

        layout = qt.QFormLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addRow("Geolog directory:", self.geologInstalation)
        layout.addRow("Projects directory:", self.geologProjectsFolder)
        layout.addRow("Project:", projectSelectorWidget)
        layout.addRow(self.searchButton)
        layout.addRow(self.status)
        layout.addRow("", None)

        self.setLayout(layout)
        self.onProjectPathSelected()

        self.logic = GeologConnectLogic()

    def populateFields(self, instalationPath, projectsPath, project=""):
        self.geologInstalation.directory = instalationPath
        self.geologProjectsFolder.directory = projectsPath
        if project:
            self.projectComboBox.setCurrentText(project)

    def updateStatus(self, code=0, message="Finished!"):
        statusMessage = "Status: "
        if code:
            statusMessage = f"{statusMessage}Error code: {code} - "
            self.status.setStyleSheet("font-weight: bold; color: red")
        else:
            self.status.setStyleSheet("font-weight: bold; color: green")
        self.status.setText(f"{statusMessage}{message}")

    def getEnvs(self):
        geologPath = Path(f"{self.geologInstalation.directory}/bin/geolog").as_posix()
        scriptPath = Path(__file__).parent.as_posix()

        return geologPath, scriptPath

    def searchButtonClicked(self):
        with ProgressBarProc() as progressBar:
            if not self.checkEnvViability():
                self.updateStatus(-1, GEOLOG_SCRIPT_ERRORS[-1])
                return

            progressBar.setMessage("Getting data")
            geologPath, scriptPath = self.getEnvs()

            try:
                geologData = self.logic.getGeologData(geologPath, scriptPath, self.projectComboBox.currentText)
            except GeologScriptError as e:
                self.updateStatus(e.errorCode, e.errorMessage)
            else:
                self.signalGeologData.emit(geologData)
                self.updateStatus()

    def onProjectPathSelected(self):
        self.projectComboBox.clear()
        projectList = [f.name for f in Path(self.geologProjectsFolder.directory).iterdir() if f.is_dir()]
        if projectList:
            self.projectComboBox.enabled = True
            for project in projectList:
                self.projectComboBox.addItem(project)
        else:
            self.projectComboBox.enabled = False
            self.projectComboBox.addItem(self.NO_PROJECT)
        self.checkSearchButtonState()

    def checkEnvViability(self):
        geologPath, scriptPath = self.getEnvs()

        if sys.platform == "win32":
            if not Path(geologPath + ".exe").is_file():
                return False
        else:
            if not Path(geologPath).is_file():
                return False

        return True

    def checkSearchButtonState(self):
        envIsValid = self.checkEnvViability()
        if envIsValid and self.projectComboBox.currentText != self.NO_PROJECT:
            self.searchButton.enabled = True
        else:
            self.searchButton.enabled = False


class GeologConnectLogic(object):
    def getGeologData(self, geologPath, scriptPath, projectName):
        scriptPath = f"{scriptPath}/scriptConnect.py"
        temporaryPath = Path(slicer.util.tempDirectory())

        args = [geologPath, "mod_python", scriptPath, "--project", projectName, "--tempPath", temporaryPath]

        try:
            self._runProcess(args)
        except subprocess.CalledProcessError as e:
            if GEOLOG_SCRIPT_ERRORS.get(e.returncode, -1) == -1:
                raise GeologScriptError(-1, GEOLOG_SCRIPT_ERRORS[-1])
            raise GeologScriptError(e.returncode, GEOLOG_SCRIPT_ERRORS[e.returncode]) from e
        else:
            return self._readGeologOutput(temporaryPath)

    def _runProcess(self, args):
        proc = slicer.util.launchConsoleProcess(args)
        slicer.util.logProcessOutput(proc)
        logging.info(f"Connect process still running: {proc.poll()}")

    def _readGeologOutput(self, temporaryPath):
        code = 0
        if Path(temporaryPath).is_dir():
            file = f"{temporaryPath.as_posix()}/output.json"
            if Path(file).is_file():
                try:
                    with open(file, "r") as f:
                        geologData = json.load(f)
                except FileNotFoundError:
                    # Failed when trying to read connectScript output json file.
                    code = 11
            else:
                # Could not find connectScript output json file
                code = 12
        else:
            # Could not find temporary directory
            code = 13

        self._cleanUp(temporaryPath)

        if code:
            raise GeologScriptError(code, GEOLOG_SCRIPT_ERRORS.get(code, GEOLOG_SCRIPT_ERRORS[-1]))

        return geologData

    def _cleanUp(self, temporaryPath):
        if temporaryPath.is_dir():
            shutil.rmtree(temporaryPath, ignore_errors=True)


class GeologScriptError(BaseException):
    """Except raised for errors during GEOLOG script execution

    Args:
        errorCode (int): Error code
        errorMessage (str): Error message
    """

    def __init__(self, errorCode=-1, errorMessage="Unknown error occurred"):
        self.errorCode = errorCode
        self.errorMessage = errorMessage
        super().__init__(self.errorMessage)
