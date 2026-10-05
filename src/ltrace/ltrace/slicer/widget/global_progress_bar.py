import logging
import os
import struct
import tempfile

import vtk
import qt
import slicer
import mrml

from ltrace.slicer.helpers import svgToQIcon
from ltrace.slicer_utils import getResourcePath


class GlobalProgressBar(qt.QWidget):
    _instance = None

    @staticmethod
    def instance():
        if GlobalProgressBar._instance:
            return GlobalProgressBar._instance
        else:
            return GlobalProgressBar()

    def __init__(self):
        if GlobalProgressBar._instance:
            raise Exception("Instance already created!")
        else:
            super().__init__()

            self.currentCliNode = None
            self.observerHandler = None

            layout = qt.QHBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(2)
            layout.setAlignment(qt.Qt.AlignRight)

            self.progressBar = qt.QProgressBar()
            self.progressBar.setFixedHeight(10)
            self.progressBar.setMinimumWidth(128)
            self.progressBar.setMaximumWidth(256)
            self.progressBar.setProperty("style", "thin")
            # newFont = self.progressBar.font
            # newFont.setPixelSize(7)
            # self.progressBar.setFont(newFont)

            self.toolButton = qt.QToolButton()
            self.toolButton.setToolTip("Return to the last CLI started.")
            self.toolButton.setEnabled(False)
            icon = svgToQIcon(getResourcePath("Icons") / "svg" / "Open.svg")
            self.toolButton.setObjectName("GoBackButton")
            self.toolButton.setPopupMode(qt.QToolButton.MenuButtonPopup)
            self.toolButton.setIcon(icon)
            self.toolButton.setAutoRaise(True)

            self.lastCLILabel = qt.QLabel()
            self.lastCLILabel.setObjectName("lastCLILabel")

            layout.addStretch(1)
            layout.addWidget(self.lastCLILabel)
            layout.addWidget(self.toolButton)
            layout.addWidget(self.progressBar)

            self.setLayout(layout)

            self.visible = False

            self.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Fixed)

            GlobalProgressBar._instance = self

    def setCommandLineModuleNode(self, cliNode, localProgressBar, customText=""):
        if (
            GlobalProgressBar._instance.currentCliNode is not None
            and GlobalProgressBar._instance.observerHandler is not None
        ):
            GlobalProgressBar._instance.currentCliNode.RemoveObserver(self.observerHandler)

        GlobalProgressBar._instance.currentCliNode = cliNode
        GlobalProgressBar._instance.observerHandler = cliNode.AddObserver(
            "ModifiedEvent", GlobalProgressBar._instance.updateUiFromCommandLineModuleNode
        )

        GlobalProgressBar._instance.toolButton.setEnabled(True)
        GlobalProgressBar._instance.toolButton.clicked.disconnect()
        GlobalProgressBar._instance.toolButton.clicked.connect(localProgressBar.returnToCLIWidget)

        GlobalProgressBar._instance.lastCLILabel.setText(customText)
        localProgressBar.refToGlobal = self
        self.visible = True

    def actionCreated(self, action):
        GlobalProgressBar._instance.toolButton.addAction(action)

    def disableWhenJobIsCompleted(self):
        currentCLiNode = GlobalProgressBar._instance.currentCliNode
        if currentCLiNode and "Completed" in currentCLiNode.GetStatusString():
            GlobalProgressBar._instance.toolButton.setEnabled(False)
            GlobalProgressBar._instance.lastCLILabel.setText("")
            self.visible = False

    def updateUiFromCommandLineModuleNode(self, cliNode, event):
        if cliNode is None:
            return

        status = cliNode.GetStatus()
        info = cliNode.GetModuleDescriptionAsString()

        if status == mrml.vtkMRMLCommandLineModuleNode.Cancelled:
            self.progressBar.setRange(0, 0)
            self.progressBar.setValue(0)
            self.visible = False
        elif status == mrml.vtkMRMLCommandLineModuleNode.Scheduled:
            self.progressBar.setRange(0, 0)
            self.progressBar.setValue(0)
            GlobalProgressBar._instance.lastCLILabel.setText("Scheduling...")
        elif status == mrml.vtkMRMLCommandLineModuleNode.Running:
            maxRange = 100 if cliNode.GetProgress() != 0 else 0
            self.progressBar.setRange(0, maxRange)
            self.progressBar.setValue(cliNode.GetProgress())
            GlobalProgressBar._instance.lastCLILabel.setText("Running...")
        elif (
            status == mrml.vtkMRMLCommandLineModuleNode.Completed
            or status == mrml.vtkMRMLCommandLineModuleNode.CompletedWithErrors
        ):
            self.progressBar.setRange(0, 100)
            self.progressBar.setValue(100)
            message = (
                "Completed with errors" if status == mrml.vtkMRMLCommandLineModuleNode.CompletedWithErrors else "Done"
            )
            GlobalProgressBar._instance.lastCLILabel.setText(message)


