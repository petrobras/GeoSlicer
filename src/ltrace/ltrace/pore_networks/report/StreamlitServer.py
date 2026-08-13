import qt
import slicer
import os
import subprocess
import signal
import logging
import shutil
import psutil
import re
import requests
import hashlib

from pathlib import Path

from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.slicer_utils import getResourcePath


def md5sum(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def is_server_running(URL):
    status = None
    try:
        response = requests.head(URL)
    except Exception as e:
        print("Streamlit server is not running.")
        status = False
    else:
        if response.status_code == 200:
            status = True
        else:
            print("Streamlit server is not running.")
            status = False
    return status


class StreamlitServer(qt.QWidget):
    def __init__(self, parent, serverStatus, serverButton, updateScriptsButton):
        super().__init__(parent)
        self.serverStatus = serverStatus
        self.toggleServerButton = serverButton
        self.updateScriptsButton = updateScriptsButton
        self.pid = None
        self.ip_addr = None
        self.port = 8501
        self.openBrowser = True
        self.timer = None

        self.report_folder = (Path(slicer.app.slicerHome) / "LTrace" / "streamlit").resolve()

        self.clearStatusBar()
        self.createStatusBar()

        self.toggleServerButton.clicked.connect(self.toggleServer)

    def createStatusBar(self):
        statusBar = slicer.modules.AppContextInstance.mainWindow.findChild(qt.QObject, "StatusBar")
        statusBar.setContentsMargins(3, 0, 0, 0)
        self.statusbar_label = qt.QLabel("PNM Report server running")
        self.statusbar_label.objectName = "PNM Report status label"
        self.statusbar_button = qt.QPushButton()
        self.statusbar_button.objectName = "PNM Report status button"
        stopIcon = qt.QIcon(getResourcePath("Icons") / "png" / "GreyCancelIconStreamlit.png")
        self.statusbar_button.setIcon(stopIcon)
        self.statusbar_button.setToolTip("Stop server")
        statusBar.addWidget(self.statusbar_label)
        statusBar.addWidget(self.statusbar_button)
        self.statusbar_button.clicked.connect(self.confirmServerStop)
        self.statusbar_label.visible = False
        self.statusbar_button.visible = False

    def clearStatusBar(self):
        statusBar = slicer.modules.AppContextInstance.mainWindow.findChild(qt.QObject, "StatusBar")
        for child in statusBar.children():
            if child:
                if child.objectName.startswith("PNM Report status"):
                    statusBar.removeWidget(child)
                    child.delete()

    def onPortChanged(self, port):
        self.port = str(int(port))

    def onPathChanged(self, path):
        self.report_folder = path
        self.checkOutdated()

    def onUpdateScripts(self):
        original_path = Path(__file__).parent.resolve() / "streamlit"
        shutil.copytree(original_path, self.report_folder, dirs_exist_ok=True)
        self.checkOutdated()

    def checkOutdated(self):
        pass

    def confirmServerStop(self):
        message = "Are you sure you want to stop streamlit server?"
        if slicer.util.confirmYesNoDisplay(message):
            self.killStreamlitServer()

    def toggleServer(self):
        if self.pid:
            self.killStreamlitServer()
        else:
            self.initStreamlitServer()

    def retrieve_from_lockfile(self, filename):
        with open(Path(filename), "r") as lock_file:
            for i in range(10):
                line = lock_file.readline()
                if not line:
                    break
                pid = int(line.split("=")[1])

                line = lock_file.readline()
                if not line:
                    break
                ip_addr = line.split("=")[1][:-1]

                if ip_addr is not None:
                    status = is_server_running(ip_addr)
                    if status:
                        break

        return status, ip_addr, pid

    def retrieveActiveStreamlit(self):
        LOCK_FILE = f"{slicer.app.slicerHome}/LTrace/streamlit_server.lock"
        if Path(LOCK_FILE).exists():
            try:
                status, self.ip_addr, self.pid = self.retrieve_from_lockfile(LOCK_FILE)

                if self.ip_addr is not None and status:
                    # self.toggleServerButton.setStyleSheet("QPushButton {color: #00FF00}")
                    self.toggleServerButton.text = "Stop Streamlit Server"
                    self.serverStatus.text = f'Running in <a href="{self.ip_addr}">{self.ip_addr}</a>'
                    self.statusbar_label.text = (
                        f'PNM Report server running at <a href="{self.ip_addr}">{self.ip_addr}</a>'
                    )
                    self.statusbar_label.visible = True
                    self.statusbar_button.visible = True
                else:
                    slicer.util.errorDisplay(
                        "Error in retrieving ip address from server, try again, or check if the port 8501 is available and if has a already running instance of streamlit."
                    )
                    self.killStreamlitServer()
            except Exception as e:
                os.remove(Path(LOCK_FILE))
                import traceback

                traceback.print_exc()

    def initStreamlitServer(self):
        if not Path(self.report_folder).exists():
            msg_box = qt.QMessageBox(slicer.modules.AppContextInstance.mainWindow)
            msg_box.setIcon(qt.QMessageBox.Information)
            msg_box.text = "You are about to create an empty report. To see any results, please run the tool on a project or import an existing project through the Projects Manager page."
            msg_box.setWindowTitle("GeoSlicer confirmation")
            result = msg_box.exec()
            if result:
                original_path = Path(__file__).parent.resolve() / "streamlit"
                shutil.copytree(original_path, self.report_folder)
            else:
                return

        command = [
            "PythonSlicer",
            "-m",
            "streamlit",
            "run",
            "PNM_Report.py",
            "--server.port",
            str(int(self.port)),
            "--server.fileWatcherType",
            "none",
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ]

        wd = os.getcwd()
        os.chdir(self.report_folder)
        with open(f"{slicer.app.slicerHome}/LTrace/streamlit_server.log", "w") as f:
            if os.name == "posix":
                process = subprocess.Popen(command, preexec_fn=os.setsid, stdout=f)
            else:
                process = subprocess.Popen(
                    command, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW, stdout=f
                )
        os.chdir(wd)

        self.pid = process.pid

        ApplicationObservables().aboutToQuit.connect(self.killStreamlitServer)

        self.toggleServerButton.enabled = False
        self.toggleServerButton.text = f"Starting Streamlit Server..."
        self.serverStatus.text = f"Starting streamlit server..."
        self.waitServerStartup()

    def waitServerStartup(self):
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()

        self.timer = qt.QTimer(self)
        self.start_time = qt.QTime.currentTime()
        self.timer.timeout.connect(self.checkServerStarted)
        self.timer.start(1000)

    def checkServerStarted(self):
        elapsed = self.start_time.msecsTo(qt.QTime.currentTime())
        if elapsed < 10000:
            status = self.checkStatus()
            if status:
                if self.timer is not None:
                    self.timer.stop()
                    self.timer.deleteLater()
                    self.timer = None
                self.onSucessfullStart()
        else:
            if self.timer is not None:
                self.timer.stop()
                self.timer.deleteLater()
                self.timer = None
            self.onFailedStart()

    def checkStatus(self):
        with open(f"{slicer.app.slicerHome}/LTrace/streamlit_server.log", "r") as f:
            message = f.read()

        network_url_pattern = r"Network URL:\s*(http://\d+\.\d+\.\d+\.\d+:\d+)"
        match = re.search(network_url_pattern, message)
        if match:
            self.ip_addr = match.group(1)

        return self.ip_addr is not None

    def onSucessfullStart(self):
        logging.debug(f"Started Streamlit server with PID={self.pid} in IP={self.ip_addr}\n")

        with open(f"{slicer.app.slicerHome}/LTrace/streamlit_server.lock", "a") as f:
            f.write(f"PID={self.pid}\n")
            f.write(f"IP={self.ip_addr}\n")

        if self.openBrowser:
            qt.QDesktopServices.openUrl(qt.QUrl(self.ip_addr))

        self.toggleServerButton.enabled = True
        # self.toggleServerButton.setStyleSheet("QPushButton {color: #00FF00}")
        self.toggleServerButton.text = "Stop Streamlit Server"
        self.serverStatus.text = f'Running in <a href="{self.ip_addr}">{self.ip_addr}</a>'

        self.createStatusBar()
        self.statusbar_label.text = f'PNM Report server running at <a href="{self.ip_addr}">{self.ip_addr}</a>'
        self.statusbar_label.visible = True
        self.statusbar_button.visible = True

    def onFailedStart(self):
        self.toggleServerButton.enabled = True
        slicer.util.errorDisplay(
            f"Error in retrieving ip address from server, try again, or check if the port {self.port} is available and if has a already running instance of streamlit."
        )
        self.killStreamlitServer()

    def killStreamlitServer(self):
        if self.pid and psutil.pid_exists(self.pid):
            if os.name == "posix":
                os.killpg(os.getpgid(self.pid), signal.SIGTERM)
            else:
                subprocess.run(
                    "TASKKILL /F /PID {pid} /T".format(pid=self.pid), creationflags=subprocess.CREATE_NO_WINDOW
                )
            logging.debug(f"Killing Streamlit server with PID={self.pid}...\n")

        lock_file = f"{slicer.app.slicerHome}/LTrace/streamlit_server.lock"
        if Path(lock_file).exists():
            os.remove(lock_file)

        self.pid = None
        self.ip_addr = None

        # Fix warnings when widgets are being deleted.
        try:
            self.toggleServerButton.text = "Open Report Locally"
            self.serverStatus.text = "Stopped"

            self.clearStatusBar()
        except:
            pass

    def generateHashFile(self):
        base_path = Path(__file__).parent
        checksum_file = base_path / "checksums.txt"

        with open(checksum_file, "w") as f:
            streamlit_folder = base_path / "streamlit"
            for root, dirs, files in os.walk(streamlit_folder):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", "static")]
                for file in files:
                    if not file.endswith(".pyc"):
                        file_path = Path(root) / file
                        checksum = md5sum(file_path)
                        relative_path = file_path.relative_to(streamlit_folder)
                        f.write(f"{checksum} {relative_path}\n")

    def codeHasChanges(self):
        base_path = Path(__file__).parent
        checksum_file = base_path / "checksums.txt"

        if not checksum_file.exists():
            logging.debug(f"Report checksum file {checksum_file} not found.\n")
            return True

        report_folder = Path(self.report_folder)
        if not report_folder.exists():
            logging.debug(f"Report folder {report_folder} not found.")
            return True

        with open(checksum_file, "r") as f:
            stored_checksums = {line.split(" ", 1)[1].strip(): line.split(" ", 1)[0] for line in f}

        current_checksums = {}
        for root, dirs, files in os.walk(report_folder):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "static")]
            for file in files:
                if not file.endswith(".pyc"):
                    file_path = Path(root) / file
                    try:
                        relative_path = file_path.relative_to(report_folder)
                        current_checksums[str(relative_path)] = md5sum(file_path)
                    except ValueError:
                        pass

        if set(current_checksums.keys()) != set(stored_checksums.keys()):
            return True

        for file_path, stored_checksum in stored_checksums.items():
            if stored_checksum != current_checksums.get(file_path):
                return True

        return False