class LocalProgressBar(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.module = None
        self.tabIndex = None
        self.subtabIndex = None

        self.scheduled = set()
        self.completed = 0
        self.running = False
        self.goBackAction = None
        self.refToGlobal = None

        layout = qt.QFormLayout(self)
        self.progressBar = slicer.qSlicerCLIProgressBar()

        layout.addWidget(self.progressBar)

    def setCommandLineModuleNode(self, cliNode):

        self.module = slicer.modules.AppContextInstance.mainWindow.moduleSelector().selectedModule

        if not self.module:
            return

        try:
            moduleWidget = slicer.util.getModuleWidget(self.module)
        except RuntimeError:  # Module widget not found
            moduleWidget = None
        else:
            try:
                self.tabIndex = moduleWidget.mainTab.currentIndex
                currentTab = moduleWidget.mainTab.widget(self.tabIndex)
                if isinstance(currentTab, qt.QTabWidget):
                    self.subtabIndex = currentTab.currentIndex
                else:
                    self.subtabIndex = None
            except AttributeError:  # no attribute 'mainTab'
                self.tabIndex = None
                self.subtabIndex = None

        self.scheduled.add(cliNode)
        cliNode.AddObserver("ModifiedEvent", self._onCLIModified)

        self.progressBar.setCommandLineModuleNode(cliNode)
        GlobalProgressBar.instance().setCommandLineModuleNode(cliNode, self)

        self.changeAction()

    def changeAction(self):
        widgetName = self.getCLIWidgetName()
        completedText = f" {self.completed} completed;" if self.completed else ""
        scheduledText = f" {len(self.scheduled)} scheduled;" if self.scheduled else ""
        runningText = f" 1 running;" if self.running else ""
        actionText = f"{widgetName}:{completedText}{scheduledText}{runningText}"

        if not self.goBackAction:
            self.goBackAction = qt.QAction(actionText)
            actionName = f"{self.module}{self.tabIndex}{self.subtabIndex}"
            self.goBackAction.setObjectName(actionName)
            self.goBackAction.triggered.connect(self.returnToCLIWidget)

            GlobalProgressBar.instance().actionCreated(self.goBackAction)
        else:
            self.goBackAction.setText(actionText)

        if not self.running and not self.completed and not self.scheduled:
            self.goBackAction.setVisible(False)
        else:
            self.goBackAction.setVisible(True)

    def _onCLIModified(self, cliNode, event):
        if cliNode is None:
            return

        if "Completed" in cliNode.GetStatusString() and self.running:
            self.completed += 1
            self.running = False
        elif cliNode.GetStatusString() == "Running" and cliNode in self.scheduled:
            self.scheduled.remove(cliNode)
            self.running = True

        self.changeAction()

    def getCLIWidgetName(self):
        currentModule = eval(f"slicer.modules.{self.module}Instance")
        name = currentModule.parent.title
        try:
            moduleWidget = slicer.util.getModuleWidget(self.module)
            name += f" → {moduleWidget.mainTab.tabText(self.tabIndex)}"
            if self.subtabIndex is not None:
                currentTab = moduleWidget.mainTab.widget(self.tabIndex)
                name += f" → {currentTab.tabText(self.subtabIndex)}"
        except Exception as e:
            pass
        return name

    def returnToCLIWidget(self):
        moduleSelectorToolBar = slicer.modules.AppContextInstance.mainWindow.findChild(
            slicer.qSlicerModuleSelectorToolBar
        )
        moduleSelectorToolBar.selectModule(self.module)
        self.completed = 0
        self.refToGlobal.disableWhenJobIsCompleted()
        self.changeAction()


class CompanionProgressBar(LocalProgressBar):
    STOP = -1.0

    def __init__(self, parent=None):
        super().__init__(parent)

        self.progress_file = None
        self._file = None

    def isRunning(self):
        return self.progress_file is not None and os.path.exists(self.progress_file)

    def start(self, name, timeout=300):

        if self.progress_file:
            raise RuntimeError("Progress file already exists")

        label = "".join(character for character in name if character.isalnum() or character in "-_")
        descriptor, self.progress_file = tempfile.mkstemp(prefix=f"geoslicer-progress-{label}-", suffix=".bin")
        os.close(descriptor)
        self._file = open(self.progress_file, "r+b")
        self._write(self._file, 0.0)

        cliArgs = {
            "progressFile": self.progress_file,
            "timeout": timeout,
        }

        try:
            cliNode = slicer.cli.run(slicer.modules.companionprogressbarcli, None, cliArgs, wait_for_completion=False)
        except Exception:
            self.processStopped()
            raise

        self.setCommandLineModuleNode(cliNode)

    def update(self, progress: float):
        # Write the float value to the progress file
        logging.debug(f"Updating progress: {progress}")
        if self._file is None:
            return
        self._write(self._file, progress)
        slicer.app.processEvents()

    @staticmethod
    def _write(file, value: float):
        file.seek(0)
        file.write(struct.pack("d", value))
        file.flush()

    def processStopped(self):
        if not self.progress_file:
            return

        path, file = self.progress_file, self._file
        self.progress_file = self._file = None

        try:
            self._write(file, self.STOP)
            file.close()
            os.unlink(path)
        except OSError as error:
            logging.info(f"Error cleaning up the progress file: {error}")

    def _onCLIModified(self, caller, event):
        super()._onCLIModified(caller, event)

        if caller is None:
            return

        if caller.GetStatusString() == "Completed":
            self.processStopped()
        elif caller.GetStatusString() == "Completed with errors":
            logging.error(f"CLI error: {caller.GetErrorText()}")
            self.processStopped()
        elif caller.GetStatusString() == "Cancelled":
            logging.info("CLI cancelled")
            self.processStopped()
